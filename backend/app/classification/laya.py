"""HTTP adapter for Laya's typed intent decision endpoint."""

from __future__ import annotations

import math
import os
from typing import Any
from urllib.parse import urlsplit

import httpx


class LayaClassifierError(RuntimeError):
    """Raised when Laya cannot return a valid supported intent decision."""


ALLOWED_ENDPOINT_PATHS = {"/api/predict", "/v1/systemone"}


INTENT_OPTIONS: dict[str, str] = {
    "address_change": "The customer wants to change or correct the delivery address.",
    "compensation_request": "The customer asks for compensation, credit, or goodwill value.",
    "damaged_item": "An item or package arrived damaged, broken, or defective.",
    "delivery_delay": "The order is late or tracking stopped before delivery.",
    "delivery_dispute": "The customer disputes an attempted or completed delivery event.",
    "exchange_request": "The customer asks to exchange an item or receive a replacement.",
    "general_policy": "The customer asks a general policy or FAQ question.",
    "incorrect_item": "The delivered product or variant differs from what was ordered.",
    "invoice_request": "The customer asks for an invoice, receipt, or tax document.",
    "late_refund": "A recorded refund appears to have exceeded its expected timeline.",
    "loyalty_points": "The customer asks about a recorded loyalty points balance, accrual, or missing points.",
    "missing_accessory": "A listed accessory or component was missing from the package.",
    "non_delivery": "The customer says the package was not received, including a delivered-scan dispute.",
    "order_cancellation": "The customer asks to cancel an order or check a cancellation.",
    "order_status": "The customer asks for the recorded status of an order.",
    "partial_delivery": "Only some items or packages from the order arrived.",
    "payment_question": "The customer asks about recorded payment status or amount charged.",
    "price_difference": "The customer asks why the recorded order total differs from an expected price.",
    "product_question": "The customer asks about a product or variant in their order.",
    "refund_status": "The customer asks for the recorded status of a refund.",
    "return_eligibility": "The customer asks whether a specific item can be returned.",
    "return_pickup": "The customer asks about return collection or pickup progress.",
    "return_status": "The customer asks for the recorded state of an existing return.",
    "reward_expiry": "The customer asks about loyalty points or rewards that are expiring or have expired.",
    "reward_redemption": "The customer asks about a points redemption or reward redemption status.",
    "other_or_unsupported": "The request is unclear, outside these intents, or about an unsupported service.",
}


def _setting_float(name: str, default: float, *, maximum: float = 1.0) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise LayaClassifierError(f"Invalid {name} configuration") from exc
    if not math.isfinite(value) or value < 0 or value > maximum:
        raise LayaClassifierError(f"Invalid {name} configuration")
    return value


def _laya_url() -> str:
    base_url = os.getenv("LAYA_BASE_URL", "http://127.0.0.1:8770").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise LayaClassifierError("Invalid LAYA_BASE_URL configuration")
    endpoint_path = os.getenv("LAYA_ENDPOINT_PATH", "/api/predict").strip()
    if endpoint_path not in ALLOWED_ENDPOINT_PATHS:
        raise LayaClassifierError("Invalid LAYA_ENDPOINT_PATH configuration")
    return f"{base_url}{endpoint_path}"


def classify_with_laya(message: str) -> dict[str, Any]:
    """Return an allowlisted intent and Laya answer probability for one ticket."""
    text = (message or "").strip()
    if not text:
        raise ValueError("Ticket message must not be empty")

    threshold = _setting_float("LAYA_MIN_CONFIDENCE", 0.65)
    timeout = _setting_float("LAYA_TIMEOUT_SECONDS", 15.0, maximum=60.0)
    if timeout <= 0:
        raise LayaClassifierError("Invalid LAYA_TIMEOUT_SECONDS configuration")

    payload: dict[str, Any] = {
        "state": {"ticket_message": text},
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": (
                    "Choose the single label for the customer's primary requested outcome. "
                    "Use other_or_unsupported if no listed intent clearly applies."
                ),
                "criteria": INTENT_OPTIONS,
            }
        },
        "min_confidence": threshold,
    }
    model = os.getenv("LAYA_MODEL", "").strip()
    if model:
        payload["model"] = model

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("LAYA_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(
            _laya_url(),
            json=payload,
            headers=headers,
            timeout=timeout,
            trust_env=False,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Do not include upstream response text or the ticket message in errors.
        raise LayaClassifierError("Laya intent service request failed") from exc

    if not isinstance(body, dict):
        raise LayaClassifierError("Laya returned an invalid response")
    answers = body.get("answers")
    answer = answers.get("intent") if isinstance(answers, dict) else None
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise LayaClassifierError("Laya returned no intent choice")

    intent = answer.get("choice")
    if not isinstance(intent, str) or intent not in INTENT_OPTIONS:
        raise LayaClassifierError("Laya returned an unsupported intent label")

    # Laya's `confidence` is normalized entropy. Use answer_confidence (max p),
    # or the selected option's probability for strict Jev responses.
    score = answer.get("answer_confidence")
    if score is None:
        probabilities = answer.get("probabilities")
        score = probabilities.get(intent) if isinstance(probabilities, dict) else None
    if isinstance(score, bool) or not isinstance(score, (float, int)):
        raise LayaClassifierError("Laya returned no usable answer probability")
    score = float(score)
    if not math.isfinite(score) or score < 0.0 or score > 1.0:
        raise LayaClassifierError("Laya returned an invalid answer probability")

    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    try:
        state_tokens_dropped = int(usage.get("state_tokens_dropped", 0) or 0)
    except (TypeError, ValueError):
        state_tokens_dropped = 1
    truncated = usage.get("truncated") is True or state_tokens_dropped > 0
    laya_abstained = (
        answer.get("low_confidence") is True
        or answer.get("abstention") == "abstained"
    )

    routing = body.get("routing")
    checkpoint = routing.get("model") if isinstance(routing, dict) else None
    checkpoint = checkpoint if isinstance(checkpoint, str) and checkpoint else "auto"
    if len(checkpoint) > 80:
        checkpoint = "auto"

    return {
        "candidate_intent": intent,
        "top_class_probability": score,
        "model_version": f"laya-systemone/{checkpoint}",
        "provider": "laya",
        "fallback_used": False,
        "review_threshold": threshold,
        "force_review": truncated or laya_abstained or intent == "other_or_unsupported",
        "input_truncated": truncated,
        "laya_abstained": laya_abstained,
    }
