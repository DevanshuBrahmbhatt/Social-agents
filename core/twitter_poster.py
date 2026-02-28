import logging

import tweepy

import config

log = logging.getLogger(__name__)


def _get_clients(api_key=None, api_secret=None, access_token=None, access_token_secret=None):
    """Create both v2 Client and v1.1 API (for media uploads)."""
    ak = api_key or config.TWITTER_API_KEY
    aks = api_secret or config.TWITTER_API_SECRET
    at = access_token or config.TWITTER_ACCESS_TOKEN
    ats = access_token_secret or config.TWITTER_ACCESS_TOKEN_SECRET

    client = tweepy.Client(
        consumer_key=ak,
        consumer_secret=aks,
        access_token=at,
        access_token_secret=ats,
    )

    # v1.1 API needed for media uploads
    auth = tweepy.OAuth1UserHandler(ak, aks, at, ats)
    api = tweepy.API(auth)

    return client, api


def post_tweet(text: str, image_path: str = None, **creds) -> dict:
    """Post a tweet, optionally with an image attachment.

    Args:
        text: Tweet text (max 280 chars)
        image_path: Optional path to image file to attach
        **creds: Optional override credentials (api_key, api_secret, access_token, access_token_secret)

    Returns the API response.
    """
    client, api = _get_clients(**creds)

    try:
        media_ids = None
        if image_path:
            log.info(f"Uploading media: {image_path}")
            media = api.media_upload(filename=image_path)
            media_ids = [media.media_id]
            log.info(f"Media uploaded, ID: {media.media_id}")

        response = client.create_tweet(text=text, media_ids=media_ids)
        log.info(f"Tweet posted! ID: {response.data['id']}")
        return response

    except tweepy.errors.Forbidden as e:
        error_msg = str(e)
        if "@mentions" in error_msg.lower() or "mentions" in error_msg.lower():
            log.error("Tweet contains @mentions which are blocked on free tier. Remove them and retry.")
        else:
            log.error(f"Twitter API permission error: {e}")
        raise
    except tweepy.errors.TooManyRequests as e:
        log.error(f"Twitter rate limit hit: {e}")
        raise
    except tweepy.errors.TwitterServerError as e:
        log.error(f"Twitter server error: {e}")
        raise


def post_tweet_dry_run(text: str, image_path: str = None) -> None:
    """Print the tweet instead of posting."""
    print("\n" + "=" * 60)
    print("🐦 DRY RUN — Tweet would be posted:")
    print("=" * 60)
    print(text)
    print("-" * 60)
    print(f"Characters: {len(text)}/280")
    if image_path:
        print(f"Image: {image_path}")
    print("=" * 60 + "\n")
