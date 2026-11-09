# Heidi Systems – AI-assisted lead qualification pipeline (Berlin property managers)

Case study for the **AI Agent Builder** internship at Heidi Systems.

**Question answered:** *Which Berlin property management companies (Hausverwaltungen) should Heidi's sales team contact first, and why now?*

The "why now": under **§5 Heizkostenverordnung**, non-remotely-readable heat/hot-water meters must be retrofitted or replaced by **31.12.2026**. That deadline creates market-wide urgency. The pipeline only awards points for **company-specific evidence** and never assumes that a company is non-compliant.

---

## Pipeline

```
Public sources ──► 1 Discover ──► 2 Clean & filter ──► 3 Enrich websites ──► 4 Score KPIs ──► 5 Human verification ──► Sheet
 (directory,        (scraper)      (dedupe, city,       (rules + LLM,          (lead score +     (top 25 + 10% sample)
  manual seeds)                     drop non-managers)   evidence quotes)       confidence)            ▲
                                                               ▲                                        │
                                                               └────────── fix rules ◄──────────────────┘
```

| Stage | File | What it does |
|---|---|---|
| 1 Discover | `leadpipe/discover.py`, `leadpipe/profiles.py` | Crawls a public A–Z directory of property managers, keeps Berlin postcodes, reads each profile (website, employees, founding year). Adds hand-researched seeds (`data/seeds_manual.csv`) for large managers that small directories miss. |
| 2 Clean | `leadpipe/clean.py` | Deduplicates by website domain, then by normalised name + postcode. Drops non-managers (tax advisors, facility services…). **Every dropped row keeps a reason** (`Excluded` tab). |
| 3a Fetch | `leadpipe/enrich.py` | Visits homepage + up to 5 relevant subpages (services, about, Impressum, billing, portal). |
| 3b Rules | `leadpipe/extract_rules.py` | Deterministic extraction: services (WEG / rental), unit counts, billing mentions, metering partner, software, portal, memberships, decision makers, emails, register number. Each finding stores the **exact quote + URL**. |
| 3c LLM | `leadpipe/extract_llm.py` | LLM reads the public service text and returns JSON. **Hallucination guard:** every claim needs a verbatim quote, and claims whose quote is not in the source text are discarded. |
| 4 Score | `leadpipe/score.py` | Merges evidence, scores 7 KPIs (100 points), sets a separate **confidence** rating, a **Needs human review** flag, a **Why this lead?** explanation and a **recommended sales angle**. |
| 5 Export | `leadpipe/export.py` | Google-Sheets-ready workbook: All Leads, Top 25, KPI Definitions, Method & Stats, Validation, Excluded. |

## Lead-scoring model (100 points)

| KPI | Points | Rule (only evidence counts; unknown = 0) |
|---|---|---|
| Service fit | 25 | WEG + rental management 25 · rental 22 · WEG 20 · Sondereigentum only 12 · commercial only 8 |
| Portfolio size | 20 | ≥3,000 units 20 · ≥1,000 16 · ≥300 12 · ≥100 8 · fallback: employee count as proxy |
| Billing & heating relevance | 15 | mentions heating/operating-cost billing 10 · +5 in-house billing or named metering partner |
| Regulatory opportunity | 10 | older building stock 6 · addresses HKVO / remote reading 4 · already remote-read 0 |
| Switching opportunity | 10 | relationship with a legacy provider (ista, Techem…) 10 · in-house billing 6. A logo mention alone earns nothing. |
| Digital maturity | 10 | tenant/owner portal 5 · named management software 5 |
| Reachability | 10 | decision maker 4 · direct email 3 (general 1) · phone 1 · VDIV/IVD/BVI 2 |

**Priority:** A ≥ 70 · B 50–69 · C < 50. **Confidence** (High/Medium/Low) is reported separately, so a promising company with little evidence goes to research, not straight to sales. Weights are in `config.yaml`.

## Responsible data collection
- Respects `robots.txt`, waits 1.5 s between requests per host, identifies itself with a clear user agent.
- Logs blocked or failed pages (`data/access_log.jsonl`) and **never bypasses** restrictions (no CAPTCHA solving, no login walls, no LinkedIn scraping).
- **Privacy:** Impressum pages (personal data) are processed by local rules only and are never sent to the LLM.
- Contacts are limited to legally published business information (Impressum §5 DDG). Emails are never guessed. Cold outreach in Germany must respect **§7 UWG**; this pipeline only prepares research and sends nothing.

---

## Setup

**Requirements:** Python 3.10+

```bash
# 1. get the code
cd heidi-lead-pipeline

# 2. create a virtual environment
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 3. install
pip install -r requirements.txt

# 4. optional LLM step: free Gemini key from https://aistudio.google.com/apikey
cp .env.example .env        # Windows: copy .env.example .env
# then open .env and paste the key after GEMINI_API_KEY=

# 5. test (offline, no internet needed)
python tests/test_pipeline.py
```

## Run

```bash
python run.py all --limit 20     # first verified batch of 20 companies
python run.py all                # full run (resumes where it stopped)
python run.py score              # re-score and re-export only (e.g. after changing weights)
```

Output: `output/heidi_berlin_leads.xlsx` (upload it to Google Drive and open it as a Google Sheet) and `output/run_stats.json`.

**Validation:** open the `Validation` tab, check each sampled field against its source URL, and enter Y/N. Accuracy = Y / (Y + N), reported with the sample size.

## Reuse for another city
Change `city` and `postcode_ranges` in `config.yaml` (e.g. Hamburg `[[20095, 22769]]`), add any seeds, and run again. To switch the LLM provider, set `llm.provider` to `anthropic` or `openai`, set the model, and put the matching key in `.env`.

## Limitations
- Directory coverage is incomplete. Large managers were added as manual seeds, with their source URLs.
- Unit counts are only as good as what companies publish. Third-party figures (job ads, lists) are labelled as such.
- A missing signal means "not public", not "absent". That is why confidence and review flags exist.
