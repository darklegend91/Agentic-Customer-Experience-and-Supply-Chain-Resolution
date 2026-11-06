"""Streamlit control room for the local customer support investigation project."""

from __future__ import annotations

import html
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)

st.set_page_config(
    page_title="Customer Support Control Room",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --ink:#eaf0f5; --muted:#91a0ae; --line:#263443; --panel:#111c27; --panel2:#162330; --teal:#62dec2; --amber:#f3bd69; --red:#ff8b86; }
    html, body, [class*="css"] { font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
    .stApp { background: radial-gradient(ellipse at 75% -10%, #143340 0%, #0c141d 48%, #0a1118 100%); color:var(--ink); }
    [data-testid="stSidebar"] { background:#0b141d; border-right:1px solid var(--line); }
    [data-testid="stSidebar"] > div:first-child { padding-top:1.1rem; }
    .block-container { max-width:1440px; padding-top:2rem; padding-bottom:3rem; }
    h1,h2,h3 { font-family:Inter,ui-sans-serif,system-ui,sans-serif; letter-spacing:-.035em; color:var(--ink); }
    h1 { font-size:2.55rem !important; line-height:1.08 !important; }
    h2 { font-size:1.45rem !important; }
    p,li,label { color:#d5dee6; }
    code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
    .eyebrow { color:var(--teal); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.72rem; letter-spacing:.15em; text-transform:uppercase; margin-bottom:.65rem; }
    .subhead { color:var(--muted); font-size:1rem; max-width:820px; line-height:1.6; margin-top:.65rem; }
    .hero { border:1px solid #26404c; border-radius:18px; padding:25px 28px; background:linear-gradient(120deg,rgba(18,42,51,.94),rgba(17,28,39,.92) 65%,rgba(27,38,47,.92)); margin:0 0 1.35rem; }
    .card { border:1px solid var(--line); border-radius:14px; padding:16px 18px; background:rgba(17,28,39,.85); margin:0 0 12px; }
    .card-label { color:var(--muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.7rem; text-transform:uppercase; letter-spacing:.1em; }
    .card-value { color:var(--ink); font-size:1.1rem; font-weight:700; margin-top:6px; }
    .badge { display:inline-block; border:1px solid #35545b; border-radius:100px; color:var(--teal); padding:4px 10px; font:500 .72rem ui-monospace,SFMono-Regular,Menlo,monospace; background:#11282d; }
    .badge-amber { color:var(--amber); border-color:#665338; background:#292318; }
    .badge-red { color:var(--red); border-color:#65403f; background:#2a1b1b; }
    .current-step { border:1px solid #337567; border-radius:12px; padding:13px 16px; background:linear-gradient(90deg,#112c2c,#13242d); color:var(--teal); margin:.5rem 0 1rem; }
    .timeline-row { display:flex; gap:13px; padding:10px 8px; border-left:1px solid #344655; margin-left:10px; color:#cbd6df; }
    .timeline-dot { width:9px; height:9px; border-radius:50%; background:var(--teal); margin-left:-13px; margin-top:6px; flex:0 0 auto; box-shadow:0 0 0 4px #11242b; }
    .timeline-title { font-weight:600; }
    .timeline-meta { color:var(--muted); font: .72rem ui-monospace,SFMono-Regular,Menlo,monospace; margin-top:3px; }
    .stage-card { min-height:128px; border:1px solid var(--line); border-radius:13px; padding:15px; background:linear-gradient(145deg,#14222e,#101a24); }
    .stage-num { color:var(--teal); font: .72rem ui-monospace,SFMono-Regular,Menlo,monospace; }
    .stage-title { color:var(--ink); font-weight:700; margin:.48rem 0 .32rem; }
    .stage-copy { color:var(--muted); font-size:.82rem; line-height:1.45; }
    div[data-testid="stMetric"] { border:1px solid var(--line); border-radius:12px; padding:12px 14px; background:rgba(17,28,39,.75); }
    div[data-testid="stMetricLabel"] { color:var(--muted); }
    div[data-testid="stMetricValue"] { color:var(--ink); }
    .stButton > button[kind="primary"] { background:#3abda4; border:0; color:#071715; font-weight:700; }
    .stButton > button[kind="primary"]:hover { background:#73e7cb; color:#071715; }
    div[data-testid="stTabs"] button { font-weight:600; }
    .small-note { color:var(--muted); font-size:.78rem; line-height:1.5; }
    </style>
    """,
    unsafe_allow_html=True,
)


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def api_request(
    method: str,
    path: str,
    *,
    base_url: str,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    try:
        response = httpx.request(
            method,
            f"{base_url.rstrip('/')}{path}",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise ApiError("The API request timed out. Check that FastAPI and its data services are running.") from exc
    except httpx.HTTPError as exc:
        raise ApiError("Could not reach the FastAPI service. Check the API URL and server status.") from exc

    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text[:500]}
    if not response.is_success:
        detail = data.get("detail", f"HTTP {response.status_code}") if isinstance(data, dict) else f"HTTP {response.status_code}"
        raise ApiError(str(detail), response.status_code)
    return data


def loopback_api(base_url: str) -> bool:
    return urlparse(base_url).hostname in {"127.0.0.1", "localhost", "::1"}


def local_api_request(method: str, path: str, *, base_url: str, payload: dict[str, Any] | None = None) -> Any:
    if not loopback_api(base_url):
        raise ApiError("This local fixture endpoint is only enabled when the API URL points to this computer.")
    return api_request(method, path, base_url=base_url, payload=payload)


def show_json_result(title: str, payload: Any) -> None:
    st.markdown(f"#### {title}")
    st.json(payload, expanded=False)


def render_policy_hits(evidence: dict[str, Any]) -> None:
    results = evidence.get("results") or {}
    if not results:
        st.info("No policy passages were returned for this stage.")
        if evidence.get("missing_fields"):
            st.caption("Missing: " + ", ".join(evidence["missing_fields"]))
        return
    for method, hits in results.items():
        st.markdown(f"**{method.title()} retrieval** · {len(hits)} passage(s)")
        for hit in hits:
            title = f"{hit.get('document_id', 'Document')} · v{hit.get('policy_version', '?')} · {hit.get('section_title', 'Untitled section')}"
            with st.expander(title, expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.caption(f"Section ID\n{hit.get('section_id', '—')}")
                c2.caption(f"Status / scope\n{hit.get('status', '—')} · {hit.get('environment_scope', '—')}")
                c3.caption(f"Score\n{hit.get('score', '—')}")
                st.write(hit.get("excerpt") or "No excerpt returned.")
                st.caption(f"Evidence ID: {hit.get('chunk_id', '—')} · Source: {hit.get('source_uri', '—')}")


def render_workflow_evidence(trace: dict[str, Any], result: dict[str, Any]) -> None:
    evidence = trace.get("evidence") or {}
    order = evidence.get("order") or {}
    policy = evidence.get("policy") or {}
    customer_context = evidence.get("customer_context") or {}
    ledger = evidence.get("ledger") or {}
    order_tab, customer_tab, policy_tab, ledger_tab, rules_tab, draft_tab = st.tabs(
        ["Order & delivery · SQL", "Loyalty & prior contact", "Policy passages · Milvus", "Evidence ledger", "Decision rules", "Response draft"]
    )
    with order_tab:
        if order:
            st.caption(f"Source: {order.get('source_system', 'Neon Postgres')} · Snapshot: {order.get('as_of', 'recorded during workflow')}")
            status = order.get("status", "unknown")
            st.markdown(f"<span class='badge'>{html.escape(str(status).upper())}</span>", unsafe_allow_html=True)
            st.json(order, expanded=False)
        else:
            st.info("This specialist did not need an order lookup.")
    with customer_tab:
        if customer_context:
            st.caption("Customer IDs and direct contact fields are excluded; records are linked through the authorized order scope.")
            st.write("Status: " + str(customer_context.get("status", "unknown")))
            show_json_result("Loyalty account and transactions", {
                "loyalty_account": customer_context.get("loyalty_account"),
                "loyalty_transactions": customer_context.get("loyalty_transactions", []),
            })
            show_json_result("Prior communication summaries", customer_context.get("prior_communications", []))
            if customer_context.get("missing_fields") or customer_context.get("conflicts"):
                st.warning("Missing/conflicting context: " + ", ".join(customer_context.get("missing_fields", []) + customer_context.get("conflicts", [])))
        else:
            st.info("No loyalty or prior-contact lookup was requested for this specialist.")
    with policy_tab:
        if policy:
            st.caption(f"Collection: {policy.get('collection') or 'keyword baseline'} · Scope: {policy.get('corpus_scope', 'not reported')}")
            render_policy_hits(policy)
        else:
            st.info("This specialist did not need policy retrieval.")
    with ledger_tab:
        if ledger:
            st.markdown(f"**Ledger status:** `{ledger.get('status', 'unknown')}`")
            for label, key in (
                ("Source-record facts", "source_facts"),
                ("Retrieved policy statements", "policy_statements"),
                ("Customer reports", "customer_reports"),
                ("Model assumptions / inferences", "assumptions"),
                ("Missing information", "missing_information"),
                ("Conflicts", "conflicts"),
            ):
                with st.expander(label, expanded=key in {"missing_information", "conflicts"} and bool(ledger.get(key))):
                    st.json(ledger.get(key, []), expanded=False)
        else:
            st.info("The typed evidence ledger has not been built yet.")
    with rules_tab:
        resolution = trace.get("resolution") or {}
        if resolution:
            st.markdown(f"**Rule outcome:** `{resolution.get('outcome', 'unknown')}`")
            if resolution.get("reason_codes"):
                st.write("Reason codes: " + ", ".join(resolution["reason_codes"]))
            show_json_result("Rule evaluation details", resolution)
        else:
            st.info("The deterministic rules stage has not completed yet.")
    with draft_tab:
        draft = trace.get("draft") or {}
        if draft:
            st.write(draft.get("answer", "Draft was generated without a customer-facing answer."))
            st.caption("Provider: " + str(draft.get("provider", "deterministic template")))
            show_json_result("Validated draft payload", draft)
        elif result.get("answer"):
            st.write(result["answer"])
        else:
            st.info("A response draft has not been generated for this outcome.")


EVENT_LABELS = {
    "workflow_started": "Investigation accepted",
    "workflow_queued": "Investigation accepted and queued",
    "workflow_worker_claimed": "A worker claimed the investigation",
    "workflow_retry_scheduled": "A safe workflow retry was scheduled",
    "workflow_retry_limit_exceeded": "Workflow retries ended; case routed for human review",
    "input_validated": "Input validated and sensitive values masked",
    "input_rejected": "Input rejected by scope or schema checks",
    "ticket_classified": "Laya returned a structured intent",
    "triage_failed": "Classification failed safely",
    "specialist_selected": "Supervisor selected a specialist stage",
    "specialist_evidence_collected": "Specialist collected read-only evidence",
    "specialist_failed": "Specialist dependency failed",
    "evidence_consolidated": "Evidence references consolidated",
    "deterministic_rules_evaluated": "Deterministic policy and evidence rules evaluated",
    "response_drafted": "Response draft created",
    "response_draft_failed": "Drafting failed safely",
    "output_validation_completed": "Answer and citation validation completed",
    "proposal_persisted_for_approval": "Versioned proposal persisted",
    "proposal_paused_for_approval": "Workflow paused for human review",
    "approval_workflow_resumed": "Workflow resumed after human review",
    "proposal_approved_simulation": "Approved for simulation only",
    "proposal_rejected": "Proposal rejected by reviewer",
    "proposal_invalidated_stale_evidence": "Proposal invalidated after evidence refresh",
    "safe_fallback_selected": "Safe fallback selected",
    "workflow_finished": "Workflow finished",
    "workflow_paused": "Workflow is waiting for approval",
    "workflow_failed_safe": "Workflow stopped safely",
}


def format_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone().strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return str(value)


def render_timeline(events: list[dict[str, Any]], trace: dict[str, Any], status: str) -> None:
    if status == "running":
        step = trace.get("current_step") or "Preparing the workflow checkpoint"
        st.markdown(
            f"<div class='current-step'><span class='card-label'>ACTIVE STEP</span><br><b>{html.escape(step)}</b></div>",
            unsafe_allow_html=True,
        )
    elif status == "pending_approval":
        st.markdown(
            "<div class='current-step'><span class='card-label'>PAUSED AT APPROVAL GATE</span><br><b>Waiting for an authorized reviewer</b></div>",
            unsafe_allow_html=True,
        )

    if not events:
        st.caption("No audit events have been recorded yet.")
        return
    for event in events:
        event_type = str(event.get("event_type") or "event")
        title = EVENT_LABELS.get(event_type, event_type.replace("_", " ").capitalize())
        details = event.get("details") or {}
        specialist = details.get("specialist")
        if specialist:
            title += f" · {str(specialist).replace('_', ' ')}"
        metadata = [format_time(event.get("occurred_at")), str(event.get("stage") or "").replace("_", " ")]
        if details.get("intent"):
            metadata.append("intent: " + str(details["intent"]))
        if details.get("reason_codes"):
            metadata.append("reason: " + ", ".join(str(x) for x in details["reason_codes"]))
        st.markdown(
            "<div class='timeline-row'><span class='timeline-dot'></span><div>"
            f"<div class='timeline-title'>{html.escape(title)}</div>"
            f"<div class='timeline-meta'>{html.escape(' · '.join(x for x in metadata if x))}</div>"
            "</div></div>",
            unsafe_allow_html=True,
        )


def render_workflow_panel(base_url: str, support_token: str) -> None:
    workflow_id = st.session_state.get("active_workflow_id")
    if not workflow_id:
        st.info("Start an investigation to see the live agent and evidence timeline here.")
        return
    if st.session_state.get("workflow_poll_error"):
        st.error(f"The last status refresh failed: {st.session_state.workflow_poll_error}")

    auto_poll = bool(st.session_state.get("workflow_polling"))

    @st.fragment(run_every="2.5s" if auto_poll else None)
    def workflow_fragment() -> None:
        workflow_id = st.session_state.get("active_workflow_id")
        if not workflow_id:
            st.info("No active workflow.")
            return
        try:
            result = api_request("GET", f"/workflows/{workflow_id}", base_url=base_url, token=support_token)
            events = api_request("GET", f"/workflows/{workflow_id}/events", base_url=base_url, token=support_token)
            trace = api_request("GET", f"/workflows/{workflow_id}/trace", base_url=base_url, token=support_token)
        except ApiError as exc:
            st.session_state.workflow_poll_error = str(exc)
            st.error(f"Workflow status could not be refreshed: {exc}")
            if exc.status_code in {401, 403}:
                st.session_state.workflow_polling = False
                st.rerun()
            return

        st.session_state.workflow_poll_error = None
        st.session_state.active_workflow = result
        st.session_state.active_events = events
        st.session_state.active_trace = trace
        is_running = result.get("status") == "running"
        was_polling = bool(st.session_state.get("workflow_polling"))
        st.session_state.workflow_polling = is_running
        if was_polling and not is_running:
            st.rerun()

        status = result.get("status", "unknown")
        intent = (trace.get("classification") or result.get("classification") or {}).get("intent", "—")
        confidence = (trace.get("classification") or result.get("classification") or {}).get("confidence")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Workflow", status.replace("_", " ").title())
        c2.metric("Intent", str(intent).replace("_", " ").title())
        c3.metric("Specialist", str(trace.get("specialist") or result.get("specialist") or "—").replace("_", " ").title())
        c4.metric("Classifier confidence", f"{confidence:.0%}" if isinstance(confidence, (int, float)) else "—")

        if st.button("Refresh now", key="refresh_workflow"):
            st.rerun()

        timeline_col, details_col = st.columns([.95, 1.05], gap="large")
        with timeline_col:
            st.markdown("### Live run timeline")
            render_timeline(events, trace, status)
        with details_col:
            st.markdown("### Agent result")
            classification = trace.get("classification") or result.get("classification")
            if classification:
                cprovider, ctriage = st.columns(2)
                cprovider.caption("Classifier: " + str(classification.get("classifier_provider", "unknown")))
                ctriage.caption("Triage: " + str(classification.get("triage_status", "unknown")))
                if classification.get("fallback_used"):
                    st.warning("Laya was unavailable; the fallback classifier is review-only and did not route automatically.")
                if classification.get("risk_flags"):
                    st.caption("Risk flags: " + ", ".join(classification["risk_flags"]))
            answer = trace.get("answer") or result.get("answer")
            if answer:
                st.success(answer) if status == "answer_ready" else st.info(answer)
            elif status == "running":
                st.caption("The graph is working through the current checkpoint. The timeline refreshes automatically.")
            elif status == "pending_approval":
                st.info("The proposal is paused until a reviewer decides. No commerce action is running.")
            if result.get("reason_codes"):
                st.caption("Outcome codes: " + ", ".join(result["reason_codes"]))

        if result.get("evidence_refs"):
            st.markdown("**Evidence references**")
            st.code("\n".join(result["evidence_refs"]), language="text")
        with st.expander("Inspect data passed between the specialist, policy rules, and response validator", expanded=False):
            render_workflow_evidence(trace, result)

        proposal = result.get("proposal") or {}
        if proposal:
            render_proposal(proposal, result, base_url)

    workflow_fragment()


def render_proposal(proposal: dict[str, Any], workflow: dict[str, Any], base_url: str) -> None:
    st.markdown("### Human approval gate")
    if proposal.get("status") == "pending_approval":
        st.warning("Approval records a simulation outcome only. It cannot issue a refund, replacement, payment, message, or order mutation.")
        st.markdown(f"**Proposal:** {proposal.get('summary', 'No summary available')}")
        p1, p2 = st.columns(2)
        p1.caption(f"Action kind: {proposal.get('action_kind', '—')}")
        p2.caption(f"Version: {proposal.get('proposal_version', '—')}")
        if proposal.get("permitted_options"):
            st.write("Permitted options: " + ", ".join(proposal["permitted_options"]))
        reviewer_token = st.session_state.get("reviewer_token", "")
        idem_state_key = f"approval_idempotency_{proposal.get('proposal_id')}"
        if not st.session_state.get(idem_state_key):
            st.session_state[idem_state_key] = str(uuid.uuid4())
        with st.form("proposal_review_form"):
            decision = st.radio("Reviewer decision", ["approve", "reject"], horizontal=True)
            comment = st.text_input("Review note (optional)", max_chars=500)
            submit = st.form_submit_button("Record review decision", type="primary", disabled=not bool(reviewer_token))
        if not reviewer_token:
            st.caption("Enter the reviewer token in the sidebar to enable this approval control.")
        if submit:
            try:
                payload = {
                    "schema_version": "1.0",
                    "decision": decision,
                    "expected_proposal_version": int(proposal["proposal_version"]),
                    "comment": comment or None,
                }
                reviewed = api_request(
                    "POST",
                    f"/approvals/proposals/{proposal['proposal_id']}/decision",
                    base_url=base_url,
                    token=reviewer_token,
                    payload=payload,
                    extra_headers={"Idempotency-Key": st.session_state[idem_state_key]},
                    timeout=30,
                )
                st.session_state.active_workflow = reviewed.get("workflow", workflow)
                st.session_state.workflow_polling = False
                st.success(f"Review recorded: {reviewed.get('status', 'complete').replace('_', ' ')}")
                st.rerun()
            except ApiError as exc:
                st.error(f"Review was not recorded: {exc}")
    else:
        st.info(f"Proposal state: {str(proposal.get('status', 'unknown')).replace('_', ' ').title()}")


def render_classification(result: dict[str, Any]) -> None:
    classification = result.get("classification") or {}
    confidence = classification.get("confidence")
    a, b, c = st.columns(3)
    a.metric("Suggested intent", str(classification.get("intent", "—")).replace("_", " ").title())
    b.metric("Confidence", f"{confidence:.0%}" if isinstance(confidence, (int, float)) else "—")
    c.metric("Provider", str(classification.get("classifier_provider", "—")))
    if classification.get("fallback_used"):
        st.warning("Fallback used. This classification is for human review and must not trigger automatic routing.")
    st.json(classification, expanded=False)


def render_evaluation(result: dict[str, Any]) -> None:
    st.caption("Corpus scope: " + str(result.get("corpus_scope", "unknown")))
    metrics = result.get("metrics") or {}
    if metrics:
        cols = st.columns(max(1, len(metrics)))
        for col, (method, row) in zip(cols, metrics.items()):
            with col:
                st.markdown(f"**{method.title()}**")
                st.metric("Hit@1", f"{row.get('expected_document_hit_at_1', 0):.0%}")
                st.metric("Hit@k", f"{row.get('expected_document_hit_at_k', 0):.0%}")
                st.caption(f"MRR@k {row.get('mrr_at_k', 0):.3f} · {row.get('query_count', 0)} queries")
                st.caption(f"Scope compliance {row.get('scope_compliance', 0):.0%} · Citation metadata {row.get('citation_metadata_completeness', 0):.0%}")
    for case in result.get("cases") or []:
        label = case.get("case_id") or case.get("query") or "Evaluation case"
        with st.expander(str(label), expanded=False):
            st.write(case.get("query", ""))
            st.caption("Expected document: " + str(case.get("expected_document_id", "not scored")))
            for method, method_result in (case.get("methods") or {}).items():
                st.markdown(f"**{method.title()}**")
                if method_result.get("evaluation"):
                    st.write(method_result["evaluation"])
                render_policy_hits({"results": {method: method_result.get("hits") or []}})


def render_pipeline_overview() -> None:
    st.markdown("### One ticket, controlled evidence, visible decisions")
    stages = [
        ("01", "Intake contract", "FastAPI validates ticket text or a ticket ID, order reference, retrieval methods, and limits."),
        ("02", "Laya triage", "Laya returns an allowlisted intent and confidence. Fallback or low confidence pauses for review."),
        ("03", "Supervisor", "A deterministic intent map selects one specialist. The model cannot pick arbitrary tools or graph nodes."),
        ("04", "Specialist tools", "Order specialists read bounded Neon facts; policy specialists search versioned Milvus passages."),
        ("05", "Evidence gate", "Deterministic rules check source sufficiency and policy scope before a grounded answer or proposal."),
        ("06", "Review checkpoint", "A proposal pauses in LangGraph. A separate reviewer can approve a simulation or reject it."),
    ]
    for start in range(0, len(stages), 3):
        cols = st.columns(3, gap="medium")
        for col, (number, title, copy) in zip(cols, stages[start : start + 3]):
            with col:
                st.markdown(
                    f"<div class='stage-card'><div class='stage-num'>STAGE {number}</div>"
                    f"<div class='stage-title'>{html.escape(title)}</div>"
                    f"<div class='stage-copy'>{html.escape(copy)}</div></div>",
                    unsafe_allow_html=True,
                )

    st.markdown("### Data path and guardrails")
    st.dataframe(
        [
            {"Stage": "Ticket intake", "Input": "Ticket text / ticket ID", "Processor": "Pydantic + masking + scope checks", "Output": "Safe workflow state"},
            {"Stage": "Classification", "Input": "Masked ticket message", "Processor": "Laya; TF-IDF fallback is review-only", "Output": "Intent, confidence, risk flags"},
            {"Stage": "Order evidence", "Input": "Authorized order ID", "Processor": "Read-only allowlisted SQL", "Output": "Order, item, delivery, return facts"},
            {"Stage": "Policy evidence", "Input": "Question and intent", "Processor": "Milvus semantic + keyword retrieval", "Output": "Document/version/section citations"},
            {"Stage": "Resolution", "Input": "Evidence plus intent", "Processor": "Deterministic policy checks", "Output": "Answer, clarification, escalation, or proposal"},
            {"Stage": "Workflow state", "Input": "Masked state and decisions", "Processor": "LangGraph Postgres checkpointer + audit tables", "Output": "Resumable, versioned review"},
        ],
        hide_index=True,
        width="stretch",
    )

    try:
        manifest = json.loads((PROJECT_ROOT / "data/processed/data_quality_manifest.json").read_text(encoding="utf-8"))
        classifier = json.loads((PROJECT_ROOT / "data/processed/intent_baseline_metrics_v1.json").read_text(encoding="utf-8"))
        rag = json.loads((PROJECT_ROOT / "data/processed/rag_retrieval_metrics_v1.json").read_text(encoding="utf-8"))
        st.markdown("### Prepared-data and baseline snapshot")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Clean orders", f"{manifest['output_row_counts'].get('clean_orders', 0):,}")
        m2.metric("Training tickets", f"{classifier.get('training_rows', 0):,}")
        m3.metric("Classifier macro F1", f"{classifier.get('macro_f1', 0):.2f}")
        m4.metric("Intent labels", str(classifier.get("label_count", 0)))
        r1, r2, r3 = st.columns(3)
        r1.metric("RAG keyword Hit@1", f"{rag.get('keyword', {}).get('hit_at_1', 0):.0%}")
        r2.metric("RAG semantic Hit@1", f"{rag.get('semantic_milvus', {}).get('hit_at_1', 0):.0%}")
        r3.metric("RAG Hit@3", f"{rag.get('keyword', {}).get('hit_at_3', 0):.0%}")
        st.caption(
            f"Snapshot: {manifest.get('build_version', 'unknown')} · "
            f"{classifier.get('evaluation_rows', 0)} held-out classifier examples · "
            f"{rag.get('keyword', {}).get('query_count', 0)} labeled retrieval questions. "
            "These are small synthetic development evaluations, not production performance estimates."
        )
        if manifest.get("classifier_labels_needing_more_data"):
            st.caption("Classifier labels needing more examples: " + ", ".join(manifest["classifier_labels_needing_more_data"]))
    except (OSError, ValueError, KeyError, TypeError):
        st.info("Offline preparation or baseline metric files are not available in this checkout.")

    st.warning("This repository currently uses fictional development records and synthetic draft policy documents. Draft passages are not approved customer policy.")

    with st.expander("Read-only MCP tool surface"):
        tools = [
            "get_ticket_details", "classify_ticket", "investigate_ticket", "get_order_summary",
            "get_order_investigation", "list_delivery_events", "get_return_refund_status", "search_policy",
        ]
        st.write("The local stdio MCP server exposes: " + ", ".join(f"`{name}`" for name in tools) + ".")
        st.caption("Each tool is read-only; eligibility and remedy decisions remain with the deterministic rules and human approval flow.")

    with st.expander("Offline preparation and evaluation jobs"):
        st.markdown(
            "- `scripts/prepare_data.py` cleans the fictional operational samples and prepares evaluation mappings.\n"
            "- `scripts/train_classifier.py` builds the review-only TF-IDF baseline.\n"
            "- `scripts/chunk_versioned_policies.py` creates policy passages with version metadata.\n"
            "- `scripts/index_dev_policies.py` indexes the development-only policy collection.\n"
            "- `scripts/evaluate_day3_rag.py` writes the checked-in retrieval evaluation snapshot."
        )


def main() -> None:
    st.sidebar.markdown("<div class='eyebrow'>PROJECT CONSOLE</div>", unsafe_allow_html=True)
    st.sidebar.markdown("### Connection")
    configured_api_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    api_url_locked = os.getenv("API_BASE_URL_LOCKED", "false").strip().lower() in {"1", "true", "yes"}
    if api_url_locked:
        st.sidebar.text_input(
            "FastAPI service",
            value=configured_api_url,
            key="api_base_url_locked",
            disabled=True,
            help="The deployment controls this internal service address.",
        )
        base_url = configured_api_url
    else:
        base_url = st.sidebar.text_input(
            "FastAPI base URL",
            value=configured_api_url,
            key="api_base_url",
            help="For local use, keep FastAPI bound to 127.0.0.1.",
        ).strip().rstrip("/")
    support_token = st.sidebar.text_input(
        "Support bearer token",
        value=os.getenv("WORKFLOW_API_TOKEN", ""),
        type="password",
        key="support_token",
    )
    st.sidebar.text_input(
        "Reviewer bearer token",
        value=os.getenv("WORKFLOW_REVIEWER_TOKEN", ""),
        type="password",
        key="reviewer_token",
        help="Use a different identity/token from the workflow creator.",
    )
    st.sidebar.caption("Tokens are used for API calls and are not written to this project by the UI.")
    if st.sidebar.button("Check API health", width="stretch"):
        try:
            health = api_request("GET", "/health", base_url=base_url, timeout=4)
            st.sidebar.success("FastAPI is responding: " + str(health.get("status", "healthy")))
        except ApiError as exc:
            st.sidebar.error(str(exc))

    st.markdown(
        "<div class='hero'><div class='eyebrow'>CONTROLLED INVESTIGATION · LOCAL DEVELOPMENT</div>"
        "<h1>Customer support<br>control room</h1>"
        "<div class='subhead'>Investigate a ticket, watch the specialist workflow advance, inspect the evidence, and review a proposed outcome in one place.</div></div>",
        unsafe_allow_html=True,
    )
    st.caption("Run the FastAPI service and Laya on your computer first. Workflow routes require a support token; review decisions require a separate reviewer token.")

    workbench_tab, data_tab, rag_tab, architecture_tab = st.tabs(
        ["Investigation workbench", "Data explorer", "RAG evaluation lab", "Agents & data flow"]
    )

    with workbench_tab:
        left, right = st.columns([.9, 1.1], gap="large")
        with left:
            st.markdown("### Start a controlled investigation")
            st.caption("Provide a ticket ID or message. An order ID is optional when it is present in the ticket text or linked ticket record.")
            with st.form("workflow_intake_form", clear_on_submit=False):
                ticket_id = st.text_input("Ticket ID", placeholder="Optional · e.g. T-003")
                message = st.text_area("Customer message", height=130, placeholder="Where is my order ORD-ID-44319aea3c?")
                order_id = st.text_input("Order ID", placeholder="Optional · ORD-ID-…")
                retrieval_query = st.text_input("Policy retrieval query", placeholder="Leave blank to use the ticket message")
                m1, m2 = st.columns(2)
                top_k = m1.slider("Passages per method", min_value=1, max_value=10, value=3)
                methods = m2.multiselect("Retrieval methods", ["semantic", "keyword"], default=["semantic", "keyword"])
                submitted = st.form_submit_button("Start investigation", type="primary", width="stretch")
            if submitted:
                if not support_token:
                    st.error("Enter a support bearer token in the sidebar first.")
                elif not ticket_id.strip() and not message.strip():
                    st.error("Enter a ticket ID, a customer message, or both.")
                elif not methods:
                    st.error("Select semantic retrieval, keyword retrieval, or both.")
                else:
                    payload = {
                        "schema_version": "1.0",
                        "ticket_id": ticket_id.strip() or None,
                        "message": message.strip() or None,
                        "order_id": order_id.strip() or None,
                        "query": retrieval_query.strip() or None,
                        "top_k": top_k,
                        "methods": methods,
                    }
                    try:
                        started = api_request("POST", "/workflows", base_url=base_url, token=support_token, payload=payload)
                        st.session_state.active_workflow_id = started["workflow_id"]
                        st.session_state.active_workflow = started
                        st.session_state.workflow_polling = started.get("status") == "running"
                        st.session_state.workflow_poll_error = None
                        st.success("Workflow accepted. The timeline on the right is following the persisted graph checkpoints.")
                        st.rerun()
                    except ApiError as exc:
                        st.error(f"Could not start the workflow: {exc}")
        with right:
            st.markdown("### Processing view")
            render_workflow_panel(base_url, support_token)

    with data_tab:
        st.markdown("### Inspect the underlying read-only tools")
        st.markdown("<span class='badge badge-amber'>LOCAL FIXTURE ENDPOINTS</span> &nbsp; These calls use the project's existing local-development API surface.", unsafe_allow_html=True)
        ticket_tool_tab, order_tool_tab, policy_tool_tab = st.tabs(["Ticket tools", "Order & delivery", "Policy retrieval"])
        with ticket_tool_tab:
            ticket_message = st.text_area("Message to classify", key="explorer_message", height=90)
            ticket_id_input = st.text_input("Fixture ticket ID for investigation", key="explorer_ticket_id", placeholder="T-003")
            order_id_input = st.text_input("Optional linked order ID", key="explorer_order_id")
            explore_methods = st.multiselect("Methods for this investigation", ["semantic", "keyword"], default=["semantic", "keyword"], key="explorer_methods")
            x1, x2 = st.columns(2)
            if x1.button("Classify message", key="classify_message"):
                st.session_state.explorer_classification = None
                if not ticket_message.strip():
                    st.error("Enter a customer message to classify.")
                else:
                    try:
                        result = local_api_request("POST", "/tickets/classify", base_url=base_url, payload={"schema_version": "1.0", "message": ticket_message})
                        st.session_state.explorer_classification = result
                    except ApiError as exc:
                        st.error(f"Classification failed: {exc}")
            if st.session_state.get("explorer_classification"):
                render_classification(st.session_state.explorer_classification) # type: ignore
            if x2.button("Investigate ticket", key="investigate_ticket"):
                st.session_state.explorer_investigation = None
                if not ticket_message.strip() and not ticket_id_input.strip():
                    st.error("Provide a message or fixture ticket ID.")
                else:
                    body = {
                        "schema_version": "1.0",
                        "message": ticket_message.strip() or None,
                        "ticket_id": ticket_id_input.strip() or None,
                        "order_id": order_id_input.strip() or None,
                        "top_k": 3,
                        "methods": explore_methods or ["keyword"],
                    }
                    try:
                        result = local_api_request("POST", "/tickets/investigate", base_url=base_url, payload=body,)
                        st.success("Investigation completed using the local fixture API.")
                        st.session_state.explorer_investigation = result
                    except ApiError as exc:
                        st.error(f"Ticket investigation failed: {exc}")
            if st.session_state.get("explorer_investigation"):
                investigation = st.session_state.explorer_investigation
                assert investigation is not None
                show_json_result("Ticket classification", investigation.get("classification"))
                show_json_result("Order evidence", investigation.get("order_evidence"))
                show_json_result("Policy evidence", investigation.get("policy_evidence"))

        with order_tool_tab:
            order_lookup_id = st.text_input("Order ID to inspect", key="order_lookup_id", placeholder="ORD-ID-44319aea3c")
            query_for_order = st.text_input("Question to combine with this order", key="combined_order_query", value="Where is my order?")
            b1, b2 = st.columns(2)
            if b1.button("Read order, delivery, and return facts", key="read_order_facts"):
                st.session_state.order_facts_result = None
                if not order_lookup_id.strip():
                    st.error("Enter an order ID.")
                else:
                    try:
                        encoded_order_id = quote(order_lookup_id.strip(), safe="")
                        investigation = local_api_request("GET", f"/orders/{encoded_order_id}/investigation", base_url=base_url)
                        st.session_state.order_facts_result = investigation
                    except ApiError as exc:
                        st.error(f"Order lookup failed: {exc}")
            if st.session_state.get("order_facts_result"):
                facts = st.session_state.order_facts_result
                assert facts is not None
                st.caption("Fetched from Neon with one API request and one read-only SQL statement.")
                show_json_result("Order, delivery, and return facts", facts)
            if st.button("Read loyalty and prior-contact context (optional)", key="read_customer_context"):
                st.session_state.customer_context_result = None
                if not order_lookup_id.strip():
                    st.error("Enter an order ID.")
                else:
                    try:
                        encoded_order_id = quote(order_lookup_id.strip(), safe="")
                        st.session_state.customer_context_result = local_api_request(
                            "GET", f"/orders/{encoded_order_id}/customer-context", base_url=base_url
                        )
                    except ApiError as exc:
                        st.error(f"Customer context lookup failed: {exc}")
            if st.session_state.get("customer_context_result"):
                context = st.session_state.customer_context_result
                assert context is not None
                if context.get("status") == "insufficient_data":
                    st.info("Optional loyalty or prior-contact tables are not available in this Neon schema.")
                show_json_result("Loyalty and prior-contact context", context)
            if b2.button("Combine order facts + policy search", key="combined_order_lookup"):
                st.session_state.combined_order_result = None
                if not order_lookup_id.strip():
                    st.error("Enter an order ID.")
                elif len(query_for_order.strip()) < 3:
                    st.error("Enter a policy question with at least three characters.")
                else:
                    try:
                        result = local_api_request(
                            "POST",
                            "/support/investigate",
                            base_url=base_url,
                            payload={"order_id": order_lookup_id.strip(), "query": query_for_order, "top_k": 3, "methods": ["semantic", "keyword"]},
                        )
                        st.session_state.combined_order_result = result
                    except ApiError as exc:
                        st.error(f"Combined investigation failed: {exc}")
            if st.session_state.get("combined_order_result"):
                combined = st.session_state.combined_order_result
                st.warning(combined.get("policy_scope_notice", "Retrieved policy evidence must be checked for applicability."))
                show_json_result("Combined investigation", combined)

        with policy_tool_tab:
            policy_query = st.text_input("Question to search against the policy corpus", key="policy_query", placeholder="What should I do if my order is damaged?")
            policy_methods = st.multiselect("Compare methods", ["semantic", "keyword"], default=["semantic", "keyword"], key="policy_methods")
            policy_top_k = st.slider("Top passages", 1, 10, 3, key="policy_top_k")
            if st.button("Search policy evidence", key="search_policy"):
                st.session_state.policy_search_result = None
                if len(policy_query.strip()) < 3:
                    st.error("Enter a policy question with at least three characters.")
                else:
                    try:
                        result = local_api_request(
                            "POST", "/policies/search", base_url=base_url,
                            payload={"schema_version": "1.0", "query": policy_query, "top_k": policy_top_k, "methods": policy_methods or ["keyword"]},
                        )
                        st.session_state.policy_search_result = result
                    except ApiError as exc:
                        st.error(f"Policy search failed: {exc}")
            if st.session_state.get("policy_search_result"):
                st.caption("Search results are evidence candidates; draft development policies do not establish customer eligibility.")
                render_policy_hits(st.session_state.policy_search_result) # type: ignore

    with rag_tab:
        st.markdown("### Evaluate retrieval quality")
        st.caption("Compare semantic and keyword results, inspect citations, and run the checked-in labeled evaluation set.")
        single_tab, batch_tab = st.tabs(["Single query", "Labeled set"])
        with single_tab:
            with st.form("rag_single_form"):
                eval_query = st.text_input("Query", value="What should I do if my order is damaged?")
                e1, e2, e3 = st.columns(3)
                expected_doc = e1.text_input("Expected document ID (optional)")
                expected_version = e2.text_input("Expected policy version (optional)")
                expected_section = e3.text_input("Expected section title (optional)")
                eval_top_k = st.slider("Top k", 1, 10, 3, key="single_eval_top_k")
                eval_methods = st.multiselect("Methods", ["semantic", "keyword"], default=["semantic", "keyword"], key="single_eval_methods")
                eval_submit = st.form_submit_button("Evaluate retrieval", type="primary")
            if eval_submit:
                st.session_state.rag_single_result = None
                try:
                    result = local_api_request(
                        "POST", "/rag/evaluate", base_url=base_url,
                        payload={
                            "query": eval_query,
                            "expected_document_id": expected_doc.strip() or None,
                            "expected_policy_version": expected_version.strip() or None,
                            "expected_section_title": expected_section.strip() or None,
                            "top_k": eval_top_k,
                            "methods": eval_methods or ["keyword"],
                        },
                    )
                    st.session_state.rag_single_result = result
                except ApiError as exc:
                    st.error(f"RAG evaluation failed: {exc}")
            if st.session_state.get("rag_single_result"):
                render_evaluation(st.session_state.rag_single_result) # type: ignore
        with batch_tab:
            st.markdown("Run all checked-in labeled questions against the selected retrievers.")
            batch_top_k = st.slider("Top k for batch", 1, 10, 3, key="batch_top_k")
            batch_methods = st.multiselect("Batch methods", ["semantic", "keyword"], default=["semantic", "keyword"], key="batch_methods")
            if st.button("Run labeled evaluation set", type="primary", key="run_label_set"):
                st.session_state.rag_batch_result = None
                try:
                    result = local_api_request(
                        "POST", "/rag/evaluate/labeled-set", base_url=base_url,
                        payload={"top_k": batch_top_k, "methods": batch_methods or ["keyword"]},
                        timeout=90,
                    )
                    st.session_state.rag_batch_result = result
                except ApiError as exc:
                    st.error(f"Batch evaluation failed: {exc}")
            if st.session_state.get("rag_batch_result"):
                render_evaluation(st.session_state.rag_batch_result) # type: ignore

    with architecture_tab:
        render_pipeline_overview()


if __name__ == "__main__":
    main()
