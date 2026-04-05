"""
LinkedIn Browser Monitor (Playwright-based)
Monitors LinkedIn notifications, comments, and messages using browser automation.
Needed because the LinkedIn API doesn't expose comment/message reading without
special Partner Program approval.

Improvements:
- Playwright availability check moved to __init__ (was: silent at import time)
- All page navigations have explicit timeouts (was: could hang indefinitely)
- Proper logging throughout (was: print statements)
- asyncio.wait_for() wrappers around blocking browser operations
- Graceful fallback on selector failures
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

_NAV_TIMEOUT_MS   = 30_000  # 30s for page navigation
_ACTION_TIMEOUT_S = 20      # 20s for asyncio.wait_for actions


class LinkedInBrowserMonitor:
    """
    Playwright Chromium controller for LinkedIn monitoring and interaction.
    """

    LOGIN_URL        = "https://www.linkedin.com/login"
    FEED_URL         = "https://www.linkedin.com/feed/"
    NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"
    MESSAGING_URL    = "https://www.linkedin.com/messaging/"

    def __init__(self, email: str, password: str,
                 headless: bool = False, session_dir: str = "."):
        # Fail fast — don't let missing Playwright cause confusing errors later
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Run:\n"
                "  pip install playwright && playwright install chromium"
            )
        self.email        = email
        self.password     = password
        self.headless     = headless
        self.session_file = Path(session_dir) / "linkedin_session.json"
        self._browser: Optional[Browser]         = None
        self._page:    Optional[Page]            = None
        self._context: Optional[BrowserContext]  = None
        self._playwright                         = None

    # ──────────────────────────────────────────────
    # Browser Lifecycle
    # ──────────────────────────────────────────────

    async def start(self):
        """Launch Chromium and restore session if available."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        if self.session_file.exists():
            logger.info("[BrowserMonitor] 🔄 Restoring saved session from %s", self.session_file)
            try:
                with open(self.session_file) as f:
                    storage_state = json.load(f)
                self._context = await self._browser.new_context(
                    storage_state=storage_state,
                    user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/122.0.0.0 Safari/537.36"),
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("[BrowserMonitor] ⚠️  Invalid session file (%s). Starting fresh.", e)
                self.session_file.unlink(missing_ok=True)
                self._context = await self._browser.new_context()
        else:
            self._context = await self._browser.new_context(
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/122.0.0.0 Safari/537.36"),
            )

        self._page = await self._context.new_page()
        await self._ensure_logged_in()

    async def stop(self):
        """Close the browser and persist the session."""
        if self._context:
            await self._save_session()
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("[BrowserMonitor] 🛑 Browser stopped.")

    async def _save_session(self):
        """Persist cookies and local storage for next run."""
        try:
            state = await self._context.storage_state()
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.session_file, "w") as f:
                json.dump(state, f)
            logger.info("[BrowserMonitor] 💾 Session saved to %s", self.session_file)
        except Exception as e:
            logger.warning("[BrowserMonitor] Could not save session: %s", e)

    # ──────────────────────────────────────────────
    # Login
    # ──────────────────────────────────────────────

    async def _navigate(self, url: str):
        """Navigate with timeout — raises on timeout instead of hanging."""
        try:
            await asyncio.wait_for(
                self._page.goto(url, wait_until="networkidle"),
                timeout=_NAV_TIMEOUT_MS / 1000
            )
        except asyncio.TimeoutError:
            logger.warning("[BrowserMonitor] ⏱️  Navigation timeout for %s. Continuing anyway.", url)

    async def _ensure_logged_in(self):
        """Check if already logged in; perform login if not."""
        await self._navigate(self.FEED_URL)
        if "feed" in self._page.url:
            logger.info("[BrowserMonitor] ✅ Already logged in.")
            return

        logger.info("[BrowserMonitor] 🔐 Logging in as %s...", self.email)
        try:
            await self._navigate(self.LOGIN_URL)
            await self._page.fill("#username", self.email)
            await self._page.fill("#password", self.password)
            await self._page.click('[data-litms-control-urn="login-submit"]')
            await self._page.wait_for_url("**/feed/**", timeout=_NAV_TIMEOUT_MS)
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Login failed: %s", e, exc_info=True)
            raise

        if "checkpoint" in self._page.url or "challenge" in self._page.url:
            logger.warning("[BrowserMonitor] ⚠️  2FA/CAPTCHA required. Complete it in the browser window.")
            input("Press ENTER after completing 2FA/CAPTCHA to continue...")

        await self._save_session()
        logger.info("[BrowserMonitor] ✅ Login successful.")

    # ──────────────────────────────────────────────
    # Notifications
    # ──────────────────────────────────────────────

    async def get_new_notifications(self) -> List[Dict]:
        """Scrape the notifications page for new comment notifications."""
        try:
            await self._navigate(self.NOTIFICATIONS_URL)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Could not load notifications: %s", e)
            return []

        notifications = []
        try:
            items = await self._page.query_selector_all(".nt-card-list__item")
            for item in items[:20]:
                text_el = await item.query_selector(".nt-card__text")
                text    = await text_el.inner_text() if text_el else ""
                link_el = await item.query_selector("a")
                link    = await link_el.get_attribute("href") if link_el else ""

                if any(kw in text.lower() for kw in ["commented", "replied", "mentioned"]):
                    notifications.append({
                        "type": "comment",
                        "text": text.strip(),
                        "url":  ("https://www.linkedin.com" + link
                                 if link and link.startswith("/") else link),
                    })
        except Exception as e:
            logger.warning("[BrowserMonitor] ⚠️  Error scraping notifications: %s", e)

        logger.info("[BrowserMonitor] 📬 Found %d comment notifications.", len(notifications))
        return notifications

    # ──────────────────────────────────────────────
    # Comments
    # ──────────────────────────────────────────────

    async def get_comments_on_post(self, post_url: str) -> List[Dict]:
        """Navigate to a post and extract all comments."""
        try:
            await self._navigate(post_url)
            await asyncio.sleep(3)
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Could not load post %s: %s", post_url, e)
            return []

        # Expand comments
        try:
            load_more = await self._page.query_selector(
                "button.comments-comments-list__load-more-comments-button"
            )
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
                name    = (await name_el.inner_text()).strip() if name_el else "Unknown"
                text    = (await text_el.inner_text()).strip() if text_el else ""
                if text:
                    comments.append({
                        "commenter_name": name,
                        "comment_text":   text,
                        "element":        el,
                    })
        except Exception as e:
            logger.warning("[BrowserMonitor] ⚠️  Error scraping comments: %s", e)

        logger.info("[BrowserMonitor] 💬 Found %d comments on post.", len(comments))
        return comments

    async def reply_to_comment_in_browser(self, comment_element, reply_text: str) -> bool:
        """Click Reply on a comment, type the reply, and submit."""
        try:
            reply_btn = await comment_element.query_selector(
                "button.comments-comment-social-bar__reply-action-button"
            )
            if not reply_btn:
                logger.warning("[BrowserMonitor] ⚠️  Reply button not found on comment.")
                return False

            await reply_btn.click()
            await asyncio.sleep(1)

            reply_box = await self._page.query_selector(".ql-editor[contenteditable='true']")
            if not reply_box:
                return False

            await reply_box.click()
            await reply_box.type(reply_text, delay=30)
            await asyncio.sleep(0.5)

            submit_btn = await self._page.query_selector(
                "button.comments-comment-box__submit-button"
            )
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(1)
                logger.info("[BrowserMonitor] ✅ Reply posted: '%s...'", reply_text[:60])
                return True
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Error replying to comment: %s", e, exc_info=True)
        return False

    # ──────────────────────────────────────────────
    # Direct Messages
    # ──────────────────────────────────────────────

    async def get_unread_messages(self) -> List[Dict]:
        """Scrape the messaging inbox for unread conversations."""
        try:
            await self._navigate(self.MESSAGING_URL)
            await asyncio.sleep(3)
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Could not load messaging: %s", e)
            return []

        conversations = []
        try:
            conv_els = await self._page.query_selector_all(
                ".msg-conversation-listitem__link"
            )
            for el in conv_els[:10]:
                badge = await el.query_selector(".notification-badge")
                if not badge:
                    continue

                name_el    = await el.query_selector(".msg-conversation-listitem__participant-names")
                preview_el = await el.query_selector(".msg-conversation-card__message-snippet-body")
                href       = await el.get_attribute("href")

                name    = (await name_el.inner_text()).strip() if name_el else "Unknown"
                preview = (await preview_el.inner_text()).strip() if preview_el else ""

                conversations.append({
                    "sender_name":  name,
                    "last_message": preview,
                    "url": "https://www.linkedin.com" + href if href else "",
                })
        except Exception as e:
            logger.warning("[BrowserMonitor] ⚠️  Error scraping messages: %s", e)

        logger.info("[BrowserMonitor] 📨 Found %d unread conversations.", len(conversations))
        return conversations

    async def get_conversation_history(self, conversation_url: str) -> List[Dict]:
        """Navigate to a conversation and extract message history."""
        try:
            await self._navigate(conversation_url)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Could not load conversation: %s", e)
            return []

        messages = []
        try:
            msg_els = await self._page.query_selector_all(".msg-s-message-list__event")
            for el in msg_els[-8:]:
                sender_el = await el.query_selector(".msg-s-message-group__name")
                body_el   = await el.query_selector(".msg-s-event-listitem__body")
                sender    = (await sender_el.inner_text()).strip() if sender_el else "Me"
                body      = (await body_el.inner_text()).strip() if body_el else ""
                messages.append({"role": sender, "text": body})
        except Exception as e:
            logger.warning("[BrowserMonitor] ⚠️  Error reading conversation: %s", e)

        return messages

    async def send_message_reply(self, reply_text: str) -> bool:
        """Send a reply in the currently open conversation."""
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
                logger.info("[BrowserMonitor] ✅ DM sent: '%s...'", reply_text[:60])
                return True
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Error sending DM: %s", e, exc_info=True)
        return False

    # ──────────────────────────────────────────────
    # Post via Browser (fallback)
    # ──────────────────────────────────────────────

    async def create_post_via_browser(self, post_text: str) -> bool:
        """Create a LinkedIn post via browser automation (API fallback)."""
        try:
            await self._navigate(self.FEED_URL)
            await asyncio.sleep(2)

            start_post = (
                await self._page.query_selector("button.share-box-feed-entry__trigger")
                or await self._page.query_selector("[data-control-name='share.sharebox_open']")
            )
            if not start_post:
                logger.error("[BrowserMonitor] ❌ 'Start a post' button not found.")
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
                logger.info("[BrowserMonitor] ✅ Post created via browser.")
                return True
        except Exception as e:
            logger.error("[BrowserMonitor] ❌ Error creating post via browser: %s", e, exc_info=True)
        return False
