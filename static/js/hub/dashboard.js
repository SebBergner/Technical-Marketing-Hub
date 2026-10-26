/* The Dashboard's Library tab and its CSV exports (Serge, 2026-10-23).
 *
 * Hub activity said how the Hub is used; Serge wanted the library beside
 * it -- how much of each kind there is, by product, segment, language and
 * age, month by month -- as standard charts that can go straight into a
 * deck, so nobody has to ask for an extract. Every card exports its own
 * numbers as CSV (Elio). activity.js lays the tabs out; this draws them.
 *
 * Colour (2026-10-26, Liwei: "more eye-catching"): each asset type keeps one
 * colour everywhere -- the type donut, the month columns, usage by type --
 * from the dataviz reference palette's first five categorical slots
 * (--viz-1..5 in hub.css, validated against the Hub's light and dark
 * surfaces). Segments take the same slots in their own donut; "Not set" is
 * always neutral grey. Video age is one blue stepped light to dark
 * (--viz-age-1..5, validated as an ordinal ramp). Three light-mode slots sit
 * below 3:1 on white, so every chart prints its numbers beside the marks
 * and the month chart has a table: nothing relies on colour or hover. */

import { TYPE_LABELS } from "./util.js";
import { navMarkHtml } from "./nav.js";

var TYPE_ORDER = ["video", "ldk", "vdk", "cad_model", "vm"];
var TYPE_COLOR = { video: 1, ldk: 2, vdk: 3, cad_model: 4, vm: 5 };

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function svgEl(tag, attrs) {
  var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
  return n;
}

function pct(n, of) { return of ? Math.round(n * 100 / of) + "%" : ""; }

function typeLabel(t) { return TYPE_LABELS[t] || t; }

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
  var c = el("div", "hub-act__card hub-dash__card");
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

/* ------------------------------------------------------------- tooltip */

/* One floating readout per card, placed over whatever mark is hovered. */
function tipFor(cardEl) {
  var tip = cardEl.querySelector(".hub-dash__tip");
  if (!tip) {
    tip = el("div", "hub-dash__tip");
    tip.hidden = true;
    cardEl.appendChild(tip);
  }
  return tip;
}

function hoverTip(cardEl, mark, lines) {
  mark.addEventListener("mouseenter", function () {
    var tip = tipFor(cardEl);
    tip.innerHTML = "";
    tip.appendChild(el("b", null, lines[0]));
    lines.slice(1).forEach(function (l) { tip.appendChild(el("div", null, l)); });
    tip.hidden = false;
    var box = cardEl.getBoundingClientRect(), r = mark.getBoundingClientRect();
    tip.style.left = (r.left - box.left + r.width / 2) + "px";
    tip.style.top = (r.top - box.top) + "px";
  });
  mark.addEventListener("mouseleave", function () { tipFor(cardEl).hidden = true; });
}

/* --------------------------------------------------------------- donut */

/* A ring of slices with a 2px gap between them, the total in the middle,
 * and a legend that names every slice with its count and share. */
function donut(cardEl, slices, total, centreLabel) {
  var wrap = el("div", "hub-dash__donut");
  var size = 168, r = 70, w = 22, c = 2 * Math.PI * r;
  var svg = svgEl("svg", { viewBox: "0 0 " + size + " " + size, role: "img",
                           "aria-label": centreLabel + ": " + total });
  svg.appendChild(svgEl("circle", { cx: size / 2, cy: size / 2, r: r, fill: "none",
                                    class: "hub-dash__donut-track", "stroke-width": w }));
  var at = 0, gap = slices.filter(function (s) { return s.count; }).length > 1 ? 2 : 0;
  slices.forEach(function (s) {
    if (!s.count) return;
    var len = c * s.count / total;
    var drawn = Math.max(len - gap, 0.5);
    var arc = svgEl("circle", {
      cx: size / 2, cy: size / 2, r: r, fill: "none", "stroke-width": w,
      class: "hub-dash__slice " + s.cls,
      "stroke-dasharray": drawn + " " + (c - drawn),
      "stroke-dashoffset": String(-at),
      transform: "rotate(-90 " + size / 2 + " " + size / 2 + ")"
    });
    hoverTip(cardEl, arc, [s.label, s.count.toLocaleString() + " · " + pct(s.count, total)]);
    svg.appendChild(arc);
    at += len;
  });
  var mid = svgEl("text", { x: size / 2, y: size / 2 - 2, class: "hub-dash__donut-n",
                            "text-anchor": "middle" });
  mid.textContent = total.toLocaleString();
  var cap = svgEl("text", { x: size / 2, y: size / 2 + 17, class: "hub-dash__donut-cap",
                            "text-anchor": "middle" });
  cap.textContent = centreLabel;
  svg.appendChild(mid);
  svg.appendChild(cap);
  wrap.appendChild(svg);

  var legend = el("ul", "hub-dash__legend");
  slices.forEach(function (s) {
    var li = el("li");
    var name = s.href ? el("a", null, s.label) : el("span", null, s.label);
    if (s.href) name.href = s.href;
    li.appendChild(el("span", "hub-dash__swatch " + s.cls));
    li.appendChild(name);
    li.appendChild(el("span", "hub-dash__legend-n", s.count.toLocaleString()));
    li.appendChild(el("span", "hub-dash__legend-p", pct(s.count, total)));
    legend.appendChild(li);
  });
  wrap.appendChild(legend);
  return wrap;
}

/* ------------------------------------------------------------ bar lists */

/* Ranked bars: label (with the product's own mark where there is one),
 * bar, count. One hue unless the rows are types: the length is the message. */
function barList(cardEl, buckets, total, opts) {
  opts = opts || {};
  var max = Math.max.apply(null, buckets.map(function (b) { return b.count; }).concat([1]));
  var list = el("div", "hub-dash__bars" + (opts.thick ? " is-thick" : ""));
  buckets.forEach(function (b) {
    var row = el("div", "hub-dash__bar-row" + (b.value === "Not set" ? " is-unset" : ""));
    var label = el("span", "hub-dash__bar-label");
    if (opts.marks && b.value !== "Not set") label.innerHTML = navMarkHtml(b.value);
    label.appendChild(document.createTextNode(b.label));
    row.appendChild(label);
    var track = el("span", "hub-dash__bar-track");
    var fill = el("span", "hub-dash__bar-fill" + (b.cls ? " " + b.cls : ""));
    fill.style.width = Math.max(b.count ? 1.5 : 0, b.count * 100 / max) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("span", "hub-dash__bar-n", b.count.toLocaleString()));
    hoverTip(cardEl, track, [b.label, b.count.toLocaleString()
      + (total ? " · " + pct(b.count, total) : "") + (b.note ? " · " + b.note : "")]);
    list.appendChild(row);
  });
  return list;
}

/* ------------------------------------------------------------ age strip */

/* Video age as one strip, newest to oldest, light to dark, each band
 * named with its count in the legend underneath. */
function ageStrip(cardEl, buckets, total) {
  var wrap = el("div", "hub-dash__age");
  var strip = el("div", "hub-dash__strip");
  var dated = buckets.filter(function (b) { return b.value !== "Not set"; });
  dated.forEach(function (b, i) {
    if (!b.count) return;
    var seg = el("span", "hub-dash__strip-seg hub-dash__age-" + (i + 1));
    seg.style.flexGrow = String(b.count);
    hoverTip(cardEl, seg, [b.label, b.count.toLocaleString() + " videos · " + pct(b.count, total)]);
    strip.appendChild(seg);
  });
  wrap.appendChild(strip);
  var legend = el("ul", "hub-dash__legend hub-dash__legend--row");
  dated.forEach(function (b, i) {
    var li = el("li");
    li.appendChild(el("span", "hub-dash__swatch hub-dash__age-" + (i + 1)));
    li.appendChild(el("span", null, b.label));
    li.appendChild(el("span", "hub-dash__legend-n", b.count.toLocaleString()));
    li.appendChild(el("span", "hub-dash__legend-p", pct(b.count, total)));
    legend.appendChild(li);
  });
  wrap.appendChild(legend);
  return wrap;
}

/* ------------------------------------------------------ month by month */

function monthTotal(m) {
  return TYPE_ORDER.reduce(function (s, t) { return s + (m[t] || 0); }, 0);
}

function monthLabel(key, long) {
  var d = new Date(key + "-01T00:00:00");
  return d.toLocaleDateString("en-US", long ? { month: "long", year: "numeric" }
                                            : { month: "short" });
}

/* Columns stacked by type, in the type donut's colours, a 2px gap between
 * the parts; the breakdown on hover and in the table beneath. */
function monthChart(cardEl, months) {
  var max = Math.max.apply(null, months.map(monthTotal).concat([1]));
  var legend = el("ul", "hub-dash__legend hub-dash__legend--row");
  TYPE_ORDER.forEach(function (t) {
    var li = el("li");
    li.appendChild(el("span", "hub-dash__swatch hub-dash__c" + TYPE_COLOR[t]));
    li.appendChild(el("span", null, typeLabel(t)));
    legend.appendChild(li);
  });
  var wrap = el("div", "hub-dash__months");
  months.forEach(function (m, i) {
    var total = monthTotal(m);
    var col = el("div", "hub-dash__month");
    col.appendChild(el("span", "hub-dash__month-n", total ? String(total) : ""));
    var stack = el("span", "hub-dash__month-stack");
    stack.style.height = (total * 100 / max) + "%";
    TYPE_ORDER.forEach(function (t) {
      if (!m[t]) return;
      var part = el("span", "hub-dash__month-part hub-dash__c" + TYPE_COLOR[t]);
      part.style.flexGrow = String(m[t]);
      stack.appendChild(part);
    });
    col.appendChild(stack);
    hoverTip(cardEl, stack, [monthLabel(m.month, true) + ": " + total].concat(
      TYPE_ORDER.filter(function (t) { return m[t]; })
        .map(function (t) { return typeLabel(t) + ": " + m[t]; })));
    // Labels on Jan, Apr, Jul and Oct; January and the first month carry
    // the year in full ("Jan 2025").
    var month = Number(m.month.slice(5));
    var withYear = month === 1 || i === 0;
    col.appendChild(el("span", "hub-dash__month-x", month % 3 === 1 || i === 0
      ? monthLabel(m.month) + (withYear ? " " + m.month.slice(0, 4) : "") : ""));
    wrap.appendChild(col);
  });
  var box = el("div");
  box.appendChild(legend);
  box.appendChild(wrap);
  return box;
}

function monthTable(months) {
  var details = el("details");
  details.appendChild(el("summary", null, "Show as a table"));
  var table = el("table");
  var head = table.insertRow();
  ["Month"].concat(TYPE_ORDER.map(typeLabel), ["Total"])
    .forEach(function (h, i) { head.appendChild(el("th", i ? "r" : null, h)); });
  months.slice().reverse().forEach(function (m) {
    var tr = table.insertRow();
    tr.appendChild(el("td", null, monthLabel(m.month, true)));
    TYPE_ORDER.forEach(function (t) { tr.appendChild(el("td", "r", String(m[t] || 0))); });
    tr.appendChild(el("td", "r", String(monthTotal(m))));
  });
  details.appendChild(table);
  return details;
}

/* -------------------------------------------------------------- the tab */

function dim(d, key) {
  return (d.dimensions || []).filter(function (x) { return x.key === key; })[0];
}

function csvOf(x) {
  return function () {
    downloadCsv("hub-" + x.key, [x.title, "Count"],
                x.buckets.map(function (b) { return [b.label, b.count]; }));
  };
}

function renderLibrary(host, d) {
  host.appendChild(el("div", "hub-act__sub hub-dash__intro", "What the Hub holds today: "
    + d.total.toLocaleString() + " items."));

  // ── type and segment, as rings
  var top = el("div", "hub-dash__grid");
  var types = card("By type", "Click a type to browse it.", function () {
    downloadCsv("hub-type", ["Type", "Count"], d.types.map(function (t) { return [t.label, t.count]; }));
  });
  types.appendChild(donut(types, d.types.map(function (t) {
    return { label: t.label, count: t.count, cls: "hub-dash__c" + TYPE_COLOR[t.type],
             href: "/?type=" + encodeURIComponent(t.type) };
  }), d.total, "items"));
  top.appendChild(types);

  var seg = dim(d, "segment");
  if (seg) {
    var segCard = card("By segment", seg.of.toLocaleString() + " items.", csvOf(seg));
    var slot = 0;
    segCard.appendChild(donut(segCard, seg.buckets.map(function (b) {
      var unset = b.value === "Not set";
      return { label: b.label, count: b.count,
               cls: unset ? "hub-dash__unset" : "hub-dash__c" + Math.min(++slot, 5) };
    }), seg.of, "items"));
    top.appendChild(segCard);
  }
  host.appendChild(top);

  // ── products and languages, as bars
  var mid = el("div", "hub-dash__grid");
  var prod = dim(d, "product");
  if (prod) {
    var p = card("By product", prod.note, csvOf(prod));
    p.appendChild(barList(p, prod.buckets, prod.of, { marks: true, thick: true }));
    mid.appendChild(p);
  }
  var lang = dim(d, "language");
  if (lang) {
    var l = card("By language", lang.of.toLocaleString() + " items.", csvOf(lang));
    l.appendChild(barList(l, lang.buckets, lang.of, { thick: true }));
    mid.appendChild(l);
  }
  host.appendChild(mid);

  // ── how old the videos are
  var age = dim(d, "age");
  if (age) {
    var a = card("How old the videos are", age.note, csvOf(age));
    a.appendChild(ageStrip(a, age.buckets, age.of));
    host.appendChild(a);
  }

  // ── month by month
  var months = card("Content by month",
    "Items per month over the last two years, by each item's date: its publication date "
    + "where one is stated, otherwise when its files were last updated.",
    function () {
      downloadCsv("hub-content-by-month", ["Month"].concat(TYPE_ORDER.map(typeLabel), ["Total"]),
        d.by_month.map(function (m) {
          return [m.month].concat(TYPE_ORDER.map(function (t) { return m[t] || 0; }), [monthTotal(m)]);
        }));
    });
  months.appendChild(monthChart(months, d.by_month));
  months.appendChild(monthTable(d.by_month));
  host.appendChild(months);
}

/* Usage per type for the period, each type in its own colour. */
function usageByTypeCard(rows, period) {
  var c = card("Usage by asset type", "Opened and downloaded by PTC people, last " + period
    + ". Shows which kinds of content get used.", function () {
    downloadCsv("hub-usage-by-type", ["Type", "Views and previews", "Downloads", "Items used"],
      rows.map(function (r) { return [typeLabel(r.type), r.views, r.downloads, r.demos]; }));
  });
  if (!rows.length) {
    c.appendChild(el("div", "hub-act__empty", "Nothing was opened in this period."));
    return c;
  }
  c.appendChild(barList(c, rows.map(function (r) {
    return { value: r.type, label: typeLabel(r.type), count: r.views + r.downloads,
             cls: "hub-dash__c" + (TYPE_COLOR[r.type] || 1),
             note: r.demos + " items used" };
  }), null, { thick: true }));
  return c;
}

export { downloadCsv, renderLibrary, usageByTypeCard };
