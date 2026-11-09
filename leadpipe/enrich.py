"""Stage 3a - Fetch each company website: homepage + the most relevant subpages (services, about, impressum)."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .http import PoliteClient

# subpages we want, in priority order; the key becomes the page "role"
PAGE_PATTERNS = [
    ("impressum", re.compile(r"impressum|imprint|legal-notice|anbieterkennzeichnung", re.I)),
    ("services", re.compile(r"leistung|service|verwaltung|weg-|mietverwaltung|angebot|portfolio", re.I)),
    ("about", re.compile(r"ueber-uns|uber-uns|über|about|unternehmen|wir|philosophie|historie", re.I)),
    ("team", re.compile(r"team|ansprechpartner|mitarbeiter|kontakt|contact", re.I)),
    ("billing", re.compile(r"heizkosten|betriebskosten|nebenkosten|abrechnung|messdienst|verbrauch", re.I)),
    ("portal", re.compile(r"portal|app|login|mieterservice|eigentuemerservice|kundenbereich", re.I)),
]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)


def _candidate_links(html: str, base_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc.removeprefix("www.")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        p = urlparse(href)
        if p.scheme not in ("http", "https") or p.netloc.removeprefix("www.") != host:
            continue
        if re.search(r"\.(pdf|jpg|png|zip|docx?)$", p.path, re.I):
            continue
        hay = (p.path + " " + a.get_text(" ", strip=True)).lower()
        for role, pat in PAGE_PATTERNS:
            if role not in found and pat.search(hay):
                found[role] = href
                break
    return found


def fetch_company_pages(website: str, client: PoliteClient, max_pages: int = 6) -> dict:
    """Returns {"pages": [{"role","url","text"}], "status": str}."""
    if not website:
        return {"pages": [], "status": "no_website"}
    if not website.startswith("http"):
        website = "https://" + website
    home = client.get(website)
    if home is None and website.startswith("https://"):
        home = client.get("http://" + website[8:])
    if home is None:
        return {"pages": [], "status": "website_unreachable_or_blocked"}
    pages = [{"role": "home", "url": website, "text": html_to_text(home)}]
    for role, url in list(_candidate_links(home, website).items())[: max_pages - 1]:
        html = client.get(url)
        if html:
            pages.append({"role": role, "url": url, "text": html_to_text(html)})
    return {"pages": pages, "status": "ok"}
