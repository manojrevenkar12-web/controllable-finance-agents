"""Policy checks on the Terraform for GCP: the worker never touches the database, nothing is public, data stays in the EU."""

import hcl2
import pytest

from cfa import config

INFRA = config.ROOT / "infra"


def _clean(v):
    if isinstance(v, dict):
        return {_clean(k): _clean(x) for k, x in v.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, str) and len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1]
    return v


@pytest.fixture(scope="module")
def tf():
    out: dict = {"resource": {}, "variable": {}}
    for path in INFRA.glob("*.tf"):
        with open(path) as f:
            doc = _clean(hcl2.load(f))
        for block in doc.get("resource", []):
            for rtype, named in block.items():
                for name, body in named.items():
                    out["resource"].setdefault(rtype, {})[name] = body
        for block in doc.get("variable", []):
            out["variable"].update(block)
    return out


def members(tf, kind):
    return [(n, m["member"], m["role"]) for n, m in tf["resource"].get(kind, {}).items()]


def test_the_worker_has_no_database_access(tf):
    for _, member, role in members(tf, "google_project_iam_member"):
        if "worker" in member:
            assert not role.startswith("roles/cloudsql"), role
    users = tf["resource"]["google_sql_user"]
    assert all("worker" not in u["name"] for u in users.values())


def test_database_is_private_iam_only_and_backed_up(tf):
    s = tf["resource"]["google_sql_database_instance"]["ledger"]["settings"][0]
    ip = s["ip_configuration"][0]
    assert ip["ipv4_enabled"] is False and ip["ssl_mode"] == "ENCRYPTED_ONLY"
    assert {"name": "cloudsql.iam_authentication", "value": "on"} in s["database_flags"]
    assert s["backup_configuration"][0]["point_in_time_recovery_enabled"] is True
    assert all(u["type"] == "CLOUD_IAM_SERVICE_ACCOUNT" for u in tf["resource"]["google_sql_user"].values())


def test_only_the_publisher_writes_to_kafka(tf):
    kafka = [m for _, m, r in members(tf, "google_project_iam_member") if r.startswith("roles/managedkafka")]
    assert kafka == ["serviceAccount:${google_service_account.publisher.email}"]


def test_the_ledger_is_not_public_and_runs_in_production_mode(tf):
    svc = tf["resource"]["google_cloud_run_v2_service"]["ledger"]
    assert svc["ingress"] == "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    env = {e["name"] for e in svc["template"][0]["containers"][0]["env"]}
    assert {"CFA_ENV", "CFA_JWT_SECRET"} <= env


def test_model_key_only_for_the_worker(tf):
    holders = [
        m["member"]
        for m in tf["resource"]["google_secret_manager_secret_iam_member"].values()
        if "model_key" in m["secret_id"]
    ]
    assert holders == ["serviceAccount:${google_service_account.worker.email}"]


def test_everything_in_the_eu(tf):
    assert tf["variable"]["region"]["default"].startswith("europe-")
    assert tf["resource"]["google_bigquery_dataset"]["quality"]["location"] == "EU"
