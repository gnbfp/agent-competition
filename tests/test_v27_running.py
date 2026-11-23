"""V2.7 runner-first metrics and missing HR resilience."""
import unittest
from datetime import date
from src.p3_metrics.running_summary import compute_running_summary
from src.p2_ingest.csv_parser import parse_rows,build_document
from src.p3_metrics.compute import compute_metrics

class RunnerFirstTests(unittest.TestCase):
    def rows(self):
        return [dict(date='2026-11-16',sport='run',duration_s='1800',distance_m='5000',avg_hr='',max_hr=''),
                dict(date='2026-11-18',sport='run',duration_s='2400',distance_m='6000',avg_hr='',max_hr=''),
                dict(date='2026-11-20',sport='run',duration_s='3600',distance_m='10000',avg_hr='',max_hr='')]
    def test_missing_hr_still_calculates_mileage_and_weighted_pace(self):
        activities,skipped,rejected,warnings=parse_rows(self.rows())
        self.assertEqual((len(activities),len(skipped),len(rejected)),(3,0,0))
        report=compute_running_summary(build_document(activities,'anon_01'),date(2026,11,21),date(2026,11,1))
        week=report['week']
        self.assertEqual(week['distance_km'],21)
        self.assertEqual(week['sessions'],3)
        self.assertEqual(week['duration_min'],130)
        self.assertEqual(week['average_pace_s_per_km'],371)
        self.assertIsNone(week['average_hr_bpm'])
        self.assertEqual(week['hr_sessions'],0)
    def test_unknown_day_is_not_automatically_zero(self):
        activities,*_=parse_rows(self.rows())
        data=build_document(activities,'anon_01')
        unknown=compute_running_summary(data,date(2026,11,21))
        known=compute_running_summary(data,date(2026,11,21),date(2026,11,1))
        self.assertIsNone(unknown['daily'][-1]['distance_km'])
        self.assertEqual(known['daily'][-1]['distance_km'],0)
    def test_other_sports_not_counted_as_running(self):
        row=self.rows()[0].copy();row['sport']='bike'
        activities,*_=parse_rows([row]+self.rows())
        report=compute_running_summary(build_document(activities,'anon_01'),date(2026,11,21))
        self.assertEqual(report['week']['sessions'],3)
    def test_incomplete_heart_does_not_compute_trimp(self):
        acts,*_=parse_rows(self.rows());metrics=compute_metrics(build_document(acts,'anon_01'),as_of=date(2026,11,21),history_start=date(2026,11,1),resting_hr=None,max_hr=None,profile=None)
        self.assertIsNone(metrics['load']['trimp_week'])
        self.assertIsNone(metrics['load']['acwr_ewma'])
        self.assertTrue(any(item['code']=='TRIMP_INCOMPLETE_DAYS' for item in metrics['flags']))
    def test_duration_weighted_heart_rate(self):
        rows=self.rows();rows[0]['avg_hr']='120';rows[0]['max_hr']='150';rows[1]['avg_hr']='150';rows[1]['max_hr']='180'
        acts,*_=parse_rows(rows);report=compute_running_summary(build_document(acts,'anon_01'),date(2026,11,21))
        self.assertEqual(report['week']['average_hr_bpm'],137)
        self.assertEqual(report['week']['hr_sessions'],2)

if __name__=='__main__':unittest.main()
