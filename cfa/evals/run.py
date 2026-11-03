"""Evaluate the agents on a month: load the ledger, run the worker for every company, score the proposals.

evaluate(split)       seed the ledger with the split, run all companies, score, write reports/evals/<split>/<name>.json
variants              named overrides of config/agents.yaml (config/variants.yaml): the candidates gates judge
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import yaml

from .. import config
from ..agents.client import Ledger
from ..agents.pipeline import run_company
from ..ledger.app import reset_pool
from ..ledger.auth import mint
from ..ledger.seed import seed
from .score import score


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@contextmanager
def variant(name: str) -> Iterator[dict]:
    """Run with a variant's overrides applied to config/agents.yaml."""
    overrides = (
        {}
        if name == "production"
        else yaml.safe_load((config.ROOT / "config" / "variants.yaml").read_text())["variants"][name]["overrides"]
    )
    original = config.load("agents")
    merged = _merge(original, overrides)
    real_load = config.load

    def load(n: str) -> dict[str, Any]:
        return merged if n == "agents" else real_load(n)

    config.load = load  # type: ignore[assignment]
    try:
        yield merged
    finally:
        config.load = real_load  # type: ignore[assignment]


def tenants() -> list[str]:
    return [t["id"] for t in config.load("world")["tenants"]]


def evaluate(split: str, name: str = "production", use_llm: bool = True, write: bool = True) -> dict:
    month = config.load("world")["months"]["splits"][split]
    reset_pool()
    seed(split)
    reset_pool()
    t0 = time.perf_counter()
    runs, proposals, documents = [], {}, {}
    with variant(name) as agents_cfg:
        for t in tenants():
            agent = Ledger.in_process(mint("agent:worker", t, "agent"))
            r = run_company(agent, t, month, use_llm=use_llm and agents_cfg["coding"]["llm"]["enabled"])
            runs.append(r)
            admin = Ledger.in_process(mint(f"{t}-eval", t, "admin"))
            proposals[t] = admin.get("/api/proposals", limit=2000)
            documents.update({d["id"]: d for d in admin.documents(month)})
    truth = json.loads((config.DATA / split / "truth.json").read_text())
    result = score(truth, proposals, documents)
    lat = sorted(sum(s["ms"] for s in tr.get("spans", [])) for r in runs for tr in r.traces if tr.get("document"))
    result.update(
        {
            "split": split,
            "month": month,
            "agent": name,
            "operational": {
                "llm_calls": sum(r.llm_calls for r in runs),
                "cost_usd": round(sum(r.cost_usd for r in runs), 4),
                "seconds": round(time.perf_counter() - t0, 1),
                "p50_ms_per_document": lat[len(lat) // 2] if lat else None,
                "p95_ms_per_document": lat[int(len(lat) * 0.95)] if lat else None,
                "periods_by_rules": sum(r.close.periods_by_rules for r in runs if r.close),
                "periods_by_model": sum(r.close.periods_by_model for r in runs if r.close),
            },
        }
    )
    if write:
        out = config.REPORTS / "evals" / split / f"{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        traces = config.DATA / "traces" / split / f"{name}.jsonl"
        traces.parent.mkdir(parents=True, exist_ok=True)
        traces.write_text(
            "\n".join(json.dumps({"tenant": r.tenant, **tr}, ensure_ascii=False) for r in runs for tr in r.traces)
            + "\n"
        )
    return result
