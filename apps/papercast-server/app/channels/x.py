"""X（推特）渠道：**只出素材包，不真投递**（material-only）。

为什么有这个渠道：产品里 X 是「英文传播」的落点 —— article 阶段的 en 变体写的就是
6-10 条英文 thread（见 app/styles.py 的 PLATFORMS["en"]）。但 2026-09-19 的决策是
**英文不发**：不接投递 API、不碰账号、不存凭证。

所以它跟三个真渠道**形状一样、语义不同**：
- 一样按渠道取自己那份文案（en 变体）、一样在闸门之前落 publish/x/export/、一样写回执；
- 但 preflight() 直接报 material_only（不触网、不需要登录），publish() **无条件**返回 draft ——
  就算闸门放行也不会发出任何请求（fail-closed：先有真通道，再谈放行）。

回执落在 publish/x/receipt.json，status=draft，作品库里那一格显示成「存了草稿」。
接真通道是 R2 的事，那时只需把 publish() 换成真投递，编排层不用动。
"""

from __future__ import annotations

from pathlib import Path

from .base import Channel, Delivery, Materials, Preflight


class XChannel(Channel):
    id = "x"
    name = "X（推特）"
    # 'en' 也认：老配置里英文传播可能被当成目标写法，归一到 X 而不是报「未知渠道」
    aliases = ("twitter", "x-com", "en")
    capabilities = frozenset({"text"})          # 英文 thread 是纯文本；配图按素材包人工带
    login_kind = "none"                         # 不需要登录：不发，就没有账号
    transport = "export"                        # 传输=导出素材包（不是 HTTP/MCP/CLI）
    material_only = True
    why = "只把英文 thread 落成本地素材包，不接投递通道（本轮不真发）"
    restart_hint = "不需要登录，也没有通道服务：素材包落在 publish/x/export/，可手动贴到 X"

    # ------------------------------------------------------------------ #
    # 适配性：X 只要英文 thread，别的稿子别拿来说事
    # ------------------------------------------------------------------ #

    def supports(self, m: Materials) -> tuple[bool, str]:
        platform = str((m.extra or {}).get("variantPlatform") or "")
        if platform != "en":
            return False, "这一轮没有英文 thread（只有中文稿）：先勾上「英文传播」再跑，X 才有东西可发"
        return True, "英文 thread %d 字符（6-10 条帖的合稿）" % len(m.body)

    # ------------------------------------------------------------------ #
    # 探测 / 投递
    # ------------------------------------------------------------------ #

    async def preflight(self) -> Preflight:
        """**不触网**：X 没有通道服务、不需要账号，状态是配置性事实而非探测结果。"""
        return Preflight(
            state="material_only",
            account="",
            detail="只把英文 thread 落成本地素材包，不会真的发到 X",
            transport=self.transport,
            reachable=False,
            hint=self.restart_hint,
        )

    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        """**永远不真发**：本轮没接投递通道，确认与否都只回 draft。

        这是刻意的 fail-closed —— 编排层（modules/publish.py）也不会为它调这里，
        留着这一层是为了「万一被别的路径调到」也不会有任何一个字节发出去。
        """
        return Delivery(
            channel=self.id,
            status="draft",
            raw={"note": self.why, "confirmed": bool(confirmed)},
        )

    # ------------------------------------------------------------------ #
    # 素材包
    # ------------------------------------------------------------------ #

    def compose_body(self, m: Materials) -> str:
        """thread 原文照发（标签已经写在 en 变体的 Tags 小节里），只补一行论文出处。"""
        body = m.body.strip()
        if m.source:
            body += "\n\nSource: " + m.source
        return body + "\n"

    def manual_steps(self, m: Materials, out: Path) -> str:
        shots = "、".join(p.name for p in m.images) or "（这一件没有配图）"
        return (
            "X（推特）素材包 —— 这一轮不会自动发，照下面三步手动发：\n"
            "\n"
            "1. 打开 x.com 并登录你自己的账号（本机没有存 X 的任何凭证）；\n"
            "2. 把 content.txt 里的 thread 按空行分条贴上去：第一条是钩子、最后一条收在结论，"
            "每条不超过 280 字符；\n"
            "3. 需要配图就带上 %s；标签在 tags.txt 里。\n"
            "\n"
            "发完想留个记录：把链接填进同目录的 publish_request.json（可选）。\n"
            % shots
        )
