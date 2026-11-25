"""Isolated LangGraph worker with SQLite cursors at node boundaries."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context
from threading import BoundedSemaphore
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .evidence import merge_sources
from .local_llm import ContextBudgetExceeded, ModelContractError, ProviderFailure, evidence_payload
from .multi_schema import WorkerAssessment
from .store import ModelCallBudgetExceeded, now_iso

RETRYABLE = {"failed", "timed_out"}
MAX_ATTEMPTS = 2


class ResearchIO:
    """Bound waits and in-flight I/O even when a synchronous adapter returns late."""

    def __init__(self, concurrency: int):
        self.pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="research-io")
        self.slots = BoundedSemaphore(concurrency)

    def call(self, timeout: float, operation):
        deadline = time.monotonic() + timeout
        if not self.slots.acquire(timeout=timeout):
            raise TimeoutError("RESEARCH_IO_CAPACITY_TIMEOUT")
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("RESEARCH_IO_TIMEOUT")
            future = self.pool.submit(operation, remaining)
        except BaseException:
            self.slots.release()
            raise
        future.add_done_callback(lambda _: self.slots.release())
        try:
            return future.result(timeout=max(0, deadline - time.monotonic()))
        except TimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class WorkerState(TypedDict):
    task_id: str
    limits: dict
    spec: dict
    progress: dict


def new_queries(queries: list[str], rounds: list[dict]) -> list[str]:
    used = {q.casefold() for round_info in rounds for q in round_info["queries"]}
    fresh = []
    for query in queries:
        if query.casefold() not in used:
            fresh.append(query)
            used.add(query.casefold())
    return fresh


def missing_dimensions(spec: dict, progress: dict) -> list[str]:
    return [dimension for dimension in spec["dimensions"]
            if dimension not in progress.get("covered_dimensions", [])]


def worker_error(exc: Exception) -> tuple[str, str]:
    from httpx import TimeoutException
    from openai import APITimeoutError

    if isinstance(exc, ProviderFailure):
        return ("timed_out" if exc.code == "MODEL_TIMEOUT" else "failed"), exc.code
    if isinstance(exc, (TimeoutError, TimeoutException, APITimeoutError)):
        return "timed_out", "WORKER_TIMEOUT"
    if isinstance(exc, (ModelContractError, ValueError)):
        return "failed", "INVALID_WORKER_RESULT"
    return "failed", f"WORKER_FAILURE_{type(exc).__name__}"


def build_worker(tools, store, generate, io: ResearchIO):
    def save(state: WorkerState, **updates) -> dict:
        progress = {**state["progress"], **updates}
        store.save_subtask(state["task_id"], state["spec"]["id"], progress)
        return {"progress": progress}

    def retrieve(state: WorkerState) -> dict:
        progress = state["progress"]
        limits = state["limits"]
        deadline = time.monotonic() + limits["step_timeout_seconds"]
        incoming, errors = [], []
        for query in progress["queries"]:
            timeout = min(deadline - time.monotonic(),
                          store.remaining_seconds(state["task_id"], limits["task_timeout_seconds"]))
            if timeout <= 0:
                raise TimeoutError("WORKER_RETRIEVAL_TIMEOUT")
            found, failures = io.call(
                timeout, lambda _, query=query: tools.search([query], limits["max_sources"]),
            )
            store.check_task_deadline(state["task_id"], limits["task_timeout_seconds"])
            incoming.extend(found)
            errors.extend(failures)
        previous = progress["sources"]
        sources = merge_sources(previous, incoming, limits["max_sources"])
        rounds = [*progress["rounds"], {
            "generation": progress["generation"], "queries": progress["queries"],
            "new_source_ids": [source["source_id"] for source in sources[len(previous):]],
        }]
        return save(state, sources=sources, rounds=rounds, errors=progress.get("errors", []) + errors,
                    step="assess")

    def assess(state: WorkerState) -> dict:
        spec = state["spec"]
        progress = state["progress"]
        assessment = None
        error = None
        unchanged = progress["generation"] > 0 and not progress["rounds"][-1]["new_source_ids"]
        if progress["sources"] and not (unchanged and "source_ids" in progress):
            try:
                assessment = generate(
                    state, "worker_assess", WorkerAssessment,
                    "按研究维度评估局部证据。covered_dimensions须选用原维度名称，"
                    "source_ids只填支持该对象的资料ID。逐项找出对应证据才填写维度。"
                    "试点安排、职责分工或明确待测事项可覆盖相应维度，不需要额外的技术原理或量化指标。"
                    "缺口仅限用户要求。next_queries用候选名和缺失维度组成新词组。",
                    {"objective": spec["objective"], "scope": spec["scope"],
                     "dimensions": spec["dimensions"], "constraints": spec["constraints"],
                     "seen_queries": [q for item in progress["rounds"] for q in item["queries"]],
                     "sources": [{**source, "excerpt": source["excerpt"][:260]}
                                 for source in evidence_payload(progress["sources"])]},
                    subtask_id=spec["id"], keep_calls=2,
                )
            except ModelCallBudgetExceeded:
                error = "WORKER_BUDGET_RESERVED"
            except ContextBudgetExceeded:
                error = "WORKER_CONTEXT_LIMIT"
        updates = {}
        if assessment is not None:
            known = {source["source_id"] for source in progress["sources"]}
            if (set(assessment.source_ids) - known or
                    set(assessment.covered_dimensions) - set(spec["dimensions"]) or
                    (assessment.covered_dimensions and not assessment.source_ids)):
                raise ModelContractError("INVALID_WORKER_EVIDENCE_REFERENCE")
            updates = assessment.model_dump()
        elif not progress["sources"]:
            updates = {"conclusion": "资料库没有返回可用摘录。", "source_ids": [],
                       "covered_dimensions": [], "open_questions": spec["dimensions"],
                       "next_queries": []}
        combined = {**progress, **updates}
        missing = missing_dimensions(spec, combined)
        fresh = new_queries(updates.get("next_queries", []), progress["rounds"])
        # Keep one round available for a Supervisor-directed supplement.
        local_limit = max(1, state["limits"]["max_rounds"] - 1)
        if progress["generation"] == 0 and missing and fresh and len(progress["rounds"]) < local_limit:
            return save(state, **updates, queries=fresh, step="retrieve")
        status = "completed" if not missing and combined.get("source_ids") and not error else "insufficient"
        return save(state, **updates, status=status, step="done", completed_at=now_iso(), error_code=error)

    def route(state: WorkerState) -> str:
        return state["progress"]["step"]

    builder = StateGraph(WorkerState)
    builder.add_node("retrieve", retrieve)
    builder.add_node("assess", assess)
    destinations = {"retrieve": "retrieve", "assess": "assess", "done": END}
    builder.add_conditional_edges(START, route, destinations)
    builder.add_edge("retrieve", "assess")
    builder.add_conditional_edges("assess", route, destinations)
    graph = builder.compile(checkpointer=False)

    def run(state: WorkerState, assignment: dict) -> dict:
        task_id, subtask_id = state["task_id"], state["spec"]["id"]
        progress = store.subtask_state(task_id, subtask_id)
        generation = assignment["generation"]
        if progress["generation"] > generation:
            return progress
        if progress["generation"] == generation:
            if progress["step"] == "done" or (
                progress["status"] in RETRYABLE and progress["attempts"] >= MAX_ATTEMPTS
            ):
                return progress
        else:
            progress = {**progress, "generation": generation, "attempts": 0, "step": "retrieve",
                        "queries": assignment["queries"]}
            if generation:
                progress["supplement"] = {"reason": assignment["reason"], "queries": assignment["queries"]}
        progress = {**progress, "status": "running", "attempts": progress["attempts"] + 1,
                    "total_attempts": progress.get("total_attempts", 0) + 1,
                    "started_at": progress.get("started_at") or now_iso(),
                    "completed_at": None, "error_code": None}
        store.save_subtask(task_id, subtask_id, progress)
        try:
            store.check_task_deadline(task_id, state["limits"]["task_timeout_seconds"])
            # The worker owns its cursor and must not inherit the parent graph's checkpoint context.
            return Context().run(graph.invoke, {**state, "progress": progress})["progress"]
        except Exception as exc:  # noqa: BLE001 -- classify at the worker boundary
            # Persist the last completed step before exposing a retryable failure to the parent.
            status, error = worker_error(exc)
            progress = store.subtask_state(task_id, subtask_id)
            ended = now_iso()
            failure = {"generation": generation, "attempt": progress["attempts"],
                       "step": progress["step"], "error_code": error, "at": ended}
            progress = {**progress, "status": status, "error_code": error, "completed_at": ended,
                        "failures": [*progress.get("failures", []), failure]}
            store.save_subtask(task_id, subtask_id, progress)
            return progress

    return run
