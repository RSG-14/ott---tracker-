"""
Sentiment and theme analyzer for the OTT Tracker.

Passes raw text entries to the Claude API in batches of 5, extracting
brand attribution, sentiment, catalog keywords, and organic signal.
Returns the original dicts enriched with analysis fields.
"""

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

__version__ = "1.0.0"

BATCH_SIZE = 5

SYSTEM_PROMPT = (
    "You are a social media analyst. For each post provided, return a JSON array "
    "where each element corresponds to one post and contains:\n"
    "- brand_mentioned: which OTT platform is the main subject — one of JioHotstar, Netflix, Prime, Multiple, None\n"
    "- sentiment: positive, neutral, or negative — toward the brand mentioned\n"
    "- sentiment_score: float from 0.0 (very negative) to 1.0 (very positive), 0.5 for neutral\n"
    "- catalog_keywords: list of any catalog-related terms present such as film library, award films, "
    "content variety, classic movies, regional content\n"
    "- organic_signal: true if the post reads as genuine user opinion, false if it reads promotional or scripted\n"
    "Return only the JSON array. No explanation. No markdown."
)


def _build_user_message(batch: list[dict]) -> str:
    lines = []
    for i, entry in enumerate(batch, 1):
        lines.append(f"Post {i}: {entry.get('text', '').strip()}")
    return "\n\n".join(lines)


def _merge(entry: dict, result: dict) -> dict:
    """Write analysis fields from result into entry, normalising types."""
    entry["brand_mentioned"] = result.get("brand_mentioned") or entry.get("brand_mentioned") or ""
    entry["sentiment"] = result.get("sentiment") or "neutral"

    raw_score = result.get("sentiment_score", 0.5)
    try:
        entry["sentiment_score"] = max(0.0, min(1.0, float(raw_score)))
    except (TypeError, ValueError):
        entry["sentiment_score"] = 0.5

    kw = result.get("catalog_keywords", [])
    if isinstance(kw, list):
        entry["catalog_keywords"] = ", ".join(str(k) for k in kw)
    else:
        entry["catalog_keywords"] = str(kw) if kw else ""

    entry["organic_signal"] = bool(result.get("organic_signal", True))
    return entry


def analyze_batch(entries: list[dict]) -> list[dict]:
    """Enrich each entry dict with brand, sentiment, and catalog fields.

    Processes entries in batches of 5. Batches that fail JSON parsing are
    logged and skipped — their entries are returned with fields unchanged.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    enriched: list[dict] = []

    for batch_start in range(0, len(entries), BATCH_SIZE):
        batch = entries[batch_start : batch_start + BATCH_SIZE]

        try:
            response = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_message(batch)}],
            )
            raw_text = response.content[0].text.strip()

            # Strip accidental markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            results = json.loads(raw_text)

            if not isinstance(results, list):
                raise ValueError(f"Expected a JSON array, got {type(results).__name__}")

            for i, entry in enumerate(batch):
                if i < len(results) and isinstance(results[i], dict):
                    _merge(entry, results[i])
                else:
                    logger.warning("No result for batch index %d — skipping merge", i)

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.error(
                "Batch %d–%d failed (%s: %s) — entries kept without analysis",
                batch_start,
                batch_start + len(batch) - 1,
                type(exc).__name__,
                exc,
            )
        except anthropic.APIError as exc:
            logger.error(
                "API error on batch %d–%d (%s) — entries kept without analysis",
                batch_start,
                batch_start + len(batch) - 1,
                exc,
            )

        enriched.extend(batch)

    return enriched
