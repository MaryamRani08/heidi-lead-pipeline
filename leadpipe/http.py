"""Polite HTTP client: robots.txt, per-host rate limit, retries, disk cache and an access log."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from . import CACHE, DATA


class PoliteClient:
    def __init__(self, cfg: dict):
        h = cfg["http"]
        self.ua = h["user_agent"]
        self.delay = h["delay_seconds"]
        self.timeout = h["timeout_seconds"]
        self.retries = h["max_retries"]
        self.respect_robots = h["respect_robots_txt"]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Accept-Language": "de-DE,de;q=0.9"})
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        CACHE.mkdir(parents=True, exist_ok=True)
        self.log_path = DATA / "access_log.jsonl"

    # ---------- helpers ----------
    def _log(self, url: str, status: str, detail: str = "") -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "url": url, "status": status, "detail": detail[:200],
            }) + "\n")

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=self.timeout)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # no robots.txt -> allowed
            except requests.RequestException:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.ua, url)

    def _wait(self, host: str) -> None:
        last = self._last_hit.get(host, 0)
        gap = time.time() - last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last_hit[host] = time.time()

    @staticmethod
    def _cache_file(url: str):
        return CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    # ---------- public ----------
    def get(self, url: str, use_cache: bool = True) -> str | None:
        """Return page HTML, or None if blocked / failed. Never bypasses access restrictions."""
        cf = self._cache_file(url)
        if use_cache and cf.exists():
            return cf.read_text(encoding="utf-8", errors="ignore")
        if not self._allowed(url):
            self._log(url, "blocked_by_robots")
            return None
        host = urlparse(url).netloc
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as e:
                self._log(url, "error", str(e))
                continue
            if r.status_code == 200 and "html" in r.headers.get("Content-Type", "html"):
                r.encoding = r.apparent_encoding or r.encoding
                cf.write_text(r.text, encoding="utf-8")
                self._log(url, "ok")
                return r.text
            if r.status_code in (401, 403, 429):
                # access restricted or rate limited: log and stop, do not try to get around it
                self._log(url, f"http_{r.status_code}")
                if r.status_code == 429 and attempt < self.retries:
                    time.sleep(30)
                    continue
                return None
            self._log(url, f"http_{r.status_code}")
            if r.status_code == 404:
                return None
        return None
