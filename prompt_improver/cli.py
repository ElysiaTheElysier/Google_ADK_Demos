"""Minimal programmatic Runner for the complete prompt-improvement workflow."""

import argparse
import asyncio
import json
import os
import sys
import uuid

from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import root_agent
from .schemas import FinalResult

APP_NAME = "prompt_improver"
USER_ID = "demo_user"


def _ensure_authentication() -> None:
    """Fail early with an actionable message instead of a model-client error."""

    uses_vertex_ai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    has_api_key = bool(
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not uses_vertex_ai and not has_api_key:
        raise RuntimeError(
            "Missing GOOGLE_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY. Copy .env.example "
            "to .env and add your key, or configure Vertex AI authentication."
        )


def _openai_fallback_workflow(workflow: object) -> tuple[object, str]:
    """Clone the workflow graph and switch all LLM nodes to OpenAI via LiteLlm."""
    from google.adk.models.lite_llm import LiteLlm

    model_name = os.getenv("OPENAI_MODEL", "openai/gpt-4.1-mini")
    if not model_name.startswith("openai/"):
        model_name = f"openai/{model_name}"

    fallback_root = workflow.model_copy(deep=True)  # type: ignore[attr-defined]
    for node in fallback_root.graph.nodes:
        if hasattr(node, "model"):
            node.model = LiteLlm(model=model_name)
    return fallback_root, model_name


async def _run_workflow_once(prompt: str, workflow: object) -> FinalResult:
    app = App(name=APP_NAME, root_agent=workflow)  # type: ignore[arg-type]
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=str(uuid.uuid4()),
    )

    final_text: str | None = None
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=message,
    ):
        print(f"[event] author={event.author} final={event.is_final_response()}")
        if event.author == "final_reviewer" and event.is_final_response() and event.content:
            text_parts = [part.text for part in event.content.parts or [] if part.text]
            if text_parts:
                final_text = "".join(text_parts)

    if final_text is None:
        updated_session = await runner.session_service.get_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session.id,
        )
        state_result = (updated_session.state or {}).get("final_result") if updated_session else None
        if state_result is not None:
            return FinalResult.model_validate(state_result)
        raise RuntimeError("The workflow completed without a final text response.")

    return FinalResult.model_validate_json(final_text)


async def improve_prompt(prompt: str) -> FinalResult:
    """Run the complete workflow and parse its final structured response."""

    if not prompt.strip():
        raise ValueError("Prompt must not be empty.")

    _ensure_authentication()

    try:
        return await _run_workflow_once(prompt, root_agent)
    except Exception as exc:
        if not os.getenv("OPENAI_API_KEY"):
            raise
        fallback_workflow, fallback_model = _openai_fallback_workflow(root_agent)
        print(
            f"[fallback] Gemini failed ({exc}); retrying with {fallback_model}...",
            file=sys.stderr,
        )
        return await _run_workflow_once(prompt, fallback_workflow)


def main() -> None:
    # Windows may default to a legacy console encoding that cannot print Vietnamese output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Evaluate and improve one prompt with ADK.")
    parser.add_argument("prompt", help="The prompt to improve, wrapped in quotes.")
    args = parser.parse_args()

    result = asyncio.run(improve_prompt(args.prompt))
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
