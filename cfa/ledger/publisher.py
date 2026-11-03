"""Relay the outbox to Kafka: every event written in the same transaction as the change it describes, sent at
least once, in order per company, and marked published only after the broker acknowledged it.

Consumers dedupe by the event id (the outbox row id, sent as a header). A send that fails leaves the row
unpublished, so the next pass retries it; nothing is ever lost between the database and the topic.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import psycopg

from .. import config


class Producer(Protocol):
    def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None: ...  # raises on failure


class KafkaProducer:
    """confluent-kafka, configured from CFA_KAFKA_BOOTSTRAP (Google Managed Kafka uses SASL/OAUTHBEARER on GCP)."""

    def __init__(self, bootstrap: str, extra: dict[str, Any] | None = None):
        from confluent_kafka import Producer as CK  # type: ignore[import-not-found]

        self.p = CK({"bootstrap.servers": bootstrap, "enable.idempotence": True, "acks": "all", **(extra or {})})

    def send(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> None:
        errors: list[Any] = []
        self.p.produce(
            topic,
            key=key,
            value=value,
            headers=list(headers.items()),
            on_delivery=lambda err, _msg: errors.append(err) if err else None,
        )
        self.p.flush(10)
        if errors:
            raise RuntimeError(str(errors[0]))


def publisher_url() -> str:
    return os.environ.get("CFA_PUBLISHER_URL", "postgresql://cfa_publisher:cfa_publisher@127.0.0.1:5544/cfa")


def publish_batch(conn: psycopg.Connection[Any], producer: Producer, limit: int = 500) -> dict:
    topics = config.load("ledger")["kafka"]["topics"]
    sent = failed = 0
    with conn.transaction():
        rows = conn.execute(
            "select id, tenant_id, topic, key, payload from outbox where published_at is null "
            "order by id limit %s for update skip locked",
            (limit,),
        ).fetchall()
        done = []
        for row_id, tenant, event, key, payload in rows:
            try:
                producer.send(
                    topics.get(event, "cfa.events"),
                    key=f"{tenant}:{key}",
                    value=json.dumps(payload, ensure_ascii=False).encode(),
                    headers={"event-id": str(row_id), "event": event, "tenant": tenant},
                )
            except Exception:
                failed += 1
                break  # keep order: later events of the batch wait for this one
            done.append(row_id)
            sent += 1
        if done:
            conn.execute("update outbox set published_at = now() where id = any(%s)", (done,))
    return {"sent": sent, "failed": failed}
