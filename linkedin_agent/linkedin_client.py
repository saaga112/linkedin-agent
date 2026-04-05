"""
LinkedIn API Client
Handles OAuth authentication and all LinkedIn API interactions.
Uses the official LinkedIn REST API for posting content.
"""

import os
import json
import time
import requests
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode


class LinkedInClient:
    """
    Official LinkedIn API client for posting content and fetching profile data.
    Scopes required: openid, profile, email, w_member_social
    """

    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    API_BASE = "https://api.linkedin.com/v2"

    def __init__(self, client_id: str, client_secret: str, access_token: str = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self._profile_urn = None

    # ──────────────────────────────────────────────
    # OAuth Helpers
    # ──────────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str, scopes: list = None) -> str:
        """Generate the OAuth authorization URL for first-time setup."""
        if scopes is None:
            scopes = ["openid", "profile", "email", "w_member_social"]
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": "linkedin_agent_" + str(int(time.time())),
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange an OAuth code for an access token."""
        response = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        token_data = response.json()
        self.access_token = token_data["access_token"]
        return token_data

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ──────────────────────────────────────────────
    # Profile
    # ──────────────────────────────────────────────

    def get_profile(self) -> dict:
        """Fetch the authenticated user's LinkedIn profile."""
        url = f"{self.API_BASE}/userinfo"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()

    def get_profile_urn(self) -> str:
        """Return the user's URN (e.g. urn:li:person:XXXX), cached after first call."""
        if not self._profile_urn:
            profile = self.get_profile()
            self._profile_urn = f"urn:li:person:{profile['sub']}"
        return self._profile_urn

    # ──────────────────────────────────────────────
    # Posting
    # ──────────────────────────────────────────────

    def create_post(self, text: str, visibility: str = "PUBLIC") -> dict:
        """
        Create a text post on LinkedIn.
        visibility: 'PUBLIC' or 'CONNECTIONS'
        Returns the API response dict with the post ID.
        """
        author_urn = self.get_profile_urn()
        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": visibility
            },
        }
        url = f"{self.API_BASE}/ugcPosts"
        response = requests.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        post_id = response.headers.get("x-restli-id", "unknown")
        print(f"[LinkedIn] ✅ Post published. ID: {post_id}")
        return {"post_id": post_id, "response": response.json() if response.text else {}}

    def create_post_with_article(self, text: str, article_url: str, title: str = "", description: str = "") -> dict:
        """Create a post with a linked article."""
        author_urn = self.get_profile_urn()
        media = {
            "status": "READY",
            "originalUrl": article_url,
        }
        if title:
            media["title"] = {"text": title}
        if description:
            media["description"] = {"text": description}

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "ARTICLE",
                    "media": [media],
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        url = f"{self.API_BASE}/ugcPosts"
        response = requests.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        post_id = response.headers.get("x-restli-id", "unknown")
        print(f"[LinkedIn] ✅ Article post published. ID: {post_id}")
        return {"post_id": post_id}

    # ──────────────────────────────────────────────
    # Comments (read via API — requires approval for most)
    # ──────────────────────────────────────────────

    def get_post_comments(self, post_urn: str) -> list:
        """
        Fetch comments on a specific post.
        Note: Full comment access requires LinkedIn Partner approval.
        This works for posts made by the authenticated user.
        """
        encoded_urn = requests.utils.quote(post_urn, safe="")
        url = f"{self.API_BASE}/socialActions/{encoded_urn}/comments"
        response = requests.get(url, headers=self._headers())
        if response.status_code == 200:
            return response.json().get("elements", [])
        else:
            print(f"[LinkedIn] ⚠️ Could not fetch comments via API (status {response.status_code}). Using browser monitor instead.")
            return []

    def reply_to_comment(self, post_urn: str, comment_urn: str, reply_text: str) -> dict:
        """Reply to a comment on a post."""
        author_urn = self.get_profile_urn()
        encoded_post_urn = requests.utils.quote(post_urn, safe="")
        url = f"{self.API_BASE}/socialActions/{encoded_post_urn}/comments"
        payload = {
            "actor": author_urn,
            "message": {"text": reply_text},
            "parentComment": comment_urn,
        }
        response = requests.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        print(f"[LinkedIn] ✅ Reply posted to comment {comment_urn}")
        return response.json()

    def like_post(self, post_urn: str) -> bool:
        """Like a post."""
        author_urn = self.get_profile_urn()
        encoded_urn = requests.utils.quote(post_urn, safe="")
        url = f"{self.API_BASE}/socialActions/{encoded_urn}/likes"
        payload = {"actor": author_urn}
        response = requests.post(url, headers=self._headers(), json=payload)
        return response.status_code in (200, 201)
