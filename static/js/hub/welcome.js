/* The welcome pop-up (Liwei, 2026-11-08; backend/welcome.py).
 *
 * Once per person, after the Customer Data Disclaimer: a short welcome and
 * where the user guide is (the "?" in the top right corner, #/guide). Shown
 * again only after a big update, then as "What's new". Unlike the
 * disclaimer it can be closed any way at all -- X, Escape, a click outside
 * -- and closing it is what counts as seen. As it closes, the "?" pulses
 * and says what it is, so the way back is found by looking, not reading. */

import { escapeHtml } from "./util.js";

var POINTS = [
  ["i-search", "Find", "Search or browse every video, VDK, LDK, CAD dataset and VM."],
  ["i-play", "Open and share", "Watch, preview and download; share a link with a colleague."],
  ["i-plus", "Ask", "Missing something? Send a New Asset Inquiry."]
];

function icon(id) {
  return '<svg class="orion-ico" aria-hidden="true"><use href="#' + id + '"/></svg>';
}

export async function askWelcomeIfDue() {
  var d;
  try {
    var r = await fetch("/api/welcome", { credentials: "same-origin" });
    if (!r.ok) return;
    d = await r.json();
  } catch (e) {
    return;
  }
  if (!d.required) return;
  show(d);
}

function body(d) {
  if (d.kind === "whats_new") {
    return '<div class="hub-welcome__eyebrow">Hub update</div>'
      + '<h2 class="hub-welcome__title" id="hubWelcomeTitle">What\'s new in the Hub</h2>'
      + '<ul class="hub-welcome__new">'
      + d.whats_new.map(function (t) { return "<li>" + escapeHtml(t) + "</li>"; }).join("")
      + "</ul>";
  }
  return '<div class="hub-welcome__eyebrow">Welcome</div>'
    + '<h2 class="hub-welcome__title" id="hubWelcomeTitle">Welcome to the Technical Marketing Hub</h2>'
    + '<p class="hub-welcome__lead">One place for PTC\'s technical demo content.</p>'
    + '<div class="hub-welcome__points">'
    + POINTS.map(function (p) {
        return '<div class="hub-welcome__point"><span class="hub-welcome__ico">' + icon(p[0])
          + "</span><span><b>" + p[1] + "</b>" + p[2] + "</span></div>";
      }).join("")
    + "</div>";
}

function show(d) {
  var overlay = document.createElement("div");
  overlay.className = "hub-welcome";
  overlay.innerHTML =
      '<div class="hub-welcome__dialog" role="dialog" aria-modal="true" aria-labelledby="hubWelcomeTitle">'
    +   '<button type="button" class="hub-welcome__x" aria-label="Close">' + icon("i-x") + "</button>"
    +   '<div class="hub-welcome__band" aria-hidden="true">'
    +     '<svg class="hub-welcome__spark" viewBox="0 0 24 24" fill="currentColor">'
    +       '<path d="M14.6 1 C14.8 7.3 17.3 9.4 23 9.7 C17.3 10 14.8 12.1 14.6 18.4 C14.4 12.1 11.9 10 6.2 9.7 C11.9 9.4 14.4 7.3 14.6 1 Z"/>'
    +       '<path d="M6 12.2 C6.1 15.2 7.7 16.2 10.6 16.4 C7.7 16.6 6.1 17.6 6 20.6 C5.9 17.6 4.3 16.6 1.4 16.4 C4.3 16.2 5.9 15.2 6 12.2 Z"/>'
    +     "</svg>"
    +   "</div>"
    +   '<div class="hub-welcome__content">'
    +     body(d)
    +     '<div class="hub-welcome__guide"><span class="hub-welcome__q">?</span>'
    +       "<span>The <b>user guide</b> is always one click away: the <b>?</b> in the "
    +       "top right corner.</span></div>"
    +     '<div class="hub-welcome__foot">'
    +       '<a class="btn-ghost hub-welcome__open" href="#/guide">Open the user guide</a>'
    +       '<button type="button" class="btn-primary-sm hub-welcome__go">Get started</button>'
    +     "</div>"
    +   "</div>"
    + "</div>";
  document.body.appendChild(overlay);

  var closed = false;
  function close() {
    if (closed) return;
    closed = true;
    overlay.classList.add("is-leaving");
    setTimeout(function () { overlay.remove(); }, 160);
    document.removeEventListener("keydown", onKey, true);
    // Seen however it was closed; a failure only means it shows next time.
    fetch("/api/welcome/seen", { method: "POST", credentials: "same-origin" }).catch(function () {});
    pointAtGuide();
  }
  function onKey(e) { if (e.key === "Escape") close(); }
  document.addEventListener("keydown", onKey, true);
  overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
  overlay.querySelector(".hub-welcome__x").addEventListener("click", close);
  overlay.querySelector(".hub-welcome__go").addEventListener("click", close);
  overlay.querySelector(".hub-welcome__open").addEventListener("click", close);
  overlay.querySelector(".hub-welcome__go").focus();
}

/* The "?" pulses for a few seconds with a label beside it. */
function pointAtGuide() {
  var btn = document.getElementById("hubGuideBtn");
  if (!btn) return;
  btn.classList.add("hub-guide-btn--pulse");
  var tip = document.createElement("div");
  tip.className = "hub-guide-tip";
  tip.textContent = "The user guide is here";
  document.body.appendChild(tip);
  setTimeout(function () {
    btn.classList.remove("hub-guide-btn--pulse");
    tip.classList.add("is-leaving");
    setTimeout(function () { tip.remove(); }, 300);
  }, 6000);
}
