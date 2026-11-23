"""Partial reports remain readable while unverified schedules are withheld."""
from __future__ import annotations
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
from contracts.validate_contract import validate_document

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'
class PartialReportTests(unittest.TestCase):
    def scenario(self, status):
        activity,metrics,context=demo_inputs()
        if status=='awaiting_input':
            metrics['recovery']['daily'][-1]['resting_hr_bpm']=None
            metrics['recovery']['resting_hr_delta']=None
            metrics['capacity']['vo2max']['value']=None
        else:
            context['pain_reported']=True
        rules=load_rules()
        assessment=run_agent(metrics,activities=activity,context=context,rules=rules)
        plan=generate_plan(metrics,assessment,rules,activities=activity,context=context)
        report=build_report(metrics,assessment,plan,rules,generated_at='2026-11-22T08:00:00+08:00')
        self.assertEqual(report['plan']['status'],status)
        self.assertEqual(report['plan']['days'],[])
        self.assertEqual(validate_document('report.json',report),[])
        return report
    def test_report_kept_when_recovery_and_capacity_are_unknown(self):
        report=self.scenario('awaiting_input')
        self.assertIsNotNone(report['metrics']['load']['trimp_week'])
        self.assertIsNone(report['metrics']['capacity']['vo2max']['value'])
        self.assertIsNone(report['metrics']['recovery']['resting_hr_delta'])
        self.assertEqual(report['plan']['attempts'],[])
    def test_high_risk_still_withholds_schedule_but_not_report(self):
        report=self.scenario('hold_for_review')
        self.assertTrue(report['risks'])
    @unittest.skipUnless(shutil.which('node'),'Node not available')
    def test_frontend_review_build_renders_partial_data(self):
        report=self.scenario('awaiting_input')
        script='''const fs=require('fs'),vm=require('vm');const source=fs.readFileSync(process.argv[1],'utf8');
const data=JSON.parse(fs.readFileSync(0,'utf8'));global.window={};vm.runInThisContext(source);
const result=window.RunWiseReview.build(data,null);console.log(JSON.stringify({count:result.knownCount,missing:result.completeness.filter(x=>typeof x.value!=="number"),summary:result.summaryLabel,plan:result.planDays.length,lines:result.loadText}));'''
        p=subprocess.run(['node','-e',script,str(WEB/'training_review.js')],input=json.dumps(report),text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        result=json.loads(p.stdout)
        self.assertEqual(result['plan'],0)
        self.assertTrue(any(x['label']=='有氧能力估算' for x in result['missing']))
        self.assertTrue(any(x['label']=='静息心率变化' for x in result['missing']))
        self.assertTrue(any('最近 7 天训练负荷' in x for x in result['lines']))
    def test_cta_and_plan_check_wording_do_not_claim_success(self):
        text=(WEB/'dashboard.js').read_text()
        self.assertIn('查看训练报告',text)
        self.assertIn('未生成草案 · 未进行计划自检',text)
        self.assertIn('暂未生成下周计划',text)
        self.assertIn('"未知"',text)
        self.assertNotIn('status.textContent="已做必要的风险检查"',text)

if __name__ == '__main__':unittest.main()
