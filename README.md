# TweetAgent v2

**AI-powered Twitter/X automation for builders, founders & startup enthusiasts.**

TweetAgent autonomously finds trending tech news, researches it deeply, writes insightful long-form posts with data-backed charts, and publishes them on your schedule — all hands-free.

Built on a **"Bring Your Own Keys"** model: you host the agent, users bring their own API keys. Zero cost to you.

---

## What It Does

```
Trending News → Deep Research → Long-Form Post → Data Chart → Published to X
```

Every cycle, TweetAgent runs this pipeline:

1. **Fetches news** from HackerNews (top stories, score ≥ 50) and TechCrunch RSS (Venture + Startups)
2. **Picks the best story** using Claude — looks for market shifts, funding rounds, new tools, breakthroughs
3. **Deep researches** the story with Perplexity AI — extracts funding amounts, valuations, TAM, competitor data, real numbers
4. **Generates a long-form post** (800–2000 chars) with a builder-focused narrative: what happened → why it matters → what to build → bigger picture
5. **Creates a data chart** (Plotly, dark theme, Twitter-optimized) with relevant metrics from the research
6. **Posts to Twitter/X** with the chart attached — or queues it for your review first

---

## Features

- **Long-form posts** — 800–2000 characters targeting X Pro, not generic 280-char tweets
- **Mandatory charts** — every post includes a dark-theme data visualization (bar, line, or comparison)
- **Deep research** — Perplexity Sonar Pro provides real numbers, not hallucinated stats
- **Builder persona** — writes like a startup enthusiast, not a news bot or VC partner
- **Multi-user dashboard** — login with Twitter, each user gets their own agent
- **Bring Your Own Keys** — users provide their own Anthropic, Perplexity, and Twitter credentials
- **Flexible scheduling** — set posting times, timezone, frequency (1–5x/day)
- **Preview before posting** — generate a preview, edit it, then post manually or let the agent auto-post
- **Tweet history** — track everything that was posted with links back to X
- **Start/stop agent** — one-click control over your automation
- **CLI mode** — run a single cycle from the terminal (`python cli.py --dry-run`)
- **Docker-ready** — deploy anywhere with one command

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12, FastAPI, Uvicorn |
| **AI** | Anthropic Claude (claude-sonnet-4-20250514), Perplexity Sonar Pro |
| **Database** | SQLAlchemy + SQLite |
| **Scheduler** | APScheduler (per-user cron jobs) |
| **Charts** | Plotly + Kaleido (PNG export) |
| **Twitter** | Tweepy (OAuth 1.0a posting + OAuth 2.0 PKCE login) |
| **News** | HackerNews API, TechCrunch RSS (feedparser) |
| **Auth** | Twitter OAuth 2.0 PKCE, signed cookies (itsdangerous) |
| **Frontend** | Jinja2 templates, TailwindCSS, vanilla JS |
| **Deployment** | Docker, Docker Compose, EC2 deploy script |

---

## Project Structure

```
Social-agents/
├── main.py                    # App entry — starts FastAPI server
├── cli.py                     # CLI entry — run one pipeline cycle
├── config.py                  # Central config (env vars, constants)
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Docker image (Python 3.12 + Chromium)
├── docker-compose.yml         # Single-service compose config
├── deploy.sh                  # EC2 one-click deploy script
├── .env.example               # Template for environment variables
│
├── core/                      # Pipeline logic
│   ├── news_fetcher.py        # HackerNews + TechCrunch + Perplexity research
│   ├── tweet_generator.py     # Claude story picker + post writer
│   ├── chart_generator.py     # Plotly chart creation (always mandatory)
│   └── twitter_poster.py      # Tweepy hybrid posting (v1.1 media + v2 tweet)
│
└── web/                       # Web application
    ├── app.py                 # FastAPI routes & API endpoints
    ├── auth.py                # Twitter OAuth 2.0 PKCE + session cookies
    ├── database.py            # SQLAlchemy models (User, Settings, TweetHistory)
    ├── scheduler.py           # APScheduler per-user job management
    └── templates/
        ├── login.html         # Landing page with Twitter login
        └── index.html         # Dashboard (preview, schedule, history, keys)
```

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)
- Twitter/X developer credentials ([developer.x.com](https://developer.x.com))
- (Optional) [Perplexity API key](https://docs.perplexity.ai/) for deep research

### 1. Clone & install

```bash
git clone https://github.com/DevanshuBrahmbhatt/Social-agents.git
cd Social-agents

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Required — your API keys
ANTHROPIC_API_KEY=sk-ant-...
PERPLEXITY_API_KEY=pplx-...          # Optional but recommended

# Required — Twitter OAuth 1.0a (for posting tweets)
TWITTER_API_KEY=your_consumer_key
TWITTER_API_SECRET=your_consumer_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret

# Required for multi-user login — Twitter OAuth 2.0
TWITTER_CLIENT_ID=your_oauth2_client_id
TWITTER_CLIENT_SECRET=your_oauth2_client_secret
TWITTER_REDIRECT_URI=http://localhost:8000/auth/callback
```

### 3. Run

**Web dashboard:**
```bash
python main.py
# Open http://localhost:8000
```

**CLI (single run, no posting):**
```bash
python cli.py --dry-run
```

**CLI (generate and post):**
```bash
python cli.py
```

---

## Getting Your API Keys

### Anthropic (Claude)

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account or sign in
3. Navigate to **API Keys** → **Create Key**
4. Copy the key (starts with `sk-ant-`)

### Perplexity (Optional)

1. Go to [docs.perplexity.ai](https://docs.perplexity.ai/)
2. Sign up and navigate to API settings
3. Generate an API key (starts with `pplx-`)
4. If skipped, the agent uses Claude-only research (still works, less data-rich)

### Twitter/X Developer Credentials

You need **two sets** of Twitter credentials:

#### For Posting (OAuth 1.0a) — 4 keys

1. Go to [developer.x.com](https://developer.x.com) → Developer Portal
2. Create a **Project** and an **App** inside it
3. In your app settings, set **User authentication** to:
   - **App permissions**: Read and Write
   - **Type**: Web App
4. Go to **Keys and Tokens** tab:
   - Under **Consumer Keys** → Generate → copy **API Key** and **API Secret**
   - Under **Authentication Tokens** → Generate → copy **Access Token** and **Access Token Secret**

These 4 values go into your `.env` as:
```
TWITTER_API_KEY=        (Consumer Key / API Key)
TWITTER_API_SECRET=     (Consumer Secret / API Secret)
TWITTER_ACCESS_TOKEN=   (Access Token)
TWITTER_ACCESS_TOKEN_SECRET= (Access Token Secret)
```

#### For Login (OAuth 2.0) — 2 keys (multi-user mode)

1. In the same app on [developer.x.com](https://developer.x.com):
2. Go to **Settings** → **User authentication settings** → **Set up**
3. Enable **OAuth 2.0**
4. Set **Callback URL**: `http://localhost:8000/auth/callback` (or your server URL)
5. Set **Website URL**: your domain or `http://localhost:8000`
6. Save → copy **Client ID** and **Client Secret**

These go into `.env` as:
```
TWITTER_CLIENT_ID=
TWITTER_CLIENT_SECRET=
TWITTER_REDIRECT_URI=http://localhost:8000/auth/callback
```

---

## Multi-User Mode (Bring Your Own Keys)

TweetAgent supports multiple users, each with their own API keys and isolated data.

### How It Works

1. **User visits the app** → sees a login page
2. **Clicks "Login with Twitter"** → Twitter OAuth 2.0 PKCE flow → returns with verified identity
3. **Enters their own API keys** in the dashboard:
   - Anthropic API key (for Claude)
   - Perplexity API key (optional, for deep research)
   - Twitter developer credentials (4 keys — for posting to their own account)
4. **Configures topics and schedule** → starts the agent
5. **Agent runs autonomously** on their schedule, posting to THEIR Twitter account using THEIR keys

### Cost Model

| Service | Cost | Who Pays |
|---|---|---|
| Hosting (EC2/VPS) | ~$5–10/month | You (the host) |
| Anthropic API | ~$0.02/tweet | Each user pays their own |
| Perplexity API | Free tier or ~$5/month | Each user (optional) |
| Twitter API | Free (1,500 tweets/month) | Each user |

**You provide the agent. Users provide the keys. Everyone wins.**

### Data Isolation

- Each user only sees their own tweets, settings, and API keys
- API keys are stored per-user in the database
- Scheduler runs independent jobs per user
- No shared API quotas

---

## Deployment

### Docker Compose (Recommended)

```bash
# Clone the repo
git clone https://github.com/DevanshuBrahmbhatt/Social-agents.git
cd Social-agents

# Set up environment
cp .env.example .env
nano .env                    # Add your API keys

# Build and run
docker compose up -d --build

# View logs
docker compose logs -f
```

App will be available at `http://localhost:8000`

### AWS EC2 (One-Click Script)

1. **Launch an EC2 instance:**
   - AMI: Ubuntu 22.04 LTS
   - Instance type: `t3.small` (2 vCPU, 2GB RAM)
   - Storage: 20 GB gp3
   - Security group: Allow TCP `22` (SSH) and TCP `8000` (App)

2. **SSH in and deploy:**
   ```bash
   ssh -i your-key.pem ubuntu@<your-ec2-ip>

   git clone https://github.com/DevanshuBrahmbhatt/Social-agents.git
   cd Social-agents
   bash deploy.sh
   ```

3. **Configure:**
   ```bash
   cp .env.example .env
   nano .env                   # Add your API keys
   sudo docker compose up -d --build
   ```

4. **Visit:** `http://<your-ec2-ip>:8000`

### Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key (owner's default) |
| `PERPLEXITY_API_KEY` | No | Perplexity API key (owner's default) |
| `TWITTER_API_KEY` | Yes | Twitter Consumer Key (owner's posting) |
| `TWITTER_API_SECRET` | Yes | Twitter Consumer Secret (owner's posting) |
| `TWITTER_ACCESS_TOKEN` | Yes | Twitter Access Token (owner's posting) |
| `TWITTER_ACCESS_TOKEN_SECRET` | Yes | Twitter Access Token Secret (owner's posting) |
| `TWITTER_CLIENT_ID` | For multi-user | Twitter OAuth 2.0 Client ID (login) |
| `TWITTER_CLIENT_SECRET` | For multi-user | Twitter OAuth 2.0 Client Secret (login) |
| `TWITTER_REDIRECT_URI` | For multi-user | OAuth callback URL |
| `SECRET_KEY` | No | Session signing key (auto-derived if not set) |

---

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/login` | Login page |
| `GET` | `/auth/twitter` | Start Twitter OAuth 2.0 PKCE login |
| `GET` | `/auth/callback` | OAuth callback handler |
| `GET` | `/auth/owner-login` | Quick owner login (dev mode) |
| `GET` | `/auth/logout` | Logout and clear session |

### Dashboard & Config
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Main dashboard |
| `POST` | `/api/settings` | Save topics, schedule, timezone, style |
| `POST` | `/api/setup` | Save API keys |

### Agent Control
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/agent/start` | Start automated posting |
| `POST` | `/api/agent/stop` | Stop automated posting |
| `GET` | `/api/agent/status` | Agent status + next run time |

### Tweets
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/generate-preview` | Generate a preview (no posting) |
| `POST` | `/api/post-now` | Post tweet immediately |
| `GET` | `/api/history` | Get last 50 tweets |

---

## How the Pipeline Works

```
┌─────────────────────────────────────────────────────────┐
│                    NEWS FETCHING                         │
│                                                         │
│   HackerNews API ──┐                                    │
│   (top 30, score≥50)├──→ Deduplicated Story Pool        │
│   TechCrunch RSS ──┘    (~20-30 stories)                │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                   STORY SELECTION                        │
│                                                         │
│   Claude picks the most compelling story                │
│   Prioritizes: funding rounds, new tools, market shifts │
│   Skips: routine updates, PR fluff, opinion pieces      │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                   DEEP RESEARCH                          │
│                                                         │
│   Perplexity Sonar Pro researches the story             │
│   Extracts: funding amounts, valuations, TAM,           │
│   competitor data, growth metrics, real numbers          │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                  POST GENERATION                         │
│                                                         │
│   Claude writes a long-form post (800-2000 chars)       │
│   Structure:                                            │
│     → What happened (the news)                          │
│     → Why it matters (market context)                   │
│     → What it means (for builders)                      │
│     → What to build (product ideas)                     │
│     → Bigger picture (industry trend)                   │
│                                                         │
│   Also outputs chart_data (type, title, data points)    │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                  CHART GENERATION                         │
│                                                         │
│   Plotly creates a dark-theme chart (1200x675px)        │
│   Types: bar, line, comparison                          │
│   Auto-formats: $1M, $1B, etc.                          │
│   Exported as PNG via Kaleido                           │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                  PUBLISH TO X                            │
│                                                         │
│   1. Upload chart image (Twitter API v1.1)              │
│   2. Create tweet with media (Twitter API v2)           │
│   3. Save to database (TweetHistory)                    │
└─────────────────────────────────────────────────────────┘
```

---

## CLI Usage

```bash
# Dry run — generate post + chart, don't publish
python cli.py --dry-run

# Full run — generate and post to Twitter
python cli.py
```

---

## Useful Docker Commands

```bash
# Start in background
docker compose up -d --build

# View live logs
docker compose logs -f

# Restart
docker compose restart

# Stop
docker compose down

# Rebuild after code changes
docker compose up -d --build
```

---

## License

MIT

---

**Built with Claude, Perplexity, and a love for building things.**
