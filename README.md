# 运动生理闭环智能体

> 常州大学首届智能体创新大赛 · 赛道三（AI＋跨学科融合创新）
> 把跑步手表的数据翻译成"训练该不该加量、这次心率高是正常还是过度、膝盖疼要不要停"的可解释决策。

项目从跑步记录计算训练负荷、能力估算和恢复指标，给出带依据的复核信号。数据足够且规则允许时生成下周草案，由本人或教练确认。

## 它解决什么

| 现状 | 本项目 |
|---|---|
| 跑步 App 告诉你"下周跑 46 公里" | 展示负荷、规则和草案的依据，有复核信号时暂停自动排课 |
| 心率变化难解释 | 同时展示配速、心率漂移和静息心率基线，缺量测时标明不足 |
| 疼痛了才想起休息 | 主诉疼痛即触发 R15：强制暂停计划，输出就医建议 |
| 数字没有出处 | 每条结论挂 `rule_id`，每条规则挂文献或标准 |

## 仓库结构

```
contracts/   7 份 JSON Schema（指标、计划及报告兼容 v1/v2）、样例、校验器和模拟 API
tools/       环境自检等脚本
src/         p2_ingest（CSV→activity）· p3_metrics（→metrics）· p4_agent（→plan/report）· p5_web（本机报告与演示）
data/        sample（脱敏样例，可进 Git）· raw（原始导出，禁止进 Git）
docs/        文档、AI 使用留痕、答辩材料
tests/       各模块最小测试
```

## 一条命令跑完演示

```powershell
python -m src.pipeline --demo --serve
```

在浏览器打开终端打印的本机预览地址。初始报告使用模拟 CSV，可展开 R15 查看复核依据。点击「运行草案演示」可查看逐日 TRIMP、7 天下周草案，以及候选计划因超量和缺依据被打回后通过自检的记录。两个演示均可断网运行。

可在页面展开「导入自己的 CSV」，填入计算截止日、静息心率、个人最大心率和 TRIMP 系数。导入成功后可直接回答本轮追问并复算。每次成功的报告和导入体检独立存放在 `out/pipeline/run-*/`。页面导入失败时会保留上一次成功的报告。

也可以从命令行导入。命令中的日期和心率是示例参数。只生成文件可省略 `--serve`，按 Ctrl+C 可停止预览。

```powershell
python -m src.pipeline data/raw/my_export.csv --as-of 2026-11-14 --trimp-profile female --resting-hr 55 --max-hr 183 --measurements data/raw/measurements.json --context data/raw/context.json --serve
```

支持自动识别中间格式、Garmin 与华为，也可用 `--source` 指定。仅在导出覆盖完整时提供 `--history-start`。已知有丢弃或旁路时，本次按不完整历史处理；`--strict` 则在导入阶段直接停止。补充 JSON 的 `athlete_id` 须与 `--athlete` 一致，默认是 `anon_01`。

环境要求为 Python 3.12.x、Git ≥ 2.40，无第三方依赖。可用 `python tools/check_env.py` 和 `python contracts/validate_contract.py` 自检。独立联调页面的模拟接口仍可用，见 [P5 使用说明](src/p5_web/README.md)。

## 文档

| 文件 | 内容 |
|---|---|
| [团队统一标准与环境要求.md](团队统一标准与环境要求.md) | 环境、仓库、代码、数据、AI 使用五类规范（动手前必读） |
| [接口契约与数据统一方案.md](接口契约与数据统一方案.md) | 五个人怎么保证前后端数据统一：契约、校验、变更流程 |
| [运动生理闭环智能体-工作流程与五人分工.md](运动生理闭环智能体-工作流程与五人分工.md) | 项目设计、20 条规则、8 个工具、五层验证、五人分工 |
| [docs/AI使用留痕.md](docs/AI使用留痕.md) | AI 产出登记表（每段进仓库的 AI 代码记一行） |

## 数据与隐私

本项目使用真实跑步记录，**健康数据不进仓库**：`data/raw/` 已被 `.gitignore` 拦截；仓库里只放脱敏样例（匿名 ID + 生理指标）。仓库是公开的，任何一次推送都等于公开发布。

## 依据

TRIMP（Banister 1991）、ACWR 与 EWMA（Gabbett 2016 / Williams 2017）、sRPE（Foster 2001）、VO₂max 估算（Uth 2004 / Riegel 1981 / Daniels VDOT）、心率漂移（Friel）、ACSM 运动测试与处方指南。完整出处见工作流程文档附录。
