# Google ADK Prompt Improver Demo

A small, learning-focused repository that demonstrates how Google Agent Development Kit
(ADK) can orchestrate multiple LLM agents to evaluate and improve a user prompt.

The first executable milestone contains a single structured `prompt_analyzer`. The evaluator
fan-out and final reviewer remain intentionally unimplemented so each ADK concept can be added
and verified one step at a time.

## Learning goals

- Understand the role of an `LlmAgent`.
- See deterministic orchestration around non-deterministic LLM calls.
- Observe fan-out evaluation and fan-in synthesis.
- Follow data as it moves between workflow nodes.
- Learn the responsibilities of `Runner`, `Session`, state, events, and callbacks.

The goal is not to build a production prompt-management platform or integrate with Promptify.

## Proposed v1 flow

```text
User prompt
    |
    v
Analyze prompt
    |
    +----------------+----------------+----------------+
    |                |                |                |
    v                v                v                v
Clarity          Context         Constraints      Output format
evaluator        evaluator       evaluator        evaluator
    |                |                |                |
    +----------------+----------------+----------------+
                             |
                             v
                  Synthesize evaluations
                  and improve the prompt
                             |
                             v
             Evaluation report + improved prompt
```

The implementation should use the ADK 2.x graph-based `Workflow` API. Conceptually, the graph
is equivalent to:

```text
Sequential(analyze, Parallel(evaluators), final_review)
```

`SequentialAgent` and `ParallelAgent` are useful for understanding the pattern, but the ADK
2.x documentation supersedes these template workflow agents with graph workflows for new
Python projects.

## Repository structure

```text
.
|-- .env.example
|-- .gitignore
|-- pyproject.toml
|-- README.md
|-- prompt_improver/
|   |-- __init__.py
|   |-- __main__.py    # Enables: python -m prompt_improver
|   |-- agent.py       # Agent definitions and root workflow
|   |-- cli.py         # Minimal Runner and in-memory Session example
|   |-- schemas.py     # Pydantic contracts between workflow steps
|   `-- callbacks.py   # Optional trace callbacks; no business logic
`-- tests/
    |-- test_runner.py  # Local App/Runner/Session smoke test
    `-- test_schemas.py # Deterministic schema tests
```

Keeping the whole agent topology in one `agent.py` initially makes the execution flow easier
to read and explain. Split agents into separate modules only when that file becomes genuinely
difficult to navigate.

## Intended components

| Component | Use in v1 | Responsibility |
| --- | --- | --- |
| `LlmAgent` | Yes | Analyze, evaluate, synthesize, and rewrite |
| `Workflow` | Yes | Define deterministic fan-out/fan-in execution |
| `Runner` | Yes | Execute the root workflow and expose events |
| `InMemorySessionService` | Yes | Keep local demo sessions without infrastructure |
| Session state | Sparingly | Small values needed by callbacks or instruction templates |
| Node output | Yes | Primary way to pass data between graph nodes |
| `output_key` | Not initially | Mainly useful in the classic template-workflow variant |
| Callback | Optional | Log agent/model boundaries for learning and debugging |
| Tools, memory, database | No | Outside the scope of the first version |

## Output contracts

Implement these contracts in `schemas.py` before writing agent instructions:

### `PromptAnalysis`

- `inferred_goal`
- `target_audience`
- `detected_context`
- `detected_constraints`
- `requested_output_format`
- `missing_information`

### `CriterionEvaluation`

- `criterion`
- `score` from 1 to 5
- up to three `findings`
- up to three `suggestions`

All four evaluators should return the same schema. The criterion name distinguishes their
results.

### `FinalResult`

- `overall_score`
- `summary`
- `evaluations`
- `improved_prompt`
- `assumptions`

The final reviewer owns the rewrite. Individual evaluators should critique only their assigned
criterion and should not produce competing rewritten prompts.

## Implementation plan

Implement and verify one vertical slice at a time.

### Step 1: prepare the environment

1. Create a virtual environment.
2. Install the project in editable mode with development dependencies.
3. Copy `.env.example` to `.env` and set either `GOOGLE_API_KEY` or `GEMINI_API_KEY`.
4. Confirm that a one-agent ADK hello-world invocation works before building the workflow.

PowerShell example:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Before installation, check the currently released `google-adk` version and update the bounded
dependency in `pyproject.toml` if the project is no longer on ADK 2.x.

### Step 2: define schemas

Add the three Pydantic models described above. Write fast tests for score boundaries and
required fields. This provides stable contracts before prompts and orchestration are added.

Status: implemented.

### Step 3: implement one analyzer

Create one `LlmAgent` that accepts the original prompt and returns `PromptAnalysis`. Run it by
itself and inspect both the final event and parsed structured output.

Status: implemented. After configuring `.env`, run:

```powershell
python -m prompt_improver "Explain Google ADK"
```

### Step 4: implement one evaluator

Start with clarity. It should receive the original prompt plus `PromptAnalysis`, return
`CriterionEvaluation`, and never rewrite the prompt. Verify this sequential path before adding
parallelism.

### Step 5: add the remaining evaluators

Use the same output contract for context, constraints, and output format. Keep instructions
short and criterion-specific.

### Step 6: compose fan-out and fan-in

Build the ADK graph so all evaluator nodes depend on the analyzer and the final reviewer depends
on all evaluator branches. Do not have parallel branches write to the same state key.

### Step 7: add the final reviewer

The final reviewer receives the original prompt, analysis, and all evaluations. It returns one
`FinalResult`, preserving user intent and making missing information explicit as assumptions or
placeholders.

### Step 8: expose execution through Runner

Use one `Runner` with `InMemorySessionService`. Create a fresh session ID per demo run and print
events with their author/node name so the execution order is visible.

Start with `adk run` or `adk web`. Do not add FastAPI or a custom UI yet.

### Step 9: add minimal tracing

First use Runner events. Only then add a small callback that records start/end boundaries or
timings. Keep evaluation and routing logic out of callbacks.

### Step 10: create three manual examples

Include:

1. A vague prompt with almost no context.
2. A prompt with good context but no output format.
3. An already strong prompt that should change only slightly.

These cases are enough to explain expected behavior without introducing a full evaluation
dataset.

## Definition of done for v1

- One text prompt can be submitted locally.
- The analyzer returns validated structured output.
- Four independent evaluators run as fan-out branches.
- The final reviewer runs only after all four branches complete.
- The response contains concise scores, findings, and one improved prompt.
- Runtime events make execution order visible.
- Restarting the application may discard sessions by design.
- The README includes one reproducible example.

## Deliberately out of scope

- Promptify integration
- A custom frontend or API server
- Persistent sessions or a database
- Long-term memory, RAG, or web search
- Dynamic evaluator selection
- Automatic multi-pass improvement loops
- Human approval workflows
- Multiple model comparison
- Cloud deployment
- External observability services
- Production security, tenancy, and authentication
- A full benchmark or calibrated scoring system

The evaluator scores are LLM-as-judge signals, not objective measurements. The first version is
primarily a demonstration of ADK orchestration and structured agent collaboration.

## Useful ADK references

- [Graph-based workflows](https://adk.dev/graphs/)
- [Workflow data handling](https://adk.dev/graphs/data-handling/)
- [LlmAgent](https://adk.dev/agents/llm-agents/)
- [Runner and runtime](https://adk.dev/runtime/)
- [Sessions and state](https://adk.dev/sessions/)
- [Callbacks](https://adk.dev/callbacks/)
