/* The results as a table (Serge, 2026-10-23): rows and columns rather than
 * tiles, sorted by clicking a column -- by publication date, say -- and
 * exported as CSV for the deck that needs a list.
 *
 * Sorting is the server's (sort + order on /api/assets), not done here: a
 * table shows the first 200 of perhaps 1,300 rows, and sorting only those
 * would put row 201's "A" after row 200's "Z". The view itself (tiles or
 * table) is a per-person convenience kept in this browser.
 *
 * filters.js owns the query, the sort state and loading more; it calls
 * renderRows() where it used to append cards. */

import { dateLabel, durationLabel, getJSON, LANGUAGE_LABEL, report } from "./util.js";
import { familyDisplayName } from "./nav.js";
import { openAssetDetail } from "./detail.js";
import { assetHref, cardImage, gxcPill, paintCoverInto, TYPE_CHIP, whenNearScreen } from "./cards.js";

var VIEW_KEY = "hub.resultsView";

//: [column, heading, sort it asks the server for]. Date asks for
//: recent/oldest, which carry their own direction; the rest send `order`.
//: Length has no sort.
//:
//: Length replaced Views (Liwei, 2026-11-05): Views read a counter only
//: Consensus shares fed, so it was empty on every row. How long a video
//: runs, or how many files a kit holds, is what someone picking one from a
//: list wants to know.
//:
//: A small picture first (Serge #25, Liwei 2026-11-08): small so rows stay
//: short, shown larger beside it while the pointer is on it.
var COLUMNS = [
  ["thumb", "", null],
  ["title", "Title", "title"],
  ["type", "Type", "type"],
  ["product", "Products", "product"],
  ["segment", "Segment", "segment"],
  ["language", "Language", "language"],
  ["date", "Date", null],
  ["length", "Length", null]
];

function tableView() {
  try { return localStorage.getItem(VIEW_KEY) === "table"; } catch (e) { return false; }
}

function rememberView(table) {
  try { localStorage.setItem(VIEW_KEY, table ? "table" : "tiles"); } catch (e) { /* private window */ }
}

/* The column a sort means, and which way: what the header marks. */
function sortedColumn(sort, order) {
  if (!sort || sort === "recent") return ["date", "desc"];
  if (sort === "oldest") return ["date", "asc"];
  if (sort === "relevance") return [null, null];
  for (var i = 0; i < COLUMNS.length; i++) {
    if (COLUMNS[i][2] === sort) {
      return [COLUMNS[i][0], order || "asc"];
    }
  }
  return [null, null];
}

/* What clicking a column asks for: its natural direction first (newest,
 * A to Z), the other way on a second click. */
function sortFor(column, current) {
  var natural = column === "date" ? "desc" : "asc";
  var dir = current[0] === column ? (current[1] === "asc" ? "desc" : "asc") : natural;
  if (column === "date") return { sort: dir === "desc" ? "recent" : "oldest", order: null };
  var spec = COLUMNS.filter(function (c) { return c[0] === column; })[0];
  return { sort: spec[2], order: dir };
}

function cellValues(a) {
  return {
    title: a.title || "",
    type: (TYPE_CHIP[a.type] || [])[1] || a.type || "",
    product: (a.product_families || []).map(familyDisplayName).join(", "),
    segment: a.segment || "",
    language: a.language ? (LANGUAGE_LABEL[a.language] || a.language.toUpperCase()) : "",
    date: dateLabel(a),
    length: lengthLabel(a)
  };
}

/* A video's running time; a kit's file count. */
function lengthLabel(a) {
  if (a.type === "video") return durationLabel(a.duration_seconds);
  var n = a.resource_count || 0;
  return n ? n + (n === 1 ? " file" : " files") : "";
}

function head(onSort, sort, order) {
  var current = sortedColumn(sort, order);
  var thead = document.createElement("thead");
  var tr = thead.insertRow();
  COLUMNS.forEach(function (c) {
    var th = document.createElement("th");
    th.scope = "col";
    th.className = "hub-table__th hub-table__th--" + c[0];
    if (!c[2] && c[0] !== "date") {      // not sortable: a heading, no button
      th.textContent = c[1];
      tr.appendChild(th);
      return;
    }
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = c[1];
    if (current[0] === c[0]) {
      th.setAttribute("aria-sort", current[1] === "asc" ? "ascending" : "descending");
      btn.className = "is-sorted is-" + current[1];
    }
    btn.addEventListener("click", function () { onSort(sortFor(c[0], current)); });
    th.appendChild(btn);
    tr.appendChild(th);
  });
  return thead;
}

function row(a) {
  var v = cellValues(a);
  var tr = document.createElement("tr");
  COLUMNS.forEach(function (c) {
    var td = tr.insertCell();
    td.className = "hub-table__td hub-table__td--" + c[0];
    if (c[0] === "thumb") {
      td.appendChild(thumbCell(a));
    } else if (c[0] === "title") {
      var link = document.createElement("a");
      link.href = assetHref(a);
      link.textContent = v.title;
      link.addEventListener("click", function (e) {
        e.preventDefault();
        openAssetDetail(a.id);
      });
      td.appendChild(link);
      var gxc = gxcPill(a);
      if (gxc) {
        gxc.classList.add("hub-table__pill");
        td.appendChild(gxc);
      }
    } else {
      td.textContent = v[c[0]];
    }
  });
  return tr;
}

/* The row's picture: the card's own, or the card's cover where there is
 * none (or it fails to load). Fetched once it nears the screen. */
function thumbCell(a) {
  var thumb = document.createElement("div");
  thumb.className = "hub-table__thumb";
  thumb.setAttribute("role", "img");
  thumb.setAttribute("aria-label", a.title || "");
  var url = a.thumbnail_url ? cardImage(a.thumbnail_url) : null;
  whenNearScreen(thumb, function () {
    if (url) thumb.style.backgroundImage = "url(" + JSON.stringify(url) + ")";
    paintCoverInto(thumb, Object.assign({}, a, { thumbnail_url: url }));
  });
  thumb.addEventListener("click", function () { openAssetDetail(a.id); });
  thumb.addEventListener("mouseenter", function () { showZoom(thumb); });
  thumb.addEventListener("mouseleave", hideZoom);
  return thumb;
}

/* The larger picture, beside the small one. Fixed to the window, so the
 * table's scrolling box cannot clip it and no row grows. */
var zoom = null;
function showZoom(thumb) {
  if (!thumb.style.backgroundImage) return;      // a cover says nothing more larger
  if (!zoom) {
    zoom = document.createElement("div");
    zoom.className = "hub-table__zoom";
    zoom.setAttribute("aria-hidden", "true");
    document.body.appendChild(zoom);
  }
  zoom.style.backgroundImage = thumb.style.backgroundImage;
  var r = thumb.getBoundingClientRect();
  var w = 256, h = 144, gap = 10;
  var left = r.right + gap;
  if (left + w > window.innerWidth - 8) left = Math.max(8, r.left - gap - w);
  var top = Math.min(Math.max(8, r.top + r.height / 2 - h / 2), window.innerHeight - h - 8);
  zoom.style.left = left + "px";
  zoom.style.top = top + "px";
  zoom.classList.add("is-on");
}

function hideZoom() {
  if (zoom) zoom.classList.remove("is-on");
}
window.addEventListener("scroll", hideZoom, true);

/* Into `grid`: a fresh table, or (append) more rows onto the one there. */
function renderRows(grid, items, append, state) {
  var table = grid.querySelector("table.hub-table");
  if (!append || !table) {
    grid.innerHTML = "";
    table = document.createElement("table");
    table.className = "hub-table";
    table.appendChild(head(state.onSort, state.sort, state.order));
    table.appendChild(document.createElement("tbody"));
    grid.appendChild(table);
  }
  var body = table.tBodies[0];
  items.forEach(function (a) { body.appendChild(row(a)); });
}

/* ------------------------------------------------------------- CSV export */

function csvCell(value) {
  var s = String(value == null ? "" : value);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

/* Every row the current filters match, not just the ones on screen:
 * fetched 200 at a time, in the table's order. */
async function exportCsv(params, button) {
  var label = button.textContent;
  button.disabled = true;
  var rows = [], offset = 0, total = Infinity;
  try {
    while (offset < total) {
      button.textContent = "Exporting " + offset + (isFinite(total) ? " of " + total : "") + "…";
      var p = new URLSearchParams(params);
      p.set("limit", 200);
      p.set("offset", offset);
      var page = await getJSON("/api/assets?" + p);
      total = page.total;
      if (!page.items.length) break;
      rows = rows.concat(page.items);
      offset += page.items.length;
    }
  } catch (err) {
    report("Export failed - " + err.message, true);
    button.disabled = false;
    button.textContent = label;
    return;
  }
  var base = location.origin + location.pathname;
  var lines = [["Title", "Type", "Products", "Segment", "Language", "Date",
                "Date (ISO)", "Length", "Link"].join(",")];
  rows.forEach(function (a) {
    var v = cellValues(a);
    lines.push([v.title, v.type, v.product, v.segment, v.language, v.date,
                a.uploaded_at || "", v.length, base + "#/asset/" + encodeURIComponent(a.id)]
      .map(csvCell).join(","));
  });
  // A BOM, so Excel reads the UTF-8 (pure::variants, Chinese titles) right.
  var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  var link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "technical-marketing-hub-" + new Date().toISOString().slice(0, 10) + ".csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  button.disabled = false;
  button.textContent = label;
}

export { exportCsv, rememberView, renderRows, tableView };
