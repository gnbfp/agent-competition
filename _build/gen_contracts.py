#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the interface contracts (JSON Schema) + golden samples.

Single source of truth for the five-person team:
  contracts/<name>.schema.json  <- shapes   (P4 owns)
  contracts/samples/*_sample.json <- examples (golden fixtures)
Run:  python gen_contracts.py
"""
import json
import os

OUT = r"E:\智能体大赛\contracts"
SAMPLES = os.path.join(OUT, "samples")

DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}

ACTIVITY_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["activity_id", "date", "sport", "duration_s", "distance_m", "avg_hr", "max_hr"],
    "properties": {
        "activity_id": {"type": "string", "pattern": r"^[A-Za-z0-9_\-]+$"},
        "date": DATE,
        "start_time": {"type": ["string", "null"], "pattern": r"^\d{2}:\d{2}$"},
        "sport": {"type": "string", "enum": ["run", "bike", "swim", "strength", "other"]},
        "duration_s": {"type": "integer", "minimum": 1},
        "distance_m": {"type": "number", "minimum": 0},
        "avg_hr": {"type": "integer", "minimum": 30, "maximum": 230},
        "max_hr": {"type": "integer", "minimum": 30, "maximum": 250},
        "elevation_gain_m": {"type": ["number", "null"], "minimum": 0},
        "avg_pace_s_per_km": {"type": ["number", "null"], "minimum": 120, "maximum": 1200},
        "rpe": {"type": ["integer", "null"], "minimum": 0, "maximum": 10},
        "sleep_h": {"type": ["number", "null"], "minimum": 0, "maximum": 24},
        "pain": {"type": ["string", "null"]},
        "source": {"type": "string", "enum": ["garmin", "coros", "huawei", "keep", "manual", "csv"]},
        "device_anomaly": {"type": "boolean"}
    }
}

ACTIVITY_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "activity.json — 原始活动数据（P2 解析器产出）",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "athlete_id", "timezone", "activities"],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "athlete_id": {"type": "string"},
        "timezone": {"type": "string", "enum": ["Asia/Shanghai"]},
        "generated_at": {"type": "string"},
        "activities": {"type": "array", "items": ACTIVITY_ITEM}
    }
}

METRICS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "metrics.json — 指标计算结果（P3 产出）",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "athlete_id", "window", "load", "capacity", "recovery", "flags"],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "athlete_id": {"type": "string"},
        "window": {
            "type": "object",
            "additionalProperties": False,
            "required": ["start", "end", "days"],
            "properties": {"start": DATE, "end": DATE, "days": {"type": "integer", "minimum": 7}}
        },
        "load": {
            "type": "object",
            "additionalProperties": False,
            "required": ["trimp_week", "acwr_rolling", "acwr_ewma", "acwr_status", "week_load_change_pct"],
            "properties": {
                "trimp_daily": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["date", "trimp"],
                    "properties": {"date": DATE, "trimp": {"type": "number", "minimum": 0}}}},
                "trimp_week": {"type": "number", "minimum": 0},
                "acwr_rolling": {"type": "number", "minimum": 0, "maximum": 5},
                "acwr_ewma": {"type": "number", "minimum": 0, "maximum": 5},
                "acwr_status": {"type": "string", "enum": ["undertrained", "optimal", "high", "danger"]},
                "week_load_change_pct": {"type": "number"}
            }
        },
        "capacity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["vo2max", "methods", "consistency_ok", "max_spread_pct"],
            "properties": {
                "vo2max": {
                    "type": "object", "additionalProperties": False,
                    "required": ["value", "unit", "method", "ci_low", "ci_high"],
                    "properties": {
                        "value": {"type": "number", "minimum": 20, "maximum": 90},
                        "unit": {"type": "string", "enum": ["ml/kg/min"]},
                        "method": {"type": "string", "enum": ["uth_sorensen", "riegel", "cooper", "daniels"]},
                        "ci_low": {"type": "number"},
                        "ci_high": {"type": "number"}
                    }
                },
                "methods": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["method", "value"],
                    "properties": {
                        "method": {"type": "string", "enum": ["uth_sorensen", "riegel", "cooper", "daniels"]},
                        "value": {"type": "number"}}}},
                "consistency_ok": {"type": "boolean"},
                "max_spread_pct": {"type": "number", "minimum": 0}
            }
        },
        "recovery": {
            "type": "object",
            "additionalProperties": False,
            "required": ["resting_hr_baseline", "resting_hr_delta", "hr_drift_pct", "sleep_h_avg"],
            "properties": {
                "resting_hr_baseline": {"type": "integer", "minimum": 30, "maximum": 120},
                "resting_hr_delta": {"type": "number"},
                "hr_drift_pct": {"type": ["number", "null"]},
                "hrv_rmssd": {"type": ["number", "null"], "minimum": 0},
                "sleep_h_avg": {"type": "number", "minimum": 0, "maximum": 24}
            }
        },
        "flags": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["code", "level", "message"],
            "properties": {
                "code": {"type": "string"},
                "level": {"type": "string", "enum": ["low", "medium", "high"]},
                "message": {"type": "string"}}}}
    }
}

PLAN_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "plan.json — 周训练计划（P4 agent 产出）",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "athlete_id", "week_start", "weekly_targets", "days", "self_check"],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "athlete_id": {"type": "string"},
        "week_start": DATE,
        "weekly_targets": {
            "type": "object", "additionalProperties": False,
            "required": ["load_target_trimp", "sessions", "long_run_max_pct"],
            "properties": {
                "load_target_trimp": {"type": "number", "minimum": 0},
                "sessions": {"type": "integer", "minimum": 0, "maximum": 14},
                "long_run_max_pct": {"type": "number", "minimum": 0, "maximum": 100},
                "intensity_days": {"type": "integer", "minimum": 0, "maximum": 7}
            }
        },
        "days": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["date", "kind", "duration_min", "rules"],
            "properties": {
                "date": DATE,
                "kind": {"type": "string", "enum": ["rest", "easy", "tempo", "interval", "long", "race", "cross", "other"]},
                "duration_min": {"type": "number", "minimum": 0, "maximum": 400},
                "distance_m": {"type": "number", "minimum": 0},
                "target_pace_s_per_km": {"type": ["number", "null"], "minimum": 120, "maximum": 1200},
                "hr_zone": {"type": ["string", "null"], "enum": ["Z1", "Z2", "Z3", "Z4", "Z5", None]},
                "purpose": {"type": "string"},
                "rules": {"type": "array", "items": {"type": "string", "pattern": r"^R\d{2}$"}}
            }
        }},
        "adjustments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["rule_id", "reason", "action"],
            "properties": {
                "rule_id": {"type": "string", "pattern": r"^R\d{2}$"},
                "reason": {"type": "string"},
                "action": {"type": "string"}}}},
        "self_check": {
            "type": "object", "additionalProperties": False,
            "required": ["passed", "checks"],
            "properties": {
                "passed": {"type": "boolean"},
                "checks": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["code", "passed", "detail"],
                    "properties": {
                        "code": {"type": "string"},
                        "passed": {"type": "boolean"},
                        "detail": {"type": "string"}}}}
            }
        }
    }
}

RISK_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rule_id", "level", "category", "title", "evidence", "action"],
    "properties": {
        "rule_id": {"type": "string", "pattern": r"^R\d{2}$"},
        "level": {"type": "string", "enum": ["low", "medium", "high"]},
        "category": {"type": "string", "enum": ["load", "capacity", "recovery", "injury", "environment", "data"]},
        "title": {"type": "string"},
        "evidence": {
            "type": "object", "additionalProperties": False,
            "required": ["clause", "source"],
            "properties": {
                "clause": {"type": "string"},
                "source": {"type": "string"},
                "threshold": {"type": "string"}}},
        "action": {"type": "string"},
        "missing_data": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    }
}

REPORT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "report.json — 前端唯一消费对象（P4 产出，P5 只读）",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "generated_at", "athlete_id", "summary", "metrics", "risks", "plan", "evidence", "agent_trace"],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "generated_at": {"type": "string"},
        "athlete_id": {"type": "string"},
        "summary": {
            "type": "object", "additionalProperties": False,
            "required": ["headline", "risk_level", "load_status"],
            "properties": {
                "headline": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "load_status": {"type": "string", "enum": ["undertrained", "optimal", "high", "danger"]}}},
        "metrics": METRICS_SCHEMA,
        "risks": {"type": "array", "items": RISK_ITEM},
        "plan": PLAN_SCHEMA,
        "evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["rule_id", "ref"],
            "properties": {"rule_id": {"type": "string", "pattern": r"^R\d{2}$"}, "ref": {"type": "string"}}}},
        "agent_trace": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["step", "tool", "status"],
            "properties": {
                "step": {"type": "integer", "minimum": 1},
                "tool": {"type": "string", "enum": ["load_activities", "compute_load", "estimate_vo2max",
                                                   "check_risk", "retrieve_evidence", "ask_athlete",
                                                   "generate_plan", "explain"]},
                "status": {"type": "string", "enum": ["ok", "retry", "failed", "skipped"]},
                "notes": {"type": "string"}}}},
        "disclaimers": {"type": "array", "items": {"type": "string"}}
    }
}

# ---------------- golden samples ----------------

ACTIVITY_SAMPLE = {
    "schema_version": "1.0",
    "athlete_id": "ATH-001",
    "timezone": "Asia/Shanghai",
    "generated_at": "2026-11-15T10:00:00+08:00",
    "activities": [
        {"activity_id": "A20261112-01", "date": "2026-11-12", "start_time": "06:30", "sport": "run",
         "duration_s": 2880, "distance_m": 8000, "avg_hr": 152, "max_hr": 171,
         "elevation_gain_m": 22, "avg_pace_s_per_km": 360, "rpe": 6, "sleep_h": 6.5,
         "pain": None, "source": "garmin", "device_anomaly": False},
        {"activity_id": "A20261114-01", "date": "2026-11-14", "start_time": "16:10", "sport": "run",
         "duration_s": 5400, "distance_m": 14000, "avg_hr": 158, "max_hr": 183,
         "elevation_gain_m": 65, "avg_pace_s_per_km": 385, "rpe": 8, "sleep_h": 7.0,
         "pain": "右膝外侧轻微不适", "source": "garmin", "device_anomaly": False}
    ]
}

METRICS_SAMPLE = {
    "schema_version": "1.0",
    "athlete_id": "ATH-001",
    "window": {"start": "2026-10-18", "end": "2026-11-14", "days": 28},
    "load": {
        "trimp_daily": [{"date": "2026-11-12", "trimp": 96.0}, {"date": "2026-11-14", "trimp": 214.0}],
        "trimp_week": 540.0,
        "acwr_rolling": 1.62,
        "acwr_ewma": 1.44,
        "acwr_status": "high",
        "week_load_change_pct": 22.0
    },
    "capacity": {
        "vo2max": {"value": 51.2, "unit": "ml/kg/min", "method": "uth_sorensen", "ci_low": 48.0, "ci_high": 54.4},
        "methods": [{"method": "uth_sorensen", "value": 51.2},
                    {"method": "riegel", "value": 50.1},
                    {"method": "cooper", "value": 52.4}],
        "consistency_ok": True,
        "max_spread_pct": 4.5
    },
    "recovery": {"resting_hr_baseline": 52, "resting_hr_delta": 4.0, "hr_drift_pct": 6.2,
                 "hrv_rmssd": 48.0, "sleep_h_avg": 6.6},
    "flags": [{"code": "LOAD_HIGH", "level": "high", "message": "ACWR 1.62 超过 1.5 高危线"}]
}

PLAN_SAMPLE = {
    "schema_version": "1.0",
    "athlete_id": "ATH-001",
    "week_start": "2026-11-16",
    "weekly_targets": {"load_target_trimp": 430.0, "sessions": 4, "long_run_max_pct": 30.0, "intensity_days": 1},
    "days": [
        {"date": "2026-11-16", "kind": "rest", "duration_min": 0, "distance_m": 0,
         "target_pace_s_per_km": None, "hr_zone": None, "purpose": "完全休息，处理膝部不适", "rules": ["R15"]},
        {"date": "2026-11-17", "kind": "easy", "duration_min": 40, "distance_m": 7000,
         "target_pace_s_per_km": 400, "hr_zone": "Z2", "purpose": "有氧维持", "rules": ["R05", "R14"]},
        {"date": "2026-11-18", "kind": "cross", "duration_min": 45, "distance_m": 0,
         "target_pace_s_per_km": None, "hr_zone": "Z1", "purpose": "交叉训练，减冲击", "rules": ["R15"]},
        {"date": "2026-11-19", "kind": "rest", "duration_min": 0, "distance_m": 0,
         "target_pace_s_per_km": None, "hr_zone": None, "purpose": "恢复", "rules": ["R07"]},
        {"date": "2026-11-20", "kind": "easy", "duration_min": 35, "distance_m": 6000,
         "target_pace_s_per_km": 405, "hr_zone": "Z2", "purpose": "有氧维持", "rules": ["R05"]},
        {"date": "2026-11-21", "kind": "long", "duration_min": 70, "distance_m": 12000,
         "target_pace_s_per_km": 420, "hr_zone": "Z2", "purpose": "长距离耐力（占比 28%）", "rules": ["R10"]},
        {"date": "2026-11-22", "kind": "rest", "duration_min": 0, "distance_m": 0,
         "target_pace_s_per_km": None, "hr_zone": None, "purpose": "恢复", "rules": ["R07"]}
    ],
    "adjustments": [
        {"rule_id": "R05", "reason": "ACWR 1.62 > 1.5", "action": "本周总负荷由 540 下调到 430"},
        {"rule_id": "R15", "reason": "用户反馈右膝外侧不适", "action": "取消两次强度课，长距离缩到 12km"}
    ],
    "self_check": {
        "passed": True,
        "checks": [
            {"code": "R19", "passed": True, "detail": "周负荷变化 -20.4%，未超 +10% 上限"},
            {"code": "R20", "passed": True, "detail": "7 天全部挂 rule_id，依据覆盖率 100%"}
        ]
    }
}

REPORT_SAMPLE = {
    "schema_version": "1.0",
    "generated_at": "2026-11-15T10:05:00+08:00",
    "athlete_id": "ATH-001",
    "summary": {"headline": "本周建议减量：负荷偏高 + 膝部不适", "risk_level": "high", "load_status": "high"},
    "metrics": METRICS_SAMPLE,
    "risks": [
        {"rule_id": "R05", "level": "high", "category": "load", "title": "负荷急增（ACWR 1.62）",
         "evidence": {"clause": "ACWR = 近 7 天负荷 / 近 28 天平均负荷；> 1.5 为高危", "source": "Gabbett TJ, 2016, Br J Sports Med 50:273-280", "threshold": "1.5"},
         "action": "本周总负荷下调 20%，砍掉强度课", "missing_data": [], "confidence": 0.9},
        {"rule_id": "R15", "level": "high", "category": "injury", "title": "膝部疼痛主诉",
         "evidence": {"clause": "用户报告疼痛时强制暂停原计划", "source": "运动医学通行做法 + 5 步伤情筛查表", "threshold": "任意疼痛主诉"},
         "action": "暂停强度课，建议就医评估", "missing_data": ["疼痛部位具体定位"], "confidence": 0.95}
    ],
    "plan": PLAN_SAMPLE,
    "evidence": [
        {"rule_id": "R05", "ref": "Gabbett TJ, 2016, Br J Sports Med 50:273-280"},
        {"rule_id": "R07", "ref": "训练学通行做法：每周至少 1–2 个完全休息日"},
        {"rule_id": "R10", "ref": "训练学通行做法：单次长距离不超过周跑量 35%"},
        {"rule_id": "R14", "ref": "训练学：同配速心率比 4 周前高 > 8bpm 判疲劳累积"},
        {"rule_id": "R15", "ref": "运动医学通行做法；本文档第九节"}
    ],
    "agent_trace": [
        {"step": 1, "tool": "load_activities", "status": "ok", "notes": "读取 28 天记录 21 条，2 条设备异常已剔除"},
        {"step": 2, "tool": "compute_load", "status": "ok", "notes": "TRIMP 540，ACWR 滚动 1.62 / EWMA 1.44"},
        {"step": 3, "tool": "ask_athlete", "status": "ok", "notes": "补问：最大心率是否实测 → 194"},
        {"step": 4, "tool": "check_risk", "status": "ok", "notes": "命中 R05、R15，其余 18 条未触发"},
        {"step": 5, "tool": "generate_plan", "status": "retry", "notes": "第一版周负荷 +18% 被 R19 打回，重排后 -20.4%"},
        {"step": 6, "tool": "explain", "status": "ok", "notes": "输出报告，依据覆盖率 100%"}
    ],
    "disclaimers": ["本报告为训练建议，不构成医疗诊断；疼痛持续请就医。"]
}

FILES = [
    ("activity.schema.json", ACTIVITY_SCHEMA),
    ("metrics.schema.json", METRICS_SCHEMA),
    ("plan.schema.json", PLAN_SCHEMA),
    ("report.schema.json", REPORT_SCHEMA),
    (os.path.join("samples", "activity_sample.json"), ACTIVITY_SAMPLE),
    (os.path.join("samples", "metrics_sample.json"), METRICS_SAMPLE),
    (os.path.join("samples", "plan_sample.json"), PLAN_SAMPLE),
    (os.path.join("samples", "report_sample.json"), REPORT_SAMPLE),
]


def main():
    os.makedirs(SAMPLES, exist_ok=True)
    for name, obj in FILES:
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("wrote", path)


if __name__ == "__main__":
    main()
