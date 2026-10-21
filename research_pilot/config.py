"""Environment-only, fail-closed configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("./data")
    model_backend: str = "mock"
    search_backend: str = "none"
    max_rounds: int = 2
    min_evidence: int = 2
    max_sources: int = 10
    model_name: str = ""
    model_base_url: str = ""
    model_api_key: str = field(default="", repr=False)
    tavily_api_key: str = field(default="", repr=False)
    retrieval_backend: str = "lexical"
    postgres_dsn: str = field(default="", repr=False)
    vector_collection: str = "default"
    embedding_cache_dir: Path = Path("./data/models")
    vector_min_score: float = 0.5
    step_timeout_seconds: float = 30.0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_query_instruction: bool = False
    model_context_tokens: int = 4096
    model_output_tokens: int = 768
    max_model_calls: int = 5
    task_timeout_seconds: float = 300.0
    retrieval_top_k: int = 5

    @classmethod
    def from_env(cls) -> Settings:
        config = cls(
            data_dir=Path(os.getenv("RESEARCH_DATA_DIR", "./data")),
            model_backend=os.getenv("RESEARCH_MODEL_BACKEND", "mock"),
            search_backend=os.getenv("RESEARCH_SEARCH_BACKEND", "none"),
            max_rounds=int(os.getenv("RESEARCH_MAX_ROUNDS", "2")),
            min_evidence=int(os.getenv("RESEARCH_MIN_EVIDENCE", "2")),
            max_sources=int(os.getenv("RESEARCH_MAX_SOURCES", "10")),
            model_name=os.getenv("RESEARCH_OPENAI_MODEL", ""),
            model_base_url=os.getenv("RESEARCH_OPENAI_BASE_URL", ""),
            model_api_key=os.getenv("RESEARCH_OPENAI_API_KEY", ""),
            tavily_api_key=os.getenv("RESEARCH_TAVILY_API_KEY", ""),
            retrieval_backend=os.getenv("RESEARCH_RETRIEVAL_BACKEND", "lexical"),
            postgres_dsn=os.getenv("RESEARCH_POSTGRES_DSN", ""),
            vector_collection=os.getenv("RESEARCH_VECTOR_COLLECTION", "default"),
            embedding_cache_dir=Path(os.getenv("RESEARCH_EMBEDDING_CACHE_DIR", "./data/models")),
            vector_min_score=float(os.getenv("RESEARCH_VECTOR_MIN_SCORE", "0.5")),
            step_timeout_seconds=float(os.getenv("RESEARCH_STEP_TIMEOUT_SECONDS", "30")),
            embedding_model=os.getenv("RESEARCH_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
            embedding_query_instruction=os.getenv("RESEARCH_EMBEDDING_QUERY_INSTRUCTION", "false").lower() == "true",
            model_context_tokens=int(os.getenv("RESEARCH_MODEL_CONTEXT_TOKENS", "4096")),
            model_output_tokens=int(os.getenv("RESEARCH_MODEL_OUTPUT_TOKENS", "768")),
            max_model_calls=int(os.getenv("RESEARCH_MAX_MODEL_CALLS", "5")),
            task_timeout_seconds=float(os.getenv("RESEARCH_TASK_TIMEOUT_SECONDS", "300")),
            retrieval_top_k=int(os.getenv("RESEARCH_RETRIEVAL_TOP_K", "5")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.model_backend not in {"mock", "openai", "ollama"}:
            raise ValueError("RESEARCH_MODEL_BACKEND must be mock, openai or ollama")
        if self.search_backend not in {"none", "tavily"}:
            raise ValueError("RESEARCH_SEARCH_BACKEND must be none or tavily")
        if self.retrieval_backend not in {"lexical", "pgvector"}:
            raise ValueError("RESEARCH_RETRIEVAL_BACKEND must be lexical or pgvector")
        if self.retrieval_backend == "pgvector" and not self.postgres_dsn:
            raise ValueError("PgVector requires RESEARCH_POSTGRES_DSN")
        if self.embedding_model not in {"BAAI/bge-small-en-v1.5", "BAAI/bge-small-zh-v1.5"}:
            raise ValueError("Unsupported embedding model")
        if self.embedding_query_instruction and self.embedding_model != "BAAI/bge-small-zh-v1.5":
            raise ValueError("Chinese query instruction requires Chinese embedding")
        if not self.vector_collection or len(self.vector_collection) > 100:
            raise ValueError("Invalid vector collection")
        if not 0 <= self.vector_min_score <= 1:
            raise ValueError("vector_min_score must be in [0, 1]")
        if not 0 < self.step_timeout_seconds <= 300:
            raise ValueError("step_timeout_seconds must be in (0, 300]")
        if not 1 <= self.max_rounds <= 3 or not 1 <= self.min_evidence <= 10:
            raise ValueError("Invalid round/evidence limits")
        if not 1 <= self.max_sources <= 20:
            raise ValueError("max_sources must be in [1, 20]")
        if not 1 <= self.retrieval_top_k <= 5:
            raise ValueError("retrieval_top_k must be in [1, 5]")
        if self.model_backend == "openai" and not (self.model_name and self.model_api_key):
            raise ValueError("Real model mode requires a model name and API key")
        if self.model_backend == "ollama":
            endpoint = urlparse(self.model_base_url)
            if (endpoint.scheme != "http" or endpoint.hostname not in
                    {"127.0.0.1", "localhost", "host.docker.internal"} or
                    endpoint.username or endpoint.password or endpoint.query or
                    endpoint.path.rstrip("/") != "/v1" or not self.model_name):
                raise ValueError("Ollama requires an explicit local /v1 URL and model name")
            if "cloud" in self.model_name.lower():
                raise ValueError("Cloud models are forbidden in local mode")
        if not 2048 <= self.model_context_tokens <= 8192:
            raise ValueError("Context must be in [2048, 8192]")
        if not 128 <= self.model_output_tokens <= 1536:
            raise ValueError("Output tokens must be in [128, 1536]")
        if not 3 <= self.max_model_calls <= 8 or not 1 <= self.task_timeout_seconds <= 600:
            raise ValueError("Invalid model call/time budget")
        if self.search_backend == "tavily" and not self.tavily_api_key:
            raise ValueError("Tavily mode requires a search API key")
