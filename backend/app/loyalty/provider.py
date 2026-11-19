"""Safe provider boundary for a future loyalty-system integration.

The workflow does not call this adapter today: loyalty proposals remain
simulation-only.  Keeping the provider boundary separate prevents a reviewer
approval from accidentally becoming an external points mutation.
"""

from __future__ import annotations

import ipaddress
import json
import os
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from ..runtime import LOCAL_ENVIRONMENTS


class LoyaltyProviderError(RuntimeError):
    """A configured loyalty provider cannot safely accept an adjustment."""


@dataclass(frozen=True)
class ProviderConfiguration:
    mode: str
    endpoint: str | None
    token: str | None
    environment: str


class _NoRedirect(HTTPRedirectHandler):
    """Reject redirects so an approved endpoint cannot be redirected elsewhere."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str):  # type: ignore[override]
        return None


def _configured_mode() -> str:
    return os.getenv("LOYALTY_PROVIDER_MODE", "disabled").strip().lower() or "disabled"


def _is_private_or_local_host(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain", "::1"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)


def _allowed_hosts() -> set[str]:
    return {
        value.strip().lower().rstrip(".")
        for value in os.getenv("LOYALTY_PROVIDER_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    }


def provider_configuration() -> ProviderConfiguration:
    """Read a secret-backed configuration without exposing secrets to callers."""
    return ProviderConfiguration(
        mode=_configured_mode(),
        endpoint=os.getenv("LOYALTY_PROVIDER_URL", "").strip() or None,
        token=os.getenv("LOYALTY_PROVIDER_TOKEN", "").strip() or None,
        environment=os.getenv("APP_ENV", "").strip().lower(),
    )


def provider_status() -> dict[str, Any]:
    """Return a non-sensitive readiness report for operators and the UI."""
    config = provider_configuration()
    errors: list[str] = []
    if config.mode not in {"disabled", "simulation", "http_json"}:
        errors.append("LOYALTY_PROVIDER_MODE must be disabled, simulation, or http_json")
    elif config.mode == "simulation":
        if config.environment not in LOCAL_ENVIRONMENTS:
            errors.append("Simulation mode is limited to local development")
    elif config.mode == "http_json":
        if config.environment != "production":
            errors.append("The HTTP provider is limited to APP_ENV=production")
        if not config.endpoint:
            errors.append("LOYALTY_PROVIDER_URL is required for http_json mode")
        else:
            parsed = urlparse(config.endpoint)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                errors.append("LOYALTY_PROVIDER_URL must be an HTTPS URL without user credentials")
            else:
                host = parsed.hostname.lower().rstrip(".")
                allowed_hosts = _allowed_hosts()
                if not allowed_hosts:
                    errors.append("LOYALTY_PROVIDER_ALLOWED_HOSTS is required for http_json mode")
                elif host not in allowed_hosts:
                    errors.append("LOYALTY_PROVIDER_URL host is not in LOYALTY_PROVIDER_ALLOWED_HOSTS")
                if _is_private_or_local_host(host) and os.getenv("LOYALTY_ALLOW_PRIVATE_PROVIDER_HOST") != "true":
                    errors.append("LOYALTY_PROVIDER_URL must not target a private or local host")
        if not config.token:
            errors.append("LOYALTY_PROVIDER_TOKEN is required for http_json mode")
    return {
        "mode": config.mode,
        "configured": config.mode != "disabled" and not errors,
        "external_writes_enabled": False,
        "errors": errors,
        "execution_boundary": "simulation_only_until_a_separate_reviewed_executor_is_enabled",
    }


def apply_adjustment(*, adjustment: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    """Call a provider with an evidence-derived adjustment.

    This low-level adapter intentionally has no route or workflow caller. A
    future production executor must add its own authorization, immutable audit
    record, second-person approval, and provider-specific contract tests.
    """
    if not isinstance(adjustment, dict):
        raise LoyaltyProviderError("Adjustment must be an object")
    account_id = str(adjustment.get("account_id") or "")
    order_id = str(adjustment.get("order_id") or "")
    reason_code = str(adjustment.get("reason_code") or "")
    points_delta = adjustment.get("points_delta")
    if not account_id or not order_id or reason_code != "reinstate_reversed_points":
        raise LoyaltyProviderError("Adjustment does not contain verified loyalty evidence")
    if not isinstance(points_delta, int) or not 1 <= points_delta <= 100_000:
        raise LoyaltyProviderError("Adjustment points must be a bounded positive integer")
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
        raise LoyaltyProviderError("Idempotency key must be between 1 and 128 characters")

    config = provider_configuration()
    status = provider_status()
    if not status["configured"]:
        raise LoyaltyProviderError("Loyalty provider is not safely configured")
    if config.mode == "simulation":
        return {
            "status": "simulated",
            "provider_reference": f"simulated:{idempotency_key}",
            "applied_points_delta": points_delta,
        }
    if config.mode != "http_json" or not config.endpoint or not config.token:
        raise LoyaltyProviderError("Loyalty provider mode is not executable")

    body = json.dumps({
        "adjustment_id": idempotency_key,
        "account_id": account_id,
        "order_id": order_id,
        "points_delta": points_delta,
        "reason_code": reason_code,
    }, separators=(",", ":")).encode("utf-8")
    request = Request(
        config.endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=5) as response:
            if int(response.status) not in {200, 201, 202}:
                raise LoyaltyProviderError("Loyalty provider rejected the adjustment")
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise LoyaltyProviderError("Loyalty provider request failed") from exc
    if not isinstance(payload, dict):
        raise LoyaltyProviderError("Loyalty provider returned an invalid response")
    provider_reference = payload.get("provider_reference")
    applied_points = payload.get("applied_points_delta")
    if not isinstance(provider_reference, str) or not provider_reference or len(provider_reference) > 128:
        raise LoyaltyProviderError("Loyalty provider response has no valid reference")
    if applied_points != points_delta:
        raise LoyaltyProviderError("Loyalty provider did not confirm the expected points adjustment")
    return {
        "status": "applied",
        "provider_reference": provider_reference,
        "applied_points_delta": applied_points,
    }
