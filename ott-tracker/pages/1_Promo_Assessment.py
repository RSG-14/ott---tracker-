"""
Promo Performance Assessment — standalone Streamlit page.

Lets users describe a planned OTT content promo, optionally pick a
historical comparable campaign, and receive a Claude-powered multi-
dimension performance potential breakdown.
"""

import json
import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database import get_weekly_snapshots, init_db
from promo_assessor import DIMENSION_LABELS, assess_promo

logger = logging.getLogger(__name__)

BRANDS = ["JioHotstar", "Netflix", "Prime"]

SCORE_COLORS = {
    (0, 4): "#e53935",
    (4, 6): "#fb8c00",
    (6, 8): "#fdd835",
    (8, 10.1): "#43a047",
}

st.set_page_config(
    page_title="Promo Assessment | OTT Tracker",
    page_icon="🎬",
    layout="wide",
)


def _score_color(score: float) -> str:
    for (lo, hi), color in SCORE_COLORS.items():
        if lo <= score < hi:
            return color
    return "#43a047"


def _score_emoji(score: float) -> str:
    if score >= 8:
        return "🟢"
    if score >= 6:
        return "🟡"
    if score >= 4:
        return "🟠"
    return "🔴"


def _radar_chart(dimensions: dict, historical: dict | None) -> go.Figure:
    dim_keys = list(dimensions.keys())
    if historical:
        dim_keys_all = dim_keys + ["historical_benchmark"]
        scores = [dimensions[k]["score"] for k in dim_keys] + [historical["score"]]
        labels = [DIMENSION_LABELS.get(k, k) for k in dim_keys_all]
    else:
        scores = [dimensions[k]["score"] for k in dim_keys]
        labels = [DIMENSION_LABELS.get(k, k) for k in dim_keys]

    # Close the polygon
    scores_closed = scores + [scores[0]]
    labels_closed = labels + [labels[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=scores_closed,
        theta=labels_closed,
        fill="toself",
        fillcolor="rgba(99, 110, 250, 0.2)",
        line=dict(color="rgba(99, 110, 250, 0.9)", width=2),
        name="Assessment",
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickfont=dict(size=10)),
            angularaxis=dict(tickfont=dict(size=12)),
        ),
        showlegend=False,
        margin=dict(l=60, r=60, t=40, b=40),
        height=420,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _gauge(score: float, label: str) -> go.Figure:
    color = _score_color(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": "/10", "font": {"size": 36}},
        title={"text": label, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, 10], "tickwidth": 1},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 4], "color": "rgba(229,57,53,0.15)"},
                {"range": [4, 6], "color": "rgba(251,140,0,0.15)"},
                {"range": [6, 8], "color": "rgba(253,216,53,0.15)"},
                {"range": [8, 10], "color": "rgba(67,160,71,0.15)"},
            ],
        },
    ))
    fig.update_layout(height=220, margin=dict(l=20, r=20, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _available_comparable_weeks(brand: str) -> dict[str, int]:
    """Return {display_label: week_number} for snapshots of the given brand."""
    snaps = get_weekly_snapshots()
    brand_snaps = snaps[snaps["brand"] == brand].sort_values("week_number", ascending=False)
    options: dict[str, int] = {}
    for _, row in brand_snaps.iterrows():
        wk = int(row["week_number"])
        vol = int(row["mention_volume"])
        pos = row["positive_pct"]
        label = f"Week {wk}  —  {vol} mentions, {pos:.0f}% positive"
        options[label] = wk
    return options


# ── Page layout ─────────────────────────────────────────────────────────────

st.title("🎬 Promo Performance Assessment")
st.caption("Describe a planned OTT content promo and get an AI-powered assessment of its performance potential.")

init_db()

with st.form("promo_form"):
    col_left, col_right = st.columns([2, 1])

    with col_left:
        promo_desc = st.text_area(
            "Promo description",
            height=180,
            placeholder=(
                "Describe the promo in plain language. Include:\n"
                "• What content is being promoted (title, genre, cast highlights)\n"
                "• Platform and campaign type (launch push, mid-season, finale, etc.)\n"
                "• Key messaging angle or hook\n"
                "• Target audience if known\n"
                "• Campaign duration or timing"
            ),
        )

    with col_right:
        brand = st.selectbox("Target platform", BRANDS)

        st.markdown("**Historical comparable** *(optional)*")
        comparable_options = _available_comparable_weeks(brand)
        use_comparable = st.checkbox("Compare against a past campaign", value=bool(comparable_options))

        comparable_week: int | None = None
        if use_comparable:
            if comparable_options:
                selected_label = st.selectbox(
                    "Select comparable week",
                    list(comparable_options.keys()),
                )
                comparable_week = comparable_options[selected_label]
            else:
                st.info("No historical snapshots found for this platform yet. Collect some data first.")

    submitted = st.form_submit_button("Run Assessment", type="primary", use_container_width=True)


if submitted:
    if not promo_desc.strip():
        st.warning("Please enter a promo description before running the assessment.")
        st.stop()

    with st.spinner("Analysing promo potential — this takes about 10–15 seconds…"):
        try:
            result = assess_promo(
                promo_description=promo_desc.strip(),
                brand=brand,
                comparable_week=comparable_week,
            )
        except json.JSONDecodeError as exc:
            st.error(f"Claude returned unexpected output — please try again. (JSON error: {exc})")
            st.stop()
        except Exception as exc:
            logger.exception("Assessment failed")
            st.error(f"Assessment failed: {exc}")
            st.stop()

    # ── Overall score ──────────────────────────────────────────────────────
    st.divider()
    overall = result.get("overall_score", 0.0)
    overall_label = result.get("overall_label", "")

    oc1, oc2 = st.columns([1, 2])
    with oc1:
        st.plotly_chart(_gauge(overall, overall_label), use_container_width=True)
    with oc2:
        st.subheader("Executive Summary")
        st.write(result.get("executive_summary", ""))

        risk_col, opp_col = st.columns(2)
        with risk_col:
            st.markdown("**Key Risks**")
            for r in result.get("key_risks", []):
                st.markdown(f"- {r}")
        with opp_col:
            st.markdown("**Key Opportunities**")
            for o in result.get("key_opportunities", []):
                st.markdown(f"- {o}")

    # ── Radar chart ────────────────────────────────────────────────────────
    st.divider()
    dims = result.get("dimensions", {})
    hist = result.get("historical_benchmark")

    rc1, rc2 = st.columns([1, 1])
    with rc1:
        st.subheader("Dimension Radar")
        st.plotly_chart(_radar_chart(dims, hist), use_container_width=True)

    with rc2:
        st.subheader("Dimension Breakdown")
        all_dims = dict(dims)
        if hist:
            all_dims["historical_benchmark"] = hist

        for key, data in all_dims.items():
            dim_score = data.get("score", 0.0)
            dim_label_text = data.get("label", "")
            dim_rationale = data.get("rationale", "")
            display_name = DIMENSION_LABELS.get(key, key)

            emoji = _score_emoji(dim_score)
            with st.expander(f"{emoji} {display_name} — **{dim_score:.1f}/10** · {dim_label_text}"):
                st.write(dim_rationale)

    # ── Recommendations ────────────────────────────────────────────────────
    recs = result.get("recommendations", [])
    if recs:
        st.divider()
        st.subheader("Recommendations")
        for i, rec in enumerate(recs, 1):
            st.markdown(f"**{i}.** {rec}")

    # ── Raw JSON (debug) ───────────────────────────────────────────────────
    with st.expander("Raw assessment JSON"):
        st.json(result)
