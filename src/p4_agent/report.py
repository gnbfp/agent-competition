"""Generate a validated plan and v2 report from the local assessment."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.validate_contract import load_json, validate_document
from src.p4_agent.evidence import load_rules, lookup_evidence
from src.p4_agent.followup import prompt_answers
from src.p4_agent.planner import generate_plan
from src.p4_agent.risk_rules import read_verified
from src.p4_agent.run import answers_from_file, run_agent


def build_report(metrics: dict, assessment: dict, plan: dict, rules: dict[str, dict],
                 *, generated_at: str) -> dict:
    risks = assessment["risks"]
    refs = {tag for day in plan["days"] for tag in day["rules"]}
    refs.update(risk["rule_id"] for risk in risks)
    refs.update(check["code"] for check in plan["self_check"]["checks"])
    trace = [dict(item) for item in assessment["agent_trace"]]
    for attempt in plan["attempts"]:
        failed = [item["code"] for item in attempt["checks"] if not item["passed"]]
        kept = "未通过：" + "、".join(failed) if failed else "R19、R20 通过"
        status = "ok"
        if failed:
            status = "retry" if attempt["round"] < len(plan["attempts"]) else "failed"
        trace.append({"step": len(trace) + 1, "tool": "generate_plan", "status": status,
                      "notes": f"第 {attempt['round']} 轮草案自检。{kept}。"})
    if not plan["attempts"]:
        trace.append({"step": len(trace) + 1, "tool": "generate_plan", "status": "skipped",
                      "notes": "未生成训练安排。"})
    title = {
        "draft": "下周草案已生成，待人工确认",
        "awaiting_input": "等待补充数据，暂未生成下周安排",
        "hold_for_review": "需要人工复核，暂未生成下周安排",
    }
    levels = {"low": 0, "medium": 1, "high": 2}
    risk_level = max((item["level"] for item in risks), key=levels.__getitem__, default=None)
    return {
        "schema_version": "2.0", "generated_at": generated_at, "athlete_id": metrics["athlete_id"],
        "summary": {"headline": title[plan["status"]], "risk_level": risk_level,
                    "load_status": metrics["load"]["acwr_status"], "plan_status": plan["status"]},
        "metrics": metrics, "risks": risks, "plan": plan,
        "evidence": [{"rule_id": rule_id, "ref": lookup_evidence(rule_id, rules)["source"]}
                     for rule_id in sorted(refs)],
        "agent_trace": trace, "questions": assessment["questions"],
        "disclaimers": ["训练草案供本人或教练复核。风险信号用于项目规则展示，不构成医疗诊断。"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成有自检和依据的计划 v2 与报告 v2")
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--activities", type=Path)
    parser.add_argument("--context", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--answers", type=Path)
    mode.add_argument("--interactive", action="store_true")
    parser.add_argument("--candidate", type=Path, help="可选的本地候选计划，用于审核和重排")
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("out"))
    args = parser.parse_args(argv)
    try:
        plan_path, report_path = (args.out_dir / name for name in ("plan.json", "report.json"))
        inputs = [path.resolve() for path in (args.metrics, args.activities, args.context, args.answers, args.candidate) if path]
        if any(path.resolve() in inputs for path in (plan_path, report_path)):
            raise ValueError("输入与输出路径不得重合")
        metrics = read_verified(args.metrics)
        activities = read_verified(args.activities) if args.activities else None
        context = load_json(args.context) if args.context else None
        candidate = load_json(args.candidate) if args.candidate else None
        answerer = answers_from_file(args.answers, metrics["athlete_id"]) if args.answers else (
            prompt_answers if args.interactive else None)
        rules = load_rules()
        assessed = run_agent(metrics, activities=activities, context=context, answerer=answerer, rules=rules)
        plan = generate_plan(metrics, assessed, rules, activities=activities, context=context, candidate=candidate)
        timestamp = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat()
        report = build_report(metrics, assessed, plan, rules, generated_at=timestamp)
        documents = [(plan_path, plan), (report_path, report)]
        payloads = []
        for path, doc in documents:
            if errors := validate_document(path, doc):
                raise ValueError(f"{path.name} 未通过校验：{errors[0]}")
            payloads.append((path, json.dumps(doc, ensure_ascii=False, allow_nan=False, indent=2) + "\n"))
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for path, text in payloads:
            path.write_text(text, encoding="utf-8", newline="\n")
    except (OSError, KeyError, TypeError, OverflowError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    for attempt in plan["attempts"]:
        state = "通过" if all(info["passed"] for info in attempt["checks"]) else "打回"
        print(f"第 {attempt['round']} 轮 {state}，周 TRIMP {attempt['planned_trimp']:.2f}。")
    print(f"{plan['status']} · 已写出 {plan_path} 和 {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
