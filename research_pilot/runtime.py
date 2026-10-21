"""Single-worker demonstrator with SQLite tasks and LangGraph checkpoints."""
from __future__ import annotations

import os
import sqlite3
import threading

from .config import Settings
from .model import LangChainOpenAIResearchModel, MockResearchModel
from .retrieval import LocalSearch, NoExternalSearch, SearchTools, TavilySearch
from .schema import CreateTask, IngestText
from .store import LocalStore


class ResearchRuntime:
    def __init__(self, settings: Settings, *, model=None, interrupt_before=None):
        settings.validate()
        self.settings = settings
        self.store = LocalStore(settings.data_dir / "tasks.sqlite3")
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
        from langgraph.checkpoint.sqlite import SqliteSaver

        from .workflow import build_graph
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(settings.data_dir / "checkpoints.sqlite3"),
                               check_same_thread=False)
        self.checkpoint_conn = conn
        self.checkpointer = SqliteSaver(conn)
        if model is None:
            if settings.model_backend == "ollama":
                from .local_llm import LocalStructuredModel, verify_local_model
                model = LocalStructuredModel(settings)
                model.identity = {**verify_local_model(settings), "provider": "ollama",
                                  "base_url": settings.model_base_url.rstrip("/")}
            elif settings.model_backend == "deepseek":
                from .deepseek import DeepSeekStructuredModel
                model = DeepSeekStructuredModel(settings)
            else:
                model = MockResearchModel() if settings.model_backend == "mock" else \
                    LangChainOpenAIResearchModel(settings.model_name, settings.model_api_key,
                                                 settings.model_base_url)
        self.model_identity = dict(getattr(model, "identity", {}))
        external = NoExternalSearch() if settings.search_backend == "none" else \
            TavilySearch(settings.tavily_api_key)
        self.local = LocalSearch(self.store)
        if settings.retrieval_backend == "pgvector":
            from .vector import PgVectorSearch, create_embedding
            self.local = PgVectorSearch(settings.postgres_dsn,
                                        create_embedding(settings.embedding_cache_dir, settings.embedding_model,
                                                         query_instruction=settings.embedding_query_instruction),
                                        settings.vector_collection, settings.vector_min_score)
        self.graph = build_graph(
            model, SearchTools(self.local, external, settings.retrieval_top_k), settings, self.checkpointer,
            interrupt_before=interrupt_before,
            model_budget=self.store,
        )
        self.lock = threading.Lock()  # Protect the active-task set within one process.
        self.active: set[str] = set()

    def _on_step(self, name: str, state: dict) -> None:
        self.store.patch_task(state["task_id"], phase=name, trace=state.get("trace", []),
                              sources=state.get("sources", []),
                              tool_errors=state.get("tool_errors", []),
                              evidence_status=state.get("evidence_status", "unassessed"),
                              research=state.get("research", {}))

    def create_task(self, data: CreateTask) -> str:
        task_id = self.store.create_task(data)
        if self.model_identity:
            self.store.patch_task(task_id, research={"model": self.model_identity})
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        return self.store.task(task_id)

    def ingest_text(self, data: IngestText) -> tuple[str, int]:
        if self.settings.retrieval_backend == "pgvector":
            return self.local.ingest_text(data)
        return self.store.ingest_text(data)

    def run_task(self, task_id: str) -> None:
        # BackgroundTasks uses worker threads; suppress duplicate execution of the same task.
        with self.lock:
            if task_id in self.active:
                return
            self.active.add(task_id)
        current = {}
        try:
            current = self.store.task(task_id)
            if not current or current["status"] == "completed":
                return
            self.store.patch_task(task_id, status="running", phase="starting", error_code=None)
            config = {"configurable": {"thread_id": task_id}, "recursion_limit": 20}
            snapshot = self.graph.get_state(config)
            saved = snapshot.values.get("research", current.get("research", {})).get("model", {})
            if saved:
                # Legacy pinned Qwen tasks had no explicit provider/endpoint fields.
                provider = saved.get("provider", "ollama" if saved.get("manifest_sha256") else None)
                if (provider != self.model_identity.get("provider") or
                        saved.get("model") != self.model_identity.get("model") or
                        saved.get("base_url", self.model_identity.get("base_url")) !=
                        self.model_identity.get("base_url") or
                        saved.get("manifest_sha256") != self.model_identity.get("manifest_sha256")):
                    from .local_llm import ProviderFailure
                    raise ProviderFailure("MODEL_IDENTITY_MISMATCH")
            elif snapshot.values and self.model_identity.get("provider") == "deepseek":
                from .local_llm import ProviderFailure
                raise ProviderFailure("MODEL_IDENTITY_MISSING")
            graph_input = None if snapshot.values else {
                "task_id": task_id, "question": current["question"], "scope": current["scope"],
                "research": current.get("research", {})}
            if not snapshot.values or snapshot.next:
                # Stream only from the runtime thread. Timed-out node threads never update tasks.
                for state in self.graph.stream(graph_input, config, stream_mode="values",
                                               durability="sync"):
                    trace = state.get("trace", [])
                    phase = trace[-1].split(":")[0] if trace else "starting"
                    self._on_step(phase, state)
            snapshot = self.graph.get_state(config)
            result = snapshot.values
            if snapshot.next:
                self.store.patch_task(task_id, status="interrupted", phase="interrupted")
                return
            if result.get("report_status") == "completed":
                self.store.patch_task(task_id, status="completed", phase="complete",
                                      report=result["report"], sources=result.get("sources", []),
                                      trace=result.get("trace", []), error_code=None,
                                      tool_errors=result.get("tool_errors", []),
                                      evidence_status=result.get("evidence_status", "unassessed"),
                                      research=result.get("research", {}))
            else:
                self.store.patch_task(task_id, status="failed", phase="validation",
                                      error_code="REPORT_CITATION_INVALID",
                                      sources=result.get("sources", []),
                                      trace=result.get("trace", []),
                                      tool_errors=result.get("tool_errors", []),
                                      research=result.get("research", {}))
        except Exception as exc:  # noqa: BLE001 -- worker boundary stores safe classifications only
            # Do not persist a raw exception, which might contain keys / prompts.
            fields = {}
            try:
                stable = self.graph.get_state({"configurable": {"thread_id": task_id}}).values
                fields = {"sources": stable.get("sources", []), "trace": stable.get("trace", []),
                          "tool_errors": stable.get("tool_errors", []),
                          "evidence_status": stable.get("evidence_status", "unassessed"),
                          "research": stable.get("research", current.get("research", {}))}
            except Exception:  # noqa: BLE001 -- preserve the original safe failure classification
                fields = {}  # Keep the last published state if the checkpoint cannot be read.
            from httpx import TimeoutException
            from openai import APITimeoutError
            timed_out = isinstance(exc, (TimeoutError, APITimeoutError, TimeoutException))
            from .local_llm import ProviderFailure
            if isinstance(exc, ProviderFailure):
                timed_out = exc.code == "MODEL_TIMEOUT"
            self.store.patch_task(task_id, status="timed_out" if timed_out else "failed",
                                  phase="timeout" if timed_out else "error",
                                  error_code=(exc.code if isinstance(exc, ProviderFailure) else
                                              "WORKFLOW_STEP_TIMEOUT" if timed_out else
                                              f"WORKFLOW_FAILURE_{type(exc).__name__}"), **fields)
        finally:
            with self.lock:
                self.active.discard(task_id)

    def close(self) -> None:
        if self.settings.retrieval_backend == "pgvector":
            self.local.close()
        self.store.close()
        self.checkpoint_conn.close()
