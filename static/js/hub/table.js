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

import { dateLabel, getJSON, LANGUAGE_LABEL, report } from "./util.js";
import { familyDisplayName } from "./nav.js";
import { openAssetDetail } from "./detail.js";
import { TYPE_CHIP } from "./cards.js";

var VIEW_KEY = "hub.resultsView";

//: [column, heading, sort it asks the server for]. Date asks for
//: recent/oldest, which carry their own direction; the rest send `order`.
var COLUMNS = [
  ["title", "Title", "title"],
  ["type", "Type", "type"],
  ["product", "Products", "product"],
  ["segment", "Segment", "segment"],
  ["language", "Language", "language"],
  ["date", "Date", null],
  ["views", "Views", "most_viewed"]
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
      return [COLUMNS[i][0], order || (sort === "most_viewed" ? "desc" : "asc")];
    }
  }
  return [null, null];
}

/* What clicking a column asks for: its natural direction first (newest,
 * most viewed, A to Z), the other way on a second click. */
function sortFor(column, current) {
  var natural = column === "date" || column === "views" ? "desc" : "asc";
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
    views: (a.stats && a.stats.views) || 0
  };
}

function head(onSort, sort, order) {
  var current = sortedColumn(sort, order);
  var thead = document.createElement("thead");
  var tr = thead.insertRow();
  COLUMNS.forEach(function (c) {
    var th = document.createElement("th");
    th.scope = "col";
    th.className = "hub-table__th hub-table__th--" + c[0];
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
    if (c[0] === "title") {
      var link = document.createElement("a");
      link.href = "#/asset/" + encodeURIComponent(a.id);
      link.textContent = v.title;
      link.addEventListener("click", function (e) {
        e.preventDefault();
        openAssetDetail(a.id);
      });
      td.appendChild(link);
    } else {
      td.textContent = c[0] === "views" ? (v.views ? String(v.views) : "") : v[c[0]];
    }
  });
  return tr;
}

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
                "Date (ISO)", "Views", "Link"].join(",")];
  rows.forEach(function (a) {
    var v = cellValues(a);
    lines.push([v.title, v.type, v.product, v.segment, v.language, v.date,
                a.uploaded_at || "", v.views, base + "#/asset/" + encodeURIComponent(a.id)]
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
