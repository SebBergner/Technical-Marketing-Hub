/* Building and escaping markup: the two helpers every page's script used to
 * carry its own copy of (Hub, Admin, Content health, Migration; one module
 * each, WS-G 2026-11-28).
 *
 * Plain ES module, no build step: imported as "../shared/dom.js". */

/* An element with an optional class and text. The text goes in as text,
 * never as markup; null and undefined leave the element empty. */
function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

/* Safe in text AND in a quoted attribute (2026-11-26). The textContent /
 * innerHTML round trip it replaced left " and ' as they were, so a title
 * with a quote could close a title="..." or data-x='...' it was put in. */
var HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function escapeHtml(text) {
  return (text == null ? "" : String(text)).replace(/[&<>"']/g, function (c) {
    return HTML_ESCAPES[c];
  });
}

export { el, escapeHtml };
