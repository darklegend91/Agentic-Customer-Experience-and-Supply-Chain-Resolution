"""Present truthful chatbot outcomes without interpreting model output as success."""

from __future__ import annotations

from typing import Any

from backend.app.domain.resolution_rules import ORDER_REQUIRED_INTENTS
from backend.app.domain.support_messages import account_access_request, cannot_answer


def chat_reply(result: dict[str, Any], message: str = "") -> dict[str, Any]:
    status = result.get("status")
    answer = result.get("answer")
    if status in {"escalated", "needs_information", "failed_safe"} and isinstance(answer, str) and answer.strip():
        return {"status": status, "answer": answer, "reason_codes": result.get("reason_codes") or []}
    classification = result.get("classification") or {}
    codes = result.get("reason_codes") or []
    if account_access_request(message):
        codes = ["unsupported_account_request"]
    elif classification.get("triage_status") == "security_review":
        codes = ["unsafe_input"]
    elif classification.get("intent") == "other_or_unsupported":
        codes = ["unsupported_request"]
    elif status == "answer_ready" and isinstance(answer, str) and answer.strip():
        return {"status": status, "answer": answer, "reason_codes": codes}
    elif classification.get("intent") in ORDER_REQUIRED_INTENTS and not ((result.get("order_evidence") or {}).get("order") or {}).get("order_id"):
        codes = ["order_id_required"]
    return {
        "status": "needs_information" if "order_id_required" in codes else "escalated",
        "answer": cannot_answer(codes, result.get("missing_information")),
        "reason_codes": codes,
    }


def chat_error(status_code: int | None, detail: str) -> str:
    detail_lower = (detail or "").lower()
    if status_code == 422 and "security review" in detail_lower:
        return cannot_answer(["unsafe_input"])
    if status_code == 422 and "one customer id" in detail_lower:
        return "Please provide one customer ID, and make sure it matches the Customer ID field."
    if status_code == 422:
        return f"I couldn't process those details ({detail}). Please check the IDs and try again with a short description."
    if status_code in {401, 403}:
        return "I can't access this request with the current permissions. Please check your support bearer token in the sidebar."
    if status_code == 503:
        if "database" in detail_lower or "workflowstore" in detail_lower or "timeout" in detail_lower:
            return (
                "⚠️ **Workflow Database Unavailable (HTTP 503)**\n\n"
                "The background PostgreSQL workflow store could not be reached. "
                "You can switch to **⚡ Investigate Tool** mode in the context bar above for instant direct answers "
                "without background database queuing."
            )
        if "milvus" in detail_lower or "rag" in detail_lower:
            return "⚠️ Vector database (Milvus) is currently unavailable. You can retry with keyword search mode."
        return cannot_answer(["dependency_unavailable"])
    return f"⚠️ Request could not be completed: {detail}"


def repair_legacy_turns(history: list[dict[str, Any]]) -> None:
    previous_message = ""
    for turn in history:
        if turn.get("role") == "user":
            previous_message = turn.get("content") or ""
        elif turn.get("content") in {"Investigation completed successfully using the investigation tool.", "Order status investigated."}:
            codes = ["unsupported_account_request"] if account_access_request(previous_message) else []
            turn["content"] = cannot_answer(codes)
            turn["meta"] = "Unable to answer · Please review the guidance above"
