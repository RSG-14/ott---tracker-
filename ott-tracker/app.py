"""
Streamlit dashboard for the OTT Tracker.

Renders sentiment trends, share of voice, keyword analysis, and Google
Trends data. Sidebar controls data pulls, filters, and manual entry.
"""

from collections import Counter
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from analyzer import analyze_batch
from database import (
    compute_weekly_snapshot,
    get_mentions,
    get_trends,
    get_weekly_snapshots,
    init_db,
    insert_mention,
    insert_trends,
)
from reddit_pull import pull_reddit
from trends_pull import pull_trends

# ── Constants ────────────────────────────────────────────────────────────────

__version__ = "1.0.0"

_NO_DATA_MSG = "No data yet. Run a Reddit pull or add manual entries to get started."

CAMPAIGN_START_WEEK: int | None = None  # set to a week number to show the campaign marker

BRAND_COLORS: dict[str, str] = {
    "jiohotstar": "#6C3CE3",
    "hotstar":    "#6C3CE3",
    "netflix":    "#E50914",
    "prime":      "#00A8E1",
    "multiple":   "#F5A623",
}
SENTIMENT_COLORS: dict[str, str] = {
    "positive": "#2E7D32",
    "neutral":  "#9E9E9E",
    "negative": "#C62828",
}
LINE_DASHES = ["solid", "dash", "dot"]

SIDEBAR_BRANDS = ["JioHotstar", "Netflix", "Prime"]
SIDEBAR_PLATFORMS = ["Reddit", "X", "Quora"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _csv_button(df: pd.DataFrame, label: str = "⬇ Export CSV", filename: str = "export.csv") -> None:
    st.download_button(label, data=df.to_csv(index=False).encode(), file_name=filename, mime="text/csv")


def _brand_matches(value: str, selected: list[str]) -> bool:
    """Fuzzy brand match: 'Prime' matches 'Prime Video', 'Amazon Prime', etc."""
    v = str(value).lower()
    for b in selected:
        if b.lower() in v or v in b.lower():
            return True
    return False


def _filter_df(
    df: pd.DataFrame,
    platforms: list[str],
    brands: list[str],
    brand_col: str = "brand_mentioned",
) -> pd.DataFrame:
    if df.empty:
        return df
    if "All" not in platforms:
        df = df[df["platform"].str.strip().isin(platforms)]
    if "All" not in brands:
        df = df[df[brand_col].apply(lambda v: _brand_matches(v, brands))]
    return df

# ── App bootstrap ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="OTT Tracker", layout="wide", page_icon="📺")
load_dotenv()
init_db()

# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("📺 OTT Tracker")
st.sidebar.markdown("---")

today = date.today()
start_date: date = st.sidebar.date_input("Start date", value=today - timedelta(days=90))
end_date: date   = st.sidebar.date_input("End date",   value=today)

selected_platforms: list[str] = st.sidebar.multiselect(
    "Platform", options=["All"] + SIDEBAR_PLATFORMS, default=["All"]
)
selected_brands: list[str] = st.sidebar.multiselect(
    "Brand", options=["All"] + SIDEBAR_BRANDS, default=["All"]
)
exclude_seeded: bool = st.sidebar.toggle("Exclude seeded posts", value=False)

st.sidebar.markdown("---")

# Run Reddit Pull
if st.sidebar.button("🔄 Run Reddit Pull", use_container_width=True):
    with st.spinner("Pulling Reddit data…"):
        try:
            raw = pull_reddit()
            enriched = analyze_batch(raw)
            for entry in enriched:
                insert_mention(entry)
            compute_weekly_snapshot()
            st.sidebar.success(f"✓ Inserted {len(enriched)} records.")
        except Exception as exc:
            st.sidebar.error(f"Reddit pull failed: {exc}")

# Refresh Google Trends
if st.sidebar.button("📈 Refresh Google Trends", use_container_width=True):
    with st.spinner("Fetching Google Trends…"):
        try:
            rows = pull_trends()
            for row in rows:
                insert_trends(row)
            st.sidebar.success(f"✓ Inserted {len(rows)} trend rows.")
        except Exception as exc:
            st.sidebar.error(f"Trends pull failed: {exc}")

# Manual entry form
with st.sidebar.expander("✏️ Add Manual Entry"):
    with st.form("manual_entry", clear_on_submit=True):
        m_platform  = st.selectbox("Platform", ["X", "Quora"])
        m_date      = st.date_input("Date", value=today)
        m_text      = st.text_area(
            "Text",
            placeholder="One or more posts. Separate multiple entries with ---",
            height=120,
        )
        m_seeded    = st.checkbox("Is Seeded")
        m_submitted = st.form_submit_button("Submit")

    if m_submitted:
        texts = [t.strip() for t in m_text.split("---") if t.strip()]
        if not texts:
            st.warning("No text entered.")
        else:
            with st.spinner(f"Analysing {len(texts)} {'entry' if len(texts) == 1 else 'entries'}…"):
                try:
                    base_week = m_date.isocalendar()[1]
                    entries = [
                        {
                            "platform":    m_platform,
                            "source":      "manual",
                            "date":        str(m_date),
                            "text":        t,
                            "is_seeded":   int(m_seeded),
                            "week_number": base_week,
                        }
                        for t in texts
                    ]
                    enriched = analyze_batch(entries)
                    for entry in enriched:
                        insert_mention(entry)
                    compute_weekly_snapshot()
                    st.success(f"✓ Added {len(enriched)} {'entry' if len(enriched) == 1 else 'entries'}.")
                except Exception as exc:
                    st.error(f"Submission failed: {exc}")

# ── Load filtered data ────────────────────────────────────────────────────────

sql_filters: dict = {"date_from": str(start_date), "date_to": str(end_date)}
if exclude_seeded:
    sql_filters["is_seeded"] = False

df_mentions = get_mentions(sql_filters)
df_mentions = _filter_df(df_mentions, selected_platforms, selected_brands)

df_snap = get_weekly_snapshots()
df_snap = _filter_df(df_snap, selected_platforms, selected_brands, brand_col="brand")

df_trends = get_trends()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Sentiment Trends",
    "🥧 Share of Voice",
    "🔑 Keyword Tracker",
    "🌐 Google Trends",
])

# ─── Tab 1 · Sentiment Trends ─────────────────────────────────────────────────

with tab1:
    st.subheader("Sentiment Trends by Brand")

    if df_snap.empty:
        st.info(_NO_DATA_MSG)
    else:
        fig = go.Figure()

        for b_idx, brand in enumerate(df_snap["brand"].dropna().unique()):
            bdf = df_snap[df_snap["brand"] == brand].sort_values("week_number")
            dash = LINE_DASHES[b_idx % len(LINE_DASHES)]
            for sentiment, color in SENTIMENT_COLORS.items():
                col = f"{sentiment}_pct"
                if col not in bdf.columns:
                    continue
                fig.add_trace(go.Scatter(
                    x=bdf["week_number"],
                    y=bdf[col],
                    name=f"{brand} – {sentiment}",
                    mode="lines+markers",
                    line=dict(color=color, dash=dash, width=2),
                    marker=dict(size=5),
                ))

        if CAMPAIGN_START_WEEK is not None:
            fig.add_vline(
                x=CAMPAIGN_START_WEEK,
                line_dash="dot",
                line_color="#444444",
                annotation_text="Campaign Start",
                annotation_position="top right",
            )

        fig.update_layout(
            xaxis_title="Week Number",
            yaxis_title="Percentage (%)",
            yaxis=dict(range=[0, 100]),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            height=480,
        )
        st.plotly_chart(fig, use_container_width=True)

    _csv_button(df_snap, filename="sentiment_trends.csv")

# ─── Tab 2 · Share of Voice ───────────────────────────────────────────────────

with tab2:
    st.subheader("Share of Voice — Mention Volume by Brand")

    if df_snap.empty:
        st.info(_NO_DATA_MSG)
    else:
        fig2 = go.Figure()

        for brand in df_snap["brand"].dropna().unique():
            bdf = df_snap[df_snap["brand"] == brand].sort_values("week_number")
            color = BRAND_COLORS.get(brand.lower(), "#888888")
            fig2.add_trace(go.Bar(
                x=bdf["week_number"],
                y=bdf["mention_volume"],
                name=brand,
                marker_color=color,
                text=bdf["sov_pct"].apply(lambda v: f"{v:.0f}%"),
                textposition="inside",
                insidetextanchor="middle",
            ))

        fig2.update_layout(
            barmode="stack",
            xaxis_title="Week Number",
            yaxis_title="Mention Volume",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            height=450,
        )
        st.plotly_chart(fig2, use_container_width=True)

    _csv_button(df_snap, filename="share_of_voice.csv")

# ─── Tab 3 · Keyword Tracker ──────────────────────────────────────────────────

with tab3:
    st.subheader("Top Catalog Keywords")

    if df_mentions.empty:
        st.info(_NO_DATA_MSG)
    else:
        kw_counter: Counter = Counter()
        brand_kw: dict[str, Counter] = {}

        for _, row in df_mentions.iterrows():
            raw_kw = str(row.get("catalog_keywords") or "")
            brand  = str(row.get("brand_mentioned") or "").strip()
            keywords = [
                k.strip() for k in raw_kw.split(",")
                if k.strip() and k.strip().lower() not in ("nan", "none", "")
            ]
            for kw in keywords:
                kw_counter[kw] += 1
                brand_kw.setdefault(kw, Counter())[brand] += 1

        if not kw_counter:
            st.info("No catalog keywords found yet. They are extracted automatically during analysis.")
        else:
            top15 = kw_counter.most_common(15)
            labels = [k for k, _ in top15]
            counts = [c for _, c in top15]

            fig3 = go.Figure(go.Bar(
                x=counts,
                y=labels,
                orientation="h",
                marker_color="#4A90D9",
                text=counts,
                textposition="outside",
            ))
            fig3.update_layout(
                xaxis_title="Frequency",
                yaxis=dict(autorange="reversed"),
                height=max(300, 32 * len(top15) + 80),
                margin=dict(l=20, r=60),
            )
            st.plotly_chart(fig3, use_container_width=True)

            st.markdown("**Keyword breakdown by brand**")
            kw_table = pd.DataFrame([
                {
                    "Keyword":    kw,
                    "JioHotstar": brand_kw.get(kw, Counter()).get("JioHotstar", 0),
                    "Netflix":    brand_kw.get(kw, Counter()).get("Netflix", 0),
                    "Prime":      brand_kw.get(kw, Counter()).get("Prime", 0),
                }
                for kw in labels
            ])
            st.dataframe(kw_table, use_container_width=True, hide_index=True)
            _csv_button(kw_table, filename="keyword_tracker.csv")

# ─── Tab 4 · Google Trends ────────────────────────────────────────────────────

with tab4:
    st.subheader("Google Trends — Search Interest in India")
    st.caption(
        "Relative search interest in India. "
        "100 = peak search interest for that keyword in the period."
    )

    if df_trends.empty:
        st.info(_NO_DATA_MSG)
    else:
        dt = df_trends.copy()
        dt["date"] = pd.to_datetime(dt["date"])
        dt = dt[
            (dt["date"] >= pd.Timestamp(str(start_date))) &
            (dt["date"] <= pd.Timestamp(str(end_date)))
        ]

        fig4 = go.Figure()
        for col, label, color in [
            ("jiohotstar_score", "JioHotstar", BRAND_COLORS["jiohotstar"]),
            ("netflix_score",    "Netflix",    BRAND_COLORS["netflix"]),
            ("prime_score",      "Prime",      BRAND_COLORS["prime"]),
        ]:
            if col in dt.columns:
                fig4.add_trace(go.Scatter(
                    x=dt["date"],
                    y=dt[col],
                    name=label,
                    mode="lines+markers",
                    line=dict(color=color, width=2),
                    marker=dict(size=4),
                ))

        fig4.update_layout(
            xaxis_title="Date",
            yaxis_title="Relative Search Interest",
            yaxis=dict(range=[0, 105]),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            height=450,
        )
        st.plotly_chart(fig4, use_container_width=True)

    _csv_button(df_trends, filename="google_trends.csv")
