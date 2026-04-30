from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from typing import Any

from . import db as dbmod


def _dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _parse_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _date_in_range(date_text: str | None, start: str | None, end: str | None) -> bool:
    if not date_text:
        return False
    day = date_text[:10]
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _item_matches(
    row: dict[str, Any],
    country: str | None = None,
    event_type: str | None = None,
    population_type: str | None = None,
    signal: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> bool:
    item_date = row.get("published_at") or row.get("retrieved_at")
    if start or end:
        if not _date_in_range(item_date, start, end):
            return False
    if country and country not in _parse_json(row.get("country_codes_json"), []):
        return False
    if event_type and row.get("event_type") != event_type:
        return False
    if population_type and row.get("population_type") != population_type:
        return False
    if signal and row.get("operational_signal") != signal:
        return False
    return True


def get_overview(
    db_path: str,
    country: str | None = None,
    event_type: str | None = None,
    population_type: str | None = None,
    signal: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    conn = dbmod.connect(db_path)
    item_rows = _dicts(dbmod.get_all_items(conn, start_iso=start, end_iso=end))
    filtered = [
        r for r in item_rows
        if _item_matches(r, country=country, event_type=event_type, population_type=population_type, signal=signal)
    ]
    reports = _dicts(conn.execute("SELECT date, report_path, meta_json, created_at FROM reports ORDER BY date DESC LIMIT 10").fetchall())
    anomalies = _dicts(
        conn.execute("SELECT date, item_count, zscore FROM daily_volume WHERE is_anomaly=1 ORDER BY date DESC LIMIT 5").fetchall()
    )
    last_run = conn.execute(
        "SELECT run_id, started_at, finished_at, query_pack_hash, items_fetched, items_new FROM collection_runs ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()

    top_countries = Counter()
    top_signals = Counter()
    top_event_types = Counter()
    for row in filtered:
        top_countries.update(_parse_json(row.get("country_codes_json"), []))
        top_signals.update([row.get("operational_signal") or "monitor"])
        top_event_types.update([row.get("event_type") or "unknown"])

    freshness = []
    source_rows = _dicts(
        conn.execute("SELECT source, MAX(retrieved_at) AS last_seen, COUNT(*) AS records FROM external_events GROUP BY source ORDER BY source").fetchall()
    )
    now = dt.datetime.utcnow()
    for src in source_rows:
        last_seen = src.get("last_seen")
        age_hours = None
        status = "no_data"
        if last_seen:
            try:
                seen_dt = dt.datetime.fromisoformat(last_seen.replace("Z", "+00:00")).replace(tzinfo=None)
                age_hours = round((now - seen_dt).total_seconds() / 3600, 1)
                if age_hours <= 24:
                    status = "fresh"
                elif age_hours <= 72:
                    status = "stale"
                else:
                    status = "very_stale"
            except Exception:
                status = "unknown"
        freshness.append({
            "source": src["source"],
            "last_seen": last_seen,
            "age_hours": age_hours,
            "status": status,
            "records": src["records"],
        })

    conn.close()
    return {
        "filters": {
            "country": country,
            "event_type": event_type,
            "population_type": population_type,
            "signal": signal,
            "start": start,
            "end": end,
        },
        "summary": {
            "items": len(filtered),
            "reports": len(reports),
            "anomaly_days": len(anomalies),
            "avg_confidence": round(sum((r.get("coverage_confidence") or 0.0) for r in filtered) / max(len(filtered), 1), 2),
        },
        "latest_run": dict(last_run) if last_run else None,
        "recent_anomalies": anomalies,
        "top_countries": [{"country_code": code, "items": count} for code, count in top_countries.most_common(8)],
        "top_signals": [{"signal": code, "items": count} for code, count in top_signals.most_common(8)],
        "top_event_types": [{"event_type": code, "items": count} for code, count in top_event_types.most_common(8)],
        "freshness": freshness,
    }


def get_country_summary(
    db_path: str,
    country: str | None = None,
    event_type: str | None = None,
    population_type: str | None = None,
    signal: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    conn = dbmod.connect(db_path)
    rows = _dicts(dbmod.get_all_items(conn, start_iso=start, end_iso=end))
    country_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "country_code": "",
        "items": 0,
        "avg_confidence": 0.0,
        "signals": Counter(),
        "event_types": Counter(),
        "populations": Counter(),
        "latest_date": None,
    })
    for row in rows:
        if not _item_matches(row, country=country, event_type=event_type, population_type=population_type, signal=signal):
            continue
        for code in _parse_json(row.get("country_codes_json"), []):
            stat = country_stats[code]
            stat["country_code"] = code
            stat["items"] += 1
            stat["avg_confidence"] += row.get("coverage_confidence") or 0.0
            stat["signals"].update([row.get("operational_signal") or "monitor"])
            stat["event_types"].update([row.get("event_type") or "unknown"])
            stat["populations"].update([row.get("population_type") or "mixed_or_unspecified"])
            day = (row.get("published_at") or row.get("retrieved_at") or "")[:10]
            if day and (not stat["latest_date"] or day > stat["latest_date"]):
                stat["latest_date"] = day
    conn.close()

    out = []
    for code, stat in country_stats.items():
        out.append({
            "country_code": code,
            "items": stat["items"],
            "avg_confidence": round(stat["avg_confidence"] / max(stat["items"], 1), 2),
            "top_signal": stat["signals"].most_common(1)[0][0] if stat["signals"] else None,
            "top_event_type": stat["event_types"].most_common(1)[0][0] if stat["event_types"] else None,
            "top_population": stat["populations"].most_common(1)[0][0] if stat["populations"] else None,
            "latest_date": stat["latest_date"],
        })
    out.sort(key=lambda x: (-x["items"], x["country_code"]))
    return out


def get_timeseries(db_path: str, country: str | None = None, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    conn = dbmod.connect(db_path)
    volume_rows = _dicts(dbmod.get_daily_volume_series(conn, start_iso=start, end_iso=end))
    if country:
        from .analytics import country_volume_series
        media_series = country_volume_series(conn, country, window_days=365)
        if start or end:
            media_series = [r for r in media_series if _date_in_range(r["date"], start, end)]
    else:
        media_series = [{"date": r["date"], "count": r["item_count"]} for r in volume_rows]

    external_rows = _dicts(dbmod.get_external_events(conn, country_code=country, start_iso=start, end_iso=end))
    metrics: dict[str, dict[str, float]] = defaultdict(dict)
    for row in external_rows:
        day = (row.get("event_date") or "")[:10]
        if not day:
            continue
        metric = row.get("metric_name") or "unknown_metric"
        metrics[metric][day] = metrics[metric].get(day, 0.0) + float(row.get("metric_value") or 0.0)
    conn.close()

    return {
        "media": media_series,
        "metrics": [
            {"metric_name": metric, "series": [{"date": d, "value": value} for d, value in sorted(values.items())]}
            for metric, values in sorted(metrics.items())
        ],
    }


def get_displacement_flows(db_path: str) -> dict[str, Any]:
    conn = dbmod.connect(db_path)
    rows = _dicts(conn.execute("SELECT source, metric_name, raw_json, event_date, country_name, metric_value FROM external_events").fetchall())
    conn.close()

    origin_counter = Counter()
    host_counter = Counter()
    latest_year = None
    parsed_rows = []
    for row in rows:
        year = (row.get("event_date") or "")[:4]
        if year.isdigit():
            latest_year = max(latest_year or year, year)
        parsed_rows.append((row, _parse_json(row.get("raw_json"), {})))

    for row, raw in parsed_rows:
        if latest_year and not str(row.get("event_date", "")).startswith(latest_year):
            continue
        metric_name = row.get("metric_name")
        value = float(row.get("metric_value") or 0.0)
        if row.get("source") == "unhcr_stats":
            coo_name = raw.get("coo_name") or raw.get("coo") or row.get("country_name")
            coa_name = raw.get("coa_name") or raw.get("coa")
            if coo_name and metric_name in ("refugee_stock", "asylum_seeker_stock", "idp_stock"):
                origin_counter.update({coo_name: int(value)})
            if coa_name and metric_name in ("refugee_stock", "asylum_seeker_stock"):
                host_counter.update({coa_name: int(value)})
        elif row.get("source") == "idmc" and metric_name == "idp_stock" and row.get("country_name"):
            origin_counter.update({row["country_name"]: int(value)})

    def _with_badges(counter: Counter) -> list[dict[str, Any]]:
        out = []
        for name, value in counter.most_common(10):
            badge = "watch"
            if value >= 1_000_000:
                badge = "critical"
            elif value >= 500_000:
                badge = "high"
            elif value >= 100_000:
                badge = "elevated"
            out.append({"name": name, "value": value, "badge": badge})
        return out

    return {"origins": _with_badges(origin_counter), "hosts": _with_badges(host_counter), "latest_year": latest_year}


def get_briefs(db_path: str, date: str | None = None) -> dict[str, Any]:
    conn = dbmod.connect(db_path)
    reports = _dicts(conn.execute("SELECT date, report_path, docx_path, meta_json, created_at FROM reports ORDER BY date DESC").fetchall())
    conn.close()

    chosen = None
    for report in reports:
        if date is None or report["date"] == date:
            chosen = report
            break

    brief_text = None
    if chosen and chosen.get("report_path"):
        try:
            with open(chosen["report_path"], "r", encoding="utf-8") as f:
                brief_text = f.read()
        except OSError:
            brief_text = None

    return {
        "reports": [
            {
                "date": report["date"],
                "created_at": report["created_at"],
                "meta": _parse_json(report.get("meta_json"), {}),
                "report_path": report.get("report_path"),
            }
            for report in reports[:30]
        ],
        "selected_date": chosen["date"] if chosen else None,
        "brief_markdown": brief_text,
    }


def get_filter_options(db_path: str) -> dict[str, list[str]]:
    conn = dbmod.connect(db_path)
    rows = _dicts(dbmod.get_all_items(conn))
    conn.close()
    return {
        "countries": sorted({code for r in rows for code in _parse_json(r.get("country_codes_json"), [])}),
        "event_types": sorted({r.get("event_type") for r in rows if r.get("event_type")}),
        "population_types": sorted({r.get("population_type") for r in rows if r.get("population_type")}),
        "signals": sorted({r.get("operational_signal") for r in rows if r.get("operational_signal")}),
    }
