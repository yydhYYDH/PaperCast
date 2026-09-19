"""知乎「文章」发布流程 —— 在 app 层自己实现，**不改 `reference/upstream/`**。

为什么不再直接用上游 `ZhihuService.publish_article`（2026-09-19 实测一次真发布踩到的）：

1. **图片上传靠 click + expect_file_chooser**：知乎点「图片」会弹出上传弹窗（`.Modal-backdrop`），
   弹窗把自己的按钮挡住 —— 于是 4 张配图 30 秒超时全失败、紧接着「设置话题」也被同一个遮罩挡住，
   上游只记 WARNING 就继续往下走，**最后照样点了「发布」**：结果是一条无图、无标签的正文上线了。
2. **从不返回文章链接**：上游只 `{"success": True, "message": "文章发布流程完成，请到知乎主页确认"}`，
   回执里 URL 永远是空的，用户没法知道「发到哪了」。
3. **失败信息不出函数**：配图/标签全军覆没也不影响 success，回执写 imageCount=4 看着像发了 4 张图。

这里的三条对治：
- 配图**不点按钮**，直接给编辑器里的隐藏 `input[type=file]` 塞文件（Playwright 允许对隐藏 input
  set_input_files），绕开遮罩；每次塞完**核对编辑器里的图片数量真的涨了**才算成功；
- 每次动作前先 `_dismiss_modals()` 把遮罩关掉（Escape + 关闭按钮两条路）；
- 结论里如实带 `warnings` / `imagesUploaded` / `imagesFailed` / `tagsAdded`，并**尽量抓回文章链接**。

另外提供 `dry_run=True`：标题/正文/配图/标签全部填好、**绝不点发布**，只回报「填进去了什么」。
这是给「改完怎么验」用的 —— 真发布不可逆，验证不该靠再发一篇。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

TITLE_SELECTORS = [
    "textarea[placeholder*='标题']",
    "textarea.WriteIndex-titleInput",
    "input[placeholder*='标题']",
    ".WriteIndex-titleInput textarea",
]
EDITOR_SELECTORS = [
    ".public-DraftEditor-content",
    "div[contenteditable='true']",
    ".WriteIndex-contentEditable [contenteditable='true']",
    "[role='textbox']",
]
IMAGE_BUTTONS = [
    'button[aria-label*="图片"]',
    'button:has-text("图片")',
]
# 真正的上传框在「上传图片」弹窗内部：探针实测 accept=image/*、class 是随机 hash。
# 千万别用裸的 input[type=file] —— 页面上还有一个「附件」输入框（accept 里全是 pdf/docx），
# 塞进去会静默失败：文件交出去了，编辑器里什么都不会出现（2026-09-19 就是踩了这个）。
IMAGE_INPUTS = [
    '[class*="Modal"] input[type=file][accept*="image"]',
    '[class*="Modal"] input[type=file]',
    'input[type=file][accept="image/*"]',
]
# 知乎文章写作页**没有**话题输入框（探针实测：发布设置里只有「添加封面」）。
# 上游那个 input[placeholder*="话题"] 命中的是图片弹窗里的搜索框 —— 别再让标签去点它。
TAG_INPUTS = [
    '.PublishPanel input[placeholder*="话题"]',
    '.PublishPanel input[placeholder*="标签"]',
    'input[placeholder="添加话题"]',
]
PUBLISH_BUTTONS = [
    'button:text-is("发布")',
    'button:text-is("发表")',
    'button:text-is("确认发布")',
    'button.PublishButton:text-is("发布")',
]
MODAL_CLOSERS = [
    ".Modal-closeButton",
    'button[aria-label*="关闭"]',
    'button:has-text("取消")',
    ".Modal button:has-text('确定')",
]


# --------------------------------------------------------------------------- #
# 页面小工具：每个都只做一件事，失败不抛（失败要变成 warnings，不能变成「假装成功」）
# --------------------------------------------------------------------------- #

def _first(page: Any, selectors: list[str]) -> Any:
    for sel in selectors:
        try:
            el = page.query_selector(sel)
        except Exception:
            el = None
        if el is not None:
            return el
    return None


def _dismiss_modals(page: Any, *, rounds: int = 3) -> int:
    """关掉挡点击的遮罩。知乎的图片上传弹窗是 `.Modal-backdrop` + `.Modal`。

    遮罩不关，后面所有 click/fill 都会以「intercepts pointer events」超时 —— 这正是
    上游那次「图全失败、标签也失败」的直接原因，所以每次交互前都先清一遍。
    """
    closed = 0
    for _ in range(rounds):
        try:
            if not page.query_selector(".Modal-backdrop, .Modal, [class*='Modal-backdrop']"):
                break
        except Exception:
            break
        try:
            page.keyboard.press("Escape")
            time.sleep(0.4)
        except Exception:
            pass
        closer = _first(page, MODAL_CLOSERS)
        if closer is not None:
            try:
                closer.click(timeout=2000)
                closed += 1
                time.sleep(0.4)
                continue
            except Exception:
                pass
        try:
            # 最后一条路：点遮罩空白处（多数弹窗点外部即关）
            page.mouse.click(8, 8)
            time.sleep(0.3)
        except Exception:
            pass
    return closed


def _count_blocks(page: Any) -> int:
    """编辑器里的块数（Draft.js 的 `[data-block]`）——换行有没有生效的唯一依据。"""
    try:
        return int(page.evaluate(
            """() => {
                const ed = document.querySelector('.public-DraftEditor-content, .DraftEditor-root');
                return ed ? ed.querySelectorAll('[data-block="true"]').length : 0;
            }"""
        ) or 0)
    except Exception:
        return 0


def _count_blocks(page: Any) -> int:
    """编辑器里的块数（Draft.js 的 `[data-block]`）——段落有没有真的分开的唯一依据。"""
    try:
        return int(page.evaluate(
            """() => {
                const ed = document.querySelector('.public-DraftEditor-content, .DraftEditor-root');
                return ed ? ed.querySelectorAll('[data-block="true"]').length : 0;
            }"""
        ) or 0)
    except Exception:
        return 0


def _set_content(page: Any, content: str, warnings: list[str], *, title: str = "") -> dict[str, Any]:
    """把正文放进知乎编辑器：**先粘贴打底拿段落结构，再补敲标记行触发 markdown 转换**。

    为什么不用「逐行敲键盘」（2026-09-19 实测两条路各瘸一条腿）：
      - 逐行 type + Enter：标记会被转换，但长段落上 Enter 会被编辑器吞掉 ——
        3624 字的真稿只得到 **1 个块**（整篇挤成一个 H2），自检报「28 行没能断开」；
      - 直接粘贴：换行会变成真正的段落块（54 个块，4.5 秒），但 `## ` 这些标记**不转换**，
        会以原文留在正文里。
    所以：粘贴拿结构 → 找出以 `# ` / `## ` / `- ` 开头的块，删掉行首标记再用键盘敲一遍，
    让知乎的输入规则把它转成标题/列表块 → 最后把块结构量出来如实回报。
    """
    stats: dict[str, Any] = {"blocksAfter": 0, "headings": 0, "listItems": 0, "markerBlocks": 0, "repaired": 0}

    lines = (content or "").split("\n")
    # 首行的 `# 标题` 与标题字段重复，留在正文里就是一篇开头又抄一遍标题
    if lines and lines[0].startswith("# ") and not lines[0].startswith("## "):
        stats["droppedTitleLine"] = True
        lines = lines[1:]
    text = "\n".join(lines)

    editor = _first(page, EDITOR_SELECTORS)
    if editor is None:
        warnings.append("没找到正文编辑器，正文没放进去")
        return stats
    editor.click()
    time.sleep(0.3)
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    time.sleep(0.5)

    # 1) 逐行放进去：**标记用敲键、内容用 insert_text**
    #
    # 三条实测事实（2026-09-19，`scripts/probe_typing.py` / `probe_paste.py`）决定了这个做法：
    #   · 整篇 type()：换行只是普通换行 → 整篇挤成一段，`##` 原样留在正文里；
    #   · 逐行 type() + Enter：长段落上 Enter 会被吞 → 3624 字只得到 1 个块；
    #   · insert_text（不走键盘事件）+ Enter：段落能正常分开，但**不触发 markdown 输入规则**；
    #   · 剪贴板粘贴：段落分得很干净，同样不触发转换。
    # 而且知乎的转换规则**只对空块生效**（块里已经有字时敲 `## ` 不转 —— 补敲那版试过，白敲）。
    # 所以：每行都从「空块」开始 —— 标记先用键盘敲出来（此刻块是空的，规则生效 → 变成标题/列表块），
    # 再用 insert_text 把这一行的正文填进去（不碰键盘事件，不会把分段搞坏），最后 Enter 开下一块。
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    time.sleep(0.4)
    marker_lines = 0
    for line in lines:
        stripped = line.strip()
        marker = ""
        if stripped.startswith("## "):
            marker = "## "
        elif stripped.startswith("# "):
            marker = "# "
        elif stripped.startswith("- "):
            marker = "- "
        try:
            if marker:
                page.keyboard.type(marker, delay=30)      # 键盘事件 → 触发转换
                marker_lines += 1
                rest = stripped[len(marker):]
                if rest:
                    page.keyboard.insert_text(rest)       # 内容不走键盘事件
            elif stripped:
                page.keyboard.insert_text(stripped)
            page.keyboard.press("Enter")
            time.sleep(0.05)
        except Exception as exc:
            warnings.append(f"正文第 {marker_lines} 行没放进去（{type(exc).__name__}）")
            break
    time.sleep(1.0)
    stats["markerLines"] = marker_lines
    stats["blocksAfterTyping"] = _count_blocks(page)

    # 3) 量结果
    md = _markdown_report(page)
    stats.update({k: md.get(k) for k in ("blocks", "headings", "listItems", "markerBlocks")})
    stats["blocksAfter"] = md.get("blocks") or 0
    if stats.get("markerBlocks"):
        warnings.append(
            f"正文里还有 {stats['markerBlocks']} 处 markdown 标记没被转换（`##` 之类会以原文显示）"
        )
    return stats


def _repair_marker_blocks(page: Any, warnings: list[str]) -> int:
    """把行首的 `# `/`## `/`- ` 重新敲一遍，让知乎把它们转成标题/列表块。

    知乎的转换靠**键盘输入规则**（敲出 `## ` 才转），粘贴不触发；所以这里定位到
    还带标记的块，删掉标记再敲回来。
    """
    fixed = 0
    for _ in range(20):
        target = None
        try:
            target = page.evaluate(
                """() => {
                    const ed = document.querySelector('.public-DraftEditor-content, .DraftEditor-root');
                    if (!ed) return null;
                    const blocks = Array.from(ed.querySelectorAll('[data-block="true"]'));
                    const b = blocks.find((x) => {
                        const t = x.innerText || '';
                        return t.startsWith('## ') || t.startsWith('# ') || t.startsWith('- ');
                    });
                    if (!b) return null;
                    const r = b.getBoundingClientRect();
                    return {x: r.left + 6, y: r.top + r.height / 2, text: (b.innerText || '').slice(0, 20)};
                }"""
            )
        except Exception:
            target = None
        if not target:
            break
        text = str(target.get("text") or "")
        marker = "## " if text.startswith("## ") else ("# " if text.startswith("# ") else "- ")
        try:
            page.mouse.click(float(target["x"]), float(target["y"]))
            time.sleep(0.25)
            page.keyboard.press("Home")
            for _ in range(len(marker)):
                page.keyboard.press("Shift+ArrowRight")
            page.keyboard.press("Delete")
            time.sleep(0.15)
            # 键盘敲出标记本身（最后一个空格触发转换）
            page.keyboard.type(marker, delay=40)
            time.sleep(0.6)
            fixed += 1
        except Exception as exc:
            warnings.append(f"补敲标记行失败（{type(exc).__name__}）")
            break
    if fixed:
        time.sleep(0.8)
    return fixed


def _count_editor_images(page: Any) -> int:
    """编辑器里现在有几张图 —— 判断「真的插进去了」的唯一依据。

    口径必须只算一次/张：一张图在 DOM 里是「外层容器 + 内层 img」，混着数会把 4 张
    报成 8 张（上一版就报了 8/4，差点让「成功」变成又一次自说自话）。
    优先数 img（一张图一个 img），拿不到再退回数顶层容器。
    """
    try:
        return int(page.evaluate(
            """() => {
                const roots = document.querySelectorAll(
                    '.public-DraftEditor-content, .DraftEditor-root, [contenteditable="true"]'
                );
                const imgs = new Set();
                roots.forEach((r) => r.querySelectorAll('img').forEach((i) => imgs.add(i)));
                if (imgs.size) return imgs.size;
                const blocks = new Set();
                roots.forEach((r) => r.querySelectorAll('figure, [class*="imageContainer"], [class*="Editable-image"]')
                    .forEach((el) => {
                        // 只算最外层：父级里已经有同类容器的不重复计
                        if (!el.parentElement || !el.parentElement.closest('figure, [class*="imageContainer"], [class*="Editable-image"]')) {
                            blocks.add(el);
                        }
                    }));
                return blocks.size;
            }"""
        ) or 0)
    except Exception:
        return 0


def _markdown_report(page: Any) -> dict[str, Any]:
    """正文到底被渲染成了什么结构 —— 用 DOM 事实说话，不靠肉眼看截图。

    （第一版这里只数「行首 `##`」，结果整段被压成一行时行首一个都没有，报了个假绿。
    现在直接吐块结构：每块的标签 + 文本前 24 字，外加「还残留标记的块数」。）
    知乎的 markdown 是块级转换：`## x` 变成 H2/H3 块、`- x` 变成 LI 块；
    没转换的话这些标记会原样留在块文本里。
    """
    try:
        raw = page.evaluate(
            """() => {
                const ed = document.querySelector('.public-DraftEditor-content, .DraftEditor-root');
                if (!ed) return {blocks: 0, headings: 0, listItems: 0, markerBlocks: 0, head: []};
                const blocks = Array.from(ed.querySelectorAll('[data-block="true"]'));
                const texts = blocks.map((b) => (b.innerText || '').replace(/\\n/g, ' ').trim());
                return {
                    blocks: blocks.length,
                    headings: blocks.filter((b) => (b.tagName || '').charAt(0) === 'H').length,
                    listItems: blocks.filter((b) => b.tagName === 'LI').length,
                    // 用字符串方法数残留标记，不写正则：两层字符串里正则转义太容易写坏
                    // （上一版就因为转义写坏，整个 evaluate 抛 SyntaxError，报告成了 error）
                    // 只算真正的 markdown 标记：`# `/`## ` 带空格开头，或正文里残留 `## `。
                    // 别用「以 # 开头」——正文里的 `#标签` 是正常内容，会被误报成残留标记。
                    markerBlocks: texts.filter((t) => t.startsWith('# ') || t.startsWith('## ')
                        || t.indexOf('## ') >= 0).length,
                    head: blocks.slice(0, 12).map((b) => b.tagName + ': ' + (b.innerText || '').replace(/\\n/g, ' ').slice(0, 24)),
                };
            }"""
        )
        return dict(raw)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _open_image_modal(page: Any, warnings: list[str]) -> Any:
    """点「图片」打开上传弹窗，返回弹窗里的上传输入框（找不到返回 None）。"""
    inp = page.query_selector('.Modal input[type=file][accept*="image"]')
    if inp is not None:
        return inp
    btn = _first(page, IMAGE_BUTTONS)
    if btn is None:
        return None
    try:
        btn.click(timeout=6000)
    except Exception:
        # 被别的浮层挡住时退一步用 JS 点（只影响「点得到点不到」，不影响上传本身）
        try:
            page.evaluate("""() => {
                const b = Array.from(document.querySelectorAll('button')).find(x => (x.innerText || '').includes('图片'));
                if (b) b.click();
            }""")
        except Exception as exc:
            warnings.append(f"点不开「图片」按钮：{type(exc).__name__}")
            return None
    for _ in range(12):
        time.sleep(0.8)
        for sel in IMAGE_INPUTS:
            inp = page.query_selector(sel)
            if inp is not None:
                return inp
    return None


def _modal_uploaded_count(page: Any) -> int:
    """弹窗里「已上传 N 张图片」的 N —— 判断某张图有没有真的传上去。"""
    try:
        text = page.evaluate("""() => ((document.querySelector('.Modal-inner') || {}).innerText || '')""") or ""
    except Exception:
        return 0
    m = re.search(r"已上传\s*(\d+)\s*张", text)
    return int(m.group(1)) if m else 0


def _modal_image_input(page: Any) -> Any:
    """弹窗里那个上传输入框（找不到返回 None）。"""
    for sel in IMAGE_INPUTS:
        try:
            inp = page.query_selector(sel)
        except Exception:
            inp = None
        if inp is not None:
            return inp
    return None


def _wait_modal_uploaded(page: Any, target: int, *, timeout: float = 150.0, stall: float = 12.0) -> int:
    """等弹窗里的「已上传 N 张图片」涨到 target，返回最后看到的 N。

    快在两点：0.25 秒一问（原来 1 秒一问），到了就立刻返回；
    连续 stall 秒没变化就当卡住，不傻等到超时（2026-09-19 前逐张传 8 张，实测 61 秒里大半花在这里）。
    """
    deadline = time.monotonic() + timeout
    last = _modal_uploaded_count(page)
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        n = _modal_uploaded_count(page)
        if n >= target:
            return n
        if n != last:
            last, last_change = n, time.monotonic()
        elif time.monotonic() - last_change > stall:
            return n
        time.sleep(0.25)
    return _modal_uploaded_count(page)


def _insert_images(page: Any, warnings: list[str]) -> bool:
    """点弹窗里的「插入图片」—— 上传到弹窗只是进了队列，不点这个不会进正文。"""
    for _ in range(3):
        btn = None
        try:
            for b in page.query_selector_all("button"):
                if (b.inner_text() or "").strip() == "插入图片":
                    btn = b
                    break
        except Exception:
            btn = None
        if btn is None:
            warnings.append("图片弹窗里没找到「插入图片」按钮")
            return False
        try:
            btn.click(timeout=8000)
        except Exception:
            try:
                page.evaluate("""() => {
                    const b = Array.from(document.querySelectorAll('button')).find(x => (x.innerText || '').trim() === '插入图片');
                    if (b) b.click();
                }""")
            except Exception as exc:
                warnings.append(f"「插入图片」点不动：{type(exc).__name__}")
                continue
        time.sleep(1.5)
        return True
    return False


def _set_images(page: Any, images: list[str], warnings: list[str]) -> tuple[int, int]:
    """把配图插进正文。返回 (真正进正文的张数, 没进去的张数)。

    实测到的两段式（探针 `scripts/probe_image_upload.py` 量出来的，别再靠猜）：
      1. 点工具栏「图片」→ 打开「上传图片」弹窗；
      2. 对弹窗里的隐藏 input（accept=image/*）`set_input_files`；
         传上去的图进的是**弹窗的队列**，弹窗会显示「已上传 N 张图片」；
      3. 必须再点弹窗里的「插入图片」，图才会进正文（编辑器里的图片数这时才涨）。
    只做第 2 步不做第 3 步，就是「编辑器里图片数没变化」—— 中间那版就卡在这里。
    """
    real_images = [Path(p) for p in images]
    for p in real_images:
        if not p.is_file():
            warnings.append(f"配图不存在，跳过：{p.name}")
    todo = [p for p in real_images if p.is_file()]
    if not todo:
        return 0, len(images)

    if _open_image_modal(page, warnings) is None:
        warnings.append("打不开「上传图片」弹窗，这一篇没有配图")
        return 0, len(images)

    uploaded = 0
    # 一次把全部图交给弹窗（若那个 input 支持 multiple）：弹窗自己排队上传。
    # 逐张传时每张「一次 set_input_files + 最多 25 次 ×1 秒 轮询」，8 张实测光这一步就 ~50 秒。
    inp0 = _modal_image_input(page)
    multi = False
    try:
        multi = bool(inp0 is not None and inp0.get_attribute("multiple") is not None)
    except Exception:
        multi = False
    if multi and len(todo) > 1:
        logger.info(f"配图一次传 {len(todo)} 张（弹窗 input 支持 multiple，不再逐张）")
        try:
            inp0.set_input_files([str(p) for p in todo])
            uploaded = _wait_modal_uploaded(page, len(todo))
            if uploaded < len(todo):
                # 只报告差额，**不重传**已排队的那些：重传会让同一张图进正文两次
                warnings.append(f"一次传 {len(todo)} 张，弹窗里确认到 {uploaded} 张")
        except Exception as exc:
            warnings.append(f"一次传图失败（{type(exc).__name__}: {str(exc)[:80]}），改回逐张")
            uploaded = 0

    if uploaded == 0:
        for path in todo:
            before = _modal_uploaded_count(page)
            sent = False
            for _ in range(2):
                inp = _modal_image_input(page)
                if inp is None:
                    break
                try:
                    inp.set_input_files(str(path))
                except Exception as exc:
                    warnings.append(f"配图塞不进去：{path.name}（{type(exc).__name__}: {str(exc)[:80]}）")
                    break
                if _wait_modal_uploaded(page, before + 1, timeout=30.0, stall=8.0) > before:
                    uploaded += 1
                    sent = True
                    break
                time.sleep(0.5)
            if not sent:
                warnings.append(f"配图没传上去：{path.name}（弹窗里的已上传数没变）")

    if uploaded == 0:
        _dismiss_modals(page)
        return 0, len(images)

    before_editor = _count_editor_images(page)
    if _insert_images(page, warnings):
        for _ in range(20):
            time.sleep(1.0)
            if _count_editor_images(page) > before_editor:
                break
    inserted = max(0, _count_editor_images(page) - before_editor)
    if inserted < uploaded:
        warnings.append(
            f"配图只进正文 {inserted} 张（弹窗里已上传 {uploaded} 张）：剩下的没插进正文，发布前请核对"
        )
    _dismiss_modals(page)
    return inserted, len(images) - inserted


def _count_tags(page: Any) -> int:
    """已添加的话题个数（知乎把它们渲染成小胶囊）。"""
    try:
        return int(page.evaluate(
            """() => document.querySelectorAll('.InputTag, .Tag, [class*="InputTag"]').length"""
        ) or 0)
    except Exception:
        return 0


def _set_tags(page: Any, tags: list[str], warnings: list[str]) -> int:
    """添加话题标签，返回成功个数。

    实测：知乎**文章**写作页没有话题输入框（「发布设置」里只有「添加封面」）。
    上游那个 `input[placeholder*="话题"]` 命中的其实是图片弹窗里的搜索框 ——
    对着它点，只会得到「ElementHandle.click 超时」，然后被记成「标签失败」。
    这里找不到就如实说明并跳过，不去点别的输入框凑数。
    """
    added = 0
    if not tags:
        return 0
    for tag in tags:
        _dismiss_modals(page)
        inp = _first(page, TAG_INPUTS)
        if inp is None:
            warnings.append(
                "标签这一项跳过：知乎文章写作页只有「添加封面」，没有话题输入框"
                "（探针实测；话题要发布后在文章页补）"
            )
            return added
        before = _count_tags(page)
        try:
            inp.click(timeout=4000)
            inp.fill(tag)
            time.sleep(1.0)
            page.keyboard.press("Enter")
            for _ in range(6):
                time.sleep(0.6)
                if _count_tags(page) > before:
                    break
            if _count_tags(page) > before:
                added += 1
            else:
                warnings.append(f"标签没加上：{tag}")
        except Exception as exc:
            warnings.append(f"标签没加上：{tag}（{type(exc).__name__}: {str(exc)[:80]}）")
    return added


# --------------------------------------------------------------------------- #
# 发布后核验：点完「发布」不等于发出去了
# --------------------------------------------------------------------------- #

# 知乎的「这篇不存在」页：登录态打开一条被删/从未存在过的文章就会看到它
_ZH_MISSING_MARKERS = ("没有知识存在的荒原", "内容不存在", "你似乎来到了")

# 账号文章列表接口（和 scripts/list_articles.py 用的是同一个，**纯读**）
_ARTICLE_LIST_API = "https://www.zhihu.com/api/v4/members/{t}/articles?limit=20&offset=0&sort_by=created"


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def account_articles(page: Any, account_token: str) -> Optional[list[dict[str, Any]]]:
    """列出当前账号的文章。

    **读不到返回 None（≠ 空表）**：空表是「读到了，但一篇都没有」，None 是「这次没读上」。
    两者在结论里必须分开说 —— 否则「没读上」会被写成「账号里没有它」。
    """
    if not account_token:
        return None
    try:
        page.goto(_ARTICLE_LIST_API.format(t=account_token), wait_until="domcontentloaded", timeout=30000)
        data = json.loads(page.inner_text("body"))
    except Exception as exc:
        logger.warning(f"读账号文章列表失败：{type(exc).__name__}: {str(exc)[:120]}")
        return None
    return [it for it in (data.get("data") or []) if isinstance(it, dict)]


def verify_published(
    page: Any,
    account_token: str,
    url: str,
    title: str,
    *,
    tries: int = 4,
    gap: float = 5.0,
) -> dict[str, Any]:
    """核验「这一篇真的发出去了吗」：账号文章列表里有没有它 / 文章页能不能打开。

    为什么必须核验：点完「发布」知乎可能根本没发（校验没过、触发风控），页面照样停在
    /p/<id>，于是回执把「没发出去」写成「已发布」。2026-09-19 实测两次（22:24 与 22:53 的回执
    都写 published，登录态打开那个链接是知乎 404、账号文章列表里也没有它）；同一天另外两篇
    则是**记了 /edit 编辑页地址**。所以这里只认「账号列表里有它」或「文章页打得开且标题对得上」。

    返回 {verified, canonicalUrl, matchedTitle, total, how, note}。**纯读，不改任何东西。**
    """
    want_id = ""
    m = re.search(r"/p/(\d+)", url or "")
    if m:
        want_id = m.group(1)
    want_title = _norm_title(title)

    total = 0
    readable = False      # 读到过列表吗？没有的话结论只能是「无法确认」，不能说「账号里没有」
    for attempt in range(max(1, tries)):
        items = account_articles(page, account_token)
        if items is None:
            if attempt < tries - 1:
                time.sleep(gap)
            continue
        readable = True
        total = len(items)
        for it in items:
            if want_id and str(it.get("id") or "") == want_id:
                return {
                    "verified": True, "canonicalUrl": str(it.get("url") or url), "matchedTitle": str(it.get("title") or ""),
                    "total": total, "how": "account-list", "readable": True, "note": "",
                }
        if want_title:
            for it in items:
                if _norm_title(str(it.get("title") or "")) == want_title:
                    note = ""
                    if want_id and str(it.get("id") or "") != want_id:
                        note = "回执里的地址不是这篇文章的地址（登录页拿到的多是编辑页/草稿地址），已按账号列表里的正式地址记"
                    return {
                        "verified": True, "canonicalUrl": str(it.get("url") or url), "matchedTitle": str(it.get("title") or ""),
                        "total": total, "how": "account-list-title", "readable": True, "note": note,
                    }
        if attempt < tries - 1:
            time.sleep(gap)      # 刚发出去可能还没进列表，给它几次机会再判死

    # 列表里没有：再看文章页本身（可能是刚发布、还在审核，列表滞后）
    if url:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)
            body = ""
            try:
                body = str(page.inner_text("body") or "")
            except Exception:
                body = ""
            head = body[:400]
            page_title = str(page.title() or "")
            missing = any(k in head or k in page_title for k in _ZH_MISSING_MARKERS)
            if not missing and want_title and want_title in _norm_title(page_title):
                return {
                    "verified": True, "canonicalUrl": url, "matchedTitle": page_title.strip(),
                    "total": total, "how": "article-page", "readable": readable,
                    "note": f"账号文章列表（{total} 篇）里暂时没看到它（可能刚发布或还在审核），但文章页能打开且标题对得上",
                }
        except Exception as exc:
            logger.warning(f"打开文章页核验失败：{type(exc).__name__}: {str(exc)[:120]}")

    if not readable:
        note = "连续几次都没能读到账号文章列表，文章页也打不开，无法确认这一篇真的发出去了"
    else:
        note = f"账号文章列表（{total} 篇）里没有这一篇，链接打开也不是这篇文章" + (
            "（回执里那个地址多半是编辑页/草稿地址）" if want_id else ""
        )
    return {
        "verified": False, "canonicalUrl": "", "matchedTitle": "", "total": total, "how": "",
        "readable": readable, "note": note,
    }


def check_article(url: str, title: str = "", *, tries: int = 1) -> dict[str, Any]:
    """独立核验一个链接（给 /api/v1/verify 用）：自己起一个浏览器上下文，纯读。"""
    from browser.manager import create_browser  # type: ignore[import-not-found]

    with create_browser(headless=True) as (_b, _ctx, page):
        page.set_default_timeout(30000)
        token = ""
        try:
            page.goto("https://www.zhihu.com/api/v4/me", wait_until="domcontentloaded", timeout=30000)
            token = str(json.loads(page.inner_text("body")).get("url_token") or "")
        except Exception as exc:
            logger.warning(f"读账号身份失败：{type(exc).__name__}: {str(exc)[:120]}")
        out = verify_published(page, token, url, title, tries=tries)
        out["url"] = url
        out["account"] = token
        return out


def _capture_url(page: Any, account_token: str, title: str) -> str:
    """发布后抓文章链接。

    上游压根不返回链接，所以这里自己找：先看当前页地址，再去「我的文章」列表里按标题对。
    **抓不到就返回空串**（回执里 url 为空 + 一条 warning），绝不编一个链接出来。
    """
    try:
        url = str(page.url or "")
        if "/p/" in url:
            # 发布后知乎会停在编辑页 …/p/<id>/edit；回执里要给人看的是文章地址
            return url.split("?")[0].removesuffix("/edit").rstrip("/")
    except Exception:
        pass
    if not account_token:
        return ""
    for tmpl in (
        "https://www.zhihu.com/api/v4/members/{t}/articles?limit=5&offset=0&sort_by=created",
        "https://www.zhihu.com/api/v4/members/{t}/articles?limit=5&sort=created",
    ):
        try:
            page.goto(tmpl.format(t=account_token), wait_until="domcontentloaded", timeout=30000)
            data = json.loads(page.inner_text("body"))
            for item in (data.get("data") or []):
                if str(item.get("title") or "").strip() == title.strip():
                    return str(item.get("url") or "")
            first = (data.get("data") or [{}])[0]
            if first.get("url"):
                return str(first["url"])
        except Exception as exc:
            logger.warning(f"取文章链接失败：{type(exc).__name__}: {str(exc)[:120]}")
            continue
    return ""


def _screenshot(page: Any, shot_dir: Optional[Path], name: str) -> str:
    if shot_dir is None:
        return ""
    try:
        shot_dir.mkdir(parents=True, exist_ok=True)
        target = shot_dir / f"{name}.png"
        page.screenshot(path=str(target), full_page=False)
        return str(target)
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def publish_article(
    *,
    title: str,
    content: str,
    images: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    account_token: str = "",
    dry_run: bool = False,
    headless: bool = True,
    shot_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """发一篇知乎文章，或（`dry_run=True`）只把内容填好并回报填成了什么样。

    返回体固定带 `warnings` / `imagesUploaded` / `imagesFailed` / `tagsAdded` / `dryRun` /
    `url`，调用方（通道服务 → 通道 → 回执）把这些如实带出去就好了。
    """
    from browser.manager import create_browser, save_browser_cookies  # type: ignore[import-not-found]

    images = [str(p) for p in (images or [])]
    tags = [str(t) for t in (tags or [])]
    warnings: list[str] = []
    out: dict[str, Any] = {
        "success": False, "message": "", "url": "", "dryRun": dry_run,
        "imagesUploaded": 0, "imagesFailed": 0, "tagsAdded": 0,
        "contentChars": len(content or ""), "warnings": warnings,
    }

    with create_browser(headless=headless) as (browser, context, page):
        page.set_default_timeout(30000)
        page.goto("https://zhuanlan.zhihu.com/write", wait_until="domcontentloaded", timeout=60000)
        time.sleep(2.0)
        _dismiss_modals(page)

        # 1) 标题
        title_el = _first(page, TITLE_SELECTORS)
        if title_el is None:
            out["message"] = "没找到标题输入框（知乎写作页改版了？）"
            out["screenshot"] = _screenshot(page, shot_dir, "no-title-input")
            return out
        title_el.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        title_el.fill(title)
        logger.info(f"标题已填：{title[:40]}")

        # 2) 正文
        editor = _first(page, EDITOR_SELECTORS)
        if editor is None:
            out["message"] = "没找到正文编辑器（知乎写作页改版了？）"
            out["screenshot"] = _screenshot(page, shot_dir, "no-editor")
            return out
        editor.click()
        time.sleep(0.5)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # 逐行输入 + 真的按 Enter：知乎的 markdown 是**块级**转换（`## ` 变成标题、Enter 开新块）。
        # 一口气 page.keyboard.type 整篇（含 \n）实测不转换：`##` 会以原文留在正文里
        # （第一次真发布的截图里就是这样）。逐行敲，代价是慢一点。
        out["typing"] = _set_content(page, content, warnings, title=title)
        time.sleep(0.5)
        logger.info(f"正文已进入编辑器：块数 {out['typing'].get('blocksAfter')}，"
                    f"标题块 {out['typing'].get('headings')}，补敲 {out['typing'].get('repaired')} 行")

        # 3) 配图（逐个核对，失败进 warnings）
        if images:
            ok, bad = _set_images(page, images, warnings)
            out["imagesUploaded"], out["imagesFailed"] = ok, bad
            logger.info(f"配图：成功 {ok} / 失败 {bad}")

        # 4) 标签（失败进 warnings）
        if tags:
            out["tagsAdded"] = _set_tags(page, tags, warnings)

        out["markdown"] = {**(_markdown_report(page)), "blocksAfterTyping": out.get("typing", {}).get("blocksAfter")}
        md = out["markdown"]
        logger.info(f"正文块结构：{md.get('blocks')} 块 / 标题 {md.get('headings')} / 列表 {md.get('listItems')} / 残留标记块 {md.get('markerBlocks')}")
        try:
            page.evaluate("() => window.scrollTo(0, 0)")
            time.sleep(0.5)
        except Exception:
            pass
        out["screenshot"] = _screenshot(page, shot_dir, "draft" if dry_run else "before-publish")

        # 5) 只填不发：到这里就回，**绝不点发布**
        if dry_run:
            save_browser_cookies(context)
            out["success"] = True
            out["message"] = (
                f"只填不发：标题+正文 {out['contentChars']} 字已填，"
                f"配图 {out['imagesUploaded']}/{len(images)} 张进编辑器，标签 {out['tagsAdded']}/{len(tags)} 个"
            )
            return out

        # 6) 真发布
        _dismiss_modals(page)
        btn = _first(page, PUBLISH_BUTTONS)
        if btn is None:
            out["message"] = "没找到「发布」按钮"
            return out
        try:
            btn.click(timeout=8000)
        except Exception:
            # 被遮罩挡住时退一步用 JS 点（上游也是这么干的）；这只影响「点得到点不到」
            page.evaluate("""() => {
                const b = Array.from(document.querySelectorAll('button')).find(x => x.innerText.trim() === '发布');
                if (b) b.click();
            }""")
        logger.info("已点发布，等待结果")
        time.sleep(6.0)
        for _ in range(6):   # 等知乎把页面带到文章页（多数情况会跳 /p/<id>）
            if "/p/" in str(page.url or ""):
                break
            time.sleep(2.0)
        out["url"] = _capture_url(page, account_token, title)
        save_browser_cookies(context)
        out["screenshot"] = _screenshot(page, shot_dir, "after-publish")

        # 7) 核验：点完发布不算数，账号文章列表里真有这一篇才算（2026-09-19 实测过两次假成功）
        verify = verify_published(page, account_token, out["url"], title)
        out["verify"] = verify
        if verify.get("canonicalUrl"):
            out["url"] = verify["canonicalUrl"]
        if verify.get("note"):
            warnings.append(verify["note"])
        if not verify.get("verified"):
            out["success"] = False
            out["message"] = "点了发布但没能确认发出去：" + str(verify.get("note") or "核验不通过")
            logger.warning(f"发布未确认：{out['message']}")
            return out

        out["success"] = True
        out["message"] = (
            "文章发布流程完成（已核验：" + ("账号文章列表里有它" if verify["how"].startswith("account-list") else "文章页能打开且标题对得上") + "）"
            + ("，链接 " + out["url"] if out["url"] else "")
        )
        return out
