"""Authentication: Twitter OAuth 2.0 PKCE login + cookie sessions."""

import base64
import hashlib
import logging
import secrets
import urllib.parse
from datetime import datetime

import httpx
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import config
from web.database import SessionLocal, User, Settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Secret key for signing cookies
# ---------------------------------------------------------------------------
# Derived from ANTHROPIC_API_KEY so it's stable across restarts.
# Production deployments should set SECRET_KEY in .env for full control.
_raw_secret = config.SECRET_KEY or config.ANTHROPIC_API_KEY or "tweetagent-dev-secret"
SECRET_KEY = hashlib.sha256(_raw_secret.encode()).hexdigest()

_serializer = URLSafeTimedSerializer(SECRET_KEY)
COOKIE_NAME = "tweetagent_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


# ---------------------------------------------------------------------------
# Cookie session helpers
# ---------------------------------------------------------------------------

def _is_production() -> bool:
    """Detect production mode from redirect URI (HTTPS = production)."""
    return config.TWITTER_REDIRECT_URI.startswith("https://")


def create_session_cookie(response, user_id: int):
    """Set a signed session cookie."""
    token = _serializer.dumps({"uid": user_id})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_production(),
    )


def clear_session_cookie(response):
    """Remove the session cookie."""
    response.delete_cookie(key=COOKIE_NAME)


def get_user_id_from_cookie(request: Request) -> int | None:
    """Extract user_id from signed cookie. Returns None if invalid."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


# ---------------------------------------------------------------------------
# FastAPI dependency: get current user
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> User:
    """Extract the authenticated user from the session cookie.

    - API routes (/api/*) → return 401 JSON
    - Page routes → redirect to /login
    """
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    session = SessionLocal()
    try:
        user = session.query(User).get(user_id)
        if user is None:
            if request.url.path.startswith("/api/"):
                raise HTTPException(status_code=401, detail="Not authenticated")
            raise HTTPException(status_code=302, headers={"Location": "/login"})
        session.expunge(user)
        return user
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Twitter OAuth 2.0 PKCE — for LOGIN / identity only
# ---------------------------------------------------------------------------

# In-memory store for PKCE verifiers (keyed by state param)
_pkce_store: dict[str, dict] = {}


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _cleanup_pkce_store():
    """Remove PKCE entries older than 10 minutes."""
    now = datetime.utcnow()
    expired = [
        k for k, v in _pkce_store.items()
        if (now - v["created_at"]).total_seconds() > 600
    ]
    for k in expired:
        _pkce_store.pop(k, None)


async def twitter_login_start(request: Request):
    """Start Twitter OAuth 2.0 PKCE flow for login."""
    if not config.TWITTER_CLIENT_ID:
        return JSONResponse(
            {"error": "TWITTER_CLIENT_ID not configured. Add it to .env."},
            status_code=500,
        )

    _cleanup_pkce_store()

    state = secrets.token_urlsafe(32)
    verifier, challenge = _generate_pkce()

    _pkce_store[state] = {
        "verifier": verifier,
        "created_at": datetime.utcnow(),
    }

    params = {
        "response_type": "code",
        "client_id": config.TWITTER_CLIENT_ID,
        "redirect_uri": config.TWITTER_REDIRECT_URI,
        "scope": "tweet.read users.read offline.access",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"https://twitter.com/i/oauth2/authorize?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=303)


async def twitter_login_callback(request: Request):
    """Handle Twitter OAuth 2.0 callback — create/find user, set session cookie."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return RedirectResponse(url=f"/login?error=Twitter+auth+failed:+{error}", status_code=303)

    if not code or not state:
        return RedirectResponse(url="/login?error=Invalid+callback+parameters", status_code=303)

    # Retrieve and consume the PKCE verifier
    pkce_data = _pkce_store.pop(state, None)
    if not pkce_data:
        return RedirectResponse(url="/login?error=Invalid+or+expired+state", status_code=303)

    verifier = pkce_data["verifier"]

    try:
        # Exchange code for access token
        # Twitter OAuth 2.0 confidential clients require Basic Auth header
        _basic_auth = base64.b64encode(
            f"{config.TWITTER_CLIENT_ID}:{config.TWITTER_CLIENT_SECRET}".encode()
        ).decode()

        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://api.twitter.com/2/oauth2/token",
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "client_id": config.TWITTER_CLIENT_ID,
                    "redirect_uri": config.TWITTER_REDIRECT_URI,
                    "code_verifier": verifier,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {_basic_auth}",
                },
            )
            token_data = token_resp.json()

        if "access_token" not in token_data:
            log.error(f"Twitter token exchange failed: {token_data}")
            error_desc = token_data.get("error_description", "Token exchange failed")
            return RedirectResponse(url=f"/login?error={urllib.parse.quote(error_desc)}", status_code=303)

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")

        # Fetch the user's Twitter profile
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            me_data = me_resp.json()

        twitter_user_id = me_data.get("data", {}).get("id")
        twitter_username = me_data.get("data", {}).get("username", "unknown")

        if not twitter_user_id:
            log.error(f"Failed to get Twitter user info: {me_data}")
            return RedirectResponse(url="/login?error=Failed+to+get+Twitter+profile", status_code=303)

        # Find or create user
        db_session = SessionLocal()
        try:
            user = db_session.query(User).filter_by(twitter_user_id=twitter_user_id).first()

            if user:
                # Existing user — update OAuth tokens
                user.twitter_oauth2_access_token = access_token
                user.twitter_oauth2_refresh_token = refresh_token
                user.twitter_username = twitter_username
            else:
                # New user — create account
                user = User(
                    twitter_user_id=twitter_user_id,
                    twitter_username=twitter_username,
                    twitter_oauth2_access_token=access_token,
                    twitter_oauth2_refresh_token=refresh_token,
                    is_owner=False,
                )
                db_session.add(user)
                db_session.flush()

                # Create default settings
                settings = Settings(user_id=user.id)
                db_session.add(settings)

            db_session.commit()
            user_id = user.id
        finally:
            db_session.close()

        # Set session cookie and redirect to dashboard
        response = RedirectResponse(url="/", status_code=303)
        create_session_cookie(response, user_id)
        return response

    except Exception as e:
        log.error(f"Twitter OAuth callback error: {e}")
        return RedirectResponse(
            url=f"/login?error={urllib.parse.quote(str(e)[:100])}",
            status_code=303,
        )


async def owner_login(request: Request):
    """Password-protected owner login.

    Requires OWNER_PASSWORD in .env. Disabled if no password is set.
    Only accepts POST with correct password — never auto-logs in.
    """
    # Block if no password is configured (production safety)
    if not config.OWNER_PASSWORD:
        return RedirectResponse(
            url="/login?error=Owner+login+disabled.+Set+OWNER_PASSWORD+in+.env+or+use+Twitter+OAuth.",
            status_code=303,
        )

    # Must be POST
    if request.method != "POST":
        return RedirectResponse(url="/login?error=Invalid+request", status_code=303)

    # Parse form data
    form = await request.form()
    submitted_password = form.get("owner_password", "")

    # Constant-time comparison to prevent timing attacks
    import hmac
    if not hmac.compare_digest(submitted_password, config.OWNER_PASSWORD):
        return RedirectResponse(url="/login?error=Invalid+password", status_code=303)

    db_session = SessionLocal()
    try:
        owner = db_session.query(User).filter_by(is_owner=True).first()
        if not owner:
            return RedirectResponse(url="/login?error=No+owner+user+found", status_code=303)

        response = RedirectResponse(url="/", status_code=303)
        create_session_cookie(response, owner.id)
        return response
    finally:
        db_session.close()


async def logout(request: Request):
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# LinkedIn OAuth 2.0 — for connecting LinkedIn posting
# ---------------------------------------------------------------------------

# In-memory store for LinkedIn OAuth state
_linkedin_state_store: dict[str, dict] = {}


def _cleanup_linkedin_state():
    """Remove LinkedIn state entries older than 10 minutes."""
    now = datetime.utcnow()
    expired = [
        k for k, v in _linkedin_state_store.items()
        if (now - v["created_at"]).total_seconds() > 600
    ]
    for k in expired:
        _linkedin_state_store.pop(k, None)


async def linkedin_connect_start(request: Request):
    """Start LinkedIn OAuth 2.0 flow to connect LinkedIn posting.

    User must already be logged in (Twitter auth). This adds LinkedIn
    as an additional posting platform.
    """
    if not config.LINKEDIN_CLIENT_ID:
        return JSONResponse(
            {"error": "LINKEDIN_CLIENT_ID not configured. Add it to .env."},
            status_code=500,
        )

    # Must be logged in first
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    _cleanup_linkedin_state()

    state = secrets.token_urlsafe(32)
    _linkedin_state_store[state] = {
        "user_id": user_id,
        "created_at": datetime.utcnow(),
    }

    params = {
        "response_type": "code",
        "client_id": config.LINKEDIN_CLIENT_ID,
        "redirect_uri": config.LINKEDIN_REDIRECT_URI,
        "state": state,
        "scope": "openid profile w_member_social",
    }
    auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=303)


async def linkedin_connect_callback(request: Request):
    """Handle LinkedIn OAuth callback — store tokens on the existing user."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        error_desc = request.query_params.get("error_description", error)
        return RedirectResponse(
            url=f"/?error=LinkedIn+auth+failed:+{urllib.parse.quote(error_desc)}",
            status_code=303,
        )

    if not code or not state:
        return RedirectResponse(url="/?error=Invalid+LinkedIn+callback", status_code=303)

    state_data = _linkedin_state_store.pop(state, None)
    if not state_data:
        return RedirectResponse(url="/?error=Invalid+or+expired+LinkedIn+state", status_code=303)

    user_id = state_data["user_id"]

    try:
        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.LINKEDIN_REDIRECT_URI,
                    "client_id": config.LINKEDIN_CLIENT_ID,
                    "client_secret": config.LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_data = token_resp.json()

        if "access_token" not in token_data:
            log.error(f"LinkedIn token exchange failed: {token_data}")
            error_desc = token_data.get("error_description", "Token exchange failed")
            return RedirectResponse(
                url=f"/?error={urllib.parse.quote(error_desc)}",
                status_code=303,
            )

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 5184000)  # default 60 days

        # Calculate expiry datetime
        from datetime import timedelta
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Fetch LinkedIn user info via OpenID Connect userinfo endpoint
        async with httpx.AsyncClient() as client:
            userinfo_resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo = userinfo_resp.json()

        person_urn_id = userinfo.get("sub")  # This is the person ID for the URN
        linkedin_name = userinfo.get("name", "Unknown")

        if not person_urn_id:
            log.error(f"Failed to get LinkedIn user info: {userinfo}")
            return RedirectResponse(url="/?error=Failed+to+get+LinkedIn+profile", status_code=303)

        # Store on existing user
        db_session = SessionLocal()
        try:
            user = db_session.query(User).get(user_id)
            if user:
                user.linkedin_access_token = access_token
                user.linkedin_refresh_token = refresh_token
                user.linkedin_token_expires_at = expires_at
                user.linkedin_person_urn = person_urn_id
                user.linkedin_name = linkedin_name
                db_session.commit()
                log.info(f"LinkedIn connected for user {user_id}: {linkedin_name}")
            else:
                return RedirectResponse(url="/?error=User+not+found", status_code=303)
        finally:
            db_session.close()

        return RedirectResponse(url="/?success=LinkedIn+connected!", status_code=303)

    except Exception as e:
        log.error(f"LinkedIn OAuth callback error: {e}")
        return RedirectResponse(
            url=f"/?error={urllib.parse.quote(str(e)[:100])}",
            status_code=303,
        )


async def linkedin_disconnect(request: Request):
    """Disconnect LinkedIn by clearing tokens."""
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    db_session = SessionLocal()
    try:
        user = db_session.query(User).get(user_id)
        if user:
            user.linkedin_access_token = None
            user.linkedin_refresh_token = None
            user.linkedin_token_expires_at = None
            user.linkedin_person_urn = None
            user.linkedin_name = None
            db_session.commit()
            log.info(f"LinkedIn disconnected for user {user_id}")
    finally:
        db_session.close()

    return RedirectResponse(url="/", status_code=303)


def refresh_linkedin_token_sync(user_id: int) -> bool:
    """Refresh LinkedIn access token if expired or near-expiry.

    Synchronous version (uses requests) for use in APScheduler background threads.
    """
    import requests as req

    db_session = SessionLocal()
    try:
        user = db_session.query(User).get(user_id)
        if not user or not user.linkedin_refresh_token:
            return False

        # Check if token is near expiry (within 7 days)
        if user.linkedin_token_expires_at:
            days_until_expiry = (user.linkedin_token_expires_at - datetime.utcnow()).days
            if days_until_expiry > 7:
                return True  # Token still valid, no refresh needed

        resp = req.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": user.linkedin_refresh_token,
                "client_id": config.LINKEDIN_CLIENT_ID,
                "client_secret": config.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        data = resp.json()

        if "access_token" in data:
            from datetime import timedelta
            user.linkedin_access_token = data["access_token"]
            if "refresh_token" in data:
                user.linkedin_refresh_token = data["refresh_token"]
            user.linkedin_token_expires_at = datetime.utcnow() + timedelta(
                seconds=data.get("expires_in", 5184000)
            )
            db_session.commit()
            log.info(f"LinkedIn token refreshed for user {user_id}")
            return True
        else:
            log.error(f"LinkedIn token refresh failed: {data}")
            return False
    except Exception as e:
        log.error(f"LinkedIn token refresh error for user {user_id}: {e}")
        return False
    finally:
        db_session.close()
