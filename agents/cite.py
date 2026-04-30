"""
Academic citation export utilities.

Converts collected items to BibTeX and RIS formats suitable for import into
Zotero, Mendeley, EndNote, and other reference managers.
"""
from __future__ import annotations
import datetime as dt
from typing import Any

from . import db as dbmod


def _safe_title(title: str) -> str:
    """Escape BibTeX-special characters in a title."""
    return (
        title
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("$", "\\$")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("~", "\\textasciitilde{}")
        .replace("^", "\\^{}")
    )


def _parse_year(iso: str | None) -> str:
    if not iso:
        return ""
    return iso[:4] if len(iso) >= 4 else iso


def _parse_date_ris(iso: str | None) -> str:
    """Return YYYY/MM/DD for RIS DA field."""
    if not iso:
        return ""
    parts = iso[:10].split("-")
    if len(parts) == 3:
        return "/".join(parts)
    return iso[:10]


def _row_to_dict(row: Any) -> dict:
    if hasattr(row, "keys"):
        return dict(row)
    return row


def items_to_bibtex(rows: list, citekey_prefix: str = "dispwatch") -> str:
    """
    Convert a list of item rows to a BibTeX string.

    Each item becomes an @misc entry with:
      - citekey: {prefix}_{id[:8]}
      - author: institution/publisher
      - title
      - year
      - url
      - urldate (today)
- note: source tier and Displacement Monitor attribution
    """
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    entries: list[str] = []

    for row in rows:
        d = _row_to_dict(row)
        item_id = d.get("id", "unknown")
        citekey = f"{citekey_prefix}_{item_id[:8]}"
        title = _safe_title(d.get("title") or "Untitled")
        publisher = d.get("publisher") or d.get("domain") or "Unknown"
        url = d.get("url") or d.get("canonical_url") or ""
        year = _parse_year(d.get("published_at") or d.get("retrieved_at"))
        tier = d.get("tier") or "U"

        entry = (
            f"@misc{{{citekey},\n"
            f"  author    = {{{{{publisher}}}}},\n"
            f"  title     = {{{title}}},\n"
            f"  year      = {{{year}}},\n"
            f"  url       = {{{url}}},\n"
            f"  urldate   = {{{today}}},\n"
            f"  note      = {{Retrieved via Displacement Monitor v2. Source tier: {tier}.}}\n"
            f"}}"
        )
        entries.append(entry)

    return "\n\n".join(entries) + "\n"


def items_to_ris(rows: list) -> str:
    """
    Convert a list of item rows to a RIS format string.

    RIS field mapping:
      TY - ICOMM (internet communication / online source)
      TI - title
      PB - publisher
      UR - url
      DA - publication date (YYYY/MM/DD)
      Y2 - retrieval date
      N1 - note (tier)
      ER - end of record
    """
    records: list[str] = []

    for row in rows:
        d = _row_to_dict(row)
        title = (d.get("title") or "Untitled").replace("\n", " ")
        publisher = d.get("publisher") or d.get("domain") or "Unknown"
        url = d.get("url") or d.get("canonical_url") or ""
        pub_date = _parse_date_ris(d.get("published_at"))
        ret_date = _parse_date_ris(d.get("retrieved_at"))
        tier = d.get("tier") or "U"

        lines = [
            "TY  - ICOMM",
            f"TI  - {title}",
            f"PB  - {publisher}",
        ]
        if url:
            lines.append(f"UR  - {url}")
        if pub_date:
            lines.append(f"DA  - {pub_date}")
        if ret_date:
            lines.append(f"Y2  - {ret_date}")
        lines.append(f"N1  - Source tier: {tier}. Retrieved via Displacement Monitor v2.")
        lines.append("ER  - ")

        records.append("\n".join(lines))

    return "\n\n".join(records) + "\n"


def report_to_bibtex(
    date_key: str,
    db_path: str = dbmod.DB_PATH,
    citekey_prefix: str = "dispwatch",
) -> str:
    """Return BibTeX for all items selected on date_key."""
    conn = dbmod.connect(db_path)
    rows = dbmod.get_selected_items_for_date(conn, date_key)
    conn.close()
    return items_to_bibtex(rows, citekey_prefix=citekey_prefix)


def report_to_ris(date_key: str, db_path: str = dbmod.DB_PATH) -> str:
    """Return RIS for all items selected on date_key."""
    conn = dbmod.connect(db_path)
    rows = dbmod.get_selected_items_for_date(conn, date_key)
    conn.close()
    return items_to_ris(rows)
