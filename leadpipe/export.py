"""Stage 6 - Export the Google-Sheets-ready workbook: All Leads, Top 25, KPI Definitions, Method & Stats, Excluded, Validation."""

from __future__ import annotations

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

KPI_DEFS = [
    ("Service fit", "service_fit", 25, "Does the company manage residential rental properties (Mietverwaltung) and/or owner associations (WEG)?",
     "Heidi bills per residential unit with central heating; pure brokers or commercial-only managers are weak fits.",
     "WEG+Miet 25 · Miet 22 · WEG 20 · SEV only 12 · unspecified management 10 · commercial only 8 · none 0"),
    ("Portfolio size", "portfolio_size", 20, "Number of managed units stated on the website (fallback: employee count from directory as proxy).",
     "More units = more meters and recurring revenue per contract; one decision unlocks many buildings.",
     "≥3,000: 20 · ≥1,000: 16 · ≥300: 12 · ≥100: 8 · <100: 4 · proxy ≥50 staff: 12 · ≥20: 8 · ≥5: 4"),
    ("Billing & heating relevance", "billing_relevance", 15, "Website mentions heating/operating-cost billing (Heiz-/Betriebskostenabrechnung).",
     "These managers own the billing process Heidi automates.",
     "mention 10 · +5 if in-house billing or a named metering partner"),
    ("Regulatory opportunity", "regulatory_opportunity", 10, "Company-specific signals linked to the HKVO §5 retrofit deadline (31.12.2026).",
     "The deadline creates urgency market-wide; points only for company evidence (older stock, HKVO topic). Never assumes non-compliance.",
     "older building stock 6 · addresses HKVO/remote reading 4 · states already remote-read: 0"),
    ("Switching opportunity", "switching_opportunity", 10, "Evidence of a relationship with a legacy metering provider, or in-house billing.",
     "A named incumbent (ista, Techem, …) is a concrete switch conversation; a mere logo mention earns nothing.",
     "provider relationship 10 · in-house billing 6"),
    ("Digital maturity", "digital_maturity", 10, "Tenant/owner portal or named management software (ERP).",
     "Heidi's dashboard integrates with management software; digital managers adopt faster.",
     "portal 5 · named software 5"),
    ("Reachability", "reachability", 10, "Named decision maker, direct email, phone, association membership.",
     "A sales team needs a person to call; VDIV members are reachable through Heidi's VDIV partnership.",
     "decision maker 4 · direct email 3 (general 1) · phone 1 · VDIV/IVD/BVI 2"),
]

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
PRIO_FILL = {"A": PatternFill("solid", fgColor="C6EFCE"), "B": PatternFill("solid", fgColor="FFEB9C"),
             "C": PatternFill("solid", fgColor="F2F2F2")}


def _format_sheet(ws, widths: dict[str, int] | None = None, wrap_cols: tuple[str, ...] = ()):
    headers = [c.value for c in ws[1]]
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "B2" if ws.max_column > 3 else "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, h in enumerate(headers, 1):
        col = get_column_letter(i)
        ws.column_dimensions[col].width = (widths or {}).get(h, min(45, max(10, len(str(h)) + 2)))
        if h in wrap_cols:
            for cell in ws[col][1:]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        if h in ("Website", "Evidence URL", "Source URL", "Directory profile"):
            for cell in ws[col][1:]:
                if cell.value and str(cell.value).startswith("http"):
                    cell.hyperlink = str(cell.value)
                    cell.font = Font(color="0563C1", underline="single")
    if "Priority" in headers:
        pc = headers.index("Priority") + 1
        for row in ws.iter_rows(min_row=2):
            fill = PRIO_FILL.get(row[pc - 1].value)
            if fill:
                row[pc - 1].fill = fill


def write(path, leads: pd.DataFrame, top: pd.DataFrame, excluded: pd.DataFrame, stats: dict,
          validation: pd.DataFrame, weights: dict):
    kpi = pd.DataFrame([{"KPI": n, "Max points": weights[k], "What we measure": m, "Why it matters for Heidi": w,
                         "Scoring rule": r} for n, k, _, m, w, r in KPI_DEFS])
    kpi.loc[len(kpi)] = {"KPI": "Confidence (separate from score)", "Max points": "",
                         "What we measure": "How many KPIs are backed by evidence quotes.",
                         "Why it matters for Heidi": "A promising lead with little evidence goes to research, not straight to sales.",
                         "Scoring rule": "High ≥5 evidenced · Medium 3–4 · Low ≤2 or website unreachable"}
    kpi.loc[len(kpi)] = {"KPI": "Priority", "Max points": "", "What we measure": "Lead score bands.",
                         "Why it matters for Heidi": "Tells sales who to call first.",
                         "Scoring rule": "A ≥70 · B 50–69 · C <50"}
    st = pd.DataFrame([{"Metric": k, "Value": v} for k, v in stats.items()])

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        leads.to_excel(xw, sheet_name="All Leads", index=False)
        top.to_excel(xw, sheet_name="Top 25", index=False)
        kpi.to_excel(xw, sheet_name="KPI Definitions", index=False)
        st.to_excel(xw, sheet_name="Method & Stats", index=False)
        validation.to_excel(xw, sheet_name="Validation", index=False)
        excluded.to_excel(xw, sheet_name="Excluded", index=False)

    wb = load_workbook(path)
    wide = {"Company": 34, "Why this lead?": 70, "Recommended sales angle": 42, "Evidence (quotes)": 80,
            "Needs human review": 14, "Review notes": 40, "Website": 30, "Decision maker(s)": 28,
            "What we measure": 50, "Why it matters for Heidi": 60, "Scoring rule": 55, "Metric": 45, "Value": 60,
            "Evidence quote": 70, "Extracted value": 30, "Source URL": 40, "Reason excluded": 45}
    for ws in wb.worksheets:
        _format_sheet(ws, wide, wrap_cols=("Why this lead?", "Evidence (quotes)", "What we measure",
                                           "Why it matters for Heidi", "Scoring rule", "Evidence quote", "Review notes"))
    wb.save(path)
