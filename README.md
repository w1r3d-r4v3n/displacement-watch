# Displacement Watch v2

A personal, multi-agent monitoring pipeline for displaced people/refugee coverage in news and humanitarian sources.

## What it does
- Collects items from RSS + GDELT (legal/ToS-friendly sources)
- Deduplicates and persists items in SQLite
- Proposes guarded keyword/source refinements (no mission drift)
- Generates a daily brief with superscript citations and Chicago-style footnotes
- Runs QA checks and appends quality/methods + trend appendices (7/30-day)
- Optionally exports a `.docx` version of the brief

## Repo layout
- `agents/collector.py` - Agent 1 (collection + persistence)
- `agents/refiner.py` - Agent 2 (query/source refinement proposals)
- `agents/writer.py` - Agent 3 (brief generation + footnotes)
- `agents/editor.py` - Agent 4 (QA + trend appendices)
- `agents/db.py` - SQLite schema + queries
- `agents/trends.py` - rolling trend calculations
- `agents/export_docx.py` - optional docx export
- `cli.py` - commands (`run_daily`, `validate`, `backfill`)
- `config/query_pack.json` - mission, sources, keywords, negatives
- `schemas/` - JSON Schemas for contracts
- `tests/` - schema/report/QA tests

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python cli.py init-db
python cli.py run-daily --since-hours 24 --refine --export-docx
python cli.py validate --date 2026-02-20
```

## Notes
- Uses RSS where possible, and GDELT Doc API for broad coverage.
- Stores all collected items and selections in `displacement_watch.db` (SQLite).
- Daily artifacts are written to `data/YYYY-MM-DD/`.
- This is a personal monitoring pipeline (not surveillance targeting individuals).

## Legal / ToS
- Prefer RSS and public APIs.
- Respect robots.txt and Terms of Service.
- Do not scrape disallowed sites.
