"use strict";

const live = window.location.pathname === "/live";
const $ = (id) => document.getElementById(id);
const controls = $("local-controls");
const csvForm = $("csv-form");
const answerForm = $("answer-form");
const requestLimit = 2 * 1024 * 1024;
const decisions = {
  draft: ["草案待确认", ""],
  hold_for_review: ["人工复核", "hold"],
  awaiting_input: ["待补数据", "pending"],
};
const kinds = {rest: "休息", easy: "轻松跑", long: "长跑", tempo: "节奏跑",
  interval: "间歇跑", cross: "交叉训练", strength: "力量训练"};
const choiceNames = {measured: "实测", race: "赛事记录", estimated_220_age: "220 减年龄估算"};
const countNames = {input_rows: "总活动行", accepted_rows: "已接纳", skipped_rows: "已跳过",
  incomplete_rows: "信息不全", device_anomaly_rows: "设备异常"};
let busy = false;
let currentReport = null;
let currentUpload = null;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value != null) node.textContent = value;
  return node;
}

function format(value, digits = 1) {
  return Number.isFinite(value) ? value.toLocaleString("zh-CN", {maximumFractionDigits: digits}) : "数据不足";
}

function showStatus(message, error = false) {
  $("run-status").textContent = message;
  $("run-status").classList.toggle("error", error);
}

function setBusy(value) {
  busy = value;
  for (const button of document.querySelectorAll(".sidebar button")) button.disabled = value;
}

async function request(url, options) {
  const response = await fetch(url, {...options, cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || `请求失败（${response.status}）`);
  return data;
}

async function readJSON(file) {
  if (!file) return null;
  if (file.size > 256 * 1024) throw new Error("单份补充 JSON 不得超过 256 KB。");
  try {
    const data = JSON.parse(await file.text());
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error();
    return data;
  } catch {
    throw new Error("补充资料需为 UTF-8 编码的 JSON 对象。");
  }
}

async function readUpload() {
  const fields = csvForm.elements;
  const file = fields.csv.files[0];
  if (!file || !file.size || file.size > requestLimit) throw new Error("请选择 2 MB 以内的非空 CSV 文件。");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunks = [];
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 32768)));
  }
  const options = {
    athlete: fields.athlete.value.trim() || "anon_01",
    source: fields.source.value,
    as_of: fields.as_of.value,
    history_start: fields.history_start.value || null,
    trimp_profile: fields.trimp_profile.value,
    resting_hr: fields.resting_hr.valueAsNumber,
    max_hr: fields.max_hr.valueAsNumber,
  };
  return {
    mode: "csv", csv: btoa(chunks.join("")), options,
    measurements: await readJSON(fields.measurements.files[0]),
    context: await readJSON(fields.context.files[0]),
  };
}

async function run(makePayload) {
  if (busy) return;
  setBusy(true);
  showStatus("正在生成训练报告…");
  try {
    const payload = await makePayload();
    const result = await request("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    currentUpload = payload.mode === "csv" ? payload : null;
    renderReport(result.report);
    renderQuality(result.import_quality);
    showStatus("报告已更新。");
  } catch (error) {
    showStatus(`${error.message || "生成报告失败。"}${currentReport ? " 上一次成功的报告仍可查看。" : ""}`, true);
  } finally {
    setBusy(false);
  }
}

function renderQuality(counts) {
  $("quality").hidden = !counts;
  if (!counts) return;
  $("quality-stats").replaceChildren(...Object.entries(countNames).map(([key, label]) => {
    const stat = element("div");
    stat.append(element("dt", label), element("dd", format(counts[key], 0)));
    return stat;
  }));
}

function renderQuestions(questions) {
  $("followup").hidden = !live || !questions.length;
  const canAnswer = currentUpload !== null;
  const submit = answerForm.querySelector("button");
  submit.hidden = !canAnswer;
  $("question-note").textContent = canAnswer ? "可先回答已知项，再复算报告。"
    : "从页面导入该 CSV 后，可提交答复并复算。";
  $("questions").replaceChildren(...questions.map((question) => {
    const label = element("label", question.prompt);
    if (!canAnswer) return label;
    const input = element(question.type === "number" ? "input" : "select");
    input.name = question.key;
    if (question.type === "number") {
      input.type = "number";
      input.min = 0;
      input.max = 24;
      input.step = "any";
    } else {
      const options = question.type === "boolean" ? {true: "是", false: "否"} : choiceNames;
      const values = question.choices || Object.keys(options);
      input.add(new Option("待补充", ""));
      for (const value of values) input.add(new Option(options[value] || value, value));
    }
    label.append(input);
    return label;
  }));
}

function renderOverview(report) {
  const {window, load, capacity, recovery} = report.metrics;
  const [title, style] = decisions[report.plan.status] || ["历史报告", "pending"];
  $("window").textContent = `${window.start} 至 ${window.end}`;
  $("headline").textContent = report.summary.headline;
  $("decision").textContent = title;
  $("decision").className = `pill ${style}`;
  $("metrics").replaceChildren(...[
    ["本周负荷", load.trimp_week, "TRIMP"],
    ["ACWR · EWMA", load.acwr_ewma, ""],
    ["VO₂max", capacity.vo2max.value, "ml/kg/min"],
    ["静息心率变化", recovery.resting_hr_delta, "bpm"],
  ].map(([label, value, unit]) => {
    const card = element("div", null, "metric");
    const reading = element("p", format(value, 2), "metric-value");
    if (unit && Number.isFinite(value)) reading.append(element("span", ` ${unit}`, "metric-unit"));
    card.append(element("p", label, "metric-label"), reading);
    return card;
  }));
}

function drawChart() {
  const data = currentReport?.metrics.load.trimp_daily || [];
  const values = data.map((entry) => entry.trimp).filter(Number.isFinite);
  const canvas = $("load-chart");
  canvas.hidden = !values.length;
  $("chart-empty").hidden = !!values.length;
  if (!values.length) return;

  const {width, height} = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.scale(scale, scale);
  const left = 48;
  const right = width - 16;
  const top = 13;
  const bottom = height - 28;
  const maxValue = Math.max(...values, 1);
  const step = 10 ** Math.floor(Math.log10(maxValue));
  const ceiling = Math.ceil(maxValue / step) * step;
  const x = (index) => left + (right - left) * (data.length === 1 ? 0.5 : index / (data.length - 1));
  const y = (value) => bottom - (bottom - top) * value / ceiling;
  context.font = "11px system-ui";
  context.fillStyle = "#526866";
  context.strokeStyle = "#d7e3de";
  context.lineWidth = 1;
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (const value of [0, ceiling / 2, ceiling]) {
    context.beginPath();
    context.moveTo(left, y(value));
    context.lineTo(right, y(value));
    context.stroke();
    context.fillText(format(value), left - 7, y(value), left - 9);
  }
  context.textAlign = "center";
  const ticks = new Set([0, ...(width >= 440 ? [Math.floor(data.length / 2)] : []), data.length - 1]);
  for (const index of ticks) context.fillText(data[index].date.slice(5), x(index), height - 13);

  context.strokeStyle = "#187c68";
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.beginPath();
  let joined = false;
  data.forEach(({trimp}, index) => {
    if (!Number.isFinite(trimp)) {
      joined = false;
      return;
    }
    if (joined) context.lineTo(x(index), y(trimp));
    else context.moveTo(x(index), y(trimp));
    joined = true;
  });
  context.stroke();
  context.fillStyle = "#187c68";
  data.forEach(({trimp}, index) => {
    if (!Number.isFinite(trimp)) return;
    context.beginPath();
    context.arc(x(index), y(trimp), 2.6, 0, 2 * Math.PI);
    context.fill();
  });
}

function renderRisks(risks) {
  $("risk-count").textContent = `${risks.length} 项信号`;
  $("risk-list").replaceChildren(...risks.map((risk) => {
    const details = element("details", null, `signal ${risk.level}`);
    const summary = element("summary");
    summary.append(element("code", risk.rule_id), ` ${risk.title}`);
    details.append(summary, element("p", risk.evidence.clause),
      element("p", `出处 · ${risk.evidence.source}`, "muted"), element("p", risk.action));
    return details;
  }));
  if (!risks.length) $("risk-list").append(element("p", "本次报告没有列出触发信号。", "empty"));
}

function renderPlan(report) {
  const {plan} = report;
  const refs = new Map(report.evidence.map(({rule_id, ref}) => [rule_id, ref]));
  $("week-start").textContent = `${plan.week_start} 起`;
  const content = $("week-content");
  content.replaceChildren();
  if (plan.days.length) {
    const calendar = element("div", null, "calendar");
    for (const day of plan.days) {
      const card = element("article", null, `day ${day.kind}`);
      card.append(element("p", day.date.slice(5), "eyebrow"), element("h3", kinds[day.kind] || day.kind));
      if (day.duration_min) card.append(element("p", `${format(day.duration_min)} 分钟`));
      if (day.distance_m) card.append(element("p", `${format(day.distance_m / 1000, 2)} km`));
      if (Number.isFinite(day.planned_trimp) && day.kind !== "rest") {
        card.append(element("p", `${format(day.planned_trimp)} TRIMP`));
      }
      if (day.purpose) card.append(element("p", day.purpose));
      if (day.rules.length) {
        const detail = element("details");
        detail.append(element("summary", day.rules.join(" · ")));
        for (const rule of day.rules) {
          const ref = refs.get(rule);
          if (ref) detail.append(element("p", ref));
        }
        card.append(detail);
      }
      calendar.append(card);
    }
    content.append(calendar);
  } else {
    for (const reason of plan.hold_reasons || []) content.append(element("p", reason, "empty"));
  }
  const attempts = plan.attempts || [];
  $("attempts").hidden = !attempts.length;
  $("attempt-list").replaceChildren(...attempts.map((attempt) => {
    const item = element("section", null, "attempt");
    item.append(element("h3", `第 ${attempt.round} 轮 · ${format(attempt.planned_trimp)} TRIMP`));
    for (const check of attempt.checks) {
      item.append(element("p", `${check.code} · ${check.passed ? "通过" : "未通过"} · ${check.detail}`));
    }
    return item;
  }));
  for (const note of report.disclaimers || []) content.append(element("p", note, "plan-note muted"));
}

function renderReport(report) {
  currentReport = report;
  renderOverview(report);
  renderRisks(report.risks);
  renderPlan(report);
  renderQuestions(report.questions || []);
  const daily = report.metrics.load.trimp_daily;
  $("load-values").hidden = !daily.length;
  $("load-list").replaceChildren(...daily.map(({date, trimp}) =>
    element("li", `${date} · ${format(trimp, 2)}`)));
  $("initial-error").hidden = true;
  for (const id of ["overview", "load-panel", "risk-panel", "weekly"]) $(id).hidden = false;
  drawChart();
}

async function init() {
  if (live) {
    controls.hidden = false;
    $("demo").addEventListener("click", () => run(() => ({mode: "demo"})));
    $("review").addEventListener("click", () => run(() => ({mode: "review"})));
    csvForm.addEventListener("submit", (event) => {
      event.preventDefault();
      run(readUpload);
    });
    answerForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (busy || !currentUpload) return;
      const answers = {};
      for (const question of currentReport.questions) {
        const input = answerForm.elements.namedItem(question.key);
        if (!input.value) continue;
        answers[question.key] = question.type === "number" ? input.valueAsNumber
          : question.type === "boolean" ? input.value === "true" : input.value;
      }
      if (!Object.keys(answers).length) {
        showStatus("请至少填写一项答复。", true);
        return;
      }
      run(() => ({...currentUpload, answers: {...currentUpload.answers, ...answers}}));
    });
  } else {
    document.querySelector(".workspace").classList.add("readonly");
  }
  let frame;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(drawChart);
  });
  setBusy(true);
  try {
    if (live) {
      const {report, import_quality} = await request("/api/snapshot");
      renderReport(report);
      renderQuality(import_quality);
    } else {
      renderReport(await request("http://127.0.0.1:8080/api/report"));
    }
  } catch {
    $("initial-error").textContent = live ? "暂时无法读取报告。可运行演示或导入 CSV 重试。"
      : "暂时无法读取报告。请检查本地模拟接口是否已启动。";
    $("initial-error").hidden = false;
  } finally {
    setBusy(false);
  }
}

init();
