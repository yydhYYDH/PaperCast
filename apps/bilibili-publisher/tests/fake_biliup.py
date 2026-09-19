#!/usr/bin/env python3
"""假的 biliup：只复刻「上传锁写哪儿」这一件事。

路径推导跟上游一致（crates/biliup-cli/src/upload_lock.rs）：
    dirs::data_local_dir() = 绝对路径的 $XDG_DATA_HOME，否则 $HOME/.local/share
锁文件：<data_local_dir>/biliup/locks/biliup_upload_<mid>.lock
"""
import json
import os
import sys
from pathlib import Path

STATE = os.environ.get("STUB_STATE")


def data_local_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME") or ""
    if xdg.startswith("/"):
        return Path(xdg)
    return Path(os.path.expanduser("~")) / ".local" / "share"


def main() -> int:
    lock_dir = data_local_dir() / "biliup" / "locks"
    lock_path = lock_dir / "biliup_upload_123456.lock"
    mode = os.environ.get("STUB_MODE", "ok")
    record = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "HOME": os.environ.get("HOME"),
        "XDG_DATA_HOME": os.environ.get("XDG_DATA_HOME"),
        "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME"),
        "lock_path": str(lock_path),
        "mode": mode,
    }
    if STATE:
        Path(STATE).write_text(json.dumps(record), encoding="utf-8")

    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path.touch()
    except OSError as exc:
        print("Failed to create upload lock: {} (os error {})".format(exc.strerror, exc.errno),
              file=sys.stderr)
        return 1

    if mode == "lock_fail":
        print("Failed to create upload lock: Read-only file system (os error 30)", file=sys.stderr)
        return 1
    if mode == "stale_lock":
        print("另一个使用该账号 (123456) 的上传进程正在等待限流恢复，请稍后重试。", file=sys.stderr)
        return 1
    print("投稿成功 BV1Stub00001 https://www.bilibili.com/video/BV1Stub00001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
