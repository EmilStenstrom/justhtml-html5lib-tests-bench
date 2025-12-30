from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any
from typing import Literal
from urllib.parse import urlsplit


BrowserName = Literal["chromium", "firefox", "webkit"]

_MAX_PLAYWRIGHT_TIMEOUT_MS = 10_000


def _read_js_resource(filename: str) -> str:
    try:
        return resources.files("html5lib_tests_bench").joinpath("js", filename).read_text(encoding="utf-8").strip()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "JS resource not found. If installed from a wheel/sdist, this likely means packaging"
            " didn't include html5lib_tests_bench/js/*.js."
        ) from exc


_DOM_TREE_SERIALIZER_DECL_JS = _read_js_resource("dom_tree_serializer.js")
_DOM_TREE_SERIALIZER_JS = f"(() => {{\n{_DOM_TREE_SERIALIZER_DECL_JS}\n  return domTreeSerializer;\n}})()"

_PARSE_AND_SERIALIZE_DOCUMENT_JS = (
    "(html) => {\n"
    "  const parser = new DOMParser();\n"
    '  const doc = parser.parseFromString(String(html ?? ""), "text/html");\n'
    f"  const serialize = {_DOM_TREE_SERIALIZER_JS};\n"
    "  return serialize(doc);\n"
    "}"
)

_SERIALIZE_CURRENT_DOCUMENT_JS = (
    f"() => {{\n  const serialize = {_DOM_TREE_SERIALIZER_JS};\n  return serialize(document);\n}}"
)

_FRAGMENT_TREE_SERIALIZER_DECL_JS = _read_js_resource("fragment_tree_serializer.js")
_FRAGMENT_TREE_SERIALIZER_JS = (
    f"(() => {{\n{_FRAGMENT_TREE_SERIALIZER_DECL_JS}\n  return fragmentTreeSerializer;\n}})()"
)


## NOTE: Fragment parsing is already fast (no navigation) via `_FRAGMENT_TREE_SERIALIZER_JS`.


def _is_same_origin(url: str, *, base_url: str) -> bool:
    base = urlsplit(base_url)
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return False
    return parts.scheme == base.scheme and parts.netloc == base.netloc


@dataclass(frozen=True, slots=True)
class BrowserResult:
    tree: str
    external_requests: list[str]


class BrowserHarness:
    def __init__(self, *, browser: BrowserName, headless: bool = True):
        self._browser_name = browser
        self._headless = headless
        self._pw_cm: Any | None = None
        self._pw: Any | None = None
        self._browser_instance: Any | None = None
        self._page: Any | None = None
        self._timeout_error: type[Exception] | None = None

        self._browser_display_name: str | None = None
        self._browser_version: str | None = None

        self._current_html: str = ""
        self._base_url: str = "http://html5libtests.local/"
        self._external_network_requests: list[str] = []

    def __enter__(self) -> "BrowserHarness":
        try:
            sync_api = __import__("playwright.sync_api", fromlist=["sync_playwright", "TimeoutError"])
            sync_playwright = sync_api.sync_playwright
            self._timeout_error = sync_api.TimeoutError
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Playwright is not installed. Install with: pip install -e '.[test]'") from exc

        self._pw_cm = sync_playwright()
        self._pw = self._pw_cm.__enter__()

        browser_type, launch_kwargs, display_name = self._resolve_playwright_browser(self._pw, self._browser_name)
        self._browser_display_name = display_name
        launch_kwargs = {**launch_kwargs, "headless": self._headless}
        self._browser_instance = browser_type.launch(**launch_kwargs)
        version_attr = getattr(self._browser_instance, "version", "")
        try:
            version_value = version_attr() if callable(version_attr) else version_attr
        except Exception:
            version_value = ""
        self._browser_version = str(version_value or "")
        self._page = self._browser_instance.new_page()

        def _route(route) -> None:
            req = route.request

            # Deterministic runs: block all external network, but record attempts.
            if req.url.startswith(("http://", "https://")):
                self._external_network_requests.append(req.url)
                route.abort()
                return

            route.continue_()

        self._page.route("**/*", _route)

        # Ensure a live DOM exists for fragment parsing/evaluation.
        self._page.set_content(
            '<!doctype html><meta charset="utf-8"><title>html5lib-tests-bench</title>',
            wait_until="domcontentloaded",
            timeout=_MAX_PLAYWRIGHT_TIMEOUT_MS,
        )
        return self

    @staticmethod
    def _resolve_playwright_browser(pw: Any, browser: BrowserName) -> tuple[Any, dict[str, Any], str]:
        launch_kwargs: dict[str, Any] = {}

        if browser == "chromium":
            return pw.chromium, {**launch_kwargs}, "chromium"
        if browser == "firefox":
            return pw.firefox, {**launch_kwargs}, "firefox"
        if browser == "webkit":
            return pw.webkit, {**launch_kwargs}, "webkit"

        # Real, installed browsers via Playwright channels. These require the browser to be installed
        # on the system (Playwright does not download them).
        raise ValueError(f"Unknown browser: {browser}")

    @property
    def browser_display_name(self) -> str:
        if self._browser_display_name is None:
            return str(self._browser_name)
        return self._browser_display_name

    @property
    def browser_version(self) -> str:
        return self._browser_version or ""

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._browser_instance is not None:
                self._browser_instance.close()
        finally:
            if self._pw_cm is not None:
                self._pw_cm.__exit__(exc_type, exc, tb)

    def run_document(self, *, html: str, scripting_enabled: bool) -> BrowserResult:
        if self._page is None:
            raise RuntimeError("Harness not initialized")

        self._external_network_requests.clear()
        if scripting_enabled:
            # Script-on mode: parse as a live document.
            self._page.set_content(
                html,
                wait_until="domcontentloaded",
                timeout=_MAX_PLAYWRIGHT_TIMEOUT_MS,
            )
            tree = str(self._page.evaluate(_SERIALIZE_CURRENT_DOCUMENT_JS) or "")
        else:
            # Script-off mode: DOMParser best matches html5lib-tests' script-off expectations,
            # and avoids executing scripts.
            tree = str(self._page.evaluate(_PARSE_AND_SERIALIZE_DOCUMENT_JS, html) or "")
        return BrowserResult(tree=tree, external_requests=list(self._external_network_requests))

    def run_fragment(self, *, fragment_context: str, html: str) -> BrowserResult:
        if self._page is None:
            raise RuntimeError("Harness not initialized")

        self._external_network_requests.clear()
        tree = str(
            self._page.evaluate(_FRAGMENT_TREE_SERIALIZER_JS, {"fragmentTag": fragment_context, "html": html}) or ""
        )
        return BrowserResult(tree=tree, external_requests=list(self._external_network_requests))
