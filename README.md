# Displacement Watch v2

A multi-agent monitoring pipeline for displaced people/refugee coverage in news and humanitarian sources, with research-grade data exports and predictive analytics.

## What it does
- Collects items from RSS + GDELT (legal/ToS-friendly sources)
- Deduplicates and persists items in SQLite
- Tags items with ISO country codes and UN regions (offline, no external dependencies)
- Proposes guarded keyword/source refinements (no mission drift)
- Generates a daily brief with superscript citations and Chicago-style footnotes
- Runs QA checks and appends quality/methods + trend appendices (7/30-day)
- Computes rolling z-score anomaly detection and keyword velocity signals
- Exports structured data (CSV, JSON, BibTeX, RIS) for use in R/Python
- Optionally exports a `.docx` version of the brief

## Repo layout

### Core pipeline
- `agents/collector.py` — Agent 1: collection, geo-tagging, provenance, persistence
- `agents/refiner.py` — Agent 2: guarded query/source refinement proposals
- `agents/writer.py` — Agent 3: brief generation + footnotes
- `agents/editor.py` — Agent 4: QA + trend appendices
- `agents/trends.py` — rolling 7/30-day trend calculations
- `agents/export_docx.py` — optional DOCX export

### Research tools
- `agents/geo_tag.py` — offline ISO country/UN-region tagging (FIPS + text scan)
- `agents/analytics.py` — z-score anomaly detection, velocity spikes, keyword velocity, Granger causality stub
- `agents/exporter.py` — CSV/JSON exports and full research data package builder
- `agents/external_sources.py` — IDMC, ACLED, UNHCR Stats API integrations
- `agents/cite.py` — BibTeX and RIS citation export

### Infrastructure
- `agents/db.py` — SQLite schema + queries
- `agents/utils.py` — URL canonicalization, hashing, keyword utilities
- `cli.py` — all CLI commands
- `config/query_pack.json` — mission, sources, keywords, negatives
- `schemas/` — JSON Schemas for data contracts
- `tests/` — schema/report/QA tests

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python cli.py init-db
python cli.py run-daily --since-hours 24 --refine --export-docx
python cli.py validate --date 2026-04-30
```

## CLI reference

### Core commands
```bash
# Initialise or migrate the database
python cli.py init-db

# Run the full daily pipeline
python cli.py run-daily [--since-hours 24] [--max-gdelt 100] [--refine] [--export-docx]

# Validate a generated report
python cli.py validate --date YYYY-MM-DD
```

### Historical backfill
```bash
# Backfill using GDELT date params + ReliefWeb REST API
python cli.py backfill --start 2025-01-01 --end 2025-12-31 --source all [--dry-run]
# --source: gdelt | reliefweb | all (default: all)
```

### Research exports
```bash
# Export items or daily selections to CSV
python cli.py export-csv --out data/exports/items.csv [--start YYYY-MM-DD] [--end YYYY-MM-DD] \
    [--country SY] [--type items|selected|both]

# Export rolling trend statistics to JSON
python cli.py export-trends --out data/exports/trends.json [--start] [--end]

# Compute predictive analytics (anomaly detection, velocity spikes)
python cli.py analyze-trends [--window-days 90] [--out analytics.json] [--country SY]

# Fetch external datasets and store them in the DB
python cli.py fetch-external --source idmc|acled|unhcr|all \
    [--countries AFG,SYR,SDN] [--year-from 2020] [--year-to 2025] \
    [--acled-key KEY] [--acled-email EMAIL]
# ACLED key/email can also be set via ACLED_API_KEY / ACLED_EMAIL env vars

# Export citations for use in reference managers
python cli.py export-citations --format bibtex|ris --out refs.bib \
    [--date YYYY-MM-DD] [--start YYYY-MM-DD --end YYYY-MM-DD]

# Bundle everything into a self-contained research data package
python cli.py export-research-package --out data/exports/pkg/ \
    [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--include-external]
```

### Research data package contents
| File | Contents |
|------|----------|
| `items.csv` | All collected items with country tags and provenance |
| `selected.csv` | Daily-selected items with scores |
| `daily_volume.csv` | Date, item count, z-score, anomaly flag |
| `trends.json` | Rolling keyword/theme/publisher statistics |
| `analytics.json` | Velocity spikes, anomaly days, keyword velocity |
| `citations.bib` | BibTeX for all selected items |
| `citations.ris` | RIS for all selected items |
| `external_events.csv` | IDMC/ACLED/UNHCR records (`--include-external`) |
| `query_pack_snapshot.json` | Exact config used during collection |
| `codebook.md` | Column definitions, scoring formula, methodology notes |
| `manifest.json` | File list with row counts and SHA256 checksums |

## Database schema

Key tables in `displacement_watch.db`:

| Table | Contents |
|-------|----------|
| `items` | All collected articles (with `country_codes_json`, `un_region`, `provenance_hash`) |
| `daily_selected` | Items chosen for each daily brief + score |
| `daily_volume` | Per-day item counts, z-scores, anomaly flags |
| `external_events` | IDMC/ACLED/UNHCR external dataset records |
| `collection_runs` | Provenance log: query_pack version, hash, item counts |
| `reports` | Report paths and metadata |
| `query_proposals` | Guarded refinement proposals |

## Notes
- Uses RSS where possible, and GDELT Doc API for broad coverage.
- Stores all collected items and selections in `displacement_watch.db` (SQLite).
- Daily artifacts are written to `data/YYYY-MM-DD/`.
- Country tagging is offline — no external geocoding service required.
- `numpy` and `scipy` are required for analytics; `statsmodels` is optional (Granger causality only).
- This is a monitoring pipeline, not surveillance targeting individuals.

## Legal / ToS
- Prefer RSS and public APIs.
- Respect robots.txt and Terms of Service.
- Do not scrape disallowed sites.
- ACLED data requires free researcher registration at acleddata.com.
- IDMC and UNHCR Stats data are subject to their respective terms of use.
