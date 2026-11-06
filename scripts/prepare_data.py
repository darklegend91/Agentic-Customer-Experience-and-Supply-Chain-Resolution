"""Build deterministic, privacy-minimized Day 2 samples from local fixtures.

This script is offline. It reads data/raw and writes only data/processed and
data/synthetic. It never connects to Neon or Milvus.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_DIR = DATA_ROOT / "raw"
PROCESSED_DIR = DATA_ROOT / "processed"
SYNTHETIC_DIR = DATA_ROOT / "synthetic"
BUILD_VERSION = "day2-data-prep-v1"
EVAL_SEED = 20261102
MIN_CLASS_ROWS = 3
EVAL_PER_CLASS = 2

BUSINESS_INTENTS = (
    "address_change",
    "compensation_request",
    "damaged_item",
    "delivery_delay",
    "delivery_dispute",
    "exchange_request",
    "general_policy",
    "incorrect_item",
    "invoice_request",
    "late_refund",
    "missing_accessory",
    "non_delivery",
    "order_cancellation",
    "order_status",
    "partial_delivery",
    "payment_question",
    "price_difference",
    "product_question",
    "refund_status",
    "return_eligibility",
    "return_pickup",
    "return_status",
    "loyalty_points",
    "reward_expiry",
    "reward_redemption",
)
ROUTING_LABELS = {
    "ambiguous_request",
    "prompt_injection",
    "unauthorised_data_request",
}
EXPECTED_ORDER_STATUSES = {
    "cancelled",
    "delivered",
    "processing",
    "return_initiated",
    "shipped",
}


def read_rows(filename: str) -> list[dict[str, str]]:
    path = RAW_DIR / filename
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def read_optional_rows(filename: str, directory: Path = RAW_DIR) -> list[dict[str, str]]:
    """Read an optional development fixture while remaining compatible with older data."""
    path = directory / filename
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_rows(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value: str | None, field: str, required: bool = False) -> str:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise ValueError(f"Required field is blank: {field}")
    return cleaned


def parse_date(value: str | None, field: str, required: bool = False) -> str:
    raw = clean_text(value, field, required)
    if not raw:
        return ""
    try:
        if "T" in raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date in {field}") from exc


def parse_aware_datetime(value: str | None, field: str, required: bool = False) -> tuple[str, date | None]:
    raw = clean_text(value, field, required)
    if not raw:
        return "", None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO timestamp in {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone offset: {field}")
    local_day = parsed.date()
    normalized = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return normalized, local_day


def parse_decimal(value: str | None, field: str, positive: bool = False) -> Decimal:
    raw = clean_text(value, field, required=True)
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal in {field}") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise ValueError(f"Invalid positive numeric value in {field}")
    return parsed


def decimal_string(value: Decimal, places: int | None = None) -> str:
    if places is not None:
        return f"{value:.{places}f}"
    return format(value.normalize(), "f")


def assert_unique(rows: list[dict], key: str, label: str) -> set[str]:
    values = [clean_text(row.get(key), key, required=True) for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label} identifiers")
    return set(values)


def load_retrieval_cases() -> list[dict]:
    """Read the labeled benchmark constant without importing ML dependencies."""
    path = PROJECT_ROOT / "scripts" / "evaluate_rag_chunks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "BENCHMARK_CASES"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, list) or not value:
                break
            return value
    raise ValueError("Could not find a non-empty retrieval benchmark in evaluate_rag_chunks.py")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _message_signature(value: str) -> str:
    """Normalize ticket wording while excluding opaque entity IDs."""
    text = value.casefold()
    for pattern in (
        r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b",
        r"\bITM-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b",
        r"\bSKU-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b",
        r"\bRTN-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b",
    ):
        text = re.sub(pattern, " <id> ", text, flags=re.IGNORECASE)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _ticket_groups(tickets: list[dict[str, str]], order_customer_by_id: dict[str, str]) -> dict[str, str]:
    """Group linked customer/order records and duplicate templates for split isolation."""
    parent = {str(row["ticket_id"]): str(row["ticket_id"]) for row in tickets}

    def find(ticket_id: str) -> str:
        while parent[ticket_id] != ticket_id:
            parent[ticket_id] = parent[parent[ticket_id]]
            ticket_id = parent[ticket_id]
        return ticket_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            keep, merge = sorted((left_root, right_root))
            parent[merge] = keep

    by_customer: dict[str, str] = {}
    by_message: dict[str, str] = {}
    for row in tickets:
        ticket_id = str(row["ticket_id"])
        order_id = clean_text(row.get("order_id"), "order_id")
        customer_id = order_customer_by_id.get(order_id, "")
        signature = _message_signature(str(row.get("message") or ""))
        for lookup, key in ((by_customer, customer_id), (by_message, signature)):
            if not key:
                continue
            if key in lookup:
                union(ticket_id, lookup[key])
            else:
                lookup[key] = ticket_id
    return {ticket_id: find(ticket_id) for ticket_id in parent}


def main() -> None:
    customers = read_rows("customers.csv")
    orders = read_rows("orders.csv")
    items = read_rows("order_items.csv")
    events = read_rows("delivery_events.csv")
    returns = read_rows("returns_refunds.csv")
    raw_tickets = read_rows("tickets.csv")
    generated_tickets = read_optional_rows("support_context_tickets.csv", SYNTHETIC_DIR)
    tickets = raw_tickets + generated_tickets
    eval_cases = read_rows("evaluation_cases.csv")
    policy_sources = read_rows("policy_sources.csv")
    policy_evidence = read_rows("policy_evidence.csv")
    loyalty_accounts = read_optional_rows("customer_loyalty_accounts.csv", SYNTHETIC_DIR)
    loyalty_transactions = read_optional_rows("loyalty_transactions.csv", SYNTHETIC_DIR)
    customer_communications = read_optional_rows("customer_communications.csv", SYNTHETIC_DIR)

    customer_ids = assert_unique(customers, "customer_id", "customer")
    order_ids = assert_unique(orders, "order_id", "order")
    item_ids = assert_unique(items, "item_id", "order item")
    event_ids = assert_unique(events, "event_id", "delivery event")
    return_ids = assert_unique(returns, "return_id", "return")
    ticket_ids = assert_unique(tickets, "ticket_id", "ticket")
    case_ids = assert_unique(eval_cases, "case_id", "evaluation case")
    source_ids = assert_unique(policy_sources, "source_id", "policy source")
    assert_unique(policy_evidence, "evidence_id", "policy evidence")
    assert_unique(loyalty_accounts, "account_id", "loyalty account")
    assert_unique(loyalty_accounts, "customer_id", "loyalty customer account")
    assert_unique(loyalty_transactions, "event_id", "loyalty event")
    assert_unique(customer_communications, "communication_id", "customer communication")

    customer_by_id = {row["customer_id"].strip(): row for row in customers}
    order_by_id = {row["order_id"].strip(): row for row in orders}
    item_by_id = {row["item_id"].strip(): row for row in items}
    ticket_by_id = {row["ticket_id"].strip(): row for row in tickets}
    order_customer_by_id = {
        row["order_id"].strip(): row["customer_id"].strip()
        for row in orders
    }

    clean_orders: list[dict] = []
    order_day_by_id: dict[str, date] = {}
    for row in orders:
        order_id = clean_text(row.get("order_id"), "order_id", required=True)
        customer_id = clean_text(row.get("customer_id"), "customer_id", required=True)
        if customer_id not in customer_ids:
            raise ValueError("Order references an unknown customer")
        order_day_text = parse_date(row.get("order_date"), "order_date", required=True)
        order_day = date.fromisoformat(order_day_text)
        order_day_by_id[order_id] = order_day
        status = clean_text(row.get("status"), "status", required=True).lower()
        if status not in EXPECTED_ORDER_STATUSES:
            raise ValueError("Order has an unrecognized status")
        estimated = parse_date(row.get("estimated_delivery"), "estimated_delivery")
        actual = parse_date(row.get("actual_delivery"), "actual_delivery")
        if estimated and date.fromisoformat(estimated) < order_day:
            raise ValueError("Estimated delivery precedes order date")
        if actual and date.fromisoformat(actual) < order_day:
            raise ValueError("Actual delivery precedes order date")
        clean_orders.append({
            "order_id": order_id,
            "customer_id": customer_id,
            "order_date": order_day_text,
            "status": status,
            "estimated_delivery": estimated,
            "actual_delivery": actual,
            "seller_type": clean_text(row.get("seller_type"), "seller_type"),
            "marketplace": clean_text(row.get("marketplace"), "marketplace", required=True),
        })

    clean_items: list[dict] = []
    products: dict[str, dict] = {}
    for row in items:
        item_id = clean_text(row.get("item_id"), "item_id", required=True)
        order_id = clean_text(row.get("order_id"), "order_id", required=True)
        if order_id not in order_ids:
            raise ValueError("Order item references an unknown order")
        product_id = clean_text(row.get("product_id"), "product_id", required=True)
        product_name = clean_text(row.get("product_name"), "product_name", required=True)
        category = clean_text(row.get("category"), "category", required=True).lower()
        quantity = parse_decimal(row.get("quantity"), "quantity", positive=True)
        price = parse_decimal(row.get("unit_price_inr"), "unit_price_inr", positive=True)
        condition = clean_text(row.get("condition_reported"), "condition_reported")
        clean_items.append({
            "item_id": item_id,
            "order_id": order_id,
            "product_id": product_id,
            "product_name": product_name,
            "category": category,
            "quantity": decimal_string(quantity),
            "unit_price_inr": decimal_string(price, 2),
            "currency": "INR",
            "condition_reported": condition,
            "condition_source": "customer_or_fixture_report",
        })
        entry = products.setdefault(product_id, {
            "product_id": product_id,
            "product_name": product_name,
            "category": category,
            "observed_item_records": 0,
            "min_observed_unit_price": price,
            "max_observed_unit_price": price,
        })
        if entry["product_name"] != product_name or entry["category"] != category:
            raise ValueError("A product ID maps to inconsistent names or categories")
        entry["observed_item_records"] += 1
        entry["min_observed_unit_price"] = min(entry["min_observed_unit_price"], price)
        entry["max_observed_unit_price"] = max(entry["max_observed_unit_price"], price)

    clean_products = []
    for product_id in sorted(products):
        product = products[product_id]
        clean_products.append({
            "product_id": product_id,
            "product_name": product["product_name"],
            "category": product["category"],
            "observed_item_records": product["observed_item_records"],
            "min_observed_unit_price_inr": decimal_string(product["min_observed_unit_price"], 2),
            "max_observed_unit_price_inr": decimal_string(product["max_observed_unit_price"], 2),
            "price_semantics": "historical order-line price; not a current catalog price",
        })

    clean_events: list[dict] = []
    for row in events:
        event_id = clean_text(row.get("event_id"), "event_id", required=True)
        order_id = clean_text(row.get("order_id"), "order_id", required=True)
        if order_id not in order_ids:
            raise ValueError("Delivery event references an unknown order")
        event_time_utc, local_day = parse_aware_datetime(row.get("event_time"), "event_time", required=True)
        if local_day and local_day < order_day_by_id[order_id]:
            raise ValueError("Delivery event precedes order date")
        clean_events.append({
            "event_id": event_id,
            "order_id": order_id,
            "event_type": clean_text(row.get("event_type"), "event_type", required=True).lower(),
            "event_time_utc": event_time_utc,
            "location": clean_text(row.get("location"), "location"),
            "source": clean_text(row.get("source"), "source"),
        })

    clean_returns: list[dict] = []
    for row in returns:
        return_id = clean_text(row.get("return_id"), "return_id", required=True)
        order_id = clean_text(row.get("order_id"), "order_id", required=True)
        item_id = clean_text(row.get("item_id"), "item_id", required=True)
        if order_id not in order_ids or item_id not in item_ids:
            raise ValueError("Return references an unknown order or item")
        if item_by_id[item_id].get("order_id", "").strip() != order_id:
            raise ValueError("Return item does not belong to its referenced order")
        requested_at_utc, _ = parse_aware_datetime(row.get("requested_at"), "requested_at", required=True)
        clean_returns.append({
            "return_id": return_id,
            "order_id": order_id,
            "item_id": item_id,
            "requested_at_utc": requested_at_utc,
            "status": clean_text(row.get("status"), "status").lower(),
            "inspection_status": clean_text(row.get("inspection_status"), "inspection_status").lower(),
            "refund_status": clean_text(row.get("refund_status"), "refund_status").lower(),
            "source": clean_text(row.get("source"), "source"),
        })

    clean_loyalty_accounts: list[dict] = []
    loyalty_balance_by_customer: dict[str, int] = {}
    for row in loyalty_accounts:
        account_id = clean_text(row.get("account_id"), "account_id", required=True)
        customer_id = clean_text(row.get("customer_id"), "customer_id", required=True)
        if customer_id not in customer_ids:
            raise ValueError("Loyalty account references an unknown customer")
        balance_decimal = parse_decimal(row.get("points_balance"), "points_balance")
        if balance_decimal != balance_decimal.to_integral_value():
            raise ValueError("Loyalty points balance must be an integer")
        points_balance = int(balance_decimal)
        if points_balance < 0:
            raise ValueError("Loyalty account points balance cannot be negative")
        as_of, _ = parse_aware_datetime(row.get("as_of"), "loyalty as_of", required=True)
        clean_loyalty_accounts.append({
            "account_id": account_id,
            "customer_id": customer_id,
            "loyalty_tier": clean_text(row.get("loyalty_tier"), "loyalty_tier", required=True).lower(),
            "points_balance": points_balance,
            "account_status": clean_text(row.get("account_status"), "account_status", required=True).lower(),
            "as_of": as_of,
            "source": clean_text(row.get("source"), "source", required=True),
        })
        loyalty_balance_by_customer[customer_id] = points_balance

    clean_loyalty_transactions: list[dict] = []
    posted_points_by_customer: dict[str, int] = defaultdict(int)
    allowed_loyalty_statuses = {"posted", "pending", "reversed"}
    allowed_loyalty_events = {"points_earned", "reward_redeemed", "points_expired", "points_adjusted"}
    for row in loyalty_transactions:
        event_id = clean_text(row.get("event_id"), "event_id", required=True)
        customer_id = clean_text(row.get("customer_id"), "customer_id", required=True)
        order_id = clean_text(row.get("order_id"), "order_id")
        if customer_id not in customer_ids:
            raise ValueError("Loyalty event references an unknown customer")
        if order_id and (order_id not in order_ids or order_customer_by_id[order_id] != customer_id):
            raise ValueError("Loyalty event order does not belong to its customer")
        occurred_at, _ = parse_aware_datetime(row.get("occurred_at"), "loyalty occurred_at", required=True)
        expires_at = parse_date(row.get("expires_at"), "loyalty expires_at")
        event_type = clean_text(row.get("event_type"), "event_type", required=True).lower()
        status = clean_text(row.get("status"), "status", required=True).lower()
        if event_type not in allowed_loyalty_events or status not in allowed_loyalty_statuses:
            raise ValueError("Loyalty event has an unsupported type or status")
        points_decimal = parse_decimal(row.get("points_delta"), "points_delta")
        if points_decimal != points_decimal.to_integral_value():
            raise ValueError("Loyalty points delta must be an integer")
        points_delta = int(points_decimal)
        if event_type == "points_earned" and points_delta < 0:
            raise ValueError("Earned loyalty points must have a non-negative delta")
        if event_type in {"reward_redeemed", "points_expired"} and points_delta > 0:
            raise ValueError("Redeemed or expired points must have a non-positive delta")
        if status == "posted":
            posted_points_by_customer[customer_id] += points_delta
        clean_loyalty_transactions.append({
            "event_id": event_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "event_type": event_type,
            "points_delta": points_delta,
            "status": status,
            "occurred_at_utc": occurred_at,
            "expires_at": expires_at,
            "reward_code": clean_text(row.get("reward_code"), "reward_code"),
            "source": clean_text(row.get("source"), "source", required=True),
        })
    for customer_id, points_balance in loyalty_balance_by_customer.items():
        if posted_points_by_customer.get(customer_id, 0) != points_balance:
            raise ValueError("Loyalty account balance does not match its posted ledger events")

    clean_customer_communications: list[dict] = []
    email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    phone_pattern = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
    for row in customer_communications:
        communication_id = clean_text(row.get("communication_id"), "communication_id", required=True)
        customer_id = clean_text(row.get("customer_id"), "customer_id", required=True)
        order_id = clean_text(row.get("order_id"), "order_id")
        if customer_id not in customer_ids:
            raise ValueError("Customer communication references an unknown customer")
        if order_id and (order_id not in order_ids or order_customer_by_id[order_id] != customer_id):
            raise ValueError("Customer communication order does not belong to its customer")
        summary = clean_text(row.get("summary"), "summary", required=True)
        if email_pattern.search(summary) or phone_pattern.search(summary):
            raise ValueError("Customer communication summaries must not contain direct contact data")
        occurred_at, _ = parse_aware_datetime(row.get("occurred_at"), "communication occurred_at", required=True)
        clean_customer_communications.append({
            "communication_id": communication_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "channel": clean_text(row.get("channel"), "channel", required=True).lower(),
            "direction": clean_text(row.get("direction"), "direction", required=True).lower(),
            "topic": clean_text(row.get("topic"), "topic", required=True).lower(),
            "summary": summary,
            "occurred_at_utc": occurred_at,
            "outcome": clean_text(row.get("outcome"), "outcome", required=True).lower(),
            "source": clean_text(row.get("source"), "source", required=True),
        })

    clean_tickets: list[dict] = []
    mappings: list[dict] = []
    for row in tickets:
        ticket_id = clean_text(row.get("ticket_id"), "ticket_id", required=True)
        message = clean_text(row.get("message"), "message", required=True)
        intent = clean_text(row.get("expected_intent"), "expected_intent", required=True)
        order_ref = clean_text(row.get("order_id"), "order_id")
        if order_ref and order_ref not in order_ids:
            raise ValueError("Ticket references an unknown order")
        clean_tickets.append({
            "ticket_id": ticket_id,
            "message": message,
            "intent": intent,
            "expected_handling": clean_text(row.get("expected_handling"), "expected_handling"),
        })
        mappings.append({
            "mapping_version": "synthetic-ticket-order-map-v1",
            "ticket_id": ticket_id,
            "order_id": order_ref,
            "mapping_source": "tickets.csv.order_id",
            "mapping_status": "mapped" if order_ref else "unmapped_missing_order_reference",
        })

    intent_counts = Counter(row["intent"] for row in clean_tickets)
    unknown_labels = set(intent_counts) - set(BUSINESS_INTENTS) - ROUTING_LABELS
    if unknown_labels:
        raise ValueError(f"Ticket labels are missing from the documented taxonomy: {sorted(unknown_labels)}")

    ticket_group_by_id = _ticket_groups(tickets, order_customer_by_id)
    groups_by_label: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in clean_tickets:
        if row["intent"] in BUSINESS_INTENTS:
            groups_by_label[row["intent"]][ticket_group_by_id[row["ticket_id"]]].append(row)

    eligible_labels = {
        label for label in BUSINESS_INTENTS
        if len(groups_by_label.get(label, {})) >= MIN_CLASS_ROWS
    }
    rng = random.Random(EVAL_SEED)
    eval_groups_by_label: dict[str, list[str]] = {}
    all_eval_groups: set[str] = set()
    for label in sorted(eligible_labels):
        candidate_groups = sorted(groups_by_label[label])
        rng.shuffle(candidate_groups)
        selected = candidate_groups[:EVAL_PER_CLASS]
        eval_groups_by_label[label] = selected
        all_eval_groups.update(selected)

    model_labels = {
        label for label in eligible_labels
        if any(group not in all_eval_groups for group in groups_by_label[label])
    }
    intent_eval: list[dict] = []
    for label in sorted(model_labels):
        selected_groups = eval_groups_by_label.get(label, [])
        for group in selected_groups:
            group_rows = sorted(groups_by_label[label][group], key=lambda row: row["ticket_id"])
            row = group_rows[0]
            intent_eval.append({
                "evaluation_set_version": "intent-eval-v1",
                "ticket_id": row["ticket_id"],
                "message": row["message"],
                "expected_intent": row["intent"],
            })

    all_group_ticket_ids = {
        row["ticket_id"] for row in clean_tickets
        if ticket_group_by_id[row["ticket_id"]] in all_eval_groups
    }

    classifier_train = [
        {"ticket_id": row["ticket_id"], "message": row["message"], "intent": row["intent"]}
        for row in clean_tickets
        if row["intent"] in model_labels and row["ticket_id"] not in all_group_ticket_ids
    ]
    intent_eval.sort(key=lambda row: (row["expected_intent"], row["ticket_id"]))
    classifier_train.sort(key=lambda row: row["ticket_id"])

    coverage = []
    for label, count in sorted(intent_counts.items()):
        if label in ROUTING_LABELS:
            kind = "triage_or_security_signal"
            status = "exclude_from_intent_classifier"
        elif label not in model_labels:
            kind = "business_intent"
            status = "collect_more_independent_customer_or_template_groups_and_route_to_review"
        else:
            kind = "business_intent"
            status = "eligible_for_group_isolated_baseline_train_and_eval"
        coverage.append({
            "label": label,
            "label_kind": kind,
            "row_count": count,
            "independent_group_count": len(groups_by_label.get(label, {})),
            "classifier_status": status,
        })

    cases_by_ticket = {row["ticket_id"].strip(): row for row in eval_cases}
    workflow_eval = []
    for case in sorted(eval_cases, key=lambda row: row["case_id"]):
        ticket_id = clean_text(case.get("ticket_id"), "evaluation ticket_id", required=True)
        if ticket_id not in ticket_by_id:
            raise ValueError("Workflow evaluation case references an unknown ticket")
        ticket = ticket_by_id[ticket_id]
        workflow_eval.append({
            "evaluation_set_version": "workflow-security-eval-v1",
            "case_id": clean_text(case.get("case_id"), "case_id", required=True),
            "ticket_id": ticket_id,
            "message": clean_text(ticket.get("message"), "message", required=True),
            "expected_intent": clean_text(case.get("expected_intent"), "expected_intent"),
            "expected_route": clean_text(case.get("expected_route"), "expected_route"),
            "expected_outcome": clean_text(case.get("expected_outcome"), "expected_outcome"),
            "security_tag": clean_text(case.get("security_tag"), "security_tag"),
        })

    retrieval_cases = load_retrieval_cases()
    retrieval_eval = []
    for index, case in enumerate(retrieval_cases, start=1):
        retrieval_eval.append({
            "evaluation_set_version": "retrieval-eval-v1",
            "case_id": f"RAG-{index:02d}",
            "query": clean_text(case.get("query"), "retrieval query", required=True),
            "target_marketplace": clean_text(case.get("target_marketplace"), "target_marketplace", required=True),
            "expected_document_id": clean_text(case.get("expected_doc"), "expected_doc", required=True),
            "expected_page": case.get("expected_page"),
            "expected_policy_version": "",
            "version_label_status": "unavailable_in_current_milvus_schema",
        })

    normalized_sources = []
    for row in policy_sources:
        normalized_sources.append({
            "source_id": clean_text(row.get("source_id"), "source_id", required=True),
            "marketplace": clean_text(row.get("marketplace"), "marketplace", required=True),
            "source_url": clean_text(row.get("source_url"), "source_url", required=True),
            "source_type": clean_text(row.get("source_type"), "source_type"),
            "observed_on": parse_date(row.get("observed_on"), "observed_on"),
            "intended_use": clean_text(row.get("use"), "use"),
            "source_review_note": clean_text(row.get("verification_status"), "verification_status"),
            "publication_status": "excluded_wrong_marketplace" if row.get("marketplace") == "Amazon.com" else "review_required",
        })
    evidence_source_ids = {row["source_id"].strip() for row in policy_evidence}
    if not evidence_source_ids.issubset(source_ids):
        raise ValueError("Policy evidence references an unknown policy source")

    write_rows(
        PROCESSED_DIR / "clean_orders.csv",
        clean_orders,
        ["order_id", "customer_id", "order_date", "status", "estimated_delivery", "actual_delivery", "seller_type", "marketplace"],
    )
    write_rows(
        PROCESSED_DIR / "clean_order_items.csv",
        clean_items,
        ["item_id", "order_id", "product_id", "product_name", "category", "quantity", "unit_price_inr", "currency", "condition_reported", "condition_source"],
    )
    write_rows(
        PROCESSED_DIR / "clean_products.csv",
        clean_products,
        ["product_id", "product_name", "category", "observed_item_records", "min_observed_unit_price_inr", "max_observed_unit_price_inr", "price_semantics"],
    )
    write_rows(
        PROCESSED_DIR / "clean_delivery_events.csv",
        clean_events,
        ["event_id", "order_id", "event_type", "event_time_utc", "location", "source"],
    )
    write_rows(
        PROCESSED_DIR / "clean_returns_refunds.csv",
        clean_returns,
        ["return_id", "order_id", "item_id", "requested_at_utc", "status", "inspection_status", "refund_status", "source"],
    )
    write_rows(
        PROCESSED_DIR / "clean_customer_loyalty_accounts.csv",
        clean_loyalty_accounts,
        ["account_id", "customer_id", "loyalty_tier", "points_balance", "account_status", "as_of", "source"],
    )
    write_rows(
        PROCESSED_DIR / "clean_loyalty_transactions.csv",
        clean_loyalty_transactions,
        ["event_id", "customer_id", "order_id", "event_type", "points_delta", "status", "occurred_at_utc", "expires_at", "reward_code", "source"],
    )
    write_rows(
        PROCESSED_DIR / "clean_customer_communications.csv",
        clean_customer_communications,
        ["communication_id", "customer_id", "order_id", "channel", "direction", "topic", "summary", "occurred_at_utc", "outcome", "source"],
    )
    write_rows(
        PROCESSED_DIR / "classifier_train.csv",
        classifier_train,
        ["ticket_id", "message", "intent"],
    )
    write_rows(
        PROCESSED_DIR / "intent_evaluation.csv",
        intent_eval,
        ["evaluation_set_version", "ticket_id", "message", "expected_intent"],
    )
    write_rows(
        PROCESSED_DIR / "intent_label_coverage.csv",
        coverage,
        ["label", "label_kind", "row_count", "independent_group_count", "classifier_status"],
    )
    write_rows(
        PROCESSED_DIR / "workflow_security_evaluation.csv",
        workflow_eval,
        ["evaluation_set_version", "case_id", "ticket_id", "message", "expected_intent", "expected_route", "expected_outcome", "security_tag"],
    )
    write_rows(
        PROCESSED_DIR / "retrieval_evaluation.csv",
        retrieval_eval,
        ["evaluation_set_version", "case_id", "query", "target_marketplace", "expected_document_id", "expected_page", "expected_policy_version", "version_label_status"],
    )
    write_rows(
        PROCESSED_DIR / "policy_source_review.csv",
        normalized_sources,
        ["source_id", "marketplace", "source_url", "source_type", "observed_on", "intended_use", "source_review_note", "publication_status"],
    )
    write_rows(
        SYNTHETIC_DIR / "ticket_order_mapping.csv",
        mappings,
        ["mapping_version", "ticket_id", "order_id", "mapping_source", "mapping_status"],
    )

    source_files = sorted(RAW_DIR.glob("*.csv")) + [
        SYNTHETIC_DIR / filename for filename in (
            "customer_loyalty_accounts.csv",
            "loyalty_transactions.csv",
            "customer_communications.csv",
            "support_context_tickets.csv",
        ) if (SYNTHETIC_DIR / filename).exists()
    ]
    manifest = {
        "build_version": BUILD_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fixture_provenance": "generated fictional development/evaluation data",
        "source_files_sha256": {
            path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path) for path in source_files
        },
        "source_row_counts": {
            "customers": len(customers),
            "orders": len(orders),
            "order_items": len(items),
            "delivery_events": len(events),
            "returns_refunds": len(returns),
            "customer_loyalty_accounts": len(loyalty_accounts),
            "loyalty_transactions": len(loyalty_transactions),
            "customer_communications": len(customer_communications),
            "raw_tickets": len(raw_tickets),
            "synthetic_support_tickets": len(generated_tickets),
            "tickets_total": len(tickets),
            "evaluation_cases": len(eval_cases),
            "policy_sources": len(policy_sources),
            "policy_evidence": len(policy_evidence),
        },
        "output_row_counts": {
            "clean_orders": len(clean_orders),
            "clean_order_items": len(clean_items),
            "clean_products": len(clean_products),
            "clean_delivery_events": len(clean_events),
            "clean_returns_refunds": len(clean_returns),
            "clean_customer_loyalty_accounts": len(clean_loyalty_accounts),
            "clean_loyalty_transactions": len(clean_loyalty_transactions),
            "clean_customer_communications": len(clean_customer_communications),
            "classifier_train": len(classifier_train),
            "intent_evaluation": len(intent_eval),
            "workflow_security_evaluation": len(workflow_eval),
            "retrieval_evaluation": len(retrieval_eval),
            "policy_source_review": len(normalized_sources),
            "ticket_order_mapping": len(mappings),
        },
        "classifier_eval_labels": sorted(model_labels),
        "classifier_split": {
            "grouping": "linked_customer_or_normalized_message_template",
            "evaluation_groups_per_label": EVAL_PER_CLASS,
            "evaluation_ticket_count": len(intent_eval),
            "train_evaluation_group_overlap": False,
        },
        "classifier_labels_needing_more_data": sorted(
            label for label in BUSINESS_INTENTS if intent_counts.get(label, 0) < MIN_CLASS_ROWS
        ),
        "validation": {
            "unique_primary_ids": True,
            "customer_order_item_event_return_ticket_links": True,
            "evaluation_case_ticket_links": True,
            "policy_evidence_source_links": True,
            "order_dates_and_delivery_event_ordering": True,
            "positive_quantity_and_price": True,
            "email_and_full_name_exported": False,
            "return_eligibility_carried_into_clean_items": False,
            "unmapped_tickets": sum(1 for row in mappings if row["mapping_status"] != "mapped"),
        },
    }
    manifest_path = PROCESSED_DIR / "data_quality_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Day 2 preparation complete: {len(clean_orders)} orders, {len(clean_items)} order items, {len(clean_products)} products")
    print(f"Intent evaluation: {len(intent_eval)} cases across {len(model_labels)} supported baseline labels")
    print(f"Workflow/security evaluation: {len(workflow_eval)}; retrieval evaluation: {len(retrieval_eval)}")
    print(f"Ticket/order mapping: {len(mappings)} tickets, {manifest['validation']['unmapped_tickets']} without an order reference")
    print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
