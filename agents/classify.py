from __future__ import annotations

from collections import Counter


POPULATION_RULES = {
    "refugee": "refugees",
    "refugees": "refugees",
    "asylum seeker": "asylum_seekers",
    "asylum seekers": "asylum_seekers",
    "idp": "idps",
    "idps": "idps",
    "internally displaced": "idps",
    "returnee": "returnees",
    "returnees": "returnees",
    "migrant": "migrants",
    "migrants": "migrants",
}

EVENT_RULES = {
    "border closed": "border_measure",
    "border closure": "border_measure",
    "border restrictions": "border_measure",
    "deport": "return_or_deportation",
    "deported": "return_or_deportation",
    "return": "return_or_deportation",
    "returns": "return_or_deportation",
    "resettlement": "resettlement",
    "camp closure": "camp_status_change",
    "camp": "camp_status_change",
    "evacuation": "displacement_trigger",
    "flee": "displacement_trigger",
    "fled": "displacement_trigger",
    "displaced": "displacement_trigger",
    "displacement": "displacement_trigger",
    "funding shortfall": "aid_and_funding",
    "funding gap": "aid_and_funding",
    "aid cut": "aid_and_funding",
    "humanitarian access": "aid_and_access",
    "access constraints": "aid_and_access",
    "access denied": "aid_and_access",
    "asylum policy": "policy_change",
    "protection": "protection_risk",
    "detention": "protection_risk",
}

DRIVER_RULES = {
    "conflict": "conflict",
    "violence": "conflict",
    "airstrike": "conflict",
    "attack": "conflict",
    "fighting": "conflict",
    "flood": "climate_or_disaster",
    "drought": "climate_or_disaster",
    "storm": "climate_or_disaster",
    "earthquake": "climate_or_disaster",
    "policy": "policy_or_legal",
    "asylum": "policy_or_legal",
    "border": "policy_or_legal",
    "eviction": "housing_land_property",
    "demolition": "housing_land_property",
}

OPERATIONAL_SIGNAL_RULES = {
    "border_measure": "border_restriction",
    "return_or_deportation": "return_pressure",
    "camp_status_change": "camp_change",
    "aid_and_funding": "funding_gap",
    "aid_and_access": "access_constraint",
    "protection_risk": "protection_risk",
    "displacement_trigger": "new_displacement",
}


def _match_first(text: str, rules: dict[str, str], default: str) -> str:
    for needle, label in rules.items():
        if needle in text:
            return label
    return default


def _coverage_confidence(tier: str, matched_keywords: int, country_codes: list[str]) -> float:
    tier_weight = {"A": 0.95, "B": 0.8, "C": 0.65, "U": 0.45}.get(tier or "U", 0.45)
    keyword_bonus = min(matched_keywords, 4) * 0.05
    country_bonus = 0.05 if country_codes else 0.0
    return round(min(0.99, tier_weight + keyword_bonus + country_bonus), 2)


def _location_precision(country_codes: list[str], text: str) -> str:
    if not country_codes:
        return "unknown"
    if len(country_codes) == 1:
        if any(term in text for term in ("province", "district", "city", "camp", "village", "governorate", "state")):
            return "subnational"
        return "national"
    return "regional"


def classify_item(item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    country_codes = item.get("country_codes") or []
    keywords_hit = item.get("keywords_hit") or []
    event_type = _match_first(text, EVENT_RULES, "general_displacement_coverage")
    population_type = _match_first(text, POPULATION_RULES, "mixed_or_unspecified")
    driver = _match_first(text, DRIVER_RULES, "unspecified")
    operational_signal = OPERATIONAL_SIGNAL_RULES.get(event_type, "monitor")

    result = dict(item)
    result["event_type"] = event_type
    result["population_type"] = population_type
    result["driver"] = driver
    result["displacement_stage"] = "ongoing"
    if event_type == "return_or_deportation":
        result["displacement_stage"] = "return_or_restriction"
    elif event_type == "displacement_trigger":
        result["displacement_stage"] = "acute_movement"
    elif event_type in ("aid_and_funding", "aid_and_access", "protection_risk"):
        result["displacement_stage"] = "response_and_protection"

    result["location_precision"] = _location_precision(country_codes, text)
    result["operational_signal"] = operational_signal
    result["coverage_confidence"] = _coverage_confidence(item.get("tier", "U"), len(keywords_hit), country_codes)
    result["research_priority"] = "high" if result["coverage_confidence"] >= 0.85 or item.get("tier") == "A" else "medium"
    if event_type in ("aid_and_access", "aid_and_funding", "protection_risk", "border_measure"):
        result["field_priority"] = "high"
    elif event_type in ("displacement_trigger", "return_or_deportation", "camp_status_change"):
        result["field_priority"] = "medium"
    else:
        result["field_priority"] = "monitor"
    return result


def summarize_classifications(rows: list[dict]) -> dict[str, list[tuple[str, int]]]:
    event_counter = Counter()
    signal_counter = Counter()
    driver_counter = Counter()
    for row in rows:
        event_counter.update([row.get("event_type") or "unknown"])
        signal_counter.update([row.get("operational_signal") or "monitor"])
        driver_counter.update([row.get("driver") or "unspecified"])
    return {
        "event_types": event_counter.most_common(5),
        "signals": signal_counter.most_common(5),
        "drivers": driver_counter.most_common(5),
    }
