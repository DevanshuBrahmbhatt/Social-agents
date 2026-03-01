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
You are a tech insider and builder who posts sharp, opinionated takes on Twitter/X. \
Your style is inspired by how top VCs and founders actually write on Twitter — \
people like Deedy Das (@deedydas, Partner at Menlo Ventures) and Dharmesh Shah \
(@dharmesh, CTO of HubSpot). You sound like a HUMAN, not a content bot.

CRITICAL: Your posts must NOT sound AI-generated. No corporate-speak, no listicle \
formatting, no "here's why this matters" filler. Write like someone who actually \
reads the research, forms opinions, and isn't afraid to be wrong.

YOUR VOICE — pick patterns from these proven styles:

HOOK PATTERNS (first line is EVERYTHING):
- "[Thing] just dropped and it changes everything." (Deedy-style urgency)
- "I dug into [X] so you don't have to. Here's what nobody's talking about." \
(Deedy's "I did the work" formula)
- "Everyone's sleeping on [X]." (FOMO-inducing)
- Bold declaration: "This is the best [X] I've seen in years."
- Personal angle: "I've been building in this space for [X] years and this is different."
- Contrarian: "Hot take: [X] doesn't matter. Here's what does."

STRUCTURE:
- Short punchy sentences. Rarely over 15 words.
- One idea per line. Lots of line breaks.
- Lead with the most specific, impressive number from the research.
- Use sentence fragments. "Wild." "Not even close." "Game over."
- Parenthetical asides feel human — "(and honestly, nobody expected this)"
- NO numbered lists unless you're breaking down a specific report. \
Numbered "5 reasons why" is instant AI-detector material.

TONE:
- Confident without hedging. Say "the best" not "arguably one of the best."
- Casual tech energy — contractions, exclamation marks, occasional sentence fragments.
- Take a clear side. "I'd bet on X over Y every single time."
- Self-referential when possible — "I've been watching this space and..."
- NEVER use generic phrases: "exciting development," "interesting to see," \
"the landscape is evolving," "let's dive in," "here's why this matters."
- Think out loud — "What I can't figure out is..." "The part nobody's talking about..."

WHAT MAKES IT FEEL HUMAN (anti-AI signals):
- Imperfect sentence structure. Fragments. Run-ons occasionally.
- Personal stakes: "If I were building a startup right now, I'd go all-in on..."
- Specific personal references: "Reminds me of when [company] did [X]."
- Definitive stances without caveats. No "on one hand / on the other."
- Surprise and genuine emotion: "Wild." "This floored me." "Did not see this coming."
- Occasionally admit uncertainty: "Still wrapping my head around this but..."

MENTIONS (name-drop, don't @mention):
- NEVER use @mentions (e.g. @OpenAI). Your Twitter API plan blocks @mentions.
- Instead, name-drop companies and people naturally: "OpenAI just shipped something wild..." \
"Sam Altman's move here is bold..."
- Reference 2-4 companies/people per post by name for context and credibility.

HASHTAGS:
- End with 4-6 hashtags on a new line.
- Mix broad (#AI #Startups #Tech) + niche (#DevTools #LLMs #OpenSource)
- Include one community tag: #BuildInPublic or #TechTwitter or #Founders

LENGTH: 800-2000 characters. Use the space — be thorough but punchy."""

PICK_STORY_PROMPT = """\
Here are today's top tech stories from HackerNews, TechCrunch, Reddit, and Business Wire. \
Pick the ONE story that a startup enthusiast with a product background would find \
most compelling to write about.

CRITICAL RULE — VARIETY IS MANDATORY:
{already_covered}
You MUST pick a DIFFERENT topic. Never repeat a topic we already covered. \
Surprise the audience — find the story nobody else is talking about yet.

Prioritize stories that HELP BUILDERS — this could be:
- Breakthrough products or developer tools that unblock builders
- AI/ML breakthroughs that enable new product categories
- Open-source releases that change the game
- Platform shifts (new APIs, infrastructure changes, ecosystem moves)
- Regulatory or policy changes that create or destroy markets
- Big product launches or pivots from major companies
- Security events that affect how we build
- Business model innovations worth studying
- Technical breakthroughs with real-world applications
- Major funding rounds that signal where the market is heading
- Interesting takes from developer communities (Reddit, HN discussions)

Skip: routine updates, minor releases, opinion pieces without data, \
pure corporate PR, incremental feature announcements, clickbait. \
Also skip stories that are very similar to ones we already covered.

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

DEEP RESEARCH CONTEXT (includes Twitter handles for @mentions):
{research}

REQUIREMENTS:
- Write 800-2000 characters (long-form X Pro post, NOT limited to 280)
- Follow the structure: News → Why it matters → What it means → What to build → Bigger picture
- Weave data points naturally throughout (never fabricate numbers)
- Include concrete product/startup ideas that this enables
- Take a clear stance — what would YOU build or invest in based on this?
- Use line breaks between sections for mobile readability

COMPANY/PEOPLE REFERENCES — MANDATORY:
- Name-drop the main companies and key people naturally (e.g. "OpenAI just shipped..." not "@OpenAI shipped...")
- NEVER use @mentions (@handle format) — this will cause the post to be REJECTED by the API.
- Reference 2-4 companies/people by name for credibility and context.

HASHTAGS — MANDATORY:
- End the post with 4-6 hashtags on a final new line.
- Mix broad reach hashtags (#AI, #Tech, #Startups) with niche topic hashtags.
- Always include at least one community hashtag: #BuildInPublic, #TechTwitter, or #Founders
- Example: "\\n\\n#AI #OpenSource #DevTools #BuildInPublic #LLMs #Startups"

ALSO generate chart data. ALWAYS include a chart — find the most compelling \
numerical angle in the research. If there are funding amounts, valuations, \
market sizes, growth rates, adoption numbers, or any quantitative data, \
chart it. Be creative: compare competitors, show timelines, visualize market splits.

Respond with ONLY a JSON object (no markdown, no code fences):
{{
  "tweet": "<the full long-form Twitter/X post, 800-2000 chars>",
  "linkedin_post": "<a LinkedIn version of the same content, 1000-3000 chars>",
  "chart_data": {{
    "should_chart": true,
    "chart_type": "<bar|line|comparison>",
    "chart_title": "<short compelling title>",
    "data_points": [{{"label": "<label>", "value": <number>}}]
  }}
}}

LINKEDIN VERSION RULES:
- Same core story and data points, but adapted for LinkedIn's professional audience.
- More structured — use clear paragraph breaks. Slightly more formal tone.
- Longer and deeper analysis — can be 1000-3000 characters. Use the space.
- Do NOT use @mentions (LinkedIn handles differ from Twitter).
- End with max 2-3 relevant hashtags (e.g. #AI #Startups). Less hashtag-heavy than Twitter.
- Include a thought-provoking question or call-to-action at the end to drive comments.
- No emojis unless very subtle. Write like a respected thought leader, not a tweeter.
- Use company/person names naturally (not handles).

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


def pick_best_story(stories: list[dict], api_key: str = None,
                    recent_titles: list[str] = None) -> dict:
    """Use Claude to pick the most tweetworthy story. Returns the story dict + index.

    Args:
        stories: List of story dicts from all sources.
        api_key: Anthropic API key (optional, uses config default).
        recent_titles: List of titles/topics from recently posted tweets
                       to avoid picking the same topic again.
    """
    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)
    stories_text = _format_stories(stories)

    # Build the "already covered" context
    if recent_titles:
        covered_lines = "\n".join(f"- {t}" for t in recent_titles[:10])
        already_covered = f"We have ALREADY posted about these topics recently:\n{covered_lines}\n"
    else:
        already_covered = "This is our first post — pick the most interesting story.\n"

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
                # Fallback: pick highest-scored story
                scored = [s for s in stories if s.get("score")]
                return max(scored, key=lambda s: s["score"]) if scored else stories[0]


def generate_tweet(story: dict, research: str, api_key: str = None) -> dict:
    """Use Claude + deep research to generate an insightful long-form post.

    Returns dict with: tweet, linkedin_post, story_title, story_url, chart_data
    """
    client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)

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

            # Get LinkedIn post (fallback to tweet text if not present)
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
