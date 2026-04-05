"""
Configuration Loader
Reads settings from environment variables (via .env file).
All required keys are validated on startup.

Improvements:
- Added LINKEDIN_REFRESH_TOKEN support (was: missing, token refresh couldn't persist)
- Bounds validation on POST_HOUR (0-23) and POST_MINUTE (0-59)
- Bounds validation on ENGAGEMENT_INTERVAL_MINUTES (1-1440)
- Proper logging instead of print statements
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional; env vars can be set directly


REQUIRED_KEYS = [
    "ANTHROPIC_API_KEY",
    "LINKEDIN_EMAIL",
    "LINKEDIN_PASSWORD",
    "LINKEDIN_CLIENT_ID",
    "LINKEDIN_CLIENT_SECRET",
]

VALID_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def load_config() -> dict:
    """
    Load and validate configuration from environment variables.
    Returns a config dict used by the agent.
    Raises SystemExit(1) on missing required keys or invalid values.
    """
    missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
    if missing:
        logger.error("❌ Missing required environment variables: %s", ", ".join(missing))
        logger.error("Please copy .env.example to .env and fill in your credentials.")
        raise SystemExit(1)

    # ── Parse and validate schedule settings ────────────────────────────────
    post_day = os.getenv("POST_DAY_OF_WEEK", "tuesday").lower().strip()
    if post_day not in VALID_DAYS:
        raise ValueError(
            f"POST_DAY_OF_WEEK must be one of: {', '.join(sorted(VALID_DAYS))}. Got: '{post_day}'"
        )

    try:
        post_hour = int(os.getenv("POST_HOUR", "9"))
    except ValueError:
        raise ValueError("POST_HOUR must be an integer (0–23).")
    if not (0 <= post_hour <= 23):
        raise ValueError(f"POST_HOUR must be between 0 and 23. Got: {post_hour}")

    try:
        post_minute = int(os.getenv("POST_MINUTE", "0"))
    except ValueError:
        raise ValueError("POST_MINUTE must be an integer (0–59).")
    if not (0 <= post_minute <= 59):
        raise ValueError(f"POST_MINUTE must be between 0 and 59. Got: {post_minute}")

    try:
        engagement_interval = int(os.getenv("ENGAGEMENT_INTERVAL_MINUTES", "30"))
    except ValueError:
        raise ValueError("ENGAGEMENT_INTERVAL_MINUTES must be an integer (1–1440).")
    if not (1 <= engagement_interval <= 1440):
        raise ValueError(
            f"ENGAGEMENT_INTERVAL_MINUTES must be between 1 and 1440. Got: {engagement_interval}"
        )

    return {
        # ── Anthropic / Claude ──────────────────────
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        "claude_model": os.getenv("CLAUDE_MODEL", "claude-opus-4-6"),

        # ── LinkedIn Credentials ─────────────────────
        "linkedin_email":        os.environ["LINKEDIN_EMAIL"],
        "linkedin_password":     os.environ["LINKEDIN_PASSWORD"],
        "linkedin_client_id":    os.environ["LINKEDIN_CLIENT_ID"],
        "linkedin_client_secret":os.environ["LINKEDIN_CLIENT_SECRET"],
        # Access token — optional until OAuth setup is complete
        "linkedin_access_token": os.getenv("LINKEDIN_ACCESS_TOKEN", ""),
        # Refresh token — used to auto-renew access tokens before expiry
        "linkedin_refresh_token": os.getenv("LINKEDIN_REFRESH_TOKEN", ""),

        # ── Posting Schedule ─────────────────────────
        "post_day_of_week": post_day,
        "post_hour":        post_hour,
        "post_minute":      post_minute,

        # ── Engagement Settings ──────────────────────
        "engagement_interval_minutes": engagement_interval,

        # ── Browser Settings ─────────────────────────
        # Set HEADLESS_BROWSER=false for first-time login (to handle 2FA manually)
        "headless_browser": os.getenv("HEADLESS_BROWSER", "false").lower() == "true",

        # ── Data / State Directory ───────────────────
        "data_dir": os.getenv("DATA_DIR", "./data"),

        # ── Safety / Testing ─────────────────────────
        # Set DRY_RUN=true to generate content but NOT post/reply (testing mode)
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
    }
