"""Phase 6 evidence integrity and fixed Chinese retrieval, using real ONNX/PgVector."""
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from research_pilot.benchmark import load_dataset, metrics, run_benchmark
from research_pilot.evidence import merge_sources, validate_citations
from research_pilot.schema import CreateTask, IngestText
from research_pilot.vector import LocalEmbedding, PgVectorSearch, pinned_model_path

DATASET = Path(__file__).resolve().parents[1] / "benchmarks/zh_retrieval_v1/dataset.json"
DATASET_SHA256 = "6b7975eb701d461fd712cef3acc0ab749d42498eca65fb75f67250be46d5475c"
DEMO_DSN = ("postgresql://researchpilot_demo:researchpilot_local_demo"
            "@127.0.0.1:15432/researchpilot_demo")


@pytest.fixture(scope="module")
def embedding():
    return LocalEmbedding(Path(os.getenv("RESEARCH_EMBEDDING_CACHE_DIR", "data/models")))


@pytest.fixture
def store(embedding):
    search = PgVectorSearch(os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN),
                            embedding, "phase6-test-" + uuid.uuid4().hex)
    try:
        yield search
    finally:
        with search.conn.transaction():
            search.conn.execute("DELETE FROM researchpilot_vector_chunks WHERE collection=%s",
                                (search.collection,))
            search.conn.execute("DELETE FROM researchpilot_vector_collections WHERE name=%s",
                                (search.collection,))
        search.close()


def test_source_metadata_survives_search_dedup_and_evidence_schema(store):
    doc_id, _ = store.ingest_text(IngestText(title="合成测试：检查点", source_ref="synthetic:zh:source",
                                            content="LangGraph 检查点保存图状态，进程意外退出后可以恢复执行。"))
    result = store.search("LangGraph 检查点保存图状态")
    assert result and result[0]["source_ref"] == "synthetic:zh:source"
    source = result[0]
    assert source["document_id"] == doc_id and source["chunk_id"] == f"{doc_id}-0"
    assert source["locator"] == f"pgvector:{source['chunk_id']}"
    merged = merge_sources([], result + result, 10)
    assert len(merged) == 1 and merged[0]["source_id"] == "S1"
    assert merged[0]["source_ref"] == source["source_ref"]
    from research_pilot.schema import Evidence
    assert Evidence.model_validate(merged[0]).model_dump()["chunk_id"] == source["chunk_id"]
    assert validate_citations("伪造来源 [S999]", merged) == (False, "UNKNOWN_CITATION_ID")


def test_retrieved_evidence_preserves_entire_stored_chunk(store):
    text = "persistence " * 100 + "EVIDENCE_TAIL_MARKER"
    assert len(text) > 900 and len(store.embedding.chunks(text)) == 1
    store.ingest_text(IngestText(title="Synthetic full evidence", content=text))
    result = store.search("persistence")
    assert result and result[0]["excerpt"] == text
    assert result[0]["excerpt"].endswith("EVIDENCE_TAIL_MARKER")


def test_fixed_dataset_labels_and_metric_denominators():
    dataset, checksum = load_dataset(DATASET)
    assert checksum == DATASET_SHA256
    assert len(dataset["queries"]) == 20 and len(dataset["documents"]) == 19
    assert sum(not q["relevant_documents"] for q in dataset["queries"]) == 4
    # Hand-computable metric fixture, independent of model rankings.
    rows = [{"relevant_documents": ["A", "B"], "hits": [{"document": "X"}, {"document": "A"}]},
            {"relevant_documents": ["C"], "hits": []},
            {"relevant_documents": [], "hits": [{"document": "X"}]}]
    result = metrics(rows, "hits")
    assert result["recall@3"] == 0.25 and result["mrr@5"] == 0.25
    assert result["no_answer_nonempty_count"] == 1


def test_real_chinese_vectors_are_normalized_and_use_consistent_encoder(embedding):
    text = "合成测试材料：数据库事务回滚后，失败文档的所有分片均不应留存。"
    query = embedding.query(text)
    passage = embedding.documents([text])[0]
    assert query.shape == (384,) and np.isfinite(query).all()
    assert abs(float(np.linalg.norm(query)) - 1) < 1e-5
    assert abs(float(np.linalg.norm(passage)) - 1) < 1e-5
    np.testing.assert_allclose(query, passage, atol=1e-6)
    long_text = "图状态检查点与数据库事务必须分别验证，不能把恢复当作重试。" * 50 + "CHINESE_TAIL_MARKER"
    parts = embedding.chunks(long_text)
    assert len(parts) > 1 and parts[-1].endswith("CHINESE_TAIL_MARKER")
    assert all(part in long_text and len(embedding.tokenizer.encode(
        part, add_special_tokens=False).ids) <= 256 for part in parts)
    # No claim that a valid vector means a correct Chinese semantic representation.


def test_frozen_chinese_benchmark_evidence_integrity(embedding):
    dataset, checksum = load_dataset(DATASET)
    report = run_benchmark(dataset, checksum, embedding,
                           os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN), "pytest-phase6")
    assert report["query_count"] == 20
    assert report["evidence_checks"] == {
        "missing_source_rows": 0, "metadata_mismatches": 0,
        "excerpt_mismatches": 0, "dedup_mismatches": 0}
    assert report["truncation_probe"]["full_chunk_preserved"]
    assert report["truncation_probe"]["tail_marker_preserved"]
    no_answer = [q for q in report["queries"] if not q["relevant_documents"]]
    assert len(no_answer) == 4
    assert report["production_metrics"]["no_answer_nonempty_count"] == sum(
        bool(q["production_top5"]) for q in no_answer)
    # Inspect/store every low rank and false positive, never assert a tuned recall target.
    assert any(q["id"] == "Q11" and q["relevant_documents"] == ["D17"] for q in report["queries"])


def test_pinned_model_rejects_modified_artifact_and_missing_cache(tmp_path, embedding):
    import json
    from importlib.resources import files
    lock = json.loads(files("research_pilot").joinpath("embedding.lock.json").read_text("utf-8"))
    assert Path(embedding.model.model._model_dir).name == lock["revision"]
    with pytest.raises(FileNotFoundError, match="PINNED_EMBEDDING_NOT_CACHED"):
        pinned_model_path(tmp_path)
    path = tmp_path / ("models--" + lock["repository"].replace("/", "--")) / "snapshots" / lock["revision"]
    path.mkdir(parents=True)
    (path / "config.json").write_text("tampered fixture", encoding="utf-8")
    with pytest.raises(ValueError, match="EMBEDDING_ARTIFACT_HASH_MISMATCH:config.json"):
        pinned_model_path(tmp_path)


def test_chinese_empty_corpus_and_similar_timeout_concepts(store):
    dataset, _ = load_dataset(DATASET)
    assert store.search(dataset["queries"][19]["question"]) == []
    assert validate_citations("没有实际证据却引用 [S1]", []) == (False, "UNKNOWN_CITATION_ID")
    # Fixed gold D17 versus the semantically different SQL timeout and kitchen distractors.
    for doc in dataset["documents"]:
        if doc["id"] in {"D13", "D17", "D18"}:
            store.ingest_text(IngestText(title=doc["title"], content=doc["content"],
                                        source_ref=f"synthetic:{doc['id']}"))
    question = next(q for q in dataset["queries"] if q["id"] == "Q11")
    result = store.search(question["question"])
    assert result and result[0]["source_ref"] == "synthetic:D17"


def test_untrusted_chinese_text_remains_data_and_prompt_boundary(tmp_path):
    from research_pilot.config import Settings
    from research_pilot.model import LangChainOpenAIResearchModel
    from research_pilot.runtime import ResearchRuntime

    dataset, _ = load_dataset(DATASET)
    document = next(d for d in dataset["documents"] if d["id"] == "D16")
    runtime = ResearchRuntime(Settings(data_dir=tmp_path, min_evidence=1))
    try:
        runtime.ingest_text(IngestText(title=document["title"], content=document["content"],
                                      source_ref="synthetic:D16"))
        task_id = runtime.create_task(CreateTask(question="取回的不可信文本与系统指令有何区别？"))
        runtime.run_task(task_id)
        task = runtime.get_task(task_id)
        assert task["status"] == "completed", task
        assert task["sources"][0]["source_ref"] == "synthetic:D16"
        assert "Mock" in task["report"] and task["report"].strip() != "INJECTION_EXECUTED"
        assert task["trace"][-1] == "validate:OK"

        # Only capture request construction, not model security or real LLM behavior.
        calls = []
        class RequestRecorder:
            def invoke(self, messages):
                calls.append(messages)
                return SimpleNamespace(content="确定性请求构建测试 [S1]")
        adapter = object.__new__(LangChainOpenAIResearchModel)
        adapter.client = RequestRecorder()
        adapter.draft("检查不可信文档边界", "", task["sources"])
        system, human = calls[0]
        assert system[0] == "system" and human[0] == "human"
        assert "UNTRUSTED" in system[1] and "INJECTION_EXECUTED" not in system[1]
        assert document["content"] in human[1] and "untrusted" in human[1].lower()
    finally:
        runtime.close()


def test_actual_pgvector_disconnect_fails_workflow_instead_of_inventing_answer(tmp_path, store):
    from fastapi.testclient import TestClient

    from research_pilot.api import create_app
    from research_pilot.config import Settings
    from research_pilot.runtime import ResearchRuntime

    app = ResearchRuntime(Settings(data_dir=tmp_path, retrieval_backend="pgvector",
                                   postgres_dsn=os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN),
                                   embedding_cache_dir=Path(os.getenv("RESEARCH_EMBEDDING_CACHE_DIR", "data/models")),
                                   vector_collection=store.collection))
    try:
        task_id = app.create_task(CreateTask(question="中文检索数据库中断后应如何处理？"))
        app.local.conn.close()  # Real driver error, no fake vector provider.
        app.run_task(task_id)
        task = app.get_task(task_id)
        assert task["status"] == "failed" and task["report"] is None
        assert task["error_code"].startswith("WORKFLOW_FAILURE_")
        with TestClient(create_app(app)) as client:
            assert client.get(f"/api/tasks/{task_id}/report").status_code == 409
    finally:
        app.close()
