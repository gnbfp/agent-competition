"""Run the complete local CSV-to-report pipeline and optionally serve the result."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts.validate_contract import load_json, validate_document
from src.p2_ingest import csv_parser, format_adapters, import_export
from src.p2_ingest.csv_input import read_csv
from src.p3_metrics.compute import TRIMP_COEFFICIENTS, compute_metrics, parse_date
from src.p4_agent.evidence import load_rules
from src.p4_agent.followup import prompt_answers
from src.p4_agent.planner import generate_plan
from src.p4_agent.report import build_report
from src.p4_agent.run import answers_from_file, run_agent
from src.report_server import serve_report


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LOCAL_TIME = timezone(timedelta(hours=8))


class PipelineError(RuntimeError):
    """A named pipeline stage could not be completed."""


@contextmanager
def stage(name):
    try:
        yield
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise PipelineError(f"[{name}] {exc}") from exc


def read_object(path: Path | None) -> dict | None:
    if path is None:
        return None
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 应为 JSON 对象")
    return data


def write_document(path: Path, document: dict) -> None:
    if errors := validate_document(path, document):
        raise ValueError(f"{path.name} 未通过契约校验：{errors[0]}")
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def import_csv(path: Path, work: Path, source: str, athlete: str, strict: bool) -> tuple[dict, dict]:
    headers, rows, encoding = read_csv(path)
    if source == "auto":
        source = ("middle" if set(csv_parser.REQUIRED_FIELDS) <= set(headers)
                  else format_adapters.detect_format(headers))
    if not rows:
        raise ValueError("CSV 没有活动数据行")
    if source == "middle":
        csv_parser.validate_middle_headers(headers)
        warnings = []
    elif source in format_adapters.ADAPTER_SPECS:
        rows, warnings = format_adapters.adapt(headers, rows, source)
        import_export.write_middle_csv(work / "activities_middle.csv", rows)
        import_export.show_warnings(warnings)
    else:
        raise ValueError("无法识别 CSV 表头，请检查格式或指定 --source")

    activity_path = work / "activity.json"
    quality_path = work / "import_quality.json"
    result = csv_parser.import_rows(rows, activity_path, source_name=path.name, encoding=encoding,
                                    athlete_id=athlete, strict=strict, adapter_warning_count=len(warnings),
                                    quality_path=quality_path)
    if result:
        raise ValueError("严格导入未通过，存在丢弃或设备异常记录")
    activity = load_json(activity_path)
    quality = load_json(quality_path)
    if not quality["accepted_rows"]:
        raise ValueError("本次导入没有可用的活动记录")
    if errors := validate_document(activity_path, activity):
        raise ValueError(f"activity.json 未通过校验：{errors[0]}")
    return activity, quality


def run_pipeline(args: argparse.Namespace) -> Path:
    with stage("准备运行目录"):
        args.out_dir.mkdir(parents=True, exist_ok=True)
        temp = TemporaryDirectory(dir=args.out_dir, prefix=".building-")
    with temp as directory:
        work = Path(directory)
        with stage("P2 导入"):
            activity, quality = import_csv(args.csv, work, args.source, args.athlete, args.strict)
        partial = quality["skipped_rows"] > 0 or quality["device_anomaly_rows"] > 0
        with stage("P3 指标"):
            as_of = parse_date(args.as_of)
            history_start = parse_date(args.history_start) if args.history_start else None
            if history_start is not None and history_start > as_of:
                raise ValueError("历史覆盖起始日不得晚于计算日")
            metrics = compute_metrics(
                activity, as_of=as_of, history_start=None if partial else history_start,
                resting_hr=args.resting_hr, max_hr=args.max_hr, profile=args.trimp_profile,
                measurements=read_object(args.measurements),
            )
            if partial:
                metrics["flags"].append({"code": "P2_IMPORT_PARTIAL", "level": "medium",
                                         "message": "有活动被丢弃或旁路，未按完整历史处理。"})
            write_document(work / "metrics.json", metrics)

        with stage("P4 评估"):
            context = read_object(args.context)
            if context is None:
                context = {"athlete_id": args.athlete}
            context["import_quality"] = {key: quality[key] for key in ("incomplete_rows", "device_anomaly_rows")}
            answerer = (answers_from_file(args.answers, args.athlete) if args.answers else
                        prompt_answers if args.interactive else None)
            rules = load_rules()
            assessment = run_agent(metrics, activities=activity, context=context, answerer=answerer, rules=rules)

        with stage("P4 计划与报告"):
            plan = generate_plan(metrics, assessment, rules, activities=activity, context=context,
                                 candidate=read_object(args.candidate))
            timestamp = datetime.now(LOCAL_TIME).replace(microsecond=0).isoformat()
            report = build_report(metrics, assessment, plan, rules, generated_at=timestamp)
            write_document(work / "plan.json", plan)
            write_document(work / "report.json", report)
        with stage("发布产物"):
            run_id = f"run-{datetime.now(LOCAL_TIME):%Y%m%d-%H%M%S}-{uuid4().hex[:12]}"
            result = args.out_dir / run_id
            work.rename(result)
    return result


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 CSV 一键生成本地计划和报告")
    parser.add_argument("csv", type=Path, nargs="?")
    parser.add_argument("--demo", action="store_true", help="运行仓库的模拟案例")
    parser.add_argument("--source", choices=("auto", "middle", "garmin", "huawei"))
    parser.add_argument("--athlete")
    parser.add_argument("--as-of")
    parser.add_argument("--history-start")
    parser.add_argument("--trimp-profile", choices=TRIMP_COEFFICIENTS)
    parser.add_argument("--resting-hr", type=int)
    parser.add_argument("--max-hr", type=int)
    parser.add_argument("--measurements", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--candidate", type=Path)
    answers = parser.add_mutually_exclusive_group()
    answers.add_argument("--answers", type=Path)
    answers.add_argument("--interactive", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("out/pipeline"), help="存放每次运行目录")
    parser.add_argument("--serve", action="store_true", help="完成后开启本机预览")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port 应在 0–65535 之间")
    if args.demo:
        demo = {"csv": SAMPLE / "activities_sample.csv", "source": "middle", "athlete": "ATH-001",
                "as_of": "2026-11-14", "history_start": "2026-11-08", "trimp_profile": "female",
                "resting_hr": 55, "max_hr": 183, "measurements": SAMPLE / "measurements_sample.json",
                "context": SAMPLE / "risk_context_sample.json"}
        if any(getattr(args, key) is not None for key in (*demo, "candidate", "answers")) or args.interactive:
            parser.error("--demo 使用复现参数，请单独运行或传入自己的 CSV")
        for key, value in demo.items():
            setattr(args, key, value)
    elif any(getattr(args, key) is None for key in ("csv", "as_of", "trimp_profile", "resting_hr", "max_hr")):
        parser.error("请使用 --demo，或提供 CSV、--as-of、--trimp-profile、--resting-hr 和 --max-hr")
    args.source = args.source or "auto"
    args.athlete = args.athlete or csv_parser.DEFAULT_ATHLETE
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_pipeline(args)
        report = result / "report.json"
        print(f"已生成 {report.resolve()}", flush=True)
        if args.serve:
            with stage("本地预览"):
                serve_report(report, args.port)
    except PipelineError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
