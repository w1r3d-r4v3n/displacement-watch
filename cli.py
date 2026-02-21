from __future__ import annotations
import argparse, os, json, datetime as dt
from jsonschema import validate as js_validate

from agents import db as dbmod
from agents.collector import collect_and_persist
from agents.refiner import propose
from agents.writer import build_report
from agents.editor import qa_and_append
from agents.export_docx import markdown_to_docx

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
        "# Displacement Watch Brief",
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
    # Stub scaffold: iterate dates, run collector/writer/editor. Historical coverage depends on source support.
    dbmod.init_db(args.db)
    print(f"Backfill scaffold: start={args.start} end={args.end} (implement source-specific backfill for RSS/GDELT).")

def build_parser():
    p = argparse.ArgumentParser(description="Displacement Watch v2 CLI")
    p.add_argument("--db", default="displacement_watch.db")
    sub = p.add_subparsers(dest="cmd", required=True)

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
    a.set_defaults(func=cmd_backfill)
    return p

if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
