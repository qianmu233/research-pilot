"""Exercise retrieval failures inside the real graph, including real DB disconnects."""
import httpx
from fastapi.testclient import TestClient

from research_pilot.api import create_app
from research_pilot.config import Settings
from research_pilot.retrieval import NoExternalSearch
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText


def test_local_storage_error_cannot_be_reported_as_successful_no_evidence(tmp_path):
    runtime = ResearchRuntime(Settings(data_dir=tmp_path))
    task_id = runtime.create_task(CreateTask(question="Explain LangGraph checkpoint persistence"))
    # Read-only retrieval really fails against a closed SQLite connection.
    separate = runtime.local.store.__class__(tmp_path / "broken.sqlite3")
    runtime.local.store = separate
    separate.close()
    try:
        runtime.run_task(task_id)
        task = runtime.get_task(task_id)
        assert task["status"] == "failed" and task["report"] is None
        assert "ProgrammingError" in task["error_code"]
        with TestClient(create_app(runtime)) as client:
            assert client.get(f"/api/tasks/{task_id}/report").status_code == 409
    finally:
        runtime.close()


def test_optional_external_timeout_is_visible_with_local_evidence(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectTimeout("SYNTHETIC_SECRET_MUST_NOT_LEAK")
    monkeypatch.setattr(NoExternalSearch, "search", fail)
    runtime = ResearchRuntime(Settings(data_dir=tmp_path, min_evidence=1))
    try:
        runtime.ingest_text(IngestText(title="Local evidence", content=
                                      "LangGraph checkpoint persistence supports durable state."))
        task_id = runtime.create_task(CreateTask(question="Explain LangGraph checkpoint persistence"))
        runtime.run_task(task_id)
        task = runtime.get_task(task_id)
        assert task["status"] == "completed"
        assert task["tool_errors"] == ["external:SEARCH_FAILED:ConnectTimeout"]
        assert "SYNTHETIC_SECRET" not in str(task)
        with TestClient(create_app(runtime)) as client:
            report = client.get(f"/api/tasks/{task_id}/report").json()
            assert report["tool_errors"] == task["tool_errors"]
            assert client.get(f"/api/tasks/{task_id}/trace").json()["tool_errors"]
    finally:
        runtime.close()
