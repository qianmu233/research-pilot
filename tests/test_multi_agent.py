"""Offline orchestration coverage against real LangGraph and SQLite."""
import json
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_http_integration import running_server

from research_pilot.api import create_app
from research_pilot.config import Settings
from research_pilot.local_llm import LocalStructuredModel, ModelContractError, ProviderFailure
from research_pilot.model import MockResearchModel
from research_pilot.multi_schema import (
    EnterpriseReport,
    ReviewDecision,
    SupervisorPlan,
    WorkerAssessment,
)
from research_pilot.multi_workflow import comparison_targets, plan_specs, requested_dimensions
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText
from research_pilot.store import LocalStore, ModelCallBudgetExceeded

QUESTION = "Compare enterprise data storage options and their cost."
DIMENSION = "cost"


class ScenarioModel(MockResearchModel):
    def __init__(self, *subjects):
        self.subjects = subjects or ("alpha", "beta")
        self.worker_payloads = []
        self.fail = set()
        self.invalid_worker = False
        self.report_error = None
        self.local_followup = False
        self.review_conflict = False
        self.truncate_stage = None
        self.unknown_followup = False

    def generate_multi(self, schema, instruction, payload, timeout):
        if schema is self.truncate_stage:
            raise ProviderFailure("MODEL_OUTPUT_TRUNCATED", {"total_tokens": 50})
        if schema is SupervisorPlan:
            return {"subtasks": [
                {"objective": subject, "scope": "architecture", "dimensions": [DIMENSION],
                 "constraints": ["on-prem"], "queries": [subject]} for subject in self.subjects
            ]}, {}
        if schema is WorkerAssessment:
            self.worker_payloads.append(payload)
            subject, sources = payload["objective"], payload["sources"]
            if subject in self.fail:
                raise ProviderFailure("MODEL_SERVER_ERROR")
            if self.invalid_worker:
                return {"covered_dimensions": 42}, {}
            matching = [s["source_id"] for s in sources if f"{subject} {DIMENSION}" in s["excerpt"]]
            return {"conclusion": "fixture", "source_ids": matching,
                    "covered_dimensions": [DIMENSION] if matching else [],
                    "open_questions": [] if matching else ["Missing fixture"],
                    "next_queries": [f"{subject} cost"] if self.local_followup and not matching else []}, {}
        if schema is ReviewDecision and self.review_conflict:
            return {"sufficient": False, "gaps": [], "conflicts": ["资料口径不同"], "followups": []}, {}
        if schema is ReviewDecision and self.unknown_followup:
            return {"sufficient": False, "gaps": [], "conflicts": [],
                    "followups": [{"subtask_id": "unknown", "reason": "fixture", "queries": ["bad"]}]}, {}
        result, usage = super().generate_multi(schema, instruction, payload, timeout)
        if schema is EnterpriseReport and self.report_error == "unknown":
            result["claims"][0]["source_id"] = "S999"
        if schema is EnterpriseReport and self.report_error == "quote":
            result["claims"][0]["quote"] = "fabricated"
        if schema is EnterpriseReport and self.report_error == "overclaim":
            result["answer_status"] = "answered"
        return result, usage


def evidence(name, text=None):
    return {"title": name, "locator": f"local:{name}", "excerpt": text or f"{name} cost is documented.",
            "source_type": "local", "retrieved_at": datetime.now(UTC).isoformat(), "query": name}


def make_runtime(tmp_path, model, **changes):
    return ResearchRuntime(Settings(data_dir=tmp_path, max_model_calls=changes.pop("max_model_calls", 8),
                                    **changes), model=model)


def run_multi(runtime):
    task_id = runtime.create_task(CreateTask(question=QUESTION, mode="multi"))
    runtime.run_task(task_id)
    return runtime.get_task(task_id)


def test_dynamic_plan_parallel_isolation_and_stable_dedup(tmp_path, monkeypatch):
    model = ScenarioModel("alpha", "beta", "gamma", "alpha")
    runtime = make_runtime(tmp_path, model, multi_max_concurrency=2, max_rounds=1)
    barrier = Barrier(2)
    active = set()
    lock = Lock()
    shared = evidence("shared", "Shared internal deployment constraints.")

    def search(query, limit):
        if query in {"alpha", "beta"}:
            with lock:
                active.add(query)
            barrier.wait(3)
        return [evidence(query), shared]

    monkeypatch.setattr(runtime.local, "search", search)
    try:
        first = run_multi(runtime)
        second = run_multi(runtime)
        assert active == {"alpha", "beta"}
        assert [t["objective"] for t in first["progress"]["subtasks"]] == ["alpha", "beta", "gamma"]
        assert all(p["seen_queries"] == [p["objective"]] for p in model.worker_payloads)
        assert all({s["title"] for s in p["sources"]} == {p["objective"], "shared"}
                   for p in model.worker_payloads)
        expected = [("S1", "alpha"), ("S2", "beta"), ("S3", "gamma"), ("S4", "shared")]
        for task in (first, second):
            assert task["status"] == "completed", task
            assert [(s["source_id"], s["title"]) for s in task["sources"]] == expected
            assert "review:sufficient" in task["trace"]
            assert task["progress"]["supplemented_subtask_count"] == 0
        model.subjects = ("gamma",)
        third = run_multi(runtime)
        assert third["progress"]["subtask_count"] == 1
    finally:
        runtime.close()


def test_supervisor_enforces_limit_and_validates_output(tmp_path):
    runtime = make_runtime(tmp_path, ScenarioModel("a", "b", "c"), multi_max_subtasks=2)
    try:
        task = run_multi(runtime)
        assert task["status"] == "failed"
        assert task["error_code"] == "WORKFLOW_FAILURE_ModelContractError"
        assert task["progress"]["subtask_count"] == 0
    finally:
        runtime.close()


@pytest.mark.parametrize("local", [False, True])
def test_targeted_and_autonomous_retrieval(tmp_path, monkeypatch, local):
    model = ScenarioModel()
    model.local_followup = local
    runtime = make_runtime(tmp_path, model, max_rounds=3 if local else 2)
    counts = Counter()
    lock = Lock()

    def search(query, limit):
        with lock:
            counts[query] += 1
        if query == "beta":
            return [evidence("beta-overview", "beta general architecture")]
        if query == "beta cost":
            return [evidence("beta-cost", "beta cost is documented.")]
        return [evidence(query)]

    monkeypatch.setattr(runtime.local, "search", search)
    try:
        task = run_multi(runtime)
        assert task["status"] == "completed", task
        assert task["research"]["quality"] == "full"
        assert counts == {"alpha": 1, "beta": 1, "beta cost": 1}
        assert task["progress"]["supplemented_subtask_count"] == (0 if local else 1)
        assert [t["retrieval_rounds"] for t in task["progress"]["subtasks"]] == [1, 2]
        assert task["trace"].count("review:insufficient") == (0 if local else 1)
        assert task["model_calls"] == (6 if local else 7)
    finally:
        runtime.close()


def test_sqlite_atomic_reservations_across_connections(tmp_path):
    stores = [LocalStore(tmp_path / "budget.sqlite3") for _ in range(3)]
    task = stores[0].create_task(CreateTask(question=QUESTION))
    barrier = Barrier(12)

    def attempt(index):
        store = stores[index % len(stores)]
        barrier.wait(5)
        try:
            number, _ = store.reserve_model_call(task, "worker_assess", 7, 30,
                                                 subtask_id=str(index), keep_calls=2)
        except ModelCallBudgetExceeded:
            return None
        store.finish_model_call(task, number, "completed", 0, {"total_tokens": number})
        return number

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(attempt, range(12)))
        assert sorted(value for value in results if value) == list(range(1, 6))
        stores[1].reserve_model_call(task, "review", 7, 30, keep_calls=1)
        stores[2].reserve_model_call(task, "multi_write", 7, 30)
        with pytest.raises(ModelCallBudgetExceeded):
            stores[0].reserve_model_call(task, "multi_write", 7, 30)
        events = stores[0].task(task)["model_events"]
        assert [e["total_tokens"] for e in events[:5]] == list(range(1, 6))
        assert len({e["subtask_id"] for e in events[:5]}) == 5
    finally:
        for store in stores:
            store.close()


def test_shared_budget_keeps_review_and_report(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path, ScenarioModel(), max_model_calls=3, max_rounds=1)
    monkeypatch.setattr(runtime.local, "search", lambda q, limit: [evidence(q)])
    try:
        task = run_multi(runtime)
        assert task["status"] == "completed", task
        assert task["research"]["quality"] == "partial"
        assert [e["stage"] for e in task["model_events"]] == ["supervisor", "review", "multi_write"]
        assert all(t["error_code"] == "WORKER_BUDGET_RESERVED" for t in task["progress"]["subtasks"])
    finally:
        runtime.close()


@pytest.mark.parametrize("stage", [ReviewDecision, EnterpriseReport])
def test_truncated_global_generation_publishes_only_limited_report(tmp_path, monkeypatch, stage):
    model = ScenarioModel("alpha")
    model.truncate_stage = stage
    runtime = make_runtime(tmp_path, model, max_rounds=1)
    monkeypatch.setattr(runtime.local, "search", lambda q, limit: [evidence(q)])
    try:
        task = run_multi(runtime)
        assert task["status"] == "completed", task
        assert task["research"]["quality"] == "partial"
        assert task["research"]["citation_valid"] is True
        assert "长度上限" in task["report"]
        failed, = [event for event in task["model_events"] if event["status"] == "failed"]
        assert failed["total_tokens"] == 50
    finally:
        runtime.close()


def test_retry_only_failed_child_after_reopen_and_reuses_search(tmp_path, monkeypatch):
    model = ScenarioModel()
    model.fail.add("beta")
    counts = Counter()
    lock = Lock()

    def search(query, limit):
        with lock:
            counts[query] += 1
        return [evidence(query)]

    runtime = make_runtime(tmp_path, model)
    monkeypatch.setattr(runtime.local, "search", search)
    try:
        task = run_multi(runtime)
        assert task["phase"] == "waiting_for_retry", task
        children = task["progress"]["subtasks"]
        assert [child["status"] for child in children] == ["completed", "failed"]
        assert [child["retrieval_rounds"] for child in children] == [1, 1]
    finally:
        runtime.close()
    model.fail.clear()
    reopened = make_runtime(tmp_path, model)
    monkeypatch.setattr(reopened.local, "search", search)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(reopened.run_task, [task["id"]] * 4))
        restored = reopened.get_task(task["id"])
        assert restored["status"] == "completed", restored
        assert counts == {"alpha": 1, "beta": 1}
        assert [child["attempts"] for child in restored["progress"]["subtasks"]] == [1, 2]
        assert [child["id"] for child in restored["progress"]["subtasks"]] == [c["id"] for c in children]
        assert [child["model_calls"] for child in restored["progress"]["subtasks"]] == [1, 2]
        assert restored["model_calls"] == task["model_calls"] + 3
    finally:
        reopened.close()


def test_invalid_worker_exhausts_retry_then_reports_partial(tmp_path, monkeypatch):
    model = ScenarioModel("alpha")
    model.invalid_worker = True
    runtime = make_runtime(tmp_path, model)
    monkeypatch.setattr(runtime.local, "search", lambda q, limit: [evidence(q)])
    try:
        task = run_multi(runtime)
        assert task["phase"] == "waiting_for_retry", task
        runtime.run_task(task["id"])
        task = runtime.get_task(task["id"])
        assert task["status"] == "completed", task
        assert task["research"]["quality"] == "partial"
        assert "INVALID_WORKER_RESULT" in task["report"]
    finally:
        runtime.close()


def test_hard_worker_timeout_discards_late_retrieval(tmp_path, monkeypatch):
    executor_release = Event()
    entered = Event()
    runtime = make_runtime(tmp_path, ScenarioModel(), step_timeout_seconds=0.5)

    def search(query, limit):
        if query == "beta":
            entered.set()
            assert executor_release.wait(6)
        return [evidence(query)]

    monkeypatch.setattr(runtime.local, "search", search)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_multi, runtime)
            try:
                assert entered.wait(4)
                active_id, = runtime.active
                progress = runtime.get_task(active_id)["progress"]
                assert progress["phase"] == "research"
                assert progress["subtask_count"] == 2
                assert any(child["status"] == "running" for child in progress["subtasks"])
                task = future.result(timeout=4)
                assert task["phase"] == "waiting_for_retry", task
                assert [t["status"] for t in task["progress"]["subtasks"]] == ["completed", "timed_out"]
            finally:
                executor_release.set()
        assert runtime.get_task(task["id"])["progress"]["subtasks"][1]["sources"] == []
        runtime.run_task(task["id"])
        assert runtime.get_task(task["id"])["status"] == "completed"
    finally:
        runtime.close()


def test_worker_crash_recovery_uses_sqlite_cursor_across_processes(tmp_path, monkeypatch):
    helper = Path(__file__).parent / "helpers/multi_crash_worker.py"
    process = subprocess.run([sys.executable, str(helper), str(tmp_path)], timeout=20, check=False)
    assert process.returncode == 79
    task_id = (tmp_path / "task-id.txt").read_text()
    runtime = make_runtime(tmp_path, MockResearchModel(), multi_max_concurrency=2)
    original = runtime.local.search
    queries = []

    def observed(query, limit):
        queries.append(query)
        return original(query, limit)

    monkeypatch.setattr(runtime.local, "search", observed)
    try:
        interrupted = runtime.get_task(task_id)
        assert interrupted["status"] == "running"
        assert [c["status"] for c in interrupted["progress"]["subtasks"]] == ["completed", "running"]
        with TestClient(create_app(runtime)) as client:
            assert client.post(f"/api/tasks/{task_id}/resume").status_code == 202
            check = client.get(f"/api/tasks/{task_id}").json()
        assert check["status"] == "completed", check
        assert check["research"]["quality"] == "full"
        assert check["trace"].count("supervisor:2") == 1
        assert queries == ["beta"]
        assert [c["attempts"] for c in check["progress"]["subtasks"]] == [1, 2]
        assert check["model_calls"] == 5
    finally:
        runtime.close()


def test_resume_does_not_reset_total_deadline(tmp_path, monkeypatch):
    model = ScenarioModel()
    model.fail.add("beta")
    runtime = make_runtime(tmp_path, model, task_timeout_seconds=10)
    monkeypatch.setattr(runtime.local, "search", lambda q, limit: [evidence(q)])
    try:
        task = run_multi(runtime)
        assert task["phase"] == "waiting_for_retry", task
        with runtime.store.lock, runtime.store.conn:
            runtime.store.conn.execute("UPDATE model_budgets SET started=? WHERE task_id=?",
                                       (time.time() - 11, task["id"]))
        runtime.run_task(task["id"])
        resumed = runtime.get_task(task["id"])
        assert resumed["status"] == "completed"
        assert resumed["research"]["quality"] == "partial"
        assert resumed["model_calls"] == task["model_calls"]
        assert [c["attempts"] for c in resumed["progress"]["subtasks"]] == [1, 1]
        assert "时间上限" in resumed["report"]
    finally:
        runtime.close()


@pytest.mark.parametrize("error,reason", [("unknown", "UNKNOWN_CITATION_ID"), ("quote", "QUOTE_NOT_IN_SOURCE"),
                                         ("overclaim", "UNSUPPORTED_ANSWER_STATUS")])
def test_validation_rejects_incorrect_report(tmp_path, monkeypatch, error, reason):
    model = ScenarioModel("alpha")
    model.report_error = error
    model.review_conflict = error == "overclaim"
    runtime = make_runtime(tmp_path, model)
    monkeypatch.setattr(runtime.local, "search", lambda q, limit: [evidence(q)])
    try:
        with TestClient(create_app(runtime)) as client:
            task_id = client.post("/api/tasks", json={"question": QUESTION, "mode": "multi"}).json()["task_id"]
            task = client.get(f"/api/tasks/{task_id}").json()
            assert task["status"] == "failed"
            assert task["research"]["validation_reason"] == reason
            assert client.get(f"/api/tasks/{task_id}/report").status_code == 409
    finally:
        runtime.close()


def test_empty_library_is_not_successful_research_and_single_mode_still_works(tmp_path):
    runtime = make_runtime(tmp_path, ScenarioModel())
    try:
        with TestClient(create_app(runtime)) as client:
            multi = client.post("/api/tasks", json={"question": QUESTION, "mode": "multi"}).json()["task_id"]
            task = client.get(f"/api/tasks/{multi}").json()
            assert task["status"] == "completed"
            assert task["evidence_status"] == "no_evidence"
            assert task["progress"]["quality"] == "insufficient"
            report = client.get(f"/api/tasks/{multi}/report").json()
            assert report["research"]["report"]["claims"] == []
            runtime.ingest_text(IngestText(title="alpha", content="enterprise data storage and cost"))
            for options in ({}, {"mode": "single"}):
                response = client.post("/api/tasks", json={"question": QUESTION, **options})
                task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
                assert task["status"] == "completed" and task["mode"] == "single"
                assert task["trace"][0] == "plan"
                assert task["progress"] is None
    finally:
        runtime.close()


def test_review_cannot_dispatch_an_unknown_subtask(tmp_path, monkeypatch):
    model = ScenarioModel("alpha")
    model.unknown_followup = True
    runtime = make_runtime(tmp_path, model)
    monkeypatch.setattr(runtime.local, "search", lambda q, limit: [evidence(q)])
    try:
        task = run_multi(runtime)
        assert task["status"] == "completed", task
        assert task["research"]["quality"] == "partial"
        assert task["research"]["review"]["rejected_followup_count"] == 1
        assert task["progress"]["supplemented_subtask_count"] == 0
    finally:
        runtime.close()


def test_enterprise_rag_demo_over_real_tcp(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RETRIEVAL_BACKEND", "lexical")
    monkeypatch.setenv("RESEARCH_MAX_MODEL_CALLS", "8")
    monkeypatch.setenv("RESEARCH_RETRIEVAL_TOP_K", "1")
    data = Path(__file__).resolve().parents[1] / "benchmarks/multi_agent_v1/dataset.json"
    case = json.loads(data.read_text("utf-8"))["cases"][0]
    with running_server(tmp_path) as client:
        for item in case["documents"]:
            response = client.post("/api/documents/text", json={
                "title": item["title"], "content": item["content"], "source_ref": item["id"],
            })
            assert response.status_code == 201
        submitted = client.post("/api/tasks", json={
            "question": case["question"], "scope": case["scope"], "mode": "multi",
        })
        assert submitted.status_code == 202
        task_path = f"/api/tasks/{submitted.json()['task_id']}"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = client.get(task_path).raise_for_status().json()
            if task["status"] not in {"pending", "running"}:
                break
            time.sleep(.05)
        assert task["status"] == "completed", task
        assert task["progress"]["quality"] == "full"
        children = task["progress"]["subtasks"]
        assert [child["objective"] for child in children if child["generation"] == 1] == ["PgVector"]
        assert task["model_calls"] == 8
        report = client.get(task_path + "/report").raise_for_status().json()
        assert len(report["research"]["report"]["claims"]) == 4
        assert report["research"]["citation_valid"]


def test_explicit_comparison_anchors_omitted_candidates_and_dimensions():
    question = "比较 AlphaDB、BetaDB 和 GammaDB 在企业内网中的方案。"
    scope = "维度：运维、部署；优先复用现有平台。"
    plan = SupervisorPlan.model_validate({"subtasks": [
        {"objective": "评估AlphaDB", "scope": "运维", "dimensions": ["运维"],
         "constraints": [], "queries": ["AlphaDB 性能明细"]},
        {"objective": "综合比较 AlphaDB 和 BetaDB", "scope": "集成", "dimensions": ["集成"],
         "constraints": [], "queries": ["技术方案综合比较"]},
    ]})
    specs = plan_specs("task", plan, 4, targets=comparison_targets(question),
                       dimensions=requested_dimensions(scope), scope=scope)
    assert [spec["objective"] for spec in specs] == ["AlphaDB", "BetaDB", "GammaDB"]
    assert [spec["queries"] for spec in specs] == [["AlphaDB"], ["BetaDB"], ["GammaDB"]]
    assert all(spec["dimensions"] == ["运维", "部署"] for spec in specs)
    assert all(spec["scope"] == scope for spec in specs)


def test_term_mismatch_can_focus_review_search_without_marking_a_fact(tmp_path, monkeypatch):
    class OverconfidentLocalAssessment(ScenarioModel):
        def generate_multi(self, schema, instruction, payload, timeout):
            result, usage = super().generate_multi(schema, instruction, payload, timeout)
            if schema is WorkerAssessment and payload["objective"] == "alpha" and not result["source_ids"]:
                result["source_ids"] = [payload["sources"][0]["source_id"]]
                result["covered_dimensions"] = ["cost"]
            return result, usage

    runtime = make_runtime(tmp_path, OverconfidentLocalAssessment(), max_rounds=2)
    queries = []

    def search(query, limit):
        queries.append(query)
        target = query.split()[0]
        if "cost" in query:
            return [evidence(target, f"{target} cost is documented in the review material.")]
        return [evidence(target, f"{target} initial design has no financial detail.")]

    monkeypatch.setattr(runtime.local, "search", search)
    try:
        task_id = runtime.create_task(CreateTask(question="比较 alpha 和 beta 在企业内网中的选型。",
                                                scope="维度：cost", mode="multi"))
        runtime.run_task(task_id)
        task = runtime.get_task(task_id)
        assert task["status"] == "completed", task
        assert sorted(queries) == ["alpha", "alpha cost", "beta", "beta cost"]
        assert all(len(child["sources"]) == 2 for child in task["progress"]["subtasks"])
    finally:
        runtime.close()


@pytest.mark.parametrize("reference", ["S2.2", "S9.1"])
def test_ollama_passage_selection_resolves_only_model_chosen_exact_quote(monkeypatch, reference):
    model = LocalStructuredModel(Settings(
        model_backend="ollama", model_base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3:4b-instruct-2507-q4_K_M",
    ))
    monkeypatch.setattr(model, "input_size", lambda *_: 1)

    def request(schema, wire, messages, timeout):
        assert wire["properties"]["answer_status"]["enum"] == ["insufficient_evidence"]
        assert "S2.2" in wire["$defs"]["PassageClaim"]["properties"]["quote_ref"]["enum"]
        human = json.loads(messages[1][1])
        assert human["sources"][1]["passages"]["S2.2"] == "由运维组负责。"
        result = {"title": "范围内证据", "answer_status": "insufficient_evidence", "limitations": ["未实测"],
                  "claims": [{"quote_ref": reference, "section": "fit", "text": "运维组负责。"}]}
        return SimpleNamespace(response_metadata={}, usage_metadata={}), result

    monkeypatch.setattr(model, "request", request)
    payload = {"sufficient": False, "sources": [
        {"source_id": "S1", "title": "A", "excerpt": "由应用组负责。"},
        {"source_id": "S2", "title": "B", "excerpt": "完成交接。由运维组负责。"},
    ]}
    if reference == "S9.1":
        with pytest.raises(ModelContractError, match="UNKNOWN_QUOTE_REFERENCE"):
            model.generate_multi(EnterpriseReport, "", payload, 1)
    else:
        report, _ = model.generate_multi(EnterpriseReport, "", payload, 1)
        assert report["claims"] == [{"text": "运维组负责。", "source_id": "S2",
                                     "quote": "由运维组负责。", "section": "fit"}]


def test_ollama_review_requires_a_distinct_source_pair_for_a_conflict(monkeypatch):
    model = LocalStructuredModel(Settings(
        model_backend="ollama", model_base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3:4b-instruct-2507-q4_K_M",
    ))
    monkeypatch.setattr(model, "input_size", lambda *_: 1)

    def request(schema, wire, messages, timeout):
        bound = wire["$defs"]["PassageConflict"]["properties"]["first_quote_ref"]["enum"]
        assert bound == ["S1.1", "S1.2", "S2.1"]
        return SimpleNamespace(response_metadata={}, usage_metadata={}), {
            "sufficient": True, "gaps": [], "followups": [],
            "conflicts": [
                {"first_quote_ref": "S1.1", "second_quote_ref": "S1.2", "description": "同来源"},
                {"first_quote_ref": "S1.1", "second_quote_ref": "S2.1", "description": "两个来源"},
            ],
        }

    monkeypatch.setattr(model, "request", request)
    result, _ = model.generate_multi(ReviewDecision, "", {
        "subtasks": [{"id": "R-1"}], "sources": [
            {"source_id": "S1", "title": "A", "excerpt": "步骤甲。步骤乙。"},
            {"source_id": "S2", "title": "B", "excerpt": "步骤丙。"},
        ],
    }, 1)
    assert result["sufficient"] is False
    assert result["conflicts"] == ["两个来源（原文段落 S1.1 / S2.1）"]
    assert len(result["gaps"]) == 1
