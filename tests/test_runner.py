"""Local ADK runtime smoke tests that do not call a model."""

import asyncio

from google.adk.apps import App
from google.adk.runners import InMemoryRunner

from prompt_improver.agent import root_agent


def test_runner_can_create_an_in_memory_session() -> None:
    async def create_session() -> str:
        app = App(name="prompt_improver_test", root_agent=root_agent)
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(
            app_name=app.name,
            user_id="test_user",
        )
        return session.id

    assert asyncio.run(create_session())
