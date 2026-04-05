"""
Configuration Loader
Reads settings from environment variables (via .env file).
All required keys are validated on startup.
"""

import os
from pathlib import Path

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


def load_config() -> dict:
    """
    Load and validate configuration from environment variables.
    Returns a config dict used by the agent.
    """
    missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
    if missing:
        print("❌ Missing required environment variables:")
        for k in missing:
            print(f"   - {k}")
        print("\nPlease copy .env.example to .env and fill in your credentials.")
        raise SystemExit(1)

    return {
        # ── Anthropic / Claude ──────────────────────
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        "claude_model": os.getenv("CLAUDE_MODEL", "claude-opus-4-6"),

        # ── LinkedIn Credentials ─────────────────────
        "linkedin_email": os.environ["LINKEDIN_EMAIL"],
        "linkedin_password": os.environ["LINKEDIN_PASSWORD"],
        "linkedin_client_id": os.environ["LINKEDIN_CLIENT_ID"],
        "linkedin_client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
        "linkedin_access_token": os.getenv("LINKEDIN_ACCESS_TOKEN", ""),  # optional until OAuth done

        # ── Posting Schedule ─────────────────────────
        # Day of week for weekly post: monday, tuesday, wednesday, thursday, friday
        "post_day_of_week": os.getenv("POST_DAY_OF_WEEK", "tuesday"),
        # Hour (24h) and minute for the weekly post (in local time)
        "post_hour": int(os.getenv("POST_HOUR", "9")),
        "post_minute": int(os.getenv("POST_MINUTE", "0")),

        # ── Engagement Settings ──────────────────────
        # How often (minutes) to scan for new comments and messages
        "engagement_interval_minutes": int(os.getenv("ENGAGEMENT_INTERVAL_MINUTES", "30")),

        # ── Browser Settings ─────────────────────────
        # Set to "true" to run browser in headless mode (no visible window)
        # Set to "false" for first-time login (to handle 2FA manually)
        "headless_browser": os.getenv("HEADLESS_BROWSER", "false").lower() == "true",

        # ── Data / State Directory ───────────────────
        "data_dir": os.getenv("DATA_DIR", "./data"),

        # ── Safety / Testing ─────────────────────────
        # Set to "true" to generate content but NOT post/reply (testing mode)
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
    }
