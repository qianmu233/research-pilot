"""Run real LangGraph through an in-process ASGI client (not a TCP HTTP test)."""
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from research_pilot.api import create_app
from research_pilot.config import Settings
from research_pilot.runtime import ResearchRuntime


def main() -> None:
    with TemporaryDirectory(prefix="researchpilot-smoke-") as temp:
        runtime = ResearchRuntime(Settings(data_dir=Path(temp), max_rounds=2, min_evidence=1))
        try:
            with TestClient(create_app(runtime)) as client:
                doc = client.post("/api/documents/text", json={
                    "title": "ResearchPilot offline fixture",
                    "content": "LangGraph supports stateful research graphs and resumable checkpoint records."
                })
                assert doc.status_code == 201, doc.text
                created = client.post("/api/tasks", json={
                    "question": "How does LangGraph checkpoint state support research?"
                })
                assert created.status_code == 202, created.text
                tid = created.json()["task_id"]
                task = client.get(f"/api/tasks/{tid}").json()
                assert task["status"] == "completed", task
                report = client.get(f"/api/tasks/{tid}/report").json()
                assert "[S1]" in report["markdown"] and report["sources"], report
                print("Real LangGraph HTTP smoke: PASS", tid)
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
