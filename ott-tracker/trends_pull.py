"""
Google Trends data collector for the OTT Tracker.

Uses pytrends to fetch 90-day search interest for the three main OTT
platforms in India and returns a list of weekly score dicts.
"""

import time
import logging

from dotenv import load_dotenv
from pytrends.request import TrendReq
from pytrends.exceptions import TooManyRequestsError

load_dotenv()

logger = logging.getLogger(__name__)

__version__ = "1.0.0"

KEYWORDS = ["JioHotstar", "Netflix", "Amazon Prime Video"]
COLUMN_MAP = {
    "JioHotstar": "jiohotstar_score",
    "Netflix": "netflix_score",
    "Amazon Prime Video": "prime_score",
}


def pull_trends() -> list[dict]:
    """Fetch 90-day Google Trends interest for OTT keywords in India.

    Returns a list of dicts with keys: date, jiohotstar_score,
    netflix_score, prime_score — one dict per data point returned
    by the Trends API (typically weekly).
    """
    pytrends = TrendReq(hl="en-IN", tz=330)
    pytrends.build_payload(KEYWORDS, geo="IN", timeframe="today 90-d")

    time.sleep(1)

    def _fetch() -> list[dict]:
        df = pytrends.interest_over_time()

        if df.empty:
            logger.warning("pytrends returned an empty DataFrame")
            return []

        df = df.drop(columns=["isPartial"], errors="ignore")
        df = df.rename(columns=COLUMN_MAP)
        df.index.name = "date"
        df = df.reset_index()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")

        return df[["date", "jiohotstar_score", "netflix_score", "prime_score"]].to_dict(
            orient="records"
        )

    try:
        return _fetch()
    except TooManyRequestsError:
        logger.warning("Rate limited by Google Trends — waiting 60 s before retry")
        time.sleep(60)
        return _fetch()


if __name__ == "__main__":
    rows = pull_trends()
    print(f"Fetched {len(rows)} rows")
    for row in rows[:5]:
        print(row)
