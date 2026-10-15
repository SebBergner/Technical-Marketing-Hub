/* The Hub usage tab: period, totals, the chart, the breakdown table,
 * searches and what nobody opened, with their drill-downs.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, delta, el, openSheet, tile } from "./util.js";

/* ── time ranges ──────────────────────────────────────────────────────
 *
 * Computed in the browser's own clock and sent as UTC bounds, because the
 * events are stored in UTC and "this week" is a question about where the
 * reader is sitting. Resolving it on the server would hand everyone the
 * server's week, which is nobody's.
 */
var RANGES = [
  { id: "today", label: "Today" },
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "quarter", label: "This quarter" },
  { id: "year", label: "This year" },
  { id: "all", label: "All time" }
];
var currentRange = "month";

function utcStamp(d) {
  // "YYYY-MM-DDTHH:MM:SS" with no zone, matching how the log writes them,
  // so the server's string comparison stays a comparison of like with like.
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 19);
}

function rangeBounds(id) {
  var now = new Date();
  var start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (id === "week") {
    // Monday, not Sunday: a working-week question asked by a team that
    // works Monday to Friday.
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  } else if (id === "month") {
    start = new Date(now.getFullYear(), now.getMonth(), 1);
  } else if (id === "quarter") {
    start = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);
  } else if (id === "year") {
    start = new Date(now.getFullYear(), 0, 1);
  } else if (id === "all") {
    return { since: null };
  }
  return { since: utcStamp(start) };
}

function rangeLabel() {
  for (var i = 0; i < RANGES.length; i++) {
    if (RANGES[i].id === currentRange) return RANGES[i].label;
  }
  return currentRange;
}

function renderRanges() {
  var host = $("ranges");
  host.innerHTML = "";
  RANGES.forEach(function (r) {
    var b = el("button", null, r.label);
    b.setAttribute("aria-pressed", String(r.id === currentRange));
    b.addEventListener("click", function () {
      currentRange = r.id;
      renderRanges();
      loadUsage();
    });
    host.appendChild(b);
  });
}

/* ── the chart ────────────────────────────────────────────────────────
 *
 * Hand-drawn SVG rather than a charting library: three series of daily
 * counts is not worth a dependency, and this page has no build step to
 * hide one behind.
 */
var SERIES = [
  { key: "view", label: "Detail page opened", color: "#2f8f3f" },
  { key: "preview", label: "Previewed", color: "#4b8ec4" },
  { key: "download", label: "Downloaded", color: "#b5841f" }
];

function drawChart(host, daily) {
  host.innerHTML = "";
  if (!daily || !daily.length) {
    var empty = el("p", "muted", "Nothing recorded in this window.");
    empty.style.cssText = "margin:0;font-size:13px";
    host.appendChild(empty);
    return;
  }

  var W = 900, H = 150, padL = 34, padB = 20, padT = 8;
  var max = 1;
  daily.forEach(function (d) {
    SERIES.forEach(function (s) { max = Math.max(max, d[s.key] || 0); });
  });

  var NS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("class", "chart");
  svg.setAttribute("preserveAspectRatio", "none");

  function add(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text !== undefined) n.textContent = text;
    svg.appendChild(n);
    return n;
  }

  // Two gridlines with their values, so a bar's height means a number and
  // not merely "taller than that one".
  [0, max].forEach(function (value) {
    var y = padT + (H - padT - padB) * (1 - value / max);
    add("line", { x1: padL, x2: W, y1: y, y2: y,
                  stroke: "#cbd3c2", "stroke-width": 1 });
    add("text", { x: 4, y: y + 4, fill: "#8a9682", "font-size": 10 },
        String(value));
  });

  var band = (W - padL) / daily.length;
  var barW = Math.max(1, Math.min(6, band / 4));
  daily.forEach(function (d, i) {
    SERIES.forEach(function (s, si) {
      var v = d[s.key] || 0;
      if (!v) return;
      var h = (H - padT - padB) * (v / max);
      var rect = add("rect", {
        x: padL + i * band + si * (barW + 0.5),
        y: H - padB - h, width: barW, height: h, fill: s.color, rx: 1
      });
      var title = document.createElementNS(NS, "title");
      title.textContent = d.day + " · " + s.label + ": " + v;
      rect.appendChild(title);
    });
  });

  // First and last day only: one label per day is unreadable across a year
  // and says nothing the two ends do not.
  add("text", { x: padL, y: H - 5, fill: "#8a9682", "font-size": 10 },
      daily[0].day);
  if (daily.length > 1) {
    add("text", { x: W, y: H - 5, fill: "#8a9682", "font-size": 10,
                  "text-anchor": "end" }, daily[daily.length - 1].day);
  }

  host.appendChild(svg);

  var legend = el("div", "chart-legend");
  SERIES.forEach(function (s) {
    var item = el("span");
    var sw = el("span", "swatch");
    sw.style.background = s.color;
    item.appendChild(sw);
    item.appendChild(document.createTextNode(s.label));
    legend.appendChild(item);
  });
  host.appendChild(legend);
}

function renderUsage(u) {
  $("syntheticBanner").hidden = !u.synthetic;
  var prev = u.previous;
  var vs = prev
    ? "vs previous " + rangeLabel().toLowerCase().replace(/^this /, "")
    : null;

  var totals = $("usageTotals");
  totals.innerHTML = "";
  tile(totals, u.totals.views, "Detail pages opened", vs,
    delta(u.totals.views, prev && prev.views));
  tile(totals, u.totals.previews, "Files previewed", vs,
    delta(u.totals.previews, prev && prev.previews));
  tile(totals, u.totals.downloads, "Files downloaded", vs,
    delta(u.totals.downloads, prev && prev.downloads));
  // A ratio, deliberately not called a conversion rate: with no identity in
  // the log, one person opening ten demos is indistinguishable from ten
  // people opening one, so this is downloads per page-open and must never
  // be read as "x% of visitors".
  tile(totals, u.totals.views
    ? Math.round(u.totals.downloads / u.totals.views * 100) + "%" : "—",
    "Downloads per open", "not per person — the log is anonymous");
  tile(totals, u.totals.assets_touched, "Demos touched");

  drawChart($("usageChart"), u.daily);
  renderSearches(u);
}

/* ── the breakdown table ──────────────────
 *
 * This is the shape every analytics product converges on, for the reason
 * that forced the rewrite: a fixed "top 25 demos" answers one question and
 * hides the catalogue behind it. So -- a dimension to group by, a box to
 * search, headers that sort, a pager that admits how much is off screen,
 * and a click that drills from a group into the demos inside it.
 *
 * Rolling up is the important half. "Which product got the attention" fits
 * on a screen at any catalogue size; "which demo" stops fitting somewhere
 * around the second hundred.
 */
var DIMS = [
  { id: "demo", label: "By demo", col: "Demo" },
  { id: "product", label: "By product", col: "Product" },
  { id: "segment", label: "By segment", col: "Segment" },
  { id: "source", label: "By source", col: "Source" },
  { id: "type", label: "By type", col: "Asset type" }
];
var SORTS = [
  { key: "view", label: "Opened" },
  { key: "preview", label: "Prev." },
  { key: "download", label: "Down." }
];

var bd = {
  dimension: "demo", sort: "view", q: "", offset: 0, limit: 25,
  scopeDim: null, scopeKey: null
};

function dimLabel(id) {
  for (var i = 0; i < DIMS.length; i++) if (DIMS[i].id === id) return DIMS[i];
  return DIMS[0];
}

function renderDims() {
  var host = $("breakdownDims");
  host.innerHTML = "";
  DIMS.forEach(function (d) {
    var b = el("button", null, d.label);
    b.setAttribute("aria-pressed", String(d.id === bd.dimension));
    b.addEventListener("click", function () {
      bd.dimension = d.id;
      bd.offset = 0;
      // Leaving a scope set while grouping by something else would put a
      // filtered total under an unfiltered heading.
      if (d.id !== "demo") { bd.scopeDim = null; bd.scopeKey = null; }
      renderDims();
      loadBreakdown();
    });
    host.appendChild(b);
  });
}

function loadBreakdown() {
  var b = rangeBounds(currentRange);
  var p = ["dimension=" + bd.dimension, "sort=" + bd.sort,
           "limit=" + bd.limit, "offset=" + bd.offset];
  if (b.since) p.push("since=" + encodeURIComponent(b.since));
  if (bd.q) p.push("q=" + encodeURIComponent(bd.q));
  if (bd.scopeKey) {
    p.push("scope_dim=" + encodeURIComponent(bd.scopeDim));
    p.push("scope_key=" + encodeURIComponent(bd.scopeKey));
  }
  return fetch("/api/admin/usage/breakdown?" + p.join("&"))
    .then(function (r) { return r.json(); })
    .then(renderBreakdown)
    .catch(function () {
      $("breakdownTable").textContent = "Could not load the breakdown.";
    });
}

function renderBreakdown(d) {
  var host = $("breakdownTable");
  host.innerHTML = "";

  var scope = $("breakdownScope");
  scope.innerHTML = "";
  if (bd.scopeKey) {
    var chip = el("button", "chip",
      dimLabel(bd.scopeDim).col + ": " + bd.scopeKey + " ✕");
    chip.title = "Show all demos again";
    chip.addEventListener("click", function () {
      bd.scopeDim = null;
      bd.scopeKey = null;
      bd.offset = 0;
      loadBreakdown();
    });
    scope.appendChild(chip);
  }

  if (!d.rows || !d.rows.length) {
    host.appendChild(el("p", "muted", bd.q
      ? "Nothing matching “" + bd.q + "” in this window."
      : "Nothing recorded in this window."));
    $("breakdownPager").innerHTML = "";
    return;
  }

  var t = el("table");
  var head = el("tr");
  head.appendChild(el("th", null, dimLabel(d.dimension).col));
  if (d.dimension === "demo") head.appendChild(el("th", null, "Source"));
  SORTS.forEach(function (s) {
    var th = el("th", "r sortable",
      s.label + (bd.sort === s.key ? " ▾" : ""));
    th.title = "Sort by " + s.label.toLowerCase();
    if (bd.sort === s.key) th.setAttribute("aria-sort", "descending");
    th.addEventListener("click", function () {
      bd.sort = s.key;
      bd.offset = 0;
      loadBreakdown();
    });
    head.appendChild(th);
  });
  var shareTh = el("th", "r", "Share");
  shareTh.title = "Share of the rows in this table, by the sorted column"
    + (d.dimension === "product"
      ? " — a demo listed under two products counts under both, so these "
        + "divide up attributions rather than visits."
      : ".");
  head.appendChild(shareTh);
  t.appendChild(el("thead")).appendChild(head);

  var body = el("tbody");
  d.rows.forEach(function (r) {
    var tr = el("tr", "clickable");
    tr.title = d.dimension === "demo"
      ? "Open this demo's own usage"
      : "Show the demos inside " + r.label;
    tr.addEventListener("click", function () {
      if (d.dimension === "demo") { openAssetSheet(r.key); return; }
      bd.scopeDim = d.dimension;
      bd.scopeKey = r.key;
      bd.dimension = "demo";
      bd.offset = 0;
      bd.q = "";
      $("breakdownSearch").value = "";
      renderDims();
      loadBreakdown();
    });
    tr.appendChild(el("td", null, r.label));
    if (d.dimension === "demo") {
      tr.appendChild(el("td", "faint", r.source || "—"));
    }
    SORTS.forEach(function (s) {
      tr.appendChild(el("td", "r num", r[s.key]));
    });
    var cell = el("td", "r");
    var bar = el("div", "bar");
    var fill = el("div", "bar__f");
    fill.style.width = Math.max(2, r.share) + "%";
    bar.appendChild(fill);
    cell.appendChild(bar);
    cell.appendChild(el("div", "faint num share", r.share + "%"));
    tr.appendChild(cell);
    body.appendChild(tr);
  });
  t.appendChild(body);
  // The table scrolls sideways, the page does not. Six columns do not fit a
  // phone, and a page that scrolls horizontally loses the range chips and
  // the tiles off the left edge along with them.
  var wrap = el("div", "tablewrap");
  wrap.appendChild(t);
  host.appendChild(wrap);

  renderPager(d);
}

function renderPager(d) {
  var host = $("breakdownPager");
  host.innerHTML = "";
  var first = d.total_rows ? d.offset + 1 : 0;
  var last = Math.min(d.offset + d.limit, d.total_rows);
  // Says the total, always. A page showing 25 rows without saying there are
  // 412 would be the kind of number that misleads because it looks whole.
  host.appendChild(el("span", "faint", "Showing " + first + "–" + last
    + " of " + d.total_rows.toLocaleString()
    + (d.dimension === "demo" ? " demos" : " groups") + " with activity"));

  var nav = el("div", "pager__nav");
  var back = el("button", null, "← Previous");
  back.disabled = d.offset <= 0;
  back.addEventListener("click", function () {
    bd.offset = Math.max(0, bd.offset - bd.limit);
    loadBreakdown();
  });
  var fwd = el("button", null, "Next →");
  fwd.disabled = last >= d.total_rows;
  fwd.addEventListener("click", function () {
    bd.offset = bd.offset + bd.limit;
    loadBreakdown();
  });
  nav.appendChild(back);
  nav.appendChild(fwd);
  host.appendChild(nav);
}

/* ── what nobody opened ───────────────────
 *
 * Its own panel rather than a tail of zeroes on the table above. In any
 * given week most of the catalogue is untouched, so mixed in they would
 * bury the demos that were used under hundreds of rows saying nothing.
 * Split out, the same fact turns into the more useful question: which
 * content is not earning its place.
 */
var untouchedShown = 10;

function loadUntouched() {
  var b = rangeBounds(currentRange);
  var p = ["limit=" + untouchedShown];
  if (b.since) p.push("since=" + encodeURIComponent(b.since));
  return fetch("/api/admin/usage/untouched?" + p.join("&"))
    .then(function (r) { return r.json(); })
    .then(renderUntouched)
    .catch(function () {});
}

function renderUntouched(d) {
  var host = $("usageUntouched");
  host.innerHTML = "";
  host.appendChild(el("h2", null, "Not opened at all"));
  var total = d.total_rows + d.touched;
  var lead = el("p", "muted", d.total_rows.toLocaleString() + " of "
    + total.toLocaleString() + " demos ("
    + (total ? Math.round(d.total_rows * 100 / total) : 0)
    + "%) were not opened once in this window.");
  lead.style.cssText = "font-size:12.5px;margin:6px 0 8px";
  host.appendChild(lead);

  if (!d.rows.length) {
    host.appendChild(el("p", "muted", "Every demo was opened at least once."));
    return;
  }
  var t = el("table");
  var body = el("tbody");
  d.rows.forEach(function (r) {
    var tr = el("tr", "clickable");
    tr.title = "Open this demo's own usage";
    tr.addEventListener("click", function () { openAssetSheet(r.asset_id); });
    tr.appendChild(el("td", null, r.label));
    tr.appendChild(el("td", "r faint", r.source || "—"));
    body.appendChild(tr);
  });
  t.appendChild(body);
  host.appendChild(t);

  if (d.rows.length < d.total_rows) {
    var more = el("button", null, "Show more");
    more.style.cssText = "margin-top:10px;font-size:12.5px;padding:5px 12px";
    more.addEventListener("click", function () {
      untouchedShown += 25;
      loadUntouched();
    });
    host.appendChild(more);
  }
}

function renderSearches(u) {
  var s2 = $("usageSearches");
  s2.innerHTML = "";
  s2.appendChild(el("h2", null, "Searches"));
  var zero = u.searches.zero_result || [];
  if (zero.length) {
    var lead = el("p", "muted",
      "Searched for, and found nothing — the most direct evidence there "
      + "is of what the catalogue is missing.");
    lead.style.cssText = "font-size:12.5px;margin:6px 0 4px";
    s2.appendChild(lead);
    var zt = el("table");
    var zh = el("tr");
    zh.appendChild(el("th", null, "No results for"));
    zh.appendChild(el("th", "r", "Times"));
    zt.appendChild(el("thead")).appendChild(zh);
    var zb = el("tbody");
    zero.slice(0, 8).forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", null, r.q));
      tr.appendChild(el("td", "r num", r.zero_results));
      zb.appendChild(tr);
    });
    zt.appendChild(zb);
    s2.appendChild(zt);
  }
  if ((u.searches.top || []).length) {
    var lead2 = el("p", "muted", "Most searched");
    lead2.style.cssText = "font-size:12.5px;margin:14px 0 4px";
    s2.appendChild(lead2);
    var tt = el("table");
    var tb = el("tbody");
    u.searches.top.slice(0, 8).forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", null, r.q));
      tr.appendChild(el("td", "r num", r.times));
      tb.appendChild(tr);
    });
    tt.appendChild(tb);
    s2.appendChild(tt);
  }
  if (!zero.length && !(u.searches.top || []).length) {
    s2.appendChild(el("p", "muted", "No searches recorded in this window."));
  }
}

/* ── drill-downs ───────────────────────────────────────────────────── */

function syntheticNotice() {
  var warn = el("div", "synthetic");
  warn.appendChild(el("strong", null, "Synthetic data. "));
  warn.appendChild(document.createTextNode(
    "Generated for testing; not a measurement."));
  return warn;
}

function openAssetSheet(assetId) {
  var b = rangeBounds(currentRange);
  var qs = b.since ? "?since=" + encodeURIComponent(b.since) : "";
  fetch("/api/admin/usage/asset/" + encodeURIComponent(assetId) + qs)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var body = openSheet(d.asset.title, [d.asset.type, d.asset.source,
        rangeLabel()].filter(Boolean).join(" · "));
      if (d.synthetic) body.appendChild(syntheticNotice());

      var tiles = el("div", "tiles");
      body.appendChild(tiles);
      tile(tiles, d.totals.views, "Opened");
      tile(tiles, d.totals.previews, "Previewed");
      tile(tiles, d.totals.downloads, "Downloaded");

      var chartCard = el("div", "card");
      chartCard.style.margin = "12px 0";
      body.appendChild(chartCard);
      drawChart(chartCard, d.daily);

      var files = el("div", "card");
      files.appendChild(el("h2", null, "Files people took"));
      if (!d.files.length) {
        files.appendChild(el("p", "muted",
          "No file was previewed or downloaded in this window."));
      } else {
        var t = el("table");
        var h = el("tr");
        ["File", "Kind", "Prev.", "Down."].forEach(function (x, i) {
          h.appendChild(el("th", i > 1 ? "r" : null, x));
        });
        t.appendChild(el("thead")).appendChild(h);
        var tb = el("tbody");
        d.files.forEach(function (f) {
          var tr = el("tr");
          tr.appendChild(el("td", null, f.file));
          tr.appendChild(el("td", "faint", f.kind || "—"));
          tr.appendChild(el("td", "r num", f.preview));
          tr.appendChild(el("td", "r num", f.download));
          tb.appendChild(tr);
        });
        t.appendChild(tb);
        files.appendChild(t);
      }
      body.appendChild(files);

      var link = el("a", null, "Open this demo in the catalogue →");
      link.href = "/#/asset/" + encodeURIComponent(assetId);
      link.target = "_blank";
      link.style.cssText = "display:inline-block;margin-top:12px;font-size:13px";
      body.appendChild(link);
    });
}

function loadUsage() {
  // A new window means a new population: page 4 of last month is not page 4
  // of this week, and silently keeping the offset would show an empty table
  // that looks like "no activity".
  bd.offset = 0;
  untouchedShown = 10;
  var b = rangeBounds(currentRange);
  var qs = b.since ? "?since=" + encodeURIComponent(b.since) : "";
  return Promise.all([
    fetch("/api/admin/usage" + qs)
      .then(function (r) { return r.json(); })
      .then(renderUsage),
    loadBreakdown(),
    loadUntouched()
  ]);
}

// Typing is throttled rather than sent per keystroke: every letter would be
// a full pass over the event log for a query the person has not finished.
var searchTimer = null;
$("breakdownSearch").addEventListener("input", function (e) {
  var value = e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(function () {
    bd.q = value;
    bd.offset = 0;
    loadBreakdown();
  }, 250);
});

export {
  loadUsage, renderDims, renderRanges
};
