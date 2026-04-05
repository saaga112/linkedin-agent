# 🤖 LinkedIn AI Agent — Setup Guide
**For: Satyam Agarwal | AI/Data Engineering Architect**

This agent automatically:
- ✅ Posts weekly AI/Data Engineering content on LinkedIn (every Tuesday at 9 AM by default)
- ✅ Reads every new comment on your posts and replies instantly with AI
- ✅ Reads every new DM and replies with a professional, personalised response
- ✅ Skips spam and classifies comments before replying

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   LinkedIn AI Agent                     │
│                                                         │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │  Scheduler  │───▶│ ContentGen   │───▶│ LinkedIn  │  │
│  │  (weekly    │    │ (Claude AI)  │    │    API    │  │
│  │   post)     │    └──────────────┘    │  (post)   │  │
│  └─────────────┘                        └───────────┘  │
│                                                         │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │  Scheduler  │───▶│  Browser     │───▶│  Reply    │  │
│  │  (every     │    │  Monitor     │    │  Engine   │  │
│  │   30 min)   │    │  (Playwright)│    │           │  │
│  └─────────────┘    └──────────────┘    └───────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Hybrid approach:**
- **LinkedIn Official API** — Used for posting content (stable, reliable)
- **Playwright (browser automation)** — Used for monitoring comments & messages (API doesn't expose these without Partner approval)

---

## Step 1 — Prerequisites

Make sure you have **Python 3.10+** installed.

```bash
python --version
```

---

## Step 2 — Install Dependencies

```bash
cd LinkedInAgent
pip install -r requirements.txt
playwright install chromium
```

---

## Step 3 — Create a LinkedIn Developer App

1. Go to [https://www.linkedin.com/developers/apps](https://www.linkedin.com/developers/apps)
2. Click **Create App**
3. Fill in:
   - **App name**: `My LinkedIn Agent` (or anything)
   - **LinkedIn Page**: Your personal profile page
   - **App logo**: Any image
4. In the **Auth** tab, add a redirect URL: `http://localhost:8080/callback`
5. In the **Products** tab, request access to **Share on LinkedIn** (instant approval)
6. Copy your **Client ID** and **Client Secret**

---

## Step 4 — Configure Your .env File

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
ANTHROPIC_API_KEY=sk-ant-...        # From https://console.anthropic.com
LINKEDIN_EMAIL=agarsatyam1@gmail.com
LINKEDIN_PASSWORD=your_password
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
```

---

## Step 5 — Get Your LinkedIn Access Token (OAuth)

Run the setup wizard:

```bash
python main.py --setup
```

This will:
1. Print a URL — open it in your browser
2. Authorize the app (click "Allow")
3. Copy the `code=` value from the redirect URL
4. Paste it back into the terminal
5. Your access token will be printed — paste it into `.env` as `LINKEDIN_ACCESS_TOKEN=...`

---

## Step 6 — First Login (Browser Session)

On first run, set `HEADLESS_BROWSER=false` in `.env` so you can see the browser window and complete any 2FA/CAPTCHA manually.

```bash
python main.py --dry-run
```

This opens the browser, logs you in, saves the session cookie, and shows you what posts/replies would be generated — without actually posting anything.

After a successful dry run, change `HEADLESS_BROWSER=true` in `.env`.

---

## Step 7 — Start the Agent

```bash
python main.py
```

The agent will:
- Start the browser session in the background
- Schedule your weekly post (Tuesday 9 AM by default)
- Scan for new comments and messages every 30 minutes

---

## Manual Commands

```bash
# Post right now (auto-generate topic)
python main.py --post-now

# Post on a specific topic right now
python main.py --post-now "Real-world lessons from deploying RAG pipelines at scale"

# Immediately reply to all pending comments and messages
python main.py --engage-now

# Test without posting/replying
python main.py --dry-run
```

---

## Customize Your Schedule

Edit `.env`:

```env
POST_DAY_OF_WEEK=wednesday     # monday–friday
POST_HOUR=8                    # 8 AM
POST_MINUTE=30                 # 8:30 AM
ENGAGEMENT_INTERVAL_MINUTES=15 # Check every 15 min instead of 30
```

---

## File Structure

```
LinkedInAgent/
├── main.py                        ← Entry point (run this)
├── config.py                      ← Config loader
├── requirements.txt               ← Python dependencies
├── .env.example                   ← Copy to .env and fill in
├── .gitignore                     ← Protects credentials from git
│
├── linkedin_agent/
│   ├── __init__.py
│   ├── agent.py                   ← Main orchestrator + scheduler
│   ├── linkedin_client.py         ← LinkedIn REST API wrapper
│   ├── content_generator.py       ← Claude AI content + reply generator
│   ├── browser_monitor.py         ← Playwright browser monitor
│   └── reply_engine.py            ← Comment + message reply engine
│
└── data/                          ← Auto-created at runtime
    ├── linkedin_session.json      ← Saved browser session (auto)
    ├── posts_log.json             ← Log of published posts (auto)
    └── replied_items.json         ← Deduplication state (auto)
```

---

## Run as a Background Service (Optional)

To keep the agent running 24/7 in the background on a Mac or Linux machine:

**Mac (launchd):**
```bash
# Create a launchd plist or simply run in a screen session:
screen -S linkedin_agent
python main.py
# Detach: Ctrl+A then D
```

**Linux (systemd):**
```bash
# Create /etc/systemd/system/linkedin-agent.service
# Then: systemctl enable linkedin-agent && systemctl start linkedin-agent
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `Playwright not installed` | Run `pip install playwright && playwright install chromium` |
| Browser login fails | Set `HEADLESS_BROWSER=false` and complete 2FA manually |
| API post fails | Re-run `python main.py --setup` to refresh access token |
| Getting rate-limited | Increase `ENGAGEMENT_INTERVAL_MINUTES` to 60+ |
| Want to test safely | Set `DRY_RUN=true` in `.env` |

---

## Privacy & Safety Notes

- Your `.env` file is in `.gitignore` — it will never be committed to git
- The browser session cookie (`data/linkedin_session.json`) is stored locally only
- The agent uses human-like typing delays and rate limiting to avoid triggering LinkedIn's bot detection
- LinkedIn's Terms of Service permit personal automation for productivity; avoid aggressive scraping

---

*Built with Claude AI (Anthropic) + LinkedIn API + Playwright*
*Designed for Satyam Agarwal — AI/Data Engineering Architect*
