import sys
import unittest
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m
import free_sources as f

FIXTURES = Path(__file__).parent / 'fixtures/free_sources'


class FreeSourceTests(unittest.TestCase):
    def test_shenzhen_precision_identity_and_percent(self):
        payload = m.read_json(FIXTURES / 'shenzhen.json')
        quote = f.parse_shenzhen(payload)
        self.assertEqual(quote['price'], Decimal('13818.99'))
        for field,value in [('f57','399006'), ('f59',3), ('f170',900), ('f86',None), ('f43',-1)]:
            bad = deepcopy(payload); bad['data'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                f.parse_shenzhen(bad)

    def test_shenzhen_replaces_only_older_quote_and_preserves_source_time(self):
        q = f.parse_shenzhen(m.read_json(FIXTURES / 'shenzhen.json'))
        now = datetime.fromisoformat(q['timestamp']) + timedelta(seconds=20)
        q['retrieved_at'] = now.isoformat()
        row = dict(source_timestamp=(now-timedelta(minutes=10)).isoformat(),
                   ticker='399001.SZ',name='Shenzhen',indexValue=1,field_metadata={})
        out = m.apply_free_source(row,'399001.SZ',q,{},now)
        self.assertEqual(out['source'],'Eastmoney')
        self.assertEqual(out['source_timestamp'],q['timestamp'])
        self.assertEqual(out['validation_status'],'INDICATIVE')
        self.assertIsNone(out['field_metadata']['indexValue']['currency'])
        self.assertIs(m.apply_free_source(out,'399001.SZ',q,{},now),out)
        for time in [now+timedelta(hours=1),now-timedelta(hours=1)]:
            with self.assertRaises(ValueError):m.apply_free_source(row,'399001.SZ',q,{},time)

    def tsm(self):
        q=f.parse_tsm(m.read_json(FIXTURES/'tsm_info.json'),m.read_json(FIXTURES/'tsm_summary.json'))
        now=datetime(2026,9,22,3,tzinfo=timezone.utc);q['retrieved_at']=now.isoformat()
        yahoo=dict(symbol='TSM',quoteType='EQUITY',currency='USD',exchange='NYQ',
                   longName='Taiwan Semiconductor Manufacturing Company Limited',
                   marketState='CLOSED',exchangeTimezoneName='America/New_York',
                   regularMarketTime=int(datetime(2026,9,21,20,tzinfo=timezone.utc).timestamp()),
                   regularMarketPrice=Decimal('445.14'),marketCap=Decimal('2308707188736'),
                   _retrieved_at=now.isoformat())
        return q,yahoo,now

    def test_tsm_cap_corroborated_with_provenance(self):
        q,yahoo,now=self.tsm()
        out=m.apply_free_source({'field_metadata':{}},'TSM',q,yahoo,now)
        self.assertEqual(out['marketCap'],yahoo['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['verification_sources'],['Yahoo Finance','Nasdaq'])
        self.assertIn('neither provider',out['field_metadata']['marketCap']['timestamp_scope'])
        self.assertEqual(out['marketCapUSD'],out['marketCap'])

    def test_tsm_rejects_mismatched_date_identity_price_and_cap(self):
        q,yahoo,now=self.tsm()
        for changes in [dict(symbol='2330.TW'),dict(currency='TWD'),dict(marketCap=Decimal('2050000000000')),
                        dict(regularMarketPrice=Decimal('200'))]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                m.apply_free_source({'field_metadata':{}},'TSM',q,dict(yahoo,**changes),now)
        with self.assertRaises(ValueError):
            m.apply_free_source({'field_metadata':{}},'TSM',dict(q,source_date='2026-09-18'),yahoo,now)

    def test_free_source_failure_keeps_normal_fallback(self):
        row=dict(ticker='399001.SZ',name='Shenzhen',source_timestamp='2026-09-22T03:00:00+00:00',
                 validation_status='INDICATIVE',indexValue=Decimal('13800'))
        with patch.object(m,'yahoo_quotes',return_value={}), patch.object(m,'fetch_google',side_effect=ValueError('UNAVAILABLE')), \
             patch.object(m,'fetch_shenzhen',side_effect=TimeoutError), patch.object(m,'unavailable',return_value=row):
            out,attempts=m.refresh_markets({'regions':{'indexes':[row]}})
        self.assertEqual(out['regions']['indexes'][0]['indexValue'],row['indexValue'])
        self.assertEqual(attempts[-1]['free_source_error'],'TimeoutError')


if __name__ == '__main__':unittest.main()
