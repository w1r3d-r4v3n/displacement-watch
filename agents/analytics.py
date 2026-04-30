"""
Predictive analytics module for displacement coverage data.

Provides:
- Daily coverage volume with rolling z-scores (anomaly detection)
- Velocity spike detection (leading-indicator alerts)
- Keyword week-over-week velocity
- Per-country coverage time series
- Optional Granger causality test (requires statsmodels)
"""
from __future__ import annotations
import collections, datetime as dt, json
from typing import Any

import numpy as np

from . import db as dbmod

try:
    from scipy import stats as _scipy_stats
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

try:
    from statsmodels.tsa.stattools import grangercausalitytests as _granger
    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False


def _date_range(start: dt.date, end: dt.date) -> list[str]:
    days = (end - start).days + 1
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]


def compute_daily_volume(
    conn: Any,
    window_days: int = 90,
    threshold: float = 2.0,
) -> list[dict]:
    """
    Returns a contiguous daily series with rolling 7-day z-scores.
    Persists results to daily_volume table.
    """
    end_dt = dt.datetime.utcnow()
    start_dt = end_dt - dt.timedelta(days=window_days)
    rows = dbmod.get_items_for_window(
        conn,
        start_dt.isoformat() + "Z",
        end_dt.isoformat() + "Z",
    )

    # Count by publication date (fall back to retrieved_at date)
    counts: dict[str, int] = collections.Counter()
    for r in rows:
        raw = r["published_at"] or r["retrieved_at"] or ""
        if raw:
            counts[raw[:10]] += 1

    # Fill contiguous date range (gaps become 0)
    all_dates = _date_range(start_dt.date(), end_dt.date())
    series = [counts.get(d, 0) for d in all_dates]

    # Rolling 7-day mean and std (centre on each day using preceding 6 days + current)
    result = []
    for i, (date, count) in enumerate(zip(all_dates, series)):
        window = series[max(0, i - 6): i + 1]
        mean = float(np.mean(window))
        std = float(np.std(window, ddof=0))
        if std > 0:
            zscore = round((count - mean) / std, 3)
        else:
            zscore = 0.0
        is_anomaly = int(abs(zscore) > threshold)
        entry = {
            "date": date,
            "count": count,
            "rolling_7d_mean": round(mean, 2),
            "rolling_7d_std": round(std, 3),
            "zscore": zscore,
            "is_anomaly": is_anomaly,
        }
        result.append(entry)
        # Persist
        sel_rows = dbmod.get_daily_volume_series(conn, date, date)
        selected_count = sel_rows[0]["selected_count"] if sel_rows else 0
        dbmod.upsert_daily_volume(conn, date, count, selected_count, zscore, is_anomaly)

    return result


def detect_velocity_spikes(
    volume_series: list[dict],
    lookback: int = 7,
    threshold_pct: float = 50.0,
) -> list[dict]:
    """
    Returns rows where count increased > threshold_pct% over the rolling mean.
    These are leading-indicator alert candidates.
    """
    spikes = []
    for entry in volume_series:
        mean = entry.get("rolling_7d_mean", 0)
        count = entry.get("count", 0)
        if mean > 0:
            pct_change = round((count - mean) / mean * 100, 1)
        else:
            pct_change = 0.0
        is_spike = pct_change >= threshold_pct
        spikes.append({
            "date": entry["date"],
            "count": count,
            "rolling_mean": mean,
            "pct_change": pct_change,
            "is_spike": is_spike,
        })
    return [s for s in spikes if s["is_spike"]]


def keyword_velocity(
    conn: Any,
    window_days: int = 30,
    min_count: int = 3,
) -> list[dict]:
    """
    Week-over-week keyword velocity: (last_7d - prev_7d) / prev_7d * 100.
    Returns entries sorted by velocity descending.
    """
    now = dt.datetime.utcnow()
    last7_start = (now - dt.timedelta(days=7)).isoformat() + "Z"
    prev7_start = (now - dt.timedelta(days=14)).isoformat() + "Z"
    prev7_end = (now - dt.timedelta(days=7)).isoformat() + "Z"

    last7_rows = dbmod.get_items_for_window(conn, last7_start, now.isoformat() + "Z")
    prev7_rows = dbmod.get_items_for_window(conn, prev7_start, prev7_end)

    def _count(rows: list) -> collections.Counter:
        c: collections.Counter = collections.Counter()
        for r in rows:
            kws = json.loads(r["keywords_hit_json"] or "[]")
            c.update(kws)
        return c

    last7 = _count(last7_rows)
    prev7 = _count(prev7_rows)
    all_kws = set(last7.keys()) | set(prev7.keys())

    result = []
    for kw in all_kws:
        l = last7.get(kw, 0)
        p = prev7.get(kw, 0)
        if l + p < min_count:
            continue
        if p > 0:
            velocity = round((l - p) / p * 100, 1)
        elif l > 0:
            velocity = 100.0  # appeared from zero
        else:
            velocity = 0.0
        result.append({"keyword": kw, "last_7d": l, "prev_7d": p, "velocity_pct": velocity})

    result.sort(key=lambda x: x["velocity_pct"], reverse=True)
    return result


def country_volume_series(
    conn: Any,
    country_code: str,
    window_days: int = 90,
) -> list[dict]:
    """Daily item count for a specific ISO country code."""
    end_dt = dt.datetime.utcnow()
    start_dt = end_dt - dt.timedelta(days=window_days)
    rows = dbmod.get_all_items(
        conn,
        start_iso=start_dt.isoformat() + "Z",
        end_iso=end_dt.isoformat() + "Z",
        country_code=country_code,
    )

    counts: dict[str, int] = collections.Counter()
    for r in rows:
        raw = r["published_at"] or r["retrieved_at"] or ""
        if raw:
            counts[raw[:10]] += 1

    all_dates = _date_range(start_dt.date(), end_dt.date())
    return [{"date": d, "count": counts.get(d, 0), "country_code": country_code} for d in all_dates]


def granger_causality_summary(
    media_series: list[float],
    event_series: list[float],
    max_lag: int = 7,
) -> dict | None:
    """
    Test whether media coverage Granger-causes displacement events.
    Requires statsmodels. Returns None if not available.

    Parameters
    ----------
    media_series : list[float]
        Daily media item counts (same length as event_series)
    event_series : list[float]
        Daily external event metric values (e.g. ACLED fatalities)
    max_lag : int
        Maximum lag in days to test

    Returns
    -------
    dict with pvalues_by_lag and min_pvalue_lag, or None
    """
    if not _HAS_STATSMODELS:
        return None
    if len(media_series) != len(event_series) or len(media_series) < max_lag * 2 + 1:
        return None

    try:
        data = list(zip(event_series, media_series))
        test_results = _granger(data, maxlag=max_lag, verbose=False)
        pvalues: dict[int, float] = {}
        for lag, res_dict in test_results.items():
            # Use F-test p-value (ssr_ftest)
            pvalues[lag] = float(res_dict[0]["ssr_ftest"][1])
        min_lag = min(pvalues, key=lambda k: pvalues[k])
        return {
            "pvalues_by_lag": pvalues,
            "min_pvalue_lag": min_lag,
            "min_pvalue": pvalues[min_lag],
            "significant_at_05": pvalues[min_lag] < 0.05,
        }
    except Exception:
        return None


def compute_all_analytics(db_path: str, window_days: int = 90) -> dict:
    """
    Orchestrator: compute all analytics, persist daily_volume, return JSON-serializable summary.
    """
    conn = dbmod.connect(db_path)
    volume = compute_daily_volume(conn, window_days=window_days)
    spikes = detect_velocity_spikes(volume)
    kw_vel = keyword_velocity(conn, window_days=window_days)
    conn.close()

    anomalies = [v for v in volume if v["is_anomaly"]]

    return {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "window_days": window_days,
        "total_days": len(volume),
        "anomaly_days": len(anomalies),
        "spike_days": len(spikes),
        "anomalies": anomalies,
        "velocity_spikes": spikes,
        "keyword_velocity": kw_vel[:20],  # top 20 by velocity
        "volume_series": volume,
    }
