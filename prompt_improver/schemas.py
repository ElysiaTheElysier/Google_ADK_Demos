"""Structured contracts shared by the prompt-improvement workflow."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PromptAnalysis(BaseModel):
    """A factual inventory of information present in the user's prompt."""

    original_prompt: str = Field(min_length=1)
    inferred_goal: str = Field(min_length=1)
    target_audience: str | None = None
    detected_context: list[str] = Field(default_factory=list)
    detected_constraints: list[str] = Field(default_factory=list)
    requested_output_format: str | None = None
    missing_information: list[str] = Field(default_factory=list)


class CriterionEvaluation(BaseModel):
    """The result produced by one specialized evaluator."""

    criterion: Literal["clarity", "context", "constraints", "output_format"]
    score: int = Field(ge=1, le=5)
    findings: list[str] = Field(min_length=1, max_length=3)
    suggestions: list[str] = Field(default_factory=list, max_length=3)


class ContextSource(BaseModel):
    title: str
    url: str
    fact: str


class ResearchDecision(BaseModel):
    """Structured routing decision made before any external request."""

    needs_search: bool
    reason: str = Field(min_length=1)
    search_query: str | None = None


class ContextEnrichment(BaseModel):
    """Optional public context gathered by an agent through a tool call."""
    used_search: bool
    search_query: str | None = None
    useful_context: list[str] = Field(default_factory=list, max_length=3)
    sources: list[ContextSource] = Field(default_factory=list, max_length=3)
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_sources_for_external_facts(self) -> "ContextEnrichment":
        """A successful research result must keep evidence attached."""
        if self.used_search and not self.sources:
            raise ValueError("used_search=true requires at least one sourced fact")
        return self


class FinalResult(BaseModel):
    """The final report produced after all evaluator branches finish."""

    overall_score: float = Field(ge=1, le=5)
    summary: str = Field(min_length=1)
    evaluations: list[CriterionEvaluation] = Field(min_length=4, max_length=4)
    improved_prompt: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_overall_score(self) -> "FinalResult":
        """Make the aggregate deterministic instead of trusting LLM arithmetic."""
        self.overall_score = round(
            sum(evaluation.score for evaluation in self.evaluations)
            / len(self.evaluations),
            2,
        )
        return self


class ExternalValidationResult(BaseModel):
    """Result returned by the optional Phase 3 Promptify Validator agent."""

    status: Literal[
        "login_required",
        "running",
        "completed",
        "failed",
    ]
    submitted_prompt: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0, le=10)
    feedback: list[str] = Field(default_factory=list)
    result_url: str | None = None

