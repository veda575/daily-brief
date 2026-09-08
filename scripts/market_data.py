"""Fail-closed, decimal-preserving market validation. Never promotes legacy data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from functools import lru_cache
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo
import os
import re
import tempfile
import math

import requests
import simplejson as json
from bs4 import BeautifulSoup
import yfinance as yf
import exchange_calendars as calendars
import pandas as pd

FIELDS = ('indexValue', 'marketCap', 'changePercent', 'absoluteChange',
          'previousClose', 'dayHigh', 'dayLow', 'volume', 'marketCapUSD')
EXCHANGES = {'NMS': 'NASDAQ', 'NGM': 'NASDAQ', 'NCM': 'NASDAQ', 'NYQ': 'NYSE',
             'ASE': 'NYSEAMERICAN', 'NSE': 'NSE', 'NSI': 'NSE', 'BSE': 'BOM', 'HKG': 'HKG',
             'KSC': 'KRX', 'SHH': 'SHA', 'SHZ': 'SHE'}
INDEX_IDS = {'^BSESN': 'SENSEX:INDEXBOM', '^IXIC': '.IXIC:INDEXNASDAQ',
             '^HSI': 'HSI:INDEXHANGSENG', '000001.SS': '000001:SHA',
             '399001.SZ': '399001:SHE', 'DX-Y.NYB': 'DXY:INDEXICE'}
PAIRS = {'INR=X': ('USD', 'INR'), 'JPY=X': ('USD', 'JPY'),
         'CNY=X': ('USD', 'CNY'), 'EURUSD=X': ('EUR', 'USD'),
         'GBPUSD=X': ('GBP', 'USD'), 'HKD=X': ('USD', 'HKD'),
         'KRW=X': ('USD', 'KRW')}
# Explicit issuer aliases, never replacements for a different listed instrument.
ALIASES = {'TSM': ['taiwan semiconductor', 'taiwan semicndctr mnufctrng'],
           'GE': ['general electric company'], 'TCS.NS': ['tata consultancy'],
           'SPCX': ['space exploration technologies'], 'ETERNAL.NS': ['eternal'],
           'KIMS.NS': ['krishna institute'], 'AMD': ['advanced micro devices'],
           'DIVISLAB.NS': ['divi s laboratories', 'divis laboratories']}
CALENDARS = {'NMS': 'XNYS', 'NGM': 'XNYS', 'NCM': 'XNYS', 'NYQ': 'XNYS',
             'NIM': 'XNYS', 'HKG': 'XHKG', 'KSC': 'XKRX', 'SHH': 'XSHG'}


@lru_cache(maxsize=12)
def exchange_calendar(name):
    return calendars.get_calendar(name)


def session_state(quote, now):
    state = {'REGULAR': 'OPEN', 'PRE': 'PRE_MARKET', 'POST': 'AFTER_HOURS',
             'PREPRE': 'CLOSED', 'POSTPOST': 'CLOSED', 'CLOSED': 'CLOSED'}.get(quote.get('marketState'))
    if not state:
        raise ValueError('MARKET_STATUS_UNAVAILABLE')
    local_day = now.astimezone(ZoneInfo(quote['exchangeTimezoneName'])).date()
    name = CALENDARS.get(quote.get('exchange'))
    if name:
        cal = exchange_calendar(name)
        day, minute = pd.Timestamp(local_day), pd.Timestamp(now).floor('min')
        if not cal.is_session(day):
            if state == 'OPEN':
                raise ValueError('MARKET_STATUS_CALENDAR_CONFLICT')
            return ('WEEKEND' if local_day.weekday() >= 5 else 'HOLIDAY'), name
        if cal.is_break_minute(minute):
            return 'BREAK', name
        if cal.is_open_on_minute(minute) and state == 'CLOSED':
            raise ValueError('MARKET_STATUS_CALENDAR_CONFLICT')
        if not cal.is_open_on_minute(minute) and state == 'OPEN':
            raise ValueError('MARKET_STATUS_CALENDAR_CONFLICT')
    if local_day.weekday() >= 5 and state == 'CLOSED':
        state = 'WEEKEND'
    return state, name


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def decimal(value):
    if value is None or isinstance(value, bool) or value == '':
        raise ValueError('MISSING_NUMBER')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('INVALID_NUMBER') from exc
    if not result.is_finite():
        raise ValueError('NONFINITE_NUMBER')
    return result


def timestamp(value):
    if isinstance(value, (int, Decimal)):
        return datetime.fromtimestamp(int(value), timezone.utc)
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('NAIVE_TIMESTAMP')
    return result.astimezone(timezone.utc)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), use_decimal=True)


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    def finite(value):
        if isinstance(value, Decimal) and not value.is_finite() or isinstance(value, float) and not math.isfinite(value):
            raise ValueError('NONFINITE_NUMBER')
        if isinstance(value, dict):
            for child in value.values(): finite(child)
        elif isinstance(value, list):
            for child in value: finite(child)
    finite(payload)
    body = json.dumps(payload, use_decimal=True, allow_nan=False, indent=2, ensure_ascii=False) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == body:
        return False
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def yahoo_quotes(symbols):
    """One batch, raw JSON Decimal parsing; bounded request, no fast_info mixing."""
    result = {}
    yf.set_tz_cache_location(os.getenv('YF_CACHE_DIR', 'work/yf-cache'))
    for offset in range(0, len(symbols), 50):
        batch = symbols[offset:offset + 50]
        # yfinance owns Yahoo cookie/crumb negotiation. Pin its adapter version.
        response = yf.Ticker(batch[0])._data.get(
            'https://query1.finance.yahoo.com/v7/finance/quote',
            params={'symbols': ','.join(batch)}, timeout=12)
        response.raise_for_status()
        payload = json.loads(response.text, use_decimal=True)
        for quote in payload.get('quoteResponse', {}).get('result', []):
            if quote.get('symbol') in batch:
                quote['_retrieved_at'] = now_iso()
                result[quote['symbol']] = quote
    return result


def google_id(symbol, quote):
    if symbol in PAIRS:
        return '-'.join(PAIRS[symbol])
    if symbol in INDEX_IDS:
        return INDEX_IDS[symbol]
    # Continuous futures do not prove identical expiry/roll methodology.
    if quote.get('quoteType') != 'EQUITY':
        raise ValueError('INDEPENDENT_INSTRUMENT_MAPPING_UNAVAILABLE')
    exchange = EXCHANGES.get(quote.get('exchange'))
    if not exchange:
        raise ValueError('UNSUPPORTED_EXCHANGE')
    code = symbol.split('.')[0]
    if exchange == 'HKG':
        code = code.zfill(4)
    return code + ':' + exchange


def display_number(text):
    match = re.search(r'[-+]?\d[\d,]*(?:\.\d+)?', text)
    if not match:
        raise ValueError('MISSING_NUMBER')
    return decimal(match.group().replace(',', ''))


def parse_google(body, identifier):
    soup = BeautifulSoup(body, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"]')
    if not canonical or unquote(urlparse(canonical.get('href', '')).path).split('/')[-1] != identifier:
        raise ValueError('GOOGLE_IDENTITY_MISMATCH')
    nodes = soup.select('[data-last-price][data-last-normal-market-timestamp]')
    if len(nodes) != 1:
        raise ValueError('GOOGLE_QUOTE_SCHEMA_CHANGED')
    node = nodes[0]
    result = {'source': 'Google Finance', 'id': identifier,
              'currency': node.get('data-currency-code'), 'exchange': node.get('data-exchange'),
              'price': decimal(node['data-last-price']),
              'timestamp': timestamp(int(node['data-last-normal-market-timestamp'])).isoformat(),
              'retrieved_at': now_iso(), 'session': 'REGULAR'}
    heading = soup.select_one('.zzDege')
    result['name'] = heading.get_text(' ', strip=True) if heading else ''
    if identifier in {'-'.join(pair) for pair in PAIRS.values()}:
        # The canonical currency-pair URL itself specifies the denominator currency.
        result['currency'] = identifier.split('-')[1]
        result['exchange'] = 'CCY'
    shown = node.select_one('.YMlKec')
    if shown and display_number(shown.get_text()) == result['price']:
        result['price'] = display_number(shown.get_text())
    for row in soup.select('.gyFHrc'):
        label, value = row.select_one('.mfs7Fc'), row.select_one('.P6K39c')
        if not label or not value:
            continue
        key, raw = label.get_text(strip=True), value.get_text(' ', strip=True)
        try:
            if key == 'Previous close':
                result['previousClose'] = display_number(raw)
            elif key == 'Day range':
                nums = re.findall(r'\d[\d,]*(?:\.\d+)?', raw)
                if len(nums) == 2:
                    result['dayLow'], result['dayHigh'] = [decimal(n.replace(',', '')) for n in nums]
            elif key == 'Market cap':
                match = re.fullmatch(r'([\d.,]+)\s*([TBMK]?)\s+([A-Z]{3})', raw)
                if match and match[3] == result['currency']:
                    base = decimal(match[1].replace(',', ''))
                    scale = Decimal(10) ** {'T': 12, 'B': 9, 'M': 6, 'K': 3, '': 0}[match[2]]
                    result['marketCap'] = base * scale
                    result['cap_resolution'] = Decimal(10) ** base.as_tuple().exponent * scale
        except ValueError:
            continue
    return result


def fetch_google(identifier):
    response = requests.get('https://www.google.com/finance/quote/' + identifier,
                            params={'hl': 'en'}, timeout=(4, 10))
    response.raise_for_status()
    return parse_google(response.text, identifier)


def issuer_matches(name, candidate, symbol):
    def normalize(s):
        s = re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()
        return re.sub(r'\b(ltd|limited|inc|corporation|corp)\b', '', s).strip()
    candidate = normalize(candidate)
    options = [normalize(name.split('(')[0])] + ALIASES.get(symbol, [])
    return any(option and (option in candidate or candidate and candidate in option) for option in options)


def validate_pair(row, symbol, a, b, now):
    if a.get('symbol') != symbol:
        raise ValueError('TICKER_MISMATCH')
    expected_type = 'CURRENCY' if symbol in PAIRS else 'INDEX' if symbol in INDEX_IDS else 'FUTURE' if symbol.endswith('=F') else 'EQUITY'
    if a.get('quoteType') != expected_type:
        raise ValueError('SECURITY_TYPE_MISMATCH')
    if expected_type == 'EQUITY':
        if not issuer_matches(row['name'], a.get('longName') or a.get('shortName', ''), symbol) or not issuer_matches(row['name'], b['name'], symbol):
            raise ValueError('ISSUER_IDENTITY_REQUIRES_REVIEW')
        if EXCHANGES.get(a.get('exchange')) != b.get('exchange'):
            raise ValueError('EXCHANGE_MISMATCH')
    if expected_type == 'CURRENCY' and a.get('currency') != PAIRS[symbol][1]:
        raise ValueError('FX_DIRECTION_MISMATCH')
    if expected_type == 'INDEX':
        # An index level has units of points, not a monetary conversion.
        if b.get('exchange') != INDEX_IDS[symbol].split(':')[1]:
            raise ValueError('INDEX_EXCHANGE_MISMATCH')
    elif not a.get('currency') or a['currency'] != b.get('currency'):
        raise ValueError('CURRENCY_MISMATCH')
    if b.get('id') != google_id(symbol, a):
        raise ValueError('INDEPENDENT_INSTRUMENT_ID_MISMATCH')
    ZoneInfo(a['exchangeTimezoneName'])
    state, _ = session_state(a, now)
    ta, tb = timestamp(a['regularMarketTime']), timestamp(b['timestamp'])
    if min((now-ta).total_seconds(), (now-tb).total_seconds()) < -120:
        raise ValueError('FUTURE_TIMESTAMP')
    policy = quote_policy(symbol, state)
    if abs((ta-tb).total_seconds()) > policy['max_timestamp_skew_seconds']:
        raise ValueError('INCOMPARABLE_SOURCE_TIMESTAMPS')
    # Closing quotes can span long weekends; never label them live.
    max_age = policy['max_quote_age_seconds']
    if max((now-ta).total_seconds(), (now-tb).total_seconds()) > max_age:
        raise ValueError('STALE_SOURCE_DATA')
    price, other = decimal(a['regularMarketPrice']), decimal(b['price'])
    if price <= 0 or other <= 0:
        raise ValueError('NONPOSITIVE_PRICE')
    if abs(price-other) / other > policy['price_relative_tolerance']:
        raise ValueError('SOURCE_CONFLICT')
    if symbol in PAIRS:
        # Neither public adapter documents bid/ask/midpoint. Never infer it.
        basis = a.get('quote_basis')
        if basis not in {'bid', 'ask', 'midpoint', 'last'} or basis != b.get('quote_basis'):
            raise ValueError('FX_QUOTE_BASIS_UNCONFIRMED')
    # Split-shaped jumps are NOT automatically exempted.
    if row.get('verification_version') == 1 and row.get('indexValue'):
        if abs(price / decimal(row['indexValue']) - 1) > Decimal('0.35'):
            # Two independent comparable quotes must agree tightly before accepting.
            if abs(price-other) / other > Decimal('0.0005'):
                raise ValueError('OUTLIER_REQUIRES_ADDITIONAL_VALIDATION')
    return ta, tb


def quote_policy(symbol, state):
    """Conservative acceptance limits, not a guarantee of provider accuracy."""
    fx = symbol in PAIRS
    return {'policy_version': 2,
            'price_relative_tolerance': Decimal('0.0001') if fx else Decimal('0.001') if symbol in INDEX_IDS else Decimal('0.005'),
            'max_timestamp_skew_seconds': 60 if fx else 1200,
            # FX: disclosed three-minute Google delay plus one refresh interval.
            'max_quote_age_seconds': 480 if fx else 1800 if state == 'OPEN' else 7200 if state == 'BREAK' else 7 * 86400}


def unavailable(row, reason):
    result = deepcopy(row)
    symbol = row.get('source_symbol') or row.get('ticker')
    result['quote_policy'] = quote_policy(symbol, row.get('market_status'))
    if row.get('verification_version') == 1 and row.get('source_timestamp') and row.get('field_metadata', {}).get('indexValue', {}).get('validation_status') == 'VERIFIED':
        result['validation_status'] = 'STALE'
    else:
        # Preserve historical bytes as evidence, never reuse as verified history.
        result.setdefault('legacy_snapshot', {k: row[k] for k in FIELDS if k in row})
        for field in FIELDS:
            result[field] = None
        result['validation_status'] = 'DATA_UNAVAILABLE'
        result['source_timestamp'] = None
        result['market_status'] = 'TEMPORARILY_UNAVAILABLE'
    result['validationStatus'] = result['validation_status']
    result['error'] = {'status': 'VALIDATION_FAILED', 'reason': reason}
    return result


def accepted(row, symbol, a, b, now):
    ta, tb = validate_pair(row, symbol, a, b, now)
    state, calendar_name = session_state(a, now)
    out = deepcopy(row)
    out.pop('error', None)
    out.pop('field_conflicts', None)
    for field in FIELDS:
        out[field] = None
    out.update(verification_version=1, validation_status='VERIFIED', validationStatus='VERIFIED',
               validation_scope='regular-session quote; other fields have independent field_metadata status',
               source='Google Finance', source_timestamp=b['timestamp'],
               retrieved_at=b['retrieved_at'], quote_currency=a['currency'], currency=a['currency'],
               exchange=a['exchange'], market_timezone=a['exchangeTimezoneName'],
               source_symbol=symbol, instrument_type=a['quoteType'], quote_session='REGULAR',
               market_status=state, calendar=calendar_name,
               market_status_basis='Yahoo Finance + exchange_calendars' if calendar_name else 'Yahoo Finance; holiday calendar unavailable',
               provider_market_state=a['marketState'], field_metadata={})
    out['quote_policy'] = quote_policy(symbol, state)
    if now.astimezone(ZoneInfo(a['exchangeTimezoneName'])).weekday() >= 5 and out['market_status'] == 'CLOSED':
        out['market_status'] = 'WEEKEND'
    def put(field, value, source='Google Finance', resolution=None):
        value = decimal(value)
        out[field] = value
        out['field_metadata'][field] = {'validation_status': 'VERIFIED', 'source': source,
            'source_timestamp': b['timestamp'] if source == 'Google Finance' else ta.isoformat(),
            'retrieved_at': b['retrieved_at'] if source == 'Google Finance' else a['_retrieved_at'],
            'decimal': format(value, 'f'), 'currency': a['currency'],
            'verification_sources': ['Google Finance', 'Yahoo Finance']}
        if resolution:
            out['field_metadata'][field]['verification_resolution'] = resolution
        if field == 'marketCap':
            out['field_metadata'][field]['timestamp_scope'] = 'quote snapshot; provider supplies no market-cap-specific timestamp'
    put('indexValue', b['price'])
    for field, key in [('previousClose', 'regularMarketPreviousClose'), ('dayHigh', 'regularMarketDayHigh'), ('dayLow', 'regularMarketDayLow')]:
        if b.get(field) is not None and a.get(key) is not None:
            v, w = decimal(b[field]), decimal(a[key])
            tolerance = Decimal('0.0001') if field == 'previousClose' else Decimal('0.005')
            if v > 0 and abs(v-w)/v <= tolerance:
                put(field, v)
            else:
                out.setdefault('field_conflicts', []).append(field)
    if out['dayLow'] and out['dayHigh'] and out['dayLow'] > out['dayHigh']:
        raise ValueError('INVALID_DAY_RANGE')
    # Provider changes must reconcile with its own regular-session previous close.
    if out['previousClose']:
        prev, price = decimal(a['regularMarketPreviousClose']), decimal(a['regularMarketPrice'])
        calculated = price-prev
        pct = calculated/prev*100
        for field, key, expected, tolerance in [('absoluteChange', 'regularMarketChange', calculated, Decimal('0.02')),
                                               ('changePercent', 'regularMarketChangePercent', pct, Decimal('0.02'))]:
            if a.get(key) is not None and abs(decimal(a[key])-expected) <= tolerance:
                put(field, a[key], 'Yahoo Finance')
    if a.get('marketCap') is not None and b.get('marketCap') is not None:
        cap = decimal(a['marketCap'])
        if cap > 0 and abs(cap-b['marketCap']) <= b['cap_resolution']/2:
            put('marketCap', cap, 'Yahoo Finance', b['cap_resolution'])
        else:
            out.setdefault('field_conflicts', []).append('marketCap')
    if symbol in PAIRS:
        out['base_currency'], out['quote_currency'] = PAIRS[symbol]
        out['quote_basis'] = a['quote_basis']
    out['sourceTimestamp'], out['marketStatus'], out['marketTimezone'] = out['source_timestamp'], out['market_status'], out['market_timezone']
    out['retrievedAt'] = out['retrieved_at']
    out['validation_evidence'] = {'google_id': b['id'], 'yahoo_symbol': symbol,
        'google_timestamp': tb.isoformat(), 'yahoo_timestamp': ta.isoformat(),
        'google_price': b['price'], 'yahoo_price': a['regularMarketPrice'],
        **out['quote_policy']}
    out['country'] = {'NMS': 'US', 'NGM': 'US', 'NCM': 'US', 'NYQ': 'US',
        'NSI': 'IN', 'NSE': 'IN', 'BSE': 'IN', 'HKG': 'HK', 'KSC': 'KR',
        'SHH': 'CN', 'SHZ': 'CN', 'NIM': 'US'}.get(a['exchange'])
    out['country_basis'] = 'listing exchange; not issuer domicile'
    if a['quoteType'] == 'INDEX':
        out['value_unit'] = 'index points'
        out['field_metadata']['indexValue']['currency'] = None
    if out['currency'] == 'USD' and out['marketCap'] is not None:
        out['marketCapUSD'] = out['marketCap']
        out['field_metadata']['marketCapUSD'] = deepcopy(out['field_metadata']['marketCap'])
    if row.get('verification_version') == 1 and row.get('indexValue'):
        if abs(decimal(out['indexValue']) / decimal(row['indexValue']) - 1) > Decimal('0.35'):
            out['outlier_validation'] = 'Two comparable independent quotes agree within 0.05%; corporate action not inferred'
    for field in FIELDS:
        if out.get(field) is not None:
            continue
        old_meta = row.get('field_metadata', {}).get(field, {})
        if (row.get('verification_version') == 1 and row.get('quote_currency') == out['quote_currency']
                and row.get('currency') == out['currency'] and row.get(field) is not None
                and old_meta.get('validation_status') in {'VERIFIED', 'STALE'}):
            out[field] = row[field]
            out['field_metadata'][field] = dict(old_meta, validation_status='STALE',
                reason='SOURCE_CONFLICT' if field in out.get('field_conflicts', []) else 'NEW_FIELD_UNCONFIRMED')
        else:
            out['field_metadata'][field] = {'validation_status': 'DATA_UNAVAILABLE',
                'reason': 'SOURCE_CONFLICT' if field in out.get('field_conflicts', []) else 'SOURCE_FIELD_UNCONFIRMED'}
    return out


def convert_usd(row, fx):
    if row.get('validation_status') != 'VERIFIED' or row.get('marketCap') is None:
        return row
    row['nativeMarketCap'] = row['marketCap']
    if row['quote_currency'] == 'USD':
        row['marketCapUSD'] = row['marketCap']
        row['field_metadata']['marketCapUSD'] = deepcopy(row['field_metadata']['marketCap'])
        return row
    if not fx or fx.get('validation_status') != 'VERIFIED':
        row['marketCap'] = None
        row['currency'] = 'USD'
        row['fxValidation'] = 'DATA_UNAVAILABLE'
        row['field_metadata'].pop('marketCap', None)
        return row
    if fx.get('base_currency') != 'USD' or fx.get('quote_currency') != row['quote_currency']:
        raise ValueError('FX_DIRECTION_MISMATCH')
    with localcontext() as context:
        context.prec = 34
        usd = decimal(row['nativeMarketCap']) / decimal(fx['indexValue'])
    row.update(marketCap=usd, marketCapUSD=usd, currency='USD', fxRate=fx['indexValue'],
               fxTimestamp=fx['source_timestamp'], fxValidation='VERIFIED')
    row['fx_metadata'] = {'base_currency': 'USD', 'quote_currency': row['quote_currency'],
        'source_timestamp': fx['source_timestamp'], 'source': fx['source'],
        'market_cap_source_timestamp': row['field_metadata']['marketCap']['source_timestamp'],
        'timestamp_skew_seconds': abs((timestamp(row['source_timestamp'])-timestamp(fx['source_timestamp'])).total_seconds()),
        'calculation': 'nativeMarketCap / units_of_native_currency_per_USD', 'decimal_precision': 34}
    row['field_metadata']['marketCap'].update(decimal=format(usd, 'f'), currency='USD', calculation='FX conversion')
    row['field_metadata']['marketCapUSD'] = deepcopy(row['field_metadata']['marketCap'])
    return row


def refresh_markets(payload):
    now = datetime.now(timezone.utc)
    symbols = [r.get('source_symbol') or ('BHARTIARTL.NS' if r['ticker'] == 'BHARTIARTL' else r['ticker'])
               for rows in payload['regions'].values() for r in rows]
    symbols = list(dict.fromkeys(symbols + ['HKD=X', 'KRW=X']))
    try:
        quotes = yahoo_quotes(symbols)
    except Exception as exc:
        quotes = {}
        print('[market] Yahoo batch unavailable: ' + type(exc).__name__)
    def get_secondary(symbol):
        try:
            return symbol, fetch_google(google_id(symbol, quotes.get(symbol, {})))
        except Exception as exc:
            return symbol, {'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    with ThreadPoolExecutor(max_workers=6) as pool:
        secondary = dict(pool.map(get_secondary, symbols))
    attempts = []
    def refresh(row):
        symbol = row.get('source_symbol') or ('BHARTIARTL.NS' if row['ticker'] == 'BHARTIARTL' else row['ticker'])
        reason = 'SOURCE_UNAVAILABLE'
        for attempt in range(2):
            try:
                a, b = quotes[symbol], secondary[symbol]
                if 'error' in b:
                    raise ValueError(b['error'])
                result = accepted(row, symbol, a, b, datetime.now(timezone.utc))
                if result.get('field_conflicts') and attempt == 0:
                    try:
                        quotes.update(yahoo_quotes([symbol]))
                        secondary[symbol] = fetch_google(google_id(symbol, quotes[symbol]))
                        continue
                    except Exception:
                        pass  # Keep accepted fields, quarantine conflicting fields.
                break
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else 'MISSING_SOURCE_FIELDS'
                if attempt == 0 and reason in {'SOURCE_CONFLICT', 'OUTLIER_REQUIRES_ADDITIONAL_VALIDATION'}:
                    try:
                        quotes.update(yahoo_quotes([symbol]))
                        secondary[symbol] = fetch_google(google_id(symbol, quotes[symbol]))
                        continue
                    except Exception:
                        pass
                result = unavailable(row, reason)
                break
        attempts.append({'ticker': row['ticker'], 'retrieved_at': now_iso(),
                         'validation_status': result['validation_status'], 'reason': result.get('error', {}).get('reason'),
                         'field_conflicts': result.get('field_conflicts', [])})
        return result
    fx = {ccy: refresh({'ticker': ccy + '=X', 'name': 'USD/' + ccy}) for ccy in ['HKD', 'KRW']}
    output = deepcopy(payload)
    for region, rows in payload['regions'].items():
        output['regions'][region] = [refresh(row) for row in rows]
        if region == 'asia':
            output['regions'][region] = [convert_usd(row, fx.get(row.get('quote_currency'))) for row in output['regions'][region]]
            for current, previous in zip(output['regions'][region], rows):
                old = previous.get('field_metadata', {}).get('marketCap', {})
                if (current.get('marketCap') is None and previous.get('verification_version') == 1
                        and previous.get('currency') == 'USD' and previous.get('marketCap') is not None
                        and old.get('validation_status') in {'VERIFIED', 'STALE'}):
                    current['marketCap'] = previous['marketCap']
                    current['marketCapUSD'] = previous.get('marketCapUSD')
                    current['currency'] = 'USD'
                    current['field_metadata']['marketCap'] = dict(old, validation_status='STALE', reason='NEW_FX_OR_CAP_UNCONFIRMED')
                    current['last_verified_fx_metadata'] = previous.get('fx_metadata')
    # Retrieval times are execution evidence, not a reason for a Git commit.
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k,v in value.items() if k not in {'retrieved_at', 'retrievedAt', 'updated'}}
        return [stable(v) for v in value] if isinstance(value, list) else value
    if stable(output) == stable(payload):
        output = payload
    else:
        output['updated'] = now_iso()
    return output, attempts
