# 知乎官方 OpenAPI 发布（本地实现）

对齐知乎官方 skill [zhihu/ZhihuPublisher](https://github.com/zhihu/ZhihuPublisher) 的协议，
用一份自包含脚本走完 validate -> preview -> publish 三阶段，不依赖 skill 注册中心。

## 文件

- `publish.py`：Markdown -> validate/latest.json + preview/latest.html + publish/latest-request.json，签名并 POST。
- `sample-article.md`：测试稿（已挪到 `var/samples/zhihu-sample-article.md`）。
- 产物目录：`var/artifacts/zhihu/publish-output/{validate,preview,publish}/`（不再写 cwd 下的隐藏目录）。

## 凭证

| 变量 | 含义 | 获取 |
|---|---|---|
| `ZHIHU_OPENAPI_APP_KEY` | 知乎用户 Token（主页 URL 用户名） | `https://www.zhihu.com/people/<这里>` |
| `ZHIHU_OPENAPI_APP_SECRET` | 开放平台访问密钥 | https://www.zhihu.com/playground/zhihu-publisher |

读取顺序：环境变量 -> `~/.zhihu/openapi-credentials.json`。

## 用法（凭证就绪后）

```bash
cd "$(git rev-parse --show-toplevel)"
SAMPLE=var/samples/zhihu-sample-article.md

# 0) 凭证探测：401 = 密钥无效；非 401 = 鉴权通过（发送的是故意非法的 type，不会创建内容）
python3 apps/zhihu-publisher/scripts/publish.py "$SAMPLE" --check-creds

# 1) 只生成 validate/preview/request，不发送
python3 apps/zhihu-publisher/scripts/publish.py "$SAMPLE" --title "DSH 官方接口连通性测试" --creation-statement ai_creation --dry-run

# 2) 真发（confirmed=true 即直接公开到你的知乎账号，接口没有草稿开关）
python3 apps/zhihu-publisher/scripts/publish.py "$SAMPLE" --title "DSH 官方接口连通性测试" --creation-statement ai_creation
```

可选参数：`--topics https://www.zhihu.com/topic/19555547/hot`（最多 3 个）、
`--comment-permission {all,nobody,followee,censor,follower}`、`--toc`。

## 已实测

- 端点存活（GET 405），签名+headers 被正常解析，假凭证返回 HTTP 401 `AuthenticationError`。
- 真实发布尚未执行：等待 `APP_SECRET`（需到开放平台申请，**需等审核**）。
- **绕开审核的登录路线实测（2026-09-19）**：
  - `zhihu-cli`（`reference/upstream/zhihu-cli`，MIT）走 `POST https://www.zhihu.com/api/v3/account/api/login/qrcode` 拿扫码链接，
    实测能拿到二维码，但本机网络随即被知乎**风控拦截**：返回 `https://www.zhihu.com/account/unhuman?type=S6E3V1...`，
    CLI 停在「请在浏览器完成验证后按回车」。日志：`var/logs/zhihu-qr-login.log`。
  - 结论：本机 IP 已被判定为自动化环境，**纯 HTTP 扫码登录不可用**；可行的是
    1) `zhihu auth paste`：从你自己浏览器 DevTools 复制 cURL（最省事，无风控）；
    2) 有头浏览器人工登录（`zhihu-mcp/login.py --no-headless`，DISPLAY=:0 可用），窗口里人工过验证；
    3) 浏览器插件（Wechatsync）在你自己的 Chrome 里带真实会话发布。

## 已打通的通道（cookie + Playwright，2026-09-19 实测成功）

账号 `yydh-75`（YYDH）；cookie 落盘 `var/secrets/zhihu/cookies.json`（含 `z_c0`，23→33 个；
凭证进 `var/secrets/`，投递中转才放 `var/artifacts/`，规范见 `docs/conventions.md` §4/§5）。

```bash
# 1) 人工登录（必须在能看到窗口的终端跑；沙箱内看不到 X/Wayland socket）
./apps/zhihu-publisher/scripts/login_wait.py   # 实际用 var/toolchains/zhihu-mcp-venv/bin/python 执行
#    打开窗口 -> 你扫码/密码登录（含人机验证）-> 轮询到 z_c0 才保存

# 2) 发布（无头复用登录态；无草稿模式，点发布即公开）
cd reference/upstream/zhihu-mcp
COOKIES_PATH="$WS/var/secrets/zhihu/cookies.json" \
PLAYWRIGHT_BROWSERS_PATH=/home/yydh/.cache/ms-playwright \
"$WS/var/toolchains/zhihu-mcp-venv/bin/python" -c "
import os,sys; sys.path.insert(0,os.getcwd())
from zhihu.service import ZhihuService
print(ZhihuService().publish_article('标题','正文',None,None,headless=True))"
```

- 实测产物：<https://zhuanlan.zhihu.com/p/2084432742410993947>，证据图 `docs/evidence/zhihu-test-post.png`。
- 坑 1：上游 `login.py` 用「访问 /signin 被重定向」判断已登录，**风控跳转会被误判成登录成功**（存下 16 个没有 `z_c0` 的假 cookie）。所以用 `login_wait.py`。
- 坑 2：上游 `main.py --headless` 不生效（`--no-headless` 的 `default=True` 让 `headless` 恒为 False），起 MCP 服务会试图开有头浏览器；无头场景直接调 `ZhihuService` 更省事。
- 坑 3：18060 端口已被并发会话的 MCP 实例占用，自己起实例请换端口。

## 运行环境（已就位）

```bash
WS=/home/yydh/hack   # 仅示例，脚本内部不写死
var/toolchains/zhihu-cli-venv        # zhihu-toolkit 0.1.1.dev1（从本地 clone 装的）
var/toolchains/zhihu-mcp-venv        # Douyh123/zhihu-mcp 依赖（fastmcp 4.0.5 + playwright）
var/home/zhihu-home                  # 上面两个工具用 HOME 重定向到这里，避免写 ~/.zhihu-cli
var/artifacts/zhihu/                 # 二维码截图、export/ 等投递中转产物（凭证不在这里）
var/secrets/zhihu/cookies.json       # 登录凭证（chmod 600）
```

签名：`X-Sign = Base64(HMAC-SHA256("app_key:{k}|ts:{ts}|logid:{logid}|extra_info:{extra}", SECRET))`。
判定：HTTP 200 不代表成功，必须看响应 JSON 的 `status == 0`。
