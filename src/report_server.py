"""Serve one completed pipeline report and its page on loopback."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from contracts.validate_contract import load_json, validate_document


PAGE = Path(__file__).resolve().parent / "p5_web" / "index.html"


def report_handler(report_path: Path) -> type[BaseHTTPRequestHandler]:
    report_path = report_path.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_data(self, status: int, body: bytes, mime: str, *, location: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, data: dict) -> None:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_data(status, body, "application/json; charset=utf-8")

        def do_GET(self):
            port = self.server.server_port
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self.send_json(400, {"error": "invalid_host", "message": "请使用本机预览地址。"})
                return
            path = urlparse(self.path).path
            if path == "/":
                self.send_data(303, b"", "text/plain; charset=utf-8", location="/live")
            elif path == "/live":
                try:
                    page = PAGE.read_bytes()
                except OSError:
                    self.send_json(503, {"error": "page_unavailable", "message": "预览页面暂不可读。"})
                else:
                    self.send_data(200, page, "text/html; charset=utf-8")
            elif path in ("/api/report", "/api/health"):
                self.send_report(path == "/api/health")
            else:
                self.send_json(404, {"error": "not_found", "message": "页面或接口不存在。"})

        def send_report(self, health: bool) -> None:
            try:
                report = load_json(report_path)
                if (not isinstance(report, dict) or report.get("schema_version") != "2.0"
                        or validate_document(report_path, report)):
                    raise ValueError("report v2 required")
            except FileNotFoundError:
                self.send_json(503 if health else 404,
                               {"error": "report_missing", "message": "本次运行的报告文件不存在。"})
            except (OSError, KeyError, ValueError, TypeError, OverflowError):
                self.send_json(503, {"error": "report_unavailable", "message": "本次报告无法读取或未通过校验。"})
            else:
                self.send_json(200, {"ok": True, "mode": "local", "schema_version": "2.0"} if health else report)

    return Handler


def make_report_server(report_path: Path, port: int = 8080) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), report_handler(report_path))


def serve_report(report_path: Path, port: int) -> None:
    with make_report_server(report_path, port) as server:
        print(f"本地报告预览 http://127.0.0.1:{server.server_port}/live", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("本地预览已停止。")
