/* Content health -> Searches (2026-11-11; a small table on Admin -> Hub
 * usage until then): what people searched for and found nothing or almost
 * nothing, in a period -- what the catalogue is missing, in their words.
 * How many people, never who (GET /api/content-health/searches).
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, el } from "../admin/util.js";

var RANGES = [["30d", "30 days", 30], ["90d", "90 days", 90], ["all", "All time", null]];
var range = "90d";

function since() {
  var r = RANGES.filter(function (x) { return x[0] === range; })[0];
  if (!r || !r[2]) return "";
  return new Date(Date.now() - r[2] * 86400000).toISOString();
}

function renderRanges() {
  var host = $("srRanges");
  host.innerHTML = "";
  RANGES.forEach(function (r) {
    var b = el("button", null, r[1]);
    b.type = "button";
    b.setAttribute("aria-pressed", String(r[0] === range));
    b.addEventListener("click", function () { range = r[0]; loadSearches(); });
    host.appendChild(b);
  });
}

function render(d) {
  var host = $("srBody");
  host.innerHTML = "";
  $("srIntro").textContent = d.searches.toLocaleString() + " searches in this period; "
    + d.rows.length + " different words found " + d.few_results_max + " demos or fewer at "
    + "least once. Worth a demo, a better title or description, or a keyword.";
  if (!d.rows.length) { host.appendChild(el("div", "faint", "Every search found something.")); return; }
  var t = el("table");
  var hr = t.createTHead().insertRow();
  [["Searched for"], ["Times", "r"], ["Nothing found", "r"], ["1–" + d.few_results_max + " found", "r"],
   ["People", "r"], ["Last"], [""]].forEach(function (h) {
    hr.appendChild(el("th", h[1] || null, h[0]));
  });
  var tb = t.createTBody();
  d.rows.forEach(function (r) {
    var tr = tb.insertRow();
    tr.insertCell().textContent = r.q;
    [r.times, r.zero_results, r.few_results, r.people].forEach(function (n) {
      var c = tr.insertCell();
      c.className = "r num" + (n ? "" : " faint");
      c.textContent = n;
    });
    tr.insertCell().textContent = r.last_at || "—";
    var a = el("a", null, "Try it");
    a.href = "/#/search/" + encodeURIComponent(r.q);
    a.target = "_blank";
    a.rel = "noopener";
    a.title = "Search the Hub for this now";
    tr.insertCell().appendChild(a);
  });
  var wrap = el("div", "tablewrap");
  wrap.appendChild(t);
  host.appendChild(wrap);
}

function loadSearches() {
  renderRanges();
  var s = since();
  return fetch("/api/content-health/searches" + (s ? "?since=" + encodeURIComponent(s) : ""))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) render(d); });
}

export {
  loadSearches
};
