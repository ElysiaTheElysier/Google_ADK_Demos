"""Minimal programmatic Runner example for the prompt analyzer."""

import argparse
import asyncio
import json
import os
import uuid

from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import root_agent
from .schemas import PromptAnalysis

APP_NAME = "prompt_improver"
USER_ID = "demo_user"


def _ensure_authentication() -> None:
    """Fail early with an actionable message instead of a model-client error."""

    uses_vertex_ai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    if not uses_vertex_ai and not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError(
            "Missing GOOGLE_API_KEY. Copy .env.example to .env and add your key, "
            "or configure Vertex AI authentication."
        )


async def analyze_prompt(prompt: str) -> PromptAnalysis:
    """Run one analyzer turn and parse its final structured response."""

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
        raise RuntimeError("The analyzer completed without a final text response.")

    return PromptAnalysis.model_validate_json(final_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze one prompt with Google ADK.")
    parser.add_argument("prompt", help="The prompt to analyze, wrapped in quotes.")
    args = parser.parse_args()

    result = asyncio.run(analyze_prompt(args.prompt))
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
