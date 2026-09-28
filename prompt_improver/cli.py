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
    has_api_key = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    if not uses_vertex_ai and not has_api_key:
        raise RuntimeError(
            "Missing GOOGLE_API_KEY or GEMINI_API_KEY. Copy .env.example to .env and "
            "add your key, or configure Vertex AI authentication."
        )


async def improve_prompt(prompt: str) -> FinalResult:
    """Run the complete workflow and parse its final structured response."""

    if not prompt.strip():
        raise ValueError("Prompt must not be empty.")

    _ensure_authentication()

    app = App(name=APP_NAME, root_agent=root_agent)
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
        if event.is_final_response() and event.content:
            text_parts = [part.text for part in event.content.parts or [] if part.text]
            if text_parts:
                final_text = "".join(text_parts)

    if final_text is None:
        raise RuntimeError("The workflow completed without a final text response.")

    return FinalResult.model_validate_json(final_text)


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
