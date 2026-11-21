# P5 本机训练报告与演示

```bash
python -m src.pipeline --demo --serve
```

在浏览器打开终端打印的 `/live` 链接。演示只需本机 Python 和浏览器，断网也可以完成。按 Ctrl+C 停止服务。

1. 点击「运行草案演示」，看逐日 TRIMP 和 7 天下周安排。展开「查看计划自检记录」，看第一轮因超量和缺少规则依据被打回，以及重排后的检查结果。
2. 点击「运行复核演示」，展开 R15 查看条款与出处，确认人工复核状态会暂停下周排课。
3. 展开「导入自己的 CSV」，选择中间格式、Garmin 或华为导出，填写计算参数，提交后查看导入体检。页面列出追问时，可填写已知项并复算。

浏览器导入支持 2 MB 以内的 CSV，两份可选补充 JSON 每份上限 256 KB。JSON 的 `athlete_id` 须与页面的匿名 ID 一致。只有确定导出覆盖完整时才填数据起始日。浏览器通过本机服务处理文件，成功产物独立存放于 `out/pipeline/run-*/`，请用模拟数据做公开演示。

页面从报告读取指标和规则。图表以断点显示缺数据，以零值显示已确认的零负荷；逐日数值可在图表下方展开查看。导入失败保留最近一份成功报告。

## AI 实时分析

在本机预览页展开「连接 API」，选择支持 Chat Completions 的 HTTPS 地址和可用模型。

| 服务 | API 基础地址 | 模型示例 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-5-mini` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-flash` |
| 其他兼容服务 | 服务商提供的 HTTPS 基础地址 | 账户可调用的模型名称 |

填入自己的 API 密钥，点击「连接并分析」。模型会解读当前报告，随后每次生成新报告都调用一次，按服务商规则计费。页面保留原有指标和计划。需要停止后续请求时，点击「断开 AI」或关闭标签页。配置和模型解读保留在当前标签页内。

模型收到的内容包括负荷汇总、可用天数、规则信号和待补项类型。原始 CSV、个人标识、具体会话日期和手工补答原文保存在本机。API 授权失败、无网络或限流时，页面显示错误并继续提供本机报告。

[OpenAI 接口说明](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) · [DeepSeek 接口说明](https://api-docs.deepseek.com/)

## 独立调试

页面也可读取模拟报告。分别运行下列命令，再打开 `http://127.0.0.1:8000`。实时导入和补答使用前面的 `--serve` 入口。

```bash
python contracts/mock_api.py --port 8080
python -m http.server 8000 -d src/p5_web
```
