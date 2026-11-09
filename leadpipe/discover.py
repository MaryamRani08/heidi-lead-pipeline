"""Stage 1 - Discovery: collect candidate companies from public directories + manual seeds."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

from . import DATA, ROOT, in_city
from .http import PoliteClient

PLZ_CITY = re.compile(r"\b(\d{5})\s+([A-ZÄÖÜ][\wäöüß .()\-/]+)")
PROFILE_HREF = re.compile(r"/hausverwaltung/[a-z0-9\-]+$")
STREET = re.compile(r"([A-ZÄÖÜa-zäöüß][\wäöüß.\- ]{2,60}?\s\d+[a-zA-Z]?(?:\s?[-/]\s?\d+[a-zA-Z]?)?)\s*,?\s*\d{5}")


def _parse_directory_page(html: str, page_url: str) -> list[dict]:
    """Find every profile link and read the postcode/address from the surrounding block."""
    soup = BeautifulSoup(html, "html.parser")
    rows, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"]).split("?")[0].split("#")[0]
        if not PROFILE_HREF.search(urlparse(href).path) or href in seen:
            continue
        name = a.get_text(" ", strip=True).rstrip(" >").strip()
        if not name or len(name) < 2:
            continue
        # walk up until the container text includes a postcode
        block, text = a, ""
        for _ in range(5):
            block = block.parent
            if block is None:
                break
            text = block.get_text(" ", strip=True)
            if PLZ_CITY.search(text):
                break
        m = PLZ_CITY.search(text or "")
        if not m:
            continue
        # if the container holds several entries, cut text after this entry's name
        idx = text.find(name)
        local = text[idx: idx + 250] if idx >= 0 else text
        m = PLZ_CITY.search(local) or m
        s = STREET.search(local)
        seen.add(href)
        rows.append({
            "name": name,
            "street": s.group(1).strip() if s else "",
            "postcode": m.group(1),
            "city": m.group(2).strip().split(" -")[0].strip(),
            "profile_url": href,
            "source": "jacasa_directory",
            "source_url": page_url,
        })
    return rows


def discover_jacasa(cfg: dict, client: PoliteClient, letters: str | None = None) -> list[dict]:
    src = cfg["sources"]["jacasa_directory"]
    letters = letters or src["letters"]
    out: list[dict] = []
    for letter in tqdm(letters, desc="directory letters"):
        prev_first = None
        for page in range(1, src["max_pages_per_letter"] + 1):
            url = src["base_url"].format(letter=letter, page=page)
            html = client.get(url)
            if not html:
                break
            rows = _parse_directory_page(html, url)
            if not rows or rows[0]["profile_url"] == prev_first:
                break  # empty page or the site repeated the last page
            prev_first = rows[0]["profile_url"]
            out.extend(r for r in rows if in_city(r["postcode"], cfg))
    return out


def load_manual_seeds(cfg: dict) -> list[dict]:
    p = ROOT / cfg["sources"]["manual_seeds"]["path"]
    if not p.exists():
        return []
    df = pd.read_csv(p, dtype=str).fillna("")
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "name": r.get("name", ""), "street": r.get("street", ""),
            "postcode": r.get("postcode", ""), "city": cfg["city"],
            "profile_url": r.get("profile_url", ""), "website": r.get("website", ""),
            "source": "manual_seed", "source_url": r.get("source_url", ""),
            "units_hint": r.get("units_hint", ""), "units_hint_quote": r.get("units_hint_quote", ""),
        })
    return rows


def run(cfg: dict, client: PoliteClient, letters: str | None = None) -> pd.DataFrame:
    rows = []
    # manual seeds first, so deduplication keeps their extra evidence (e.g. unit counts from job ads)
    if cfg["sources"]["manual_seeds"]["enabled"]:
        rows += load_manual_seeds(cfg)
    if cfg["sources"]["jacasa_directory"]["enabled"]:
        rows += discover_jacasa(cfg, client, letters)
    df = pd.DataFrame(rows)
    df.to_csv(DATA / "01_discovered.csv", index=False)
    print(f"[discover] {len(df)} candidate rows in {cfg['city']}")
    return df
