"""Pure offline component tests: do not require LangGraph installation."""
from pathlib import Path

import pytest

from research_pilot.config import Settings
from research_pilot.evidence import merge_sources, validate_citations
from research_pilot.model import MockResearchModel
from research_pilot.retrieval import LocalSearch, NoExternalSearch, SearchTools
from research_pilot.schema import CreateTask, IngestText
from research_pilot.store import LocalStore


def test_task_state_persistence(tmp_path: Path):
    store = LocalStore(tmp_path / "test.sqlite3")
    task_id = store.create_task(CreateTask(question="What are the LangGraph checkpointing tradeoffs?"))
    assert store.task(task_id)["status"] == "pending"
    store.patch_task(task_id, status="completed", phase="complete", report="OK", trace=["plan"])
    assert store.task(task_id)["report"] == "OK"
    store.close()
    reopened = LocalStore(tmp_path / "test.sqlite3")
    assert reopened.task(task_id)["trace"] == ["plan"]
    reopened.close()


def test_document_ingest_and_real_lexical_retrieval(tmp_path: Path):
    store = LocalStore(tmp_path / "test.sqlite3")
    store.ingest_text(IngestText(title="LangGraph", content="LangGraph provides graph state and checkpoints.\nLangChain supports model adapters and tools."))
    result = LocalSearch(store).search("LangGraph state checkpoints", 3)
    assert len(result) >= 1
    assert "LangGraph" in result[0]["excerpt"]
    assert result[0]["locator"].startswith("local:")
    store.close()


def test_no_external_search_does_not_fabricate_results(tmp_path: Path):
    store = LocalStore(tmp_path / "test.sqlite3")
    found, errors = SearchTools(LocalSearch(store), NoExternalSearch()).search(["unknown"])
    assert found == [] and errors == []
    store.close()


def test_evidence_dedup_and_citation_guard():
    item = {"title": "T", "locator": "local:x", "excerpt": "Fact", "source_type": "local", "query": "Q", "retrieved_at": "2026-01-01"}
    sources = merge_sources([], [item, item], 10)
    assert len(sources) == 1 and sources[0]["source_id"] == "S1"
    assert validate_citations("Fact [S1]", sources) == (True, "OK")
    assert validate_citations("Fact [S99]", sources) == (False, "UNKNOWN_CITATION_ID")
    assert validate_citations("Fact [S123456]", sources) == (False, "UNKNOWN_CITATION_ID")
    assert validate_citations("Fact without reference", sources) == (False, "MISSING_CITATIONS")


def test_mock_report_is_labelled_not_real_llm():
    report = MockResearchModel().draft("A topic", "", [{"source_id": "S1", "title": "test", "excerpt": "Demo text"}])
    assert "Mock" in report and "[S1]" in report


def test_configuration_fails_closed(tmp_path: Path):
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, max_rounds=100).validate()
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, model_backend="openai").validate()
