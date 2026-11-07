"""Streamlit control room for the local customer support investigation project."""

from __future__ import annotations

import hashlib
import html
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = Path(__file__).resolve().parent
for directory in (str(PROJECT_ROOT), str(FRONTEND_DIR)):
    if directory not in sys.path:
        sys.path.insert(0, directory)

import httpx
import streamlit as st
from dotenv import load_dotenv

try:
    from frontend.chat_context import resolve_order_context
except ModuleNotFoundError:
    from chat_context import resolve_order_context

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
    /* Chat panel */
    [data-testid="stChatMessage"] { border-radius:14px; padding:4px 2px; }
    [data-testid="stChatMessageContent"] p { font-size:.93rem; line-height:1.6; }
    [data-testid="stChatInput"] textarea { background:#111c27 !important; border:1px solid #2a3f52 !important; border-radius:12px !important; color:var(--ink) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@st.cache_resource
def api_client() -> httpx.Client:
    """Reuse local API connections across fragment polls; credentials stay per call."""
    return httpx.Client(limits=httpx.Limits(max_connections=12, max_keepalive_connections=6))


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
    configured_api = get_token("API_BASE_URL") or get_token("FASTAPI_BASE_URL")
    demo_token = get_token("DEMO_API_TOKEN")
    if demo_token and configured_api and urlparse(base_url).scheme == "https" and base_url.rstrip("/") == configured_api.rstrip("/"):
        headers["X-Demo-Token"] = demo_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    try:
        response = api_client().request(
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
    hostname = (urlparse(base_url).hostname or "").lower()
    return (
        hostname in {"127.0.0.1", "localhost", "::1"}
        or hostname.endswith(".onrender.com")
        or bool(os.getenv("ALLOW_REMOTE_API"))
    )


def local_api_request(method: str, path: str, *, base_url: str, payload: dict[str, Any] | None = None, timeout: float = 60.0) -> Any:
    if not loopback_api(base_url):
        raise ApiError("This local fixture endpoint is only enabled when the API URL points to this computer.")
    return api_request(method, path, base_url=base_url, payload=payload, timeout=timeout)


def show_json_result(title: str, payload: Any) -> None:
    st.markdown(f"#### {title}")
    st.json(payload, expanded=False)


def classification_score(classification: dict[str, Any]) -> str:
    if classification.get("classifier_provider") == "deterministic_rule":
        return "Rule match"
    score = classification.get("confidence")
    return f"{score:.1%} (raw)" if isinstance(score, (int, float)) else "—"


def get_token(key: str) -> str:
    """Discover a credential from st.secrets, os.environ, or return empty string."""
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:  # noqa: BLE001, S110
        pass
    return os.getenv(key, "").strip()


def groq_synthesize_investigation(
    message: str,
    answer_lines: list[str],
    intent: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> str | None:
    """Optionally synthesize an empathetic, natural customer response using Groq."""
    key = api_key or get_token("GROQ_API_KEY")
    if not key or key.startswith("CHANGE_ME"):
        return None
    mdl = model or os.getenv("GROQ_MODEL", "").strip() or "llama-3.3-70b-versatile"
    facts_text = "\n".join(f"- {line}" for line in answer_lines)
    payload = {
        "model": mdl,
        "temperature": 0.3,
        "max_tokens": 400,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a friendly, empathetic customer support AI for an e-commerce platform. "
                    "Draft a warm, polite, natural response directly answering the customer query based ONLY on the verified details below. "
                    "Explain the order status, items, delivery tracking, or policies clearly and reassuringly. "
                    "Never promise or claim to have executed refunds, replacements, or cancellations if not explicitly confirmed in the verified facts."
                ),
            },
            {
                "role": "user",
                "content": f"Customer Message: {message}\n\nVerified Investigation Facts:\n{facts_text}\n\nPlease respond to the customer:",
            },
        ],
    }
    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            if resp.is_success:
                return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
    return None


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
        st.info("Start an investigation above to see the live agent timeline here.", icon=":material/query_stats:")
        return
    if st.session_state.get("workflow_poll_error"):
        st.error(f"Last refresh failed: {st.session_state.workflow_poll_error}")

    poll_rate = "0.8s" if st.session_state.get("workflow_polling") else None

    @st.fragment(run_every=poll_rate)
    def workflow_fragment() -> None:
        wid = st.session_state.get("active_workflow_id")
        if not wid:
            return

        is_polling = bool(st.session_state.get("workflow_polling"))

        if is_polling:
            try:
                snapshot = api_request("GET", f"/workflows/{wid}/snapshot", base_url=base_url, token=support_token)
                result = snapshot["workflow"]
                events = snapshot["events"]
                trace = snapshot["trace"]
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

            still_running = result.get("status") == "running"
            st.session_state.workflow_polling = still_running

            if not still_running:
                # Workflow just settled — push answer into chat history
                answer       = trace.get("answer") or result.get("answer")
                status_final = result.get("status", "unknown")
                intent       = (trace.get("classification") or result.get("classification") or {}).get("intent", "—")
                confidence   = (trace.get("classification") or result.get("classification") or {}).get("confidence")
                conf_str = classification_score(trace.get("classification") or result.get("classification") or {})
                chat_hist    = st.session_state.get("chat_history", [])
                already_resolved = any(
                    m["role"] == "assistant" and m.get("resolved_workflow_id") == wid
                    for m in chat_hist
                )
                if not already_resolved:
                    for turn in chat_hist:
                        if turn.get("started_workflow_id") == wid:
                            turn["content"] = f"Investigation `{wid[:8]}…` completed."
                            turn["meta"] = f"Status: {status_final.replace('_', ' ')}"
                    if answer:
                        chat_hist.append({
                            "role": "assistant", "avatar": "🤖",
                            "content": answer,
                            "meta": f"Intent: {str(intent).replace('_', ' ').title()} · Score: {conf_str} · {status_final.replace('_', ' ').title()}",
                            "resolved_workflow_id": wid,
                        })
                    elif status_final == "pending_approval":
                        chat_hist.append({
                            "role": "assistant", "avatar": "🔍",
                            "content": "Workflow needs **human approval**. Use the approval gate below.",
                            "meta": f"Intent: {str(intent).replace('_', ' ').title()} · Score: {conf_str}",
                            "resolved_workflow_id": wid,
                        })
                    else:
                        chat_hist.append({
                            "role": "assistant", "avatar": "⚠️",
                            "content": f"Workflow ended: **{status_final.replace('_', ' ')}**",
                            "meta": f"Reason codes: {', '.join(result.get('reason_codes') or ['—'])}",
                            "resolved_workflow_id": wid,
                        })
                    st.session_state.chat_history = chat_hist
                st.rerun()
        else:
            # Settled — read from cache, no HTTP
            result = st.session_state.get("active_workflow") or {}
            events = st.session_state.get("active_events") or []
            trace  = st.session_state.get("active_trace")  or {}

        # ── Render ────────────────────────────────────────────────────────────
        status     = result.get("status", "unknown")
        intent     = (trace.get("classification") or result.get("classification") or {}).get("intent", "—")
        confidence = (trace.get("classification") or result.get("classification") or {}).get("confidence")
        specialist = str(trace.get("specialist") or result.get("specialist") or "—")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Workflow", status.replace("_", " ").title())
        c2.metric("Intent", str(intent).replace("_", " ").title())
        c3.metric("Specialist", specialist.replace("_", " ").title())
        c4.metric("Routing signal", classification_score(trace.get("classification") or result.get("classification") or {}))
        st.caption("Model scores are uncalibrated and do not measure accuracy. Rule matches only identify a bounded read-only request.")

        col_refresh, _ = st.columns([1, 5])
        if col_refresh.button(":material/refresh: Refresh", key="refresh_workflow"):
            st.session_state.workflow_polling = True
            st.rerun()

        if is_polling:
            st.caption("⏱ Live — polling every 0.8 s")

        # ── 1. Agent result (Stacked on top) ───────────────────────────────────
        with st.container(border=True):
            st.markdown("#### Agent result")
            classification = trace.get("classification") or result.get("classification")
            if classification:
                cprovider, ctriage = st.columns(2)
                cprovider.caption("Classifier: " + str(classification.get("classifier_provider", "unknown")))
                ctriage.caption("Triage: " + str(classification.get("triage_status", "unknown")))
                if classification.get("fallback_used"):
                    st.warning("Laya unavailable — fallback is review-only.")
                if classification.get("risk_flags"):
                    st.caption("Risk flags: " + ", ".join(classification["risk_flags"]))
            answer = trace.get("answer") or result.get("answer")
            if answer:
                if status == "answer_ready":
                    st.success(answer, icon=":material/check_circle:")
                else:
                    st.info(answer)
            elif status == "running":
                st.caption("Agent is processing… timeline refreshes automatically.")
            elif status == "pending_approval":
                st.info("Paused at approval gate — no action taken yet.")
            if result.get("reason_codes"):
                st.caption("Outcome codes: " + ", ".join(result["reason_codes"]))

        # ── 2. Live run timeline (Stacked below agent result) ─────────────────
        with st.container(border=True):
            st.markdown("#### Live run timeline")
            render_timeline(events, trace, status)

        if result.get("evidence_refs"):
            st.markdown("**Evidence references**")
            st.code("\n".join(result["evidence_refs"]), language="text")

        evidence_expander = st.expander("Evidence & decision data", expanded=False, on_change="rerun")
        if evidence_expander.open:  # only render expensive tabs when open
            with evidence_expander:
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
    b.metric("Routing signal", classification_score(classification))
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

    st.sidebar.markdown("### Navigation")
    selected_page = st.sidebar.radio(
        "Navigation Menu",
        [
            "Investigation workbench",
            "Data explorer",
            "RAG evaluation lab",
            "Agents & data flow",
        ],
        index=0,
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Connection")

    # Discover API URL: st.secrets -> os.getenv -> default
    api_url_from_secrets = ""
    try:
        api_url_from_secrets = str(st.secrets.get("API_BASE_URL") or st.secrets.get("FASTAPI_BASE_URL") or "").strip()
    except Exception:
        pass
    configured_api_url = (api_url_from_secrets or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).strip().rstrip("/")
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

    support_token = get_token("WORKFLOW_API_TOKEN")
    reviewer_token = get_token("WORKFLOW_REVIEWER_TOKEN")

    if support_token and reviewer_token:
        st.sidebar.caption("🔒 Tokens loaded from secrets/environment.")
    else:
        if not support_token:
            support_token = st.sidebar.text_input(
                "Support bearer token",
                type="password",
                key="manual_support_token",
                help="Can be configured in st.secrets['WORKFLOW_API_TOKEN'].",
            ).strip()
        if not reviewer_token:
            reviewer_token = st.sidebar.text_input(
                "Reviewer bearer token",
                type="password",
                key="manual_reviewer_token",
                help="Can be configured in st.secrets['WORKFLOW_REVIEWER_TOKEN'].",
            ).strip()

    groq_token = get_token("GROQ_API_KEY")
    if groq_token and not groq_token.startswith("CHANGE_ME"):
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        st.sidebar.caption(f"⚡ **Groq LLM Active** (`{groq_model}`)")
    else:
        user_groq = st.sidebar.text_input(
            "Groq API Key (Optional)",
            type="password",
            key="manual_groq_key",
            help="Add GROQ_API_KEY in .env or st.secrets for AI-synthesized responses.",
        ).strip()
        if user_groq:
            os.environ["GROQ_API_KEY"] = user_groq
            st.sidebar.caption("⚡ **Groq Key Set**")

    # Never carry a previous user's evidence/context across API or token changes.
    context_owner = hashlib.sha256(f"{base_url}\0{support_token}".encode()).hexdigest()
    if st.session_state.get("chat_context_owner") != context_owner:
        for key in ("chat_history", "chat_last_order_id", "active_workflow_id", "active_workflow", "active_trace", "active_events", "workflow_polling", "chat_order_id", "chat_ticket_id", "ctx_order_id", "ctx_ticket_id"):
            st.session_state.pop(key, None)
        st.session_state.chat_context_owner = context_owner
    st.session_state.support_token = support_token
    st.session_state.reviewer_token = reviewer_token

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

    if selected_page == "Investigation workbench":
        # ── Session-state initialisation ─────────────────────────────────────
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        if "chat_order_id" not in st.session_state:
            st.session_state.chat_order_id = ""
        if "chat_ticket_id" not in st.session_state:
            st.session_state.chat_ticket_id = ""
        if "chat_top_k" not in st.session_state:
            st.session_state.chat_top_k = 3
        if "chat_methods" not in st.session_state:
            st.session_state.chat_methods = ["semantic", "keyword"]

        # ── TOP: Investigation chat (Full Width) ─────────────────────────────
        st.markdown("### Investigation chat")
        st.caption("Each message is safety checked. The last order reference carries over in this chat; records are read again for each investigation.")
        if st.session_state.get("chat_last_order_id"):
            st.caption(f"Current order context: {st.session_state.chat_last_order_id}")

        # Context strip — inline settings above the chat
        with st.container(border=True):
            ctx1, ctx2, ctx3, ctx4, ctx5 = st.columns([1.8, 1.8, 1, 1.8, 2.2])
            st.session_state.chat_ticket_id = ctx1.text_input(
                "Ticket ID", value=st.session_state.chat_ticket_id,
                placeholder="Optional · T-003", label_visibility="visible", key="ctx_ticket_id",
            )
            st.session_state.chat_order_id = ctx2.text_input(
                "Order ID", value=st.session_state.chat_order_id,
                placeholder="ORD-ID-…", label_visibility="visible", key="ctx_order_id",
            )
            st.session_state.chat_top_k = ctx3.number_input(
                "Top-k", min_value=1, max_value=10,
                value=st.session_state.chat_top_k, key="ctx_top_k",
            )
            st.session_state.chat_methods = ctx4.multiselect(
                "Methods", ["semantic", "keyword"],
                default=st.session_state.chat_methods, key="ctx_methods",
            )
            engine_mode = ctx5.segmented_control(
                "Engine",
                ["⚡ Investigate Tool", "⚙️ Workflow"],
                default=st.session_state.get("chat_engine_mode", "⚡ Investigate Tool"),
                key="chat_engine_mode",
            )

        # Render chat history
        chat_container = st.container(height=360, border=False)
        with chat_container:
            if not st.session_state.chat_history:
                st.markdown(
                    "<div style='text-align:center;color:#526370;padding:50px 0 20px'>"
                    "<div style='font-size:2.2rem'>💬</div>"
                    "<div style='font-size:.93rem;margin-top:.5rem'>Send a customer message to start an investigation.<br>"
                    "Previous turns are kept as context.</div></div>",
                    unsafe_allow_html=True,
                )
            for turn in st.session_state.chat_history:
                with st.chat_message(turn["role"], avatar=turn.get("avatar")):
                    st.markdown(turn["content"])
                    if turn.get("meta"):
                        st.caption(turn["meta"])

        # Chat input (always at the bottom of the chat panel)
        user_input = st.chat_input(
            "Describe the customer's issue…",
            key="investigation_chat_input",
            disabled=not bool(support_token),
        )
        if not support_token:
            st.caption("🔒 Enter a support token in the sidebar to enable chat.")

        if user_input:
            methods = st.session_state.chat_methods or ["keyword"]
            order_context = resolve_order_context(
                user_input,
                st.session_state.chat_order_id,
                st.session_state.get("chat_last_order_id"),
            )
            if order_context:
                st.session_state.chat_last_order_id = order_context
                st.session_state.chat_order_id = order_context

            # Append user turn to history
            st.session_state.chat_history.append({
                "role": "user",
                "avatar": "🧑‍💼",
                "content": user_input,
                "meta": (
                    (f"Ticket: `{st.session_state.chat_ticket_id}`  " if st.session_state.chat_ticket_id else "")
                    + (f"Order: `{order_context}`  " if order_context else "")
                    + f"top-k: {st.session_state.chat_top_k}  methods: {', '.join(methods)}"
                ),
            })

            # Ensure message carries order context if available and not already mentioned
            effective_message = user_input.strip()
            if order_context and order_context not in effective_message:
                effective_message = f"{effective_message} for order {order_context}"

            mode = st.session_state.get("chat_engine_mode") or "⚡ Investigate Tool"

            if mode == "⚡ Investigate Tool":
                try:
                    payload = {
                        "schema_version": "1.0",
                        "ticket_id": st.session_state.chat_ticket_id.strip() or None,
                        "message": effective_message,
                        "order_id": order_context,
                        "top_k": st.session_state.chat_top_k,
                        "methods": methods,
                    }
                    with st.spinner("Running investigation tool…"):
                        res = local_api_request("POST", "/tickets/investigate", base_url=base_url, payload=payload, timeout=60.0)

                    classification = res.get("classification") or {}
                    order_ev = res.get("order_evidence") or {}
                    order = order_ev.get("order") or {}
                    items = order_ev.get("items") or []
                    delivery_events = order_ev.get("delivery_events") or []
                    policy_ev = res.get("policy_evidence") or {}
                    ledger = res.get("evidence_ledger") or {}
                    intent = classification.get("intent", "order_status")

                    # Formulate grounded response
                    answer_lines = []
                    if order.get("order_id"):
                        status_str = str(order.get("status", "unknown")).replace("_", " ")
                        answer_lines.append(f"Your order **`{order['order_id']}`** is marked as **{status_str}**.")
                    elif intent == "order_status":
                        answer_lines.append("Order status investigated.")

                    if items:
                        item_str = ", ".join(f"{it.get('product_name', 'Item')} (qty {it.get('quantity', 1)})" for it in items[:6])
                        answer_lines.append(f"📦 **Order items:** {item_str}")

                    if delivery_events:
                        latest = delivery_events[-1]
                        evt_name = str(latest.get("event_type", "Event")).replace("_", " ").title()
                        evt_loc = latest.get("location", "")
                        evt_time = latest.get("event_time", "")
                        evt_desc = evt_name + (f" at {evt_loc}" if evt_loc else "") + (f" on {evt_time}" if evt_time else "")
                        answer_lines.append(f"🚚 **Latest delivery event:** {evt_desc}")

                    if not order.get("order_id") and policy_ev.get("results"):
                        passages = []
                        for method_hits in policy_ev["results"].values():
                            for hit in (method_hits or [])[:2]:
                                if hit.get("text"):
                                    passages.append(f"> {hit['text'].strip()}")
                        if passages:
                            answer_lines.append("📋 **Policy Evidence:**\n" + "\n\n".join(passages[:2]))

                    if not answer_lines:
                        answer_lines.append("Investigation completed successfully using the investigation tool.")

                    # Check if Groq can synthesize an empathetic conversational response
                    groq_answer = None
                    groq_key_to_use = get_token("GROQ_API_KEY")
                    if groq_key_to_use and not groq_key_to_use.startswith("CHANGE_ME"):
                        with st.spinner("Synthesizing empathetic response with Groq…"):
                            groq_answer = groq_synthesize_investigation(
                                effective_message,
                                answer_lines,
                                intent,
                                api_key=groq_key_to_use,
                            )

                    answer = groq_answer if groq_answer else "\n\n".join(answer_lines)
                    inv_id = f"tool-inv-{uuid.uuid4().hex[:8]}"

                    # Save into workflow / trace session state so processing view renders it
                    st.session_state.active_workflow_id = inv_id
                    st.session_state.workflow_polling = False
                    st.session_state.active_workflow = {
                        "workflow_id": inv_id,
                        "status": "answer_ready",
                        "classification": classification,
                        "specialist": "order_delivery" if "order" in intent else "policy_faq",
                        "answer": answer,
                        "reason_codes": ["investigation_tool_direct_evidence"],
                    }
                    st.session_state.active_trace = {
                        "classification": classification,
                        "specialist": "order_delivery" if "order" in intent else "policy_faq",
                        "answer": answer,
                        "evidence": {
                            "order": order_ev,
                            "policy": policy_ev,
                            "customer_context": res.get("customer_context"),
                            "ledger": ledger,
                        },
                        "evidence_refs": [ref for chunk in (policy_ev.get("results") or {}).values() for hit in chunk for ref in [hit.get("chunk_id")] if ref],
                        "resolution": {"outcome": "answer", "reason_codes": ["investigation_tool_grounded"]},
                    }
                    st.session_state.active_events = [
                        {"stage": "intake", "event_type": "investigation_tool_called", "details": {"source": "direct_tool"}, "occurred_at": datetime.now().isoformat()},
                        {"stage": "triage", "event_type": "ticket_classified", "details": {"intent": intent, "provider": classification.get("classifier_provider")}, "occurred_at": datetime.now().isoformat()},
                        {"stage": "evidence", "event_type": "evidence_retrieved", "details": {"order_found": bool(order), "items_count": len(items)}, "occurred_at": datetime.now().isoformat()},
                        {"stage": "resolution", "event_type": "grounded_response_generated", "details": {"status": "answer_ready"}, "occurred_at": datetime.now().isoformat()},
                    ]

                    # Append answer to chat history
                    raw_conf = classification.get("confidence")
                    conf_str = f"{raw_conf * 100:.1f}%" if raw_conf is not None else "—"
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "avatar": "🤖",
                        "content": answer,
                        "meta": f"Intent: {str(intent).replace('_', ' ').title()} · Confidence: {conf_str} · Engine: Investigate Tool (instant)",
                    })
                except Exception as exc:  # noqa: BLE001
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "avatar": "⚠️",
                        "content": f"Investigation tool error: **{exc}**",
                        "meta": None,
                    })
            else:
                payload = {
                    "schema_version": "1.0",
                    "ticket_id": st.session_state.chat_ticket_id.strip() or None,
                    "message": effective_message,
                    "order_id": order_context,
                    "top_k": st.session_state.chat_top_k,
                    "methods": methods,
                }
                try:
                    started = api_request(
                        "POST", "/workflows",
                        base_url=base_url, token=support_token, payload=payload,
                    )
                    wid = started["workflow_id"]
                    st.session_state.active_workflow_id = wid
                    st.session_state.active_workflow = started
                    st.session_state.workflow_polling = started.get("status") == "running"
                    st.session_state.workflow_poll_error = None
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "avatar": "🤖",
                        "content": f"Investigation started — workflow `{wid[:8]}…` is running.",
                        "meta": f"Status: {started.get('status', 'queued')} · Check processing view below ↓",
                        "started_workflow_id": wid,
                    })
                except ApiError as exc:
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "avatar": "⚠️",
                        "content": f"Could not start the workflow: **{exc}**",
                        "meta": None,
                    })
            st.rerun()

        # Clear chat button
        if st.session_state.chat_history:  # noqa: SIM102
            if st.button(":material/delete_sweep: Clear chat", key="clear_chat"):
                st.session_state.chat_history = []
                st.session_state.chat_last_order_id = None
                st.session_state.active_workflow_id = None
                st.session_state.workflow_polling = False
                st.rerun()

        # ── BOTTOM: Processing panel (Stacked directly below chat) ───────────
        st.markdown("<hr style='margin: 2.5rem 0 1.5rem; border: none; border-top: 1px solid var(--line);'>", unsafe_allow_html=True)
        st.markdown("### Processing view")
        render_workflow_panel(base_url, support_token)

    elif selected_page == "Data explorer":
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
                assert combined is not None
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

    elif selected_page == "RAG evaluation lab":
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

    elif selected_page == "Agents & data flow":
        render_pipeline_overview()


if __name__ == "__main__":
    main()
