"""FastAPI web application — dashboard, API endpoints, and auth."""

import json
import logging
import secrets
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
from web.database import init_db, get_or_create_owner, SessionLocal, User, Settings, TweetHistory
from web.scheduler import (
    start_scheduler, stop_scheduler, setup_user_schedule,
    start_user_agent, stop_user_agent, is_user_agent_running, get_user_next_run,
)
from web.auth import (
    get_current_user, get_user_id_from_cookie,
    twitter_login_start, twitter_login_callback, owner_login, logout,
    linkedin_connect_start, linkedin_connect_callback, linkedin_disconnect,
)
from core.news_fetcher import fetch_all_stories, deep_research_story
from core.content_strategist import create_content_strategy
from core.tweet_generator import generate_tweet
from core.chart_generator import generate_chart
from core.twitter_poster import post_tweet, post_tweet_dry_run
from core.linkedin_poster import post_linkedin

log = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(config.PROJECT_ROOT / "web" / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    init_db()
    get_or_create_owner()
    start_scheduler()
    log.info("TweetAgent started — dashboard at http://localhost:8000")
    yield
    stop_scheduler()


app = FastAPI(title="TweetAgent", lifespan=lifespan)

# Mount charts directory for serving chart images
app.mount("/charts", StaticFiles(directory=str(config.CHARTS_DIR)), name="charts")
# Mount static files (logo, etc.)
app.mount("/static", StaticFiles(directory=str(config.PROJECT_ROOT / "web" / "static")), name="static")


# ---------------------------------------------------------------------------
# Exception handler for 302 redirects
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 302 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page. Redirect to dashboard if already logged in."""
    user_id = get_user_id_from_cookie(request)
    if user_id is not None:
        return RedirectResponse(url="/dashboard", status_code=303)
    error = request.query_params.get("error", "")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
    })


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Public privacy policy page (required by LinkedIn)."""
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/auth/twitter")
async def do_twitter_login(request: Request):
    return await twitter_login_start(request)


@app.get("/auth/callback")
async def do_twitter_callback(request: Request):
    return await twitter_login_callback(request)


@app.post("/auth/owner-login")
async def do_owner_login(request: Request):
    return await owner_login(request)


@app.get("/auth/logout")
async def do_logout(request: Request):
    return await logout(request)


@app.get("/auth/linkedin")
async def do_linkedin_connect(request: Request):
    return await linkedin_connect_start(request)


@app.get("/auth/linkedin/callback")
async def do_linkedin_callback(request: Request):
    return await linkedin_connect_callback(request)


@app.post("/auth/linkedin/disconnect")
async def do_linkedin_disconnect(request: Request):
    return await linkedin_disconnect(request)


# ---------------------------------------------------------------------------
# Homepage / Landing
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Show landing page or dashboard based on auth status."""
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        return templates.TemplateResponse("landing.html", {"request": request})
    # If logged in, show dashboard (redirect to /dashboard)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Public landing page with MCP docs — no login required."""
    return templates.TemplateResponse("landing.html", {"request": request})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(get_current_user)):
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        settings = user.settings if user else None
        tweets = session.query(TweetHistory).filter_by(user_id=user.id).order_by(
            TweetHistory.posted_at.desc()
        ).limit(20).all() if user else []

        agent_running = is_user_agent_running(user.id) if user else False
        next_run = get_user_next_run(user.id) if user else None

        # Owner-only: get all users with tweet counts
        all_users = []
        if user and user.is_owner:
            from sqlalchemy import func
            user_stats = (
                session.query(
                    User.id,
                    User.twitter_username,
                    User.is_owner,
                    User.created_at,
                    func.count(TweetHistory.id).label("tweet_count"),
                )
                .outerjoin(TweetHistory, TweetHistory.user_id == User.id)
                .group_by(User.id)
                .order_by(User.created_at.asc())
                .all()
            )
            all_users = [
                {
                    "id": u.id,
                    "username": u.twitter_username or "—",
                    "is_owner": u.is_owner,
                    "created_at": u.created_at,
                    "tweet_count": u.tweet_count,
                }
                for u in user_stats
            ]

        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user,
            "settings": settings,
            "tweets": tweets,
            "topics_list": settings.get_topics() if settings else [],
            "schedule_times": settings.get_schedule_times() if settings else ["09:00"],
            "agent_running": agent_running,
            "next_run": next_run,
            "all_users": all_users,
            "linkedin_connected": bool(user.linkedin_access_token) if user else False,
            "linkedin_name": user.linkedin_name if user else None,
            "linkedin_posting_enabled": settings.linkedin_posting_enabled if settings and hasattr(settings, 'linkedin_posting_enabled') else True,
            "mcp_api_key": user.mcp_api_key if user else None,
        })
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Agent Start / Stop
# ---------------------------------------------------------------------------

@app.post("/api/agent/start")
async def agent_start(current_user: User = Depends(get_current_user)):
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        if not user:
            return JSONResponse({"error": "No user found"}, status_code=400)
        if not user.twitter_access_token:
            return JSONResponse({"error": "Twitter developer credentials not configured. Add them in API Keys section."}, status_code=400)
        if not user.anthropic_api_key:
            return JSONResponse({"error": "Anthropic API key missing. Add it in API Keys section."}, status_code=400)

        success = start_user_agent(user.id)
        if success:
            next_run = get_user_next_run(user.id)
            return JSONResponse({
                "status": "ok",
                "message": "Agent started!",
                "next_run": next_run,
            })
        else:
            return JSONResponse({"error": "Failed to start — check settings and API keys"}, status_code=400)
    finally:
        session.close()


@app.post("/api/agent/stop")
async def agent_stop(current_user: User = Depends(get_current_user)):
    stop_user_agent(current_user.id)
    return JSONResponse({"status": "ok", "message": "Agent stopped."})


@app.get("/api/agent/status")
async def agent_status(current_user: User = Depends(get_current_user)):
    running = is_user_agent_running(current_user.id)
    next_run = get_user_next_run(current_user.id) if running else None
    return JSONResponse({"running": running, "next_run": next_run})


# ---------------------------------------------------------------------------
# API: Settings
# ---------------------------------------------------------------------------

@app.post("/api/settings")
async def save_settings(
    current_user: User = Depends(get_current_user),
    topics: str = Form(""),
    tweet_frequency: int = Form(1),
    schedule_times: str = Form("09:00"),
    timezone: str = Form("America/Los_Angeles"),
    tweet_style: str = Form("founder-focused"),
    linkedin_posting_enabled: str = Form("true"),
):
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        if not user or not user.settings:
            return JSONResponse({"error": "No user found"}, status_code=400)

        s = user.settings
        s.set_topics([t.strip() for t in topics.split(",") if t.strip()])
        s.tweet_frequency = tweet_frequency
        s.set_schedule_times([t.strip() for t in schedule_times.split(",") if t.strip()])
        s.timezone = timezone
        s.tweet_style = tweet_style
        s.linkedin_posting_enabled = linkedin_posting_enabled.lower() in ("true", "1", "on", "yes")
        session.commit()

        # Update scheduler if agent is running
        if is_user_agent_running(user.id):
            setup_user_schedule(user.id, s.get_schedule_times(), s.timezone)

        return JSONResponse({"status": "ok", "message": "Settings saved!"})
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Setup (API keys)
# ---------------------------------------------------------------------------

@app.post("/api/setup")
async def save_api_keys(
    current_user: User = Depends(get_current_user),
    anthropic_key: str = Form(""),
    perplexity_key: str = Form(""),
    twitter_api_key: str = Form(""),
    twitter_api_secret: str = Form(""),
    twitter_access_token: str = Form(""),
    twitter_access_token_secret: str = Form(""),
):
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        if not user:
            return JSONResponse({"error": "No user found"}, status_code=400)

        if anthropic_key:
            user.anthropic_api_key = anthropic_key
        if perplexity_key:
            user.perplexity_api_key = perplexity_key
        if twitter_api_key:
            user.twitter_api_key = twitter_api_key
        if twitter_api_secret:
            user.twitter_api_secret = twitter_api_secret
        if twitter_access_token:
            user.twitter_access_token = twitter_access_token
        if twitter_access_token_secret:
            user.twitter_access_token_secret = twitter_access_token_secret
        session.commit()

        return JSONResponse({"status": "ok", "message": "API keys updated!"})
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Generate API Key (for MCP / external access)
# ---------------------------------------------------------------------------

@app.post("/api/generate-api-key")
async def generate_api_key(current_user: User = Depends(get_current_user)):
    """Generate or regenerate the user's personal MCP API key."""
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=400)

        # Generate a new API key
        new_key = f"sa-{secrets.token_urlsafe(32)}"
        user.mcp_api_key = new_key
        session.commit()

        return JSONResponse({"api_key": new_key, "message": "API key generated!"})
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Generate Preview
# ---------------------------------------------------------------------------

@app.post("/api/generate-preview")
async def generate_preview(current_user: User = Depends(get_current_user)):
    try:
        session = SessionLocal()
        user = session.query(User).get(current_user.id)
        session.close()

        if not user or not user.anthropic_api_key:
            return JSONResponse({"error": "Anthropic API key not configured"}, status_code=400)

        # 1. Fetch stories from all 12 sources
        stories = fetch_all_stories()
        if not stories:
            return JSONResponse({"error": "No stories found"}, status_code=500)

        # Get recent tweets to avoid repeating topics
        hist_session = SessionLocal()
        recent_tweets = (
            hist_session.query(TweetHistory)
            .filter_by(user_id=user.id, status="posted")
            .order_by(TweetHistory.posted_at.desc())
            .limit(10)
            .all()
        )
        recent_titles = [t.story_title or t.tweet_text[:80] for t in recent_tweets if t.story_title or t.tweet_text]
        hist_session.close()

        # 2. Content Strategist — reason about what/how to post
        strategy = create_content_strategy(
            stories,
            recent_titles=recent_titles,
            api_key=user.anthropic_api_key,
        )
        story = stories[strategy.selected_story_index]

        # 3. Conditional deep research
        if strategy.needs_deep_research:
            research = deep_research_story(story, api_key=user.perplexity_api_key)
        else:
            research = story.get("summary") or story.get("title", "")

        # 4. Generate post (strategy-driven)
        result = generate_tweet(story, research, api_key=user.anthropic_api_key, strategy=strategy)

        # 5. Conditional chart generation
        chart_path = generate_chart(result.get("chart_data"))
        chart_url = None
        if chart_path:
            from pathlib import Path
            chart_url = f"/charts/{Path(chart_path).name}"

        linkedin_post = result.get("linkedin_post", result["tweet"])
        return JSONResponse({
            "tweet": result["tweet"],
            "linkedin_post": linkedin_post,
            "story_title": result.get("story_title", ""),
            "story_url": result.get("story_url", ""),
            "chart_url": chart_url,
            "chars": len(result["tweet"]),
            "linkedin_chars": len(linkedin_post),
            # Strategy metadata for debugging/display
            "strategy": {
                "content_type": strategy.content_type,
                "post_length": strategy.post_length,
                "tone": strategy.tone,
                "style_reference": strategy.style_reference,
                "include_chart": strategy.include_chart,
                "needs_deep_research": strategy.needs_deep_research,
                "pick_reason": strategy.pick_reason,
                "angle": strategy.angle,
            },
        })

    except Exception as e:
        log.error(f"Preview generation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# API: Post Now
# ---------------------------------------------------------------------------

@app.post("/api/post-now")
async def post_now(
    current_user: User = Depends(get_current_user),
    tweet_text: str = Form(""),
    linkedin_text: str = Form(""),
    chart_url: str = Form(""),
    post_to_linkedin: str = Form("false"),
):
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        if not user:
            return JSONResponse({"error": "No user found"}, status_code=400)

        if not tweet_text:
            return JSONResponse({"error": "Tweet text is empty"}, status_code=400)

        # Convert chart URL to file path
        chart_path = None
        if chart_url:
            from pathlib import Path
            chart_name = Path(chart_url).name
            chart_path = str(config.CHARTS_DIR / chart_name)

        results = {"twitter": None, "linkedin": None}

        # Post to Twitter (if credentials configured)
        if user.twitter_access_token:
            try:
                response = post_tweet(
                    text=tweet_text,
                    image_path=chart_path,
                    api_key=user.twitter_api_key,
                    api_secret=user.twitter_api_secret,
                    access_token=user.twitter_access_token,
                    access_token_secret=user.twitter_access_token_secret,
                )
                tweet_id = str(response.data["id"])
                results["twitter"] = tweet_id

                # Save Twitter history
                history = TweetHistory(
                    user_id=user.id,
                    tweet_text=tweet_text,
                    tweet_id=tweet_id,
                    chart_path=chart_path,
                    status="posted",
                    platform="twitter",
                )
                session.add(history)
            except Exception as e:
                log.error(f"Twitter post failed: {e}")
                results["twitter"] = f"error: {e}"
                # Log failure
                history = TweetHistory(
                    user_id=user.id,
                    tweet_text=tweet_text[:500],
                    status="failed",
                    platform="twitter",
                )
                session.add(history)
        else:
            return JSONResponse({"error": "Twitter developer credentials not configured"}, status_code=400)

        # Post to LinkedIn (if connected and requested)
        should_post_linkedin = post_to_linkedin.lower() in ("true", "1", "on", "yes")
        if should_post_linkedin and user.linkedin_access_token and user.linkedin_person_urn:
            try:
                li_text = linkedin_text or tweet_text  # fallback to tweet text
                li_response = post_linkedin(
                    text=li_text,
                    image_path=chart_path,
                    person_urn=user.linkedin_person_urn,
                    access_token=user.linkedin_access_token,
                )
                linkedin_post_id = li_response.get("id", "")
                results["linkedin"] = linkedin_post_id

                # Save LinkedIn history
                li_history = TweetHistory(
                    user_id=user.id,
                    tweet_text=li_text,
                    linkedin_post_id=linkedin_post_id,
                    chart_path=chart_path,
                    status="posted",
                    platform="linkedin",
                )
                session.add(li_history)
            except Exception as e:
                log.error(f"LinkedIn post failed: {e}")
                results["linkedin"] = f"error: {e}"

        session.commit()

        message_parts = []
        if results["twitter"] and not str(results["twitter"]).startswith("error"):
            message_parts.append("Tweet posted!")
        if results["linkedin"] and not str(results["linkedin"]).startswith("error"):
            message_parts.append("LinkedIn posted!")

        return JSONResponse({
            "status": "ok",
            "tweet_id": results["twitter"],
            "linkedin_post_id": results["linkedin"],
            "message": " ".join(message_parts) or "Posted!",
        })

    except Exception as e:
        log.error(f"Post failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: History
# ---------------------------------------------------------------------------

@app.get("/api/history")
async def get_history(current_user: User = Depends(get_current_user)):
    session = SessionLocal()
    try:
        tweets = session.query(TweetHistory).filter_by(user_id=current_user.id).order_by(
            TweetHistory.posted_at.desc()
        ).limit(50).all()

        return JSONResponse({
            "tweets": [
                {
                    "id": t.id,
                    "text": t.tweet_text,
                    "tweet_id": t.tweet_id,
                    "linkedin_post_id": getattr(t, "linkedin_post_id", None),
                    "platform": getattr(t, "platform", "twitter"),
                    "story_title": t.story_title,
                    "story_url": t.story_url,
                    "posted_at": t.posted_at.isoformat() if t.posted_at else None,
                    "status": t.status,
                }
                for t in tweets
            ]
        })
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: External Post (for Research Agent integration)
# ---------------------------------------------------------------------------

@app.post("/api/external-post")
async def external_post(request: Request):
    """Receive post from external agents (e.g., Research Agent).

    Authenticated via X-API-Key header matching EXTERNAL_API_KEY or per-user mcp_api_key.
    """
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        return JSONResponse({"error": "X-API-Key header required"}, status_code=401)

    session = SessionLocal()
    try:
        # Check global key first (for backward compat)
        expected_key = getattr(config, "EXTERNAL_API_KEY", "")
        if expected_key and api_key == expected_key:
            user = session.query(User).filter_by(is_owner=True).first()
        else:
            # Check per-user API keys
            user = session.query(User).filter_by(mcp_api_key=api_key).first()

        if not user:
            return JSONResponse({"error": "Invalid API key"}, status_code=401)

        body = await request.json()
        tweet_text = body.get("tweet_text", "")
        linkedin_text = body.get("linkedin_text", "")
        target_audience = body.get("target_audience", "")
        custom_prompt = body.get("custom_prompt", "")

        if not tweet_text:
            return JSONResponse({"error": "tweet_text is required"}, status_code=400)

        results = {"tweet_id": None, "linkedin_post_id": None}

        # Post to Twitter
        if user.twitter_access_token:
            try:
                response = post_tweet(
                    text=tweet_text,
                    api_key=user.twitter_api_key,
                    api_secret=user.twitter_api_secret,
                    access_token=user.twitter_access_token,
                    access_token_secret=user.twitter_access_token_secret,
                )
                results["tweet_id"] = str(response.data["id"])

                history = TweetHistory(
                    user_id=user.id,
                    tweet_text=tweet_text,
                    tweet_id=results["tweet_id"],
                    story_title=body.get("paper_title", ""),
                    story_url=body.get("paper_url", ""),
                    status="posted",
                    platform="twitter",
                    content_type="ai_research",
                )
                session.add(history)
            except Exception as e:
                log.error(f"External post Twitter failed: {e}")
                results["tweet_id"] = None

        # Post to LinkedIn
        if user.linkedin_access_token and user.linkedin_person_urn and linkedin_text:
            try:
                from web.auth import refresh_linkedin_token_sync
                refresh_linkedin_token_sync(user.id)

                li_response = post_linkedin(
                    text=linkedin_text,
                    person_urn=user.linkedin_person_urn,
                    access_token=user.linkedin_access_token,
                )
                results["linkedin_post_id"] = li_response.get("id", "")

                li_history = TweetHistory(
                    user_id=user.id,
                    tweet_text=linkedin_text,
                    linkedin_post_id=results["linkedin_post_id"],
                    story_title=body.get("paper_title", ""),
                    story_url=body.get("paper_url", ""),
                    status="posted",
                    platform="linkedin",
                    content_type="ai_research",
                )
                session.add(li_history)
            except Exception as e:
                log.error(f"External post LinkedIn failed: {e}")

        session.commit()
        return JSONResponse(results)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Generate and Post (full AI pipeline via MCP)
# ---------------------------------------------------------------------------

@app.post("/api/generate-and-post")
async def generate_and_post_endpoint(request: Request):
    """Full AI pipeline: fetch stories -> strategist -> generate -> post.
    Supports target_audience and custom_prompt overrides.
    Authenticated via X-API-Key header.
    """
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        return JSONResponse({"error": "X-API-Key header required"}, status_code=401)

    session = SessionLocal()
    try:
        # Auth: check global key or per-user key
        expected_key = getattr(config, "EXTERNAL_API_KEY", "")
        if expected_key and api_key == expected_key:
            user = session.query(User).filter_by(is_owner=True).first()
        else:
            user = session.query(User).filter_by(mcp_api_key=api_key).first()

        if not user:
            return JSONResponse({"error": "Invalid API key"}, status_code=401)

        if not user.anthropic_api_key:
            return JSONResponse({"error": "Anthropic API key not configured"}, status_code=400)

        body = await request.json()
        target_audience = body.get("target_audience", "")
        custom_prompt = body.get("custom_prompt", "")
        platforms = body.get("platforms", "all")  # "twitter", "linkedin", "all"
        preview_only = body.get("preview_only", False)

        # Fetch stories
        stories = fetch_all_stories()
        if not stories:
            return JSONResponse({"error": "No stories found"}, status_code=500)

        # Get recent titles
        recent_tweets = (
            session.query(TweetHistory)
            .filter_by(user_id=user.id, status="posted")
            .order_by(TweetHistory.posted_at.desc())
            .limit(10)
            .all()
        )
        recent_titles = [t.story_title or t.tweet_text[:80] for t in recent_tweets if t.story_title or t.tweet_text]

        # Strategy
        strategy = create_content_strategy(
            stories,
            recent_titles=recent_titles,
            api_key=user.anthropic_api_key,
        )
        story = stories[strategy.selected_story_index]

        # Conditional research
        if strategy.needs_deep_research:
            research = deep_research_story(story, api_key=user.perplexity_api_key)
        else:
            research = story.get("summary") or story.get("title", "")

        # Generate with overrides
        result = generate_tweet(
            story, research,
            api_key=user.anthropic_api_key,
            strategy=strategy,
        )

        # If preview only, return without posting
        if preview_only:
            chart_path = generate_chart(result.get("chart_data"))
            chart_url = None
            if chart_path:
                from pathlib import Path
                chart_url = f"/charts/{Path(chart_path).name}"
            return JSONResponse({
                "tweet": result["tweet"],
                "linkedin_post": result.get("linkedin_post", result["tweet"]),
                "story_title": result.get("story_title", ""),
                "chart_url": chart_url,
                "strategy": {
                    "content_type": strategy.content_type,
                    "style_reference": strategy.style_reference,
                    "tone": strategy.tone,
                },
            })

        # Post
        results = {"tweet_id": None, "linkedin_post_id": None}
        chart_path = generate_chart(result.get("chart_data"))

        if platforms in ("twitter", "all") and user.twitter_access_token:
            try:
                from core.twitter_poster import post_tweet as do_post_tweet
                response = do_post_tweet(
                    text=result["tweet"],
                    image_path=chart_path,
                    api_key=user.twitter_api_key,
                    api_secret=user.twitter_api_secret,
                    access_token=user.twitter_access_token,
                    access_token_secret=user.twitter_access_token_secret,
                )
                results["tweet_id"] = str(response.data["id"])
                session.add(TweetHistory(
                    user_id=user.id,
                    tweet_text=result["tweet"],
                    tweet_id=results["tweet_id"],
                    story_title=result.get("story_title", ""),
                    status="posted",
                    platform="twitter",
                    content_type=strategy.content_type,
                ))
            except Exception as e:
                log.error(f"Generate-and-post Twitter failed: {e}")
                results["tweet_id"] = f"error: {e}"

        if platforms in ("linkedin", "all") and user.linkedin_access_token and user.linkedin_person_urn:
            try:
                from web.auth import refresh_linkedin_token_sync
                refresh_linkedin_token_sync(user.id)
                li_text = result.get("linkedin_post", result["tweet"])
                li_resp = post_linkedin(
                    text=li_text,
                    image_path=chart_path,
                    person_urn=user.linkedin_person_urn,
                    access_token=user.linkedin_access_token,
                )
                results["linkedin_post_id"] = li_resp.get("id", "")
                session.add(TweetHistory(
                    user_id=user.id,
                    tweet_text=li_text,
                    linkedin_post_id=results["linkedin_post_id"],
                    story_title=result.get("story_title", ""),
                    status="posted",
                    platform="linkedin",
                    content_type=strategy.content_type,
                ))
            except Exception as e:
                log.error(f"Generate-and-post LinkedIn failed: {e}")
                results["linkedin_post_id"] = f"error: {e}"

        session.commit()
        return JSONResponse(results)
    except Exception as e:
        log.error(f"Generate-and-post failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        session.close()
