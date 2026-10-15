/* The Content dashboard tab: counts by dimension and data
 * completeness, each drilling into its demos.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, card, el, openSheet, tile, TYPE_WORD, when } from "./util.js";

/* ── Content dashboard (HLR-F1) ─────────────────────────────────────
 *
 * Serge's ask: what the Hub holds by type, product, segment, stage,
 * customer, industry and age, every chart drilling into the matching
 * demos. One ranked bar list per dimension -- a single series, so one
 * hue, with the count written on each row so it reads as a table too.
 * "Not set" is drawn in grey, last: it is the catalogue's own gap. */
var DIM_SHOWN = 8;
var contentState = { loaded: false };

function loadContent() {
  return fetch("/api/admin/content")
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(renderContent)
    .catch(function (err) {
      $("contentCharts").textContent = "The dashboard could not be loaded: " + err.message;
    });
}

function renderContent(d) {
  contentState.loaded = true;
  $("contentAsOf").textContent = d.total.toLocaleString() + " demos · counted "
    + new Date(d.as_of + "T00:00:00").toLocaleDateString();
  var totals = $("contentTotals");
  totals.innerHTML = "";
  var byType = d.dimensions.find(function (x) { return x.key === "type"; });
  (byType ? byType.buckets : []).forEach(function (b) {
    tile(totals, b.count, b.label);
  });
  renderCompleteness(d.completeness || []);
  var host = $("contentCharts");
  host.innerHTML = "";
  d.dimensions.forEach(function (dim) {
    if (dim.key === "type") return;          // the tiles above carry it
    host.appendChild(dimCard(dim));
  });
}

/* Data completeness (2026-10-14; was Catalogue health on the Overview).
 * Each field over only the types it applies to, over the same demos as the
 * charts; a row lists the demos missing it. Shown as how complete, worst
 * first, the way data-quality panels read: the number to raise. */
function renderCompleteness(rows) {
  var host = $("contentCompleteness");
  host.innerHTML = "";
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "Data completeness"));
  host.appendChild(head);
  host.appendChild(el("p", "dim-note", "How much of the catalogue has each field, "
    + "counted only where the field applies. Click a row to list the demos missing it; "
    + "fill them in SharePoint or Consensus and the next sync picks it up."));
  rows.forEach(function (c) {
    var pct = c.of ? Math.round((c.of - c.missing) / c.of * 1000) / 10 : 100;
    var r = el("button", "cmp-row");
    r.type = "button";
    var label = el("span", "cmp-row__label");
    label.appendChild(el("b", null, c.title));
    label.appendChild(el("span", null, (c.types ? c.types.join(", ") : "All types")
      + (c.note ? " · " + c.note : "")));
    r.appendChild(label);
    var bar = el("span", "cmp-bar cmp-bar--" + (pct >= 90 ? "good" : pct >= 70 ? "fair" : "poor"));
    bar.appendChild(el("span")).style.width = pct + "%";
    r.appendChild(bar);
    var n = el("span", "cmp-row__n", pct + "% complete");
    n.appendChild(el("span", null, c.missing
      ? c.missing.toLocaleString() + " of " + c.of.toLocaleString() + " missing"
      : "nothing missing"));
    r.appendChild(n);
    if (c.missing) {
      r.title = "List the " + c.missing.toLocaleString() + " demos without " + c.title.toLowerCase();
      r.addEventListener("click", function () {
        openContentSheet({ key: c.key, title: "Missing " + c.title.toLowerCase() },
                         { value: "Not set", label: "", count: c.missing });
      });
    } else {
      r.disabled = true;
    }
    host.appendChild(r);
  });
}

function dimCard(dim) {
  var c = card(dim.title);
  c.querySelector(".card-head").appendChild(el("span", "faint num", dim.of.toLocaleString()));
  var max = dim.buckets.reduce(function (m, b) { return Math.max(m, b.count); }, 0) || 1;
  var list = el("div");
  var rows = dim.buckets.map(function (b) {
    var unset = b.value === "Not set";
    var r = el("button", "dim-row" + (unset ? " dim-row--unset" : ""));
    r.type = "button";
    var pct = dim.of ? Math.round(b.count / dim.of * 100) : 0;
    r.title = b.label + ": " + b.count.toLocaleString() + " (" + pct + "% of "
      + dim.of.toLocaleString() + ") — click to list them";
    r.appendChild(el("span", "dim-row__label", b.label));
    var bar = el("span", "dim-row__bar");
    var fill = el("span");
    fill.style.width = Math.max(1, Math.round(b.count / max * 100)) + "%";
    bar.appendChild(fill);
    r.appendChild(bar);
    r.appendChild(el("span", "dim-row__n", b.count.toLocaleString()));
    r.addEventListener("click", function () { openContentSheet(dim, b); });
    list.appendChild(r);
    return r;
  });
  c.appendChild(list);
  // Long tails (customers) show the top rows; "Not set" stays visible.
  var hidden = rows.filter(function (r, i) {
    return i >= DIM_SHOWN && !r.classList.contains("dim-row--unset");
  });
  if (hidden.length) {
    hidden.forEach(function (r) { r.hidden = true; });
    var more = el("button", "dim-more", "Show " + hidden.length + " more");
    more.type = "button";
    more.addEventListener("click", function () {
      hidden.forEach(function (r) { r.hidden = false; });
      more.remove();
    });
    c.appendChild(more);
  }
  if (dim.note) c.appendChild(el("p", "dim-note", dim.note));
  return c;
}

function openContentSheet(dim, b) {
  var body = openSheet(b.label ? dim.title + ": " + b.label : dim.title,
                       b.count.toLocaleString() + " demos, newest first");
  body.textContent = "Loading…";
  fetch("/api/admin/content/assets?dim=" + encodeURIComponent(dim.key)
        + "&value=" + encodeURIComponent(b.value))
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (items) {
      body.innerHTML = "";
      var t = el("table");
      var head = t.createTHead().insertRow();
      ["Demo", "Type", "Date"].forEach(function (h) { head.appendChild(el("th", null, h)); });
      var tb = t.createTBody();
      items.forEach(function (a) {
        var tr = tb.insertRow();
        var link = el("a", null, a.title);
        link.href = "/#/asset/" + encodeURIComponent(a.id);
        link.target = "_blank";
        link.rel = "noopener";
        tr.insertCell().appendChild(link);
        tr.insertCell().textContent = TYPE_WORD[a.type] || a.type;
        var when = tr.insertCell();
        when.className = "num faint";
        when.textContent = a.uploaded_at || "—";
      });
      body.appendChild(t);
    })
    .catch(function (err) { body.textContent = "Could not load: " + err.message; });
}

export {
  contentState, loadContent
};
