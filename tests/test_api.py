"""API behavior tests use fake runtime. They DO NOT validate LangGraph execution."""
from pathlib import Path

from fastapi.testclient import TestClient

from research_pilot.api import create_app
from research_pilot.config import Settings
from research_pilot.store import LocalStore


class FakeRuntime:
    def __init__(self, tmp_path: Path):
        self.settings = Settings(data_dir=tmp_path)
        self.store = LocalStore(tmp_path / "api.sqlite3")

    def create_task(self, body):
        return self.store.create_task(body)

    def get_task(self, task_id):
        return self.store.task(task_id)

    def ingest_text(self, body):
        return self.store.ingest_text(body)

    def run_task(self, task_id):
        self.store.patch_task(task_id, status="completed", phase="fake",
                              report="# FAKE API TEST", trace=["fake"])


def test_create_and_query_task(tmp_path: Path):
    runtime = FakeRuntime(tmp_path)
    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/tasks", json={"question": "What is a checkpoint in LangGraph?"})
        assert response.status_code == 202
        tid = response.json()["task_id"]
        result = client.get(f"/api/tasks/{tid}")
        assert result.status_code == 200 and result.json()["status"] == "completed"
        assert client.get(f"/api/tasks/{tid}/report").json()["markdown"] == "# FAKE API TEST"
        assert client.get(f"/api/tasks/{tid}/trace").json()["events"] == ["fake"]
        assert client.get("/api/tasks/unknown").status_code == 404
    runtime.store.close()


def test_input_validation_and_local_ingestion(tmp_path: Path):
    runtime = FakeRuntime(tmp_path)
    with TestClient(create_app(runtime)) as client:
        assert client.post("/api/tasks", json={"question": "hi"}).status_code == 422
        assert client.post("/api/documents/text", json={
            "title": "demo", "content": "A local document about LangGraph and research planning."
        }).status_code == 201
    runtime.store.close()
