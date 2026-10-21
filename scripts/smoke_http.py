"""Accept an already running server over real TCP HTTP (no paid providers)."""
import argparse
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--backend", choices=["lexical", "pgvector"], default="lexical")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=15, trust_env=False) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json()["model_backend"] == "mock", "Acceptance requires no paid model"
        assert health.json()["search_backend"] == "none", "Acceptance disables external search"
        assert health.json()["retrieval_backend"] == args.backend, health.text
        assert client.get("/docs").status_code == 200
        assert client.post("/api/tasks", json={"question": "hi"}).status_code == 422
        assert client.get("/api/tasks/unknown").status_code == 404
        doc = client.post("/api/documents/text", json={
            "title": "Container checkpoint evidence", "source_ref": "acceptance:docker",
            "content": "LangGraph checkpoints persist workflow state for recovery after interruption.",
        })
        assert doc.status_code == 201, doc.text
        created = client.post("/api/tasks", json={
            "question": "How do LangGraph checkpoints recover workflow state?"})
        assert created.status_code == 202, created.text
        task_id = created.json()["task_id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = client.get(f"/api/tasks/{task_id}")
            response.raise_for_status()
            task = response.json()
            if task["status"] in {"completed", "failed", "timed_out"}:
                break
            time.sleep(0.1)
        assert task["status"] == "completed", task
        report = client.get(f"/api/tasks/{task_id}/report")
        assert report.status_code == 200, report.text
        assert report.json()["markdown"] == task["report"]
        assert "[S1]" in task["report"] and "Mock" in task["report"]
        prefix = "pgvector:" if args.backend == "pgvector" else "local:"
        assert any(s["locator"].startswith(prefix + doc.json()["document_id"])
                   for s in task["sources"]), task
        trace = client.get(f"/api/tasks/{task_id}/trace").json()
        assert trace["events"] == task["trace"]
        assert task["trace"][0] == "plan" and task["trace"][-1] == "validate:OK"
        assert 1 <= sum(e.startswith("retrieve:") for e in task["trace"]) <= 2
        assert client.post(f"/api/tasks/{task_id}/resume").status_code == 409
        evidence = {"backend": args.backend, "health": health.json(),
                    "document": doc.json(), "task": task, "trace": trace}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"TCP HTTP acceptance PASS: backend={args.backend}, task={task_id}, "
              f"sources={len(task['sources'])}, trace={task['trace']}")


if __name__ == "__main__":
    main()
