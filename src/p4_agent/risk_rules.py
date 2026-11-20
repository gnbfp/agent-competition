"""Evaluate local project rules using metrics v2 and explicit observations."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from contracts.validate_contract import load_json, validate_file

from .evidence import load_rules, lookup_evidence
from .risk_context import HARD_SESSIONS, as_number, iso_day, normalized_context


REVIEW_ACTIONS = {
    "R01": "核对缺字段或导入明细，补齐后再复算。",
    "R02": "复核心率读数、设备佩戴及导入明细。",
    "R03": "标注估算来源；有可靠记录时补充个人最大心率。",
    "R05": "记录当前负荷区间，与主诉和其他观测一起复核。",
    "R06": "复核负荷和数据完整性，请本人或教练确认后续安排。",
    "R07": "核对近期负荷与记录覆盖，再由本人或教练判断是否调整。",
    "R08": "复核跑量数据和比较窗口，请本人或教练确认安排。",
    "R09": "复核连续强度课记录与恢复安排。",
    "R10": "复核单次距离与当周跑量的占比。",
    "R11": "核对连续静息心率、测量条件和主诉，再确认后续安排。",
    "R12": "复核分段心率、配速和当日条件。",
    "R13": "保留估算范围，核查最大心率来源及赛绩。",
    "R14": "复核对照训练的配速、环境和心率。",
    "R15": "暂停自动生成训练计划，请本人确认情况；若疼痛持续或加重，咨询医疗专业人员。",
    "R16": "复核连续睡眠记录与恢复情况。",
    "R17": "核查计划场地的实际天气，由本人或教练确认安排。",
    "R18": "确认目标赛事日期与后续安排。",
}
REVIEW_TITLES = {
    "R05": "ACWR 位于项目参考区间",
    "R06": "ACWR 超过项目关注阈值",
    "R07": "ACWR 低于项目参考区间",
    "R11": "静息心率连续偏离个人基线",
}
PACE_MATCH_SECONDS = 5


class Assessment:
    def __init__(self, rules: dict[str, dict], *, allow_missing_evidence: bool = False):
        self.rules = rules
        self.allow_missing_evidence = allow_missing_evidence
        self.checks: list[dict] = []
        self.risks: list[dict] = []

    def threshold(self, rule_id: str):
        return self.rules[rule_id]["threshold"]

    def add(self, rule_id: str, condition: bool | None, observed: dict,
            missing: tuple[str, ...] = ()) -> None:
        rule = self.rules[rule_id]
        evidence = lookup_evidence(rule_id, self.rules)
        if evidence is None and not self.allow_missing_evidence:
            raise ValueError(f"{rule_id} 缺少可回查的规则依据")
        if rule["kind"] == "compute":
            status = "not_applicable"
        elif condition is None:
            status = "insufficient_data"
        else:
            status = "triggered" if condition else "not_triggered"
        self.checks.append({"rule_id": rule_id, "status": status, "observed": observed,
                            "missing_data": list(missing) if condition is None else [],
                            "evidence": evidence})
        if status == "triggered":
            self.risks.append({
                "rule_id": rule_id, "level": rule["level"], "category": rule["category"],
                "title": REVIEW_TITLES.get(rule_id, rule["title"]),
                "evidence": evidence, "action": REVIEW_ACTIONS[rule_id],
            })


def any_observed(*conditions: bool | None) -> bool | None:
    if any(condition is True for condition in conditions):
        return True
    return None if None in conditions else False


def dates_ending(day: date, count: int) -> list[date]:
    return [day - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


def data_checks(result: Assessment, metrics: dict, activities: list[dict] | None,
                answers: dict, day: date) -> None:
    quality = answers.get("import_quality") or {}
    start = iso_day(metrics["window"]["start"])
    sample = [item for item in activities or [] if start <= item["_day"] <= day]
    required = ("duration_s", "distance_m", "avg_hr", "max_hr")
    incomplete = [{"activity_id": item["activity_id"],
                   "fields": [key for key in required if as_number(item.get(key)) is None]}
                  for item in sample if any(as_number(item.get(key)) is None for key in required)]
    imported = quality.get("incomplete_rows")
    condition = any_observed(bool(incomplete), imported > 0 if imported is not None else None)
    result.add("R01", condition, {"incomplete_activities": incomplete, "import_incomplete_rows": imported},
               ("活动记录或导入缺字段计数",))

    bounds = result.threshold("R02")["resting_hr_bpm"]
    daily = metrics["recovery"]["daily"]
    current = next((item for item in daily if item["date"] == day.isoformat()), {})
    resting = as_number(current.get("resting_hr_bpm"))
    if resting is None:
        resting = as_number(metrics["load_inputs"]["resting_hr"])
    sanity = []
    for item in sample:
        avg, peak = as_number(item.get("avg_hr")), as_number(item.get("max_hr"))
        if item.get("device_anomaly") or (avg is not None and peak is not None and avg > peak):
            sanity.append({"activity_id": item["activity_id"], "avg_hr": avg, "max_hr": peak})
    bypassed = quality.get("device_anomaly_rows")
    # Complete import counts already cover bypassed rows when no separate activity file is provided.
    activity_signal = bool(sanity)
    condition = any_observed(activity_signal, not bounds[0] <= resting <= bounds[1] if resting is not None else None,
                             bypassed > 0 if bypassed is not None else None)
    result.add("R02", condition, {"resting_hr_bpm": resting, "activity_anomalies": sanity,
                                  "import_device_anomaly_rows": bypassed}, ("导入心率异常计数或静息心率",))

    source = answers.get("max_hr_source")
    result.add("R03", None if source is None else source == "estimated_220_age",
               {"source": source, "max_hr_bpm": metrics["load_inputs"]["max_hr"]},
               ("最大心率的来源",))
    result.add("R04", None, {"load_inputs": metrics["load_inputs"],
                             "trimp_records": len(metrics["activity_trimp"])})


def running_distances(activities: list[dict] | None, start: date, end: date,
                      covered_from: date | None) -> list[int | float] | None:
    if activities is None or covered_from is None or covered_from > start:
        return None
    distances = []
    for item in activities:
        if item.get("sport") != "run" or not start <= item["_day"] <= end:
            continue
        distance = as_number(item.get("distance_m"))
        if item.get("device_anomaly") or distance is None or distance < 0:
            return None
        distances.append(distance)
    return distances


def load_checks(result: Assessment, metrics: dict, activities: list[dict] | None,
                answers: dict, day: date) -> None:
    load = metrics["load"]
    acwr = as_number(load["acwr_ewma"]) if load["acwr_status"] is not None else None
    observations = {"acwr_ewma": load["acwr_ewma"], "acwr_rolling": load["acwr_rolling"],
                    "acwr_status": load["acwr_status"], "window": metrics["window"]}
    lower, upper = result.threshold("R05")
    result.add("R05", lower <= acwr <= upper if acwr is not None else None, observations, ("可分档的 EWMA ACWR",))
    result.add("R06", acwr > result.threshold("R06") if acwr is not None else None, observations, ("可分档的 EWMA ACWR",))
    result.add("R07", acwr < result.threshold("R07") if acwr is not None else None, observations, ("可分档的 EWMA ACWR",))

    covered_from = metrics["load_inputs"]["history_start"]
    coverage = iso_day(covered_from) if covered_from else None
    quality = answers.get("import_quality") or {}
    if any((count or 0) > 0 for count in quality.values()):
        coverage = None  # Bypassed or incomplete rows may hide runs in either window.
    week_start = day - timedelta(days=6)
    current = running_distances(activities, week_start, day, coverage)
    previous = running_distances(activities, day - timedelta(days=34), week_start - timedelta(days=1), coverage)
    current_total = sum(current) if current is not None else None
    prior_average = sum(previous) / 4 if previous is not None else None
    change = (current_total - prior_average) / prior_average if current_total is not None and prior_average else None
    result.add("R08", change > result.threshold("R08") if change is not None else None,
               {"week_distance_m": current_total, "previous_4_week_mean_m": prior_average,
                "increase_pct": round(100 * change, 6) if change is not None else None},
               ("本周及此前四周的完整跑量，且历史周均跑量大于零；若有丢弃或旁路需先复核",))

    sessions = answers.get("session_types") or {}
    dates = [value.isoformat() for value in dates_ending(day, 7)]
    hard = [None if value not in sessions else bool(HARD_SESSIONS.intersection(sessions[value])) for value in dates]
    span = result.threshold("R09")
    candidates = [hard[i:i + span] for i in range(len(hard) - span + 1)]
    condition = any_observed(*(None if None in block and False not in block else all(block) for block in candidates))
    result.add("R09", condition, {"days": dict(zip(dates, hard, strict=True))}, ("最近 7 日的训练类型",))

    longest = max(current, default=0) if current is not None else None
    ratio = longest / current_total if current_total else None
    result.add("R10", ratio > result.threshold("R10") if ratio is not None else None,
               {"longest_run_m": longest, "week_distance_m": current_total, "long_run_ratio": ratio},
               ("本周完整且非零的跑量及单次跑步距离；若有丢弃或旁路需先复核",))


def consecutive(condition_values: list[bool | None]) -> bool | None:
    if False in condition_values:
        return False
    return None if None in condition_values else True


def recent_readings(metrics: dict, day: date, field: str, count: int) -> dict[str, int | float | None]:
    by_date = {item["date"]: as_number(item.get(field)) for item in metrics["recovery"]["daily"]}
    return {value.isoformat(): by_date.get(value.isoformat()) for value in dates_ending(day, count)}


def capacity_and_recovery_checks(result: Assessment, metrics: dict, day: date) -> None:
    recovery = metrics["recovery"]
    baseline = as_number(recovery["resting_hr_baseline"])
    heart_rates = recent_readings(metrics, day, "resting_hr_bpm", 3)
    raised = [value - baseline > result.threshold("R11") if value is not None and baseline is not None
              else None for value in heart_rates.values()]
    result.add("R11", consecutive(raised), {"baseline_bpm": baseline, "daily_bpm": heart_rates},
               ("个人静息心率基线和截止日前连续 3 天的静息心率",))

    drift = as_number(recovery["hr_drift_pct"])
    has_splits = recovery["hr_drift_inputs"] is not None
    result.add("R12", drift > result.threshold("R12") * 100 if drift is not None and has_splits else None,
               {"hr_drift_pct": drift, "splits": recovery["hr_drift_inputs"]},
               ("符合配速要求的分段心率数据",))

    capacity = metrics["capacity"]
    spread = as_number(capacity["max_spread_pct"])
    result.add("R13", spread > result.threshold("R13") * 100 if spread is not None else None,
               {"max_spread_pct": spread, "methods": capacity["methods"],
                "estimate_range": capacity["estimate_range"]}, ("三条有氧估算路径的有效结果",))


def pace_match(activities: list[dict] | None, day: date) -> dict | None:
    by_day = defaultdict(list)
    for item in activities or []:
        if item.get("sport") == "run" and not item.get("device_anomaly"):
            pace = as_number(item.get("avg_pace_s_per_km"))
            hr = as_number(item.get("avg_hr"))
            if pace is not None and hr is not None:
                by_day[item["_day"]].append((pace, hr, item["activity_id"]))
    matches = []
    for current_day in dates_ending(day, 7):
        earlier = current_day - timedelta(days=28)
        for current_pace, current_hr, current_id in by_day.get(current_day, []):
            candidates = [(abs(current_pace - pace), ref_id, pace, hr)
                          for pace, hr, ref_id in by_day.get(earlier, [])
                          if abs(current_pace - pace) <= PACE_MATCH_SECONDS]
            if candidates:
                _, prior_id, prior_pace, prior_hr = min(candidates)
                matches.append({"current_activity_id": current_id, "baseline_activity_id": prior_id,
                                "current_pace_s_per_km": current_pace, "baseline_pace_s_per_km": prior_pace,
                                "current_avg_hr": current_hr, "baseline_avg_hr": prior_hr,
                                "delta_bpm": current_hr - prior_hr})
    return max(matches, key=lambda item: (item["delta_bpm"], item["current_activity_id"]), default=None)


def condition_checks(result: Assessment, metrics: dict, activities: list[dict] | None,
                     answers: dict, day: date) -> None:
    match = pace_match(activities, day)
    result.add("R14", match["delta_bpm"] > result.threshold("R14") if match is not None else None,
               match or {}, ("本周与四周前同一天、配速差不超过 5 秒/公里的两次跑步记录",))

    recent_days = set(dates_ending(day, 7))
    logged_pain = any(isinstance(item.get("pain"), str) and item["pain"].strip()
                      for item in activities or [] if item["_day"] in recent_days)
    pain = answers.get("pain_reported")
    result.add("R15", any_observed(logged_pain, pain),
               {"pain_reported": pain, "recent_activity_reports_pain": logged_pain},
               ("用户明确确认是否有疼痛",))

    sleep = recent_readings(metrics, day, "sleep_h", 2)
    supplied = {key: value for key, value in (answers.get("sleep_readings") or {}).items()
                if key in sleep and sleep[key] is None}
    sleep.update(supplied)
    low_sleep = [value < result.threshold("R16") if value is not None else None for value in sleep.values()]
    result.add("R16", consecutive(low_sleep), {"daily_sleep_h": sleep, "supplemented_dates": list(supplied)},
               ("截止日前连续两天的睡眠记录",))

    environment = answers.get("environment") or {}
    temp, humidity = environment.get("temperature_c"), environment.get("humidity_pct")
    threshold = result.threshold("R17")
    result.add("R17", any_observed(temp > threshold["temp_c"] if temp is not None else None,
                                   humidity > threshold["humidity_pct"] if humidity is not None else None),
               {"temperature_c": temp, "humidity_pct": humidity},
               ("计划地点的气温及相对湿度",))

    target = answers.get("target_race_date")
    remaining = (target - day).days if target is not None else None
    result.add("R18", 0 <= remaining <= result.threshold("R18") if remaining is not None else None,
               {"target_race_date": target.isoformat() if target is not None else None,
                "days_to_race": remaining}, ("目标赛事日期",))


def evaluate_rules(metrics: dict, *, activities: dict | None = None,
                   context: dict | None = None, rules: dict[str, dict] | None = None,
                   allow_missing_evidence: bool = False) -> dict:
    """Return auditable checks, a report-compatible list of signals, and a review gate."""
    if not isinstance(metrics, dict) or metrics.get("schema_version") != "2.0":
        raise ValueError("风险判断需要 P3 生成的 metrics v2 文件")
    athlete_id = metrics["athlete_id"]
    day = iso_day(metrics["window"]["end"])
    answers = normalized_context(context, athlete_id)
    records = None
    if activities is not None:
        if not isinstance(activities, dict) or activities.get("athlete_id") != athlete_id:
            raise ValueError("活动文件的 athlete_id 必须与指标一致")
        records = [{**item, "_day": iso_day(item["date"])} for item in activities["activities"]]
    result = Assessment(rules if rules is not None else load_rules(), allow_missing_evidence=allow_missing_evidence)
    data_checks(result, metrics, records, answers, day)
    load_checks(result, metrics, records, answers, day)
    capacity_and_recovery_checks(result, metrics, day)
    condition_checks(result, metrics, records, answers, day)

    review = [risk["rule_id"] for risk in result.risks if risk["level"] == "high"]
    pain_check = next(check for check in result.checks if check["rule_id"] == "R15")
    if review:
        gate = {"status": "hold_for_review", "rule_ids": review}
    elif pain_check["status"] == "insufficient_data":
        gate = {"status": "needs_confirmation", "rule_ids": ["R15"]}
    else:
        gate = {"status": "no_hold_signal", "rule_ids": []}
    return {"athlete_id": athlete_id, "as_of": day.isoformat(), "checks": result.checks,
            "risks": result.risks, "planning_gate": gate}


def read_verified(path: Path) -> dict:
    errors = validate_file(path)
    if errors:
        raise ValueError(f"{path.name} 未通过契约校验：{errors[0]}")
    return load_json(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地训练监测规则判断与依据查询")
    command = parser.add_subparsers(dest="mode", required=True)
    evaluate = command.add_parser("evaluate", help="判断 R01–R18")
    evaluate.add_argument("metrics", type=Path)
    evaluate.add_argument("--activities", type=Path)
    evaluate.add_argument("--context", type=Path)
    evaluate.add_argument("-o", "--out", type=Path, default=Path("out/risk_checks.json"))
    evidence = command.add_parser("evidence", help="查询规则库条款")
    evidence.add_argument("rule_id")
    args = parser.parse_args(argv)

    try:
        rules = load_rules()
        if args.mode == "evidence":
            item = lookup_evidence(args.rule_id, rules)
            if item is None:
                raise ValueError("未找到规则依据")
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0

        sources = [path.resolve() for path in (args.metrics, args.activities, args.context) if path]
        if args.out.resolve() in sources:
            raise ValueError("输入与输出路径不得重合")
        result = evaluate_rules(read_verified(args.metrics),
                                activities=read_verified(args.activities) if args.activities else None,
                                context=load_json(args.context) if args.context else None, rules=rules)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8", newline="\n")
    except (OSError, KeyError, TypeError, OverflowError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print(f"已写出规则检查 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
