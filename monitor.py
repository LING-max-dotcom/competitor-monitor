"""
Win786 Competitor Monitor v2.0
==============================
Monitors 786win.pk for new backlinks, mentions, and activity.
Sends alerts to Telegram when new items are discovered.

Data Sources:
  1. Google Alerts RSS (user-configured feeds)
  2. CommonCrawl Index API (new pages linking to competitor)
  3. Wayback Machine CDX API (new URLs mentioning competitor)
  4. Reddit JSON search (public, no auth needed)
  5. Google Custom Search JSON API (new web mentions)

Deployment: GitHub Actions (cron every 30 min via --once flag)
"""

import requests
import feedparser
import time
import json
import os
import hashlib
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

# ============================================================
# CONFIGURATION
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

COMPETITOR_DOMAIN = "786win.pk"
COMPETITOR_BRAND  = "786win"

# Google Alerts RSS feed URLs
GOOGLE_ALERT_FEEDS = [
    os.environ.get("ALERT_FEED_1", ""),
    os.environ.get("ALERT_FEED_2", ""),
    os.environ.get("ALERT_FEED_3", ""),
]

# Google Custom Search Engine (optional, for web mention monitoring)
GOOGLE_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_ID      = os.environ.get("GOOGLE_CSE_ID", "")

# Persistent state file (cached across GitHub Actions runs)
SEEN_FILE = "seen_items.json"

# User-Agent for HTTP requests
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# ============================================================
# HELPERS
# ============================================================

def load_seen():
    """Load previously seen item hashes from JSON file."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                data = json.load(f)
                # Support both list (legacy) and dict (new) formats
                if isinstance(data, list):
                    return {"items": set(data), "last_run": None}
                return {"items": set(data.get("items", [])), "last_run": data.get("last_run")}
        except (json.JSONDecodeError, Exception) as e:
            log(f"[WARN] Could not load seen file: {e}")
    return {"items": set(), "last_run": None}


def save_seen(seen_data):
    """Save seen item hashes to JSON file."""
    with open(SEEN_FILE, "w") as f:
        json.dump({
            "items": list(seen_data["items"]),
            "last_run": datetime.now(timezone.utc).isoformat()
        }, f)


def item_id(url, title=""):
    """Generate a unique hash for a discovered item."""
    return hashlib.md5((url + title).encode()).hexdigest()


def log(msg):
    """Print timestamped log message."""
    text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def send_telegram(message):
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log(f"[WARN] Telegram not configured. Message: {message[:200]}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }, timeout=15)
        if r.status_code == 200:
            log("[OK] Telegram message sent.")
            return True
        else:
            log(f"[ERROR] Telegram HTTP {r.status_code}: {r.text[:300]}")
            return False
    except Exception as e:
        log(f"[ERROR] Telegram exception: {e}")
        return False


def safe_get(url, headers=None, timeout=20):
    """Make a GET request with error handling. Returns response or None."""
    if headers is None:
        headers = {"User-Agent": UA}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.HTTPError as e:
        log(f"[HTTP Error] {e}")
    except requests.exceptions.ConnectionError as e:
        log(f"[Connection Error] {url}: {e}")
    except requests.exceptions.Timeout:
        log(f"[Timeout] {url}")
    except Exception as e:
        log(f"[Request Error] {url}: {e}")
    return None


# ============================================================
# MODULE 1: Google Alerts RSS
# ============================================================

def check_google_alerts(seen_items):
    """Parse Google Alerts RSS feeds for new entries."""
    new_items = []
    active_feeds = 0

    for feed_url in GOOGLE_ALERT_FEEDS:
        if not feed_url or not feed_url.startswith("http"):
            continue
        active_feeds += 1
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                log(f"[Alert WARN] Feed parse error: {feed.bozo_exception}")
                continue

            log(f"[Alert] Feed returned {len(feed.entries)} entries")
            for entry in feed.entries:
                link = entry.get("link", "")
                title = entry.get("title", "No title")
                # Clean HTML from title
                title = re.sub(r"<[^>]+>", "", title).strip()
                uid = item_id(link, title)
                if uid not in seen_items:
                    seen_items.add(uid)
                    new_items.append({
                        "source": "Google Alert",
                        "title": title,
                        "url": link,
                        "published": entry.get("published", "")
                    })
        except Exception as e:
            log(f"[Alert Error] {e}")

    if active_feeds == 0:
        log("[Alert] No active Google Alert feeds configured.")
    else:
        log(f"[Alert] Checked {active_feeds} feed(s), found {len(new_items)} new item(s)")

    return new_items, seen_items


# ============================================================
# MODULE 2: Wayback Machine CDX API (Free Backlink Discovery)
# ============================================================

def check_wayback_cdx(seen_items):
    """
    Use the Wayback Machine CDX API to find newly archived pages
    of the competitor domain. New URLs appearing = new content/links.
    """
    new_items = []
    # Get pages from the last 7 days
    from_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

    url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url=*.{COMPETITOR_DOMAIN}/*"
        f"&output=json"
        f"&fl=timestamp,original,statuscode"
        f"&from={from_date}"
        f"&filter=statuscode:200"
        f"&collapse=urlkey"
        f"&limit=30"
    )

    log(f"[Wayback] Checking CDX API...")
    resp = safe_get(url, timeout=60)
    if not resp:
        log("[Wayback] CDX API request failed")
        return new_items, seen_items

    try:
        rows = resp.json()
        if not rows or len(rows) <= 1:
            log("[Wayback] No results")
            return new_items, seen_items

        # First row is the header
        for row in rows[1:]:
            if len(row) < 3:
                continue
            timestamp, original_url, status = row[0], row[1], row[2]
            uid = item_id(original_url, f"wayback-{timestamp}")
            if uid not in seen_items:
                seen_items.add(uid)
                new_items.append({
                    "source": "Wayback CDX",
                    "title": f"New/updated page on {COMPETITOR_DOMAIN}",
                    "url": original_url,
                    "published": timestamp
                })
    except Exception as e:
        log(f"[Wayback Error] {e}")

    log(f"[Wayback] Found {len(new_items)} new page(s)")
    return new_items, seen_items


# ============================================================
# MODULE 3: Reddit Search (Public JSON API, No Auth)
# ============================================================

def check_reddit(seen_items):
    """
    Search Reddit for mentions of the competitor brand/domain.
    Uses Reddit's public RSS search feeds (no API key or auth needed).
    """
    new_items = []
    search_terms = [COMPETITOR_DOMAIN, COMPETITOR_BRAND, "786 win pakistan"]

    headers = {
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml"
    }

    for term in search_terms:
        # Reddit RSS search endpoint — still publicly accessible
        url = f"https://www.reddit.com/search.rss?q={quote_plus(term)}&sort=new&limit=10&t=month"
        log(f"[Reddit] Searching RSS: {term}")

        try:
            feed = feedparser.parse(url, request_headers=headers)

            if feed.bozo and not feed.entries:
                log(f"[Reddit WARN] Feed parse error for '{term}': {feed.bozo_exception}")
                continue

            log(f"[Reddit] Found {len(feed.entries)} results for '{term}'")

            for entry in feed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                published = entry.get("published", "")

                # Try to extract subreddit from the link
                subreddit = ""
                if "/r/" in link:
                    parts = link.split("/r/")
                    if len(parts) > 1:
                        subreddit = "r/" + parts[1].split("/")[0]

                uid = item_id(link, title)
                if uid not in seen_items:
                    seen_items.add(uid)
                    new_items.append({
                        "source": "Reddit",
                        "title": title[:150],
                        "url": link,
                        "subreddit": subreddit,
                        "published": published
                    })
        except Exception as e:
            log(f"[Reddit Error] {e}")

        time.sleep(2)  # Be respectful to Reddit's rate limits

    log(f"[Reddit] Total new: {len(new_items)}")
    return new_items, seen_items


# ============================================================
# MODULE 4: Google Custom Search API (Web Mentions)
# ============================================================

def check_google_cse(seen_items):
    """
    Use Google Custom Search JSON API to find new web mentions.
    Free tier: 100 queries/day. We use ~3 per run.
    """
    new_items = []

    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
        log("[CSE] Google CSE not configured (no API key or CX). Skipping.")
        return new_items, seen_items

    search_queries = [
        f'"{COMPETITOR_DOMAIN}"',
        f'"{COMPETITOR_BRAND}" pakistan',
        f'"{COMPETITOR_BRAND}" app download',
    ]

    for query in search_queries:
        url = (
            f"https://www.googleapis.com/customsearch/v1"
            f"?key={GOOGLE_CSE_API_KEY}"
            f"&cx={GOOGLE_CSE_ID}"
            f"&q={quote_plus(query)}"
            f"&num=10"
            f"&dateRestrict=w1"  # Last week only
        )

        log(f"[CSE] Searching: {query}")
        resp = safe_get(url, timeout=15)
        if not resp:
            continue

        try:
            data = resp.json()

            if "error" in data:
                log(f"[CSE Error] {data['error'].get('message', 'Unknown error')}")
                continue

            results = data.get("items", [])
            log(f"[CSE] {len(results)} results for '{query}'")

            for item in results:
                link = item.get("link", "")
                title = item.get("title", "")
                # Skip results from the competitor's own domain
                if COMPETITOR_DOMAIN in link:
                    continue
                uid = item_id(link, title)
                if uid not in seen_items:
                    seen_items.add(uid)
                    new_items.append({
                        "source": "Google CSE",
                        "title": title[:150],
                        "url": link,
                        "snippet": item.get("snippet", "")[:200]
                    })
        except Exception as e:
            log(f"[CSE Error] {e}")

        time.sleep(1)

    log(f"[CSE] Total new: {len(new_items)}")
    return new_items, seen_items


# ============================================================
# MODULE 5: CommonCrawl Index API (Backlink Discovery)
# ============================================================

def check_commoncrawl(seen_items):
    """
    Query CommonCrawl index for pages that link to the competitor.
    Free, no auth required. Updated monthly.
    """
    new_items = []

    # Get the latest CC index
    log("[CC] Fetching latest CommonCrawl index...")
    resp = safe_get("https://index.commoncrawl.org/collinfo.json", timeout=15)
    if not resp:
        log("[CC] Could not fetch index list")
        return new_items, seen_items

    try:
        indexes = resp.json()
        if not indexes:
            return new_items, seen_items

        latest_index = indexes[0]["cdx-api"]
        log(f"[CC] Using index: {indexes[0].get('name', 'unknown')}")

        # Search for pages containing the competitor domain
        cc_url = f"{latest_index}?url=*.{COMPETITOR_DOMAIN}&output=json&limit=20"
        resp2 = safe_get(cc_url, timeout=30)
        if not resp2:
            return new_items, seen_items

        lines = resp2.text.strip().split("\n")
        for line in lines:
            try:
                record = json.loads(line)
                page_url = record.get("url", "")
                uid = item_id(page_url, "cc")
                if uid not in seen_items:
                    seen_items.add(uid)
                    new_items.append({
                        "source": "CommonCrawl",
                        "title": f"Page indexed: {urlparse(page_url).netloc}",
                        "url": page_url,
                    })
            except json.JSONDecodeError:
                continue

    except Exception as e:
        log(f"[CC Error] {e}")

    log(f"[CC] Found {len(new_items)} new page(s)")
    return new_items, seen_items


# ============================================================
# ALERT FORMATTING & SENDING
# ============================================================

def format_alert(item):
    """Format a single alert item as an HTML Telegram message."""
    source = item["source"]
    emoji_map = {
        "Google Alert": "🔔",
        "Wayback CDX": "📸",
        "Reddit": "📣",
        "Google CSE": "🔍",
        "CommonCrawl": "🕸️",
    }
    emoji = emoji_map.get(source, "📢")

    msg = f"{emoji} <b>New {source} Activity</b>\n"
    msg += f"<b>Competitor:</b> {COMPETITOR_DOMAIN}\n"

    if item.get("title"):
        msg += f"<b>Title:</b> {item['title'][:150]}\n"

    if item.get("subreddit"):
        msg += f"<b>Subreddit:</b> {item['subreddit']}\n"

    if item.get("snippet"):
        msg += f"<b>Snippet:</b> {item['snippet'][:200]}\n"

    if item.get("url"):
        msg += f"<b>URL:</b> {item['url']}"

    return msg


# ============================================================
# MAIN MONITOR JOB
# ============================================================

def run_monitor():
    """Execute one full monitoring cycle across all sources."""
    log("=" * 50)
    log("Starting monitor cycle...")
    log("=" * 50)

    seen_data = load_seen()
    seen_items = seen_data["items"]
    all_new = []
    source_counts = {}

    # --- Module 1: Google Alerts ---
    items, seen_items = check_google_alerts(seen_items)
    all_new.extend(items)
    source_counts["Google Alert"] = len(items)

    # --- Module 2: Wayback CDX ---
    items, seen_items = check_wayback_cdx(seen_items)
    all_new.extend(items)
    source_counts["Wayback CDX"] = len(items)

    # --- Module 3: Reddit ---
    items, seen_items = check_reddit(seen_items)
    all_new.extend(items)
    source_counts["Reddit"] = len(items)

    # --- Module 4: Google CSE ---
    items, seen_items = check_google_cse(seen_items)
    all_new.extend(items)
    source_counts["Google CSE"] = len(items)

    # --- Module 5: CommonCrawl ---
    items, seen_items = check_commoncrawl(seen_items)
    all_new.extend(items)
    source_counts["CommonCrawl"] = len(items)

    # Save state
    save_seen({"items": seen_items, "last_run": None})

    # Report
    log(f"\n--- Results ---")
    for source, count in source_counts.items():
        log(f"  {source}: {count} new item(s)")
    log(f"  TOTAL: {len(all_new)} new item(s)")
    log(f"  Seen DB size: {len(seen_items)} items")

    # Send individual alerts
    if all_new:
        log(f"Sending {len(all_new)} alert(s) to Telegram...")
        for item in all_new:
            msg = format_alert(item)
            send_telegram(msg)
            time.sleep(1.5)  # Avoid Telegram rate limits
    else:
        log("No new items found this cycle.")

    # Send summary (always, even if nothing new)
    summary = f"📊 <b>Monitor Summary</b>\n"
    summary += f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    summary += f"<b>Target:</b> {COMPETITOR_DOMAIN}\n"
    summary += f"<b>New items:</b> {len(all_new)}\n"
    for source, count in source_counts.items():
        status = "✅" if count > 0 else "—"
        summary += f"  {status} {source}: {count}\n"
    summary += f"<b>DB size:</b> {len(seen_items)} tracked items"
    send_telegram(summary)

    log("Monitor cycle complete.\n")
    return len(all_new)


# ============================================================
# STARTUP & CLI
# ============================================================

if __name__ == "__main__":
    if "--test-telegram" in sys.argv:
        # Quick test: just send a test message
        log("Testing Telegram connection...")
        success = send_telegram(
            f"🧪 <b>Test Message</b>\n"
            f"Telegram is working!\n"
            f"Bot Token: {'✅ Set' if TELEGRAM_BOT_TOKEN else '❌ Missing'}\n"
            f"Chat ID: {'✅ Set' if TELEGRAM_CHAT_ID else '❌ Missing'}"
        )
        if success:
            log("✅ Telegram test passed!")
        else:
            log("❌ Telegram test failed. Check your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        sys.exit(0 if success else 1)

    if "--once" in sys.argv:
        # Single run mode (for GitHub Actions)
        log(f"Single run mode. Watching: {COMPETITOR_DOMAIN}")
        log(f"Telegram: {'✅ Configured' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else '❌ Not configured'}")
        log(f"Google CSE: {'✅ Configured' if GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID else '⚠️ Not configured (skipping)'}")
        log(f"Alert feeds: {sum(1 for f in GOOGLE_ALERT_FEEDS if f)} configured")
        count = run_monitor()
        sys.exit(0)
    else:
        # Continuous mode (for server deployment)
        from apscheduler.schedulers.blocking import BlockingScheduler

        log(f"Continuous mode. Watching: {COMPETITOR_DOMAIN}")
        send_telegram(
            f"✅ <b>Monitor v2.0 Started</b>\n"
            f"Watching: <code>{COMPETITOR_DOMAIN}</code>\n"
            f"Checks every: 30 minutes\n"
            f"Sources: Google Alerts, Wayback, Reddit, Google CSE, CommonCrawl"
        )
        run_monitor()

        scheduler = BlockingScheduler()
        scheduler.add_job(run_monitor, "interval", minutes=30)
        scheduler.start()
