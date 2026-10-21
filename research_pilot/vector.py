"""Local pretrained ONNX embeddings and real PostgreSQL/pgvector cosine search.

No model API or generated placeholder vectors. Model downloads are explicit;
normal application startup only loads an existing local cache.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from .schema import IngestText

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
ZH_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
ZH_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def model_manifest(model_name: str = MODEL_NAME) -> dict:
    names = {MODEL_NAME: "embedding.lock.json", ZH_MODEL_NAME: "embedding-zh.lock.json"}
    if model_name not in names:
        raise ValueError("UNSUPPORTED_EMBEDDING_MODEL")
    return json.loads(files("research_pilot").joinpath(names[model_name]).read_text("utf-8"))


def pinned_model_path(cache_dir: Path, *, local_files_only: bool = True,
                      model_name: str = MODEL_NAME) -> Path:
    """Freeze weights AND tokenizer; a cached moving `main` is not a version lock."""
    lock = model_manifest(model_name)
    if lock["model"] != model_name or lock["dimensions"] != (384 if model_name == MODEL_NAME else 512):
        raise ValueError("EMBEDDING_LOCK_IDENTITY_MISMATCH")
    path = cache_dir / ("models--" + lock["repository"].replace("/", "--")) / "snapshots" / lock["revision"]
    if not local_files_only:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=lock["repository"], revision=lock["revision"],
                          cache_dir=str(cache_dir), allow_patterns=list(lock["artifacts_sha256"]),
                          token=False)
    for name, expected in lock["artifacts_sha256"].items():
        artifact = path / name
        if not artifact.is_file():
            raise FileNotFoundError("PINNED_EMBEDDING_NOT_CACHED: run scripts/download_embedding.py")
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
            raise ValueError(f"EMBEDDING_ARTIFACT_HASH_MISMATCH:{name}")
    return path


class TokenChunking:
    def chunks(self, text: str, size: int = 256, overlap: int = 32) -> list[str]:
        if not 0 <= overlap < size <= 480:
            raise ValueError("Invalid embedding token chunk limits")
        with self.lock:
            encoded = self.tokenizer.encode(text, add_special_tokens=False)
        offsets = encoded.offsets
        parts = []
        for start in range(0, len(offsets), size - overlap):
            end = min(start + size, len(offsets))
            part = text[offsets[start][0]:offsets[end - 1][1]].strip()
            if part:
                parts.append(part)
            if end == len(offsets):
                break
        return parts


class LocalEmbedding(TokenChunking):
    model_name = MODEL_NAME
    dimensions = DIMENSIONS
    query_instruction = False
    query_prefix = ""

    def __init__(self, cache_dir: Path, *, local_files_only: bool = True):
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        self.cache_dir = cache_dir
        self.model_dir = pinned_model_path(cache_dir, local_files_only=local_files_only)
        self.model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache_dir),
                                   local_files_only=True, threads=2,
                                   specific_model_path=str(self.model_dir))
        # Clone the actual embedding tokenizer so chunking cannot change inference settings.
        self.tokenizer = Tokenizer.from_str(self.model.model.tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.lock = threading.Lock()

    def documents(self, texts: list[str]):
        with self.lock:
            return list(self.model.passage_embed(texts, batch_size=32))

    def query(self, text: str):
        with self.lock:
            return next(iter(self.model.query_embed(text)))


class ChineseEmbedding(TokenChunking):
    """Official BAAI safetensors, CPU/float32 CLS + L2, without remote custom code."""
    model_name = ZH_MODEL_NAME
    dimensions = 512

    def __init__(self, cache_dir: Path, *, query_instruction: bool = False,
                 local_files_only: bool = True):
        import torch
        from tokenizers import Tokenizer
        from transformers import AutoModel, AutoTokenizer

        self.cache_dir = cache_dir
        self.model_dir = pinned_model_path(cache_dir, model_name=self.model_name,
                                           local_files_only=local_files_only)
        self.query_instruction = query_instruction
        self.query_prefix = ZH_QUERY_INSTRUCTION if query_instruction else ""
        torch.set_num_threads(2)
        self.encoding_tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_dir), local_files_only=True, trust_remote_code=False)
        self.tokenizer = Tokenizer.from_str(self.encoding_tokenizer.backend_tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.model = AutoModel.from_pretrained(str(self.model_dir), local_files_only=True,
                                               trust_remote_code=False, use_safetensors=True)
        self.model.to("cpu").eval()
        if self.model.config.hidden_size != self.dimensions:
            raise ValueError("EMBEDDING_MODEL_DIMENSION_MISMATCH")
        self.lock = threading.Lock()

    def documents(self, texts: list[str]):
        import torch
        vectors = []
        with self.lock, torch.inference_mode():
            for start in range(0, len(texts), 32):
                tokens = self.encoding_tokenizer(texts[start:start+32], padding=True,
                                                  truncation=True, max_length=512,
                                                  return_tensors="pt")
                cls = self.model(**tokens).last_hidden_state[:, 0]
                normalized = torch.nn.functional.normalize(cls, p=2, dim=1, eps=1e-12)
                vectors.extend(normalized.cpu().numpy())
        return vectors

    def query(self, text: str):
        # The instruction is query-only. Passage encoding never adds it.
        return self.documents([self.query_prefix + text])[0]


def create_embedding(cache_dir: Path, model_name: str = MODEL_NAME, *,
                     query_instruction: bool = False, local_files_only: bool = True):
    if model_name == MODEL_NAME:
        if query_instruction:
            raise ValueError("CHINESE_INSTRUCTION_REQUIRES_CHINESE_MODEL")
        return LocalEmbedding(cache_dir, local_files_only=local_files_only)
    if model_name == ZH_MODEL_NAME:
        return ChineseEmbedding(cache_dir, query_instruction=query_instruction,
                                 local_files_only=local_files_only)
    raise ValueError("UNSUPPORTED_EMBEDDING_MODEL")


class PgVectorSearch:
    def __init__(self, dsn: str, embedding, collection: str = "default",
                 min_score: float = 0.5):
        import psycopg
        from pgvector.psycopg import register_vector

        self.embedding = embedding
        tables = {MODEL_NAME: (384, "researchpilot_vector_chunks", "researchpilot_vector_collections"),
                  ZH_MODEL_NAME: (512, "researchpilot_vector_chunks_512", "researchpilot_vector_collections_512")}
        if embedding.model_name not in tables or embedding.dimensions != tables[embedding.model_name][0]:
            raise ValueError("VECTOR_MODEL_DIMENSION_MISMATCH")
        self.dimensions, self.chunk_table, self.collection_table = tables[embedding.model_name]
        self.model_fingerprint = hashlib.sha256(json.dumps(
            model_manifest(embedding.model_name), sort_keys=True).encode()).hexdigest()
        self.collection = collection
        self.min_score = min_score
        self.lock = threading.RLock()
        self.conn = psycopg.connect(dsn, connect_timeout=5, autocommit=True)
        try:
            self.conn.execute("SET statement_timeout = '10s'")
            self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(self.conn)
            extra = ", fingerprint TEXT NOT NULL" if self.dimensions == 512 else ""
            self.conn.execute(self.statement("""
                CREATE TABLE IF NOT EXISTS {collections} (
                    name TEXT PRIMARY KEY, model TEXT NOT NULL, dimensions INTEGER NOT NULL
                    {extra}
                )
            """, extra=extra))
            self.conn.execute(self.statement("""
                CREATE TABLE IF NOT EXISTS {chunks} (
                    chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                    collection TEXT NOT NULL REFERENCES {collections}(name),
                    title TEXT NOT NULL, source_ref TEXT NOT NULL, content TEXT NOT NULL,
                    embedding vector({dimensions}) NOT NULL
                )
            """))
            from psycopg import sql
            self.conn.execute(self.statement("""
                CREATE INDEX IF NOT EXISTS {index} ON {chunks}(collection)
            """, index=sql.Identifier(self.chunk_table + "_collection_idx")))
            actual_type = self.conn.execute("""
                SELECT format_type(atttypid,atttypmod) FROM pg_attribute
                WHERE attrelid=%s::regclass AND attname='embedding'
            """, (self.chunk_table,)).fetchone()[0]
            if actual_type != f"vector({self.dimensions})":
                raise ValueError("VECTOR_TABLE_DIMENSION_MISMATCH")
            with self.conn.transaction():
                values = (collection, embedding.model_name, self.dimensions)
                placeholders = "%s, %s, %s"
                if self.dimensions == 512:
                    values += (self.model_fingerprint,)
                    placeholders += ", %s"
                self.conn.execute(self.statement("""
                    INSERT INTO {collections} VALUES ({placeholders})
                    ON CONFLICT (name) DO NOTHING
                """, placeholders=placeholders), values)
                fields = "model, dimensions, fingerprint" if self.dimensions == 512 else "model, dimensions"
                row = self.conn.execute(self.statement("""
                    SELECT {fields} FROM {collections} WHERE name=%s
                """, fields=fields), (collection,)).fetchone()
                if row != values[1:]:
                    raise ValueError("VECTOR_COLLECTION_MODEL_MISMATCH")
        except BaseException:
            self.conn.close()
            raise

    def statement(self, template: str, **extra):
        """Identifiers and fixed SQL fragments only; all document/query values stay parameters."""
        from psycopg import sql
        return sql.SQL(template).format(
            chunks=sql.Identifier(self.chunk_table), collections=sql.Identifier(self.collection_table),
            dimensions=sql.Literal(self.dimensions),
            **{key: sql.SQL(value) if isinstance(value, str) else value for key, value in extra.items()})

    def ingest_text(self, document: IngestText) -> tuple[str, int]:
        chunks = self.embedding.chunks(document.content)
        if not chunks:
            raise ValueError("DOCUMENT_HAS_NO_TOKENS")
        vectors = self.embedding.documents(chunks)
        if len(vectors) != len(chunks):
            raise ValueError("EMBEDDING_COUNT_MISMATCH")
        doc_id = uuid.uuid4().hex
        with self.lock, self.conn.transaction(), self.conn.cursor() as cursor:
            cursor.executemany(self.statement("""
                    INSERT INTO {chunks}
                    (chunk_id,doc_id,collection,title,source_ref,content,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """), [(f"{doc_id}-{i}", doc_id, self.collection, document.title,
                    document.source_ref, chunk, vector)
                   for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))])
        return doc_id, len(chunks)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if not 1 <= limit <= 20:
            raise ValueError("VECTOR_LIMIT_MUST_BE_1_TO_20")
        vector = self.embedding.query(query)
        with self.lock:
            rows = self.conn.execute(self.statement("""
                SELECT chunk_id, title, content, 1 - (embedding <=> %s) AS score,
                       doc_id, source_ref
                FROM {chunks} WHERE collection=%s
                ORDER BY embedding <=> %s, source_ref, chunk_id LIMIT %s
            """), (vector, self.collection, vector, limit)).fetchall()
        timestamp = datetime.now(UTC).isoformat()
        return [{"title": title, "locator": f"pgvector:{chunk_id}", "excerpt": content,
                 "source_type": "local", "retrieved_at": timestamp, "query": query,
                 "document_id": doc_id, "chunk_id": chunk_id, "source_ref": source_ref,
                 "score": float(score)}
                for chunk_id, title, content, score, doc_id, source_ref in rows
                if score >= self.min_score]

    def close(self):
        with self.lock:
            self.conn.close()
