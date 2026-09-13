import feedparser
import requests
import time
import json
import os
import hashlib
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURATION
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

COMPETITOR_DOMAIN = "786win.pk"
COMPETITOR_BRAND  = "786win"

GOOGLE_ALERT_FEEDS = [
    os.environ.get("ALERT_FEED_1", ""),
    os.environ.get("ALERT_FEED_2", ""),
    os.environ.get("ALERT_FEED_3", ""),
]

SEEN_FILE = "seen_items.json"

# ============================================================
# HELPERS
# ============================================================

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_set), f)

def item_id(url, title=""):
    return hashlib.md5((url + title).encode()).hexdigest()

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("[WARN] Telegram not configured. Message:", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }, timeout=10)
        if r.status_code != 200:
            print(f"[ERROR] Telegram: {r.text}")
    except Exception as e:
        print(f"[ERROR] Telegram: {e}")

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

# ============================================================
# MODULE 1: Google Alerts RSS
# ============================================================

def check_google_alerts(seen):
    new_items = []
    for feed_url in GOOGLE_ALERT_FEEDS:
        if not feed_url:
            continue
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                uid = item_id(entry.get("link", ""), entry.get("title", ""))
                if uid not in seen:
                    seen.add(uid)
                    new_items.append({
                        "source": "Google Alert",
                        "title": entry.get("title", "No title"),
                        "url": entry.get("link", ""),
                        "published": entry.get("published", "")
                    })
        except Exception as e:
            log(f"[Alert Error] {e}")
    return new_items, seen

# ============================================================
# MODULE 2: Ahrefs Free Backlink Checker
# ============================================================

def check_ahrefs_free(seen):
    new_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        url = f"https://ahrefs.com/backlink-checker/?input={COMPETITOR_DOMAIN}&mode=domain"
        r = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table tbody tr")[:10]
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 2:
                link_el = cols[0].find("a")
                if link_el:
                    href = link_el.get("href", "")
                    text = link_el.get_text(strip=True)
                    uid = item_id(href, text)
                    if uid not in seen:
                        seen.add(uid)
                        new_items.append({
                            "source": "Ahrefs Backlink",
                            "title": text or href,
                            "url": href
                        })
    except Exception as e:
        log(f"[Ahrefs Error]: {e}")
    return new_items, seen

# ============================================================
# MAIN JOB
# ============================================================

def run_monitor():
    log("Running monitor cycle...")
    seen = load_seen()
    all_new = []

    items, seen = check_google_alerts(seen)
    all_new.extend(items)

    items, seen = check_ahrefs_free(seen)
    all_new.extend(items)

    save_seen(seen)

    if all_new:
        log(f"Found {len(all_new)} new item(s). Sending alerts...")
        for item in all_new:
            emoji = "🔔" if item["source"] == "Google Alert" else "🔗"
            msg = f"{emoji} <b>New {item['source']}</b>\n"
            msg += f"<b>Competitor:</b> {COMPETITOR_DOMAIN}\n"
            if item.get("title"):
                msg += f"<b>Title:</b> {item['title'][:120]}\n"
            if item.get("url"):
                msg += f"<b>URL:</b> {item['url']}"
            send_telegram(msg)
            time.sleep(1)
    else:
        log("No new items found.")

# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":
    import sys

    if "--once" in sys.argv:
        # Single run mode (for GitHub Actions)
        log(f"Single run. Watching: {COMPETITOR_DOMAIN}")
        run_monitor()
    else:
        # Loop mode (for local or server deployment)
        log(f"Monitor started. Watching: {COMPETITOR_DOMAIN}")
        send_telegram(
            f"✅ <b>Monitor Started</b>\n"
            f"Watching: <code>{COMPETITOR_DOMAIN}</code>\n"
            f"Checks every: 30 minutes\n"
            f"Sources: Google Alerts, Ahrefs Free"
        )
        run_monitor()

        scheduler = BlockingScheduler()
        scheduler.add_job(run_monitor, "interval", minutes=30)
        scheduler.start()

