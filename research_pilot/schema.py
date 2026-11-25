"""Explicit schemas for user inputs and research output."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateTask(BaseModel):
    question: str = Field(min_length=8, max_length=2000)
    scope: str = Field(default="", max_length=500)
    mode: Literal["single", "multi"] = "single"


class IngestText(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=20, max_length=200_000)
    source_ref: str = Field(default="local-document", max_length=200)


class Evidence(BaseModel):
    source_id: str
    title: str
    locator: str
    excerpt: str
    source_type: Literal["local", "external"]
    retrieved_at: str
    query: str
    document_id: str | None = None
    chunk_id: str | None = None
    source_ref: str | None = None
    score: float | None = None


class SubtaskView(BaseModel):
    task_id: str
    subtask_id: str
    objective: str
    scope: str
    dimensions: list[str]
    constraints: list[str]
    initial_queries: list[str]
    queries: list[str]
    status: Literal["pending", "running", "completed", "insufficient", "failed", "timed_out"]
    generation: int
    attempts: int
    total_attempts: int = 0
    failures: list[dict] = Field(default_factory=list)
    retrieval_rounds: int
    rounds: list[dict]
    sources: list[Evidence]
    model_calls: int
    started_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    conclusion: str | None = None
    covered_dimensions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    supplement: dict | None = None


class MultiProgress(BaseModel):
    phase: str
    subtask_count: int
    completed_subtask_count: int
    settled_subtask_count: int
    evidence_count: int
    report_source_count: int
    model_calls: int
    supplemented_subtask_count: int
    report_status: Literal["pending", "completed", "failed"]
    quality: Literal["full", "partial", "insufficient", "invalid"] | None = None
    subtasks: list[SubtaskView]


class TaskView(BaseModel):
    id: str
    question: str
    scope: str
    status: Literal["pending", "running", "completed", "failed", "interrupted", "timed_out"]
    phase: str
    created_at: str
    updated_at: str
    error_code: str | None = None
    report: str | None = None
    sources: list[Evidence] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    tool_errors: list[str] = Field(default_factory=list)
    evidence_status: Literal["unassessed", "no_evidence", "unverified"] = "unassessed"
    research: dict = Field(default_factory=dict)
    model_calls: int = 0
    model_events: list[dict] = Field(default_factory=list)
    mode: Literal["single", "multi"] = "single"
    progress: MultiProgress | None = None


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1, max_length=300)
    questions: list[str] = Field(min_length=1, max_length=3)
    queries: list[str] = Field(min_length=1, max_length=2)


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sufficient: bool
    reason: str = Field(min_length=1, max_length=600)
    source_ids: list[str] = Field(max_length=10)
    missing_information: list[str] = Field(max_length=4)
    next_queries: list[str] = Field(max_length=2)


class GroundedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    source_id: str
    quote: str = Field(min_length=1, max_length=400)


class StructuredReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    answer_status: Literal["answered", "insufficient_evidence"]
    claims: list[GroundedClaim] = Field(max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=5)
