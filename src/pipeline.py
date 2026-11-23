"""Run the complete local CSV-to-report pipeline and optionally serve the result."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
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
from src.p3_metrics.running_summary import compute_running_summary
from src.p4_agent.evidence import load_rules
from src.p4_agent.followup import prompt_answers
from src.p4_agent.planner import generate_plan
from src.p4_agent.report import build_report
from src.p4_agent.run import answers_from_file, run_agent
from src.report_server import serve_report


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LOCAL_TIME = timezone(timedelta(hours=8))
MAX_BROWSER_CSV = 2 * 1024 * 1024


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
            # Persist the normalized observation context for later explicit human review.
            # Only record observations that the rule engine actually accepted; this does
            # not mark any safety risk as approved or create a training prescription.
            checks = {item["rule_id"]: item for item in assessment["checks"]}
            observed_pain = checks["R15"]["observed"].get("pain_reported")
            if type(observed_pain) is bool:
                context["pain_reported"] = observed_pain
            observed_hr_source = checks["R03"]["observed"].get("source")
            if observed_hr_source is not None:
                context["max_hr_source"] = observed_hr_source
            sleep_observed = checks["R16"]["observed"]
            if sleep_observed.get("supplemented_dates"):
                sleep = dict(context.get("sleep_readings") or {})
                for date_key in sleep_observed["supplemented_dates"]:
                    sleep[date_key] = sleep_observed["daily_sleep_h"][date_key]
                context["sleep_readings"] = sleep
            (work / "context.json").write_text(
                json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

        with stage("P4 计划与报告"):
            plan = generate_plan(metrics, assessment, rules, activities=activity, context=context,
                                 candidate=read_object(args.candidate))
            timestamp = datetime.now(LOCAL_TIME).replace(microsecond=0).isoformat()
            running = compute_running_summary(activity, as_of, history_start if not partial else None)
            report = build_report(metrics, assessment, plan, rules, generated_at=timestamp, running=running)
            write_document(work / "plan.json", plan)
            write_document(work / "report.json", report)
        with stage("发布产物"):
            source_kind = "demo" if getattr(args, "demo", False) else "csv"
            (work / "source.json").write_text(json.dumps({"kind": source_kind}), encoding="utf-8")
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
    elif any(getattr(args, key) is None for key in ("csv", "as_of")):
        parser.error("请使用 --demo，或提供 CSV 和 --as-of；心率资料可留空生成基础报告")
    args.source = args.source or "auto"
    args.athlete = args.athlete or csv_parser.DEFAULT_ATHLETE
    return args


def browser_run(payload: dict, out_dir: Path) -> Path:
    """Run one browser submission with local-only inputs and server-owned paths."""
    if not isinstance(payload, dict):
        raise ValueError("提交内容应为 JSON 对象。")
    mode = payload.get("mode")
    if mode in ("demo", "review", "missing"):
        if set(payload) != {"mode"}:
            raise ValueError("示例运行使用固定参数。")
        args = parse_args(["--demo", "-o", str(out_dir)])
        if mode in ("demo", "missing"):
            args.csv = SAMPLE / "demo_activity.csv"
            args.history_start = "2026-10-18"
            args.measurements = SAMPLE / "demo_measurements.json"
            args.context = SAMPLE / "demo_context.json"
            args.candidate = SAMPLE / "demo_candidate.json"
            if mode == "missing":
                args.measurements = None  # Intentionally incomplete: the agent must ask, never invent.
        return run_pipeline(args)

    if mode != "csv" or set(payload) - {"mode", "csv", "options", "measurements", "context", "answers"}:
        raise ValueError("请选择手动 CSV 上传或内置功能演示。")
    encoded, options = payload.get("csv"), payload.get("options")
    if not isinstance(encoded, str) or len(encoded) > (MAX_BROWSER_CSV + 2) // 3 * 4:
        raise ValueError("CSV 不得超过 2 MB。")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("CSV 无法解码。") from None
    if not content or len(content) > MAX_BROWSER_CSV:
        raise ValueError("CSV 为空或超过 2 MB。")
    if not isinstance(options, dict) or set(options) - {
        "athlete", "source", "as_of", "history_start", "trimp_profile", "resting_hr", "max_hr",
    }:
        raise ValueError("导入参数无效。")
    athlete = options.get("athlete", "anon_01")
    source = options.get("source", "auto")
    profile = options.get("trimp_profile")
    resting, peak = options.get("resting_hr"), options.get("max_hr")
    if not isinstance(athlete, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", athlete):
        raise ValueError("匿名 ID 应为 1–40 位字母、数字、下划线或连字符。")
    if source not in ("auto", "middle", "garmin", "huawei") or profile not in (None, "female", "male"):
        raise ValueError("请选择有效的 CSV 来源和计算系数。")
    if resting is not None and (type(resting) is not int or not 30 <= resting <= 110):
        raise ValueError("静息心率须在 30–110 之间。")
    if peak is not None and (type(peak) is not int or not 100 <= peak <= 250):
        raise ValueError("最大心率须在 100–250 之间。")
    if resting is not None and peak is not None and peak <= resting:
        raise ValueError("最大心率应高于静息心率。")
    as_of = options.get("as_of")
    history = options.get("history_start")
    parse_date(as_of)
    if history is not None:
        parse_date(history)

    try:
        with TemporaryDirectory(prefix="p5-input-") as work:
            directory = Path(work)
            csv_path = directory / "upload.csv"
            csv_path.write_bytes(content)
            paths = {}
            for key in ("measurements", "context", "answers"):
                supplied = payload.get(key)
                paths[key] = None
                if supplied is None:
                    continue
                if not isinstance(supplied, dict):
                    raise ValueError("补充资料和答复应为 JSON 对象。")
                if key == "answers":
                    supplied = {"athlete_id": athlete, "answers": supplied}
                paths[key] = directory / f"{key}.json"
                paths[key].write_text(json.dumps(supplied, ensure_ascii=False, allow_nan=False),
                                      encoding="utf-8")
            args = argparse.Namespace(csv=csv_path, source=source, athlete=athlete, as_of=as_of,
                                      history_start=history, trimp_profile=profile, resting_hr=resting,
                                      max_hr=peak, out_dir=out_dir, strict=False, interactive=False,
                                      candidate=None, **paths)
            return run_pipeline(args)
    except OSError:
        raise ValueError("暂时无法处理本地导入文件。") from None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_pipeline(args)
        report = result / "report.json"
        print(f"已生成 {report.resolve()}", flush=True)
        if args.serve:
            with stage("本地预览"):
                serve_report(report, args.port, on_run=lambda payload: browser_run(payload, args.out_dir))
    except PipelineError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
