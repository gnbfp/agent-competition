"""Request an explanation of a completed report from a compatible AI provider."""

from __future__ import annotations

import json
import re
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.p4_agent.evidence import load_rules


MAX_RESPONSE = 128 * 1024
PROMPT = (
    "你是跑步训练报告解读助手。仅依据提供的结构化数据，用简体中文分三段说明："
    "负荷指标、触发规则和计划状态、需要补充的信息。指标缺失时说明数据不足，"
    "对 ACWR 两种口径分别说明，不把项目阈值当作伤病诊断。"
    "引用数据中已有的规则编号，不编造数据、阈值或出处。保持原计划状态，"
    "尤其在需要人工复核或待补数据时不要建议具体训练安排。"
    "不要提供医疗诊断或处方。控制在约 300 字以内。"
)


class AnalysisError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def connection_options(payload: dict) -> tuple[str, str, str]:
    key, base, model = (payload.get(name) for name in ("api_key", "base_url", "model"))
    if not isinstance(key, str) or not re.fullmatch(r"[\x21-\x7e]{1,512}", key):
        raise AnalysisError(400, "请输入有效的 API 密钥。")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", model):
        raise AnalysisError(400, "请输入服务商提供的模型名称。")
    if not isinstance(base, str) or len(base) > 512 or re.search(r"[\s\\]", base):
        raise AnalysisError(400, "请输入有效的 HTTPS API 基础地址。")
    try:
        url = urlsplit(base)
        port = url.port
    except ValueError:
        raise AnalysisError(400, "请输入有效的 HTTPS API 基础地址。") from None
    if (url.scheme != "https" or not url.hostname or "@" in url.netloc
            or url.query or url.fragment or (port is not None and port == 0)
            or not re.fullmatch(r"[A-Za-z0-9._/-]*", url.path)):
        raise AnalysisError(400, "请输入有效的 HTTPS API 基础地址。")
    path = url.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urlunsplit((url.scheme, url.netloc, path, "", "")), model, key


def report_summary(report: dict) -> dict:
    metrics = report["metrics"]
    load = metrics["load"]
    rules = load_rules()
    week = (report.get("running") or {}).get("week") or {}
    known = week.get("coverage_confirmed") or (week.get("sessions") or 0) > 0
    return {
        "recorded_running_week": {key: week.get(key) if known else None for key in
                                  ("sessions", "distance_km", "duration_min", "average_pace_s_per_km", "average_hr_bpm")},
        "week_coverage_confirmed": week.get("coverage_confirmed") is True,
        "window_days": metrics["window"]["days"],
        "load": {key: load[key] for key in (
            "trimp_week", "acwr_rolling", "acwr_ewma", "acwr_status", "week_load_change_pct"
        )},
        "load_days_available": sum(item["trimp"] is not None for item in load["trimp_daily"]),
        "data_flags": [flag["code"] for flag in metrics["flags"]
                       if re.fullmatch(r"[A-Z0-9_]{1,64}", flag["code"])],
        "risk_signals": [{"rule_id": risk["rule_id"], "level": risk["level"],
                          "clause": rules[risk["rule_id"]]["clause"]}
                         for risk in report["risks"] if risk["rule_id"] in rules],
        "plan_status": report["plan"]["status"],
        "planning_checks": [[{"code": item["code"], "passed": item["passed"]}
                             for item in attempt["checks"]] for attempt in report["plan"]["attempts"]],
        "pending_rules": sorted({item["rule_id"] for item in report["questions"] if item["rule_id"] in rules}),
    }


def analyze_report(report: dict, payload: dict, *, question: str | None = None) -> str:
    endpoint, model, key = connection_options(payload)
    if question is not None and (not isinstance(question, str) or not question.strip() or len(question) > 250):
        raise AnalysisError(400, "追问内容应为 1–250 个字符。")
    # Compatible providers use max_tokens. OpenAI has moved to max_completion_tokens.
    token_option = "max_completion_tokens" if urlsplit(endpoint).hostname == "api.openai.com" else "max_tokens"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT if question is None else (
                "你是训练报告问答助手。只根据输入的结构化报告回答用户提出的一条问题。"
                "拒绝编造数据和规则，缺数据时明确说不足；不要提供医疗诊断、处方，"
                "不要更改当前计划状态，必要时建议人工复核。150 字内。")},
            {"role": "user", "content": json.dumps(report_summary(report), ensure_ascii=False, allow_nan=False)
             if question is None else json.dumps({"report": report_summary(report),
                                                "question": question.strip()}, ensure_ascii=False, allow_nan=False)},
        ],
        token_option: 1600,
    }
    request = Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise AnalysisError(502, "AI 服务返回内容过大。")
        content = json.loads(raw)["choices"][0]["message"]["content"]
    except HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise AnalysisError(401, "AI 服务拒绝授权，请核对 API 密钥和模型权限。") from None
        if exc.code == 429:
            raise AnalysisError(429, "AI 服务限流或额度不足，请稍后再试。") from None
        if exc.code in (400, 404, 422):
            raise AnalysisError(502, "AI 服务拒绝请求，请核对基础地址、模型名称和接口兼容性。") from None
        raise AnalysisError(502, "AI 服务暂不可用，请稍后再试。") from None
    except TimeoutError:
        raise AnalysisError(504, "等待 AI 分析超时，请稍后再试。") from None
    except (URLError, OSError, HTTPException):
        raise AnalysisError(502, "无法连接 AI 服务，请检查网络和基础地址。") from None
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise AnalysisError(502, "AI 服务没有返回可读取的解读。") from None
    if not isinstance(content, str) or not content.strip():
        raise AnalysisError(502, "模型未返回解读，请确认模型支持文本回复。")
    return content.strip().replace(key, "[已隐藏]")[:5000]
