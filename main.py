#!/usr/bin/env python3
"""
LinkedIn AI Agent — Entry Point
Usage:
  python main.py                     # Start the full agent (post + engage on schedule)
  python main.py --post-now          # Immediately generate & publish a post
  python main.py --post-now "topic"  # Immediately post on a specific topic
  python main.py --engage-now        # Immediately run one comment/message reply cycle
  python main.py --dry-run           # Run in dry-run mode (no actual posts/replies)
  python main.py --setup             # Run the OAuth setup wizard
"""

import asyncio
import argparse
import sys
from config import load_config
from linkedin_agent import LinkedInAgent


def parse_args():
    parser = argparse.ArgumentParser(
        description="LinkedIn AI Agent for Satyam Agarwal — Auto-posts and replies on LinkedIn."
    )
    parser.add_argument(
        "--post-now",
        nargs="?",
        const=True,
        metavar="TOPIC",
        help="Immediately post content. Optionally provide a topic.",
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
        help="Run the LinkedIn OAuth setup wizard.",
    )
    return parser.parse_args()


async def run_setup(config):
    """Interactive OAuth setup wizard."""
    from linkedin_agent.linkedin_client import LinkedInClient
    client = LinkedInClient(
        client_id=config["linkedin_client_id"],
        client_secret=config["linkedin_client_secret"],
    )
    redirect_uri = input("Enter your redirect URI (e.g. http://localhost:8080/callback): ").strip()
    auth_url = client.get_auth_url(redirect_uri)
    print(f"\n🔗 Open this URL in your browser to authorize the app:\n\n{auth_url}\n")
    code = input("Paste the 'code' parameter from the redirect URL: ").strip()
    token_data = client.exchange_code_for_token(code, redirect_uri)
    print(f"\n✅ Access token obtained! Expires in {token_data.get('expires_in', '?')} seconds.")
    print(f"\nAdd this to your .env file:\nLINKEDIN_ACCESS_TOKEN={token_data['access_token']}\n")


async def main():
    args = parse_args()
    config = load_config()

    if args.dry_run:
        config["dry_run"] = True
        print("⚠️  DRY RUN mode enabled — no posts or replies will be sent.\n")

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
