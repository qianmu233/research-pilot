"""Validated model contracts for enterprise research."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .schema import GroundedClaim, StructuredReport

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Detail = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubtaskSpec(Contract):
    objective: Detail
    scope: Detail
    dimensions: list[Label] = Field(min_length=1, max_length=8)
    constraints: list[Detail] = Field(max_length=4)
    queries: list[Query] = Field(min_length=1, max_length=2)


class SupervisorPlan(Contract):
    subtasks: list[SubtaskSpec] = Field(min_length=1, max_length=6)


class WorkerAssessment(Contract):
    conclusion: Detail
    source_ids: list[str] = Field(max_length=20)
    covered_dimensions: list[Label] = Field(max_length=8)
    open_questions: list[Detail] = Field(max_length=5)
    next_queries: list[Query] = Field(max_length=2)


class Followup(Contract):
    subtask_id: str
    reason: Detail
    queries: list[Query] = Field(min_length=1, max_length=2)


class ReviewDecision(Contract):
    sufficient: bool
    gaps: list[Detail] = Field(max_length=12)
    conflicts: list[Detail] = Field(max_length=8)
    followups: list[Followup] = Field(max_length=6)


class PassageConflict(Contract):
    first_quote_ref: str
    second_quote_ref: str
    description: Detail


class ReviewDraft(Contract):
    gaps: list[Detail] = Field(max_length=4)
    conflicts: list[PassageConflict] = Field(max_length=3)
    followups: list[Followup] = Field(max_length=4)
    sufficient: bool


class EnterpriseClaim(GroundedClaim):
    section: Literal["candidates", "comparison", "fit", "risks", "recommendation"]


class EnterpriseReport(StructuredReport):
    claims: list[EnterpriseClaim] = Field(max_length=8)


class PassageClaim(Contract):
    quote_ref: str
    text: Detail
    section: Literal["candidates", "comparison", "fit", "risks", "recommendation"]


class EnterpriseDraft(Contract):
    """Ollama wire contract. The model selects a specific quotation before writing each claim."""

    claims: list[PassageClaim] = Field(max_length=8)
    answer_status: Literal["answered", "insufficient_evidence"]
    title: Label
    limitations: list[Detail] = Field(min_length=1, max_length=5)
