from __future__ import annotations
import csv, json, os, hashlib, datetime as dt
from typing import Any

from . import db as dbmod
from .trends import rolling_trends

CODEBOOK = """# Displacement Watch — Research Data Codebook

## items.csv / selected.csv columns

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | 16-char SHA256 stable identifier (canonical_url + lowercase title) |
| canonical_url | TEXT | De-tracked URL (utm_* / fbclid / gclid params stripped) |
| url | TEXT | Original URL as published |
| title | TEXT | Article headline |
| publisher | TEXT | Feed name or source domain |
| domain | TEXT | Bare domain (no www) |
| published_at | TEXT | ISO 8601 UTC publication timestamp (nullable) |
| retrieved_at | TEXT | ISO 8601 UTC collection timestamp |
| snippet | TEXT | Article excerpt / RSS summary (≤1000 chars) |
| language | TEXT | BCP-47 language code (nullable; mainly from GDELT) |
| tier | TEXT | Source reliability tier: A=UNHCR/UN/IOM/ReliefWeb, B=Reuters/AP/BBC/etc, C=other known, U=unranked |
| source_type | TEXT | "rss" or "gdelt" |
| keywords_hit | TEXT | Pipe-delimited list of matched mission keywords |
| collection_run_id | TEXT | ISO datetime string identifying the collection batch |
| country_codes | TEXT | Pipe-delimited ISO 3166-1 alpha-2 codes extracted from text/GDELT |
| un_region | TEXT | UN macro-region (e.g. "Western Asia", "Sub-Saharan Africa") |
| provenance_hash | TEXT | SHA256(query_pack_version + collection_run_id)[:16] for reproducibility |
| event_type | TEXT | Structured article coding for event or development type |
| population_type | TEXT | Main affected population category |
| driver | TEXT | Inferred displacement driver |
| displacement_stage | TEXT | Acute movement, ongoing, returns/restrictions, or response/protection |
| location_precision | TEXT | unknown, national, subnational, or regional |
| operational_signal | TEXT | Field-oriented signal label such as access_constraint or funding_gap |
| coverage_confidence | REAL | Heuristic confidence score for triage and filtering |
| research_priority | TEXT | high or medium research relevance |
| field_priority | TEXT | high, medium, or monitor operational urgency |
| score | REAL | (selected.csv only) Ranking score: tier_weight + keyword_bonus + recency_decay |
| selection_date | TEXT | (selected.csv only) Date this item was selected for the daily brief |

## Scoring formula

score = tier_weight + keyword_bonus + recency_decay

- tier_weight: A=3.0, B=2.0, C=1.0, U=0.7
- keyword_bonus: min(keyword_hit_count, 4) * 0.5
- recency_decay: max(0.1, 1.5 - min(age_hours/48, 1.4))

## daily_volume.csv columns

| Column | Description |
|--------|-------------|
| date | ISO date (YYYY-MM-DD) |
| item_count | Total items published on this date in the DB |
| selected_count | Items selected for the daily brief on this date |
| zscore | Z-score of item_count relative to 7-day rolling mean/std |
| is_anomaly | 1 if |zscore| > 2.0, else 0 |

## Source tiers

- **Tier A**: reliefweb.int, unhcr.org, iom.int, un.org — primary humanitarian sources
- **Tier B**: reuters.com, apnews.com, bbc.com, aljazeera.com, theguardian.com — major news outlets
- **Tier C**: Other known/configured sources
- **Tier U**: Unranked / not on whitelist (treat with lower confidence)

## Data limitations

- GDELT covers English-language content predominantly; non-English displacement reporting is underrepresented.
- RSS feeds expose only the current ~30-day window; historical data requires the `backfill` command using GDELT date params.
- Country tagging is heuristic (text scan + GDELT FIPS field); multi-country stories may tag multiple codes.
- The `published_at` field is nullable for some GDELT articles; use `retrieved_at` as fallback for time ordering.

## Reproducibility

Each collection batch is identified by `collection_run_id`. The `provenance_hash` ties items to the specific
query_pack version used. To reproduce a collection, record the `query_pack_version` from `collection_runs`
and use the same `config/query_pack.json` version with the `run-daily` command.

## External events (external_events.csv)

| Column | Description |
|--------|-------------|
| id | Stable identifier (source + country + date + metric) |
| source | "idmc", "acled", or "unhcr_stats" |
| event_date | ISO date of the event or reporting period start |
| country_code | ISO 3166-1 alpha-2 |
| metric_name | e.g. "idp_stock", "fatalities", "refugee_stock" |
| metric_value | Numeric value (annual figures for IDMC/UNHCR; event count for ACLED) |

ACLED and IDMC data are subject to their respective terms of use. ACLED requires free researcher registration.
"""


def _row_to_dict(row: Any) -> dict:
    if hasattr(row, "keys"):
        return dict(row)
    return row


def export_items_csv(
    db_path: str,
    out_path: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
    country_code: str | None = None,
) -> dict:
    conn = dbmod.connect(db_path)
    rows = dbmod.get_all_items(conn, start_iso=start_iso, end_iso=end_iso, country_code=country_code)
    conn.close()

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fieldnames = [
        "id", "canonical_url", "url", "title", "publisher", "domain",
        "published_at", "retrieved_at", "snippet", "language",
        "tier", "source_type", "keywords_hit", "collection_run_id",
        "country_codes", "un_region", "provenance_hash", "event_type", "population_type",
        "driver", "displacement_stage", "location_precision", "operational_signal",
        "coverage_confidence", "research_priority", "field_priority",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            d = _row_to_dict(row)
            d["keywords_hit"] = "|".join(json.loads(d.get("keywords_hit_json") or "[]"))
            d["country_codes"] = "|".join(json.loads(d.get("country_codes_json") or "[]"))
            writer.writerow(d)

    return {"rows": len(rows), "path": out_path}


def export_selected_csv(
    db_path: str,
    out_path: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> dict:
    conn = dbmod.connect(db_path)
    cur = conn.cursor()
    clauses = []
    params: list[Any] = []
    if start_iso:
        clauses.append("ds.date >= ?")
        params.append(start_iso)
    if end_iso:
        clauses.append("ds.date <= ?")
        params.append(end_iso)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur.execute(
        f"""SELECT i.*, ds.score, ds.date AS selection_date
            FROM daily_selected ds
            JOIN items i ON i.id = ds.item_id
            {where}
            ORDER BY ds.date DESC, ds.score DESC""",
        params,
    )
    rows = cur.fetchall()
    conn.close()

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fieldnames = [
        "id", "canonical_url", "url", "title", "publisher", "domain",
        "published_at", "retrieved_at", "snippet", "language",
        "tier", "source_type", "keywords_hit", "collection_run_id",
        "country_codes", "un_region", "provenance_hash", "event_type", "population_type",
        "driver", "displacement_stage", "location_precision", "operational_signal",
        "coverage_confidence", "research_priority", "field_priority",
        "score", "selection_date",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            d = _row_to_dict(row)
            d["keywords_hit"] = "|".join(json.loads(d.get("keywords_hit_json") or "[]"))
            d["country_codes"] = "|".join(json.loads(d.get("country_codes_json") or "[]"))
            writer.writerow(d)

    return {"rows": len(rows), "path": out_path}


def export_trends_json(
    db_path: str,
    out_path: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> dict:
    trends = rolling_trends(db_path)

    conn = dbmod.connect(db_path)
    vol_rows = dbmod.get_daily_volume_series(conn, start_iso=start_iso, end_iso=end_iso)
    conn.close()

    volume_series = [
        {
            "date": r["date"],
            "count": r["item_count"],
            "selected_count": r["selected_count"],
            "zscore": r["zscore"],
            "is_anomaly": bool(r["is_anomaly"]),
        }
        for r in vol_rows
    ]

    out = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "date_range": {"start": start_iso, "end": end_iso},
        "rolling_trends": {
            "7d": {
                "item_count": trends["counts"]["7d"],
                "top_keywords": trends["7d"]["keywords"],
                "top_publishers": trends["7d"]["publishers"],
                "tier_breakdown": trends["7d"]["tiers"],
                "theme_counts": trends["7d"]["themes"],
            },
            "30d": {
                "item_count": trends["counts"]["30d"],
                "top_keywords": trends["30d"]["keywords"],
                "top_publishers": trends["30d"]["publishers"],
                "tier_breakdown": trends["30d"]["tiers"],
                "theme_counts": trends["30d"]["themes"],
            },
        },
        "volume_series": volume_series,
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    return {"path": out_path, "volume_points": len(volume_series)}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_csv_rows(path: str) -> int:
    with open(path, newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)  # subtract header


def build_research_package(
    db_path: str,
    out_dir: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
    include_external: bool = False,
    query_pack_path: str = "config/query_pack.json",
) -> dict:
    os.makedirs(out_dir, exist_ok=True)

    files: dict[str, dict] = {}

    def _track(name: str, result: dict | None = None) -> str:
        path = os.path.join(out_dir, name)
        sha = _sha256_file(path)
        entry: dict = {"sha256": sha}
        if result:
            entry.update({k: v for k, v in result.items() if k != "path"})
        files[name] = entry
        return path

    # items.csv
    r = export_items_csv(db_path, os.path.join(out_dir, "items.csv"), start_iso, end_iso)
    _track("items.csv", r)

    # selected.csv
    r = export_selected_csv(db_path, os.path.join(out_dir, "selected.csv"), start_iso, end_iso)
    _track("selected.csv", r)

    # daily_volume.csv
    conn = dbmod.connect(db_path)
    vol_rows = dbmod.get_daily_volume_series(conn, start_iso, end_iso)
    vol_path = os.path.join(out_dir, "daily_volume.csv")
    with open(vol_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "item_count", "selected_count", "zscore", "is_anomaly"])
        w.writeheader()
        for row in vol_rows:
            w.writerow(dict(row))
    _track("daily_volume.csv", {"rows": len(vol_rows)})

    # trends.json
    r = export_trends_json(db_path, os.path.join(out_dir, "trends.json"), start_iso, end_iso)
    _track("trends.json", r)

    # analytics.json — import lazily so analytics module is optional
    try:
        from .analytics import compute_all_analytics
        analytics = compute_all_analytics(db_path)
        analytics_path = os.path.join(out_dir, "analytics.json")
        with open(analytics_path, "w", encoding="utf-8") as f:
            json.dump(analytics, f, indent=2)
        _track("analytics.json")
    except Exception as exc:
        files["analytics.json"] = {"error": str(exc)}

    # citations
    try:
        from .cite import items_to_bibtex, items_to_ris
        selected_rows = dbmod.get_all_items(conn, start_iso, end_iso)
        bib_path = os.path.join(out_dir, "citations.bib")
        ris_path = os.path.join(out_dir, "citations.ris")
        with open(bib_path, "w", encoding="utf-8") as f:
            f.write(items_to_bibtex(selected_rows))
        with open(ris_path, "w", encoding="utf-8") as f:
            f.write(items_to_ris(selected_rows))
        _track("citations.bib")
        _track("citations.ris")
    except Exception as exc:
        files["citations.bib"] = {"error": str(exc)}

    conn.close()

    # external_events.csv
    if include_external:
        conn2 = dbmod.connect(db_path)
        ext_rows = dbmod.get_external_events(conn2, start_iso=start_iso, end_iso=end_iso)
        conn2.close()
        ext_path = os.path.join(out_dir, "external_events.csv")
        with open(ext_path, "w", newline="", encoding="utf-8") as f:
            w2 = csv.DictWriter(f, fieldnames=["id","source","event_date","country_code","country_name","region","metric_name","metric_value","retrieved_at"])
            w2.writeheader()
            for row in ext_rows:
                d = dict(row)
                d.pop("raw_json", None)
                w2.writerow(d)
        _track("external_events.csv", {"rows": len(ext_rows)})

    # query_pack_snapshot.json
    snapshot_path = os.path.join(out_dir, "query_pack_snapshot.json")
    try:
        with open(query_pack_path, "r", encoding="utf-8") as f:
            qp = json.load(f)
        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(qp, f, indent=2)
        _track("query_pack_snapshot.json")
    except Exception as exc:
        files["query_pack_snapshot.json"] = {"error": str(exc)}

    # codebook.md
    codebook_path = os.path.join(out_dir, "codebook.md")
    with open(codebook_path, "w", encoding="utf-8") as f:
        f.write(CODEBOOK)
    _track("codebook.md")

    # manifest.json
    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "tool_version": "2.1.0",
        "date_range": {"start": start_iso, "end": end_iso},
        "files": files,
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest
