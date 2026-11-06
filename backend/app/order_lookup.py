"""Read-only, allowlisted Neon order lookup for the local development fixture."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class OrderNotFoundError(LookupError):
    pass


class OrderDatabaseUnavailable(RuntimeError):
    pass


def _load_environment() -> None:
    for path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def lookup_order_readonly(order_id: str) -> dict[str, Any]:
    """Return a bounded allowlist of order facts; never return customer PII."""
    _load_environment()
    # Fail closed: a missing environment setting must never enable a dev-only lookup.
    environment = os.getenv("APP_ENV", "").strip().lower()
    if environment not in {"local", "dev", "development"}:
        raise OrderDatabaseUnavailable("The development order lookup is disabled outside local development")
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise OrderDatabaseUnavailable("DATABASE_URL is not configured")

    connection = None
    cursor = None
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        connection = psycopg2.connect(
            dsn,
            sslmode="require",
            connect_timeout=8,
            application_name="agentic-customer-support-dev-readonly",
        )
        connection.set_session(readonly=True, autocommit=False)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

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
        order = cursor.fetchone()
        if order is None:
            raise OrderNotFoundError("Order was not found in the development fixture")

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
        items = cursor.fetchall()

        cursor.execute(
            """
            SELECT event_id, event_type, event_time, location, source
            FROM delivery_events
            WHERE order_id = %s
            ORDER BY event_time, event_id
            LIMIT 100
            """,
            (order_id,),
        )
        events = cursor.fetchall()

        cursor.execute(
            """
            SELECT return_id, item_id, requested_at, status,
                   inspection_status, refund_status, source
            FROM returns_refunds
            WHERE order_id = %s
            ORDER BY requested_at, return_id
            LIMIT 50
            """,
            (order_id,),
        )
        returns = cursor.fetchall()

        return {
            "source_system": "Neon Postgres",
            "as_of": as_of,
            "status": "found",
            "order": _json_safe(dict(order)),
            "items": _json_safe([dict(row) for row in items]),
            "delivery_events": _json_safe([dict(row) for row in events]),
            "returns_refunds": _json_safe([dict(row) for row in returns]),
            "evidence_refs": {
                "order": [f"order:{order_id}"],
                "items": [f"item:{row['item_id']}" for row in items],
                "delivery_events": [f"delivery_event:{row['event_id']}" for row in events],
                "returns_refunds": [f"return:{row['return_id']}" for row in returns],
            },
        }
    except OrderNotFoundError:
        raise
    except Exception as exc:
        # Do not return DSNs, SQL details, or driver exception text to the API caller.
        raise OrderDatabaseUnavailable("Neon read-only order lookup failed") from exc
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()
