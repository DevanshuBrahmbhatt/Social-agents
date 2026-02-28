"""SQLite database models for multi-user support."""

import json
import sqlite3
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

import config

Base = declarative_base()
engine = create_engine(config.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Auth — Twitter is the identity provider
    twitter_user_id = Column(String, unique=True, nullable=True)  # Twitter's unique user ID
    twitter_oauth2_access_token = Column(String, nullable=True)  # OAuth 2.0 (login only)
    twitter_oauth2_refresh_token = Column(String, nullable=True)

    # API Keys (user provides their own)
    anthropic_api_key = Column(String, nullable=True)
    perplexity_api_key = Column(String, nullable=True)

    # Twitter Developer Credentials (user provides, for posting via OAuth 1.0a)
    twitter_api_key = Column(String, nullable=True)
    twitter_api_secret = Column(String, nullable=True)
    twitter_access_token = Column(String, nullable=True)
    twitter_access_token_secret = Column(String, nullable=True)
    twitter_username = Column(String, nullable=True)

    # Role
    is_owner = Column(Boolean, default=False)

    # Relationships
    settings = relationship("Settings", back_populates="user", uselist=False)
    tweets = relationship("TweetHistory", back_populates="user", order_by="TweetHistory.posted_at.desc()")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    topics = Column(Text, default='["AI", "funding", "dev tools", "startups"]')
    tweet_frequency = Column(Integer, default=1)
    schedule_times = Column(Text, default='["09:00"]')
    timezone = Column(String, default="America/Los_Angeles")
    tweet_style = Column(String, default="founder-focused")

    user = relationship("User", back_populates="settings")

    def get_topics(self) -> list[str]:
        return json.loads(self.topics) if self.topics else []

    def set_topics(self, topics: list[str]):
        self.topics = json.dumps(topics)

    def get_schedule_times(self) -> list[str]:
        return json.loads(self.schedule_times) if self.schedule_times else []

    def set_schedule_times(self, times: list[str]):
        self.schedule_times = json.dumps(times)


class TweetHistory(Base):
    __tablename__ = "tweet_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    tweet_text = Column(Text)
    tweet_id = Column(String, nullable=True)  # Twitter's tweet ID
    story_title = Column(String, nullable=True)
    story_url = Column(String, nullable=True)
    chart_path = Column(String, nullable=True)
    posted_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="posted")  # posted | failed | scheduled

    user = relationship("User", back_populates="tweets")


def upgrade_db():
    """Add new columns to existing tables (lightweight migration for SQLite)."""
    db_path = config.PROJECT_ROOT / "db.sqlite3"
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get existing columns in users table
    cursor.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("twitter_user_id", "TEXT"),
        ("twitter_oauth2_access_token", "TEXT"),
        ("twitter_oauth2_refresh_token", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()


def init_db():
    """Create all tables and run migrations."""
    Base.metadata.create_all(engine)
    upgrade_db()


def get_or_create_owner() -> User:
    """Get or create the owner user from .env credentials."""
    session = SessionLocal()
    try:
        owner = session.query(User).filter_by(is_owner=True).first()
        if not owner:
            owner = User(
                is_owner=True,
                anthropic_api_key=config.ANTHROPIC_API_KEY,
                perplexity_api_key=config.PERPLEXITY_API_KEY,
                twitter_api_key=config.TWITTER_API_KEY,
                twitter_api_secret=config.TWITTER_API_SECRET,
                twitter_access_token=config.TWITTER_ACCESS_TOKEN,
                twitter_access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
                twitter_username="owner",
            )
            session.add(owner)
            session.flush()

            # Default settings
            settings = Settings(user_id=owner.id)
            session.add(settings)
            session.commit()
            session.refresh(owner)
        return owner
    finally:
        session.close()
