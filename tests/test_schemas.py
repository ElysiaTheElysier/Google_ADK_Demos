"""Deterministic tests for data passed between agents."""

import pytest
from pydantic import ValidationError

from prompt_improver.schemas import CriterionEvaluation, FinalResult, PromptAnalysis


def test_prompt_analysis_defaults_optional_information() -> None:
    analysis = PromptAnalysis(inferred_goal="Summarize a technical article")

    assert analysis.target_audience is None
    assert analysis.detected_context == []
    assert analysis.detected_constraints == []
    assert analysis.requested_output_format is None
    assert analysis.missing_information == []


@pytest.mark.parametrize("score", [1, 5])
def test_criterion_evaluation_accepts_score_boundaries(score: int) -> None:
    evaluation = CriterionEvaluation(
        criterion="clarity",
        score=score,
        findings=["The requested action is explicit."],
    )

    assert evaluation.score == score


@pytest.mark.parametrize("score", [0, 6])
def test_criterion_evaluation_rejects_score_outside_range(score: int) -> None:
    with pytest.raises(ValidationError):
        CriterionEvaluation(
            criterion="clarity",
            score=score,
            findings=["Finding"],
        )


def test_criterion_evaluation_limits_findings_to_three() -> None:
    with pytest.raises(ValidationError):
        CriterionEvaluation(
            criterion="context",
            score=3,
            findings=["One", "Two", "Three", "Four"],
        )


def test_final_result_serialization_round_trip() -> None:
    result = FinalResult(
        overall_score=4.0,
        summary="The prompt is clear but needs an explicit output format.",
        evaluations=[
            CriterionEvaluation(
                criterion="output_format",
                score=3,
                findings=["No output format is requested."],
                suggestions=["Request a concise Markdown list."],
            )
        ],
        improved_prompt="Summarize the article as five concise Markdown bullets.",
    )

    restored = FinalResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PromptAnalysis(inferred_goal="Explain ADK", unexpected="not allowed")
