"""Call Claude headless through the Claude Code CLI, in a folder holding only the given files, with caching.

The model gets the Read tool and nothing else, a system prompt, a JSON schema for its answer and a spending
cap. Answers are cached under a key of everything that can change them (model, prompts, schema, files), so a
rerun replays exactly what the model said. With ``CFA_LLM=off`` a cache miss raises instead of calling.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import config

CACHE = config.ROOT / "fixtures" / "llm_cache"  # committed: CI replays model answers without calling


class CacheMiss(RuntimeError):
    pass


def cache_key(model: str, system: str, user: str, schema: dict, files: list[Path]) -> str:
    h = hashlib.sha256()
    for part in (model, system, user, json.dumps(schema, sort_keys=True)):
        h.update(part.encode())
        h.update(b"\0")
    for f in sorted(files):
        h.update(f.name.encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:24]


def ask(
    model: str, system: str, user: str, schema: dict, files: list[Path], budget_usd: float = 1.0, timeout_s: int = 600
) -> tuple[dict, str, bool]:
    """Return (raw CLI result, cache key, replayed)."""
    key = cache_key(model, system, user, schema, files)
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text()), key, True
    if os.environ.get("CFA_LLM", "on") == "off":
        raise CacheMiss(f"no cached answer ({key}) and CFA_LLM=off")
    with tempfile.TemporaryDirectory(prefix="cfa-claude-") as tmp:
        for f in files:
            shutil.copy(f, Path(tmp) / f.name)
        cmd = [
            "claude",
            "-p",
            user,
            "--model",
            model,
            "--output-format",
            "json",
            "--system-prompt",
            system,
            "--tools",
            "Read",
            "--allowedTools",
            "Read",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--json-schema",
            json.dumps(schema),
            "--max-budget-usd",
            str(budget_usd),
        ]
        p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=timeout_s)
        if p.returncode != 0 and not p.stdout.strip():
            raise RuntimeError(f"claude exited {p.returncode}: {p.stderr[-500:]}")
        raw = json.loads(p.stdout)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(raw, ensure_ascii=False))
    return raw, key, False


def usage(raw: dict) -> dict:
    u = raw.get("usage", {})
    return {
        "input_tokens": int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)),
        "output_tokens": int(u.get("output_tokens", 0)),
        "cache_read_tokens": int(u.get("cache_read_input_tokens", 0)),
        "cost_usd": float(raw.get("total_cost_usd", 0.0)),
        "duration_ms": float(raw.get("duration_ms", 0.0)),
        "turns": int(raw.get("num_turns", 0)),
    }


def failed(raw: dict) -> str | None:
    if raw.get("subtype", "success") == "success" and not raw.get("is_error"):
        return None
    return str(raw.get("subtype") or raw.get("result"))[:300]
