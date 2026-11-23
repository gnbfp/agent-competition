"""Ensure the easy-reading UI remains connected to generic CSV imports and honest report exports."""
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'
class ReadabilityTests(unittest.TestCase):
    def test_explanations_and_visible_headings(self):
        source=(WEB/'training_review.js').read_text()
        for title in ('本周期训练总结','训练负荷分析', '身体恢复情况', '下周训练安排', '训练建议', '指标说明（选读）'):
            self.assertIn(title, source)
        self.assertIn('textContent', source)
        self.assertIn('review-print', source)
        self.assertIn('训练负荷（TRIMP）',source)
    def test_high_contrast_and_adjustable_text_size(self):
        page=(WEB/'server_app.html').read_text()
        css=(WEB/'dashboard.css').read_text()
        self.assertIn('id="text-size-toggle"',page)
        self.assertIn('src="/readability.js"',page)
        self.assertIn('--muted:#395348',css)
        self.assertIn('.reader-large',css)
        self.assertIn('@media print',css)
        self.assertIn('color:#111e17!important',css)
    def test_generic_csv_only_and_offline_self_contained(self):
        server=(WEB/'server_app.html').read_text()
        offline=(WEB/'index.html').read_text()
        self.assertIn('id="import-panel"',server)
        self.assertNotIn('DeepSeek 七份',offline+server)
        self.assertNotIn('scenario-select',offline+server)
        self.assertIn('window.RUNWISE_OFFLINE_REPORT',offline)
        self.assertNotIn('href="/dashboard.css"',offline)
        self.assertIn('id="text-size-toggle"',offline)
        self.assertIn('指标说明（选读）',offline)
        self.assertIn('readability.js',Path('src/report_server.py').read_text())

if __name__=='__main__':unittest.main()
