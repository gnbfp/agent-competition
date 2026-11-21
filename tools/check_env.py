#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""团队环境自检：一条命令确认你的机器符合《团队统一标准与环境要求》。

用法（在仓库根目录下）：

    python tools/check_env.py
    python tools/check_env.py --verbose

任何一项 FAIL 都不要开始写代码：先把整段输出发到群里。
WARN 不影响开工，但要在当天的站会上说一声。

本脚本只用标准库，Windows / macOS / Linux 都能跑。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 标准：Python 3.12.x（见文档第一节）
PY_OK_MAJOR, PY_OK_MINOR = 3, 12

REQUIRED_FILES = [
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "requirements.txt",
    "contracts/activity.schema.json",
    "contracts/metrics.schema.json",
    "contracts/metrics.v2.schema.json",
    "contracts/samples/metrics_v2_sample.json",
    "contracts/plan.schema.json",
    "contracts/plan.v2.schema.json",
    "contracts/report.schema.json",
    "contracts/report.v2.schema.json",
    "contracts/samples/plan_v2_sample.json",
    "contracts/samples/report_v2_sample.json",
    "contracts/validate_contract.py",
    "contracts/mock_api.py",
    "contracts/rules.json",
    "docs/CSV中间格式.md",
    "src/p2_ingest/csv_parser.py",
    "src/p2_ingest/csv_input.py",
    "src/p2_ingest/format_adapters.py",
    "src/p2_ingest/import_export.py",
    "src/p2_ingest/anonymize.py",
    "src/p3_metrics/compute.py",
    "src/p3_metrics/physiology.py",
    "src/p4_agent/evidence.py",
    "src/p4_agent/risk_context.py",
    "src/p4_agent/risk_rules.py",
    "data/sample/measurements_sample.json",
    "data/sample/risk_context_sample.json",
    "tests/test_csv_parser.py",
    "src/p4_agent/followup.py",
    "src/p4_agent/run.py",
    "src/p4_agent/planner.py",
    "src/p4_agent/report.py",
    "src/pipeline.py",
    "src/report_server.py",
    "src/p5_web/index.html",
    "src/p5_web/dashboard.css",
    "src/p5_web/dashboard.js",
    "data/sample/agent_answers_sample.json",
    "data/sample/demo_activity.csv",
    "data/sample/demo_measurements.json",
    "data/sample/demo_context.json",
    "data/sample/demo_candidate.json",
    "docs/AI使用留痕.md",
    "tools/check_env.py",
]

RESULT: list[tuple[str, str, str]] = []  # (项目, PASS/WARN/FAIL, 说明)


def add(item: str, status: str, detail: str = "") -> None:
    RESULT.append((item, status, detail))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- 1. Python 版本
def check_python() -> None:
    v = sys.version_info
    ok = (v.major, v.minor) == (PY_OK_MAJOR, PY_OK_MINOR)
    detail = f"当前 {v.major}.{v.minor}.{v.micro}（要求 {PY_OK_MAJOR}.{PY_OK_MINOR}.x）"
    if ok:
        add("Python 版本", "PASS", detail)
    else:
        add("Python 版本", "FAIL", detail + " → 卸载重装 3.12.x，或改 PATH 指向 3.12")


# ---------------------------------------------------------------- 2. 必备文件
def check_files() -> None:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    total = len(REQUIRED_FILES)
    if not missing:
        add("必备文件", "PASS", f"{total}/{total} 齐全")
    else:
        add("必备文件", "FAIL", f"缺 {len(missing)} 个：" + "、".join(missing[:6]))


# ---------------------------------------------------------------- 3. 第三方依赖
def check_deps() -> None:
    path = ROOT / "requirements.txt"
    if not path.is_file():
        add("第三方依赖", "FAIL", "requirements.txt 不存在")
        return
    active = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not active:
        add("第三方依赖", "PASS", "0 个（本版只用标准库）")
    else:
        add(
            "第三方依赖",
            "FAIL",
            f"发现 {len(active)} 行依赖声明，本版不允许：" + "；".join(active[:3]),
        )


# ---------------------------------------------------------------- 4. schema 可解析
def check_schemas() -> None:
    files = sorted((ROOT / "contracts").glob("*.schema.json"))
    if not files:
        add("契约 schema", "FAIL", "contracts/ 下没有 *.schema.json")
        return
    bad: list[str] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                bad.append(f"{f.name}: 顶层不是对象")
        except Exception as exc:  # noqa: BLE001 - 自检脚本要捕获所有解析错误
            bad.append(f"{f.name}: {exc}")
    if bad:
        add("契约 schema", "FAIL", "；".join(bad))
    else:
        add("契约 schema", "PASS", f"{len(files)} 份 JSON 全部可解析")


# ---------------------------------------------------------------- 5. 样例过校验器
def check_validator() -> None:
    script = ROOT / "contracts" / "validate_contract.py"
    if not script.is_file():
        add("样例校验", "FAIL", "contracts/validate_contract.py 不存在")
        return
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT / "contracts"),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        add("样例校验", "FAIL", "校验器 120 秒超时")
        return
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        last = [ln for ln in out.strip().splitlines() if ln.strip()]
        add("样例校验", "PASS", last[-1] if last else "退出码 0")
    else:
        first_err = next((ln for ln in out.splitlines() if "ERROR" in ln.upper() or "错误" in ln), "")
        add("样例校验", "FAIL", f"退出码 {proc.returncode} {first_err}".strip())


# ---------------------------------------------------------------- 6/7. 编码与换行
TEXT_SUFFIX = {".py", ".json", ".md", ".html", ".css", ".js", ".txt", ".schema", ".csv"}
SKIP_DIR = {".git", "__pycache__", ".venv", "venv", "node_modules", "out", "dist"}


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIR for part in relative.parts[:-1]) or relative.parts[:2] == ("data", "raw"):
            continue
        if path.suffix.lower() not in TEXT_SUFFIX:
            continue
        try:
            if path.suffix.lower() != ".csv" and path.stat().st_size > 4 * 1024 * 1024:
                continue
        except OSError:
            continue
        yield path


def check_encoding() -> None:
    bom: list[str] = []
    invalid_csv: list[str] = []
    scanned = 0
    for path in iter_text_files():
        scanned += 1
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if content.startswith(b"\xef\xbb\xbf"):
            bom.append(rel(path))
        elif path.suffix.lower() == ".csv":
            try:
                if b"\0" in content:
                    invalid_csv.append(rel(path))
                else:
                    content.decode("utf-8")
            except UnicodeDecodeError:
                invalid_csv.append(rel(path))
    if bom or invalid_csv:
        details = []
        if bom:
            details.append(f"{len(bom)} 个文件带 BOM：" + "、".join(bom[:5]))
        if invalid_csv:
            details.append(f"{len(invalid_csv)} 个 CSV 不是有效 UTF-8 文本：" + "、".join(invalid_csv[:5]))
        add("UTF-8 无 BOM", "FAIL", "；".join(details))
    else:
        add("UTF-8 无 BOM", "PASS", f"扫描 {scanned} 个文本文件")


def check_eol() -> None:
    crlf: list[str] = []
    for path in iter_text_files():
        if path.suffix == ".md":
            continue  # 文档不强制，代码与数据文件才强制
        try:
            chunk = path.read_bytes()[: 2 * 1024 * 1024]
        except OSError:
            continue
        if b"\r\n" in chunk:
            crlf.append(rel(path))
    if crlf:
        add("换行符 LF", "WARN", f"{len(crlf)} 个文件含 CRLF：" + "、".join(crlf[:5]))
    else:
        add("换行符 LF", "PASS", "代码与数据文件全部 LF")


# ---------------------------------------------------------------- 8. Git
def check_git() -> None:
    try:
        proc = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired):
        add("Git", "FAIL", "git 命令不可用 → 安装 Git 并勾选加入 PATH")
        return
    if proc.returncode != 0:
        add("Git", "FAIL", "git --version 执行失败")
        return
    version = proc.stdout.strip().replace("git version ", "")
    major_minor = re.findall(r"\d+", version)[:2]
    ok = len(major_minor) == 2 and (int(major_minor[0]), int(major_minor[1])) >= (2, 40)
    add("Git", "PASS" if ok else "WARN", f"{version}（要求 ≥2.40）")


# ---------------------------------------------------------------- main
def main() -> int:
    check_python()
    check_files()
    check_deps()
    check_schemas()
    check_validator()
    check_encoding()
    check_eol()
    check_git()

    width = max(len(item) for item, _, _ in RESULT) + 2
    print("=" * 62)
    print(" 团队环境自检 · Team Env Check · v1.0")
    print(" 依据：《团队统一标准与环境要求》")
    print("=" * 62)
    for idx, (item, status, detail) in enumerate(RESULT, 1):
        print(f"[{idx}/{len(RESULT)}] {item.ljust(width)}{status:<5}{detail}")
    print("-" * 62)

    passed = sum(1 for _, s, _ in RESULT if s == "PASS")
    warned = sum(1 for _, s, _ in RESULT if s == "WARN")
    failed = sum(1 for _, s, _ in RESULT if s == "FAIL")
    print(f"结果：{passed} PASS / {warned} WARN / {failed} FAIL")

    if failed:
        print("结论：环境不合规，先别开工。把上面整段输出发到群里。")
        return 1
    if warned:
        print("结论：可以开工，但 WARN 项要在站会上说一声。")
        return 0
    print("结论：环境就绪，可以开始写代码。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
