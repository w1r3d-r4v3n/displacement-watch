from __future__ import annotations
import argparse, os, json, datetime as dt, time

from agents import db as dbmod
from agents.collector import collect_and_persist, backfill_date
from agents.refiner import propose
from agents.writer import build_report
from agents.editor import qa_and_append
from agents.export_docx import markdown_to_docx
from agents.dashboard_server import run_dashboard_server

def cmd_status(args):
    if not os.path.exists(args.db):
        raise SystemExit(f"Database not found: {args.db}. Run init-db first.")
    conn = dbmod.connect(args.db)

    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    row = conn.execute(
        "SELECT MIN(COALESCE(published_at,retrieved_at)), MAX(COALESCE(published_at,retrieved_at)) FROM items"
    ).fetchone()
    date_min = (row[0] or "")[:10] or "—"
    date_max = (row[1] or "")[:10] or "—"

    tiers = {r[0] or "U": r[1] for r in conn.execute(
        "SELECT tier, COUNT(*) FROM items GROUP BY tier ORDER BY tier"
    ).fetchall()}

    top_pubs = conn.execute(
        "SELECT COALESCE(publisher, domain, 'Unknown'), COUNT(*) FROM items "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
    ).fetchall()

    selected_total = conn.execute("SELECT COUNT(*) FROM daily_selected").fetchone()[0]
    selected_days = conn.execute("SELECT COUNT(DISTINCT date) FROM daily_selected").fetchone()[0]

    last_run = conn.execute(
        "SELECT run_id, finished_at, items_fetched, items_new FROM collection_runs "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()

    anomalies = conn.execute(
        "SELECT date, ROUND(zscore,2) FROM daily_volume WHERE is_anomaly=1 ORDER BY date DESC LIMIT 5"
    ).fetchall()

    volume_today = conn.execute(
        "SELECT item_count, selected_count FROM daily_volume WHERE date=?",
        (dt.datetime.utcnow().date().isoformat(),)
    ).fetchone()

    conn.close()

    print(f"\n{'='*42}")
    print(f"  Displacement Monitor — DB Status")
    print(f"{'='*42}")
    print(f"  Database  : {args.db}")
    print(f"  Items     : {total:,}  ({date_min} → {date_max})")
    tier_str = "  ".join(f"{t}:{n}" for t, n in sorted(tiers.items()))
    print(f"  Tiers     : {tier_str}")
    print(f"  Selected  : {selected_total:,} across {selected_days} day(s)")
    if volume_today:
        print(f"  Today     : {volume_today[0]} collected, {volume_today[1]} selected")
    print(f"\n  Top publishers (all time):")
    for pub, cnt in top_pubs:
        print(f"    {cnt:>5}  {pub}")
    if last_run:
        finished = (last_run[1] or "")[:19].replace("T", " ")
        print(f"\n  Last run  : {last_run[0]}  ({finished})")
        print(f"             fetched={last_run[2]}  new={last_run[3]}")
    else:
        print(f"\n  Last run  : none recorded")
    if anomalies:
        print(f"\n  Anomaly days (recent): {', '.join(f'{d} (z={z})' for d, z in anomalies)}")
    else:
        print(f"\n  No anomaly days detected (run analyze-trends to compute)")
    print(f"{'='*42}\n")

def cmd_init_db(args):
    dbmod.init_db(args.db)
    print(f"Initialized DB at {args.db}")

def cmd_run_daily(args):
    dbmod.init_db(args.db)
    cmeta = collect_and_persist(args.db, since_hours=args.since_hours, max_gdelt=args.max_gdelt)
    date_key = cmeta["date"]
    out_dir = os.path.join("data", date_key)
    os.makedirs(out_dir, exist_ok=True)

    report_path, wmeta = build_report(date_key, db_path=args.db, out_dir=out_dir)
    emeta = qa_and_append(date_key, report_path, db_path=args.db)

    docx_path = None
    if args.export_docx:
        docx_path = os.path.join(out_dir, "report.docx")
        markdown_to_docx(report_path, docx_path)

    if args.refine:
        proposal, rationale = propose(args.db, "config/query_pack.json")
        with open(os.path.join(out_dir, "query_pack.proposed.json"), "w", encoding="utf-8") as f:
            json.dump(proposal, f, indent=2)
        with open(os.path.join(out_dir, "query_pack.rationale.md"), "w", encoding="utf-8") as f:
            f.write(rationale + "\n")
        conn = dbmod.connect(args.db)
        dbmod.save_query_proposal(conn, proposal, rationale)
        conn.close()

    # enrich and save report meta
    conn = dbmod.connect(args.db)
    selected = dbmod.get_selected_items_for_date(conn, date_key)
    tier_breakdown = {}
    for r in selected:
        tier_breakdown[r["tier"] or "U"] = tier_breakdown.get(r["tier"] or "U", 0) + 1
    final_meta = {
        "date": date_key,
        "items_collected": cmeta["window_items"],
        "items_selected": len(selected),
        "footnotes": emeta["footnotes"],
        "tier_breakdown": tier_breakdown,
        "regions": emeta["trends"]["7d"]["themes"] if isinstance(emeta.get("trends"), dict) else [],
        "publishers": [p for p,_ in emeta["top_publishers"]],
        "collector": cmeta,
        "editor": emeta,
    }
    dbmod.save_report_meta(conn, date_key, report_path, docx_path, final_meta)
    conn.close()

    print(json.dumps({"date": date_key, "report": report_path, "docx": docx_path, "collector": cmeta}, indent=2))

def cmd_validate(args):
    date_key = args.date
    out_dir = os.path.join("data", date_key)
    report_path = os.path.join(out_dir, "report.md")
    if not os.path.exists(report_path):
        raise SystemExit(f"Missing {report_path}")

    # basic report validation
    txt = open(report_path, "r", encoding="utf-8").read()
    required_headers = [
        "# Displacement Monitor Brief",
        "## Executive Summary",
        "## Top Developments",
        "## Footnotes",
        "## Appendix A: Quality & Methods Notes",
        "## Appendix B: Trend Signals",
    ]
    missing = [h for h in required_headers if h not in txt]
    if missing:
        raise SystemExit(f"Report validation failed; missing headers: {missing}")

    print(f"Report validated: {report_path}")

def cmd_backfill(args):
    dbmod.init_db(args.db)
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    source = args.source
    dry_run = args.dry_run

    dates = [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    total_inserted = 0

    for i, d in enumerate(dates):
        if dry_run:
            print(f"[dry-run] would backfill {d} (source={source})")
            continue
        result = backfill_date(args.db, d, source=source, max_gdelt=args.max_gdelt)
        total_inserted += result.get("inserted", 0)
        print(f"[backfill] {d} inserted={result['inserted']}")
        # Courtesy delay between GDELT requests
        if i < len(dates) - 1 and source in ("gdelt", "all"):
            time.sleep(1.0)

    print(f"Backfill complete. Total inserted/updated: {total_inserted}")

def cmd_export_csv(args):
    dbmod.init_db(args.db)
    from agents.exporter import export_items_csv, export_selected_csv

    out = args.out
    stem, ext = os.path.splitext(out)
    ext = ext or ".csv"

    if args.type in ("items", "both"):
        path = f"{stem}_items{ext}" if args.type == "both" else out
        result = export_items_csv(args.db, path, args.start, args.end, args.country)
        print(json.dumps(result))

    if args.type in ("selected", "both"):
        path = f"{stem}_selected{ext}" if args.type == "both" else out
        result = export_selected_csv(args.db, path, args.start, args.end)
        print(json.dumps(result))

def cmd_export_trends(args):
    dbmod.init_db(args.db)
    from agents.exporter import export_trends_json
    result = export_trends_json(args.db, args.out, args.start, args.end)
    print(json.dumps(result))

def cmd_analyze_trends(args):
    dbmod.init_db(args.db)
    from agents.analytics import compute_all_analytics, country_volume_series

    result = compute_all_analytics(args.db, window_days=args.window_days)

    if args.country:
        conn = dbmod.connect(args.db)
        result["country_series"] = country_volume_series(conn, args.country, args.window_days)
        conn.close()

    out_path = args.out or os.path.join("data", dt.datetime.utcnow().date().isoformat(), "analytics.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Analytics written to {out_path}")
    print(f"  Anomaly days: {result['anomaly_days']}  Velocity spikes: {result['spike_days']}")
    if result["keyword_velocity"]:
        top3 = result["keyword_velocity"][:3]
        print(f"  Top keyword velocity: {top3}")

def cmd_fetch_external(args):
    dbmod.init_db(args.db)
    from agents.external_sources import fetch_idmc, fetch_acled, fetch_unhcr_stats

    countries = [c.strip() for c in args.countries.split(",")] if args.countries else None
    conn = dbmod.connect(args.db)
    total = 0

    if args.source in ("idmc", "all"):
        print("[fetch-external] Fetching IDMC...")
        events = fetch_idmc(
            country_iso3s=countries,
            year_from=args.year_from,
            year_to=args.year_to,
        )
        n = dbmod.upsert_external_events(conn, events)
        total += n
        print(f"  IDMC: {n} records inserted/updated")

    if args.source in ("unhcr", "all"):
        print("[fetch-external] Fetching UNHCR Stats...")
        events = fetch_unhcr_stats(year_from=args.year_from, year_to=args.year_to)
        n = dbmod.upsert_external_events(conn, events)
        total += n
        print(f"  UNHCR: {n} records inserted/updated")

    if args.source in ("acled", "all"):
        key = args.acled_key or os.environ.get("ACLED_API_KEY")
        mail = args.acled_email or os.environ.get("ACLED_EMAIL")
        if not key or not mail:
            print("[fetch-external] Skipping ACLED: ACLED_API_KEY and ACLED_EMAIL required.")
        else:
            print("[fetch-external] Fetching ACLED...")
            events = fetch_acled(
                api_key=key,
                email=mail,
                date_range_start=f"{args.year_from}-01-01" if args.year_from else None,
                date_range_end=f"{args.year_to}-12-31" if args.year_to else None,
            )
            n = dbmod.upsert_external_events(conn, events)
            total += n
            print(f"  ACLED: {n} records inserted/updated")

    conn.close()
    print(f"Total external records inserted/updated: {total}")

def cmd_export_citations(args):
    dbmod.init_db(args.db)
    from agents.cite import report_to_bibtex, report_to_ris, items_to_bibtex, items_to_ris

    if args.date:
        if args.format == "bibtex":
            content = report_to_bibtex(args.date, args.db)
        else:
            content = report_to_ris(args.date, args.db)
    else:
        conn = dbmod.connect(args.db)
        rows = dbmod.get_all_items(conn, args.start, args.end)
        conn.close()
        if args.format == "bibtex":
            content = items_to_bibtex(rows)
        else:
            content = items_to_ris(rows)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Citations written to {args.out}")

def cmd_export_research_package(args):
    dbmod.init_db(args.db)
    from agents.exporter import build_research_package
    manifest = build_research_package(
        args.db,
        args.out,
        start_iso=args.start,
        end_iso=args.end,
        include_external=args.include_external,
    )
    print(f"Research package written to {args.out}")
    print(f"  Files: {list(manifest['files'].keys())}")

def cmd_serve_dashboard(args):
    dbmod.init_db(args.db)
    run_dashboard_server(db_path=args.db, host=args.host, port=args.port)

def build_parser():
    p = argparse.ArgumentParser(description="Displacement Monitor v2 CLI")
    p.add_argument("--db", default="displacement_monitor.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("status", help="Show database statistics at a glance")
    a.set_defaults(func=cmd_status)

    a = sub.add_parser("init-db")
    a.set_defaults(func=cmd_init_db)

    a = sub.add_parser("run-daily")
    a.add_argument("--since-hours", type=int, default=24)
    a.add_argument("--max-gdelt", type=int, default=100)
    a.add_argument("--refine", action="store_true")
    a.add_argument("--export-docx", action="store_true")
    a.set_defaults(func=cmd_run_daily)

    a = sub.add_parser("validate")
    a.add_argument("--date", required=True)
    a.set_defaults(func=cmd_validate)

    a = sub.add_parser("backfill")
    a.add_argument("--start", required=True)
    a.add_argument("--end", required=True)
    a.add_argument("--source", default="all", choices=["gdelt", "reliefweb", "all"])
    a.add_argument("--max-gdelt", type=int, default=250)
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_backfill)

    a = sub.add_parser("export-csv", help="Export collected items to CSV")
    a.add_argument("--out", required=True, help="Output CSV path")
    a.add_argument("--start", default=None)
    a.add_argument("--end", default=None)
    a.add_argument("--country", default=None, help="ISO alpha-2 country code filter")
    a.add_argument("--type", default="items", choices=["items", "selected", "both"])
    a.set_defaults(func=cmd_export_csv)

    a = sub.add_parser("export-trends", help="Export trend statistics to JSON")
    a.add_argument("--out", required=True, help="Output JSON path")
    a.add_argument("--start", default=None)
    a.add_argument("--end", default=None)
    a.set_defaults(func=cmd_export_trends)

    a = sub.add_parser("analyze-trends", help="Compute predictive analytics (z-scores, velocity spikes)")
    a.add_argument("--window-days", type=int, default=90)
    a.add_argument("--out", default=None, help="Output JSON path (default: data/<today>/analytics.json)")
    a.add_argument("--country", default=None, help="Also produce per-country volume series (ISO alpha-2)")
    a.set_defaults(func=cmd_analyze_trends)

    a = sub.add_parser("fetch-external", help="Fetch external datasets (IDMC, ACLED, UNHCR Stats)")
    a.add_argument("--source", required=True, choices=["idmc", "acled", "unhcr", "all"])
    a.add_argument("--countries", default=None, help="Comma-separated ISO3 country codes")
    a.add_argument("--year-from", type=int, default=2018)
    a.add_argument("--year-to", type=int, default=None)
    a.add_argument("--acled-key", default=None)
    a.add_argument("--acled-email", default=None)
    a.set_defaults(func=cmd_fetch_external)

    a = sub.add_parser("export-citations", help="Export citations in BibTeX or RIS format")
    a.add_argument("--format", required=True, choices=["bibtex", "ris"])
    a.add_argument("--out", required=True, help="Output file path")
    a.add_argument("--date", default=None, help="Export citations for a specific daily brief date")
    a.add_argument("--start", default=None, help="Date range start (alternative to --date)")
    a.add_argument("--end", default=None)
    a.set_defaults(func=cmd_export_citations)

    a = sub.add_parser("export-research-package", help="Bundle all exports into a research data package")
    a.add_argument("--out", required=True, help="Output directory path")
    a.add_argument("--start", default=None)
    a.add_argument("--end", default=None)
    a.add_argument("--include-external", action="store_true", help="Include external_events.csv")
    a.set_defaults(func=cmd_export_research_package)

    a = sub.add_parser("serve-dashboard", help="Launch the local browser dashboard")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8765)
    a.set_defaults(func=cmd_serve_dashboard)

    return p

if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
