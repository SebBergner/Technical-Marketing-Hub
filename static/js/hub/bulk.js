/* Create New Demo, several at once (#/upload, 2026-11-25).
 *
 * Seb had 34 AI Portfolio clips to add as Demo Videos, one demo each. The
 * one-demo wizard (upload.js) would take 34 passes; this takes one:
 *
 *   2. Shared values -- filled once (video type, audio, date, ...): every
 *      video starts from them.
 *   3. Videos -- drop the files (or a folder); a row per video, its title
 *      made from the file name. Title and description are edited in the row;
 *      "Details" changes any other field for that video alone. A sheet fills
 *      the rows: paste from Excel or import a CSV, matched on the File
 *      column; "Download sheet" gives the columns, filled with the rows.
 *      "Check all" asks the server (POST /api/uploads/check) about every row
 *      at once -- required fields, options, names taken, two rows with the
 *      same title -- before anything is created.
 *   4. Create -- each row exactly as the one-demo wizard does it (POST
 *      /api/uploads, the file in chunks, finish), two at a time; a failed
 *      row can be tried again, the others are not held up.
 *
 * Videos only for now; a kit per dropped folder is the obvious next target.
 * Part of the Hub page's script; upload.js draws it. */

import { api, button, drawWizard, el, isVideo, loadMine, metadataForm, requiredNow, sendAll,
         size, up, walkDrop, warnLeaving } from "./upload.js";

var BULK_STEPS = ["Destination", "Shared values", "Videos", "Create"];
//: Said per video, never shared.
var OWN_ONLY = { title: true, description: true, long_description: true, named_customer: true };
//: Edited in the row itself; the rest under "Details".
var INLINE = { title: true, description: true };
var AT_ONCE = 2;
var nextId = 1;

function bulk() { return up.bulk; }

function blank(f) {
  if (f.default != null) return f.default;
  return f.kind === "multi" ? [] : "";
}

function sharedValue(f) {
  var b = bulk();
  return b.shared[f.key] !== undefined ? b.shared[f.key] : blank(f);
}

/* A row's values: its own where it has them, else the shared ones. */
function effective(row) {
  var out = {};
  up.target.fields.forEach(function (f) {
    out[f.key] = Object.prototype.hasOwnProperty.call(row.own, f.key)
      ? row.own[f.key] : (OWN_ONLY[f.key] ? blank(f) : sharedValue(f));
  });
  var internal = row.internal != null ? row.internal : bulk().internal;
  if (internal && "customer_facing" in out) out.customer_facing = false;
  return out;
}

function rowInternal(row) { return row.internal != null ? row.internal : bulk().internal; }

function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

/* Anything edited makes the last check stale. */
function stale() {
  bulk().checked = false;
  var go = document.getElementById("hubBulkNext");
  if (go) go.disabled = true;
}

/* ── names ─────────────────────────────────────────────────────────────── */
/* "Windchill---AI-Parts-Rationalization_Technical-Overview_sbergner_v1.mp4"
   -> "Windchill - AI Parts Rationalization Technical Overview sbergner v1":
   a start, edited in the row or replaced from a sheet. */
function titleFromFile(name) {
  var t = String(name).replace(/\.[^.]+$/, "")
    .replace(/-{2,}/g, " - ")
    .replace(/_/g, " ")
    .replace(/([A-Za-z0-9])-(?=[A-Za-z0-9])/g, "$1 ")
    .replace(/["*:<>?\\|#%]/g, " - ")
    .replace(/\s+-(\s+-)*\s+/g, " - ")
    .replace(/\s{2,}/g, " ")
    .trim().replace(/^[ .-]+|[ .-]+$/g, "");
  return t.slice(0, 120);
}

/* The product a file name starts with, when it is one of the options
   ("Windchill---…", "Creo AI Assist.mp4", "Orbit_AI-Hub.mp4" -> PTC Orbit). */
function productFromFile(name, choices) {
  var head = String(name).split(/---|_| - /)[0].trim();
  var tries = [head, head.split(/[\s-]/)[0]];
  for (var i = 0; i < tries.length; i++) {
    var t = tries[i].toLowerCase();
    if (!t) continue;
    var hit = (choices || []).filter(function (c) {
      return c.toLowerCase() === t || c.toLowerCase() === "ptc " + t;
    })[0];
    if (hit) return [hit];
  }
  return [];
}

function field(key) { return up.target.fields.filter(function (f) { return f.key === key; })[0]; }

function addVideos(files) {
  var b = bulk(), skipped = [];
  var products = field("products");
  Array.prototype.forEach.call(files, function (file) {
    if (!isVideo(file.name)) { skipped.push(file.name); return; }
    var row = b.rows.filter(function (r) {
      return r.name.toLowerCase() === file.name.toLowerCase();
    })[0];
    if (row && row.state === "done") return;
    if (!row) {
      row = { id: nextId++, name: file.name, own: { title: titleFromFile(file.name) },
              internal: null, problems: null, state: "", record: null, error: "", open: false };
      if (products && !sharedValue(products).length) {
        var guess = productFromFile(file.name, products.choices);
        if (guess.length) row.own.products = guess;
      }
      b.rows.push(row);
    }
    row.file = file;
    row.size = file.size;
  });
  stale();
  b.note = skipped.length ? "Not videos, left out: " + skipped.join(", ") : "";
}

/* ── sheets ────────────────────────────────────────────────────────────── */
/* Excel's clipboard is tab-separated, a CSV comma-separated; both quote a
   cell holding a separator, a quote or a line break. */
function parseSheet(text) {
  text = String(text).replace(/^﻿/, "");
  var first = text.split(/\r?\n/)[0] || "";
  var sep = first.indexOf("\t") >= 0 ? "\t" : (first.split(";").length > first.split(",").length
                                               ? ";" : ",");
  var rows = [], row = [], cell = "", quoted = false;
  for (var i = 0; i < text.length; i++) {
    var c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"' && cell === "") quoted = true;
    else if (c === sep) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows.filter(function (r) { return r.some(function (x) { return x.trim(); }); });
}

function norm(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, ""); }

var FILE_NAMES = { file: 1, filename: 1, video: 1, videofile: 1 };
var INTERNAL_NAMES = { ptconly: 1, internal: 1 };

function columnKey(header) {
  var n = norm(header);
  if (FILE_NAMES[n]) return "@file";
  if (INTERNAL_NAMES[n]) return "@internal";
  var f = up.target.fields.filter(function (x) {
    return norm(x.key) === n || norm(x.label) === n;
  })[0];
  return f ? f.key : null;
}

function yesNo(v) {
  if (/^(y|yes|true|1|x)$/i.test(v)) return true;
  if (/^(n|no|false|0)$/i.test(v)) return false;
  return v;
}

function cellValue(f, raw) {
  var v = raw.trim();
  var pick = function (x) {
    var hit = (f.choices || []).filter(function (c) { return c.toLowerCase() === x.toLowerCase(); })[0];
    return hit || x;
  };
  if (f.kind === "multi") {
    return v.split(/[;\n]|,/).map(function (x) { return x.trim(); }).filter(Boolean).map(pick);
  }
  if (f.kind === "yesno") return yesNo(v);
  if (f.kind === "choice") return pick(v);
  if (f.kind === "date") {
    var us = v.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (us) return us[3] + "-" + ("0" + us[1]).slice(-2) + "-" + ("0" + us[2]).slice(-2);
    return v.slice(0, 10);
  }
  return v;
}

function baseName(s) { return String(s).split(/[\\/]/).pop().toLowerCase(); }
function stem(s) { return baseName(s).replace(/\.[^.]+$/, ""); }

/* Fills rows from a sheet. Rows are matched on the File column (with or
   without the extension); a sheet row naming a video not added yet becomes a
   row waiting for it. An empty cell leaves the value as it was. */
function applySheet(text) {
  var b = bulk();
  var table = parseSheet(text);
  if (table.length < 2) return "The sheet needs a header row and at least one row.";
  var keys = table[0].map(columnKey);
  var ignored = table[0].filter(function (h, i) { return !keys[i] && h.trim(); });
  var fileCol = keys.indexOf("@file");
  var data = table.slice(1);
  if (fileCol < 0 && data.length !== b.rows.length) {
    return "The sheet has no File column, so its rows cannot be matched to the videos.";
  }
  var filled = 0, waiting = 0;
  data.forEach(function (cells, n) {
    var row;
    if (fileCol >= 0) {
      var name = (cells[fileCol] || "").trim();
      if (!name) return;
      row = b.rows.filter(function (r) {
        return baseName(r.name) === baseName(name) || stem(r.name) === stem(name);
      })[0];
      if (!row) {
        row = { id: nextId++, name: name.split(/[\\/]/).pop(), file: null, size: 0, own: {},
                internal: null, problems: null, state: "", record: null, error: "", open: false };
        b.rows.push(row);
        waiting++;
      }
    } else row = b.rows[n];
    if (row.state === "done") return;
    keys.forEach(function (k, i) {
      var raw = cells[i];
      if (!k || k === "@file" || raw == null || !String(raw).trim()) return;
      if (k === "@internal") { var y = yesNo(raw.trim()); if (y === true || y === false) row.internal = y; return; }
      row.own[k] = cellValue(field(k), String(raw));
    });
    filled++;
  });
  stale();
  return "Filled " + filled + " video" + (filled === 1 ? "" : "s") + " from the sheet."
    + (waiting ? " " + waiting + " name a video not added yet: drop it to fill its row." : "")
    + (fileCol < 0 ? " No File column: matched in order." : "")
    + (ignored.length ? " Columns not used: " + ignored.join(", ") + "." : "");
}

function csvCell(v) {
  v = v == null ? "" : String(v);
  return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
}

/* The sheet's columns, filled with the rows as they are: a template when
   there are none. Opens in Excel (UTF-8 with BOM). */
function downloadSheet() {
  var fields = up.target.fields;
  var head = ["File"].concat(fields.map(function (f) { return f.label; }), ["PTC Only"]);
  var lines = [head.map(csvCell).join(",")];
  bulk().rows.forEach(function (row) {
    var v = effective(row);
    lines.push([row.name].concat(fields.map(function (f) {
      var x = v[f.key];
      if (Array.isArray(x)) return x.join("; ");
      return x === true ? "Yes" : x === false ? "No" : x;
    }), [rowInternal(row) ? "Yes" : "No"]).map(csvCell).join(","));
  });
  var blob = new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
  var a = el("a");
  a.href = URL.createObjectURL(blob);
  a.download = "TMH bulk - " + up.target.library + ".csv";
  document.body.appendChild(a);
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

/* ── step 2: shared values ─────────────────────────────────────────────── */
function stepShared(box) {
  var b = bulk();
  box.appendChild(el("p", "hub-up__muted", "Filled in once for every video. Each video can "
    + "still change any of them in the next step, or from a sheet. Title, description and "
    + "long description are said per video."));
  var target = Object.assign({}, up.target, {
    fields: up.target.fields.filter(function (f) { return !OWN_ONLY[f.key]; }) });
  var note = el("span", "hub-up__muted");
  var refresh = function () {
    stale();
    var empty = target.fields.filter(function (f) {
      if (!requiredNow(target, b.shared, f)) return false;
      var v = b.shared[f.key];
      return f.kind === "yesno" ? (v !== true && v !== false)
        : (v == null || v === "" || (Array.isArray(v) && !v.length));
    });
    note.textContent = empty.length ? "Required, still empty here: "
      + empty.map(function (f) { return f.label; }).join(", ")
      + ". Fill them here, per video, or from a sheet." : "";
  };
  box.appendChild(metadataForm(target, b.shared, { onChange: refresh }));
  var internal = el("label", "hub-up__check");
  var tick = el("input");
  tick.type = "checkbox";
  tick.checked = b.internal;
  tick.addEventListener("change", function () {
    b.internal = tick.checked;
    if (tick.checked && b.shared.customer_facing !== false) {
      b.shared.customer_facing = false;
      drawWizard();
    }
    stale();
  });
  internal.appendChild(tick);
  internal.appendChild(document.createTextNode(" PTC Only — partners cannot open the files, "
    + "and none is customer facing"));
  box.appendChild(internal);
  var bar = el("div", "hub-up__bar");
  var back = button("Back");
  back.addEventListener("click", function () { up.step = 1; drawWizard(); });
  var next = button("Next: videos", true);
  next.addEventListener("click", function () { up.step = 3; drawWizard(); });
  bar.appendChild(back);
  bar.appendChild(next);
  bar.appendChild(note);
  box.appendChild(bar);
  refresh();
}

/* ── step 3: the videos ────────────────────────────────────────────────── */
function dropZone() {
  var drop = el("div", "hub-up__drop");
  drop.appendChild(el("b", null, "Drop the videos, or a folder of them, here"));
  var picks = el("div", "hub-up__picks");
  var fileIn = el("input");
  fileIn.type = "file";
  fileIn.multiple = true;
  fileIn.accept = "video/*,.mp4,.mov,.m4v,.webm,.wmv,.avi,.mkv";
  fileIn.hidden = true;
  fileIn.addEventListener("change", function () { addVideos(fileIn.files); drawWizard(); });
  var dirIn = el("input");
  dirIn.type = "file";
  dirIn.webkitdirectory = true;
  dirIn.hidden = true;
  dirIn.addEventListener("change", function () { addVideos(dirIn.files); drawWizard(); });
  var a = button("Choose videos");
  a.addEventListener("click", function () { fileIn.click(); });
  var d = button("Choose a folder");
  d.addEventListener("click", function () { dirIn.click(); });
  [fileIn, dirIn, a, d].forEach(function (n) { picks.appendChild(n); });
  drop.appendChild(picks);
  drop.appendChild(el("span", "hub-up__help", "Each video becomes its own demo. Videos in "
    + "sub-folders are included; other files are left out."));
  drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", function () { drop.classList.remove("over"); });
  drop.addEventListener("drop", function (e) {
    e.preventDefault();
    drop.classList.remove("over");
    walkDrop(e.dataTransfer.items, function (files) { addVideos(files); drawWizard(); });
  });
  return drop;
}

function sheetTools() {
  var b = bulk();
  var box = el("div", "hub-bulk__sheet");
  var bar = el("div", "hub-up__picks");
  var paste = button("Paste from Excel");
  var csvIn = el("input");
  csvIn.type = "file";
  csvIn.accept = ".csv,.tsv,.txt,text/csv";
  csvIn.hidden = true;
  var csv = button("Import CSV");
  var dl = button(b.rows.length ? "Download sheet" : "Download empty sheet");
  var msg = el("span", "hub-up__muted", b.sheetNote || "");
  var area = el("div", "hub-bulk__paste");
  area.hidden = true;
  var text = el("textarea");
  text.rows = 6;
  text.placeholder = "Copy the rows from Excel, header row included, and paste here. "
    + "Columns: File, Title, Description, Long description, Products, … (Download sheet "
    + "shows them all). Products: separate several with ;";
  var apply = button("Fill in the rows", true);
  area.appendChild(text);
  area.appendChild(apply);
  paste.addEventListener("click", function () { area.hidden = !area.hidden; if (!area.hidden) text.focus(); });
  apply.addEventListener("click", function () {
    b.sheetNote = applySheet(text.value);
    drawWizard();
  });
  csv.addEventListener("click", function () { csvIn.click(); });
  csvIn.addEventListener("change", function () {
    var f = csvIn.files[0];
    if (!f) return;
    f.text().then(function (t) { b.sheetNote = applySheet(t); drawWizard(); });
  });
  dl.addEventListener("click", downloadSheet);
  [paste, csv, csvIn, dl].forEach(function (n) { bar.appendChild(n); });
  box.appendChild(el("span", "hub-up__label", "Fill in from a sheet"));
  box.appendChild(bar);
  box.appendChild(msg);
  box.appendChild(area);
  return box;
}

function drawRow(list, row, i) {
  var done = row.state === "done";
  var wrap = el("div", "hub-bulk__row" + (row.problems && row.problems.length ? " bad" : "")
                       + (done ? " done" : ""));
  var line = el("div", "hub-bulk__line");
  line.appendChild(el("span", "hub-bulk__n", String(i + 1)));
  var file = el("div", "hub-bulk__file");
  file.appendChild(el("span", "hub-up__path", row.name));
  file.appendChild(el("span", row.file ? "hub-up__muted" : "hub-up__err",
                      row.file ? size(row.size) : "Video not added yet"));
  line.appendChild(file);
  var title = el("input", "hub-bulk__in");
  title.type = "text";
  title.maxLength = 120;
  title.placeholder = "Title";
  title.value = row.own.title || "";
  title.disabled = done;
  title.addEventListener("input", function () { row.own.title = title.value; stale(); });
  line.appendChild(title);
  var desc = el("textarea", "hub-bulk__in");
  desc.rows = 2;
  desc.maxLength = 2000;
  desc.placeholder = "Description (shown on the card)";
  desc.value = row.own.description || "";
  desc.disabled = done;
  desc.addEventListener("input", function () { row.own.description = desc.value; stale(); });
  line.appendChild(desc);
  var acts = el("div", "hub-bulk__acts");
  var v = effective(row);
  var prod = el("span", "hub-up__muted hub-bulk__prod",
                (v.products || []).join(", ") || "No product");
  acts.appendChild(prod);
  if (done) {
    acts.appendChild(el("span", "hub-up__status hub-up__status--published", "Created"));
  } else {
    var more = button(row.open ? "Hide details" : "Details");
    more.addEventListener("click", function () { row.open = !row.open; drawWizard(); });
    var x = button("Remove");
    x.addEventListener("click", function () {
      bulk().rows = bulk().rows.filter(function (r) { return r !== row; });
      stale();
      drawWizard();
    });
    acts.appendChild(more);
    acts.appendChild(x);
  }
  line.appendChild(acts);
  wrap.appendChild(line);
  if (row.problems && row.problems.length) {
    wrap.appendChild(el("div", "hub-up__err hub-bulk__why", row.problems.join(" ")));
  } else if (row.problems && row.folder) {
    wrap.appendChild(el("div", "hub-up__muted hub-bulk__why", "OK — folder “" + row.folder + "”"));
  }
  if (row.open && !done) wrap.appendChild(details(row, prod));
  list.appendChild(wrap);
}

/* Every other field for this video alone. What differs from the shared
   values becomes the row's own; set back to the shared value, it follows
   the shared value again. */
function details(row, prod) {
  var box = el("div", "hub-bulk__details");
  var target = Object.assign({}, up.target, {
    fields: up.target.fields.filter(function (f) { return !INLINE[f.key]; }) });
  var values = effective(row);
  var changed = function () {
    target.fields.forEach(function (f) {
      if (OWN_ONLY[f.key] || !same(values[f.key], sharedValue(f))) row.own[f.key] = values[f.key];
      else delete row.own[f.key];
    });
    prod.textContent = (values.products || []).join(", ") || "No product";
    stale();
  };
  box.appendChild(metadataForm(target, values, { onChange: changed }));
  var internal = el("label", "hub-up__check");
  var tick = el("input");
  tick.type = "checkbox";
  tick.checked = rowInternal(row);
  tick.addEventListener("change", function () {
    row.internal = tick.checked === bulk().internal ? null : tick.checked;
    if (tick.checked) row.own.customer_facing = false;
    stale();
    drawWizard();
  });
  internal.appendChild(tick);
  internal.appendChild(document.createTextNode(" PTC Only"));
  box.appendChild(internal);
  return box;
}

function itemOf(row) {
  return { target: up.target.key, kind: up.kind, values: effective(row),
           internal: rowInternal(row), preview: null,
           files: [{ path: row.name, size: row.size || 0 }] };
}

function checkAll(msg, go) {
  var b = bulk();
  var todo = b.rows.filter(function (r) { return r.state !== "done"; });
  var sendable = todo.filter(function (r) { return r.file; });
  todo.forEach(function (r) {
    if (!r.file) r.problems = ["No video file: drop " + r.name + " to add it."];
  });
  if (!sendable.length) { b.checked = false; drawWizard(); return; }
  go.disabled = true;
  msg.textContent = "Checking " + sendable.length + "…";
  api("POST", "/api/uploads/check", { items: sendable.map(itemOf) }).then(function (res) {
    res.items.forEach(function (r, i) {
      sendable[i].problems = r.problems;
      sendable[i].folder = r.folder_name;
    });
    b.checked = sendable.length === todo.length && res.ok;
    b.checkNote = b.checked ? "All " + todo.length + " can be created."
      : todo.filter(function (r) { return r.problems && r.problems.length; }).length
        + " of " + todo.length + " need a change (in red).";
    drawWizard();
  }).catch(function (e) {
    go.disabled = false;
    msg.textContent = e.message;
  });
}

function stepRows(box) {
  var b = bulk();
  box.appendChild(dropZone());
  if (b.note) box.appendChild(el("p", "hub-up__err", b.note));
  box.appendChild(sheetTools());
  var list = el("div", "hub-bulk__rows");
  if (b.rows.length) {
    var head = el("div", "hub-bulk__line hub-bulk__head");
    ["#", "Video", "Title *", "Description *", ""].forEach(function (h) {
      head.appendChild(el("span", "hub-up__label", h));
    });
    list.appendChild(head);
  }
  b.rows.forEach(function (row, i) { drawRow(list, row, i); });
  box.appendChild(list);
  var total = b.rows.reduce(function (s, r) { return s + (r.size || 0); }, 0);
  if (b.rows.length) {
    box.appendChild(el("p", "hub-up__muted", b.rows.length + " video"
      + (b.rows.length === 1 ? "" : "s") + " · " + size(total)));
  }
  var bar = el("div", "hub-up__bar");
  var back = button("Back");
  back.addEventListener("click", function () { up.step = 2; drawWizard(); });
  var check = button("Check all");
  var next = button("Next: create", true);
  next.id = "hubBulkNext";
  next.disabled = !b.checked;
  var msg = el("span", b.checked ? "hub-up__muted" : "hub-up__err", b.checkNote || "");
  check.disabled = !b.rows.some(function (r) { return r.state !== "done"; });
  check.addEventListener("click", function () { b.checkNote = ""; checkAll(msg, check); });
  next.addEventListener("click", function () { up.step = 4; drawWizard(); });
  [back, check, next, msg].forEach(function (n) { bar.appendChild(n); });
  box.appendChild(bar);
}

/* ── step 4: create ────────────────────────────────────────────────────── */
function createOne(row) {
  row.state = "running";
  row.error = "";
  row.box.innerHTML = "";
  row.status.textContent = row.record ? "Continuing…" : "Creating…";
  var made = row.record ? Promise.resolve(row.record)
    : api("POST", "/api/uploads", itemOf(row)).then(function (rec) { row.record = rec; return rec; });
  return made.then(function (rec) {
    row.status.textContent = "Uploading";
    return sendAll(rec, [{ path: rec.files[0].path, size: row.size, file: row.file }], row.box, true);
  }).then(function (rec) {
    row.state = "done";
    row.record = rec;
    row.status.textContent = "Created";
    row.status.className = "hub-up__status hub-up__status--published";
  }, function (e) {
    row.state = "failed";
    row.error = e.message;
    row.status.textContent = "Failed";
    row.status.className = "hub-up__status hub-up__status--sent_back";
    row.box.appendChild(el("div", "hub-up__err", e.message));
  });
}

function runAll(rows, after) {
  var b = bulk();
  var queue = rows.slice();
  b.running = true;
  window.addEventListener("beforeunload", warnLeaving);
  var lane = function () {
    var row = queue.shift();
    if (!row) return Promise.resolve();
    return createOne(row).then(lane);
  };
  var lanes = [];
  for (var i = 0; i < Math.min(AT_ONCE, queue.length); i++) lanes.push(lane());
  Promise.all(lanes).then(function () {
    b.running = false;
    window.removeEventListener("beforeunload", warnLeaving);
    loadMine();
    after();
  });
}

function stepCreate(box) {
  var b = bulk();
  var todo = b.rows.filter(function (r) { return r.state !== "done"; });
  var total = todo.reduce(function (s, r) { return s + (r.size || 0); }, 0);
  box.appendChild(el("p", null, todo.length + " demo" + (todo.length === 1 ? "" : "s")
    + " to create in " + up.target.library + " (" + size(total) + "), each published as soon "
    + "as its video is in. Keep this page open until all are done."));
  var list = el("div", "hub-bulk__rows");
  b.rows.forEach(function (row) {
    var line = el("div", "hub-bulk__crow");
    var head = el("div", "hub-bulk__chead");
    head.appendChild(el("b", "hub-up__title", effective(row).title));
    row.status = el("span", "hub-up__status" + (row.state === "done"
      ? " hub-up__status--published" : row.state === "failed" ? " hub-up__status--sent_back" : ""),
      row.state === "done" ? "Created" : row.state === "failed" ? "Failed" : "Waiting");
    head.appendChild(row.status);
    line.appendChild(head);
    row.box = el("div", "hub-up__progress");
    if (row.error) row.box.appendChild(el("div", "hub-up__err", row.error));
    line.appendChild(row.box);
    list.appendChild(line);
  });
  box.appendChild(list);
  var bar = el("div", "hub-up__bar");
  var back = button("Back");
  back.addEventListener("click", function () { if (!b.running) { up.step = 3; drawWizard(); } });
  var go = button(b.rows.some(function (r) { return r.state === "failed"; })
    ? "Try the failed ones again" : "Create " + todo.length + " demo" + (todo.length === 1 ? "" : "s"),
    true);
  go.disabled = !todo.length || b.running;
  var msg = el("span", "hub-up__muted");
  go.addEventListener("click", function () {
    go.disabled = back.disabled = true;
    runAll(b.rows.filter(function (r) { return r.state !== "done"; }), function () {
      var ok = b.rows.filter(function (r) { return r.state === "done"; }).length;
      var bad = b.rows.length - ok;
      back.disabled = false;
      go.disabled = !bad;
      go.textContent = "Try the failed ones again";
      msg.textContent = ok + " created" + (bad ? ", " + bad + " failed: fix them with Back, or "
        + "try again." : ". They appear in the Hub within a minute or two.");
      if (!bad) {
        go.hidden = true;
        var again = button("Start another batch", true);
        again.addEventListener("click", function () {
          up.bulk = { shared: b.shared, internal: b.internal, rows: [] };
          up.step = 3;
          drawWizard();
        });
        bar.appendChild(again);
      }
    });
  });
  [back, go, msg].forEach(function (n) { bar.appendChild(n); });
  box.appendChild(bar);
}

function drawBulk(box) {
  if (up.step === 2) stepShared(box);
  else if (up.step === 3) stepRows(box);
  else stepCreate(box);
}

export { BULK_STEPS, drawBulk, applySheet, parseSheet, titleFromFile, productFromFile };
