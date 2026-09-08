"""Publisher evidence, safe URLs, real publication dates and stable story history."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import re
import requests
from bs4 import BeautifulSoup

PRIMARY = {'openai.com', 'anthropic.com', 'blog.google', 'deepmind.google', 'huggingface.co'}
PUBLISHERS = PRIMARY | {'techcrunch.com', 'theverge.com', 'venturebeat.com', 'arstechnica.com',
    'technologyreview.com', 'wired.com', 'indianexpress.com', 'theprint.in', 'livemint.com',
    'economictimes.indiatimes.com', 'thewire.in', 'scroll.in', 'bbc.com', 'bbc.co.uk',
    'aljazeera.com', 'foreignpolicy.com', 'thediplomat.com', 'apnews.com', 'dw.com',
    'reuters.com', 'reutersagency.com', 'warontherocks.com'}
FEED_HOSTS = {'feeds.bbci.co.uk': {'bbc.com', 'bbc.co.uk'},
              'rss.dw.com': {'dw.com'}, 'feeds.arstechnica.com': {'arstechnica.com'},
              'feeds.apnews.com': {'apnews.com'}, 'reutersagency.com': {'reuters.com', 'reutersagency.com'}}


def canonical_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().removeprefix('www.')
    if parts.scheme not in {'http', 'https'} or parts.username or parts.password or host not in PUBLISHERS:
        raise ValueError('UNTRUSTED_NEWS_URL')
    query = [(k,v) for k,v in parse_qsl(parts.query) if not k.startswith(('utm_', 'at_')) and k not in {'ref', 'traffic_source', 'maca'}]
    return urlunsplit(('https', host, parts.path.rstrip('/'), urlencode(sorted(query)), ''))


def tokens(title):
    return re.sub(r'[^\w]+', ' ', title.lower()).strip()


def verify_article(item):
    """Confirm a publisher actually published the headline; no AI-generated claims."""
    try:
        url = canonical_url(item['url'])
        feed_host = (urlsplit(item.get('feed_url', '')).hostname or '').removeprefix('www.')
        article_host = (urlsplit(url).hostname or '').removeprefix('www.')
        if (feed_host in PUBLISHERS and article_host == feed_host) or article_host in FEED_HOSTS.get(feed_host, set()):
            return dict(item, url=url, verification_status='SOURCE_CONFIRMED',
                        verification_method='Publisher feed headline and attributed summary',
                        evidence_url=item['feed_url'],
                        source_type='PRIMARY' if feed_host in PRIMARY else 'PUBLISHER')
        # Check every redirect before requesting; never follow a feed URL to local/private hosts.
        for _ in range(4):
            response = requests.get(url, timeout=(4, 8), allow_redirects=False, stream=True)
            if response.is_redirect:
                from urllib.parse import urljoin
                target = urljoin(url, response.headers['Location'])
                response.close()
                url = canonical_url(target)
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    break
                chunks.append(chunk)
            response.close()
            soup = BeautifulSoup(b''.join(chunks), 'html.parser')
            title = soup.select_one('meta[property="og:title"]')
            headline = title.get('content', '') if title else soup.title.get_text() if soup.title else ''
            if SequenceMatcher(None, tokens(item['title']), tokens(headline)).ratio() < .72:
                raise ValueError('ARTICLE_HEADLINE_MISMATCH')
            item = dict(item, url=url, verification_status='SOURCE_CONFIRMED',
                        verification_method='Publisher article headline matched to publisher feed',
                        evidence_url=url, retrieved_at=datetime.now(timezone.utc).isoformat(),
                        source_type='PRIMARY' if urlsplit(url).hostname in PRIMARY else 'PUBLISHER')
            return item
        raise ValueError('TOO_MANY_REDIRECTS')
    except Exception:
        return None


def merge_news(new_items, existing, parse_date, category):
    now = datetime.now(timezone.utc)
    valid_existing, pending = [], []
    known = {}
    for item in existing:
        if item.get('verification_status') == 'SOURCE_CONFIRMED':
            known[(item.get('url'), item.get('title'), item.get('summary'))] = item
    for item in new_items + existing:
        try:
            url = canonical_url(item['url'])
            published = parse_date(item['published']).astimezone(timezone.utc)
            if not item.get('title', '').strip() or not item.get('source') or not now-timedelta(days=35) <= published <= now+timedelta(minutes=2):
                continue
            item = dict(item, url=url, published=published.isoformat(), category=category,
                        relevance='AI' if item.get('isAI') else category)
            prior = known.get((url, item['title'], item.get('summary')))
            if prior:
                valid_existing.append(prior)
            else:
                pending.append(item)
        except (ValueError, KeyError, TypeError):
            continue
    unique = {}
    for item in pending:
        unique.setdefault(item['url'], item)
    # Bound cold-start work; subsequent cycles verify the newest candidates first.
    pending = sorted(unique.values(), key=lambda i: i['published'], reverse=True)[:60]
    with ThreadPoolExecutor(max_workers=6) as pool:
        confirmed = [item for item in pool.map(verify_article, pending) if item]
    results = []
    for item in sorted(confirmed + valid_existing, key=lambda i: i['published'], reverse=True):
        duplicate = next((old for old in results if old['url'] == item['url'] or
            (abs((parse_date(old['published'])-parse_date(item['published'])).total_seconds()) < 172800 and
             SequenceMatcher(None, tokens(old['title']), tokens(item['title'])).ratio() >= .9)), None)
        if duplicate:
            continue
        item = dict(item)
        item['story_fingerprint'] = sha256(tokens(item['title']).encode()).hexdigest()[:24]
        for signal in new_items:
            if signal.get('xSignal') and SequenceMatcher(None, tokens(signal.get('title', '')), tokens(item['title'])).ratio() >= .8:
                item.update(xSignal=True, xScore=signal.get('xScore', 0), xEvidence=signal.get('url'))
        results.append(item)
    return results[:250]
