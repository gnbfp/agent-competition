"""Serve one completed pipeline report and its page on loopback."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from contracts.validate_contract import load_json, validate_document


WEB = Path(__file__).resolve().parent / "p5_web"
STATIC = {"/live": ("index.html", "text/html"), "/dashboard.css": ("dashboard.css", "text/css"),
          "/dashboard.js": ("dashboard.js", "text/javascript")}
MAX_REQUEST = 4 * 1024 * 1024
COUNT_KEYS = ("input_rows", "accepted_rows", "skipped_rows", "incomplete_rows", "device_anomaly_rows")


def report_handler(report_path: Path, *, on_run=None) -> type[BaseHTTPRequestHandler]:
    report_path = report_path.resolve()
    run_lock = Lock()

    def get_report(path: Path) -> dict:
        report = load_json(path)
        if (not isinstance(report, dict) or report.get("schema_version") != "2.0"
                or validate_document(path, report)):
            raise ValueError("report v2 required")
        return report

    def get_summary(path: Path) -> dict:
        summary = load_json(path.with_name("import_quality.json"))
        if not isinstance(summary, dict) or any(type(summary.get(key)) is not int or summary[key] < 0
                                                for key in COUNT_KEYS):
            raise ValueError("invalid import summary")
        return {key: summary[key] for key in COUNT_KEYS}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_data(self, status: int, body: bytes, mime: str, *, location: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                             "style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, data: dict) -> None:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_data(status, body, "application/json; charset=utf-8")

        def valid_host(self) -> bool:
            port = self.server.server_port
            if self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return True
            self.send_json(400, {"error": "invalid_host", "message": "请使用本机预览地址。"})
            return False

        def do_GET(self):
            if not self.valid_host():
                return
            path = urlparse(self.path).path
            if path == "/":
                self.send_data(303, b"", "text/plain; charset=utf-8", location="/live")
            elif path in STATIC:
                filename, mime = STATIC[path]
                try:
                    page = (WEB / filename).read_bytes()
                except OSError:
                    self.send_json(503, {"error": "page_unavailable", "message": "预览页面暂不可读。"})
                else:
                    self.send_data(200, page, mime + "; charset=utf-8")
            elif path in ("/api/report", "/api/health", "/api/snapshot"):
                self.send_report(path)
            else:
                self.send_json(404, {"error": "not_found", "message": "页面或接口不存在。"})

        def send_report(self, route: str) -> None:
            path = report_path
            try:
                report = get_report(path)
                if route == "/api/snapshot":
                    report = {"report": report, "import_quality": get_summary(path)}
                elif route == "/api/health":
                    report = {"ok": True, "mode": "local", "schema_version": "2.0"}
            except FileNotFoundError:
                self.send_json(503 if route == "/api/health" else 404,
                               {"error": "report_missing", "message": "本次运行的报告文件不存在。"})
            except (OSError, KeyError, ValueError, TypeError, OverflowError):
                self.send_json(503, {"error": "report_unavailable", "message": "本次报告无法读取或未通过校验。"})
            else:
                self.send_json(200, report)

        def do_POST(self):
            nonlocal report_path
            if not self.valid_host():
                return
            if urlparse(self.path).path != "/api/run" or on_run is None:
                self.send_json(404, {"error": "not_found", "message": "导入接口不可用。"})
                return
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                self.send_json(403, {"error": "bad_origin", "message": "请从本机预览页提交。"})
                return
            mime = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if mime != "application/json":
                self.send_json(415, {"error": "bad_media", "message": "请求需使用 JSON。"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if not 0 < size <= MAX_REQUEST:
                self.send_json(413, {"error": "bad_size", "message": "提交内容为空或太大。"})
                return
            if not run_lock.acquire(blocking=False):
                self.send_json(409, {"error": "run_in_progress", "message": "已有导入任务正在运行。"})
                return
            try:
                self.connection.settimeout(15)
                try:
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("主体长度不一致")
                    payload = json.loads(raw)
                except (OSError, RecursionError, ValueError):
                    self.send_json(400, {"error": "invalid_json", "message": "无法读取完整的 JSON 请求。"})
                    return
                try:
                    path = Path(on_run(payload)) / "report.json"
                    report = get_report(path)
                    summary = get_summary(path)
                except (ValueError, RuntimeError) as exc:
                    self.send_json(422, {"error": "run_failed", "message": str(exc)})
                    return
                except (OSError, KeyError, TypeError):
                    self.send_json(503, {"error": "report_unavailable", "message": "本次报告暂不可用。"})
                    return
                report_path = path
                self.send_json(200, {"report": report, "import_quality": summary})
            finally:
                run_lock.release()

    return Handler


def make_report_server(report_path: Path, port: int = 8080, *, on_run=None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), report_handler(report_path, on_run=on_run))


def serve_report(report_path: Path, port: int, *, on_run=None) -> None:
    with make_report_server(report_path, port, on_run=on_run) as server:
        print(f"本地报告预览 http://127.0.0.1:{server.server_port}/live", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("本地预览已停止。")
