"""Refresh regressions: source rollout, exact instruments, and worker cadence."""
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m
import refresh_loop as worker


class RecoveryTests(unittest.TestCase):
    def test_stock_fallback_is_indicative_and_rejects_wrong_issuer(self):
        now = datetime(2026, 9, 21, 15, tzinfo=timezone.utc)
        row = dict(ticker='MSFT', name='Microsoft', currency='USD', exchange='NMS')
        quote = dict(symbol='MSFT', longName='Microsoft Corporation', quoteType='EQUITY',
                     exchange='NMS', currency='USD', marketState='REGULAR',
                     exchangeTimezoneName='America/New_York', regularMarketTime=int(now.timestamp()),
                     regularMarketPrice=Decimal('100'), regularMarketPreviousClose=Decimal('99'),
                     marketCap=Decimal('1000000000'), _retrieved_at=now.isoformat())
        out = m.yahoo_observation(row, 'MSFT', quote, now)
        self.assertEqual(out['validation_status'], 'INDICATIVE')
        self.assertEqual(out['source'], 'Yahoo Finance')
        self.assertEqual(out['field_metadata']['marketCap']['source'], 'Yahoo Finance')
        for changes in [dict(symbol='AMD'), dict(longName='AMD'), dict(currency='INR'), dict(exchange='NYQ')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                m.yahoo_observation(row, 'MSFT', dict(quote, **changes), now)

    def test_yahoo_fx_recovers_failed_google_without_mixing_previous_close(self):
        now = datetime.now(timezone.utc)
        yahoo = dict(symbol='INR=X', quoteType='CURRENCY', currency='INR',
                     regularMarketPrice=Decimal('96'), regularMarketPreviousClose=Decimal('100'),
                     regularMarketTime=int(now.timestamp()), _retrieved_at=now.isoformat())
        out = m.freshest_fx({'ticker':'INR=X'}, 'INR=X', {'error':'GOOGLE_IDENTITY_MISMATCH'}, yahoo, now)
        self.assertEqual(out['source'], 'Yahoo Finance')
        self.assertEqual(out['changePercent'], Decimal('-4'))
        self.assertEqual(out['validation_status'], 'INDICATIVE')
        self.assertEqual(out['field_metadata']['changePercent']['source'], 'Yahoo Finance')
        self.assertEqual(out['field_metadata']['indexValue']['verification_sources'], [])
        for changes in [dict(symbol='EURUSD=X'), dict(currency='USD'), dict(quoteType='EQUITY'),
                        dict(regularMarketPrice=Decimal('NaN'))]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                m.freshest_fx({}, 'INR=X', {'error':'UNAVAILABLE'}, dict(yahoo, **changes), now)

    def test_google_identity_failure_retries_without_accepting_wrong_instrument(self):
        response = Mock(text='page')
        quote = {'timestamp': datetime.now(timezone.utc).isoformat(), 'id': 'USD-INR'}
        with patch.object(m.requests, 'get', return_value=response) as get, \
             patch.object(m, 'parse_google', side_effect=[ValueError('GOOGLE_IDENTITY_MISMATCH'), quote]):
            self.assertEqual(m.fetch_google('USD-INR'), quote)
            self.assertIn('/beta/quote/USD-INR', get.call_args.args[0])
        with patch.object(m.requests, 'get', return_value=response), \
             patch.object(m, 'parse_google', side_effect=ValueError('GOOGLE_IDENTITY_MISMATCH')):
            with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
                m.fetch_google('USD-INR')

    def test_stale_fx_retry_keeps_newest_actual_source_timestamp(self):
        newer = {'timestamp': '2026-09-01T00:00:00+00:00', 'price': Decimal('95')}
        older = {'timestamp': '2026-08-31T00:00:00+00:00', 'price': Decimal('94')}
        with patch.object(m.requests, 'get', return_value=Mock(text='page')), \
             patch.object(m, 'parse_google', side_effect=[newer, older]):
            self.assertEqual(m.fetch_google('USD-INR'), newer)

    def test_beta_short_futures_heading_preserves_exact_series_requirement(self):
        now = datetime.now(timezone.utc)
        quote = dict(id='CLW00:NYMEX', name='Crude Oil', exchange='NYMEX',
                     currency='USD', price=Decimal('94.31'),
                     timestamp=now.isoformat(), retrieved_at=now.isoformat())
        row = dict(ticker='CL=F', name='Crude Oil', currency='USD')
        result = m.google_observation(row, 'CL=F', quote, {}, now)
        self.assertEqual(result['indexValue'], Decimal('94.31'))
        self.assertEqual(result['validation_status'], 'INDICATIVE')
        for changes in [dict(id='CLZ26:NYMEX'), dict(exchange='COMEX'), dict(name='Natural Gas')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                m.google_observation(row, 'CL=F', dict(quote, **changes), {}, now)

    def test_refresh_does_not_drift_or_overlap(self):
        self.assertEqual(worker.next_tick(1000, 1075, 300), 1300)
        self.assertEqual(worker.next_tick(1000, 1350, 300), 1600)

    def test_failed_fetch_is_never_committed_or_pushed(self):
        import subprocess
        with patch.object(worker, 'run', side_effect=[None, None, subprocess.TimeoutExpired('fetch', 240)]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                worker.cycle('main')
        self.assertFalse(any('push' in c.args or 'commit' in c.args for c in run.call_args_list))

    def test_push_failure_is_not_force_pushed(self):
        import subprocess
        with patch.object(worker, 'run', side_effect=[None, None, None, None, None, subprocess.CalledProcessError(1, 'push')]) as run, \
             patch.object(worker.subprocess, 'run', return_value=Mock(returncode=1)):
            with self.assertRaises(subprocess.CalledProcessError):
                worker.cycle('main')
        self.assertEqual(run.call_args.args, ('git', 'push', 'origin', 'HEAD:main'))


if __name__ == '__main__':
    unittest.main()
