/* The Customer Data Disclaimer (Elio, 2026-11-05; backend/disclaimer.py).
 *
 * Asked once on any page before the Hub is used, then again twelve months
 * after the last Accept, or when the text changes. One button, "Accept": no
 * close, no Escape, no click outside -- the Hub is used on these terms or not
 * at all. The acceptance is recorded on the server against the sign-in, so it
 * follows the person to every browser, and Admin -> Users & groups lists it. */

import { escapeHtml } from "./util.js";

/* Resolves once the person may use the Hub: at once if nothing is due,
 * else on Accept. The welcome pop-up (welcome.js) waits for it. */
export async function askDisclaimerIfDue() {
  var d;
  try {
    var r = await fetch("/api/disclaimer", { credentials: "same-origin" });
    if (!r.ok) return;                 // signed out, or an older server: never block
    d = await r.json();
  } catch (e) {
    return;
  }
  if (!d.required) return;
  await new Promise(function (done) { show(d, done); });
}

function show(d, done) {
  var overlay = document.createElement("div");
  overlay.className = "hub-disclaimer";
  overlay.innerHTML =
      '<div class="hub-disclaimer__dialog" role="dialog" aria-modal="true" aria-labelledby="hubDisclaimerTitle">'
    +   '<h2 class="hub-disclaimer__title" id="hubDisclaimerTitle">' + escapeHtml(d.title) + "</h2>"
    +   '<div class="hub-disclaimer__body">'
    +     "<p>" + escapeHtml(d.intro) + "</p>"
    +     "<ul>" + d.terms.map(function (t) { return "<li>" + escapeHtml(t) + "</li>"; }).join("") + "</ul>"
    +   "</div>"
    +   '<div class="hub-disclaimer__foot">'
    +     '<span class="hub-disclaimer__status" role="status"></span>'
    +     '<button type="button" class="hub-disclaimer__accept">Accept</button>'
    +   "</div>"
    + "</div>";
  document.body.appendChild(overlay);
  document.body.classList.add("hub-disclaimer-open");

  var button = overlay.querySelector(".hub-disclaimer__accept");
  var status = overlay.querySelector(".hub-disclaimer__status");
  // Keyboard focus stays inside: Tab and Shift+Tab land on Accept, Escape
  // does nothing.
  overlay.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); }
    if (e.key === "Tab") { e.preventDefault(); button.focus(); }
  }, true);
  button.addEventListener("click", function () {
    button.disabled = true;
    status.textContent = "Saving…";
    fetch("/api/disclaimer/accept", { method: "POST", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        overlay.remove();
        document.body.classList.remove("hub-disclaimer-open");
        if (done) done();
      })
      .catch(function (err) {
        button.disabled = false;
        status.textContent = "Not saved (" + err.message + "). Please try again.";
      });
  });
  button.focus();
}
