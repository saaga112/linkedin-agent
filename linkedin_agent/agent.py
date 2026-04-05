"""
LinkedIn Agent — Main Orchestrator
Ties together: content generation, posting, comment monitoring, and auto-replies.
Runs on a schedule: posts weekly, checks for replies every 30 minutes.
"""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .linkedin_client import LinkedInClient
from .content_generator import ContentGenerator
from .browser_monitor import LinkedInBrowserMonitor
from .reply_engine import ReplyEngine


POSTS_LOG_FILE = Path("posts_log.json")


class LinkedInAgent:
    """
    The main LinkedIn AI Agent.

    Responsibilities:
    1. Post weekly AI/Data Engineering content (configurable day/time)
    2. Every N minutes, scan for new comments and reply automatically
    3. Every N minutes, scan for new DMs and reply automatically
    4. Log all activity
    """

    def __init__(self, config: dict):
        self.config = config
        self._posts_log = self._load_posts_log()

        # Initialize components
        self.linkedin = LinkedInClient(
            client_id=config["linkedin_client_id"],
            client_secret=config["linkedin_client_secret"],
            access_token=config.get("linkedin_access_token"),
        )

        self.content_gen = ContentGenerator(
            api_key=config["anthropic_api_key"],
            model=config.get("claude_model", "claude-opus-4-6"),
        )

        self.browser = LinkedInBrowserMonitor(
            email=config["linkedin_email"],
            password=config["linkedin_password"],
            headless=config.get("headless_browser", True),
            session_dir=config.get("data_dir", "."),
        )

        self.reply_engine = ReplyEngine(
            content_generator=self.content_gen,
            browser_monitor=self.browser,
            state_dir=config.get("data_dir", "."),
            dry_run=config.get("dry_run", False),
        )

        self.scheduler = AsyncIOScheduler()
        self._running = False

    # ──────────────────────────────────────────────
    # Posts Log
    # ──────────────────────────────────────────────

    def _load_posts_log(self) -> list:
        log_path = Path(self.config.get("data_dir", ".")) / "posts_log.json"
        if log_path.exists():
            with open(log_path) as f:
                return json.load(f)
        return []

    def _save_post_log(self, post_text: str, post_id: str):
        entry = {
            "post_id": post_id,
            "post_text": post_text,
            "post_url": f"https://www.linkedin.com/feed/update/{post_id}/",
            "timestamp": datetime.now().isoformat(),
        }
        self._posts_log.append(entry)
        # Keep last 100 posts
        self._posts_log = self._posts_log[-100:]
        log_path = Path(self.config.get("data_dir", ".")) / "posts_log.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(self._posts_log, f, indent=2)

    def get_recent_posts(self, n: int = 5) -> list:
        """Return the N most recent posts for context when replying to comments."""
        return self._posts_log[-n:]

    # ──────────────────────────────────────────────
    # Core Jobs
    # ──────────────────────────────────────────────

    async def job_post_content(self, custom_topic: Optional[str] = None):
        """
        Scheduled job: generate and publish a LinkedIn post.
        Called weekly (or manually).
        """
        print(f"\n{'='*60}")
        print(f"[Agent] 📝 POST JOB triggered at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")

        try:
            post_text = self.content_gen.generate_weekly_post(custom_topic=custom_topic)
            print(f"\n[Agent] 📋 Generated post preview:\n{post_text[:200]}...\n")

            if self.config.get("dry_run", False):
                print("[Agent] 🔍 DRY RUN — Post not published.")
                return

            # Try official API first
            if self.config.get("linkedin_access_token"):
                try:
                    result = self.linkedin.create_post(post_text)
                    post_id = result.get("post_id", "unknown")
                    self._save_post_log(post_text, post_id)
                    print(f"[Agent] ✅ Post published via API. ID: {post_id}")
                    return
                except Exception as e:
                    print(f"[Agent] ⚠️  API post failed: {e}. Falling back to browser...")

            # Fallback: browser automation
            success = await self.browser.create_post_via_browser(post_text)
            if success:
                self._save_post_log(post_text, f"browser_{datetime.now().strftime('%Y%m%d%H%M%S')}")

        except Exception as e:
            print(f"[Agent] ❌ Post job failed: {e}")

    async def job_engagement(self):
        """
        Scheduled job: check for new comments and messages, then reply.
        Called every 30 minutes.
        """
        print(f"\n[Agent] 🔄 ENGAGEMENT JOB triggered at {datetime.now().strftime('%H:%M')}")
        recent_posts = self.get_recent_posts(n=10)
        try:
            summary = await self.reply_engine.run_engagement_cycle(recent_posts)
            print(f"[Agent] 📊 Engagement summary: {summary}")
        except Exception as e:
            print(f"[Agent] ❌ Engagement job failed: {e}")

    # ──────────────────────────────────────────────
    # Scheduler Setup
    # ──────────────────────────────────────────────

    def _setup_schedule(self):
        """Configure the scheduler based on config."""
        # Weekly post job
        post_day = self.config.get("post_day_of_week", "tuesday")  # default: Tuesday
        post_hour = self.config.get("post_hour", 9)                  # default: 9 AM
        post_minute = self.config.get("post_minute", 0)

        self.scheduler.add_job(
            self.job_post_content,
            CronTrigger(day_of_week=post_day, hour=post_hour, minute=post_minute),
            id="weekly_post",
            name=f"Weekly LinkedIn Post ({post_day.capitalize()} {post_hour:02d}:{post_minute:02d})",
            replace_existing=True,
        )
        print(f"[Agent] 📅 Post scheduled: Every {post_day.capitalize()} at {post_hour:02d}:{post_minute:02d}")

        # Engagement job (every N minutes)
        engagement_interval = self.config.get("engagement_interval_minutes", 30)
        self.scheduler.add_job(
            self.job_engagement,
            IntervalTrigger(minutes=engagement_interval),
            id="engagement",
            name=f"Auto-Reply Scan (every {engagement_interval} min)",
            replace_existing=True,
        )
        print(f"[Agent] 🔄 Engagement scan scheduled: every {engagement_interval} minutes")

    # ──────────────────────────────────────────────
    # Start / Stop
    # ──────────────────────────────────────────────

    async def start(self):
        """Start the agent: launch browser session and begin scheduler."""
        print("\n" + "="*60)
        print("  🤖 LinkedIn AI Agent — Starting Up")
        print("  Author: Satyam Agarwal | AI/Data Engineering Architect")
        print("="*60)

        if self.config.get("dry_run"):
            print("[Agent] ⚠️  Running in DRY RUN mode — no posts or replies will be sent.")

        print("[Agent] 🌐 Starting browser session...")
        await self.browser.start()

        self._setup_schedule()
        self.scheduler.start()
        self._running = True

        print("\n[Agent] ✅ Agent is live! Watching LinkedIn for you...")
        print(f"[Agent] 📋 Next jobs scheduled:")
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            print(f"         - {job.name}: next run at {next_run.strftime('%Y-%m-%d %H:%M') if next_run else 'N/A'}")
        print()

        # Handle graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self):
        """Gracefully stop the agent."""
        print("\n[Agent] 🛑 Shutting down...")
        self._running = False
        self.scheduler.shutdown(wait=False)
        await self.browser.stop()
        print("[Agent] 👋 Agent stopped. Goodbye!")

    # ──────────────────────────────────────────────
    # Manual Triggers (CLI commands)
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
