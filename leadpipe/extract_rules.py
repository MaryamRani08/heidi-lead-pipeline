"""Stage 3b - Deterministic extraction. Every finding stores the exact quote and source URL (evidence)."""

from __future__ import annotations

import re

WIN = 90  # characters of context kept around a match as the evidence quote


def _quote(text: str, m: re.Match) -> str:
    s, e = max(0, m.start() - WIN), min(len(text), m.end() + WIN)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def find(pages: list[dict], pattern: re.Pattern, roles: tuple[str, ...] | None = None):
    """First match across pages -> (match, quote, url) or None."""
    for p in pages:
        if roles and p["role"] not in roles:
            continue
        m = pattern.search(p["text"])
        if m:
            return m, _quote(p["text"], m), p["url"]
    return None


def ev(value, hit) -> dict:
    return {"value": value, "quote": hit[1] if hit else "", "url": hit[2] if hit else ""}


# ---------------- patterns ----------------
P = {
    "weg": re.compile(r"WEG[- ]?Verwaltung|Wohnungseigentümergemeinschaft|Wohnungseigentumsverwaltung|Verwaltung von Wohnungseigentum|\bWEG\b", re.I),
    "miet": re.compile(r"Mietverwaltung|Mietshausverwaltung|Mietshäuser|Zinshaus|Verwaltung von Miet|Mietobjekte|Mehrfamilienh", re.I),
    "sev": re.compile(r"Sondereigentumsverwaltung|\bSEV\b|Sondereigentum", re.I),
    "gewerbe": re.compile(r"Gewerbe(?:immobilien|objekte|verwaltung|einheiten)|Büroimmobilien|commercial", re.I),
    "broker": re.compile(r"Immobilienmakler|Maklerleistung|Vermittlung von Immobilien|Verkauf Ihrer Immobilie|Immobilienverkauf", re.I),
    "manager": re.compile(r"Hausverwaltung|Immobilienverwaltung|Hausverwalter|Property Management|Objektverwaltung|Grundstücksverwaltung", re.I),
    "units": re.compile(
        r"(?:über|mehr als|rund|ca\.?|circa|etwa|insgesamt)?\s*(\d{1,3}(?:[.\s]\d{3})+|\d{2,6})\s*\+?\s*"
        r"(?:verwaltete[n]?\s+)?(?:Wohn-?\s*(?:und|&)\s*Gewerbeeinheiten|Wohneinheiten|Einheiten|Wohnungen|Mieteinheiten|Verwaltungseinheiten|units)",
        re.I),
    "heating_billing": re.compile(r"Heizkostenabrechnung|Betriebskostenabrechnung|Nebenkostenabrechnung|Heizkosten|Verbrauchserfassung|Wärmekosten", re.I),
    "self_billing": re.compile(r"(Heiz|Betriebs|Neben)kostenabrechnung(?:en)?\s+(?:erstellen wir|wird bei uns|im eigenen Haus|selbst|inhouse|in-house)", re.I),
    "older_stock": re.compile(r"Altbau|Gründerzeit|Bestandsimmobilie|Bestandsgebäude|denkmalgeschützt|Jahrhundertwende|Plattenbau", re.I),
    "regulation_topic": re.compile(r"Heizkostenverordnung|HKVO|HeizkostenV|fernablesbar|Fernablesung|unterjährige Verbrauchsinformation|\bUVI\b|Funkzähler|Funkablesung", re.I),
    "remote_done": re.compile(r"(bereits|vollständig|komplett|alle)[^.]{0,60}(fernablesbar|Funk(?:technik|zähler|messtechnik)|umgerüstet)", re.I),
    "portal": re.compile(r"Mieterportal|Eigentümerportal|Kundenportal|Online[- ]Portal|Mieter-?App|Eigentümer-?App|Service-?App|Kundenbereich|casavi|Facilioo|immocloud|Allthings|Animus|ImmoMio", re.I),
    "membership": re.compile(r"\b(VDIV|IVD|BVI|DDIV)\b|Verband der Immobilienverwalter|Immobilienverband Deutschland|Bundesfachverband der Immobilienverwalter"),
}
PROVIDERS = re.compile(r"\b(ista|Techem|Brunata|Minol|KALO|Kalorimeta|Metrona|Qundis|noventic|Wärmemessdienst|Viterra|BFW|Messdienst Lorenz|ENERGIE-Service)\b")
PROVIDER_RELATION = re.compile(r"Partner|Zusammenarbeit|zusammen mit|beauftragt|Messdienst|Abrechnung durch|abgerechnet|Ablesung durch|Vertrag", re.I)
SOFTWARE = re.compile(r"\b(DOMUS|Immoware24|casavi|Haufe|PowerHaus|axera|Karthago|Wodis|iX-Haus|Facilioo|Hausperfekt|Fairwalter|objego|Aareon|SAP RE-FX|GES|EVERREAL|Immoledo|Immocloud)\b", re.I)

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+\s?(?:@|\(at\)|\[at\]| at )\s?[A-Za-z0-9.\-]+\s?(?:\.|\(dot\)|\[dot\])\s?[A-Za-z]{2,}")
GENERIC_PREFIX = re.compile(r"^(info|kontakt|contact|office|mail|post|service|verwaltung|hausverwaltung|empfang|zentrale|hallo|hello|team|buero|büro|anfrage|bewerbung|datenschutz|webmaster|support|noreply|no-reply|investor|investorrelations|ir|presse|press|karriere|jobs|career|weg|miete|mietverwaltung|buchhaltung|technik|notdienst|vermietung|kundenservice|immobilien)\b", re.I)
FREEMAIL = re.compile(r"@(gmail|googlemail|gmx|web|t-online|yahoo|outlook|hotmail|icloud|aol|freenet|posteo|mail)\.", re.I)
PHONE = re.compile(r"(?:Tel(?:efon)?\.?|Fon|T)\s*:?\s*(\+?\d[\d\s/()\-]{6,20}\d)")
HRB = re.compile(r"HR[AB]\s?\d{3,7}\s?[A-Z]?")
GF_LINE = re.compile(
    r"(?:Geschäftsführ(?:er|erin|ung|ende[rn]?\s+Gesellschafter(?:in)?)|Vertreten durch(?:\s+(?:den|die)\s+Geschäftsführer(?:in)?)?|Inhaber(?:in)?|Vorstand|Managing Director|Geschäftsleitung)"
    r"\s*[:\-]?\s*\n?\s*([^\n]{3,160})", re.I)
_W = r"[A-ZÄÖÜ][a-zäöüß]+(?:-\s?[A-ZÄÖÜ][a-zäöüß]+)?"
NAME = re.compile(r"(?:(?:Dr\.|Prof\.|Dipl\.-[A-Za-zä]+\.?|Kfm\.)\s+)*" + _W + r"(?:\s+(?:von|van|de|zu)\b)?(?:\s+" + _W + r"){1,2}")
NOT_NAMES = re.compile(r"GmbH|Straße|Str\.|Berlin|Amtsgericht|Registergericht|Telefon|Gesellschaft|Hausverwaltung|Immobilien|Verwaltung|Handelsregister|"
                       r"Unsere|Unser|Dienstleistung|Leistung|Kontakt|Team|Datenschutz|Impressum|Angaben|Sitz|Steuer|Umsatz|Verantwortlich|Inhalt|Service|Mitglied|Verband|Telefax|Weitere|Kunden|Eigentümer|Mieter|Willkommen|Startseite|Partner", re.I)


def _norm_email(e: str) -> str:
    e = re.sub(r"\s?(\(at\)|\[at\]| at )\s?", "@", e, flags=re.I)
    e = re.sub(r"\s?(\(dot\)|\[dot\])\s?", ".", e, flags=re.I)
    return e.replace(" ", "").strip(".").lower()


def _site_domain(pages: list[dict]) -> str:
    from urllib.parse import urlparse
    if not pages:
        return ""
    host = urlparse(pages[0]["url"]).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def parse_units(raw: str) -> int | None:
    n = int(re.sub(r"[.\s]", "", raw))
    return n if 10 <= n <= 300_000 else None


# some signals only count if the surrounding text is about the company itself (not a blog article / a provider's app)
CONTEXT = {
    "older_stock": (re.compile(r"\bunser|\bwir\b|verwalte|Bestand|Liegenschaft|Objekt|Portfolio|betreuen", re.I),
                    re.compile(r"Funk|Empfang|Messdienst|Ablesung", re.I)),
    "portal": (re.compile(r"\bunser|\bIhr|Login|Kunden|Eigentümer|Mieter|einloggen|Zugang", re.I),
               re.compile(r"des Messdienst|Messdienstes|Abrechnungsdienstleister", re.I)),
}


def find_in_context(pages, key):
    want, avoid = CONTEXT[key]
    for p in pages:
        t = p["text"]
        for m in P[key].finditer(t):
            # judge only the sentence (or line) that contains the match
            s0 = max(t.rfind(".", 0, m.start()), t.rfind("\n", 0, m.start()), t.rfind(":", 0, m.start() - 1)) + 1
            e_candidates = [i for i in (t.find(".", m.end()), t.find("\n", m.end())) if i != -1]
            e0 = min(e_candidates) if e_candidates else len(t)
            sent = t[s0:e0]
            if want.search(sent) and not avoid.search(sent):
                return m, re.sub(r"\s+", " ", sent).strip()[:240], p["url"]
    return None


def extract(pages: list[dict]) -> dict:
    r: dict = {}
    for key in ("weg", "miet", "sev", "gewerbe", "broker", "manager", "heating_billing", "self_billing",
                "older_stock", "regulation_topic", "remote_done", "portal"):
        hit = find_in_context(pages, key) if key in CONTEXT else find(pages, P[key])
        r[key] = ev(bool(hit), hit)
    r["text_chars"] = {"value": sum(len(p["text"]) for p in pages), "quote": "", "url": ""}

    # units: take the largest plausible number found anywhere (sites often say "über 2.500 Einheiten")
    best = None
    for p in pages:
        for m in P["units"].finditer(p["text"]):
            n = parse_units(m.group(1))
            if n and (best is None or n > best[0]):
                best = (n, _quote(p["text"], m), p["url"])
    r["units"] = {"value": best[0], "quote": best[1], "url": best[2]} if best else ev(None, None)

    # metering provider: only counts if a relationship word is in the same sentence
    prov = None
    for p in pages:
        for sent in re.split(r"(?<=[.!?\n])\s+", p["text"]):
            m = PROVIDERS.search(sent)
            if m and PROVIDER_RELATION.search(sent):
                prov = (m.group(1), re.sub(r"\s+", " ", sent)[:220], p["url"])
                break
        if prov:
            break
    r["metering_provider"] = {"value": prov[0], "quote": prov[1], "url": prov[2]} if prov else ev(None, None)

    sw = set()
    sw_hit = None
    for p in pages:
        for m in SOFTWARE.finditer(p["text"]):
            sw.add(m.group(1))
            sw_hit = sw_hit or (m, _quote(p["text"], m), p["url"])
    r["software"] = ev(", ".join(sorted(sw)) or None, sw_hit if sw else None)

    mem = set()
    mem_hit = None
    for p in pages:
        for m in P["membership"].finditer(p["text"]):
            label = m.group(1) or {"Verband der Immobilienverwalter": "VDIV", "Immobilienverband Deutschland": "IVD",
                                   "Bundesfachverband der Immobilienverwalter": "BVI"}.get(m.group(0), m.group(0))
            mem.add("VDIV" if label == "DDIV" else label)
            mem_hit = mem_hit or (m, _quote(p["text"], m), p["url"])
    r["memberships"] = ev(", ".join(sorted(mem)) or None, mem_hit if mem else None)

    # ----- contacts: Impressum first (legally required info), then contact/team pages -----
    contact_pages = sorted(pages, key=lambda p: {"impressum": 0, "team": 1, "home": 2}.get(p["role"], 3))
    site = _site_domain(pages)
    emails, phones = [], []
    for p in contact_pages:
        for m in EMAIL.finditer(p["text"]):
            e = _norm_email(m.group(0))
            dom = e.split("@")[-1]
            if e in [x[0] for x in emails] or "." not in dom or FREEMAIL.search(e):
                continue
            if site and not (dom == site or dom.endswith("." + site) or site.endswith("." + dom)):
                continue  # only addresses on the company's own domain
            emails.append((e, p["url"]))
        pm = PHONE.search(p["text"])
        if pm and not phones:
            phones.append((re.sub(r"\s+", " ", pm.group(1)).strip(), p["url"]))
    def is_generic(e: str) -> bool:
        local, dom = e.split("@")
        return bool(GENERIC_PREFIX.match(local)) or local.replace("-", "") in dom.replace("-", "")
    personal = [e for e in emails if not is_generic(e[0])]
    generic = [e for e in emails if is_generic(e[0])]
    r["email_personal"] = {"value": personal[0][0] if personal else None, "quote": personal[0][0] if personal else "",
                           "url": personal[0][1] if personal else ""}
    r["email_generic"] = {"value": generic[0][0] if generic else None, "quote": generic[0][0] if generic else "",
                          "url": generic[0][1] if generic else ""}
    r["phone"] = {"value": phones[0][0] if phones else None, "quote": phones[0][0] if phones else "",
                  "url": phones[0][1] if phones else ""}

    names, gf_hit = [], None
    for p in contact_pages:
        if p["role"] not in ("impressum", "team", "home"):
            continue
        for m in GF_LINE.finditer(p["text"]):
            for n in NAME.findall(m.group(1)):
                n = re.sub(r"^(?:Kfm\.)\s+", "", n.strip()).rstrip("-").strip()
                if not NOT_NAMES.search(n) and n not in names:
                    names.append(n)
                    gf_hit = gf_hit or (m, _quote(p["text"], m), p["url"])
        if names:
            break
    r["decision_makers"] = ev("; ".join(names[:3]) or None, gf_hit if names else None)

    hrb = find(pages, HRB, roles=("impressum",))
    r["register_number"] = ev(hrb[0].group(0) if hrb else None, hrb)
    return r
