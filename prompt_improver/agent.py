"""End-to-end prompt evaluation and improvement workflow."""

import os

from dotenv import load_dotenv
from google.adk import Workflow
from google.adk.agents import LlmAgent
from google.adk.workflow import START, JoinNode

from .schemas import (
    ContextEnrichment,
    CriterionEvaluation,
    ExternalValidationResult,
    FinalResult,
    PromptAnalysis,
)
from .tools import (
    search_public_context,
    validate_context_enrichment_tool_call,
    validate_promptify_tool_call,
    validate_with_promptify,
)

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

Use the structured prompt analysis below as the only prompt being evaluated:

{{prompt_analysis}}

Evaluate only this concern: {focus}

Return:
- criterion exactly as "{criterion}";
- an integer score using these fixed anchors:
  1 = the criterion is missing or unusable;
  2 = it is mentioned but too vague to act on;
  3 = it is usable at a basic level but has important ambiguity;
  4 = it is clear and actionable with only minor gaps;
  5 = it is complete, specific, and requires no material guessing;
- one to three concrete findings;
- up to three actionable suggestions.

Judge only information present in the prompt. Do not reward fluent wording when required
information is absent. Do not rewrite the prompt. Do not evaluate other criteria. Return only
the structured result required by the output schema. Write findings and suggestions in the
same language as the original prompt.
""".strip(),
        output_schema=CriterionEvaluation,
        output_key=f"{criterion}_evaluation",
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

context_enricher = LlmAgent(
    name="context_enricher",
    model=MODEL,
    description="Decides whether public context is needed and calls search_public_context when helpful.",
    instruction="""
You are the context enrichment agent in a prompt-improvement workflow.

Inspect the analyzed prompt below:

{prompt_analysis}

Decide whether public factual context from Wikipedia would help improve or ground this prompt:
1. CALL `search_public_context` (at most once) when:
   - the prompt asks to search, verify facts, provide public sources, citations, or links, or cover origins/history/timelines; OR
   - the prompt is about a real-world public topic, technology, scientific concept, historical event, or public entity (even when phrased as "Write a guide/explainer/article about...").
2. DO NOT call `search_public_context` (set `used_search=false`, `search_query=null`, `useful_context=[]`, `sources=[]`) when:
   - the prompt explicitly forbids adding external information (e.g., "do not add external information", "keep all facts exactly as provided", "do not invent pricing or availability dates"); OR
   - the prompt is purely about a private/internal/fictional product or announcement (such as "Remi") or is too generic to name any public topic (such as "Write something good about our new app").

When calling `search_public_context`:
- Pass a short canonical English topic name (1 to 4 words), expanding acronyms (for example, use "Retrieval-augmented generation" instead of "RAG", and omit words like "origin", "verify", "guide", or "explainer").
- After receiving tool results, set `used_search=true`, set `search_query` to the query used, extract 1 to 3 concise factual points into `useful_context`, and populate `sources` using only the titles, URLs, and facts returned by the tool.
- Write `useful_context` and `note` in the same language as `original_prompt`.
""".strip(),
    tools=[search_public_context],
    before_tool_callback=validate_context_enrichment_tool_call,
    output_schema=ContextEnrichment,
    output_key="context_enrichment",
    include_contents="none",
)

evaluation_join = JoinNode(name="evaluation_join")

final_reviewer = LlmAgent(
    name="final_reviewer",
    model=MODEL,
    description="Combines all evaluations and produces one improved prompt.",
    instruction="""
You are the final reviewer in a prompt-improvement workflow.

The current input contains four evaluations and may also contain context_enrichment.
The original prompt and its analysis are available here:

{prompt_analysis}

Available external context (if any):
{context_enrichment?}

Produce one final result:
- include all four evaluations exactly once;
- include an overall score field; the application recalculates it as the arithmetic mean;
- summarize the most important weaknesses concisely;
- write one improved prompt that preserves the user's intent;
- list assumptions explicitly instead of inventing missing facts.

External context may improve the rewrite (for example, by grounding the improved prompt with
verified background facts and source URLs when helpful), but must not change the four scores:
those scores describe the original prompt. Never turn a search result into an unrelated user
requirement.

Use the same language as the original prompt for all free-text fields. Never choose an arbitrary
meaning for an ambiguous acronym or term. Preserve the ambiguity with a clear placeholder or
clarification request in the improved prompt.

Return only the structured result required by the output schema.
""".strip(),
    output_schema=FinalResult,
    output_key="final_result",
    include_contents="none",
)

response_generator = LlmAgent(
    name="response_generator",
    model=MODEL,
    description="Executes the improved prompt and returns the final user-facing answer.",
    instruction="""
The completed review is below:

{final_result}

Verified external context (if any):
{context_enrichment?}

The improved_prompt field is an instruction for you to execute now. Follow that instruction and
produce the requested artifact or answer. When verified external sources are provided above and
relevant to the prompt, incorporate those grounded facts and include the source links. Do not
repeat or rewrite the prompt itself. Do not discuss evaluation scores, workflow internals, or how
the prompt was improved. Return only the final user-facing answer.
""".strip(),
    output_key="generated_response",
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
            response_generator,
        )
    ],
)

# Context enricher and its search tool are unreachable unless explicitly enabled by the caller.
enriched_root_agent = Workflow(
    name="prompt_improvement_with_research_workflow",
    description="Evaluates a prompt and optionally enriches it with public context.",
    edges=[
        (
            START,
            prompt_analyzer,
            (
                clarity_evaluator,
                context_evaluator,
                constraints_evaluator,
                format_evaluator,
                context_enricher,
            ),
            evaluation_join,
            final_reviewer,
            response_generator,
        )
    ],
)

# Phase 3: Standalone external validation agent invoked only on explicit user action.
promptify_validator_agent = LlmAgent(
    name="promptify_validator_agent",
    model=MODEL,
    description="Validates an improved prompt against the external Promptify web application.",
    instruction="""
You are the external validation agent for the Prompt Improver system.

The user wants to validate the following improved prompt on Promptify:

Prompt to validate:
{submitted_prompt}

Requested topic (or "auto"):
{requested_topic}

Follow these steps strictly:
1. Call `validate_with_promptify(prompt=..., topic=...)` passing the exact `submitted_prompt` and `requested_topic`.
2. Return the exact `status`, `submitted_prompt`, `topic`, `score`, `feedback`, and `result_url` returned by the tool without inventing or modifying scores.
""".strip(),
    tools=[validate_with_promptify],
    before_tool_callback=validate_promptify_tool_call,
    output_schema=ExternalValidationResult,
    output_key="external_validation",
    include_contents="none",
)

