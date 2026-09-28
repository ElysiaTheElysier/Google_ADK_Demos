"""Deterministic tests for data passed between agents."""

import pytest
from pydantic import ValidationError

from prompt_improver.schemas import (
    ContextEnrichment,
    ContextSource,
    CriterionEvaluation,
    ExternalValidationResult,
    FinalResult,
    PromptAnalysis,
)


def test_prompt_analysis_defaults_optional_information() -> None:
    analysis = PromptAnalysis(
        original_prompt="Summarize this article.",
        inferred_goal="Summarize a technical article",
    )

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


def test_context_enrichment_requires_sources_when_search_is_used() -> None:
    with pytest.raises(ValidationError):
        ContextEnrichment(
            used_search=True,
            search_query="Retrieval-augmented generation",
            useful_context=["RAG combines retrieval with generation."],
            sources=[],
            note="Searched public context.",
        )

    valid = ContextEnrichment(
        used_search=True,
        search_query="Retrieval-augmented generation",
        useful_context=["RAG combines retrieval with generation."],
        sources=[
            ContextSource(
                title="Retrieval-augmented generation",
                url="https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
                fact="RAG combines retrieval with generation.",
            )
        ],
        note="Searched public context.",
    )
    assert valid.used_search is True
    assert len(valid.sources) == 1


def test_final_result_serialization_round_trip() -> None:
    evaluations = [
        CriterionEvaluation(
            criterion=criterion,
            score=3,
            findings=["The criterion needs improvement."],
            suggestions=["Add a concrete requirement."],
        )
        for criterion in ("clarity", "context", "constraints", "output_format")
    ]
    result = FinalResult(
        overall_score=4.0,
        summary="The prompt is clear but needs an explicit output format.",
        evaluations=evaluations,
        improved_prompt="Summarize the article as five concise Markdown bullets.",
    )

    restored = FinalResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert restored.overall_score == 3.0


def test_external_validation_result_schema() -> None:
    completed = ExternalValidationResult(
        status="completed",
        submitted_prompt="Explain RAG to a junior engineer.",
        topic="Giải thích một khái niệm kỹ thuật cho người mới",
        score=8.5,
        feedback=["Good structure.", "Clear target audience."],
        result_url="https://promptify-wheat-seven.vercel.app/",
    )
    assert completed.score == 8.5

    login_needed = ExternalValidationResult(
        status="login_required",
        submitted_prompt="Explain RAG to a junior engineer.",
        topic="Giải thích một khái niệm kỹ thuật cho người mới",
        score=None,
        feedback=["Complete Google login in the opened browser window."],
        result_url="https://promptify-wheat-seven.vercel.app/",
    )
    assert login_needed.score is None
