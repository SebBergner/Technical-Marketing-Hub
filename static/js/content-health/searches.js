/* Content health -> Searches (2026-11-11; a small table on Admin -> Hub
 * usage until then): what people searched for and found nothing or almost
 * nothing, in a period -- what the catalogue is missing, in their words.
 * How many people, never who (GET /api/content-health/searches).
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, el } from "../admin/util.js";

var RANGES = [["30d", "30 days", 30], ["90d", "90 days", 90], ["all", "All time", null]];
var range = "90d";
var hideFound = true;          // set aside words that find plenty today
var last = null;

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
  last = d;
  var host = $("srBody");
  host.innerHTML = "";
  var max = d.few_results_max;
  var rows = d.rows.filter(function (r) {
    return !hideFound || r.finds_now === null || r.finds_now <= max;
  });
  var set = d.rows.length - rows.length;
  $("srIntro").textContent = d.searches.toLocaleString() + " searches in this period; "
    + d.rows.length + " searches, words with their filters, found " + max + " demos or fewer "
    + "at least once" + (set ? " (" + set + " of them find more today and are set aside)" : "")
    + ". Worth a demo, a better title, description or keyword, or a look at how the demos "
    + "are tagged. Searches before 2026-11-12 did not record their filters.";
  if (!rows.length) { host.appendChild(el("div", "faint", "Every search found something.")); return; }
  var t = el("table");
  var hr = t.createTHead().insertRow();
  [["Searched for"], ["With filters"], ["Times", "r"], ["Nothing found", "r"], ["1–" + max + " found", "r"],
   ["Finds today", "r"], ["People", "r"], ["Last"], [""]].forEach(function (h) {
    hr.appendChild(el("th", h[1] || null, h[0]));
  });
  var tb = t.createTBody();
  rows.forEach(function (r) {
    var tr = tb.insertRow();
    tr.insertCell().textContent = r.q;
    var f = tr.insertCell();
    f.textContent = r.filters || "—";
    if (!r.filters) f.className = "faint";
    [r.times, r.zero_results, r.few_results, r.finds_now, r.people].forEach(function (n) {
      var c = tr.insertCell();
      c.className = "r num" + (n ? "" : " faint");
      c.textContent = n === null || n === undefined ? "—" : n;
    });
    tr.insertCell().textContent = r.last_at || "—";
    var a = el("a", null, "Try it");
    a.href = "/#/search/" + encodeURIComponent(r.q);   // the words; set filters there
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
  var box = $("srHideFound");
  if (box && !box.dataset.wired) {
    box.dataset.wired = "1";
    box.checked = hideFound;
    box.addEventListener("change", function () { hideFound = box.checked; if (last) render(last); });
  }
  renderRanges();
  var s = since();
  return fetch("/api/content-health/searches" + (s ? "?since=" + encodeURIComponent(s) : ""))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) render(d); });
}

export {
  loadSearches
};
