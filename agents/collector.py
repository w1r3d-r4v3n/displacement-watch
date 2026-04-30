from __future__ import annotations
import json, datetime as dt, requests, feedparser
from dateutil import parser as dtparser
from typing import Any
from .utils import canonicalize_url, stable_id, norm_text, has_negative, keyword_hits, domain_from_url, provenance_hash
from .geo_tag import tag_items_batch
from . import db as dbmod

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

def _iso_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def load_query_pack(path: str = "config/query_pack.json") -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def tier_for_domain(domain: str, source_tiers: dict[str, list[str]]) -> str:
    for tier, domains in source_tiers.items():
        for d in domains:
            if domain.endswith(d):
                return tier
    return "U"

def parse_feed(feed_url: str, feed_name: str, query_pack: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(feed_url)
    out: list[dict[str, Any]] = []
    for e in parsed.entries:
        title = norm_text(getattr(e, "title", ""))
        link = getattr(e, "link", None)
        summary = norm_text(getattr(e, "summary", ""))
        text_blob = f"{title} {summary}"
        if not link or has_negative(text_blob, query_pack["negative_keywords"]):
            continue
        hits = keyword_hits(text_blob, query_pack["keywords"])
        if not hits:
            continue
        pub = None
        for attr in ("published", "updated"):
            val = getattr(e, attr, None)
            if val:
                try:
                    pub = dtparser.parse(val).astimezone(dt.timezone.utc).replace(tzinfo=None).isoformat() + "Z"
                    break
                except Exception:
                    pass
        c_url = canonicalize_url(link)
        domain = domain_from_url(c_url)
        out.append({
            "id": stable_id(c_url, title),
            "canonical_url": c_url,
            "url": link,
            "title": title,
            "publisher": feed_name,
            "domain": domain,
            "published_at": pub,
            "retrieved_at": _iso_now(),
            "snippet": summary[:1000],
            "full_text": None,
            "language": None,
            "tier": tier_for_domain(domain, query_pack["source_tiers"]),
            "keywords_hit": hits,
            "source_type": "rss",
            "collection_run_id": run_id,
        })
    return out

def query_gdelt(query_pack: dict[str, Any], max_records: int, run_id: str) -> list[dict[str, Any]]:
    params = {
        "query": query_pack["gdelt_query"],
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "sort": "DateDesc",
    }
    r = requests.get(GDELT_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    out: list[dict[str, Any]] = []
    for a in data.get("articles", []):
        title = norm_text(a.get("title", ""))
        snippet = norm_text(a.get("seendate", "")) + " " + norm_text(a.get("socialimage",""))
        url = a.get("url")
        if not url:
            continue
        text_blob = f"{title} {a.get('sourceCollection','')} {a.get('domain','')}"
        if has_negative(text_blob, query_pack["negative_keywords"]):
            continue
        hits = keyword_hits(title, query_pack["keywords"])
        if not hits:
            hits = keyword_hits(text_blob, query_pack["keywords"])
        if not hits:
            continue
        c_url = canonicalize_url(url)
        domain = domain_from_url(c_url)
        pub = a.get("seendate")
        published_at = None
        if pub:
            try:
                published_at = dt.datetime.strptime(pub, "%Y%m%dT%H%M%SZ").isoformat() + "Z"
            except Exception:
                published_at = None
        out.append({
            "id": stable_id(c_url, title),
            "canonical_url": c_url,
            "url": url,
            "title": title,
            "publisher": a.get("domain", domain),
            "domain": domain,
            "published_at": published_at,
            "retrieved_at": _iso_now(),
            "snippet": norm_text(a.get("sourceCountry",""))[:1000],
            "full_text": None,
            "language": a.get("language"),
            "tier": tier_for_domain(domain, query_pack["source_tiers"]),
            "keywords_hit": hits,
            "source_type": "gdelt",
            "collection_run_id": run_id,
        })
    return out

def score_item(item: dict[str, Any]) -> float:
    tier_w = {"A": 3.0, "B": 2.0, "C": 1.0, "U": 0.7}.get(item.get("tier","U"), 0.7)
    kw = min(len(item.get("keywords_hit",[])), 4) * 0.5
    recency = 1.0
    if item.get("published_at"):
        try:
            t = dtparser.parse(item["published_at"])
            age_h = max((dt.datetime.now(dt.timezone.utc) - t.astimezone(dt.timezone.utc)).total_seconds()/3600, 0)
            recency = max(0.1, 1.5 - min(age_h/48, 1.4))
        except Exception:
            pass
    return round(tier_w + kw + recency, 3)

def collect_and_persist(db_path: str, since_hours: int = 24, max_gdelt: int = 100) -> dict[str, Any]:
    q = load_query_pack()
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    items: list[dict[str, Any]] = []
    for feed in q["rss_feeds"]:
        try:
            items.extend(parse_feed(feed["url"], feed["name"], q, run_id))
        except Exception as e:
            print(f"[collector] feed failed: {feed['name']}: {e}")
    try:
        items.extend(query_gdelt(q, max_gdelt, run_id))
    except Exception as e:
        print(f"[collector] gdelt failed: {e}")

    # Dedupe by id/canonical_url, keep highest scored or richer metadata
    dedup = {}
    for it in items:
        key = it["id"]
        if key not in dedup:
            dedup[key] = it
        else:
            if score_item(it) > score_item(dedup[key]):
                dedup[key] = it
    items = list(dedup.values())

    # Enrich items with country codes and UN region
    items = tag_items_batch(items)

    # Attach provenance hash
    qp_version = q.get("version", 0)
    for it in items:
        it["provenance_hash"] = provenance_hash(qp_version, run_id)

    conn = dbmod.connect(db_path)
    started_at = (dt.datetime.utcnow() - dt.timedelta(hours=since_hours)).isoformat() + "Z"
    n = dbmod.upsert_items(conn, items)

    end = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    start = (dt.datetime.utcnow() - dt.timedelta(hours=since_hours)).replace(microsecond=0).isoformat() + "Z"
    rows = dbmod.get_items_for_window(conn, start, end)
    selected_scored = []
    for r in rows:
        item = dict(r)
        item["keywords_hit"] = json.loads(item.get("keywords_hit_json") or "[]")
        selected_scored.append((item["id"], score_item(item)))
    selected_scored.sort(key=lambda x: x[1], reverse=True)
    date_key = dt.datetime.utcnow().date().isoformat()
    top = selected_scored[: max(5, q["report"].get("max_top_developments", 8))]
    dbmod.save_daily_selected(conn, date_key, top)

    import hashlib as _hl, json as _json
    qp_hash = _hl.sha256(_json.dumps(q, sort_keys=True).encode()).hexdigest()
    finished_at = dt.datetime.utcnow().isoformat() + "Z"
    dbmod.save_collection_run(conn, {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "query_pack_version": qp_version,
        "query_pack_hash": qp_hash,
        "items_fetched": len(items),
        "items_new": n,
        "sources": [f["name"] for f in q.get("rss_feeds", [])] + ["gdelt"],
    })
    conn.close()

    return {"run_id": run_id, "inserted_or_updated": n, "window_items": len(rows), "selected": len(top), "date": date_key}


RELIEFWEB_API = "https://api.reliefweb.int/v1/reports"


def _query_reliefweb_date(date_iso: str, query_pack: dict, run_id: str, limit: int = 100) -> list[dict]:
    """Fetch ReliefWeb articles published on a specific date via the REST API."""
    payload = {
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "date.created", "value": {"from": f"{date_iso}T00:00:00+00:00", "to": f"{date_iso}T23:59:59+00:00"}},
            ],
        },
        "fields": {"include": ["title", "url", "date", "source", "body-html", "language"]},
        "limit": limit,
        "sort": ["date.created:desc"],
    }
    try:
        r = requests.post(f"{RELIEFWEB_API}?appname=displacement-watch", json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"[backfill] ReliefWeb API failed for {date_iso}: {exc}")
        return []

    out = []
    for item in data.get("data", []):
        fields = item.get("fields", {})
        title = norm_text(fields.get("title", ""))
        url = fields.get("url", "")
        if not url or not title:
            continue
        text_blob = title
        if has_negative(text_blob, query_pack["negative_keywords"]):
            continue
        hits = keyword_hits(text_blob, query_pack["keywords"])
        if not hits:
            continue
        pub_raw = (fields.get("date") or {}).get("created")
        published_at = None
        if pub_raw:
            try:
                from dateutil import parser as _dtparser
                published_at = _dtparser.parse(pub_raw).astimezone(dt.timezone.utc).replace(tzinfo=None).isoformat() + "Z"
            except Exception:
                pass
        c_url = canonicalize_url(url)
        domain = domain_from_url(c_url)
        out.append({
            "id": stable_id(c_url, title),
            "canonical_url": c_url,
            "url": url,
            "title": title,
            "publisher": "ReliefWeb",
            "domain": domain,
            "published_at": published_at or f"{date_iso}T00:00:00Z",
            "retrieved_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "snippet": norm_text(fields.get("body-html", ""))[:1000],
            "full_text": None,
            "language": (fields.get("language") or [{}])[0].get("code"),
            "tier": tier_for_domain(domain, query_pack["source_tiers"]),
            "keywords_hit": hits,
            "source_type": "rss",
            "collection_run_id": run_id,
        })
    return out


def _query_gdelt_date(date_iso: str, query_pack: dict, run_id: str, max_records: int = 250) -> list[dict]:
    """Fetch GDELT articles for a specific date using startdatetime/enddatetime params."""
    date_fmt = date_iso.replace("-", "")
    params = {
        "query": query_pack["gdelt_query"],
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "sort": "DateDesc",
        "startdatetime": f"{date_fmt}000000",
        "enddatetime": f"{date_fmt}235959",
    }
    try:
        r = requests.get(GDELT_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"[backfill] GDELT failed for {date_iso}: {exc}")
        return []

    out = []
    for a in data.get("articles", []):
        title = norm_text(a.get("title", ""))
        url = a.get("url")
        if not url:
            continue
        text_blob = f"{title} {a.get('sourceCollection','')} {a.get('domain','')}"
        if has_negative(text_blob, query_pack["negative_keywords"]):
            continue
        hits = keyword_hits(title, query_pack["keywords"])
        if not hits:
            hits = keyword_hits(text_blob, query_pack["keywords"])
        if not hits:
            continue
        c_url = canonicalize_url(url)
        domain = domain_from_url(c_url)
        pub = a.get("seendate")
        published_at = None
        if pub:
            try:
                published_at = dt.datetime.strptime(pub, "%Y%m%dT%H%M%SZ").isoformat() + "Z"
            except Exception:
                published_at = f"{date_iso}T00:00:00Z"
        out.append({
            "id": stable_id(c_url, title),
            "canonical_url": c_url,
            "url": url,
            "title": title,
            "publisher": a.get("domain", domain),
            "domain": domain,
            "published_at": published_at,
            "retrieved_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "snippet": norm_text(a.get("sourceCountry", ""))[:1000],
            "full_text": None,
            "language": a.get("language"),
            "tier": tier_for_domain(domain, query_pack["source_tiers"]),
            "keywords_hit": hits,
            "source_type": "gdelt",
            "collection_run_id": run_id,
        })
    return out


def backfill_date(
    db_path: str,
    date_iso: str,
    source: str = "all",
    max_gdelt: int = 250,
    query_pack_path: str = "config/query_pack.json",
) -> dict:
    """
    Collect items for a specific historical date and persist them.

    source: "gdelt", "reliefweb", or "all"
    RSS feeds only expose current content; use ReliefWeb REST API for historical data.
    Returns {"date": date_iso, "inserted": n}
    """
    q = load_query_pack(query_pack_path)
    run_id = f"backfill_{date_iso}"
    items: list[dict] = []

    if source in ("reliefweb", "all"):
        items.extend(_query_reliefweb_date(date_iso, q, run_id))
    if source in ("gdelt", "all"):
        items.extend(_query_gdelt_date(date_iso, q, run_id, max_records=max_gdelt))

    # Dedupe
    dedup: dict[str, dict] = {}
    for it in items:
        key = it["id"]
        if key not in dedup or score_item(it) > score_item(dedup[key]):
            dedup[key] = it
    items = list(dedup.values())

    # Geo-tag and add provenance
    items = tag_items_batch(items)
    qp_version = q.get("version", 0)
    for it in items:
        it["provenance_hash"] = provenance_hash(qp_version, run_id)

    conn = dbmod.connect(db_path)
    n = dbmod.upsert_items(conn, items)
    conn.close()

    return {"date": date_iso, "inserted": n}
