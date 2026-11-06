"""Local RAG evaluation API for the synthetic development policy collection."""

from __future__ import annotations

import csv
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.investigations import router as investigations_router
from backend.app.api.routes.orders import router as orders_router
from backend.app.api.routes.policies import router as policies_router
from backend.app.api.routes.tickets import router as tickets_router
from backend.app.api.routes.workflows import router as workflows_router
from backend.app.api.routes.proposals import router as proposals_router
from backend.app.api.routes.approvals import router as approvals_router
from backend.app.agents.graph import close_workflow_graph
from backend.app.approval.workflow_state import close_workflow_pool
from backend.app.observability.tracing import shutdown_langfuse
from backend.app.middleware.error_handler import install_error_handlers
from backend.app.middleware.request_id import install_request_middleware
from backend.app.milvus_index import collection_name
from backend.app.observability.logging import log_safe_error
from backend.app.order_lookup import (
    OrderDatabaseUnavailable,
    OrderNotFoundError,
    lookup_order_readonly,
)
from backend.app.policy_retrieval import (
    KeywordPolicyRetriever,
    MilvusPolicyRetriever,
)
from backend.app.runtime import load_project_environment, require_local_development
from backend.app.tools.policy_tools import close_policy_retrievers

logger = logging.getLogger(__name__)
load_project_environment()
_local_environment = os.getenv("APP_ENV", "").strip().lower() in {"local", "dev", "development"}
METHOD = Literal["semantic", "keyword"]
DEFAULT_EVALUATION_SET = PROJECT_ROOT / "data" / "processed" / "rag_policy_evaluation_v1.csv"


@asynccontextmanager
async def lifespan(_app):
    import threading

    def _warmup_classifiers():
        try:
            from backend.app.classification.laya import classify_with_laya
            classify_with_laya("Where is my order")
            logger.info("Laya classifier warmed up in background thread")
        except Exception as exc:
            logger.warning("Laya warmup skipped: %s", exc)

    threading.Thread(target=_warmup_classifiers, daemon=True, name="classifier-warmup").start()

    try:
        yield
    finally:
        shutdown_langfuse()
        close_workflow_graph()
        close_workflow_pool()
        close_policy_retrievers()


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=3000)
    expected_document_id: str | None = Field(default=None, max_length=128)
    expected_policy_version: str | None = Field(default=None, max_length=32)
    expected_section_title: str | None = Field(default=None, max_length=256)
    top_k: int = Field(default=3, ge=1, le=10)
    methods: list[METHOD] = Field(default_factory=lambda: ["semantic", "keyword"], min_length=1, max_length=2)


class BatchCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=3, max_length=3000)
    expected_document_id: str = Field(min_length=1, max_length=128)
    expected_policy_version: str | None = Field(default=None, max_length=32)
    expected_section_title: str | None = Field(default=None, max_length=256)


class BatchEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[BatchCase] | None = Field(default=None, max_length=50)
    top_k: int = Field(default=3, ge=1, le=10)
    methods: list[METHOD] = Field(default_factory=lambda: ["semantic", "keyword"], min_length=1, max_length=2)


class SupportInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=3, max_length=3000)
    top_k: int = Field(default=3, ge=1, le=10)
    methods: list[METHOD] = Field(default_factory=lambda: ["semantic", "keyword"], min_length=1, max_length=2)


class Evidence(BaseModel):
    rank: int
    score: float
    document_id: str
    policy_id: str
    policy_version: str
    artifact_type: str
    status: str
    marketplace: str
    environment_scope: str
    section_id: str
    section_title: str
    chunk_id: str
    source_uri: str
    source_path: str
    source_file_sha256: str
    excerpt: str
    jurisdiction: str = ""
    locale: str = ""
    effective_from: str = ""
    effective_to: str = ""
    synthetic_demo: bool = True
    intents: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class CaseScores(BaseModel):
    expected_document_hit_at_1: bool
    expected_document_hit_at_k: bool
    expected_version_at_1: bool | None
    expected_section_at_1: bool | None


class MethodResult(BaseModel):
    hits: list[Evidence]
    evaluation: CaseScores | None


class CaseResult(BaseModel):
    case_id: str | None
    query: str
    expected_document_id: str | None
    expected_policy_version: str | None
    expected_section_title: str | None
    methods: dict[str, MethodResult]


class RetrievalMetrics(BaseModel):
    query_count: int
    expected_document_hit_at_1: float
    expected_document_hit_at_k: float
    mrr_at_k: float
    expected_version_at_1: float | None
    expected_section_at_1: float | None
    scope_compliance: float
    citation_metadata_completeness: float


class EvaluationResponse(BaseModel):
    collection: str | None
    top_k: int
    methods: list[str]
    metrics: dict[str, RetrievalMetrics] | None
    cases: list[CaseResult]
    corpus_scope: str


class SupportInvestigationResponse(BaseModel):
    request_id: str
    execution_scope: str
    order_evidence: dict
    milvus_collection: str | None
    policy_evidence: dict[str, list[Evidence]]
    policy_scope_notice: str


def _validate_methods(methods: list[str]) -> list[str]:
    selected = list(dict.fromkeys(methods))
    if not selected:
        raise HTTPException(status_code=422, detail="Select semantic, keyword, or both methods")
    return selected


def _make_case_scores(case: dict, hits: list[dict], top_k: int) -> dict | None:
    expected_document_id = case.get("expected_document_id")
    if not expected_document_id:
        return None
    top = hits[0] if hits else {}
    doc_at_1 = top.get("document_id") == expected_document_id
    doc_at_k = any(hit.get("document_id") == expected_document_id for hit in hits[:top_k])
    expected_version = case.get("expected_policy_version")
    expected_section = case.get("expected_section_title")
    return {
        "expected_document_hit_at_1": doc_at_1,
        "expected_document_hit_at_k": doc_at_k,
        "expected_version_at_1": (doc_at_1 and top.get("policy_version") == expected_version) if expected_version else None,
        "expected_section_at_1": (doc_at_1 and top.get("section_title") == expected_section) if expected_section else None,
    }


def _retrieve_case(
    case: dict,
    *,
    top_k: int,
    methods: list[str],
    semantic: MilvusPolicyRetriever | None,
    keyword: KeywordPolicyRetriever | None,
) -> dict:
    method_results = {}
    for method in methods:
        if method == "semantic":
            if semantic is None:
                raise RuntimeError("Semantic retriever is unavailable")
            hits = semantic.search(case["query"], top_k=top_k)
        else:
            if keyword is None:
                raise RuntimeError("Keyword retriever is unavailable")
            hits = keyword.search(case["query"], top_k=top_k)
        method_results[method] = {
            "hits": hits,
            "evaluation": _make_case_scores(case, hits, top_k),
        }
    return {
        "case_id": case.get("case_id"),
        "query": case["query"],
        "expected_document_id": case.get("expected_document_id"),
        "expected_policy_version": case.get("expected_policy_version"),
        "expected_section_title": case.get("expected_section_title"),
        "methods": method_results,
    }


def _aggregate_metrics(cases: list[dict], evaluated: list[dict], methods: list[str], top_k: int) -> dict:
    aggregate = {}
    for method in methods:
        rows = [entry["methods"][method] for entry in evaluated]
        scores = [row["evaluation"] for row in rows]
        total = len(scores)
        reciprocal_ranks = []
        scope_ok = 0
        citation_ok = 0
        returned = 0
        for case, row in zip(cases, rows):
            hits = row["hits"]
            docs = [hit.get("document_id") for hit in hits]
            expected = case["expected_document_id"]
            rank = next((idx + 1 for idx, document_id in enumerate(docs[:top_k]) if document_id == expected), None)
            reciprocal_ranks.append(1 / rank if rank else 0.0)
            for hit in hits:
                returned += 1
                scope_ok += int(
                    hit.get("status") == "draft"
                    and hit.get("environment_scope") == "development-only"
                    and hit.get("marketplace") == "synthetic-fixture"
                )
                citation_ok += int(bool(hit.get("document_id") and hit.get("policy_version") and hit.get("excerpt")))
        section_cases = [score for score in scores if score["expected_section_at_1"] is not None]
        version_cases = [score for score in scores if score["expected_version_at_1"] is not None]
        aggregate[method] = {
            "query_count": total,
            "expected_document_hit_at_1": sum(score["expected_document_hit_at_1"] for score in scores) / total if total else 0.0,
            "expected_document_hit_at_k": sum(score["expected_document_hit_at_k"] for score in scores) / total if total else 0.0,
            "mrr_at_k": sum(reciprocal_ranks) / total if total else 0.0,
            "expected_version_at_1": sum(score["expected_version_at_1"] for score in version_cases) / len(version_cases) if version_cases else None,
            "expected_section_at_1": sum(score["expected_section_at_1"] for score in section_cases) / len(section_cases) if section_cases else None,
            "scope_compliance": scope_ok / returned if returned else 1.0,
            "citation_metadata_completeness": citation_ok / returned if returned else 1.0,
        }
    return aggregate


def _default_cases() -> list[dict]:
    if not DEFAULT_EVALUATION_SET.exists():
        raise FileNotFoundError(f"Labeled RAG evaluation set not found: {DEFAULT_EVALUATION_SET}")
    with DEFAULT_EVALUATION_SET.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _run_cases(cases: list[dict], top_k: int, methods: list[str]) -> dict:
    selected_methods = _validate_methods(methods)
    semantic = MilvusPolicyRetriever() if "semantic" in selected_methods else None
    keyword = KeywordPolicyRetriever() if "keyword" in selected_methods else None
    try:
        evaluated = [
            _retrieve_case(case, top_k=top_k, methods=selected_methods, semantic=semantic, keyword=keyword)
            for case in cases
        ]
    finally:
        if semantic is not None:
            semantic.close()
    aggregate = _aggregate_metrics(cases, evaluated, selected_methods, top_k) if all(case.get("expected_document_id") for case in cases) else None
    return {
        "collection": collection_name() if "semantic" in selected_methods else None,
        "top_k": top_k,
        "methods": selected_methods,
        "metrics": aggregate,
        "cases": evaluated,
        "corpus_scope": "synthetic development-only draft documents; not production policy",
    }


def _safe_run(cases: list[dict], top_k: int, methods: list[str], *, request_id: str = "unavailable") -> dict:
    try:
        require_local_development()
        return _run_cases(cases, top_k, methods)
    except HTTPException:
        raise
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        log_safe_error(logger, event="rag_evaluation_failed", request_id=request_id, stage="rag_evaluation", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(logger, event="rag_evaluation_failed", request_id=request_id, stage="rag_evaluation", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="RAG dependency unavailable; check the Milvus and embedding-model configuration") from exc


app = FastAPI(
    title="Agentic Customer Support Investigation API",
    description=(
        "Local support investigation API. Legacy Day 4 read-only routes remain local-development-only. "
        "LangGraph workflow routes require bearer authentication and enforce ticket/order scope. "
        "Approval records only a simulation and cannot execute customer or order actions."
    ),
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _local_environment else None,
    redoc_url="/redoc" if _local_environment else None,
    openapi_url="/openapi.json" if _local_environment else None,
)


install_request_middleware(app)
install_error_handlers(app)
app.include_router(health_router)
app.include_router(tickets_router)
app.include_router(investigations_router)
app.include_router(orders_router)
app.include_router(policies_router)
app.include_router(workflows_router)
app.include_router(proposals_router)
app.include_router(approvals_router)


@app.post("/rag/evaluate", response_model=EvaluationResponse)
def evaluate_query(request: EvaluationRequest, http_request: Request) -> dict:
    """Evaluate one query, optionally against expected document/version/section labels."""
    case = request.model_dump(exclude={"top_k", "methods"})
    return _safe_run([case], request.top_k, request.methods, request_id=http_request.state.request_id) # type: ignore


@app.post("/rag/evaluate/labeled-set", response_model=EvaluationResponse)
def evaluate_labeled_set(http_request: Request, request: BatchEvaluationRequest | None = None) -> dict:
    """Run the checked-in 11-case set, or a supplied labeled case list."""
    request = request or BatchEvaluationRequest()
    cases = [case.model_dump() for case in request.cases] if request.cases else _default_cases()
    if not cases:
        raise HTTPException(status_code=422, detail="Evaluation set has no cases")
    return _safe_run(cases, request.top_k, request.methods, request_id=http_request.state.request_id) # type: ignore


@app.post("/support/investigate", response_model=SupportInvestigationResponse)
def investigate_order(request: SupportInvestigationRequest, http_request: Request) -> dict:
    """Combine allowlisted Neon order facts with separately retrieved policy excerpts."""
    try:
        order_evidence = lookup_order_readonly(request.order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrderDatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    methods = _validate_methods(request.methods) # type: ignore
    semantic = None
    keyword = None
    policy_hits = {}
    try:
        semantic = MilvusPolicyRetriever() if "semantic" in methods else None
        keyword = KeywordPolicyRetriever() if "keyword" in methods else None
        for method in methods:
            if method == "semantic":
                assert semantic is not None
                policy_hits[method] = semantic.search(request.query, top_k=request.top_k)
            else:
                assert keyword is not None
                policy_hits[method] = keyword.search(request.query, top_k=request.top_k)
    except Exception as exc:
        log_safe_error(
            logger,
            event="support_evidence_retrieval_failed",
            request_id=http_request.state.request_id,
            stage="policy_retrieval",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Policy retrieval dependency unavailable") from exc
    finally:
        if semantic is not None:
            semantic.close()

    marketplace = order_evidence["order"].get("marketplace", "unknown")
    return {
        "request_id": http_request.state.request_id,
        "execution_scope": "development-only; local fixture lookup; no identity authorization",
        "order_evidence": order_evidence,
        "milvus_collection": collection_name() if semantic is not None else None,
        "policy_evidence": policy_hits,
        "policy_scope_notice": (
            f"The order marketplace is {marketplace}. Retrieved passages are synthetic, draft, "
            "development-only documents in synthetic-fixture scope; they are not approved policy "
            "for this order marketplace and must not be used to decide customer eligibility."
        ),
    }
