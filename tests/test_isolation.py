"""Agents never see how the world was made or what the right answers are."""

import ast
from pathlib import Path

from cfa import config

AGENTS = config.ROOT / "cfa" / "agents"
FORBIDDEN_MODULES = ("cfa.sim", "cfa.evals")
FORBIDDEN_TEXT = ("truth", "world.yaml", "habit_changes", "cc_department", "recurring_key")


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            base = "cfa.agents" if node.level == 1 else "cfa" if node.level == 2 else ""
            mod = ".".join(x for x in (base, node.module or "") if x)
            out |= {f"{mod}.{a.name}" for a in node.names} if node.module is None else {mod}
        elif isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
    return out


def test_agents_do_not_import_the_generator_or_the_evaluator():
    for path in [*AGENTS.glob("*.py"), config.ROOT / "cfa" / "mcp_server.py"]:
        bad = {m for m in _imports(path) if m.startswith(FORBIDDEN_MODULES)}
        assert not bad, f"{path.name}: {bad}"


def test_agents_do_not_name_the_truth():
    for path in AGENTS.glob("*.py"):
        text = path.read_text()
        for word in FORBIDDEN_TEXT:
            assert word not in text, f"{path.name} mentions {word}"


def test_prompts_do_not_describe_the_simulation():
    for path in (config.ROOT / "prompts").glob("*.md"):
        low = path.read_text().lower()
        for word in ("synthetic", "seeded", "generator", "decoy", "habit change"):
            assert word not in low, f"{path.name} mentions {word}"


def test_the_ledger_never_reads_the_world():
    for path in (config.ROOT / "cfa" / "ledger").glob("*.py"):
        if path.name == "seed.py":  # the seeding job loads the simulated companies; the service never does
            continue
        assert "world" not in path.read_text(), path.name
