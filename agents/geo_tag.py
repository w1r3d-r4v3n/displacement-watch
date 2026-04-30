"""
Offline country/region tagging for displacement-relevant items.

Two-pass strategy:
  Pass 1 — GDELT sourceCountry field (stored in item["snippet"] for gdelt items).
            GDELT uses FIPS-104 country codes; we map them to ISO 3166-1 alpha-2.
  Pass 2 — Text scan of title + snippet using longest-match word-boundary regex.

No external dependencies. Embedded lookup tables cover ~80 countries most
relevant to displacement research (all UNHCR persons-of-concern nations).
"""
from __future__ import annotations
import re

# FIPS-104 -> ISO 3166-1 alpha-2 for displacement-relevant countries
FIPS_TO_ISO: dict[str, str] = {
    "AF": "AF",  # Afghanistan
    "AG": "DZ",  # Algeria
    "AO": "AO",  # Angola
    "AR": "AR",  # Argentina
    "BA": "BA",  # Bosnia-Herzegovina
    "BC": "BW",  # Botswana
    "BF": "BF",  # Burkina Faso
    "BG": "BD",  # Bangladesh
    "BM": "MM",  # Burma/Myanmar
    "BP": "SB",  # Solomon Islands
    "BR": "BR",  # Brazil
    "BU": "BI",  # Burundi
    "BY": "BY",  # Belarus
    "CA": "CA",  # Canada
    "CB": "KH",  # Cambodia
    "CD": "TD",  # Chad
    "CF": "CG",  # Congo (Brazzaville)
    "CG": "CD",  # Congo (DRC)
    "CI": "CL",  # Chile
    "CM": "CM",  # Cameroon
    "CO": "CO",  # Colombia
    "CT": "CF",  # Central African Republic
    "CU": "CU",  # Cuba
    "CY": "CY",  # Cyprus
    "DA": "DK",  # Denmark
    "DR": "DO",  # Dominican Republic
    "EC": "EC",  # Ecuador
    "EG": "EG",  # Egypt
    "EI": "IE",  # Ireland
    "ER": "ER",  # Eritrea
    "ET": "ET",  # Ethiopia
    "EZ": "CZ",  # Czech Republic
    "FI": "FI",  # Finland
    "GA": "GM",  # Gambia
    "GH": "GH",  # Ghana
    "GJ": "AZ",  # Azerbaijan
    "GM": "DE",  # Germany
    "GQ": "GU",  # Guam
    "GR": "GR",  # Greece
    "GT": "GT",  # Guatemala
    "GV": "GN",  # Guinea
    "HA": "HT",  # Haiti
    "HO": "HN",  # Honduras
    "HR": "HR",  # Croatia
    "HU": "HU",  # Hungary
    "ID": "ID",  # Indonesia
    "IN": "IN",  # India
    "IQ": "IQ",  # Iraq
    "IR": "IR",  # Iran
    "IT": "IT",  # Italy
    "IV": "CI",  # Cote d'Ivoire
    "IZ": "IQ",  # Iraq (alt)
    "JO": "JO",  # Jordan
    "KE": "KE",  # Kenya
    "KG": "KG",  # Kyrgyzstan
    "KN": "KP",  # North Korea
    "KS": "XK",  # Kosovo
    "KU": "KW",  # Kuwait
    "KZ": "KZ",  # Kazakhstan
    "LB": "LB",  # Lebanon
    "LE": "LB",  # Lebanon (alt)
    "LI": "LR",  # Liberia
    "LO": "SK",  # Slovakia
    "LS": "LS",  # Lesotho
    "LY": "LY",  # Libya
    "MA": "MG",  # Madagascar
    "MB": "MZ",  # Mozambique
    "ML": "ML",  # Mali
    "MO": "MA",  # Morocco
    "MP": "MU",  # Mauritius
    "MR": "MR",  # Mauritania
    "MU": "OM",  # Oman
    "MV": "MV",  # Maldives
    "MW": "MW",  # Malawi
    "MY": "MY",  # Malaysia
    "MZ": "MZ",  # Mozambique (alt)
    "NE": "NE",  # Niger
    "NG": "NG",  # Nigeria
    "NI": "NI",  # Nicaragua
    "NL": "NL",  # Netherlands
    "NO": "NO",  # Norway
    "NR": "NR",  # Nauru
    "NS": "SR",  # Suriname
    "OD": "SS",  # South Sudan
    "PA": "PY",  # Paraguay
    "PE": "PE",  # Peru
    "PK": "PK",  # Pakistan
    "PU": "GW",  # Guinea-Bissau
    "QA": "QA",  # Qatar
    "RI": "SR",  # Serbia (alt)
    "RO": "RO",  # Romania
    "RQ": "PR",  # Puerto Rico
    "RS": "RU",  # Russia
    "RW": "RW",  # Rwanda
    "SA": "SA",  # Saudi Arabia
    "SB": "ST",  # Sao Tome/Principe
    "SE": "SE",  # Sweden
    "SF": "ZA",  # South Africa
    "SG": "SN",  # Senegal
    "SI": "SI",  # Slovenia
    "SL": "SL",  # Sierra Leone
    "SM": "SM",  # San Marino
    "SO": "SO",  # Somalia
    "SP": "ES",  # Spain
    "SR": "SR",  # Suriname (alt)
    "SS": "SS",  # South Sudan (alt)
    "SU": "SD",  # Sudan
    "SW": "SE",  # Sweden (alt)
    "SY": "SY",  # Syria
    "TD": "TJ",  # Tajikistan
    "TH": "TH",  # Thailand
    "TI": "TJ",  # Tajikistan (alt)
    "TK": "TK",  # Tokelau
    "TN": "TN",  # Tunisia
    "TO": "TO",  # Tonga
    "TS": "TN",  # Tunisia (alt)
    "TU": "TR",  # Turkey/Turkiye
    "TZ": "TZ",  # Tanzania
    "UG": "UG",  # Uganda
    "UK": "GB",  # United Kingdom
    "UP": "UA",  # Ukraine
    "US": "US",  # United States
    "UV": "BF",  # Burkina Faso (alt)
    "UZ": "UZ",  # Uzbekistan
    "VE": "VE",  # Venezuela
    "VM": "VN",  # Vietnam
    "WA": "NA",  # Namibia
    "WI": "EH",  # Western Sahara
    "XO": "XO",  # International/unknown (skip)
    "YM": "YE",  # Yemen
    "ZA": "ZM",  # Zambia
    "ZI": "ZW",  # Zimbabwe
    "ZM": "ZM",  # Zambia (alt)
    "ZW": "ZW",  # Zimbabwe (alt)
}

# ISO 3166-1 alpha-2 -> UN macro-region
ISO_TO_UN_REGION: dict[str, str] = {
    # Western Asia
    "SY": "Western Asia", "IQ": "Western Asia", "LB": "Western Asia",
    "PS": "Western Asia", "JO": "Western Asia", "YE": "Western Asia",
    "TR": "Western Asia", "SA": "Western Asia", "QA": "Western Asia",
    "KW": "Western Asia", "AZ": "Western Asia", "GE": "Western Asia",
    "AM": "Western Asia", "XK": "Western Asia",
    # Eastern Europe
    "UA": "Eastern Europe", "BY": "Eastern Europe", "RU": "Eastern Europe",
    "MD": "Eastern Europe", "RO": "Eastern Europe", "BA": "Eastern Europe",
    "RS": "Eastern Europe", "HR": "Eastern Europe", "SI": "Eastern Europe",
    "HU": "Eastern Europe", "CZ": "Eastern Europe", "SK": "Eastern Europe",
    "PL": "Eastern Europe",
    # Southern Asia
    "AF": "Southern Asia", "PK": "Southern Asia", "BD": "Southern Asia",
    "IN": "Southern Asia", "LK": "Southern Asia", "NP": "Southern Asia",
    "MV": "Southern Asia",
    # South-Eastern Asia
    "MM": "South-Eastern Asia", "TH": "South-Eastern Asia", "MY": "South-Eastern Asia",
    "ID": "South-Eastern Asia", "PH": "South-Eastern Asia", "VN": "South-Eastern Asia",
    "KH": "South-Eastern Asia", "LA": "South-Eastern Asia",
    # Sub-Saharan Africa
    "SS": "Sub-Saharan Africa", "SD": "Sub-Saharan Africa", "SO": "Sub-Saharan Africa",
    "CD": "Sub-Saharan Africa", "ET": "Sub-Saharan Africa", "NG": "Sub-Saharan Africa",
    "ML": "Sub-Saharan Africa", "BF": "Sub-Saharan Africa", "CF": "Sub-Saharan Africa",
    "NE": "Sub-Saharan Africa", "MZ": "Sub-Saharan Africa", "ZW": "Sub-Saharan Africa",
    "ZM": "Sub-Saharan Africa", "KE": "Sub-Saharan Africa", "UG": "Sub-Saharan Africa",
    "TZ": "Sub-Saharan Africa", "RW": "Sub-Saharan Africa", "BI": "Sub-Saharan Africa",
    "AO": "Sub-Saharan Africa", "CM": "Sub-Saharan Africa", "GN": "Sub-Saharan Africa",
    "SL": "Sub-Saharan Africa", "LR": "Sub-Saharan Africa", "GH": "Sub-Saharan Africa",
    "CI": "Sub-Saharan Africa", "SN": "Sub-Saharan Africa", "GM": "Sub-Saharan Africa",
    "GW": "Sub-Saharan Africa", "MR": "Sub-Saharan Africa", "TD": "Sub-Saharan Africa",
    "ER": "Sub-Saharan Africa", "DJ": "Sub-Saharan Africa", "MG": "Sub-Saharan Africa",
    "MW": "Sub-Saharan Africa", "LS": "Sub-Saharan Africa", "ZA": "Sub-Saharan Africa",
    "NA": "Sub-Saharan Africa",
    # Northern Africa
    "LY": "Northern Africa", "TN": "Northern Africa", "DZ": "Northern Africa",
    "MA": "Northern Africa", "EG": "Northern Africa", "SD": "Northern Africa",
    "EH": "Northern Africa",
    # Latin America and the Caribbean
    "HT": "Latin America and the Caribbean", "VE": "Latin America and the Caribbean",
    "CO": "Latin America and the Caribbean", "EC": "Latin America and the Caribbean",
    "PE": "Latin America and the Caribbean", "BO": "Latin America and the Caribbean",
    "GT": "Latin America and the Caribbean", "HN": "Latin America and the Caribbean",
    "NI": "Latin America and the Caribbean", "SV": "Latin America and the Caribbean",
    "MX": "Latin America and the Caribbean", "CU": "Latin America and the Caribbean",
    "DO": "Latin America and the Caribbean",
    # Central Asia
    "KZ": "Central Asia", "KG": "Central Asia", "TJ": "Central Asia",
    "TM": "Central Asia", "UZ": "Central Asia",
    # Eastern Asia
    "KP": "Eastern Asia", "CN": "Eastern Asia",
}

# Country name / demonym variants -> ISO 3166-1 alpha-2
# Sorted by key length (longest first) at module load to enable longest-match scanning
_RAW_NAME_TO_ISO: dict[str, str] = {
    # Multi-word names first (longest-match priority)
    "south sudan": "SS",
    "western sahara": "EH",
    "central african republic": "CF",
    "democratic republic of the congo": "CD",
    "republic of the congo": "CG",
    "guinea-bissau": "GW",
    "sierra leone": "SL",
    "burkina faso": "BF",
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "north korea": "KP",
    "south africa": "ZA",
    "saudi arabia": "SA",
    "united arab emirates": "AE",
    "west bank": "PS",
    "occupied territories": "PS",
    "western asia": "XW",  # handled as region marker
    # Single-word names and demonyms
    "syria": "SY", "syrian": "SY", "syrians": "SY",
    "ukraine": "UA", "ukrainian": "UA", "ukrainians": "UA",
    "afghanistan": "AF", "afghan": "AF", "afghans": "AF",
    "myanmar": "MM", "burmese": "MM", "rohingya": "MM", "burma": "MM",
    "sudan": "SD", "sudanese": "SD",
    "somalia": "SO", "somali": "SO", "somalis": "SO",
    "ethiopia": "ET", "ethiopian": "ET", "ethiopians": "ET",
    "nigeria": "NG", "nigerian": "NG",
    "mali": "ML", "malian": "ML",
    "niger": "NE",
    "chad": "TD", "chadian": "TD",
    "cameroon": "CM", "cameroonian": "CM",
    "congo": "CD",  # default DRC (larger crisis); override with "republic of the congo" above
    "mozambique": "MZ", "mozambican": "MZ",
    "zimbabwe": "ZW", "zimbabwean": "ZW",
    "zambia": "ZM",
    "kenya": "KE", "kenyan": "KE",
    "uganda": "UG", "ugandan": "UG",
    "tanzania": "TZ",
    "rwanda": "RW", "rwandan": "RW",
    "burundi": "BI", "burundian": "BI",
    "angola": "AO", "angolan": "AO",
    "guinea": "GN", "guinean": "GN",
    "liberia": "LR", "liberian": "LR",
    "ghana": "GH", "ghanaian": "GH",
    "senegal": "SN",
    "mauritania": "MR",
    "eritrea": "ER", "eritrean": "ER",
    "haiti": "HT", "haitian": "HT", "haitians": "HT",
    "venezuela": "VE", "venezuelan": "VE", "venezuelans": "VE",
    "colombia": "CO", "colombian": "CO",
    "ecuador": "EC", "ecuadorian": "EC",
    "peru": "PE", "peruvian": "PE",
    "guatemala": "GT", "guatemalan": "GT",
    "honduras": "HN", "honduran": "HN",
    "nicaragua": "NI", "nicaraguan": "NI",
    "iraq": "IQ", "iraqi": "IQ", "iraqis": "IQ",
    "gaza": "PS", "palestine": "PS", "palestinian": "PS", "palestinians": "PS",
    "lebanon": "LB", "lebanese": "LB",
    "jordan": "JO", "jordanian": "JO",
    "yemen": "YE", "yemeni": "YE", "yemenis": "YE",
    "turkey": "TR", "turkish": "TR", "turkiye": "TR",
    "iran": "IR", "iranian": "IR",
    "pakistan": "PK", "pakistani": "PK",
    "bangladesh": "BD", "bangladeshi": "BD",
    "india": "IN", "indian": "IN",
    "russia": "RU", "russian": "RU",
    "belarus": "BY", "belarusian": "BY",
    "moldova": "MD",
    "georgia": "GE", "georgian": "GE",
    "azerbaijan": "AZ",
    "tajikistan": "TJ", "tajik": "TJ",
    "kyrgyzstan": "KG", "kyrgyz": "KG",
    "uzbekistan": "UZ", "uzbek": "UZ",
    "kazakhstan": "KZ",
    "libya": "LY", "libyan": "LY",
    "egypt": "EG", "egyptian": "EG",
    "morocco": "MA", "moroccan": "MA",
    "tunisia": "TN", "tunisian": "TN",
    "algeria": "DZ", "algerian": "DZ",
    "indonesia": "ID", "indonesian": "ID",
    "cambodia": "KH", "cambodian": "KH",
    "vietnam": "VN", "vietnamese": "VN",
    "laos": "LA", "lao": "LA",
    "thailand": "TH", "thai": "TH",
    "malaysia": "MY",
    "philippines": "PH", "filipino": "PH",
    "cuba": "CU", "cuban": "CU",
    "sahel": None,  # multi-country region; handled as a region marker (None skips ISO tagging)
    "kosovo": "XK",
    "drc": "CD",
    "idp": None,   # not a country; prevent false matches
    "unhcr": None,
    "iom": None,
}

# Build compiled regex patterns sorted by key length descending (longest-match wins)
_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    (re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE), v)
    for k, v in sorted(_RAW_NAME_TO_ISO.items(), key=lambda x: len(x[0]), reverse=True)
]

COUNTRY_NAME_TO_ISO: dict[str, str] = {
    k: v for k, v in _RAW_NAME_TO_ISO.items() if v is not None
}


def tag_item(item: dict) -> dict:
    """Return a copy of item with country_codes (list[str]) and un_region (str|None) added."""
    codes: set[str] = set()

    # Pass 1: GDELT sourceCountry (FIPS stored in snippet for gdelt items)
    if item.get("source_type") == "gdelt":
        fips = (item.get("snippet") or "").strip().upper()
        if fips and fips in FIPS_TO_ISO:
            iso = FIPS_TO_ISO[fips]
            if iso and iso != "XO":
                codes.add(iso)

    # Pass 2: text scan of title + snippet
    title = item.get("title") or ""
    snippet = item.get("snippet") or ""
    text = f"{title} {snippet}"
    seen_spans: list[tuple[int, int]] = []

    for pattern, iso in _PATTERNS:
        if iso is None:
            continue
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            # Skip if overlapped by a longer already-matched span
            if any(s <= start and end <= e for s, e in seen_spans):
                continue
            seen_spans.append((start, end))
            codes.add(iso)

    country_codes = sorted(codes)

    # Determine UN region: use most-mentioned code, or first alphabetically
    un_region: str | None = None
    if country_codes:
        region_counts: dict[str, int] = {}
        for code in country_codes:
            region = ISO_TO_UN_REGION.get(code)
            if region:
                region_counts[region] = region_counts.get(region, 0) + 1
        if region_counts:
            un_region = max(region_counts, key=lambda r: region_counts[r])

    result = dict(item)
    result["country_codes"] = country_codes
    result["un_region"] = un_region
    return result


def tag_items_batch(items: list[dict]) -> list[dict]:
    return [tag_item(it) for it in items]
