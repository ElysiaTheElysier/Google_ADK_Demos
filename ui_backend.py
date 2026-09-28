"""Thin HTTP/SSE-like streaming layer for the existing ADK workflow.

Run with: uvicorn ui_backend:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

from prompt_improver.agent import (
    enriched_root_agent,
    promptify_validator_agent,
    root_agent,
)
from prompt_improver.schemas import ExternalValidationResult

LLM_AGENT_NAMES = (
    "prompt_analyzer",
    "clarity_evaluator",
    "context_evaluator",
    "constraints_evaluator",
    "format_evaluator",
    "context_enricher",
    "final_reviewer",
    "response_generator",
)


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    enable_research: bool = False


class ValidateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    topic: str = Field(default="auto", min_length=1, max_length=200)



app = FastAPI(title="ADK Prompt Improver API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _line(event: str, data: dict[str, Any]) -> bytes:
    return (json.dumps({"event": event, "data": data}, default=str) + "\n").encode()


async def _events_with_idle_timeout(source: Any, timeout_seconds: float) -> AsyncIterator[Any]:
    """Stop a run when ADK produces no event for too long.

    This is an inactivity timeout, not a limit on the whole workflow. A healthy
    long run may continue as long as events keep arriving.
    """
    iterator = source.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(iterator.__anext__(), timeout=timeout_seconds)
        except StopAsyncIteration:
            return


def _workflow_with_temperature(workflow: Any, temperature: float) -> Any:
    """Clone a workflow and apply one run-scoped sampling temperature."""
    configured = workflow.model_copy(deep=True)
    for node in configured.graph.nodes:
        if hasattr(node, "model"):
            node_temperature = 0.0 if node.name == "context_enricher" else temperature
            current = getattr(node, "generate_content_config", None)
            if current is None:
                node.generate_content_config = types.GenerateContentConfig(
                    temperature=node_temperature
                )
            else:
                node.generate_content_config = current.model_copy(
                    update={"temperature": node_temperature}
                )
    return configured


def _openai_fallback_agent(workflow: Any) -> tuple[Any, str]:
    """Clone the current graph and replace only the LLM models."""
    from google.adk.models.lite_llm import LiteLlm

    model_name = os.getenv("OPENAI_MODEL", "openai/gpt-4.1-mini")
    if not model_name.startswith("openai/"):
        model_name = f"openai/{model_name}"

    fallback_root = workflow.model_copy(deep=True)
    agents_by_name = {
        node.name: node
        for node in fallback_root.graph.nodes
        if hasattr(node, "model")
    }
    for name in LLM_AGENT_NAMES:
        agent = agents_by_name.get(name)
        if agent is not None:
            agent.model = LiteLlm(model=model_name)
    return fallback_root, model_name


def _text(event: Any) -> str | None:
    content = getattr(event, "content", None)
    if not content:
        return None
    parts = getattr(content, "parts", None) or []
    texts = [part.text for part in parts if getattr(part, "text", None)]
    return "\n".join(texts) or None


def _usage(event: Any) -> dict[str, int]:
    usage = getattr(event, "usage_metadata", None)
    if not usage:
        return {"input": 0, "output": 0, "total": 0}
    return {
        "input": int(getattr(usage, "prompt_token_count", 0) or 0),
        "output": int(getattr(usage, "candidates_token_count", 0) or 0),
        "total": int(getattr(usage, "total_token_count", 0) or 0),
    }


def _metadata(event: Any) -> dict[str, Any]:
    tool_calls: list[dict[str, Any]] = []
    content = getattr(event, "content", None)
    for part in getattr(content, "parts", None) or []:
        call = getattr(part, "function_call", None)
        response = getattr(part, "function_response", None)
        if call and getattr(call, "name", None) != "set_model_response":
            tool_calls.append(
                {
                    "phase": "call",
                    "name": getattr(call, "name", None),
                    "args": getattr(call, "args", None),
                }
            )
        if response and getattr(response, "name", None) != "set_model_response":
            tool_calls.append(
                {
                    "phase": "response",
                    "name": getattr(response, "name", None),
                    "response": getattr(response, "response", None),
                }
            )
    return {
        "id": getattr(event, "id", None),
        "invocationId": getattr(event, "invocation_id", None),
        "branch": getattr(event, "branch", None),
        "timestamp": getattr(event, "timestamp", None),
        "partial": getattr(event, "partial", None),
        "turnComplete": getattr(event, "turn_complete", None),
        "tools": tool_calls,
    }


def _state_output(event: Any, author: str) -> Any | None:
    """Read structured output written by an LlmAgent through output_key.

    Depending on the ADK/model response shape, the useful structured payload may
    be present in actions.state_delta even when the event has no text part.
    """
    actions = getattr(event, "actions", None)
    delta = getattr(actions, "state_delta", None) if actions else None
    if not delta:
        return None
    preferred = {
        "prompt_analyzer": "prompt_analysis",
        "clarity_evaluator": "clarity_evaluation",
        "context_evaluator": "context_evaluation",
        "constraints_evaluator": "constraints_evaluation",
        "format_evaluator": "output_format_evaluation",
        "context_enricher": "context_enrichment",
        "final_reviewer": "final_result",
        "response_generator": "generated_response",
        "promptify_validator_agent": "external_validation",
    }.get(author)
    if preferred and preferred in delta:
        return delta[preferred]
    values = [v for k, v in delta.items() if not str(k).startswith("temp:")]
    return values[0] if len(values) == 1 else None


async def _stream(
    prompt: str,
    *,
    workflow_agent: Any = root_agent,
    model_name: str | None = None,
    allow_fallback: bool = True,
    temperature: float = 0.0,
    research_enabled: bool = False,
) -> AsyncIterator[bytes]:
    session_id = str(uuid.uuid4())
    user_id = "ui-demo"
    model = model_name or os.getenv("ADK_MODEL", "gemini-3.5-flash-lite")
    runner = InMemoryRunner(app=App(name="prompt_improver_ui", root_agent=workflow_agent))
    started = time.perf_counter()
    idle_timeout = float(os.getenv("ADK_EVENT_TIMEOUT_SECONDS", "60"))
    totals = {"input": 0, "output": 0, "total": 0, "calls": 0}
    completed: set[str] = set()
    branch_nodes = [
        "clarity_evaluator",
        "context_evaluator",
        "constraints_evaluator",
        "format_evaluator",
    ] + (["context_enricher"] if research_enabled else [])
    branch_outputs: dict[str, Any] = {}
    node_usage: dict[str, dict[str, int]] = {}
    node_tools: dict[str, list[dict[str, Any]]] = {}

    await runner.session_service.create_session(
        app_name="prompt_improver_ui", user_id=user_id, session_id=session_id
    )
    yield _line(
        "run.started",
        {
            "sessionId": session_id,
            "model": model,
            "temperature": temperature,
            "researchEnabled": research_enabled,
        },
    )
    yield _line("node.started", {"node": "user", "at": time.time(), "input": prompt})
    yield _line("node.completed", {"node": "user", "at": time.time(), "duration": 0})
    yield _line("node.started", {"node": "prompt_analyzer", "at": time.time(), "input": prompt})

    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    try:
        async for event in _events_with_idle_timeout(
            runner.run_async(
                user_id=user_id, session_id=session_id, new_message=message
            ),
            idle_timeout,
        ):
            author = getattr(event, "author", None) or "runner"
            text = _text(event)
            state_output = _state_output(event, author)
            usage = _usage(event)
            if usage["total"]:
                totals["calls"] += 1
                for key in ("input", "output", "total"):
                    totals[key] += usage[key]
                accum = node_usage.setdefault(author, {"input": 0, "output": 0, "total": 0})
                for key in ("input", "output", "total"):
                    accum[key] += usage[key]

            meta = _metadata(event)
            if meta["tools"]:
                node_tools.setdefault(author, []).extend(meta["tools"])
            if author in node_tools:
                meta["tools"] = list(node_tools[author])

            effective_usage = node_usage.get(author, usage)

            yield _line(
                "adk.event",
                {
                    "node": author,
                    "at": getattr(event, "timestamp", None) or time.time(),
                    "text": text,
                    "stateOutput": state_output,
                    "usage": effective_usage,
                    "metadata": meta,
                },
            )

            is_final = bool(getattr(event, "is_final_response", lambda: True)())
            raw_output = state_output if state_output is not None else text
            if author not in completed and raw_output is not None and (is_final or state_output is not None):
                completed.add(author)
                parsed_output: Any = raw_output
                try:
                    parsed_output = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
                except (TypeError, json.JSONDecodeError):
                    pass
                if author in branch_nodes:
                    branch_outputs[author] = parsed_output
                yield _line(
                    "node.completed",
                    {
                        "node": author,
                        "at": time.time(),
                        "output": parsed_output,
                        "usage": effective_usage,
                        "metadata": meta,
                    },
                )
                if author == "prompt_analyzer":
                    for node in branch_nodes:
                        yield _line(
                            "node.started",
                            {"node": node, "at": time.time(), "input": parsed_output},
                        )
                elif author in branch_nodes and all(node in completed for node in branch_nodes):
                    joined_at = time.time()
                    completed.add("evaluation_join")
                    yield _line(
                        "node.started",
                        {"node": "evaluation_join", "at": joined_at, "input": branch_outputs},
                    )
                    yield _line(
                        "node.completed",
                        {"node": "evaluation_join", "at": time.time(), "output": branch_outputs},
                    )
                    yield _line(
                        "node.started",
                        {"node": "final_reviewer", "at": time.time(), "input": branch_outputs},
                    )
                elif author == "final_reviewer":
                    yield _line(
                        "node.started",
                        {"node": "response_generator", "at": time.time(), "input": parsed_output},
                    )

        session = await runner.session_service.get_session(
            app_name="prompt_improver_ui", user_id=user_id, session_id=session_id
        )
        final_state = dict(getattr(session, "state", {}) or {})
        state_keys = {
            "prompt_analyzer": "prompt_analysis",
            "clarity_evaluator": "clarity_evaluation",
            "context_evaluator": "context_evaluation",
            "constraints_evaluator": "constraints_evaluation",
            "format_evaluator": "output_format_evaluation",
            "context_enricher": "context_enrichment",
        }
        for node, key in state_keys.items():
            if node not in completed and key in final_state:
                completed.add(node)
                if node in branch_nodes:
                    branch_outputs[node] = final_state[key]
                yield _line(
                    "node.completed",
                    {"node": node, "at": time.time(), "output": final_state[key]},
                )

        required_branch_keys = {
            node: state_keys[node] for node in branch_nodes if node in state_keys
        }
        if (
            "evaluation_join" not in completed
            and all(key in final_state for key in required_branch_keys.values())
        ):
            joined_output = {
                node: final_state[key]
                for node, key in required_branch_keys.items()
            }
            joined_at = time.time()
            completed.add("evaluation_join")
            yield _line(
                "node.started",
                {
                    "node": "evaluation_join",
                    "at": joined_at,
                    "input": joined_output,
                },
            )
            yield _line(
                "node.completed",
                {
                    "node": "evaluation_join",
                    "at": time.time(),
                    "output": joined_output,
                },
            )

        if "final_reviewer" not in completed and "final_result" in final_state:
            completed.add("final_reviewer")
            yield _line(
                "node.completed",
                {
                    "node": "final_reviewer",
                    "at": time.time(),
                    "output": final_state["final_result"],
                },
            )
        if "response_generator" not in completed and "generated_response" in final_state:
            completed.add("response_generator")
            yield _line(
                "node.completed",
                {
                    "node": "response_generator",
                    "at": time.time(),
                    "output": final_state["generated_response"],
                },
            )
        yield _line(
            "run.completed",
            {
                "sessionId": session_id,
                "duration": time.perf_counter() - started,
                "usage": totals,
                "state": final_state,
            },
        )
    except Exception as exc:  # noqa: BLE001
        reason = (
            f"No Gemini event was received for {idle_timeout:.0f}s."
            if isinstance(exc, TimeoutError)
            else f"Gemini unavailable ({exc})."
        )
        if allow_fallback and os.getenv("OPENAI_API_KEY"):
            try:
                fallback_agent, fallback_model = _openai_fallback_agent(workflow_agent)
                yield _line(
                    "run.fallback",
                    {
                        "fromModel": model,
                        "toModel": fallback_model,
                        "reason": reason,
                    },
                )
                async for chunk in _stream(
                    prompt,
                    workflow_agent=fallback_agent,
                    model_name=fallback_model,
                    allow_fallback=False,
                    temperature=temperature,
                    research_enabled=research_enabled,
                ):
                    yield chunk
                return
            except Exception as fallback_error:  # noqa: BLE001
                yield _line(
                    "run.failed",
                    {
                        "sessionId": session_id,
                        "duration": time.perf_counter() - started,
                        "error": f"Gemini failed ({exc}) and OpenAI fallback could not complete: {fallback_error}",
                    },
                )
                return
        yield _line(
            "run.failed",
            {
                "sessionId": session_id,
                "duration": time.perf_counter() - started,
                "error": (
                    f"{reason} OPENAI_API_KEY is not configured, so fallback is unavailable."
                    if isinstance(exc, TimeoutError)
                    else str(exc)
                ),
            },
        )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/runs")
async def run_workflow(request: RunRequest) -> StreamingResponse:
    selected = enriched_root_agent if request.enable_research else root_agent
    workflow = _workflow_with_temperature(selected, request.temperature)
    return StreamingResponse(
        _stream(
            request.prompt,
            workflow_agent=workflow,
            temperature=request.temperature,
            research_enabled=request.enable_research,
        ),
        media_type="application/x-ndjson",
    )


async def _stream_validation(
    prompt: str, topic: str, *, allow_fallback: bool = True, use_openai: bool = False
) -> AsyncIterator[bytes]:
    """Run the standalone Phase 3 promptify_validator_agent and stream events."""
    from prompt_improver.tools import _PROMPTIFY_MANAGER

    session_id = str(uuid.uuid4())
    user_id = "ui-demo"
    started = time.perf_counter()
    validator = promptify_validator_agent.model_copy(deep=True)
    validator.generate_content_config = types.GenerateContentConfig(temperature=0.0)
    if use_openai:
        from google.adk.models.lite_llm import LiteLlm

        openai_model = os.getenv("OPENAI_MODEL", "openai/gpt-4.1-mini")
        if not openai_model.startswith("openai/"):
            openai_model = f"openai/{openai_model}"
        validator.model = LiteLlm(model=openai_model)

    runner = InMemoryRunner(
        app=App(name="prompt_improver_validator", root_agent=validator)
    )
    await runner.session_service.create_session(
        app_name="prompt_improver_validator",
        user_id=user_id,
        session_id=session_id,
        state={"submitted_prompt": prompt, "requested_topic": topic},
    )

    if not use_openai:
        yield _line(
            "validation.started",
            {
                "sessionId": session_id,
                "node": "promptify_validator_agent",
                "at": time.time(),
                "input": {"prompt": prompt, "topic": topic},
            },
        )

    node_usage = {"input": 0, "output": 0, "total": 0}
    node_tools: list[dict[str, Any]] = []
    final_payload: dict[str, Any] | None = None
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=f"Validate this prompt on Promptify under topic '{topic}'."
            )
        ],
    )

    try:
        async for event in _events_with_idle_timeout(
            runner.run_async(
                user_id=user_id, session_id=session_id, new_message=message
            ),
            200.0,
        ):
            author = getattr(event, "author", None) or "promptify_validator_agent"
            text = _text(event)
            state_output = _state_output(event, author)
            usage = _usage(event)
            for key in ("input", "output", "total"):
                node_usage[key] += usage[key]
            meta = _metadata(event)
            if meta["tools"]:
                node_tools.extend(meta["tools"])
                for tool_item in meta["tools"]:
                    if (
                        tool_item.get("phase") == "response"
                        and tool_item.get("name") == "validate_with_promptify"
                        and isinstance(tool_item.get("response"), dict)
                    ):
                        final_payload = dict(tool_item["response"])
            meta["tools"] = list(node_tools)

            yield _line(
                "adk.event",
                {
                    "node": "promptify_validator_agent",
                    "at": getattr(event, "timestamp", None) or time.time(),
                    "text": text,
                    "stateOutput": state_output,
                    "usage": dict(node_usage),
                    "metadata": meta,
                },
            )
            if state_output is not None:
                parsed = (
                    json.loads(state_output)
                    if isinstance(state_output, str)
                    else state_output
                )
                if isinstance(parsed, dict):
                    final_payload = parsed

        session = await runner.session_service.get_session(
            app_name="prompt_improver_validator",
            user_id=user_id,
            session_id=session_id,
        )
        session_state = dict(getattr(session, "state", {}) or {})
        if final_payload is None:
            raw_ext = session_state.get("external_validation") or session_state.get(
                "temp:promptify_result"
            )
            if isinstance(raw_ext, str):
                raw_ext = json.loads(raw_ext)
            if isinstance(raw_ext, dict):
                final_payload = raw_ext
    except Exception as exc:  # noqa: BLE001
        if final_payload is None and allow_fallback and os.getenv("OPENAI_API_KEY"):
            openai_model = os.getenv("OPENAI_MODEL", "openai/gpt-4.1-mini")
            if not openai_model.startswith("openai/"):
                openai_model = f"openai/{openai_model}"
            yield _line(
                "run.fallback",
                {
                    "fromModel": os.getenv("ADK_MODEL", "gemini-3.5-flash-lite"),
                    "toModel": openai_model,
                    "reason": f"Gemini unavailable during Promptify validation ({exc}).",
                    "scope": "validation",
                },
            )
            async for chunk in _stream_validation(
                prompt, topic, allow_fallback=False, use_openai=True
            ):
                yield chunk
            return
        if final_payload is None:
            final_payload = await asyncio.to_thread(
                _PROMPTIFY_MANAGER.run, prompt, topic
            )

    if final_payload is None:
        final_payload = await asyncio.to_thread(_PROMPTIFY_MANAGER.run, prompt, topic)

    validated = ExternalValidationResult.model_validate(final_payload).model_dump()
    yield _line(
        "validation.completed",
        {
            "sessionId": session_id,
            "node": "promptify_validator_agent",
            "at": time.time(),
            "duration": time.perf_counter() - started,
            "output": validated,
            "usage": node_usage,
            "metadata": {"tools": node_tools},
        },
    )


@app.post("/api/validate")
async def validate_prompt(request: ValidateRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_validation(request.prompt, request.topic),
        media_type="application/x-ndjson",
    )

