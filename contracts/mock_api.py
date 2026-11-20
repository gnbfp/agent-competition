#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mock API — lets P5 (frontend) start on day one, before P2/P3/P4 exist.

Serves the golden samples with the exact response shape of the real API,
so the frontend is written against the contract, not against real code.

Usage
  python mock_api.py                 # http://127.0.0.1:8000
  python mock_api.py --port 8080 --delay 300
Routes
  GET /api/health /api/activity /api/metrics /api/plan /api/report
  GET /api/metrics?version=2.0
  GET /api/report?version=2.0
  GET /api/report?week=2026-11-16    (same body, week ignored)
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
ROUTES = {
    "/api/activity": "activity_sample.json",
    "/api/metrics": "metrics_sample.json",
    "/api/plan": "plan_sample.json",
    "/api/report": "report_sample.json",
}
VERSIONED_SAMPLES = {
    "/api/metrics": {"1.0": ROUTES["/api/metrics"], "2.0": "metrics_v2_sample.json"},
    "/api/report": {"1.0": ROUTES["/api/report"], "2.0": "report_v2_sample.json"},
}
DELAY_MS = 0


class Handler(BaseHTTPRequestHandler):
    server_version = "MockAPI/1.0"

    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        request = urlparse(self.path)
        path = request.path.rstrip("/") or "/"
        if DELAY_MS:
            time.sleep(DELAY_MS / 1000.0)
        if path == "/api/health":
            self._send({"ok": True, "schema_version": "1.0", "mode": "mock"})
            return
        sample = ROUTES.get(path)
        if path in VERSIONED_SAMPLES:
            choices = VERSIONED_SAMPLES[path]
            versions = parse_qs(request.query, keep_blank_values=True).get("version", ["1.0"])
            if len(versions) != 1 or versions[0] not in choices:
                self._send({"error": f"unsupported_{path.rsplit('/', 1)[-1]}_version",
                            "supported_versions": list(choices)}, status=400)
                return
            sample = choices[versions[0]]
        if not sample:
            self._send({"error": "not_found", "path": path,
                        "available": ["/api/health"] + sorted(ROUTES)}, status=404)
            return
        with open(os.path.join(SAMPLES, sample), encoding="utf-8") as f:
            self._send(json.load(f))

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        print("[mock] " + fmt % args)


def make_server(port=8000, delay_ms=0):
    global DELAY_MS
    DELAY_MS = delay_ms
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--delay", type=int, default=0, help="milliseconds of fake latency")
    args = parser.parse_args()
    httpd = make_server(args.port, args.delay)
    print("mock API on http://127.0.0.1:%d  (Ctrl+C to stop)" % args.port)
    for path in ["/api/health"] + sorted(ROUTES):
        print("  GET " + path)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
