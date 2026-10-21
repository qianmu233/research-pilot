"""Genuine LangGraph StateGraph; bounded loop and SQLite checkpointing.

Validated against real LangGraph 1.x; see TEST_REPORT.md for exact versions.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import Settings
from .evidence import merge_sources, validate_citations
from .model import ResearchModel
from .retrieval import SearchTools


class ResearchState(TypedDict, total=False):
    task_id: str
    question: str
    scope: str
    queries: list[str]
    iteration: int
    sources: list[dict]
    tool_errors: list[str]
    report: str
    report_status: str
    trace: list[str]
    evidence_status: str
    research: dict


def build_graph(model: ResearchModel, tools: SearchTools, settings: Settings, checkpointer,
                on_step: Callable[[str, ResearchState], None] | None = None,
                interrupt_before: list[str] | None = None, model_budget=None):
    """State flow: plan -> retrieve -> assess -> (retrieve | write) -> validate."""

    structured = getattr(model, "structured_research", False)

    def generate(stage: str, state: ResearchState, payload: dict) -> dict:
        if model_budget is None:
            raise RuntimeError("PERSISTENT_MODEL_BUDGET_REQUIRED")
        number, remaining = model_budget.reserve_model_call(
            state["task_id"], stage, settings.max_model_calls, settings.task_timeout_seconds)
        started = time.monotonic()
        usage, status = {}, "failed"
        try:
            value, usage = model.generate(stage, payload, min(remaining, settings.step_timeout_seconds))
            if time.monotonic() - started >= min(remaining, settings.step_timeout_seconds):
                raise TimeoutError("MODEL_DEADLINE_EXCEEDED")
            status = "completed"
            return value
        except Exception as exc:
            usage = getattr(exc, "usage", {})
            raise
        finally:
            model_budget.finish_model_call(state["task_id"], number, status,
                                           time.monotonic() - started, usage)

    def plan(state: ResearchState) -> dict:
        if structured:
            value = generate("plan", state, {"question": state["question"], "scope": state.get("scope", "")})
            return {"queries": value["queries"][:1], "iteration": 0, "sources": [],
                    "tool_errors": [], "trace": ["plan"], "evidence_status": "unassessed",
                    "research": {"plan": value, "assessments": [], "citation_valid": False,
                                 "facts_verified": False, "model": getattr(model, "identity", {}),
                                 "inference": {"temperature": 0, "reasoning_effort": "none",
                                     "context_tokens": settings.model_context_tokens,
                                     "output_tokens": settings.model_output_tokens}}}
        queries = model.plan(state["question"], state.get("scope", ""))[:2]
        if not queries:
            queries = [state["question"]]
        return {"queries": queries, "iteration": 0, "sources": [],
                "tool_errors": [], "trace": ["plan"], "evidence_status": "unassessed"}

    def retrieve(state: ResearchState) -> dict:
        iteration = state.get("iteration", 0) + 1
        incoming, errors = tools.search(state["queries"], settings.max_sources)
        sources = merge_sources(state.get("sources", []), incoming, settings.max_sources)
        extra = {}
        if structured:
            rounds = state["research"].get("retrieval_rounds", []) + [{
                "iteration": iteration, "queries": state["queries"],
                "incoming_count": len(incoming),
                "new_source_ids": [s["source_id"] for s in sources[len(state.get("sources", [])):]],
            }]
            extra["research"] = {**state["research"], "retrieval_rounds": rounds}
        return {**extra, "iteration": iteration, "sources": sources,
                "tool_errors": state.get("tool_errors", []) + errors,
                "trace": state.get("trace", []) + [f"retrieve:{iteration}:{len(sources)}"]}

    def assess(state: ResearchState) -> dict:
        if structured:
            from .local_llm import ModelContractError, evidence_payload
            value = generate("assess", state, {"question": state["question"],
                             "plan": state["research"]["plan"], "sources": evidence_payload(state["sources"])})
            allowed = {s["source_id"] for s in state["sources"]}
            if (set(value["source_ids"]) - allowed or
                    (value["sufficient"] and (not value["source_ids"] or value["missing_information"]))):
                raise ModelContractError("INVALID_EVIDENCE_ASSESSMENT")
            return {"research": {**state["research"], "assessments": state["research"]["assessments"] + [value]},
                    "queries": [q[:300] for q in value["next_queries"] if q.strip()][:2],
                    "trace": state["trace"] + [f"assess:model_{'sufficient' if value['sufficient'] else 'insufficient'}"],
                    "evidence_status": "unverified" if state["sources"] else "no_evidence"}
        # Quantity stops candidate collection; it cannot verify semantic answerability.
        return {"trace": state["trace"] + [
            f"assess:{'candidates_collected' if len(state['sources']) >= settings.min_evidence else 'insufficient'}"
        ], "evidence_status": "unverified" if state["sources"] else "no_evidence"}

    def route(state: ResearchState) -> str:
        if structured:
            value = state["research"]["assessments"][-1]
            return "write" if (value["sufficient"] or not state["queries"] or
                               state["iteration"] >= settings.max_rounds) else "retrieve"
        if len(state["sources"]) >= settings.min_evidence:
            return "write"
        if state["iteration"] >= settings.max_rounds:
            return "write"
        return "retrieve"

    def write(state: ResearchState) -> dict:
        if structured:
            from .local_llm import evidence_payload, render_report
            value = generate("write", state, {"question": state["question"], "scope": state.get("scope", ""),
                             "assessment": state["research"]["assessments"][-1],
                             "sources": evidence_payload(state["sources"])})
            return {"report": render_report(value), "research": {**state["research"], "report": value},
                    "trace": state["trace"] + ["write"]}
        report = model.draft(state["question"], state.get("scope", ""), state["sources"])
        return {"report": report, "trace": state["trace"] + ["write"]}

    def validate(state: ResearchState) -> dict:
        ok, reason = validate_citations(state["report"], state["sources"])
        if structured:
            from .local_llm import validate_structured_report
            report = state["research"]["report"]
            if reason == "MISSING_CITATIONS" and not report["claims"] and report["answer_status"] == "insufficient_evidence":
                ok, reason = True, "OK"
            structured_reason = validate_structured_report(
                report, state["sources"], state["research"]["assessments"][-1])
            if structured_reason != "OK":
                ok, reason = False, structured_reason
            return {"report_status": "completed" if ok else "failed",
                    "research": {**state["research"], "citation_valid": ok,
                                 "validation_reason": reason, "facts_verified": False},
                    "trace": state["trace"] + [f"validate:{reason}"]}
        return {"report_status": "completed" if ok else "failed",
                "trace": state["trace"] + [f"validate:{reason}"]}

    def observed(name: str, fn):
        def wrapped(state: ResearchState):
            started = time.monotonic()
            if structured:
                model_budget.check_task_deadline(state["task_id"], settings.task_timeout_seconds)
            result = fn(state)
            if structured:
                model_budget.check_task_deadline(state["task_id"], settings.task_timeout_seconds)
            # A synchronous provider cannot be forcibly killed by a thread timeout.
            # Reject its late result before LangGraph can record successful pending writes.
            if time.monotonic() - started >= settings.step_timeout_seconds:
                raise TimeoutError("NODE_DEADLINE_EXCEEDED")
            if on_step is not None:
                on_step(name, {**state, **result})
            return result
        return wrapped

    builder = StateGraph(ResearchState)
    for name, fn in (("plan", plan), ("retrieve", retrieve), ("assess", assess),
                     ("write", write), ("validate", validate)):
        builder.add_node(name, observed(name, fn))
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "retrieve")
    builder.add_edge("retrieve", "assess")
    builder.add_conditional_edges("assess", route, {"retrieve": "retrieve", "write": "write"})
    builder.add_edge("write", "validate")
    builder.add_edge("validate", END)
    graph = builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)
    graph.step_timeout = settings.step_timeout_seconds
    return graph
