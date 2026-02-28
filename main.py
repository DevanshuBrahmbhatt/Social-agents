#!/usr/bin/env python3
"""TweetAgent v2 — Start the web dashboard + scheduler."""

import logging
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

if __name__ == "__main__":
    print("\n🐦 TweetAgent v2 — Starting...")
    print("   Dashboard: http://localhost:8000")
    print("   Press Ctrl+C to stop\n")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
