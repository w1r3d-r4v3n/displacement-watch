from __future__ import annotations
import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

TRACKING_PARAMS = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content","fbclid","gclid"}

def canonicalize_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        query = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True) if k not in TRACKING_PARAMS]
        query.sort()
        path = re.sub(r"/+$", "", p.path or "/")
        return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", urlencode(query), ""))
    except Exception:
        return url

def stable_id(url: str, title: str = "") -> str:
    h = hashlib.sha256()
    h.update(canonicalize_url(url).encode("utf-8"))
    if title:
        h.update(title.lower().strip().encode("utf-8"))
    return h.hexdigest()[:16]

def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def has_negative(text: str, negatives: list[str]) -> bool:
    t = (text or "").lower()
    return any(n.lower() in t for n in negatives)

def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    t = (text or "").lower()
    hits = [k for k in keywords if k.lower() in t]
    return sorted(set(hits))

def domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.","")
    except Exception:
        return ""

def title_jaccard(t1: str, t2: str) -> float:
    """Jaccard similarity on word sets; used for near-duplicate detection."""
    w1 = set((t1 or "").lower().split())
    w2 = set((t2 or "").lower().split())
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)

def dedup_near_duplicates(items: list, score_fn, threshold: float = 0.75) -> list:
    """Remove near-duplicate items by title similarity, keeping the highest-scored version."""
    kept: list = []
    for item in items:
        matched = False
        for i, k in enumerate(kept):
            if title_jaccard(item.get("title", ""), k.get("title", "")) >= threshold:
                if score_fn(item) > score_fn(k):
                    kept[i] = item
                matched = True
                break
        if not matched:
            kept.append(item)
    return kept

def provenance_hash(version: int, run_id: str) -> str:
    """Stable 16-char identifier tying items to a specific query_pack version + run."""
    h = hashlib.sha256()
    h.update(str(version).encode())
    h.update(run_id.encode())
    return h.hexdigest()[:16]
