"""Daily fetcher: stocks (US / Asia / India) + private-company news + 3 news categories."""
import html
import json
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
    ("GOOGL",   "Alphabet Inc.",       "Earnings / AI growth"),
    ("MSFT",    "Microsoft",           "Cloud / AI"),
    ("TSLA",    "Tesla",               "EV demand"),
    ("AMZN",    "Amazon",              "AWS / Retail"),
    ("META",    "Meta Platforms",      "Ads / AI"),
    ("INTC",    "Intel",               "Chips"),
    ("ORCL",    "Oracle",              "Cloud"),
    ("SAP",     "SAP",                 "Enterprise AI"),
    ("CRM",     "Salesforce",          "AI CRM"),
]

ASIA_STOCKS = [
    ("BABA",      "Alibaba Group",       "E-commerce"),
    ("0700.HK",   "Tencent",             "Gaming / AI"),
    ("TSM",       "TSMC",                "Chips demand"),
    ("005930.KS", "Samsung Electronics", "Memory chips"),
    ("AMD",       "AMD",                 "AI chips"),
]

INDIA_STOCKS = [
    ("RELIANCE.NS",   "Reliance Industries", "Energy / Telecom"),
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
]

PRIVATE_COMPANIES = [
    ("SpaceX",    "Aerospace / Satellites"),
    ("OpenAI",    "AI / Foundation Models"),
    ("Anthropic", "AI / Foundation Models"),
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
    keep.sort(key=lambda x: parse_date(x["published"]), reverse=True)
    return keep[:MAX_STORED]


def keep_item(item: dict, must_match: re.Pattern | None,
              must_not_match: re.Pattern | None = SPORTS_ENTERTAINMENT_RE) -> bool:
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    if must_not_match and must_not_match.search(text):
        return False
    if must_match and not must_match.search(text):
        return False
    return True


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


# ────────────────────────────────────────────────────────────────────
# STOCKS
# ────────────────────────────────────────────────────────────────────

def fetch_stock(ticker: str, name: str, sector: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        hist = t.history(period="ytd", auto_adjust=False)
        if hist.empty:
            hist = t.history(period="5d", auto_adjust=False)
        if hist.empty:
            print(f"[stocks] {ticker} no history")
            return None

        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        change = price - prev
        pct = (change / prev * 100) if prev else 0.0
        ytd_first = float(hist["Close"].iloc[0])
        ytd_pct = ((price - ytd_first) / ytd_first * 100) if ytd_first else 0.0

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "currency": info.get("currency") or info.get("financialCurrency") or "",
            "price": round(price, 2),
            "change": round(change, 2),
            "changePercent": round(pct, 2),
            "marketCap": info.get("marketCap"),
            "peRatio": round(info["trailingPE"], 2) if info.get("trailingPE") else None,
            "high52w": round(info["fiftyTwoWeekHigh"], 2) if info.get("fiftyTwoWeekHigh") else None,
            "low52w": round(info["fiftyTwoWeekLow"], 2) if info.get("fiftyTwoWeekLow") else None,
            "ytdPercent": round(ytd_pct, 2),
            "dividendYield": round(info["dividendYield"] * 100, 2) if info.get("dividendYield") else None,
        }
    except Exception as e:
        print(f"[stocks] {ticker} failed: {e}")
        return None


def fetch_all_stocks() -> dict:
    return {
        "us":    [s for s in (fetch_stock(*x) for x in US_STOCKS)    if s],
        "asia":  [s for s in (fetch_stock(*x) for x in ASIA_STOCKS)  if s],
        "india": [s for s in (fetch_stock(*x) for x in INDIA_STOCKS) if s],
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
                   top_n: int = TOP_N) -> list[dict]:
    all_items = []
    for src, url in feeds:
        all_items.extend(fetch_feed(src, url, limit=20))

    relevant = [i for i in all_items if keep_item(i, topic_re)]
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    fresh = [i for i in relevant if parse_date(i["published"]) >= cutoff]
    pool = fresh if len(fresh) >= top_n else (relevant if relevant else all_items)

    pool.sort(key=lambda x: parse_date(x["published"]), reverse=True)

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
    items = []

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
    deduped.sort(key=lambda x: parse_date(x["published"]), reverse=True)
    return deduped[:TOP_N]


def fetch_private_company_news(name: str, limit: int = 5) -> list[dict]:
    """Pull recent news for a private company via Google News RSS (no API key needed)."""
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(name)}&hl=en-US&gl=US&ceid=US:en"
    items = fetch_feed(f"Google News · {name}", url, limit=limit)
    return items


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

    print("Fetching private-company news…")
    privates = []
    for name, tag in PRIVATE_COMPANIES:
        news = fetch_private_company_news(name)
        privates.append({"name": name, "tag": tag, "news": news})
        print(f"  {name}: {len(news)} items")
    (DATA / "private.json").write_text(json.dumps(
        {"updated": now, "companies": privates}, indent=2
    ))

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

    for label, feeds, filter_re, filename in [
        ("india political", INDIA_POLITICAL_FEEDS, INDIA_POLITICS_RE, "news_india.json"),
        ("geopolitical",    GEOPOLITICAL_FEEDS,    GEOPOLITICS_RE,    "news_global.json"),
    ]:
        print(f"Fetching {label} news…")
        new_items = fetch_category(feeds, filter_re)
        existing  = load_existing_items(DATA / filename)
        merged    = merge_with_history(new_items, existing)
        (DATA / filename).write_text(json.dumps(
            {"updated": now, "items": merged}, indent=2
        ))
        print(f"  stored {len(merged)} items in {filename} — was {len(existing)} before merge")


if __name__ == "__main__":
    main()
