"""REQUIRES real LangGraph dependency; run explicitly in Codex Windows venv.

Do not mark as passing solely because domain and API-unit tests pass.
"""
from pathlib import Path

from research_pilot.config import Settings


def test_real_graph_nodes_checkpoint_and_bounded_search(tmp_path: Path):
    from research_pilot.runtime import ResearchRuntime
    from research_pilot.schema import CreateTask, IngestText
    app = ResearchRuntime(Settings(data_dir=tmp_path, max_rounds=2, min_evidence=1))
    try:
        app.ingest_text(IngestText(title="LangGraph local document", content=
                                  "LangGraph provides state-based workflows and checkpoint persistence."))
        task_id = app.create_task(CreateTask(question="Explain LangGraph checkpoint persistence."))
        app.run_task(task_id)
        result = app.get_task(task_id)
        assert result["status"] == "completed", result
        assert "[S1]" in result["report"]
        assert result["trace"][0] == "plan"
        assert any(event.startswith("validate:") for event in result["trace"])
        assert sum(event.startswith("retrieve:") for event in result["trace"]) <= 2
    finally:
        app.close()


def test_empty_corpus_ends_after_bounded_retries(tmp_path: Path):
    from research_pilot.runtime import ResearchRuntime
    from research_pilot.schema import CreateTask
    app = ResearchRuntime(Settings(data_dir=tmp_path, max_rounds=2, min_evidence=2))
    try:
        tid = app.create_task(CreateTask(question="Research an unknown internal dataset"))
        app.run_task(tid)
        result = app.get_task(tid)
        assert result["status"] == "completed"
        assert sum(event.startswith("retrieve:") for event in result["trace"]) == 2
        assert "无证据" in result["report"]
    finally:
        app.close()
