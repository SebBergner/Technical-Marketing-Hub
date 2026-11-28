/* One way for every modal to behave at the keyboard (WS-G, 2026-11-28).
 *
 * Each modal still shows and hides itself as it always has (a class, a
 * `hidden`, an element added and removed); this module only adds what a
 * modal owes keyboard and screen-reader users, which until now some had
 * and most did not:
 *
 *  - role="dialog", aria-modal="true" and a label;
 *  - focus moves into it when it opens, and back to whatever opened it
 *    when it closes;
 *  - Tab and Shift+Tab go round inside it and never reach the page behind;
 *  - Esc closes it (or, for one that must be answered, does nothing).
 *
 * Usage:
 *
 *   var d = dialog(box, { labelledBy: "titleId", onEscape: close });
 *   ...show the box..., then d.open();
 *   ...hide the box..., then d.close();
 *
 * Dialogs stack: one opened over another (a frame picker over the editor)
 * takes the keyboard until it closes, then the one below has it again. */

var FOCUSABLE = [
  "a[href]", "area[href]", "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])", "select:not([disabled])",
  "textarea:not([disabled])", "iframe", "audio[controls]", "video[controls]",
  "[contenteditable]:not([contenteditable=false])", "[tabindex]:not([tabindex='-1'])"
].join(",");

var stack = [];

function shown(n) {
  return !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)
    && getComputedStyle(n).visibility !== "hidden";
}

function focusables(box) {
  return Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), shown);
}

function focusInto(d) {
  var target = typeof d.opts.initialFocus === "function" ? d.opts.initialFocus()
    : typeof d.opts.initialFocus === "string" ? d.box.querySelector(d.opts.initialFocus)
    : d.opts.initialFocus;
  if (!target || !shown(target)) target = focusables(d.box)[0];
  if (!target) {
    if (!d.box.hasAttribute("tabindex")) d.box.tabIndex = -1;
    target = d.box;
  }
  target.focus();
}

function top() { return stack[stack.length - 1]; }

function onKeydown(e) {
  var d = top();
  if (!d) return;
  if (e.key === "Escape" || e.key === "Esc") {
    // A control inside that already used Esc (a dropdown closing itself)
    // said so with preventDefault: the dialog stays.
    if (e.defaultPrevented) return;
    e.preventDefault();
    e.stopPropagation();
    if (d.opts.onEscape === null) return;          // must be answered
    (d.opts.onEscape || d.close)();
    return;
  }
  if (e.key !== "Tab") return;
  var list = focusables(d.box);
  if (!list.length) { e.preventDefault(); focusInto(d); return; }
  var first = list[0], last = list[list.length - 1];
  var active = document.activeElement;
  var inside = d.box.contains(active);
  if (e.shiftKey && (!inside || active === first || active === d.box)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (!inside || active === last)) {
    e.preventDefault();
    first.focus();
  }
}

/* Focus that lands outside the top dialog -- tabbing out of an iframe in
 * it, a script focusing something behind -- is brought back. */
function onFocusin(e) {
  var d = top();
  if (!d || d.box.contains(e.target)) return;
  focusInto(d);
}

function listen(on) {
  var method = on ? "addEventListener" : "removeEventListener";
  document[method]("keydown", onKeydown);
  document[method]("focusin", onFocusin);
}

/* box: the element that IS the dialog (not its backdrop).
 * opts:
 *   label       its name, when it has no visible title;
 *   labelledBy  the id of its visible title (preferred);
 *   onEscape    what Esc does (default: close); null: nothing;
 *   initialFocus the element (or selector, or function returning one) to
 *               focus on open; default the first focusable inside. */
function dialog(box, opts) {
  opts = opts || {};
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  if (opts.labelledBy) box.setAttribute("aria-labelledby", opts.labelledBy);
  else if (opts.label) box.setAttribute("aria-label", opts.label);

  var d = { box: box, opts: opts, opener: null };
  d.isOpen = function () { return stack.indexOf(d) >= 0; };
  d.open = function (opener) {
    if (d.isOpen()) { focusInto(d); return d; }
    var active = opener || document.activeElement;
    d.opener = active && active !== document.body && !box.contains(active) ? active : null;
    if (!stack.length) listen(true);
    stack.push(d);
    focusInto(d);
    return d;
  };
  d.close = function () {
    var at = stack.indexOf(d);
    if (at < 0) return d;
    stack.splice(at, 1);
    if (!stack.length) listen(false);
    var back = d.opener;
    d.opener = null;
    // Only to an opener still on the page and still reachable: a demo
    // page's button rebuilt while the dialog was open is not.
    if (back && back.isConnected && shown(back) && typeof back.focus === "function") {
      back.focus();
    } else if (stack.length) {
      focusInto(top());
    }
    return d;
  };
  return d;
}

export { dialog };
