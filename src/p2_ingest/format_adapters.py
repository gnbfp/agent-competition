#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2 数据入口（上游）：手表/App 的原始导出 CSV → 「CSV 中间格式」13 列。

分工边界（照 docs/CSV中间格式.md 一、五节）：
- 本模块只做 **列名映射 / 单位归一 / 文本清理**，不判断哪一行能入库；
- 「缺字段丢行、心率异常按 R02 旁路」仍由 csv_parser.py 负责，全队只有那一套规则；
- 因此本模块输出的每一行都是字符串字典，可以直接交给 csv_parser.parse_rows()。

新增一种导出格式 = 在 ADAPTER_SPECS 里加一条（必要时补 _ALIASES 别名），不碰校验逻辑。
"""

from __future__ import annotations

import math
import re
from datetime import date as date_cls

# 中间格式的 13 列，顺序与 docs/CSV中间格式.md 二节一致
MIDDLE_COLUMNS = (
    "date", "start_time", "sport", "duration_s", "distance_m", "avg_hr", "max_hr",
    "elevation_gain_m", "avg_pace_s_per_km", "rpe", "sleep_h", "pain", "source",
)

# 各家导出表示"这一格空着"的写法。注意 0 不在此列：0 是真实值，不能当缺失。
MISSING_TOKENS = {
    "", "-", "--", "---", "—", "–", "－", "?", "？",
    "n/a", "na", "nan", "none", "null", "无", "空", "/",
}

# 表头别名：键是规范化后的表头（去空白、转小写），值是中间格式字段名。
# 覆盖 Garmin 中英文界面、华为运动健康、Keep / 悦跑圈摘要导出。
_ALIASES: dict[str, str] = {
    # 日期 / 开始时间
    "date": "date", "日期": "date", "运动日期": "date", "开始时间": "date",
    "starttime": "date", "startedat": "date", "datetime": "date",
    # 运动类型
    "sport": "sport", "activitytype": "sport", "运动类型": "sport",
    "活动类型": "sport", "运动项目": "sport", "类型": "sport",
    # 时长
    "time": "duration", "duration": "duration", "时长": "duration",
    "运动时长": "duration", "用时": "duration", "持续时间": "duration", "时间": "duration",
    # 距离
    "distance": "distance", "距离": "distance", "里程": "distance",
    # 心率
    "avghr": "avg_hr", "平均心率": "avg_hr", "心率均值": "avg_hr", "avgheartrate": "avg_hr",
    "maxhr": "max_hr", "最大心率": "max_hr", "maxheartrate": "max_hr",
    # 爬升 / 配速
    "elevgain": "elevation", "elevationgain": "elevation", "elevation": "elevation",
    "爬升": "elevation", "累计爬升": "elevation", "总爬升": "elevation", "爬升高度": "elevation",
    "avgpace": "pace", "平均配速": "pace", "配速": "pace",
    # 主观与睡眠
    "rpe": "rpe", "主观疲劳度": "rpe",
    "sleeph": "sleep_h", "睡眠": "sleep_h", "睡眠时长": "sleep_h",
    # 疼痛
    "pain": "pain", "疼痛": "pain", "疼痛反馈": "pain",
}

# 各格式的规格：签名表头用于自动识别，distance_unit 是该格式距离列的默认单位。
ADAPTER_SPECS: dict[str, dict] = {
    "garmin": {
        "label": "Garmin Connect 导出（英文或中文表头）",
        "source_id": "garmin",
        "signature": {"activitytype", "date", "distance", "time", "avghr"},
        "distance_unit": "km",
    },
    "huawei": {
        "label": "华为运动健康 / Keep / 悦跑圈 摘要导出（中文表头）",
        "source_id": "huawei",
        "signature": {"运动类型", "开始时间", "时长", "距离"},
        "distance_unit": "km",
    },
}

# 入库前至少要有这三列，缺了说明这个文件根本不是活动导出
_REQUIRED_FIELDS = ("date", "sport", "duration")

_UNIT_RE = re.compile(r"^(.+?)[\(（]([^\)）]+)[\)）]\s*$")
_DT_RE = re.compile(
    r"^(?P<y>\d{4})[-/.年](?P<mo>\d{1,2})[-/.月](?P<d>\d{1,2})日?"
    r"(?:[ T](?P<h>\d{1,2}):(?P<mi>\d{1,2})(?::(?P<s>\d{1,2}))?)?"
    r"\s*(?:Z|[+-]\d{2}:?\d{2})?$"
)
_PACE_RE = re.compile(r"^(\d{1,2})['′](\d{1,2})[\"″]?$")
_HMS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.\d+)?$")
_CN_DUR_RE = re.compile(r"^(?:(\d+)\s*(?:小时|时))?\s*(?:(\d+)\s*分)?\s*(?:(\d+)\s*秒)?$")

_SPORT_KEYWORDS = (
    ("骑", "bike"), ("单车", "bike"), ("cycle", "bike"), ("bike", "bike"),
    ("游", "swim"), ("泳", "swim"), ("swim", "swim"),
    ("力量", "strength"), ("核心", "strength"), ("gym", "strength"), ("strength", "strength"),
    ("跑", "run"), ("run", "run"), ("jog", "run"),
    ("走", "other"), ("徒步", "other"), ("hike", "other"), ("walk", "other"),
)


class AdapterError(ValueError):
    """这个文件/这一格不符合预期，无法转换为中间格式。"""


class ColumnMap:
    """表头映射结果：每个字段来自哪一列、那一列带什么单位。"""

    __slots__ = ("columns", "units", "warnings")

    def __init__(self, columns: dict[str, str], units: dict[str, str], warnings: list[str]) -> None:
        self.columns = columns
        self.units = units
        self.warnings = warnings

    def raw(self, row: dict, field: str) -> str:
        """取这一行某字段的原始文本；没有这一列就返回空串。"""
        column = self.columns.get(field)
        if column is None:
            return ""
        return str(row.get(column) or "").strip()

    def unit(self, field: str, default: str = "") -> str:
        """取这一列声明的单位，没写就用格式默认单位。"""
        return self.units.get(field) or default


def _norm(text: str) -> str:
    """表头规范化：去掉全部空白并转小写，便于比对别名。"""
    return re.sub(r"\s+", "", (text or "").strip().lower())


def split_header(header: str) -> tuple[str, str]:
    """把「距离(km)」拆成 ("距离", "km")；没有括号时单位为空串。"""
    text = (header or "").strip()
    matched = _UNIT_RE.match(text)
    if matched:
        return _norm(matched.group(1)), _norm(matched.group(2))
    return _norm(text), ""


def is_missing(text: str) -> bool:
    """这一格是不是"空着"（含各家表示空的符号）。"""
    return _norm(text) in MISSING_TOKENS


def parse_start_time(raw: str, unit: str = "") -> tuple[str, str | None]:
    """解析日期时间列，返回 (YYYY-MM-DD, HH:MM 或 None)。认不出就抛 AdapterError。"""
    if is_missing(raw):
        return "", None
    text = raw.strip()
    matched = _DT_RE.match(text)
    if not matched:
        raise AdapterError(f"认不出的日期时间：{text!r}")
    year, month, day = int(matched.group("y")), int(matched.group("mo")), int(matched.group("d"))
    try:
        value = date_cls(year, month, day)
    except ValueError as exc:
        raise AdapterError(f"日期不存在：{text!r}（{exc}）") from None
    if matched.group("h") is None:
        return value.isoformat(), None
    hour, minute = int(matched.group("h")), int(matched.group("mi"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise AdapterError(f"时间不存在：{text!r}")
    return value.isoformat(), f"{hour:02d}:{minute:02d}"


def parse_duration(raw: str, unit: str = "") -> int | None:
    """解析时长，统一成秒。支持 1:02:03 / 48:00 / 2880 / 48分 / 1小时2分。"""
    if is_missing(raw):
        return None
    text = re.sub(r"\s+", "", raw)
    matched = _HMS_RE.match(text)
    if matched:
        hours, minutes, seconds = matched.group(1), matched.group(2), matched.group(3)
        total = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
        return total
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        value = float(text)
        if unit in ("min", "分", "分钟"):
            value *= 60
        elif unit in ("h", "小时", "时"):
            value *= 3600
        if not math.isfinite(value):
            raise AdapterError(f"时长不是有限数值：{raw!r}")
        return round(value)
    cn = _CN_DUR_RE.match(text)
    if cn and any(cn.groups()):
        hours, minutes, seconds = (int(g or 0) for g in cn.groups())
        return hours * 3600 + minutes * 60 + seconds
    raise AdapterError(f"认不出的时长：{raw!r}")


def parse_distance_m(raw: str, unit: str = "") -> float | None:
    """解析距离并统一成米。默认按公里，表头写了 (m)/(米) 就按米。"""
    if is_missing(raw):
        return None
    text = re.sub(r"[,\s]", "", raw)
    try:
        value = float(text)
    except ValueError:
        raise AdapterError(f"认不出的距离：{raw!r}") from None
    if not math.isfinite(value):
        raise AdapterError(f"距离不是有限数值：{raw!r}")
    if value < 0:
        raise AdapterError(f"距离为负：{raw!r}")
    if unit in ("mi", "mile", "miles", "英里"):
        value *= 1609.344
    elif unit not in ("m", "米", "meter", "meters"):
        value *= 1000
    if not math.isfinite(value):
        raise AdapterError(f"距离换算后不是有限数值：{raw!r}")
    return round(value, 1)


def parse_pace(raw: str, unit: str = "") -> int | None:
    """解析每公里或每英里配速，统一成秒/公里。"""
    if is_missing(raw):
        return None
    text = re.sub(r"\s+", "", str(raw)).lower()
    value_text, separator, explicit_distance = text.partition("/")
    time_unit, _, header_distance = unit.partition("/")
    mile_units = ("mi", "mile", "miles", "英里")
    if separator and explicit_distance not in (*mile_units, "km", "公里"):
        raise AdapterError(f"认不出的配速距离单位：{raw!r}")
    distance_unit = explicit_distance if separator else header_distance
    matched = _PACE_RE.fullmatch(value_text) or re.fullmatch(r"(\d{1,2}):(\d{2})", value_text)
    numeric_text = value_text.removesuffix("s")
    if matched:
        seconds = int(matched.group(1)) * 60 + int(matched.group(2))
    elif re.fullmatch(r"\d+(?:\.\d+)?", numeric_text):
        seconds = float(numeric_text)
        if not value_text.endswith("s") and time_unit in ("min", "分", "分钟"):
            seconds *= 60
    else:
        raise AdapterError(f"认不出的配速：{raw!r}")
    if not math.isfinite(seconds):
        raise AdapterError(f"配速不是有限数值：{raw!r}")
    if distance_unit in mile_units:
        seconds /= 1.609344
    return round(seconds)


def normalize_running_pace(raw: str, unit: str, pace: int, duration: int, distance: float) -> tuple[int, bool]:
    """Resolve an ambiguous numeric minutes header using the row's actual speed."""
    time_unit, slash, distance_unit = unit.partition("/")
    if not slash or time_unit not in ("min", "分", "分钟") or not re.fullmatch(r"\d+(?:\.\d+)?", raw.strip()):
        return pace, False
    estimated = duration / distance * 1000
    if abs(estimated - pace) <= 15:
        return pace, False
    in_seconds = parse_pace(raw, f"s/{distance_unit}")
    if in_seconds is not None and 120 <= in_seconds <= 1200 and abs(estimated - in_seconds) <= 15:
        return in_seconds, True
    return pace, False


def parse_int(raw: str, unit: str = "") -> int | None:
    """解析整数（心率等）。带 bpm 后缀也认。"""
    if is_missing(raw):
        return None
    text = re.sub(r"[,\s]|bpm|次/分|次", "", str(raw).lower())
    try:
        value = float(text)
    except ValueError:
        raise AdapterError(f"认不出的整数：{raw!r}") from None
    if not math.isfinite(value):
        raise AdapterError(f"数值不是有限数值：{raw!r}")
    return round(value)


def parse_float(raw: str, unit: str = "") -> float | None:
    """解析小数（爬升、睡眠时长等）。"""
    if is_missing(raw):
        return None
    text = re.sub(r"[,\s]|米|m$", "", str(raw))
    try:
        value = float(text)
    except ValueError:
        raise AdapterError(f"认不出的小数：{raw!r}") from None
    if not math.isfinite(value):
        raise AdapterError(f"数值不是有限数值：{raw!r}")
    return round(value, 1)


def map_sport(raw: str) -> str | None:
    """把各家运动名映射到契约枚举；认不出返回 None（由下游按缺字段丢行）。"""
    text = _norm(raw)
    if not text:
        return None
    exact = {
        "run": "run", "running": "run", "跑步": "run", "跑": "run",
        "bike": "bike", "cycling": "bike", "骑行": "bike", "自行车": "bike",
        "swim": "swim", "swimming": "swim", "游泳": "swim",
        "strength": "strength", "力量": "strength", "力量训练": "strength", "gym": "strength",
        "other": "other", "走": "other", "徒步": "other", "hike": "other", "其他": "other",
    }
    if text in exact:
        return exact[text]
    for keyword, sport in _SPORT_KEYWORDS:
        if keyword in text:
            return sport
    return None


def map_columns(fieldnames: list[str]) -> ColumnMap:
    """按表头建立「字段 → 列」映射，并对重名列与未知列给出提示。"""
    columns: dict[str, str] = {}
    units: dict[str, str] = {}
    warnings: list[str] = []
    for header in fieldnames or []:
        base, unit = split_header(header)
        field = _ALIASES.get(base)
        if field is None:
            continue
        if field in columns:
            warnings.append(f"表头 {header!r} 与 {columns[field]!r} 都映射到 {field}，取前者")
            continue
        columns[field] = header
        if unit:
            units[field] = unit
    missing = [f for f in _REQUIRED_FIELDS if f not in columns]
    if missing:
        raise AdapterError(
            f"表头缺少必需列：{', '.join(missing)}；实际表头：{fieldnames}"
        )
    return ColumnMap(columns, units, warnings)


def detect_format(fieldnames: list[str]) -> str | None:
    """按表头签名猜导出格式；分数低于 2 视为猜不出，返回 None。"""
    normalized = {split_header(h)[0] for h in fieldnames or []}
    best_name: str | None = None
    best_score = 0
    for name, spec in ADAPTER_SPECS.items():
        score = len(normalized & spec["signature"])
        if score > best_score:
            best_name, best_score = name, score
    return best_name if best_score >= 2 else None


def _safe(parser, raw: str, unit: str, label: str, line_no: int,
          warnings: list[str]) -> object:
    """调用解析器；解析失败只记警告并按缺失处理，不中断整份文件。"""
    try:
        return parser(raw, unit)
    except AdapterError as exc:
        warnings.append(f"第 {line_no} 行 {label}：{exc}，按缺失处理")
        return None


def adapt_row(row: dict, column_map: ColumnMap, source_id: str, line_no: int,
              warnings: list[str]) -> dict[str, str]:
    """把一行原始导出行转成中间格式的一行（值全为字符串，缺失用空串）。"""
    output = {column: "" for column in MIDDLE_COLUMNS}

    try:
        day, start_time = parse_start_time(column_map.raw(row, "date"),
                                           column_map.unit("date"))
        output["date"] = day
        output["start_time"] = start_time or ""
    except AdapterError as exc:
        warnings.append(f"第 {line_no} 行 日期：{exc}，整行按缺失日期处理")

    raw_sport = column_map.raw(row, "sport")
    sport = map_sport(raw_sport)
    if sport is None and raw_sport:
        warnings.append(f"第 {line_no} 行 运动类型认不出：{raw_sport!r}")
    output["sport"] = sport or ""

    duration = _safe(parse_duration, column_map.raw(row, "duration"),
                     column_map.unit("duration"), "时长", line_no, warnings)
    if duration is not None:
        output["duration_s"] = str(int(duration))

    distance = _safe(parse_distance_m, column_map.raw(row, "distance"),
                     column_map.unit("distance"), "距离", line_no, warnings)
    if distance is not None:
        output["distance_m"] = f"{float(distance):.1f}"

    for field, parser, label in (
        ("avg_hr", parse_int, "平均心率"),
        ("max_hr", parse_int, "最大心率"),
        ("elevation", parse_float, "爬升"),
        ("pace", parse_pace, "配速"),
        ("rpe", parse_int, "RPE"),
        ("sleep_h", parse_float, "睡眠"),
    ):
        value = _safe(parser, column_map.raw(row, field), column_map.unit(field),
                      label, line_no, warnings)
        if value is None:
            continue
        if field in ("avg_hr", "max_hr") and int(value) == 0:
            # 各家导出"没戴心率带"时爱写 0（见 docs/CSV中间格式.md 四节）：0 不是测量值，
            # 直接当缺失，让下游按"缺心率丢行"处理，别让 0 拉垮均值。
            warnings.append(f"第 {line_no} 行 {label} 为 0，视为缺失（设备未记录）")
            continue
        target = "elevation_gain_m" if field == "elevation" else field
        if field == "pace":
            target = "avg_pace_s_per_km"
            if sport == "run" and duration and distance:
                value, corrected = normalize_running_pace(column_map.raw(row, field), column_map.unit(field),
                                                          value, duration, distance)
                if corrected:
                    warnings.append(f"第 {line_no} 行 配速与表头单位不符，按距离和时长复核后采用秒值")
        output[target] = str(value)

    pain = column_map.raw(row, "pain")
    output["pain"] = "" if is_missing(pain) else pain
    output["source"] = source_id
    return output


def adapt(fieldnames: list[str], rows: list[dict], source: str) -> tuple[list[dict], list[str]]:
    """整份文件转换：返回 (中间格式行列表, 警告列表)。"""
    if source not in ADAPTER_SPECS:
        raise AdapterError(f"不支持的格式 {source!r}，可选：{', '.join(ADAPTER_SPECS)}")
    spec = ADAPTER_SPECS[source]
    column_map = map_columns(fieldnames)
    warnings = list(column_map.warnings)
    adapted: list[dict] = []
    for line_no, row in enumerate(rows, start=2):  # 第 1 行是表头
        adapted.append(adapt_row(row, column_map, spec["source_id"], line_no, warnings))
    return adapted, warnings
