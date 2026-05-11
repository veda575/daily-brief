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
    ("Anthropic",       "https://www.anthropic.com/news/rss.xml"),
    ("OpenAI",          "https://openai.com/blog/rss.xml"),
    ("Hugging Face",    "https://huggingface.co/blog/feed.xml"),
    ("Google AI",       "https://blog.google/technology/ai/rss/"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("The Verge",       "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch",      "https://techcrunch.com/feed/"),
    ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/index"),
    ("Wired",           "https://www.wired.com/feed/rss"),
]

INDIA_POLITICAL_FEEDS = [
    ("Times of India",  "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"),
    ("The Hindu",       "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("Indian Express",  "https://indianexpress.com/section/india/feed/"),
    ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/index.xml"),
    ("NDTV",            "https://feeds.feedburner.com/ndtvnews-top-stories"),
    ("Mint",            "https://www.livemint.com/rss/politics"),
]

GEOPOLITICAL_FEEDS = [
    ("BBC World",       "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera",      "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Foreign Policy",  "https://foreignpolicy.com/feed/"),
    ("The Diplomat",    "https://thediplomat.com/feed/"),
    ("AP World",        "https://feeds.apnews.com/rss/world"),
    ("DW",              "https://rss.dw.com/rdf/rss-en-world"),
    ("Reuters World",   "https://www.reutersagency.com/feed/?best-topics=world&post_type=best"),
]

TOP_N = 20
LOOKBACK_DAYS = 30   # widen to 30d so we always have items; UI labels as "recent"

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


def fetch_category(feeds: list[tuple[str, str]], top_n: int = TOP_N) -> list[dict]:
    all_items = []
    for src, url in feeds:
        all_items.extend(fetch_feed(src, url))
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    fresh = [i for i in all_items if parse_date(i["published"]) >= cutoff]
    pool = fresh if len(fresh) >= top_n else all_items
    pool.sort(key=lambda x: parse_date(x["published"]), reverse=True)
    seen = set()
    deduped = []
    for it in pool:
        key = it["url"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped[:top_n]


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

    for label, feeds, filename in [
        ("tech / AI",     TECH_AI_FEEDS,        "news_tech.json"),
        ("india political", INDIA_POLITICAL_FEEDS, "news_india.json"),
        ("geopolitical",  GEOPOLITICAL_FEEDS,   "news_global.json"),
    ]:
        print(f"Fetching {label} news…")
        items = fetch_category(feeds)
        (DATA / filename).write_text(json.dumps(
            {"updated": now, "items": items}, indent=2
        ))
        print(f"  wrote {len(items)} items to {filename}")


if __name__ == "__main__":
    main()
