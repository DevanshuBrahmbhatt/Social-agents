"""Content Strategist — AI reasoning engine that decides what and how to post.

Replaces the old pick_best_story() with a multi-dimensional decision:
what content type, what length, what tone, whether to chart, what angle.
"""

import json
import logging
import time
from dataclasses import dataclass

import anthropic

import config

log = logging.getLogger(__name__)


@dataclass
class ContentStrategy:
    """The output of the content strategist's reasoning."""
    selected_story_index: int
    story_title: str
    story_url: str
    pick_reason: str
    content_type: str       # breaking_news|hot_take|startup_wisdom|product_spotlight|ai_research|founder_move|open_source|industry_analysis
    post_length: str        # short|medium|long
    target_chars: int
    include_chart: bool
    chart_reasoning: str
    tone: str               # aphoristic|witty|data-driven|contrarian|enthusiastic|analytical
    style_reference: str    # naval|deedy|seibel|altman|rabois|garrytan|dharmesh|collison
    angle: str
    needs_deep_research: bool


STRATEGIST_PROMPT = """\
You are a world-class social media strategist for a tech-focused Twitter/X account. \
Your job is to analyze the available stories and make a STRATEGIC decision about what \
to post and how to post it.

Think like a top content creator with 500K+ followers who knows that \
VARIETY, TIMING, and AUTHENTICITY drive engagement.

CRITICAL ALGORITHM INSIGHTS:
- Tweets under 110 characters perform BEST algorithmically
- Text-only posts get 30% more engagement than image posts
- Retweets weighted 20x likes, Replies 13.5x, Bookmarks 10x
- 80-90% of posts should be short and punchy. Go long ONLY for industry_analysis.
- External links are PENALIZED by the algorithm

RECENT POSTS (avoid repeating):
{already_covered}

AVAILABLE STORIES:
{stories_text}

CONTENT TYPE OPTIONS (pick ONE):
- breaking_news: Major funding, acquisition, or launch. Lead with the number. Medium length, chart likely.
- hot_take: Contrarian opinion on trending topic. 1-3 sentences MAX. No chart.
- startup_wisdom: Timeless advice for builders. Naval/Seibel style ultra-concise. No chart.
- product_spotlight: New tool/product worth knowing. Medium length. Maybe chart.
- ai_research: Paper drop or AI breakthrough. Technical but accessible. Medium.
- founder_move: Notable founder/CEO decision. Story-driven. No chart.
- open_source: Trending repo or major release. Short-medium. Developer-focused.
- industry_analysis: Market shift, data-driven take. THE ONLY type that should be long. WITH chart.

STYLE REFERENCES:
- naval: 1-2 sentence aphorisms. Timeless. Under 100 chars. No hashtags.
- deedy: Data + wit. Sharp observations with numbers. 1-3 sentences.
- seibel: 1-2 sentence tactical founder advice. Under 150 chars.
- altman: Lowercase energy, casual, 1-3 sentences. Understated.
- rabois: Contrarian provocations. Single bold claims. Debate-inducing.
- garrytan: Founder enthusiasm + policy takes. 1-4 sentences.
- dharmesh: Counterintuitive startup truths. Founder confessions.
- collison: Intellectual observations. Curious, 2-4 sentences.

YOUR TASK — reason step-by-step:
1. What story has the highest engagement potential RIGHT NOW?
2. What content type fits best? (bias toward short — 80% of posts should be short/medium)
3. What length will perform best for THIS story?
4. Does a chart ADD value or is it noise? (most of the time: NO chart)
5. What tone and style reference matches this story?
6. What specific angle makes this UNIQUE — not just a news summary?
7. Does this need deep research or is a quick sharp take better?

Respond with ONLY a JSON object:
{{
    "selected_story_index": <int>,
    "pick_reason": "<one sentence>",
    "content_type": "<one of 8 types>",
    "post_length": "<short|medium|long>",
    "target_chars": <int>,
    "include_chart": <true|false>,
    "chart_reasoning": "<one sentence>",
    "tone": "<aphoristic|witty|data-driven|contrarian|enthusiastic|analytical>",
    "style_reference": "<naval|deedy|seibel|altman|rabois|garrytan|dharmesh|collison>",
    "angle": "<1-2 sentences: the specific angle/hook>",
    "needs_deep_research": <true|false>
}}"""


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


def create_content_strategy(
    stories: list[dict],
    recent_titles: list[str] = None,
    api_key: str = None,
) -> ContentStrategy:
    """Analyze all stories and decide what/how to post.

    This is the reasoning engine that replaces pick_best_story().
    """
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
                max_tokens=500,
                messages=[
                    {"role": "user", "content": STRATEGIST_PROMPT.format(
                        stories_text=stories_text,
                        already_covered=already_covered,
                    )}
                ],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            result = json.loads(raw)
            idx = result["selected_story_index"]
            story = stories[idx]

            strategy = ContentStrategy(
                selected_story_index=idx,
                story_title=story["title"],
                story_url=story.get("url", ""),
                pick_reason=result.get("pick_reason", ""),
                content_type=result.get("content_type", "breaking_news"),
                post_length=result.get("post_length", "medium"),
                target_chars=result.get("target_chars", 300),
                include_chart=result.get("include_chart", False),
                chart_reasoning=result.get("chart_reasoning", ""),
                tone=result.get("tone", "witty"),
                style_reference=result.get("style_reference", "deedy"),
                angle=result.get("angle", ""),
                needs_deep_research=result.get("needs_deep_research", True),
            )
            log.info(
                f"Strategy: [{strategy.content_type}] {strategy.post_length} "
                f"({strategy.target_chars} chars) tone={strategy.tone} "
                f"style={strategy.style_reference} chart={strategy.include_chart} "
                f"— {story['title'][:60]}"
            )
            return strategy

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.warning(f"Strategy attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                time.sleep(2)

    # Fallback: pick highest-scored story with sensible defaults
    scored = [s for s in stories if s.get("score")]
    best = max(scored, key=lambda s: s["score"]) if scored else stories[0]
    idx = stories.index(best)
    log.warning("Strategist fallback — using default strategy")
    return ContentStrategy(
        selected_story_index=idx,
        story_title=best["title"],
        story_url=best.get("url", ""),
        pick_reason="Fallback: highest scored story",
        content_type="breaking_news",
        post_length="medium",
        target_chars=350,
        include_chart=False,
        chart_reasoning="Fallback: skip chart",
        tone="witty",
        style_reference="deedy",
        angle="Quick take on trending news",
        needs_deep_research=True,
    )
