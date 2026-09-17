"""Regression tests for beta quote pages and Asian market-cap conversions."""
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m

FIXTURES = Path(__file__).parent / 'fixtures' / 'google_beta'


class StockRefreshTests(unittest.TestCase):
    def body(self, name):
        return (FIXTURES / (name + '.html')).read_text(encoding='utf-8')

    def test_beta_regular_quote_excludes_after_hours(self):
        q = m.parse_google(self.body('MSFT_NASDAQ'), 'MSFT:NASDAQ')
        self.assertEqual(q['price'], Decimal('490.30'))
        self.assertEqual(q['previousClose'], Decimal('497.12'))
        self.assertEqual(q['timestamp'], '2026-09-16T20:00:01+00:00')
        self.assertEqual(q['marketCap'], Decimal('3640000000000'))
        self.assertEqual(q['cap_resolution'], Decimal('10000000000'))

    def test_native_market_caps_and_fx(self):
        for name, identifier, currency, cap in [
            ('005930_KRX', '005930:KRX', 'KRW', '1635180000000000'),
            ('0700_HKG', '0700:HKG', 'HKD', '3880000000000'),
            ('ADANIENT_NSE', 'ADANIENT:NSE', 'INR', '4190000000000'),
        ]:
            with self.subTest(identifier=identifier):
                q = m.parse_google(self.body(name), identifier)
                self.assertEqual(q['currency'], currency)
                self.assertEqual(q['marketCap'], Decimal(cap))
        fx = m.parse_google(self.body('USD-KRW'), 'USD-KRW')
        self.assertEqual(fx['exchange'], 'CCY')
        self.assertEqual(fx['currency'], 'KRW')
        self.assertEqual(fx['price'], Decimal('1380.7700'))

    def test_google_cap_fallback_updates_usd_companion(self):
        q = m.parse_google(self.body('MSFT_NASDAQ'), 'MSFT:NASDAQ')
        row = m.google_observation({'name': 'Microsoft', 'ticker': 'MSFT'}, 'MSFT', q,
            {'quoteType': 'EQUITY', 'exchange': 'NMS', 'currency': 'USD'},
            datetime.fromisoformat(q['timestamp']))
        self.assertEqual(row['marketCapUSD'], row['marketCap'])
        self.assertEqual(row['field_metadata']['marketCapUSD'], row['field_metadata']['marketCap'])

    def test_beta_identity_and_schema_fail_closed(self):
        body = self.body('MSFT_NASDAQ')
        with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
            m.parse_google(body, 'AMD:NASDAQ')
        with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
            m.parse_google(body.replace('["MSFT","NASDAQ"]', '["AMD","NASDAQ"]'), 'MSFT:NASDAQ')
        with self.assertRaisesRegex(ValueError, 'TIMESTAMP_UNAVAILABLE'):
            m.parse_google(body.replace('[1789588801]', 'null'), 'MSFT:NASDAQ')
        with self.assertRaisesRegex(ValueError, 'SCHEMA_CHANGED'):
            m.parse_google(body.replace("key: 'ds:2'", "key: 'ds:99'"), 'MSFT:NASDAQ')

    def native_row(self):
        q = m.parse_google(self.body('0700_HKG'), '0700:HKG')
        now = datetime.fromisoformat(q['timestamp'])
        return m.google_observation({'name': 'Tencent', 'ticker': '0700.HK'},
            '0700.HK', q, {'quoteType': 'EQUITY', 'exchange': 'HKG', 'currency': 'HKD'}, now)

    def fx(self):
        return {'indexValue': Decimal('8'), 'base_currency': 'USD', 'quote_currency': 'HKD',
                'validation_status': 'INDICATIVE', 'source': 'Google Finance',
                'source_timestamp': '2026-09-17T03:23:29+00:00'}

    def test_conversion_once_and_refresh_failure_preserves_dollars(self):
        row = m.convert_usd(self.native_row(), self.fx())
        expected = Decimal('485000000000')
        self.assertEqual(row['marketCap'], expected)
        self.assertEqual(row['nativeMarketCap'], Decimal('3880000000000'))
        self.assertEqual(row['native_market_cap_metadata']['currency'], 'HKD')
        self.assertEqual(row['field_metadata']['marketCap']['currency'], 'USD')
        stale = m.unavailable(row, 'SOURCE_UNAVAILABLE')
        self.assertEqual(stale['field_metadata']['marketCap']['validation_status'], 'STALE')
        for fx in [self.fx(), None]:
            self.assertEqual(m.convert_usd(deepcopy(stale), fx)['marketCap'], expected)

    def test_fx_outage_keeps_native_cap_and_can_recover(self):
        row = m.convert_usd(self.native_row(), None)
        self.assertEqual(row['marketCap'], Decimal('3880000000000'))
        self.assertEqual(row['currency'], 'HKD')
        self.assertIsNone(row['marketCapUSD'])
        self.assertEqual(m.convert_usd(row, self.fx())['marketCap'], Decimal('485000000000'))

    def test_repeated_failures_retain_verified_snapshot_as_stale(self):
        row = self.native_row()
        row.pop('quote_quality')
        row['validation_status'] = 'VERIFIED'
        for meta in row['field_metadata'].values():
            if meta.get('decimal'):
                meta['validation_status'] = 'VERIFIED'
        original = deepcopy(row)
        for _ in range(3):
            row = m.unavailable(row, 'SOURCE_UNAVAILABLE')
            self.assertEqual(row['validation_status'], 'STALE')
            self.assertEqual(row['marketCap'], original['marketCap'])
            self.assertEqual(row['source_timestamp'], original['source_timestamp'])
            self.assertEqual(row['field_metadata']['marketCap']['validation_status'], 'STALE')


if __name__ == '__main__':
    unittest.main()
