"""Local bearer-token adapter and OIDC/JWKS verification for protected workflows."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient

from ..runtime import LOCAL_ENVIRONMENTS, load_project_environment


@dataclass(frozen=True)
class WorkflowActor:
    subject: str
    roles: frozenset[str]
    allowed_order_ids: frozenset[str]
    allowed_ticket_ids: frozenset[str]
    tenant_id: str | None = None

    @property
    def role(self) -> str:
        return "reviewer" if "support_reviewer" in self.roles else "support"


@lru_cache(maxsize=4)
def _jwks_client(uri: str) -> PyJWKClient:
    return PyJWKClient(uri, cache_jwk_set=True, lifespan=300, timeout=5)


def _string_set(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(part for part in value.split() if part)
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(part) for part in value if str(part))
    return frozenset()


def _from_oidc(token: str) -> WorkflowActor:
    issuer = os.getenv("OIDC_ISSUER", "").strip().rstrip("/")
    audience = os.getenv("OIDC_AUDIENCE", "").strip()
    jwks_uri = os.getenv("OIDC_JWKS_URL", "").strip() or (f"{issuer}/.well-known/jwks.json" if issuer else "")
    if not issuer or not audience or not jwks_uri:
        raise HTTPException(status_code=503, detail="OIDC issuer, audience, and JWKS URL must be configured")
    try:
        signing_key = _jwks_client(jwks_uri).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Bearer token is invalid or expired") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Identity verification service is unavailable") from exc

    raw_roles = _string_set(claims.get("roles")) | _string_set(claims.get("role"))
    raw_roles = raw_roles | _string_set(claims.get("scope"))
    reviewer_role = os.getenv("OIDC_REVIEWER_ROLE", "support_reviewer").strip()
    support_role = os.getenv("OIDC_SUPPORT_ROLE", "support_agent").strip()
    roles: frozenset[str] = frozenset()
    if reviewer_role and reviewer_role in raw_roles:
        roles = roles | {"support_reviewer"}
    if support_role and support_role in raw_roles:
        roles = roles | {"support_agent"}
    if "support_admin" in raw_roles:
        roles = roles | {"support_admin", "support_reviewer", "support_agent"}
    if not roles:
        raise HTTPException(status_code=403, detail="A support workflow role is required")
    return WorkflowActor(
        subject=str(claims["sub"]),
        roles=roles,
        allowed_order_ids=_string_set(claims.get("order_ids")) | _string_set(claims.get("allowed_order_ids")),
        allowed_ticket_ids=_string_set(claims.get("ticket_ids")) | _string_set(claims.get("allowed_ticket_ids")),
        tenant_id=str(claims.get("tenant_id")) if claims.get("tenant_id") is not None else None,
    )


def get_workflow_actor(authorization: str | None = Header(default=None)) -> WorkflowActor:
    """Authenticate users; production requires a signed OIDC access token."""
    load_project_environment()
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        raise HTTPException(status_code=401, detail="Bearer authentication is required")

    issuer = os.getenv("OIDC_ISSUER", "").strip()
    audience = os.getenv("OIDC_AUDIENCE", "").strip()
    if issuer or audience:
        return _from_oidc(supplied)

    environment = os.getenv("APP_ENV", "").strip().lower()
    if environment not in LOCAL_ENVIRONMENTS:
        raise HTTPException(status_code=503, detail="OIDC identity verification is not configured")
    api_token = os.getenv("WORKFLOW_API_TOKEN", "").strip()
    reviewer_token = os.getenv("WORKFLOW_REVIEWER_TOKEN", "").strip()
    if not api_token or not reviewer_token or hmac.compare_digest(api_token, reviewer_token):
        raise HTTPException(status_code=503, detail="Distinct local workflow and reviewer tokens must be configured")

    if hmac.compare_digest(supplied, reviewer_token):
        return WorkflowActor(
            subject=os.getenv("WORKFLOW_REVIEWER_ID", "local-reviewer").strip() or "local-reviewer",
            roles=frozenset({"support_reviewer"}),
            allowed_order_ids=frozenset({"*"}),
            allowed_ticket_ids=frozenset({"*"}),
        )
    if hmac.compare_digest(supplied, api_token):
        return WorkflowActor(
            subject=os.getenv("WORKFLOW_API_ACTOR_ID", "local-support-agent").strip() or "local-support-agent",
            roles=frozenset({"support_agent"}),
            allowed_order_ids=frozenset({"*"}),
            allowed_ticket_ids=frozenset({"*"}),
        )
    raise HTTPException(status_code=401, detail="Bearer token is invalid")


def require_support(actor: WorkflowActor = Depends(get_workflow_actor)) -> WorkflowActor:
    if not (actor.roles & {"support_agent", "support_admin"}):
        raise HTTPException(status_code=403, detail="Support agent role is required")
    return actor


def require_reviewer(actor: WorkflowActor = Depends(get_workflow_actor)) -> WorkflowActor:
    if not (actor.roles & {"support_reviewer", "support_admin"}):
        raise HTTPException(status_code=403, detail="Reviewer role is required")
    return actor


def authorize_order(actor: WorkflowActor, order_id: str) -> None:
    if "*" not in actor.allowed_order_ids and order_id not in actor.allowed_order_ids:
        raise HTTPException(status_code=403, detail="Caller is not authorized for this order")


def authorize_ticket(actor: WorkflowActor, ticket_id: str) -> None:
    if "*" not in actor.allowed_ticket_ids and ticket_id not in actor.allowed_ticket_ids:
        raise HTTPException(status_code=403, detail="Caller is not authorized for this ticket")
