"""Build and check a conservative weekly draft, or withhold its schedule."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from contracts.validate_contract import PLAN_RULES_BY_KIND
from src.p3_metrics.compute import trimp
from src.p4_agent.evidence import lookup_evidence
from src.p4_agent.risk_context import as_number, iso_day


PLAN_VERSION = "2.0"
MAX_REPLANS = 2


def next_week(as_of: date) -> list[str]:
    start = as_of + timedelta(days=7 - as_of.weekday())
    return [(start + timedelta(days=offset)).isoformat() for offset in range(7)]


def rest_day(day: str) -> dict:
    return {"date": day, "kind": "rest", "duration_s": 0, "distance_m": 0,
            "reference_avg_hr_bpm": None, "rules": ["R09"]}


def candidate_days(document: dict, athlete_id: str, week: list[str]) -> list[dict]:
    if not isinstance(document, dict) or set(document) != {"athlete_id", "days"} or document["athlete_id"] != athlete_id:
        raise ValueError("候选计划需含相同的 athlete_id 和 days")
    days = document["days"]
    if not isinstance(days, list) or len(days) != 7:
        raise ValueError("候选计划需要下周的 7 个日期")
    keys = {"date", "kind", "duration_s", "distance_m", "reference_avg_hr_bpm", "rules"}
    for item in days:
        if not isinstance(item, dict) or set(item) != keys or item["kind"] not in PLAN_RULES_BY_KIND:
            raise ValueError("候选计划仅支持字段完整的 easy 和 rest 条目")
        seconds, distance, hr = item["duration_s"], as_number(item["distance_m"]), item["reference_avg_hr_bpm"]
        tags = item["rules"]
        if (type(seconds) is not int or not 0 <= seconds <= 24000
                or distance is None or not 0 <= distance <= 100000
                or not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
            raise ValueError("候选计划的时长、距离或依据字段无效")
        if item["kind"] == "rest":
            if seconds or distance or hr is not None:
                raise ValueError("休息日须为零时长和零距离")
        elif seconds == 0 or distance == 0 or type(hr) is not int:
            raise ValueError("轻松日需要正数时长、距离和整数参考心率")
    if [item["date"] for item in days] != week:
        raise ValueError("候选计划日期必须与下周日期一致并按时间排列")
    return [dict(item) for item in days]


def draft_from_history(week: list[str], as_of: date, activities: dict | None, context: dict | None) -> list[dict]:
    recent = defaultdict(list)
    for item in (activities or {}).get("activities", []):
        recent[item["date"]].append(item)
    tags = (context or {}).get("session_types") or {}
    days = []
    for offset, day in enumerate(week):
        prior_day = (as_of - timedelta(days=6 - offset)).isoformat()
        items = recent[prior_day]
        slot = rest_day(day)
        if tags.get(prior_day) == ["easy"] and len(items) == 1:
            item = items[0]
            if item["sport"] == "run" and not item.get("device_anomaly") and item["distance_m"] > 0:
                slot = {"date": day, "kind": "easy", "duration_s": item["duration_s"],
                        "distance_m": item["distance_m"], "reference_avg_hr_bpm": item["avg_hr"],
                        "rules": ["R04", "R05"]}
        days.append(slot)
    return days


def day_load(day: dict, inputs: dict) -> float:
    if day["kind"] == "rest":
        return 0.0
    return round(trimp(day["duration_s"], day["reference_avg_hr_bpm"],
                       resting_hr=inputs["resting_hr"], max_hr=inputs["max_hr"], profile=inputs["profile"]), 6)


def evaluate_candidate(days: list[dict], metrics: dict, baseline: float,
                       rules: dict[str, dict]) -> tuple[list[float], list[dict], set[str]]:
    planned = [day_load(day, metrics["load_inputs"]) for day in days]
    total = round(sum(planned), 6)
    limit_pct = rules["R19"]["threshold"]
    if as_number(limit_pct) is None or limit_pct < 0:
        raise ValueError("R19 增幅阈值无效")
    limit = round(baseline * (1 + limit_pct), 6)
    unproven = {day["date"] for day in days if not day["rules"] or
                any(tag not in PLAN_RULES_BY_KIND[day["kind"]] or lookup_evidence(tag, rules) is None
                    for tag in day["rules"])}
    coverage = f"{len(days) - len(unproven)}/{len(days)} 日有适用的规则依据。"
    if unproven:
        coverage += " 待处理日期 " + "、".join(sorted(unproven))
    checks = [
        {"code": "R19", "passed": total <= limit,
         "detail": f"按每日参考心率复算 {total:.2f} TRIMP，本周 {baseline:.2f}，项目上限 {limit:.2f}。"},
        {"code": "R20", "passed": not unproven, "detail": coverage},
    ]
    return planned, checks, unproven


def reduce_to_baseline(days: list[dict], metrics: dict, baseline: float) -> list[dict]:
    total = sum(day_load(day, metrics["load_inputs"]) for day in days)
    if total <= baseline:
        return days
    ratio = baseline / total
    reduced = []
    for day in days:
        seconds = math.floor(day["duration_s"] * ratio)
        if not seconds:
            reduced.append(rest_day(day["date"]))
        else:
            distance = round(day["distance_m"] * seconds / day["duration_s"], 2)
            reduced.append({**day, "duration_s": seconds, "distance_m": distance}
                           if distance else rest_day(day["date"]))
    return reduced


def generate_plan(metrics: dict, assessment: dict, rules: dict[str, dict], *, activities: dict | None = None,
                  context: dict | None = None, candidate: dict | None = None) -> dict:
    athlete_id = metrics["athlete_id"]
    as_of = iso_day(metrics["window"]["end"])
    week = next_week(as_of)
    baseline = as_number(metrics["load"]["trimp_week"])
    attempts = []
    adjustments = []
    common = {"schema_version": PLAN_VERSION, "athlete_id": athlete_id, "week_start": week[0],
              "baseline_trimp": baseline, "attempts": attempts, "adjustments": adjustments}

    def withheld(status: str, reasons: list[str]) -> dict:
        final_checks = attempts[-1]["checks"] if attempts else []
        return {**common, "status": status, "hold_reasons": reasons, "days": [], "weekly_targets": None,
                "self_check": {"passed": False, "checks": final_checks}}

    if assessment["status"] == "hold_for_review":
        codes = "、".join(assessment["planning_gate"]["rule_ids"])
        return withheld("hold_for_review", [f"规则评估需要人工复核。{codes}"])
    if assessment["status"] == "awaiting_input":
        return withheld("awaiting_input", ["规则评估仍有追问待答。"])
    if any(item["code"] == "P2_IMPORT_PARTIAL" for item in metrics["flags"]):
        return withheld("awaiting_input", ["本次导入有被丢弃或旁路的活动，请复核记录完整性。"])
    if any(lookup_evidence(code, rules) is None for code in ("R19", "R20")):
        return withheld("hold_for_review", ["计划自检规则缺少依据。"])
    states = {item["rule_id"]: item["status"] for item in assessment["checks"]}
    resting_days = next(item["observed"]["daily_bpm"] for item in assessment["checks"] if item["rule_id"] == "R11")
    resting_complete = all(value is not None for value in resting_days.values()) and metrics["recovery"]["resting_hr_delta"] is not None
    if (baseline is None or baseline <= 0 or states.get("R05") != "triggered"
            or states.get("R11") != "not_triggered" or not resting_complete):
        return withheld("awaiting_input", ["草案需要非零的周负荷、可复核的参考区间和完整的静息心率判断。"])
    if any(states.get(code) == "triggered" for code in ("R02", "R08", "R09", "R14", "R16", "R17")):
        return withheld("hold_for_review", ["近期训练或恢复信号需先人工复核。"])

    days = (candidate_days(candidate, athlete_id, week) if candidate is not None
            else draft_from_history(week, as_of, activities, context))
    if not any(day["kind"] == "easy" for day in days):
        return withheld("awaiting_input", ["缺少已确认的近期轻松跑或可供复核的草案活动。"])

    for attempt in range(MAX_REPLANS + 1):
        planned, checks, unproven = evaluate_candidate(days, metrics, baseline, rules)
        attempts.append({"round": attempt + 1, "planned_trimp": round(sum(planned), 6), "checks": checks})
        if all(item["passed"] for item in checks):
            rows = [{**day, "planned_trimp": load, "duration_min": round(day["duration_s"] / 60, 6),
                     "target_pace_s_per_km": None} for day, load in zip(days, planned, strict=True)]
            return {**common, "status": "draft", "hold_reasons": [], "days": rows,
                    "weekly_targets": {"load_target_trimp": attempts[-1]["planned_trimp"],
                                       "sessions": sum(day["kind"] != "rest" for day in days)},
                    "self_check": {"passed": True, "checks": checks}}
        if attempt == MAX_REPLANS:
            break
        if unproven:
            days = [rest_day(day["date"]) if day["date"] in unproven else day for day in days]
            adjustments.append({"rule_id": "R20", "reason": "有日期缺少适用的规则依据。",
                                "action": "移除无依据的活动，留空为休息日供复核。"})
        if not checks[0]["passed"]:
            days = reduce_to_baseline(days, metrics, baseline)
            adjustments.append({"rule_id": "R19", "reason": "按参考心率复算超过项目增幅上限。",
                                "action": "重新计算保留活动的负荷，必要时缩短时长。"})
    return withheld("hold_for_review", ["草案自检重排后仍未通过。"])
