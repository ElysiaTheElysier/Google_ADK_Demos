"""End-to-end prompt evaluation and improvement workflow."""

import os

from dotenv import load_dotenv
from google.adk import Workflow
from google.adk.agents import LlmAgent
from google.adk.workflow import START, JoinNode

from .schemas import CriterionEvaluation, FinalResult, PromptAnalysis

load_dotenv()

MODEL = os.getenv("ADK_MODEL", "gemini-3.5-flash-lite")

prompt_analyzer = LlmAgent(
    name="prompt_analyzer",
    model=MODEL,
    description="Extracts the goal, audience, context, constraints, and format from a prompt.",
    instruction="""
You analyze a user prompt without rewriting or scoring it.

Extract only information that is stated or can be safely inferred from the prompt:
- copy the complete user prompt exactly into original_prompt;
- inferred goal;
- target audience, or null when it is not identifiable;
- relevant context already provided;
- explicit constraints;
- requested output format, or null when none is requested;
- important missing information that would make the prompt more actionable.

Keep every list concise. Do not invent domain facts, requirements, or user preferences.
Return only the structured result required by the output schema.
""".strip(),
    output_schema=PromptAnalysis,
    output_key="prompt_analysis",
)


def _create_evaluator(
    *,
    name: str,
    criterion: str,
    focus: str,
) -> LlmAgent:
    """Create one small evaluator with the shared output contract."""

    return LlmAgent(
        name=name,
        model=MODEL,
        description=f"Evaluates prompt {criterion}.",
        instruction=f"""
You are the {criterion} evaluator in a prompt-review workflow.

The current input is a structured prompt analysis containing the original prompt.
Evaluate only this concern: {focus}

Return:
- criterion exactly as "{criterion}";
- an integer score from 1 (poor) to 5 (excellent);
- one to three concrete findings;
- up to three actionable suggestions.

Do not rewrite the prompt. Do not evaluate other criteria. Return only the structured result
required by the output schema. Write findings and suggestions in the same language as the
original prompt.
""".strip(),
        output_schema=CriterionEvaluation,
        include_contents="none",
    )


clarity_evaluator = _create_evaluator(
    name="clarity_evaluator",
    criterion="clarity",
    focus="Is the goal specific, unambiguous, and easy to understand?",
)

context_evaluator = _create_evaluator(
    name="context_evaluator",
    criterion="context",
    focus="Does the prompt provide enough background, audience, and domain context?",
)

constraints_evaluator = _create_evaluator(
    name="constraints_evaluator",
    criterion="constraints",
    focus="Are scope, boundaries, requirements, and success conditions explicit?",
)

format_evaluator = _create_evaluator(
    name="format_evaluator",
    criterion="output_format",
    focus="Does the prompt clearly specify the desired structure, style, and length?",
)

evaluation_join = JoinNode(name="evaluation_join")

final_reviewer = LlmAgent(
    name="final_reviewer",
    model=MODEL,
    description="Combines all evaluations and produces one improved prompt.",
    instruction="""
You are the final reviewer in a prompt-improvement workflow.

The current input is a mapping keyed by evaluator name. It contains four structured
evaluations. The original prompt and its analysis are available here:

{prompt_analysis}

Produce one final result:
- include all four evaluations exactly once;
- calculate an overall score as their arithmetic mean;
- summarize the most important weaknesses concisely;
- write one improved prompt that preserves the user's intent;
- list assumptions explicitly instead of inventing missing facts.

Use the same language as the original prompt for all free-text fields. Never choose an arbitrary
meaning for an ambiguous acronym or term. Preserve the ambiguity with a clear placeholder or
clarification request in the improved prompt.

Return only the structured result required by the output schema.
""".strip(),
    output_schema=FinalResult,
    include_contents="none",
)

# ADK compiles and validates this graph when the module is imported.
root_agent = Workflow(
    name="prompt_improvement_workflow",
    description="Analyzes, evaluates, and improves one user prompt.",
    edges=[
        (
            START,
            prompt_analyzer,
            (
                clarity_evaluator,
                context_evaluator,
                constraints_evaluator,
                format_evaluator,
            ),
            evaluation_join,
            final_reviewer,
        )
    ],
)
