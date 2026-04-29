"""Fetch daily stock closes and recent LLM news, write JSON files for the dashboard."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

STOCKS = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("TCS.NS",      "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("ICICIBANK.NS","ICICI Bank"),
    ("BHARTIARTL.NS","Bharti Airtel"),
]

RSS_FEEDS = [
    ("Anthropic",       "https://www.anthropic.com/news/rss.xml"),
    ("OpenAI",          "https://openai.com/blog/rss.xml"),
    ("Hugging Face",    "https://huggingface.co/blog/feed.xml"),
    ("Google AI",       "https://blog.google/technology/ai/rss/"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
]

HN_API = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_stocks():
    out = []
    for ticker, name in STOCKS:
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
            if hist.empty or len(hist) < 2:
                continue
            close = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            change = close - prev
            pct = (change / prev) * 100 if prev else 0.0
            out.append({
                "ticker": ticker,
                "name": name,
                "close": round(close, 2),
                "change": round(change, 2),
                "changePercent": round(pct, 2),
            })
        except Exception as e:
            print(f"[stocks] {ticker} failed: {e}")
    return out


def fetch_rss_items():
    items = []
    for source, url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:5]:
                published = (
                    entry.get("published")
                    or entry.get("updated")
                    or ""
                )
                items.append({
                    "title": entry.get("title", "(untitled)").strip(),
                    "url": entry.get("link", ""),
                    "source": source,
                    "published": published,
                })
        except Exception as e:
            print(f"[rss] {source} failed: {e}")
    return items


def fetch_hn_items():
    items = []
    try:
        r = requests.get(HN_API, params={
            "tags": "story",
            "query": "LLM OR \"large language model\" OR Anthropic OR OpenAI",
            "hitsPerPage": 8,
        }, timeout=15)
        r.raise_for_status()
        for hit in r.json().get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            items.append({
                "title": hit.get("title", "(untitled)"),
                "url": url,
                "source": "Hacker News",
                "published": hit.get("created_at", ""),
            })
    except Exception as e:
        print(f"[hn] failed: {e}")
    return items


def parse_date(s):
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            d = datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def main():
    now = datetime.now(timezone.utc).isoformat()

    stocks = fetch_stocks()
    (DATA / "stocks.json").write_text(json.dumps(
        {"updated": now, "stocks": stocks}, indent=2
    ))
    print(f"[stocks] wrote {len(stocks)} entries")

    items = fetch_rss_items() + fetch_hn_items()
    items.sort(key=lambda x: parse_date(x["published"]), reverse=True)
    items = items[:20]
    (DATA / "news.json").write_text(json.dumps(
        {"updated": now, "items": items}, indent=2
    ))
    print(f"[news] wrote {len(items)} entries")


if __name__ == "__main__":
    main()
