"""Serve one completed pipeline report and its page on loopback."""

from __future__ import annotations

import json
import copy
import shutil
import re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse
from uuid import uuid4

from contracts.validate_contract import load_json, validate_document
from src.ai_analysis import AnalysisError, analyze_report
from src.p4_agent.planner import evaluate_candidate, generate_plan
from src.p4_agent.run import run_agent
from src.p4_agent.report import build_report
from src.p4_agent.risk_context import normalized_context
from src.p4_agent.evidence import load_rules


WEB = Path(__file__).resolve().parent / "p5_web"
STATIC = {"/live": ("server_app.html", "text/html"), "/dashboard.css": ("dashboard.css", "text/css"),
          "/dashboard.js": ("dashboard.js", "text/javascript"),
          "/page_navigation.js": ("page_navigation.js", "text/javascript"),
          "/page_navigation.css": ("page_navigation.css", "text/css"),
          "/theme_unified.css": ("theme_unified.css", "text/css"),
          "/professional_analysis.js": ("professional_analysis.js", "text/javascript"),
          "/professional_analysis.css": ("professional_analysis.css", "text/css"),
          "/training_review.js": ("training_review.js", "text/javascript"),
          "/readability.js": ("readability.js", "text/javascript"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/icon.svg": ("icon.svg", "image/svg+xml"),
          "/icon-192.png": ("icon-192.png", "image/png"),
          "/icon-512.png": ("icon-512.png", "image/png"),
          "/sw.js": ("sw.js", "text/javascript")}
MAX_REQUEST = 4 * 1024 * 1024
COUNT_KEYS = ("input_rows", "accepted_rows", "skipped_rows", "incomplete_rows", "device_anomaly_rows")


def report_handler(report_path: Path, *, on_run=None) -> type[BaseHTTPRequestHandler]:
    current = (report_path.resolve(), uuid4().hex)
    run_lock = Lock()
    history_dir = report_path.resolve().parent.parent

    # Only the currently imported input is retained in memory to resume follow-ups.
    upload_id = None
    active_upload = None

    def source_kind(path: Path) -> str:
        try:
            kind = load_json(path.with_name("source.json"))["kind"]
            return kind if kind in ("demo", "csv") else "unknown"
        except (OSError, ValueError, KeyError, TypeError):
            return "unknown"

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
                             "style-src 'self'; connect-src 'self'; worker-src 'self'; "
                             "manifest-src 'self'; base-uri 'none'; "
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
            elif path == "/sample.csv":
                sample = WEB.parents[1] / "data" / "sample" / "demo_activity.csv"
                self.send_data(200, sample.read_bytes(), "text/csv; charset=utf-8")
            elif path == "/api/history":
                self.send_history_list()
            elif path == "/api/r15-review":
                self.send_r15_review_status()
            elif re.fullmatch(r"/api/history/run-[A-Za-z0-9_-]{8,75}", path):
                self.send_history_report(path.rsplit("/", 1)[-1])
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

        def history_path(self, identifier: str) -> Path:
            if not re.fullmatch(r"run-[A-Za-z0-9_-]{8,75}", identifier):
                raise ValueError("invalid history identifier")
            directory = (history_dir / identifier).resolve()
            if directory.parent != history_dir.resolve():
                raise ValueError("invalid history path")
            return directory / "report.json"

        def send_history_list(self) -> None:
            results = []
            try:
                directories = sorted((p for p in history_dir.glob("run-*") if p.is_dir()),
                                     key=lambda p: p.name, reverse=True)[:60]
                for directory in directories:
                    if len(results) >= 18:
                        break
                    try:
                        report = get_report(self.history_path(directory.name))
                        results.append({"id": directory.name,
                                        "generated_at": report["generated_at"],
                                        "window_end": report["metrics"]["window"]["end"],
                                        "source": source_kind(directory / "report.json"),
                                        "sessions": (report.get("running") or {}).get("week", {}).get("sessions"),
                                        "status": report["plan"]["status"]})
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
            except OSError:
                pass
            self.send_json(200, {"reports": results})

        def send_history_report(self, identifier: str) -> None:
            try:
                path = self.history_path(identifier)
                report = get_report(path)
                quality = get_summary(path)
            except (OSError, ValueError, KeyError, TypeError):
                self.send_json(404, {"error": "history_missing", "message": "找不到已验证的历史报告。"})
                return
            self.send_json(200, {"report": report, "import_quality": quality})

        def send_report(self, route: str) -> None:
            path, report_id = current
            try:
                report = get_report(path)
                if route == "/api/snapshot":
                    report = {"report": report, "import_quality": get_summary(path), "report_id": report_id,
                              "source": source_kind(path), "can_answer": report_id == upload_id,
                              "can_supplement": report_id == upload_id}
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
            if route not in ("/api/run", "/api/ai", "/api/ask", "/api/replan", "/api/r15-review") or (route in ("/api/run", "/api/replan", "/api/r15-review") and on_run is None):
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
            if not 0 < size <= (4096 if route in ("/api/ai", "/api/ask", "/api/replan", "/api/r15-review") else MAX_REQUEST):
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
            if route in ("/api/ai", "/api/ask"):
                self.send_analysis(payload, ask=route == "/api/ask")
            elif route == "/api/replan":
                self.replan_report(payload)
            elif route == "/api/r15-review":
                self.review_r15(payload)
            else:
                self.run_report(payload)

        def pain_sources(self, path: Path, report: dict) -> dict:
            athlete = report["athlete_id"]
            context_path = path.with_name("context.json")
            if not context_path.is_file():
                return {"available": False, "csv_pain": None, "context_pain": None,
                        "message": "该报告生成于升级前，缺少可复算的原始上下文。请重新上传原 CSV 和补充资料。"}
            context = normalized_context(load_json(context_path), athlete)
            activity_path = path.with_name("activity.json")
            activity = load_json(activity_path)
            if validate_document(activity_path, activity):
                raise ValueError("原始活动未通过校验")
            if activity.get("athlete_id") != athlete:
                raise ValueError("活动与报告 ID 不一致")
            start = (datetime.fromisoformat(report["metrics"]["window"]["end"]).date() - timedelta(days=6)).isoformat()
            end = report["metrics"]["window"]["end"]
            csv_pain = any(start <= item.get("date", "") <= end and
                           isinstance(item.get("pain"), str) and bool(item["pain"].strip())
                           for item in activity.get("activities", []))
            return {"available": True, "csv_pain": csv_pain,
                    "context_pain": context.get("pain_reported"),
                    "message": "近期 CSV 存在疼痛记录" if csv_pain else "近期 CSV 未发现疼痛字段记录"}

        def send_r15_review_status(self) -> None:
            path, report_id = current
            try:
                report = get_report(path)
                sources = self.pain_sources(path, report)
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                self.send_json(503, {"error": "review_unavailable", "message": "无法读取疼痛记录来源。"})
                return
            self.send_json(200, {"report_id": report_id, **sources})

        def review_r15(self, payload) -> None:
            nonlocal current, active_upload, upload_id
            if (not isinstance(payload, dict) or set(payload) != {"report_id", "choice", "confirmed"}
                    or not isinstance(payload.get("report_id"), str)
                    or payload.get("choice") not in ("pain_present", "context_record_incorrect")
                    or payload.get("confirmed") is not True):
                self.send_json(400, {"error": "invalid_review", "message": "请选择真实情况并勾选确认。"})
                return
            if not run_lock.acquire(blocking=False):
                self.send_json(409, {"error": "run_in_progress", "message": "另一个任务正在运行。"})
                return
            try:
                path, active_id = current
                if payload["report_id"] != active_id:
                    self.send_json(409, {"error": "stale_report", "message": "报告已更新，请重新加载后再确认。"})
                    return
                try:
                    old_report = get_report(path)
                    r15 = next((risk for risk in old_report["risks"] if risk["rule_id"] == "R15"), None)
                    if r15 is None:
                        raise ValueError("当前报告没有已触发的 R15 疼痛提醒。")
                    source = self.pain_sources(path, old_report)
                    context = None
                    if not source["available"]:
                        if payload["choice"] != "pain_present":
                            raise ValueError(source["message"] + "如资料有误，请重新导入原始文件。")
                        # Legacy reports did not retain review context. They can
                        # record a true-positive acknowledgement, never a clearance.
                        plan = copy.deepcopy(old_report["plan"])
                        new_report = copy.deepcopy(old_report)
                        status_text = "已确认疼痛记录属实；原有 R15 风险和计划暂停状态均保留。旧报告缺少上下文，未重新计算。"
                    else:
                        if payload["choice"] == "context_record_incorrect" and source["csv_pain"]:
                            raise ValueError("原始 CSV 最近 7 天仍记录了疼痛。请先更正错误的 CSV 记录后重新导入；不能用按钮覆盖运动记录。")
                        if payload["choice"] == "context_record_incorrect" and source["context_pain"] is not True:
                            raise ValueError("原始上下文没有已确认的疼痛标记。如 CSV 记录有误，请更正 CSV 并重新导入。")
                        context = load_json(path.with_name("context.json"))
                        context["pain_reported"] = payload["choice"] == "pain_present"
                        metrics = load_json(path.with_name("metrics.json"))
                        activity = load_json(path.with_name("activity.json"))
                        for name, document in (("metrics.json", metrics), ("activity.json", activity)):
                            if validate_document(path.with_name(name), document):
                                raise ValueError(f"{name} 未通过校验，无法重新评估")
                        rules = load_rules()
                        assessment = run_agent(metrics, activities=activity, context=context, rules=rules)
                        plan = generate_plan(metrics, assessment, rules, activities=activity, context=context)
                        now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()
                        new_report = build_report(metrics, assessment, plan, rules, generated_at=now,
                                                  running=old_report.get("running"))
                        status_text = ("已确认近期存在疼痛；R15 提醒保留，下周训练安排仍需人工复核。"
                                       if payload["choice"] == "pain_present" else
                                       "已更正原上下文中的疼痛误填，重新执行全部规则；其他条件不满足时仍不会生成七日计划。")
                    new_report["generated_at"] = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()
                    new_report["agent_trace"].append({"step": len(new_report["agent_trace"]) + 1,
                                                      "tool": "check_risk", "status": "ok", "notes": status_text})
                    new_report["disclaimers"].append("R15 手动核对记录：" + status_text)
                    if (validate_document(path.with_name("plan.json"), plan)
                            or validate_document(path, new_report)):
                        raise ValueError("复核结果未通过报告校验，旧报告保留。")
                    directory = history_dir / f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:12]}"
                    directory.mkdir(parents=True, exist_ok=False)
                    if path.with_name("source.json").is_file():
                        shutil.copy2(path.with_name("source.json"), directory / "source.json")
                    for name in ("metrics.json", "activity.json", "import_quality.json"):
                        shutil.copy2(path.with_name(name), directory / name)
                    outputs = [("plan.json", plan), ("report.json", new_report)]
                    if context is not None:
                        outputs.insert(0, ("context.json", context))
                    for name, document in outputs:
                        (directory / name).write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                                                  allow_nan=False) + "\n", encoding="utf-8")
                    summary = get_summary(directory / "report.json")
                except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
                    self.send_json(422, {"error": "review_failed", "message": str(exc)})
                    return
                new_id = uuid4().hex
                current = (directory / "report.json", new_id)
                if active_upload is not None and upload_id == active_id and context is not None:
                    # Resume with the observations just validated by run_agent.
                    # Previously answered fields are already in the saved context.
                    active_upload = {**active_upload, "context": context, "answers": {}}
                    upload_id = new_id
                self.send_json(200, {"source": source_kind(current[0]), "can_answer": upload_id == new_id,
                                     "can_supplement": upload_id == new_id,
                                     "report": new_report, "import_quality": summary,
                                     "report_id": new_id, "message": status_text})
            finally:
                run_lock.release()

        def send_analysis(self, payload, *, ask=False):
            path, report_id = current
            if not isinstance(payload, dict) or set(payload) != ({"report_id", "api_key", "base_url", "model", "question"} if ask else {"report_id", "api_key", "base_url", "model"}):
                self.send_json(400, {"error": "invalid_analysis_request", "message": "AI 连接参数不完整。"})
                return
            if payload["report_id"] != report_id:
                self.send_json(409, {"error": "stale_report", "message": "本机报告已更新，请刷新页面后再分析。"})
                return
            try:
                analysis = analyze_report(get_report(path), payload, question=payload["question"] if ask else None)
            except AnalysisError as exc:
                self.send_json(exc.status, {"error": "ai_failed", "message": str(exc)})
                return
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                self.send_json(503, {"error": "report_unavailable", "message": "本次报告无法读取或未通过校验。"})
                return
            self.send_json(200, {"report_id": report_id, "analysis": analysis})

        def replan_report(self, payload):
            nonlocal current
            if (not isinstance(payload, dict) or set(payload) != {"report_id", "first_date", "second_date"}
                    or not all(isinstance(payload[key], str) for key in payload)):
                self.send_json(400, {"error": "invalid_swap", "message": "调整请求格式无效。"})
                return
            if not run_lock.acquire(blocking=False):
                self.send_json(409, {"error": "run_in_progress", "message": "另一个报告任务正在运行。"})
                return
            try:
                old_path, active_id = current
                if payload["report_id"] != active_id:
                    self.send_json(409, {"error": "stale_report", "message": "请先刷新当前报告。"})
                    return
                try:
                    report = copy.deepcopy(get_report(old_path))
                    plan = report["plan"]
                    if plan["status"] != "draft" or not plan["self_check"]["passed"]:
                        raise ValueError("当前报告没有通过自检的可调整草案。")
                    days = plan["days"]
                    positions = {d["date"]: i for i, d in enumerate(days)}
                    first, second = payload["first_date"], payload["second_date"]
                    if first == second or first not in positions or second not in positions:
                        raise ValueError("需要两个不同且存在于草案中的日期。")
                    i, j = positions[first], positions[second]
                    a, b = days[i], days[j]
                    days[i], days[j] = ({**b, "date": first}, {**a, "date": second})
                    rules = load_rules()
                    planned, checks, missing = evaluate_candidate(days, report["metrics"],
                                                                      plan["baseline_trimp"], rules)
                    if missing or not all(item["passed"] for item in checks):
                        failed = ", ".join(x["code"] for x in checks if not x["passed"])
                        raise ValueError(f"本次交换未通过规则自检（{failed}），原计划保持不变。")
                    for day, load in zip(days, planned, strict=True):
                        day["planned_trimp"] = load
                    total = round(sum(planned), 6)
                    plan["weekly_targets"]["load_target_trimp"] = total
                    plan["self_check"] = {"passed": True, "checks": checks}
                    plan["adjustments"].append({"rule_id": "R20", "reason": "使用者提出整天训练日期互换请求。",
                                                "action": f"交换 {first} 与 {second}，服务端重新验证 R19、R20。"})
                    report["agent_trace"].append({"step": len(report["agent_trace"]) + 1,
                                                   "tool": "generate_plan", "status": "ok",
                                                   "notes": "日期交换后已重新验证 R19 和 R20；仍需人工确认。"})
                    report["disclaimers"].append("本报告含经过 R19/R20 重新校验的日期互换；未评估新的伤病与即时恢复状态，需人工复核。")
                    report["generated_at"] = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()
                    plan_path = old_path.with_name("plan.json")
                    if validate_document(plan_path, plan) or validate_document(old_path, report):
                        raise ValueError("调整结果未通过报告契约校验，原计划保持不变。")
                    directory = history_dir / f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:12]}"
                    directory.mkdir(parents=True, exist_ok=False)
                    for filename in ("metrics.json", "activity.json", "import_quality.json", "source.json", "context.json"):
                        source = old_path.with_name(filename)
                        if source.is_file():
                            shutil.copy2(source, directory / filename)
                    for name, data in (("plan.json", plan), ("report.json", report)):
                        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                                                  allow_nan=False) + "\n", encoding="utf-8")
                    summary = get_summary(directory / "report.json")
                except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
                    self.send_json(422, {"error": "replan_failed", "message": str(exc)})
                    return
                new_id = uuid4().hex
                current = (directory / "report.json", new_id)
                self.send_json(200, {"source": source_kind(current[0]), "report": report, "import_quality": summary, "report_id": new_id})
            finally:
                run_lock.release()

        def run_report(self, payload):
            nonlocal current, active_upload, upload_id
            if not run_lock.acquire(blocking=False):
                self.send_json(409, {"error": "run_in_progress", "message": "已有导入任务正在运行。"})
                return
            try:
                try:
                    if isinstance(payload, dict) and payload.get("mode") in ("followup", "supplement"):
                        if (active_upload is None or upload_id != current[1]
                                or payload.get("report_id") != upload_id):
                            self.send_json(409, {"error": "stale_report", "message": "请刷新并核对当前报告。"})
                            return
                        if payload["mode"] == "supplement":
                            patch = payload.get("options")
                            if not isinstance(patch, dict) or set(patch) - {
                                    "resting_hr", "max_hr", "trimp_profile", "history_start"}:
                                raise ValueError("请选择有效的计算参数。")
                            updated = {**active_upload, "options": {**active_upload["options"], **patch}}
                            if payload.get("measurements") is not None:
                                updated["measurements"] = payload["measurements"]
                            readings = payload.get("daily_resting_hr", {})
                            if not isinstance(readings, dict) or len(readings) > 28:
                                raise ValueError("请选择报告窗口内的量测日期。")
                            if readings:
                                window = get_report(current[0])["metrics"]["window"]
                                measurements = dict(updated.get("measurements") or {})
                                daily = {row["date"]: row for row in measurements.get("daily", [])}
                                for day, value in readings.items():
                                    if (not window["start"] <= day <= window["end"]
                                            or type(value) is not int or not 30 <= value <= 110):
                                        raise ValueError("请填写报告窗口内的有效静息心率。")
                                    daily[day] = {**daily.get(day, {}), "date": day, "resting_hr_bpm": value}
                                measurements.update(athlete_id=active_upload["options"].get("athlete", "anon_01"),
                                                    daily=list(daily.values()))
                                updated["measurements"] = measurements
                            payload = updated
                        else:
                            answers = payload.get("answers")
                            if not isinstance(answers, dict) or not answers:
                                raise ValueError("请填写本轮追问。")
                            keys = {q["key"] for q in get_report(current[0]).get("questions", [])}
                            if set(answers) - keys:
                                raise ValueError("请仅填写当前报告列出的追问。")
                            payload = {**active_upload, "answers": {**active_upload.get("answers", {}), **answers}}
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
                active_upload = payload if payload.get("mode") == "csv" else None
                upload_id = report_id if active_upload is not None else None
                current = (path, report_id)
                self.send_json(200, {"source": source_kind(path), "can_answer": active_upload is not None,
                                     "can_supplement": active_upload is not None,
                                     "report": report, "import_quality": summary, "report_id": report_id})
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
