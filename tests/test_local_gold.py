import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import requests
from local_gold import GOLD_ID, parse_gold, refresh_gold

PAGE = (Path(__file__).parent / 'fixtures/groww_gold.html').read_text(encoding='utf-8')


class LocalGoldTests(unittest.TestCase):
    now = datetime(2026, 9, 15, 10, tzinfo=timezone.utc)

    def test_city_purity_units_date_and_change(self):
        row = parse_gold(PAGE, self.now)
        self.assertEqual(row['indexValue'], Decimal('15317'))
        self.assertEqual(row['changePercent'], Decimal('-0.60'))
        self.assertEqual(row['unit'], 'INR/gram')
        self.assertEqual(row['source_date'], '2026-09-15')
        self.assertEqual(row['validation_status'], 'INDICATIVE')

    def test_rejects_wrong_city_purity_units_and_future_date(self):
        for old, new in [('Hyderabad', 'Delhi'), ('TWENTY_FOUR', 'MISSING_PURITY'),
                         ('1 Gram', '1 Ounce'), ('₹15,317.00', '₹0'),
                         ('₹1,22,536.00', '₹1,22,537.00'), ('2026-09-15', '2026-09-16')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_gold(PAGE.replace(old, new), self.now)

    def test_missing_change_is_not_zero(self):
        row = parse_gold(PAGE.replace('-0.5970536699331559', 'null'), self.now)
        self.assertIsNone(row['changePercent'])
        self.assertNotIn('changePercent', row['field_metadata'])

    def test_old_source_date_is_stale(self):
        self.assertEqual(parse_gold(PAGE, self.now + timedelta(days=3))['validation_status'], 'STALE')

    @patch('local_gold.requests.get', side_effect=requests.Timeout)
    def test_failure_never_relabels_futures(self, _):
        row = refresh_gold({'ticker':'GC=F', 'indexValue':5000, 'unit':'USD/troy oz'}, self.now)
        self.assertEqual(row['ticker'], GOLD_ID)
        self.assertIsNone(row['indexValue'])
        self.assertEqual(row['validation_status'], 'DATA_UNAVAILABLE')

    @patch('local_gold.requests.get', side_effect=requests.Timeout)
    def test_failure_retains_local_rate_and_original_date(self, _):
        previous = parse_gold(PAGE, self.now)
        row = refresh_gold(previous, self.now + timedelta(days=1))
        self.assertEqual(row['indexValue'], previous['indexValue'])
        self.assertEqual(row['source_date'], previous['source_date'])
        self.assertEqual(row['validation_status'], 'STALE')
        self.assertEqual(row['field_metadata']['indexValue']['validation_status'], 'STALE')
        self.assertEqual(previous['validation_status'], 'INDICATIVE')
