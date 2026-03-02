import json
import logging
import time

import anthropic

import config
from core.content_strategist import ContentStrategy

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — anti-AI, human-sounding, strategy-driven
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a tech insider who actually builds things. You post on Twitter/X like the \
best VCs and founders — NOT like an AI content bot.

CARDINAL RULES:
- Sound like a HUMAN. No corporate-speak. No listicles. No "here's why this matters."
- Fragments OK. Run-ons OK. Imperfect grammar is GOOD.
- Take a side. Be definitive. No hedging. No "arguably" or "on one hand."
- NO external links — algorithm penalizes them heavily.
- NEVER use @mentions (@handle format) — your API plan blocks them.
- Name-drop companies and people naturally instead.
- Think out loud: "What I can't figure out is..." "The part nobody talks about..."

ANTI-AI SIGNALS (use these to feel human):
- Personal stakes: "If I were building a startup right now..."
- Genuine surprise: "Wild." "This floored me." "Did not see this coming."
- Admit uncertainty: "Still wrapping my head around this but..."
- Specific references: "Reminds me of when Stripe did X."
- Sentence fragments. One-word reactions. Parenthetical asides.
- NO numbered lists. NO "5 reasons why." NO "let's dive in."

HASHTAGS: Max 2-3 at the end, only when the content type calls for it. \
Mix broad (#AI #Tech) with one community tag (#BuildInPublic or #TechTwitter)."""

# ---------------------------------------------------------------------------
# Style example banks — one per style_reference
# ---------------------------------------------------------------------------

STYLE_EXAMPLES = {
    "naval": """STYLE: Naval Ravikant — ultra-concise aphorisms.
Examples of this style (DO NOT copy, capture the energy):
- One sentence. Timeless. Under 100 characters.
- "Specific knowledge is found by pursuing your genuine curiosity."
- No hashtags. No links. Just the idea, distilled.""",

    "deedy": """STYLE: Deedy Das — data + wit + sharp observations.
Examples of this style:
- Lead with the most impressive number.
- "I dug into [X] so you don't have to."
- 1-3 punchy sentences. Specific data points woven in naturally.
- End with a hot take or "wild" moment.""",

    "seibel": """STYLE: Michael Seibel — tactical founder advice.
Examples of this style:
- 1-2 sentences of direct, tactical startup advice.
- Under 150 characters ideally. Blunt. No fluff.
- "The best founders I know do X, not Y."
- Feels like advice from a mentor, not a content creator.""",

    "altman": """STYLE: Sam Altman — lowercase energy, casual, understated.
Examples of this style:
- 1-3 sentences. Casual tone. Sometimes just an observation.
- Lowercase energy — not shouting, just thinking out loud.
- "i think the most underrated thing about X is..."
- Understated confidence. Big ideas in simple words.""",

    "rabois": """STYLE: Keith Rabois — contrarian provocations.
Examples of this style:
- Single bold claim. Debate-inducing.
- "Everyone thinks X. They're wrong. Here's why."
- Sharp, sometimes controversial. Backed by conviction.
- Designed to make people quote-tweet with their take.""",

    "garrytan": """STYLE: Garry Tan — founder enthusiasm + policy takes.
Examples of this style:
- 1-4 sentences. Genuine excitement about building.
- "This is the future and most people don't see it yet."
- Mixes builder energy with market awareness.
- Sometimes includes a call to action for founders.""",

    "dharmesh": """STYLE: Dharmesh Shah — counterintuitive startup truths.
Examples of this style:
- "The thing nobody tells you about scaling is..."
- Founder confessions. Lessons learned the hard way.
- 2-4 sentences. Conversational. Slightly self-deprecating.
- Feels like wisdom from someone who's been through it.""",

    "collison": """STYLE: Patrick Collison — intellectual observations.
Examples of this style:
- Curious, thoughtful, 2-4 sentences.
- References history, science, or unexpected connections.
- "Interesting that X happened at the same time as Y."
- Makes you think. Doesn't try to go viral.""",
}

# ---------------------------------------------------------------------------
# Length instruction builders
# ---------------------------------------------------------------------------

LENGTH_INSTRUCTIONS = {
    "short": "Write 1-3 sentences MAX. Under 200 characters total. Punchy. Every word earns its place. This should feel like a tweet from someone with strong opinions, not a content creator.",
    "medium": "Write 3-6 lines. 200-500 characters. Enough to make your point with one key data point or insight. Line breaks between ideas for mobile readability.",
    "long": "Write a structured long-form post. 500-1500 characters. Multiple paragraphs with line breaks. Data points woven throughout. This is the ONLY length where detailed analysis is appropriate.",
}

# ---------------------------------------------------------------------------
# Generate prompt — parameterized by ContentStrategy
# ---------------------------------------------------------------------------

GENERATE_TWEET_PROMPT = """\
Write a Twitter/X post about this story.

STORY: {story_title}
URL: {story_url}

RESEARCH CONTEXT:
{research}

YOUR STRATEGY:
- Content type: {content_type}
- Target length: {target_chars} characters ({post_length})
- Tone: {tone}
- Angle: {angle}

{style_bank}

{length_instruction}

{chart_instruction}

MANDATORY RULES:
- NEVER use @mentions — name-drop companies/people naturally instead.
- NO external links in the tweet. The algorithm penalizes them.
- Take a clear stance. Don't hedge.
- If the research has specific numbers, USE them — but never fabricate.
- {hashtag_instruction}

Respond with ONLY a JSON object (no markdown, no code fences):
{{
  "tweet": "<the Twitter/X post>",
  "linkedin_post": "<LinkedIn version, always 800-2000 chars, professional tone, 2-3 hashtags, end with a thought-provoking question>"{chart_json_field}
}}"""

CHART_JSON_TEMPLATE = """,
  "chart_data": {{
    "should_chart": true,
    "chart_type": "<bar|line|comparison>",
    "chart_title": "<short compelling title>",
    "data_points": [{{"label": "<label>", "value": <number>}}]
  }}"""

NO_CHART_JSON = ""


# ---------------------------------------------------------------------------
# Legacy pick_best_story — kept for backward compatibility
# ---------------------------------------------------------------------------

PICK_STORY_PROMPT = """\
Here are today's top tech stories. Pick the ONE most compelling story.

ALREADY COVERED:
{already_covered}

STORIES:
{stories_text}

Respond with ONLY a JSON: {{"selected_story_index": <int>, "reason": "<one sentence>"}}"""


def _format_stories(stories: list[dict]) -> str:
    lines = []
    for i, story in enumerate(stories):
        lines.append(f"[{i}] {story['title']}")
        if story.get("summary"):
            lines.append(f"    Summary: {story['summary'][:200]}")
        if story.get("url"):
            lines.append(f"    URL: {story['url']}")
        if story.get("score"):
            lines.append(f"    Score: {story['score']}")
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


def pick_best_story(stories: list[dict], api_key: str = None,
                    recent_titles: list[str] = None) -> dict:
    """Legacy: Use Claude to pick story. Prefer create_content_strategy() instead."""
    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)
    stories_text = _format_stories(stories)

    if recent_titles:
        covered_lines = "\n".join(f"- {t}" for t in recent_titles[:10])
        already_covered = f"Already posted about:\n{covered_lines}\n"
    else:
        already_covered = "First post — pick the most interesting story.\n"

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=200,
                messages=[
                    {"role": "user", "content": PICK_STORY_PROMPT.format(
                        stories_text=stories_text,
                        already_covered=already_covered,
                    )}
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
                scored = [s for s in stories if s.get("score")]
                return max(scored, key=lambda s: s["score"]) if scored else stories[0]


def generate_tweet(story: dict, research: str, api_key: str = None,
                   strategy: ContentStrategy = None) -> dict:
    """Generate a post driven by ContentStrategy.

    If no strategy is provided, falls back to medium/witty/deedy defaults.

    Returns dict with: tweet, linkedin_post, story_title, story_url, chart_data (or None)
    """
    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)

    # Build strategy-driven prompt parameters
    if strategy:
        content_type = strategy.content_type
        post_length = strategy.post_length
        target_chars = strategy.target_chars
        tone = strategy.tone
        style_ref = strategy.style_reference
        angle = strategy.angle
        include_chart = strategy.include_chart
    else:
        # Legacy defaults
        content_type = "breaking_news"
        post_length = "medium"
        target_chars = 350
        tone = "witty"
        style_ref = "deedy"
        angle = "Quick take on trending tech news"
        include_chart = True

    style_bank = STYLE_EXAMPLES.get(style_ref, STYLE_EXAMPLES["deedy"])
    length_instruction = LENGTH_INSTRUCTIONS.get(post_length, LENGTH_INSTRUCTIONS["medium"])

    # Chart instruction
    if include_chart:
        chart_instruction = (
            "ALSO generate chart data. Find the most compelling numerical angle "
            "in the research. Use REAL numbers only — never fabricate. Minimum 3 data points."
        )
        chart_json_field = CHART_JSON_TEMPLATE
    else:
        chart_instruction = "NO chart for this post. Skip chart_data entirely."
        chart_json_field = NO_CHART_JSON

    # Hashtag instruction based on content type
    if content_type in ("hot_take", "startup_wisdom"):
        hashtag_instruction = "NO hashtags for this post type. Clean and minimal."
    elif content_type in ("breaking_news", "industry_analysis"):
        hashtag_instruction = "End with 2-3 relevant hashtags on a new line."
    else:
        hashtag_instruction = "Optionally end with 1-2 hashtags if they add value. Don't force it."

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": GENERATE_TWEET_PROMPT.format(
                        story_title=story["title"],
                        story_url=story.get("url", "N/A"),
                        research=research[:4000],
                        content_type=content_type,
                        target_chars=target_chars,
                        post_length=post_length,
                        tone=tone,
                        angle=angle,
                        style_bank=style_bank,
                        length_instruction=length_instruction,
                        chart_instruction=chart_instruction,
                        chart_json_field=chart_json_field,
                        hashtag_instruction=hashtag_instruction,
                    )}
                ],
            )
            raw = response.content[0].text
            result = _parse_response(raw)

            tweet = result["tweet"]

            # Only refine if WAY over target (give 50% buffer)
            max_allowed = int(target_chars * 1.5)
            if len(tweet) > max_allowed and post_length != "long":
                log.warning(f"Post is {len(tweet)} chars (target {target_chars}), trimming...")
                refine_resp = client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": (
                        f"This post is {len(tweet)} characters but should be under "
                        f"{target_chars} characters. Shorten it while keeping the core insight "
                        f"and tone. Return ONLY the refined post text.\n\n{tweet}"
                    )}],
                )
                tweet = refine_resp.content[0].text.strip()

            # Get chart data (None if strategy says no chart)
            chart_data = result.get("chart_data")
            if chart_data and include_chart:
                chart_data["should_chart"] = True
            elif not include_chart:
                chart_data = None

            # LinkedIn post (always 800-2000 chars regardless of tweet length)
            linkedin_post = result.get("linkedin_post", tweet)

            return {
                "tweet": tweet,
                "linkedin_post": linkedin_post,
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
