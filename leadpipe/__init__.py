"""Heidi Systems lead pipeline: discover, enrich, score and export property-management leads."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
CACHE = DATA / "cache"


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def in_city(postcode: str | None, cfg: dict) -> bool:
    if not postcode or not str(postcode).isdigit():
        return False
    p = int(postcode)
    return any(lo <= p <= hi for lo, hi in cfg["postcode_ranges"])
