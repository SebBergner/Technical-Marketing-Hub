/* The Dashboard's library half and its CSV exports (Serge, 2026-10-23).
 *
 * Hub activity said how the Hub is used; Serge wanted the library beside
 * it -- how much of each kind there is, by product, segment, language and
 * age, month by month -- as standard charts that can go straight into a
 * deck, so nobody has to ask for an extract. Every card exports its own
 * numbers as CSV (Elio). activity.js lays the page out; this draws the
 * pieces it does not already have.
 *
 * One hue throughout: each chart is a single series (magnitude), so colour
 * says nothing a bar's length does not. Values are always printed, so no
 * chart relies on hover alone. */

import { TYPE_LABELS } from "./util.js";

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/* ------------------------------------------------------------------ CSV */

function csvCell(value) {
  var s = String(value == null ? "" : value);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function downloadCsv(name, header, rows) {
  var lines = [header.map(csvCell).join(",")].concat(rows.map(function (r) {
    return r.map(csvCell).join(",");
  }));
  var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  var link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name + "-" + new Date().toISOString().slice(0, 10) + ".csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
}

/* A card's heading row: title, a line under it, and its CSV button. */
function card(title, sub, csv) {
  var c = el("div", "hub-act__card");
  var head = el("div", "hub-dash__head");
  var words = el("div");
  words.appendChild(el("h3", null, title));
  if (sub) words.appendChild(el("div", "hub-act__sub", sub));
  head.appendChild(words);
  if (csv) {
    var b = el("button", "hub-dash__csv", "CSV");
    b.type = "button";
    b.title = "Download these numbers as CSV";
    b.addEventListener("click", csv);
    head.appendChild(b);
  }
  c.appendChild(head);
  return c;
}

/* ----------------------------------------------------------- bar lists */

/* One ranked bar per value: label, bar, count -- the count printed, the
 * share on hover. */
function barList(buckets, total) {
  var max = Math.max.apply(null, buckets.map(function (b) { return b.count; }).concat([1]));
  var list = el("div", "hub-dash__bars");
  buckets.forEach(function (b) {
    var row = el("div", "hub-dash__bar-row" + (b.value === "Not set" ? " is-unset" : ""));
    row.title = b.label + ": " + b.count.toLocaleString()
      + (total ? " (" + Math.round(b.count * 100 / total) + "%)" : "");
    row.appendChild(el("span", "hub-dash__bar-label", b.label));
    var track = el("span", "hub-dash__bar-track");
    var fill = el("span", "hub-dash__bar-fill");
    fill.style.width = Math.max(b.count ? 1.5 : 0, b.count * 100 / max) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("span", "hub-dash__bar-n r", b.count.toLocaleString()));
    list.appendChild(row);
  });
  return list;
}

function dimensionCard(dim) {
  var c = card(dim.title, (dim.note ? dim.note + " " : "") + dim.of.toLocaleString() + " items.",
    function () {
      downloadCsv("hub-" + dim.key, [dim.title, "Count"],
                  dim.buckets.map(function (b) { return [b.label, b.count]; }));
    });
  c.appendChild(barList(dim.buckets, dim.of));
  return c;
}

/* ------------------------------------------------------ month by month */

var MONTH_TYPES = ["video", "ldk", "vdk", "cad_model", "vm"];

function monthTotal(m) {
  return MONTH_TYPES.reduce(function (s, t) { return s + (m[t] || 0); }, 0);
}

function monthLabel(key, long) {
  var d = new Date(key + "-01T00:00:00");
  return d.toLocaleDateString("en-GB", long ? { month: "long", year: "numeric" }
                                            : { month: "short" });
}

/* Columns, one per month; the breakdown by type on hover and in the
 * table beneath, so it is readable without the hover too. */
function monthChart(months) {
  var max = Math.max.apply(null, months.map(monthTotal).concat([1]));
  var wrap = el("div", "hub-dash__months");
  months.forEach(function (m, i) {
    var total = monthTotal(m);
    var col = el("div", "hub-dash__month");
    col.title = monthLabel(m.month, true) + ": " + total + "\n" + MONTH_TYPES
      .filter(function (t) { return m[t]; })
      .map(function (t) { return (TYPE_LABELS[t] || t) + " " + m[t]; }).join(", ");
    col.appendChild(el("span", "hub-dash__month-n", total ? String(total) : ""));
    var bar = el("span", "hub-dash__month-bar");
    bar.style.height = (total * 100 / max) + "%";
    col.appendChild(bar);
    // Labels on Jan, Apr, Jul and Oct; January and the first month carry
    // the year in full ("Jan 2025"), so "Nov 24" is never read as a day.
    var month = Number(m.month.slice(5));
    var withYear = month === 1 || i === 0;
    var label = month % 3 === 1 || i === 0
      ? monthLabel(m.month) + (withYear ? " " + m.month.slice(0, 4) : "")
      : "";
    col.appendChild(el("span", "hub-dash__month-x", label));
    wrap.appendChild(col);
  });
  return wrap;
}

function monthTable(months) {
  var details = el("details");
  details.appendChild(el("summary", null, "Show as a table"));
  var table = el("table");
  var head = table.insertRow();
  ["Month"].concat(MONTH_TYPES.map(function (t) { return TYPE_LABELS[t] || t; }), ["Total"])
    .forEach(function (h, i) { var th = el("th", i ? "r" : null, h); head.appendChild(th); });
  months.slice().reverse().forEach(function (m) {
    var tr = table.insertRow();
    tr.appendChild(el("td", null, monthLabel(m.month, true)));
    MONTH_TYPES.forEach(function (t) { tr.appendChild(el("td", "r", String(m[t] || 0))); });
    tr.appendChild(el("td", "r", String(monthTotal(m))));
  });
  details.appendChild(table);
  return details;
}

/* ------------------------------------------------------------ the half */

/* The library section: a tile per type, then the charts. */
function renderLibrary(host, d) {
  var section = el("div", "hub-dash__section");
  section.appendChild(el("h2", "hub-dash__h", "Library"));
  section.appendChild(el("div", "hub-act__sub", "What the Hub holds today: "
    + d.total.toLocaleString() + " items. Click a type to browse it."));

  var tiles = el("div", "hub-dash__tiles");
  d.types.forEach(function (t) {
    var tile = el("a", "hub-act__card hub-dash__tile");
    tile.href = "/?type=" + encodeURIComponent(t.type);
    tile.appendChild(el("div", "hub-act__label", t.label));
    tile.appendChild(el("div", "hub-act__n", t.count.toLocaleString()));
    tiles.appendChild(tile);
  });
  section.appendChild(tiles);

  var grid = el("div", "hub-dash__grid");
  d.dimensions.filter(function (x) { return x.key !== "type"; }).forEach(function (dim) {
    grid.appendChild(dimensionCard(dim));
  });
  section.appendChild(grid);

  var months = card("Content by month",
    "Items per month over the last two years, by each item's date: its publication date "
    + "where one is stated, otherwise when its files were last updated.",
    function () {
      downloadCsv("hub-content-by-month",
        ["Month"].concat(MONTH_TYPES.map(function (t) { return TYPE_LABELS[t] || t; }), ["Total"]),
        d.by_month.map(function (m) {
          return [m.month].concat(MONTH_TYPES.map(function (t) { return m[t] || 0; }), [monthTotal(m)]);
        }));
    });
  months.appendChild(monthChart(d.by_month));
  months.appendChild(monthTable(d.by_month));
  section.appendChild(months);
  host.appendChild(section);
}

/* Usage per type for the period: comparable at a glance. */
function usageByTypeCard(rows, period) {
  var c = card("Usage by asset type", "Opened and downloaded by PTC people, last " + period
    + ". Shows which kinds of content get used.", function () {
    downloadCsv("hub-usage-by-type", ["Type", "Views and previews", "Downloads", "Items used"],
      rows.map(function (r) { return [TYPE_LABELS[r.type] || r.type, r.views, r.downloads, r.demos]; }));
  });
  if (!rows.length) {
    c.appendChild(el("div", "hub-act__empty", "Nothing was opened in this period."));
    return c;
  }
  c.appendChild(barList(rows.map(function (r) {
    return { value: r.type, label: (TYPE_LABELS[r.type] || r.type) + " · " + r.demos + " used",
             count: r.views + r.downloads };
  })));
  return c;
}

export { downloadCsv, renderLibrary, usageByTypeCard };
