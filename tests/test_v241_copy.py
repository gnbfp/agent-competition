"""No template-style self narration in user-facing dashboard and training review."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'
class CopyReviewTests(unittest.TestCase):
    def test_no_canned_self_narration(self):
        for name in ('server_app.html','training_review.js','dashboard.js','index.html'):
            text=(WEB/name).read_text(encoding='utf-8')
            for phrase in ('看训练量变化，不只看一个数字','现在最该做的事','先打开“七天计划”','绝不假装已判断','看不懂专业数字？','更聪明地跑，'):
                self.assertNotIn(phrase,text, f'{name}: {phrase}')
    def test_report_has_neutral_sections_and_safety_context(self):
        text=(WEB/'training_review.js').read_text(encoding='utf-8')
        for phrase in ('本周期训练总结','训练负荷分析','身体恢复情况','风险评估','下周训练安排','训练建议','指标说明（选读）','下周计划暂缓','计划待复核'):
            self.assertIn(phrase,text)
    def test_real_csv_import_and_independent_report_preserved(self):
        page=(WEB/'server_app.html').read_text(encoding='utf-8')
        assert 'id="csv-form"' in page
        assert 'id="review-export-html"' in page
        assert 'id="chart-download"' in page
        assert 'DeepSeek 七份' not in page
if __name__=='__main__': unittest.main()
