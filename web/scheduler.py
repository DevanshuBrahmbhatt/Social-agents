"""APScheduler-based job management for scheduled tweet posting."""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from web.database import SessionLocal, User, Settings, TweetHistory
from core.news_fetcher import fetch_all_stories, deep_research_story
from core.tweet_generator import pick_best_story, generate_tweet
from core.chart_generator import generate_chart
from core.twitter_poster import post_tweet
from core.linkedin_poster import post_linkedin
from web.auth import refresh_linkedin_token_sync

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Track which users have their agent running
_active_users: set[int] = set()


def run_scheduled_tweet(user_id: int):
    """Execute the full tweet pipeline for a specific user."""
    # Check if user agent is still active
    if user_id not in _active_users:
        log.info(f"Agent for user {user_id} is stopped — skipping scheduled tweet")
        return

    session = SessionLocal()
    try:
        user = session.query(User).get(user_id)
        if not user:
            log.error(f"User {user_id} not found")
            return

        log.info(f"Running scheduled tweet for user {user.twitter_username or user.id}")

        # Get recent tweet titles to avoid repeating topics
        recent_tweets = (
            session.query(TweetHistory)
            .filter_by(user_id=user_id, status="posted")
            .order_by(TweetHistory.posted_at.desc())
            .limit(10)
            .all()
        )
        recent_titles = [t.story_title or t.tweet_text[:80] for t in recent_tweets if t.story_title or t.tweet_text]

        # Fetch stories
        stories = fetch_all_stories()
        if not stories:
            log.error("No stories found")
            return

        # Pick best story (avoiding recently covered topics)
        story = pick_best_story(stories, api_key=user.anthropic_api_key, recent_titles=recent_titles)

        # Deep research
        research = deep_research_story(story, api_key=user.perplexity_api_key)

        # Generate tweet (long-form)
        result = generate_tweet(story, research, api_key=user.anthropic_api_key)

        # Generate chart (always mandatory now)
        chart_path = generate_chart(result.get("chart_data", {"should_chart": True}))

        # Post to Twitter
        creds = dict(
            api_key=user.twitter_api_key,
            api_secret=user.twitter_api_secret,
            access_token=user.twitter_access_token,
            access_token_secret=user.twitter_access_token_secret,
        )
        try:
            response = post_tweet(result["tweet"], chart_path, **creds)
            history = TweetHistory(
                user_id=user.id,
                tweet_text=result["tweet"],
                tweet_id=str(response.data["id"]),
                story_title=result.get("story_title"),
                story_url=result.get("story_url"),
                chart_path=chart_path,
                status="posted",
                platform="twitter",
            )
            session.add(history)
            log.info(f"Scheduled tweet posted: {response.data['id']}")
        except Exception as e:
            log.error(f"Twitter post failed for user {user_id}: {e}")
            history = TweetHistory(
                user_id=user_id,
                tweet_text=str(e)[:500],
                status="failed",
                platform="twitter",
            )
            session.add(history)

        # Post to LinkedIn (if connected and enabled)
        settings = user.settings
        linkedin_enabled = getattr(settings, "linkedin_posting_enabled", True) if settings else True
        if user.linkedin_access_token and user.linkedin_person_urn and linkedin_enabled:
            try:
                # Refresh token if near expiry
                refresh_linkedin_token_sync(user_id)

                li_text = result.get("linkedin_post", result["tweet"])
                li_response = post_linkedin(
                    text=li_text,
                    image_path=chart_path,
                    person_urn=user.linkedin_person_urn,
                    access_token=user.linkedin_access_token,
                )
                li_history = TweetHistory(
                    user_id=user.id,
                    tweet_text=li_text,
                    linkedin_post_id=li_response.get("id", ""),
                    story_title=result.get("story_title"),
                    story_url=result.get("story_url"),
                    chart_path=chart_path,
                    status="posted",
                    platform="linkedin",
                )
                session.add(li_history)
                log.info(f"Scheduled LinkedIn post created: {li_response.get('id')}")
            except Exception as e:
                log.error(f"LinkedIn post failed for user {user_id}: {e}")
                li_history = TweetHistory(
                    user_id=user_id,
                    tweet_text=str(e)[:500],
                    status="failed",
                    platform="linkedin",
                )
                session.add(li_history)

        session.commit()

    except Exception as e:
        log.error(f"Scheduled tweet pipeline failed for user {user_id}: {e}")
        # Log failure
        try:
            history = TweetHistory(
                user_id=user_id,
                tweet_text=str(e)[:500],
                status="failed",
                platform="twitter",
            )
            session.add(history)
            session.commit()
        except Exception:
            pass
    finally:
        session.close()


def setup_user_schedule(user_id: int, schedule_times: list[str], timezone: str = "America/Los_Angeles"):
    """Set up cron jobs for a user based on their schedule."""
    # Remove existing jobs for this user
    existing_jobs = [j for j in scheduler.get_jobs() if j.id.startswith(f"user_{user_id}_")]
    for job in existing_jobs:
        scheduler.remove_job(job.id)

    # Add new jobs
    for i, time_str in enumerate(schedule_times):
        hour, minute = time_str.split(":")
        job_id = f"user_{user_id}_{i}"
        scheduler.add_job(
            run_scheduled_tweet,
            trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=timezone),
            args=[user_id],
            id=job_id,
            replace_existing=True,
        )
        log.info(f"Scheduled job {job_id} at {time_str} ({timezone})")


def start_user_agent(user_id: int):
    """Start the agent for a specific user."""
    _active_users.add(user_id)

    # Load their schedule
    session = SessionLocal()
    try:
        user = session.query(User).get(user_id)
        if user and user.settings and user.twitter_access_token:
            times = user.settings.get_schedule_times()
            tz = user.settings.timezone
            if times:
                setup_user_schedule(user.id, times, tz)
                log.info(f"Agent started for user {user_id}")
                return True
        log.warning(f"Cannot start agent for user {user_id} — missing settings or Twitter auth")
        return False
    finally:
        session.close()


def stop_user_agent(user_id: int):
    """Stop the agent for a specific user."""
    _active_users.discard(user_id)

    # Remove their scheduled jobs
    existing_jobs = [j for j in scheduler.get_jobs() if j.id.startswith(f"user_{user_id}_")]
    for job in existing_jobs:
        scheduler.remove_job(job.id)

    log.info(f"Agent stopped for user {user_id}")


def is_user_agent_running(user_id: int) -> bool:
    """Check if a user's agent is currently running."""
    return user_id in _active_users


def get_user_next_run(user_id: int) -> str | None:
    """Get the next scheduled run time for a user."""
    jobs = [j for j in scheduler.get_jobs() if j.id.startswith(f"user_{user_id}_")]
    if not jobs:
        return None
    next_times = [j.next_run_time for j in jobs if j.next_run_time]
    if not next_times:
        return None
    soonest = min(next_times)
    return soonest.strftime("%I:%M %p %Z")


def load_all_schedules():
    """Load schedules for all users from the database."""
    session = SessionLocal()
    try:
        users = session.query(User).all()
        for user in users:
            if user.settings and user.twitter_access_token:
                times = user.settings.get_schedule_times()
                tz = user.settings.timezone
                if times:
                    setup_user_schedule(user.id, times, tz)
                    _active_users.add(user.id)  # Auto-start on boot
    finally:
        session.close()


def start_scheduler():
    """Start the background scheduler."""
    if not scheduler.running:
        scheduler.start()
        load_all_schedules()
        log.info("Scheduler started")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        log.info("Scheduler stopped")
