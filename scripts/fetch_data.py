"""Daily fetcher: stocks (US / Asia / India) + 3 news categories."""
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# ────────────────────────────────────────────────────────────────────
# STOCK UNIVERSE
# ────────────────────────────────────────────────────────────────────

US_STOCKS = [
    ("AMD",     "AMD (Advanced Micro Devices)", "Semiconductors / AI Chips", None, "Advanced Micro Devices"),
    ("GOOGL",   "Alphabet Inc.",       "Earnings / AI growth"),
    ("MSFT",    "Microsoft",           "Cloud / AI"),
    ("TSLA",    "Tesla",               "EV demand"),
    ("AMZN",    "Amazon",              "AWS / Retail"),
    ("META",    "Meta Platforms",      "Ads / AI"),
    ("INTC",    "Intel",               "Chips"),
    ("ORCL",    "Oracle",              "Cloud"),
    ("SAP",     "SAP",                 "Enterprise AI"),
    ("CRM",     "Salesforce",          "AI CRM"),
    ("ACN",     "Accenture",           "IT Services / Consulting"),
    ("AMAT",    "Applied Materials",   "Semiconductors"),
    ("GE",      "GE Aerospace",        "Aerospace / Industrial"),
    ("GM",      "General Motors",      "Automotive"),
    ("NVDA",    "NVIDIA",              "AI Chips"),
    ("SNOW",    "Snowflake",           "Cloud Data"),
    ("TEAM",    "Atlassian",           "Software"),
    ("SHOP",    "Shopify",             "E-commerce"),
]

ASIA_STOCKS = [
    ("BABA",      "Alibaba Group",       "E-commerce"),
    ("0700.HK",   "Tencent",             "Gaming / AI"),
    ("TSM",       "TSMC",                "Chips demand"),
    ("005930.KS", "Samsung Electronics", "Memory chips"),
]

INDIA_STOCKS = [
    ("RELIANCE.NS",   "Reliance Industries", "Energy / Telecom"),
    ("BHARTIARTL.NS", "Bharti Airtel",       "Telecom / Digital Infrastructure", "BHARTIARTL"),
    ("TCS.NS",        "TCS",                 "IT demand"),
    ("INFY.NS",       "Infosys",             "Growth outlook"),
    ("WIPRO.NS",      "Wipro",               "IT"),
    ("TECHM.NS",      "Tech Mahindra",       "Telecom IT"),
    ("SBIN.NS",       "State Bank of India", "Banking"),
    ("HDFCBANK.NS",   "HDFC Bank",           "Lending"),
    ("HEROMOTOCO.NS", "Hero MotoCorp",       "Auto"),
    ("MARUTI.NS",     "Maruti Suzuki",       "Auto"),
    ("DRREDDY.NS",    "Dr. Reddy's",         "Pharma"),
    ("DIVISLAB.NS",   "Divi's Labs",         "API"),
    ("AUROPHARMA.NS", "Aurobindo Pharma",    "Pharma Exports"),
    ("APOLLOHOSP.NS", "Apollo Hospitals",    "Healthcare"),
    ("GLENMARK.NS",   "Glenmark Pharmaceuticals", "Pharma"),
    ("SWIGGY.NS",     "Swiggy",                  "Food Delivery / Quick Commerce"),
    ("ETERNAL.NS",    "Eternal",                 "Food Delivery / Quick Commerce"),
    ("ASTERDM.NS",    "Aster DM Quality Care",   "Healthcare"),
    ("SIGMAADV.NS",   "Sigma Advanced Systems",  "Technology"),
    ("NCC.NS",        "NCC Ltd",                 "Construction / Infrastructure"),
    ("KIMS.NS",       "Krishna Institute of Medical Sciences", "Healthcare / Hospitals"),
    ("GLAND.NS",      "Gland Pharma",            "Pharma"),
    ("INDIGO.NS",     "InterGlobe Aviation (IndiGo)", "Aviation"),
    ("ADANIENT.NS",   "Adani Enterprises",       "Conglomerate"),
    ("SAILIFE.NS",    "Sai Life Sciences",       "Pharma CRDMO"),
]

# ────────────────────────────────────────────────────────────────────
# NEWS SOURCES
# ────────────────────────────────────────────────────────────────────

TECH_AI_FEEDS = [
    # AI-native publishers (all items definitionally AI)
    ("Anthropic",         "https://www.anthropic.com/news/rss.xml"),
    ("OpenAI",            "https://openai.com/blog/rss.xml"),
    ("Hugging Face",      "https://huggingface.co/blog/feed.xml"),
    ("Google AI",         "https://blog.google/technology/ai/rss/"),
    ("Google DeepMind",   "https://deepmind.google/blog/rss.xml"),
    # Category-specific feeds (AI section only)
    ("TechCrunch AI",     "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI",      "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("VentureBeat AI",    "https://venturebeat.com/category/ai/feed/"),
    ("Ars Technica AI",   "https://arstechnica.com/ai/feed/"),
    ("MIT Tech Review",   "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
]

# General tech feeds — used to surface the 5 non-AI tech items per window
TECH_GENERAL_FEEDS = [
    ("TechCrunch",   "https://techcrunch.com/feed/"),
    ("The Verge",    "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("Hacker News",  "https://hnrss.org/frontpage?points=150"),
    ("Wired",        "https://www.wired.com/feed/rss"),
]

INDIA_POLITICAL_FEEDS = [
    # Politics-specific feeds (not general "national news")
    ("Indian Express - Political Pulse",
        "https://indianexpress.com/section/political-pulse/feed/"),
    ("The Print - Politics",
        "https://theprint.in/category/politics/feed/"),
    ("Mint - Politics",
        "https://www.livemint.com/rss/politics"),
    ("Economic Times - Politics",
        "https://economictimes.indiatimes.com/news/politics-and-nation/rssfeeds/1052734.cms"),
    ("The Wire - Politics",
        "https://thewire.in/politics/feed"),
    ("Scroll.in",
        "https://feeds.feedburner.com/ScrollinArticles.rss"),
]

GEOPOLITICAL_FEEDS = [
    ("BBC World",       "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera",      "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Foreign Policy",  "https://foreignpolicy.com/feed/"),
    ("The Diplomat",    "https://thediplomat.com/feed/"),
    ("AP World",        "https://feeds.apnews.com/rss/world"),
    ("DW",              "https://rss.dw.com/rdf/rss-en-world"),
    ("Reuters World",   "https://www.reutersagency.com/feed/?best-topics=world&post_type=best"),
    ("War on the Rocks","https://warontherocks.com/feed/"),
]

# X signals are optional. Add X_BEARER_TOKEN as a GitHub secret to enable them.
X_API_URL = "https://api.twitter.com/2/tweets/search/recent"
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "").strip()

X_TECH_QUERIES = [
    '(OpenAI OR "Google AI" OR "Microsoft AI" OR "Meta AI" OR Anthropic OR NVIDIA) '
    '(AI OR LLM OR agents OR model OR regulation OR startup OR breakthrough)',
    '("AI regulation" OR "AI startup" OR "LLM agents" OR "AI breakthrough" OR "technology trends")',
]

X_GEO_QUERIES = [
    '(US OR China OR India OR Europe OR "Russia Ukraine" OR "Middle East") '
    '(defense OR policy OR strategic OR economy OR summit OR sanctions OR conflict)',
    '("global economy" OR "international development" OR "defense policy" OR "strategic development")',
]

TRUSTED_X_HANDLES = {
    "tech": {
        "openai", "anthropicai", "googledeepmind", "googleai", "microsoftai",
        "nvidia", "ylecun", "sama", "karpathy", "demishassabis",
        "techcrunch", "verge", "wired", "mittr", "venturebeat",
    },
    "global": {
        "ap", "reuters", "bbcworld", "bbcbreaking", "aljazeera", "dwnews",
        "foreignpolicy", "thediplomat", "csis", "iiss_org", "ianbremmer",
        "euronews", "ft", "economist",
    },
}

LOW_QUALITY_X_RE = re.compile(
    r"\b(giveaway|airdrop|promo|discount|subscribe|follow me|dm me|whatsapp|telegram|"
    r"crypto pump|100x|betting|casino|onlyfans|thread below|like and retweet)\b",
    re.I,
)

# ── Category filters (drop off-topic items even if they slip in via broad feeds) ──
SPORTS_ENTERTAINMENT_RE = re.compile(
    r"\b(cricket|football|soccer|tennis|kabaddi|hockey|olympic|world cup|la liga|el clasico|"
    r"epl|premier league|ipl|test match|odi|t20|wicket|striker|midfielder|hamstring|"
    r"movie|film|actor|actress|album|trailer|box office|netflix|web series|concert|"
    r"song release|EP release|kalimba|synth|recipe|fashion|celebrity|wedding|honeymoon|"
    r"mother's day gift|gift ideas|horoscope|zodiac|"
    r"promo code|coupon|discount|% off|limited time|deal of the|best deals|"
    r"on sale|holiday sale|black friday|cyber monday)\b",
    re.I,
)

TECH_AI_RE = re.compile(
    r"\b(AI|A\.I\.|artificial intelligence|machine learning|deep learning|neural|"
    r"LLM|GPT|Claude|Gemini|ChatGPT|Anthropic|OpenAI|Mistral|Llama|HuggingFace|"
    r"DeepMind|Nvidia|GPU|TPU|inference|training|fine.?tun|transformer|diffusion|"
    r"agent(?:ic)?|RAG|embedding|prompt|chatbot|copilot|data ?center|hyperscaler|"
    r"semiconductor|chip|silicon|wafer|foundry|TSMC|robotic|automation|"
    r"startup|cloud|SaaS|software|cybersecurity|tech compan)\b",
    re.I,
)

INDIA_POLITICS_RE = re.compile(
    r"\b(politic|elect|BJP|Congress(?!ional)|Modi|Rahul Gandhi|Sonia Gandhi|"
    r"parliament|Lok Sabha|Rajya Sabha|minister|cabinet|policy|opposition|MLA|"
    r"AAP|DMK|AIADMK|TMC|Trinamool|Shiv Sena|NCP|CPI|CPM|Samajwadi|"
    r"party|vote|coalition|alliance|assembly|legislative|legislator|"
    r"chief minister|prime minister|governor|president(?:ial)?|"
    r"supreme court|high court|constitution|amendment|bill |ordinance|"
    r"CBI|ED|enforcement directorate|election commission|EC )\b",
    re.I,
)

GEOPOLITICS_RE = re.compile(
    r"\b(war|conflict|sanctions|treaty|diplomat|NATO|UN |U\.N\.|Putin|Xi |Trump|"
    r"Biden|Zelensk|election|foreign|embassy|geopolitic|invasion|missile|nuclear|"
    r"Iran|Russia|China|Ukraine|Israel|Hamas|Gaza|Hezbollah|Lebanon|Syria|"
    r"North Korea|Pyongyang|Taiwan|South China|Middle East|trade war|tariff|"
    r"alliance|coup|protest|uprising|summit|peace talks|cease.?fire|airstrike|"
    r"drone strike|refugee|asylum)\b",
    re.I,
)


def load_existing_items(path: Path) -> list[dict]:
    """Read existing items from a data file so we can accumulate history."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("items", []) or []
    except Exception as e:
        print(f"[merge] could not load {path}: {e}")
        return []


def merge_with_history(new_items: list[dict], existing: list[dict]) -> list[dict]:
    """Merge new RSS items with what's already on disk. Dedupe by URL, drop old."""
    by_key: dict[str, dict] = {}
    for it in existing:
        key = (it.get("url") or it.get("title") or "").strip()
        if key:
            by_key[key] = it
    for it in new_items:                              # new items take priority for any conflict
        key = (it.get("url") or it.get("title") or "").strip()
        if not key:
            continue
        prev = by_key.get(key)
        if prev and len(prev.get("summary") or "") > len(it.get("summary") or ""):
            # keep the older record only if it has a longer / better summary
            for k, v in it.items():
                prev.setdefault(k, v)                 # but still pick up any new fields (e.g. isAI)
        else:
            by_key[key] = it

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    keep = [v for v in by_key.values() if parse_date(v.get("published", "")) >= cutoff]
    keep.sort(key=lambda x: (news_quality_score(x), parse_date(x["published"])), reverse=True)
    return keep[:MAX_STORED]


def keep_item(item: dict, must_match: re.Pattern | None,
              must_not_match: re.Pattern | None = SPORTS_ENTERTAINMENT_RE) -> bool:
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    if must_not_match and must_not_match.search(text):
        return False
    if must_match and not must_match.search(text):
        return False
    return True


def news_quality_score(item: dict) -> float:
    """Boost items supported by X engagement and trusted/verified sources."""
    score = float(item.get("xScore") or 0)
    if item.get("xSignal"):
        score += 2
    if item.get("verifiedSource"):
        score += 2
    if item.get("source", "").lower() in {"reuters world", "ap world", "bbc world"}:
        score += 2
    return score


TOP_N = 100           # fetch up to this many per run; merged with existing on disk
MAX_STORED = 250      # cap on total items kept per category after merge
LOOKBACK_DAYS = 35    # items older than this get dropped when merging

TECH_BROAD_RE = re.compile(
    r"\b(AI|tech|software|hardware|app|platform|cloud|startup|chip|silicon|"
    r"semiconductor|robot|cyber|API|developer|coding|programming|encrypt|"
    r"database|browser|mobile|laptop|smartphone|GPU|server|network|"
    r"cryptocurrency|blockchain|quantum|battery|EV|autonomous)\b",
    re.I,
)

# ────────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────────

def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def truncate(s: str, n: int = 400) -> str:
    if not s or len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + "…"


def parse_date(s: str) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    formats = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            d = datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def x_engagement_score(metrics: dict, verified: bool, trusted: bool) -> float:
    likes = metrics.get("like_count") or 0
    reposts = metrics.get("retweet_count") or 0
    replies = metrics.get("reply_count") or 0
    quotes = metrics.get("quote_count") or 0
    raw = likes + (2 * reposts) + replies + (2 * quotes)
    score = min(8, raw / 150)
    if verified:
        score += 2
    if trusted:
        score += 3
    return round(score, 2)


def credible_x_post(text: str, metrics: dict, verified: bool, trusted: bool) -> bool:
    if LOW_QUALITY_X_RE.search(text):
        return False
    engagement = (
        (metrics.get("like_count") or 0)
        + (2 * (metrics.get("retweet_count") or 0))
        + (2 * (metrics.get("quote_count") or 0))
        + (metrics.get("reply_count") or 0)
    )
    return trusted or verified or engagement >= 75


def fetch_x_posts(queries: list[str], section: str, topic_re: re.Pattern,
                  limit_per_query: int = 20) -> list[dict]:
    """Use X recent search as a primary signal when X_BEARER_TOKEN is configured."""
    if not X_BEARER_TOKEN:
        print(f"[x] no X_BEARER_TOKEN configured; skipping {section} X signals")
        return []

    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    items: list[dict] = []
    trusted_handles = TRUSTED_X_HANDLES.get(section, set())

    for query in queries:
        params = {
            "query": f"({query}) lang:en -is:retweet -is:reply",
            "max_results": max(10, min(100, limit_per_query)),
            "tweet.fields": "created_at,public_metrics,author_id,possibly_sensitive,lang",
            "expansions": "author_id",
            "user.fields": "username,name,verified,public_metrics",
        }
        try:
            res = requests.get(X_API_URL, headers=headers, params=params, timeout=20)
            if res.status_code == 429:
                print(f"[x] rate limited while fetching {section}")
                break
            res.raise_for_status()
            payload = res.json()
        except Exception as e:
            print(f"[x] {section} query failed: {e}")
            continue

        users = {
            u["id"]: u for u in payload.get("includes", {}).get("users", [])
            if u.get("id")
        }
        for tweet in payload.get("data", []):
            text = strip_html(tweet.get("text", ""))
            if tweet.get("possibly_sensitive") or not topic_re.search(text):
                continue

            user = users.get(tweet.get("author_id"), {})
            username = (user.get("username") or "x").lower()
            verified = bool(user.get("verified"))
            trusted = username in trusted_handles
            metrics = tweet.get("public_metrics") or {}
            if not credible_x_post(text, metrics, verified, trusted):
                continue

            display_name = user.get("name") or username
            items.append({
                "title": truncate(text, 140),
                "url": f"https://x.com/{username}/status/{tweet['id']}",
                "source": f"X · @{username}",
                "published": tweet.get("created_at", ""),
                "summary": truncate(f"{display_name}: {text}", 400),
                "xSignal": True,
                "verifiedSource": verified or trusted,
                "xScore": x_engagement_score(metrics, verified, trusted),
            })

    seen, deduped = set(), []
    for item in items:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda x: (news_quality_score(x), parse_date(x["published"])), reverse=True)
    return deduped[:TOP_N]


# ────────────────────────────────────────────────────────────────────
# STOCKS
# ────────────────────────────────────────────────────────────────────

def fetch_stock(ticker: str, name: str, sector: str,
                display_ticker: str | None = None,
                sort_name: str | None = None) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        change_percent = info.get("regularMarketChangePercent")
        if change_percent is None:
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            previous_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            if price and previous_close:
                change_percent = ((price - previous_close) / previous_close) * 100

        stock = {
            "ticker": display_ticker or ticker,
            "name": name,
            "sector": sector,
            "currency": info.get("currency") or info.get("financialCurrency") or "",
            "marketCap": info.get("marketCap"),
            "changePercent": change_percent,
        }
        if sort_name:
            stock["sortName"] = sort_name
        return stock
    except Exception as e:
        print(f"[stocks] {ticker} failed: {e}")
        return None


def convert_market_cap_to_usd(stock: dict) -> dict:
    currency = stock.get("currency")
    market_cap = stock.get("marketCap")
    if not market_cap or currency in ("", "USD"):
        stock["currency"] = "USD"
        return stock

    try:
        fx = yf.Ticker(f"{currency}=X")
        rate = None
        try:
            rate = (fx.fast_info or {}).get("last_price")
        except Exception:
            pass
        if not rate:
            info = fx.info or {}
            rate = info.get("regularMarketPrice") or info.get("currentPrice")
        if rate:
            stock["marketCap"] = market_cap / rate
            stock["currency"] = "USD"
    except Exception as e:
        print(f"[stocks] {stock.get('ticker')} USD conversion failed: {e}")
    return stock


def fetch_all_stocks() -> dict:
    def sorted_region(stocks: list[dict]) -> list[dict]:
        return sorted(stocks, key=lambda s: (s.get("sortName") or s.get("name") or "").casefold())

    asia = [convert_market_cap_to_usd(s) for s in (fetch_stock(*x) for x in ASIA_STOCKS) if s]

    return {
        "us":    sorted_region([s for s in (fetch_stock(*x) for x in US_STOCKS)    if s]),
        "asia":  sorted_region(asia),
        "india": sorted_region([s for s in (fetch_stock(*x) for x in INDIA_STOCKS) if s]),
    }


# ────────────────────────────────────────────────────────────────────
# NEWS
# ────────────────────────────────────────────────────────────────────

def fetch_feed(source: str, url: str, limit: int = 10) -> list[dict]:
    items = []
    try:
        parsed = feedparser.parse(url)
        for entry in parsed.entries[:limit]:
            published = entry.get("published") or entry.get("updated") or ""
            summary = entry.get("summary") or entry.get("description") or ""
            items.append({
                "title":     strip_html(entry.get("title", "(untitled)")).strip(),
                "url":       entry.get("link", ""),
                "source":    source,
                "published": published,
                "summary":   truncate(strip_html(summary), 400),
            })
    except Exception as e:
        print(f"[rss] {source} failed: {e}")
    return items


def fetch_category(feeds: list[tuple[str, str]],
                   topic_re: re.Pattern | None = None,
                   top_n: int = TOP_N,
                   x_items: list[dict] | None = None) -> list[dict]:
    all_items = list(x_items or [])
    for src, url in feeds:
        all_items.extend(fetch_feed(src, url, limit=20))

    relevant = [i for i in all_items if keep_item(i, topic_re)]
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    fresh = [i for i in relevant if parse_date(i["published"]) >= cutoff]
    pool = fresh if len(fresh) >= top_n else (relevant if relevant else all_items)

    pool.sort(key=lambda x: (news_quality_score(x), parse_date(x["published"])), reverse=True)

    seen, deduped = set(), []
    for it in pool:
        key = it["url"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped[:top_n]


def fetch_tech_news() -> list[dict]:
    """Combined tech feed. Each item tagged with isAI=True/False so the frontend
    can present 15 AI + 5 other-tech per time window."""
    items = fetch_x_posts(X_TECH_QUERIES, "tech", TECH_AI_RE)
    for it in items:
        it["isAI"] = True

    # 1. AI-native publishers — always isAI=True
    for src, url in TECH_AI_FEEDS:
        for it in fetch_feed(src, url, limit=20):
            if not keep_item(it, None):                  # only block sports/entertainment
                continue
            it["isAI"] = True
            items.append(it)

    # 2. General tech feeds — tag isAI based on whether the title/summary mentions AI
    for src, url in TECH_GENERAL_FEEDS:
        for it in fetch_feed(src, url, limit=15):
            if not keep_item(it, TECH_BROAD_RE):         # must be tech-ish, not sports
                continue
            text = (it["title"] + " " + it.get("summary", "")).lower()
            it["isAI"] = bool(TECH_AI_RE.search(text))
            items.append(it)

    # 3. dedupe by URL/title, drop very old, sort by date
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    items = [i for i in items if parse_date(i["published"]) >= cutoff]
    seen, deduped = set(), []
    for it in items:
        key = it["url"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    deduped.sort(key=lambda x: (news_quality_score(x), parse_date(x["published"])), reverse=True)
    return deduped[:TOP_N]


# ────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc).isoformat()

    print("Fetching stocks…")
    regions = fetch_all_stocks()
    (DATA / "stocks.json").write_text(json.dumps(
        {"updated": now, "regions": regions}, indent=2
    ))
    counts = {k: len(v) for k, v in regions.items()}
    print(f"  stocks per region: {counts}")

    print("Fetching tech / AI news…")
    new_tech = fetch_tech_news()
    existing_tech = load_existing_items(DATA / "news_tech.json")
    # Retro-tag old items that pre-date the isAI field
    for it in existing_tech:
        if "isAI" not in it:
            t = (it.get("title", "") + " " + it.get("summary", "")).lower()
            it["isAI"] = bool(TECH_AI_RE.search(t))
    tech_items = merge_with_history(new_tech, existing_tech)
    (DATA / "news_tech.json").write_text(json.dumps(
        {"updated": now, "items": tech_items}, indent=2
    ))
    ai_count = sum(1 for i in tech_items if i.get("isAI"))
    print(f"  stored {len(tech_items)} tech items ({ai_count} AI, {len(tech_items)-ai_count} other) — was {len(existing_tech)} before merge")

    global_x_items = fetch_x_posts(X_GEO_QUERIES, "global", GEOPOLITICS_RE)
    for label, feeds, filter_re, filename, x_items in [
        ("india political", INDIA_POLITICAL_FEEDS, INDIA_POLITICS_RE, "news_india.json", []),
        ("geopolitical",    GEOPOLITICAL_FEEDS,    GEOPOLITICS_RE,    "news_global.json", global_x_items),
    ]:
        print(f"Fetching {label} news…")
        new_items = fetch_category(feeds, filter_re, x_items=x_items)
        existing  = load_existing_items(DATA / filename)
        merged    = merge_with_history(new_items, existing)
        (DATA / filename).write_text(json.dumps(
            {"updated": now, "items": merged}, indent=2
        ))
        print(f"  stored {len(merged)} items in {filename} — was {len(existing)} before merge")


if __name__ == "__main__":
    main()
