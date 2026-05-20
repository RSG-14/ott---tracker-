"""
Database layer for the OTT Tracker.

Initializes and manages the local SQLite database. Provides helper
functions for inserting raw posts, sentiment results, and trends data,
and for querying records needed by the dashboard and analyzer.
"""

import sqlite3
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

__version__ = "1.0.0"

DB_PATH = Path(__file__).parent / "data" / "tracker.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they don't already exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mentions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                platform          TEXT,
                source            TEXT,
                date              DATE,
                text              TEXT,
                brand_mentioned   TEXT,
                sentiment         TEXT,
                sentiment_score   REAL,
                catalog_keywords  TEXT,
                is_seeded         BOOLEAN DEFAULT 0,
                week_number       INTEGER
            );

            CREATE TABLE IF NOT EXISTS trends (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                date              DATE,
                jiohotstar_score  INTEGER,
                netflix_score     INTEGER,
                prime_score       INTEGER
            );

            CREATE TABLE IF NOT EXISTS weekly_snapshots (
                week_number          INTEGER,
                platform             TEXT,
                brand                TEXT,
                mention_volume       INTEGER,
                positive_pct         REAL,
                neutral_pct          REAL,
                negative_pct         REAL,
                sov_pct              REAL,
                top_catalog_keywords TEXT
            );
        """)


def insert_mention(data: dict) -> None:
    """Insert one row into the mentions table."""
    columns = [
        "platform", "source", "date", "text", "brand_mentioned",
        "sentiment", "sentiment_score", "catalog_keywords",
        "is_seeded", "week_number",
    ]
    values = [data.get(col) for col in columns]
    placeholders = ", ".join("?" * len(columns))
    sql = f"INSERT INTO mentions ({', '.join(columns)}) VALUES ({placeholders})"
    with _connect() as conn:
        conn.execute(sql, values)


def insert_trends(data: dict) -> None:
    """Insert one row into the trends table."""
    columns = ["date", "jiohotstar_score", "netflix_score", "prime_score"]
    values = [data.get(col) for col in columns]
    placeholders = ", ".join("?" * len(columns))
    sql = f"INSERT INTO trends ({', '.join(columns)}) VALUES ({placeholders})"
    with _connect() as conn:
        conn.execute(sql, values)


def get_mentions(filters: dict | None = None) -> pd.DataFrame:
    """Return rows from mentions as a DataFrame, optionally filtered.

    Supported filter keys: platform, brand_mentioned, sentiment,
    week_number, is_seeded, date_from (inclusive), date_to (inclusive).
    """
    sql = "SELECT * FROM mentions WHERE 1=1"
    params: list = []

    if filters:
        if "platform" in filters:
            sql += " AND platform = ?"
            params.append(filters["platform"])
        if "brand_mentioned" in filters:
            sql += " AND brand_mentioned = ?"
            params.append(filters["brand_mentioned"])
        if "sentiment" in filters:
            sql += " AND sentiment = ?"
            params.append(filters["sentiment"])
        if "week_number" in filters:
            sql += " AND week_number = ?"
            params.append(filters["week_number"])
        if "is_seeded" in filters:
            sql += " AND is_seeded = ?"
            params.append(int(filters["is_seeded"]))
        if "date_from" in filters:
            sql += " AND date >= ?"
            params.append(filters["date_from"])
        if "date_to" in filters:
            sql += " AND date <= ?"
            params.append(filters["date_to"])

    with _connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_trends() -> pd.DataFrame:
    """Return all rows from the trends table as a DataFrame."""
    with _connect() as conn:
        return pd.read_sql_query("SELECT * FROM trends ORDER BY date", conn)


def compute_weekly_snapshot() -> None:
    """Aggregate mentions by week_number + brand and write to weekly_snapshots.

    Clears existing rows before rewriting so snapshots stay idempotent.
    """
    with _connect() as conn:
        mentions = pd.read_sql_query(
            "SELECT week_number, platform, brand_mentioned, sentiment, catalog_keywords "
            "FROM mentions WHERE week_number IS NOT NULL",
            conn,
        )

    if mentions.empty:
        return

    rows = []
    total_by_week_platform = (
        mentions.groupby(["week_number", "platform"])["brand_mentioned"]
        .count()
        .rename("total_volume")
    )

    grouped = mentions.groupby(["week_number", "platform", "brand_mentioned"])

    for (week, platform, brand), group in grouped:
        volume = len(group)

        sentiment_counts = group["sentiment"].value_counts()
        positive_pct = sentiment_counts.get("positive", 0) / volume * 100
        neutral_pct  = sentiment_counts.get("neutral",  0) / volume * 100
        negative_pct = sentiment_counts.get("negative", 0) / volume * 100

        week_platform_total = total_by_week_platform.get((week, platform), volume)
        sov_pct = volume / week_platform_total * 100 if week_platform_total else 0

        # Flatten and rank keywords by frequency
        all_keywords: list[str] = []
        for kw_str in group["catalog_keywords"].dropna():
            all_keywords.extend(k.strip() for k in kw_str.split(",") if k.strip())
        kw_series = pd.Series(all_keywords)
        top_keywords = (
            ", ".join(kw_series.value_counts().head(5).index.tolist())
            if not kw_series.empty else ""
        )

        rows.append({
            "week_number": week,
            "platform": platform,
            "brand": brand,
            "mention_volume": volume,
            "positive_pct": round(positive_pct, 2),
            "neutral_pct": round(neutral_pct, 2),
            "negative_pct": round(negative_pct, 2),
            "sov_pct": round(sov_pct, 2),
            "top_catalog_keywords": top_keywords,
        })

    columns = [
        "week_number", "platform", "brand", "mention_volume",
        "positive_pct", "neutral_pct", "negative_pct",
        "sov_pct", "top_catalog_keywords",
    ]
    placeholders = ", ".join("?" * len(columns))
    insert_sql = (
        f"INSERT INTO weekly_snapshots ({', '.join(columns)}) "
        f"VALUES ({placeholders})"
    )

    with _connect() as conn:
        conn.execute("DELETE FROM weekly_snapshots")
        conn.executemany(insert_sql, [[r[c] for c in columns] for r in rows])


def get_weekly_snapshots() -> pd.DataFrame:
    """Return all rows from weekly_snapshots as a DataFrame."""
    with _connect() as conn:
        return pd.read_sql_query(
            "SELECT * FROM weekly_snapshots ORDER BY week_number, brand",
            conn,
        )


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")
