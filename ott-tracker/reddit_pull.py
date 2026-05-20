"""
Reddit data collector for the OTT Tracker.

Uses PRAW to search configured subreddits for brand-related posts and
top comments, returning raw dicts ready for the analyzer and database.
"""

import os
from datetime import datetime, timezone
from collections import defaultdict

import praw
from dotenv import load_dotenv

load_dotenv()

__version__ = "1.0.0"

SUBREDDITS = [
    "india",
    "bollywood",
    "indiancinema",
    "netflixindia",
    "hotstar",
    "OTTIndia",
    "amazonprimevideo",
]

BRAND_KEYWORDS = [
    "JioHotstar",
    "Hotstar",
    "Netflix",
    "Prime Video",
    "Amazon Prime",
]

CATALOG_KEYWORDS = [
    "National Award",
    "Oscar submission",
    "500 crore",
    "Hindi film",
    "classic Bollywood",
    "must watch",
    "OTT library",
    "catalog",
    "film library",
    "regional films",
    "Bollywood classics",
]


def _make_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
    )


def _detect_brand(text: str) -> str:
    """Return the first matching brand keyword found in text, or empty string."""
    lower = text.lower()
    for brand in BRAND_KEYWORDS:
        if brand.lower() in lower:
            return brand
    return ""


def _detect_catalog_keywords(text: str) -> str:
    """Return comma-separated catalog keywords found in text."""
    lower = text.lower()
    found = [kw for kw in CATALOG_KEYWORDS if kw.lower() in lower]
    return ", ".join(found)


def _utc_to_date(utc_timestamp: float) -> str:
    return datetime.fromtimestamp(utc_timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def _week_number(utc_timestamp: float) -> int:
    return datetime.fromtimestamp(utc_timestamp, tz=timezone.utc).isocalendar()[1]


def _build_record(text: str, utc_timestamp: float, source: str) -> dict:
    return {
        "platform": "Reddit",
        "source": source,
        "date": _utc_to_date(utc_timestamp),
        "text": text[:500],
        "brand_mentioned": _detect_brand(text),
        "catalog_keywords": _detect_catalog_keywords(text),
        "week_number": _week_number(utc_timestamp),
        # sentiment fields left for analyzer.py
        "sentiment": None,
        "sentiment_score": None,
        "is_seeded": 0,
    }


def pull_reddit(limit: int = 100) -> list[dict]:
    """Search each subreddit for each brand keyword and return raw record dicts.

    Each dict covers one post title+body or one top comment. Posts are
    deduplicated by Reddit post ID across all keyword searches.
    """
    reddit = _make_reddit_client()
    records: list[dict] = []

    # Track stats for the summary printout
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"posts": 0, "comments": 0})
    seen_post_ids: set[str] = set()

    for sub_name in SUBREDDITS:
        subreddit = reddit.subreddit(sub_name)

        for brand in BRAND_KEYWORDS:
            try:
                results = subreddit.search(brand, limit=limit)
            except Exception as exc:
                print(f"  [warn] r/{sub_name} search '{brand}' failed: {exc}")
                continue

            for post in results:
                if post.id in seen_post_ids:
                    continue
                seen_post_ids.add(post.id)

                # Post title + body combined
                post_text = f"{post.title} {post.selftext}".strip()
                records.append(_build_record(post_text, post.created_utc, f"r/{sub_name}"))
                stats[sub_name]["posts"] += 1

                # Top 5 comments
                try:
                    post.comments.replace_more(limit=0)
                    top_comments = sorted(
                        post.comments.list(),
                        key=lambda c: getattr(c, "score", 0),
                        reverse=True,
                    )[:5]
                    for comment in top_comments:
                        if not comment.body or comment.body in ("[deleted]", "[removed]"):
                            continue
                        records.append(
                            _build_record(comment.body, comment.created_utc, f"r/{sub_name}")
                        )
                        stats[sub_name]["comments"] += 1
                except Exception as exc:
                    print(f"  [warn] could not fetch comments for post {post.id}: {exc}")

    # Summary
    print("\n--- Reddit Pull Summary ---")
    total_posts = total_comments = 0
    for sub_name in SUBREDDITS:
        p = stats[sub_name]["posts"]
        c = stats[sub_name]["comments"]
        total_posts += p
        total_comments += c
        print(f"  r/{sub_name:<22} {p:>4} posts   {c:>4} comments")
    print(f"  {'TOTAL':<22} {total_posts:>4} posts   {total_comments:>4} comments")
    print(f"  Records returned: {len(records)}")
    print("---------------------------\n")

    return records


if __name__ == "__main__":
    pull_reddit()
