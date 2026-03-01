"""FastAPI web application — dashboard, API endpoints, and auth."""

import json
import logging
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
)
from core.news_fetcher import fetch_all_stories, deep_research_story
from core.tweet_generator import pick_best_story, generate_tweet
from core.chart_generator import generate_chart
from core.twitter_poster import post_tweet, post_tweet_dry_run

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
        return RedirectResponse(url="/", status_code=303)
    error = request.query_params.get("error", "")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
    })


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


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
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

        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user,
            "settings": settings,
            "tweets": tweets,
            "topics_list": settings.get_topics() if settings else [],
            "schedule_times": settings.get_schedule_times() if settings else ["09:00"],
            "agent_running": agent_running,
            "next_run": next_run,
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

        story = pick_best_story(stories, api_key=user.anthropic_api_key, recent_titles=recent_titles)
        research = deep_research_story(story, api_key=user.perplexity_api_key)
        result = generate_tweet(story, research, api_key=user.anthropic_api_key)

        # Always generate chart (mandatory)
        chart_path = generate_chart(result.get("chart_data", {"should_chart": True}))
        chart_url = None
        if chart_path:
            from pathlib import Path
            chart_url = f"/charts/{Path(chart_path).name}"

        return JSONResponse({
            "tweet": result["tweet"],
            "story_title": result.get("story_title", ""),
            "story_url": result.get("story_url", ""),
            "chart_url": chart_url,
            "chars": len(result["tweet"]),
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
    chart_url: str = Form(""),
):
    session = SessionLocal()
    try:
        user = session.query(User).get(current_user.id)
        if not user:
            return JSONResponse({"error": "No user found"}, status_code=400)

        if not tweet_text:
            return JSONResponse({"error": "Tweet text is empty"}, status_code=400)

        if not user.twitter_access_token:
            return JSONResponse({"error": "Twitter developer credentials not configured"}, status_code=400)

        # Convert chart URL to file path
        chart_path = None
        if chart_url:
            from pathlib import Path
            chart_name = Path(chart_url).name
            chart_path = str(config.CHARTS_DIR / chart_name)

        response = post_tweet(
            text=tweet_text,
            image_path=chart_path,
            api_key=user.twitter_api_key,
            api_secret=user.twitter_api_secret,
            access_token=user.twitter_access_token,
            access_token_secret=user.twitter_access_token_secret,
        )

        # Save to history
        history = TweetHistory(
            user_id=user.id,
            tweet_text=tweet_text,
            tweet_id=str(response.data["id"]),
            chart_path=chart_path,
            status="posted",
        )
        session.add(history)
        session.commit()

        return JSONResponse({
            "status": "ok",
            "tweet_id": str(response.data["id"]),
            "message": "Tweet posted!",
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
