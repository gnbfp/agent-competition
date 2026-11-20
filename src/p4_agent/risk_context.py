"""Validate optional observations without interpreting missing values as negatives."""

from __future__ import annotations

from datetime import date
import math


HARD_SESSIONS = {"tempo", "interval", "race"}
SESSION_TYPES = HARD_SESSIONS | {"easy", "long", "cross", "rest"}


def as_number(value):
    return value if type(value) is int or (type(value) is float and math.isfinite(value)) else None


def iso_day(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("日期必须是 YYYY-MM-DD") from None
    if result.isoformat() != value:
        raise ValueError("日期必须是 YYYY-MM-DD")
    return result


def normalized_context(document: dict | None, athlete_id: str) -> dict:
    if document is None:
        return {}
    if not isinstance(document, dict) or document.get("athlete_id") != athlete_id:
        raise ValueError("补充信息的 athlete_id 必须与指标一致")
    fields = {"athlete_id", "max_hr_source", "session_types", "pain_reported",
              "import_quality", "environment", "target_race_date"}
    if unknown := set(document) - fields:
        raise ValueError(f"补充信息包含未知字段：{', '.join(sorted(unknown))}")
    context = dict(document)
    source = context.get("max_hr_source")
    if source is not None and source not in ("estimated_220_age", "measured", "race"):
        raise ValueError("max_hr_source 应为 estimated_220_age、measured 或 race")
    pain = context.get("pain_reported")
    if pain is not None and type(pain) is not bool:
        raise ValueError("pain_reported 应为布尔值或 null")
    if context.get("target_race_date") is not None:
        context["target_race_date"] = iso_day(context["target_race_date"])

    sessions = context.get("session_types")
    if sessions is not None:
        if not isinstance(sessions, dict):
            raise ValueError("session_types 应是日期到训练类型的映射")
        for day, kinds in sessions.items():
            iso_day(day)
            if (not isinstance(kinds, list)
                    or not all(isinstance(kind, str) and kind in SESSION_TYPES for kind in kinds)):
                raise ValueError("session_types 包含未知的训练类型")

    quality = context.get("import_quality")
    if quality is not None:
        if not isinstance(quality, dict) or set(quality) - {"incomplete_rows", "device_anomaly_rows"}:
            raise ValueError("import_quality 仅接受 incomplete_rows 和 device_anomaly_rows")
        for value in quality.values():
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("导入计数应为非负整数或 null")

    environment = context.get("environment")
    if environment is not None:
        limits = {"temperature_c": (-50, 65), "humidity_pct": (0, 100)}
        if not isinstance(environment, dict) or set(environment) - set(limits):
            raise ValueError("environment 仅接受 temperature_c 和 humidity_pct")
        for field, value in environment.items():
            if value is None:
                continue
            low, high = limits[field]
            numeric = as_number(value)
            if numeric is None or not low <= numeric <= high:
                raise ValueError(f"{field} 超出允许范围")
    return context
