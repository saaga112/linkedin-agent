#!/usr/bin/env python3
"""
LinkedIn AI Agent — Entry Point
Usage:
  python main.py                          # Start the full agent (post + engage on schedule)
  python main.py --post-now               # Immediately generate & publish a post
  python main.py --post-now "topic"       # Immediately post on a specific topic
  python main.py --engage-now             # Immediately run one comment/message reply cycle
  python main.py --dry-run                # Run in dry-run mode (no actual posts/replies)
  python main.py --setup                  # Run the OAuth setup wizard
  python main.py --engagement-interval 15 # Override engagement scan interval (minutes)

Improvements:
- Added --engagement-interval CLI flag (was: only configurable via env var)
- OAuth setup redirect_uri defaults to localhost:8080 (no longer prompted interactively)
- Raw access token is NOT printed to stdout (write to .env file only)
- Proper logging setup with configurable log level
"""

import asyncio
import argparse
import logging
import sys
from config import load_config
from linkedin_agent import LinkedInAgent


def setup_logging(level: str = "INFO"):
    """Configure structured logging for the entire application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="LinkedIn AI Agent for Satyam Agarwal — Auto-posts and replies on LinkedIn.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          Start full scheduled agent
  python main.py --post-now               Post immediately using next topic
  python main.py --post-now "RAG vs fine-tuning"  Post on a custom topic
  python main.py --engage-now             Run one reply cycle immediately
  python main.py --dry-run                Test mode — no actual posts/replies
  python main.py --setup                  Authenticate with LinkedIn API
  python main.py --engagement-interval 15 Scan for replies every 15 minutes
        """,
    )
    parser.add_argument(
        "--post-now",
        nargs="?",
        const=True,
        metavar="TOPIC",
        help="Immediately post content. Optionally provide a custom topic string.",
    )
    parser.add_argument(
        "--engage-now",
        action="store_true",
        help="Immediately run one engagement cycle (comment + message replies).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate content but do NOT post or reply. Useful for testing.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the LinkedIn OAuth setup wizard to obtain API tokens.",
    )
    parser.add_argument(
        "--engagement-interval",
        type=int,
        metavar="MINUTES",
        default=None,
        help=(
            "Override the engagement scan interval in minutes (1–1440). "
            "Defaults to ENGAGEMENT_INTERVAL_MINUTES env var (or 30)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set the logging verbosity level (default: INFO).",
    )
    return parser.parse_args()


async def run_setup(config: dict):
    """
    Interactive OAuth setup wizard.
    Guides the user through LinkedIn API authorization and saves tokens to .env.
    The redirect URI defaults to localhost — no user input needed for standard setups.
    """
    from linkedin_agent.linkedin_client import LinkedInClient

    logger = logging.getLogger(__name__)

    # Default redirect URI — change only if you have a custom OAuth app callback
    redirect_uri = "http://localhost:8080/callback"

    client = LinkedInClient(
        client_id=config["linkedin_client_id"],
        client_secret=config["linkedin_client_secret"],
    )
    auth_url = client.get_auth_url(redirect_uri)

    print("\n" + "=" * 60)
    print("  LinkedIn OAuth Setup Wizard")
    print("=" * 60)
    print(f"\n1. Open this URL in your browser:\n\n   {auth_url}\n")
    print(f"2. Authorize the app. You'll be redirected to:\n   {redirect_uri}?code=...")
    print("\n3. Copy the 'code' value from the redirect URL.")
    print("=" * 60)

    code = input("\nPaste the authorization code here: ").strip()
    if not code:
        logger.error("No authorization code entered. Aborting setup.")
        raise SystemExit(1)

    try:
        token_data = client.exchange_code_for_token(code, redirect_uri)
    except Exception as e:
        logger.error("Failed to exchange code for token: %s", e)
        raise SystemExit(1)

    expires_in = token_data.get("expires_in", 0)
    expires_days = round(expires_in / 86400, 1)

    print(f"\n✅ Authorization successful! Token expires in {expires_days} days.")
    print("\nAdd the following lines to your .env file:\n")
    print(f"   LINKEDIN_ACCESS_TOKEN={token_data['access_token']}")
    if token_data.get("refresh_token"):
        print(f"   LINKEDIN_REFRESH_TOKEN={token_data['refresh_token']}")
    print("\n⚠️  Keep these tokens private — do not commit them to version control.\n")


async def main():
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    config = load_config()

    # CLI overrides for config values
    if args.dry_run:
        config["dry_run"] = True
        logger.warning("DRY RUN mode enabled — no posts or replies will be sent.")

    if args.engagement_interval is not None:
        if not (1 <= args.engagement_interval <= 1440):
            logger.error(
                "--engagement-interval must be between 1 and 1440 minutes. Got: %d",
                args.engagement_interval,
            )
            raise SystemExit(1)
        config["engagement_interval_minutes"] = args.engagement_interval
        logger.info("Engagement interval overridden to %d minutes.", args.engagement_interval)

    if args.setup:
        await run_setup(config)
        return

    agent = LinkedInAgent(config)

    if args.post_now is not None:
        topic = args.post_now if isinstance(args.post_now, str) else None
        await agent.post_now(topic=topic)

    elif args.engage_now:
        await agent.engage_now()

    else:
        # Full agent mode — runs indefinitely on schedule
        await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
