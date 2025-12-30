function domTreeSerializer(doc) {
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
