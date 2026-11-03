import os

import psycopg
import pytest

from cfa import config

OWNER = os.environ.get("CFA_TEST_OWNER_URL", "postgresql://postgres@127.0.0.1:5544/cfa_test")
APP = os.environ.get("CFA_TEST_APP_URL", "postgresql://cfa_app:cfa_app@127.0.0.1:5544/cfa_test")


def _db_available() -> bool:
    try:
        with psycopg.connect(OWNER, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def world() -> None:
    if not (config.DATA / "dev" / "truth.json").exists():
        from cfa.sim.build import build

        build()


@pytest.fixture(scope="session")
def ledger_db(world):
    """The dev month loaded into a test database; the service connects as the runtime role."""
    if not _db_available():
        pytest.skip("PostgreSQL not available (set CFA_TEST_OWNER_URL)")
    os.environ["CFA_OWNER_URL"] = OWNER
    os.environ["CFA_APP_URL"] = APP
    from cfa.ledger.app import reset_pool
    from cfa.ledger.seed import seed

    reset_pool()
    seed("dev", OWNER)
    reset_pool()
    yield OWNER
    reset_pool()


def mark_db(fn):
    return pytest.mark.db(fn)
