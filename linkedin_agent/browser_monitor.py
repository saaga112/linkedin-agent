"""
LinkedIn Browser Monitor (Playwright-based)
Monitors LinkedIn notifications, comments, and messages using browser automation.
This is needed because the LinkedIn API does not expose comment/message reading
without special Partner Program approval.

IMPORTANT: Run this with a real browser session (non-headless recommended for
first login so you can complete any CAPTCHA/2FA).
"""

import os
import json
import time
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[BrowserMonitor] ⚠️  Playwright not installed. Run: pip install playwright && playwright install chromium")


class LinkedInBrowserMonitor:
    """
    Uses Playwright to log into LinkedIn and monitor:
    - New comments on posts
    - New direct messages
    - Notifications
    Then posts replies via the browser as well.
    """

    LOGIN_URL = "https://www.linkedin.com/login"
    FEED_URL = "https://www.linkedin.com/feed/"
    NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"
    MESSAGING_URL = "https://www.linkedin.com/messaging/"
    SESSION_FILE = Path("linkedin_session.json")

    def __init__(self, email: str, password: str, headless: bool = False, session_dir: str = "."):
        self.email = email
        self.password = password
        self.headless = headless
        self.session_file = Path(session_dir) / "linkedin_session.json"
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._context = None

    # ──────────────────────────────────────────────
    # Browser Lifecycle
    # ──────────────────────────────────────────────

    async def start(self):
        """Start the Playwright browser and restore session if available."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not installed.")

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        # Try to restore saved session
        if self.session_file.exists():
            print("[BrowserMonitor] 🔄 Restoring saved session...")
            with open(self.session_file) as f:
                storage_state = json.load(f)
            self._context = await self._browser.new_context(
                storage_state=storage_state,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
        else:
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )

        self._page = await self._context.new_page()
        await self._ensure_logged_in()

    async def stop(self):
        """Close the browser and save the session."""
        if self._context:
            await self._save_session()
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright"):
            await self._playwright.stop()
        print("[BrowserMonitor] 🛑 Browser stopped.")

    async def _save_session(self):
        """Save browser cookies/storage for next run."""
        state = await self._context.storage_state()
        with open(self.session_file, "w") as f:
            json.dump(state, f)
        print("[BrowserMonitor] 💾 Session saved.")

    # ──────────────────────────────────────────────
    # Login
    # ──────────────────────────────────────────────

    async def _ensure_logged_in(self):
        """Check if logged in; if not, perform login."""
        await self._page.goto(self.FEED_URL, wait_until="networkidle")
        if "feed" in self._page.url:
            print("[BrowserMonitor] ✅ Already logged in.")
            return

        print("[BrowserMonitor] 🔐 Logging in...")
        await self._page.goto(self.LOGIN_URL)
        await self._page.fill("#username", self.email)
        await self._page.fill("#password", self.password)
        await self._page.click('[data-litms-control-urn="login-submit"]')
        await self._page.wait_for_url("**/feed/**", timeout=30000)

        if "checkpoint" in self._page.url or "challenge" in self._page.url:
            print("[BrowserMonitor] ⚠️  2FA/CAPTCHA required. Please complete it manually in the browser window.")
            input("Press ENTER after completing 2FA/CAPTCHA...")

        await self._save_session()
        print("[BrowserMonitor] ✅ Login successful.")

    # ──────────────────────────────────────────────
    # Notification Monitoring
    # ──────────────────────────────────────────────

    async def get_new_notifications(self) -> List[Dict]:
        """
        Scrape the notifications page for new comment notifications.
        Returns a list of notification dicts: {type, actor, post_url, text, element}
        """
        await self._page.goto(self.NOTIFICATIONS_URL, wait_until="networkidle")
        await asyncio.sleep(2)

        notifications = []
        try:
            items = await self._page.query_selector_all(".nt-card-list__item")
            for item in items[:20]:  # Check latest 20
                text_el = await item.query_selector(".nt-card__text")
                text = await text_el.inner_text() if text_el else ""

                link_el = await item.query_selector("a")
                link = await link_el.get_attribute("href") if link_el else ""

                # Filter for comment notifications
                if any(kw in text.lower() for kw in ["commented", "replied", "mentioned"]):
                    notifications.append({
                        "type": "comment",
                        "text": text.strip(),
                        "url": "https://www.linkedin.com" + link if link and link.startswith("/") else link,
                        "raw_element": item,
                    })
        except Exception as e:
            print(f"[BrowserMonitor] ⚠️  Error scraping notifications: {e}")

        print(f"[BrowserMonitor] 📬 Found {len(notifications)} new comment notifications.")
        return notifications

    # ──────────────────────────────────────────────
    # Comment Scraping & Replying
    # ──────────────────────────────────────────────

    async def get_comments_on_post(self, post_url: str) -> List[Dict]:
        """
        Navigate to a post and extract comments.
        Returns list of {commenter_name, comment_text, comment_element}
        """
        await self._page.goto(post_url, wait_until="networkidle")
        await asyncio.sleep(3)

        # Expand comments if needed
        try:
            load_more = await self._page.query_selector("button.comments-comments-list__load-more-comments-button")
            if load_more:
                await load_more.click()
                await asyncio.sleep(2)
        except Exception:
            pass

        comments = []
        try:
            comment_els = await self._page.query_selector_all(".comments-comment-item")
            for el in comment_els:
                name_el = await el.query_selector(".comments-post-meta__name-text")
                text_el = await el.query_selector(".comments-comment-item__main-content")
                name = await name_el.inner_text() if name_el else "Unknown"
                text = await text_el.inner_text() if text_el else ""
                if text.strip():
                    comments.append({
                        "commenter_name": name.strip(),
                        "comment_text": text.strip(),
                        "element": el,
                    })
        except Exception as e:
            print(f"[BrowserMonitor] ⚠️  Error scraping comments: {e}")

        print(f"[BrowserMonitor] 💬 Found {len(comments)} comments on post.")
        return comments

    async def reply_to_comment_in_browser(self, comment_element, reply_text: str) -> bool:
        """
        Click the Reply button on a comment and type the reply.
        Returns True if successful.
        """
        try:
            reply_btn = await comment_element.query_selector("button.comments-comment-social-bar__reply-action-button")
            if not reply_btn:
                print("[BrowserMonitor] ⚠️  Reply button not found.")
                return False
            await reply_btn.click()
            await asyncio.sleep(1)

            # Find the reply input that appeared
            reply_box = await self._page.query_selector(".ql-editor[contenteditable='true']")
            if not reply_box:
                return False

            await reply_box.click()
            await reply_box.type(reply_text, delay=30)
            await asyncio.sleep(0.5)

            # Submit
            submit_btn = await self._page.query_selector("button.comments-comment-box__submit-button")
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(1)
                print(f"[BrowserMonitor] ✅ Reply posted: '{reply_text[:60]}...'")
                return True
        except Exception as e:
            print(f"[BrowserMonitor] ❌ Error replying to comment: {e}")
        return False

    # ──────────────────────────────────────────────
    # DM Monitoring & Replying
    # ──────────────────────────────────────────────

    async def get_unread_messages(self) -> List[Dict]:
        """
        Scrape the messaging inbox for unread conversations.
        Returns list of {sender_name, last_message, conversation_url}
        """
        await self._page.goto(self.MESSAGING_URL, wait_until="networkidle")
        await asyncio.sleep(3)

        conversations = []
        try:
            conv_els = await self._page.query_selector_all(".msg-conversation-listitem__link")
            for el in conv_els[:10]:  # Check latest 10
                # Check for unread badge
                badge = await el.query_selector(".notification-badge")
                if not badge:
                    continue  # Skip read conversations

                name_el = await el.query_selector(".msg-conversation-listitem__participant-names")
                preview_el = await el.query_selector(".msg-conversation-card__message-snippet-body")
                href = await el.get_attribute("href")

                name = await name_el.inner_text() if name_el else "Unknown"
                preview = await preview_el.inner_text() if preview_el else ""

                conversations.append({
                    "sender_name": name.strip(),
                    "last_message": preview.strip(),
                    "url": "https://www.linkedin.com" + href if href else "",
                    "element": el,
                })
        except Exception as e:
            print(f"[BrowserMonitor] ⚠️  Error scraping messages: {e}")

        print(f"[BrowserMonitor] 📨 Found {len(conversations)} unread conversations.")
        return conversations

    async def get_conversation_history(self, conversation_url: str) -> List[Dict]:
        """Navigate to a conversation and extract message history."""
        await self._page.goto(conversation_url, wait_until="networkidle")
        await asyncio.sleep(2)

        messages = []
        try:
            msg_els = await self._page.query_selector_all(".msg-s-message-list__event")
            for el in msg_els[-8:]:  # Last 8 messages for context
                sender_el = await el.query_selector(".msg-s-message-group__name")
                body_el = await el.query_selector(".msg-s-event-listitem__body")
                sender = await sender_el.inner_text() if sender_el else "Me"
                body = await body_el.inner_text() if body_el else ""
                messages.append({"role": sender.strip(), "text": body.strip()})
        except Exception as e:
            print(f"[BrowserMonitor] ⚠️  Error reading conversation: {e}")

        return messages

    async def send_message_reply(self, reply_text: str) -> bool:
        """
        Send a reply in the currently open conversation.
        Must be called after navigating to a conversation.
        """
        try:
            msg_input = await self._page.query_selector(".msg-form__contenteditable")
            if not msg_input:
                return False
            await msg_input.click()
            await msg_input.type(reply_text, delay=25)
            await asyncio.sleep(0.5)

            send_btn = await self._page.query_selector("button.msg-form__send-button")
            if send_btn:
                await send_btn.click()
                await asyncio.sleep(1)
                print(f"[BrowserMonitor] ✅ DM sent: '{reply_text[:60]}...'")
                return True
        except Exception as e:
            print(f"[BrowserMonitor] ❌ Error sending message: {e}")
        return False

    # ──────────────────────────────────────────────
    # Post via Browser (fallback)
    # ──────────────────────────────────────────────

    async def create_post_via_browser(self, post_text: str) -> bool:
        """
        Create a LinkedIn post via browser automation.
        Use this as a fallback if the API token is expired.
        """
        await self._page.goto(self.FEED_URL, wait_until="networkidle")
        await asyncio.sleep(2)
        try:
            # Open the post creation modal
            start_post = await self._page.query_selector("button.share-box-feed-entry__trigger")
            if not start_post:
                start_post = await self._page.query_selector("[data-control-name='share.sharebox_open']")
            if not start_post:
                print("[BrowserMonitor] ❌ Could not find 'Start a post' button.")
                return False
            await start_post.click()
            await asyncio.sleep(1)

            post_box = await self._page.query_selector(".ql-editor[contenteditable='true']")
            if not post_box:
                return False
            await post_box.click()
            await post_box.type(post_text, delay=15)
            await asyncio.sleep(0.5)

            post_btn = await self._page.query_selector("button.share-actions__primary-action")
            if post_btn:
                await post_btn.click()
                await asyncio.sleep(2)
                print("[BrowserMonitor] ✅ Post created via browser.")
                return True
        except Exception as e:
            print(f"[BrowserMonitor] ❌ Error creating post: {e}")
        return False
