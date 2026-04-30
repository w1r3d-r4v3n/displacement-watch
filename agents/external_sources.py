"""
External data source integrations for academic research context.

Integrates three authoritative displacement datasets:
  - IDMC  : Internal Displacement Monitoring Centre (annual IDP stocks)
  - ACLED : Armed Conflict Location & Event Data (conflict events, fatalities)
  - UNHCR : UNHCR Population Statistics API (refugee/IDP/asylum-seeker stocks)

All fetch functions return list[dict] conforming to the external_events table schema.
No DB writes happen here — the caller decides when to persist via db.upsert_external_events.
"""
from __future__ import annotations
import datetime as dt, os
from typing import Any

import requests

# ISO3 -> ISO2 for the ~30 countries most relevant to displacement research
_ISO3_TO_ISO2: dict[str, str] = {
    "AFG": "AF", "AGO": "AO", "BGD": "BD", "BDI": "BI", "BFA": "BF",
    "CAF": "CF", "CHL": "CL", "CHN": "CN", "CMR": "CM", "COD": "CD",
    "COG": "CG", "COL": "CO", "CUB": "CU", "DJI": "DJ", "ECU": "EC",
    "EGY": "EG", "ERI": "ER", "ETH": "ET", "GNB": "GW", "GTM": "GT",
    "GIN": "GN", "HTI": "HT", "HND": "HN", "IRN": "IR", "IRQ": "IQ",
    "KAZ": "KZ", "KEN": "KE", "KGZ": "KG", "KHM": "KH", "LBN": "LB",
    "LBY": "LY", "LBR": "LR", "LKA": "LK", "MAR": "MA", "MDG": "MG",
    "MEX": "MX", "MLI": "ML", "MOZ": "MZ", "MRT": "MR", "MMR": "MM",
    "MWI": "MW", "NER": "NE", "NGA": "NG", "NIC": "NI", "PAK": "PK",
    "PER": "PE", "PSE": "PS", "RUS": "RU", "RWA": "RW", "SDN": "SD",
    "SLE": "SL", "SOM": "SO", "SSD": "SS", "SYR": "SY", "TCD": "TD",
    "TJK": "TJ", "TUN": "TN", "TZA": "TZ", "UGA": "UG", "UKR": "UA",
    "UZB": "UZ", "VEN": "VE", "VNM": "VN", "YEM": "YE", "ZAF": "ZA",
    "ZMB": "ZM", "ZWE": "ZW",
}

_NOW = lambda: dt.datetime.utcnow().isoformat() + "Z"


def _stable_id(source: str, country: str, date: str, metric: str) -> str:
    import hashlib
    key = f"{source}:{country}:{date}:{metric}"
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def fetch_idmc(
    country_iso3s: list[str] | None = None,
    year_from: int = 2018,
    year_to: int | None = None,
    timeout: int = 30,
) -> list[dict]:
    """
    Fetch conflict-induced IDP stock figures from the IDMC public API.

    Returns normalized records with metric_name="idp_stock".
    event_date is set to {year}-01-01 (annual figures convention).

    API: https://api.idmcdb.org/api/displacement_data
    """
    if year_to is None:
        year_to = dt.datetime.utcnow().year

    params: dict[str, Any] = {
        "year[from]": year_from,
        "year[to]": year_to,
        "type": "Conflict",
        "limit": 2000,
    }
    if country_iso3s:
        # API accepts comma-separated ISO3 list
        params["iso3"] = ",".join(country_iso3s)

    try:
        r = requests.get(
            "https://api.idmcdb.org/api/displacement_data",
            params=params,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        raise RuntimeError(f"IDMC fetch failed: {exc}") from exc

    results = []
    for row in data.get("results", []):
        iso3 = (row.get("iso3") or "").upper()
        iso2 = _ISO3_TO_ISO2.get(iso3, iso3[:2] if len(iso3) >= 2 else "")
        year = row.get("year") or row.get("Year")
        if not year:
            continue
        event_date = f"{int(year)}-01-01"
        stock = row.get("conflict_stock_displacement") or row.get("new_displacements")
        if stock is None:
            continue
        results.append({
            "id": _stable_id("idmc", iso2, event_date, "idp_stock"),
            "source": "idmc",
            "event_date": event_date,
            "country_code": iso2,
            "country_name": row.get("country_name") or row.get("country") or iso3,
            "region": row.get("region"),
            "metric_name": "idp_stock",
            "metric_value": float(stock),
            "raw_json": row,
            "retrieved_at": _NOW(),
        })
    return results


def fetch_acled(
    api_key: str | None = None,
    email: str | None = None,
    country: str | None = None,
    date_range_start: str | None = None,
    date_range_end: str | None = None,
    event_types: list[str] | None = None,
    limit: int = 500,
    timeout: int = 30,
) -> list[dict]:
    """
    Fetch conflict events from the ACLED API.

    API key and email are required; they can be set via env vars
    ACLED_API_KEY and ACLED_EMAIL as an alternative to passing them directly.

    Returns normalized records with metric_name="fatalities".

    API: https://api.acleddata.com/acled/read
    """
    key = api_key or os.environ.get("ACLED_API_KEY")
    mail = email or os.environ.get("ACLED_EMAIL")
    if not key or not mail:
        raise ValueError(
            "ACLED API key and email are required. "
            "Set ACLED_API_KEY and ACLED_EMAIL env vars or pass them explicitly."
        )

    if event_types is None:
        event_types = ["Violence against civilians", "Battles", "Explosions/Remote violence"]

    params: dict[str, Any] = {
        "key": key,
        "email": mail,
        "limit": limit,
        "format": "json",
        "event_type": "|".join(event_types),
        "fields": "event_id_cnty|event_date|event_type|country|iso|fatalities|latitude|longitude|notes",
    }
    if country:
        params["country"] = country
    if date_range_start:
        params["event_date"] = f"{date_range_start}|{date_range_end or dt.datetime.utcnow().date().isoformat()}"
        params["event_date_where"] = "BETWEEN"

    try:
        r = requests.get(
            "https://api.acleddata.com/acled/read",
            params=params,
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        raise RuntimeError(f"ACLED fetch failed: {exc}") from exc

    results = []
    for row in data.get("data", []):
        iso_num = str(row.get("iso", ""))
        # ACLED uses ISO numeric; map common ones. Fall back to country field.
        event_date = row.get("event_date", "")
        fatalities = row.get("fatalities")
        country_name = row.get("country", "")
        # Try to get alpha-2 from ISO3 if available
        iso2 = ""
        for iso3, i2 in _ISO3_TO_ISO2.items():
            if country_name and country_name.lower() in iso3.lower():
                iso2 = i2
                break
        results.append({
            "id": _stable_id("acled", row.get("event_id_cnty", iso_num), event_date, "fatalities"),
            "source": "acled",
            "event_date": event_date,
            "country_code": iso2,
            "country_name": country_name,
            "region": None,
            "metric_name": "fatalities",
            "metric_value": float(fatalities) if fatalities is not None else None,
            "raw_json": row,
            "retrieved_at": _NOW(),
        })
    return results


def fetch_unhcr_stats(
    coo_iso3: str | None = None,
    coa_iso3: str | None = None,
    year_from: int = 2018,
    year_to: int | None = None,
    populations: list[str] | None = None,
    timeout: int = 30,
) -> list[dict]:
    """
    Fetch population statistics from the UNHCR public API.

    populations: list of population types to request.
      Options: "refugees", "idps", "asylumseekers", "stateless", "otherofconcern"
      Default: ["refugees", "idps", "asylumseekers"]

    Returns normalized records with metric_name in:
      "refugee_stock", "idp_stock", "asylum_seeker_stock"

    API: https://api.unhcr.org/population/v1/
    """
    if year_to is None:
        year_to = dt.datetime.utcnow().year
    if populations is None:
        populations = ["refugees", "idps", "asylumseekers"]

    _pop_to_metric = {
        "refugees": "refugee_stock",
        "idps": "idp_stock",
        "asylumseekers": "asylum_seeker_stock",
        "stateless": "stateless_stock",
        "otherofconcern": "other_concern_stock",
    }

    results = []
    for pop_type in populations:
        metric_name = _pop_to_metric.get(pop_type, pop_type)
        params: dict[str, Any] = {
            "yearFrom": year_from,
            "yearTo": year_to,
            "limit": 5000,
        }
        if coo_iso3:
            params["coo"] = coo_iso3
        if coa_iso3:
            params["coa"] = coa_iso3

        url = f"https://api.unhcr.org/population/v1/{pop_type}/"
        try:
            r = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            raise RuntimeError(f"UNHCR stats fetch failed for {pop_type}: {exc}") from exc

        for row in data.get("items", []):
            year = row.get("year")
            if not year:
                continue
            event_date = f"{int(year)}-01-01"
            # Country of origin
            coo = (row.get("coo_iso") or row.get("coo", "")).upper()
            coa = (row.get("coa_iso") or row.get("coa", "")).upper()
            iso3 = coo or coa
            iso2 = _ISO3_TO_ISO2.get(iso3, iso3[:2] if len(iso3) >= 2 else "")
            total = row.get("individuals") or row.get("total") or row.get("value")
            if total is None:
                continue
            results.append({
                "id": _stable_id("unhcr_stats", f"{coo}_{coa}", event_date, metric_name),
                "source": "unhcr_stats",
                "event_date": event_date,
                "country_code": iso2,
                "country_name": row.get("coo_name") or row.get("coa_name") or iso3,
                "region": None,
                "metric_name": metric_name,
                "metric_value": float(total),
                "raw_json": row,
                "retrieved_at": _NOW(),
            })
    return results
