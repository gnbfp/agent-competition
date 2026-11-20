"""Run the local assessment loop and optionally answer its follow-up questions."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.validate_contract import load_json
from src.p4_agent.evidence import load_rules, retrieve_evidence
from src.p4_agent.followup import apply_answers, prompt_answers, questions_for
from src.p4_agent.risk_rules import evaluate_rules, read_verified


def run_agent(metrics: dict, *, activities: dict | None = None, context: dict | None = None,
              answerer: Callable[[list[dict]], dict] | None = None,
              evidence_query: str | None = None, rules: dict[str, dict] | None = None) -> dict:
    rulebook = rules if rules is not None else load_rules()
    trace = []
    phases = []

    def tool(name: str, status: str, notes: str) -> None:
        trace.append({"step": len(trace) + 1, "tool": name, "status": status, "notes": notes})

    def phase(name: str, notes: str) -> None:
        phases.append({"phase": name, "notes": notes})

    def observe(snapshot: dict) -> dict[str, str]:
        states = {item["rule_id"]: item["status"] for item in snapshot["checks"]}
        counts = Counter(states.values())
        phase("Observe", f"命中 {counts['triggered']} 条，证据不足 {counts['insufficient_data']} 条。")
        return states

    def assess(observations: dict | None) -> dict:
        phase("Act", "调用规则判断工具。")
        snapshot = evaluate_rules(metrics, activities=activities, context=observations, rules=rulebook,
                                  allow_missing_evidence=True)
        tool("check_risk", "ok", f"已检查 {len(snapshot['checks'])} 项。")
        return snapshot

    phase("Plan", "检查 R01–R18，按缺失观测选择追问，复核命中的规则依据。")
    if activities is not None:
        tool("load_activities", "ok", "使用同一跑者的活动记录作为规则输入。")
    snapshot = assess(context)
    initial_states = observe(snapshot)
    asked = questions_for(snapshot["checks"])
    used = 0
    if asked:
        if answerer is None:
            tool("ask_athlete", "skipped", f"{len(asked)} 项追问待答。")
        else:
            updated, used = apply_answers(context, snapshot["athlete_id"], asked, answerer(asked))
            tool("ask_athlete", "ok", f"收到 {used}/{len(asked)} 项有效答复。")
            if used:
                snapshot = assess(updated)
                observe(snapshot)
    elif answerer is not None:
        # A saved answer file may be stale. Check it even when no follow-up is needed.
        apply_answers(context, snapshot["athlete_id"], asked, answerer(asked))

    evidence_gaps = []
    for check in snapshot["checks"]:
        rule_id = check["rule_id"]
        if check["status"] != "triggered" and check["evidence"] is not None:
            continue
        found = trace_lookup(rule_id, rulebook, tool)
        check["evidence"] = found["evidence"]
        if not found["evidence"]:
            evidence_gaps.append(rule_id)
    evidence_match = trace_lookup(evidence_query, rulebook, tool) if evidence_query else None

    pending = questions_for(snapshot["checks"])
    changed = [{"rule_id": item["rule_id"], "before": initial_states[item["rule_id"]], "after": item["status"]}
               for item in snapshot["checks"] if initial_states[item["rule_id"]] != item["status"]]
    expected_ids = {f"R{index:02d}" for index in range(1, 19)}
    checked_ids = {item["rule_id"] for item in snapshot["checks"]}
    complete = len(snapshot["checks"]) == len(expected_ids) and checked_ids == expected_ids
    gate = snapshot["planning_gate"]
    high_ids = {risk["rule_id"] for risk in snapshot["risks"] if risk["level"] == "high"}
    gated = not high_ids or (gate["status"] == "hold_for_review" and high_ids <= set(gate["rule_ids"]))
    passed = complete and gated and not evidence_gaps
    phase("Self-check", "校验规则覆盖、依据和人工复核门。" if passed else "有依据或状态需要人工复核。")
    if not passed:
        snapshot["risks"] = [risk for risk in snapshot["risks"] if risk["rule_id"] not in evidence_gaps]
        gate = {"status": "hold_for_review", "rule_ids": sorted(set(gate["rule_ids"]) | set(evidence_gaps))}
    status = ("hold_for_review" if gate["status"] == "hold_for_review" else
              "awaiting_input" if pending else "assessment_ready")
    explanations = {
        "hold_for_review": "当前结果需要人工复核。",
        "awaiting_input": "还有追问待答，相关规则保留证据不足。",
        "assessment_ready": "本轮规则评估已完成。",
    }
    tool("explain", "ok", explanations[status])
    return {**snapshot, "planning_gate": gate, "status": status, "agent_trace": trace, "phases": phases,
            "questions": pending, "asked_count": len(asked), "answer_count": used, "changed_checks": changed,
            "self_check": {"passed": passed, "checks_complete": complete, "high_risks_gated": gated,
                           "missing_evidence_rule_ids": evidence_gaps}, "evidence_lookup": evidence_match}


def trace_lookup(query: str, rules: dict[str, dict], record: Callable[[str, str, str], None]) -> dict:
    found = retrieve_evidence(query, rules)
    for index, attempt in enumerate(found["attempts"]):
        last = index == len(found["attempts"]) - 1
        status = "ok" if attempt["status"] == "found" else "failed" if last else "retry"
        notes = f"{found['rule_id']} 依据匹配。" if status == "ok" else "规则编号未命中，改查名称或同义词。"
        if status == "failed":
            notes = "两次查询均未找到规则依据。"
        record("retrieve_evidence", status, notes)
    return found


def answers_from_file(path: Path, athlete_id: str) -> Callable[[list[dict]], dict]:
    document = load_json(path)
    if (not isinstance(document, dict) or set(document) != {"athlete_id", "answers"}
            or document["athlete_id"] != athlete_id or not isinstance(document["answers"], dict)):
        raise ValueError("答复文件需含相同的 athlete_id 和 answers 对象")
    return lambda _: document["answers"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行本地风险评估和追问")
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--activities", type=Path)
    parser.add_argument("--context", type=Path)
    answer_mode = parser.add_mutually_exclusive_group()
    answer_mode.add_argument("--answers", type=Path, help="用本地 JSON 回答本轮追问")
    answer_mode.add_argument("--interactive", action="store_true", help="在终端回答本轮追问")
    parser.add_argument("--evidence-query", help="附加一次依据检索演示")
    parser.add_argument("-o", "--out", type=Path, default=Path("out/agent_run.json"))
    args = parser.parse_args(argv)
    try:
        inputs = (args.metrics, args.activities, args.context, args.answers)
        if any(path is not None and path.resolve() == args.out.resolve() for path in inputs):
            raise ValueError("输入与输出路径不得重合")
        metrics = read_verified(args.metrics)
        answerer = None
        if args.answers:
            answerer = answers_from_file(args.answers, metrics["athlete_id"])
        elif args.interactive:
            answerer = prompt_answers
        result = run_agent(metrics, activities=read_verified(args.activities) if args.activities else None,
                           context=load_json(args.context) if args.context else None,
                           answerer=answerer, evidence_query=args.evidence_query)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8", newline="\n")
    except (OSError, KeyError, TypeError, OverflowError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    for step in result["phases"]:
        print(f"{step['phase']}: {step['notes']}")
    print(f"{result['status']} · 已写出 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
