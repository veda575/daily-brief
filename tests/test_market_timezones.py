import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from market_timezones import apply_region_timezones


class RegionalTimeTests(unittest.TestCase):
    def test_offsets_rollover_and_source_preservation(self):
        for source, offsets in [
            ('2026-01-15T20:00:00+00:00', {'us': '2026-01-15T15:00:00-05:00',
             'india': '2026-01-16T01:30:00+05:30', 'asia': '2026-01-16T04:00:00+08:00'}),
            ('2026-07-15T20:00:00+00:00', {'us': '2026-07-15T16:00:00-04:00',
             'india': '2026-07-16T01:30:00+05:30', 'asia': '2026-07-16T04:00:00+08:00'}),
        ]:
            payload = {'regions': {region: [{'source_timestamp': source,
                'market_timezone': 'Asia/Seoul', 'validation_status': 'STALE'}] for region in offsets}}
            apply_region_timezones(payload)
            for region, expected in offsets.items():
                row = payload['regions'][region][0]
                self.assertEqual(row['source_timestamp_local'], expected)
                self.assertEqual(row['source_timestamp'], source)
                self.assertEqual(row['market_timezone'], 'Asia/Seoul')
                self.assertEqual(row['validation_status'], 'STALE')

    def test_missing_invalid_and_naive_times_not_fabricated(self):
        payload = {'regions': {'us': [{'source_timestamp': value} for value in
            [None, '', 'invalid', '2026-01-15T20:00:00']]}}
        apply_region_timezones(payload)
        self.assertTrue(all(row['source_timestamp_local'] is None for row in payload['regions']['us']))

    def test_dst_transition(self):
        for instant, expected in [('2026-03-08T06:59:00Z', '2026-03-08T01:59:00-05:00'),
                                  ('2026-03-08T07:00:00Z', '2026-03-08T03:00:00-04:00')]:
            payload = {'regions': {'us': [{'source_timestamp': instant}]}}
            self.assertEqual(apply_region_timezones(payload)['regions']['us'][0]['source_timestamp_local'], expected)
