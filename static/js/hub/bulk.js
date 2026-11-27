/* Create New Demo -> Multi-video upload (#/upload, 2026-11-25; reordered
 * 2026-11-27 at Liwei's request).
 *
 * Seb had 34 AI Portfolio clips to add as Demo Videos, one demo each. The
 * one-demo wizard (upload.js) would take 34 passes; this takes one, in a
 * fixed order:
 *
 *   2. Videos -- drop the files (or a folder); a row per video, its title
 *      made from the file name.
 *   3. Details -- (1) download the sheet: the File column already lists the
 *      videos; (2) fill it in, in Excel; (3) import it, or paste it. Rows are
 *      matched on the File column. Or edit each video here: title and
 *      description in the row, any other field under "Details". A value the
 *      same for every video is filled down in the sheet (a "Shared values"
 *      step before the videos read as unclear and was dropped, 2026-11-27).
 *   4. Check & create -- the server checks every row at once (POST
 *      /api/uploads/check: required fields, options, names taken, two rows
 *      with the same title) before anything is created; then each row exactly
 *      as the one-demo wizard does it (POST /api/uploads, the file in chunks,
 *      finish), two at a time; a failed row can be tried again, the others
 *      are not held up.
 *
 * Videos only for now; a kit per dropped folder is the obvious next target.
 * Part of the Hub page's script; upload.js draws it. */

import { api, button, drawWizard, el, isVideo, loadMine, metadataForm, requiredNow, sendAll,
         size, up, walkDrop, warnLeaving } from "./upload.js";

var BULK_STEPS = ["Destination", "Videos", "Details", "Check & create"];
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
  bulk().asked = false;
  bulk().checkError = "";
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

/* Step 3's guide: the sheet, in the order it is used. */
function sheetTools() {
  var b = bulk();
  var box = el("div", "hub-bulk__sheet");
  box.appendChild(el("b", "hub-bulk__sheet-h", "Fill in the details from a sheet"));
  var steps = el("ol", "hub-bulk__guide");

  var one = el("li");
  var dl = button("Download the sheet");
  dl.addEventListener("click", downloadSheet);
  one.appendChild(dl);
  one.appendChild(el("span", "hub-up__muted", "The File column already lists your "
    + b.rows.length + " video" + (b.rows.length === 1 ? "" : "s") + "; there is a column for "
    + "every field."));
  steps.appendChild(one);

  steps.appendChild(el("li", null, "Fill it in, in Excel. A value that is the same for every "
    + "video: type it once and drag it down. Several products: separate them with ;"));

  var three = el("li");
  var csvIn = el("input");
  csvIn.type = "file";
  csvIn.accept = ".csv,.tsv,.txt,text/csv";
  csvIn.hidden = true;
  var csv = button("Import the sheet (CSV)", true);
  var paste = button("Or paste from Excel");
  var area = el("div", "hub-bulk__paste");
  area.hidden = true;
  var text = el("textarea");
  text.rows = 6;
  text.placeholder = "Copy the rows from Excel, header row included, and paste here.";
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
  var picks = el("div", "hub-up__picks");
  [csv, paste, csvIn].forEach(function (n) { picks.appendChild(n); });
  three.appendChild(picks);
  three.appendChild(el("span", "hub-up__muted", "Rows are matched on the File column. Already "
    + "have a sheet? Start here."));
  three.appendChild(area);
  steps.appendChild(three);

  box.appendChild(steps);
  if (b.sheetNote) box.appendChild(el("p", "hub-up__ok", b.sheetNote));
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

/* Asks the server about every row not created yet (nothing is created). A
   row whose demo was already made, but whose video failed, is not asked: it
   only continues. Calls done() when the answer is in. */
function checkAll(done) {
  var b = bulk();
  var todo = b.rows.filter(function (r) { return r.state !== "done"; });
  var ask = todo.filter(function (r) { return r.file && !r.record; });
  todo.forEach(function (r) {
    r.problems = r.file ? null : ["No video file: go back to Videos and add " + r.name + "."];
  });
  b.checking = true;
  b.asked = true;
  b.checkError = "";
  var answer = ask.length ? api("POST", "/api/uploads/check", { items: ask.map(itemOf) })
    : Promise.resolve({ items: [], ok: true });
  answer.then(function (res) {
    res.items.forEach(function (r, i) {
      ask[i].problems = r.problems;
      ask[i].folder = r.folder_name;
    });
    b.checked = !todo.some(function (r) { return r.problems && r.problems.length; });
  }).catch(function (e) {
    b.checked = false;
    b.checkError = e.message;
  }).then(function () {
    b.checking = false;
    done();
  });
}

function bar(box, back, backTo, next) {
  var row = el("div", "hub-up__bar");
  var b = button(back);
  b.addEventListener("click", function () {
    if (bulk().running) return;
    up.step = backTo;
    drawWizard();
  });
  row.appendChild(b);
  if (next) row.appendChild(next);
  box.appendChild(row);
  return row;
}

/* ── step 2: the videos ────────────────────────────────────────────────── */
function stepVideos(box) {
  var b = bulk();
  box.appendChild(el("p", "hub-up__muted", "First add the videos: each one becomes its own "
    + "demo. Next you fill in their details, from a sheet or one by one."));
  box.appendChild(dropZone());
  if (b.note) box.appendChild(el("p", "hub-up__err", b.note));
  var withFile = b.rows.filter(function (r) { return r.file; });
  if (b.rows.length) {
    var list = el("div", "hub-bulk__rows");
    b.rows.forEach(function (row) {
      var line = el("div", "hub-up__file");
      line.appendChild(el("span", "hub-up__path", row.name));
      line.appendChild(el("span", row.file ? "hub-up__muted" : "hub-up__err",
                          row.file ? size(row.size) : "Named in the sheet, not added yet"));
      var x = button("Remove");
      x.disabled = row.state === "done";
      x.addEventListener("click", function () {
        b.rows = b.rows.filter(function (r) { return r !== row; });
        stale();
        drawWizard();
      });
      line.appendChild(x);
      list.appendChild(line);
    });
    box.appendChild(list);
    var total = withFile.reduce(function (s, r) { return s + (r.size || 0); }, 0);
    box.appendChild(el("p", "hub-up__muted", withFile.length + " video"
      + (withFile.length === 1 ? "" : "s") + " · " + size(total)));
  }
  var next = button("Next: details", true);
  next.disabled = !withFile.length;
  next.addEventListener("click", function () { up.step = 3; drawWizard(); });
  bar(box, "Back", 1, next);
}

/* ── step 3: the details ───────────────────────────────────────────────── */
function stepDetails(box) {
  var b = bulk();
  box.appendChild(sheetTools());
  box.appendChild(el("p", "hub-up__muted hub-bulk__or", "Or fill in each video below: title "
    + "and description here, everything else under Details."));
  var missing = b.rows.filter(function (r) { return !r.file && r.state !== "done"; }).length;
  if (missing) {
    box.appendChild(el("p", "hub-up__err", missing + " row" + (missing === 1 ? " names a video"
      : "s name videos") + " not added yet: go back to Videos and add " + (missing === 1
      ? "it" : "them") + ", or remove the row."));
  }
  var list = el("div", "hub-bulk__rows");
  var head = el("div", "hub-bulk__line hub-bulk__head");
  ["#", "Video", "Title *", "Description *", ""].forEach(function (h) {
    head.appendChild(el("span", "hub-up__label", h));
  });
  list.appendChild(head);
  b.rows.forEach(function (row, i) { drawRow(list, row, i); });
  box.appendChild(list);
  var next = button("Next: check & create", true);
  next.disabled = !b.rows.some(function (r) { return r.state !== "done"; });
  next.addEventListener("click", function () { up.step = 4; drawWizard(); });
  bar(box, "Back", 2, next);
}

/* ── step 4: check, then create ────────────────────────────────────────── */
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
  // Checked once on the way in; anything edited since makes it check again.
  if (!b.asked && !b.checking && !b.running && todo.length) {
    checkAll(drawWizard);
  }
  if (b.checking) {
    box.appendChild(el("p", "hub-up__muted", "Checking " + todo.length + " video"
      + (todo.length === 1 ? "" : "s") + "… nothing is created yet."));
    bar(box, "Back", 3);
    return;
  }
  if (b.checkError) {
    box.appendChild(el("p", "hub-up__err", "The check did not finish: " + b.checkError));
    var again = button("Check again", true);
    again.addEventListener("click", function () { b.checkError = ""; b.asked = false; drawWizard(); });
    bar(box, "Back", 3, again);
    return;
  }
  if (!b.checked && todo.length) {
    var bad = todo.filter(function (r) { return r.problems && r.problems.length; });
    box.appendChild(el("p", "hub-up__err", bad.length + " of " + todo.length + " video"
      + (todo.length === 1 ? "" : "s") + (bad.length === 1 ? " needs" : " need")
      + " a change before anything is created. "
      + "Change them in the sheet or under Details, then come back here."));
    var probs = el("div", "hub-bulk__rows");
    bad.forEach(function (row) {
      var line = el("div", "hub-bulk__crow");
      var head = el("div", "hub-bulk__chead");
      head.appendChild(el("b", "hub-up__title", effective(row).title || row.name));
      head.appendChild(el("span", "hub-up__muted", row.name));
      line.appendChild(head);
      line.appendChild(el("div", "hub-up__err", row.problems.join(" ")));
      probs.appendChild(line);
    });
    box.appendChild(probs);
    bar(box, "Back to details", 3);
    return;
  }
  box.appendChild(el("p", "hub-up__ok", todo.length === 1 ? "Checked: it can be created."
    : "Checked: all " + todo.length + " videos can be created."));
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
  var go = button(b.rows.some(function (r) { return r.state === "failed"; })
    ? "Try the failed ones again" : "Create " + todo.length + " demo" + (todo.length === 1 ? "" : "s"),
    true);
  go.disabled = !todo.length || b.running;
  var msg = el("span", "hub-up__muted");
  var foot = bar(box, "Back", 3, go);
  var back = foot.firstChild;
  foot.appendChild(msg);
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
          up.step = 2;
          drawWizard();
        });
        foot.appendChild(again);
      }
    });
  });
}

function drawBulk(box) {
  if (up.step === 2) stepVideos(box);
  else if (up.step === 3) stepDetails(box);
  else stepCreate(box);
}

export { BULK_STEPS, drawBulk, applySheet, parseSheet, titleFromFile, productFromFile };
