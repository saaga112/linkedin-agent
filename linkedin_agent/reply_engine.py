"""
Auto-Reply Engine
Orchestrates reading new comments/messages and posting AI-generated replies.
Tracks which items have already been replied to using a local state file.

Improvements:
- Hash-based comment deduplication (was: weak first-50-chars key)
- Message dedup by sender+message hash (was: sender name only — missed 2nd message)
- File locking to prevent concurrent write corruption
- JSON schema validation on load (was: could crash on malformed files)
- Proper logging throughout
"""

import json
import hashlib
import asyncio
import logging
import fcntl
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from .content_generator import ContentGenerator
from .browser_monitor import LinkedInBrowserMonitor

logger = logging.getLogger(__name__)


class ReplyEngine:
    """
    Manages automatic replies to LinkedIn comments and direct messages.
    """

    def __init__(self, content_generator: ContentGenerator,
                 browser_monitor: LinkedInBrowserMonitor,
                 state_dir: str = ".", dry_run: bool = False):
        self.gen        = content_generator
        self.monitor    = browser_monitor
        self.state_file = Path(state_dir) / "replied_items.json"
        self.dry_run    = dry_run
        self._state     = self._load_state()

    # ──────────────────────────────────────────────
    # State Management
    # ──────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Load dedup state with schema validation and error recovery."""
        if not self.state_file.exists():
            return {"replied_comments": [], "replied_messages": [], "last_run": None}

        try:
            with open(self.state_file) as f:
                data = json.load(f)
            # Validate schema
            if not isinstance(data, dict):
                raise ValueError("State file is not a JSON object.")
            if not isinstance(data.get("replied_comments", []), list):
                raise ValueError("replied_comments is not a list.")
            if not isinstance(data.get("replied_messages", []), list):
                raise ValueError("replied_messages is not a list.")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[ReplyEngine] ⚠️  Corrupted state file (%s). Starting fresh.", e)
            # Back up the corrupt file before overwriting
            backup = self.state_file.with_suffix(
                f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
            )
            try:
                self.state_file.rename(backup)
                logger.info("[ReplyEngine] Backed up corrupt state to %s", backup)
            except Exception:
                pass
            return {"replied_comments": [], "replied_messages": [], "last_run": None}

    def _save_state(self):
        """Save dedup state with exclusive file lock to prevent concurrent corruption."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(self._state, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            # Atomic replace
            tmp_path.replace(self.state_file)
        except Exception as e:
            logger.error("[ReplyEngine] ❌ Failed to save state: %s", e, exc_info=True)
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _comment_key(post_url: str, commenter_name: str, comment_text: str) -> str:
        """
        Stable, collision-resistant dedup key for a comment.
        Hashes the full comment text so edits produce a different key.
        """
        text_hash = hashlib.sha256(comment_text.encode()).hexdigest()[:16]
        return f"{post_url}::{commenter_name}::{text_hash}"

    @staticmethod
    def _message_key(sender_name: str, message_text: str) -> str:
        """
        Dedup key for a DM — includes message hash so a second message from
        the same sender is NOT skipped.
        """
        text_hash = hashlib.sha256(message_text.encode()).hexdigest()[:16]
        return f"{sender_name}::{text_hash}"

    def _already_replied_comment(self, key: str) -> bool:
        return key in self._state["replied_comments"]

    def _mark_comment_replied(self, key: str):
        self._state["replied_comments"].append(key)
        self._state["replied_comments"] = self._state["replied_comments"][-500:]
        self._save_state()

    def _already_replied_message(self, key: str) -> bool:
        return key in self._state["replied_messages"]

    def _mark_message_replied(self, key: str):
        if key not in self._state["replied_messages"]:
            self._state["replied_messages"].append(key)
            self._state["replied_messages"] = self._state["replied_messages"][-200:]
            self._save_state()

    # ──────────────────────────────────────────────
    # Comment Reply Cycle
    # ──────────────────────────────────────────────

    async def process_comment_notifications(self, recent_posts: List[Dict]) -> int:
        """
        Check for new comments on recent posts and reply to each one.
        Returns the number of replies posted.
        """
        replied_count = 0
        notifications = await self.monitor.get_new_notifications()
        visited_posts: set = set()

        for notif in notifications:
            post_url = notif.get("url", "")
            if not post_url or post_url in visited_posts:
                continue
            visited_posts.add(post_url)

            # Find post text for context
            post_text = next(
                (p["post_text"] for p in recent_posts
                 if p.get("post_url") == post_url),
                "AI and Data Engineering insights",
            )

            comments = await self.monitor.get_comments_on_post(post_url)
            for comment in comments:
                comment_key = self._comment_key(
                    post_url,
                    comment["commenter_name"],
                    comment["comment_text"],
                )
                if self._already_replied_comment(comment_key):
                    continue

                classification = self.gen.classify_comment(comment["comment_text"])
                logger.info("[ReplyEngine] 💬 Comment from %s [%s]: %s...",
                            comment["commenter_name"], classification,
                            comment["comment_text"][:80])

                if classification == "spam":
                    logger.info("[ReplyEngine] 🚫 Skipping spam comment.")
                    self._mark_comment_replied(comment_key)
                    continue

                try:
                    reply_text = self.gen.generate_comment_reply(
                        original_post=post_text,
                        commenter_name=comment["commenter_name"],
                        comment_text=comment["comment_text"],
                    )
                except Exception as e:
                    logger.error("[ReplyEngine] ❌ Failed to generate reply: %s", e, exc_info=True)
                    continue

                if self.dry_run:
                    logger.info("[ReplyEngine] 🔍 DRY RUN — Would reply: '%s'", reply_text)
                    self._mark_comment_replied(comment_key)
                else:
                    success = await self.monitor.reply_to_comment_in_browser(
                        comment["element"], reply_text
                    )
                    if success:
                        replied_count += 1
                        self._mark_comment_replied(comment_key)
                        await asyncio.sleep(2)  # Gentle rate limiting

        logger.info("[ReplyEngine] ✅ Comment cycle done. Replied: %d", replied_count)
        return replied_count

    # ──────────────────────────────────────────────
    # DM Reply Cycle
    # ──────────────────────────────────────────────

    async def process_direct_messages(self) -> int:
        """
        Check the inbox for unread messages and auto-reply.
        Returns the number of replies sent.
        """
        replied_count = 0
        unread = await self.monitor.get_unread_messages()

        for convo in unread:
            sender          = convo["sender_name"]
            history         = await self.monitor.get_conversation_history(convo["url"])
            incoming_message = convo["last_message"]

            # Find the actual last incoming message in history
            for msg in reversed(history):
                role = msg.get("role", "").lower()
                if "me" not in role and "satyam" not in role:
                    incoming_message = msg["text"]
                    break

            message_key = self._message_key(sender, incoming_message)
            if self._already_replied_message(message_key):
                logger.info("[ReplyEngine] Already replied to this message from %s, skipping.", sender)
                continue

            logger.info("[ReplyEngine] 📨 Message from %s: '%s...'",
                        sender, incoming_message[:80])

            try:
                reply_text = self.gen.generate_message_reply(
                    sender_name=sender,
                    message_text=incoming_message,
                    conversation_history=history,
                )
            except Exception as e:
                logger.error("[ReplyEngine] ❌ Failed to generate DM reply: %s", e, exc_info=True)
                continue

            if self.dry_run:
                logger.info("[ReplyEngine] 🔍 DRY RUN — Would send: '%s'", reply_text)
                self._mark_message_replied(message_key)
            else:
                success = await self.monitor.send_message_reply(reply_text)
                if success:
                    replied_count += 1
                    self._mark_message_replied(message_key)
                    await asyncio.sleep(3)

        logger.info("[ReplyEngine] ✅ DM cycle done. Replied: %d", replied_count)
        return replied_count

    # ──────────────────────────────────────────────
    # Full Engagement Cycle
    # ──────────────────────────────────────────────

    async def run_engagement_cycle(self, recent_posts: List[Dict]) -> Dict:
        """Run a full engagement cycle: comments + messages."""
        logger.info("[ReplyEngine] 🔄 Starting engagement cycle at %s",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        comment_replies = await self.process_comment_notifications(recent_posts)
        message_replies = await self.process_direct_messages()
        self._state["last_run"] = datetime.now().isoformat()
        self._save_state()
        summary = {
            "timestamp":       datetime.now().isoformat(),
            "comment_replies": comment_replies,
            "message_replies": message_replies,
        }
        logger.info("[ReplyEngine] 📊 Cycle summary: %s", summary)
        return summary
