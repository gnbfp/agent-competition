"""Progressive disclosure: professional data remains tied to real report values."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'

class ProfessionalAnalysisTests(unittest.TestCase):
    def test_live_and_offline_include_professional_modal(self):
        for file in (WEB/'server_app.html', WEB/'index.html'):
            s=file.read_text(encoding='utf-8')
            for text in ('id="pro-dialog"','id="pro-title"','id="pro-close"','id="pro-content"'):
                self.assertIn(text,s)
        self.assertIn('professional_analysis.js',(WEB/'server_app.html').read_text())
        self.assertIn('RunWiseProfessional',(WEB/'index.html').read_text())

    def test_modal_never_fills_missing_values(self):
        s=(WEB/'professional_analysis.js').read_text()
        self.assertIn('"未计算"',s)
        self.assertIn('Number.isFinite',s)
        self.assertNotIn('innerHTML=',s)
        self.assertIn('exportDetails',s)
        self.assertIn('showModal()',s)

    def test_report_export_replaces_interactive_buttons_with_details(self):
        s=(WEB/'training_review.js').read_text()
        self.assertIn('cloneNode(true)',s)
        self.assertIn('exportDetails(key)',s)
        self.assertIn('const contents=cloned.innerHTML',s)

    def test_static_resource_mapping(self):
        s=(ROOT/'src/report_server.py').read_text()
        self.assertIn('"/professional_analysis.js"',s)
        self.assertIn('"/professional_analysis.css"',s)

if __name__=='__main__': unittest.main()
