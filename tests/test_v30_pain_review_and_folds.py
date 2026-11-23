"""V3.0 regression: review never overrides real pain, and report sections fold."""
import base64
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import SAMPLE, browser_run
from src.report_server import report_handler
from contracts.validate_contract import load_json
from test_pipeline import request

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src' / 'p5_web'
ORIGIN = 'http://127.0.0.1:8080'


class PainReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def payload(self, *, csv_pain=False):
        csv_text = (SAMPLE / 'demo_activity.csv').read_text('utf-8')
        if csv_pain:
            rows = csv_text.splitlines()
            rows[0] += ',pain'
            rows[1:] = [line + (',膝盖疼痛' if i==len(rows)-2 else ',') for i,line in enumerate(rows[1:])]
            csv_text = '\n'.join(rows) + '\n'
        return {
            'mode':'csv',
            'csv':base64.b64encode(csv_text.encode()).decode(),
            'options':{'athlete':'ATH-001','source':'middle',
                       'as_of':'2026-11-14','history_start':'2026-10-18',
                       'resting_hr':55,'max_hr':183,'trimp_profile':'female'},
            'context':{'athlete_id':'ATH-001','pain_reported':True,'max_hr_source':'measured'},
            'measurements':json.loads((SAMPLE / 'demo_measurements.json').read_text('utf-8')),
        }

    def test_human_confirmed_pain_keeps_r15_and_hold(self):
        initial = browser_run(self.payload(),self.out)
        self.assertTrue((initial/'context.json').is_file())
        self.assertEqual(load_json(initial/'context.json')['pain_reported'],True)
        handler=report_handler(initial/'report.json',on_run=lambda x:browser_run(x,self.out))
        snapshot=json.loads(request(handler,'/api/snapshot')[2])
        source=json.loads(request(handler,'/api/r15-review')[2])
        self.assertTrue(source['available'])
        self.assertFalse(source['csv_pain'])
        req={'report_id':snapshot['report_id'],'choice':'pain_present','confirmed':True}
        status,_,body=request(handler,'/api/r15-review',data=req,origin=ORIGIN)
        self.assertEqual(status,200,body)
        updated=json.loads(body)['report']
        self.assertEqual(updated['plan']['status'],'hold_for_review')
        self.assertIn('R15',{x['rule_id'] for x in updated['risks']})
        self.assertTrue(any('R15 手动核对' in x for x in updated['disclaimers']))

    def test_context_typo_corrected_recomputes_and_keeps_other_gates(self):
        initial=browser_run(self.payload(),self.out)
        handler=report_handler(initial/'report.json',on_run=lambda x:browser_run(x,self.out))
        snapshot=json.loads(request(handler,'/api/snapshot')[2])
        req={'report_id':snapshot['report_id'],'choice':'context_record_incorrect','confirmed':True}
        status,_,body=request(handler,'/api/r15-review',data=req,origin=ORIGIN)
        self.assertEqual(status,200,body)
        updated=json.loads(body)
        self.assertNotIn('R15',{x['rule_id'] for x in updated['report']['risks']})
        self.assertNotEqual(updated['report_id'],snapshot['report_id'])
        self.assertEqual(json.loads(request(handler,'/api/snapshot')[2])['report_id'],updated['report_id'])
        self.assertEqual(request(handler,'/api/r15-review',data=req,origin=ORIGIN)[0],409)

    def test_csv_pain_cannot_be_overridden_and_no_false_clearance(self):
        initial=browser_run(self.payload(csv_pain=True),self.out)
        handler=report_handler(initial/'report.json',on_run=lambda x:browser_run(x,self.out))
        snapshot=json.loads(request(handler,'/api/snapshot')[2])
        source=json.loads(request(handler,'/api/r15-review')[2])
        self.assertTrue(source['csv_pain'])
        req={'report_id':snapshot['report_id'],'choice':'context_record_incorrect','confirmed':True}
        status,_,body=request(handler,'/api/r15-review',data=req,origin=ORIGIN)
        self.assertEqual(status,422,body)
        self.assertIn('CSV',json.loads(body)['message'])
        self.assertEqual(json.loads(request(handler,'/api/snapshot')[2]),snapshot)

    def test_legacy_report_can_acknowledge_pain_without_clearing_r15(self):
        initial=browser_run(self.payload(),self.out)
        (initial/'context.json').unlink()  # Simulates a report from V2.9.1.
        handler=report_handler(initial/'report.json',on_run=lambda x:browser_run(x,self.out))
        snapshot=json.loads(request(handler,'/api/snapshot')[2])
        sources=json.loads(request(handler,'/api/r15-review')[2])
        self.assertFalse(sources['available'])
        req={'report_id':snapshot['report_id'],'choice':'context_record_incorrect','confirmed':True}
        self.assertEqual(request(handler,'/api/r15-review',data=req,origin=ORIGIN)[0],422)
        req['choice']='pain_present'
        status,_,body=request(handler,'/api/r15-review',data=req,origin=ORIGIN)
        self.assertEqual(status,200,body)
        report=json.loads(body)['report']
        self.assertEqual(report['plan']['status'],'hold_for_review')
        self.assertIn('R15',{x['rule_id'] for x in report['risks']})
        self.assertIn('未重新计算',json.loads(body)['message'])

    def test_review_endpoint_requires_ack_and_same_origin(self):
        initial=browser_run(self.payload(),self.out)
        handler=report_handler(initial/'report.json',on_run=lambda x:browser_run(x,self.out))
        snapshot=json.loads(request(handler,'/api/snapshot')[2]); rid=snapshot['report_id']
        req={'report_id':rid,'choice':'context_record_incorrect','confirmed':False}
        self.assertEqual(request(handler,'/api/r15-review',data=req,origin=ORIGIN)[0],400)
        req['confirmed']=True
        self.assertEqual(request(handler,'/api/r15-review',data=req,origin='https://other.example')[0],403)

    def test_five_fold_sections_and_moving_emphasis_exist(self):
        js=(WEB/'training_review.js').read_text('utf-8')
        css=(WEB/'dashboard.css').read_text('utf-8')
        for section in ('身体恢复情况','风险评估','下周训练安排','需要核对的事项','资料缺失及补充建议'):
            self.assertIn(section,js)
        self.assertGreaterEqual(js.count('foldSection('),6)
        self.assertIn('@keyframes rw-vibrant-current',css)
        self.assertIn('html.motion-paused',css)
        self.assertIn('prefers-reduced-motion:reduce',css)

if __name__ == '__main__':unittest.main()
