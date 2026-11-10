"""Stage 4 - Merge evidence (rules + grounded LLM claims), score 7 KPIs, rate confidence, explain each lead."""

from __future__ import annotations

import re

DEFAULT_MAX = {"service_fit": 25, "portfolio_size": 20, "billing_relevance": 15, "regulatory_opportunity": 10,
               "switching_opportunity": 10, "digital_maturity": 10, "reachability": 10}


def _llm(llm: dict | None, key: str):
    if not llm or key not in llm:
        return None
    v = llm[key]
    return v if v.get("grounded") and v.get("value") not in (None, [], "") else None


def merge(rules: dict, llm: dict | None, directory: dict) -> dict:
    """Combine sources into one fact sheet. Each fact: value + evidence (quote, url, source)."""
    f: dict = {}
    llm_types = set((_llm(llm, "management_types") or {}).get("value") or [])
    lt_q = (_llm(llm, "management_types") or {}).get("quote", "")
    src_urls = (llm or {}).get("_source_urls", [""])
    llm_url = src_urls[0] if src_urls else ""

    def pick(rule_key, llm_key=None, llm_match=None):
        r = rules.get(rule_key, {})
        if r.get("value"):
            return {"value": r["value"], "quote": r["quote"], "url": r["url"], "source": "rules"}
        if llm_key:
            lv = _llm(llm, llm_key)
            if lv and (llm_match is None or llm_match(lv["value"])):
                return {"value": lv["value"], "quote": lv["quote"], "url": lv.get("url") or llm_url, "source": "llm"}
        return {"value": None, "quote": "", "url": "", "source": ""}

    for t, rk in (("WEG", "weg"), ("Mietverwaltung", "miet"), ("Sondereigentum", "sev"), ("Gewerbe", "gewerbe"), ("Makler", "broker")):
        r = rules.get(rk, {})
        if r.get("value"):
            f[rk] = {"value": True, "quote": r["quote"], "url": r["url"], "source": "rules"}
        elif t in llm_types:
            f[rk] = {"value": True, "quote": lt_q, "url": llm_url, "source": "llm"}
        else:
            f[rk] = {"value": False, "quote": "", "url": "", "source": ""}
    f["manager"] = pick("manager")
    f["units"] = pick("units", "units_managed", lambda v: isinstance(v, int) and 10 <= v <= 300000)
    hint = str(directory.get("units_hint") or "").replace(".0", "")
    if not f["units"]["value"] and hint.isdigit():
        f["units"] = {"value": int(hint), "quote": directory.get("units_hint_quote", ""),
                      "url": directory.get("source_url", ""), "source": "third-party (job ad / list)"}
    f["heating_billing"] = pick("heating_billing", "handles_heating_cost_billing", lambda v: v is True)
    f["self_billing"] = pick("self_billing")
    f["metering_provider"] = pick("metering_provider", "metering_provider")
    f["remote_done"] = pick("remote_done", "remote_reading_status", lambda v: v == "already_remote")
    f["older_stock"] = pick("older_stock", "older_building_stock", lambda v: v is True)
    f["regulation_topic"] = pick("regulation_topic")
    from .extract_rules import SOFTWARE
    f["portal"] = pick("portal")
    f["software"] = pick("software", "software_or_portal", lambda v: bool(SOFTWARE.search(str(v))))
    if not f["portal"]["value"]:
        lv = _llm(llm, "software_or_portal")
        if lv and re.search(r"portal|app|login", str(lv["value"]) + lv["quote"], re.I):
            f["portal"] = {"value": True, "quote": lv["quote"], "url": llm_url, "source": "llm"}
    f["text_chars"] = (rules.get("text_chars") or {}).get("value") or 0
    for k in ("memberships", "decision_makers", "email_personal", "email_generic", "phone", "register_number"):
        f[k] = pick(k)
    if not f["memberships"]["value"] and directory.get("directory_memberships"):
        f["memberships"] = {"value": directory["directory_memberships"], "quote": "listed on directory profile",
                            "url": directory.get("profile_url", ""), "source": "directory"}
    try:
        f["employees"] = int(float(directory.get("employees") or 0)) or None
    except (TypeError, ValueError):
        f["employees"] = None
    f["llm_is_manager"] = (llm or {}).get("is_property_manager", {}).get("value") if llm else None
    f["llm_units_rejected"] = (llm or {}).get("units_managed", {}).get("rejected_value") if llm else None
    f["llm_units"] = (_llm(llm, "units_managed") or {}).get("value")
    f["summary_en"] = (llm or {}).get("summary_en")
    return f


def score(f: dict, weights: dict) -> dict:
    pts, why = {}, {}

    # 1 service fit
    if f["weg"]["value"] and f["miet"]["value"]:
        pts["service_fit"], why["service_fit"] = 25, "WEG + rental management"
    elif f["miet"]["value"]:
        pts["service_fit"], why["service_fit"] = 22, "rental management"
    elif f["weg"]["value"]:
        pts["service_fit"], why["service_fit"] = 20, "WEG management"
    elif f["sev"]["value"]:
        pts["service_fit"], why["service_fit"] = 12, "Sondereigentum management only"
    elif f["manager"]["value"]:
        pts["service_fit"], why["service_fit"] = 10, "property management (type not specified)"
    elif f["gewerbe"]["value"]:
        pts["service_fit"], why["service_fit"] = 8, "commercial only"
    else:
        pts["service_fit"], why["service_fit"] = 0, "no management service evidenced"

    # 2 portfolio size
    u = f["units"]["value"]
    if u:
        pts["portfolio_size"] = 20 if u >= 3000 else 16 if u >= 1000 else 12 if u >= 300 else 8 if u >= 100 else 4
        src = " (third-party source)" if f["units"].get("source", "").startswith("third") else ""
        why["portfolio_size"] = f"{u:,} units stated{src}".replace(",", ".")
    elif f["employees"]:
        e = f["employees"]
        pts["portfolio_size"] = 12 if e >= 50 else 8 if e >= 20 else 4 if e >= 5 else 0
        why["portfolio_size"] = f"proxy: ~{e} employees (units not published)"
    else:
        pts["portfolio_size"], why["portfolio_size"] = 0, "size unknown"

    # 3 billing / heating relevance
    b = 10 if f["heating_billing"]["value"] else 0
    if f["self_billing"]["value"] or f["metering_provider"]["value"]:
        b += 5
    pts["billing_relevance"] = min(15, b)
    why["billing_relevance"] = "mentions heating/operating-cost billing" if b else "no billing evidence"

    # 4 regulatory opportunity (company-specific evidence only, never just the market deadline)
    if f["remote_done"]["value"]:
        pts["regulatory_opportunity"], why["regulatory_opportunity"] = 0, "states remote reading already in place"
    else:
        r = (6 if f["older_stock"]["value"] else 0) + (4 if f["regulation_topic"]["value"] else 0)
        pts["regulatory_opportunity"] = r
        why["regulatory_opportunity"] = ", ".join(x for x in [
            "older building stock" if f["older_stock"]["value"] else "",
            "addresses HKVO / remote reading topic" if f["regulation_topic"]["value"] else ""] if x) or "no company-specific signal"

    # 5 switching opportunity
    if f["metering_provider"]["value"]:
        pts["switching_opportunity"] = 10
        why["switching_opportunity"] = f"works with {f['metering_provider']['value']}"
    elif f["self_billing"]["value"]:
        pts["switching_opportunity"], why["switching_opportunity"] = 6, "bills in-house"
    else:
        pts["switching_opportunity"], why["switching_opportunity"] = 0, "current provider unknown"

    # 6 digital maturity
    d = (5 if f["portal"]["value"] else 0) + (5 if f["software"]["value"] else 0)
    pts["digital_maturity"] = d
    why["digital_maturity"] = ", ".join(x for x in [
        "tenant/owner portal" if f["portal"]["value"] else "",
        f"software: {f['software']['value']}" if f["software"]["value"] else ""] if x) or "no digital signal"

    # 7 reachability
    rch = (4 if f["decision_makers"]["value"] else 0) + (3 if f["email_personal"]["value"] else 1 if f["email_generic"]["value"] else 0) \
        + (1 if f["phone"]["value"] else 0) + (2 if f["memberships"]["value"] else 0)
    pts["reachability"] = min(10, rch)
    why["reachability"] = ", ".join(x for x in [
        "named decision maker" if f["decision_makers"]["value"] else "",
        "direct email" if f["email_personal"]["value"] else "general email" if f["email_generic"]["value"] else "",
        f"member: {f['memberships']['value']}" if f["memberships"]["value"] else ""] if x) or "no contact found"

    # scale to configured weights
    scaled = {k: round(v * weights[k] / DEFAULT_MAX[k], 1) for k, v in pts.items()}
    total = round(sum(scaled.values()))
    evidenced = sum(1 for v in pts.values() if v > 0)
    return {"points": scaled, "why": why, "total": total, "evidenced_kpis": evidenced}


def confidence(f: dict, s: dict, has_pages: bool) -> str:
    if not has_pages:
        return "Low"
    n = s["evidenced_kpis"] + (1 if f["units"]["value"] else 0)
    return "High" if n >= 5 else "Medium" if n >= 3 else "Low"


def review_flags(f: dict, s: dict, prio: str, conf: str, fetch_status: str, prior: str = "") -> list[str]:
    flags = [prior] if prior else []
    if fetch_status != "ok":
        flags.append(f"website: {fetch_status}")
    elif f.get("text_chars", 0) < 800:
        flags.append("very little website text (JavaScript site?) - check manually")
    if f["llm_is_manager"] is False:
        flags.append("LLM says not a property manager")
    if f["broker"]["value"] and not (f["weg"]["value"] or f["miet"]["value"]):
        flags.append("may be broker only")
    if f["llm_units_rejected"]:
        flags.append(f"LLM unit claim rejected (quote not found): {f['llm_units_rejected']}")
    ru, lu = f["units"]["value"], f["llm_units"]
    if ru and lu and abs(ru - lu) / max(ru, lu) > 0.3:
        flags.append(f"unit counts conflict ({ru} vs {lu})")
    if prio == "A" and conf == "Low":
        flags.append("high score but low evidence")
    if prio == "A" and not f["decision_makers"]["value"]:
        flags.append("A-lead without named decision maker")
    return flags


def sales_angle(f: dict, s: dict) -> str:
    p = s["points"]
    if p["switching_opportunity"] > 0 and f["metering_provider"]["value"]:
        return f"Provider switch: modern, remotely-read alternative to {f['metering_provider']['value']}"
    if p["regulatory_opportunity"] > 0:
        return "Compliance review before the 31.12.2026 remote-reading deadline (HKVO §5)"
    if f["self_billing"]["value"]:
        return "Automate in-house heating-cost billing with real-time data"
    if p["digital_maturity"] > 0:
        return "Dashboard + software integration (fits their digital setup)"
    if f["heating_billing"]["value"]:
        return "Billing efficiency: one-click heating-cost billing"
    return "Discovery call: qualify metering setup and portfolio"


def explain(name: str, f: dict, s: dict, prio: str, conf: str) -> str:
    w = s["why"]
    parts = [f"Priority {prio} ({s['total']}/100, confidence {conf})."]
    parts.append(f"Service: {w['service_fit']}; size: {w['portfolio_size']}.")
    extras = [w[k] for k in ("billing_relevance", "regulatory_opportunity", "switching_opportunity")
              if s["points"][k] > 0]
    if extras:
        parts.append("Signals: " + "; ".join(extras) + ".")
    if not f["remote_done"]["value"]:
        parts.append("Remote-reading status not public, so position as a compliance check, not a claim of non-compliance.")
    return " ".join(parts)
