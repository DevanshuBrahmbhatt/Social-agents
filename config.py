import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (not CWD)
PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env", override=True)

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# Twitter OAuth 2.0 (for login identity)
TWITTER_CLIENT_ID = os.getenv("TWITTER_CLIENT_ID", "")
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET", "")
TWITTER_REDIRECT_URI = os.getenv("TWITTER_REDIRECT_URI", "http://localhost:8000/auth/callback")

# Session security (optional — auto-derived if not set)
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Owner login password (REQUIRED in production — disables owner login if empty)
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "")

# News source URLs — HackerNews
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"

# News source URLs — TechCrunch RSS (multiple categories)
TC_FEEDS = [
    ("venture", "https://techcrunch.com/category/venture/feed/"),
    ("startups", "https://techcrunch.com/category/startups/feed/"),
    ("ai", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("apps", "https://techcrunch.com/category/apps/feed/"),
]
# Legacy aliases
TC_FUNDING_RSS = TC_FEEDS[0][1]
TC_STARTUPS_RSS = TC_FEEDS[1][1]

# News source URLs — Reddit (public JSON API, no auth)
REDDIT_SUBREDDITS = [
    "technology",
    "startups",
    "programming",
    "artificial",
    "machinelearning",
]
REDDIT_USER_AGENT = "TweetAgent/2.0 (by /u/tweetagent-bot)"

# News source URLs — Business Wire RSS
BW_TECH_RSS = "https://feed.businesswire.com/rss/home/?rss=G1QFDERJhkQ%3D"

# Settings
MAX_HN_STORIES = 30
MIN_HN_SCORE = 50
MAX_REDDIT_POSTS = 15
MIN_REDDIT_SCORE = 100
CLAUDE_MODEL = "claude-sonnet-4-20250514"
PERPLEXITY_MODEL = "sonar-pro"

# Database
DATABASE_URL = f"sqlite:///{PROJECT_ROOT / 'db.sqlite3'}"

# Chart output
CHARTS_DIR = PROJECT_ROOT / "charts"
CHARTS_DIR.mkdir(exist_ok=True)
