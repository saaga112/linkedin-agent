"""
Auto-Reply Engine
Orchestrates reading new comments/messages and posting AI-generated replies.
Tracks which items have already been replied to using a local state file.
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from .content_generator import ContentGenerator
from .browser_monitor import LinkedInBrowserMonitor


STATE_FILE = Path("replied_items.json")


class ReplyEngine:
    """
    Manages automatic replies to LinkedIn comments and direct messages.
    Keeps a persistent state file to avoid double-replying.
    """

    def __init__(
        self,
        content_generator: ContentGenerator,
        browser_monitor: LinkedInBrowserMonitor,
        state_dir: str = ".",
        dry_run: bool = False,
    ):
        self.gen = content_generator
        self.monitor = browser_monitor
        self.state_file = Path(state_dir) / "replied_items.json"
        self.dry_run = dry_run  # If True, generate replies but don't post them
        self._state = self._load_state()

    # ──────────────────────────────────────────────
    # State Management (Deduplication)
    # ──────────────────────────────────────────────

    def _load_state(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {"replied_comments": [], "replied_messages": [], "last_run": None}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self._state, f, indent=2)

    def _already_replied_comment(self, comment_key: str) -> bool:
        return comment_key in self._state["replied_comments"]

    def _mark_comment_replied(self, comment_key: str):
        self._state["replied_comments"].append(comment_key)
        # Keep only last 500 to prevent file bloat
        self._state["replied_comments"] = self._state["replied_comments"][-500:]
        self._save_state()

    def _already_replied_message(self, sender: str) -> bool:
        return sender in self._state["replied_messages"]

    def _mark_message_replied(self, sender: str):
        if sender not in self._state["replied_messages"]:
            self._state["replied_messages"].append(sender)
            self._state["replied_messages"] = self._state["replied_messages"][-200:]
            self._save_state()

    # ──────────────────────────────────────────────
    # Comment Reply Cycle
    # ──────────────────────────────────────────────

    async def process_comment_notifications(self, recent_posts: List[Dict]) -> int:
        """
        Check notifications for new comments on recent posts and reply to them.
        recent_posts: list of {post_url, post_text}
        Returns number of replies posted.
        """
        replied_count = 0

        # 1. Get notifications
        notifications = await self.monitor.get_new_notifications()

        # 2. For each comment notification, go to the post and reply
        visited_posts = set()
        for notif in notifications:
            post_url = notif.get("url", "")
            if not post_url or post_url in visited_posts:
                continue
            visited_posts.add(post_url)

            # Find the matching post text for context
            post_text = next(
                (p["post_text"] for p in recent_posts if p.get("post_url") == post_url),
                "AI and Data Engineering insights",
            )

            comments = await self.monitor.get_comments_on_post(post_url)
            for comment in comments:
                comment_key = f"{comment['commenter_name']}::{comment['comment_text'][:50]}"
                if self._already_replied_comment(comment_key):
                    continue

                # Classify the comment
                classification = self.gen.classify_comment(comment["comment_text"])
                print(f"[ReplyEngine] 💬 Comment from {comment['commenter_name']} [{classification}]: {comment['comment_text'][:80]}...")

                # Skip spam
                if classification == "spam":
                    print(f"[ReplyEngine] 🚫 Skipping spam comment.")
                    self._mark_comment_replied(comment_key)
                    continue

                # Generate reply
                reply_text = self.gen.generate_comment_reply(
                    original_post=post_text,
                    commenter_name=comment["commenter_name"],
                    comment_text=comment["comment_text"],
                )

                if self.dry_run:
                    print(f"[ReplyEngine] 🔍 DRY RUN — Would reply: '{reply_text}'")
                else:
                    success = await self.monitor.reply_to_comment_in_browser(
                        comment["element"], reply_text
                    )
                    if success:
                        replied_count += 1
                        self._mark_comment_replied(comment_key)
                        await asyncio.sleep(2)  # Be gentle on LinkedIn's rate limits

        print(f"[ReplyEngine] ✅ Comment cycle done. Replied to {replied_count} comments.")
        return replied_count

    # ──────────────────────────────────────────────
    # Direct Message Reply Cycle
    # ──────────────────────────────────────────────

    async def process_direct_messages(self) -> int:
        """
        Check the inbox for unread messages and auto-reply to them.
        Returns number of replies sent.
        """
        replied_count = 0
        unread = await self.monitor.get_unread_messages()

        for convo in unread:
            sender = convo["sender_name"]

            # Get full conversation history for context
            history = await self.monitor.get_conversation_history(convo["url"])

            # Use the last message in history as the incoming message
            incoming_message = convo["last_message"]
            if history:
                # Find the last message not from "Me"
                for msg in reversed(history):
                    if "me" not in msg["role"].lower() and "satyam" not in msg["role"].lower():
                        incoming_message = msg["text"]
                        break

            print(f"[ReplyEngine] 📨 Message from {sender}: '{incoming_message[:80]}...'")

            # Generate reply
            reply_text = self.gen.generate_message_reply(
                sender_name=sender,
                message_text=incoming_message,
                conversation_history=history,
            )

            if self.dry_run:
                print(f"[ReplyEngine] 🔍 DRY RUN — Would send: '{reply_text}'")
                self._mark_message_replied(sender)
            else:
                # Navigate to conversation and send reply
                await self.monitor.get_conversation_history(convo["url"])  # Already navigated
                success = await self.monitor.send_message_reply(reply_text)
                if success:
                    replied_count += 1
                    self._mark_message_replied(sender)
                    await asyncio.sleep(3)

        print(f"[ReplyEngine] ✅ Message cycle done. Replied to {replied_count} messages.")
        return replied_count

    # ──────────────────────────────────────────────
    # Full Engagement Cycle
    # ──────────────────────────────────────────────

    async def run_engagement_cycle(self, recent_posts: List[Dict]) -> Dict:
        """
        Run a full engagement cycle: process comments + messages.
        Returns a summary dict.
        """
        print(f"\n[ReplyEngine] 🔄 Starting engagement cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        comment_replies = await self.process_comment_notifications(recent_posts)
        message_replies = await self.process_direct_messages()
        self._state["last_run"] = datetime.now().isoformat()
        self._save_state()
        summary = {
            "timestamp": datetime.now().isoformat(),
            "comment_replies": comment_replies,
            "message_replies": message_replies,
        }
        print(f"[ReplyEngine] 📊 Cycle summary: {summary}")
        return summary
