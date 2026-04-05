"""
LinkedIn API Client
Handles OAuth authentication and all LinkedIn API interactions.
Uses the official LinkedIn REST API for posting content.

Improvements:
- Token expiry tracking + automatic refresh before expiry
- Retry with exponential backoff on rate-limits and transient errors
- Post/comment length validation (LinkedIn limits)
- Proper logging instead of print statements
"""

import json
import time
import logging
import requests
from urllib.parse import urlencode
from typing import Optional

logger = logging.getLogger(__name__)

_TOKEN_REFRESH_BUFFER_SECS = 300   # Refresh 5 min before expiry
_MAX_POST_CHARS            = 3000  # LinkedIn post character limit
_MAX_COMMENT_CHARS         = 1250  # LinkedIn comment character limit


def _with_retry(fn, max_attempts: int = 3, base_delay: float = 2.0):
    """Exponential-backoff retry for transient API failures and rate limits."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 429:
                retry_after = int(e.response.headers.get("Retry-After", base_delay * (2 ** attempt)))
                logger.warning("[LinkedInClient] Rate-limited. Waiting %ss (attempt %d/%d)",
                               retry_after, attempt + 1, max_attempts)
                time.sleep(retry_after)
            elif status in (500, 502, 503, 504) and attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("[LinkedInClient] Server error %s. Retrying in %ss (attempt %d/%d)",
                               status, delay, attempt + 1, max_attempts)
                time.sleep(delay)
            else:
                raise
        except requests.ConnectionError as e:
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("[LinkedInClient] Connection error: %s. Retrying in %ss", e, delay)
                time.sleep(delay)
            else:
                raise
    return None


class LinkedInClient:
    """
    Official LinkedIn API client.
    Scopes required: openid, profile, email, w_member_social
    """

    AUTH_URL  = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    API_BASE  = "https://api.linkedin.com/v2"

    def __init__(self, client_id: str, client_secret: str,
                 access_token: str = None, refresh_token: str = None,
                 token_expires_at: float = 0.0):
        self.client_id        = client_id
        self.client_secret    = client_secret
        self.access_token     = access_token
        self.refresh_token    = refresh_token
        # Default to 60 days from now if not supplied
        self.token_expires_at = token_expires_at or (time.time() + 5_256_000)
        self._profile_urn: Optional[str] = None

    # ──────────────────────────────────────────────
    # OAuth
    # ──────────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str, scopes: list = None) -> str:
        if scopes is None:
            scopes = ["openid", "profile", "email", "w_member_social"]
        params = {
            "response_type": "code",
            "client_id":     self.client_id,
            "redirect_uri":  redirect_uri,
            "scope":         " ".join(scopes),
            "state":         f"linkedin_agent_{int(time.time())}",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange auth code for access + refresh tokens."""
        response = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        token_data = response.json()
        self._store_token(token_data)
        return token_data

    def _store_token(self, token_data: dict):
        """Save token fields from an API response."""
        self.access_token     = token_data["access_token"]
        self.refresh_token    = token_data.get("refresh_token", self.refresh_token)
        expires_in            = token_data.get("expires_in", 5_256_000)
        self.token_expires_at = time.time() + expires_in
        logger.info("[LinkedInClient] Token stored. Expires in %.1f days.", expires_in / 86400)

    def _ensure_token_valid(self):
        """Proactively refresh the access token before it expires."""
        if time.time() < self.token_expires_at - _TOKEN_REFRESH_BUFFER_SECS:
            return  # Token is still valid
        if not self.refresh_token:
            logger.warning("[LinkedInClient] ⚠️  Token expired and no refresh token stored. "
                           "Re-run `python main.py --setup` to re-authenticate.")
            return
        logger.info("[LinkedInClient] 🔄 Refreshing access token...")
        try:
            r = requests.post(
                self.TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id":     self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            r.raise_for_status()
            self._store_token(r.json())
            logger.info("[LinkedInClient] ✅ Token refreshed successfully.")
        except Exception as e:
            logger.error("[LinkedInClient] ❌ Token refresh failed: %s", e, exc_info=True)

    def _headers(self) -> dict:
        self._ensure_token_valid()
        return {
            "Authorization":             f"Bearer {self.access_token}",
            "Content-Type":              "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ──────────────────────────────────────────────
    # Profile
    # ──────────────────────────────────────────────

    def get_profile(self) -> dict:
        def _call():
            r = requests.get(f"{self.API_BASE}/userinfo", headers=self._headers())
            r.raise_for_status()
            return r.json()
        return _with_retry(_call)

    def get_profile_urn(self) -> str:
        if not self._profile_urn:
            profile = self.get_profile()
            self._profile_urn = f"urn:li:person:{profile['sub']}"
        return self._profile_urn

    # ──────────────────────────────────────────────
    # Posting
    # ──────────────────────────────────────────────

    def create_post(self, text: str, visibility: str = "PUBLIC") -> dict:
        """Publish a text post. Truncates if over LinkedIn's 3000-char limit."""
        if len(text) > _MAX_POST_CHARS:
            logger.warning("[LinkedInClient] ⚠️  Post truncated from %d → %d chars.",
                           len(text), _MAX_POST_CHARS)
            text = text[:_MAX_POST_CHARS - 3] + "..."

        author_urn = self.get_profile_urn()
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary":    {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }

        def _call():
            r = requests.post(f"{self.API_BASE}/ugcPosts",
                              headers=self._headers(), json=payload)
            r.raise_for_status()
            return r

        response = _with_retry(_call)
        post_id  = response.headers.get("x-restli-id", "unknown")
        post_url = (f"https://www.linkedin.com/feed/update/{post_id}/"
                    if post_id != "unknown" else None)
        logger.info("[LinkedInClient] ✅ Post published. ID: %s", post_id)
        return {"post_id": post_id, "post_url": post_url}

    def create_post_with_article(self, text: str, article_url: str,
                                 title: str = "", description: str = "") -> dict:
        """Publish a post linking to an article."""
        if len(text) > _MAX_POST_CHARS:
            text = text[:_MAX_POST_CHARS - 3] + "..."

        author_urn = self.get_profile_urn()
        media: dict = {"status": "READY", "originalUrl": article_url}
        if title:       media["title"]       = {"text": title}
        if description: media["description"] = {"text": description}

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary":    {"text": text},
                    "shareMediaCategory": "ARTICLE",
                    "media":              [media],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        def _call():
            r = requests.post(f"{self.API_BASE}/ugcPosts",
                              headers=self._headers(), json=payload)
            r.raise_for_status()
            return r

        response = _with_retry(_call)
        post_id  = response.headers.get("x-restli-id", "unknown")
        logger.info("[LinkedInClient] ✅ Article post published. ID: %s", post_id)
        return {"post_id": post_id, "post_url": None}

    # ──────────────────────────────────────────────
    # Comments
    # ──────────────────────────────────────────────

    def get_post_comments(self, post_urn: str) -> list:
        """Fetch comments. Full access requires LinkedIn Partner Program approval."""
        encoded = requests.utils.quote(post_urn, safe="")
        def _call():
            r = requests.get(f"{self.API_BASE}/socialActions/{encoded}/comments",
                             headers=self._headers())
            r.raise_for_status()
            return r.json().get("elements", [])
        try:
            return _with_retry(_call)
        except requests.HTTPError as e:
            logger.warning("[LinkedInClient] ⚠️  Comment API unavailable (%s). "
                           "Using browser monitor.", e.response.status_code)
            return []

    def reply_to_comment(self, post_urn: str, comment_urn: str, reply_text: str) -> dict:
        """Post a reply to a comment."""
        if len(reply_text) > _MAX_COMMENT_CHARS:
            reply_text = reply_text[:_MAX_COMMENT_CHARS - 3] + "..."

        author_urn = self.get_profile_urn()
        encoded    = requests.utils.quote(post_urn, safe="")
        payload    = {
            "actor":         author_urn,
            "message":       {"text": reply_text},
            "parentComment": comment_urn,
        }

        def _call():
            r = requests.post(f"{self.API_BASE}/socialActions/{encoded}/comments",
                              headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

        result = _with_retry(_call)
        logger.info("[LinkedInClient] ✅ Reply posted to comment %s", comment_urn)
        return result

    def like_post(self, post_urn: str) -> bool:
        """Like a post."""
        author_urn = self.get_profile_urn()
        encoded    = requests.utils.quote(post_urn, safe="")
        try:
            def _call():
                r = requests.post(f"{self.API_BASE}/socialActions/{encoded}/likes",
                                  headers=self._headers(), json={"actor": author_urn})
                return r.status_code in (200, 201)
            return _with_retry(_call)
        except Exception as e:
            logger.warning("[LinkedInClient] Could not like post: %s", e)
            return False
