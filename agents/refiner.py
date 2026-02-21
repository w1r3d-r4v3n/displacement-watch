from __future__ import annotations
import json, collections
from . import db as dbmod

SAFE_EXPANSIONS = {
    "refugee": ["refugee influx", "refugee camp", "refugee agency"],
    "displaced": ["forced displacement", "mass displacement"],
    "internally displaced": ["IDP camp", "IDP settlement"],
    "asylum seeker": ["asylum application", "asylum claim"],
    "resettlement": ["resettlement program", "third-country resettlement"]
}

def propose(db_path: str = dbmod.DB_PATH, query_pack_path: str = "config/query_pack.json") -> tuple[dict, str]:
    with open(query_pack_path, "r", encoding="utf-8") as f:
        q = json.load(f)
    conn = dbmod.connect(db_path)
    rows = dbmod.get_items_since_days(conn, 14)
    conn.close()

    title_tokens = collections.Counter()
    publishers = collections.Counter()
    for r in rows:
        title = (r["title"] or "").lower()
        for tok in title.replace("/", " ").replace("-", " ").split():
            tok = tok.strip(",.():;!?\"\'")
            if len(tok) < 4:
                continue
            title_tokens[tok] += 1
        publishers[r["domain"] or r["publisher"] or "unknown"] += 1

    new_keywords = []
    for kw in q["keywords"]:
        for s in SAFE_EXPANSIONS.get(kw, []):
            if s not in q["keywords"]:
                new_keywords.append(s)

    proposed = dict(q)
    proposed["version"] = int(q.get("version",1)) + 1
    proposed["keywords"] = sorted(set(q["keywords"] + new_keywords))

    rationale_lines = [
        "# Query Pack Proposal Rationale",
        "",
        "Guardrails: mission unchanged; only safe term expansions proposed; no source auto-removals.",
        "",
        f"Observed items in last 14 days: {len(rows)}",
        f"Top publishers/domains: {publishers.most_common(10)}",
        f"Top title tokens: {title_tokens.most_common(20)}",
        "",
        "Proposed additions:",
    ] + [f"- {k}" for k in new_keywords]

    return proposed, "\n".join(rationale_lines)
