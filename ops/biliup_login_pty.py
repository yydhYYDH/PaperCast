#!/usr/bin/env python3
"""用 pty 驱动 biliup 扫码登录：选择「扫码登录」，原始输出写到 var/logs/。
路径全部相对本文件推导（var/scratch/xxx.py -> 工作区根）。"""
import os, pty, select, pathlib, time, sys

WS = pathlib.Path(__file__).resolve().parents[2]
PY = str(WS / "var/toolchains/bili-venv/bin/python")
HOME = str(WS / "var/home")
COOKIE = str(WS / "var/home/.bilibili/cookies.json")
LOG = WS / "var/logs/biliup_login_pty.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(HOME, ".bilibili").mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = HOME
os.environ["USERPROFILE"] = HOME
os.chdir(HOME)  # biliup 把 qrcode.png 写在 CWD

pid, fd = pty.fork()
if pid == 0:
    os.execv(PY, [PY, "-m", "biliup", "-u", COOKIE, "login"])

buf = b""
sent = False
start = time.time()
with open(LOG, "wb") as f:
    while time.time() - start < 900:
        try:
            r, _, _ = select.select([fd], [], [], 1.0)
        except OSError:
            break
        if r:
            try:
                data = os.read(fd, 8192)
            except OSError:
                break
            if not data:
                break
            f.write(data)
            f.flush()
            buf += data
            if not sent and "扫码登录".encode() in buf:
                time.sleep(0.4)
                os.write(fd, b"\x1b[B\r")
                sent = True
                print("selected 扫码登录", flush=True)
print("login process ended; cookie exists:", pathlib.Path(COOKIE).exists(), flush=True)
