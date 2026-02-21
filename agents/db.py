from __future__ import annotations
import sqlite3, json, os
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

def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DB_PATH) -> None:
    conn = connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

def upsert_items(conn: sqlite3.Connection, items: Iterable[dict[str, Any]]) -> int:
    cur = conn.cursor()
    n = 0
    for it in items:
        cur.execute(
            '''INSERT INTO items (
                id, canonical_url, url, title, publisher, domain, published_at, retrieved_at, snippet, full_text,
                language, tier, source_type, keywords_hit_json, collection_run_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                collection_run_id=excluded.collection_run_id
            ''',
            (
                it["id"], it.get("canonical_url"), it["url"], it["title"], it.get("publisher"), it.get("domain"),
                it.get("published_at"), it.get("retrieved_at"), it.get("snippet",""), it.get("full_text"),
                it.get("language"), it.get("tier","U"), it.get("source_type","rss"),
                json.dumps(it.get("keywords_hit",[])), it.get("collection_run_id")
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
