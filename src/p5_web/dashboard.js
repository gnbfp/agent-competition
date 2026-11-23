"use strict";

// RunWise AI · local-first front-end. All numbers and rule outcomes originate from report v2.
const live = window.location.pathname === "/live";
const $ = id => document.getElementById(id);
const csvForm = $("csv-form"), aiForm = $("ai-form"), answerForm = $("answer-form");
const MAX_CSV = 2 * 1024 * 1024;
const decisions = {
  draft: {label:"待确认",style:"",title:"下周计划待确认",focus:"确认下周训练安排",desc:"下周训练计划已生成，执行前需本人或教练确认。",glyph:"✓"},
  hold_for_review:{label:"待复核",style:"hold",title:"下周计划待复核",focus:"存在待复核风险",desc:"有待核对的风险，暂未安排下周训练。",glyph:"!"},
  awaiting_input:{label:"待补充",style:"pending",title:"下周计划待补充资料",focus:"关键资料尚不完整",desc:"部分关键信息缺失，暂未安排下周训练。",glyph:"…"}
};
const kinds = {rest:"休息恢复",easy:"轻松跑",long:"长跑",tempo:"节奏跑",interval:"间歇跑",cross:"交叉训练",strength:"力量训练"};
const kindSymbols = {rest:"☾",easy:"↗",long:"↗",tempo:"⌁",interval:"⚡",cross:"✦",strength:"◆"};
const weekNames = ["周日","周一","周二","周三","周四","周五","周六"];
const countNames = {input_rows:"活动总行数",accepted_rows:"成功接纳",skipped_rows:"被跳过",incomplete_rows:"信息不全",device_anomaly_rows:"设备异常"};
const choiceNames = {measured:"实测",race:"赛事记录",estimated_220_age:"220 减年龄估算"};
let busy=false, reportId=null, currentReport=null, currentQuality=null, canAnswerCurrent=false;
let aiConnection=null, aiRequest=null, aiQuestionRequest=null, chartPeriod="28", chartPoints=[], chartSelection=-1;
let wizardStep=0, cachedCsvText="", historyIndex=[], selectedCompare=null, drawerReturn=null;
let toastTimer;

function el(tag, text=null, className="") {const node=document.createElement(tag);if(className)node.className=className;if(text!==null)node.textContent=String(text);return node;}
function fmt(value,digits=1){return Number.isFinite(value)?value.toLocaleString("zh-CN",{maximumFractionDigits:digits}):"数据不足";}
function dateLabel(iso){if(!iso)return "—";const parts=iso.split("-");const date=new Date(`${iso}T12:00:00`);return `${+parts[1]}月${+parts[2]}日 · ${weekNames[date.getDay()]}`;}
function notice(text,error=false){$("run-status").textContent=text;$("run-status").classList.toggle("error",error);if(!error)toast(text);}
function toast(message){const box=$("toast");box.textContent=message;box.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>box.hidden=true,3600);}
function setBusy(value){busy=value;for(const button of document.querySelectorAll("#local-controls button,#csv-form button,#answer-form button,#plan-adjust"))button.disabled=value;}
async function request(url,options={}){const response=await fetch(url,{...options,cache:"no-store"});const data=await response.json();if(!response.ok)throw new Error(data.message||`请求失败（${response.status}）`);return data;}
let canSupplementCurrent=false;
const sourceLabels = {demo:"演示数据", csv:"已导入的跑步记录", unknown:"来源未记录"};
function showSnapshot({report,import_quality,report_id,source,can_answer,can_supplement}){
 canAnswerCurrent = can_answer === true;
 canSupplementCurrent = can_supplement === true;
 $("plan-supplements").hidden=true;
 $("data-mode").textContent=sourceLabels[source] || sourceLabels.unknown;
if(reportId!==report_id){aiRequest?.abort();aiQuestionRequest?.abort();aiRequest=null;aiQuestionRequest=null;$("ai-result").hidden=true;$("ai-answer").hidden=true;$("ai-ask-form").hidden=true;if(aiConnection)setAiStatus("报告已更新，请重新获取模型解读。");}reportId=report_id||null;currentQuality=import_quality||null;renderReport(report);renderQuality(import_quality);renderDataQuality(report.metrics.flags||[],import_quality);$("ai-panel").hidden=!live||!reportId;if(live&&report.risks.some(r=>r.rule_id==="R15"))refreshPainReviewSource(reportId); if(aiConnection&&$("ai-auto").checked)analyzeCurrentReport(); refreshHistory();}


// V2.7: consumer metrics are sourced from report.running, not from TRIMP or guessed demo values.
let runningMode="distance";
const runningInfo={distance:{label:"每日跑量",unit:"公里",key:"distance_km",color:"#6bbdcc"},
  pace:{label:"平均配速",unit:"秒/公里",key:"pace_s_per_km",color:"#96b9dd"},
  heart:{label:"平均心率",unit:"次/分",key:"avg_hr_bpm",color:"#d6a581"}};
function readablePace(raw){if(!Number.isFinite(raw)||raw<=0)return "未知";
 const m=Math.floor(raw/60),s=Math.round(raw%60);return `${m+Math.floor(s/60)}′${String(s%60).padStart(2,"0")}″`;
}
function renderRunnerDashboard(report){
 const data=report.running;const grid=$("runner-kpis");if(!grid)return;
 const w=data?.week||{},has=!!data,known=has&&(w.sessions>0||w.coverage_confirmed);
 const arr=[
  ["本周跑量",known?fmt(w.distance_km,2):"未记录","公里","route","本周已接纳跑步记录"],
  ["平均配速",readablePace(w.average_pace_s_per_km),"/公里","timer","按总跑步时间与总距离计算"],
  ["跑步次数",known?fmt(w.sessions,0):"未记录","次","footprints","仅统计跑步项目"],
  ["跑步时长",known?fmt(w.duration_min,0):"未记录","分钟","clock","有效跑步累计"],
  ["平均心率",Number.isFinite(w.average_hr_bpm)?fmt(w.average_hr_bpm,0):"未记录","次/分","heart","有心率的跑步才参与统计"]];
 grid.replaceChildren(...arr.map(([label,value,unit,kind,note])=>{
  const card=el("article",null,"runner-kpi");card.append(el("span",label,"runner-kpi-label"));
  const main=el("div",null,"runner-kpi-number");main.append(el("strong",value));if(value!=="未记录"&&value!=="未知")main.append(el("span",unit));card.append(main,el("small",note));
  const key={"本周跑量":"distance","平均配速":"pace","跑步次数":"sessions","跑步时长":"duration","平均心率":"heart"}[label];
  if(key&&window.RunWiseProfessional)card.append(window.RunWiseProfessional.button(key));return card;
 }));
 $("runner-period").textContent=data?.daily?.length>=7?`${data.daily.at(-7).date} — ${data.window.end}`:"暂无跑步记录";
 $("runner-caveat").textContent=has?(
  w.hr_sessions<w.sessions?`心率覆盖 ${w.hr_sessions}/${w.sessions} 次跑步；未记录心率不影响跑量和配速。`:
  "显示的都是已导入跑步记录。缺少记录的日期不会自动当作休息日。"):
  "旧报告没有独立的跑量统计。请重新导入 CSV，生成新版报告。";
 $("running-panel").hidden=!has;
 requestAnimationFrame(drawRunningChart);
}
function drawRunningChart(){
 const canvas=$("running-chart"),report=currentReport,days=report?.running?.daily||[],tip=$("running-empty");
 if(!canvas||!tip)return;const config=runningInfo[runningMode];
 const pairs=days.map((d,i)=>({date:d.date,i,v:d[config.key]})).filter(d=>Number.isFinite(d.v)&&!(runningMode==="pace"&&d.v<=0));
 canvas.hidden=!pairs.length;tip.hidden=!!pairs.length;
 if(!pairs.length){tip.textContent=runningMode==="heart"?"尚未上传有效心率记录。":"暂无可用跑步记录。";return;}
 const rect=canvas.getBoundingClientRect();const width=rect.width,height=rect.height;if(width<1||height<1)return;
 const dpr=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
 const ctx=canvas.getContext("2d");ctx.scale(dpr,dpr);
 const palette=getComputedStyle(document.documentElement);
 const ink=palette.getPropertyValue("--ui-ink").trim(),grid=palette.getPropertyValue("--ui-stroke").trim();
 const L=60,R=width-22,T=23,B=height-43;const high=Math.max(...pairs.map(p=>p.v),1),low=runningMode==="pace"?Math.max(0,Math.min(...pairs.map(p=>p.v))*0.92):0;
 const ceiling=Math.max(high*1.15,low+1);const x=i=>L+(R-L)*(days.length<2?.5:i/(days.length-1));const y=v=>B-(v-low)/(ceiling-low)*(B-T);
 ctx.font="13px system-ui";ctx.fillStyle=ink;ctx.textAlign="right";
 for(const ratio of [0,.5,1]){const value=low+(ceiling-low)*ratio;ctx.strokeStyle=grid;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(L,B-ratio*(B-T));ctx.lineTo(R,B-ratio*(B-T));ctx.stroke();ctx.fillStyle=ink;ctx.fillText(runningMode==="pace"?readablePace(value):value.toFixed(runningMode==="distance"?1:0),L-12,B-ratio*(B-T)+4);}
 ctx.fillStyle=ink;ctx.textAlign="center";for(let i=0;i<days.length;i+=Math.max(1,Math.ceil(days.length/6)))ctx.fillText(days[i].date.slice(5),x(i),height-12);
 if(runningMode==="distance"){
  const bar=(R-L)/days.length*.62;
  for(const p of pairs){ctx.fillStyle=config.color;ctx.globalAlpha=.88;ctx.fillRect(x(p.i)-bar/2,y(p.v),bar,B-y(p.v));}
 }else{
  ctx.strokeStyle=config.color;ctx.lineWidth=3;ctx.lineJoin="round";ctx.lineCap="round";
  ctx.beginPath();let connected=false;days.forEach((d,i)=>{const v=d[config.key];if(!Number.isFinite(v)){connected=false;return;}if(connected)ctx.lineTo(x(i),y(v));else ctx.moveTo(x(i),y(v));connected=true;});ctx.stroke();
  for(const p of pairs){ctx.beginPath();ctx.arc(x(p.i),y(p.v),4,0,Math.PI*2);ctx.fillStyle=config.color;ctx.fill();}
 }
 ctx.globalAlpha=1;canvas.setAttribute("aria-label",`${config.label}：${pairs.length} 个有数值的日期。`);
 $("running-explanation").textContent=runningMode==="distance"?"单位：公里；缺失日期留空":runningMode==="pace"?"配速数值越小表示跑得越快；缺失日期不连线":"单位：次/分；仅包含上传了心率的跑步记录";
}
function registerRunningChart(){
 const canvas=$("running-chart");let selected=27;
 const show=i=>{const days=currentReport?.running?.daily||[];if(!days.length)return;selected=Math.max(0,Math.min(days.length-1,i));const item=days[selected],value=item?.[runningInfo[runningMode].key];
  const valueText=!Number.isFinite(value)?"未记录":runningMode==="pace"?readablePace(value)+"/公里":`${fmt(value,runningMode==="distance"?2:0)} ${runningMode==="distance"?"公里":"次/分"}`;
  $("running-explanation").textContent=`${item.date} · ${valueText}`;};
 canvas.addEventListener("pointermove",event=>{const box=canvas.getBoundingClientRect(),x=event.clientX-box.left;
  show(Math.round((x-60)/(box.width-82)*27));});
 canvas.addEventListener("pointerleave",()=>drawRunningChart());
 canvas.addEventListener("keydown",event=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;event.preventDefault();
  show(event.key==="Home"?0:event.key==="End"?27:selected+(event.key==="ArrowRight"?1:-1));});
 for(const b of document.querySelectorAll("[data-running-mode]"))b.addEventListener("click",()=>{
  runningMode=b.dataset.runningMode;
  for(const v of document.querySelectorAll("[data-running-mode]")){v.classList.toggle("selected",v===b);v.setAttribute("aria-pressed",String(v===b));}
  drawRunningChart();
 });
 $("running-chart-export").addEventListener("click",()=>{
  const source=$("running-chart");if(source.hidden)return toast("暂无可保存的图表。");
  const output=document.createElement("canvas");output.width=1600;output.height=900;const c=output.getContext("2d");
  c.fillStyle="#f7faf8";c.fillRect(0,0,1600,900);c.fillStyle="#173a30";c.font="bold 48px system-ui";c.fillText(`RunWise · ${runningInfo[runningMode].label}`,70,88);
  c.font="25px system-ui";c.fillText(`${currentReport.running.window.start} — ${currentReport.running.window.end}`,70,138);
  c.drawImage(source,70,180,1460,610);c.font="21px system-ui";c.fillText("依据已导入训练记录生成；缺失日期不补零。",70,855);
  output.toBlob(blob=>{if(blob)downloadBlob(`runwise-${runningMode}-${currentReport.running.window.end}.png`,blob);else toast("PNG 导出失败。")},"image/png");
 });
}

function renderOverview(report){
 renderRunnerDashboard(report);
 const meta=decisions[report.plan.status]||decisions.awaiting_input;
 const {window,load,capacity,recovery}=report.metrics;
 const daily=load.trimp_daily||[],recent=daily.slice(-7),prior=daily.slice(-14,-7);
 const complete=recent.length===7&&prior.length===7&&[...recent,...prior].every(d=>Number.isFinite(d.trimp));
 const recentTotal=recent.reduce((sum,d)=>sum+(d.trimp||0),0),priorTotal=prior.reduce((sum,d)=>sum+(d.trimp||0),0);
 const weekFootnote=complete&&priorTotal>0?`较前 7 天 ${recentTotal>=priorTotal?"+":""}${fmt((recentTotal-priorTotal)/priorTotal*100,1)}%`:"缺少可比周数据";
 // Technical VO₂max details remain in data quality; the main card uses a human explanation.
 $("window").textContent=`${window.start} — ${window.end}`;
 $("headline").textContent=report.plan.status==="draft"?report.summary.headline:meta.title;
 $("decision-desc").textContent=meta.desc;
 $("decision").textContent=meta.label;$("decision").className=`hero-status ${meta.style}`;
 const planAvailable=report.plan.status==="draft"&&Array.isArray(report.plan.days)&&report.plan.days.length>0;
 const planLink=$("hero-plan-link"),reportLink=$("hero-report-link"),riskLink=$("hero-risk-link");
 planLink.hidden=!planAvailable;
 reportLink.className=planAvailable?"hero-secondary":"hero-action";
 reportLink.textContent=planAvailable?"训练报告":"查看训练报告";
 riskLink.textContent=!planAvailable&&report.plan.status==="awaiting_input"&&live&&(report.questions||[]).length?"补充资料":"风险提醒";
 riskLink.href=riskLink.textContent==="补充资料"?"#followup":"#risk-panel";
 $("focus-graphic").className=`focus-graphic ${meta.style}`;$("focus-graphic").firstElementChild.textContent=meta.glyph;
 const firstQuestion=Array.isArray(report.questions)?report.questions[0]:null;
 $("focus-title").textContent=report.plan.status==="awaiting_input"&&firstQuestion?"待补充资料":meta.focus;
 $("focus-description").textContent=report.plan.status==="awaiting_input"&&firstQuestion?firstQuestion.prompt:meta.desc;
 $("focus-footnote").textContent=report.plan.status==="draft"?"训练计划需确认":report.plan.status==="awaiting_input"&&report.questions?.length?`${report.questions.length} 项资料待补充`:"风险提醒需复核";
 $("metrics").replaceChildren(...[
  ["最近 7 天训练负荷",load.trimp_week,"负荷值","≈",weekFootnote],
  ["近期和长期训练量对比",load.acwr_ewma,"","⌁",load.acwr_status?`计算状态：${{optimal:"位于项目参考区间",high:"高于参考区间",danger:"明显高于参考区间",undertrained:"低于参考区间",low:"低于参考区间",insufficient:"数据不足",unavailable:"数据不足"}[load.acwr_status]||"未判定"}`:"短期 / 长期负荷比"],
  ["有氧能力（估算）",capacity.vo2max.value,"ml/kg/min","✳",Number.isFinite(capacity.vo2max.value)?"基于可用数据估算":"记录不足，暂时无法可靠估算"],
  ["静息心率和往常比",recovery.resting_hr_delta,"bpm","♡",Number.isFinite(recovery.resting_hr_delta)?"相对于基线变化":"需补充静息心率量测"]
 ].map(([label,value,unit,icon,sub])=>{const card=el("article",null,"metric");const reading=el("p",Number.isFinite(value)?fmt(value,2):"未知","metric-value");if(unit&&Number.isFinite(value))reading.append(el("span",` ${unit}`,"metric-unit"));card.append(el("span",icon,"metric-mini-icon"),el("p",label,"metric-label"),reading,el("p",sub,"metric-footer"));return card;}));
}
function renderQuality(counts){$("quality").hidden=!counts;if(!counts)return;$("quality-stats").replaceChildren(...Object.entries(countNames).map(([key,label])=>{const d=el("div");d.append(el("dt",label),el("dd",fmt(counts[key],0)));return d;}));}
function renderDataQuality(flags,quality){const list=$("data-quality-list");list.replaceChildren();$("data-quality-count").textContent=`${flags.length} 项指标说明`;if(!flags.length){list.append(el("div","暂无额外数据完整性提示，数据来源仍需核实。","quality-ok"));}for(const flag of flags){const row=el("div",null,"quality-flag");row.append(el("code",flag.code),el("p",flag.message));list.append(row);}if(quality&&(quality.skipped_rows||quality.device_anomaly_rows)){const row=el("div",null,"quality-flag");row.append(el("code","P2 导入"),el("p",`跳过 ${quality.skipped_rows} 行，设备异常 ${quality.device_anomaly_rows} 行。系统不将这些记录的负荷计为零，请核对原始文件。`));list.append(row);}$("data-quality").hidden=false;}
function renderQuestions(questions){$("followup").hidden=!live||!questions.length;const canAnswer=canAnswerCurrent;const submit=answerForm.querySelector("button");submit.hidden=!canAnswer;$("question-note").textContent=canAnswer?"填写补充信息后重新计算。":"需先导入对应 CSV，才能补充回答。";$("questions").replaceChildren(...questions.map(question=>{const label=el("label",question.prompt);if(!canAnswer)return label;const input=el(question.type==="number"?"input":"select");input.name=question.key;if(question.type==="number"){input.type="number";input.min="0";input.max="24";input.step="any";}else{const options=question.type==="boolean"?{true:"是",false:"否"}:choiceNames;input.add(new Option("待补充",""));for(const value of question.choices||Object.keys(options))input.add(new Option(options[value]||value,value));}label.append(input);return label;}));}

function getVisibleDaily(){const all=currentReport?.metrics?.load?.trimp_daily||[];return chartPeriod==="all"?all:all.slice(-Number(chartPeriod));}
function setupChartSelectors(){for(const button of document.querySelectorAll("[data-period]"))button.addEventListener("click",()=>{chartPeriod=button.dataset.period;chartSelection=-1;for(const other of document.querySelectorAll("[data-period]")){const active=button===other;other.classList.toggle("selected",active);other.setAttribute("aria-pressed",String(active));}drawChart();});}
function drawChart(){
 const canvas=$("load-chart"),daily=getVisibleDaily(),valid=daily.filter(d=>Number.isFinite(d.trimp));chartPoints=[];
 canvas.hidden=!valid.length;$("chart-empty").hidden=!!valid.length;$("chart-tooltip").hidden=true;
 if(!valid.length)return;
 const rect=canvas.getBoundingClientRect();const width=rect.width,height=rect.height;if(!width||!height)return;
 const dpr=Math.min(devicePixelRatio||1,3);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
 const ctx=canvas.getContext("2d");if(!ctx)return;ctx.scale(dpr,dpr);
 const dark=document.documentElement.classList.contains("dark");
 const ink=dark?"#cbdde8":"#315768",grid=dark?"#426175":"#ccdce5",brand=dark?"#74c7d8":"#14788d";
 const left=47,right=width-16,top=16,bottom=height-32;
 const max=Math.max(...valid.map(d=>d.trimp),1),power=10**Math.floor(Math.log10(max)),ceiling=Math.ceil(max/power)*power;
 const x=i=>left+(right-left)*(daily.length<=1?.5:i/(daily.length-1));const y=v=>bottom-(bottom-top)*(v/ceiling);
 ctx.font="12px system-ui";ctx.textBaseline="middle";ctx.textAlign="right";
 for(const n of [0,ceiling/2,ceiling]){ctx.beginPath();ctx.lineWidth=1;ctx.strokeStyle=grid;ctx.moveTo(left,y(n));ctx.lineTo(right,y(n));ctx.stroke();ctx.fillStyle=ink;ctx.fillText(fmt(n,1),left-10,y(n));}
 ctx.textAlign="center";const step=Math.max(1,Math.ceil(daily.length/(width>=630?6:width>=350?4:3)));
 for(let i=0;i<daily.length;i++){if(i%step===0||i===daily.length-1){ctx.fillStyle=ink;ctx.fillText((daily[i].date||"").slice(5),x(i),height-11);}}
 // Preserve unknown intervals as gaps instead of drawing a misleading continuous line.
 ctx.beginPath();ctx.lineWidth=2.5;ctx.lineJoin="round";ctx.lineCap="round";let linked=false;
 daily.forEach((d,i)=>{if(!Number.isFinite(d.trimp)){linked=false;return;}if(linked)ctx.lineTo(x(i),y(d.trimp));else ctx.moveTo(x(i),y(d.trimp));linked=true;});ctx.strokeStyle=brand;ctx.stroke();
 daily.forEach((d,i)=>{if(!Number.isFinite(d.trimp))return;const point={x:x(i),y:y(d.trimp),date:d.date,value:d.trimp};chartPoints.push(point);const chosen=chartSelection===chartPoints.length-1;ctx.beginPath();ctx.arc(point.x,point.y,chosen?5:3,0,Math.PI*2);ctx.fillStyle=brand;ctx.fill();if(chosen){ctx.beginPath();ctx.arc(point.x,point.y,9,0,Math.PI*2);ctx.strokeStyle=brand;ctx.globalAlpha=.22;ctx.lineWidth=4;ctx.stroke();ctx.globalAlpha=1;}});
 const sum=valid.reduce((a,d)=>a+d.trimp,0);$("chart-insight").textContent=`${daily.length} 个自然日中 ${valid.length} 天有 TRIMP 数值（含零值），${daily.length-valid.length} 天缺失 · 已有数值合计 ${fmt(sum,1)} 负荷值`;
}
function showChartPoint(index){if(index<0||index>=chartPoints.length)return;chartSelection=index;drawChart();const point=chartPoints[index],tip=$("chart-tooltip"),rect=$("load-chart").getBoundingClientRect();tip.replaceChildren(el("span",dateLabel(point.date)),el("strong",`${fmt(point.value,2)} 负荷值`));tip.hidden=false;const tipWidth=145;tip.style.left=`${Math.max(0,Math.min(rect.width-tipWidth,point.x+11))}px`;tip.style.top=`${Math.max(0,point.y-64)}px`;}
function registerChartInteractions(){const canvas=$("load-chart");canvas.addEventListener("pointermove",e=>{if(!chartPoints.length)return;const x=e.clientX-canvas.getBoundingClientRect().left;let best=0;for(let i=1;i<chartPoints.length;i++)if(Math.abs(chartPoints[i].x-x)<Math.abs(chartPoints[best].x-x))best=i;showChartPoint(best);});canvas.addEventListener("pointerleave",()=>$("chart-tooltip").hidden=true);canvas.addEventListener("click",()=>{if(chartSelection>=0&&chartPoints[chartSelection])toast(`${dateLabel(chartPoints[chartSelection].date)}：${fmt(chartPoints[chartSelection].value,2)} 负荷值`);});canvas.addEventListener("keydown",e=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;e.preventDefault();let next=chartSelection<0?0:chartSelection+(e.key==="ArrowRight"?1:-1);if(e.key==="Home")next=0;if(e.key==="End")next=chartPoints.length-1;showChartPoint(Math.max(0,Math.min(chartPoints.length-1,next)));});}

function renderRisks(risks){
 const signals=risks.filter(r=>r.rule_id!=="R05"),references=risks.filter(r=>r.rule_id==="R05");
 $("risk-count").textContent=`${signals.length} 项关注信号 · ${references.length} 项参考提示`;
 $("risk-list").replaceChildren(...risks.map(risk=>{
  const details=el("details",null,`signal ${risk.level} ${risk.rule_id==="R05"?"reference-signal":""}`),sum=el("summary");
  sum.append(el("span",risk.rule_id==="R05"?"参考说明":"请注意","rule-code"),el("span",risk.rule_id==="R05"?"近期训练量处于参考范围":risk.title));
  const content=el("div",null,"signal-detail"),clause=el("p");
  clause.append(el("strong",`检查依据（${risk.rule_id}）：`),document.createTextNode(risk.evidence?.clause||"—"));
  const source=el("p");source.append(el("strong","出处："),document.createTextNode(risk.evidence?.source||"—"));
  const action=el("p");action.append(el("strong","处理建议："),document.createTextNode(risk.action||"—"));
  content.append(clause,source,action);
  if(risk.rule_id==="R15"){
   details.open=true;
   const review=el("div",null,"pain-review");review.id="pain-review";
   review.append(el("h4","R15 · 疼痛记录核对"));
   const explanation=el("p","请根据实际情况核对疼痛记录。确认疼痛不会解除风险；只有来源确实填错且重新评估后，相关提醒才可能改变。","pain-review-intro");review.append(explanation);
   if(live){
    const status=el("p","正在检查本次疼痛记录来源…","pain-review-source");status.id="pain-review-source";review.append(status);
    const form=el("form",null,"pain-review-form");form.id="pain-review-form";
    const fieldset=el("fieldset"),legend=el("legend","目前的真实情况");fieldset.append(legend);
    const options=[
      ["pain_present","确实有疼痛，保留风险提醒","保留 R15；不会自动生成七日计划。"],
      ["context_record_incorrect","近期没有疼痛，之前的补充资料误填","只适用于 context.json 的疼痛标记误填；CSV 有疼痛记录必须更正原文件。"]
    ];
    for(const [value,label,hint] of options){
      const row=el("label",null,"pain-review-choice"),radio=el("input");radio.type="radio";radio.name="pain_review_choice";radio.value=value;radio.required=true;
      const words=el("span");words.append(el("strong",label),el("small",hint));row.append(radio,words);fieldset.append(row);
    }
    form.append(fieldset);
    const ack=el("label",null,"pain-review-confirm"),check=el("input");check.type="checkbox";check.name="confirm";check.required=true;
    ack.append(check,el("span","我已核对原始记录，以上选择属实。"));form.append(ack);
    const actionRow=el("div",null,"pain-review-actions"),button=el("button","保存核对并重新评估","button button-primary");button.type="submit";
    actionRow.append(button);form.append(actionRow);
    const feedback=el("p","","pain-review-feedback");feedback.id="pain-review-feedback";feedback.setAttribute("role","status");form.append(feedback);
    form.addEventListener("submit",async event=>{
      event.preventDefault();if(busy||!reportId)return;
      const chosen=form.querySelector('input[name="pain_review_choice"]:checked');if(!chosen||!check.checked)return;
      button.disabled=true;button.textContent="正在重新检查…";
      try{
       const result=await request("/api/r15-review",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({report_id:reportId,choice:chosen.value,confirmed:true})});
       showSnapshot(result);toast(result.message||"已更新规则判断。");
      }catch(error){feedback.textContent=error.message||"核对失败，请重试。";feedback.classList.add("error");}
      finally{button.disabled=false;button.textContent="保存核对并重新评估";}
    });
    review.append(form);
   }else review.append(el("p","离线预览只显示示例数据。请启动正式服务并导入记录后进行确认。","pain-review-source"));
   content.append(review);
  }
  details.append(sum,content);return details;
 }));
 if(!risks.length)$("risk-list").append(el("p","暂未出现需要重点关注的规则提醒。","empty"));
}
async function refreshPainReviewSource(expectedId){
 const output=$("pain-review-source"),form=$("pain-review-form");if(!output||!form)return;
 try{
  const data=await request("/api/r15-review");
  if(reportId!==expectedId||data.report_id!==expectedId||!output.isConnected)return;
  output.textContent=!data.available?data.message:data.csv_pain?
   "来源：最近 7 天 CSV 含疼痛记录。若记录错误，请先更正 CSV 再重新导入。":
   data.context_pain===true?"来源：补充资料中的 pain_reported = true；若误填可在下面更正。":
   "来源：当前记录仍需核对；建议重新上传原始 CSV 确认。";
  if(!data.available){
   const correction=form.querySelector('input[value="context_record_incorrect"]');
   if(correction){correction.disabled=true;correction.closest("label").querySelector("small").textContent="旧版报告缺少复算上下文。若资料错误，请重新导入 CSV 和补充资料。";}
   output.textContent+=" 你仍可确认疼痛属实并保存记录，但不会重新计算或解除 R15。";
   const link=el("a","重新上传训练数据 →","text-button pain-reimport-link");link.href="#import-panel";output.after(link);
  }else if(data.csv_pain){
   const correction=form.querySelector('input[value="context_record_incorrect"]');
   if(correction){correction.disabled=true;correction.closest("label").querySelector("small").textContent="CSV 的疼痛记录不能直接覆盖。如数据误录，请更正 CSV 后重新上传。";}
   const link=el("a","更正原始文件后重新上传 →","text-button pain-reimport-link");link.href="#import-panel";output.after(link);
  }
 }catch(error){if(reportId===expectedId&&output.isConnected){output.textContent="无法获取来源详情。";form.hidden=true;}}
}

function showDrawer(){drawerReturn=document.activeElement;$("drawer-overlay").hidden=false;$("detail-drawer").hidden=false;$("drawer-close").focus();document.body.style.overflow="hidden";}
function closeDrawer(){if($("detail-drawer").hidden)return;$("drawer-overlay").hidden=true;$("detail-drawer").hidden=true;document.body.style.overflow="";drawerReturn?.focus?.();}
function detailStat(title,value){const node=el("div",null,"detail-stat");node.append(el("span",title),el("strong",value));return node;}
function openDay(day,refs){const content=$("drawer-content"),kind=kinds[day.kind]||day.kind;content.replaceChildren();const hero=el("div",null,"drawer-hero"),heroText=el("div");heroText.append(el("h2",kind),el("p",dateLabel(day.date)));hero.append(el("span",kindSymbols[day.kind]||"○","drawer-icon"),heroText);content.append(hero);const stats=el("div",null,"detail-block"),grid=el("div",null,"detail-stats");grid.append(detailStat("时长",`${fmt(day.duration_min,0)} 分钟`),detailStat("距离",`${fmt(day.distance_m/1000,2)} km`),detailStat("预计训练负荷",fmt(day.planned_trimp,1)),detailStat("参考心率",Number.isFinite(day.reference_avg_hr_bpm)?`${day.reference_avg_hr_bpm} 次/分`:"无"));stats.append(el("h3","训练参数"),grid);content.append(stats);const purpose=el("div",null,"detail-block");purpose.append(el("h3","本次安排的目的"),el("p",day.purpose|| (day.kind==="rest"?"恢复与观察训练状态。":"根据现有训练数据生成的草案，请人工确认。")));content.append(purpose);const rules=el("div",null,"detail-block");rules.append(el("h3","适用规则与出处"));for(const tag of day.rules||[]){const row=el("div",null,"drawer-rule");row.append(el("b",tag+" · "),document.createTextNode(refs.get(tag)||"请在风险与依据模块查阅"));rules.append(row);}if(!day.rules?.length)rules.append(el("p","无规则引用，请复核。"));content.append(rules);const note=el("p","这是规则引擎给出的训练草案，并非已经执行的运动记录。","plan-note");content.append(note);showDrawer();}
function openPlanInputs(report){
 if(canAnswerCurrent && report.questions?.length){
   window.RunWisePages.go("risk");
   $("followup").scrollIntoView({block:"start"});
   $("questions").querySelector("input,select")?.focus({preventScroll:true});
   return;
 }
 window.RunWisePages.go("import");
 if(!canSupplementCurrent){
   // Existing servers and read-only reports can use the regular import form.
   // Keep the file picker on the parameter step so every required input is reachable.
   const fields=csvForm.elements, inputs=report.metrics.load_inputs||{};
   const step=csvForm.querySelector('[data-step="2"]');
   showWizardStep(2);
   step.prepend($("dropzone"));
   fields.as_of.value=report.metrics.window.end;
   fields.athlete.value=report.athlete_id||"anon_01";
   for(const name of ["resting_hr","max_hr","history_start"])fields[name].value=inputs[name]??"";
   fields.trimp_profile.value=inputs.profile||"";
   csvForm.querySelector(".supplements").open=true;
   $("date-range-note").textContent="已带入当前报告参数。请核对原始 CSV，并重新附上适用的量测及训练上下文文件。";
   $("import-status").textContent="补充资料后点击「生成训练报告」。";
   fields.resting_hr.focus();
   return;
 }
 const section=$("plan-supplements"), form=$("plan-supplement-form");
 form.reset();
 const inputs=report.metrics.load_inputs||{};
 for(const name of ["resting_hr","max_hr","history_start"])form.elements[name].value=inputs[name]??"";
 form.elements.trimp_profile.value=inputs.profile||"";
 form.elements.history_start.max=report.metrics.window.end;
 const week=report.running?.week;
 const advice=["可直接补充当前报告，原始跑步记录会继续使用。"];
 if(week?.sessions>0 && week.hr_sessions<week.sessions)advice.push("部分跑步缺少运动心率；如需补齐，请在下方导入包含运动心率的训练记录。");
 if(report.plan.hold_reasons?.some(item=>item.includes("轻松跑")))advice.push("缺少轻松跑参考，请在下方导入训练记录，并在更多资料中附上标注轻松跑日期的训练上下文。");
 $("supplement-guidance").textContent=advice.join(" ");
 const existing=new Map((report.metrics.recovery?.daily||[]).map(d=>[d.date,d.resting_hr_bpm]));
 const dates=(report.metrics.load.trimp_daily||[]).map(row=>row.date).reverse();
 $("daily-resting-inputs").replaceChildren(...dates.map(day=>{
   const label=el("label",day+"（次/分）"),input=el("input");
   input.type="number";input.min="30";input.max="110";input.dataset.day=day;
   if(Number.isFinite(existing.get(day)))input.placeholder="已记录 "+existing.get(day);
   label.append(input);return label;
 }));
 $("daily-measurements").open=report.metrics.recovery?.resting_hr_delta==null;
 $("supplement-status").textContent="";
 section.hidden=false;
 section.scrollIntoView({block:"start"});
 $("supplement-title").focus({preventScroll:true});
}

async function submitPlanInputs(event){
 event.preventDefault();
 if(busy||!canSupplementCurrent)return;
 const form=event.currentTarget,fields=form.elements,button=form.querySelector("button[type=submit]");
 const options={};
 for(const name of ["resting_hr","max_hr"])if(fields[name].value)options[name]=fields[name].valueAsNumber;
 for(const name of ["trimp_profile","history_start"])if(fields[name].value)options[name]=fields[name].value;
 const readings={};
 for(const input of form.querySelectorAll("[data-day]"))if(input.value)readings[input.dataset.day]=input.valueAsNumber;
 setBusy(true);button.disabled=true;
 $("supplement-status").textContent="正在重新计算…";
 try{
   const result=await request("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},
     body:JSON.stringify({mode:"supplement",report_id:reportId,options,daily_resting_hr:readings})});
   showSnapshot(result);window.RunWisePages.go("weekly");
   toast("资料已保存 · 七天计划"+decisions[result.report.plan.status].label);
 }catch(error){$("supplement-status").textContent=error.message;}
 finally{setBusy(false);button.disabled=false;}
}

function renderPlan(report){
 const plan=report.plan,hasPlan=plan.status==="draft"&&Array.isArray(plan.days)&&plan.days.length>0;
 const refs=new Map((report.evidence||[]).map(x=>[x.rule_id,x.ref]));
 $("week-start").textContent=hasPlan?`${plan.week_start} 起 · 请确认后执行`:"";
 $("week-badge").textContent=hasPlan?"待确认":plan.status==="hold_for_review"?"待复核":"待补充";
 $("plan-adjust").hidden=!live||!hasPlan;
 $("plan-bottom").hidden=!hasPlan;
 const content=$("week-content");content.replaceChildren();
 if(hasPlan){
   const calendar=el("div",null,"calendar");
   for(const day of plan.days){
     const card=el("button",null,`day ${day.kind}`);card.type="button";
     card.setAttribute("aria-label",`${dateLabel(day.date)} ${kinds[day.kind]||day.kind}，查看详情`);
     const date=el("div",null,"day-top");date.append(el("span",weekNames[new Date(`${day.date}T12:00:00`).getDay()]),el("span",day.date.slice(5)));
     card.append(date,el("span",kindSymbols[day.kind]||"○","day-symbol"),el("strong",kinds[day.kind]||day.kind),el("small",day.duration_min?`${fmt(day.duration_min,0)} 分钟`:"恢复"),el("span",day.kind==="rest"?"休息":`${fmt(day.planned_trimp,1)} 负荷值`,"day-value"));
     card.addEventListener("click",()=>openDay(day,refs));calendar.append(card);
   }
   content.append(calendar);
   for(const note of report.disclaimers||[])content.append(el("p",note,"plan-note"));
 }else{
   const block=el("div",null,"plan-pending");
   const main=el("div",null,"plan-pending-main");
   const icon=el("span","!","plan-pending-icon");
   const body=el("div",null,"plan-pending-body");
   const reasons=Array.isArray(plan.hold_reasons)?plan.hold_reasons.filter(Boolean):[];
   const needsInput=plan.status==="awaiting_input" && live;
   body.append(el("h3","暂未生成下周计划"),el("p",plan.status==="hold_for_review"?"训练风险需要进一步核对，建议先完成复核再安排下周训练。":"需要补充部分关键资料，补齐后再重新生成七日计划。"));
   if(reasons.length){const detail=el("details",null,"plan-pending-details"),summary=el("summary","待核对事项"),list=el("ul");for(const reason of reasons)list.append(el("li",reason));detail.append(summary,list);body.append(detail);}
   const actions=el("div",null,"plan-pending-actions");
   if(needsInput){
     const fill=el("button","填写缺失资料","button button-primary");
     fill.type="button";
     fill.addEventListener("click",()=>openPlanInputs(report));
     actions.append(fill);
   }
   const reportLink=el("a","查看训练报告",needsInput?"button button-outline":"button button-primary");
   reportLink.href="#review-panel";
   actions.append(reportLink);
   if(!needsInput){
     const riskLink=el("a","风险提醒","button button-outline");
     riskLink.href="#risk-panel";
     actions.append(riskLink);
   }
   body.append(actions);
   main.append(icon,body);
   const side=el("aside",null,"plan-pending-side");
   const badge=el("span",plan.status==="hold_for_review"?"待复核":"待补充","plan-pending-badge");
   const title=el("h4","接下来建议这样处理");
   const list=el("ul");
   const items=plan.status==="hold_for_review"
     ? ["先查看训练报告中的风险评估与训练建议。","如存在疼痛、异常疲劳或主诉，请优先完成 R15 / 风险复核。",reasons.length?`当前待核对 ${reasons.length} 项，处理后再重新生成计划。`:"完成复核后再重新评估下周安排。"]
     : ["先补充缺失资料，再重新计算。","缺资料前不建议据此安排新的高强度训练。",(report.questions||[]).length?`当前还有 ${(report.questions||[]).length} 项资料可补充。`:"填写后将重新检查计划生成条件。"];
   for(const item of items) list.append(el("li",item));
   side.append(badge,title,list);
   block.append(main,side);
   content.append(block);
 }
}
function renderTimeline(plan){const attempts=plan.attempts||[],list=$("attempt-list"),raw=$("attempt-raw");list.replaceChildren();raw.replaceChildren();$("attempts").hidden=!attempts.length;const status=$("timeline-status");if(!attempts.length){status.textContent="未生成草案 · 未进行计划自检";const n=el("div",null,"timeline-entry pending"),rail=el("div",null,"timeline-rail"),body=el("div",null,"timeline-body");rail.append(el("span","i","timeline-bullet"));body.append(el("div","本次没有需要检查的训练计划","timeline-head"),el("p","训练数据分析和报告已生成；由于风险待复核或关键信息不足，没有形成逐日训练草案，因此也没有执行草案的负荷上限与规则覆盖检查。"));const link=el("a","查看训练分析报告 →","report-evidence-link");link.href="#review-panel";body.append(link);n.append(rail,body);list.append(n);return;}
 status.textContent=plan.self_check.passed?"已通过软件检查":"未通过软件检查";
 attempts.forEach((attempt,i)=>{const passed=attempt.checks.every(x=>x.passed),entry=el("div",null,`timeline-entry ${passed?"passed":"failed"}`),rail=el("div",null,"timeline-rail"),body=el("div",null,"timeline-body"),head=el("div",null,"timeline-head"),label=i===0?"首次生成候选计划":passed?"自动修正与再次自检":"重新编排候选计划";head.append(el("strong",label),el("span",passed?"全部通过":"发现问题","timeline-badge"));body.append(head);const value=el("div",null,"timeline-value");value.append(el("b",fmt(attempt.planned_trimp,1)),"训练负荷 · 第 ",String(attempt.round)," 轮");body.append(value);body.append(el("p",passed?"这次安排通过了软件设定的训练负荷上限和规则依据检查，但仍需本人确认。":"首次方案没有通过检查，系统已尝试调整并重新计算。"));for(const check of attempt.checks)body.append(el("span",`${check.code} ${check.passed?"✓":"×"}`,"timeline-rule"));rail.append(el("span",passed?"✓":"!","timeline-bullet"),el("div",null,"timeline-line"));entry.append(rail,body);list.append(entry);const info=el("div",null,"raw-check");info.append(el("h3",`第 ${attempt.round} 轮 · ${fmt(attempt.planned_trimp,2)} 负荷值`));for(const check of attempt.checks)info.append(el("p",`${check.code} ${check.passed?"通过":"未通过"}：${check.detail}`));raw.append(info);});
 const swaps=(plan.adjustments||[]).filter(x=>x.reason?.includes("使用者提出"));
 for(const adjustment of swaps){const entry=el("div",null,"timeline-entry passed"),rail=el("div",null,"timeline-rail"),body=el("div",null,"timeline-body"),head=el("div",null,"timeline-head");rail.append(el("span","✓","timeline-bullet"));head.append(el("strong","人工提出日期调整"),el("span","重新校验通过","timeline-badge"));body.append(head,el("p",adjustment.action),el("span","R19 ✓ · R20 ✓","timeline-rule"));entry.append(rail,body);list.append(entry);}
}
function renderReport(report){currentReport=report;renderOverview(report);renderRisks(report.risks||[]);renderPlan(report);renderTimeline(report.plan);renderQuestions(report.questions||[]);const daily=report.metrics.load.trimp_daily||[];$("load-values").hidden=!daily.length;$("load-list").replaceChildren(...daily.map(row=>el("li",`${row.date} · ${fmt(row.trimp,2)} 负荷值`)));$("initial-error").hidden=true;for(const id of ["overview","load-panel","focus-panel","weekly","risk-panel"])$(id).hidden=false;$("timeline-panel").hidden=!(report.plan.attempts||[]).length;chartSelection=-1;if(window.RunWiseReview)window.RunWiseReview.render(report,currentQuality,{live});window.RunWiseProfessional?.setReport(report,currentQuality);requestAnimationFrame(drawChart);}

async function readJSON(file){if(!file)return null;if(file.size>256*1024)throw new Error("单份补充 JSON 不得超过 256 KB。");try{const data=JSON.parse(await file.text());if(!data||typeof data!=="object"||Array.isArray(data))throw Error();return data;}catch{throw new Error("补充资料需为 UTF-8 编码的 JSON 对象。");}}
async function readUpload(){const fields=csvForm.elements,file=fields.csv.files[0];if(!file||!file.size||file.size>MAX_CSV)throw new Error("请选择 2 MB 以内的非空 CSV 文件。");const buffer=new Uint8Array(await file.arrayBuffer());const chunks=[];for(let i=0;i<buffer.length;i+=32768)chunks.push(String.fromCharCode(...buffer.subarray(i,i+32768)));return{mode:"csv",csv:btoa(chunks.join("")),options:{athlete:fields.athlete.value.trim()||"anon_01",source:fields.source.value,as_of:fields.as_of.value,history_start:fields.history_start.value||null,trimp_profile:fields.trimp_profile.value||null,resting_hr:fields.resting_hr.value?fields.resting_hr.valueAsNumber:null,max_hr:fields.max_hr.value?fields.max_hr.valueAsNumber:null},measurements:await readJSON(fields.measurements.files[0]),context:await readJSON(fields.context.files[0])};}
async function run(build){
 if(busy)return;
 const fromImport=window.RunWisePages?.active==="import";
 const status=fromImport?$("import-status"):$("run-status");
 setBusy(true);
 status.classList.remove("error");
 status.textContent="正在分析训练记录…";
 try{
   const payload=await build();
   const result=await request("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
   showSnapshot(result);
   const planState=decisions[result.report.plan.status]?.label || "请查看报告";
   const count=result.import_quality?.accepted_rows;
   const message="报告已生成"+(Number.isInteger(count)?" · 已分析 "+count+" 条活动":"")+" · 七天计划"+planState;
   status.textContent=message;
   if(payload.mode==="csv"||payload.mode==="followup")window.RunWisePages.go("review");
   toast(message);
 }catch(error){
   const reason=(error.message||"生成失败").replace(/^\[P2 导入\]\s*/, "").replace(/指定 --source/g,"在第三步选择 CSV 格式");
   status.classList.add("error");
   status.textContent=fromImport ? reason.replace(/[。.]$/, "")+"。请核对文件表头和所选格式，再重试。" : reason;
   toast(reason);
 }finally{setBusy(false);}
}

function parseCSVPreview(text){const rows=[],limit=7;let field="",row=[],quoted=false;for(let i=0;i<text.length&&rows.length<limit;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===","&&!quoted){row.push(field);field="";}else if((c==="\n"||c==="\r")&&!quoted){if(c==="\r"&&text[i+1]==="\n")i++;row.push(field);if(row.some(v=>v.trim()))rows.push(row);row=[];field="";}else field+=c;}if(rows.length<limit&&(field||row.length)){row.push(field);if(row.some(v=>v.trim()))rows.push(row);}return rows;}
function decodeCSV(bytes){for(const charset of ["utf-8","gb18030"]){try{return new TextDecoder(charset,{fatal:true}).decode(bytes);}catch{}}return new TextDecoder("utf-8").decode(bytes);}

function csvDateRange(text,dateIndex){
 if(dateIndex<0)return null;
 let quoted=false,cell="",row=[],dates=[],ok=0;
 function appendRow(){row.push(cell);cell="";if(row.length>dateIndex){const raw=(row[dateIndex]||"").trim();const match=/^(\d{4})[-/](\d{2})[-/](\d{2})(?:\D|$)/.exec(raw);if(match){const date=`${match[1]}-${match[2]}-${match[3]}`;const parsed=new Date(`${date}T12:00:00Z`);if(!Number.isNaN(parsed.getTime())&&parsed.toISOString().slice(0,10)===date){dates.push(date);ok++;}}}row=[];}
 // Work on the complete input (<= 2 MB) and respect CSV quotes/newlines.
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(cell);cell="";}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;appendRow();}else cell+=c;}
 if(cell||row.length)appendRow();
 if(dates.length<=1)return dates.length?{earliest:dates[0],latest:dates[0],count:dates.length}:null;
 dates.sort();return{earliest:dates[0],latest:dates.at(-1),count:ok};
}

async function previewFile(){const file=csvForm.elements.csv.files[0];if(!file||!file.size||file.size>MAX_CSV)throw new Error("请选择大小不超过 2 MB 的非空 CSV 文件。");cachedCsvText=decodeCSV(await file.arrayBuffer());const rows=parseCSVPreview(cachedCsvText.replace(/^\uFEFF/,""));if(rows.length<2)throw new Error("CSV 没有足够的表头和活动数据。");const headers=rows[0];const body=rows.slice(1);const dateCol=headers.findIndex(h=>/date|日期|时间|开始/i.test(h));const preview=$("csv-preview");preview.replaceChildren();const stats=el("div",null,"preview-stat");const approxLines=cachedCsvText.split(/\r\n|\r|\n/).filter(x=>x.trim()).length-1;for(const [name,value] of [["预估数据行",Math.max(0,approxLines)],["检测到列数",headers.length],["文件大小",`${(file.size/1024).toFixed(1)} KB`]]){const card=el("div");card.append(el("strong",value),el("small",name));stats.append(card);}preview.append(stats);if(!headers.length||headers.length>120)throw new Error("CSV 表头无效或列数过多。");const scroll=el("div",null,"preview-scroll"),table=el("table"),head=el("thead"),tr=el("tr");for(const key of headers.slice(0,10))tr.append(el("th",key.slice(0,60)));head.append(tr);table.append(head);const tbody=el("tbody");for(const item of body.slice(0,5)){const r=el("tr");for(const cell of item.slice(0,10))r.append(el("td",cell.slice(0,140)));tbody.append(r);}table.append(tbody);scroll.append(table);preview.append(scroll,el("p","以上仅为浏览器预览（最多前 5 行），不是最终解析结果；正式的异常筛查、日期与格式校验由后端完成。","preview-note"));const dates=csvDateRange(cachedCsvText.replace(/^\uFEFF/,""),dateCol);const note=$("date-range-note");if(dates){note.textContent=`CSV 识别到 ${dates.count} 条有效日期，范围 ${dates.earliest} 至 ${dates.latest}。截止日默认建议最后一天，提交前请核对。`;if(csvForm.elements.as_of.dataset.manuallyEdited!=="true")csvForm.elements.as_of.value=dates.latest;preview.prepend(el("p",`完整 CSV 日期范围：${dates.earliest} — ${dates.latest}（已检查全部有效日期，不只是预览行）。`,"preview-note"));}else{note.textContent="未识别出有效日期；请手动核对截止日和 CSV 日期列。";}}
function showWizardStep(index){if(index===0)csvForm.querySelector('[data-step="0"]').prepend($("dropzone"));wizardStep=index;for(const page of document.querySelectorAll(".wizard-page"))page.hidden=Number(page.dataset.step)!==index;for(const [i,step] of [...document.querySelectorAll(".wizard-progress .step")].entries()){step.classList.toggle("active",i===index);step.classList.toggle("done",i<index);}window.RunWisePages?.go("import",{push:false,animate:false});}
function registerImport(){csvForm.elements.as_of.addEventListener("input",()=>{csvForm.elements.as_of.dataset.manuallyEdited="true";});const file=csvForm.elements.csv;file.addEventListener("change",()=>{$("import-status").textContent="";csvForm.elements.as_of.dataset.manuallyEdited="false";$("selected-file").textContent=file.files[0]?.name||"尚未选择文件";});const drop=$("dropzone");for(const type of ["dragenter","dragover"])drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add("dragover");});for(const type of ["dragleave","drop"])drop.addEventListener(type,e=>{e.preventDefault();drop.classList.remove("dragover");});drop.addEventListener("drop",e=>{const f=e.dataTransfer?.files?.[0];if(!f)return;const transfer=new DataTransfer();transfer.items.add(f);file.files=transfer.files;file.dispatchEvent(new Event("change"));});$("wizard-next-0").addEventListener("click",async()=>{try{await previewFile();showWizardStep(1);}catch(error){toast(error.message);}});$("wizard-next-1").addEventListener("click",()=>showWizardStep(2));for(const back of document.querySelectorAll(".wizard-back"))back.addEventListener("click",()=>showWizardStep(Math.max(0,wizardStep-1)));csvForm.addEventListener("submit",e=>{e.preventDefault();if(!csvForm.reportValidity())return;if(csvForm.elements.resting_hr.value&&csvForm.elements.max_hr.value&&+csvForm.elements.resting_hr.value>=+csvForm.elements.max_hr.value){toast("最大心率应高于静息心率。");return;}run(readUpload);});}

function setAiStatus(message,error=false){$("ai-status").textContent=message;$("ai-status").classList.toggle("error",error);}
function showAIText(text){const result=$("ai-result");result.replaceChildren();let source=String(text||"").replace(/<\s*br\s*\/?\s*>/gi,"\n").replace(/<\s*\/\s*(p|div|h[1-6]|li)\s*>/gi,"\n").replace(/<[^>]*>/g,"");for(const original of source.split(/\n+/)){const line=original.trim();if(!line)continue;if(/^#{1,4}\s+/.test(line)){result.append(el("h3",line.replace(/^#{1,4}\s+/,"")));}else if(/^([-*•]|\d+[.)])\s+/.test(line)){result.append(el("p","• "+line.replace(/^([-*•]|\d+[.)])\s+/,"").replace(/\*\*/g,"")));}else result.append(el("p",line.replace(/\*\*/g,"")));}result.append(el("p","模型回复不改变本地计算结果或训练计划。","ai-disclaimer"));result.hidden=false;}
async function analyzeCurrentReport(){if(!aiConnection||!reportId)return;aiRequest?.abort();const controller=new AbortController();aiRequest=controller;$("ai-retry").disabled=true;$("ai-result").hidden=true;$("ai-actions").hidden=false;setAiStatus("正在请求外部模型… 本次调用可能产生 API 费用。");const activeReport=reportId;try{const response=await request("/api/ai",{method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,body:JSON.stringify({report_id:reportId,...aiConnection})});if(controller!==aiRequest||activeReport!==reportId||response.report_id!==reportId)return;showAIText(response.analysis);$("ai-model").textContent=aiConnection.model;setAiStatus("模型解读已返回。规则和计划未被修改。");$("ai-settings").open=false;$("ai-ask-form").hidden=false;}catch(error){if(controller===aiRequest&&error.name!=="AbortError")setAiStatus(error.message||"AI 解读失败。",true);}finally{if(controller===aiRequest){aiRequest=null;$("ai-retry").disabled=false;}}}
async function askReportQuestion(event){event.preventDefault();if(!aiConnection||!reportId)return toast("请先连接 AI API。");const question=$("ai-ask-form").elements.question.value.trim();if(!question)return;aiQuestionRequest?.abort();const controller=new AbortController();aiQuestionRequest=controller;const btn=$("ai-ask-form").querySelector("button");btn.disabled=true;btn.textContent="模型正在回答…";$("ai-answer").hidden=true;const oldId=reportId;try{const res=await request("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,body:JSON.stringify({report_id:oldId,...aiConnection,question})});if(controller!==aiQuestionRequest||oldId!==reportId)return;$("ai-answer").replaceChildren(el("h3",`问：${question}`),el("p",res.analysis),el("p","外部模型回复；未修改训练计划。","ai-disclaimer"));$("ai-answer").hidden=false;$("ai-ask-form").elements.question.value="";}catch(error){if(error.name!=="AbortError")toast(error.message);}finally{if(controller===aiQuestionRequest){aiQuestionRequest=null;btn.disabled=false;btn.textContent="发送追问 ↗";}}}
function registerAi(){ $("ai-ask-form").addEventListener("submit",askReportQuestion);aiForm.addEventListener("submit",e=>{e.preventDefault();const {api_key,base_url,model}=aiForm.elements;aiConnection={api_key:api_key.value.trim(),base_url:base_url.value.trim(),model:model.value.trim()};api_key.value="";$("processing-mode").textContent="AI 解读会发送报告摘要";analyzeCurrentReport();});$("ai-retry").addEventListener("click",analyzeCurrentReport);$("ai-disconnect").addEventListener("click",()=>{aiRequest?.abort();aiQuestionRequest?.abort();aiRequest=null;aiQuestionRequest=null;aiConnection=null;$("processing-mode").textContent="训练指标在本机计算";$("ai-ask-form").hidden=true;$("ai-answer").hidden=true;$("ai-model").textContent="未连接";$("ai-result").replaceChildren();$("ai-result").hidden=true;$("ai-actions").hidden=true;aiForm.elements.api_key.value="";setAiStatus("连接已断开；后续报告更新不会调用模型。");});}

function downloadBlob(name,blob){const url=URL.createObjectURL(blob),a=el("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);toast(`已生成 ${name}`);}
const escapeHTML=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function exportStandaloneHTML(){const r=currentReport,d=r.metrics.load.trimp_daily||[],p=r.plan;const metrics=[["最近 7 天训练负荷",r.metrics.load.trimp_week],["近期与长期训练量对比",r.metrics.load.acwr_ewma],["有氧能力（估算）",r.metrics.capacity.vo2max.value],["静息心率和往常比",r.metrics.recovery.resting_hr_delta]];const info=r.risks.map(x=>`<section><h3>${escapeHTML(x.rule_id)} · ${escapeHTML(x.title)}</h3><p>${escapeHTML(x.evidence.clause)}</p><p>出处：${escapeHTML(x.evidence.source)}</p><p>建议：${escapeHTML(x.action)}</p></section>`).join("")||"<p>本次未列出触发信号，不代表没有风险。</p>";const days=p.days.map(x=>`<tr><td>${escapeHTML(x.date)}</td><td>${escapeHTML(kinds[x.kind]||x.kind)}</td><td>${fmt(x.duration_min,0)} 分钟</td><td>${fmt(x.planned_trimp,1)}</td><td>${escapeHTML(x.rules.join('、'))}</td></tr>`).join("")||`<tr><td colspan="5">${escapeHTML((p.hold_reasons||[]).join("；")||"未生成计划")}</td></tr>`;const checks=p.attempts.map(x=>`<p>第 ${x.round} 轮 · ${fmt(x.planned_trimp,1)} 负荷值：${escapeHTML(x.checks.map(c=>`${c.code}${c.passed?"通过":"未通过"}（${c.detail}）`).join("；"))}</p>`).join("")||"<p>风险门禁先于计划自检，未生成草案。</p>";const data=d.map(x=>`<tr><td>${escapeHTML(x.date)}</td><td>${fmt(x.trimp,2)}</td></tr>`).join("");const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RunWise AI 离线报告</title><style>body{font:14px/1.8 system-ui,'Microsoft YaHei',sans-serif;max-width:900px;margin:auto;padding:38px 22px;background:#f5f8f6;color:#203b34}header{background:#12513f;color:#fff;padding:32px;border-radius:15px}h1{margin:0}h2{color:#17654b;font-size:19px}section{background:white;border:1px solid #e1eee7;padding:17px;border-radius:10px;margin:13px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.cards div{background:#e7f6ee;padding:14px;border-radius:9px}.cards b{display:block;font-size:20px}table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:10px;border-bottom:1px solid #e4eae6}small{color:#77978b}footer{font-size:11px;margin-top:25px}@media print{body{background:white;padding:0}section{break-inside:avoid}}</style></head><body><header><p>RUNWISE AI · 已导出的独立离线报告</p><h1>${escapeHTML(r.summary.headline)}</h1><p>分析窗口：${escapeHTML(r.metrics.window.start)} — ${escapeHTML(r.metrics.window.end)}</p></header><h2>核心指标</h2><div class="cards">${metrics.map(([label,value])=>`<div>${escapeHTML(label)}<b>${fmt(value,2)}</b></div>`).join("")}</div><h2>训练负荷数据</h2><section><table><thead><tr><th>日期</th><th>TRIMP</th></tr></thead><tbody>${data}</tbody></table></section><h2>下周安排 · ${escapeHTML(p.status)}</h2><section><table><thead><tr><th>日期</th><th>训练类型</th><th>时长</th><th>计划负荷</th><th>规则</th></tr></thead><tbody>${days}</tbody></table></section><h2>自检过程</h2><section>${checks}</section><h2>风险信号与出处</h2>${info}<footer>该文件可直接用浏览器打开，无需 Python 或网络。仅为报告快照，不能重算计划。个人训练资料请妥善保管。不是医疗诊断或训练执行许可。</footer></body></html>`;downloadBlob(`runwise-report-${r.metrics.window.end}.html`,new Blob([html],{type:"text/html;charset=utf-8"}));}
function exportChartPNG(){
 if(!currentReport)return toast("请先生成报告。");
 const daily=getVisibleDaily(),valid=daily.filter(d=>Number.isFinite(d.trimp));
 if(!valid.length)return toast("当前缺少可导出的心率训练负荷。可在跑步趋势页保存跑量图。");
 const canvas=document.createElement("canvas");canvas.width=1600;canvas.height=900;
 const c=canvas.getContext("2d");if(!c)return toast("浏览器不支持图片导出。");
 c.fillStyle="#f4f9f6";c.fillRect(0,0,1600,900);
 c.fillStyle="#155a44";c.fillRect(0,0,1600,154);
 c.fillStyle="#abebd0";c.font="bold 22px system-ui";c.fillText("RUNWISE AI  /  训练负荷趋势",62,54);
 c.fillStyle="#fff";c.font="bold 43px system-ui,Microsoft YaHei,sans-serif";c.fillText("每天的训练负荷变化",62,118);
 c.font="23px system-ui,Microsoft YaHei,sans-serif";c.textAlign="right";
 c.fillText(`${chartPeriod==="all"?"全部":chartPeriod+" 天"}   |   ${decisions[currentReport.plan.status]?.label||"报告"}`,1530,93);c.textAlign="left";
 c.fillStyle="#fff";c.fillRect(50,182,1500,542);
 c.fillStyle="#314d3b";c.font="21px system-ui";
 c.fillText(`${daily[0].date} — ${daily.at(-1).date}`,104,229);
 const L=153,R=1490,T=277,B=639,max=Math.max(...valid.map(d=>d.trimp),1),power=10**Math.floor(Math.log10(max)),ceil=Math.ceil(max/power)*power;
 const x=i=>L+(R-L)*(daily.length===1?.5:i/(daily.length-1)),y=v=>B-(B-T)*v/ceil;
 c.textAlign="right";c.font="18px system-ui";
 for(const v of [0,ceil/4,ceil/2,ceil*3/4,ceil]){c.strokeStyle="#e3eee8";c.lineWidth=2;c.beginPath();c.moveTo(L,y(v));c.lineTo(R,y(v));c.stroke();c.fillStyle="#365b46";c.fillText(Number(v.toFixed(1)).toString(),L-16,y(v)+6);}
 c.textAlign="center";const tick=Math.max(1,Math.ceil(daily.length/8));
 daily.forEach((d,i)=>{if(i%tick===0||i===daily.length-1){c.fillStyle="#365b46";c.fillText(d.date.slice(5),x(i),681);}});
 c.strokeStyle="#189a77";c.lineWidth=5;c.lineJoin="round";c.lineCap="round";
 c.beginPath();let linked=false;
 daily.forEach((d,i)=>{if(!Number.isFinite(d.trimp)){linked=false;return;}if(linked)c.lineTo(x(i),y(d.trimp));else c.moveTo(x(i),y(d.trimp));linked=true;});c.stroke();
 daily.forEach((d,i)=>{if(!Number.isFinite(d.trimp))return;c.beginPath();c.arc(x(i),y(d.trimp),4.5,0,Math.PI*2);c.fillStyle="#189a77";c.fill();});
 c.textAlign="left";c.fillStyle="#155a44";c.font="bold 26px system-ui";
 c.fillText(`最近 7 天负荷   ${fmt(currentReport.metrics.load.trimp_week,1)}`,65,783);
 c.fillText(`近期/长期负荷比   ${fmt(currentReport.metrics.load.acwr_ewma,2)}`,596,783);
 c.fillText(`有效数据   ${valid.length} / ${daily.length} 天`,1130,783);
 c.fillStyle="#314d3b";c.font="18px system-ui,Microsoft YaHei,sans-serif";
 c.fillText(`图示期间负荷合计 ${fmt(valid.reduce((sum,d)=>sum+d.trimp,0),1)} · 曲线断开表示缺少数据。`,65,833);
 c.font="16px system-ui,Microsoft YaHei,sans-serif";
 c.fillText("依据当前报告生成；图表不构成训练或医疗建议。",65,869);
 canvas.toBlob(blob=>{if(blob)downloadBlob(`runwise-trimp-${daily[0].date}-${daily.at(-1).date}.png`,blob);else toast("PNG 生成失败。");},"image/png");
}

function registerExport(){const toggle=$("export-toggle"),menu=$("export-menu");toggle.addEventListener("click",()=>{menu.hidden=!menu.hidden;toggle.setAttribute("aria-expanded",String(!menu.hidden));});document.addEventListener("click",e=>{if(!e.target.closest(".export-wrap")){menu.hidden=true;toggle.setAttribute("aria-expanded","false");}});const close=()=>{menu.hidden=true;toggle.setAttribute("aria-expanded","false");};$("export-png").addEventListener("click",()=>{close();exportChartPNG();});$("export-review").addEventListener("click",()=>{close();if(currentReport)window.RunWiseReview.exportHTML();else toast("请先生成报告。");});$("export-html").addEventListener("click",()=>{close();if(currentReport)exportStandaloneHTML();else toast("请先生成报告。");});$("export-json").addEventListener("click",()=>{close();if(!currentReport)return toast("请先生成报告。");downloadBlob("runwise-report.json",new Blob([JSON.stringify(currentReport,null,2)],{type:"application/json;charset=utf-8"}));});$("export-running-csv").addEventListener("click",()=>{close();
  const data=currentReport?.running?.daily;if(!data)return toast("此报告没有逐日跑步数据，请重新导入 CSV。");
  const rows=["date,distance_km,pace_s_per_km,avg_hr_bpm,sessions\r\n",...data.map(x=>[x.date,x.distance_km,x.pace_s_per_km,x.avg_hr_bpm,x.sessions].map(v=>v==null?"":v).join(",")+"\r\n")];
  downloadBlob("runwise-daily-running.csv",new Blob(["\ufeff",...rows],{type:"text/csv;charset=utf-8"}));
 });$("export-csv").addEventListener("click",()=>{close();if(!currentReport)return toast("请先生成报告。");const data=currentReport.metrics.load.trimp_daily||[];downloadBlob("runwise-daily-trimp.csv",new Blob(["\ufeffdate,trimp\r\n",...data.map(x=>`${x.date},${Number.isFinite(x.trimp)?x.trimp:""}\r\n`)],{type:"text/csv;charset=utf-8"}));});$("export-print").addEventListener("click",()=>{close();if(currentReport)window.print();else toast("请先生成报告。");});}

async function refreshHistory(){if(!live)return;try{const res=await request("/api/history");historyIndex=res.reports||[];renderHistory();}catch(error){$("history-list").replaceChildren(el("p",`历史读取失败：${error.message}`,"empty"));}}
function renderHistory(){const list=$("history-list");list.replaceChildren();if(!historyIndex.length){list.append(el("p","暂无已保存的报告。运行演示或导入 CSV 后会自动生成本地历史记录。","empty"));return;}for(const entry of historyIndex){const row=el("div",null,"history-row"),info=el("div"),actions=el("div",null,"history-actions");info.append(el("strong",entry.generated_at||entry.id),el("small",`${sourceLabels[entry.source] || sourceLabels.unknown} · ${Number.isInteger(entry.sessions)?"近 7 天已记录 "+entry.sessions+" 次跑步 · ":""}窗口截至 ${entry.window_end} · ${decisions[entry.status]?.label||entry.status||"历史报告"}`));const view=el("button","查看","button button-soft"),compare=el("button","与当前对比","button button-outline");view.addEventListener("click",()=>loadHistory(entry.id,false));compare.addEventListener("click",()=>loadHistory(entry.id,true));actions.append(view,compare);row.append(info,actions);list.append(row);}}
async function loadHistory(id,compare){try{const response=await request(`/api/history/${encodeURIComponent(id)}`);if(compare){if(!currentReport)throw new Error("请先加载当前报告。");showComparison(response.report);}else{aiRequest?.abort();aiQuestionRequest?.abort();aiRequest=null;aiQuestionRequest=null;$("ai-ask-form").hidden=true;$("ai-answer").hidden=true;reportId=null;canAnswerCurrent=false;canSupplementCurrent=false;$("plan-supplements").hidden=true;currentQuality=response.import_quality||null;$("data-mode").textContent="历史报告 · 只读";renderReport(response.report);renderQuality(response.import_quality);window.RunWiseReview?.render(response.report,response.import_quality,{live:false});renderDataQuality(response.report.metrics.flags||[],response.import_quality);$("ai-panel").hidden=true;$("plan-adjust").hidden=true;toast("已打开历史报告（只读）。点击演示按钮可重新生成当前报告。");window.RunWisePages?.go("review");}}catch(error){toast(error.message);}}
function showComparison(old){const box=$("compare-box"),a=currentReport.metrics,b=old.metrics;box.replaceChildren(el("h3",`与 ${old.generated_at} 的报告对比`));const grid=el("div",null,"comparison-grid");for(const [name,x,y,unit] of [["最近 7 天训练负荷",a.load.trimp_week,b.load.trimp_week,""],["近期与长期训练量对比",a.load.acwr_ewma,b.load.acwr_ewma,""],["静息心率差",a.recovery.resting_hr_delta,b.recovery.resting_hr_delta," bpm"]]){const card=el("div");card.append(el("small",name),el("strong",fmt(x,2)+unit),el("em",`旧报告：${fmt(y,2)}${unit}${Number.isFinite(x)&&Number.isFinite(y)?` · 差 ${fmt(x-y,2)}`:""}`));grid.append(card);}box.append(grid,el("p","不同报告可能对应不同数据窗口，请勿将差值直接视为生理进步。","preview-note"));box.hidden=false;window.RunWisePages?.go("history",{push:false});box.scrollIntoView({behavior:"smooth",block:"nearest"});}

// Schedule swaps are submitted to the local server for R19/R20 and schema re-validation.
function openAdjustDrawer(){const plan=currentReport?.plan;if(!reportId||plan?.status!=="draft")return toast("只有当前有效的草案可以调整。");const content=$("drawer-content");content.replaceChildren();content.append(el("h2","调整训练日期"),el("p","请选择两个日期交换整天的安排。服务端会重新检查 R19 / R20 并验证报告契约；未经校验不会保存。","muted"));const form=el("form"),aLabel=el("label","原日期"),bLabel=el("label","目标日期"),a=el("select"),b=el("select");a.className="date-choice";b.className="date-choice";for(const d of plan.days){a.add(new Option(`${dateLabel(d.date)} · ${kinds[d.kind]||d.kind}`,d.date));b.add(new Option(`${dateLabel(d.date)} · ${kinds[d.kind]||d.kind}`,d.date));}if(b.options.length>1)b.selectedIndex=1;aLabel.append(a);bLabel.append(b);const submit=el("button","提交后端重新校验","button button-primary");submit.type="submit";form.append(aLabel,bLabel,submit);form.addEventListener("submit",async e=>{e.preventDefault();if(a.value===b.value)return toast("请选择两个不同日期。");submit.disabled=true;submit.textContent="正在重新校验…";try{const result=await request("/api/replan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({report_id:reportId,first_date:a.value,second_date:b.value})});showSnapshot(result);closeDrawer();notice("新草案已由后端重新执行 R19 / R20 检查并通过数据契约验证；仍需人工确认。");}catch(error){toast(error.message);}finally{submit.disabled=false;submit.textContent="提交后端重新校验";}});content.append(form);showDrawer();}
function registerTheme(){const toggle=$("theme-toggle");let saved="";try{saved=localStorage.getItem("runwise-theme")||"";}catch{}const dark=saved==="dark"||(!saved&&matchMedia("(prefers-color-scheme:dark)").matches);document.documentElement.classList.toggle("dark",dark);toggle.textContent=dark?"☀":"☾";toggle.addEventListener("click",()=>{const next=!document.documentElement.classList.contains("dark");document.documentElement.classList.toggle("dark",next);toggle.textContent=next?"☀":"☾";try{localStorage.setItem("runwise-theme",next?"dark":"light");}catch{}drawChart();drawRunningChart();});}
window.RunWiseCharts={drawRunning:drawRunningChart,drawLoad:drawChart};
function registerNavigation(){const menu=$("menu-toggle"),sidebar=$("app-sidebar");menu.addEventListener("click",()=>{const open=sidebar.classList.toggle("open");menu.setAttribute("aria-expanded",String(open));});for(const link of document.querySelectorAll(".side-nav a,.mobile-nav a"))link.addEventListener("click",()=>{sidebar.classList.remove("open");menu.setAttribute("aria-expanded","false");for(const item of document.querySelectorAll(".side-nav a"))item.classList.toggle("active",item.getAttribute("href")===link.getAttribute("href"));});$("drawer-overlay").addEventListener("click",closeDrawer);$("drawer-close").addEventListener("click",closeDrawer);document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer();if($("detail-drawer").hidden||e.key!=="Tab")return;const list=[...$("detail-drawer").querySelectorAll("button,input,select,a")].filter(x=>!x.disabled);if(!list.length)return;const first=list[0],last=list[list.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});}
async function init(){registerTheme();registerNavigation();registerExport();window.RunWiseReview?.setup();$("chart-download").addEventListener("click",exportChartPNG);setupChartSelectors();registerChartInteractions();registerRunningChart();$("today-label").textContent=new Date().toLocaleDateString("zh-CN",{year:"numeric",month:"long",day:"numeric"});$("history-refresh").addEventListener("click",refreshHistory);$("plan-adjust").addEventListener("click",openAdjustDrawer);window.addEventListener("resize",()=>requestAnimationFrame(()=>{drawChart();drawRunningChart();}));
 if(live){$("local-controls").hidden=false;$("history-panel").hidden=false;$("import-panel").hidden=false;registerImport();registerAi();$("plan-supplement-form").addEventListener("submit",submitPlanInputs);$("demo").addEventListener("click",()=>run(()=>({mode:"demo"})));$("review").addEventListener("click",()=>run(()=>({mode:"review"})));$("missing-demo").addEventListener("click",()=>run(()=>({mode:"missing"})));answerForm.addEventListener("submit",e=>{e.preventDefault();if(busy||!canAnswerCurrent)return;const answers={};for(const question of currentReport.questions||[]){const input=answerForm.elements.namedItem(question.key);if(!input||!input.value)continue;answers[question.key]=question.type==="number"?input.valueAsNumber:question.type==="boolean"?input.value==="true":input.value;}if(!Object.keys(answers).length)return toast("请至少填写一项答复。");run(()=>({mode:"followup",report_id:reportId,answers}));});}else{$("data-mode").textContent="匿名示例 · 离线预览";$("history-nav").hidden=true;$("import-nav").hidden=true;$("mobile-import").hidden=true;}
 setBusy(true);try{if(live)showSnapshot(await request("/api/snapshot"));else if(window.RUNWISE_OFFLINE_REPORT){renderReport(window.RUNWISE_OFFLINE_REPORT);renderDataQuality(window.RUNWISE_OFFLINE_REPORT.metrics.flags||[],null);}else renderReport(await request("http://127.0.0.1:8080/api/report"));}catch(error){$("initial-error").textContent=live?"暂时无法读取本机报告。点击“草案生成演示”重试。":"无法连接本地模拟接口，请按项目 README 启动模拟服务。";$("initial-error").hidden=false;}finally{setBusy(false);}if(live&&"serviceWorker"in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});}
init();
