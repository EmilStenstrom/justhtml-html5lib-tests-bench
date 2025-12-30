function fragmentTreeSerializer(arg) {
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
    const local = a && a.localName ? String(a.localName) : a && a.name ? String(a.name) : "";
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
