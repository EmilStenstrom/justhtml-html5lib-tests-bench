from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal
from urllib.parse import urlsplit


BrowserName = Literal["chromium", "firefox", "webkit"]

_MAX_PLAYWRIGHT_TIMEOUT_MS = 10_000


_DOM_TREE_SERIALIZER_JS = r"""
() => {
  const lines = [];
  const escapeText = (s) => {
    // Match html5lib test tree format reasonably well.
    // Use JSON escaping so newlines/tabs are visible.
    return JSON.stringify(String(s)).slice(1, -1);
  };
  const indentStr = (depth) => "  ".repeat(depth);
  const add = (depth, txt) => lines.push(`| ${indentStr(depth)}${txt}`);

  const serializeNode = (node, depth) => {
    if (!node) return;

    switch (node.nodeType) {
      case Node.DOCUMENT_TYPE_NODE: {
        const name = node.name ? String(node.name) : "";
        add(depth, `<!DOCTYPE ${name}>`.trimEnd());
        return;
      }
      case Node.ELEMENT_NODE: {
        const tag = node.tagName ? String(node.tagName).toLowerCase() : "";
        add(depth, `<${tag}>`);
        try {
          const attrs = Array.from(node.attributes || []);
          attrs.sort((a, b) => String(a.name).localeCompare(String(b.name)));
          for (const a of attrs) {
            add(depth + 1, `${a.name}="${escapeText(a.value)}"`);
          }
        } catch {
          /* ignore */
        }
        for (const child of Array.from(node.childNodes || [])) {
          serializeNode(child, depth + 1);
        }
        return;
      }
      case Node.TEXT_NODE: {
        add(depth, `"${escapeText(node.data)}"`);
        return;
      }
      case Node.COMMENT_NODE: {
        add(depth, `<!-- ${escapeText(node.data)} -->`);
        return;
      }
      default:
        return;
    }
  };

  const doc = document;
  try {
    if (doc.doctype) serializeNode(doc.doctype, 0);
  } catch {
    /* ignore */
  }

  if (doc.documentElement) {
    serializeNode(doc.documentElement, 0);
  }

  return lines.join("\n");
}
"""


_FRAGMENT_TREE_SERIALIZER_JS = r"""
(arg) => {
  const fragmentTag = arg && typeof arg === "object" ? arg.fragmentTag : undefined;
  const html = arg && typeof arg === "object" ? arg.html : undefined;
  const lines = [];
  const escapeText = (s) => JSON.stringify(String(s)).slice(1, -1);
  const indentStr = (depth) => "  ".repeat(depth);
  const add = (depth, txt) => lines.push(`| ${indentStr(depth)}${txt}`);

  const SVG_NS = "http://www.w3.org/2000/svg";
  const MATH_NS = "http://www.w3.org/1998/Math/MathML";

  const makeContextElement = (ctx) => {
    const raw = ctx ? String(ctx).trim() : "div";
    const parts = raw.split(/\s+/g).filter(Boolean);

    // html5lib-tests uses contexts like "svg desc" or "math mi".
    if (parts.length >= 2) {
      const prefix = parts[0].toLowerCase();
      const localName = parts[1];
      if (prefix === "svg") return document.createElementNS(SVG_NS, localName);
      if (prefix === "math") return document.createElementNS(MATH_NS, localName);
      // Unknown prefix: fall back to the localName as an HTML element.
      return document.createElement(localName);
    }

    return document.createElement(raw);
  };

  const serializeNode = (node, depth) => {
    if (!node) return;
    switch (node.nodeType) {
      case Node.ELEMENT_NODE: {
        const tag = node.tagName ? String(node.tagName).toLowerCase() : "";
        add(depth, `<${tag}>`);
        const attrs = Array.from(node.attributes || []);
        attrs.sort((a, b) => String(a.name).localeCompare(String(b.name)));
        for (const a of attrs) {
          add(depth + 1, `${a.name}="${escapeText(a.value)}"`);
        }
        for (const child of Array.from(node.childNodes || [])) {
          serializeNode(child, depth + 1);
        }
        return;
      }
      case Node.TEXT_NODE:
        add(depth, `"${escapeText(node.data)}"`);
        return;
      case Node.COMMENT_NODE:
        add(depth, `<!-- ${escapeText(node.data)} -->`);
        return;
      default:
        return;
    }
  };

  const contextEl = makeContextElement(fragmentTag);
  // Some fragment contexts are in foreign namespaces; parsing via Range uses
  // the HTML parsing algorithm for "contextual fragments".
  // Keep the element attached to the document to avoid edge-case differences.
  document.body.appendChild(contextEl);

  const range = document.createRange();
  range.selectNodeContents(contextEl);
  const frag = range.createContextualFragment(String(html ?? ""));

  contextEl.remove();

  for (const child of Array.from(frag.childNodes || [])) {
    serializeNode(child, 0);
  }

  return lines.join("\n");
}
"""


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

        browser_type = getattr(self._pw, self._browser_name)
        self._browser_instance = browser_type.launch(headless=self._headless)
        self._page = self._browser_instance.new_page()

        def _route(route) -> None:
            req = route.request

            if req.resource_type == "document" and req.url == self._base_url:
                route.fulfill(status=200, content_type="text/html", body=self._current_html)
                return

            # Deterministic runs: block all network, but record external attempts.
            if req.url.startswith(("http://", "https://")) and not _is_same_origin(req.url, base_url=self._base_url):
                self._external_network_requests.append(req.url)

            route.abort()

        self._page.route("**/*", _route)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._browser_instance is not None:
                self._browser_instance.close()
        finally:
            if self._pw_cm is not None:
                self._pw_cm.__exit__(exc_type, exc, tb)

    def run_document(self, *, html: str) -> BrowserResult:
        if self._page is None:
            raise RuntimeError("Harness not initialized")

        self._external_network_requests.clear()
        self._current_html = html

        self._page.goto(
            self._base_url,
            wait_until="domcontentloaded",
            timeout=_MAX_PLAYWRIGHT_TIMEOUT_MS,
        )

        tree = str(self._page.evaluate(_DOM_TREE_SERIALIZER_JS) or "")
        return BrowserResult(tree=tree, external_requests=list(self._external_network_requests))

    def run_fragment(self, *, fragment_context: str, html: str) -> BrowserResult:
        if self._page is None:
            raise RuntimeError("Harness not initialized")

        self._external_network_requests.clear()
        # Load an empty base document.
        self._current_html = "<!doctype html><meta charset=\"utf-8\"><title>html5lib-tests-bench</title>"
        self._page.goto(
            self._base_url,
            wait_until="domcontentloaded",
            timeout=_MAX_PLAYWRIGHT_TIMEOUT_MS,
        )

        tree = str(self._page.evaluate(_FRAGMENT_TREE_SERIALIZER_JS, {"fragmentTag": fragment_context, "html": html}) or "")
        return BrowserResult(tree=tree, external_requests=list(self._external_network_requests))
