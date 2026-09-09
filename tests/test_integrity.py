import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import tempfile
import market_data as m
from news_integrity import canonical_url, merge_news
from fetch_data import parse_date


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 8, 15, tzinfo=timezone.utc)
        self.row = {'ticker': 'MSFT', 'name': 'Microsoft', 'sector': 'Cloud / AI'}
        self.yahoo = {'symbol': 'MSFT', 'longName': 'Microsoft Corporation',
            'exchange': 'NMS', 'quoteType': 'EQUITY', 'currency': 'USD',
            'exchangeTimezoneName': 'America/New_York', 'marketState': 'REGULAR',
            'regularMarketTime': int(self.now.timestamp()), '_retrieved_at': self.now.isoformat(),
            'regularMarketPrice': Decimal('100.000'), 'regularMarketPreviousClose': Decimal('100.000'),
            'regularMarketChange': Decimal('0.000'), 'regularMarketChangePercent': Decimal('0.0000'),
            'marketCap': Decimal('1000000000')}
        self.google = {'id': 'MSFT:NASDAQ', 'name': 'Microsoft Corp', 'exchange': 'NASDAQ',
            'currency': 'USD', 'timestamp': self.now.isoformat(), 'retrieved_at': self.now.isoformat(),
            'price': Decimal('100.000'), 'previousClose': Decimal('100.000'),
            'marketCap': Decimal('1000000000'), 'cap_resolution': Decimal('10000000')}

    def accept(self):
        return m.accepted(self.row, 'MSFT', self.yahoo, self.google, self.now)

    def test_precision_and_zero_change(self):
        result = self.accept()
        self.assertEqual(result['field_metadata']['indexValue']['decimal'], '100.000')
        self.assertEqual(result['field_metadata']['changePercent']['decimal'], '0.000000')

    def test_change_uses_displayed_snapshot_not_earlier_yahoo_quote(self):
        self.yahoo.update(regularMarketPrice=Decimal('100.4'),
                          regularMarketChange=Decimal('0.4'), regularMarketChangePercent=Decimal('0.4'))
        result = self.accept()
        self.assertEqual(result['indexValue'], Decimal('100'))
        self.assertEqual(result['changePercent'], Decimal('0'))
        self.assertEqual(result['absoluteChange'], Decimal('0'))
        self.assertEqual(result['field_metadata']['changePercent']['source'], 'Google Finance')

    def test_missing_previous_close_does_not_reuse_yesterdays_change(self):
        self.row = self.accept()
        self.google.pop('previousClose')
        self.yahoo.pop('regularMarketPreviousClose')
        result = self.accept()
        self.assertIsNone(result['previousClose'])
        self.assertIsNone(result['changePercent'])
        self.assertIsNone(result['absoluteChange'])

    def test_failed_asian_refresh_never_converts_usd_twice(self):
        for currency, rate in [('HKD', '7.8416'), ('KRW', '1300')]:
            with self.subTest(currency=currency):
                row = self.accept()
                row.update(currency=currency, quote_currency=currency)
                fx = dict(indexValue=Decimal(rate), base_currency='USD', quote_currency=currency,
                          validation_status='INDICATIVE', source='Google Finance', source_timestamp=self.now.isoformat())
                converted = m.convert_usd(row, fx)
                cap, native = converted['marketCap'], converted['nativeMarketCap']
                for _ in range(3):
                    converted = m.convert_usd(m.unavailable(converted, 'SOURCE_UNAVAILABLE'), fx)
                    self.assertEqual(converted['marketCap'], cap)
                    self.assertEqual(converted['nativeMarketCap'], native)
                    self.assertEqual(converted['field_metadata']['marketCap']['validation_status'], 'STALE')
                self.assertEqual(m.convert_usd(converted, None)['marketCap'], cap)

    def test_conflict(self):
        self.google['price'] = Decimal('150')
        with self.assertRaisesRegex(ValueError, 'SOURCE_CONFLICT'):
            self.accept()

    def fx_quotes(self):
        a = dict(self.yahoo, symbol='INR=X', quoteType='CURRENCY', currency='INR',
                 exchange='CCY', exchangeTimezoneName='Asia/Kolkata',
                 regularMarketPrice=Decimal('94.4905'), quote_basis='midpoint')
        b = dict(self.google, id='USD-INR', currency='INR', exchange='CCY',
                 price=Decimal('94.4905'), quote_basis='midpoint')
        return a, b

    def test_usdinr_reported_discrepancy_rejected(self):
        a, b = self.fx_quotes()
        a['regularMarketPrice'] = Decimal('94.475')
        with self.assertRaisesRegex(ValueError, 'SOURCE_CONFLICT'):
            m.validate_pair({}, 'INR=X', a, b, self.now)

    def test_google_fx_visible_without_yahoo_and_preserves_precision(self):
        _, b = self.fx_quotes()
        b.pop('quote_basis')
        row = m.google_fx({'ticker':'INR=X'}, 'INR=X', b, self.now)
        self.assertEqual(row['validation_status'], 'INDICATIVE')
        self.assertEqual(row['field_metadata']['indexValue']['decimal'], '94.4905')
        self.assertEqual(row['field_metadata']['indexValue']['verification_sources'], [])
        payload = {'regions':{'currency':[{'ticker':'INR=X','name':'USD/INR'}]}}
        b['timestamp'] = datetime.now(timezone.utc).isoformat()
        with patch.object(m, 'yahoo_quotes', side_effect=TimeoutError), patch.object(m, 'fetch_google', return_value=b):
            output, _ = m.refresh_markets(payload)
        self.assertEqual(output['regions']['currency'][0]['indexValue'], Decimal('94.4905'))

    def test_old_google_fx_visible_and_failed_refresh_retains_timestamp(self):
        _, b = self.fx_quotes()
        b['timestamp'] = (self.now-timedelta(days=3)).isoformat()
        row = m.google_fx({'ticker':'INR=X'}, 'INR=X', b, self.now)
        self.assertEqual(row['validation_status'], 'STALE')
        retained = m.unavailable(row, 'TimeoutError')
        self.assertEqual(retained['indexValue'], Decimal('94.4905'))
        self.assertEqual(retained['source_timestamp'], b['timestamp'])
        self.assertEqual(retained['quote_quality'], 'INDICATIVE')

    def test_google_fx_still_rejects_invalid_observations(self):
        _, b = self.fx_quotes()
        for updates in [{'id':'EUR-INR'}, {'currency':'USD'}, {'price':Decimal('NaN')},
                        {'price':0}, {'timestamp':(self.now+timedelta(hours=1)).isoformat()}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                m.google_fx({}, 'INR=X', dict(b, **updates), self.now)

    def test_fx_matching_basis_precision_and_policy(self):
        a, b = self.fx_quotes()
        out = m.accepted({'ticker': 'INR=X', 'name': 'USD/INR'}, 'INR=X', a, b, self.now)
        self.assertEqual(out['field_metadata']['indexValue']['decimal'], '94.4905')
        self.assertEqual(out['quote_policy']['max_quote_age_seconds'], 480)
        self.assertEqual(out['validation_evidence']['price_relative_tolerance'], Decimal('0.0001'))
        for basis in [None, 'bid']:
            b['quote_basis'] = basis
            with self.assertRaisesRegex(ValueError, 'FX_QUOTE_BASIS_UNCONFIRMED'):
                m.validate_pair({}, 'INR=X', a, b, self.now)

    def test_fx_close_timestamps_and_freshness_required(self):
        a, b = self.fx_quotes()
        b['timestamp'] = (self.now-timedelta(seconds=61)).isoformat()
        with self.assertRaisesRegex(ValueError, 'INCOMPARABLE_SOURCE_TIMESTAMPS'):
            m.validate_pair({}, 'INR=X', a, b, self.now)
        old = self.now-timedelta(seconds=481)
        a['regularMarketTime'] = int(old.timestamp())
        b['timestamp'] = old.isoformat()
        with self.assertRaisesRegex(ValueError, 'STALE_SOURCE_DATA'):
            m.validate_pair({}, 'INR=X', a, b, self.now)

    def test_independent_pair_identity_required(self):
        a, b = self.fx_quotes()
        b['id'] = 'EUR-INR'
        with self.assertRaisesRegex(ValueError, 'INDEPENDENT_INSTRUMENT_ID_MISMATCH'):
            m.validate_pair({}, 'INR=X', a, b, self.now)

    def test_cap_only_allows_display_rounding_interval(self):
        self.yahoo['marketCap'] = Decimal('1006000000')
        self.assertIsNone(self.accept()['marketCap'])
        self.yahoo['marketCap'] = Decimal('1004000000')
        self.assertEqual(self.accept()['marketCap'], Decimal('1004000000'))

    def test_missing_or_nonfinite_never_zero(self):
        for value in [None, True, '', 'NaN', 'Infinity', '-Infinity']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.decimal(value)

    def test_exchange_currency_symbol_and_name(self):
        for key, value in [('exchange', 'NSE'), ('currency', 'INR'), ('symbol', 'AAPL'), ('longName', 'Unrelated Fund')]:
            original = self.yahoo[key]
            self.yahoo[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.accept()
            self.yahoo[key] = original

    def test_timestamps(self):
        with self.assertRaisesRegex(ValueError, 'NAIVE_TIMESTAMP'):
            m.timestamp('2026-09-08T15:00:00')
        for delta in [-1500, 200, -86400]:
            self.google['timestamp'] = (self.now+timedelta(seconds=delta)).isoformat()
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.accept()

    def test_stale_agreeing_quotes(self):
        old = self.now-timedelta(hours=1)
        self.yahoo['regularMarketTime'] = int(old.timestamp())
        self.google['timestamp'] = old.isoformat()
        with self.assertRaisesRegex(ValueError, 'STALE_SOURCE_DATA'):
            self.accept()

    def test_closed_long_weekend(self):
        self.now = self.now.replace(hour=8)
        old = self.now-timedelta(days=4)
        self.yahoo['marketState'] = 'CLOSED'
        self.yahoo['regularMarketTime'] = int(old.timestamp())
        self.google['timestamp'] = old.isoformat()
        result = self.accept()
        self.assertEqual(result['market_status'], 'CLOSED')
        self.assertEqual(result['source_timestamp'], old.isoformat())

    def test_holiday_and_lunch_break(self):
        quote = dict(self.yahoo, marketState='CLOSED')
        state, _ = m.session_state(quote, datetime(2026, 9, 7, 15, tzinfo=timezone.utc))
        self.assertEqual(state, 'HOLIDAY')
        quote.update(exchange='HKG', exchangeTimezoneName='Asia/Hong_Kong', marketState='REGULAR')
        state, _ = m.session_state(quote, datetime(2026, 9, 8, 4, 30, tzinfo=timezone.utc))
        self.assertEqual(state, 'BREAK')

    def test_unknown_india_holiday_not_inferred(self):
        quote = dict(self.yahoo, exchange='NSI', exchangeTimezoneName='Asia/Kolkata', marketState='CLOSED')
        state, calendar = m.session_state(quote, self.now)
        self.assertEqual(state, 'CLOSED')
        self.assertIsNone(calendar)

    def test_missing_field_retains_provenance(self):
        self.row = self.accept()
        self.yahoo.pop('marketCap')
        result = self.accept()
        self.assertEqual(result['marketCap'], self.row['marketCap'])
        self.assertEqual(result['field_metadata']['marketCap']['validation_status'], 'STALE')
        self.assertEqual(result['field_metadata']['marketCap']['source_timestamp'], self.row['field_metadata']['marketCap']['source_timestamp'])

    def test_unknown_session_fails(self):
        self.yahoo['marketState'] = None
        with self.assertRaisesRegex(ValueError, 'MARKET_STATUS'):
            self.accept()

    def test_legacy_not_promoted(self):
        result = m.unavailable(dict(self.row, indexValue=123, validationStatus='VERIFIED'), 'FAIL')
        self.assertIsNone(result['indexValue'])
        self.assertEqual(result['legacy_snapshot']['indexValue'], 123)

    def test_verified_fallback_preserves_time(self):
        original = self.accept()
        result = m.unavailable(original, 'SOURCE_CONFLICT')
        self.assertEqual(result['source_timestamp'], original['source_timestamp'])
        self.assertEqual(result['retrieved_at'], original['retrieved_at'])
        self.assertEqual(result['indexValue'], original['indexValue'])
        self.assertEqual(result['validation_status'], 'STALE')

    def test_no_cap_calculation_or_conflict_acceptance(self):
        self.yahoo['marketCap'] = 3000000000
        self.assertIsNone(self.accept()['marketCap'])
        self.yahoo.pop('marketCap')
        self.yahoo['sharesOutstanding'] = 99999
        self.assertIsNone(self.accept()['marketCap'])

    def test_outlier_no_split_exemption(self):
        self.row.update(verification_version=1, indexValue=Decimal('50'))
        self.google['price'] = Decimal('100.3')
        with self.assertRaisesRegex(ValueError, 'OUTLIER'):
            self.accept()
        self.google['price'] = Decimal('100.000')
        self.assertEqual(self.accept()['indexValue'], Decimal('100'))

    def test_fx_decimal_and_missing_rate(self):
        row = self.accept()
        row.update(quote_currency='HKD', currency='HKD', marketCap=Decimal('10.00'))
        fx = dict(indexValue=Decimal('3'), base_currency='USD', quote_currency='HKD',
                  validation_status='VERIFIED', source='Google Finance', source_timestamp=self.now.isoformat())
        result = m.convert_usd(row, fx)
        self.assertEqual(str(result['marketCap']), '3.333333333333333333333333333333333')
        self.assertEqual(result['nativeMarketCap'], Decimal('10'))
        row = self.accept(); row.update(quote_currency='HKD', currency='HKD')
        self.assertIsNone(m.convert_usd(row, None)['marketCap'])

    def test_fx_direction(self):
        row = self.accept(); row.update(quote_currency='HKD', currency='HKD')
        with self.assertRaisesRegex(ValueError, 'FX_DIRECTION'):
            m.convert_usd(row, {'validation_status': 'VERIFIED', 'base_currency': 'HKD', 'quote_currency': 'USD'})

    def test_atomic_json_decimal_and_nan(self):
        # Keep fixture paths in workspace, including on Windows hosts with restricted TEMP.
        path = Path(__file__).parent.parent / 'work' / 'test-atomic.json'
        payload = {'price': Decimal('123.0000')}
        m.atomic_write(path, payload)
        self.assertIn('123.0000', path.read_text())
        self.assertFalse(m.atomic_write(path, payload))
        self.assertEqual(m.read_json(path)['price'].as_tuple().exponent, -4)
        with self.assertRaises(ValueError):
            m.atomic_write(path, {'price': float('nan')})
        with self.assertRaises(ValueError):
            m.atomic_write(path, {'price': Decimal('NaN')})
        self.assertEqual(m.read_json(path), payload)

    def test_google_wrong_page(self):
        with self.assertRaisesRegex(ValueError, 'IDENTITY'):
            m.parse_google('<link rel="canonical" href="https://www.google.com/finance/quote/AAPL:NASDAQ">', 'MSFT:NASDAQ')

    def test_url_security_and_tracking(self):
        for url in ['javascript:alert(1)', 'http://localhost/a', 'https://openai.com.evil.test/a', 'https://user:pass@openai.com/a']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_url(url)
        self.assertEqual(canonical_url('https://www.openai.com/news/a?utm_source=x#fragment'), 'https://openai.com/news/a')

    def test_news_future_dates_duplicates_and_stability(self):
        now = datetime.now(timezone.utc)
        item = dict(title='OpenAI announces a new research model', summary='Publisher summary',
                    published=now.isoformat(), source='OpenAI', url='https://openai.com/news/model', isAI=True)
        def confirmed(value):
            return dict(value, verification_status='SOURCE_CONFIRMED')
        with patch('news_integrity.verify_article', side_effect=confirmed):
            first = merge_news([item, dict(item, url=item['url']+'?utm_source=x'),
                                dict(item, published=(now+timedelta(days=1)).isoformat())], [], parse_date, 'tech')
            self.assertEqual(len(first), 1)
            self.assertEqual(first, merge_news([item], first, parse_date, 'tech'))

    def test_noop_refresh_ignores_retrieval_clock(self):
        original = self.accept()
        payload = {'updated': self.now.isoformat(), 'regions': {'us': [original]}}
        def accept_again(row, symbol, a, b, now):
            return dict(row, retrieved_at='2026-09-08T15:05:00+00:00')
        with patch.object(m, 'yahoo_quotes', return_value={'MSFT': self.yahoo}), \
             patch.object(m, 'fetch_google', return_value=self.google), \
             patch.object(m, 'accepted', side_effect=accept_again), \
             patch.object(m, 'fill_google_fields', side_effect=lambda row, *args: row):
            output, attempts = m.refresh_markets(payload)
        self.assertEqual(output, payload)
        self.assertEqual(len(attempts), 3)  # existing row + two internal FX dependencies

    def test_failed_fetch_preserves_universe(self):
        payload = {'regions': {'us': [dict(self.row, indexValue=100)], 'currency': []}}
        with patch.object(m, 'yahoo_quotes', side_effect=TimeoutError), \
             patch.object(m, 'fetch_google', side_effect=TimeoutError):
            output, attempts = m.refresh_markets(payload)
        self.assertEqual(list(output['regions']), list(payload['regions']))
        self.assertEqual([r['ticker'] for r in output['regions']['us']], ['MSFT'])
        self.assertIsNone(output['regions']['us'][0]['indexValue'])

    def test_google_display_precision_fixture(self):
        body = '''<link rel="canonical" href="https://www.google.com/finance/quote/MSFT:NASDAQ">
        <div class="zzDege">Microsoft Corp</div>
        <div data-last-price="123" data-currency-code="USD" data-exchange="NASDAQ"
        data-last-normal-market-timestamp="1788879600"><div class="YMlKec">$123.0000</div></div>'''
        result = m.parse_google(body, 'MSFT:NASDAQ')
        self.assertEqual(format(result['price'], 'f'), '123.0000')

    def test_futures_contract_not_substituted(self):
        with self.assertRaisesRegex(ValueError, 'MAPPING_UNAVAILABLE'):
            m.google_id('CL=F', {'quoteType': 'FUTURE'})

    def test_google_missing_cap_and_calculated_change_are_indicative(self):
        row = self.accept()
        row['marketCap'] = None
        row['changePercent'] = None
        quote = dict(self.google, price=Decimal('101'),previousClose=Decimal('100'))
        out = m.fill_google_fields(row, quote, self.now)
        self.assertEqual(out['marketCap'], quote['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['quality'],'INDICATIVE')
        self.assertEqual(out['changePercent'],Decimal('1.000000'))
        self.assertIn('Google',out['field_metadata']['changePercent']['calculation'])

    def test_google_futures_explicit_series_identity_and_units(self):
        quote = dict(self.google,id='ZCW00:CBOT',name='Corn Continuous Contract',exchange='CBOT',currency='USX',price=Decimal('539.75'))
        row = {'ticker':'ZC=F','name':'Corn','currency':'USX','unit':'cents/bushel'}
        out = m.google_observation(row,'ZC=F',quote,{},self.now)
        self.assertEqual(out['google_instrument'],'ZCW00:CBOT')
        self.assertEqual(out['currency'],'USX')
        self.assertEqual(out['validation_status'],'INDICATIVE')
        with self.assertRaisesRegex(ValueError,'CURRENCY_MISMATCH'):
            m.google_observation(row,'ZC=F',dict(quote,currency='USD'),{},self.now)
        with self.assertRaisesRegex(ValueError,'INDEPENDENT_INSTRUMENT_ID_MISMATCH'):
            m.google_observation(row,'ZC=F',dict(quote,id='ZSW00:CBOT'),{},self.now)

    def test_stale_google_fx_conversion_is_not_verified(self):
        row = self.accept(); row.update(quote_currency='HKD',currency='HKD',marketCap=Decimal('10'))
        fx = dict(indexValue=Decimal('2'),base_currency='USD',quote_currency='HKD',
                  validation_status='STALE',source='Google Finance',source_timestamp=self.now.isoformat())
        out=m.convert_usd(row,fx)
        self.assertEqual(out['marketCap'],Decimal('5'))
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'],'STALE')
        self.assertEqual(out['field_metadata']['marketCap']['quality'],'INDICATIVE')

    def test_google_float_artifact_uses_display_precision(self):
        body = '''<link rel="canonical" href="https://www.google.com/finance/quote/GCW00:COMEX">
        <div data-last-price="4448.10009765625" data-last-normal-market-timestamp="1788851396">
        <div class="YMlKec">$4,448.10</div></div>'''
        self.assertEqual(str(m.parse_google(body,'GCW00:COMEX')['price']),'4448.10')


if __name__ == '__main__':
    unittest.main()
