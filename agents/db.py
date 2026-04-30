from __future__ import annotations
import sqlite3, json, os, datetime as dt
from typing import Iterable, Any

DB_PATH = "displacement_watch.db"

SCHEMA_SQL = '''
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  canonical_url TEXT,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  publisher TEXT,
  domain TEXT,
  published_at TEXT,
  retrieved_at TEXT,
  snippet TEXT,
  full_text TEXT,
  language TEXT,
  tier TEXT,
  source_type TEXT,
  keywords_hit_json TEXT,
  collection_run_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_domain ON items(domain);

CREATE TABLE IF NOT EXISTS daily_selected (
  date TEXT NOT NULL,
  item_id TEXT NOT NULL,
  score REAL NOT NULL,
  PRIMARY KEY (date, item_id),
  FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE TABLE IF NOT EXISTS reports (
  date TEXT PRIMARY KEY,
  report_path TEXT,
  docx_path TEXT,
  meta_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS query_proposals (
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  proposal_json TEXT NOT NULL,
  rationale TEXT NOT NULL
);
'''

MIGRATION_SQL_TABLES = '''
CREATE TABLE IF NOT EXISTS daily_volume (
  date TEXT PRIMARY KEY,
  item_count INTEGER NOT NULL,
  selected_count INTEGER NOT NULL,
  zscore REAL,
  is_anomaly INTEGER DEFAULT 0,
  computed_at TEXT
);

CREATE TABLE IF NOT EXISTS external_events (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  event_date TEXT,
  country_code TEXT,
  country_name TEXT,
  region TEXT,
  metric_name TEXT,
  metric_value REAL,
  raw_json TEXT,
  retrieved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_extevents_date ON external_events(event_date);
CREATE INDEX IF NOT EXISTS idx_extevents_country ON external_events(country_code);

CREATE TABLE IF NOT EXISTS collection_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT,
  finished_at TEXT,
  query_pack_version INTEGER,
  query_pack_hash TEXT,
  items_fetched INTEGER,
  items_new INTEGER,
  sources_json TEXT
);
'''

def _safe_alter(conn: sqlite3.Connection, sql: str) -> None:
    try:
        conn.execute(sql)
    except sqlite3.OperationalError:
        pass  # column already exists

def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DB_PATH) -> None:
    conn = connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(MIGRATION_SQL_TABLES)
    _safe_alter(conn, "ALTER TABLE items ADD COLUMN country_codes_json TEXT")
    _safe_alter(conn, "ALTER TABLE items ADD COLUMN un_region TEXT")
    _safe_alter(conn, "ALTER TABLE items ADD COLUMN anomaly_score REAL")
    _safe_alter(conn, "ALTER TABLE items ADD COLUMN provenance_hash TEXT")
    conn.commit()
    conn.close()

def upsert_items(conn: sqlite3.Connection, items: Iterable[dict[str, Any]]) -> int:
    cur = conn.cursor()
    n = 0
    for it in items:
        cur.execute(
            '''INSERT INTO items (
                id, canonical_url, url, title, publisher, domain, published_at, retrieved_at, snippet, full_text,
                language, tier, source_type, keywords_hit_json, collection_run_id,
                country_codes_json, un_region, provenance_hash
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                canonical_url=excluded.canonical_url,
                url=excluded.url,
                title=excluded.title,
                publisher=excluded.publisher,
                domain=excluded.domain,
                published_at=excluded.published_at,
                retrieved_at=excluded.retrieved_at,
                snippet=excluded.snippet,
                full_text=COALESCE(excluded.full_text, items.full_text),
                language=COALESCE(excluded.language, items.language),
                tier=excluded.tier,
                source_type=excluded.source_type,
                keywords_hit_json=excluded.keywords_hit_json,
                collection_run_id=excluded.collection_run_id,
                country_codes_json=COALESCE(excluded.country_codes_json, items.country_codes_json),
                un_region=COALESCE(excluded.un_region, items.un_region),
                provenance_hash=COALESCE(excluded.provenance_hash, items.provenance_hash)
            ''',
            (
                it["id"], it.get("canonical_url"), it["url"], it["title"], it.get("publisher"), it.get("domain"),
                it.get("published_at"), it.get("retrieved_at"), it.get("snippet",""), it.get("full_text"),
                it.get("language"), it.get("tier","U"), it.get("source_type","rss"),
                json.dumps(it.get("keywords_hit",[])), it.get("collection_run_id"),
                json.dumps(it.get("country_codes", [])) if it.get("country_codes") is not None else None,
                it.get("un_region"),
                it.get("provenance_hash"),
            )
        )
        n += 1
    conn.commit()
    return n

def save_daily_selected(conn: sqlite3.Connection, date: str, selected: list[tuple[str, float]]) -> None:
    cur = conn.cursor()
    for item_id, score in selected:
        cur.execute(
            "INSERT OR REPLACE INTO daily_selected(date,item_id,score) VALUES (?,?,?)",
            (date, item_id, score),
        )
    conn.commit()

def get_items_for_window(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        '''SELECT * FROM items
           WHERE COALESCE(published_at, retrieved_at) >= ? AND COALESCE(published_at, retrieved_at) <= ?
           ORDER BY COALESCE(published_at, retrieved_at) DESC''',
        (start_iso, end_iso)
    )
    return cur.fetchall()

def get_selected_items_for_date(conn: sqlite3.Connection, date: str) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        '''SELECT i.*, ds.score FROM daily_selected ds
           JOIN items i ON i.id = ds.item_id
           WHERE ds.date = ?
           ORDER BY ds.score DESC, COALESCE(i.published_at, i.retrieved_at) DESC''',
        (date,)
    )
    return cur.fetchall()

def get_items_since_days(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        f'''SELECT * FROM items
            WHERE datetime(COALESCE(published_at, retrieved_at)) >= datetime('now', '-{int(days)} days')
            ORDER BY COALESCE(published_at, retrieved_at) DESC'''
    )
    return cur.fetchall()

def save_report_meta(conn: sqlite3.Connection, date: str, report_path: str, docx_path: str | None, meta: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO reports(date,report_path,docx_path,meta_json) VALUES (?,?,?,?)",
        (date, report_path, docx_path, json.dumps(meta))
    )
    conn.commit()

def save_query_proposal(conn: sqlite3.Connection, proposal: dict, rationale: str) -> None:
    conn.execute("INSERT INTO query_proposals(proposal_json,rationale) VALUES (?,?)", (json.dumps(proposal), rationale))
    conn.commit()

def get_all_items(
    conn: sqlite3.Connection,
    start_iso: str | None = None,
    end_iso: str | None = None,
    country_code: str | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list[Any] = []
    if start_iso:
        clauses.append("COALESCE(published_at, retrieved_at) >= ?")
        params.append(start_iso)
    if end_iso:
        clauses.append("COALESCE(published_at, retrieved_at) <= ?")
        params.append(end_iso)
    if country_code:
        clauses.append("country_codes_json LIKE ?")
        params.append(f'%"{country_code}"%')
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM items {where} ORDER BY COALESCE(published_at, retrieved_at) DESC", params)
    return cur.fetchall()

def get_daily_volume_series(
    conn: sqlite3.Connection,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list[Any] = []
    if start_iso:
        clauses.append("date >= ?")
        params.append(start_iso)
    if end_iso:
        clauses.append("date <= ?")
        params.append(end_iso)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM daily_volume {where} ORDER BY date", params)
    return cur.fetchall()

def upsert_daily_volume(
    conn: sqlite3.Connection,
    date: str,
    item_count: int,
    selected_count: int,
    zscore: float | None = None,
    is_anomaly: int = 0,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO daily_volume(date,item_count,selected_count,zscore,is_anomaly,computed_at) VALUES (?,?,?,?,?,?)",
        (date, item_count, selected_count, zscore, is_anomaly, dt.datetime.utcnow().isoformat() + "Z"),
    )
    conn.commit()

def get_external_events(
    conn: sqlite3.Connection,
    source: str | None = None,
    country_code: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> list[sqlite3.Row]:
    clauses = []
    params: list[Any] = []
    if source:
        clauses.append("source = ?")
        params.append(source)
    if country_code:
        clauses.append("country_code = ?")
        params.append(country_code)
    if start_iso:
        clauses.append("event_date >= ?")
        params.append(start_iso)
    if end_iso:
        clauses.append("event_date <= ?")
        params.append(end_iso)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM external_events {where} ORDER BY event_date", params)
    return cur.fetchall()

def upsert_external_events(conn: sqlite3.Connection, events: Iterable[dict[str, Any]]) -> int:
    n = 0
    for ev in events:
        conn.execute(
            '''INSERT OR REPLACE INTO external_events
               (id, source, event_date, country_code, country_name, region,
                metric_name, metric_value, raw_json, retrieved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                ev["id"], ev["source"], ev.get("event_date"), ev.get("country_code"),
                ev.get("country_name"), ev.get("region"), ev.get("metric_name"),
                ev.get("metric_value"), json.dumps(ev.get("raw_json", {})),
                ev.get("retrieved_at", dt.datetime.utcnow().isoformat() + "Z"),
            ),
        )
        n += 1
    conn.commit()
    return n

def save_collection_run(conn: sqlite3.Connection, run_meta: dict[str, Any]) -> None:
    conn.execute(
        '''INSERT OR REPLACE INTO collection_runs
           (run_id, started_at, finished_at, query_pack_version, query_pack_hash,
            items_fetched, items_new, sources_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            run_meta.get("run_id"), run_meta.get("started_at"), run_meta.get("finished_at"),
            run_meta.get("query_pack_version"), run_meta.get("query_pack_hash"),
            run_meta.get("items_fetched"), run_meta.get("items_new"),
            json.dumps(run_meta.get("sources", [])),
        ),
    )
    conn.commit()
