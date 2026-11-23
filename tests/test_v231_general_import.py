"""Regression: uploaded test CSV must not turn into app-specific built-in scenarios."""
import base64, json, tempfile, unittest
from pathlib import Path
from src.pipeline import SAMPLE, browser_run
from contracts.validate_contract import validate_document

class GeneralImportTests(unittest.TestCase):
    def test_data_is_uploaded_using_generic_csv_route(self):
        csv=(SAMPLE/'demo_activity.csv').read_bytes()
        payload={"mode":"csv", "csv":base64.b64encode(csv).decode(),
                 "options":{"as_of":"2026-11-14", "history_start":"2026-10-18",
                            "resting_hr":55,"max_hr":183,"trimp_profile":"female",
                            "source":"middle","athlete":"ATH-001"}}
        with tempfile.TemporaryDirectory() as tmp:
            path=browser_run(payload,Path(tmp))
            report=json.loads((path/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['schema_version'],'2.0')
            self.assertFalse(validate_document(Path('report.json'),report))
    def test_specific_scenario_api_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                browser_run({'mode':'scenario','scene':'01-stable'},Path(tmp))
    def test_ui_and_offline_export_stay_generic(self):
        root=Path(__file__).resolve().parents[1]
        web=root/'src/p5_web'
        html=(web/'server_app.html').read_text()
        js=(web/'dashboard.js').read_text()
        offline=(web/'index.html').read_text()
        self.assertIn('id="import-panel"',html)
        self.assertIn('id="review-panel"',html)
        self.assertNotIn('scenario-select',html+js+offline)
        self.assertNotIn('DeepSeek 七份',html+js+offline)
        self.assertIn('RUNWISE_OFFLINE_REPORT',offline)
        self.assertIn('<style>',offline)
        self.assertNotIn('href="/dashboard.css"',offline)
        self.assertFalse((root/'data/DeepSeek_六套测试数据').exists())
        self.assertIn('csvDateRange',js)

if __name__=='__main__':unittest.main()
