import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HackerNews
# ---------------------------------------------------------------------------

def _fetch_hn_item(item_id: int) -> dict | None:
    try:
        resp = requests.get(config.HN_ITEM_URL.format(item_id), timeout=10)
        resp.raise_for_status()
        item = resp.json()
        if item and item.get("type") == "story" and item.get("score", 0) >= config.MIN_HN_SCORE:
            return {
                "source": "hackernews",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "score": item.get("score", 0),
                "summary": None,
            }
    except Exception as e:
        log.debug(f"Failed to fetch HN item {item_id}: {e}")
    return None


def fetch_hn_stories(limit: int = None) -> list[dict]:
    limit = limit or config.MAX_HN_STORIES
    try:
        resp = requests.get(config.HN_TOP_STORIES_URL, timeout=10)
        resp.raise_for_status()
        story_ids = resp.json()[:limit]
    except Exception as e:
        log.warning(f"Failed to fetch HN top stories: {e}")
        return []

    stories = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_hn_item, sid): sid for sid in story_ids}
        for future in as_completed(futures):
            result = future.result()
            if result:
                stories.append(result)

    log.info(f"Fetched {len(stories)} HackerNews stories (score >= {config.MIN_HN_SCORE})")
    return stories


# ---------------------------------------------------------------------------
# TechCrunch RSS (multiple categories)
# ---------------------------------------------------------------------------

def fetch_techcrunch_stories() -> list[dict]:
    stories = []
    for feed_name, feed_url in config.TC_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                summary = entry.get("summary", "")
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]
                stories.append({
                    "source": f"techcrunch-{feed_name}",
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "score": None,
                    "summary": summary or None,
                })
            log.info(f"Fetched {min(len(feed.entries), 10)} TechCrunch {feed_name} stories")
        except Exception as e:
            log.warning(f"Failed to fetch TechCrunch {feed_name} feed: {e}")
    return stories


# ---------------------------------------------------------------------------
# Reddit (public JSON API — no auth required)
# ---------------------------------------------------------------------------

def fetch_reddit_stories() -> list[dict]:
    """Fetch hot posts from tech subreddits via Reddit's public JSON API."""
    stories = []
    headers = {"User-Agent": config.REDDIT_USER_AGENT}

    for subreddit in config.REDDIT_SUBREDDITS:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={config.MAX_REDDIT_POSTS}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("data", {}).get("children", []):
                p = post.get("data", {})

                # Skip: low score, stickied, self-posts without real URLs
                if p.get("score", 0) < config.MIN_REDDIT_SCORE:
                    continue
                if p.get("stickied"):
                    continue

                post_url = p.get("url", "")
                # Skip self-posts (they link to reddit itself)
                if post_url.startswith(f"https://www.reddit.com/r/{subreddit}"):
                    continue

                stories.append({
                    "source": f"reddit-r/{subreddit}",
                    "title": p.get("title", ""),
                    "url": post_url,
                    "score": p.get("score", 0),
                    "summary": (p.get("selftext") or "")[:300] or None,
                })

            log.info(f"Fetched {len([s for s in stories if f'r/{subreddit}' in s['source']])} Reddit r/{subreddit} stories")
        except Exception as e:
            log.warning(f"Failed to fetch Reddit r/{subreddit}: {e}")

    return stories


# ---------------------------------------------------------------------------
# Business Wire (Technology RSS)
# ---------------------------------------------------------------------------

def fetch_businesswire_stories() -> list[dict]:
    """Fetch tech press releases from Business Wire RSS."""
    stories = []
    try:
        feed = feedparser.parse(config.BW_TECH_RSS)
        for entry in feed.entries[:15]:
            summary = entry.get("summary", "")
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]
            stories.append({
                "source": "businesswire",
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "score": None,
                "summary": summary or None,
            })
        log.info(f"Fetched {len(stories)} Business Wire stories")
    except Exception as e:
        log.warning(f"Failed to fetch Business Wire feed: {e}")
    return stories


# ---------------------------------------------------------------------------
# Perplexity Deep Research
# ---------------------------------------------------------------------------

def deep_research_story(story: dict, api_key: str = None) -> str:
    """Use Perplexity Sonar to deeply research a story for builders and founders.

    Returns a rich text analysis with market context, data points, and insights.
    """
    api_key = api_key or config.PERPLEXITY_API_KEY
    if not api_key:
        log.warning("No Perplexity API key — skipping deep research")
        return story.get("summary") or story.get("title", "")

    try:
        from openai import OpenAI

        pplx = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")

        query = f"""Provide a deep analysis of this tech news story for builders, founders, and investors:

Title: {story['title']}
URL: {story.get('url', 'N/A')}
Summary: {story.get('summary', 'N/A')}
Source: {story.get('source', 'N/A')}

Include ALL of the following if available:
1. Key numbers: funding amounts, valuations, revenue, growth rates, user counts, market size
2. Context: company background, previous rounds, competitive landscape
3. Market impact: what this means for the industry, who benefits, who loses
4. Builder angle: what products/tools/services could be built because of this
5. Technical details: what technology is involved, what it enables
6. Regulatory/policy implications if relevant
7. Timeline: when did this happen, what's the trajectory
8. Comparable events: similar moves by competitors, historical parallels

Be specific with numbers and data points. This analysis will be used to write an insightful long-form post for builders and startup founders."""

        response = pplx.chat.completions.create(
            model=config.PERPLEXITY_MODEL,
            messages=[{"role": "user", "content": query}],
        )

        research = response.choices[0].message.content
        log.info(f"Deep research complete ({len(research)} chars)")
        return research

    except Exception as e:
        log.warning(f"Perplexity research failed: {e}")
        return story.get("summary") or story.get("title", "")


# ---------------------------------------------------------------------------
# Combined Fetch — All Sources
# ---------------------------------------------------------------------------

def fetch_all_stories() -> list[dict]:
    """Fetch stories from ALL sources and deduplicate by URL."""
    hn_stories = fetch_hn_stories()
    tc_stories = fetch_techcrunch_stories()
    reddit_stories = fetch_reddit_stories()
    bw_stories = fetch_businesswire_stories()

    all_stories = hn_stories + tc_stories + reddit_stories + bw_stories

    seen_urls = set()
    unique_stories = []
    for story in all_stories:
        url = story.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_stories.append(story)
        elif not url:
            unique_stories.append(story)

    source_counts = {}
    for s in unique_stories:
        src = s["source"].split("-")[0]
        source_counts[src] = source_counts.get(src, 0) + 1

    log.info(f"Total unique stories: {len(unique_stories)} — {source_counts}")
    return unique_stories
