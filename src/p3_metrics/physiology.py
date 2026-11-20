"""Capacity estimates and date-based recovery metrics for P3."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import fmean, median

HISTORY_DAYS = 28
RECENT_DAYS = 7
MIN_BASELINE_DAYS = 7
MAX_STEADY_PACE_GAP = 0.05
RIEGEL_EXPONENT = 1.06


def valid_number(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and low <= value <= high


def required_number(record: dict, key: str, low: float, high: float) -> float:
    value = record.get(key)
    if not valid_number(value, low, high):
        raise ValueError(f"补充量测字段 {key} 缺失或超出输入范围")
    return value


def measurement_date(record: dict) -> date:
    value = record.get("date")
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("补充量测日期应为 YYYY-MM-DD") from None
    if day.isoformat() != value:
        raise ValueError("补充量测日期应为 YYYY-MM-DD")
    return day


def normalized_measurements(document: dict | None, athlete_id: str) -> tuple:
    """Check explicit inputs and reject mixed athlete IDs or duplicate dates."""
    if document is None:
        return {}, None, None
    if not isinstance(document, dict) or document.get("athlete_id") != athlete_id:
        raise ValueError("补充量测的 athlete_id 必须与活动文件一致")
    if set(document) - {"athlete_id", "daily", "race", "steady_run"}:
        raise ValueError("补充量测文件包含未知的顶层字段")
    days = {}
    entries = document.get("daily", [])
    if not isinstance(entries, list):
        raise ValueError("daily 必须是数组")
    limits = {"resting_hr_bpm": (30, 120), "hrv_rmssd_ms": (0, 1000), "sleep_h": (0, 24)}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"date", *limits}:
            raise ValueError("daily 记录格式不正确")
        day = measurement_date(entry)
        if day in days:
            raise ValueError("补充量测的 daily 中存在重复日期")
        days[day] = {key: None if entry.get(key) is None else required_number(entry, key, *bounds)
                     for key, bounds in limits.items()}

    race = document.get("race")
    if race is not None:
        if not isinstance(race, dict) or set(race) != {"date", "distance_m", "duration_s"}:
            raise ValueError("race 需要 date、distance_m 和 duration_s")
        race = {"date": measurement_date(race),
                "distance_m": required_number(race, "distance_m", 1500, 42195),
                "duration_s": required_number(race, "duration_s", 210, 13800)}

    steady = document.get("steady_run")
    if steady is not None:
        fields = {"first_hr_bpm": (30, 250), "second_hr_bpm": (30, 250),
                  "first_pace_s_per_km": (120, 1200), "second_pace_s_per_km": (120, 1200)}
        if not isinstance(steady, dict) or set(steady) - {"date", "temperature_c", *fields}:
            raise ValueError("steady_run 需要日期、两段平均心率和配速")
        steady = {"date": measurement_date(steady),
                  **{key: required_number(steady, key, *bounds) for key, bounds in fields.items()},
                  "temperature_c": None if steady.get("temperature_c") is None
                  else required_number(steady, "temperature_c", -50, 65)}
    return days, race, steady


def daniels_vdot(distance_m: float, duration_s: float) -> float:
    minutes = duration_s / 60
    speed = distance_m / minutes
    oxygen_cost = -4.60 + 0.182258 * speed + 0.000104 * speed**2
    fraction = 0.8 + 0.1894393 * math.exp(-0.012778 * minutes) + 0.2989558 * math.exp(-0.1932605 * minutes)
    return oxygen_cost / fraction


def capacity(resting_hr: int, max_hr: int, race: dict | None, as_of: date, threshold_pct: float) -> tuple[dict, list]:
    flags = []
    methods = []
    uth = 15.3 * max_hr / resting_hr
    if 20 <= uth <= 90:
        methods.append({"method": "uth_sorensen", "value": round(uth, 4)})
    else:
        flags.append(("VO2_HR_OUT_OF_RANGE", "心率比估算超出项目的输出范围，请核查输入。"))
    race_inputs = None
    if race is not None and 0 <= (as_of - race["date"]).days < HISTORY_DAYS:
        distance, elapsed = race["distance_m"], race["duration_s"]
        reference_distance = 10000 if distance == 5000 else 5000
        reference_time = elapsed * (reference_distance / distance)**RIEGEL_EXPONENT
        race_inputs = {"date": race["date"].isoformat(), "distance_m": distance,
                       "duration_s": elapsed, "riegel_distance_m": reference_distance,
                       "riegel_duration_s": round(reference_time, 6), "riegel_exponent": RIEGEL_EXPONENT}
        for method, value in (("daniels", daniels_vdot(distance, elapsed)),
                              ("riegel", daniels_vdot(reference_distance, reference_time))):
            if 20 <= value <= 90:
                methods.append({"method": method, "value": round(value, 4)})
            else:
                flags.append(("VDOT_OUT_OF_RANGE", f"{method} 赛绩指标超出项目的输出范围。"))
    elif race is not None:
        flags.append(("RACE_OUTSIDE_WINDOW", "赛绩日期不在计算截止日前的 28 日窗口内。"))

    values = [item["value"] for item in methods]
    bounds = None if len(values) < 2 else {"low": min(values), "high": max(values)}
    spread = None
    consistent = None
    if len(values) == 3:
        spread = round((max(values) - min(values)) / max(values) * 100, 6)
        consistent = spread <= threshold_pct
        if not consistent:
            flags.append(("VO2_METHOD_GAP", "三种计算结果差异超过项目阈值，仅提供估算范围。"))
    else:
        missing = ", ".join(sorted({"uth_sorensen", "daniels", "riegel"} - {item["method"] for item in methods}))
        flags.append(("VO2_INSUFFICIENT_INPUT", f"可用估算不足三条，缺少有效结果：{missing}。"))
    return {
        "vo2max": {"value": round(uth, 4) if consistent else None,
                   "unit": "ml/kg/min", "method": "uth_sorensen" if consistent else None},
        "methods": methods, "estimate_range": bounds, "consistency_ok": consistent,
        "max_spread_pct": spread, "race_inputs": race_inputs,
    }, flags


def recovery(activities: list[dict], daily: dict, steady: dict | None,
             as_of: date, resting_bounds: list[int]) -> tuple[dict, list]:
    flags = []
    window_start = as_of - timedelta(days=HISTORY_DAYS - 1)
    week_start = as_of - timedelta(days=RECENT_DAYS - 1)
    low, high = resting_bounds
    in_window = {day: entry["resting_hr_bpm"] for day, entry in daily.items() if window_start <= day <= as_of}
    historical = [value for day, value in in_window.items() if day < as_of and valid_number(value, low, high)]
    review_count = sum(value is not None and not valid_number(value, low, high) for value in in_window.values())
    if review_count:
        flags.append(("RESTING_HR_REVIEW", f"有 {review_count} 天静息心率超出 R02 复核范围，暂不用于计算。"))
    baseline = median(historical) if len(historical) >= MIN_BASELINE_DAYS else None
    current = daily.get(as_of, {})
    resting = current.get("resting_hr_bpm")
    delta = resting - baseline if valid_number(resting, low, high) and baseline is not None else None
    if delta is None:
        flags.append(("RESTING_HR_INSUFFICIENT", "静息心率偏差需要当天及至少 7 天历史的可用测量。"))

    activity_sleep = defaultdict(set)
    for activity in activities:
        sleep_h = activity.get("sleep_h")
        if not activity.get("device_anomaly") and valid_number(sleep_h, 0, 24):
            day = date.fromisoformat(activity["date"])
            if week_start <= day <= as_of:
                activity_sleep[day].add(sleep_h)
    recent = []
    sleep = []
    for day in sorted(set(daily) | set(activity_sleep)):
        if not window_start <= day <= as_of:
            continue
        entry = daily.get(day, {})
        sleep_h = entry.get("sleep_h")
        candidates = activity_sleep[day]
        if sleep_h is None and len(candidates) == 1:
            sleep_h = next(iter(candidates))
        elif sleep_h is None and len(candidates) > 1:
            flags.append(("SLEEP_CONFLICT", f"{day.isoformat()} 有冲突的睡眠记录，未纳入均值。"))
        if sleep_h is not None and day >= week_start:
            sleep.append(sleep_h)
        recent.append({"date": day.isoformat(), "resting_hr_bpm": entry.get("resting_hr_bpm"),
                       "sleep_h": sleep_h, "hrv_rmssd_ms": entry.get("hrv_rmssd_ms")})
    if not sleep:
        flags.append(("SLEEP_MISSING", "最近 7 天无可用睡眠记录。"))
    hrv = current.get("hrv_rmssd_ms")
    if hrv is None:
        flags.append(("HRV_MISSING", "截止日没有 RMSSD 量测。"))

    drift = None
    drift_input = None
    if steady is not None and window_start <= steady["date"] <= as_of:
        drift_input = {**steady, "date": steady["date"].isoformat()}
        pace1, pace2 = steady["first_pace_s_per_km"], steady["second_pace_s_per_km"]
        if abs(pace2 - pace1) / pace1 <= MAX_STEADY_PACE_GAP:
            first, second = steady["first_hr_bpm"], steady["second_hr_bpm"]
            drift = round((second - first) / first * 100, 6)
        else:
            flags.append(("HR_DRIFT_PACE_MISMATCH", "两段配速差超过 5%，未计算恒速心率漂移。"))
    else:
        flags.append(("HR_DRIFT_MISSING", "28 日内没有带两段心率和配速的恒速跑记录。"))
    return {
        "resting_hr_baseline": baseline, "resting_hr_baseline_days": len(historical),
        "resting_hr_delta": delta, "hr_drift_pct": drift, "hr_drift_inputs": drift_input,
        "hrv_rmssd": hrv, "sleep_h_avg": round(fmean(sleep), 6) if sleep else None,
        "sleep_days": len(sleep), "daily": recent,
    }, flags
