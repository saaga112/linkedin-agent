# 🤖 LinkedIn AI Agent

> **Automated LinkedIn presence for AI/Data Engineering professionals**
> Auto-posts weekly content · Auto-replies to every comment · Auto-responds to every DM

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Claude AI](https://img.shields.io/badge/Claude-claude--opus--4--6-D97706?style=flat&logo=anthropic&logoColor=white)](https://anthropic.com)
[![LinkedIn API](https://img.shields.io/badge/LinkedIn-REST%20API%20v2-0A66C2?style=flat&logo=linkedin&logoColor=white)](https://developer.linkedin.com)
[![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33?style=flat&logo=playwright&logoColor=white)](https://playwright.dev)
[![License](https://img.shields.io/badge/License-Private-red?style=flat)](LICENSE)

---

## What It Does

| Feature | Description |
|---|---|
| 📝 **Weekly Posts** | Generates and publishes AI/Data Engineering content every Tuesday at 9 AM |
| 💬 **Comment Replies** | Monitors all post comments every 30 min and replies with contextual AI responses |
| 📨 **DM Replies** | Reads unread LinkedIn messages and sends personalised replies automatically |
| 🚫 **Spam Filter** | Classifies comments before replying — skips spam silently |
| 🔁 **No Double-replies** | Persistent deduplication state across restarts |
| 🧪 **Dry-run Mode** | Full test mode — generates content but never posts or replies |

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                      LinkedIn AI Agent                        │
│                                                               │
│  ⏰ APScheduler                                               │
│  ├── CronTrigger ──► 📝 ContentGenerator (Claude AI)         │
│  │                        └──► 📤 LinkedIn REST API           │
│  │                               (POST /v2/ugcPosts)          │
│  │                                                            │
│  └── IntervalTrigger (30 min)                                 │
│       └──► 🌐 BrowserMonitor (Playwright)                     │
│                ├── Scrape notifications & comments            │
│                ├── Scrape DM inbox                            │
│                └──► 💬 ReplyEngine                            │
│                         ├── Classify (Claude AI)              │
│                         ├── Deduplicate (replied_items.json)  │
│                         └── Post reply via browser            │
└───────────────────────────────────────────────────────────────┘
```

**Hybrid design:**
- **LinkedIn Official API** → posting content (stable, OAuth-authenticated)
- **Playwright browser automation** → monitoring comments & messages (API doesn't expose these without Partner Program approval)
- **Claude AI (claude-opus-4-6)** → all content generation and classification

---

## Project Structure

```
linkedin-agent/
├── main.py                        ← Entry point — run this
├── config.py                      ← Environment variable loader
├── requirements.txt               ← Python dependencies
├── .env.example                   ← Copy to .env and configure
├── .gitignore
├── SETUP_GUIDE.md                 ← Detailed setup walkthrough
│
├── linkedin_agent/
│   ├── agent.py                   ← Main orchestrator + scheduler
│   ├── linkedin_client.py         ← LinkedIn REST API wrapper (OAuth, posting)
│   ├── content_generator.py       ← Claude AI: posts, replies, classification
│   ├── browser_monitor.py         ← Playwright: login, comments, DMs
│   └── reply_engine.py            ← Reply logic, dedup, spam filter
│
├── docs/
│   ├── LinkedIn_AI_Agent_Documentation.docx   ← Full technical doc
│   ├── LinkedIn_AI_Agent_Workflow.pptx        ← 7-slide deck
│   └── architecture_workflow.mermaid          ← Pipeline flowchart
│
└── data/                          ← Auto-created at runtime
    ├── linkedin_session.json      ← Saved browser session
    ├── posts_log.json             ← Published post history
    └── replied_items.json         ← Deduplication state
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/saaga112/linkedin-agent.git
cd linkedin-agent
pip install -r requirements.txt
playwright install chromium
```

### 2. Create LinkedIn Developer App

1. Go to [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) → **Create App**
2. In **Auth** tab → add redirect URI: `http://localhost:8080/callback`
3. In **Products** tab → request **Share on LinkedIn** (instant approval)
4. Copy your **Client ID** and **Client Secret**

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required variables:

```env
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASSWORD=yourpassword
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
```

### 4. Get OAuth Token

```bash
python main.py --setup
```

Follow the prompts → paste your access token into `.env` as `LINKEDIN_ACCESS_TOKEN`.

### 5. First Login (handles 2FA)

```bash
# Keep HEADLESS_BROWSER=false for first run
python main.py --dry-run
```

After successful login, set `HEADLESS_BROWSER=true` in `.env`.

### 6. Go Live

```bash
python main.py
```

---

## CLI Commands

```bash
python main.py                          # Full agent (scheduled mode)
python main.py --post-now               # Post right now (auto topic)
python main.py --post-now "RAG at scale"  # Post on specific topic
python main.py --engage-now             # Run one reply cycle now
python main.py --dry-run                # Test — no real posts/replies
python main.py --setup                  # OAuth setup wizard
```

---

## Schedule Configuration

Edit `.env` to customise:

```env
POST_DAY_OF_WEEK=tuesday       # monday–friday
POST_HOUR=9                    # 9 AM
POST_MINUTE=0
ENGAGEMENT_INTERVAL_MINUTES=30 # Reply scan every 30 min
```

---

## Content Topics

The agent cycles through 20 built-in AI/Data Engineering topics weekly:

- Building real-time data pipelines with Apache Kafka and Flink
- How AI agents are transforming data engineering workflows
- Modern data lakehouse architecture: Delta Lake vs Apache Iceberg
- MLOps best practices for production AI systems
- Vector databases: Pinecone, Weaviate, and pgvector compared
- Data mesh architecture: decentralising data ownership
- LLM fine-tuning vs RAG: when to use each approach
- The future of the Modern Data Stack in the AI era
- _...and 12 more topics_

Or post on any custom topic instantly:
```bash
python main.py --post-now "Your topic here"
```

---

## How Reply Intelligence Works

```
New Comment Received
        │
        ▼
  Already replied? ──YES──► Skip
        │ NO
        ▼
  Classify with Claude AI
        │
   ┌────┴────┬──────────┬─────────────┬──────────────┐
   ▼         ▼          ▼             ▼              ▼
question  praise  disagreement  engagement       spam
   │         │          │             │              │
   └────┬────┘          └──────┬──────┘           Skip
        ▼                      ▼
  Generate contextual reply (Claude AI)
        │
        ▼
  Post reply via browser → Save to dedup state
```

---

## Documentation

| File | Contents |
|---|---|
| [`SETUP_GUIDE.md`](SETUP_GUIDE.md) | Step-by-step setup walkthrough |
| [`docs/LinkedIn_AI_Agent_Documentation.docx`](docs/LinkedIn_AI_Agent_Documentation.docx) | Full technical documentation (architecture, modules, workflows, troubleshooting) |
| [`docs/LinkedIn_AI_Agent_Workflow.pptx`](docs/LinkedIn_AI_Agent_Workflow.pptx) | 7-slide presentation deck |
| [`docs/architecture_workflow.mermaid`](docs/architecture_workflow.mermaid) | Agent pipeline flowchart |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Playwright not installed | `pip install playwright && playwright install chromium` |
| Login fails / CAPTCHA | Set `HEADLESS_BROWSER=false`, complete manually |
| API post fails (401) | Re-run `python main.py --setup` to refresh token |
| Getting rate-limited | Increase `ENGAGEMENT_INTERVAL_MINUTES` to `60` |
| Double-replies | Delete `data/replied_items.json` |
| Session expiring | Delete `data/linkedin_session.json` to force fresh login |

---

## Security Notes

- `.env` is in `.gitignore` — credentials are never committed
- Browser session cookies stored locally in `data/` only
- Human-like typing delays and rate limiting prevent bot detection
- `DRY_RUN=true` for safe testing at any time

---

## Built With

- [Anthropic Claude API](https://docs.anthropic.com) — AI content generation
- [LinkedIn REST API v2](https://learn.microsoft.com/en-us/linkedin/) — Official posting
- [Playwright](https://playwright.dev) — Browser automation
- [APScheduler](https://apscheduler.readthedocs.io) — Job scheduling

---

*Built for Satyam Agarwal — AI / Data Engineering Architect*
