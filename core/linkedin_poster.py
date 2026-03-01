"""LinkedIn Posts API integration — text + image posting."""

import logging

import requests

import config

log = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com"


def _headers(access_token: str) -> dict:
    """Standard headers for LinkedIn REST API."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": config.LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def post_text(text: str, person_urn: str, access_token: str) -> dict:
    """Post a text-only post to LinkedIn.

    Args:
        text: Post commentary (up to 3000 chars)
        person_urn: The user's person URN ID (just the ID part, not full URN)
        access_token: OAuth 2.0 access token

    Returns: dict with post URN id and status
    """
    body = {
        "author": f"urn:li:person:{person_urn}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
    }

    resp = requests.post(
        f"{LINKEDIN_API_BASE}/rest/posts",
        headers=_headers(access_token),
        json=body,
        timeout=30,
    )

    if resp.status_code == 201:
        post_urn = resp.headers.get("x-restli-id", "")
        log.info(f"LinkedIn post created: {post_urn}")
        return {"id": post_urn, "status": "created"}
    else:
        log.error(f"LinkedIn post failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()


def post_with_image(text: str, image_path: str, person_urn: str, access_token: str) -> dict:
    """Post with an image to LinkedIn (3-step upload flow).

    Step 1: Initialize upload → get upload URL + image URN
    Step 2: Upload binary image to the upload URL
    Step 3: Create post referencing the image URN
    """
    author_urn = f"urn:li:person:{person_urn}"
    headers = _headers(access_token)

    # Step 1: Initialize upload
    init_body = {
        "initializeUploadRequest": {
            "owner": author_urn,
        }
    }
    init_resp = requests.post(
        f"{LINKEDIN_API_BASE}/rest/images?action=initializeUpload",
        headers=headers,
        json=init_body,
        timeout=30,
    )
    init_resp.raise_for_status()
    init_data = init_resp.json()

    upload_url = init_data["value"]["uploadUrl"]
    image_urn = init_data["value"]["image"]

    # Step 2: Upload binary
    with open(image_path, "rb") as f:
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/octet-stream",
        }
        upload_resp = requests.put(upload_url, headers=upload_headers, data=f, timeout=60)
        upload_resp.raise_for_status()

    log.info(f"LinkedIn image uploaded: {image_urn}")

    # Step 3: Create post with image
    post_body = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "media": {
                "title": "Chart",
                "id": image_urn,
            }
        },
        "lifecycleState": "PUBLISHED",
    }

    resp = requests.post(
        f"{LINKEDIN_API_BASE}/rest/posts",
        headers=headers,
        json=post_body,
        timeout=30,
    )

    if resp.status_code == 201:
        post_urn = resp.headers.get("x-restli-id", "")
        log.info(f"LinkedIn post with image created: {post_urn}")
        return {"id": post_urn, "status": "created"}
    else:
        log.error(f"LinkedIn image post failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()


def post_linkedin(text: str, image_path: str = None, person_urn: str = None,
                  access_token: str = None) -> dict:
    """Post to LinkedIn, optionally with an image. Main entry point.

    Mirrors the signature pattern of twitter_poster.post_tweet().
    """
    if not person_urn or not access_token:
        raise ValueError("LinkedIn person_urn and access_token are required")

    try:
        if image_path:
            return post_with_image(text, image_path, person_urn, access_token)
        else:
            return post_text(text, person_urn, access_token)
    except requests.exceptions.HTTPError as e:
        # If image upload fails, fall back to text-only
        if image_path and e.response is not None and e.response.status_code >= 400:
            log.warning(f"LinkedIn image upload failed, falling back to text-only: {e}")
            return post_text(text, person_urn, access_token)
        raise


def post_linkedin_dry_run(text: str, image_path: str = None) -> None:
    """Print the LinkedIn post instead of posting."""
    print("\n" + "=" * 60)
    print("LinkedIn DRY RUN — Post would be published:")
    print("=" * 60)
    print(text)
    print("-" * 60)
    print(f"Characters: {len(text)}/3000")
    if image_path:
        print(f"Image: {image_path}")
    print("=" * 60 + "\n")
