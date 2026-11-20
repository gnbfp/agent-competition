"""Generate and apply the narrow set of answers the rule engine can use."""

from __future__ import annotations

import sys


def questions_for(checks: list[dict]) -> list[dict]:
    status = {item["rule_id"]: item for item in checks}
    questions = []
    if status["R15"]["status"] == "insufficient_data":
        questions.append({"key": "pain_reported", "rule_id": "R15", "type": "boolean",
                          "prompt": "请确认目前是否有疼痛（是或否）"})
    if status["R03"]["status"] == "insufficient_data":
        questions.append({"key": "max_hr_source", "rule_id": "R03", "type": "choice",
                          "prompt": "最大心率来自实测、赛事记录还是 220 减年龄估算",
                          "choices": ["measured", "race", "estimated_220_age"]})
    if status["R16"]["status"] == "insufficient_data":
        for day, value in status["R16"]["observed"]["daily_sleep_h"].items():
            if value is None:
                questions.append({"key": f"sleep_h.{day}", "rule_id": "R16", "type": "number",
                                  "prompt": f"{day} 的睡眠时长为多少小时"})
    return questions


def apply_answers(context: dict | None, athlete_id: str, questions: list[dict], answers: dict) -> tuple[dict, int]:
    if not isinstance(answers, dict):
        raise ValueError("answers 应为 JSON 对象")
    known = {question["key"] for question in questions}
    if set(answers) - known:
        raise ValueError("答复只能填写本轮追问列出的字段")
    updated = dict(context or {"athlete_id": athlete_id})
    sleep = dict(updated.get("sleep_readings") or {})
    used = 0
    for key, value in answers.items():
        if value is None:
            continue
        if key.startswith("sleep_h."):
            sleep[key.partition(".")[2]] = value
        else:
            updated[key] = value
        used += 1
    if sleep:
        updated["sleep_readings"] = sleep
    return updated, used


def prompt_answers(questions: list[dict]) -> dict:
    replies = {}
    for question in questions:
        choices = question.get("choices", ())
        suffix = f" [{', '.join(choices)}]" if choices else ""
        while True:
            print(f"{question['prompt']}{suffix}（回车跳过）：", file=sys.stderr, flush=True)
            try:
                raw = input().strip().lower()
            except EOFError:
                return replies
            if not raw:
                break
            if question["type"] == "boolean":
                value = {"是": True, "否": False, "true": True, "false": False,
                         "y": True, "n": False}.get(raw)
                if value is not None:
                    replies[question["key"]] = value
                    break
            elif choices:
                if raw in choices:
                    replies[question["key"]] = raw
                    break
            else:
                try:
                    hours = float(raw)
                except ValueError:
                    hours = -1
                if 0 <= hours <= 24:
                    replies[question["key"]] = hours
                    break
            print("输入格式无效，请按提示填写。", file=sys.stderr)
    return replies
