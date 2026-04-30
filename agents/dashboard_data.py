from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from typing import Any
import csv
import io

from . import db as dbmod

COUNTRY_CENTROIDS = {
    "AF": (33.0, 65.0), "AO": (-12.3, 17.5), "BD": (24.0, 90.0), "BF": (12.2, -1.6),
    "BI": (-3.4, 29.9), "CF": (6.6, 20.9), "CD": (-2.8, 23.6), "CG": (-0.8, 15.2),
    "CM": (5.7, 12.7), "CO": (4.6, -74.1), "EC": (-1.8, -78.2), "EG": (26.8, 30.8),
    "ER": (15.3, 39.3), "ET": (9.1, 40.5), "GN": (10.4, -10.9), "GT": (15.6, -90.2),
    "HT": (18.9, -72.3), "HN": (14.8, -86.2), "IQ": (33.2, 43.7), "IR": (32.4, 53.7),
    "JO": (31.2, 36.4), "KE": (0.2, 37.9), "KG": (41.2, 74.8), "KH": (12.6, 104.9),
    "KZ": (48.0, 67.0), "LB": (33.9, 35.8), "LR": (6.4, -9.4), "LY": (26.3, 17.2),
    "MA": (31.8, -7.1), "MG": (-18.8, 46.9), "ML": (17.5, -3.9), "MM": (21.2, 96.0),
    "MR": (20.3, -10.4), "MW": (-13.3, 34.3), "MX": (23.6, -102.5), "MZ": (-18.7, 35.5),
    "NE": (17.6, 9.4), "NG": (9.1, 8.7), "NI": (12.9, -85.2), "PK": (30.4, 69.3),
    "PS": (31.9, 35.2), "RW": (-1.9, 29.9), "SD": (15.6, 32.5), "SL": (8.5, -11.8),
    "SO": (5.2, 46.2), "SS": (7.3, 30.3), "SY": (35.0, 38.5), "TD": (15.4, 18.7),
    "TJ": (38.6, 71.0), "TN": (34.0, 9.6), "TZ": (-6.3, 34.8), "UA": (49.0, 31.3),
    "UG": (1.4, 32.3), "UZ": (41.3, 64.6), "VE": (7.0, -66.0), "VN": (16.0, 108.0),
    "YE": (15.6, 48.5), "ZA": (-30.6, 22.9), "ZM": (-13.1, 27.8), "ZW": (-19.0, 29.2),
}


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
        media_component = min(40.0, stat["items"] * 1.8)
        confidence_component = min(15.0, (stat["avg_confidence"] / max(stat["items"], 1)) * 15.0)
        signal_component = min(20.0, sum(
            5 if name in ("access_constraint", "protection_risk", "funding_gap", "border_restriction") else 2
            for name, _count in stat["signals"].most_common(3)
        ))
        external_component = 0.0
        out.append({
            "country_code": code,
            "items": stat["items"],
            "avg_confidence": round(stat["avg_confidence"] / max(stat["items"], 1), 2),
            "top_signal": stat["signals"].most_common(1)[0][0] if stat["signals"] else None,
            "top_event_type": stat["event_types"].most_common(1)[0][0] if stat["event_types"] else None,
            "top_population": stat["populations"].most_common(1)[0][0] if stat["populations"] else None,
            "latest_date": stat["latest_date"],
            "risk_score": round(media_component + confidence_component + signal_component + external_component, 1),
        })
    out.sort(key=lambda x: (-x["risk_score"], -x["items"], x["country_code"]))
    return out


def get_country_detail(db_path: str, country: str, limit: int = 25) -> dict[str, Any]:
    conn = dbmod.connect(db_path)
    rows = _dicts(dbmod.get_all_items(conn))
    filtered = [r for r in rows if country in _parse_json(r.get("country_codes_json"), [])]
    filtered.sort(key=lambda r: (r.get("published_at") or r.get("retrieved_at") or ""), reverse=True)
    ext_rows = _dicts(dbmod.get_external_events(conn, country_code=country))
    conn.close()

    signal_counter = Counter((r.get("operational_signal") or "monitor") for r in filtered)
    event_counter = Counter((r.get("event_type") or "unknown") for r in filtered)
    population_counter = Counter((r.get("population_type") or "mixed_or_unspecified") for r in filtered)
    latest_items = []
    for row in filtered[:limit]:
        latest_items.append({
            "title": row.get("title"),
            "publisher": row.get("publisher") or row.get("domain"),
            "published_at": row.get("published_at") or row.get("retrieved_at"),
            "event_type": row.get("event_type"),
            "signal": row.get("operational_signal"),
            "population_type": row.get("population_type"),
            "url": row.get("url"),
            "confidence": row.get("coverage_confidence"),
        })
    metrics = Counter()
    for row in ext_rows:
        metrics.update([row.get("metric_name") or "unknown_metric"])
    return {
        "country_code": country,
        "summary": {
            "items": len(filtered),
            "avg_confidence": round(sum((r.get("coverage_confidence") or 0.0) for r in filtered) / max(len(filtered), 1), 2),
            "top_signal": signal_counter.most_common(1)[0][0] if signal_counter else None,
            "top_event_type": event_counter.most_common(1)[0][0] if event_counter else None,
            "top_population": population_counter.most_common(1)[0][0] if population_counter else None,
            "external_metrics": metrics.most_common(),
        },
        "latest_items": latest_items,
    }


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


def get_map_points(db_path: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    countries = get_country_summary(db_path, start=start, end=end)
    points = []
    for row in countries:
        coords = COUNTRY_CENTROIDS.get(row["country_code"])
        if not coords:
            continue
        points.append({
            "country_code": row["country_code"],
            "lat": coords[0],
            "lon": coords[1],
            "items": row["items"],
            "risk_score": row["risk_score"],
            "top_signal": row["top_signal"],
        })
    return {"points": points}


def build_export_csv_bytes(db_path: str, country: str | None = None, start: str | None = None, end: str | None = None) -> bytes:
    conn = dbmod.connect(db_path)
    rows = _dicts(dbmod.get_all_items(conn, start_iso=start, end_iso=end, country_code=country))
    conn.close()
    sio = io.StringIO()
    writer = csv.DictWriter(
        sio,
        fieldnames=["title", "publisher", "published_at", "event_type", "population_type", "operational_signal", "coverage_confidence", "url"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "title": row.get("title"),
            "publisher": row.get("publisher") or row.get("domain"),
            "published_at": row.get("published_at") or row.get("retrieved_at"),
            "event_type": row.get("event_type"),
            "population_type": row.get("population_type"),
            "operational_signal": row.get("operational_signal"),
            "coverage_confidence": row.get("coverage_confidence"),
            "url": row.get("url"),
        })
    return sio.getvalue().encode("utf-8")
