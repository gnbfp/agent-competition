# AI 使用留痕（AI Usage Log）

> 依据《团队统一标准与环境要求》第六节：**凡是 AI 产出并进入了仓库的代码或文档，都要在这里留下一行。**
> 目的不是监管，是三件事：① 出问题时知道去查哪一段；② 答辩时能说清"哪部分是我做的"；③ 避免两个人用 AI 各写一套风格。

## 什么时候要记

| 情况 | 要不要记 |
|---|---|
| AI 生成了要提交的代码（哪怕改了一半） | 要 |
| AI 生成了要交的文档段落（计划书、PPT 文案） | 要 |
| 只是问概念、查报错、让它解释一段已有代码 | 不要 |
| 用 AI 起变量名、写注释 | 不要（但注释仍是你的责任） |

## 记录表

| 日期 | 谁 | 文件 / 模块 | 用的 AI | 让它做了什么 | 我改了什么 | 怎么验证的 |
|---|---|---|---|---|---|---|
| 2026-11-15 | P2 | `src/p2_ingest/csv_parser.py` | DeepSeek | 写"配速 6'30" 转 390 秒"的解析函数 | 补了 `6'60"` 非法值兜底；改成抛 `ValueError` 而不是返回 None | `python -m unittest`，另加 5 条边界用例手测 |
| 2026-11-15 | P5 | `src/p5_web/render.js` | 豆包 | 生成风险等级 → 颜色的映射 | 按契约把 `level` 枚举改成 low/medium/high，去掉它自造的 `critical` | 用 `report_sample.json` 渲染，四个等级逐个看 |
| 2026-11-18 | P2 | `src/p2_ingest/format_adapters.py`、`src/p2_ingest/import_export.py` | DeepSeek | 写"Garmin / 华为导出 → CSV 中间格式"的列名映射与单位归一（时长、配速、距离、心率），并要求解析失败只降级为缺失、不中断整份文件 | 原提交未记录人工修改，节点 02 接手续改见下行记录 | 原分支 40 项单测通过，Garmin 和华为模拟导出生成的 activity JSON 均通过契约校验 |
| 2026-11-18 | P2 | `tests/test_format_adapters.py`、`docs/P2_导入适配说明.md` | DeepSeek | 生成适配器的单测骨架、样例数据与说明文档 | 原提交未记录人工修改，节点 02 接手续改见下行记录 | 原分支 40 项单测通过。两个样例均为模拟数据，已在适配说明中标注 |
| 2026-11-20 | P2 | `src/p2_ingest/format_adapters.py`、`tests/test_format_adapters.py`、`docs/P2_导入适配说明.md` | Codex | 按维护者委托修复节点 02 导入缺陷并复验 | Codex 添加英里配速换算，拦截无法参与计算的数值并沿用现有的逐行警告处理，同时补充回归用例和导入说明 | `python -m unittest discover -s tests`，用两套模拟 CSV 运行 `import_export.py` 后分别运行 `validate_contract.py` |
| 2026-11-20 | P2 | `src/p2_ingest/`、`tools/check_env.py`、`tests/test_ingest_quality.py` | Codex | 按维护者委托实现节点 03 | Codex 统一两条导入入口的 CSV 解码，完善坏行处理和体检报告，补充仓库样例编码检查和活动 JSON 脱敏工具 | `python tools/check_env.py`、`python contracts/validate_contract.py`、`python -m unittest discover -s tests`。验收使用模拟数据 |
| 2026-11-20 | P3 | `src/p3_metrics/compute.py`、`src/p3_metrics/README.md`、`tests/test_training_load.py` | Codex | 按维护者委托实现节点 04 | Codex 实现逐条 TRIMP、周汇总、两种 ACWR 和计算参数溯源，并区分未知日期、零负荷及口径差异 | `python -m unittest discover -s tests -p test_training_load.py`，现有模拟活动运行 `compute.py`，再执行全库自检和单测 |
| 2026-11-20 | P3 | `src/p3_metrics/`、`contracts/`、`tests/test_metrics.py` | Codex | 按维护者委托实现节点 05 | Codex 加入有氧能力和恢复计算，补充指标 v2 缺失值与溯源字段，并保留 v1 校验 | `python tools/check_env.py`、`python contracts/validate_contract.py`、`python -m unittest discover -s tests`，用模拟量测生成并校验指标 v2 |
|  |  |  |  |  |  |  |

**填写要点**

- 「让它做了什么」写**任务范围**，不用贴完整 prompt（prompt 太长时写一句话概述即可）。
- 「我改了什么」必须写具体：改了字段名、加了边界、换了算法、删了它臆造的引用……
  如果答案是"没改"，那要特别小心——**没改的 AI 代码最容易在答辩现场被问倒**。
- 「怎么验证的」必须是一条**能复现的命令或操作**，不许写"看了一遍""感觉没问题"。

## 三条红线（违反直接打回，见文档第八节）

1. **编造依据**：AI 给的文献、标准条款、数字，凡没查到原文的一律不许写进代码或文档。
2. **泄露隐私**：真实姓名、GPS 轨迹、心跳原始数据不进任何公共 AI 对话框。
3. **提交看不懂的代码**：评审会让你现场解释，解释不了就是没过。
