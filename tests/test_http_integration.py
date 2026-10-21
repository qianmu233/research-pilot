"""Real TCP HTTP acceptance against a separate Uvicorn process, without paid APIs."""
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx


@contextmanager
def running_server(data_dir: Path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = os.environ.copy()
    env.update(RESEARCH_DATA_DIR=str(data_dir), RESEARCH_MODEL_BACKEND="mock",
               RESEARCH_SEARCH_BACKEND="none", RESEARCH_MAX_ROUNDS="2",
               RESEARCH_MIN_EVIDENCE="2", LANGSMITH_TRACING="false",
               LANGCHAIN_TRACING_V2="false", PYTHONUTF8="1")
    with (data_dir / "uvicorn.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "research_pilot.api:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1], env=env, stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                              timeout=5) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    assert process.poll() is None, (data_dir / "uvicorn.log").read_text()
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError("Uvicorn did not become ready within 30 seconds")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def submit_and_wait(client, question):
    created = client.post("/api/tasks", json={"question": question})
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"completed", "failed"}:
            return task
        time.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not terminate")


def test_real_http_workflow_and_restart(tmp_path):
    with running_server(tmp_path) as client:
        assert client.get("/docs").status_code == 200
        assert client.post("/api/tasks", json={"question": "hi"}).status_code == 422
        assert client.get("/api/tasks/missing").status_code == 404
        assert client.post("/api/tasks/missing/resume").status_code == 404
        empty = submit_and_wait(client, "Explain LangGraph checkpoint persistence")
        assert empty["status"] == "completed", empty
        assert empty["sources"] == [] and "无证据" in empty["report"]
        assert sum(e.startswith("retrieve:") for e in empty["trace"]) == 2
        document = client.post("/api/documents/text", json={
            "title": "Checkpoint acceptance document", "source_ref": "acceptance:checkpoint",
            "content": "LangGraph checkpoint persistence saves graph state for resumable workflows.",
        })
        assert document.status_code == 201, document.text
        doc_id = document.json()["document_id"]
        task = submit_and_wait(client, "Explain LangGraph checkpoint persistence")
        assert task["status"] == "completed", task
        assert task["error_code"] is None
        assert len(task["sources"]) == 1
        assert task["sources"][0]["locator"].startswith(f"local:{doc_id}-")
        assert task["sources"][0]["source_id"] == "S1"
        assert "[S1]" in task["report"] and "Mock" in task["report"]
        assert task["trace"] == ["plan", "retrieve:1:1", "assess:insufficient",
                                  "retrieve:2:1", "assess:insufficient", "write", "validate:OK"]
        task_id = task["id"]
        report = client.get(f"/api/tasks/{task_id}/report")
        assert report.status_code == 200
        assert report.json()["markdown"] == task["report"]
        assert client.get(f"/api/tasks/{task_id}/trace").json()["events"] == task["trace"]
        assert client.post(f"/api/tasks/{task_id}/resume").status_code == 409
    with running_server(tmp_path) as restarted:
        assert restarted.get(f"/api/tasks/{task_id}").json() == task
        assert restarted.get(f"/api/tasks/{task_id}/report").json() == report.json()
