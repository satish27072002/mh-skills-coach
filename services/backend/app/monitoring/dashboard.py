"""
MH Skills Coach — Metrics Dashboard (Streamlit)

Reads structured JSON logs from logs/app.log and displays key metrics.

Run locally:
    streamlit run services/backend/app/monitoring/dashboard.py

Run via Docker (add to docker-compose):
    command: streamlit run app/monitoring/dashboard.py --server.port 8501
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LOG_FILE = Path(__file__).parents[4] / "logs" / "app.log"
OPENAI_COST_PER_1K_TOKENS = 0.00015   # gpt-4o-mini input ~ $0.15/1M tokens
AVG_TOKENS_PER_CALL = 800             # rough estimate per LLM call

st.set_page_config(
    page_title="MH Skills Coach — Dashboard",
    page_icon="🧠",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_logs(hours: int = 24) -> list[dict[str, Any]]:
    """Load and parse JSON log entries from the last N hours."""
    if not LOG_FILE.exists():
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    records: list[dict[str, Any]] = []

    with LOG_FILE.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Parse timestamp
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ts = datetime.now(tz=timezone.utc)

            if ts >= cutoff:
                entry["_ts"] = ts
                records.append(entry)

    return records


def build_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------
def count_event(df: pd.DataFrame, event: str) -> int:
    if df.empty or "event" not in df.columns:
        return 0
    return int((df["event"] == event).sum())


def count_trigger(df: pd.DataFrame, trigger_type: str) -> int:
    if df.empty or "trigger_type" not in df.columns:
        return 0
    return int((df["trigger_type"] == trigger_type).sum())


def count_route(df: pd.DataFrame, route: str) -> int:
    if df.empty or "route" not in df.columns:
        return 0
    return int((df["route"] == route).sum())


def unique_sessions(df: pd.DataFrame) -> int:
    if df.empty or "correlation_id" not in df.columns:
        return 0
    return int(df["correlation_id"].nunique())


def avg_llm_latency(df: pd.DataFrame) -> float:
    """Average LLM call duration in ms."""
    if df.empty or "duration_ms" not in df.columns:
        return 0.0
    llm_df = df[df["event"] == "llm_call"].copy()
    if llm_df.empty:
        return 0.0
    llm_df["duration_ms"] = pd.to_numeric(llm_df["duration_ms"], errors="coerce")
    return float(llm_df["duration_ms"].dropna().mean())


def error_count(df: pd.DataFrame) -> int:
    if df.empty or "level" not in df.columns:
        return 0
    return int((df["level"] == "ERROR").sum())


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🧠 MH Skills Coach — Metrics Dashboard")

# Sidebar controls
with st.sidebar:
    st.header("Controls")
    hours = st.slider("Time window (hours)", min_value=1, max_value=168, value=24, step=1)
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
    st.markdown("---")
    st.caption(f"Log file: `{LOG_FILE}`")
    st.caption(f"Exists: {'✅' if LOG_FILE.exists() else '❌ not found'}")

records = load_logs(hours=hours)
df = build_df(records)

if df.empty:
    st.warning(
        f"No log data found in `{LOG_FILE}` for the last {hours}h. "
        "Make sure the backend is running with `LOG_FORMAT=json` and writing to that path."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Row 1 — Top-level KPIs
# ---------------------------------------------------------------------------
st.subheader(f"📊 Overview — last {hours}h")

llm_calls = count_event(df, "llm_call")
estimated_cost = (llm_calls * AVG_TOKENS_PER_CALL / 1000) * OPENAI_COST_PER_1K_TOKENS
latency_ms = avg_llm_latency(df)
errors = error_count(df)
total_events = len(df)
sessions = unique_sessions(df)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total Sessions (24h)", sessions)
col2.metric("LLM Calls", llm_calls)
col3.metric("Est. Cost (USD)", f"${estimated_cost:.4f}")
col4.metric("Avg LLM Latency", f"{latency_ms:.0f} ms" if latency_ms else "—")
col5.metric("Errors", errors, delta=None, delta_color="inverse")
col6.metric("Total Log Events", total_events)

st.markdown("---")

# ---------------------------------------------------------------------------
# Row 2 — Agent distribution + Safety triggers (side by side)
# ---------------------------------------------------------------------------
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🤖 Agent Routing Distribution")

    route_counts = {
        "COACH": count_route(df, "COACH") + count_route(df, "COACH_EMOTIONAL"),
        "THERAPIST_SEARCH": count_route(df, "THERAPIST_SEARCH"),
        "BOOKING_EMAIL": count_route(df, "BOOKING_EMAIL"),
    }
    route_df = pd.DataFrame(
        {"Agent": list(route_counts.keys()), "Count": list(route_counts.values())}
    ).set_index("Agent")

    if route_df["Count"].sum() == 0:
        st.info("No agent routing events recorded yet.")
    else:
        st.bar_chart(route_df)
        for agent, count in route_counts.items():
            pct = (count / max(route_df["Count"].sum(), 1)) * 100
            st.caption(f"• {agent}: **{count}** calls ({pct:.1f}%)")

with col_right:
    st.subheader("🛡️ Safety Trigger Counts")

    safety_counts = {
        "crisis": count_trigger(df, "crisis") + count_trigger(df, "safety_gate"),
        "jailbreak": count_trigger(df, "jailbreak"),
        "out_of_scope": count_trigger(df, "out_of_scope"),
        "prescription": count_trigger(df, "prescription"),
        "rate_limit": count_event(df, "rate_limit_exceeded"),
    }
    safety_df = pd.DataFrame(
        {"Trigger": list(safety_counts.keys()), "Count": list(safety_counts.values())}
    ).set_index("Trigger")

    if safety_df["Count"].sum() == 0:
        st.info("No safety triggers recorded yet.")
    else:
        st.bar_chart(safety_df)
        for trigger, count in safety_counts.items():
            st.caption(f"• {trigger}: **{count}**")

st.markdown("---")

# ---------------------------------------------------------------------------
# Row 3 — LLM latency over time + Error rate
# ---------------------------------------------------------------------------
col_lat, col_err = st.columns(2)

with col_lat:
    st.subheader("⏱️ LLM Latency Over Time")
    if "event" in df.columns and "duration_ms" in df.columns:
        llm_df = df[df["event"] == "llm_call"].copy()
        if not llm_df.empty and "_ts" in llm_df.columns:
            llm_df["duration_ms"] = pd.to_numeric(llm_df["duration_ms"], errors="coerce")
            llm_df = llm_df.dropna(subset=["duration_ms"])
            llm_df = llm_df.set_index("_ts").sort_index()
            st.line_chart(llm_df["duration_ms"])
        else:
            st.info("No LLM call latency data yet.")
    else:
        st.info("No LLM call latency data yet.")

with col_err:
    st.subheader("❌ Error Rate Over Time")
    if "level" in df.columns and "_ts" in df.columns:
        err_df = df[df["level"] == "ERROR"].copy()
        if not err_df.empty:
            err_df = err_df.set_index("_ts").sort_index()
            err_df["error"] = 1
            # Resample to 5-minute buckets
            err_resampled = err_df["error"].resample("5min").sum().reset_index()
            err_resampled = err_resampled.set_index("_ts")
            st.bar_chart(err_resampled)
        else:
            st.success("No errors recorded in this window 🎉")
    else:
        st.success("No errors recorded in this window 🎉")

st.markdown("---")

# ---------------------------------------------------------------------------
# Row 4 — Recent log tail
# ---------------------------------------------------------------------------
with st.expander("📋 Recent Log Events (last 50)", expanded=False):
    display_cols = [c for c in ["_ts", "level", "event", "trigger_type", "route",
                                 "duration_ms", "message", "correlation_id"] if c in df.columns]
    recent = df.sort_values("_ts", ascending=False).head(50)[display_cols]
    st.dataframe(recent, use_container_width=True)

st.caption(
    f"Dashboard last loaded: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | "
    "Auto-refreshes on 'Refresh' button click or page reload."
)
