"""Release gates: may this version of the agents run for customers? Decided on the test split."""

from __future__ import annotations

import json

from .. import config


def value(report: dict, metric: str) -> float | None:
    area, name = metric.split(".", 1)
    if area == "coding":
        m = report["coding"].get(name)
        return None if m is None else m["value"]
    if area == "checks":
        a = report["checks"]["all"]
        return {"recall": a["recall"], "precision": a["precision"], "decoy_false_alarms": a["decoy_false_alarms"]}[name]
    c = report["close"]
    if name == "deferral_recall":
        return c["deferral"]["recall"]
    if name == "accrual_recall":
        return c["accrual"]["recall"]
    if name == "precision":
        tp = c["deferral"]["tp"] + c["accrual"]["tp"]
        fp = c["deferral"]["fp"] + c["accrual"]["fp"]
        return tp / (tp + fp) if tp + fp else None
    if name == "cancelled_accrued":
        return c["cancelled_accrued"]
    raise KeyError(metric)


def decide(report: dict) -> dict:
    checks = []
    for metric, lim in config.load("gates")["gates"].items():
        v = value(report, metric)
        if v is None:
            status = "n/a"
        elif "min" in lim:
            status = "pass" if v >= lim["min"] else "fail"
        else:
            status = "pass" if v <= lim["max"] else "fail"
        checks.append({"metric": metric, "value": v, "limit": lim, "status": status})
    failed = [c["metric"] for c in checks if c["status"] == "fail"]
    return {"agent": report["agent"], "split": report["split"], "ship": not failed, "failed": failed, "checks": checks}


def render(d: dict, report: dict) -> str:
    lines = [
        f"# Release decision: {d['agent']}",
        "",
        f"On the `{d['split']}` split ({report['documents']} documents). "
        f"**{'Ship' if d['ship'] else 'Do not ship'}.**"
        + (f" Failed: {', '.join(d['failed'])}." if d["failed"] else ""),
        "",
        "| Gate | Value | Limit | Result |",
        "|---|---|---|---|",
    ]
    for c in d["checks"]:
        v = "–" if c["value"] is None else (f"{c['value']:.3f}" if isinstance(c["value"], float) else str(c["value"]))
        lim = f"≥ {c['limit']['min']}" if "min" in c["limit"] else f"≤ {c['limit']['max']}"
        lines.append(f"| {c['metric']} | {v} | {lim} | {c['status']} |")
    op = report["operational"]
    lines += [
        "",
        f"Model calls {op['llm_calls']}, cost ${op['cost_usd']:.4f}, p95 {op['p95_ms_per_document']:.0f} ms per document.",
        "",
    ]
    return "\n".join(lines)


def write(d: dict, report: dict) -> None:
    folder = config.REPORTS / "releases"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{d['agent']}.json").write_text(json.dumps(d, indent=1))
    (folder / f"{d['agent']}.md").write_text(render(d, report))
