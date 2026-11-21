"""Serve one completed pipeline report and its page on loopback."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse
from uuid import uuid4

from contracts.validate_contract import load_json, validate_document
from src.ai_analysis import AnalysisError, analyze_report


WEB = Path(__file__).resolve().parent / "p5_web"
STATIC = {"/live": ("index.html", "text/html"), "/dashboard.css": ("dashboard.css", "text/css"),
          "/dashboard.js": ("dashboard.js", "text/javascript")}
MAX_REQUEST = 4 * 1024 * 1024
COUNT_KEYS = ("input_rows", "accepted_rows", "skipped_rows", "incomplete_rows", "device_anomaly_rows")


def report_handler(report_path: Path, *, on_run=None) -> type[BaseHTTPRequestHandler]:
    current = (report_path.resolve(), uuid4().hex)
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
                             "style-src 'self'; connect-src 'self'; base-uri 'none'; "
                             "form-action 'none'; frame-ancestors 'none'")
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
            path, report_id = current
            try:
                report = get_report(path)
                if route == "/api/snapshot":
                    report = {"report": report, "import_quality": get_summary(path), "report_id": report_id}
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
            if not self.valid_host():
                return
            route = urlparse(self.path).path
            if route != "/api/ai" and (route != "/api/run" or on_run is None):
                self.send_json(404, {"error": "not_found", "message": "请求接口不可用。"})
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
            if not 0 < size <= (4096 if route == "/api/ai" else MAX_REQUEST):
                self.send_json(413, {"error": "bad_size", "message": "提交内容为空或太大。"})
                return
            self.connection.settimeout(15)
            try:
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("主体长度不一致")
                payload = json.loads(raw)
            except (OSError, RecursionError, ValueError):
                self.send_json(400, {"error": "invalid_json", "message": "无法读取完整的 JSON 请求。"})
                return
            if route == "/api/ai":
                self.send_analysis(payload)
            else:
                self.run_report(payload)

        def send_analysis(self, payload):
            path, report_id = current
            if not isinstance(payload, dict) or set(payload) != {"report_id", "api_key", "base_url", "model"}:
                self.send_json(400, {"error": "invalid_analysis_request", "message": "AI 连接参数不完整。"})
                return
            if payload["report_id"] != report_id:
                self.send_json(409, {"error": "stale_report", "message": "本机报告已更新，请刷新页面后再分析。"})
                return
            try:
                analysis = analyze_report(get_report(path), payload)
            except AnalysisError as exc:
                self.send_json(exc.status, {"error": "ai_failed", "message": str(exc)})
                return
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                self.send_json(503, {"error": "report_unavailable", "message": "本次报告无法读取或未通过校验。"})
                return
            self.send_json(200, {"report_id": report_id, "analysis": analysis})

        def run_report(self, payload):
            nonlocal current
            if not run_lock.acquire(blocking=False):
                self.send_json(409, {"error": "run_in_progress", "message": "已有导入任务正在运行。"})
                return
            try:
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
                report_id = uuid4().hex
                current = (path, report_id)
                self.send_json(200, {"report": report, "import_quality": summary, "report_id": report_id})
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
