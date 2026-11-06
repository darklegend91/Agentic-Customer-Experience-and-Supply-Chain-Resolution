"""Generate synthetic loyalty, prior-contact, and loyalty-intent ticket fixtures.

This script reads the existing fictional customer/order fixtures and writes
only namespaced synthetic CSVs under data/synthetic/. It never connects to a
database or modifies source files under data/raw/.
"""

from __future__ import annotations

import csv
import hashlib
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SYNTHETIC_DIR = PROJECT_ROOT / "data" / "synthetic"
SEED = 20261106


def read_csv(name: str) -> list[dict[str, str]]:
    with (RAW_DIR / name).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty fixture: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def stable_id(kind: str, value: str) -> str:
    return hashlib.blake2s(f"{kind}:{value}".encode(), digest_size=6).hexdigest().upper()


def iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> None:
    rng = random.Random(SEED)
    customers = read_csv("customers.csv")
    orders = read_csv("orders.csv")
    items = read_csv("order_items.csv")
    tickets = read_csv("tickets.csv")
    if not customers or not orders:
        raise ValueError("Generate the base demo data before support-context fixtures")

    customer_by_id = {row["customer_id"]: row for row in customers}
    orders_by_customer: dict[str, list[dict[str, str]]] = {}
    for order in orders:
        orders_by_customer.setdefault(order["customer_id"], []).append(order)
    items_by_order: dict[str, list[dict[str, str]]] = {}
    for item in items:
        items_by_order.setdefault(item["order_id"], []).append(item)

    # Refresh the fixture snapshot time so freshness checks work in local demos.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    accounts: list[dict[str, object]] = []
    transactions: list[dict[str, object]] = []
    communications: list[dict[str, object]] = []

    summaries = {
        "delivery_delay": [
            "Customer asked for a shipment update; support shared the latest recorded delivery scan.",
            "Customer reported a delayed parcel; case was left open pending another carrier event.",
        ],
        "damaged_item": [
            "Customer reported visible item damage; no remedy was promised pending policy review.",
            "Support asked which item was affected and recorded the customer's damage description.",
        ],
        "return_status": [
            "Customer asked about a return; support shared the recorded return status.",
            "Customer requested a return update; no eligibility decision was recorded.",
        ],
        "order_status": [
            "Customer requested an order update; support reported the status available at that time.",
            "Customer asked whether the parcel had shipped; support cited the latest order record.",
        ],
        "general": [
            "Customer contacted support with a general order question; case was marked resolved.",
            "Customer asked for help; support requested an order reference for further investigation.",
        ],
    }
    channels = ["web", "email", "phone", "chat"]
    scenario_topic = {
        "delivery_delay": "delivery_update",
        "damaged_item": "damaged_item_report",
        "return_status": "return_question",
        "return_pickup": "return_question",
        "order_status": "order_status",
        "order_cancellation": "order_status",
        "non_delivery": "delivery_update",
        "partial_delivery": "delivery_update",
    }
    outcomes = ["information_provided", "awaiting_customer", "escalated", "resolved"]

    for index, customer in enumerate(customers, start=1):
        customer_id = customer["customer_id"]
        customer_orders = orders_by_customer.get(customer_id, [])
        order = customer_orders[0] if customer_orders else None
        order_id = order["order_id"] if order else ""
        customer_items = items_by_order.get(order_id, [])
        account_id = f"LOY-{stable_id('account', customer_id)}"

        # A synthetic earning mirrors an order-level rewards event. Its ledger
        # balance is derived from posted transactions rather than invented by a rule.
        total_inr = sum(int(float(item.get("unit_price_inr") or 0) * float(item.get("quantity") or 1)) for item in customer_items)
        earned = max(0, total_inr // 100) if order and order.get("status") in {"delivered", "return_initiated"} else 0
        order_day = date.fromisoformat(order["order_date"]) if order else now.date()
        earned_at = datetime(order_day.year, order_day.month, order_day.day, 10, tzinfo=timezone.utc) + timedelta(days=1)
        expiry = date(2026, 12, 31) if index % 7 == 0 else date(2027, 12, 31)
        ledger: list[dict[str, object]] = []
        if earned:
            ledger.append({
                "event_id": f"LTX-{stable_id('earn', order_id or customer_id)}",
                "customer_id": customer_id,
                "order_id": order_id,
                "event_type": "points_earned",
                "points_delta": earned,
                "status": "posted",
                "occurred_at": iso_time(earned_at),
                "expires_at": expiry.isoformat(),
                "reward_code": "",
                "source": "synthetic_rewards_ledger",
            })
        if index % 9 == 0 and earned >= 10:
            redeemed = max(1, earned // 4)
            redemption_time = earned_at + timedelta(days=14)
            ledger.append({
                "event_id": f"LTX-{stable_id('redeem', order_id or customer_id)}",
                "customer_id": customer_id,
                "order_id": order_id,
                "event_type": "reward_redeemed",
                "points_delta": -redeemed,
                "status": "posted",
                "occurred_at": iso_time(redemption_time),
                "expires_at": "",
                "reward_code": f"RWD-{stable_id('reward', customer_id)}",
                "source": "synthetic_rewards_ledger",
            })
        transactions.extend(ledger)
        balance = sum(int(row["points_delta"]) for row in ledger if row["status"] == "posted")
        accounts.append({
            "account_id": account_id,
            "customer_id": customer_id,
            "loyalty_tier": customer.get("loyalty_tier", "standard"),
            "points_balance": balance,
            "account_status": "active",
            "as_of": iso_time(now),
            "source": "synthetic_rewards_ledger",
        })

        count = 1 + (index % 3 == 0)
        issue = (order or {}).get("scenario", "general")
        templates = summaries.get(issue, summaries["general"])
        for contact_index in range(int(count)):
            prior = (order_day + timedelta(days=2 + contact_index * 3)) if order else now.date()
            # Historical conversations can never be newer than the snapshot time.
            contact_dt = datetime(prior.year, prior.month, prior.day, 14, tzinfo=timezone.utc)
            contact_dt = min(contact_dt, now - timedelta(minutes=contact_index + 1))
            topic = scenario_topic.get(issue, "general_support")
            communications.append({
                "communication_id": f"COM-{stable_id('comm', f'{customer_id}:{contact_index}')}",
                "customer_id": customer_id,
                "order_id": order_id,
                "channel": rng.choice(channels),
                "direction": "inbound_and_response",
                "topic": topic,
                "summary": templates[(index + contact_index) % len(templates)],
                "occurred_at": iso_time(contact_dt),
                "outcome": rng.choice(outcomes),
                "source": "synthetic_support_history",
            })

    if not transactions:
        raise ValueError("No synthetic loyalty transactions were generated")

    # Add balanced natural-language examples for the three supported loyalty
    # intents. They are synthetic evaluation/training material, not customer data.
    loyalty_phrases = {
        "loyalty_points": [
            "How many reward points did I earn for this order?",
            "My loyalty points are missing from my account.",
            "Please check the points balance related to this purchase.",
            "I cannot see the points for my recent order.",
            "Can you tell me the recorded rewards points balance?",
            "The points from this purchase have not appeared yet.",
        ],
        "reward_expiry": [
            "When will my reward points expire?",
            "I think some points are about to expire; please check the ledger.",
            "Which of my loyalty points are due to expire soon?",
            "Can you look up the expiration date for my points?",
            "My rewards balance shows points expiring; what is recorded?",
            "Please tell me if any points in my account are expiring.",
        ],
        "reward_redemption": [
            "My reward redemption is not showing in the account.",
            "Please check the recorded status of my rewards redemption.",
            "I redeemed points but did not get the reward; can you look it up?",
            "Can I use points for this reward, and what does the policy say?",
            "The reward I selected has not appeared in my account.",
            "I need help checking a points redemption.",
        ],
    }
    existing_by_id = {row["ticket_id"]: row for row in tickets}
    available_orders = orders[:]
    rng.shuffle(available_orders)
    new_tickets: list[dict[str, str]] = []
    ticket_prefix = {
        "loyalty_points": "LOY",
        "reward_expiry": "EXP",
        "reward_redemption": "RED",
    }
    for intent_index, (intent, phrases) in enumerate(loyalty_phrases.items()):
        for n in range(60):
            order = available_orders[(n + intent_index * 60) % len(available_orders)]
            ticket_id = f"T-CTX-{ticket_prefix[intent]}-{n + 1:03d}"
            message = f"{phrases[n % len(phrases)]} Order {order['order_id']}."
            candidate = {
                "ticket_id": ticket_id,
                "message": message,
                "expected_intent": intent,
                "order_id": order["order_id"],
                "expected_handling": {
                    "loyalty_points": "read_rewards_ledger_and_report_recorded_balance",
                    "reward_expiry": "read_expiry_events_and_escalate_policy_questions",
                    "reward_redemption": "read_redemption_status_and_escalate_eligibility",
                }[intent],
            }
            existing = existing_by_id.get(ticket_id)
            if existing is not None:
                if any(str(existing.get(key, "")) != str(value) for key, value in candidate.items()):
                    raise ValueError(f"Synthetic ticket ID collision with different content: {ticket_id}")
                continue
            new_tickets.append(candidate)
            existing_by_id[ticket_id] = candidate
    write_csv(SYNTHETIC_DIR / "customer_loyalty_accounts.csv", accounts)
    write_csv(SYNTHETIC_DIR / "loyalty_transactions.csv", transactions)
    write_csv(SYNTHETIC_DIR / "customer_communications.csv", communications)
    write_csv(SYNTHETIC_DIR / "support_context_tickets.csv", new_tickets)
    print(f"Wrote {len(accounts)} loyalty accounts, {len(transactions)} loyalty events, "
          f"{len(communications)} communication summaries, and {len(new_tickets)} synthetic loyalty tickets.")


if __name__ == "__main__":
    main()
