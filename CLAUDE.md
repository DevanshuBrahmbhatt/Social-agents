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

## Shared API Keys
- **Anthropic API Key**: stored in `.env` (never commit to repo)
- **External API Key** (for inter-agent communication): stored in `.env` as `EXTERNAL_API_KEY`

## MCP Server
- **File**: `mcp_server.py` in project root
- **Tools**: `post_content`, `post_tweet`, `post_to_all`
- **Auth**: `X-API-Key` header with `EXTERNAL_API_KEY`
- **Endpoint**: `POST /api/external-post`
- **Dashboard section**: "Agent MCP Server" on the main page shows config snippet

## Key Conventions
- "Bring Your Own Keys" model — users add their own API keys
- No secrets in repo — .env is gitignored
- Docker deployment with Caddy for SSL

## Agent Architecture Convention
- Every agent we build MUST have an MCP server (`mcp_server.py`) that exposes its core capabilities
- Every agent's dashboard MUST include an "Agent MCP Server" section on the front page showing:
  - REST API endpoint info
  - MCP config snippet (for Claude Code / Claude Desktop)
  - Available tools list
- This allows any other agent or human to connect and use the agent's capabilities
- Inter-agent communication uses REST API with shared `X-API-Key` auth
- MCP servers use stdio transport and wrap the REST API via httpx
