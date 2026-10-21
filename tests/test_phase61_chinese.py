"""Official 512-D model, real isolated PgVector tables, and conservative evidence status."""
import os
import uuid
from pathlib import Path

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from research_pilot.api import create_app
from research_pilot.config import Settings
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText
from research_pilot.vector import (
    ZH_MODEL_NAME,
    ZH_QUERY_INSTRUCTION,
    ChineseEmbedding,
    LocalEmbedding,
    PgVectorSearch,
)

DEMO_DSN = ("postgresql://researchpilot_demo:researchpilot_local_demo"
            "@127.0.0.1:15432/researchpilot_demo")


@pytest.fixture(scope="module")
def models():
    cache = Path(os.getenv("RESEARCH_EMBEDDING_CACHE_DIR", "data/models"))
    return (ChineseEmbedding(cache), ChineseEmbedding(cache, query_instruction=True),
            LocalEmbedding(cache))


@pytest.fixture
def stores():
    opened = []
    def create(model, collection=None):
        store = PgVectorSearch(os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN), model,
                               collection or "phase61-test-" + uuid.uuid4().hex)
        opened.append(store)
        return store
    try:
        yield create
    finally:
        for store in opened:
            with store.conn.transaction():
                store.conn.execute(store.statement("DELETE FROM {chunks} WHERE collection=%s"),
                                   (store.collection,))
                store.conn.execute(store.statement("DELETE FROM {collections} WHERE name=%s"),
                                   (store.collection,))
            store.close()


def test_official_512_vectors_and_query_only_instruction(models):
    plain, instructed, _ = models
    text = "一份文档的分片在同一数据库事务中写入，失败时全部回滚。"
    passage = plain.documents([text])[0]
    assert passage.shape == (512,) and np.isfinite(passage).all()
    assert abs(float(np.linalg.norm(passage))-1) < 1e-5
    np.testing.assert_allclose(instructed.documents([text])[0], passage, atol=1e-6)
    np.testing.assert_allclose(plain.query(text), passage, atol=1e-6)
    np.testing.assert_allclose(instructed.query(text),
                               plain.documents([ZH_QUERY_INSTRUCTION+text])[0], atol=1e-6)
    assert not np.allclose(instructed.query(text), passage)
    assert plain.model_dir.name == "7999e1d3359715c523056ef9478215996d62a620"


def test_actual_512_table_isolation_and_database_dimension_rejection(models, stores):
    zh, _, en = models
    name = "phase61-dim-" + uuid.uuid4().hex
    old = stores(en, name)
    new = stores(zh, name)
    assert old.chunk_table != new.chunk_table and old.collection_table != new.collection_table
    doc = IngestText(title="合成隔离测试", content="数据库事务应原子写入，失败时回滚文档所有分片。")
    old_id, _ = old.ingest_text(doc)
    new_id, _ = new.ingest_text(doc)
    assert old.conn.execute(old.statement(
        "SELECT vector_dims(embedding) FROM {chunks} WHERE doc_id=%s"), (old_id,)).fetchone()[0] == 384
    assert new.conn.execute(new.statement(
        "SELECT vector_dims(embedding) FROM {chunks} WHERE doc_id=%s"), (new_id,)).fetchone()[0] == 512
    with pytest.raises(psycopg.errors.DataException), old.conn.transaction():
        old.conn.execute(old.statement("""
            INSERT INTO {chunks} (chunk_id,doc_id,collection,title,source_ref,content,embedding)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """), ("invalid-"+uuid.uuid4().hex, "invalid", name, "dimension probe", "synthetic",
               "Must never fit into the old 384-dimensional table", zh.query("数据库事务")))
    assert old.conn.execute(old.statement(
        "SELECT count(*) FROM {chunks} WHERE collection=%s"), (name,)).fetchone()[0] == 1


def test_same_model_collection_eligibility_and_source_identity(models, stores):
    zh, _, _ = models
    current = stores(zh)
    other = stores(zh)
    content = "中文检索只允许返回当前集合的文档，其他集合即使相同文本也不能泄漏。"
    doc_id, _ = current.ingest_text(IngestText(title="合成当前集合", content=content,
                                              source_ref="synthetic:current"))
    other.ingest_text(IngestText(title="合成另一个集合", content=content, source_ref="synthetic:other"))
    result = current.search(content, 20)
    assert len(result) == 1 and result[0]["document_id"] == doc_id
    assert result[0]["source_ref"] == "synthetic:current" and result[0]["excerpt"] == content
    assert abs(result[0]["score"]-1) < 1e-5


def test_model_fingerprint_mismatch_is_rejected(models, stores):
    current = stores(models[0])
    current.conn.execute(current.statement("UPDATE {collections} SET fingerprint=%s WHERE name=%s"),
                          ("different-model-files", current.collection))
    try:
        with pytest.raises(ValueError, match="VECTOR_COLLECTION_MODEL_MISMATCH"):
            PgVectorSearch(os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN),
                            models[0], current.collection)
    finally:
        current.conn.execute(current.statement("UPDATE {collections} SET fingerprint=%s WHERE name=%s"),
                              (current.model_fingerprint, current.collection))


def test_candidate_count_never_claims_semantic_sufficiency(tmp_path):
    runtime = ResearchRuntime(Settings(data_dir=tmp_path, min_evidence=2))
    try:
        for i in range(3):
            runtime.ingest_text(IngestText(title=f"合成候选 {i}", source_ref=f"synthetic:{i}",
                                          content="PgVector 保存向量并进行相似检索。本文没有任何性能实测值。"))
        task_id = runtime.create_task(CreateTask(question="PgVector 一亿向量实测每秒请求量 QPS 是多少？"))
        runtime.run_task(task_id)
        task = runtime.get_task(task_id)
        assert len(task["sources"]) == 3 and task["status"] == "completed"
        assert task["evidence_status"] == "unverified"
        assert "assess:candidates_collected" in task["trace"]
        assert "assess:sufficient" not in task["trace"]
        assert "尚未验证是否足以回答" in task["report"]
        with TestClient(create_app(runtime)) as client:
            assert client.get(f"/api/tasks/{task_id}").json()["evidence_status"] == "unverified"
            assert client.get(f"/api/tasks/{task_id}/report").json()["evidence_status"] == "unverified"
    finally:
        runtime.close()


def test_official_chinese_profile_http_and_checkpoint_result(tmp_path, models, stores):
    store = stores(models[0])
    runtime = ResearchRuntime(Settings(
        data_dir=tmp_path, min_evidence=1, retrieval_backend="pgvector",
        postgres_dsn=os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN),
        vector_collection=store.collection, embedding_model=ZH_MODEL_NAME,
        embedding_cache_dir=models[0].cache_dir, embedding_query_instruction=True))
    try:
        with TestClient(create_app(runtime)) as client:
            imported = client.post("/api/documents/text", json={"title": "合成事务测试",
                "content": "文档所有向量分片在一个 PostgreSQL 事务中插入，失败后整份回滚。",
                "source_ref": "synthetic:phase61-http"})
            assert imported.status_code == 201
            assert imported.json()["index_type"] == "pgvector_bge_small_zh_v1.5_512"
            created = client.post("/api/tasks", json={"question": "文档分片插入失败后数据库事务如何处理？"})
            assert created.status_code == 202
            task = client.get(f"/api/tasks/{created.json()['task_id']}").json()
            assert task["status"] == "completed" and task["evidence_status"] == "unverified", task
            assert task["sources"][0]["document_id"] == imported.json()["document_id"]
            assert task["sources"][0]["source_ref"] == "synthetic:phase61-http"
    finally:
        runtime.close()
