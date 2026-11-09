"""Heidi Systems lead pipeline - command line entry point.

Examples
  python run.py all --limit 20          # first verified batch of 20 companies
  python run.py all                     # full run
  python run.py discover --letters ab   # only directory letters a and b
  python run.py enrich                  # resumes: skips companies already enriched
  python run.py score                   # re-score + re-export without re-crawling (e.g. after changing weights)
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import date

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

from leadpipe import DATA, OUTPUT, clean, discover, export, load_config, profiles
from leadpipe.enrich import fetch_company_pages
from leadpipe.extract_llm import LLMExtractor
from leadpipe.extract_rules import extract
from leadpipe.http import PoliteClient
from leadpipe import score as sc

ENRICHED = DATA / "04_enriched.jsonl"
STATS = OUTPUT / "run_stats.json"


def _load_stats() -> dict:
    return json.loads(STATS.read_text()) if STATS.exists() else {}


def _save_stats(s: dict):
    OUTPUT.mkdir(exist_ok=True)
    STATS.write_text(json.dumps(s, indent=2, ensure_ascii=False))


def stage_discover(cfg, client, args):
    t = time.time()
    raw = discover.run(cfg, client, args.letters)
    prof = profiles.run(raw, client, args.limit)
    kept, excl = clean.run(prof, cfg)
    s = _load_stats()
    s.update({"1 discovered (raw directory rows)": len(raw), "2 profiles read": len(prof),
              "3 unique relevant companies after cleaning": len(kept), "3b excluded (with reason)": len(excl),
              "runtime discovery (min)": round((time.time() - t) / 60, 1)})
    _save_stats(s)


def stage_enrich(cfg, client, args):
    t = time.time()
    kept = pd.read_csv(DATA / "03_clean.csv", dtype=str).fillna("")
    if args.limit:
        kept = kept.head(args.limit)
    done = set()
    if ENRICHED.exists():
        done = {json.loads(l)["profile_key"] for l in ENRICHED.open(encoding="utf-8")}
    llm = LLMExtractor(cfg)
    print(f"[enrich] LLM {'ON (' + cfg['llm']['provider'] + ')' if llm.enabled else 'OFF - rules only (no API key)'}")
    with ENRICHED.open("a", encoding="utf-8") as out:
        for r in tqdm(kept.to_dict("records"), desc="enrich websites"):
            key = r.get("profile_url") or r.get("name")
            if key in done:
                continue
            try:
                fetched = fetch_company_pages(r.get("website", ""), client, cfg["http"]["max_pages_per_company"])
                rules = extract(fetched["pages"]) if fetched["pages"] else {}
                llm_out = llm.extract(fetched["pages"])
                rec = {"profile_key": key, "company": r, "fetch_status": fetched["status"],
                       "pages": [{"role": p["role"], "url": p["url"]} for p in fetched["pages"]],
                       "rules": rules, "llm": llm_out}
            except Exception as e:  # one broken website must never stop the run
                rec = {"profile_key": key, "company": r, "fetch_status": f"error: {str(e)[:120]}",
                       "pages": [], "rules": {}, "llm": None}
            out.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            out.flush()
    s = _load_stats()
    s.update({"llm provider / model": f"{cfg['llm']['provider']} / {cfg['llm']['model']}" if llm.enabled else "not used",
              "llm calls (this run)": llm.stats["calls"], "llm cache hits (no API call needed)": llm.stats.get("cache_hits", 0), "llm valid JSON outputs": llm.stats["ok"],
              "llm claims made": llm.stats["claims"], "llm claims grounded + semantically supported": llm.stats["claims_grounded"],
              "runtime enrichment (min, this run)": round((time.time() - t) / 60, 1)})
    _save_stats(s)


def _evidence_text(f: dict) -> tuple[str, str]:
    lines, urls = [], []
    for k, label in (("units", "Units"), ("weg", "WEG"), ("miet", "Rental mgmt"), ("heating_billing", "Billing"),
                     ("metering_provider", "Metering partner"), ("older_stock", "Older stock"),
                     ("regulation_topic", "HKVO topic"), ("software", "Software"), ("portal", "Portal"),
                     ("decision_makers", "Decision maker")):
        e = f.get(k, {})
        if e.get("value") and e.get("quote"):
            lines.append(f"{label} [{e['source']}]: \"{e['quote'][:200]}\"")
            if e.get("url") and e["url"] not in urls:
                urls.append(e["url"])
    return "\n".join(lines), " | ".join(urls)


def stage_score(cfg, args):
    recs = [json.loads(l) for l in ENRICHED.open(encoding="utf-8")]
    weights, th = cfg["weights"], cfg["priority_thresholds"]
    rows, facts_for_validation = [], []
    today = date.today().isoformat()
    for rec in recs:
        c = rec["company"]
        f = sc.merge(rec.get("rules") or {}, rec.get("llm"), c)
        s = sc.score(f, weights)
        prio = "A" if s["total"] >= th["A"] else "B" if s["total"] >= th["B"] else "C"
        conf = sc.confidence(f, s, bool(rec["pages"]))
        flags = sc.review_flags(f, s, prio, conf, rec["fetch_status"], c.get("needs_review_flags", ""))
        ev_text, ev_urls = _evidence_text(f)
        types = [t for t, k in (("WEG", "weg"), ("Miet", "miet"), ("SEV", "sev"), ("Gewerbe", "gewerbe"), ("Makler", "broker")) if f[k]["value"]]
        rows.append({
            "Priority": prio, "Lead score": s["total"], "Confidence": conf, "Company": c["name"],
            "Website": c.get("website", ""), "Address": c.get("street", ""), "Postcode": c.get("postcode", ""),
            "Management types": ", ".join(types), "Units (stated)": f["units"]["value"],
            "Employees (directory)": f["employees"] or "",
            "Decision maker(s)": f["decision_makers"]["value"] or "", "LinkedIn (manual check)": "",
            "Email (direct)": f["email_personal"]["value"] or "", "Email (general)": f["email_generic"]["value"] or "",
            "Phone": f["phone"]["value"] or "", "Memberships": f["memberships"]["value"] or "",
            "Metering partner (evidenced)": f["metering_provider"]["value"] or "",
            "Software / portal": ", ".join(x for x in [f["software"]["value"] or "", "portal" if f["portal"]["value"] else ""] if x),
            **{f"KPI {k.replace('_', ' ')}": v for k, v in s["points"].items()},
            "Recommended sales angle": sc.sales_angle(f, s),
            "Why this lead?": sc.explain(c["name"], f, s, prio, conf),
            "Needs human review": "Yes" if flags else "No", "Review notes": "; ".join(flags),
            "Evidence (quotes)": ev_text, "Evidence URL": ev_urls.split(" | ")[0] if ev_urls else "",
            "All evidence URLs": ev_urls, "Directory rating": c.get("rating", ""),
            "Directory reviews": c.get("review_count", ""), "Directory profile": c.get("profile_url", ""),
            "Website fetch status": rec["fetch_status"], "Last checked": today,
        })
        for k, label in (("units", "Units managed"), ("decision_makers", "Decision maker"), ("weg", "Offers WEG"),
                         ("miet", "Offers rental mgmt"), ("heating_billing", "Mentions billing"),
                         ("email_personal", "Direct email")):
            if f[k]["value"]:
                facts_for_validation.append({"Company": c["name"], "Field": label, "Extracted value": f[k]["value"],
                                             "Evidence quote": f[k]["quote"], "Source URL": f[k]["url"],
                                             "Extracted by": f[k]["source"], "Correct? (Y/N)": "", "Note": ""})

    leads = pd.DataFrame(rows).sort_values(["Lead score", "Confidence"], ascending=[False, True]).reset_index(drop=True)
    leads.insert(0, "Rank", range(1, len(leads) + 1))
    top_cols = ["Rank", "Priority", "Lead score", "Confidence", "Company", "Website", "Management types",
                "Units (stated)", "Decision maker(s)", "LinkedIn (manual check)", "Email (direct)", "Email (general)",
                "Phone", "Recommended sales angle", "Why this lead?", "Needs human review", "Review notes", "Evidence URL"]
    top = leads[top_cols].head(cfg["top_n"])

    random.seed(42)
    k = max(10, int(len(facts_for_validation) * cfg["validation_sample_share"]))
    validation = pd.DataFrame(random.sample(facts_for_validation, min(k, len(facts_for_validation))))
    excluded = pd.read_csv(DATA / "03_excluded.csv", dtype=str).fillna("") if (DATA / "03_excluded.csv").exists() else pd.DataFrame()
    if len(excluded):
        excluded = excluded.rename(columns={"name": "Company", "exclude_reason": "Reason excluded",
                                            "postcode": "Postcode", "website": "Website"})[["Company", "Postcode", "Website", "Reason excluded"]]

    s = _load_stats()
    fetched_ok = sum(1 for r in recs if r["fetch_status"] == "ok")
    s.update({
        "4 websites processed": len(recs), "4a websites fetched successfully": fetched_ok,
        "4b website fetch success rate": f"{fetched_ok / max(1, len(recs)):.0%}",
        "5 priority A leads": int((leads["Priority"] == "A").sum()), "5 priority B leads": int((leads["Priority"] == "B").sum()),
        "5 priority C leads": int((leads["Priority"] == "C").sum()),
        "6 leads with named decision maker": int((leads["Decision maker(s)"] != "").sum()),
        "6 leads with direct email": int((leads["Email (direct)"] != "").sum()),
        "6 leads with stated unit count": int(leads["Units (stated)"].notna().sum()),
        "7 confidence High / Medium / Low": " / ".join(str(int((leads["Confidence"] == x).sum())) for x in ("High", "Medium", "Low")),
        "7 leads flagged for human review": int((leads["Needs human review"] == "Yes").sum()),
        "8 validation sample size (fields)": len(validation),
        "8 validation accuracy": "fill in after manual check (Validation tab)",
    })
    _save_stats(s)
    out = OUTPUT / f"heidi_{cfg['city'].lower()}_leads.xlsx"
    export.write(out, leads, top, excluded, s, validation, weights)
    leads.to_csv(OUTPUT / "all_leads.csv", index=False)
    print(f"[score] {len(leads)} leads scored -> {out}")


def check_llm(cfg):
    """Quick test: is the key valid, which models are available, does one JSON call work?"""
    llm = LLMExtractor(cfg)
    if not llm.key:
        print("No API key found. Put GEMINI_API_KEY=... in the .env file (same folder as run.py).")
        return
    if cfg["llm"]["provider"] == "gemini":
        try:
            names = [m.name.replace("models/", "") for m in llm.client.models.list()]
            flash = [n for n in names if "flash" in n]
            print("Available flash models:", ", ".join(sorted(flash)[:15]))
        except Exception as e:
            print("Could not list models:", str(e)[:300])
    for model in [m for m in llm.models if m != "auto"]:
        llm.model = model
        try:
            out = llm._call('Return JSON {"ok": true}')
            print(f"OK   {model}: {out.strip()[:60]}")
        except Exception as e:
            print(f"FAIL {model}: {str(e)[:250]}")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["discover", "enrich", "score", "all", "check-llm"])
    ap.add_argument("--limit", type=int, default=None, help="process only the first N companies")
    ap.add_argument("--letters", default=None, help="directory letters to crawl, e.g. 'abc'")
    args = ap.parse_args()
    cfg = load_config()
    DATA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    if args.stage == "check-llm":
        check_llm(cfg)
        return
    client = PoliteClient(cfg)
    if args.stage in ("discover", "all"):
        stage_discover(cfg, client, args)
    if args.stage in ("enrich", "all"):
        stage_enrich(cfg, client, args)
    if args.stage in ("score", "all"):
        stage_score(cfg, args)


if __name__ == "__main__":
    main()
