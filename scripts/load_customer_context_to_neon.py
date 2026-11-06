"""Idempotently seed synthetic customer-context fixtures into a development DB.

This script never drops or truncates tables. It requires an explicit opt-in and
a separate write-enabled development connection string. The API continues to
use DATABASE_URL through read-only transactions.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    load_dotenv(ROOT / ".env", override=False)
    if os.getenv("APP_ENV", "").strip().lower() not in {"local", "dev", "development"}:
        raise SystemExit("Refusing to seed outside APP_ENV=local")
    if os.getenv("ALLOW_DEVELOPMENT_CONTEXT_SEED", "").strip().lower() != "true":
        raise SystemExit("Set ALLOW_DEVELOPMENT_CONTEXT_SEED=true after reviewing the development target")
    dsn = os.getenv("CUSTOMER_CONTEXT_WRITE_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("Set CUSTOMER_CONTEXT_WRITE_DATABASE_URL to the development branch only")

    accounts = read_rows(PROCESSED / "clean_customer_loyalty_accounts.csv")
    transactions = read_rows(PROCESSED / "clean_loyalty_transactions.csv")
    communications = read_rows(PROCESSED / "clean_customer_communications.csv")
    connection = psycopg2.connect(dsn, sslmode="require", connect_timeout=5)
    try:
        with connection:
            with connection.cursor() as cursor:
                if accounts:
                    execute_values(cursor, """
                        INSERT INTO customer_loyalty_accounts
                            (account_id, customer_id, loyalty_tier, points_balance, account_status, as_of, source)
                        VALUES %s
                        ON CONFLICT (account_id) DO UPDATE SET
                            loyalty_tier = EXCLUDED.loyalty_tier,
                            points_balance = EXCLUDED.points_balance,
                            account_status = EXCLUDED.account_status,
                            as_of = EXCLUDED.as_of,
                            source = EXCLUDED.source
                    """, [tuple(row[k] for k in ("account_id", "customer_id", "loyalty_tier", "points_balance", "account_status", "as_of", "source")) for row in accounts])
                if transactions:
                    execute_values(cursor, """
                        INSERT INTO loyalty_transactions
                            (event_id, customer_id, order_id, event_type, points_delta, status, occurred_at, expires_at, reward_code, source)
                        VALUES %s
                        ON CONFLICT (event_id) DO UPDATE SET
                            points_delta = EXCLUDED.points_delta,
                            status = EXCLUDED.status,
                            occurred_at = EXCLUDED.occurred_at,
                            expires_at = EXCLUDED.expires_at,
                            reward_code = EXCLUDED.reward_code,
                            source = EXCLUDED.source
                    """, [tuple(row[k] or None for k in ("event_id", "customer_id", "order_id", "event_type", "points_delta", "status", "occurred_at_utc", "expires_at", "reward_code", "source")) for row in transactions])
                if communications:
                    execute_values(cursor, """
                        INSERT INTO customer_communications
                            (communication_id, customer_id, order_id, channel, direction, topic, summary, occurred_at, outcome, source)
                        VALUES %s
                        ON CONFLICT (communication_id) DO UPDATE SET
                            channel = EXCLUDED.channel,
                            direction = EXCLUDED.direction,
                            topic = EXCLUDED.topic,
                            summary = EXCLUDED.summary,
                            occurred_at = EXCLUDED.occurred_at,
                            outcome = EXCLUDED.outcome,
                            source = EXCLUDED.source
                    """, [tuple(row[k] or None for k in ("communication_id", "customer_id", "order_id", "channel", "direction", "topic", "summary", "occurred_at_utc", "outcome", "source")) for row in communications])
    finally:
        connection.close()
    print(f"Seeded/updated {len(accounts)} loyalty accounts, {len(transactions)} ledger rows, and {len(communications)} communication summaries.")


if __name__ == "__main__":
    main()
