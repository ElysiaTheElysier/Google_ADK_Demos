# Google ADK Prompt Improver

An interactive demo showcasing how the **Google Agent Development Kit (ADK)** orchestrates multi-agent workflows, custom web search tools, and browser automation tools to **analyze, enrich, score, improve, and externally validate** user prompts.

![Prompt Inspector UI](docs/images/prompt-inspector.png)

---

## Architecture & Completed Phases

The project keeps a clean, deterministic **core evaluation workflow** while exposing two optional user-triggered capabilities outside the core graph:

```text
                    ┌─ Phase 2: Enrich Context ───► context_enrichment_agent ──► search_web (Wikipedia + DuckDuckGo)
                    │
User Prompt ────────┼─ Phase 1: Run Evaluation ───► ADK Graph Workflow (Analyzer -> 4 Evaluators -> Join -> Final Reviewer)
                    │
                    └─ Phase 3: Validate Result ──► promptify_validator_agent ─► validate_with_promptify (Playwright)
```

### Summary of Completed Phases

| Phase | Status | What Was Built |
| :--- | :--- | :--- |
| **Phase 1: Core Evaluation & Scoring Stability** | ✅ Completed | Fan-out / fan-in ADK `Workflow` (`Prompt Analyzer` $\rightarrow$ 4 parallel Evaluators $\rightarrow$ `JoinNode` $\rightarrow$ `Final Reviewer`), standardized 1–5 scoring rubrics, configurable `Temperature` (`0.0` default), deterministic Python `overall_score` calculation, and automatic **OpenAI fallback** on Gemini `503`/`429`/timeout. |
| **Phase 2: Context Enrichment (Search Tool)** | ✅ Completed | Standalone `context_enrichment_agent` equipped with custom `search_web` tool (Wikipedia REST API + DuckDuckGo fallback). Identifies missing context, retrieves factual snippets + source URLs, and lets the user selectively click **Apply context** (human-in-the-loop) before evaluation. Also supports optional inline graph enrichment (`search_public_context`). |
| **Phase 3: External Validation with Promptify (Browser Tool)** | ✅ Completed | Standalone `promptify_validator_agent` equipped with `validate_with_promptify` (Playwright persistent Chromium session). Supports human-in-the-loop Google OAuth login with automatic continuation, navigates through Promptify's class/roadmap/lesson views, dismisses walkthrough overlays, selects the target Lab, submits the `improved_prompt`, and extracts the external score (`/100`) and feedback into the UI. |

---

### Phase 1: Core Evaluation Workflow (Fan-out / Fan-in)

```text
User Prompt
    |
    v
Prompt Analyzer
    |
    +--------------+---------------+----------------+----------------+
    |              |               |                |                | (optional)
    v              v               v                v                v
 Clarity        Context        Constraints      Output Format    Context Enricher
 Evaluator      Evaluator      Evaluator        Evaluator        (search_public_context)
    |              |               |                |                |
    +--------------+---------------+----------------+----------------+
                                   |
                                   v
                                  Join
                                   |
                                   v
                            Final Reviewer
                                   |
                                   v
                       Scores + Improved Prompt
```

- **Parallel Evaluators**: Four specialized evaluators (`Clarity`, `Context`, `Constraints`, `Output Format`) run concurrently, so stage latency tracks the slowest branch rather than the sum of all four.
- **Scoring Consistency**:
  - Configurable `Temperature` slider (`0.0` to `1.0`, defaulting to `0.0`).
  - Explicit 1–5 anchor rubrics across all four criteria.
  - `overall_score` is computed deterministically in Python as the exact mean of the four criterion scores.

### Phase 2: Context Enrichment (`search_web` Tool)

- Clicking **Enrich context** invokes `context_enrichment_agent`, which calls `search_web(query)` to fetch public facts from Wikipedia and DuckDuckGo.
- Returns structured `ContextEnrichmentResult`:
  - `missing_context`: Gaps identified in the user's draft prompt.
  - `search_query`: The query executed by the agent.
  - `suggested_context`: Actionable context bullets the user can toggle on/off.
  - `sources`: Cited titles, URLs, and snippets.
- **Human-in-the-loop**: Suggestions are only appended to the prompt editor when the user clicks **Apply context**.

### Phase 3: External Validation with Promptify (`validate_with_promptify` Tool)

- Once an `improved_prompt` is generated, the **External Validation** panel enables **Validate with Promptify**.
- `promptify_validator_agent` invokes `validate_with_promptify(prompt, topic)` powered by **Playwright**:
  - Uses a persistent Chromium profile (`.promptify_browser_profile/`) so Google login sessions are preserved across runs.
  - If unauthenticated on [Promptify](https://promptify-wheat-seven.vercel.app/), opens Google login and waits up to 90 seconds for the user to sign in, then **automatically continues** in the same run.
  - Navigates through Promptify's **Class Selection** $\rightarrow$ **Dashboard** $\rightarrow$ **Learning Path** $\rightarrow$ **Lesson Workspace**, dismisses guided tutorial overlays, selects the matching Lab, fills in the `improved_prompt`, clicks **Chấm điểm Prompt**, and scrapes the `/100` score and detailed feedback back into the UI.

### Automatic OpenAI Fallback

- When Gemini returns `503 UNAVAILABLE` (high demand), `429 RESOURCE_EXHAUSTED` (rate limit), or stalls past `ADK_EVENT_TIMEOUT_SECONDS`, the backend automatically cancels the stalled attempt and re-runs the request with OpenAI (`OPENAI_MODEL`) via LiteLLM if `OPENAI_API_KEY` is configured.

---

## Key Google ADK Concepts Demonstrated

| ADK Component | Role in This Project |
| :--- | :--- |
| `LlmAgent` | Defines `prompt_analyzer`, 4 criterion evaluators, `final_reviewer`, `context_enrichment_agent`, and `promptify_validator_agent` |
| `Workflow` | Declares the fan-out (parallel evaluation) and fan-in graph |
| `JoinNode` | Synchronizes all parallel branches before invoking `final_reviewer` |
| `Runner` | Executes agents/workflows and streams real-time execution `Event`s |
| `Session` | Holds invocation state (`session.state`) within a single run |
| `output_key` | Persists structured agent outputs into `session.state` for downstream agents |
| `output_schema` | Enforces strict Pydantic schemas (`PromptAnalysis`, `CriterionEvaluation`, `FinalResult`, `ContextEnrichmentResult`, `ExternalValidationResult`) |
| Custom Function Tools | Standard Python functions (`search_web`, `search_public_context`, `validate_with_promptify`) exposed as ADK tools via type annotations and docstrings |

---

## Repository Structure

```text
.
|-- prompt_improver/
|   |-- agent.py          # LlmAgent definitions and ADK Graph Workflows
|   |-- schemas.py        # Pydantic schemas for all phases
|   |-- tools.py          # Custom tools: search_web, search_public_context, validate_with_promptify (Playwright)
|   |-- cli.py            # Minimal CLI runner
|   `-- callbacks.py      # Telemetry callbacks
|-- frontend/
|   |-- src/App.tsx       # React UI with live SSE workflow & tool state
|   |-- src/styles.css    # Visual styling (Workflow Inspector, Trace Console, Validation Panel)
|   `-- package.json      # Vite + React + TypeScript dependencies
|-- ui_backend.py         # FastAPI backend + SSE streaming for Evaluate, Enrich, and Validate
|-- requirements-ui.txt   # UI backend, LiteLLM, and Playwright dependencies
|-- tests/                # Pytest unit tests for schemas, tools, and workflow structure
|-- pyproject.toml        # Core Python package configuration
`-- .env.example          # Environment variable template
```

---

## Getting Started (Step-by-Step Setup)

### Prerequisites

- **Python 3.11+**
- **Node.js 20+**
- **Google Gemini API Key** (from [Google AI Studio](https://aistudio.google.com/))
- **OpenAI API Key** *(optional, recommended for automatic fallback when Gemini experiences 503 high demand)*

### 1. Clone the Repository & Set Up Python Environment

Open **PowerShell** in your workspace directory:

```powershell
git clone https://github.com/ElysiaTheElysier/Google_ADK_Demos.git
cd Google_ADK_Demos

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# (If PowerShell blocks script execution, run the bypass command first):
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# Install Python packages and Playwright Chromium browser
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install -r requirements-ui.txt
playwright install chromium
```

### 2. Configure Environment Variables (`.env`)

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill in your keys:

```env
# Required: Google AI Studio API Key
GOOGLE_API_KEY=your-google-api-key
GOOGLE_GENAI_USE_VERTEXAI=FALSE
ADK_MODEL=gemini-3.5-flash-lite

# Optional: Automatic fallback when Gemini returns 503/429 or times out
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=openai/gpt-4.1-mini
ADK_EVENT_TIMEOUT_SECONDS=60

# Optional: Target URL for Phase 3 External Validation
PROMPTIFY_URL=https://promptify-wheat-seven.vercel.app/
```

### 3. Install Frontend Dependencies

```powershell
cd frontend
npm install
cd ..
```

### 4. Run Backend & Frontend

Open **two PowerShell terminals** side by side:

**Terminal 1 — Start Backend (`http://localhost:8000`):**

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\uvicorn.exe ui_backend:app --reload --host 127.0.0.1 --port 8000
```

*(Verify at `http://localhost:8000/api/health` $\rightarrow$ `{"status":"ok"}`)*

**Terminal 2 — Start Frontend (`http://localhost:5173`):**

```powershell
cd frontend
npm run dev
```

Open **[http://localhost:5173](http://localhost:5173)** in your browser.

---

## How to Use the UI

1. **Build & Enrich Prompt (Phase 2)**:
   - Enter a prompt or pick a sample chip.
   - Click **Enrich context** to let `context_enrichment_agent` search Wikipedia/Web for relevant facts. Select the checkboxes you want to keep and click **Apply context**.
2. **Evaluate & Improve Prompt (Phase 1)**:
   - Choose a `Temperature` (`0.0` recommended for deterministic scoring) and click **Run evaluation**.
   - Inspect live node execution in the **Workflow Inspector**, view parallel timing bars, and review the **Improved Prompt**.
3. **Validate with Promptify (Phase 3)**:
   - In the **External Validation** section, pick a target Lab topic and click **Validate with Promptify**.
   - On the first run, a Chromium window will open for Google Sign-In. Once signed in, Playwright automatically navigates to the lesson workspace, submits your improved prompt, and returns the external `/100` score and feedback to the UI.

---

## CLI & Testing

Run the core workflow from the command line without the UI:

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m prompt_improver "Explain Google ADK to a junior developer"
```

Run linter and unit tests:

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -q
```

---

## References

- [Google ADK Documentation](https://adk.dev/)
- [ADK Graph Workflows](https://adk.dev/graphs/)
- [ADK Runtime & Runner](https://adk.dev/runtime/)
- [ADK Sessions & State](https://adk.dev/sessions/)
- [ADK LiteLLM Connector](https://adk.dev/agents/models/litellm/)
