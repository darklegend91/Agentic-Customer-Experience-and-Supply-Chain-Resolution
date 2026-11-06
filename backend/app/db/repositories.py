"""Allowlisted, field-minimized read repositories for local fixture records."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .session import DatabaseUnavailable, readonly_cursor


class RecordNotFound(LookupError):
    """A requested fixture record does not exist."""


def _as_json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _as_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_json(item) for item in value]
    return value


def _as_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _as_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def get_ticket_readonly(ticket_id: str) -> dict[str, Any]:
    """Read only user-facing ticket fields; never select expected labels."""
    try:
        with readonly_cursor() as cursor:
            cursor.execute(
                """
                SELECT ticket_id, message, order_id
                FROM tickets
                WHERE ticket_id = %s
                LIMIT 1
                """,
                (ticket_id,),
            )
            row = _as_dict(cursor.fetchone())
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("Ticket lookup failed") from exc
    if row is None:
        raise RecordNotFound("Ticket was not found in the development fixture")
    return _as_json(row)


def get_order_summary_readonly(order_id: str) -> dict[str, Any]:
    """Read one order and at most 50 item rows, omitting customer identifiers."""
    try:
        with readonly_cursor() as cursor:
            cursor.execute(
                """
                SELECT order_id, status, order_date, estimated_delivery, actual_delivery,
                       seller_type, marketplace
                FROM orders
                WHERE order_id = %s
                LIMIT 1
                """,
                (order_id,),
            )
            order = _as_dict(cursor.fetchone())
            if order is not None:
                cursor.execute(
                    """
                    SELECT item_id, product_id, product_name, category, quantity,
                           unit_price_inr, condition_reported
                    FROM order_items
                    WHERE order_id = %s
                    ORDER BY item_id
                    LIMIT 50
                    """,
                    (order_id,),
                )
                items = _as_dicts(cursor.fetchall())
            else:
                items = []
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("Order summary lookup failed") from exc
    if order is None:
        raise RecordNotFound("Order was not found in the development fixture")
    missing_fields = []
    if not str(order.get("status") or "").strip():
        missing_fields.append("order.status")
    if not items:
        missing_fields.append("order_items")
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _as_json({
        "source_system": "Neon Postgres",
        "as_of": as_of,
        "status": "insufficient_data" if missing_fields else "found",
        "order_id": order_id,
        "order": order,
        "items": items,
        "evidence_refs": {
            "order": [f"order:{order_id}"],
            "items": [f"item:{row['item_id']}" for row in items] or [f"order_items_lookup:{order_id}:{as_of}"],
        },
        "missing_fields": missing_fields,
    })


def get_customer_support_context_readonly(order_id: str) -> dict[str, Any]:
    """Read loyalty and prior-contact summaries for the customer linked to one order.

    Customer identifiers are used only to join bounded rows and are never returned.
    The order identifier is the external scope key; callers must authorize it first.
    """
    try:
        with readonly_cursor() as cursor:
            cursor.execute(
                """
                SELECT o.customer_id
                FROM orders AS o
                WHERE o.order_id = %s
                LIMIT 1
                """,
                (order_id,),
            )
            order_row = _as_dict(cursor.fetchone())
            if order_row is not None:
                customer_id = str(order_row["customer_id"])
                cursor.execute(
                    """
                    SELECT account_id, loyalty_tier, points_balance, account_status, as_of, source
                    FROM customer_loyalty_accounts
                    WHERE customer_id = %s
                    LIMIT 1
                    """,
                    (customer_id,),
                )
                account = _as_dict(cursor.fetchone())
                cursor.execute(
                    """
                    SELECT event_id, order_id, event_type, points_delta, status,
                           occurred_at, expires_at, reward_code, source
                    FROM loyalty_transactions
                    WHERE customer_id = %s
                    ORDER BY occurred_at DESC, event_id
                    LIMIT 50
                    """,
                    (customer_id,),
                )
                transactions = _as_dicts(cursor.fetchall())
                cursor.execute(
                    """
                    SELECT communication_id, order_id, channel, direction, topic,
                           summary, occurred_at, outcome, source
                    FROM customer_communications
                    WHERE customer_id = %s
                    ORDER BY occurred_at DESC, communication_id
                    LIMIT 20
                    """,
                    (customer_id,),
                )
                communications = _as_dicts(cursor.fetchall())
            else:
                account, transactions, communications = None, [], []
    except DatabaseUnavailable as exc:
        # Customer context is an optional data source. Keep core order
        # investigation available when this Neon branch lacks its tables.
        cause = exc.__cause__
        if getattr(cause, "pgcode", None) != "42P01":
            raise
        as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        return {
            "schema_version": "1.0",
            "source_systems": ["Neon Postgres"],
            "as_of": as_of,
            "status": "insufficient_data",
            "order_id": order_id,
            "loyalty_account": None,
            "loyalty_transactions": [],
            "prior_communications": [],
            "evidence_refs": {
                "customer_context_lookup": [f"customer_context:{order_id}:{as_of}"],
                "loyalty_account": [],
                "loyalty_transactions": [],
                "prior_communications": [],
            },
            "missing_fields": [
                "customer_context_schema_unavailable",
                "loyalty_account_record",
                "loyalty_transactions",
                "prior_communications",
            ],
            "conflicts": [],
        }
    except Exception as exc:
        raise DatabaseUnavailable("Customer support context lookup failed") from exc

    if order_row is None:
        raise RecordNotFound("Order was not found in the development fixture")

    conflicts: list[str] = []
    if account is not None:
        ledger_balance = sum(
            int(row.get("points_delta") or 0)
            for row in transactions
            if str(row.get("status") or "").lower() == "posted"
        )
        # The query is limited to the latest 50 rows. Only compare when the
        # account has no more than 50 transactions, avoiding false conflicts.
        if ledger_balance != int(account.get("points_balance") or 0) and len(transactions) < 50:
            conflicts.append("loyalty_balance_does_not_match_posted_ledger")

    missing_fields = [] if account is not None else ["loyalty_account_record"]
    # These queries are intentionally bounded. Mark a full page as truncated so
    # downstream responses never imply that the returned history is complete.
    if len(transactions) == 50:
        missing_fields.append("loyalty_transactions_truncated")
    if len(communications) == 20:
        missing_fields.append("prior_communications_truncated")
    status = "found" if not missing_fields and not conflicts else "insufficient_data"
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _as_json({
        "schema_version": "1.0",
        "source_systems": ["Neon Postgres"],
        "as_of": as_of,
        "status": status,
        "order_id": order_id,
        "loyalty_account": account,
        "loyalty_transactions": transactions,
        "prior_communications": communications,
        "evidence_refs": {
            # This reference records the bounded lookup itself, including a
            # successful empty result, without inventing a row identifier.
            "customer_context_lookup": [f"customer_context:{order_id}:{as_of}"],
            "loyalty_account": [f"loyalty_account:{account['account_id']}"] if account else [],
            "loyalty_transactions": [f"loyalty_transaction:{row['event_id']}" for row in transactions],
            "prior_communications": [f"customer_communication:{row['communication_id']}" for row in communications],
        },
        "missing_fields": missing_fields,
        "conflicts": conflicts,
    })


def get_order_investigation_readonly(
    order_id: str,
    *,
    item_limit: int = 50,
    event_limit: int = 100,
    return_limit: int = 50,
) -> dict[str, Any]:
    """Read one order and all bounded supporting rows in a single transaction."""
    if not 1 <= item_limit <= 50 or not 1 <= event_limit <= 100 or not 1 <= return_limit <= 50:
        raise ValueError("Investigation result limits are outside the configured bounds")
    try:
        with readonly_cursor() as cursor:
            cursor.execute(
                """
                WITH request_config AS MATERIALIZED (
                    SELECT set_config('statement_timeout', '5000', true) AS timeout_value
                )
                SELECT
                    jsonb_build_object(
                        'order_id', o.order_id,
                        'status', o.status,
                        'order_date', o.order_date,
                        'estimated_delivery', o.estimated_delivery,
                        'actual_delivery', o.actual_delivery,
                        'seller_type', o.seller_type,
                        'marketplace', o.marketplace
                    ) AS order_record,
                    COALESCE((
                        SELECT jsonb_agg(item_data.item_json ORDER BY item_data.item_id)
                        FROM (
                            SELECT oi.item_id,
                                   jsonb_build_object(
                                       'item_id', oi.item_id,
                                       'product_id', oi.product_id,
                                       'product_name', oi.product_name,
                                       'category', oi.category,
                                       'quantity', oi.quantity,
                                       'unit_price_inr', oi.unit_price_inr,
                                       'condition_reported', oi.condition_reported
                                   ) AS item_json
                            FROM order_items AS oi
                            WHERE oi.order_id = o.order_id
                            ORDER BY oi.item_id
                            LIMIT %s
                        ) AS item_data
                    ), '[]'::jsonb) AS items,
                    COALESCE((
                        SELECT jsonb_agg(event_data.event_json ORDER BY event_data.event_time, event_data.event_id)
                        FROM (
                            SELECT de.event_id, de.event_time,
                                   jsonb_build_object(
                                       'event_id', de.event_id,
                                       'event_type', de.event_type,
                                       'event_time', de.event_time,
                                       'location', de.location,
                                       'source', de.source
                                   ) AS event_json
                            FROM delivery_events AS de
                            WHERE de.order_id = o.order_id
                            ORDER BY de.event_time, de.event_id
                            LIMIT %s
                        ) AS event_data
                    ), '[]'::jsonb) AS delivery_events,
                    COALESCE((
                        SELECT jsonb_agg(return_data.return_json ORDER BY return_data.requested_at, return_data.return_id)
                        FROM (
                            SELECT rr.return_id, rr.requested_at,
                                   jsonb_build_object(
                                       'return_id', rr.return_id,
                                       'item_id', rr.item_id,
                                       'requested_at', rr.requested_at,
                                       'status', rr.status,
                                       'inspection_status', rr.inspection_status,
                                       'refund_status', rr.refund_status,
                                       'source', rr.source
                                   ) AS return_json
                            FROM returns_refunds AS rr
                            WHERE rr.order_id = o.order_id
                            ORDER BY rr.requested_at, rr.return_id
                            LIMIT %s
                        ) AS return_data
                    ), '[]'::jsonb) AS returns_refunds
                FROM orders AS o
                CROSS JOIN request_config
                WHERE o.order_id = %s
                LIMIT 1
                """,
                (item_limit, event_limit, return_limit, order_id),
            )
            row = _as_dict(cursor.fetchone())
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("Order investigation lookup failed") from exc
    if row is None:
        raise RecordNotFound("Order was not found in the development fixture")

    order = row["order_record"]
    items = row["items"] or []
    events = row["delivery_events"] or []
    returns = row["returns_refunds"] or []

    missing_fields = []
    if not str(order.get("status") or "").strip():
        missing_fields.append("order.status")
    if not items:
        missing_fields.append("order_items")
    if not events:
        missing_fields.append("delivery_events")
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _as_json({
        "source_system": "Neon Postgres",
        "as_of": as_of,
        "status": "insufficient_data" if missing_fields else "found",
        "order_id": order_id,
        "order": order,
        "items": items,
        "delivery_events": events,
        "returns_refunds": returns,
        "evidence_refs": {
            "order": [f"order:{order_id}"],
            "items": [f"item:{row['item_id']}" for row in items] or [f"order_items_lookup:{order_id}:{as_of}"],
            "delivery_events": [f"delivery_event:{row['event_id']}" for row in events] or [f"delivery_events_lookup:{order_id}:{as_of}"],
            "returns_refunds": [f"return:{row['return_id']}" for row in returns] or [f"returns_refunds_lookup:{order_id}:{as_of}"],
        },
        "missing_fields": missing_fields,
        "eligibility_decided": False,
    })


def list_delivery_events_readonly(order_id: str, *, limit: int = 100) -> dict[str, Any]:
    """Read chronological delivery events for one existing order."""
    try:
        with readonly_cursor() as cursor:
            cursor.execute("SELECT order_id FROM orders WHERE order_id = %s LIMIT 1", (order_id,))
            exists = cursor.fetchone() is not None
            if exists:
                cursor.execute(
                    """
                    SELECT event_id, event_type, event_time, location, source
                    FROM delivery_events
                    WHERE order_id = %s
                    ORDER BY event_time, event_id
                    LIMIT %s
                    """,
                    (order_id, limit),
                )
                events = _as_dicts(cursor.fetchall())
            else:
                events = []
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("Delivery-event lookup failed") from exc
    if not exists:
        raise RecordNotFound("Order was not found in the development fixture")
    missing_fields = [] if events else ["delivery_events"]
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _as_json({
        "source_system": "Neon Postgres",
        "as_of": as_of,
        "status": "found" if events else "insufficient_data",
        "order_id": order_id,
        "events": events,
        "evidence_refs": [f"delivery_event:{row['event_id']}" for row in events] or [f"delivery_events_lookup:{order_id}:{as_of}"],
        "missing_fields": missing_fields,
    })


def get_return_refund_status_readonly(order_id: str, *, limit: int = 50) -> dict[str, Any]:
    """Read recorded return/refund state without deciding eligibility."""
    try:
        with readonly_cursor() as cursor:
            cursor.execute("SELECT order_id FROM orders WHERE order_id = %s LIMIT 1", (order_id,))
            exists = cursor.fetchone() is not None
            if exists:
                cursor.execute(
                    """
                    SELECT return_id, item_id, requested_at, status,
                           inspection_status, refund_status, source
                    FROM returns_refunds
                    WHERE order_id = %s
                    ORDER BY requested_at, return_id
                    LIMIT %s
                    """,
                    (order_id, limit),
                )
                returns = _as_dicts(cursor.fetchall())
            else:
                returns = []
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("Return/refund lookup failed") from exc
    if not exists:
        raise RecordNotFound("Order was not found in the development fixture")
    missing_fields = [] if returns else ["return_or_refund_record"]
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _as_json({
        "source_system": "Neon Postgres",
        "as_of": as_of,
        "status": "found" if returns else "insufficient_data",
        "order_id": order_id,
        "returns_refunds": returns,
        "evidence_refs": [f"return:{row['return_id']}" for row in returns] or [f"returns_refunds_lookup:{order_id}:{as_of}"],
        "eligibility_decided": False,
        "missing_fields": missing_fields,
    })
