"""Local ADK runtime smoke tests that do not call a model."""

import asyncio

from google.adk.apps import App
from google.adk.runners import InMemoryRunner

from prompt_improver.agent import (
    enriched_root_agent,
    promptify_validator_agent,
    root_agent,
)
from prompt_improver.tools import _normalize_wikipedia_query, resolve_promptify_topic
from ui_backend import _openai_fallback_agent


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


def test_default_workflow_excludes_context_enricher_while_enriched_includes_it() -> None:
    default_nodes = {node.name for node in root_agent.graph.nodes}
    enriched_nodes = {node.name for node in enriched_root_agent.graph.nodes}

    assert "context_enricher" not in default_nodes
    assert "context_enricher" in enriched_nodes
    assert "promptify_validator_agent" not in default_nodes
    assert "promptify_validator_agent" not in enriched_nodes
    assert promptify_validator_agent.name == "promptify_validator_agent"


def test_normalize_wikipedia_query_strips_meta_words_and_expands_acronyms() -> None:
    candidates = _normalize_wikipedia_query(
        "Verify origin of RAG using public sources"
    )
    assert candidates
    assert "retrieval-augmented generation" in candidates[0].lower()
    assert "verify" not in candidates[0].lower()


def test_resolve_promptify_topic_matches_prompt_intent() -> None:
    assert resolve_promptify_topic(
        "Explain retrieval-augmented generation and verify with search", "auto"
    ) == ("Lab 04: ReAct & Agentic Workflow", 3)
    assert resolve_promptify_topic(
        "Write a product launch blog post with clear context and target audience",
        "auto",
    ) == ("Lab 02: Context Engineering & Few-Shot", 1)


def test_openai_fallback_agent_replaces_all_llm_models_with_litellm() -> None:
    from google.adk.models.lite_llm import LiteLlm

    fallback_root, model_name = _openai_fallback_agent(enriched_root_agent)
    assert model_name.startswith("openai/")
    llm_nodes = [node for node in fallback_root.graph.nodes if hasattr(node, "model")]
    assert len(llm_nodes) == 8
    assert all(isinstance(node.model, LiteLlm) for node in llm_nodes)
