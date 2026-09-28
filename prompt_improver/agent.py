"""The first vertical slice: one structured prompt-analysis agent."""

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent

from .schemas import PromptAnalysis

load_dotenv()

MODEL = os.getenv("ADK_MODEL", "gemini-flash-latest")

prompt_analyzer = LlmAgent(
    name="prompt_analyzer",
    model=MODEL,
    description="Extracts the goal, audience, context, constraints, and format from a prompt.",
    instruction="""
You analyze a user prompt without rewriting or scoring it.

Extract only information that is stated or can be safely inferred from the prompt:
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
)

# ADK CLI and web tooling discover this conventional module-level name.
# It is intentionally a single agent in the first milestone. A Workflow will replace it
# after the analyzer and one evaluator have both been verified independently.
root_agent = prompt_analyzer
