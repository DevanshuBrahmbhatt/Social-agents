# Project: TweetAgent v2

## Deployment Defaults
- **Domain**: dagent.shop
- **Subdomain for this app**: twitter.dagent.shop
- **AWS Account**: tirthoo7.signin.aws.amazon.com (IAM user: jobagent-admin)
- **AWS Credits**: ~$9000 available
- **Convention**: Every new agent gets its own subdomain: `<name>.dagent.shop`

## Deployment Pattern
- Host: AWS EC2 (Ubuntu 22.04, t3.small)
- Containerized: Docker + Docker Compose
- SSL: Caddy reverse proxy (auto HTTPS via Let's Encrypt)
- Subdomains: `twitter.dagent.shop`, future agents get `<name>.dagent.shop`

## Tech Stack
- Python 3.12, FastAPI, SQLAlchemy + SQLite, APScheduler
- Anthropic Claude (sonnet), Perplexity Sonar Pro
- Tweepy (Twitter OAuth 1.0a posting + OAuth 2.0 login)
- Plotly + Kaleido (charts), feedparser (RSS)
- News: HackerNews, TechCrunch, Reddit, Business Wire

## Key Conventions
- "Bring Your Own Keys" model — users add their own API keys
- No secrets in repo — .env is gitignored
- Docker deployment with Caddy for SSL
