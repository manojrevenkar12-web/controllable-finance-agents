"""Settings live in config/*.yaml; code reads them here."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"


@cache
def load(name: str) -> dict[str, Any]:
    with open(ROOT / "config" / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
