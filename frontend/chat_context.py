"""Session-local order and customer references; backend authorization remains authoritative."""

from __future__ import annotations

import csv
from pathlib import Path
import re
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ORDERS_CSV = PROJECT_ROOT / "data" / "processed" / "clean_orders.csv"

_ORDER_ID = re.compile(r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", re.IGNORECASE)
_CUSTOMER_ID = re.compile(r"(?<![\w-])CUS-[0-9A-F]{10}(?![\w-])", re.IGNORECASE)

_ORDER_TO_CUSTOMER: dict[str, str] = {}
_CUSTOMER_TO_ORDERS: dict[str, list[str]] = {}
_MAP_LOADED = False


def _ensure_mappings_loaded() -> None:
    global _MAP_LOADED
    if _MAP_LOADED:
        return
    if _ORDERS_CSV.exists():
        try:
            with open(_ORDERS_CSV, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    oid = row.get("order_id", "").strip()
                    cid = row.get("customer_id", "").strip().upper()
                    if oid and cid:
                        _ORDER_TO_CUSTOMER[oid.upper()] = cid
                        _ORDER_TO_CUSTOMER[oid] = cid
                        _CUSTOMER_TO_ORDERS.setdefault(cid, []).append(oid)
            _MAP_LOADED = True
        except Exception:
            pass


def find_customer_for_order(order_id: str | None) -> str | None:
    """Return the linked customer ID for a given order ID, if known."""
    if not order_id:
        return None
    _ensure_mappings_loaded()
    res = _ORDER_TO_CUSTOMER.get(order_id) or _ORDER_TO_CUSTOMER.get(order_id.upper())
    if res:
        return res
    try:
        from backend.app.db.database import get_db_cursor
        with get_db_cursor() as cursor:
            cursor.execute("SELECT customer_id FROM orders WHERE order_id = %s", (order_id.strip(),))
            row = cursor.fetchone()
            if row and row.get("customer_id"):
                return str(row["customer_id"]).strip().upper()
    except Exception:
        pass
    return None


def find_latest_order_for_customer(customer_id: str | None) -> str | None:
    """Return the most recent linked order ID for a given customer ID, if known."""
    if not customer_id:
        return None
    _ensure_mappings_loaded()
    orders = _CUSTOMER_TO_ORDERS.get(customer_id.upper()) or []
    return orders[0] if orders else None


def find_all_orders_for_customer(customer_id: str | None) -> list[str]:
    """Return all known linked orders for a given customer ID."""
    if not customer_id:
        return []
    _ensure_mappings_loaded()
    return list(_CUSTOMER_TO_ORDERS.get(customer_id.upper()) or [])


def resolve_order_context(message: str, manual_order_id: str, previous_order_id: str | None) -> str | None:
    """Resolve active order ID from manual input, message extraction, or previous turn context."""
    if manual_order_id.strip():
        return manual_order_id.strip()
    references = sorted(set(_ORDER_ID.findall(message)))
    if references:
        return references[0] if len(references) == 1 else None
    return previous_order_id or None


def resolve_customer_context(message: str, manual_customer_id: str, previous_customer_id: str | None) -> str | None:
    """Resolve active customer ID from manual input, message extraction, or previous turn context."""
    if manual_customer_id.strip():
        return manual_customer_id.strip().upper()
    references = sorted({match.upper() for match in _CUSTOMER_ID.findall(message)})
    if references:
        return references[0] if len(references) == 1 else None
    return previous_customer_id or None


def detect_customer_mismatch(
    message: str,
    active_customer_id: str | None,
    order_id: str | None = None,
) -> str | None:
    """If the message or input explicitly specifies a customer ID that differs from active session customer,
    or references an order belonging to another customer account, return that conflicting customer ID.
    """
    if not active_customer_id:
        return None
    active_upper = active_customer_id.strip().upper()

    # 1. Direct customer reference mismatch in message
    references = sorted({match.upper() for match in _CUSTOMER_ID.findall(message)})
    for ref in references:
        if ref != active_upper:
            return ref

    # 2. Order reference in message or input belonging to another customer account
    order_refs = sorted(set(_ORDER_ID.findall(message)))
    if order_id and order_id not in order_refs:
        order_refs.append(order_id)
    for ord_ref in order_refs:
        linked_cust = find_customer_for_order(ord_ref)
        if linked_cust and linked_cust.upper() != active_upper:
            return linked_cust.upper()

    return None


def resolve_conversation_context(
    message: str,
    *,
    manual_order_id: str = "",
    manual_customer_id: str = "",
    previous_order_id: str | None = None,
    previous_customer_id: str | None = None,
    autolink: bool = True,
    **kwargs: Any,
) -> dict[str, str | None]:
    """Unified helper returning the active operational context for the current turn.

    When autolink is enabled (default):
    - Mentioning an order automatically populates its linked customer ID into context.
    - Mentioning a customer automatically populates their linked order ID into context.
    Explicit user inputs (manual fields or in the current message) always take precedence.
    """
    order_id = resolve_order_context(message, manual_order_id, previous_order_id)
    customer_id = resolve_customer_context(message, manual_customer_id, previous_customer_id)

    # Disconnect order if it belongs to a different customer
    if order_id and customer_id:
        linked_cust = find_customer_for_order(order_id)
        if linked_cust and linked_cust.upper() != customer_id.upper():
            msg_orders = _ORDER_ID.findall(message)
            msg_custs = _CUSTOMER_ID.findall(message)
            if msg_custs and not msg_orders:
                order_id = find_latest_order_for_customer(customer_id)
            elif msg_orders and not msg_custs:
                # Do NOT silently switch customer_id to linked_cust if a customer was already active!
                # If an active customer session exists, customer_id remains authoritative.
                if not (manual_customer_id or previous_customer_id):
                    customer_id = linked_cust

    if autolink:
        # Autolink customer from order if customer is missing
        if order_id and not customer_id:
            inferred_cust = find_customer_for_order(order_id)
            if inferred_cust:
                customer_id = inferred_cust

        # Autolink order from customer if order is missing
        if customer_id and not order_id:
            inferred_ord = find_latest_order_for_customer(customer_id)
            if inferred_ord:
                order_id = inferred_ord

    return {
        "order_id": order_id,
        "customer_id": customer_id,
    }
