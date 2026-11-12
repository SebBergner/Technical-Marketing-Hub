/* Content health -> Health check (2026-11-11): what in SharePoint keeps a
 * demo out of the Hub or out of its right place (GET /api/content-health/
 * checks). Each check is a card with its count; open it for the list, with
 * the demo's owner and a link to fix it in SharePoint. "Only mine" keeps the
 * rows whose owner is the person signed in.
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, demoLink, el, session, TYPE_WORD } from "../admin/util.js";

var data = null;
var onlyMine = false;

/* key, title, why it matters, what to do. */
var CHECKS = [
  ["skipped_folders", "Folders the Hub skips",
   "A top-level folder in Demo Catalog with no Demo Type (and not a CAD Model) is never "
   + "listed in the Hub, nor are its files.",
   "Set its Demo Type in SharePoint, or move it into a demo's folder if it belongs to one."],
  ["loose_files", "Files loose in the library",
   "A file at the root of Demo Catalog belongs to no demo, so nobody finds it in the Hub.",
   "Move it into its demo's folder; the file keeps its dates."],
  ["empty", "Demos with no files",
   "Listed, but there is nothing to preview or download. Its date falls back to the folder's.",
   "Upload the files, or archive the demo."],
  ["no_product", "No product",
   "Not under any product in the navigation, and never among related demos by product.",
   "Fill in Product in SharePoint (or Edit metadata on the demo's page)."],
  ["no_segment", "No segment",
   "Not under any segment, with no related demos by segment, and its feedback reaches no "
   + "segment owner. CAD datasets have no Segment column and are not counted.",
   "Fill in Segment in SharePoint (or Edit metadata on the demo's page)."],
  ["same_name_archives", "Two archives of the same name",
   "The same name as .zip and .rar (or .7z) in one folder: often one copy too many. Many CAD "
   + "datasets ship both on purpose, so check before deleting.",
   "Keep the one people should download; delete the other in SharePoint."]
];

function mine(row) {
  var me = [session.name, session.email].filter(Boolean).map(function (s) {
    return s.toLowerCase();
  });
  var owner = (row.owner || "").toLowerCase();
  if (!owner) return false;
  // SharePoint writes a file's author "Last, First".
  var parts = owner.split(",");
  var flipped = parts.length === 2 ? (parts[1].trim() + " " + parts[0].trim()) : owner;
  return me.indexOf(owner) >= 0 || me.indexOf(flipped) >= 0;
}

function spLink(url, text) {
  var a = el(url ? "a" : "span", null, text);
  if (url) {
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
  }
  return a;
}

function table(key, rows) {
  var t = el("table");
  var hr = t.createTHead().insertRow();
  var heads = key === "skipped_folders" ? ["Folder", "Files", "Created", "SharePoint"]
    : key === "loose_files" ? ["File", "Size", "Last changed", "SharePoint"]
    : ["Demo", "Type", "Owner"].concat(key === "same_name_archives" ? ["Files"] : [])
        .concat(["SharePoint"]);
  heads.forEach(function (h) { hr.appendChild(el("th", null, h)); });
  var tb = t.createTBody();
  rows.forEach(function (r) {
    var tr = tb.insertRow();
    if (key === "skipped_folders") {
      tr.insertCell().textContent = r.name;
      var n = tr.insertCell();
      n.className = "num";
      n.textContent = r.files;
      tr.insertCell().textContent = (r.created_at || "").slice(0, 10) || "—";
    } else if (key === "loose_files") {
      tr.insertCell().textContent = r.name;
      var s = tr.insertCell();
      s.className = "num";
      s.textContent = r.size ? (r.size / 1048576).toFixed(1) + " MB" : "—";
      tr.insertCell().textContent = (r.modified_at || "").slice(0, 10) || "—";
    } else {
      tr.insertCell().appendChild(demoLink(r.asset_id, r.title));
      tr.insertCell().textContent = TYPE_WORD[r.type] || r.type || "—";
      var o = tr.insertCell();
      o.textContent = r.owner || "—";
      if (!r.owner) o.className = "faint";
      if (key === "same_name_archives") tr.insertCell().textContent = (r.files || []).join(", ");
    }
    tr.insertCell().appendChild(spLink(r.web_url, r.web_url ? "Open" : "—"));
  });
  var wrap = el("div", "tablewrap");
  wrap.appendChild(t);
  return wrap;
}

function render() {
  var host = $("hcBody");
  host.innerHTML = "";
  var total = 0;
  CHECKS.forEach(function (c) {
    var rows = (data[c[0]] || []).filter(function (r) {
      return !onlyMine || mine(r);
    });
    total += rows.length;
    var card = el("details", "card hc-card" + (rows.length ? "" : " hc-card--ok"));
    var sum = el("summary", "card-head");
    sum.appendChild(el("h2", null, c[1]));
    sum.appendChild(el("span", "pill " + (rows.length ? "pill--warn" : "pill--on"),
      rows.length ? String(rows.length) : "None"));
    card.appendChild(sum);
    card.appendChild(el("p", "muted hc-why", c[2]));
    card.appendChild(el("p", "hc-fix", "To fix: " + c[3]));
    if (rows.length) card.appendChild(table(c[0], rows));
    host.appendChild(card);
  });
  $("hcIntro").textContent = (data.read_at
    ? "Folders and loose files as of the last full SharePoint sync, "
      + new Date(data.read_at).toLocaleString() + "; "
    : "Folders and loose files appear after the next SharePoint sync; ")
    + "the rest from the demos the Hub lists now. Demo Catalog only. "
    + total + (onlyMine ? " of yours." : " in all.");
}

function loadChecks() {
  var box = $("hcMine");
  if (box && !box.dataset.wired) {
    box.dataset.wired = "1";
    box.addEventListener("change", function () { onlyMine = box.checked; if (data) render(); });
  }
  return fetch("/api/content-health/checks")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) { data = d; render(); } });
}

export {
  loadChecks
};
