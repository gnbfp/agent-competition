"""V2.9 standalone views and topic-specific professional analysis regression tests."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'src/p5_web'
class PageNavigationTests(unittest.TestCase):
 def test_live_and_offline_include_router(self):
  server=(WEB/'server_app.html').read_text(encoding='utf-8')
  offline=(WEB/'index.html').read_text(encoding='utf-8')
  for value in ('page_navigation.js','page_navigation.css'):
   self.assertIn(value,server)
   self.assertNotIn(f'/{value}', offline)
  self.assertIn('window.RunWisePages',offline)
  self.assertIn('rw-page[hidden]',offline)
 def test_eight_distinct_pages_and_back_navigation(self):
  s=(WEB/'page_navigation.js').read_text(encoding='utf-8')
  for key in ('overview','running','advanced','weekly','risk','review','history','import'):
   self.assertIn(f'key:"{key}"',s)
  self.assertIn('popstate',s)
  self.assertIn('history.pushState',s)
  self.assertIn('rw-slide-forward',s)
 def test_local_server_assets_and_cache(self):
  server=(ROOT/'src/report_server.py').read_text(encoding='utf-8')
  sw=(WEB/'sw.js').read_text(encoding='utf-8')
  for asset in ('page_navigation.js','page_navigation.css'):
   self.assertIn('"/'+asset+'"',server)
   self.assertIn('"/'+asset+'"',sw)
  self.assertIn('runwise-shell-v35',sw)
 def test_topic_specific_professional_content(self):
  s=(WEB/'professional_analysis.js').read_text(encoding='utf-8')
  for phrase in ('跑量分析','配速分析','运动心率分析','恢复与身体状态','计划自检过程','解读限制','本周平均配速','相对前一周变化','有效心率训练','风险规则与判断依据','训练建议的依据'):
   self.assertIn(phrase,s)
  self.assertNotIn('innerHTML=',s)
  self.assertIn('showModal()',s)
 def test_no_fake_metrics(self):
  s=(WEB/'professional_analysis.js').read_text(encoding='utf-8')
  self.assertIn('"未计算"',s)
  self.assertIn('Number.isFinite',s)
  self.assertIn('无心率训练不参与心率均值',s)

if __name__=='__main__':unittest.main()
