"""Who is calling: a signed token names the person (or agent), their company, role and department.

When an agent acts for a person, the token carries the person as subject and the agent in ``act`` (the actor
claim of RFC 8693): permissions are the person's, the audit log records both.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

import jwt

from .. import config

ROLES = ("employee", "approver", "accountant", "admin", "agent", "ingest")


@dataclass(frozen=True)
class Principal:
    sub: str
    tenant: str
    role: str
    department: str | None = None
    actor: str | None = None  # the agent acting for this person, if any

    @property
    def audit_name(self) -> str:
        return f"{self.actor} for {self.sub}" if self.actor else self.sub


def secret() -> str:
    cfg = config.load("ledger")["auth"]
    value = os.environ.get(cfg["secret_env"])
    if value:
        return value
    if os.environ.get("CFA_ENV") == "production":
        raise RuntimeError(f"{cfg['secret_env']} must be set in production")
    return cfg["dev_secret"]


def mint(
    sub: str,
    tenant: str,
    role: str,
    department: str | None = None,
    actor: str | None = None,
    minutes: int | None = None,
) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role {role}")
    cfg = config.load("ledger")["auth"]
    now = dt.datetime.now(dt.UTC)
    claims = {
        "sub": sub,
        "tenant": tenant,
        "role": role,
        "iss": cfg["issuer"],
        "iat": now,
        "exp": now + dt.timedelta(minutes=minutes or cfg["token_minutes"]),
    }
    if department:
        claims["dept"] = department
    if actor:
        claims["act"] = {"sub": actor}
    return jwt.encode(claims, secret(), algorithm="HS256")


def verify(token: str) -> Principal:
    cfg = config.load("ledger")["auth"]
    c = jwt.decode(
        token, secret(), algorithms=["HS256"], issuer=cfg["issuer"], options={"require": ["exp", "sub", "iss"]}
    )
    if c.get("role") not in ROLES or not c.get("tenant"):
        raise jwt.InvalidTokenError("token lacks a valid role or tenant")
    act = c.get("act")
    return Principal(c["sub"], c["tenant"], c["role"], c.get("dept"), act.get("sub") if isinstance(act, dict) else None)
