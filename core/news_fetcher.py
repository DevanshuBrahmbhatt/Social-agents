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
# TechCrunch RSS
# ---------------------------------------------------------------------------

def fetch_techcrunch_stories() -> list[dict]:
    stories = []
    feeds = [
        ("venture", config.TC_FUNDING_RSS),
        ("startups", config.TC_STARTUPS_RSS),
    ]
    for feed_name, feed_url in feeds:
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
# Perplexity Deep Research
# ---------------------------------------------------------------------------

def deep_research_story(story: dict, api_key: str = None) -> str:
    """Use Perplexity Sonar to deeply research a story for founder/investor context.

    Returns a rich text analysis with funding details, market context, data points.
    """
    api_key = api_key or config.PERPLEXITY_API_KEY
    if not api_key:
        log.warning("No Perplexity API key — skipping deep research")
        return story.get("summary") or story.get("title", "")

    try:
        from openai import OpenAI

        pplx = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")

        query = f"""Provide a deep analysis of this tech news story for startup founders and VCs:

Title: {story['title']}
URL: {story.get('url', 'N/A')}
Summary: {story.get('summary', 'N/A')}

Include ALL of the following if available:
1. Exact funding amount, valuation, lead investors, round type
2. Company's previous funding history and valuation trajectory
3. Revenue, growth rate, user count, or other key metrics
4. Total addressable market (TAM) size and growth rate
5. Key competitors and how this company differentiates
6. Why this matters for the broader startup ecosystem
7. What signal this sends to founders and investors
8. Any notable data points, percentages, or dollar figures

Be specific with numbers. This analysis will be used to write an insightful tweet."""

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
# Combined Fetch
# ---------------------------------------------------------------------------

def fetch_all_stories() -> list[dict]:
    """Fetch stories from all sources and deduplicate by URL."""
    hn_stories = fetch_hn_stories()
    tc_stories = fetch_techcrunch_stories()
    all_stories = hn_stories + tc_stories

    seen_urls = set()
    unique_stories = []
    for story in all_stories:
        url = story.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_stories.append(story)
        elif not url:
            unique_stories.append(story)

    log.info(f"Total unique stories: {len(unique_stories)}")
    return unique_stories
