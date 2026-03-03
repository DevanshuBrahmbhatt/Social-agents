#!/usr/bin/env python3
"""Social Agents MCP Server — expose posting tools for AI agents.

Standalone MCP server that wraps the Social Agents REST API.
Any MCP client (Claude Code, Claude Desktop, other agents) can use this
to post content to Twitter and LinkedIn.

Setup:
    pip install mcp httpx

Usage (stdio transport, for Claude Code / Claude Desktop):
    Add to your MCP config:
    {
        "mcpServers": {
            "social-agents": {
                "command": "python",
                "args": ["/path/to/Social-agents/mcp_server.py"],
                "env": {
                    "SOCIAL_AGENTS_URL": "https://twitter.dagent.shop",
                    "SOCIAL_AGENTS_API_KEY": "your-api-key"
                }
            }
        }
    }
"""

import os
import json

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("SOCIAL_AGENTS_URL", "https://twitter.dagent.shop")
API_KEY = os.environ.get("SOCIAL_AGENTS_API_KEY", "")

mcp = FastMCP(
    "Social Agents",
    description="Post content to Twitter and LinkedIn via the Social Agents platform (twitter.dagent.shop). Supports custom audience targeting and prompt overrides.",
)


def _headers():
    return {"X-API-Key": API_KEY}


@mcp.tool()
async def post_content(
    tweet_text: str,
    linkedin_text: str = "",
    target_audience: str = "",
    custom_prompt: str = "",
    paper_title: str = "",
    paper_url: str = "",
) -> str:
    """Post content to Twitter and optionally LinkedIn with prompt overrides.

    Args:
        tweet_text: The text to post on Twitter (max 280 chars).
        linkedin_text: Optional longer text for LinkedIn (max 3000 chars).
                       If empty, only posts to Twitter.
        target_audience: Override the default audience (e.g. "K-12 teachers",
                        "government policy makers", "full-stack developers").
                        Default audience is early-stage founders and VCs.
        custom_prompt: Override the default writing style/instructions
                      (e.g. "Focus on classroom applications",
                       "Analyze regulatory implications").
        paper_title: Optional title for tracking/history purposes.
        paper_url: Optional source URL for tracking/history purposes.

    Returns:
        JSON string with tweet_id and linkedin_post_id on success,
        or an error message.
    """
    if not API_KEY:
        return "Error: SOCIAL_AGENTS_API_KEY not set. Configure it in your MCP env."

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/api/external-post",
            headers=_headers(),
            json={
                "tweet_text": tweet_text,
                "linkedin_text": linkedin_text,
                "target_audience": target_audience,
                "custom_prompt": custom_prompt,
                "paper_title": paper_title,
                "paper_url": paper_url,
            },
        )
        if resp.status_code == 401:
            return "Error: Unauthorized. Check your SOCIAL_AGENTS_API_KEY."
        if resp.status_code != 200:
            return f"Error ({resp.status_code}): {resp.text}"
        return json.dumps(resp.json())


@mcp.tool()
async def post_tweet(text: str) -> str:
    """Post a short text to Twitter only (max 280 chars).

    Args:
        text: The tweet text.

    Returns:
        JSON string with tweet_id on success, or an error message.
    """
    return await post_content(tweet_text=text)


@mcp.tool()
async def post_to_all(
    tweet_text: str,
    linkedin_text: str,
) -> str:
    """Post to both Twitter and LinkedIn simultaneously.

    Args:
        tweet_text: Short text for Twitter (max 280 chars).
        linkedin_text: Longer text for LinkedIn (max 3000 chars).

    Returns:
        JSON string with tweet_id and linkedin_post_id on success.
    """
    return await post_content(tweet_text=tweet_text, linkedin_text=linkedin_text)


@mcp.tool()
async def generate_and_post(
    target_audience: str = "",
    custom_prompt: str = "",
    platforms: str = "all",
) -> str:
    """Let the AI reasoning engine pick a trending story, generate content, and post.

    The agent will:
    1. Fetch stories from 12+ sources (HN, TechCrunch, Product Hunt, GitHub, etc.)
    2. Use a content strategist to pick the best story and decide format
    3. Generate a tweet and LinkedIn post with the right tone and length
    4. Post to the selected platforms

    Args:
        target_audience: Override the default audience. Examples:
                        - "K-12 teachers and education technologists"
                        - "Government officials and policy makers"
                        - "Full-stack developers and DevOps engineers"
                        Default: early-stage founders and VCs.
        custom_prompt: Override the default writing instructions. Examples:
                      - "Focus on classroom applications and lesson plans"
                      - "Analyze regulatory implications and citizen impact"
                      - "Focus on technical architecture and code examples"
        platforms: Which platforms to post to: "twitter", "linkedin", or "all".
                  Default: "all".

    Returns:
        JSON with tweet_id and/or linkedin_post_id, or an error.
    """
    if not API_KEY:
        return "Error: SOCIAL_AGENTS_API_KEY not set. Configure it in your MCP env."

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{BASE_URL}/api/generate-and-post",
            headers=_headers(),
            json={
                "target_audience": target_audience,
                "custom_prompt": custom_prompt,
                "platforms": platforms,
                "preview_only": False,
            },
        )
        if resp.status_code == 401:
            return "Error: Unauthorized. Check your SOCIAL_AGENTS_API_KEY."
        if resp.status_code != 200:
            return f"Error ({resp.status_code}): {resp.text}"
        return json.dumps(resp.json())


@mcp.tool()
async def generate_preview(
    target_audience: str = "",
    custom_prompt: str = "",
) -> str:
    """Generate a post preview WITHOUT actually posting. Review before you publish.

    Same AI pipeline as generate_and_post but returns the content for review
    instead of posting it.

    Args:
        target_audience: Override the default audience (e.g. "teachers",
                        "policy makers", "developers"). Default: founders/VCs.
        custom_prompt: Override the writing instructions.

    Returns:
        JSON with tweet text, linkedin text, story info, and strategy metadata.
    """
    if not API_KEY:
        return "Error: SOCIAL_AGENTS_API_KEY not set. Configure it in your MCP env."

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{BASE_URL}/api/generate-and-post",
            headers=_headers(),
            json={
                "target_audience": target_audience,
                "custom_prompt": custom_prompt,
                "preview_only": True,
            },
        )
        if resp.status_code == 401:
            return "Error: Unauthorized. Check your SOCIAL_AGENTS_API_KEY."
        if resp.status_code != 200:
            return f"Error ({resp.status_code}): {resp.text}"
        return json.dumps(resp.json())


if __name__ == "__main__":
    mcp.run(transport="stdio")
