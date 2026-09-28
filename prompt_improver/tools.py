"""External tools used only by the explicitly enabled phase-2 workflow."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google.adk.tools import ToolContext

_META_QUERY_WORDS = re.compile(
    r"\b("
    r"origin|origins|history|historical|timeline|overview|introduction|guide|"
    r"explainer|verify|verification|verified|public|sources?|links?|citations?|"
    r"references?|about|what|is|are|how|does|do|paper|et|al|latest|current|"
    r"recent|facts?|information|background|summary|explain|explaining|write|"
    r"create|concise|technical|short|article|blog|post|for|with|using|from|"
    r"the|and|or|of|in|to|by|on|a|an|"
    r"tìm|kiếm|tra|cứu|kiểm|chứng|nguồn|gốc|lịch|sử|giải|thích|viết|bài|"
    r"ngắn|gọn|về|cho|của|các|những|mới|nhất|hiện|tại|công|khai|link|dẫn"
    r")\b",
    flags=re.IGNORECASE,
)

_ACRONYM_EXPANSIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brag\b", flags=re.IGNORECASE), "Retrieval-augmented generation"),
    (re.compile(r"\bllms?\b", flags=re.IGNORECASE), "Large language model"),
)

_EXPLICIT_SEARCH_PATTERN = re.compile(
    r"("
    r"\b(search|verify|verification|research|public\s+sources?|source\s+links?|"
    r"citations?|references?|look\s+up|latest|current|origin|origins|history|timeline)\b|"
    r"(tìm\s+kiếm|tra\s+cứu|kiểm\s+chứng|nguồn\s+công\s+khai|dẫn\s+nguồn|"
    r"nguồn\s+tham\s+khảo|lịch\s+sử|nguồn\s+gốc|mới\s+nhất)"
    r")",
    flags=re.IGNORECASE,
)

_FORBID_EXTERNAL_PATTERN = re.compile(
    r"("
    r"do\s+not\s+add\s+external\s+information|"
    r"keep\s+all\s+facts\s+exactly\s+as\s+provided|"
    r"do\s+not\s+invent\s+pricing\s+or\s+availability|"
    r"không\s+thêm\s+thông\s+tin\s+bên\s+ngoài"
    r")",
    flags=re.IGNORECASE,
)


def _normalize_wikipedia_query(query: str) -> list[str]:
    """Build ordered candidate queries so Wikipedia matches the core topic page."""
    raw = re.sub(r"\s+", " ", query).strip()
    if not raw:
        return []

    expanded = raw
    for pattern, replacement in _ACRONYM_EXPANSIONS:
        if pattern.search(expanded) and replacement.lower() not in expanded.lower():
            expanded = pattern.sub(replacement, expanded)

    cleaned = _META_QUERY_WORDS.sub(" ", expanded)
    cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    candidates: list[str] = []
    for candidate in (cleaned, expanded, raw):
        trimmed = " ".join(candidate.split()[:8]).strip()
        if trimmed and trimmed.lower() not in {c.lower() for c in candidates}:
            candidates.append(trimmed)
    return candidates


def _fetch_wikipedia_lang(query: str, lang: str = "en") -> list[dict[str, str]]:
    """Query one Wikipedia language edition and return up to three article snippets."""
    base_url = f"https://{lang}.wikipedia.org/w/api.php"
    search_params = urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 3,
            "srprop": "",
            "format": "json",
            "formatversion": 2,
        }
    )
    search_request = Request(
        f"{base_url}?{search_params}",
        headers={"User-Agent": "ADK-Prompt-Improver-Demo/0.2"},
    )
    with urlopen(search_request, timeout=8) as response:
        search_payload = json.load(response)
    matches = search_payload.get("query", {}).get("search", [])
    if not matches:
        return []

    page_ids = "|".join(str(match["pageid"]) for match in matches)
    detail_params = urlencode(
        {
            "action": "query",
            "pageids": page_ids,
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "exsentences": 5,
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
        }
    )
    detail_request = Request(
        f"{base_url}?{detail_params}",
        headers={"User-Agent": "ADK-Prompt-Improver-Demo/0.2"},
    )
    with urlopen(detail_request, timeout=8) as response:
        payload = json.load(response)

    pages_by_id = {
        page.get("pageid"): page
        for page in payload.get("query", {}).get("pages", [])
    }
    ordered_pages = [pages_by_id.get(match.get("pageid"), {}) for match in matches]
    results: list[dict[str, str]] = []
    for page in ordered_pages:
        if not page:
            continue
        snippet = re.sub(r"\s+", " ", page.get("extract", "")).strip()
        if snippet:
            results.append(
                {
                    "title": page.get("title", ""),
                    "snippet": snippet,
                    "url": page.get("fullurl", ""),
                }
            )
    return results[:3]


def _search_wikipedia(query: str) -> dict[str, Any]:
    """Execute one Wikipedia lookup with query normalization and language fallback."""
    candidates = _normalize_wikipedia_query(query)
    if not candidates:
        return {"query": query, "results": []}

    has_non_ascii = any(ord(ch) > 127 for ch in query)
    langs = ("en", "vi") if has_non_ascii else ("en",)

    try:
        for lang in langs:
            for candidate in candidates:
                results = _fetch_wikipedia_lang(candidate, lang=lang)
                if results:
                    return {
                        "query": query,
                        "resolved_query": candidate,
                        "results": results,
                    }
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"query": query, "results": [], "error": str(exc)}

    return {"query": query, "results": []}


def search_public_context(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """Search Wikipedia for public factual background relevant to a prompt's topic.

    Call this tool when the prompt asks to search, verify facts, include public
    sources or links, cover history/origins, or explain a real-world public
    topic, technology, or concept. Pass a short canonical English topic name
    (for example, "Retrieval-augmented generation" or "Kubernetes"). Never use
    this tool for private company announcements, fictional products, or prompts
    that forbid adding external information.

    Args:
        query: A short canonical topic query (1 to 4 words, ideally in English).
    """
    if tool_context.state.get("temp:public_search_used"):
        cached = tool_context.state.get("temp:public_search_results")
        if cached:
            return {
                "query": tool_context.state.get("temp:public_search_query", query),
                "results": cached,
                "note": "Only one public search is allowed per run; reusing the initial search results.",
            }
        return {
            "query": query,
            "results": [],
            "error": "Only one public search is allowed per run.",
        }

    tool_context.state["temp:public_search_used"] = True
    tool_context.state["temp:public_search_query"] = query
    payload = _search_wikipedia(query)
    tool_context.state["temp:public_search_results"] = payload.get("results", [])
    return payload


def _prompt_requires_search(state: Any) -> tuple[bool, str | None]:
    """Check whether the analyzed prompt clearly requires public search."""
    analysis = state.get("prompt_analysis") if hasattr(state, "get") else None
    if not isinstance(analysis, dict):
        return False, None

    original_prompt = str(analysis.get("original_prompt", ""))
    inferred_goal = str(analysis.get("inferred_goal", ""))
    combined = f"{original_prompt}\n{inferred_goal}"

    if _FORBID_EXTERNAL_PATTERN.search(combined):
        return False, None

    if _EXPLICIT_SEARCH_PATTERN.search(combined):
        candidates = _normalize_wikipedia_query(inferred_goal or original_prompt)
        return True, (candidates[0] if candidates else inferred_goal or original_prompt)

    return False, None


def validate_context_enrichment_tool_call(
    tool: Any,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> dict[str, Any] | None:
    """Guardrail callback ensuring honest and reliable tool usage by context_enricher."""
    tool_name = getattr(tool, "name", "")
    if tool_name != "set_model_response":
        return None

    search_used = bool(tool_context.state.get("temp:public_search_used"))
    cached_query = tool_context.state.get("temp:public_search_query")
    cached_results = tool_context.state.get("temp:public_search_results") or []
    requires_search, suggested_query = _prompt_requires_search(tool_context.state)

    # 1. Never allow claiming used_search=True without actually calling search_public_context.
    if args.get("used_search") and not search_used:
        return {
            "error": (
                "You cannot set used_search=true without calling search_public_context first. "
                "Call search_public_context(query=...) with a short topic query first."
            )
        }

    # 2. If the prompt explicitly needs search/verification and the model skipped the tool,
    #    nudge it once to call search_public_context before finalizing.
    if requires_search and not search_used and not tool_context.state.get("temp:search_nudge_sent"):
        tool_context.state["temp:search_nudge_sent"] = True
        hint = f' (for example: "{suggested_query}")' if suggested_query else ""
        return {
            "error": (
                "This prompt requires public factual verification or external sources. "
                f"You must call search_public_context{hint} before calling set_model_response."
            )
        }

    # 3. When search_public_context was called, ensure search_query and retrieved sources are preserved.
    if search_used:
        if cached_query and not args.get("search_query"):
            args["search_query"] = cached_query
        if cached_results and (args.get("used_search") or requires_search):
            args["used_search"] = True
            if not args.get("sources"):
                args["sources"] = [
                    {
                        "title": item["title"],
                        "url": item["url"],
                        "fact": item["snippet"],
                    }
                    for item in cached_results[:3]
                    if item.get("snippet")
                ]
            if not args.get("useful_context"):
                args["useful_context"] = [
                    item["snippet"]
                    for item in cached_results[:3]
                    if item.get("snippet")
                ]

    return None


PROMPTIFY_DEFAULT_URL = "https://promptify-wheat-seven.vercel.app/"

PROMPTIFY_TOPICS: tuple[tuple[str, str, int, tuple[str, ...]], ...] = (
    (
        "LAB-01-PII-SCRUBBING",
        "Lab 01: PII Scrubbing & Data Privacy",
        0,
        ("pii", "scrub", "privacy", "redact", "anonym", "cccd", "bảo mật", "ẩn danh"),
    ),
    (
        "LAB-02-CONTEXT-ENGINEERING",
        "Lab 02: Context Engineering & Few-Shot",
        1,
        ("context", "few-shot", "audience", "tone", "blog", "article", "launch", "bối cảnh"),
    ),
    (
        "LAB-03-MULTISTEP-COT-GUARDRAILS",
        "Lab 03: Multi-Step CoT & Guardrails",
        2,
        ("step-by-step", "chain of thought", "cot", "guardrail", "constraint", "ràng buộc"),
    ),
    (
        "LAB-04-REACT-AGENTIC-WORKFLOW",
        "Lab 04: ReAct & Agentic Workflow",
        3,
        ("react", "agent", "tool", "workflow", "retrieval", "rag", "search", "verify"),
    ),
    (
        "LAB-05-TEMPERATURE-SAMPLING",
        "Lab 05: Temperature & Generation Control",
        4,
        ("temperature", "top-p", "sampling", "token", "creative", "deterministic"),
    ),
    (
        "LAB-07-INJECTION-DEFENSE",
        "Lab 07: Prompt Injection Defense & Grounding",
        5,
        ("injection", "hallucination", "grounding", "source", "citation", "untrusted", "ảo giác"),
    ),
    (
        "LAB-08-STEPBACK-META-PROMPT",
        "Lab 08: Step-Back & Meta-Prompting",
        6,
        ("step-back", "meta-prompt", "strategy", "architecture", "system prompt", "plan"),
    ),
)


def resolve_promptify_topic(prompt: str, topic: str | None = None) -> tuple[str, int]:
    """Resolve a user/agent topic string or prompt content to a Promptify lab label and index."""
    cleaned = (topic or "").strip()
    if cleaned and cleaned.lower() not in {"auto", "default", "general"}:
        lowered = cleaned.lower()
        for code, label, idx, keywords in PROMPTIFY_TOPICS:
            if (
                lowered == code.lower()
                or lowered in label.lower()
                or f"lab 0{idx + 1}" in lowered
                or f"lab {idx + 1}" in lowered
                or f"bài {idx + 1}" in lowered
            ):
                return label, idx
        for _code, label, idx, keywords in PROMPTIFY_TOPICS:
            if any(kw in lowered for kw in keywords):
                return label, idx

    prompt_lower = prompt.lower()
    best_label = PROMPTIFY_TOPICS[1][1]
    best_idx = PROMPTIFY_TOPICS[1][2]
    best_hits = 0
    for _code, label, idx, keywords in PROMPTIFY_TOPICS:
        hits = sum(1 for kw in keywords if kw in prompt_lower)
        if hits > best_hits:
            best_hits = hits
            best_label = label
            best_idx = idx
    return best_label, best_idx


class _PromptifyBrowserManager:
    """Single-thread Playwright persistent browser manager for human-in-the-loop Google login."""

    def __init__(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="promptify-playwright"
        )
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None

    def run(self, prompt: str, topic: str) -> dict[str, Any]:
        future = self._executor.submit(self._validate_sync, prompt, topic)
        return future.result(timeout=180)

    def _reset_browser(self) -> None:
        from contextlib import suppress

        if self._context is not None:
            with suppress(Exception):
                self._context.close()
        self._context = None
        self._page = None

    def _ensure_page(self) -> Any:
        import os
        from contextlib import suppress
        from pathlib import Path

        from playwright.sync_api import sync_playwright

        # 1. Try reusing the existing context/page if still alive
        if self._context is not None:
            try:
                pages = [p for p in self._context.pages if not p.is_closed()]
                if self._page is not None and not self._page.is_closed():
                    self._page.evaluate("1")
                    with suppress(Exception):
                        self._page.bring_to_front()
                    return self._page
                if pages:
                    self._page = pages[-1]
                    self._page.evaluate("1")
                    with suppress(Exception):
                        self._page.bring_to_front()
                    return self._page
                self._page = self._context.new_page()
                self._page.evaluate("1")
                with suppress(Exception):
                    self._page.bring_to_front()
                return self._page
            except Exception:  # noqa: BLE001
                self._reset_browser()

        # 2. Launch (or relaunch) persistent browser context
        profile_dir = (
            Path(__file__).resolve().parent.parent / ".promptify_browser_profile"
        )
        profile_dir.mkdir(parents=True, exist_ok=True)
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_file = profile_dir / lock_name
            if lock_file.exists():
                with suppress(Exception):
                    lock_file.unlink()

        headless = os.getenv("PROMPTIFY_HEADLESS", "0").strip() in {"1", "true", "yes"}
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
            "viewport": {"width": 1440, "height": 900},
        }

        for attempt in range(2):
            if self._playwright is None or attempt == 1:
                if self._playwright is not None:
                    with suppress(Exception):
                        self._playwright.stop()
                self._playwright = sync_playwright().start()

            for channel in ("chrome", "msedge", None):
                try:
                    if channel:
                        self._context = self._playwright.chromium.launch_persistent_context(
                            channel=channel, **launch_kwargs
                        )
                    else:
                        self._context = self._playwright.chromium.launch_persistent_context(
                            **launch_kwargs
                        )
                    break
                except Exception:  # noqa: BLE001, S112
                    continue
            if self._context is not None:
                break

        if self._context is None:
            raise RuntimeError("Could not launch Chrome, Edge, or Chromium via Playwright.")

        pages = [p for p in self._context.pages if not p.is_closed()]
        self._page = pages[-1] if pages else self._context.new_page()
        with suppress(Exception):
            self._page.bring_to_front()
        return self._page

    def _is_login_screen(self, page: Any) -> bool:
        url = (page.url or "").lower()
        if "accounts.google.com" in url or "/auth/v1/authorize" in url:
            return True
        login_btn = page.locator(
            'button:has-text("Bắt đầu học với Google"), button:has-text("Đăng nhập")'
        )
        return login_btn.count() > 0 and login_btn.first.is_visible()

    def _wait_initial_auth(self, page: Any) -> None:
        from contextlib import suppress

        with suppress(Exception):
            spinner = page.locator("text=Đang xác thực và tải dữ liệu từ máy chủ")
            if spinner.count() > 0 and spinner.first.is_visible():
                spinner.first.wait_for(state="hidden", timeout=12_000)

    def _dismiss_tutorials(self, page: Any) -> None:
        from contextlib import suppress

        with suppress(Exception):
            close_tour = page.locator(
                'button[title*="Đóng hướng dẫn"], '
                'button:has-text("Bỏ qua hướng dẫn"), '
                'button:has-text("Đóng hướng dẫn"), '
                'button:has-text("Bỏ qua")'
            )
            if close_tour.count() > 0 and close_tour.first.is_visible():
                close_tour.first.click(timeout=2000)
                page.wait_for_timeout(400)
            elif page.locator("#spotlight-mask, #instructor-spotlight-mask").count() > 0:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)

    def _navigate_to_lesson_workspace(self, page: Any, lab_idx: int) -> bool:
        """Progress through Class Select -> Dashboard -> Learning Path -> Lesson Playground."""
        from contextlib import suppress

        editor_locator = page.locator('[data-tour="tour-prompt"] textarea')
        for _step in range(25):
            if page.is_closed():
                return False
            self._wait_initial_auth(page)
            self._dismiss_tutorials(page)

            if editor_locator.count() > 0 and editor_locator.first.is_visible():
                return True

            # Case A: On Learning Path screen (`c_`) -> click lesson card ("Làm bài ngay" / "Vào bài" / "Học lại")
            lesson_cards = page.locator(
                'span:has-text("Làm bài ngay"), span:has-text("Vào bài"), span:has-text("Học lại")'
            )
            if lesson_cards.count() > 0 and lesson_cards.first.is_visible():
                with suppress(Exception):
                    target_card = (
                        lesson_cards.nth(lab_idx)
                        if lesson_cards.count() > lab_idx
                        else lesson_cards.first
                    )
                    target_card.click(timeout=3000)
                    page.wait_for_timeout(1200)
                    continue

            # Case B: On Learner Dashboard (`o_`) -> click "Xem lộ trình lớp này"
            roadmap_btn = page.locator('button:has-text("Xem lộ trình lớp này")')
            if roadmap_btn.count() > 0 and roadmap_btn.first.is_visible():
                with suppress(Exception):
                    roadmap_btn.first.click(timeout=4000)
                    page.wait_for_timeout(1200)
                    continue

            # Case C: On Class Selection (`ob`) -> click "Tiếp tục học" / "Tham gia miễn phí" / "Vào lớp học"
            class_btn = page.locator(
                'button:has-text("Tiếp tục học"), '
                'button:has-text("Tham gia miễn phí"), '
                'button:has-text("Vào lớp học")'
            )
            if class_btn.count() > 0 and class_btn.first.is_visible():
                with suppress(Exception):
                    class_btn.first.click(timeout=4000)
                    page.wait_for_timeout(1500)
                    continue

            # Case D: Top navigation bar has "Lộ trình học" or "Lộ trình"
            nav_path_btn = page.locator(
                'header button:has-text("Lộ trình học"), header button:has-text("Lộ trình")'
            )
            if nav_path_btn.count() > 0 and nav_path_btn.first.is_visible():
                with suppress(Exception):
                    nav_path_btn.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    continue

            page.wait_for_timeout(800)

        return editor_locator.count() > 0 and editor_locator.first.is_visible()

    def _validate_sync(self, prompt: str, topic: str) -> dict[str, Any]:
        import os
        from contextlib import suppress

        base_url = os.getenv("PROMPTIFY_URL", PROMPTIFY_DEFAULT_URL).rstrip("/")
        topic_label, lab_idx = resolve_promptify_topic(prompt, topic)

        try:
            page = self._ensure_page()
            current_url = page.url or ""
            if not current_url.startswith("http") or (
                base_url not in current_url and "accounts.google.com" not in current_url
            ):
                page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1500)

            self._wait_initial_auth(page)

            # 1. Human-in-the-loop Google login: click login and wait up to 90s for user to finish OAuth
            if self._is_login_screen(page):
                google_btn = page.locator('button:has-text("Bắt đầu học với Google")')
                if google_btn.count() > 0 and google_btn.first.is_visible():
                    with suppress(Exception):
                        google_btn.first.click(timeout=3000)
                        page.wait_for_timeout(1000)

                login_wait_ms = 90_000
                elapsed_ms = 0
                step_ms = 1000
                logged_in = False
                while elapsed_ms < login_wait_ms:
                    if page.is_closed():
                        self._reset_browser()
                        return {
                            "status": "login_required",
                            "submitted_prompt": prompt,
                            "topic": topic_label,
                            "score": None,
                            "feedback": [
                                "The Promptify browser window was closed before Google login completed.",
                                "Click 'Validate with Promptify' to reopen the browser window and sign in.",
                            ],
                            "result_url": base_url,
                        }
                    self._wait_initial_auth(page)
                    url_now = (page.url or "").lower()
                    if (
                        base_url.lower() in url_now
                        and "accounts.google.com" not in url_now
                        and "/auth/v1/authorize" not in url_now
                        and not self._is_login_screen(page)
                    ):
                        page.wait_for_timeout(1500)
                        self._wait_initial_auth(page)
                        if not self._is_login_screen(page):
                            logged_in = True
                            break
                    page.wait_for_timeout(step_ms)
                    elapsed_ms += step_ms

                if not logged_in:
                    return {
                        "status": "login_required",
                        "submitted_prompt": prompt,
                        "topic": topic_label,
                        "score": None,
                        "feedback": [
                            "Promptify is open in the browser window and waiting for Google login.",
                            "Please complete Google sign-in in the opened browser window, then click 'Continue after Google login'.",
                        ],
                        "result_url": page.url or base_url,
                    }

            # Ensure live evaluation mode and dismiss coach intro popup
            with suppress(Exception):
                page.evaluate(
                    """() => {
                        localStorage.setItem(
                            "promptify_api_config",
                            JSON.stringify({
                                mode: "live",
                                geminiApiKey: "",
                                model: "server-managed",
                                temperature: 0.3
                            })
                        );
                        localStorage.setItem("promptify_coach_intro_dismissed", "true");
                    }"""
                )

            # 2. Navigate through Class Select / Dashboard / Learning Path into the Lesson Playground
            reached_lesson = self._navigate_to_lesson_workspace(page, lab_idx)
            if not reached_lesson:
                return {
                    "status": "failed",
                    "submitted_prompt": prompt,
                    "topic": topic_label,
                    "score": None,
                    "feedback": [
                        "Logged into Promptify, but could not automatically open a lesson workspace.",
                        "Please select a class or lesson in the opened Promptify browser window and click 'Validate with Promptify' again.",
                    ],
                    "result_url": page.url or base_url,
                }

            # Wait 1s so any first-time lesson walkthrough modal (`QS`) pops up and can be dismissed
            # before we fill the prompt (closing `QS` resets the prompt editor to its pre-tutorial state).
            page.wait_for_timeout(1000)
            self._dismiss_tutorials(page)

            # 3. Select the target Lab / Topic in the lesson <select> (not the header class <select>)
            with suppress(Exception):
                lab_select = page.locator(
                    'main select:has(option[value="0"]), select:not([aria-label="Chọn lớp đang học"])'
                ).first
                if lab_select.count() > 0 and lab_select.is_visible():
                    option_count = lab_select.locator("option").count()
                    if option_count > 0:
                        target_idx = min(lab_idx, option_count - 1)
                        lab_select.select_option(value=str(target_idx), timeout=3000)
                        page.wait_for_timeout(500)
                        selected_text = lab_select.locator(
                            f'option[value="{target_idx}"]'
                        ).inner_text(timeout=2000)
                        if selected_text:
                            topic_label = selected_text.strip()

            self._dismiss_tutorials(page)

            # 4. Fill the improved prompt into the Promptify editor
            textarea = page.locator('[data-tour="tour-prompt"] textarea, main textarea').first
            textarea.wait_for(state="visible", timeout=10_000)
            textarea.click(timeout=3000)
            textarea.fill(prompt)
            page.wait_for_timeout(400)
            self._dismiss_tutorials(page)
            if not textarea.input_value().strip():
                textarea.fill(prompt)
                page.wait_for_timeout(300)

            # 5. Capture /api/evaluate response while clicking "Chạy Prompt"
            captured_eval: list[dict[str, Any]] = []

            def _on_response(response: Any) -> None:
                if "/api/evaluate" in response.url and response.status == 200:
                    with suppress(Exception):
                        data = response.json()
                        if isinstance(data, dict):
                            captured_eval.append(data)

            page.on("response", _on_response)
            try:
                run_btn = page.locator(
                    '[data-tour="tour-run"], button:has-text("Chạy Prompt")'
                ).first
                run_btn.wait_for(state="visible", timeout=5000)
                run_btn.click(timeout=5000)

                # Wait until evaluation completes (either network payload arrives or score badge renders)
                deadline = 60_000
                waited = 0
                step_ms = 500
                while waited < deadline:
                    if captured_eval:
                        page.wait_for_timeout(800)
                        break
                    score_badge = page.locator("text=/\\d+(\\.\\d+)?\\s*\\/\\s*10\\s*điểm/")
                    if score_badge.count() > 0 and score_badge.first.is_visible():
                        break
                    err_banner = page.locator(
                        "text=Không thể kết nối dịch vụ AI, text=AI chưa thể đánh giá lần này"
                    )
                    if err_banner.count() > 0 and err_banner.first.is_visible():
                        break
                    page.wait_for_timeout(step_ms)
                    waited += step_ms
            finally:
                with suppress(Exception):
                    page.remove_listener("response", _on_response)

            # Expand "Xem chi tiết" in the UI so the user can also see full feedback in browser
            with suppress(Exception):
                detail_btn = page.locator('button:has-text("Xem chi tiết")')
                if detail_btn.count() > 0 and detail_btn.first.is_visible():
                    detail_btn.first.click(timeout=2000)
                    page.wait_for_timeout(300)

            # 6. Extract score and feedback from captured /api/evaluate JSON or DOM fallback
            if captured_eval:
                eval_data = captured_eval[-1]
                raw_total = eval_data.get("total")
                score_val = float(raw_total) if isinstance(raw_total, (int, float)) else None
                feedback_items: list[str] = []
                scores_map = eval_data.get("scores")
                if isinstance(scores_map, dict):
                    label_map = {
                        "taskCompletion": "Task completion",
                        "groundedness": "Groundedness",
                        "formatAdherence": "Format adherence",
                        "constraintCompliance": "Constraint compliance",
                        "businessUsability": "Business usability",
                    }
                    sub_parts = [
                        f"{label}: {int(scores_map[key]) * 5}/10"
                        for key, label in label_map.items()
                        if isinstance(scores_map.get(key), (int, float))
                    ]
                    if sub_parts:
                        feedback_items.append("Rubric breakdown — " + " · ".join(sub_parts))
                for strength in eval_data.get("strengths") or []:
                    if isinstance(strength, str) and strength.strip():
                        feedback_items.append(f"Strength: {strength.strip()}")
                for improvement in eval_data.get("improvements") or []:
                    if isinstance(improvement, str) and improvement.strip():
                        cleaned_imp = re.sub(r"^[🚨✨💡📌\s*]+", "", improvement).strip()
                        feedback_items.append(f"Improvement: {cleaned_imp}")
                next_hint = eval_data.get("nextHint")
                if isinstance(next_hint, str) and next_hint.strip():
                    feedback_items.append(f"Next hint: {next_hint.strip()}")

                return {
                    "status": "completed",
                    "submitted_prompt": prompt,
                    "topic": topic_label,
                    "score": score_val,
                    "feedback": feedback_items or ["Evaluation completed on Promptify."],
                    "result_url": page.url or base_url,
                }

            # DOM fallback if network payload wasn't intercepted
            score_badge = page.locator("text=/\\d+(\\.\\d+)?\\s*\\/\\s*10\\s*điểm/")
            if score_badge.count() > 0 and score_badge.first.is_visible():
                badge_text = score_badge.first.inner_text()
                m_score = re.search(r"(\d+(?:\.\d+)?)\s*\/\s*10", badge_text)
                score_val = float(m_score.group(1)) if m_score else None
                dom_feedback = [
                    li.strip()
                    for li in page.locator("ul.list-disc li").all_inner_texts()
                    if li.strip()
                ]
                return {
                    "status": "completed",
                    "submitted_prompt": prompt,
                    "topic": topic_label,
                    "score": score_val,
                    "feedback": dom_feedback or [f"Promptify rubric score: {badge_text}"],
                    "result_url": page.url or base_url,
                }

            return {
                "status": "failed",
                "submitted_prompt": prompt,
                "topic": topic_label,
                "score": None,
                "feedback": [
                    (
                        "Promptify did not return a rubric score within the timeout window. "
                        "Check the opened Promptify browser window for details."
                    )
                ],
                "result_url": page.url or base_url,
            }
        except Exception as exc:  # noqa: BLE001
            self._reset_browser()
            return {
                "status": "failed",
                "submitted_prompt": prompt,
                "topic": topic_label,
                "score": None,
                "feedback": [f"Browser validation error: {exc}"],
                "result_url": base_url,
            }


_PROMPTIFY_MANAGER = _PromptifyBrowserManager()


async def validate_with_promptify(
    prompt: str,
    topic: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Validate an improved prompt on the external Promptify web application via browser automation.

    Opens or reuses a persistent browser session at Promptify, checks Google login
    status (returning status='login_required' if the user still needs to sign in),
    selects the matching lab topic, submits the prompt, and extracts the rubric
    score and feedback.

    Args:
        prompt: The improved prompt text to validate on Promptify.
        topic: The target Promptify lab/topic (or 'auto' to match automatically).
    """
    import asyncio

    result = await asyncio.to_thread(_PROMPTIFY_MANAGER.run, prompt, topic)
    tool_context.state["temp:promptify_called"] = True
    tool_context.state["temp:promptify_result"] = result
    return result


def validate_promptify_tool_call(
    tool: Any,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> dict[str, Any] | None:
    """Guardrail callback ensuring promptify_validator_agent calls validate_with_promptify and preserves its exact result."""
    tool_name = getattr(tool, "name", "")
    if tool_name != "set_model_response":
        return None

    if not tool_context.state.get("temp:promptify_called"):
        return {
            "error": (
                "You must call validate_with_promptify(prompt=..., topic=...) "
                "before calling set_model_response."
            )
        }

    recorded = tool_context.state.get("temp:promptify_result")
    if isinstance(recorded, dict):
        args["status"] = recorded.get("status", "failed")
        args["submitted_prompt"] = recorded.get(
            "submitted_prompt", args.get("submitted_prompt", "")
        )
        args["topic"] = recorded.get("topic", args.get("topic", "auto"))
        args["score"] = recorded.get("score")
        if recorded.get("feedback"):
            args["feedback"] = list(recorded["feedback"])
        args["result_url"] = recorded.get("result_url")

    return None

