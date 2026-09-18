# Win786 Competitor Monitor v2.0 — Setup Guide

Monitors **786win.pk** 24/7 and sends Telegram alerts for:
- ✅ New web mentions (Google Alerts RSS)
- ✅ New/updated pages on competitor domain (Wayback Machine CDX API)
- ✅ Reddit posts mentioning competitor (Public JSON API)
- ✅ Web pages mentioning competitor (Google Custom Search API)
- ✅ New indexed pages (CommonCrawl Index API)

---

## Step 1: Create a Telegram Bot (2 minutes)

1. Open Telegram, search for **@BotFather**
2. Send: `/newbot`
3. Give it a name: `Win786 Monitor`
4. Give it a username: `win786monitor_bot` (must end in `bot`)
5. BotFather sends you a **token** — looks like: `7123456789:AAF...`
6. **Save this token**

To get your **Chat ID**:
1. Search for **@userinfobot** on Telegram
2. Start it, it will reply with your chat ID (a number like `123456789`)
3. **Save this number**

---

## Step 2: Set Up Google Alerts (3 minutes)

1. Go to **google.com/alerts**
2. Create these 3 alerts (one at a time):
   - `786win.pk`
   - `"786win"`
   - `786win game`
3. For each alert, set:
   - **How often:** As-it-happens
   - **Sources:** Everything
   - **Delivery to:** RSS Feed
4. After creating each alert, click the RSS icon to get the feed URL
5. Save all 3 RSS feed URLs

---

## Step 3: Set Up Google Custom Search API (5 minutes, Optional)

This adds web mention discovery. Without it, the monitor still works (just skips this source).

1. Go to **console.cloud.google.com**
2. Create a new project (free)
3. Enable **Custom Search JSON API**
4. Create an API key under **Credentials**
5. Go to **programmablesearchengine.google.com**
6. Create a new search engine → search the entire web
7. Copy your **Search Engine ID (cx)**

Free tier: **100 queries per day**. The monitor uses ~3 queries per run × 4 runs/day = 12/day.

---

## Step 4: Add GitHub Secrets

In your GitHub repository, go to **Settings → Secrets and variables → Actions** and add:

| Secret Name | Value | Required? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from Step 1 | ✅ Yes |
| `TELEGRAM_CHAT_ID` | Your chat ID from Step 1 | ✅ Yes |
| `ALERT_FEED_1` | Google Alert RSS URL 1 from Step 2 | ✅ Yes |
| `ALERT_FEED_2` | Google Alert RSS URL 2 from Step 2 | ✅ Yes |
| `ALERT_FEED_3` | Google Alert RSS URL 3 from Step 2 | ✅ Yes |
| `GOOGLE_CSE_API_KEY` | Your API key from Step 3 | ⚠️ Optional |
| `GOOGLE_CSE_ID` | Your search engine ID from Step 3 | ⚠️ Optional |

---

## Step 5: Deploy

### Option A: GitHub Actions (Recommended, Free)

1. Push the `competitor-monitor/` folder to a GitHub repo
2. The `.github/workflows/monitor.yml` runs the monitor automatically every 6 hours
3. You can also trigger it manually from the **Actions** tab → **Run workflow**

### Option B: Railway / Heroku (24/7 Server)

1. Push to a GitHub repo
2. Connect to Railway/Heroku
3. Set the same environment variables from the table above
4. The `Procfile` will run the monitor in continuous mode (every 30 min)

---

## Testing

### Test Telegram Connection
```bash
# Set your env vars first, then:
python monitor.py --test-telegram
```

### Run Once Locally
```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
export ALERT_FEED_1="https://www.google.com/alerts/feeds/..."
python monitor.py --once
```

---

## What You'll Get in Telegram

### Individual Alerts
```
🔔 New Google Alert Activity
Competitor: 786win.pk
Title: 786win game review — best earning app Pakistan
URL: https://somewebsite.com/786win-review

📣 New Reddit Activity
Competitor: 786win.pk
Title: Anyone tried 786win.pk? Is it legit?
Subreddit: r/pakistan
URL: https://reddit.com/r/pakistan/...

🕸️ New CommonCrawl Activity
Competitor: 786win.pk
Title: Page indexed: techblog.pk
URL: https://techblog.pk/786win-guide
```

### Summary (sent after every run)
```
📊 Monitor Summary
Time: 2026-09-18 10:30 UTC
Target: 786win.pk
New items: 3
  ✅ Google Alert: 1
  — Wayback CDX: 0
  ✅ Reddit: 2
  — Google CSE: 0
  — CommonCrawl: 0
DB size: 47 tracked items
```

---

## Monitor Schedule

- **GitHub Actions:** Every 6 hours (0:00, 6:00, 12:00, 18:00 UTC)
- **Server mode:** Every 30 minutes

---

## Data Sources & Limits

| Source | Method | Free Limit | Auth Needed? |
|---|---|---|---|
| Google Alerts | RSS Feed | Unlimited | No |
| Wayback Machine | CDX API | Unlimited | No |
| Reddit | Public JSON API | ~60 req/min | No |
| Google CSE | JSON API | 100 queries/day | API Key |
| CommonCrawl | Index API | Unlimited | No |

---

## Files

- `monitor.py` — main monitor script (v2.0)
- `requirements.txt` — Python packages
- `Procfile` — tells Railway/Heroku how to run it
- `.github/workflows/monitor.yml` — GitHub Actions workflow
- `SETUP.md` — this file
