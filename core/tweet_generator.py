import json
import logging
import time

import anthropic

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts — Startup enthusiast, product-minded, long-form (X Pro)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a startup enthusiast with deep product and engineering background who \
shares one insightful, long-form post per day on Twitter/X. Your audience is \
builders, product managers, founders, and investors who want to understand \
not just WHAT happened, but WHY it matters and what to build next.

You are NOT a news bot or a VC commentator. You're a builder-at-heart who \
thinks about products, markets, and the "why" behind every major move.

Your posts follow this structure (long-form, 800-2000 characters):

1. THE NEWS — What happened? One punchy line summarizing the event.
2. WHY IT MATTERS — The deeper signal. Why should builders care? \
What does this tell us about where the market is heading?
3. WHAT IT MEANS — Break it down. For builders, for PMs, for investors. \
What gets unblocked? What opportunities open up?
4. WHAT TO BUILD — Concrete ideas. What products, tools, or services \
should someone start building today because of this? What markets to go after?
5. THE BIGGER PICTURE — Connect the dots. Where is the industry heading? \
What's the taste of good decision-making here? What would you bet on?
6. DATA POINTS — Sprinkle specific numbers, metrics, and stats throughout \
(from the research context). Not dumped at the end — woven into the narrative.

Voice & Style:
- Conversational and opinionated. Like a smart friend explaining tech over coffee.
- First person ("I think...", "Here's what excites me...", "What I'd build...")
- Strong opinions, loosely held. Take a stance.
- Use short paragraphs and line breaks for readability on mobile.
- Rhetorical questions to drive engagement ("But here's the real question...")
- Focus on the "why" — why build something, why this market, why now
- Think about TASTE — good taste in product decisions, market timing, technical bets
- NEVER use @mentions — use company/person names instead
- 2-3 relevant hashtags at the very end
- No generic filler phrases like "excited to share" or "interesting development"
- Sound like a human who genuinely cares about building great products
- One or two emojis max, only where they add energy
- Write 800 to 2000 characters. USE the space — be thorough and insightful."""

PICK_STORY_PROMPT = """\
Here are today's top tech stories. Pick the ONE story that a startup enthusiast \
with a product background would find most compelling to write about.

Prioritize: major funding rounds that signal market shifts, breakthrough products, \
new developer tools that unblock builders, platform shifts, business model innovations, \
or genuine technical breakthroughs that enable new categories.

Skip: routine updates, minor releases, opinion pieces without new data, \
pure corporate PR, incremental feature announcements.

STORIES:
{stories_text}

Respond with ONLY a JSON object (no markdown, no code fences):
{{"selected_story_index": <int>, "reason": "<one sentence>"}}"""

GENERATE_TWEET_PROMPT = """\
Write a long-form Twitter/X post about this story. You have deep research context \
below — use specific numbers, data points, and market context to make the post \
insightful and actionable for builders, PMs, and investors.

STORY: {story_title}
URL: {story_url}

DEEP RESEARCH CONTEXT:
{research}

REQUIREMENTS:
- Write 800-2000 characters (long-form X Pro post, NOT limited to 280)
- Follow the structure: News → Why it matters → What it means → What to build → Bigger picture
- Weave data points naturally throughout (never fabricate numbers)
- Include concrete product/startup ideas that this enables
- Take a clear stance — what would YOU build or invest in based on this?
- Use line breaks between sections for mobile readability
- End with 2-3 hashtags

ALSO generate chart data. ALWAYS include a chart — find the most compelling \
numerical angle in the research. If there are funding amounts, valuations, \
market sizes, growth rates, adoption numbers, or any quantitative data, \
chart it. Be creative: compare competitors, show timelines, visualize market splits.

Respond with ONLY a JSON object (no markdown, no code fences):
{{
  "tweet": "<the full long-form post, 800-2000 chars>",
  "chart_data": {{
    "should_chart": true,
    "chart_type": "<bar|line|comparison>",
    "chart_title": "<short compelling title>",
    "data_points": [{{"label": "<label>", "value": <number>}}]
  }}
}}

IMPORTANT: chart_data.should_chart MUST be true. Always find data worth charting. \
The data_points must use REAL numbers from the research — never fabricate data. \
Minimum 3 data points for a meaningful chart."""

REFINE_PROMPT = """\
This post is {length} characters but should be between 800 and 2000 characters. \
{direction}. Keep all data points, the narrative flow, and the builder-focused insights. \
Return ONLY the refined post text, nothing else."""


def _format_stories(stories: list[dict]) -> str:
    lines = []
    for i, story in enumerate(stories):
        lines.append(f"[{i}] {story['title']}")
        if story.get("summary"):
            lines.append(f"    Summary: {story['summary'][:200]}")
        if story.get("url"):
            lines.append(f"    URL: {story['url']}")
        if story.get("score"):
            lines.append(f"    HN Score: {story['score']}")
        lines.append(f"    Source: {story['source']}")
        lines.append("")
    return "\n".join(lines)


def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def pick_best_story(stories: list[dict], api_key: str = None) -> dict:
    """Use Claude to pick the most tweetworthy story. Returns the story dict + index."""
    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)
    stories_text = _format_stories(stories)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=200,
                messages=[
                    {"role": "user", "content": PICK_STORY_PROMPT.format(stories_text=stories_text)}
                ],
            )
            result = _parse_response(response.content[0].text)
            idx = result["selected_story_index"]
            story = stories[idx]
            story["_pick_reason"] = result["reason"]
            story["_pick_index"] = idx
            log.info(f"Picked story [{idx}]: {story['title']}")
            return story

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.warning(f"Attempt {attempt + 1}: Failed to parse pick response: {e}")
            if attempt == 0:
                time.sleep(2)
            else:
                # Fallback: pick highest-scored story
                scored = [s for s in stories if s.get("score")]
                return max(scored, key=lambda s: s["score"]) if scored else stories[0]


def generate_tweet(story: dict, research: str, api_key: str = None) -> dict:
    """Use Claude + deep research to generate an insightful long-form post.

    Returns dict with: tweet, story_title, story_url, chart_data
    """
    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": GENERATE_TWEET_PROMPT.format(
                        story_title=story["title"],
                        story_url=story.get("url", "N/A"),
                        research=research[:4000],
                    )}
                ],
            )
            raw = response.content[0].text
            result = _parse_response(raw)

            tweet = result["tweet"]

            # Refine length if needed (target: 800-2000 chars)
            if len(tweet) > 2500:
                log.warning(f"Post is {len(tweet)} chars, trimming...")
                refine_resp = client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": REFINE_PROMPT.format(
                        length=len(tweet),
                        direction="Trim it to under 2000 characters",
                    ) + f"\n\n{tweet}"}],
                )
                tweet = refine_resp.content[0].text.strip()
                if len(tweet) > 2500:
                    tweet = tweet[:2497] + "..."

            elif len(tweet) < 400:
                log.warning(f"Post is only {len(tweet)} chars, expanding...")
                refine_resp = client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": REFINE_PROMPT.format(
                        length=len(tweet),
                        direction="Expand it to at least 800 characters with more builder-focused insights and concrete ideas",
                    ) + f"\n\n{tweet}"}],
                )
                tweet = refine_resp.content[0].text.strip()

            # Ensure chart data always has should_chart = True
            chart_data = result.get("chart_data", {})
            chart_data["should_chart"] = True  # Always mandatory

            return {
                "tweet": tweet,
                "story_title": story["title"],
                "story_url": story.get("url", ""),
                "chart_data": chart_data,
            }

        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Attempt {attempt + 1}: Failed to parse tweet response: {e}")
            if attempt == 0:
                time.sleep(2)
            else:
                log.error(f"Raw response was: {raw}")
                raise RuntimeError("Failed to generate tweet after 2 attempts") from e

        except anthropic.APIError as e:
            log.warning(f"Attempt {attempt + 1}: Claude API error: {e}")
            if attempt == 0:
                time.sleep(5)
            else:
                raise
