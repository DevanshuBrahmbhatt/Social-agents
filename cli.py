#!/usr/bin/env python3
"""CLI entry point — backward compatible with v1. Run the full pipeline once."""

import sys
import logging

from core.news_fetcher import fetch_all_stories, deep_research_story
from core.tweet_generator import pick_best_story, generate_tweet
from core.chart_generator import generate_chart
from core.twitter_poster import post_tweet, post_tweet_dry_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run_pipeline(dry_run: bool = False, recent_titles: list[str] = None) -> dict | None:
    """Execute the full pipeline: fetch → pick → research → generate → chart → post.

    Args:
        dry_run: If True, don't actually post to Twitter.
        recent_titles: Titles of recently posted tweets to avoid repeating topics.

    Returns the result dict or None on failure.
    """
    # Step 1: Fetch stories from all sources
    log.info("📰 Fetching tech stories...")
    stories = fetch_all_stories()
    log.info(f"Fetched {len(stories)} stories")

    if not stories:
        log.error("No stories found. Exiting.")
        return None

    # Step 2: Claude picks the best story (avoiding recent topics)
    log.info("🧠 Picking best story with Claude...")
    story = pick_best_story(stories, recent_titles=recent_titles)
    log.info(f"Selected: {story['title']}")

    # Step 3: Deep research with Perplexity
    log.info("🔍 Deep researching with Perplexity...")
    research = deep_research_story(story)

    # Step 4: Generate long-form post with deep context
    log.info("✍️  Generating long-form post...")
    result = generate_tweet(story, research)
    log.info(f"Post ({len(result['tweet'])} chars):\n{result['tweet']}")

    # Step 5: Generate chart (always mandatory)
    log.info("📊 Generating chart...")
    chart_path = generate_chart(result.get("chart_data", {"should_chart": True}))
    if chart_path:
        log.info(f"Chart saved: {chart_path}")
    else:
        log.warning("Chart generation failed — posting without image")

    # Step 6: Post
    if dry_run:
        post_tweet_dry_run(result["tweet"], chart_path)
        log.info("[DRY RUN] Pipeline complete.")
    else:
        log.info("🚀 Posting to Twitter/X...")
        response = post_tweet(result["tweet"], chart_path)
        log.info(f"Done! Tweet ID: {response.data['id']}")

    result["chart_path"] = chart_path
    return result


def main():
    dry_run = "--dry-run" in sys.argv
    result = run_pipeline(dry_run=dry_run)
    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
