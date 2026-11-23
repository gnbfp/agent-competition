"""Launch the validated local demo server and open its URL in a browser."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8080/live"
HEALTH = "http://127.0.0.1:8080/api/health"


def main() -> int:
    print("RunWise AI 正在启动本地演示…", flush=True)
    process = subprocess.Popen([sys.executable, "-m", "src.pipeline", "--demo", "--serve"], cwd=ROOT)
    try:
        for _ in range(70):
            if process.poll() is not None:
                print("启动失败：服务提前退出，请检查上方错误。", file=sys.stderr)
                return process.returncode or 1
            try:
                with urllib.request.urlopen(HEALTH, timeout=1) as response:
                    if response.status == 200:
                        print(f"演示地址：{URL}", flush=True)
                        webbrowser.open(URL)
                        print("关闭服务：回到此窗口并按 Ctrl+C。", flush=True)
                        return process.wait()
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(.4)
        print(f"无法确认服务健康状态，请检查端口 8080 是否被占用。也可手动打开 {URL}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n正在停止本地服务…", flush=True)
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
