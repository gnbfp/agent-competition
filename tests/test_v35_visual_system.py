"""V3.5 design-system integration and accessibility guard rails."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'

class UnifiedVisualSystemTests(unittest.TestCase):
    def test_theme_loaded_in_service_and_offline(self):
        theme=(WEB/'theme_unified.css').read_text(encoding='utf-8')
        service=(WEB/'server_app.html').read_text(encoding='utf-8')
        offline=(WEB/'index.html').read_text(encoding='utf-8')
        routes=(ROOT/'src/report_server.py').read_text(encoding='utf-8')
        cache=(WEB/'sw.js').read_text(encoding='utf-8')
        self.assertIn('href="/theme_unified.css"',service)
        self.assertIn('"/theme_unified.css"',routes)
        self.assertIn('"/theme_unified.css"',cache)
        self.assertIn('RunWise AI V3.5 - unified visual language',offline)
        self.assertIn(':root.dark',theme)
    def test_eight_pages_and_reduced_motion(self):
        theme=(WEB/'theme_unified.css').read_text(encoding='utf-8')
        for selector in ('.runner-home','#running-panel','#load-panel','#weekly','#risk-panel',
                         '.review-panel','#history-panel','#import-panel','#ai-panel'):
            self.assertIn(selector,theme)
        self.assertIn('prefers-reduced-motion:reduce',theme)
        self.assertIn('html.motion-paused',theme)
        self.assertIn('@media print',theme)
    def test_focus_layout_and_chart_palette(self):
        markup=(WEB/'server_app.html').read_text(encoding='utf-8')
        chart=(WEB/'dashboard.js').read_text(encoding='utf-8')
        self.assertIn('class="focus-copy"',markup)
        self.assertIn('#74c7d8',chart)
        self.assertIn('#6bbdcc',chart)
    def test_palette_text_contrast(self):
        def luminance(hexvalue):
            values=[int(hexvalue[i:i+2],16)/255 for i in (1,3,5)]
            values=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in values]
            return .2126*values[0]+.7152*values[1]+.0722*values[2]
        def ratio(a,b):
            light,dark=sorted([luminance(a),luminance(b)],reverse=True)
            return (light+.05)/(dark+.05)
        self.assertGreaterEqual(ratio('#FFFFFF','#126778'),4.5)
        self.assertGreaterEqual(ratio('#F0F7FA','#142838'),7)
        self.assertGreaterEqual(ratio('#B6CBD8','#142838'),4.5)

if __name__=='__main__':
    unittest.main()
