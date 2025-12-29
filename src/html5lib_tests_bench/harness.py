from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal
from urllib.parse import urlsplit


BrowserName = Literal["chromium", "firefox", "webkit"]

_MAX_PLAYWRIGHT_TIMEOUT_MS = 10_000


_DOM_TREE_SERIALIZER_JS = r"""
(doc) => {
  const lines = [];
  const SVG_NS = "http://www.w3.org/2000/svg";
  const MATH_NS = "http://www.w3.org/1998/Math/MathML";
  const HTML_NS = "http://www.w3.org/1999/xhtml";

  const escapeAttr = (s) => {
    // html5lib tree output is a textual format, not a string literal.
    // Preserve literal backslashes (so "\\n" stays "\\n") but escape
    // quotes and control characters for readability.
    return String(s)
      .replace(/\r/g, "\\r")
      .replace(/\n/g, "\\n")
      .replace(/\t/g, "\\t")
      .replace(/\"/g, "\\\"");
  };
  // For node data, preserve literal newlines so the output can span multiple
  // lines like the html5lib tree format.
  const escapeTextData = (s) => String(s);
  const escapeCommentData = (s) => String(s);

  const attrDisplayName = (a) => {
    const prefix = a && a.prefix ? String(a.prefix) : "";
    const local = a && a.localName ? String(a.localName) : (a && a.name ? String(a.name) : "");
    const name = a && a.name ? String(a.name) : local;
    return prefix ? `${prefix} ${local}` : name;
  };

  const formatTag = (el) => {
    const ns = el && el.namespaceURI ? String(el.namespaceURI) : "";
    const local = el && el.localName ? String(el.localName) : "";
    const name = local || (el && el.tagName ? String(el.tagName).toLowerCase() : "");
    if (ns === SVG_NS) return `svg ${name}`;
    if (ns === MATH_NS) return `math ${name}`;
    return name;
  };
  const indentStr = (depth) => "  ".repeat(depth);
  const add = (depth, txt) => lines.push(`| ${indentStr(depth)}${txt}`);

  const serializeNode = (node, depth) => {
    if (!node) return;

    switch (node.nodeType) {
      case Node.DOCUMENT_TYPE_NODE: {
        const name = node.name ? String(node.name) : "";
        const publicId = node.publicId ? String(node.publicId) : "";
        const systemId = node.systemId ? String(node.systemId) : "";
        if (publicId || systemId) {
          add(depth, `<!DOCTYPE ${name} "${publicId}" "${systemId}">`.trimEnd());
        } else {
          add(depth, `<!DOCTYPE ${name}>`.trimEnd());
        }
        return;
      }
      case Node.ELEMENT_NODE: {
        const tag = formatTag(node);
        add(depth, `<${tag}>`);
        try {
          const attrs = Array.from(node.attributes || []);
          attrs.sort((a, b) => {
            const an = attrDisplayName(a);
            const bn = attrDisplayName(b);
            if (an < bn) return -1;
            if (an > bn) return 1;
            return 0;
          });
          for (const a of attrs) {
            add(depth + 1, `${attrDisplayName(a)}="${escapeAttr(a.value)}"`);
          }
        } catch {
          /* ignore */
        }

        // html5lib-tests treats <template> content as a separate subtree.
        // In the DOM, template children live under node.content (DocumentFragment).
        try {
          const ns = node.namespaceURI ? String(node.namespaceURI) : "";
          const local = node.localName ? String(node.localName).toLowerCase() : "";
          if (ns === HTML_NS && local === "template" && node.content) {
            add(depth + 1, "content");
            for (const child of Array.from(node.content.childNodes || [])) {
              serializeNode(child, depth + 2);
            }
            return;
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
        add(depth, `"${escapeTextData(node.data)}"`);
        return;
      }
      case Node.COMMENT_NODE: {
        add(depth, `<!-- ${escapeCommentData(node.data)} -->`);
        return;
      }
      default:
        return;
    }
  };

  // Serialize the document's top-level nodes in order.
  // This matters for html5lib-tests cases with comments/text before <html>.
  for (const child of Array.from(doc.childNodes || [])) {
    serializeNode(child, 0);
  }

  return lines.join("\n");
}
"""


_PARSE_AND_SERIALIZE_DOCUMENT_JS = (
    r"""(html) => {
  const parser = new DOMParser();
  const doc = parser.parseFromString(String(html ?? ""), "text/html");
  const serialize = """ + _DOM_TREE_SERIALIZER_JS + r""";
  return serialize(doc);
}"""
)


_FRAGMENT_TREE_SERIALIZER_JS = r"""
(arg) => {
  const fragmentTag = arg && typeof arg === "object" ? arg.fragmentTag : undefined;
  const html = arg && typeof arg === "object" ? arg.html : undefined;
  const lines = [];
  const escapeAttr = (s) => {
    return String(s)
      .replace(/\r/g, "\\r")
      .replace(/\n/g, "\\n")
      .replace(/\t/g, "\\t")
      .replace(/\"/g, "\\\"");
  };
  const escapeTextData = (s) => String(s);
  const escapeCommentData = (s) => String(s);
  const indentStr = (depth) => "  ".repeat(depth);
  const add = (depth, txt) => lines.push(`| ${indentStr(depth)}${txt}`);

  const SVG_NS = "http://www.w3.org/2000/svg";
  const MATH_NS = "http://www.w3.org/1998/Math/MathML";
  const HTML_NS = "http://www.w3.org/1999/xhtml";

  const attrDisplayName = (a) => {
    const prefix = a && a.prefix ? String(a.prefix) : "";
    const local = a && a.localName ? String(a.localName) : (a && a.name ? String(a.name) : "");
    const name = a && a.name ? String(a.name) : local;
    return prefix ? `${prefix} ${local}` : name;
  };

  const formatTag = (el) => {
    const ns = el && el.namespaceURI ? String(el.namespaceURI) : "";
    const local = el && el.localName ? String(el.localName) : "";
    const name = local || (el && el.tagName ? String(el.tagName).toLowerCase() : "");
    if (ns === SVG_NS) return `svg ${name}`;
    if (ns === MATH_NS) return `math ${name}`;
    return name;
  };

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
        const tag = formatTag(node);
        add(depth, `<${tag}>`);
        const attrs = Array.from(node.attributes || []);
        attrs.sort((a, b) => {
          const an = attrDisplayName(a);
          const bn = attrDisplayName(b);
          if (an < bn) return -1;
          if (an > bn) return 1;
          return 0;
        });
        for (const a of attrs) {
          add(depth + 1, `${attrDisplayName(a)}="${escapeAttr(a.value)}"`);
        }

        try {
          const ns = node.namespaceURI ? String(node.namespaceURI) : "";
          const local = node.localName ? String(node.localName).toLowerCase() : "";
          if (ns === HTML_NS && local === "template" && node.content) {
            add(depth + 1, "content");
            for (const child of Array.from(node.content.childNodes || [])) {
              serializeNode(child, depth + 2);
            }
            return;
          }
        } catch {
          /* ignore */
        }

        for (const child of Array.from(node.childNodes || [])) {
          serializeNode(child, depth + 1);
        }
        return;
      }
      case Node.TEXT_NODE:
        add(depth, `"${escapeTextData(node.data)}"`);
        return;
      case Node.COMMENT_NODE:
        add(depth, `<!-- ${escapeCommentData(node.data)} -->`);
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

            # Deterministic runs: block all external network, but record attempts.
            if req.url.startswith(("http://", "https://")):
                self._external_network_requests.append(req.url)
                route.abort()
                return

            route.continue_()

        self._page.route("**/*", _route)

        # Ensure a live DOM exists for fragment parsing/evaluation.
        self._page.set_content(
          "<!doctype html><meta charset=\"utf-8\"><title>html5lib-tests-bench</title>",
          wait_until="domcontentloaded",
          timeout=_MAX_PLAYWRIGHT_TIMEOUT_MS,
        )
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
        # Fast path: parse/serialize in-memory via DOMParser to avoid navigation.
        tree = str(self._page.evaluate(_PARSE_AND_SERIALIZE_DOCUMENT_JS, html) or "")
        return BrowserResult(tree=tree, external_requests=list(self._external_network_requests))

    def run_fragment(self, *, fragment_context: str, html: str) -> BrowserResult:
        if self._page is None:
            raise RuntimeError("Harness not initialized")

        self._external_network_requests.clear()
        tree = str(self._page.evaluate(_FRAGMENT_TREE_SERIALIZER_JS, {"fragmentTag": fragment_context, "html": html}) or "")
        return BrowserResult(tree=tree, external_requests=list(self._external_network_requests))
