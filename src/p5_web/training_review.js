"use strict";
/* RunWise V2.4 — 把后端已核验的报告翻译成面向跑者的文字。
   只解释现有数据；不生成新数值，不解除风险提醒，也不批准训练计划。 */
(function () {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  };
  const finite = v => typeof v === "number" && Number.isFinite(v);
  const number = (v, digits=1) => finite(v) ? v.toLocaleString("zh-CN", {minimumFractionDigits:digits,maximumFractionDigits:digits}) : "暂无数据";
  const change = v => finite(v) ? `${v>0?"+":""}${number(v,1)}%` : "无法判断";
  const kinds = {rest:"休息和恢复",easy:"轻松跑",long:"长距离跑",tempo:"节奏跑",interval:"间歇跑",cross:"交叉训练",strength:"力量训练"};
  const referenceOnly = r => r.rule_id === "R05" && /参考区间/.test(r.title || "");
  const escape = s => String(s??"").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const asParagraph = (s,cls="report-copy")=>node("p",s,cls);

  function build(report, quality) {
    const m=report.metrics||{}, p=report.plan||{}, l=m.load||{}, rec=m.recovery||{}, cap=m.capacity||{};
    const days=Array.isArray(l.trimp_daily)?l.trimp_daily:[];
    const measured=days.filter(d=>finite(d.trimp));
    const zeros=measured.filter(d=>d.trimp===0).length;
    const unknown=days.length-measured.length;
    const risks=(report.risks||[]).filter(r=>!referenceOnly(r));
    const refs=(report.risks||[]).filter(referenceOnly);
    const flags=Array.isArray(m.flags)?m.flags:[];
    const questions=Array.isArray(report.questions)?report.questions:[];
    const isDraft=p.status==="draft" && !!p.self_check?.passed;
    const planned=isDraft && finite(p.weekly_targets?.load_target_trimp)?p.weekly_targets.load_target_trimp:null;
    const baseline=finite(p.baseline_trimp)&&p.baseline_trimp>0?p.baseline_trimp:null;
    const delta=finite(planned)&&finite(baseline)?(planned/baseline-1)*100:null;
    const largeShift=finite(delta)&&Math.abs(delta)>=40;
    const span=`${m.window?.start||"未知"} 至 ${m.window?.end||"未知"}`;
    const acwrDescription={optimal:"在软件设置的参考范围内",high:"高于软件设置的参考范围",danger:"明显高于软件设置的参考范围",undertrained:"低于软件设置的参考范围",low:"低于软件设置的参考范围",insufficient:"数据不足，暂时无法判断",unavailable:"数据不足，暂时无法判断"}[l.acwr_status]||"暂时无法判断";
    const leadState=p.status==="hold_for_review"?"计划待复核":p.status==="awaiting_input"?"关键资料待补充":"下周训练计划待确认";
    const intro=p.status==="hold_for_review"
      ? "存在需进一步核对的训练风险，下周计划暂缓。"
      :p.status==="awaiting_input"
      ? "部分关键资料不足，暂无法制定下周训练安排。已知指标和缺失项目列于下文。"
      :"下周训练计划已通过规定检查，执行前还需本人或教练确认。";
    const loadLines=[];
    loadLines.push(finite(l.trimp_week)?`最近 7 天训练负荷：${number(l.trimp_week)}。`:"最近 7 天训练负荷数据不足，暂无法评估。");
    loadLines.push(finite(l.week_load_change_pct)
      ? `与前 7 天相比，训练负荷${Math.abs(l.week_load_change_pct)<1?"基本持平":l.week_load_change_pct>0?`增加 ${number(l.week_load_change_pct)}%`:`减少 ${number(Math.abs(l.week_load_change_pct))}%`}。`
      :"前一周数据不足，无法计算周间变化。");
    loadLines.push(finite(l.acwr_ewma)?`短期与长期训练负荷比值：${number(l.acwr_ewma,2)}，${acwrDescription}。`:"历史训练记录不足，无法计算短期与长期负荷比值。");
    loadLines.push(`近 ${days.length} 天记录：${measured.length} 天有数值，${unknown} 天缺失，${zeros} 天负荷为 0（不一定是休息日）。`);
    const recoveryLines=[];
    if(finite(rec.resting_hr_delta)) recoveryLines.push(Math.abs(rec.resting_hr_delta)<0.5?"静息心率与个人基线基本持平。":`静息心率较个人基线${rec.resting_hr_delta>0?"升高":"降低"} ${number(Math.abs(rec.resting_hr_delta))} 次/分。`);
    else recoveryLines.push("静息心率记录不足，无法与个人基线比较。");
    recoveryLines.push(finite(rec.sleep_h_avg)?`最近 ${rec.sleep_days||"若干"} 天睡眠记录：平均 ${number(rec.sleep_h_avg)} 小时/晚。` : "睡眠记录不足，无法分析近期情况。");
    recoveryLines.push(finite(rec.hrv_rmssd)?"已有心跳间隔变化记录，详细数值可在本栏的专业分析中查看。":"缺少心跳间隔变化记录。");
    recoveryLines.push(finite(cap.vo2max?.value)?"已有有氧能力估算结果；这是基于运动记录的估计，不是直接测量。":"记录不足，暂无法估算有氧能力。");
    const riskLines=[];
    if(risks.length)riskLines.push(`本次触发 ${risks.length} 项风险提醒，具体依据和处理建议见下方。`);
    else riskLines.push("当前记录未触发重点风险提醒，但不代表已排除全部身体风险。");
    if(refs.length)riskLines.push("训练负荷比值处于项目参考范围内（参考提示，非风险警告）。");
    const planLines=[];const notes=[];
    if(isDraft){
      const training=(p.days||[]).filter(d=>d.kind!=="rest").length;
      const rest=(p.days||[]).length-training;
      planLines.push(`下周计划（${p.week_start||"日期待定"}起）：训练 ${training} 天，休息 ${rest} 天。`);
      planLines.push(finite(planned)?(finite(delta)?`这份计划与近期训练量相比，${Math.abs(delta)<1?"基本持平":delta>0?`有所增加（约 ${number(delta)}%）`:`有所减少（约 ${number(Math.abs(delta))}%）`}。`:"暂时无法比较计划与近期训练量的变化。") :"当前没有可靠的训练负荷估算，具体指标见专业分析。");
      if(largeShift)notes.push(`计划负荷较近期参考值${delta<0?"降低":"升高"}约 ${number(Math.abs(delta))}%。需确认是否符合恢复周、比赛周等训练安排。`);
      planLines.push("草案已通过负荷上限和规则依据检查；仍需结合个人目标及身体状态确认。");
    }else{
      planLines.push(p.status==="hold_for_review"?"下周计划暂缓生成，待风险复核后重新评估。":"关键资料不足，下周计划暂缓。");
    }
    if(quality && (quality.skipped_rows||quality.device_anomaly_rows||quality.incomplete_rows))notes.push(`导入数据：未接纳 ${quality.skipped_rows||0} 条，设备异常 ${quality.device_anomaly_rows||0} 条，记录不完整 ${quality.incomplete_rows||0} 条。请核对源文件。`);
    if(flags.length)notes.push(`数据质量提示：${flags.length} 项。`);
    const advice=[];
    let adviceIntro="根据本次训练记录与风险检查，建议按以下顺序处理。";
    if(p.status==="hold_for_review"){
      adviceIntro=risks.length?"当前存在需复核的风险，暂缓增加训练负荷。":"当前计划被暂缓，建议先确认风险与资料完整性。";
      advice.push("先暂停增加训练强度或跑量，优先完成风险复核。");
      for(const r of risks.slice(0,3))if(r.action)advice.push(`因为“${r.title||"风险提示"}”，所以建议：${r.action}`);
      advice.push("如有持续或加重的疼痛、异常疲劳，应咨询专业人员；待风险情况明确后再评估训练安排。");
    }else if(p.status==="awaiting_input"){
      adviceIntro="关键资料未补齐，暂不安排下一周的逐日训练。";
      advice.push("先补充缺失的训练和身体状态资料，再重新计算报告。");
      for(const q of questions.slice(0,3))advice.push(`因为缺少关键信息，所以需补充：${q.prompt}`);
      advice.push("资料未补齐前，先按保守训练或休息处理，不建议据此安排新的高强度训练。");
    }else{
      adviceIntro="下周安排为待确认草案，执行前请核对训练负荷与恢复情况。";
      advice.push("先核对下周训练日、时长和休息安排是否符合你的真实计划与恢复状态。");
      if(largeShift)advice.push("因为计划负荷调整幅度较大，所以需要先确认这是减量周、加量周还是比赛周安排。");
      advice.push("训练后继续记录疲劳、睡眠和疼痛情况；一旦状态变化，应回到风险与恢复部分重新评估。");
      advice.push("确认无误后，再由本人或教练执行这份计划。");
    }
    // Summary always describes the *available* evidence, not whether the schedule could be made.
    const recent7=days.slice(-7);
    const recentMeasured=recent7.filter(d=>finite(d.trimp));
    const nonzero=recentMeasured.filter(d=>d.trimp>0);
    const peak=recentMeasured.length?recentMeasured.reduce((best,d)=>d.trimp>best.trimp?d:best,recentMeasured[0]):null;
    const running=report.running?.week||null;
    const summaryLines=[];
    if(running?.sessions===0&&!running?.coverage_confirmed){
      summaryLines.push("最近 7 天没有足够的可确认跑步记录，暂无法判断实际跑量与配速。");
    }else if(running){
      summaryLines.push(`最近 7 天完成 ${running.sessions} 次跑步，累计 ${number(running.distance_km,2)} 公里，用时 ${number(running.duration_min,0)} 分钟。`);
      if(finite(running.average_pace_s_per_km)){const pace=running.average_pace_s_per_km;summaryLines.push(`平均配速约每公里 ${Math.floor(pace/60)} 分 ${String(Math.round(pace%60)).padStart(2,"0")} 秒，最长单次跑步 ${number(running.longest_run_km,2)} 公里。`);}
      if(finite(running.distance_change_pct))summaryLines.push(`与前一周相比，跑量${running.distance_change_pct>=0?"增加":"减少"} ${number(Math.abs(running.distance_change_pct))}%。`);
      summaryLines.push(finite(running.average_hr_bpm)?`有心率的 ${running.hr_sessions} 次跑步，平均心率约 ${number(running.average_hr_bpm,0)} 次/分。` : "本周期缺少可用运动心率记录，暂不分析心率变化。")
    }

    if(finite(l.trimp_week)){
      summaryLines.push(finite(l.week_load_change_pct)
        ?`结合运动时长和强度计算的训练量，较上周${Math.abs(l.week_load_change_pct)<1?"基本持平":l.week_load_change_pct>0?"有所增加":"有所减少"}。`
        :"有可用的训练强度记录，暂无法与上周可靠比较。");
    }else if(recentMeasured.length){
      summaryLines.push("部分训练强度记录可用，但不足以计算整周的综合训练量。");
    }else summaryLines.push("缺少完整的运动强度记录，暂不评估综合训练负荷；公里数和配速仍可查看。");
    if(finite(l.acwr_ewma))summaryLines.push(`近期训练强度与较长时期相比，${acwrDescription}。这一结果仅供参考，不能单独判断受伤风险。`);
    if(recentMeasured.length){
      summaryLines.push(`最近 7 天中，${recentMeasured.length} 天有可用数值，${nonzero.length} 天的训练负荷大于 0。`+
        (peak?`其中最高的一天是 ${peak.date}（${number(peak.trimp)}）。` : "")+
        (recentMeasured.length<7?"其余日期资料缺失，未按休息日计算。":"数值为 0 的日期不一定是休息日。"));
    }
    if(risks.length)summaryLines.push(`本次识别出 ${risks.length} 项需要关注的风险；下周安排须先复核。`);
    else summaryLines.push("目前未检出需重点关注的风险信号，但这不代表所有健康风险均已排除。");
    const reportStatus = p.status==="draft"?"训练报告 · 计划待确认":p.status==="hold_for_review"?"训练报告 · 计划待复核":"训练报告 · 计划待补充资料";
    const completeness=[
      {label:"本周训练负荷",value:l.trimp_week,missing:"本次心率负荷资料不足；跑步距离和平均配速不受影响。"},
      {label:"近期与长期负荷对比",value:l.acwr_ewma,missing:"历史训练负荷记录不足，暂时无法比较短期与长期变化。"},
      {label:"有氧能力估算",value:cap.vo2max?.value,missing:"缺少满足估算条件的运动表现与心率记录。"},
      {label:"静息心率变化",value:rec.resting_hr_delta,missing:"没有足够的静息心率记录可与个人基线比较。"},
      {label:"睡眠情况",value:rec.sleep_h_avg,missing:"近期睡眠资料不足，无法估算平均睡眠时间。"},
      {label:"运动心率",value:report.running?.week?.average_hr_bpm,missing:"没有有效运动心率记录，跑量与配速仍可正常分析。"}
    ];
    const knownCount=completeness.filter(item=>finite(item.value)).length;
    return {
      running, title:"我的跑步训练报告",athlete:report.athlete_id||"匿名跑者",generated:report.generated_at||"—",
      windowTitle:span,status:p.status,summaryLabel:leadState,opening:intro,reportStatus,summaryLines,
      loadText:loadLines,recoveryText:recoveryLines,riskText:riskLines.join(" "),referenceText:refs.length?"参考范围提示另行列出。":"",
      planText:planLines.join(" "),planLines,advice,adviceIntro,notes,risks,refs,flags,questions,
      completeness,knownCount,
      window:m.window||{},quality:quality||null,planDays:isDraft?(p.days||[]):[],
      metrics:{weekTrimp:l.trimp_week,acwr:l.acwr_ewma,restDelta:rec.resting_hr_delta,planned,delta},
      disclaimers:report.disclaimers||[],raw:report
    };
  }

  function section(title,items,sub="") {
    const s=node("section",null,"review-section");
    s.append(node("h3",title));
    if(sub)s.append(asParagraph(sub,"review-section-intro"));
    items.forEach(x=>s.append(asParagraph(x)));
    return s;
  }
  function foldSection(sectionNode, hint="点击展开查看详情") {
    const title=sectionNode.querySelector(":scope > h3")?.textContent||"详情";
    const details=node("details",null,"review-fold");
    const summary=node("summary",null,"review-fold-summary");
    summary.append(node("span",title,"review-fold-name"),node("small",hint,"review-fold-hint"));
    details.append(summary,sectionNode);
    return details;
  }
  function feedbackKey(view){return `runwise-feedback-v23-${view.athlete}-${view.raw.plan.week_start}`;}
  function getFeedback(view){try{const data=JSON.parse(localStorage.getItem(feedbackKey(view))||"{}");return data&&typeof data==="object"&&!Array.isArray(data)?data:{};}catch{return {};}}
  function renderFeedbackSummary(view){
    const out=$("feedback-summary");if(!out)return;out.replaceChildren();
    const entries=Object.entries(getFeedback(view)).filter(([date])=>view.planDays.some(d=>d.date===date));
    if(!entries.length){out.append(asParagraph("暂无执行记录。填写内容仅保存在本浏览器，不参与负荷计算。","report-small"));return;}
    let expected=0,actual=0;
    for(const [date,item] of entries){const d=view.planDays.find(x=>x.date===date);expected+=Number(d.duration_min)||0;actual+=Number(item.minutes)||0;out.append(asParagraph(`${date}：原定 ${number(d.duration_min,0)} 分钟，实际 ${item.minutes} 分钟；自评费力程度 ${item.rpe}/10。`));}
    out.append(asParagraph(`只比较已填写的 ${entries.length} 天：计划 ${number(expected,0)} 分钟，实际 ${number(actual,0)} 分钟。未填写的日期不算未完成，这些记录暂未参与重新计算。`,`report-small`));
  }
  function render(report,quality,options={}){
    const v=build(report,quality),main=$("review-content");if(!main)return v;
    main.replaceChildren();
    // Report-first layout: substance at the top, missing-data inventory at the end.
    const lead=node("div",null,"review-lead review-report-cover");
    lead.append(node("p",`分析期间：${v.windowTitle} · ${v.athlete}`,"report-small"));
    const sessions=v.running?.sessions;
    lead.append(node("h3",Number.isInteger(sessions) ? "报告已生成 · 最近 7 天已记录 "+sessions+" 次跑步" : "训练报告已生成"));
    lead.append(node("p",v.summaryLabel,"report-cover-status"));
    if(options.live && v.status!=="draft"){
      const next=node("a",v.status==="hold_for_review"?"查看待复核事项":v.questions.length?"查看待补资料":"查看缺失指标","report-next");
      next.href=v.status==="hold_for_review"?"#risk-panel":v.questions.length?"#followup":"#data-quality";
      lead.append(next);
    }
    const summary=node("section",null,"review-section review-summary");
    summary.append(node("h3","本周期训练总结"));
    for(const line of v.summaryLines)summary.append(asParagraph(line));
    const stats=node("div",null,"review-stats");
    [
      ["最近 7 天训练负荷",v.metrics.weekTrimp,"负荷值"],
      ["近期与长期负荷比",v.metrics.acwr,"比值"],
      ["静息心率变化",v.metrics.restDelta,"次/分"],
      ["下周计划负荷",v.metrics.planned,"负荷值"]
    ].forEach(([label,value,unit],i)=>{const item=node("div",null,"review-stat");item.append(node("span",label),node("strong",finite(value)?number(value,i===1?2:1):"未知"),node("small",finite(value)?unit:"暂缺记录或计划"));stats.append(item);});
    if(v.running){
      const runStats=node("div",null,"runner-report-grid");
      const pace=finite(v.running.average_pace_s_per_km)?`${Math.floor(v.running.average_pace_s_per_km/60)}′${String(Math.round(v.running.average_pace_s_per_km%60)).padStart(2,"0")}″`:"未知";
      for(const [label,value,unit] of [["跑量",number(v.running.distance_km,2),"公里"],["平均配速",pace,"/公里"],["跑步次数",number(v.running.sessions,0),"次"],["运动心率",finite(v.running.average_hr_bpm)?number(v.running.average_hr_bpm,0):"未记录","次/分"]]){
        const card=node("div",null,"runner-report-stat");card.append(node("span",label),node("strong",value),node("small",unit));runStats.append(card);
      }
      main.append(lead,summary,runStats);
    }else main.append(lead,summary);
    const advanced=node("details",null,"review-advanced");advanced.append(node("summary","进阶训练负荷与恢复指标"),stats);main.append(advanced);
    advanced.append(section("训练负荷分析",v.loadText));
    main.append(foldSection(section("身体恢复情况",v.recoveryText),"心率、睡眠与恢复记录"));
    const riskSection=section("风险评估",[v.riskText]);
    if(v.risks.length){const list=node("div",null,"review-evidence-rows");for(const r of v.risks){const d=node("details",null,"review-evidence-item"),sum=node("summary",`${r.title||"风险提醒"} · 查看依据`),inside=node("div",null,"review-evidence-body");inside.append(asParagraph(`判断依据：${r.evidence?.clause||"未列出详细依据"}`),asParagraph(`处理建议：${r.action||"请进一步核对"}`),asParagraph(`规则出处：${r.rule_id||"—"} · ${r.evidence?.source||"未注明"}`));d.append(sum,inside);list.append(d);}riskSection.append(list);}
    if(v.refs.length)riskSection.append(asParagraph("参考提示：近期与长期训练负荷比值在项目参考区间内。","report-small"));main.append(foldSection(riskSection, v.risks.length?`${v.risks.length} 项需要关注` : "本次风险检查说明"));
    const advice=node("section",null,"review-section review-advice");advice.append(node("h3","训练建议"));if(v.adviceIntro)advice.append(asParagraph(v.adviceIntro,"review-section-intro"));const ol=node("ol");v.advice.forEach(s=>ol.append(node("li",s)));advice.append(ol);
    if(options.live&&v.risks.some(r=>r.rule_id==="R15")){
      const link=node("a","核对 R15 疼痛记录 →","button button-soft pain-review-entry");link.href="#risk-panel";
      advice.append(link);
    }
    main.append(advice);
    // Advice stays visible; background evidence can be opened only when needed.
    main.insertBefore(advice, main.querySelector(".review-advanced"));
    main.append(foldSection(section("下周训练安排",v.planLines),v.planDays.length?"查看逐日安排和说明":"暂未生成计划"));
    if(v.notes.length)main.append(foldSection(section("需要核对的事项",v.notes),`${v.notes.length} 项核对提示`));
    const available=node("section",null,"review-section review-completeness");
    available.append(node("h3","资料缺失及补充建议"));
    const absent=v.completeness.filter(item=>!finite(item.value));
    if(absent.length){
      available.append(asParagraph(`本报告使用了 ${v.knownCount} 项可用的核心指标，其余 ${absent.length} 项暂时无法判断。已有分析不受影响。`));
      const ul=node("ul",null,"review-missing-list");
      for(const item of absent){const li=node("li");li.append(node("strong",`${item.label}：未知。`),document.createTextNode(item.missing));ul.append(li);}available.append(ul);
    }else available.append(asParagraph("本报告的主要指标均有可用数据。"));
    if(v.questions.length){const heading=node("h4","与下周计划有关的待补充信息");available.append(heading);
      const list=node("ul",null,"review-missing-list");v.questions.forEach(q=>list.append(node("li",q.prompt)));available.append(list);}
    main.append(foldSection(available,absent.length?`${absent.length} 项暂缺资料` : "已导入数据说明"));
    const glossary=node("details",null,"review-glossary");glossary.append(node("summary","指标说明（选读）"));const dl=node("dl");[
      ["训练负荷（TRIMP）","把运动时间和心率强度综合成一个数，用来比较不同天的训练量；不是跑了多少公里。"],
      ["近期与长期负荷对比（ACWR）","比较短期和较长期的训练负荷，帮助观察训练量变化；不能单独预测受伤。"],
      ["心跳间隔变化（HRV）","心跳之间时间差的变化。要结合长期趋势和个人状态看，不能靠某一天判断是否恢复。"],
      ["有氧能力估算（VO₂max）","估计身体运动时利用氧气的能力；只是估算，不是实验室检测结果。"],
      ["程序规则编号（R05、R19、R20 等）","软件核验项目的编号，用于查找具体规则依据。"],
      ["程序自检通过","表示软件指定的检查项目通过，并不代表医生确认安全或计划适合所有人。"]
    ].forEach(([term,desc])=>{dl.append(node("dt",term),node("dd",desc));});glossary.append(dl);main.append(glossary);
    const source=node("details",null,"review-source");source.append(node("summary","数据来源与使用限制"));const body=node("div",null,"review-source-body");body.append(asParagraph(`指标、风险与训练草案依据本机计算结果。生成时间：${v.generated}。`));v.disclaimers.forEach(x=>body.append(asParagraph(x)));source.append(body);main.append(source);
    $("review-panel").hidden=false;
    const feedback=$("feedback-panel"),select=$("feedback-day"),button=$("feedback-submit");
    if(feedback&&select){feedback.hidden=!options.live||!v.planDays.length;select.replaceChildren();v.planDays.forEach(d=>select.add(new Option(`${d.date} · ${kinds[d.kind]||d.kind}`,d.date)));button.disabled=!v.planDays.length;renderFeedbackSummary(v);}
    window.RunWiseReview.current=v;return v;
  }
  function setupFeedback(){const form=$("feedback-form");if(!form)return;
    form.addEventListener("submit",e=>{e.preventDefault();const v=window.RunWiseReview.current;if(!v?.planDays.length)return;
      const date=form.elements.namedItem("date").value, minutes=Number(form.elements.namedItem("minutes").value),rpe=Number(form.elements.namedItem("rpe").value);
      if(!v.planDays.some(d=>d.date===date)||!Number.isFinite(minutes)||minutes<0||minutes>1440||!Number.isInteger(rpe)||rpe<0||rpe>10)return;
      try{const items=getFeedback(v);items[date]={minutes,rpe};localStorage.setItem(feedbackKey(v),JSON.stringify(items));renderFeedbackSummary(v);$("feedback-status").textContent="已保存到本浏览器；本次分析结果未更新。";}catch{$("feedback-status").textContent="当前浏览器禁止本地保存，请检查设置。";}
    });
    $("feedback-clear")?.addEventListener("click",()=>{const v=window.RunWiseReview.current;if(!v)return;try{localStorage.removeItem(feedbackKey(v));renderFeedbackSummary(v);$("feedback-status").textContent="本周的本地记录已经清除。";}catch{$("feedback-status").textContent="清除失败，请检查浏览器设置。";}});
  }
  const exportCSS=`
.review-fold{margin:12px 0;border:1px solid #a9c4b8;border-radius:11px;background:#f4f9f6;overflow:hidden}.review-fold>summary{list-style:none;display:flex;align-items:center;gap:12px;justify-content:space-between;cursor:pointer;font-weight:800;color:#1b4e3d;padding:16px 20px}.review-fold>summary::-webkit-details-marker{display:none}.review-fold>summary:after{content:"+";font-size:22px;color:#19674c}.review-fold[open]>summary:after{content:"−"}.review-fold-hint{margin-left:auto;font-size:12px;color:#4d6559}.review-fold>.review-section{margin:0;background:#fff;border:0;border-top:1px solid #b7cfc4;border-radius:0;padding:18px 20px}.review-fold>.review-section>h3,.review-fold>.review-section>.pro-report-heading h3{display:none}.review-fold .pro-report-heading{justify-content:flex-end}.review-advice{border-left:5px solid #266dd3;background:#eef2ff;padding:20px 25px;border-radius:13px}.review-advice h3{font-size:20px;color:#243c79}@media print{.review-fold{break-inside:auto}.review-fold>.review-section{display:block!important}.review-fold>summary{display:none}.review-advice{background:#f0f4ff!important;color:#162638!important}}
.pro-insight{padding:13px 16px;border-left:4px solid #20a785;background:#eaf5ef;border-radius:9px;margin:13px 0;color:#193d2e}.pro-insight h3,.pro-group h3,.pro-method h3,.pro-limit h3,.pro-compare h3{font-size:15px;color:#163b2d;margin:10px 0 6px}.pro-insight p,.pro-method p,.pro-limit p{font-size:14px;line-height:1.8;color:#1e392e}.pro-group{margin:16px 0}.pro-group .pro-data-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.pro-group .pro-data-item{min-width:0}.pro-method,.pro-limit,.pro-compare{padding:13px 16px;border:1px solid #b4cbbd;border-radius:10px;margin:13px 0}.pro-limit{background:#f7f8f3}.pro-compare-line{display:grid;grid-template-columns:76px minmax(0,1fr) 74px;align-items:center;gap:9px;margin:9px 0;font-size:12px}.pro-compare-line strong{text-align:right}.pro-track{height:10px;background:#d4e3db;border-radius:20px;overflow:hidden}.pro-bar{height:100%;background:linear-gradient(90deg,#1f9e80,#7798da);border-radius:20px}@media(max-width:640px){.pro-group .pro-data-list{grid-template-columns:1fr}}
.pro-report-heading{display:flex;justify-content:space-between;align-items:center;gap:8px}.pro-button{display:none}.export-pro-details{border:1px solid #adcabc;background:#f2f7f4;border-radius:10px;margin:14px 0;padding:12px 15px}.export-pro-details summary{font-weight:750;color:#18563b;cursor:pointer}.export-pro-body{margin-top:14px}.pro-lead,.pro-notice{color:#30493e;font-size:14px}.pro-data-list{display:grid;gap:8px;margin:10px 0}.pro-data-item{border:1px solid #c0d6c7;background:white;border-radius:9px;padding:10px 14px}.pro-data-item dt{font-size:13px;color:#36584a;font-weight:700}.pro-data-item dd{color:#183d2c;font-size:17px;font-weight:800;margin:3px 0}.pro-explanation{color:#456054;font-size:13px}.pro-report-heading .pro-button{display:none!important}@media print{.export-pro-details:not([open]){display:none}}

.runner-report-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}.runner-report-stat{display:flex;flex-direction:column;gap:7px;padding:16px;background:#f1f7f5;border:1px solid #b5cec0;border-radius:10px}.runner-report-stat span,.runner-report-stat small{color:#354b40;font-size:12px}.runner-report-stat strong{font-size:25px;color:#17392b}.review-advanced{border:1px solid #c5d8cb;border-radius:11px;padding:15px;margin:13px 0}.review-advanced summary{font-weight:750;cursor:pointer}@media(max-width:620px){.runner-report-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media print{.runner-report-stat{break-inside:avoid}.review-advanced{display:none}}
:root{color-scheme:light}*{box-sizing:border-box}body{font:16px/1.82 system-ui,"Microsoft YaHei",sans-serif;background:#fff;color:#172c25;max-width:850px;margin:auto;padding:20px 25px}header{border-bottom:3px solid #14563f;padding:15px 0 22px;margin:0 0 22px}h1{font-size:29px;line-height:1.35;margin:8px 0}h3{font-size:20px;line-height:1.5;color:#133b2c;margin:0 0 12px}p{margin:10px 0}.report-small,.review-section-intro{color:#31483f;font-size:14px}.review-lead{background:#e6f3ea;border:1px solid #9bbba8;border-radius:12px;padding:22px 26px;color:#172c25}.review-lead h3{color:#113c2a;font-size:23px}.review-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:15px 0}.review-stat{padding:15px;background:#f3f8f5;border:1px solid #b9cfc2;border-radius:10px;display:flex;flex-direction:column}.review-stat span{font-size:14px;color:#294439}.review-stat strong{font-size:27px;line-height:1.45;color:#132d21}.review-stat small{font-size:13px;color:#294439}.review-priority{padding:18px 22px;border-radius:10px;background:#fff2d9;border-left:6px solid #92620c;margin:18px 0}.review-section{background:white;border:1px solid #bacac0;border-radius:11px;padding:20px 24px;margin:16px 0}.report-copy{font-size:16px;color:#192c24;line-height:1.88}.review-advice{border-left:5px solid #126949;background:#eaf5ec}.review-advice ol{padding-left:25px;margin:8px 0}.review-advice li{padding:3px 0;margin:8px 0}.review-evidence-item,.review-glossary,.review-source{border:1px solid #b6cbbf;border-radius:10px;background:#f4f8f5;margin:12px 0;padding:14px 20px}.review-evidence-item summary,.review-glossary summary,.review-source summary{cursor:pointer;font-weight:750;color:#174a35}.review-glossary dl{display:grid;grid-template-columns:190px 1fr;gap:8px 15px}.review-glossary dt{font-weight:700}.review-glossary dd{margin:0}.review-source-body{margin-top:12px}footer{font-size:13px;color:#31483f;border-top:1px solid #b9cfc2;margin-top:26px;padding-top:15px}a{color:#14593e}.review-summary{background:#f1f8ff;border-left:5px solid #2774b8}.report-cover-status{font-size:14px;font-weight:750;color:#194b38}.review-completeness{background:#f3faf5;border-left:5px solid #176e49}.review-missing-list{padding-left:24px;font-size:15px;line-height:1.85;color:#15291e}.review-missing-list li{margin:7px 0}@media(max-width:640px){body{padding:14px;font-size:15px}.review-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.review-glossary dl{grid-template-columns:1fr}.review-section{padding:17px}}@media print{html{print-color-adjust:exact;-webkit-print-color-adjust:exact}body{padding:0;max-width:none;color:#111;background:#fff}.review-lead,.review-stat,.review-priority,.review-section,.review-advice{break-inside:avoid;page-break-inside:avoid}.review-glossary,.review-source{break-inside:avoid}.review-lead{background:#eff5f0!important;color:#14291e!important}.review-advice{background:#f1f7f2!important} .report-copy{color:#14291e!important}.review-section{border-color:#738d7c!important}}`;
  function exportHTML(){const v=window.RunWiseReview.current;if(!v)return;
    // Browser content is created with textContent (not raw user HTML).
    const cloned=$("review-content").cloneNode(true);
    for(const link of cloned.querySelectorAll(".pain-review-entry,.report-next"))link.remove();
    for(const button of cloned.querySelectorAll("button[data-pro]")){
      const key=button.dataset.pro;
      if(window.RunWiseProfessional?.exportDetails)button.replaceWith(window.RunWiseProfessional.exportDetails(key));
      else button.remove();
    }
    const contents=cloned.innerHTML;
    const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>我的跑步训练报告</title><style>${exportCSS}</style></head><body><header><small>RUNWISE AI · 训练分析</small><h1>我的跑步训练报告</h1><p>${escape(v.athlete)} · ${escape(v.windowTitle)} </p></header>${contents}<footer>本报告基于已有训练数据计算，不构成医疗诊断；训练计划须经本人或教练确认。分享前请检查个人信息。</footer></body></html>`;
    const blob=new Blob([html],{type:"text/html;charset=utf-8"}),url=URL.createObjectURL(blob),a=node("a");a.href=url;a.download=`RunWise-我的训练报告-${v.window.end||"report"}.html`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
  }
  function setup(){
    $("review-export-html")?.addEventListener("click",exportHTML);
    let printOpened=[];
    window.addEventListener("beforeprint",()=>{
      printOpened=[...document.querySelectorAll("#review-content .review-fold:not([open])")];
      for(const item of printOpened)item.open=true;
    });
    $("review-print")?.addEventListener("click",()=>{if(!window.RunWiseReview.current)return;document.documentElement.classList.add("review-print");window.print();});
    window.addEventListener("afterprint",()=>{for(const item of printOpened)item.open=false;printOpened=[];document.documentElement.classList.remove("review-print");});
    setupFeedback();
  }
  window.RunWiseReview={build,render,setup,exportHTML,current:null};
})();
