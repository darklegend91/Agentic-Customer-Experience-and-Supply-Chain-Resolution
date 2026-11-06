# Day 5 initial design notes

This file preserves the original implementation plan and examples. Day 5 has since been implemented in the project. Use the current [Day 5 LangGraph workflow guide](day5_langgraph_workflow.md) for the actual modules, configuration, endpoints, security boundaries, and tests. The implementation follows the supplied [agentic flow](Agnetic%20flow.pdf) while keeping all operational reads on the existing read-only fixture connection and all approvals simulation-only.

## Design choice

Use **LangGraph to orchestrate the workflow**. Use **Laya for structured intent classification and routing signals**. Laya’s documented System One endpoint returns typed decisions; it does not draft free-form customer responses. For the answer, use a fixed, evidence-grounded template for this sprint, or add a separate text-generating model later. [Laya self-host API](https://laya-ai.com/guides/self-host-laya), [Laya’s model comparison](https://laya-ai.com/laya-vs-llm)

I couldn’t connect to `127.0.0.1:8770` from my environment, so I haven’t confirmed which API your running instance exposes. Check it from your Mac before writing the adapter:

```bash
curl -i http://127.0.0.1:8770/openapi.json
```

The current Laya self-host docs describe `POST /v1/systemone`. If that route exists in your instance, try:

```bash
curl -i -X POST http://127.0.0.1:8770/v1/systemone \
  -H "Content-Type: application/json" \
  -d '{
    "state": {"ticket_text": "My order arrived damaged"},
    "questions": {
      "intent_group": {
        "type": "choice",
        "criteria": {
          "order_delivery": "The customer asks about order or delivery status.",
          "return_refund": "The customer asks about a return or refund.",
          "product_issue": "The customer reports damage, a defect, or a wrong item.",
          "policy_faq": "The customer asks a general policy question.",
          "other": "None of the listed categories apply."
        }
      }
    }
  }'
```

If you get `401`, configure the server’s bearer token locally and add its authorization header. Don’t put the key in source code or share it in chat.

## Implementation plan in your existing folders

1. **Add and lock dependencies** in `requirements.txt`: `langgraph` and `langgraph-checkpoint-postgres`. Keep using `httpx` for the local Laya API. Pin compatible versions in your lock file after you verify them.
2. **Define the workflow contract** in `backend/app/agents/` and `backend/app/api/schemas/`: ticket text and identifiers, intent group, confidence score, specialist, evidence references, missing information, rule result, proposal, workflow status, and error code.
3. **Write the Laya adapter** in `backend/app/agents/triage.py`. Validate the response, allow only known intent groups, apply a locally configured confidence threshold, and fall back to your existing classifier if it is available and evaluated. If neither classifier gives a valid result, route to clarification or human review.
4. **Build narrow specialist nodes** in `investigation.py` and `policy_retrieval.py`. Have them call your existing read-only repositories and RAG search. They should return evidence and provenance, not make decisions or write to the order system.
5. **Put deterministic rules** in `backend/app/domain/resolution_rules.py`. Given validated order facts and policy evidence, return a structured result such as `eligible`, `ineligible`, `needs_information`, or `escalate`, plus rule version and reason codes. Missing or conflicting evidence should produce `needs_information` or `escalate`.
6. **Build the graph** in `backend/app/agents/graph.py`, with intent routing in `supervisor.py`.
7. **Persist proposals and approvals** using the existing approval and route modules. Register the new routers in `backend/app/main.py`.
8. **Keep the workflow safe on failures:** if Laya fails, use a validated fallback or escalate; if Milvus fails, don’t invent policy evidence; if the database or checkpoint store fails, don’t accept an approval.

A practical route map for the four original specialist groups in the PDF is:

| Laya intent group | Specialist stage |
|---|---|
| `policy_faq` | Policy retrieval |
| `order_delivery` | Order and delivery lookup |
| `return_refund` | Return/refund lookup, then policy check |
| `product_issue` | Product issue evidence, then policy check |
| `other` or low confidence | Ask for details or escalate |

## Laya adapter example

This is an outline for `backend/app/agents/triage.py`; adjust the URL and response parsing to match your local OpenAPI schema.

```python
import httpx

ALLOWED_GROUPS = {
    "policy_faq",
    "order_delivery",
    "return_refund",
    "product_issue",
    "other",
}

def classify_with_laya(
    base_url: str,
    ticket_text: str,
    min_confidence: float,
) -> dict:
    payload = {
        "state": {"ticket_text": ticket_text},
        "questions": {
            "intent_group": {
                "type": "choice",
                "criteria": {
                    "order_delivery": "Order or delivery status question.",
                    "return_refund": "Return or refund question.",
                    "product_issue": "Damaged, defective, or wrong product.",
                    "policy_faq": "General policy question.",
                    "other": "None of the listed categories.",
                },
            }
        },
    }

    response = httpx.post(
        f"{base_url.rstrip('/')}/v1/systemone",
        json=payload,
        timeout=5.0,
    )
    response.raise_for_status()
    body = response.json()

    answer = body["answers"]["intent_group"]
    group = answer["choice"]
    score = float(
        answer.get("answer_confidence", answer.get("confidence", 0.0))
    )

    if group not in ALLOWED_GROUPS or score < min_confidence:
        return {"intent_group": "other", "score": score, "needs_review": True}

    return {"intent_group": group, "score": score, "needs_review": False}
```

Treat the returned score as a **routing signal**, not a calibrated probability, until you evaluate it on your labelled set. Laya’s documentation also recommends calibrating confidence for your use case. [Laya API](https://laya-ai.com/laya-api), [Laya model comparison](https://laya-ai.com/laya-vs-llm)

## LangGraph shape

Keep the graph state limited to what each node needs. Avoid storing credentials, database connections, or unnecessary personal data in persisted state.

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

class SupportState(TypedDict, total=False):
    workflow_id: str
    ticket_id: str
    ticket_text: str
    order_id: str | None
    intent_group: str
    score: float
    specialist: str
    evidence: list[dict]
    missing_information: list[str]
    rule_result: dict
    proposal: dict
    status: str
    answer: str
    error_code: str

ROUTES = {
    "policy_faq": "policy_faq",
    "order_delivery": "order_delivery",
    "return_refund": "return_refund",
    "product_issue": "product_issue",
    "other": "safe_fallback",
}

def supervisor(state: SupportState) -> dict:
    return {"specialist": ROUTES.get(state.get("intent_group", "other"),
                                    "safe_fallback")}

def approval_interrupt(state: SupportState) -> dict:
    decision = interrupt({
        "kind": "approval_required",
        "workflow_id": state["workflow_id"],
        "proposal": state["proposal"],
    })
    # Validate the resumed decision against the pending proposal/version.
    approved = decision["decision"] == "approve"
    return {
        "status": "approved" if approved else "rejected",
        "approval_event_id": decision["approval_event_id"],
    }

builder = StateGraph(SupportState)
builder.add_node("classify", classify_node)
builder.add_node("supervisor", supervisor)
builder.add_node("policy_faq", policy_faq_node)
builder.add_node("order_delivery", order_delivery_node)
builder.add_node("return_refund", return_refund_node)
builder.add_node("product_issue", product_issue_node)
builder.add_node("safe_fallback", safe_fallback_node)
builder.add_node("check_evidence", check_evidence_node)
builder.add_node("policy_rules", policy_rules_node)
builder.add_node("build_proposal", build_proposal_node)
builder.add_node("approval", approval_interrupt)
builder.add_node("finish", finish_node)

builder.add_edge(START, "classify")
builder.add_edge("classify", "supervisor")
builder.add_conditional_edges("supervisor", lambda s: s["specialist"], {
    "policy_faq": "policy_faq",
    "order_delivery": "order_delivery",
    "return_refund": "return_refund",
    "product_issue": "product_issue",
    "safe_fallback": "safe_fallback",
})
# Route each specialist through evidence checks. Only proposals needing
# approval reach "approval"; status questions can produce a grounded answer.
```

Complete the remaining edges so the workflow is:

`classify → supervisor → specialist → evidence check → deterministic rules → grounded answer or proposal → approval pause`

LangGraph needs a checkpointer and a stable `thread_id` for persistent interrupts. Resume an interrupted workflow with `Command(resume=...)`; the approval node restarts when resumed, so don’t perform non-idempotent writes before `interrupt()`. [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

## Approval boundary and API

Use Pydantic for an approval body like this:

```python
from typing import Literal
from pydantic import BaseModel, Field

class ApprovalRequest(BaseModel):
    decision: Literal["approve", "reject"]
    expected_proposal_version: int
    comment: str | None = Field(default=None, max_length=500)
```

Do **not** accept `reviewer_id` as proof of identity from this body. The API must get the reviewer from authentication, check their role, and verify that the proposal is still pending and at the submitted version. The decision resumes the workflow and records an audit event; it must not call any order/refund/action tool. LangGraph provides a PostgreSQL checkpointer integration for production persistence; use a write-enabled checkpoint database/schema and apply its setup as a controlled migration, rather than using the existing read-only order lookup connection. [PostgreSQL checkpointer](https://pypi.org/project/langgraph-checkpoint-postgres/)

For a production API, make the approval record idempotent and append-only. If approval recording and graph resumption can fail separately, put the accepted decision in a transactional outbox so a worker can retry the resume safely.

## Suggested endpoints and acceptance checks

Add endpoints along these lines:

- `POST /workflows` — start a workflow; return workflow ID and current status.
- `GET /workflows/{workflow_id}` — inspect status, evidence references, and any pending proposal.
- `POST /proposals/{proposal_id}/decision` — authorize, record, and resume an approval or rejection.

Before calling Day 5 complete, verify that a ticket can reach the right specialist, missing evidence triggers clarification/escalation, rules return a structured result, a consequential proposal pauses for approval, reject/approve resumes the same workflow, duplicate decisions are handled idempotently, and no path executes an order-changing action. Also test Laya, Milvus, and database failures.

:codex-file-citation{path="/Users/adityapathania/Codes/bz/Agentic_Customer_Experience_Supply_Chain_Resolution/docs/Agnetic flow.pdf" purpose="source"}
