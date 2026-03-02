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
    description="Post content to Twitter and LinkedIn via the Social Agents platform (twitter.dagent.shop)",
)


@mcp.tool()
async def post_content(
    tweet_text: str,
    linkedin_text: str = "",
    paper_title: str = "",
    paper_url: str = "",
) -> str:
    """Post content to Twitter and optionally LinkedIn.

    Args:
        tweet_text: The text to post on Twitter (max 280 chars).
        linkedin_text: Optional longer text for LinkedIn (max 3000 chars).
                       If empty, only posts to Twitter.
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
            headers={"X-API-Key": API_KEY},
            json={
                "tweet_text": tweet_text,
                "linkedin_text": linkedin_text,
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
