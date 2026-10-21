"""Real StateGraph/SQLiteSaver fault injection; models below only inject failures."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from test_http_integration import running_server

from research_pilot.api import create_app
from research_pilot.config import Settings
from research_pilot.model import MockResearchModel
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText
from research_pilot.store import LocalStore


def seed(runtime):
    runtime.ingest_text(IngestText(title="Durable graph", content=
                                  "LangGraph checkpoints persist state for reliable recovery."))
    return runtime.create_task(CreateTask(question="Explain LangGraph durable checkpoint recovery"))


def config(task_id):
    return {"configurable": {"thread_id": task_id}}


def test_interrupt_reopen_resume_and_idempotent_completion(tmp_path):
    settings = Settings(data_dir=tmp_path, min_evidence=1)
    first = ResearchRuntime(settings, interrupt_before=["write"])
    task_id = seed(first)
    first.run_task(task_id)
    task = first.get_task(task_id)
    assert task["status"] == "interrupted" and task["report"] is None
    assert first.graph.get_state(config(task_id)).next == ("write",)
    original_sources = task["sources"]
    first.close()
    recovered = ResearchRuntime(settings)
    try:
        with TestClient(create_app(recovered)) as client:
            assert client.get(f"/api/tasks/{task_id}/report").status_code == 409
            assert client.post(f"/api/tasks/{task_id}/resume").status_code == 202
            result = client.get(f"/api/tasks/{task_id}").json()
            assert result["status"] == "completed", result
            assert result["error_code"] is None and result["sources"] == original_sources
            assert result["trace"].count("plan") == 1 and result["trace"].count("write") == 1
            assert recovered.graph.get_state(config(task_id)).next == ()
            recovered.run_task(task_id)
            assert recovered.get_task(task_id)["updated_at"] == result["updated_at"]
    finally:
        recovered.close()


class FailDraft(MockResearchModel):
    def draft(self, *args):
        raise RuntimeError("SYNTHETIC_SECRET_MUST_NOT_LEAK")


def test_failed_node_resume_clears_old_error_and_preserves_evidence(tmp_path):
    settings = Settings(data_dir=tmp_path, min_evidence=1)
    first = ResearchRuntime(settings, model=FailDraft())
    task_id = seed(first)
    first.run_task(task_id)
    task = first.get_task(task_id)
    assert task["status"] == "failed" and task["report"] is None
    assert task["error_code"] == "WORKFLOW_FAILURE_RuntimeError"
    assert "SYNTHETIC_SECRET" not in str(task)
    assert first.graph.get_state(config(task_id)).next == ("write",)
    first.close()
    second = ResearchRuntime(settings)
    try:
        second.run_task(task_id)
        completed = second.get_task(task_id)
        assert completed["status"] == "completed" and completed["error_code"] is None
        assert completed["sources"] == task["sources"]
        assert completed["trace"].count("plan") == 1
    finally:
        second.close()


class SlowDraft(MockResearchModel):
    def draft(self, *args):
        time.sleep(0.2)
        return super().draft(*args)


def test_real_step_timeout_never_publishes_late_report_and_can_resume(tmp_path):
    first = ResearchRuntime(Settings(data_dir=tmp_path, min_evidence=1,
                                     step_timeout_seconds=0.08), model=SlowDraft())
    task_id = seed(first)
    first.run_task(task_id)
    task = first.get_task(task_id)
    assert task["status"] == "timed_out", task
    assert task["error_code"] == "WORKFLOW_STEP_TIMEOUT" and task["report"] is None
    assert "write" not in task["trace"]
    time.sleep(0.25)
    assert first.get_task(task_id) == task  # Late node completion cannot change task truth.
    assert first.graph.get_state(config(task_id)).next == ("write",)
    first.close()
    second = ResearchRuntime(Settings(data_dir=tmp_path, min_evidence=1))
    try:
        second.run_task(task_id)
        assert second.get_task(task_id)["status"] == "completed"
        assert second.get_task(task_id)["error_code"] is None
    finally:
        second.close()


class InvalidCitations(MockResearchModel):
    def draft(self, *args):
        return "Unsupported claim [S999]"


def test_invalid_citations_do_not_publish_report_or_resume_as_success(tmp_path):
    first = ResearchRuntime(Settings(data_dir=tmp_path), model=InvalidCitations())
    task_id = seed(first)
    try:
        first.run_task(task_id)
        task = first.get_task(task_id)
        assert task["status"] == "failed" and task["report"] is None
        assert task["error_code"] == "REPORT_CITATION_INVALID"
        assert task["trace"][-1] == "validate:UNKNOWN_CITATION_ID"
        with TestClient(create_app(first)) as client:
            assert client.get(f"/api/tasks/{task_id}/report").status_code == 409
        first.run_task(task_id)
        assert first.get_task(task_id)["status"] == "failed"
    finally:
        first.close()


def test_completed_checkpoint_reconciles_task_without_reexecuting_nodes(tmp_path):
    app = ResearchRuntime(Settings(data_dir=tmp_path, min_evidence=1))
    task_id = seed(app)
    task = app.get_task(task_id)
    try:
        result = app.graph.invoke({"task_id": task_id, "question": task["question"],
                                   "scope": task["scope"]}, config(task_id), durability="sync")
        assert app.get_task(task_id)["status"] == "pending"
        assert app.graph.get_state(config(task_id)).next == ()
    finally:
        app.close()
    # A second graph with a deliberately failing writer proves no nodes are replayed.
    recovered = ResearchRuntime(Settings(data_dir=tmp_path), model=FailDraft())
    try:
        recovered.run_task(task_id)
        assert recovered.get_task(task_id)["status"] == "completed"
        assert recovered.get_task(task_id)["report"] == result["report"]
        assert recovered.get_task(task_id)["trace"] == result["trace"]
    finally:
        recovered.close()


def test_real_process_crash_then_http_checkpoint_resume(tmp_path):
    worker = Path(__file__).parent / "helpers" / "crash_worker.py"
    process = subprocess.run([sys.executable, str(worker), str(tmp_path)],
                             cwd=Path(__file__).resolve().parents[1], timeout=20, check=False,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert process.returncode == 73
    task_id = (tmp_path / "task-id.txt").read_text()
    store = LocalStore(tmp_path / "tasks.sqlite3")
    try:
        before = store.task(task_id)
        assert before["status"] == "running" and before["report"] is None
        assert "write" not in before["trace"]
    finally:
        store.close()
    with running_server(tmp_path) as client:
        assert client.post(f"/api/tasks/{task_id}/resume").status_code == 202
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = client.get(f"/api/tasks/{task_id}").json()
            if result["status"] == "completed":
                break
            time.sleep(0.05)
        assert result["status"] == "completed", result
        assert result["sources"] == before["sources"]
        assert result["trace"].count("plan") == 1 and result["trace"].count("write") == 1
        assert client.get(f"/api/tasks/{task_id}/report").status_code == 200


class BlockingDraft(MockResearchModel):
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def draft(self, *args):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().draft(*args)


def test_same_task_concurrent_resume_executes_writer_once(tmp_path):
    model = BlockingDraft()
    runtime = ResearchRuntime(Settings(data_dir=tmp_path), model=model)
    task_id = seed(runtime)
    thread = threading.Thread(target=runtime.run_task, args=(task_id,))
    try:
        thread.start()
        assert model.entered.wait(timeout=5)
        runtime.run_task(task_id)
        model.release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert model.calls == 1 and runtime.get_task(task_id)["status"] == "completed"
    finally:
        model.release.set()
        thread.join(timeout=5)
        runtime.close()
