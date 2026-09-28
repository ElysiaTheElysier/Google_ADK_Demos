"""Structured contracts shared by the prompt-improvement workflow."""

from typing import Literal

from pydantic import BaseModel, Field


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


class FinalResult(BaseModel):
    """The final report produced after all evaluator branches finish."""

    overall_score: float = Field(ge=1, le=5)
    summary: str = Field(min_length=1)
    evaluations: list[CriterionEvaluation] = Field(min_length=4, max_length=4)
    improved_prompt: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
