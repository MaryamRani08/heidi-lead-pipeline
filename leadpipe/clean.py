"""Stage 2 - Clean & filter: deduplicate, keep city postcodes, drop non-property-managers. Every drop keeps a reason."""

from __future__ import annotations

import re

import pandas as pd

from . import DATA, in_city

LEGAL_FORMS = re.compile(r"\b(gmbh|mbh|co\.?|kg|ag|ug|e\.?\s?k\.?|ohg|gbr|& ?co|haftungsbeschränkt)\b", re.I)
MANAGER_WORDS = re.compile(r"verwalt|management|immobilien|grundst|wohn|haus|property|real estate|liegenschaft|treuhand|estate", re.I)
EXCLUDE_WORDS = re.compile(r"steuerberat|rechtsanw|bautenschutz|facility|reinigung|hausmeister|construction|architekt", re.I)


def norm_name(name: str) -> str:
    n = LEGAL_FORMS.sub(" ", str(name).lower())
    n = re.sub(r"[^a-z0-9äöüß ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def run(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["name_norm"] = df["name"].map(norm_name)
    df["exclude_reason"] = ""

    is_seed = df["source"].astype(str).eq("manual_seed") if "source" in df.columns else pd.Series(False, index=df.index)
    outside = ~df["postcode"].astype(str).str.replace(r"\.0$", "", regex=True).map(lambda p: in_city(p, cfg))
    df.loc[outside & ~is_seed, "exclude_reason"] = "outside city postcodes"
    df.loc[(df["exclude_reason"] == "") & df["name"].str.contains(EXCLUDE_WORDS), "exclude_reason"] = \
        "not a property manager (name: tax/legal/facility/construction)"
    df.loc[(df["exclude_reason"] == "") & ~df["name"].str.contains(MANAGER_WORDS), "exclude_reason"] = \
        "unclear business type (kept for manual check)"

    # duplicates: same website domain, then same normalised name + postcode
    keep = df["exclude_reason"].isin(["", "unclear business type (kept for manual check)"])
    dom = df["domain"].fillna("")
    dup_dom = keep & (dom != "") & dom.duplicated(keep="first")
    df.loc[dup_dom, "exclude_reason"] = "duplicate (same website)"
    keep = df["exclude_reason"].isin(["", "unclear business type (kept for manual check)"])
    dup_name = keep & df.duplicated(subset=["name_norm", "postcode"], keep="first")
    df.loc[dup_name, "exclude_reason"] = "duplicate (same name + postcode)"

    unclear = df["exclude_reason"] == "unclear business type (kept for manual check)"
    df.loc[unclear, "exclude_reason"] = ""
    df["needs_review_flags"] = ""
    df.loc[unclear, "needs_review_flags"] = "unclear business type from name"

    kept = df[df["exclude_reason"] == ""].drop(columns=["exclude_reason"]).reset_index(drop=True)
    excluded = df[df["exclude_reason"] != ""].reset_index(drop=True)
    kept.to_csv(DATA / "03_clean.csv", index=False)
    excluded.to_csv(DATA / "03_excluded.csv", index=False)
    print(f"[clean] kept {len(kept)}, excluded {len(excluded)}")
    return kept, excluded
