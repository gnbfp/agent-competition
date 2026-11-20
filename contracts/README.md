# contracts —— 接口契约（唯一真源）

五个人共用同一套"什么算对"的定义。**代码可以重写，这里的文件不许悄悄改。**

## 文件

| 文件 | 作用 |
|---|---|
| `activity.schema.json` | P2 解析器产出：原始活动数据 |
| `metrics.schema.json` / `metrics.v2.schema.json` | P3 指标契约 v1 / v2。校验器按 `schema_version` 选择，当前计算命令输出 v2。 |
| `plan.schema.json` / `plan.v2.schema.json` | P4 的计划契约 v1 / v2。v2 包含草案状态及每轮自检。 |
| `report.schema.json` / `report.v2.schema.json` | P4 的报告契约 v1 / v2，P5 读取报告。 |
| `samples/*.json` | 黄金样例：全队共同的分母 |
| `validate_contract.py` | 校验器（仅标准库，不需要 pip install） |
| `mock_api.py` | 假后端：P5 第一天就能开发 |
| `CHANGELOG.md` | 每次契约变更记一行 |

独立的指标 v2 使用 `null` 表达无法计算的数据，并保留估算和派生指标的输入。报告 v2 嵌入指标 v2 与计划 v2。旧样例仍按 v1 校验和展示。两套契约的嵌入结构由测试检查，避免各自修改后不一致。

模拟 API 的 `/api/metrics` 和 `/api/report` 默认返回 v1，添加 `?version=2.0` 可读 v2。工具校验的是本仓库采用的 JSON Schema 子集，支持对象属性、必填项、类型、枚举、数值范围、正则与同构数组。遇到尚未实现的约束（例如 `minItems` 或 `$ref`）会直接失败，新增约束时需同时补校验实现和测试。

实际导入默认使用匿名 ID `anon_01`，样例 `ATH-001` 是固定测试 ID。配对的活动、补充量测和指标必须沿用同一个 `athlete_id`。

## 三条命令

```bash
python contracts/validate_contract.py              # 校验 samples（应 7 个 PASS）
python contracts/validate_contract.py --dir out/   # 校验自己产出的数据
python contracts/mock_api.py --port 8080 --delay 300
```

## 规矩

1. 只加可用字段 = 小版本（1.0 → 1.1）；改类型/改单位/删字段/改必填 = 大版本（→ 2.0）。
2. 改 schema 必须四处同步：schema、samples、生产代码、消费代码。
3. 校验不通过不合并；`--dir` 跑自己的输出目录，退出码非 0 就修。
4. 枚举值只许用固定表里的值，不许自由文本。
5. 缺失一律 `null`，不许 `0` / `""` / `-1`。

## 单位（最常出错）

- 时长 `_s` 秒；距离 `_m` 米；配速 `_s_per_km` **秒/公里**（6'00" = 360）
- 心率 bpm 整数；占比 0–100；比率是小数（ACWR 1.62 不是 162%）
- 日期使用 `YYYY-MM-DD`，时间戳使用带 `+08:00` 的 ISO 8601。仓库文本和生成的中间文件使用 UTF-8 无 BOM，本地 CSV 入口兼容 UTF-8 BOM 和 GBK。
