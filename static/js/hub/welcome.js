/* The welcome pop-up (Liwei, 2026-11-08; backend/welcome.py).
 *
 * After the Customer Data Disclaimer: what is new in the Hub (or, with
 * nothing new, a short welcome) and where the user guide is ("User guide",
 * top right corner, #/guide). Unlike the disclaimer it can be closed any
 * way at all -- X, Escape, a click outside. It comes back at each visit
 * until "Don't show again" is ticked (Liwei, 2026-11-13), and again after
 * the next big update. As it closes, "User guide" pulses
 * and says what it is, so the way back is found by looking, not reading. */

import { escapeHtml } from "./util.js";
import { BOOK } from "./guide.js";

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
      + '<div class="hub-welcome__points">'
      + d.whats_new.map(function (p) {
          if (typeof p === "string") p = { icon: "i-check", title: "", text: p };
          var id = /^i-[a-z-]+$/.test(p.icon || "") ? p.icon : "i-check";
          return '<div class="hub-welcome__point"><span class="hub-welcome__ico">' + icon(id)
            + "</span><span>" + (p.title ? "<b>" + escapeHtml(p.title) + "</b>" : "")
            + escapeHtml(p.text || "") + "</span></div>";
        }).join("")
      + "</div>";
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
    +     '<div class="hub-welcome__guide"><span class="hub-welcome__q">' + BOOK + "</span>"
    +       "<span>The <b>User guide</b> button in the top right corner opens it any time. "
    +       "To report a problem, use <b>Get help</b> at the bottom of the menu.</span></div>"
    +     '<div class="hub-welcome__foot">'
    +       '<a class="btn-ghost hub-welcome__open" href="#/guide">Open the user guide</a>'
    +       '<button type="button" class="btn-primary-sm hub-welcome__go">'
    +         (d.kind === "whats_new" ? "Got it" : "Get started") + "</button>"
    +     "</div>"
    +     '<label class="hub-welcome__never"><input type="checkbox" class="hub-welcome__nevercb">'
    +       "Don't show again</label>"
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
    // Recorded only with "Don't show again" ticked (Liwei, 2026-11-13);
    // otherwise it comes back at the next visit. A failure only means the same.
    if (overlay.querySelector(".hub-welcome__nevercb").checked) {
      fetch("/api/welcome/seen", { method: "POST", credentials: "same-origin" }).catch(function () {});
    }
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

/* "User guide" pulses for a few seconds with a label beside it. */
function pointAtGuide() {
  var btn = document.getElementById("hubGuideBtn");
  if (!btn) return;
  btn.classList.add("hub-guide-btn--pulse");
  var tip = document.createElement("div");
  tip.className = "hub-guide-tip";
  tip.textContent = "The user guide is here";
  var r = btn.getBoundingClientRect();
  tip.style.top = (r.top + r.height / 2) + "px";
  tip.style.right = (window.innerWidth - r.left + 10) + "px";
  document.body.appendChild(tip);
  setTimeout(function () {
    btn.classList.remove("hub-guide-btn--pulse");
    tip.classList.add("is-leaving");
    setTimeout(function () { tip.remove(); }, 300);
  }, 6000);
}
