"""Everyday running metrics from accepted activity records; never infer missing training days."""
from __future__ import annotations
from datetime import date, timedelta
from math import isfinite


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and isfinite(value)


def compute_running_summary(document: dict, as_of: date, history_start: date | None = None) -> dict:
    start = as_of - timedelta(days=27)
    activities = [a for a in document.get("activities", [])
                  if a.get("sport") == "run" and not a.get("device_anomaly")
                  and start <= date.fromisoformat(a["date"]) <= as_of]
    activities.sort(key=lambda a: (a["date"], a.get("start_time") or ""))

    def rollup(items):
        valid = [a for a in items if _finite(a.get("distance_m")) and a["distance_m"] > 0
                 and isinstance(a.get("duration_s"), int) and a["duration_s"] > 0]
        km = sum(a["distance_m"] for a in valid) / 1000
        sec = sum(a["duration_s"] for a in valid)
        heart = [a for a in valid if _finite(a.get("avg_hr"))]
        heart_sec = sum(a["duration_s"] for a in heart)
        return {"distance_km": round(km, 3),
                "duration_min": round(sec / 60, 2),
                "sessions": len(items),
                "distance_sessions": len(valid),
                "average_pace_s_per_km": round(sec / km) if km > 0 else None,
                "average_hr_bpm": round(sum(a["avg_hr"] * a["duration_s"] for a in heart) / heart_sec)
                    if heart_sec else None,
                "hr_sessions": len(heart),
                "longest_run_km": round(max((a["distance_m"] for a in valid), default=0) / 1000, 3)}

    end7 = as_of - timedelta(days=6)
    before7 = end7 - timedelta(days=7)
    week = rollup([a for a in activities if a["date"] >= end7.isoformat()])
    previous = rollup([a for a in activities if before7.isoformat() <= a["date"] < end7.isoformat()])
    month = rollup(activities)
    previous_complete = history_start is not None and history_start <= before7
    week["previous_coverage_confirmed"] = previous_complete
    week["previous_distance_km"] = previous["distance_km"] if previous_complete else None
    week["distance_change_pct"] = (round((week["distance_km"] / previous["distance_km"] - 1) * 100, 1)
                                       if previous["distance_km"] > 0 and
                                       previous_complete else None)
    week["coverage_confirmed"] = history_start is not None and history_start <= end7
    by_day = {}
    for a in activities:
        by_day.setdefault(a["date"], []).append(a)
    daily=[]
    for i in range(28):
        current = start + timedelta(days=i)
        key = current.isoformat()
        rows = by_day.get(key)
        covered = history_start is not None and current >= history_start
        # A missing day is unknown unless the user confirmed full history coverage.
        if rows:
            row = rollup(rows)
            daily.append({"date": key,"distance_km":row["distance_km"],
                          "pace_s_per_km":row["average_pace_s_per_km"],
                          "avg_hr_bpm":row["average_hr_bpm"],"sessions":row["sessions"]})
        else:
            daily.append({"date":key,"distance_km":0 if covered else None,
                          "pace_s_per_km":None,"avg_hr_bpm":None,"sessions":0 if covered else None})
    return {"week": week,"month": month,"daily": daily,
            "window": {"start":start.isoformat(), "end":as_of.isoformat()},
            "notes": ["配速按有效跑步总用时÷总距离计算；心率按有心率记录的跑步时长加权。",
                      "没有记录的日期仅在用户确认历史覆盖范围时记为零；否则显示未知。",
                      "跑步统计仅包含已接纳的跑步记录；设备异常或丢弃的行不参与计算。"]}
