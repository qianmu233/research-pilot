"""Requires real local PostgreSQL/pgvector and downloaded ONNX weights. No mocks/skips."""
import os
import uuid
from pathlib import Path

import numpy as np
import psycopg
import pytest

from research_pilot.config import Settings
from research_pilot.retrieval import overlap_score
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText
from research_pilot.vector import LocalEmbedding, PgVectorSearch

DEMO_DSN = ("postgresql://researchpilot_demo:researchpilot_local_demo"
            "@127.0.0.1:15432/researchpilot_demo")


@pytest.fixture(scope="module")
def embedding():
    return LocalEmbedding(Path(os.getenv("RESEARCH_EMBEDDING_CACHE_DIR", "data/models")))


@pytest.fixture
def vector_store(embedding):
    dsn = os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN)
    collection = "test-" + uuid.uuid4().hex
    store = PgVectorSearch(dsn, embedding, collection)
    try:
        yield store
    finally:
        with store.conn.transaction():
            store.conn.execute("DELETE FROM researchpilot_vector_chunks WHERE collection=%s",
                               (collection,))
            store.conn.execute("DELETE FROM researchpilot_vector_collections WHERE name=%s",
                               (collection,))
        store.close()


def test_real_embeddings_semantic_ranking_and_postgres_persistence(vector_store):
    query = "How can I fix a car?"
    target = "An automobile mechanic repairs broken vehicles in a garage."
    assert overlap_score(query, target) == 0  # Shared words cannot explain this match.
    vector_store.ingest_text(IngestText(title="Vehicle maintenance", content=target))
    vector_store.ingest_text(IngestText(title="Cooking", content=
                                     "To bake bread, mix flour with yeast and water."))
    result = vector_store.search(query)
    assert result and result[0]["title"] == "Vehicle maintenance", result
    assert result[0]["locator"].startswith("pgvector:")
    rows = vector_store.conn.execute("""
        SELECT vector_dims(embedding), content FROM researchpilot_vector_chunks
        WHERE collection=%s
    """, (vector_store.collection,)).fetchall()
    assert len(rows) == 2 and all(row[0] == 384 for row in rows)
    # Reconnect to the actual database; vectors are not an in-memory test index.
    reopened = PgVectorSearch(os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN),
                             vector_store.embedding, vector_store.collection)
    try:
        assert reopened.search(query)[0]["locator"] == result[0]["locator"]
    finally:
        reopened.close()


def test_real_tokenizer_chunking_no_silent_truncation(embedding):
    text = "Research workflows save durable checkpoints. " * 400 + "UNIQUEFINALMARKER"
    chunks = embedding.chunks(text)
    assert len(chunks) > 2 and chunks[-1].endswith("UNIQUEFINALMARKER")
    assert all(len(embedding.tokenizer.encode(c, add_special_tokens=False).ids) <= 256
               for c in chunks)
    vectors = embedding.documents(chunks[:2])
    assert all(v.shape == (384,) and np.isfinite(v).all() for v in vectors)
    assert not np.allclose(vectors[0], embedding.query("Fresh fruit and cooking recipes"))


def test_pgvector_real_langgraph_vertical_workflow(tmp_path, vector_store):
    settings = Settings(data_dir=tmp_path, retrieval_backend="pgvector",
                        postgres_dsn=os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN),
                        embedding_cache_dir=Path(os.getenv("RESEARCH_EMBEDDING_CACHE_DIR", "data/models")),
                        vector_collection=vector_store.collection, min_evidence=1)
    app = ResearchRuntime(settings)
    try:
        app.ingest_text(IngestText(title="Checkpoint durability", content=
                                  "LangGraph checkpoints persist workflow state for crash recovery."))
        task_id = app.create_task(CreateTask(question="How do LangGraph checkpoints recover workflow state?"))
        app.run_task(task_id)
        task = app.get_task(task_id)
        assert task["status"] == "completed", task
        assert task["sources"][0]["locator"].startswith("pgvector:")
        assert "[S1]" in task["report"]
    finally:
        app.close()


def test_failed_database_statement_rolls_back_entire_ingest(vector_store):
    # Real PostgreSQL CHECK violation on this isolated collection, not a fake cursor.
    constraint = "reject_second_" + uuid.uuid4().hex
    with vector_store.conn.transaction():
        vector_store.conn.execute(psycopg.sql.SQL("""
            ALTER TABLE researchpilot_vector_chunks ADD CONSTRAINT {}
            CHECK (collection <> {} OR chunk_id NOT LIKE '%-1')
        """).format(psycopg.sql.Identifier(constraint),
                    psycopg.sql.Literal(vector_store.collection)))
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            vector_store.ingest_text(IngestText(title="REJECT_AT_DATABASE", content=
                                              "Actual database transaction rollback acceptance. " * 100))
        assert vector_store.conn.execute("""
            SELECT count(*) FROM researchpilot_vector_chunks WHERE collection=%s
        """, (vector_store.collection,)).fetchone()[0] == 0
    finally:
        vector_store.conn.execute(psycopg.sql.SQL(
            "ALTER TABLE researchpilot_vector_chunks DROP CONSTRAINT {}"
        ).format(psycopg.sql.Identifier(constraint)))
