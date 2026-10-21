"""Small frozen Chinese retrieval benchmark. No LLM calls or label tuning."""
from __future__ import annotations

import hashlib
import json
import platform
import time
import uuid
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from .evidence import merge_sources, validate_citations
from .schema import IngestText
from .vector import LocalEmbedding, PgVectorSearch


def load_dataset(path: Path) -> tuple[dict, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != path.with_suffix(".sha256").read_text(encoding="ascii").strip():
        raise ValueError("BENCHMARK_DATASET_CHECKSUM_MISMATCH")
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [d["id"] for d in data["documents"]]
    query_ids = [q["id"] for q in data["queries"]]
    if len(set(ids)) != len(ids) or len(set(query_ids)) != len(query_ids):
        raise ValueError("BENCHMARK_DUPLICATE_IDS")
    for query in data["queries"]:
        if not set(query["relevant_documents"]) <= set(ids) or not query["rationale"]:
            raise ValueError("BENCHMARK_INVALID_LABELS")
    return data, digest


def metrics(rows: list[dict], key: str) -> dict:
    answerable = [r for r in rows if r["relevant_documents"]]
    empty = [r for r in rows if not r["relevant_documents"]]
    out = {"answerable_queries": len(answerable), "no_answer_queries": len(empty)}
    for k in (3, 5):
        recalls = [len(set(r["relevant_documents"]) &
                       {d["document"] for d in r[key][:k]}) / len(r["relevant_documents"])
                   for r in answerable]
        out[f"recall@{k}"] = sum(recalls) / len(recalls) if recalls else 0.0
    rr = [next((1 / rank for rank, item in enumerate(r[key][:5], 1)
                if item["document"] in r["relevant_documents"]), 0.0) for r in answerable]
    out["mrr@5"] = sum(rr) / len(rr) if rr else 0.0
    out["no_answer_empty_count"] = sum(not r[key] for r in empty)
    out["no_answer_nonempty_count"] = sum(bool(r[key]) for r in empty)
    out["no_answer_rejection_rate"] = out["no_answer_empty_count"] / len(empty) if empty else 0.0
    multi = [r for r in answerable if len(r["relevant_documents"]) > 1]
    out["multi_document_queries"] = len(multi)
    out["multi_document_all_gold_in_top5"] = sum(
        set(r["relevant_documents"]) <= {i["document"] for i in r[key][:5]} for r in multi)
    out["returned_irrelevant_chunks@5"] = sum(
        item["document"] not in r["relevant_documents"] for r in rows for item in r[key][:5])
    return out


def model_identity(embedding: LocalEmbedding) -> dict:
    model_dir = embedding.model_dir
    packages = ["fastembed", "onnxruntime", "tokenizers", "pgvector", "psycopg"]
    if embedding.dimensions == 512:
        packages += ["torch", "transformers", "safetensors"]
    return {"name": embedding.model_name, "snapshot": model_dir.name,
            "dimensions": embedding.dimensions, "query_instruction": embedding.query_instruction,
            "query_prefix": embedding.query_prefix, "document_prefix": "",
            "encoding": "CPU, CLS pooling, L2 normalization",
            "artifacts_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(model_dir.iterdir()) if p.is_file()},
            "packages": {name: version(name) for name in packages},
            "python": platform.python_version()}


def memory_snapshot() -> dict:
    """Read this benchmark process only; native tensor memory is not Python tracemalloc."""
    if platform.system() == "Windows":
        import ctypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in
                ("peak", "working", "qpp", "qp", "qpnp", "qnp", "pagefile", "peakpagefile")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        function = ctypes.windll.psapi.GetProcessMemoryInfo
        function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if not function(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb):
            return {"error": "PROCESS_MEMORY_UNAVAILABLE"}
        return {"working_set_mib": counters.working / 2**20, "peak_working_set_mib": counters.peak / 2**20}
    import resource
    return {"peak_working_set_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}


def run_benchmark(dataset: dict, digest: str, embedding, dsn: str,
                  run_label: str, *, collection: str | None = None, keep_index: bool = False) -> dict:
    started = time.perf_counter()
    store = PgVectorSearch(dsn, embedding, collection or "benchmark-" + uuid.uuid4().hex, min_score=0.5)
    count = store.conn.execute(store.statement(
        "SELECT count(*) FROM {chunks} WHERE collection=%s"), (store.collection,)).fetchone()[0]
    if count:
        store.close()
        raise FileExistsError("BENCHMARK_COLLECTION_NOT_EMPTY: preserve prior vectors; choose a new name")
    mapping = {}
    checks = {"missing_source_rows": 0, "metadata_mismatches": 0,
              "excerpt_mismatches": 0, "dedup_mismatches": 0}
    try:
        ingest_started = time.perf_counter()
        for document in dataset["documents"]:
            doc_id, count = store.ingest_text(IngestText(
                title=document["title"], content=document["content"],
                source_ref=f"synthetic:{dataset['version']}:{document['id']}"))
            for i in range(count):
                mapping[f"{doc_id}-{i}"] = {"document": document["id"],
                                            "chunk": f"{document['id']}#{i}"}
        ingest_seconds = time.perf_counter() - ingest_started
        vector_rows = store.conn.execute(store.statement(
            "SELECT embedding FROM {chunks} WHERE collection=%s ORDER BY source_ref,chunk_id"),
            (store.collection,)).fetchall()
        document_vector_digest = hashlib.sha256(b"".join(
            np.asarray(row[0].to_numpy() if hasattr(row[0], "to_numpy") else row[0],
                       dtype="<f4").tobytes() for row in vector_rows)).hexdigest()
        norms = [float(np.linalg.norm(embedding.query(q["question"])))
                 for q in dataset["queries"]]
        texts = [q["question"] for q in dataset["queries"]] + [
            d["content"] for d in dataset["documents"]]
        token_ids = [tid for text in texts for tid in
                     embedding.tokenizer.encode(text, add_special_tokens=False).ids]
        unknown_id = embedding.tokenizer.token_to_id("[UNK]")
        rows = []
        search_times = []
        for query in dataset["queries"]:
            vector = embedding.query(query["question"])
            ranked = store.conn.execute(store.statement("""
                SELECT chunk_id, 1 - (embedding <=> %s) FROM {chunks}
                WHERE collection=%s ORDER BY embedding <=> %s, source_ref, chunk_id LIMIT 5
            """), (vector, store.collection, vector)).fetchall()
            raw = [{**mapping[chunk_id], "score": float(score)} for chunk_id, score in ranked]
            search_started = time.perf_counter()
            evidence = store.search(query["question"], limit=5)
            search_times.append((time.perf_counter() - search_started) * 1000)
            accepted = []
            for item in evidence:
                chunk_id = item["locator"].removeprefix("pgvector:")
                db = store.conn.execute(store.statement("""
                    SELECT doc_id,source_ref,content FROM {chunks}
                    WHERE chunk_id=%s AND collection=%s
                """), (chunk_id, store.collection)).fetchone()
                if db is None or chunk_id not in mapping:
                    checks["missing_source_rows"] += 1
                    continue
                checks["metadata_mismatches"] += int(
                    (item.get("document_id"), item.get("chunk_id"), item.get("source_ref")) !=
                    (db[0], chunk_id, db[1]))
                checks["excerpt_mismatches"] += int(item["excerpt"] != db[2])
                score = next(score for cid, score in ranked if cid == chunk_id)
                accepted.append({**mapping[chunk_id], "score": float(score),
                                 "source_id": f"S{len(accepted)+1}", "locator": item["locator"],
                                 "document_id": db[0], "chunk_id": chunk_id, "source_ref": db[1]})
            merged = merge_sources([], evidence + evidence, 20)
            checks["dedup_mismatches"] += int(
                len(merged) != len(evidence) or
                [s["locator"] for s in merged] != [s["locator"] for s in evidence] or
                [s["source_id"] for s in merged] != [f"S{i+1}" for i in range(len(evidence))])
            assert validate_citations("伪造证据 [S99999]", merged) == (
                False, "UNKNOWN_CITATION_ID")
            rows.append({**query, "raw_top5": raw, "production_top5": accepted})
        # Diagnostic only: a syntactically completed Mock report is not semantic answerability.
        from .config import Settings
        from .runtime import ResearchRuntime
        from .schema import CreateTask
        with TemporaryDirectory(prefix="researchpilot-zh-probe-") as temp:
            runtime = ResearchRuntime(Settings(
                data_dir=Path(temp), retrieval_backend="pgvector", postgres_dsn=dsn,
                vector_collection=store.collection,
                embedding_model=embedding.model_name,
                embedding_query_instruction=embedding.query_instruction,
                embedding_cache_dir=embedding.cache_dir))
            try:
                question = next(q for q in dataset["queries"] if q["id"] == "Q19")
                task_id = runtime.create_task(CreateTask(question=question["question"]))
                runtime.run_task(task_id)
                task = runtime.get_task(task_id)
                workflow_probe = {"query_id": "Q19", "gold_documents": [],
                                  "task_status": task["status"], "error_code": task["error_code"],
                                  "evidence_status": task["evidence_status"],
                                  "trace": task["trace"], "report_model": "Mock",
                                  "returned_documents": [
                                      mapping[s["locator"].removeprefix("pgvector:")]["document"]
                                      for s in task["sources"]]}
            finally:
                runtime.close()
        # Probe after metric queries so this deliberately long document cannot alter rankings.
        probe = "persistence " * 100 + "EVIDENCE_TAIL_MARKER"
        doc_id, _ = store.ingest_text(IngestText(title="Synthetic truncation probe",
                                                content=probe, source_ref="synthetic:tail-probe"))
        items = [i for i in store.search("persistence", limit=20)
                 if i["locator"].startswith(f"pgvector:{doc_id}-")]
        stored = dict(store.conn.execute(store.statement(
            "SELECT chunk_id,content FROM {chunks} WHERE doc_id=%s AND collection=%s"),
            (doc_id, store.collection)).fetchall())
        truncation = {"probe_chunk_count": len(stored), "returned_chunk_count": len(items),
                      "stored_characters": sum(len(text) for text in stored.values()),
                      "returned_characters": sum(len(i["excerpt"]) for i in items),
                      "character_count_note": "Counts include token overlap across chunks",
                      "full_chunk_preserved": bool(items) and all(
                          i["excerpt"] == stored[i["chunk_id"]] for i in items),
                      "all_probe_chunks_retrieved": len(stored) == len(items),
                      "tail_marker_preserved": any("EVIDENCE_TAIL_MARKER" in i["excerpt"] for i in items)}
        store.conn.execute(store.statement("DELETE FROM {chunks} WHERE doc_id=%s AND collection=%s"),
                           (doc_id, store.collection))
        return {"run_label": run_label, "dataset_sha256": digest,
                "documents": len(dataset["documents"]), "chunks": len(mapping),
                "query_count": len(rows), "annotation_policy": dataset["annotation_policy"],
                "model": model_identity(embedding), "threshold": 0.5,
                "index": {"chunks_table": store.chunk_table, "collections_table": store.collection_table,
                          "collection": store.collection, "kept": keep_index,
                          "document_vector_digest": document_vector_digest,
                          "fingerprint": store.model_fingerprint},
                "configuration": {"chunk_tokens": 256, "overlap_tokens": 32, "top_k": 5,
                                  "distance": "cosine", "eligibility": "same model table and collection, score>=0.5"},
                "performance": {"ingest_seconds": ingest_seconds,
                                "warm_search_median_ms": float(np.median(search_times)),
                                "warm_search_p95_ms": float(np.percentile(search_times, 95)),
                                "search_ms_per_query": search_times,
                                "elapsed_seconds": time.perf_counter()-started, **memory_snapshot()},
                "query_l2_norm_range": [min(norms), max(norms)],
                "unknown_tokens": token_ids.count(unknown_id), "tokens": len(token_ids),
                "unknown_token_ratio": token_ids.count(unknown_id) / len(token_ids),
                "database_version": store.conn.execute("SHOW server_version").fetchone()[0],
                "pgvector_version": store.conn.execute(
                    "SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
                "production_metrics": metrics(rows, "production_top5"),
                "raw_ranking_metrics": metrics(rows, "raw_top5"),
                "evidence_checks": checks, "truncation_probe": truncation,
                "no_answer_workflow_probe": workflow_probe, "queries": rows}
    finally:
        if not keep_index:
            with store.conn.transaction():
                store.conn.execute(store.statement("DELETE FROM {chunks} WHERE collection=%s"),
                                   (store.collection,))
                store.conn.execute(store.statement("DELETE FROM {collections} WHERE name=%s"),
                                   (store.collection,))
        store.close()
