from __future__ import annotations
import os, json, datetime as dt
from . import db as dbmod

def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "n.d."
    try:
        return dt.datetime.fromisoformat(iso.replace("Z","+00:00")).strftime("%B %-d, %Y")
    except Exception:
        try:
            return dt.datetime.fromisoformat(iso.replace("Z","+00:00")).strftime("%B %d, %Y").replace(" 0"," ")
        except Exception:
            return iso

def build_report(date_key: str, db_path: str = dbmod.DB_PATH, out_dir: str | None = None) -> tuple[str, dict]:
    conn = dbmod.connect(db_path)
    rows = dbmod.get_selected_items_for_date(conn, date_key)
    conn.close()
    if not rows:
        raise RuntimeError(f"No selected items for {date_key}. Run collector first.")

    if out_dir is None:
        out_dir = os.path.join("data", date_key)
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "report.md")

    footnotes = []
    fn_map = {}
    def cite(row):
        key = row["id"]
        if key not in fn_map:
            fn_map[key] = len(footnotes) + 1
            footnotes.append(row)
        return fn_map[key]

    # Executive summary (simple extraction + ranking)
    top_rows = rows[: min(8, len(rows))]
    exec_bullets = []
    for r in top_rows[:5]:
        n = cite(r)
        exec_bullets.append(f"- {r['title']}<sup>{n}</sup>")

    by_region = {}
    region_hints = ["syria","sudan","ukraine","gaza","myanmar","congo","afghanistan","haiti","ethiopia","sahel"]
    for r in rows:
        t = (r["title"] or "").lower() + " " + (r["snippet"] or "").lower()
        for rg in region_hints:
            if rg in t:
                by_region.setdefault(rg.title(), []).append(r)
    top_dev = []
    for r in top_rows:
        n = cite(r)
        pubdate = _fmt_date(r["published_at"] or r["retrieved_at"])
        top_dev.append(f"1. **{r['title']}** ({r['publisher']}; {pubdate})<sup>{n}</sup>")
    top_dev = [f"{i+1}. **{r['title']}** ({r['publisher']}; {_fmt_date(r['published_at'] or r['retrieved_at'])})<sup>{cite(r)}</sup>" for i,r in enumerate(top_rows)]

    lines = []
    lines.append(f"# Displacement Watch Brief — {date_key}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.extend(exec_bullets)
    lines.append("")
    lines.append("## Top Developments")
    lines.extend(top_dev)
    lines.append("")
    if by_region:
        lines.append("## Regional Snapshot")
        for rg, rs in sorted(by_region.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]:
            n = cite(rs[0])
            lines.append(f"- **{rg}:** {len(rs)} relevant item(s); representative item: {rs[0]['title']}<sup>{n}</sup>")
        lines.append("")
    lines.append("## What to Watch")
    lines.append("- Any changes in asylum policy language, border measures, or returns framing across major outlets.")
    lines.append("- Whether humanitarian funding shortfalls or aid access constraints recur across multiple regions.")
    lines.append("- Whether the same event is being framed differently by Tier A vs Tier B outlets.")
    lines.append("")
    lines.append("## Footnotes")
    accessed = dt.datetime.utcnow().strftime("%B %d, %Y").replace(" 0"," ")
    for i, r in enumerate(footnotes, start=1):
        pubdate = _fmt_date(r["published_at"] or r["retrieved_at"])
        title = (r["title"] or "").replace("\n"," ").strip()
        pub = r["publisher"] or r["domain"] or "Unknown"
        url = r["url"]
        lines.append(f"{i}. {pub}, “{title},” {pubdate}, {url} (accessed {accessed}).")

    content = "\n".join(lines) + "\n"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    meta = {
        "date": date_key,
        "items_collected": None,
        "items_selected": len(rows),
        "footnotes": len(footnotes),
        "tier_breakdown": {},
        "regions": sorted(by_region.keys()),
        "publishers": sorted({(r['publisher'] or r['domain'] or 'Unknown') for r in rows}),
    }
    return report_path, meta
