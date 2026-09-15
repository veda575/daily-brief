"""Groww's dated Hyderabad retail benchmark (INR per gram)."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import re
import json

import requests
from bs4 import BeautifulSoup

GOLD_ID = 'GOLD_24K_HYDERABAD'
GOLD_URL = 'https://groww.in/gold-rates/gold-rate-today-in-hyderabad'
MAX_AGE = 2 * 86400


def base_row():
    return dict(ticker=GOLD_ID, name='Gold (24 Carat, Hyderabad)', sector='Metals',
                unit='INR/gram', currency='INR', quote_currency='INR', city='Hyderabad',
                purity='24 Carat', source='Groww', source_url=GOLD_URL,
                quote_basis='Indicative retail rate; excludes GST and making charges',
                quote_quality='INDICATIVE', verification_version=1,
                quote_policy={'max_quote_age_seconds': MAX_AGE}, field_metadata={})


def parse_gold(page, now):
    soup = BeautifulSoup(page, 'html.parser')
    heading = soup.find('h1')
    if not heading or not re.fullmatch(r'Gold Rate Today in Hyderabad \(\d{2} [A-Za-z]{3} \d{4}\)', heading.get_text(' ', strip=True)):
        raise ValueError('HYDERABAD_PAGE_MISSING')
    embedded = soup.find('script', id='__NEXT_DATA__')
    if not embedded:
        raise ValueError('GOLD_DATA_MISSING')
    try:
        data = json.loads(embedded.get_text(), parse_float=Decimal)
        quote = data['props']['pageProps']['goldRateData']['physicalGoldRate']['hyderabad']
        if quote['priceLocation'] != 'Hyderabad' or quote['searchId'] != 'gold-rate-today-in-hyderabad':
            raise ValueError('GOLD_CITY_MISMATCH')
        day = datetime.strptime(quote['date'], '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Kolkata'))
        price = Decimal(str(quote['price']['TWENTY_FOUR']))
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError('INVALID_GOLD_DATA') from exc
    if not price.is_finite() or price <= 0:
        raise ValueError('INVALID_GOLD_PRICE')
    if day.date() > now.astimezone(ZoneInfo('Asia/Kolkata')).date():
        raise ValueError('FUTURE_GOLD_DATE')
    if day.strftime('%d %b %Y') not in heading.get_text():
        raise ValueError('GOLD_DATE_MISMATCH')
    # Confirm the embedded value is per gram against the visible 24K table.
    table = next((t for t in soup.find_all('table') if
                  [h.get_text(strip=True).lower() for h in t.select('thead th')] == ['gram', '24k', '22k', '18k']), None)
    if table is None:
        raise ValueError('GOLD_UNITS_CHANGED')
    checked = set()
    for tr in table.select('tbody tr'):
        cells = tr.find_all('td')
        if len(cells) != 4:
            continue
        weight = {'1 Gram': 1, '8 Gram': 8, '10 Gram': 10, '100 Gram': 100}.get(cells[0].get_text(strip=True))
        if weight is None:
            continue
        match = re.match(r'₹([\d,]+(?:\.\d+)?)', cells[1].get_text(strip=True))
        if not match or Decimal(match[1].replace(',', '')) != price * weight:
            raise ValueError('GOLD_UNIT_MISMATCH')
        checked.add(weight)
    if checked != {1, 8, 10, 100}:
        raise ValueError('GOLD_UNITS_MISSING')
    status = 'STALE' if (now - day).total_seconds() > MAX_AGE else 'INDICATIVE'
    row = base_row()
    row.update(indexValue=price, changePercent=None, validation_status=status,
               source_date=day.date().isoformat(), source_timestamp=day.isoformat(),
               timestamp_scope='Source publishes date only', retrieved_at=now.isoformat())
    row['field_metadata']['indexValue'] = dict(validation_status=status, quality='INDICATIVE',
        decimal=str(price), source=row['source'], source_timestamp=day.isoformat(),
        timestamp_scope=row['timestamp_scope'], currency='INR')
    change = quote.get('percentageChange', {}).get('TWENTY_FOUR')
    if change is not None:
        try:
            change = Decimal(str(change))
            if change.is_finite():
                change = change.quantize(Decimal('0.01'))
                row['changePercent'] = change
                row['field_metadata']['changePercent'] = dict(row['field_metadata']['indexValue'], decimal=str(change), currency=None)
        except ArithmeticError:
            pass
    return row


def refresh_gold(previous, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        response = requests.get(GOLD_URL, timeout=25, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        return parse_gold(response.text, now)
    except (requests.RequestException, ValueError, IndexError, TypeError) as exc:
        # A futures quote must never become the fallback for a local retail rate.
        row = base_row()
        if (previous.get('ticker') == GOLD_ID and previous.get('unit') == 'INR/gram'
                and previous.get('source_timestamp') and previous.get('indexValue') is not None
                and previous.get('verification_version') == 1):
            row = deepcopy(previous)
            row['validation_status'] = 'STALE'
            for meta in row['field_metadata'].values():
                meta['validation_status'] = 'STALE'
        else:
            row.update(indexValue=None, changePercent=None, validation_status='DATA_UNAVAILABLE')
        row['error'] = {'reason': type(exc).__name__ + ': ' + str(exc)}
        return row
