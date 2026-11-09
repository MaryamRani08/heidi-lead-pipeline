"""Stage 1b - Directory profiles: read website, employees, founding year and rating from each profile page."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

from . import DATA
from .http import PoliteClient

NOT_COMPANY_SITES = (
    "jacasa.", "google.", "facebook.", "instagram.", "linkedin.", "xing.", "twitter.", "x.com",
    "youtube.", "immobilienscout24.", "immowelt.", "yelp.", "trustpilot.", "provenexpert.",
    "apple.com", "goo.gl", "wa.me", "whatsapp.", "gstatic.", "googletagmanager.", "cookiebot.",
)
EMPLOYEES = re.compile(r"(?:ca\.\s*)?(\d{1,4})\s*\+?\s*(?:Mitarbeiter|Beschäftigte|Angestellte)", re.I)
EMPLOYEES_ALT = re.compile(r"Mitarbeiter(?:anzahl|innen)?\s*:?\s*(?:ca\.\s*)?(\d{1,4})\+?", re.I)
FOUNDED = re.compile(r"(?:seit|gegründet|Gründung(?:sjahr)?)\s*:?\s*(?:im Jahr\s*)?(1[89]\d{2}|20[0-2]\d)", re.I)
REVIEWS = re.compile(r"(\d{1,5})\s*Bewertungen")
RATING = re.compile(r"\b([1-5][,.]\d)\b")
MEMBERSHIP = re.compile(r"(?:Mitglied(?:schaft(?:en)?)?|Mitglied im|member)[^.]{0,80}?\b(VDIV|IVD|BVI|DDIV)\b|(Verband der Immobilienverwalter)", re.I)


def _website(soup: BeautifulSoup) -> str:
    # prefer an explicitly labelled website link
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True).lower()
        href = a["href"]
        if href.startswith("http") and ("webseite" in label or "website" in label or "homepage" in label):
            if not any(b in href for b in NOT_COMPANY_SITES):
                return href
    return ""


# profile pages end with "other companies near you" blocks; their numbers must not leak into this company
SIDEBAR = re.compile(r"Weitere Hausverwaltungen|Weitere Immobilienmakler|Das haben sich andere|Die besten Hausverwaltungen in der Nähe|Hausverwaltungen in Ihrer Nähe")


def parse_profile(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    full = text
    cut = SIDEBAR.search(text)
    if cut:
        text = text[: cut.start()]
    near = re.search(r"Weitere Hausverwaltungen|Weitere Immobilienmakler|Hausverwaltungen in Ihrer Nähe", full)
    member_text = full[: near.start()] if near else full
    emp = EMPLOYEES_ALT.search(text) or EMPLOYEES.search(text)
    founded = FOUNDED.search(text)
    reviews = REVIEWS.search(text)
    # rating: first x,y number near the reviews count
    rating = None
    if reviews:
        window = text[max(0, reviews.start() - 120): reviews.start()]
        rr = RATING.findall(window)
        rating = rr[-1].replace(",", ".") if rr else None
    return {
        "website": _website(soup),
        "employees": int(emp.group(1)) if emp else None,
        "founded": int(founded.group(1)) if founded else None,
        "review_count": int(reviews.group(1)) if reviews else None,
        "rating": float(rating) if rating else None,
        "directory_memberships": ",".join(sorted({(a or "VDIV").upper().replace("DDIV", "VDIV") for a, b in MEMBERSHIP.findall(member_text)})) or "",
    }


def run(df: pd.DataFrame, client: PoliteClient, limit: int | None = None) -> pd.DataFrame:
    df = df.copy().fillna("").astype(str)
    if limit:
        df = df.head(limit)
    records = []
    for r in tqdm(df.to_dict("records"), desc="directory profiles"):
        info = {"website": r.get("website", "") or ""}
        if r.get("profile_url"):
            html = client.get(r["profile_url"])
            if html:
                parsed = parse_profile(html)
                parsed["website"] = info["website"] or parsed["website"]
                info = parsed
        records.append({**r, **info})
    out = pd.DataFrame(records)
    out["domain"] = out["website"].fillna("").map(
        lambda u: urlparse(u).netloc.lower().removeprefix("www.") if u else "")
    out.to_csv(DATA / "02_profiles.csv", index=False)
    print(f"[profiles] {len(out)} profiles, {int((out['domain'] != '').sum())} with website")
    return out
