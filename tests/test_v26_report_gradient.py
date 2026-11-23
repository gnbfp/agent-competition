"""V2.6 regression: useful report exists despite absent optional metrics; animated background is accessible."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from test_plan_report import demo_inputs
from src.p4_agent.evidence import load_rules
from src.p4_agent.planner import generate_plan
from src.p4_agent.report import build_report
from src.p4_agent.run import run_agent
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT/'src/p5_web'

class ReportAndMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        activities,metrics,context = demo_inputs()
        metrics['capacity']['vo2max']['value'] = None
        metrics['recovery']['daily'][-1]['resting_hr_bpm'] = None
        metrics['recovery']['resting_hr_delta'] = None
        metrics['recovery']['sleep_h_avg'] = None
        rules = load_rules()
        assessment = run_agent(metrics,activities=activities,context=context,rules=rules)
        plan = generate_plan(metrics,assessment,rules,activities=activities,context=context)
        cls.report = build_report(metrics,assessment,plan,rules,generated_at='2026-11-22T10:00:00+08:00')

    @unittest.skipUnless(shutil.which('node'), 'Node not available')
    def test_missing_three_metrics_still_produces_substantive_summary(self):
        script='''const fs=require('fs'),vm=require('vm');const source=fs.readFileSync(process.argv[1],'utf8');
        const data=JSON.parse(fs.readFileSync(0,'utf8'));global.window={};vm.runInThisContext(source);
        let r=window.RunWiseReview.build(data,null);
        process.stdout.write(JSON.stringify({known:r.knownCount, lines:r.summaryLines,advice:r.advice,missing:r.completeness.filter(x=>typeof x.value!=="number").map(x=>x.label), plan:r.planDays.length, trimp:r.metrics.weekTrimp}));'''
        process=subprocess.run(['node','-e',script,str(WEB/'training_review.js')],input=json.dumps(self.report),text=True,capture_output=True)
        self.assertEqual(process.returncode,0,process.stderr)
        r=json.loads(process.stdout)
        self.assertEqual(r['plan'],0)
        self.assertIn('有氧能力估算',r['missing'])
        self.assertIn('静息心率变化',r['missing'])
        self.assertIn('睡眠情况',r['missing'])
        self.assertGreaterEqual(len(r['lines']),3)
        self.assertAlmostEqual(r['trimp'],120.7,places=1)  # professional figure retained; plain summary need not show TRIMP
        self.assertTrue(r['advice'])

    def test_report_order_is_analysis_first_missing_last(self):
        code=(WEB/'training_review.js').read_text()
        self.assertLess(code.index('main.append(lead,summary,runStats)'),code.index('main.append(foldSection(available'))
        for title in ('本周期训练总结','训练负荷分析','身体恢复情况','风险评估','下周训练安排','训练建议','资料缺失及补充建议'):
            self.assertIn(title,code)

    def test_infinite_gradient_and_motion_accessibility(self):
        code=(WEB/'dashboard.css').read_text()
        self.assertIn('@keyframes runwise-gradient-flow',code)
        self.assertIn('animation:runwise-gradient-flow',code)
        self.assertIn('infinite',code)
        self.assertIn('prefers-reduced-motion:reduce',code)
        self.assertIn('html.motion-paused',code)
        self.assertIn('@media print',code)
        self.assertIn('id="motion-toggle"',(WEB/'server_app.html').read_text())
        self.assertIn('runwise-motion-paused',(WEB/'readability.js').read_text())

    def test_offline_view_is_self_contained(self):
        html=(WEB/'index.html').read_text()
        self.assertIn('window.RUNWISE_OFFLINE_REPORT',html)
        self.assertNotIn('href="/dashboard.css"',html)
        self.assertIn('本周期训练总结',html)
        self.assertIn('motion-toggle',html)
        self.assertNotIn('DeepSeek 七份',html)

if __name__=='__main__':unittest.main()
