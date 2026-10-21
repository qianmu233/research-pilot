"""Minimal FastAPI contract for local research tasks."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks, FastAPI, HTTPException

from .schema import CreateTask, IngestText, TaskView

if TYPE_CHECKING:
    from .runtime import ResearchRuntime


def create_app(runtime: ResearchRuntime | None = None) -> FastAPI:
    provided = runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if provided is None:
            from .config import Settings
            from .runtime import ResearchRuntime
            app.state.runtime = ResearchRuntime(Settings.from_env())
        else:
            app.state.runtime = provided
        yield
        if provided is None:
            app.state.runtime.close()

    app = FastAPI(title="ResearchPilot", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        from .config import Settings
        settings = Settings.from_env() if provided is None else provided.settings
        return {"status": "ok", "model_backend": settings.model_backend,
                "search_backend": settings.search_backend,
                "retrieval_backend": settings.retrieval_backend,
                "embedding_model": settings.embedding_model,
                "model_name": settings.model_name,
                "warning": ("Mock results are deterministic fixtures, not verified research" if
                            settings.model_backend == "mock" else
                            "Model assessments and citation checks do not verify factual truth")}

    @app.post("/api/documents/text", status_code=201)
    def ingest(body: IngestText):
        doc_id, chunks = app.state.runtime.ingest_text(body)
        return {"document_id": doc_id, "chunks": chunks,
                "index_type": (("pgvector_bge_small_zh_v1.5_512" if
                                app.state.runtime.settings.embedding_model == "BAAI/bge-small-zh-v1.5" else
                                "pgvector_bge_small_en_v1.5_384") if
                               app.state.runtime.settings.retrieval_backend == "pgvector" else
                               "lexical_ngram_demo_NOT_semantic_embedding")}

    @app.post("/api/tasks", status_code=202)
    def create(body: CreateTask, background_tasks: BackgroundTasks):
        task_id = app.state.runtime.create_task(body)
        background_tasks.add_task(app.state.runtime.run_task, task_id)
        return {"task_id": task_id, "status": "pending"}

    @app.get("/api/tasks/{task_id}", response_model=TaskView)
    def get_task(task_id: str):
        task = app.state.runtime.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
        return task

    @app.get("/api/tasks/{task_id}/report")
    def report(task_id: str):
        task = app.state.runtime.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
        if task["status"] != "completed":
            raise HTTPException(status_code=409, detail="TASK_NOT_COMPLETED")
        return {"task_id": task_id, "markdown": task["report"], "sources": task["sources"],
                "tool_errors": task.get("tool_errors", []),
                "evidence_status": task.get("evidence_status", "unassessed"),
                "research": task.get("research", {}), "model_calls": task.get("model_calls", 0)}

    @app.get("/api/tasks/{task_id}/trace")
    def trace(task_id: str):
        task = app.state.runtime.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
        return {"task_id": task_id, "phase": task["phase"], "events": task["trace"],
                "tool_errors": task.get("tool_errors", []),
                "research": task.get("research", {}), "model_events": task.get("model_events", [])}

    @app.post("/api/tasks/{task_id}/resume", status_code=202)
    def resume(task_id: str, background_tasks: BackgroundTasks):
        task = app.state.runtime.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
        if task["status"] == "completed":
            raise HTTPException(status_code=409, detail="TASK_ALREADY_COMPLETED")
        background_tasks.add_task(app.state.runtime.run_task, task_id)
        return {"task_id": task_id, "status": "resume_requested"}

    return app


app = create_app()
