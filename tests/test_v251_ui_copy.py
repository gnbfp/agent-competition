"""V2.5.1 UI state and copy regression checks."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'
class CopyAndLayoutTests(unittest.TestCase):
    def test_no_false_report_headline_or_duplicated_explanation(self):
        js=(WEB/'dashboard.js').read_text()
        self.assertNotIn('有记录的数据仍然可以查看、分析和导出',js)
        self.assertNotIn('已生成训练分析报告',js)
        self.assertIn('暂未生成下周计划',js)
        self.assertIn('$("timeline-panel").hidden=!(report.plan.attempts||[]).length',js)
    def test_hero_actions_are_labeled_and_state_sensitive(self):
        h=(WEB/'server_app.html').read_text()
        js=(WEB/'dashboard.js').read_text()
        for id in ('hero-plan-link','hero-report-link','hero-risk-link','plan-bottom'):
            self.assertIn('id="'+id+'"',h)
        self.assertIn('planLink.hidden=!planAvailable',js)
        self.assertIn('reportLink.className=planAvailable?',js)
    def test_glossary_is_optional_and_copy_is_concise(self):
        js=(WEB/'training_review.js').read_text()
        self.assertNotIn('报告已生成，缺少的项目不会按零处理',js)
        self.assertIn('指标说明（选读）',js)
    def test_revisions_keep_generic_csv_import(self):
        js=(WEB/'dashboard.js').read_text()
        self.assertIn('function readUpload()',js)
        self.assertNotIn('DeepSeek 七份模拟',js)
if __name__=='__main__':unittest.main()
