"""Compute P3 metrics from an activity export and optional local measurements."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from statistics import fmean

if __package__:
    from .physiology import capacity, normalized_measurements, recovery
else:
    from physiology import capacity, normalized_measurements, recovery


ACUTE_DAYS = 7
CHRONIC_DAYS = 28
MAX_ACWR_GAP = 1.0
TRIMP_COEFFICIENTS = {"male": (0.64, 1.92), "female": (0.86, 1.67)}
RULES_PATH = Path(__file__).resolve().parents[2] / "contracts" / "rules.json"
METRICS_VERSION = "2.0"


def trimp_coefficients(resting_hr: int, max_hr: int, profile: str) -> tuple[float, float]:
    if profile not in TRIMP_COEFFICIENTS:
        raise ValueError("需要选择有效的 TRIMP 系数")
    low, high = rule_thresholds()["R02"]["resting_hr_bpm"]
    if type(resting_hr) is not int or not low <= resting_hr <= high:
        raise ValueError(f"用于计算的静息心率须在项目 R02 复核范围 {low}–{high} bpm 内，请核对测量值")
    if type(max_hr) is not int or not resting_hr < max_hr <= 250:
        raise ValueError("个人最大心率不符合输入范围")
    return TRIMP_COEFFICIENTS[profile]


def trimp(duration_s: int, avg_hr: int, *, resting_hr: int, max_hr: int, profile: str) -> float:
    """Calculate one session with measured athlete limits and the selected R04 coefficients."""
    a, b = trimp_coefficients(resting_hr, max_hr, profile)
    if type(duration_s) is not int or duration_s <= 0:
        raise ValueError("活动时长缺失或无效")
    if type(avg_hr) is not int or not resting_hr <= avg_hr <= max_hr:
        raise ValueError("运动平均心率缺失或超出个人心率范围")

    reserve = (avg_hr - resting_hr) / (max_hr - resting_hr)
    value = duration_s / 60 * reserve * a * math.exp(b * reserve)
    if not math.isfinite(value):
        raise ValueError("TRIMP 超出数值范围")
    return value


def ewma(values: list[float], span: int) -> float:
    """Use the first covered day as the seed and process the series in date order."""
    alpha = 2 / (span + 1)
    average = values[0]
    for value in values[1:]:
        average = alpha * value + (1 - alpha) * average
    return average


@cache
def rule_thresholds() -> dict:
    return {item["rule_id"]: item["threshold"]
            for item in json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]}


def acwr_status(value: float) -> str:
    rules = rule_thresholds()
    lower, upper = rules["R05"]
    if value < lower:
        return "undertrained"
    if value <= upper:
        return "optimal"
    return "danger" if value > rules["R06"] else "high"


def parse_date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("日期必须是 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("日期必须是有效的 YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError("日期必须是 YYYY-MM-DD")
    return parsed


def compute_load(document: dict, *, as_of: date, history_start: date | None,
                 resting_hr: int, max_hr: int, profile: str) -> dict:
    if not isinstance(document, dict) or document.get("schema_version") != "1.0":
        raise ValueError("请输入 v1.0 activity.json")
    athlete_id = document.get("athlete_id")
    records = document.get("activities")
    if not isinstance(athlete_id, str) or not athlete_id or not isinstance(records, list):
        raise ValueError("活动文档缺少 athlete_id 或 activities 列表")
    if history_start is not None and history_start > as_of:
        raise ValueError("历史覆盖起始日不得晚于计算日")
    heart_configured = resting_hr is not None and max_hr is not None and profile in TRIMP_COEFFICIENTS
    if heart_configured:
        a, b = trimp_coefficients(resting_hr, max_hr, profile)
    else:
        a, b = None, None

    window_start = as_of - timedelta(days=CHRONIC_DAYS - 1)
    days = [window_start + timedelta(days=offset) for offset in range(CHRONIC_DAYS)]
    totals: defaultdict[date, float] = defaultdict(float)
    incomplete_days: set[date] = set()
    sessions: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("activities 必须由活动对象组成")
        day = parse_date(record.get("date"))
        if not window_start <= day <= as_of:
            continue
        activity_id = record.get("activity_id")
        if not isinstance(activity_id, str) or not activity_id or activity_id in seen:
            raise ValueError("活动 ID 缺失或重复")
        seen.add(activity_id)
        reason = None
        value = None
        if record.get("device_anomaly"):
            reason = "设备异常"
        elif not heart_configured:
            reason = "缺少个人心率计算参数，无法计算训练负荷"
        else:
            try:
                value = trimp(record.get("duration_s"), record.get("avg_hr"),
                              resting_hr=resting_hr, max_hr=max_hr, profile=profile)
            except (ValueError, OverflowError) as exc:
                reason = str(exc)
        if value is None:
            incomplete_days.add(day)
        else:
            totals[day] += value
        sessions.append({"activity_id": activity_id, "date": day.isoformat(),
                         "trimp": round(value, 6) if value is not None else None, "reason": reason})

    # Unrecorded days are zero only inside a coverage period explicitly declared by the caller.
    values = []
    for day in days:
        covered = day in totals or (history_start is not None and day >= history_start)
        values.append(totals[day] if covered and day not in incomplete_days else None)
    flags = []

    def flag(code: str, message: str, level: str = "medium") -> None:
        flags.append({"code": code, "level": level, "message": message})

    if incomplete_days:
        flag("TRIMP_INCOMPLETE_DAYS", f"{len(incomplete_days)} 天有活动无法计算 TRIMP，当天负荷视为未知。")

    def week_total(week: list[float | None]) -> float | None:
        return sum(value for value in week if value is not None) if None not in week else None

    week = week_total(values[-ACUTE_DAYS:])
    previous_week = week_total(values[-2 * ACUTE_DAYS:-ACUTE_DAYS])
    change = None
    if week is None or previous_week is None:
        flag("WEEK_INSUFFICIENT_HISTORY", "计算周环比需要最近两周的完整负荷。")
    elif previous_week == 0:
        flag("WEEK_ZERO_BASELINE", "上周总负荷为零，周环比未定义。")
    else:
        change = (week / previous_week - 1) * 100

    rolling = weighted = None
    status = None
    if None in values:
        flag("ACWR_INSUFFICIENT_HISTORY", "计算 ACWR 需要 28 天完整负荷。")
    else:
        daily_values = [value for value in values if value is not None]
        baseline = fmean(daily_values)
        chronic_ewma = ewma(daily_values, CHRONIC_DAYS)
        if baseline == 0 or chronic_ewma == 0:
            flag("ACWR_ZERO_BASELINE", "慢性负荷为零，ACWR 未定义。")
        else:
            rolling = fmean(daily_values[-ACUTE_DAYS:]) / baseline
            weighted = ewma(daily_values, ACUTE_DAYS) / chronic_ewma
            if abs(rolling - weighted) > MAX_ACWR_GAP:
                flag("ACWR_METHOD_GAP", "两种 ACWR 相差超过 1.0，保留原值供复核，暂不分档。", "high")
            else:
                status = acwr_status(weighted)

    numbers = {"trimp_week": week, "acwr_rolling": rolling, "acwr_ewma": weighted,
               "week_load_change_pct": change}
    load = {key: round(value, 6) if value is not None else None for key, value in numbers.items()}
    load["acwr_status"] = status
    load["trimp_daily"] = [{"date": day.isoformat(), "trimp": round(value, 6) if value is not None else None}
                          for day, value in zip(days, values, strict=True)]
    return {
        "athlete_id": athlete_id,
        "window": {"start": window_start.isoformat(), "end": as_of.isoformat(), "days": CHRONIC_DAYS},
        "load_inputs": {"profile": profile, "coefficient_a": a, "coefficient_b": b,
                        "resting_hr": resting_hr, "max_hr": max_hr,
                        "history_start": history_start.isoformat() if history_start is not None else None},
        "activity_trimp": sessions,
        "load": load,
        "flags": flags,
    }


def compute_metrics(document: dict, *, as_of: date, history_start: date | None,
                    resting_hr: int, max_hr: int, profile: str, measurements: dict | None = None) -> dict:
    output = compute_load(document, as_of=as_of, history_start=history_start,
                          resting_hr=resting_hr, max_hr=max_hr, profile=profile)
    daily, race, steady = normalized_measurements(measurements, output["athlete_id"])
    if resting_hr is None or max_hr is None:
        capacity_values = {"vo2max": {"value": None, "unit": "ml/kg/min", "method": None},
                           "methods": [], "estimate_range": None, "consistency_ok": None,
                           "max_spread_pct": None, "race_inputs": None}
        capacity_flags = [("VO2_INSUFFICIENT_INPUT", "缺少个人心率参数，无法估算有氧能力。")]
    else:
        capacity_values, capacity_flags = capacity(resting_hr, max_hr, race, as_of,
                                                   rule_thresholds()["R13"] * 100)
    recovery_values, recovery_flags = recovery(document["activities"], daily, steady, as_of,
                                               rule_thresholds()["R02"]["resting_hr_bpm"])
    output["flags"].extend({"code": code, "level": "medium", "message": message}
                           for code, message in (*capacity_flags, *recovery_flags))
    return {"schema_version": METRICS_VERSION, **output,
            "capacity": capacity_values, "recovery": recovery_values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="计算训练负荷、有氧能力与恢复指标")
    parser.add_argument("activity", type=Path, help="P2 生成的 activity.json")
    parser.add_argument("-o", "--out", type=Path)
    parser.add_argument("--measurements", type=Path, help="可选的本地补充量测 JSON")
    parser.add_argument("--load-only", action="store_true", help="只生成节点 04 的训练负荷结果")
    parser.add_argument("--as-of", required=True, help="计算截止日，包含当天")
    parser.add_argument("--history-start", help="确认记录完整的起始日，直到计算截止日")
    parser.add_argument("--trimp-profile", required=True, choices=TRIMP_COEFFICIENTS)
    parser.add_argument("--resting-hr", type=int, required=True, help="个人静息心率 bpm")
    parser.add_argument("--max-hr", type=int, required=True, help="个人最大心率 bpm")
    args = parser.parse_args(argv)
    try:
        output_path = args.out or Path("out/load_metrics.json" if args.load_only else "out/metrics.json")
        inputs = [args.activity] + ([args.measurements] if args.measurements else [])
        if any(path.resolve() == output_path.resolve() for path in inputs):
            raise ValueError("输入与输出路径不得重合")
        if args.load_only and args.measurements:
            raise ValueError("--load-only 不读取补充量测")
        document = json.loads(args.activity.read_text(encoding="utf-8-sig"))
        options = {
            "as_of": parse_date(args.as_of),
            "history_start": parse_date(args.history_start) if args.history_start else None,
            "resting_hr": args.resting_hr, "max_hr": args.max_hr, "profile": args.trimp_profile,
        }
        if args.load_only:
            output = compute_load(document, **options)
        else:
            measurements = (json.loads(args.measurements.read_text(encoding="utf-8-sig"))
                            if args.measurements else None)
            if args.measurements and measurements is None:
                raise ValueError("补充量测文件需要提供 JSON 对象")
            output = compute_metrics(document, **options, measurements=measurements)
        payload = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    except (OSError, OverflowError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print(f"已写出指标结果 {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
