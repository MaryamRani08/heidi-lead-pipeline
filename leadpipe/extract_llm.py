"""Stage 3c - LLM extraction with a hallucination guard.

The LLM reads public service/about text (never the Impressum - personal data stays with the rules)
and returns JSON. Every claim must come with a verbatim quote; claims whose quote is NOT found in the
source text are discarded. Provider is swappable: gemini | anthropic | openai.
"""

from __future__ import annotations

import json
import os
import re
import time

PROMPT = """You analyse the website text of a German property management company (Hausverwaltung).
Extract ONLY facts that are explicitly supported by the text. Never guess. Use null when unknown.
For every non-null field, copy a short VERBATIM quote (max 25 words, exact characters from the text) as evidence.

Return JSON with exactly these keys:
{
 "is_property_manager": {"value": true|false|null, "quote": str|null},
 "management_types": {"value": [subset of "WEG","Mietverwaltung","Sondereigentum","Gewerbe","Makler"], "quote": str|null},
 "units_managed": {"value": integer|null, "quote": str|null},
 "handles_heating_cost_billing": {"value": true|false|null, "quote": str|null},
 "metering_provider": {"value": str|null, "quote": str|null},
 "remote_reading_status": {"value": "already_remote"|"in_progress"|null, "quote": str|null},
 "older_building_stock": {"value": true|null, "quote": str|null},
 "software_or_portal": {"value": str|null, "quote": str|null},
 "summary_en": "one neutral English sentence describing what the company does"
}

Website text:
---
{text}
---"""


def _norm(s: str) -> str:
    s = s.lower().replace("„", '"').replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"[^a-z0-9äöüß%]+", " ", s).strip()


# a quote must not only exist in the page, it must also be ABOUT the field (semantic check)
FIELD_KEYWORDS = {
    "units_managed": None,  # special: quote must contain the number
    "older_building_stock": re.compile(r"altbau|gründerzeit|baujahr|bestandsgeb|bestandsimmob|historisch|denkmal|jahrhundert|plattenbau|vorkrieg", re.I),
    "handles_heating_cost_billing": re.compile(r"abrechnung|heizkost|betriebskost|nebenkost|verbrauch", re.I),
    "metering_provider": None,  # special: quote must contain the provider name
    "remote_reading_status": re.compile(r"fernables|funk|remote|smart", re.I),
    "management_types": re.compile(r"verwalt|weg|miet|sondereigentum|gewerbe|makler|verkauf|vermiet", re.I),
}


def quote_supports(field: str, value, quote: str) -> bool:
    q = quote or ""
    if field == "units_managed":
        digits = re.sub(r"\D", "", q)
        return str(value) in digits or f"{value:,}".replace(",", ".") in q if isinstance(value, int) else False
    if field == "metering_provider":
        return str(value).lower()[:4] in q.lower()
    pat = FIELD_KEYWORDS.get(field)
    return True if pat is None else bool(pat.search(q))


def quote_is_grounded(quote: str | None, source: str) -> bool:
    if not quote:
        return False
    q = _norm(quote)
    return len(q) >= 6 and q in _norm(source)


class LLMExtractor:
    def __init__(self, cfg: dict):
        c = cfg["llm"]
        self.provider = c["provider"]
        self.models = [c["model"]] + list(c.get("fallback_models", []))
        self.model = self.models[0]
        self.first_error_shown = False
        self.max_chars = c["max_input_chars"]
        self.min_gap = 60.0 / max(1, c["requests_per_minute"])
        self.send_impressum = c.get("send_impressum_to_llm", False)
        self._last = 0.0
        self.client = None
        self.stats = {"calls": 0, "ok": 0, "failed": 0, "claims": 0, "claims_grounded": 0}
        key_env = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[self.provider]
        self.key = os.getenv(key_env)
        self.enabled = bool(c["enabled"] and self.key)
        if self.enabled:
            self._init_client()

    def _init_client(self):
        if self.provider == "gemini":
            from google import genai
            # 45 s timeout per request: a busy model should fail fast, not hang
            self.client = genai.Client(api_key=self.key, http_options={"timeout": 45_000})
        elif self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.key)
        elif self.provider == "openai":
            import openai
            self.client = openai.OpenAI(api_key=self.key)

    def _discover_models(self) -> list[str]:
        """Ask the API which text 'flash' models exist (newest first). Gemini only."""
        if self.provider != "gemini":
            return []
        try:
            names = [m.name.replace("models/", "") for m in self.client.models.list()]
        except Exception:
            return []
        bad = ("image", "tts", "audio", "live", "embedding", "thinking", "exp", "computer")
        flash = [n for n in names if "flash" in n and not any(b in n for b in bad)]
        return sorted(flash, reverse=True)

    def _next_model(self) -> bool:
        """Advance to the next model; expands 'auto' into the API's model list."""
        i = self.models.index(self.model)
        rest = self.models[i + 1:]
        if rest and rest[0] == "auto":
            found = [m for m in self._discover_models() if m not in self.models]
            self.models = self.models[: i + 1] + found
            rest = found
        if rest:
            self.model = rest[0]
            print(f"[llm] switching to model {self.model}")
            return True
        return False

    def _call(self, prompt: str) -> str:
        wait = self.min_gap - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        if self.provider == "gemini":
            r = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 0})
            return r.text
        if self.provider == "anthropic":
            r = self.client.messages.create(model=self.model, max_tokens=1200, temperature=0,
                                            messages=[{"role": "user", "content": prompt + "\nRespond with JSON only."}])
            return r.content[0].text
        r = self.client.chat.completions.create(model=self.model, temperature=0,
                                                response_format={"type": "json_object"},
                                                messages=[{"role": "user", "content": prompt}])
        return r.choices[0].message.content

    def extract(self, pages: list[dict]) -> dict | None:
        if not self.enabled or not pages:
            return None
        usable = [p for p in pages if self.send_impressum or p["role"] != "impressum"]
        source = "\n\n".join(f"[{p['role']}] {p['text']}" for p in usable)[: self.max_chars]
        if len(source) < 200:
            return None
        import hashlib
        from . import CACHE
        cache_file = CACHE / ("llm_" + hashlib.sha1(source.encode()).hexdigest() + ".json")
        data = None
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            self.stats["cache_hits"] = self.stats.get("cache_hits", 0) + 1
        else:
            self.stats["calls"] += 1
        for attempt in range(0 if data is not None else 3):
            try:
                raw = self._call(PROMPT.replace("{text}", source))
                data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M))
                break
            except Exception as e:
                msg = str(e)
                if not self.first_error_shown:
                    print(f"\n[llm] {self.model} error: {msg[:300]}")
                    self.first_error_shown = True
                fatal = any(t in msg for t in ("API_KEY_INVALID", "PERMISSION_DENIED", "API key not valid"))
                model_gone = ("NOT_FOUND" in msg or "404" in msg or "not found" in msg.lower()
                              or "PerDay" in msg or "per day" in msg.lower()
                              or "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower()
                              or "DEADLINE" in msg or "timed out" in msg.lower())
                if fatal:
                    print("[llm] API key problem -> continuing with rules only")
                    self.enabled = False
                    break
                if model_gone:  # unknown model or daily quota used up -> next model, else rules only
                    if self._next_model():
                        continue
                    print("[llm] no model left with quota -> continuing with rules only")
                    self.enabled = False
                    break
                if isinstance(e, json.JSONDecodeError) or attempt == 2:
                    if attempt == 2:
                        break
                    continue
                time.sleep(15 * (attempt + 1))  # per-minute rate limit -> short back-off
        if data is None:
            self.stats["failed"] += 1
            return {"_error": "llm call failed (see terminal)"}
        if not cache_file.exists():
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.stats["ok"] += 1
        # hallucination guard: keep only claims whose quote exists in the source text
        out = {"summary_en": data.get("summary_en")}
        for k, v in data.items():
            if k == "summary_en" or not isinstance(v, dict):
                continue
            if v.get("value") in (None, [], ""):
                out[k] = {"value": None, "quote": "", "grounded": False}
                continue
            self.stats["claims"] += 1
            g = quote_is_grounded(v.get("quote"), source) and quote_supports(k, v["value"], v.get("quote"))
            self.stats["claims_grounded"] += int(g)
            out[k] = {"value": v["value"] if g else None, "quote": v.get("quote") or "", "grounded": g,
                      "rejected_value": None if g else v["value"]}
        out["_source_urls"] = [p["url"] for p in usable]
        return out
