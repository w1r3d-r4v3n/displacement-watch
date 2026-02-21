from __future__ import annotations
import json, collections
from . import db as dbmod

THEME_LEXICON = {
    "asylum": ["asylum", "asylum seeker", "asylum seekers", "asylum claim"],
    "border": ["border", "crossing", "deport", "returns"],
    "resettlement": ["resettlement", "third-country", "relocation"],
    "funding": ["funding", "aid", "appeal", "shortfall", "donor"],
    "camp_conditions": ["camp", "shelter", "winterization", "cholera", "food"]
}

def _scan(rows):
    kw_counter = collections.Counter()
    pub_counter = collections.Counter()
    tier_counter = collections.Counter()
    theme_counter = collections.Counter()
    for r in rows:
        title = (r["title"] or "").lower()
        snippet = (r["snippet"] or "").lower()
        txt = f"{title} {snippet}"
        pub_counter[r["publisher"] or r["domain"] or "unknown"] += 1
        tier_counter[r["tier"] or "U"] += 1
        try:
            kws = json.loads(r["keywords_hit_json"] or "[]")
            kw_counter.update(kws)
        except Exception:
            pass
        for theme, phrases in THEME_LEXICON.items():
            if any(p.lower() in txt for p in phrases):
                theme_counter[theme] += 1
    return {
        "keywords": kw_counter.most_common(15),
        "publishers": pub_counter.most_common(10),
        "tiers": dict(tier_counter),
        "themes": theme_counter.most_common()
    }

def rolling_trends(db_path: str = dbmod.DB_PATH) -> dict:
    conn = dbmod.connect(db_path)
    rows7 = dbmod.get_items_since_days(conn, 7)
    rows30 = dbmod.get_items_since_days(conn, 30)
    conn.close()
    return {"7d": _scan(rows7), "30d": _scan(rows30), "counts": {"7d": len(rows7), "30d": len(rows30)}}
