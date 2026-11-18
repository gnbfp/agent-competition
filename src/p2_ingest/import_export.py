#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2 数据入口（命令行）：手表/App 原始导出 CSV → 中间格式 CSV → activity.json。

两段流水线，各管一件事：
    原始导出  --format_adapters-->  中间格式 CSV  --csv_parser-->  activity.json
中间格式 CSV 会留在 out/ 目录里，方便 P1 目视核对、也方便复跑。

用法：
    python src/p2_ingest/import_export.py data/raw/garmin_export.csv --from garmin
    python src/p2_ingest/import_export.py data/raw/huawei_export.csv -o out/huawei_activity.json
    python src/p2_ingest/import_export.py data/raw/xxx.csv --list-formats

退出码：0 成功；1 文件/格式问题；2 中间 CSV 产出了但校验有丢弃行且带了 --strict。
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys

import format_adapters
import csv_parser

MAX_WARNINGS_SHOWN = 20


def read_raw_csv(path: pathlib.Path) -> tuple[list[str], list[dict]]:
    """读原始导出 CSV；返回 (表头, 行字典列表)。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise format_adapters.AdapterError(f"{path} 是空文件，没有表头")
        return list(reader.fieldnames), list(reader)


def write_middle_csv(path: pathlib.Path, rows: list[dict]) -> None:
    """把中间格式行落盘（UTF-8 无 BOM、LF），作为可复查的中间产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(format_adapters.MIDDLE_COLUMNS),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def show_warnings(warnings: list[str]) -> None:
    """打印转换警告；太多时只显示前若干条，并说明剩余数量。"""
    for warning in warnings[:MAX_WARNINGS_SHOWN]:
        print(f"  [警告] {warning}")
    if len(warnings) > MAX_WARNINGS_SHOWN:
        print(f"  [警告] 其余 {len(warnings) - MAX_WARNINGS_SHOWN} 条同类警告已省略")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="原始导出 CSV → 中间格式 → activity.json")
    parser.add_argument("raw_path", help="手表/App 导出的原始 CSV")
    parser.add_argument("-o", "--out", default="out/activity.json", help="activity.json 输出路径")
    parser.add_argument("--from", dest="source", default=None,
                        help="强制指定格式：garmin / huawei（默认按表头自动识别）")
    parser.add_argument("--middle", default=None,
                        help="中间格式 CSV 输出路径（默认 out/<原文件名>_middle.csv）")
    parser.add_argument("--athlete", default=csv_parser.DEFAULT_ATHLETE, help="匿名 ID，如 anon_01")
    parser.add_argument("--strict", action="store_true", help="有丢弃行就以退出码 1 结束")
    parser.add_argument("--list-formats", action="store_true", help="列出已支持的格式后退出")
    args = parser.parse_args(argv)

    if args.list_formats:
        for name, spec in format_adapters.ADAPTER_SPECS.items():
            print(f"{name:8s} {spec['label']}")
        return 0

    raw_path = pathlib.Path(args.raw_path)
    if not raw_path.exists():
        print(f"FAIL 找不到 {raw_path}")
        return 1

    try:
        fieldnames, rows = read_raw_csv(raw_path)
    except format_adapters.AdapterError as exc:
        print(f"FAIL {exc}")
        return 1
    if not rows:
        print(f"FAIL {raw_path} 只有表头，没有数据行")
        return 1

    source = args.source
    if source is None:
        source = format_adapters.detect_format(fieldnames)
        if source is None:
            print(f"FAIL 认不出格式，表头是：{fieldnames}")
            print("     用 --from 手动指定，或先看 docs/P2_导入适配说明.md")
            return 1
        print(f"自动识别格式：{source}（{format_adapters.ADAPTER_SPECS[source]['label']}）")
    elif source not in format_adapters.ADAPTER_SPECS:
        print(f"FAIL 不支持的格式 {source!r}，可选：{', '.join(format_adapters.ADAPTER_SPECS)}")
        return 1

    try:
        adapted, warnings = format_adapters.adapt(fieldnames, rows, source)
    except format_adapters.AdapterError as exc:
        print(f"FAIL {exc}")
        return 1

    out_path = pathlib.Path(args.out)
    if not out_path.stem.startswith("activity"):
        print(f"提示 输出文件名建议以 activity 开头（本次 {out_path.name}）："
              "contracts/validate_contract.py 靠文件名判断用哪份 schema。")
    middle_path = (pathlib.Path(args.middle) if args.middle
                   else out_path.parent / f"{raw_path.stem}_middle.csv")
    write_middle_csv(middle_path, adapted)
    print(f"读入 {len(rows)} 行 → 中间格式 {len(adapted)} 行，已写出 {middle_path}")
    show_warnings(warnings)

    csv_parser_args = [str(middle_path), "-o", str(out_path), "--athlete", args.athlete]
    if args.strict:
        csv_parser_args.append("--strict")
    return csv_parser.main(csv_parser_args)


if __name__ == "__main__":
    sys.exit(main())
