"""
LinkedIn Agent — Main Orchestrator
Ties together: content generation, posting, comment monitoring, and auto-replies.
Runs on a schedule: posts weekly, checks for replies every 30 minutes.

Improvements:
- max_instances=1 on all jobs (was: overlapping concurrent execution possible)
- Signal handling via loop.add_signal_handler (was: lambda closure bug)
- File-locking on posts_log.json (was: race condition on concurrent writes)
- JSON schema validation on log load (was: crash on malformed file)
- Proper logging throughout
"""

import asyncio
import json
import logging
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional
import fcntl

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .linkedin_client import LinkedInClient
from .content_generator import ContentGenerator
from .browser_monitor import LinkedInBrowserMonitor
from .reply_engine import ReplyEngine

logger = logging.getLogger(__name__)


class LinkedInAgent:
    """
    The main LinkedIn AI Agent.
    1. Posts weekly AI/Data Engineering content
    2. Scans for new comments every N minutes and auto-replies
    3. Scans for new DMs every N minutes and auto-replies
    """

    def __init__(self, config: dict):
        self.config    = config
        self._running  = False

        # ── Components ───────────────────────────────
        self.linkedin = LinkedInClient(
            client_id         = config["linkedin_client_id"],
            client_secret     = config["linkedin_client_secret"],
            access_token      = config.get("linkedin_access_token"),
            refresh_token     = config.get("linkedin_refresh_token"),
        )
        self.content_gen = ContentGenerator(
            api_key = config["anthropic_api_key"],
            model   = config.get("claude_model", "claude-opus-4-6"),
        )
        self.browser = LinkedInBrowserMonitor(
            email       = config["linkedin_email"],
            password    = config["linkedin_password"],
            headless    = config.get("headless_browser", True),
            session_dir = config.get("data_dir", "./data"),
        )
        self.reply_engine = ReplyEngine(
            content_generator = self.content_gen,
            browser_monitor   = self.browser,
            state_dir         = config.get("data_dir", "./data"),
            dry_run           = config.get("dry_run", False),
        )
        self.scheduler = AsyncIOScheduler()
        self._posts_log = self._load_posts_log()

    # ──────────────────────────────────────────────
    # Posts Log (thread-safe file I/O)
    # ──────────────────────────────────────────────

    def _log_path(self) -> Path:
        p = Path(self.config.get("data_dir", "./data")) / "posts_log.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load_posts_log(self) -> list:
        """Load posts log with schema validation and error recovery."""
        path = self._log_path()
        if not path.exists():
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.warning("[Agent] ⚠️  posts_log.json is not a list. Resetting.")
                return []
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[Agent] ⚠️  Corrupted posts_log.json (%s). Resetting.", e)
            return []

    def _save_post_log(self, post_text: str, post_id: str, post_url: Optional[str] = None):
        """Append a post entry to the log with exclusive file locking."""
        entry = {
            "post_id":   post_id,
            "post_text": post_text,
            "post_url":  post_url,
            "timestamp": datetime.now().isoformat(),
        }
        self._posts_log.append(entry)
        self._posts_log = self._posts_log[-100:]  # Keep last 100

        path    = self._log_path()
        tmp     = path.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(self._posts_log, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            tmp.replace(path)  # Atomic replace
        except Exception as e:
            logger.error("[Agent] ❌ Could not save posts log: %s", e, exc_info=True)
            tmp.unlink(missing_ok=True)

    def get_recent_posts(self, n: int = 10) -> list:
        return self._posts_log[-n:]

    # ──────────────────────────────────────────────
    # Scheduled Jobs
    # ──────────────────────────────────────────────

    async def job_post_content(self, custom_topic: Optional[str] = None):
        """Weekly job: generate and publish a LinkedIn post."""
        logger.info("=" * 60)
        logger.info("[Agent] 📝 POST JOB triggered at %s",
                    datetime.now().strftime("%Y-%m-%d %H:%M"))
        logger.info("=" * 60)

        try:
            post_text = self.content_gen.generate_weekly_post(custom_topic=custom_topic)
            logger.info("[Agent] 📋 Generated post preview:\n%s...", post_text[:200])

            if self.config.get("dry_run"):
                logger.info("[Agent] 🔍 DRY RUN — post not published.")
                return

            # Try official API first
            if self.config.get("linkedin_access_token"):
                try:
                    result   = self.linkedin.create_post(post_text)
                    post_id  = result.get("post_id", "unknown")
                    post_url = result.get("post_url")
                    self._save_post_log(post_text, post_id, post_url)
                    logger.info("[Agent] ✅ Post published via API. ID: %s", post_id)
                    return
                except Exception as e:
                    logger.warning("[Agent] ⚠️  API post failed: %s — falling back to browser.", e)

            # Fallback: browser
            success = await self.browser.create_post_via_browser(post_text)
            if success:
                browser_id = f"browser_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                self._save_post_log(post_text, browser_id, None)

        except Exception as e:
            logger.error("[Agent] ❌ Post job failed: %s", e, exc_info=True)

    async def job_engagement(self):
        """Interval job: scan for new comments and DMs, reply to each."""
        logger.info("[Agent] 🔄 ENGAGEMENT JOB triggered at %s",
                    datetime.now().strftime("%H:%M"))
        try:
            summary = await self.reply_engine.run_engagement_cycle(
                self.get_recent_posts(n=10)
            )
            logger.info("[Agent] 📊 Engagement summary: %s", summary)
        except Exception as e:
            logger.error("[Agent] ❌ Engagement job failed: %s", e, exc_info=True)

    # ──────────────────────────────────────────────
    # Scheduler Setup
    # ──────────────────────────────────────────────

    def _setup_schedule(self):
        post_day    = self.config.get("post_day_of_week", "tuesday")
        post_hour   = self.config.get("post_hour", 9)
        post_minute = self.config.get("post_minute", 0)
        interval    = self.config.get("engagement_interval_minutes", 30)

        self.scheduler.add_job(
            self.job_post_content,
            CronTrigger(day_of_week=post_day, hour=post_hour, minute=post_minute),
            id              = "weekly_post",
            name            = f"Weekly Post ({post_day.capitalize()} {post_hour:02d}:{post_minute:02d})",
            max_instances   = 1,      # Prevent overlapping runs
            replace_existing= True,
        )
        logger.info("[Agent] 📅 Post scheduled: %s at %02d:%02d",
                    post_day.capitalize(), post_hour, post_minute)

        self.scheduler.add_job(
            self.job_engagement,
            IntervalTrigger(minutes=interval),
            id              = "engagement",
            name            = f"Engagement scan (every {interval} min)",
            max_instances   = 1,      # Prevent overlapping runs
            replace_existing= True,
        )
        logger.info("[Agent] 🔄 Engagement scan: every %d minutes", interval)

    # ──────────────────────────────────────────────
    # Start / Stop
    # ──────────────────────────────────────────────

    async def start(self):
        """Start the agent: launch browser, start scheduler, run forever."""
        logger.info("=" * 60)
        logger.info("  🤖  LinkedIn AI Agent — Starting Up")
        logger.info("  Author: Satyam Agarwal | AI/Data Engineering Architect")
        logger.info("=" * 60)

        if self.config.get("dry_run"):
            logger.info("[Agent] ⚠️  DRY RUN mode — no posts or replies will be sent.")

        logger.info("[Agent] 🌐 Starting browser session...")
        await self.browser.start()

        self._setup_schedule()
        self.scheduler.start()
        self._running = True

        logger.info("[Agent] ✅ Agent is live! Watching LinkedIn for you...")
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            logger.info("  - %s: next run %s", job.name,
                        next_run.strftime("%Y-%m-%d %H:%M") if next_run else "N/A")

        # Graceful shutdown on SIGINT / SIGTERM
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self.stop())
            )

        try:
            while self._running:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error("[Agent] Unexpected error in main loop: %s", e, exc_info=True)
        finally:
            if self._running:
                await self.stop()

    async def stop(self):
        """Gracefully shut down the agent."""
        logger.info("[Agent] 🛑 Shutting down...")
        self._running = False
        self.scheduler.shutdown(wait=False)
        await self.browser.stop()
        logger.info("[Agent] 👋 Agent stopped.")

    # ──────────────────────────────────────────────
    # Manual Triggers
    # ──────────────────────────────────────────────

    async def post_now(self, topic: Optional[str] = None):
        """Manually trigger a post immediately."""
        await self.browser.start()
        await self.job_post_content(custom_topic=topic)
        await self.browser.stop()

    async def engage_now(self):
        """Manually trigger one engagement cycle."""
        await self.browser.start()
        await self.job_engagement()
        await self.browser.stop()
