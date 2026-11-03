"""cfa: build the simulated companies, run the ledger and the agents, evaluate, calibrate, decide releases.

cfa build                         simulated companies, history, evaluation months and truth (data/)
cfa migrate [--down]              apply or roll back the ledger schema
cfa seed <split>                  load a split into the ledger (dev database)
cfa serve [--port 8090]           the ledger API (and the console, if built)
cfa mcp --token <jwt>             the MCP tool server, acting as the token's holder (stdio)
cfa run <split> [--no-llm]        run the agent worker for every company on the split's month
cfa eval <split> [--variant v]    seed, run and score; writes reports/evals/<split>/<variant>.json
cfa calibrate                     choose the bulk-approval threshold on dev; writes config/thresholds.yaml
cfa release <variant>             evaluate on test and apply the gates; writes reports/releases/
cfa heldout <set>                 run a blind case set (first run kept)
"""

from __future__ import annotations

import argparse
import json
import sys

from . import config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cfa", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    m = sub.add_parser("migrate")
    m.add_argument("--down", action="store_true")
    s = sub.add_parser("seed")
    s.add_argument("split")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8090)
    sv.add_argument("--host", default="127.0.0.1")
    mc = sub.add_parser("mcp")
    mc.add_argument("--token", required=True)
    mc.add_argument("--base-url", default="http://127.0.0.1:8090")
    r = sub.add_parser("run")
    r.add_argument("month", help="a split (dev, test, heldout), YYYY-MM, or 'current'")
    r.add_argument("--no-llm", action="store_true")
    r.add_argument("--ledger-url", help="call the ledger over HTTP instead of in-process")
    pb = sub.add_parser("publish")
    pb.add_argument("--once", action="store_true")
    e = sub.add_parser("eval")
    e.add_argument("split")
    e.add_argument("--variant", default="production")
    e.add_argument("--no-llm", action="store_true")
    sub.add_parser("calibrate")
    rl = sub.add_parser("release")
    rl.add_argument("variant", nargs="?", default="production")
    rl.add_argument("--no-llm", action="store_true")
    h = sub.add_parser("heldout")
    h.add_argument("set")
    h.add_argument("--no-worse", action="store_true", help="exit 0 unless fewer cases pass than on the first run")
    a = p.parse_args(argv)

    if a.cmd == "build":
        from .sim.build import build

        print(build())
    elif a.cmd == "migrate":
        from .ledger import migrate
        from .ledger.seed import owner_url

        print(migrate.down(owner_url()) if a.down else migrate.up(owner_url()))
    elif a.cmd == "seed":
        from .ledger.seed import seed

        print(seed(a.split))
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("cfa.ledger.app:app", host=a.host, port=a.port)
    elif a.cmd == "mcp":
        from .mcp_server import build_server

        build_server(a.token, a.base_url).run()
    elif a.cmd == "run":
        import datetime as dt

        from .agents.client import Ledger
        from .agents.pipeline import run_company
        from .evals.run import tenants
        from .ledger.auth import mint

        splits = config.load("world")["months"]["splits"]
        month = splits.get(a.month) or (dt.date.today().strftime("%Y-%m") if a.month == "current" else a.month)
        for t in tenants():
            token = mint("agent:worker", t, "agent")
            led = Ledger(token, a.ledger_url) if a.ledger_url else Ledger.in_process(token)
            res = run_company(led, t, month, use_llm=not a.no_llm)
            print(t, res.documents, "documents,", len(res.close.entries) if res.close else 0, "close entries")
    elif a.cmd == "publish":
        import os
        import time

        import psycopg

        from .ledger.publisher import KafkaProducer, publish_batch, publisher_url

        producer = KafkaProducer(os.environ["CFA_KAFKA_BOOTSTRAP"])
        with psycopg.connect(publisher_url()) as conn:
            while True:
                out = publish_batch(conn, producer)
                print(out, flush=True)
                if a.once:
                    break
                time.sleep(1 if out["sent"] else 5)
    elif a.cmd == "eval":
        from .evals.run import evaluate

        rep = evaluate(a.split, a.variant, use_llm=not a.no_llm)
        print(
            json.dumps(
                {
                    "coding": {
                        k: v
                        for k, v in rep["coding"].items()
                        if k in ("coverage_ready", "precision_ready", "document_accuracy")
                    },
                    "checks": rep["checks"]["all"],
                    "close": {k: v for k, v in rep["close"].items() if k != "near_misses"},
                    "operational": rep["operational"],
                },
                indent=1,
                default=str,
            )
        )
    elif a.cmd == "calibrate":
        from .evals.calibrate import calibrate

        print(json.dumps(calibrate(), indent=1))
    elif a.cmd == "release":
        from .evals.gate import decide, render, write
        from .evals.run import evaluate

        rep = evaluate(config.load("gates").get("split", "test"), a.variant, use_llm=not a.no_llm)
        d = decide(rep)
        write(d, rep)
        print(render(d, rep))
        return 0 if d["ship"] else 1
    elif a.cmd == "heldout":
        from .evals.heldout import run

        out = run(a.set)
        print(
            f"{out['set']} ({out['status']}): {out['passed']}/{out['cases']} cases pass; recorded as {out['recorded_as']}"
        )
        for f in out["failures"]:
            print("  ", json.dumps(f, ensure_ascii=False))
        if a.no_worse and out["recorded_as"] != "first_run.json":
            first = json.loads((config.REPORTS / "heldout" / a.set / "first_run.json").read_text())
            return 0 if out["passed"] >= first["passed"] else 1
        return 0 if not out["failures"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
