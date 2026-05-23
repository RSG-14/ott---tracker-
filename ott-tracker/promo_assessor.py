"""
Promo Performance Assessment engine for the OTT Tracker.

Accepts a promo description and optional historical comparable, pulls
relevant signal from the local database, then calls Claude to produce a
structured multi-dimension performance potential assessment.
"""

import json
import logging
import os

import anthropic
import pandas as pd
from dotenv import load_dotenv

from database import get_mentions, get_trends, get_weekly_snapshots

load_dotenv()
logger = logging.getLogger(__name__)

DIMENSIONS = [
    "sentiment_climate",
    "audience_buzz_potential",
    "content_category_fit",
    "timing_trend_alignment",
    "organic_amplification_likelihood",
]

DIMENSION_LABELS = {
    "sentiment_climate": "Sentiment Climate",
    "audience_buzz_potential": "Audience Buzz Potential",
    "content_category_fit": "Content-Category Fit",
    "timing_trend_alignment": "Timing & Trend Alignment",
    "organic_amplification_likelihood": "Organic Amplification Likelihood",
    "historical_benchmark": "Historical Benchmark",
}

SYSTEM_PROMPT = """You are a senior media strategist specialising in OTT (streaming) platform marketing in India.
You analyse promotional campaigns for streaming content — such as film or series launches — and assess their likelihood of resonating with online audiences based on current sentiment signals, platform trends, and historical performance.

You will be given:
- A promo description written by the user
- Recent social listening data (Reddit sentiment, mention volumes, top keywords) for the relevant OTT brand
- Google Trends scores for the three major OTT platforms
- Optionally, a historical comparable campaign's performance data

Your job is to return a JSON object (no markdown, no extra text) with this exact structure:
{
  "dimensions": {
    "sentiment_climate": {
      "score": <float 0.0–10.0>,
      "label": <"Very Unfavorable"|"Unfavorable"|"Neutral"|"Favorable"|"Very Favorable">,
      "rationale": <1–2 sentences grounding the score in the provided data>
    },
    "audience_buzz_potential": {
      "score": <float 0.0–10.0>,
      "label": <"Very Low"|"Low"|"Moderate"|"High"|"Very High">,
      "rationale": <1–2 sentences>
    },
    "content_category_fit": {
      "score": <float 0.0–10.0>,
      "label": <"Poor Fit"|"Weak Fit"|"Moderate Fit"|"Good Fit"|"Excellent Fit">,
      "rationale": <1–2 sentences>
    },
    "timing_trend_alignment": {
      "score": <float 0.0–10.0>,
      "label": <"Poor Timing"|"Below Average"|"Average"|"Good Timing"|"Optimal Timing">,
      "rationale": <1–2 sentences>
    },
    "organic_amplification_likelihood": {
      "score": <float 0.0–10.0>,
      "label": <"Very Low"|"Low"|"Moderate"|"High"|"Very High">,
      "rationale": <1–2 sentences>
    }
  },
  "historical_benchmark": <null if no comparable provided, otherwise {
    "score": <float 0.0–10.0>,
    "label": <"Well Below"|"Below"|"On Par"|"Above"|"Well Above">,
    "rationale": <1–2 sentences comparing to the historical campaign>
  }>,
  "overall_score": <float 0.0–10.0, weighted average>,
  "overall_label": <"Very Low Potential"|"Low Potential"|"Moderate Potential"|"Strong Potential"|"Exceptional Potential">,
  "executive_summary": <2–3 sentence plain-English summary of the assessment>,
  "key_risks": [<up to 3 concise risk strings>],
  "key_opportunities": [<up to 3 concise opportunity strings>],
  "recommendations": [<up to 3 actionable recommendation strings>]
}

Be evidence-based: reference specific numbers from the provided data in your rationale strings.
If data is sparse or absent, say so in the rationale and score conservatively (5.0).
"""


def _build_context(brand: str, comparable_week: int | None) -> str:
    """Pull relevant DB signals and serialise them as a context block."""
    lines: list[str] = []

    # --- Recent sentiment for the target brand ---
    mentions = get_mentions({"brand_mentioned": brand})
    if not mentions.empty:
        recent = mentions.sort_values("date").tail(200)
        total = len(recent)
        if total:
            pos = (recent["sentiment"] == "positive").sum()
            neu = (recent["sentiment"] == "neutral").sum()
            neg = (recent["sentiment"] == "negative").sum()
            avg_score = recent["sentiment_score"].mean()
            organic_rate = recent.get("organic_signal", pd.Series(dtype=bool)).mean() if "organic_signal" in recent.columns else None

            lines.append(f"=== Recent {brand} Sentiment (last {total} mentions) ===")
            lines.append(f"Positive: {pos} ({pos/total*100:.1f}%)  Neutral: {neu} ({neu/total*100:.1f}%)  Negative: {neg} ({neg/total*100:.1f}%)")
            lines.append(f"Average sentiment score: {avg_score:.2f} (0=very negative, 1=very positive)")
            if organic_rate is not None:
                lines.append(f"Organic signal rate: {organic_rate*100:.1f}% of posts appear genuine")

            # Top keywords
            all_kw: list[str] = []
            for kw_str in recent["catalog_keywords"].dropna():
                all_kw.extend(k.strip() for k in kw_str.split(",") if k.strip())
            if all_kw:
                kw_counts = pd.Series(all_kw).value_counts().head(8)
                kw_str = ", ".join(f"{k} ({v})" for k, v in kw_counts.items())
                lines.append(f"Top catalog keywords: {kw_str}")
    else:
        lines.append(f"=== {brand} Sentiment ===\nNo sentiment data available in database.")

    # --- Weekly snapshot trend for this brand ---
    snapshots = get_weekly_snapshots()
    brand_snaps = snapshots[snapshots["brand"] == brand].sort_values("week_number")
    if not brand_snaps.empty:
        lines.append(f"\n=== {brand} Weekly Snapshot Trend ===")
        for _, row in brand_snaps.tail(6).iterrows():
            lines.append(
                f"Week {int(row['week_number'])}: volume={int(row['mention_volume'])}, "
                f"pos={row['positive_pct']:.1f}%, neg={row['negative_pct']:.1f}%, "
                f"SoV={row['sov_pct']:.1f}%, keywords=[{row['top_catalog_keywords']}]"
            )

    # --- Google Trends ---
    trends = get_trends()
    if not trends.empty:
        recent_trends = trends.sort_values("date").tail(8)
        lines.append("\n=== Google Trends (recent weeks) ===")
        brand_col = {
            "JioHotstar": "jiohotstar_score",
            "Netflix": "netflix_score",
            "Prime": "prime_score",
        }.get(brand)
        for _, row in recent_trends.iterrows():
            jio = row.get("jiohotstar_score", "?")
            net = row.get("netflix_score", "?")
            pri = row.get("prime_score", "?")
            lines.append(f"  {row['date']}: JioHotstar={jio}, Netflix={net}, Prime={pri}")
        if brand_col and brand_col in trends.columns:
            latest = recent_trends[brand_col].iloc[-1] if len(recent_trends) else None
            if latest is not None:
                lines.append(f"Latest Google Trends score for {brand}: {latest}")
    else:
        lines.append("\n=== Google Trends ===\nNo trends data available.")

    # --- Historical comparable ---
    if comparable_week is not None and not snapshots.empty:
        comp = snapshots[(snapshots["week_number"] == comparable_week) & (snapshots["brand"] == brand)]
        if not comp.empty:
            row = comp.iloc[0]
            lines.append(f"\n=== Historical Comparable: Week {comparable_week} ({brand}) ===")
            lines.append(
                f"Mention volume: {int(row['mention_volume'])}, "
                f"Positive: {row['positive_pct']:.1f}%, Negative: {row['negative_pct']:.1f}%, "
                f"Share of Voice: {row['sov_pct']:.1f}%, "
                f"Keywords: [{row['top_catalog_keywords']}]"
            )
        else:
            lines.append(f"\n=== Historical Comparable ===\nNo snapshot found for Week {comparable_week} / {brand}.")

    return "\n".join(lines)


def _call_claude(promo_description: str, context: str, has_comparable: bool) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = (
        f"PROMO DESCRIPTION:\n{promo_description}\n\n"
        f"DATA CONTEXT:\n{context}\n\n"
        f"{'A historical comparable week has been provided — include the historical_benchmark dimension.' if has_comparable else 'No historical comparable was selected — set historical_benchmark to null.'}"
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def assess_promo(
    promo_description: str,
    brand: str,
    comparable_week: int | None = None,
) -> dict:
    """
    Run a promo performance assessment.

    Args:
        promo_description: Free-text description of the promo.
        brand: Target OTT brand — "JioHotstar", "Netflix", or "Prime".
        comparable_week: Optional week_number to use as a historical benchmark.

    Returns:
        Parsed assessment dict as described in SYSTEM_PROMPT.

    Raises:
        json.JSONDecodeError: If Claude returns malformed JSON.
        anthropic.APIError: On API failure.
    """
    context = _build_context(brand, comparable_week)
    result = _call_claude(promo_description, context, has_comparable=comparable_week is not None)
    return result
