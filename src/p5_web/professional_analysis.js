"use strict";
/* V2.9 专业分析：同一份报告中的专题解读，不虚构缺失项目。所有内容通过 textContent 安全渲染。 */
(()=>{
  let report=null,quality=null,previousFocus=null;
  const $=id=>document.getElementById(id);
  const valid=n=>typeof n==="number"&&Number.isFinite(n);
  const num=(n,d=1)=>valid(n)?n.toLocaleString("zh-CN",{maximumFractionDigits:d}):"未计算";
  const pace=n=>{if(!valid(n)||n<=0)return "未计算";const v=Math.round(n);return `${Math.floor(v/60)}′${String(v%60).padStart(2,"0")}″/公里`;};
  const html=(parent,tag,content,cls)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(content!=null)node.textContent=String(content);parent.append(node);return node;};
  const text=n=>typeof n==="string"?n.trim():"";
  const statusName={draft:"草案待确认",hold_for_review:"风险待人工复核",awaiting_input:"关键资料待补充"};
  function view(key){
    const r=report||{},running=r.running||{},w=running.week||{},m=r.metrics||{},load=m.load||{},rec=m.recovery||{},cap=m.capacity||{},plan=r.plan||{};
    const allRisks=r.risks||[];
    const refs=allRisks.filter(s=>/参考|区间/.test(s.title||"")&&s.level==="low");
    const alerts=allRisks.filter(s=>!refs.includes(s));
    const groups=[],insights=[];
    let title="专业分析",intro="",method="",limit="",comparisons=[];
    const group=(name,...rows)=>groups.push({name,rows:rows.filter(Boolean)});
    const row=(name,value,detail="")=>({label:name,value:valid(value)?num(value):String(value??"未计算"),explanation:detail});
    const metric=(name,value,unit="",detail="",digits=2)=>row(name,valid(value)?`${num(value,digits)}${unit}`:"未计算",detail);
    const msg=t=>{if(t)insights.push(t);};
    const missing=t=>`${t}目前没有足够的有效记录，不能从现有数据推算。`;
    // Older reports stored zero even for an unknown previous week.
    const comparable = w.previous_coverage_confirmed === true || valid(w.distance_change_pct);
    const previousDistance = comparable ? w.previous_distance_km : null;
    const sameWeek = comparable && valid(w.distance_km) && valid(previousDistance);
    const start=running.window?.start||m.window?.start||"—",end=running.window?.end||m.window?.end||"—";
    if(key==="distance"){
      title="跑量分析";intro="本周总距离反映跑步量，但不能单独反映每次训练强度。";
      group("本周与上周",metric("本周累计距离",w.distance_km," 公里","本周有效跑步记录的距离相加。"),metric("前一周累计距离",previousDistance," 公里"),metric("相对前一周变化",w.distance_change_pct,"%","只有前一周距离可核实时才计算。",1));
      group("单次跑步",metric("最长单次距离",w.longest_run_km," 公里"),metric("有效跑步次数",w.sessions," 次","按导入记录中的跑步活动统计。",0));
      if(sameWeek){const diff=w.distance_km-w.previous_distance_km;msg(Math.abs(diff)<.01?"本周累计跑量与上周相同。":`本周比上周${diff>0?"多":"少"}跑了 ${num(Math.abs(diff),2)} 公里。`);comparisons=[{label:"本周",value:w.distance_km},{label:"前一周",value:w.previous_distance_km}];}
      else msg(missing("上周跑量对比"));
      method="将计算窗口内、通过导入检查的跑步活动距离相加；与上周比较时使用相邻的两个 7 天窗口。";
      limit="跑量增长不代表成绩必然提高。坡度、强度、主观疲劳等因素需要结合其他数据判断；未知日期不会自动作为休息。";
    }else if(key==="pace"){
      title="配速分析";intro="平均配速表示完成每公里所需的时间，数值越小，平均速度越快。";
      group("实际跑步表现",row("本周平均配速",pace(w.average_pace_s_per_km)),metric("累计跑步时长",w.duration_min," 分钟","仅包含有效跑步活动。",0),metric("累计跑步距离",w.distance_km," 公里"));
      if(valid(w.average_pace_s_per_km))msg(`根据本周有效距离与用时，平均每公里约用 ${pace(w.average_pace_s_per_km).replace("/公里","")}。`);
      else msg("缺少可配对的距离和运动时长，暂时无法计算平均配速。");
      method="先汇总本周有效跑步用时，再除以对应跑步距离：总秒数 ÷ 总公里数 = 每公里秒数。不是简单平均每次配速。";
      limit="不同训练目的的跑步不宜仅比较配速；区间跑、坡跑、天气和路线可能造成差异。没有每次训练的环境条件时无法归因。";
    }else if(key==="sessions"){
      title="跑步频率分析";intro="训练次数用于观察本周安排的频率和规律，不等同于训练强度。";
      group("训练频率",metric("本周跑步次数",w.sessions," 次","仅统计成功识别且通过检查的跑步活动。",0),metric("具有有效距离的次数",w.distance_sessions," 次", "只有可用距离的活动才能参与距离统计。",0),metric("本周总时长",w.duration_min," 分钟", "按实际记录累计。",0));
      if(valid(w.sessions)&&valid(w.distance_sessions))msg(`本周共记录 ${num(w.sessions,0)} 次跑步，其中 ${num(w.distance_sessions,0)} 次包含可用距离。`);
      else msg("目前不足以确认训练次数。");
      method="以已接纳的跑步活动为单位统计，不把没有数据的日期推断为休息日。";
      limit="一次活动可能包含热身和放松段；多次拆分上传或设备重复记录可能影响次数，应核对原文件。";
    }else if(key==="duration"){
      title="训练时间分析";intro="训练时长展示本周投入的时间，适合与跑量一起观察。";
      const average=valid(w.duration_min)&&valid(w.sessions)&&w.sessions>0?w.duration_min/w.sessions:null;
      group("训练时间",metric("本周跑步总时长",w.duration_min," 分钟","仅统计接纳的跑步活动。",0),metric("单次平均时长",average," 分钟","总运动分钟数 ÷ 有效跑步次数。",1),metric("跑步次数",w.sessions," 次","不把空白日期自动算作休息。",0));
      if(valid(w.duration_min))msg(`本周累计运动约 ${num(w.duration_min,0)} 分钟；训练时长本身不能反映每次的运动强度。`);
      else msg(missing("跑步时间"));
      method="累加记录中的有效运动时长，不包含无法确认的等待、暂停或其他非跑步活动。";
      limit="设备对“总时间”和“运动时间”的定义不同；若含暂停时间，平均配速可能偏慢，应检查 CSV 字段。";
    }else if(key==="heart"){
      title="运动心率分析";intro="运动心率可以辅助观察训练时的身体反应，需结合个人习惯和测量质量。";
      const cover=valid(w.sessions)&&w.sessions>0&&valid(w.hr_sessions)?100*w.hr_sessions/w.sessions:null;
      group("心率记录",metric("本周运动平均心率",w.average_hr_bpm," 次/分","只汇总有有效心率记录的跑步；按对应的训练时长加权。",0),metric("有效心率训练",w.hr_sessions," 次","有有效心率数据的跑步次数。",0),metric("心率覆盖比例",cover,"%","有效心率训练次数 ÷ 全部接纳的跑步次数。",0));
      if(valid(w.average_hr_bpm))msg(`本周有效心率记录的时长加权平均值为 ${num(w.average_hr_bpm,0)} 次/分。${valid(cover)&&cover<100?"部分训练没有心率记录，该均值不能代表全部训练。":""}`);
      else msg("本周没有可用于计算平均心率的记录。距离、配速和次数仍可分析。");
      method="仅对记录了有效运动平均心率的训练，用训练时长进行加权平均；无心率训练不参与心率均值。";
      limit="没有年龄、实测最大心率、运动强度背景与长期趋势时，单独一个平均心率不能判断是否训练过量或恢复充分。";
    }else if(key==="overview"){
      title="本周数据总览";intro="把距离、时间、次数和心率放在同一窗口对照，帮助核对训练记录。";
      group("本周跑步数据",metric("累计距离",w.distance_km," 公里"),row("平均配速",pace(w.average_pace_s_per_km)),metric("跑步次数",w.sessions," 次","有效跑步活动。",0),metric("运动时长",w.duration_min," 分钟", "有效记录汇总。",0));
      group("心率与时间范围",metric("运动平均心率",w.average_hr_bpm," 次/分","缺失时不参与均值计算。",0),row("记录范围",`${start} 至 ${end}`));
      msg(valid(w.distance_km)?`本周记录 ${num(w.distance_km,2)} 公里、${num(w.sessions,0)} 次跑步；详情请分别查看对应卡片。`:"当前报告缺少可汇总的跑步距离。");
      method="从当前训练报告读取相同的 7 天统计窗口，避免混合不同计算周期。";
      limit="部分旧报告可能没有跑量字段；需要用原 CSV 重新计算才能补全。";
    }else if(key==="running"){
      const selected=document.querySelector('[data-running-mode].selected')?.dataset.runningMode||"distance";
      const field={distance:"distance_km",pace:"pace_s_per_km",heart:"avg_hr_bpm"}[selected];
      const label={distance:"跑量",pace:"配速",heart:"心率"}[selected];
      const daily=running.daily||[];const covered=daily.filter(d=>valid(d[field])).length;
      title=`${label}趋势分析`;intro=`当前图表展示${label}的逐日变化，空白不代表数值为零。`;
      group("图表覆盖范围",row("当前指标",label),metric("有数值的自然日",covered," 天","图表不为缺失日期填充数据。",0),metric("展示的自然日",daily.length," 天","通常为最近 28 个自然日。",0));
      if(selected==="distance"){group("周统计",metric("本周距离",w.distance_km," 公里"),metric("上周距离",previousDistance," 公里"));msg(sameWeek?`本周跑量相较上周${w.distance_km>=w.previous_distance_km?"增加或持平":"下降"}，变化数据见上方。`:"当前没有足够资料对比上周跑量。");}
      if(selected==="pace"){group("周统计",row("本周平均配速",pace(w.average_pace_s_per_km)));msg("配速曲线只能反映有距离和时长的训练日，不能把训练目的不同的跑步直接评价为进步或退步。");}
      if(selected==="heart"){group("周统计",metric("运动平均心率",w.average_hr_bpm," 次/分","有效心率训练的时长加权平均。",0));msg("心率曲线受训练强度、温度、坡度和设备测量影响，需结合具体训练日判断。");}
      method="每日数值从已接纳的跑步记录汇总；跨缺失日的图线不连成虚假的连续观测。";
      limit="当前趋势图主要用于查看训练记录变化，不提供成绩预测或伤病概率预测。";
    }else if(key==="load"||key==="load-detail"){
      title="训练负荷分析";intro="训练负荷结合运动时长和心率强度，描述训练刺激，不等于公里数。";
      group("负荷结果",metric("近 7 天 TRIMP",load.trimp_week,"","训练冲量；依赖满足条件的心率记录。"),metric("与前一周变化",load.week_load_change_pct,"%","以实际计算的周负荷比较。",1));
      group("短期与长期对比",metric("EWMA ACWR",load.acwr_ewma,"","基于指数加权的近期/长期负荷比。"),metric("Rolling ACWR",load.acwr_rolling,"","采用滚动窗口的负荷对比值。"));
      const daily=load.trimp_daily||[];group("记录覆盖",metric("有数值的自然日",daily.filter(d=>valid(d.trimp)).length," 天","0 有可能是确认的零值，也可能需核对记录来源。",0),metric("总观察自然日",daily.length," 天","缺失不自动换算成 0。",0));
      if(valid(load.week_load_change_pct))msg(`本周训练负荷较上周${load.week_load_change_pct>=0?"增加":"减少"} ${num(Math.abs(load.week_load_change_pct),1)}%。应结合具体训练安排解读。`);
      else msg("训练负荷缺少足够输入，无法可靠分析周际变化。基础跑量仍可用。");
      method="TRIMP 按训练时长与相对心率强度计算；ACWR 用近期和较长期的已计算负荷序列比较。";
      limit="ACWR 是描述性监测指标，不能单独判断受伤概率或证明安全。不同算法的比值也不能互相替代。";
      if(valid(load.trimp_week)&&valid(plan.baseline_trimp))comparisons=[{label:"本周",value:load.trimp_week},{label:"计划参考",value:plan.baseline_trimp}];
    }else if(key==="recovery"){
      title="恢复与身体状态";intro="恢复指标更适合与自己的长期基线比较，不能凭单次数据做医学诊断。";
      group("静息心率",metric("个人静息心率基线",rec.resting_hr_baseline," 次/分","取本地规则要求的基线窗口。"),metric("相比基线变化",rec.resting_hr_delta," 次/分","正值表示高于该基线。"),metric("基线有效记录",rec.resting_hr_baseline_days," 天","不足时不会计算差值。",0));
      group("睡眠与 HRV",metric("平均睡眠时长",rec.sleep_h_avg," 小时"),metric("有睡眠记录的天数",rec.sleep_days," 天","仅统计有效量测。",0),metric("HRV · RMSSD",rec.hrv_rmssd," ms","心跳间期变化指标，需看多日趋势。"));
      group("能力估算",metric("VO₂max 估算",cap.vo2max?.value," ml/kg/min","不是实验室直接测量。",1),metric("心率漂移",rec.hr_drift_pct,"%","仅符合特定训练条件时才计算。"));
      if(valid(rec.resting_hr_delta))msg(`静息心率相对既定基线${rec.resting_hr_delta===0?"没有变化":rec.resting_hr_delta>0?`高 ${num(rec.resting_hr_delta,1)} 次/分`:`低 ${num(Math.abs(rec.resting_hr_delta),1)} 次/分`}，需结合睡眠与疲劳状况判断。`);
      else msg("静息心率或基线记录不足，当前不能判断静息心率变化。");
      method="仅展示报告中满足统计条件的恢复指标；VO₂max 属于估算，HRV 单次值不作为恢复等级结论。";
      limit="睡眠时长不等于睡眠质量，缺少疲劳、疼痛或连续多日记录时，不应据此决定是否增加运动量。";
    }else if(key==="risk"){
      title="风险规则与判断依据";intro="把需要关注的风险与参考性提示分开列出，方便核对规则如何得出结果。";
      group("风险信号分类",metric("需关注信号",alerts.length," 项","不包括标注为参考区间的低等级提示。",0),metric("参考说明",refs.length," 项","参考指标不是受伤预言。",0));
      if(alerts.length){msg(`本次触发 ${alerts.length} 项需关注信号；它们应结合症状、训练历史及人工核对处理。`);}
      else msg("报告中没有列出额外的需关注风险信号；不能据此认定不存在伤病风险。");
      for(const [name,arr] of [["需关注的规则",alerts],["参考说明",refs]]){
        if(arr.length)group(name,...arr.map(x=>row(`${x.rule_id||"规则"} · ${x.title||"未命名"}`,x.action||"未列出处理建议",[x.evidence?.clause,x.evidence?.threshold?`项目阈值：${x.evidence.threshold}`:"",x.evidence?.source?`参考来源：${x.evidence.source}`:""].filter(Boolean).join("；"))));
      }
      method="风险页面读取本次报告的 rule_id、level、evidence、action；规则名称和处理建议均保留原始来源以供追溯。";
      limit="规则属于本项目的训练决策辅助，不能替代临床评估。遇到疼痛、胸闷、晕厥或其他异常症状应暂停训练并寻求适当专业帮助。";
    }else if(key==="plan"){
      title="下周训练计划分析";intro="训练计划与已完成的训练记录是两回事；当前展示的是待确认草案或暂缓原因。";
      group("计划基本信息",row("当前状态",statusName[plan.status]||"未生成"),row("计划开始日期",plan.week_start||"未生成"),metric("计划跑步次数",plan.weekly_targets?.sessions," 次","尚无草案时不填 0。",0),metric("计划周负荷 TRIMP",plan.weekly_targets?.load_target_trimp,"","计划值与已完成训练负荷不能混淆。"));
      const proposed=plan.weekly_targets?.load_target_trimp,baseline=plan.baseline_trimp;
      if(valid(proposed)&&valid(baseline)&&baseline>0){const diff=100*(proposed-baseline)/baseline;
        group("和近期训练对照",metric("参考训练负荷",baseline," TRIMP"),metric("计划相对参考负荷",diff,"%","比较计划总量与项目参考负荷，变化大需解释原因。",1));
        msg(`计划总负荷相对参考负荷${diff>=0?"高":"低"} ${num(Math.abs(diff),1)}%。${Math.abs(diff)>40?"差异较大，应先确认是否为恢复周、赛事周或其他特定安排。":"仍需结合目标与恢复情况核对。"}`);
        comparisons=[{label:"参考负荷",value:baseline},{label:"计划负荷",value:proposed}];
      }else msg(plan.status==="draft"?"系统已有草案，但缺少可对照的完整负荷参考。":"目前未生成可执行的逐日训练安排，仍可查看已有训练报告。");
      if((plan.hold_reasons||[]).length)group("暂缓原因",...(plan.hold_reasons||[]).slice(0,6).map((s,i)=>row(`原因 ${i+1}`,typeof s==="string"?s:JSON.stringify(s))));
      method="使用后端已生成的计划状态、计划总负荷和参考负荷，不在页面上自行变更训练日。";
      limit="R19/R20 通过只代表对应工程规则核验通过，不等于医学批准或教练确认。";
    }else if(key==="checks"){
      title="计划自检过程";intro="记录初始草案是否被规则拦截，以及实际做过哪些修改。";
      const attempts=plan.attempts||[];
      if(attempts.length){
        for(const a of attempts){group(`第 ${a.round} 轮核验`,metric("本轮计划负荷",a.planned_trimp," TRIMP"),...(a.checks||[]).map(c=>row(`${c.code||"检查"} · ${c.passed?"通过":"未通过"}`,c.detail||"无详细说明")));}
        msg(attempts.some(a=>(a.checks||[]).some(c=>!c.passed))?"草案曾触发未通过检查；后续轮次的结果可以在下方逐项核对。":"已记录的检查均通过，仍需人工确认最终安排。");
      }else{group("检查状态",row("计划自检","未执行","没有生成训练草案时不会自动标注为通过。"));msg("目前没有可供检查的训练草案。");}
      if(plan.adjustments?.length)group("实际调整记录",...plan.adjustments.map((x,i)=>row(`${x.rule_id||`调整 ${i+1}`} · ${x.reason||"调整原因"}`,x.action||"未提供调整描述")));
      method="直接展示后端 self_check 和 attempts 的记录；页面不重新运行规则引擎。";
      limit="规则检查不覆盖所有生活情境与医疗因素，不应将“通过”直接理解为“可以立即执行”。";
    }else if(key==="quality"||key==="missing"){
      title=key==="quality"?"数据质量分析":"缺失资料与计算限制";intro="记录质量决定可以分析哪些项目；未知项目不会按 0 处理。";
      if(quality){group("上传质量",...[["input_rows","原始行数"],["accepted_rows","接纳记录"],["skipped_rows","丢弃记录"],["incomplete_rows","信息不全"],["device_anomaly_rows","设备异常"]].filter(([k])=>quality[k]!=null).map(([k,l])=>metric(l,quality[k]," 行","来自本次导入质量检查。",0)));}
      const unknown=[!valid(w.average_hr_bpm)?"运动心率":"",!valid(load.trimp_week)?"心率训练负荷":"",!valid(rec.resting_hr_delta)?"静息心率变化":"",!valid(rec.sleep_h_avg)?"睡眠均值":"",!valid(cap.vo2max?.value)?"有氧能力估算":""].filter(Boolean);
      group("当前未知指标",row("需要补充的项目",unknown.length?unknown.join("、"):"上述主要指标已有计算值","只列当前真正缺少计算值的项目。"));
      if(m.flags?.length)group("原始数据提示",...m.flags.slice(0,12).map(x=>row(x.code||"数据提示",x.message||"无详细说明")));
      msg(unknown.length?`本次有 ${unknown.length} 类指标暂时未知，但已知训练记录仍能用于基础跑量和训练分析。`:"已检查上述主要计算项；仍需关注导入来源及记录覆盖范围。");
      method="逐项检查报告内实际字段和本次导入质量结果；不会补出缺失的心率、睡眠或训练距离。";
      limit="有记录不代表完全准确。设备误差、单位不一致、重复上传或历史覆盖不足可能影响结论。";
    }else if(key==="summary"){
      title="本周期总结的计算依据";intro="正文主要描述实际跑步表现，这里展示本周数据的计算口径。";
      group("跑步表现",metric("本周距离",w.distance_km," 公里"),metric("运动时长",w.duration_min," 分钟", "可用跑步记录总时长。",0),row("平均配速",pace(w.average_pace_s_per_km)),metric("跑步次数",w.sessions," 次","有效跑步活动。",0));
      group("补充观察",metric("近期训练负荷 TRIMP",load.trimp_week,"","有心率输入时按项目计算。"),metric("与上周跑量变化",w.distance_change_pct,"%","两周都有可用距离时计算。",1));
      msg(valid(w.distance_km)?`本周共记录 ${num(w.distance_km,2)} 公里跑步，${num(w.sessions,0)} 次；更具体的强度和恢复应另看对应章节。`:"当前缺少可汇总的跑步距离，报告仅分析已确认项目。");
      method="本周跑步数据使用同一个最近 7 天窗口，配速按总有效时长除以总距离计算。";
      limit="基础跑步指标和心率训练负荷计算条件不同；缺心率不影响距离与配速。";
    }else if(key==="advice"){
      title="训练建议的依据";intro="建议以已有训练情况、风险提醒和计划状态为依据，不凭空生成训练处方。";
      group("当前训练条件",row("下周计划状态",statusName[plan.status]||"未生成"),metric("本周跑量",w.distance_km," 公里"),metric("需要关注的信号",alerts.length," 项","不包含参考区间提示。",0));
      if(plan.status==="draft")msg("当前有待确认的训练草案。计划中的训练时长、训练日和实际身体状态仍需个人或教练确认。");
      else if(plan.status==="hold_for_review")msg("当前风险规则要求人工复核，暂不推荐直接执行自动排出的逐日计划。");
      else msg("关键输入尚不足以生成可靠的逐日计划，但本次已知的跑步表现仍可分析。");
      if(alerts.length)group("需要优先处理的风险",...alerts.slice(0,6).map(x=>row(x.title||x.rule_id,x.action||"未提供处理建议",x.evidence?.clause||"")));
      method="训练建议来自本地生成的报告与风险规则，专业窗口只说明依据，不额外生成新的高强度目标。";
      limit="不要仅依据单一数字调整跑量；异常疼痛或其他症状需优先处理。";
    }else if(key==="review"){
      title="训练报告的计算范围";intro="这份报告把跑步统计、恢复资料、风险规则和训练计划分开呈现。";
      group("统计范围",row("分析日期",`${m.window?.start||"—"} 至 ${m.window?.end||"—"}`),metric("本周跑步次数",w.sessions," 次","有记录的活动才计入。",0),metric("本周跑量",w.distance_km," 公里"));
      group("分析项目",row("运动心率",valid(w.average_hr_bpm)?"已计算":"未计算"),row("训练负荷",valid(load.trimp_week)?"已计算":"未计算"),row("下周计划",statusName[plan.status]||"未生成"));
      msg("报告正文先显示跑步表现和建议；每个章节的专业分析包含各自独立的算法说明与限制。");
      method="所有章节共享本次报告结果，不把不同时期的数值混作一次训练。";
      limit="资料缺失时报告仍能生成，但不能将未计算项目解读为正常或异常。";
    }else{
      title="训练数据分析";intro="根据已生成报告显示可核查的指标。";
      group("近期训练负荷",metric("TRIMP",load.trimp_week),metric("EWMA ACWR",load.acwr_ewma));
      method="来自当前本地报告。";limit="无法计算的项目保持未知。";
    }
    return{title,intro,insights,method,limit,groups,comparisons,entries:groups.flatMap(g=>g.rows)};
  }
  function fill(container,key){
    const v=view(key);container.replaceChildren();
    if(v.intro)html(container,"p",v.intro,"pro-lead");
    if(v.insights.length){const box=html(container,"section",null,"pro-insight");html(box,"h3","结果解读");for(const item of v.insights)html(box,"p",item);}
    if(v.comparisons.length&&v.comparisons.every(x=>valid(x.value)&&x.value>=0)){
      const wrap=html(container,"section",null,"pro-compare");html(wrap,"h3","两组数据对比");const largest=Math.max(1,...v.comparisons.map(x=>x.value));
      for(const item of v.comparisons){const row=html(wrap,"div",null,"pro-compare-line");html(row,"span",item.label);const track=html(row,"div",null,"pro-track");const bar=html(track,"div",null,"pro-bar");bar.style.width=`${Math.max(0,Math.min(100,100*item.value/largest))}%`;html(row,"strong",num(item.value,1));}
    }
    for(const group of v.groups){const section=html(container,"section",null,"pro-group");html(section,"h3",group.name);const dl=html(section,"dl",null,"pro-data-list");for(const item of group.rows){const card=html(dl,"div",null,"pro-data-item");html(card,"dt",item.label);html(card,"dd",item.value);if(item.explanation)html(card,"p",item.explanation,"pro-explanation");}}
    const method=html(container,"section",null,"pro-method");html(method,"h3","计算口径");html(method,"p",v.method||"以当前报告为准。");
    const limits=html(container,"section",null,"pro-limit");html(limits,"h3","解读限制");html(limits,"p",v.limit||"没有足够数据时不进行推算。");
    return v;
  }
  function open(key,trigger){const dialog=$("pro-dialog");if(!dialog||!report)return;previousFocus=trigger||document.activeElement;const v=fill($("pro-content"),key);$("pro-title").textContent=v.title;if(typeof dialog.showModal==="function")dialog.showModal();else dialog.setAttribute("open","");$("pro-close").focus();}
  function button(key,label){
    const names={overview:"周统计", distance:"跑量",pace:"配速",sessions:"跑步次数",duration:"跑步时长",heart:"心率",running:"跑步趋势",load:"训练负荷",plan:"计划",risk:"风险",review:"报告",checks:"自检",quality:"数据质量",summary:"训练总结",recovery:"恢复",advice:"训练建议",missing:"缺失资料"};
    label = label || (names[key] ? "查看"+names[key]+"依据" : "查看计算依据");
    const btn=document.createElement("button");btn.type="button";btn.className="pro-button";btn.dataset.pro=key;btn.textContent=label;btn.setAttribute("aria-haspopup","dialog");btn.title="查看本模块计算指标与依据";return btn;
  }
  function ensureSectionActions(header){
    let actions=header.querySelector(":scope > .section-actions");
    if(!actions){
      actions=document.createElement("div");
      actions.className="section-actions";
      for(const selector of [".panel-pill",".panel-icon"]){
        const node=header.querySelector(`:scope > ${selector}`);
        if(node)actions.append(node);
      }
      header.append(actions);
    }
    return actions;
  }
  function wire(){
    const locations=[["running-panel","running"],["load-panel","load"],["weekly","plan"],["risk-panel","risk"],["review-panel","review"],["focus-panel","load"],["timeline-panel","checks"],["data-quality","quality"]];
    for(const [id,key] of locations){
      const header=$(id)?.querySelector(".section-header");
      if(header&&!header.querySelector(".pro-button"))ensureSectionActions(header).append(button(key));
    }
    const home=document.querySelector(".runner-home-head");if(home&&!home.querySelector(".pro-button"))home.append(button("overview"));
    document.addEventListener("click",event=>{const target=event.target.closest("button[data-pro]");if(target)open(target.dataset.pro,target);});
    $("pro-close")?.addEventListener("click",()=>$("pro-dialog").close());
    $("pro-dialog")?.addEventListener("click",event=>{if(event.target===$("pro-dialog"))$("pro-dialog").close();});
    $("pro-dialog")?.addEventListener("close",()=>previousFocus?.isConnected&&previousFocus.focus());
  }
  function attachToReport(){
    const parent=$("review-content");if(!parent)return;
    const matches={"本周期训练总结":"summary","身体恢复情况":"recovery","风险评估":"risk","下周训练安排":"plan","训练建议":"advice","资料缺失及补充建议":"missing"};
    for(const section of parent.querySelectorAll(".review-section")){
      const heading=section.querySelector(":scope > h3"),key=matches[heading?.textContent];
      if(key&&!section.querySelector(".pro-button")){const head=document.createElement("div");head.className="pro-report-heading";heading.replaceWith(head);head.append(heading,button(key));}
    }
  }
  function exportDetails(key){const details=document.createElement("details");details.className="export-pro-details";html(details,"summary","专业分析 · 计算依据与解读");const body=html(details,"div",null,"export-pro-body");fill(body,key);return details;}
  function setReport(next,importQuality){report=next;quality=importQuality??null;attachToReport();}
  window.RunWiseProfessional={setReport,attachToReport,exportDetails,button,view};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",wire,{once:true});else wire();
})();
