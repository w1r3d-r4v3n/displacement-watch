from __future__ import annotations
import os, re, json
from collections import Counter
from . import db as dbmod
from .trends import rolling_trends

SUP_RE = re.compile(r"<sup>(\d+)</sup>")

def qa_and_append(date_key: str, report_path: str, db_path: str = dbmod.DB_PATH) -> dict:
    conn = dbmod.connect(db_path)
    rows = dbmod.get_selected_items_for_date(conn, date_key)
    conn.close()

    with open(report_path, "r", encoding="utf-8") as f:
        text = f.read()

    sup_markers = [int(x) for x in SUP_RE.findall(text)]
    footnotes_section = text.split("## Footnotes", 1)[1] if "## Footnotes" in text else ""
    footnote_lines = [ln for ln in footnotes_section.splitlines() if re.match(r"^\d+\.\s", ln)]

    # Stronger QA checks (still heuristic)
    uncited_bullets = []
    for ln in text.splitlines():
        if ln.startswith("- ") or re.match(r"^\d+\. ", ln):
            if "Footnotes" in ln or "What to Watch" in ln:
                continue
            if ("**" in ln or "—" in ln or ":" in ln) and "<sup>" not in ln and not ln.startswith("- Any ") and not ln.startswith("- Whether "):
                uncited_bullets.append(ln)

    # Tier distribution and top publishers
    tier_counter = Counter([r["tier"] or "U" for r in rows])
    pub_counter = Counter([(r["publisher"] or r["domain"] or "Unknown") for r in rows])

    trends = rolling_trends(db_path)
    appendix = []
    appendix.append("")
    appendix.append("## Appendix A: Quality & Methods Notes")
    appendix.append(f"- Items selected for brief: {len(rows)}")
    appendix.append(f"- Citation markers in report body: {len(sup_markers)}")
    appendix.append(f"- Footnotes emitted: {len(footnote_lines)}")
    appendix.append(f"- Tier breakdown (selected): {dict(tier_counter)}")
    appendix.append(f"- Top publishers (selected): {pub_counter.most_common(8)}")
    if uncited_bullets:
        appendix.append(f"- Potential uncited lines flagged (heuristic): {len(uncited_bullets)}")
        for ln in uncited_bullets[:5]:
            appendix.append(f"  - {ln}")
    else:
        appendix.append("- Potential uncited lines flagged (heuristic): 0")
    appendix.append("- Limitations: RSS/GDELT metadata may not include full article text; claim-level verification is limited to headline/snippet unless full text is legally retrievable.")
    appendix.append("")
    appendix.append("## Appendix B: Trend Signals")
    appendix.append(f"- Rolling coverage volume: 7d={trends['counts']['7d']}, 30d={trends['counts']['30d']}")
    appendix.append(f"- 7d top themes: {trends['7d']['themes']}")
    appendix.append(f"- 30d top themes: {trends['30d']['themes']}")
    appendix.append(f"- 7d top keywords: {trends['7d']['keywords']}")
    appendix.append(f"- 30d top keywords: {trends['30d']['keywords']}")
    appendix.append(f"- 7d top publishers: {trends['7d']['publishers']}")
    appendix.append(f"- 30d top publishers: {trends['30d']['publishers']}")
    appendix.append("- High-confidence signals should be those repeated across Tier A and Tier B sources. Low-confidence signals are single-source or Tier U/C dominated.")
    appendix.append("")

    with open(report_path, "a", encoding="utf-8") as f:
        f.write("\n".join(appendix))

    meta = {
        "citation_markers": len(sup_markers),
        "footnotes": len(footnote_lines),
        "tier_breakdown": dict(tier_counter),
        "top_publishers": pub_counter.most_common(8),
        "uncited_lines_flagged": len(uncited_bullets),
        "trends": trends,
    }
    return meta
