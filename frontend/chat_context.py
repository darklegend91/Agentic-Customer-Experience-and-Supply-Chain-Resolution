"""Resolve ticket, order, and customer references for the investigation chat."""

from __future__ import annotations

import csv
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ORDERS_CSV = PROJECT_ROOT / "data" / "processed" / "clean_orders.csv"

_ORDER_ID = re.compile(r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", re.IGNORECASE)
_CUSTOMER_ID = re.compile(r"(?<![\w-])CUS-[0-9A-F]{10}(?![\w-])", re.IGNORECASE)
_TICKET_ID_PATTERN = r"T-(?:CTX-[A-Z]+-)?[0-9]+"
_TICKET_ID = re.compile(rf"(?<![\w-]){_TICKET_ID_PATTERN}(?![\w-])", re.IGNORECASE)
_TICKET_LOOKUP = re.compile(
    rf"(?:(?:tell me (?:more )?about|show(?: me)?|look up|investigate|check|open|what is)\s+)?"
    rf"(?:(?:(?:the\s+)?ticket(?:\s+id)?(?:\s*[:#]\s*|\s+))?{_TICKET_ID_PATTERN}|(?:this\s+|the\s+)?ticket)"
    rf"(?:\s+(?:details|about))?",
    re.IGNORECASE,
)
_NEW_TICKET_QUESTION = r"(?:are there |do i have |show(?: me)? |list )?(?:any )?new (?:support )?tickets"
_OTHER_RECORD_QUESTION = r"(?:what happened to |what about |how about |check |look up )?(?:the )?other "
_CONTEXT_QUESTIONS = {
    "ticket_id": (
        r"(?:what(?: is|'s) |tell me |give me |remind me (?:of )?)?(?:my |the |this )?ticket (?:id|number)"
        r"(?: i (?:gave you|shared with you))?|which ticket is this"
        r"|(?:remind me )?which ticket (?:i gave you|did i give you)"
    ),
    "order_tickets": (
        r"(?:(?:show |show me |list |what are )?(?:all )?(?:the )?tickets (?:for|on|linked to)"
        r"|what tickets are linked to) (?:this |the |my )?order"
    ),
    "tickets": (
        r"(?:list |show |show me |what are )?(?:all )?(?:my |this customer's )?(?:support )?tickets"
        r"|what tickets do i have"
    ),
    "order_id": (
        r"(?:what(?: is|'s) |tell me |give me |remind me (?:of )?)?(?:my |the |this )?(?:linked )?order (?:id|number)"
        r"|which order is this ticket (?:for|linked to)|which order are we looking at"
    ),
    "other_orders": (
        r"(?:list |show |show me |what are )?(?:my |the )?other orders"
        r"|what other orders do i have|do i have any other orders"
    ),
    "orders": (
        r"(?:list |show |show me |tell me |what are )?(?:all )?(?:my |this customer's )?orders"
        r"(?: (?:for|of) (?:this |the )?customer)?|(?:my )?order history|what orders do i have|what are my order"
    ),
    "order_count": (
        r"how (?:many|may) (?:total )?orders (?:do i have|have i placed|does (?:this |the )?customer have)"
        r"(?: (?:on|for) (?:this |the )?customer)?"
    ),
    "order_contents": (
        r"what (?:do|does|did) (?:my |the |this )?order (?:contain|include)"
        r"|what(?: is|'s) (?:in|inside) (?:my |the |this )?order"
        r"|what (?:items|products) (?:are|were) in (?:my |the |this )?order"
        r"|(?:show(?: me)?|list) (?:the )?(?:items|contents) (?:in|of|for) (?:my |the |this )?order"
    ),
    "order_details": (
        r"(?:tell me|give me|show(?: me)?) (?:the )?(?:full )?details (?:of|for|about) (?:my |the |this )?order"
    ),
    "customer_id": (
        r"(?:what(?: is|'s) |tell me |give me |remind me (?:of )?)?(?:my |the |this )?customer (?:id|number)"
        r"|which customer is this order for|which customer are we looking at"
    ),
    "customer": (
        r"(?:tell me about |show me |show |what are )?(?:my |this |the )?"
        r"(?:customer (?:details|data|profile)|account (?:details|profile))|tell me about (?:this|the) customer"
    ),
    "new_tickets": _NEW_TICKET_QUESTION,
    "new_order_tickets": _NEW_TICKET_QUESTION + r" (?:for|on) (?:my |this |the )?order",
    "current_tickets": (
        r"refresh (?:my |the )?(?:tickets|ticket list)|(?:show(?: me)? |list )?(?:my |the )?(?:current|latest) tickets"
    ),
    "current_orders": (
        r"refresh (?:my |the )?(?:orders|order list)|(?:show(?: me)? |list )?(?:my |the )?(?:current|latest) orders"
    ),
    "current_order_status": (
        r"(?:what(?: is|'s) |show(?: me)? |check )?"
        r"(?:(?:the )?(?:current|latest) status of (?:my |this |the )?order"
        r"|(?:my |this |the )?(?:current|latest) order status)"
    ),
    "other_record": _OTHER_RECORD_QUESTION + "one",
    "other_ticket": _OTHER_RECORD_QUESTION + "ticket",
    "other_order": _OTHER_RECORD_QUESTION + "order",
}
_OTHER_RECORD_QUESTIONS = {"other_record", "other_ticket", "other_order"}
_ORDER_DETAIL_QUESTIONS = {"order_contents", "order_details"}
_FRESH_CONTEXT_QUESTIONS = {"new_tickets", "new_order_tickets", "current_tickets", "current_orders", "current_order_status"} | _ORDER_DETAIL_QUESTIONS
_CONTEXT_LIST_QUESTIONS = {"tickets", "order_tickets", "orders", "other_orders", "customer", "order_count"}
_CONTEXT_REFRESH_INTERVAL_SECONDS = 60
_LOOKUP_WORD_CORRECTIONS = {"ehat": "what", "cutomer": "customer", "ell": "tell", "bout": "about", "'bout": "about"}
_CONTEXT_QUESTION_WORDS = {"customer", "ticket", "tickets", "order", "orders", "details", "contain", "contents", "items"}

_OrderMappings = tuple[dict[str, str], dict[str, dict[str, str]]]


@lru_cache(maxsize=1)
def _read_order_mappings(path: Path) -> _OrderMappings:
    order_to_customer: dict[str, str] = {}
    customer_orders: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            order_id = (row.get("order_id") or "").strip()
            customer_id = (row.get("customer_id") or "").strip().upper()
            if order_id and customer_id:
                order_to_customer[order_id.upper()] = customer_id
                customer_orders.setdefault(customer_id, {})[order_id] = (row.get("order_date") or "").strip()
    return order_to_customer, customer_orders


def _order_mappings() -> _OrderMappings:
    try:
        return _read_order_mappings(_ORDERS_CSV)
    except Exception:
        logger.exception("Failed to load order-to-customer mappings from %s", _ORDERS_CSV)
        return {}, {}


def find_customer_for_order(order_id: str | None) -> str | None:
    """Return the customer linked to an order in the local fixture."""
    if not order_id:
        return None
    order_to_customer, _ = _order_mappings()
    return order_to_customer.get(order_id.strip().upper())


def find_latest_order_for_customer(customer_id: str | None) -> str | None:
    """Return the most recent linked order ID for a given customer ID, if known."""
    if not customer_id:
        return None
    _, customer_orders = _order_mappings()
    orders = customer_orders.get(customer_id.strip().upper(), {})
    return max(orders, key=orders.__getitem__, default=None)


def find_all_orders_for_customer(customer_id: str | None) -> list[str]:
    """Return all known linked orders for a given customer ID."""
    if not customer_id:
        return []
    _, customer_orders = _order_mappings()
    return list(customer_orders.get(customer_id.strip().upper(), {}))


def _normalize_lookup_wording(message: str) -> str:
    text = message.casefold().replace("’", "'").replace("`", " ")
    text = " ".join(text.split()).strip(" ?.!,:#\\")
    text = re.sub(r"^(?:(?:ok(?:ay)?|so|please|(?:can|could|would) you)[,. ]+)+", "", text)
    return " ".join(_LOOKUP_WORD_CORRECTIONS.get(word, word) for word in text.split())


def resolve_ticket_context(message: str, manual_ticket_id: str = "") -> tuple[str | None, bool]:
    """Identify the ticket and whether the turn asks to use its stored report."""
    references = {match.upper() for match in _TICKET_ID.findall(message)}
    if len(references) > 1:
        raise ValueError("Please provide one ticket ID at a time.")
    reference = next(iter(references), None)
    selected = manual_ticket_id.strip().upper()
    if reference and selected and reference != selected:
        raise ValueError("The ticket ID in your message differs from the selected ticket. Please use one ticket ID.")
    ticket_id = reference or selected or None
    lookup = _TICKET_LOOKUP.fullmatch(_normalize_lookup_wording(message)) is not None
    return ticket_id, lookup


def _canonical_order_id(value: str) -> str:
    value = value.strip()
    match = re.fullmatch(r"ord-id-([0-9a-f]{10})", value, re.IGNORECASE)
    return "ORD-ID-" + match[1].lower() if match else value


def resolve_chat_references(
    message: str,
    *,
    manual_ticket_id: str,
    manual_order_id: str,
    manual_customer_id: str,
    active_customer_id: str | None,
) -> tuple[dict[str, str | None], bool]:
    """Select explicit references for verification without inheriting an unrelated order."""
    orders = {_canonical_order_id(match) for match in _ORDER_ID.findall(message)}
    customers = {match.upper() for match in _CUSTOMER_ID.findall(message)}
    if len(orders) > 1 or len(customers) > 1:
        raise ValueError("Please provide one order ID and one customer ID at a time.")
    order = next(iter(orders), None)
    customer = next(iter(customers), None)
    manual_customer = manual_customer_id.strip().upper() or None
    if len({cid for cid in (active_customer_id, manual_customer, customer) if cid}) > 1:
        raise ValueError("This chat has a different active customer. Use Clear context to switch customers.")
    customer = active_customer_id or manual_customer or customer
    selected_order = _canonical_order_id(manual_order_id) or None
    if order and selected_order and order != selected_order:
        raise ValueError("The order ID in your message differs from the selected order. Please use one order ID.")
    ticket, lookup = resolve_ticket_context(message, "" if order and not _TICKET_ID.search(message) else manual_ticket_id)
    order = order or selected_order
    return {"ticket_id": ticket, "order_id": order, "customer_id": customer}, lookup


def tickets_for_active_order(context: dict[str, Any]) -> list[dict[str, Any]]:
    order_id = context.get("order_id")
    return [ticket for ticket in context.get("tickets", []) if not order_id or ticket.get("order_id") == order_id]


def _one_edit_away(word: str, expected: str) -> bool:
    if len(word) == len(expected):
        differences = [i for i, (actual, correct) in enumerate(zip(word, expected)) if actual != correct]
        if len(differences) == 2:
            left, right = differences
            return right == left + 1 and word[left:right + 1] == expected[left:right + 1][::-1]
        return len(differences) == 1
    shorter, longer = sorted((word, expected), key=len)
    return len(longer) == len(shorter) + 1 and any(
        longer[:i] + longer[i + 1:] == shorter for i in range(len(longer))
    )


def _correct_context_word(word: str) -> str:
    if len(word) < 4 or not word.isalpha() or word in _CONTEXT_QUESTION_WORDS:
        return word
    matches = [expected for expected in _CONTEXT_QUESTION_WORDS if _one_edit_away(word, expected)]
    return matches[0] if len(matches) == 1 else word


def _question_for_text(query: str) -> str | None:
    return next((name for name, pattern in _CONTEXT_QUESTIONS.items() if re.fullmatch(pattern, query)), None)


def _match_context_question(message: str) -> str | None:
    query = message
    for pattern in (_TICKET_ID, _ORDER_ID, _CUSTOMER_ID):
        query = pattern.sub(" ", query)
    query = _normalize_lookup_wording(query)
    question = _question_for_text(query)
    if question is None:
        corrected = " ".join(_correct_context_word(word) for word in query.split())
        if corrected != query:
            question = _question_for_text(corrected)
    if question in _OTHER_RECORD_QUESTIONS and (_TICKET_ID.search(message) or _ORDER_ID.search(message)):
        return None
    return question


def match_context_questions(message: str) -> tuple[str, ...]:
    """Recognize a single question or a combination of supported read-only questions."""
    if question := _match_context_question(message):
        return (question,)
    clauses = re.split(r"\s+(?:and(?: also)?|also)\s+", message, flags=re.IGNORECASE)
    if len(clauses) == 1:
        return ()
    questions = []
    for clause in clauses:
        question = _match_context_question(clause)
        if question is None:
            return ()
        questions.append(question)
    return tuple(dict.fromkeys(questions))


def context_needs_order_details(questions: tuple[str, ...]) -> bool:
    return bool(_ORDER_DETAIL_QUESTIONS.intersection(questions))


def context_needs_refresh(
    message: str, *, age_seconds: float | None, questions: tuple[str, ...] | None = None,
) -> bool:
    """Refresh current-record requests and lists whose snapshot is at least a minute old."""
    questions = match_context_questions(message) if questions is None else questions
    if _FRESH_CONTEXT_QUESTIONS.intersection(questions):
        return True
    return bool(_CONTEXT_LIST_QUESTIONS.intersection(questions)) and (
        age_seconds is None or age_seconds >= _CONTEXT_REFRESH_INTERVAL_SECONDS
    )


def _clarify_other_record(question: str, context: dict[str, Any]) -> tuple[str, str]:
    record_type = {"other_ticket": "ticket", "other_order": "order"}.get(question, "ticket or order")
    choices = []
    if question != "other_order":
        choices.extend(
            f"- Ticket `{row['ticket_id']}`"
            for row in context.get("tickets", []) if row["ticket_id"] != context.get("ticket_id")
        )
    if question != "other_ticket":
        choices.extend(
            f"- Order `{row['order_id']}`"
            for row in context.get("orders", []) if row["order_id"] != context.get("order_id")
        )
    prompt = f"Which {record_type} do you mean? Reply with its ID."
    if choices:
        prompt += "\n\n" + "\n".join(choices)
    return prompt, "Needs information"


def _order_details_reply(
    question: str, context: dict[str, Any], evidence: dict[str, Any] | None,
) -> tuple[str, str]:
    orders = context.get("orders") or []
    order_id = context.get("order_id")
    if not order_id:
        if len(orders) == 1:
            order_id = orders[0]["order_id"]
        elif orders:
            choices = "\n".join(f"- `{row['order_id']}`" for row in orders)
            return "Which order should I look up? Reply with one of these order IDs.\n\n" + choices, "Needs information"
        else:
            return "Please share an order ID so I can look up its details.", "Needs information"

    order = (evidence or {}).get("order") or {}
    if order.get("order_id") != order_id:
        return f"I couldn't retrieve the details for order `{order_id}`. Please try again.", "Needs information"

    full_details = question == "order_details"
    lines = [f"Order `{order_id}` details" if full_details else f"Items on order `{order_id}`"]
    if full_details:
        for label, field in (
            ("Status", "status"), ("Placed", "order_date"), ("Estimated delivery", "estimated_delivery"),
            ("Delivered", "actual_delivery"), ("Marketplace", "marketplace"), ("Seller type", "seller_type"),
        ):
            if value := order.get(field):
                lines.append(f"{label} · {str(value).replace('_', ' ')}")
        if not order.get("status"):
            lines.append("The order record did not return a status.")

    items = (evidence or {}).get("items") or []
    if items:
        item_lines = []
        for item in items:
            name = item.get("product_name") or f"Item `{item['item_id']}`"
            quantity = item.get("quantity")
            price = item.get("unit_price_inr")
            parts = [f"quantity {quantity}" if quantity is not None else "quantity unavailable"]
            if full_details and price is not None:
                parts.append(f"INR {price} per unit")
            item_lines.append(f"- {name} ({', '.join(parts)})")
        lines.append("\n".join(item_lines))
    else:
        lines.append("The order record did not return any item details.")
    complete = bool(items) and all(item.get("quantity") is not None for item in items)
    if full_details:
        complete = complete and bool(order.get("status"))
    return "\n\n".join(lines), "Answer ready" if complete else "Needs information"


def _reply_to_context_question(
    question: str, context: dict[str, Any], previous_context: dict[str, Any] | None,
    order_details: dict[str, Any] | None,
) -> tuple[str, str]:
    if question in _OTHER_RECORD_QUESTIONS:
        return _clarify_other_record(question, context)
    if question in _ORDER_DETAIL_QUESTIONS:
        return _order_details_reply(question, context, order_details)

    ticket_id, order_id, customer_id = (context.get(key) for key in ("ticket_id", "order_id", "customer_id"))
    if question == "order_count":
        if not customer_id:
            return "Please share a customer ID or an order ID so I can look up the customer's orders.", "Needs information"
        count = len(context.get("orders") or [])
        noun = "order" if count == 1 else "orders"
        return f"I found {count} accessible {noun} for customer `{customer_id}`.", "Answer ready"
    if question in {"ticket_id", "order_tickets", "tickets", "new_tickets", "new_order_tickets", "current_tickets"}:
        if question == "ticket_id" and ticket_id:
            suffix = f" It is linked to order `{order_id}`." if order_id else ""
            return f"Your ticket number is `{ticket_id}`.{suffix}", "Answer ready"
        account_wide = question in {"tickets", "new_tickets", "current_tickets"}
        rows = context.get("tickets", []) if account_wide else tickets_for_active_order(context)
        if question in {"order_tickets", "new_order_tickets"} and not order_id:
            return "Please share the order ID to look up its tickets.", "Needs information"
        if not context:
            return "Please share a ticket ID or order ID so I can look it up.", "Needs information"
        heading = "Linked tickets"
        status = "Answer ready"
        if question in {"new_tickets", "new_order_tickets"} and previous_context is not None:
            previous_rows = previous_context.get("tickets", []) if account_wide else tickets_for_active_order(previous_context)
            previous_ids = {row["ticket_id"] for row in previous_rows}
            rows = [row for row in rows if row["ticket_id"] not in previous_ids]
            if not rows:
                return "I found no new tickets in the available records since the last lookup.", "Answer ready"
            heading = "New tickets found since the last lookup"
        if not rows:
            scope = f" for order `{order_id}`" if order_id and not account_wide else " in the active context"
            return f"I found no linked tickets{scope} in the available records.", "Answer ready"
        if question == "ticket_id":
            if len(rows) == 1:
                linked_order_id = rows[0].get("order_id")
                suffix = f" It is linked to order `{linked_order_id}`." if linked_order_id else ""
                return f"Your ticket number is `{rows[0]['ticket_id']}`.{suffix}", "Answer ready"
            heading = "Which ticket do you mean? Reply with one of these ticket IDs."
            status = "Needs information"
        return heading + "\n\n" + "\n".join(
            f"- `{row['ticket_id']}`" + (f" for order `{row['order_id']}`" if row.get("order_id") else "")
            for row in rows
        ), status

    if question in {"order_id", "orders", "other_orders", "current_orders", "current_order_status"}:
        if question == "order_id" and order_id:
            return f"Your order number is `{order_id}`.", "Answer ready"
        if not context or (question in {"orders", "other_orders", "current_orders"} and not customer_id):
            return "Please share an order ID or customer ID so I can find the linked orders.", "Needs information"
        rows = context.get("orders", [])
        if question == "other_orders":
            rows = [row for row in rows if row["order_id"] != order_id]
        if question == "current_order_status" and order_id:
            rows = [row for row in rows if row["order_id"] == order_id]
        if not rows:
            wording = "other orders" if question == "other_orders" else "orders"
            return f"I found no {wording} in the available records.", "Answer ready"
        if question == "order_id" and len(rows) == 1:
            return f"Your order number is `{rows[0]['order_id']}`.", "Answer ready"
        if question == "current_order_status" and len(rows) == 1:
            row = rows[0]
            if recorded_status := row.get("status"):
                return f"Order `{row['order_id']}` is marked {recorded_status.replace('_', ' ')}.", "Answer ready"
            return f"The latest record for order `{row['order_id']}` has no status available.", "Answer ready"
        choose_order = question in {"order_id", "current_order_status"}
        heading = "Which order do you mean? Reply with one of these order IDs." if choose_order else "Linked orders"
        return heading + "\n\n" + "\n".join(
            f"- `{row['order_id']}`" + (f" · {row['status'].replace('_', ' ')}" if row.get("status") else "")
            for row in rows
        ), "Needs information" if choose_order else "Answer ready"

    if not customer_id:
        return "Please share a customer ID or an order ID so I can look up the customer.", "Needs information"
    answer = f"The linked customer ID is `{customer_id}`."
    if question == "customer":
        profile = context.get("customer") or {}
        for label, field in (("Loyalty tier", "loyalty_tier"), ("Preferred language", "preferred_language"),
                             ("Account opened", "account_created_date")):
            if value := profile.get(field):
                answer += f"\n\n{label} · {value}"
    return answer, "Answer ready"


def reply_from_chat_context(
    message: str, context: dict[str, Any], *, previous_context: dict[str, Any] | None = None,
    order_details: dict[str, Any] | None = None, questions: tuple[str, ...] | None = None,
) -> tuple[str, str] | None:
    """Answer recognized read-only questions from records in the verified context."""
    questions = match_context_questions(message) if questions is None else questions
    if not questions:
        return None
    replies = [_reply_to_context_question(question, context, previous_context, order_details) for question in questions]
    complete = all(status == "Answer ready" for _, status in replies)
    return "\n\n".join(answer for answer, _ in replies), "Answer ready" if complete else "Needs information"


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
