/* Create New Demo (#/upload, 2026-10-15).
 *
 * Four steps -- the destination (platform, then kind), its metadata, its
 * files, a last look -- and the upload itself. Destinations: SharePoint
 * today; Consensus and Brightcove are listed, not yet available. The metadata comes first and is required: the Upload
 * button stays off until every required field is filled, and the server
 * checks again (routers/uploads.py). Choices are the library's own options.
 *
 * The browser sends each file straight to SharePoint, in chunks, to an
 * upload URL the Hub opens for it; the Hub never handles the bytes. Then the
 * Hub writes the metadata and the demo waits for review: it is listed once
 * someone with Review content publishes it. "My uploads" shows where each
 * of the person's uploads stands, what a reviewer sent back, and continues
 * an interrupted one.
 *
 * Part of the Hub page's script; static/js/hub/main.js loads it. */

import { report } from "./util.js";
import { hubPermissions } from "./permissions.js";
import { closeActivity } from "./activity.js";
import { closeAdvancedSearch } from "./search.js";

//: 32 x 320 KiB: Graph wants chunks in multiples of 320 KiB, under 60 MiB.
var CHUNK = 32 * 320 * 1024;
var STATUS_WORD = { uploading: "Uploading", pending: "Waiting for review",
                    sent_back: "Sent back", published: "Published", cancelled: "Cancelled" };

var up = { platforms: null, targets: null, platform: null, target: null, kind: null,
           values: {}, internal: false, files: [], preview: null, busy: false, step: 1 };
var VIDEO_EXT = ["mp4", "mov", "m4v", "webm", "wmv", "avi", "mkv"];

function isVideo(path) {
  return VIDEO_EXT.indexOf(String(path).split(".").pop().toLowerCase()) >= 0;
}

/* With two or more videos the person chooses the preview (PreviewVideo,
   Liwei 2026-10-15); with one, it is that one. */
function previewChoice() {
  var videos = up.files.filter(function (f) { return isVideo(f.path); });
  if (videos.length === 1) return videos[0].path;
  return videos.some(function (v) { return v.path === up.preview; }) ? up.preview : null;
}

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function api(method, url, body) {
  return fetch(url, {
    method: method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
      return d;
    });
  });
}

function size(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  return Math.max(1, Math.round(n / 1e3)) + " KB";
}

/* ── the page ─────────────────────────────────────────────────────────── */
function buildUploadPage() {
  var page = document.getElementById("hubUploadPage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubUploadPage";
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to Technical Marketing Hub</button>'
    + '<div class="vp-head"><div>'
    +   '<div class="vp-title">Create New Demo</div>'
    +   '<div class="orion-subtle">A video or a demo kit, with its metadata. '
    +   'It appears in the Hub once a reviewer publishes it.</div>'
    + '</div></div>'
    + '<div class="hub-up" id="hubUp"></div>';
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeUpload();
  });
  return page;
}

function openUpload() {
  var page = buildUploadPage();
  closeAdvancedSearch();
  closeActivity();
  var request = document.getElementById("requestViewPage");
  if (request) request.classList.remove("active");
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  page.classList.add("active");
  markNav(true);
  render();
}

function closeUpload() {
  var page = document.getElementById("hubUploadPage");
  if (!page || !page.classList.contains("active")) return;
  page.classList.remove("active");
  markNav(false);
  var detail = document.getElementById("videoPreviewPage");
  if (detail && detail.classList.contains("active")) return;
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "";
  if (thread) thread.style.display = "";
}

function render() {
  var host = document.getElementById("hubUp");
  host.innerHTML = "";
  var mine = el("section", "hub-up__card");
  mine.id = "hubUpMine";
  host.appendChild(mine);
  loadMine();
  var wizard = el("section", "hub-up__card");
  wizard.id = "hubUpWizard";
  host.appendChild(wizard);
  if (up.targets) { drawWizard(); return; }
  wizard.appendChild(el("p", "hub-up__muted", "Reading the destinations' options…"));
  api("GET", "/api/uploads/targets").then(function (t) {
    up.platforms = t.platforms;
    up.targets = t.targets;
    drawWizard();
  }).catch(function (e) {
    wizard.innerHTML = "";
    wizard.appendChild(el("p", "hub-up__err", "Could not read the upload options: " + e.message));
  });
}

/* ── My uploads ───────────────────────────────────────────────────────── */
function loadMine() {
  var box = document.getElementById("hubUpMine");
  api("GET", "/api/uploads?mine=true&limit=20").then(function (items) {
    box.innerHTML = "";
    box.appendChild(el("h3", "hub-up__h", "My demos"));
    if (!items.length) {
      box.appendChild(el("p", "hub-up__muted", "Nothing created yet."));
      return;
    }
    items.forEach(function (r) {
      var row = el("div", "hub-up__mine");
      var info = el("div");
      var title = r.asset_id ? el("a", "hub-up__title", r.title) : el("b", "hub-up__title", r.title);
      if (r.asset_id) title.href = "#/asset/" + encodeURIComponent(r.asset_id);
      info.appendChild(title);
      info.appendChild(el("div", "hub-up__muted", (r.folder_name || "") + " · "
        + new Date(r.created_at).toLocaleDateString()));
      if (r.status === "sent_back" && r.note) {
        info.appendChild(el("div", "hub-up__note", "Reviewer: " + r.note));
      }
      if (r.error) info.appendChild(el("div", "hub-up__err", r.error));
      row.appendChild(info);
      var right = el("div", "hub-up__mineacts");
      right.appendChild(el("span", "hub-up__status hub-up__status--" + r.status,
                           STATUS_WORD[r.status] || r.status));
      if (r.status === "uploading") {
        var cont = button("Continue");
        cont.addEventListener("click", function () { continueUpload(r); });
        right.appendChild(cont);
      }
      if (r.status === "sent_back") {
        var fix = button("Fix and resubmit");
        fix.addEventListener("click", function () { resubmitForm(r); });
        right.appendChild(fix);
      }
      if (r.status === "uploading" || r.status === "sent_back") {
        var stop = button("Cancel");
        stop.addEventListener("click", function () {
          if (stop.dataset.armed !== "1") {
            stop.dataset.armed = "1";
            stop.textContent = "Cancel it?";
            return;
          }
          api("POST", "/api/uploads/" + r.id + "/cancel").then(loadMine)
            .catch(function (e) { report(e.message, true); });
        });
        right.appendChild(stop);
      }
      row.appendChild(right);
      box.appendChild(row);
    });
  }).catch(function () { box.innerHTML = ""; });
}

function button(text, primary) {
  var b = el("button", "hub-up__btn" + (primary ? " hub-up__btn--primary" : ""), text);
  b.type = "button";
  return b;
}

/* ── the wizard ───────────────────────────────────────────────────────── */
function steps(box) {
  var strip = el("ol", "hub-up__steps");
  ["Destination", "Metadata", "Files", "Create"].forEach(function (s, i) {
    var li = el("li", i + 1 === up.step ? "on" : (i + 1 < up.step ? "done" : ""), s);
    strip.appendChild(li);
  });
  box.appendChild(strip);
}

function drawWizard() {
  var box = document.getElementById("hubUpWizard");
  box.innerHTML = "";
  box.appendChild(el("h3", "hub-up__h", "New demo"));
  steps(box);
  if (up.step === 1) stepWhere(box);
  else if (up.step === 2) stepMetadata(box);
  else if (up.step === 3) stepFiles(box);
  else stepUpload(box);
}

function stepWhere(box) {
  box.appendChild(el("p", "hub-up__label", "Platform"));
  var platforms = el("div", "hub-up__choices");
  up.platforms.forEach(function (p) {
    var card = el("button", "hub-up__choice" + (up.platform === p.key ? " on" : ""));
    card.type = "button";
    card.disabled = !p.available;
    card.appendChild(el("b", null, p.label));
    card.appendChild(el("span", null, p.description));
    card.addEventListener("click", function () {
      if (up.platform !== p.key) { up.target = null; up.kind = null; }
      up.platform = p.key;
      drawWizard();
    });
    platforms.appendChild(card);
  });
  box.appendChild(platforms);
  if (!up.platform) return;
  box.appendChild(el("p", "hub-up__label hub-up__label--gap", "What kind of demo"));
  var grid = el("div", "hub-up__choices");
  up.targets.filter(function (t) { return t.platform === up.platform; }).forEach(function (t) {
    t.kinds.forEach(function (k) {
      var card = el("button", "hub-up__choice");
      card.type = "button";
      card.disabled = !!t.unavailable;
      if (t.unavailable) card.title = t.unavailable;
      var on = up.target && up.target.key === t.key && up.kind === k.key;
      if (on) card.classList.add("on");
      card.appendChild(el("b", null, k.label));
      card.appendChild(el("span", null, t.single_video
        ? "One video file" : "Any files and folders"));
      if (t.test_library) card.appendChild(el("span", "hub-up__err", "Test library — not listed in the Hub"));
      card.addEventListener("click", function () {
        if (!up.target || up.target.key !== t.key) { up.values = {}; up.files = []; }
        up.target = t;
        up.kind = k.key;
        up.step = 2;
        drawWizard();
      });
      grid.appendChild(card);
    });
  });
  box.appendChild(grid);
}

function fieldValue(f) {
  if (up.values[f.key] !== undefined) return up.values[f.key];
  return f.default != null ? f.default : (f.kind === "multi" ? [] : "");
}

function missingFields() {
  return up.target.fields.filter(function (f) {
    if (!f.required) return false;
    var v = fieldValue(f);
    if (f.kind === "yesno") return v !== true && v !== false;
    return v == null || v === "" || (Array.isArray(v) && !v.length);
  });
}

/* The form, drawn from the target's fields. Writes into `values` (up.values
   while uploading; a copy when fixing a sent-back upload). */
function metadataForm(target, values, opts) {
  opts = opts || {};
  var form = el("div", "hub-up__form");
  target.fields.forEach(function (f) {
    var v = values[f.key] !== undefined ? values[f.key]
      : (f.default != null ? f.default : (f.kind === "multi" ? [] : ""));
    values[f.key] = v;
    var row = el("label", "hub-up__field");
    var label = el("span", "hub-up__label", f.label);
    if (f.required) label.appendChild(el("i", "hub-up__req", " *"));
    row.appendChild(label);
    var input;
    if (f.kind === "text" || f.kind === "date") {
      input = el("input");
      input.type = f.kind === "date" ? "date" : "text";
      if (f.kind === "date") input.max = new Date().toISOString().slice(0, 10);
      if (f.max_length) input.maxLength = f.max_length;
      input.value = v || "";
      if (f.key === "title" && opts.lockTitle) input.disabled = true;
      input.addEventListener("input", function () { values[f.key] = input.value; opts.onChange(); });
    } else if (f.kind === "longtext") {
      input = el("textarea");
      input.rows = f.key === "long_description" ? 4 : 3;
      if (f.max_length) input.maxLength = f.max_length;
      input.value = v || "";
      input.addEventListener("input", function () { values[f.key] = input.value; opts.onChange(); });
    } else if (f.kind === "choice") {
      input = el("select");
      input.appendChild(new Option(f.required ? "Choose…" : "—", ""));
      (f.choices || []).forEach(function (c) { input.appendChild(new Option(c, c)); });
      input.value = v || "";
      input.addEventListener("change", function () { values[f.key] = input.value; opts.onChange(); });
    } else if (f.kind === "yesno") {
      input = el("span", "hub-up__yesno");
      [["Yes", true], ["No", false]].forEach(function (o) {
        var b = el("button", "hub-up__pill" + (v === o[1] ? " on" : ""), o[0]);
        b.type = "button";
        b.addEventListener("click", function (e) {
          e.preventDefault();
          values[f.key] = o[1];
          input.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
          b.classList.add("on");
          opts.onChange();
        });
        input.appendChild(b);
      });
    } else if (f.kind === "multi" && (f.choices || []).length > 12) {
      input = multiCombo(f, values, opts);
    } else if (f.kind === "multi") {
      input = el("span", "hub-up__multi");
      (f.choices || []).forEach(function (c) {
        var on = (values[f.key] || []).indexOf(c) >= 0;
        var b = el("button", "hub-up__pill" + (on ? " on" : ""), c);
        b.type = "button";
        b.addEventListener("click", function (e) {
          e.preventDefault();
          var list = (values[f.key] || []).slice();
          var at = list.indexOf(c);
          if (at >= 0) list.splice(at, 1); else list.push(c);
          values[f.key] = list;
          b.classList.toggle("on", at < 0);
          opts.onChange();
        });
        input.appendChild(b);
      });
    }
    row.appendChild(input);
    if (f.help) row.appendChild(el("span", "hub-up__help", f.help));
    if (f.not_stored) row.appendChild(el("span", "hub-up__err", "Not stored in the test library."));
    form.appendChild(row);
  });
  return form;
}

/* A long option list (Products: 44-49) as a searchable multi-select: the
   chosen ones as removable chips, the rest found by typing. Keyboard: arrows
   move, Enter adds, Backspace on an empty box removes the last chip, Escape
   closes. A short list (Segment) stays as pills, all visible at once. */
function multiCombo(f, values, opts) {
  var box = el("div", "hub-up__combo");
  box.setAttribute("role", "group");
  var chips = el("span", "hub-up__chips");
  var input = el("input", "hub-up__combo-input");
  input.type = "text";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.placeholder = "Search " + f.label.toLowerCase() + "…";
  var list = el("ul", "hub-up__options");
  list.setAttribute("role", "listbox");
  list.hidden = true;
  var active = 0, shown = [];

  function chosen() { return values[f.key] || []; }
  function set(next) { values[f.key] = next; drawChips(); opts.onChange(); }

  function drawChips() {
    chips.innerHTML = "";
    chosen().forEach(function (c) {
      var chip = el("span", "hub-up__chip", c);
      var x = el("button", "hub-up__chip-x", "×");
      x.type = "button";
      x.setAttribute("aria-label", "Remove " + c);
      x.addEventListener("click", function (e) {
        e.preventDefault();
        set(chosen().filter(function (v) { return v !== c; }));
        input.focus();
      });
      chip.appendChild(x);
      chips.appendChild(chip);
    });
    input.placeholder = chosen().length ? "Add another…" : "Search " + f.label.toLowerCase() + "…";
  }

  function drawList() {
    var q = input.value.trim().toLowerCase();
    shown = (f.choices || []).filter(function (c) {
      return chosen().indexOf(c) < 0 && (!q || c.toLowerCase().indexOf(q) >= 0);
    });
    active = Math.min(active, Math.max(shown.length - 1, 0));
    list.innerHTML = "";
    if (!shown.length) list.appendChild(el("li", "hub-up__option hub-up__option--none",
                                          q ? "No match" : "All chosen"));
    shown.forEach(function (c, i) {
      var li = el("li", "hub-up__option" + (i === active ? " on" : ""), c);
      li.setAttribute("role", "option");
      li.addEventListener("mousedown", function (e) { e.preventDefault(); });   // keep focus
      li.addEventListener("click", function (e) { e.preventDefault(); pick(c); });
      list.appendChild(li);
    });
    var on = list.querySelector(".on");
    if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest" });
  }

  function open(yes) {
    list.hidden = !yes;
    input.setAttribute("aria-expanded", yes ? "true" : "false");
    if (yes) drawList();
  }

  function pick(c) {
    set(chosen().concat([c]));
    input.value = "";
    active = 0;
    drawList();
  }

  input.addEventListener("focus", function () { open(true); });
  input.addEventListener("input", function () { active = 0; open(true); });
  input.addEventListener("blur", function () { open(false); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, shown.length - 1); open(true); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); open(true); }
    else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) pick(shown[active]); }
    else if (e.key === "Escape") { open(false); }
    else if (e.key === "Backspace" && !input.value && chosen().length) {
      set(chosen().slice(0, -1));
    }
  });
  // The field is a <label>: a click on the chips must not refocus elsewhere.
  box.addEventListener("click", function (e) { e.preventDefault(); input.focus(); });

  var field = el("div", "hub-up__combo-field");
  field.appendChild(chips);
  field.appendChild(input);
  box.appendChild(field);
  box.appendChild(list);
  drawChips();
  return box;
}

function stepMetadata(box) {
  var bar = el("div", "hub-up__bar");
  var next = button("Next: files", true);
  var back = button("Back");
  var note = el("span", "hub-up__muted");
  var refresh = function () {
    var missing = missingFields();
    next.disabled = missing.length > 0;
    note.textContent = missing.length
      ? "Still needed: " + missing.map(function (f) { return f.label; }).join(", ") : "";
  };
  box.appendChild(el("p", "hub-up__muted", up.target.kinds.filter(function (k) {
    return k.key === up.kind; })[0].label + ". Fields marked * are required."));
  box.appendChild(metadataForm(up.target, up.values, { onChange: refresh }));
  var internal = el("label", "hub-up__check");
  var tick = el("input");
  tick.type = "checkbox";
  tick.checked = up.internal;
  tick.addEventListener("change", function () { up.internal = tick.checked; });
  internal.appendChild(tick);
  internal.appendChild(document.createTextNode(" Internal only — files open only for people "
    + "with access to internal content (never partners)"));
  box.appendChild(internal);
  back.addEventListener("click", function () { up.step = 1; drawWizard(); });
  next.addEventListener("click", function () { up.step = 3; drawWizard(); });
  bar.appendChild(back);
  bar.appendChild(next);
  bar.appendChild(note);
  box.appendChild(bar);
  refresh();
}

function addFiles(list, keepFolders) {
  Array.prototype.forEach.call(list, function (file) {
    var path = (keepFolders && (file.webkitRelativePath || file.hubPath)) || file.name;
    if (up.target.single_video) up.files = [];
    if (up.files.some(function (x) { return x.path.toLowerCase() === path.toLowerCase(); })) return;
    up.files.push({ path: path, size: file.size, file: file });
  });
}

/* Dropped folders: walk them, keeping the paths below what was dropped. */
function walkDrop(items, done) {
  var pending = 0, out = [];
  function walk(entry, prefix) {
    pending++;
    if (entry.isFile) {
      entry.file(function (f) {
        f.hubPath = prefix + f.name;
        out.push(f);
        if (--pending === 0) done(out);
      }, function () { if (--pending === 0) done(out); });
    } else if (entry.isDirectory) {
      var reader = entry.createReader();
      var all = [];
      var read = function () {
        reader.readEntries(function (batch) {
          if (batch.length) { all = all.concat(Array.prototype.slice.call(batch)); read(); return; }
          all.forEach(function (child) { walk(child, prefix + entry.name + "/"); });
          if (--pending === 0) done(out);
        }, function () { if (--pending === 0) done(out); });
      };
      read();
    } else if (--pending === 0) done(out);
  }
  Array.prototype.forEach.call(items, function (it) {
    var entry = it.webkitGetAsEntry && it.webkitGetAsEntry();
    if (entry) walk(entry, "");
  });
  if (!pending) done(out);
}

function stepFiles(box) {
  var single = up.target.single_video;
  var drop = el("div", "hub-up__drop");
  drop.appendChild(el("b", null, single ? "Drop the video here" : "Drop files or folders here"));
  var pick = el("div", "hub-up__picks");
  var fileIn = el("input");
  fileIn.type = "file";
  fileIn.multiple = !single;
  if (single) fileIn.accept = "video/*,.mp4,.mov,.m4v,.webm,.wmv,.avi,.mkv";
  var pickFiles = button(single ? "Choose a video" : "Choose files");
  pickFiles.addEventListener("click", function () { fileIn.click(); });
  fileIn.addEventListener("change", function () { addFiles(fileIn.files, false); drawWizard(); });
  fileIn.hidden = true;
  pick.appendChild(fileIn);
  pick.appendChild(pickFiles);
  if (!single) {
    var dirIn = el("input");
    dirIn.type = "file";
    dirIn.webkitdirectory = true;
    var pickDir = button("Choose a folder");
    pickDir.addEventListener("click", function () { dirIn.click(); });
    dirIn.addEventListener("change", function () {
      // The chosen folder itself is the demo's folder: keep what is below it.
      Array.prototype.forEach.call(dirIn.files, function (f) {
        f.hubPath = (f.webkitRelativePath || f.name).split("/").slice(1).join("/") || f.name;
      });
      addFiles(dirIn.files, true);
      drawWizard();
    });
    dirIn.hidden = true;
    pick.appendChild(dirIn);
    pick.appendChild(pickDir);
  }
  drop.appendChild(pick);
  drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", function () { drop.classList.remove("over"); });
  drop.addEventListener("drop", function (e) {
    e.preventDefault();
    drop.classList.remove("over");
    if (single) { addFiles(e.dataTransfer.files, false); drawWizard(); return; }
    walkDrop(e.dataTransfer.items, function (files) { addFiles(files, true); drawWizard(); });
  });
  box.appendChild(drop);

  var list = el("div", "hub-up__files");
  var total = 0;
  up.files.forEach(function (f, i) {
    total += f.size;
    var row = el("div", "hub-up__file");
    row.appendChild(el("span", "hub-up__path", f.path));
    row.appendChild(el("span", "hub-up__muted", size(f.size)));
    var x = button("Remove");
    x.addEventListener("click", function () { up.files.splice(i, 1); drawWizard(); });
    row.appendChild(x);
    list.appendChild(row);
  });
  if (up.files.length) {
    list.appendChild(el("div", "hub-up__muted", up.files.length + " file"
      + (up.files.length === 1 ? "" : "s") + " · " + size(total)));
  }
  box.appendChild(list);

  var videos = up.files.filter(function (f) { return isVideo(f.path); });
  if (videos.length > 1) {
    var pick = el("div", "hub-up__preview");
    var label = el("span", "hub-up__label", "Preview video");
    label.appendChild(el("i", "hub-up__req", " *"));
    pick.appendChild(label);
    pick.appendChild(el("span", "hub-up__help", "The video the Hub plays for this demo. "
      + "Ticked Preview Video in SharePoint."));
    videos.forEach(function (v) {
      var row = el("label", "hub-up__radio");
      var radio = el("input");
      radio.type = "radio";
      radio.name = "hubUpPreview";
      radio.checked = up.preview === v.path;
      radio.addEventListener("change", function () { up.preview = v.path; drawWizard(); });
      row.appendChild(radio);
      row.appendChild(document.createTextNode(" " + v.path));
      pick.appendChild(row);
    });
    box.appendChild(pick);
  }

  var bar = el("div", "hub-up__bar");
  var back = button("Back");
  back.addEventListener("click", function () { up.step = 2; drawWizard(); });
  var next = button("Next: check and upload", true);
  next.disabled = !up.files.length || (videos.length > 1 && !previewChoice());
  if (videos.length > 1 && !previewChoice()) {
    bar.appendChild(el("span", "hub-up__muted", "Choose the preview video."));
  }
  next.addEventListener("click", function () { up.step = 4; drawWizard(); });
  bar.appendChild(back);
  bar.appendChild(next);
  box.appendChild(bar);
}

function platformLabel() {
  var p = (up.platforms || []).filter(function (x) { return x.key === up.platform; })[0];
  return p ? p.label : "";
}

function summary(box) {
  var dl = el("dl", "hub-up__summary");
  var add = function (k, v) {
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return;
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, Array.isArray(v) ? v.join(", ")
      : v === true ? "Yes" : v === false ? "No" : String(v)));
  };
  add("Destination", platformLabel() + " · " + up.target.library);
  up.target.fields.forEach(function (f) { add(f.label, fieldValue(f)); });
  add("Preview video", previewChoice());
  add("Internal only", up.internal);
  add("Files", up.files.length + " (" + size(up.files.reduce(function (s, f) {
    return s + f.size; }, 0)) + ")");
  box.appendChild(dl);
}

function stepUpload(box) {
  summary(box);
  var progress = el("div", "hub-up__progress");
  box.appendChild(progress);
  var bar = el("div", "hub-up__bar");
  var back = button("Back");
  back.addEventListener("click", function () { if (!up.busy) { up.step = 3; drawWizard(); } });
  var go = button("Create demo", true);
  var missing = missingFields();
  var needsPreview = up.files.filter(function (f) { return isVideo(f.path); }).length > 1
    && !previewChoice();
  go.disabled = missing.length > 0 || !up.files.length || needsPreview;
  var msg = el("span", "hub-up__err");
  if (missing.length) msg.textContent = "Fill in: " + missing.map(function (f) { return f.label; }).join(", ");
  go.addEventListener("click", function () {
    go.disabled = back.disabled = true;
    msg.textContent = "";
    var values = {};
    up.target.fields.forEach(function (f) { values[f.key] = fieldValue(f); });
    api("POST", "/api/uploads", {
      target: up.target.key, kind: up.kind, values: values, internal: up.internal,
      preview: previewChoice(),
      files: up.files.map(function (f) { return { path: f.path, size: f.size }; })
    }).then(function (record) {
      return sendAll(record, up.files, progress);
    }).then(function (record) {
      up = { platforms: up.platforms, targets: up.targets, platform: null, target: null,
             kind: null, values: {}, internal: false, files: [], preview: null, busy: false,
             step: 1 };
      var done = document.getElementById("hubUpWizard");
      done.innerHTML = "";
      var live = record.status === "published";
      done.appendChild(el("h3", "hub-up__h", live ? "Created and published"
                                                  : "Created — waiting for review"));
      done.appendChild(el("p", null, "“" + record.title + "” has been created. " + (live
        ? "It is published; it appears in the Hub within a minute or two."
        : "It appears in the Hub once a reviewer publishes it; My demos shows where it stands.")));
      var again = button("Create another", true);
      again.addEventListener("click", function () { drawWizard(); });
      done.appendChild(again);
      loadMine();
    }).catch(function (e) {
      up.busy = false;
      go.disabled = back.disabled = false;
      msg.textContent = e.message + (e.partial ? " Files already sent are kept; use Continue "
        + "in My demos to finish." : "");
      loadMine();
    });
  });
  bar.appendChild(back);
  bar.appendChild(go);
  bar.appendChild(msg);
  box.appendChild(bar);
}

/* ── sending ──────────────────────────────────────────────────────────── */
function warnLeaving(e) { e.preventDefault(); e.returnValue = ""; return ""; }

/* Every file not yet confirmed, one after another, then Finish. */
function sendAll(record, picked, progress) {
  up.busy = true;
  window.addEventListener("beforeunload", warnLeaving);
  var rows = record.files.map(function (f) {
    var row = el("div", "hub-up__prow");
    row.appendChild(el("span", "hub-up__path", f.path));
    var meter = el("span", "hub-up__meter");
    var fill = el("span");
    fill.style.width = f.done ? "100%" : "0%";
    meter.appendChild(fill);
    row.appendChild(meter);
    var pct = el("span", "hub-up__muted", f.done ? "done" : "");
    row.appendChild(pct);
    progress.appendChild(row);
    return { fill: fill, pct: pct };
  });
  var chain = Promise.resolve();
  record.files.forEach(function (f, i) {
    if (f.done) return;
    var local = picked.filter(function (p) { return p.path === f.path && p.size === f.size; })[0];
    chain = chain.then(function () {
      if (!local) throw new Error(f.path + " was not chosen again.");
      return sendFile(record.id, i, local.file, rows[i]);
    });
  });
  return chain.then(function () {
    return api("POST", "/api/uploads/" + record.id + "/finish");
  }).then(function (done) {
    window.removeEventListener("beforeunload", warnLeaving);
    up.busy = false;
    return done;
  }, function (err) {
    window.removeEventListener("beforeunload", warnLeaving);
    err.partial = true;
    throw err;
  });
}

function sendFile(uploadId, index, file, row) {
  return api("POST", "/api/uploads/" + uploadId + "/files/" + index + "/session")
    .then(function (s) {
      var offset = 0;
      var next = function () {
        var end = Math.min(offset + CHUNK, file.size);
        var put = function (attempt) {
          return fetch(s.upload_url, {
            method: "PUT",
            headers: { "Content-Range": "bytes " + offset + "-" + (end - 1) + "/" + file.size },
            body: file.slice(offset, end)
          }).then(function (r) {
            if ((r.status >= 500 || r.status === 429) && attempt < 5) {
              return new Promise(function (res) { setTimeout(res, 1500 * (attempt + 1)); })
                .then(function () { return put(attempt + 1); });
            }
            return r;
          }, function (err) {
            if (attempt < 5) {
              return new Promise(function (res) { setTimeout(res, 1500 * (attempt + 1)); })
                .then(function () { return put(attempt + 1); });
            }
            throw err;
          });
        };
        return put(0).then(function (r) {
          if (r.status === 202) {
            offset = end;
            var p = Math.round(offset / file.size * 100);
            row.fill.style.width = p + "%";
            row.pct.textContent = p + "%";
            return next();
          }
          if (r.status === 200 || r.status === 201) {
            return r.json().then(function (item) {
              row.fill.style.width = "100%";
              row.pct.textContent = "checking…";
              return api("POST", "/api/uploads/" + uploadId + "/files/" + index + "/done",
                         { item_id: item.id });
            }).then(function () { row.pct.textContent = "done"; });
          }
          throw new Error(file.name + ": SharePoint answered " + r.status);
        });
      };
      return next();
    });
}

/* An interrupted upload: choose the same files again; what is already in
   SharePoint is skipped. */
function continueUpload(record) {
  // Every file is in and only the last step failed: retry it, no files needed.
  if (record.files.every(function (f) { return f.done; })) {
    api("POST", "/api/uploads/" + record.id + "/finish")
      .then(function () { loadMine(); })
      .catch(function (e) { report(e.message, true); loadMine(); });
    return;
  }
  var input = el("input");
  input.type = "file";
  input.multiple = true;
  if (record.files.some(function (f) { return f.path.indexOf("/") >= 0; })) input.webkitdirectory = true;
  input.addEventListener("change", function () {
    var picked = Array.prototype.map.call(input.files, function (f) {
      var rel = f.webkitRelativePath ? f.webkitRelativePath.split("/").slice(1).join("/") : f.name;
      return { path: rel, size: f.size, file: f };
    });
    var box = document.getElementById("hubUpWizard");
    box.innerHTML = "";
    box.appendChild(el("h3", "hub-up__h", "Continuing “" + record.title + "”"));
    var progress = el("div", "hub-up__progress");
    box.appendChild(progress);
    sendAll(record, picked, progress).then(function () {
      box.appendChild(el("p", null, "Done — waiting for review."));
      loadMine();
    }).catch(function (e) {
      box.appendChild(el("p", "hub-up__err", e.message));
      loadMine();
    });
  });
  input.click();
}

/* Sent back: the same form, filled in, title fixed (it is the folder). */
function resubmitForm(record) {
  var target = (up.targets || []).filter(function (t) { return t.key === record.target; })[0];
  var box = document.getElementById("hubUpWizard");
  if (!target) { report("Upload options not loaded yet; try again.", true); return; }
  box.innerHTML = "";
  box.appendChild(el("h3", "hub-up__h", "Fix and resubmit “" + record.title + "”"));
  if (record.note) box.appendChild(el("div", "hub-up__note", "Reviewer: " + record.note));
  var values = JSON.parse(JSON.stringify(record.values || {}));
  var bar = el("div", "hub-up__bar");
  var send = button("Resubmit for review", true);
  var cancel = button("Cancel");
  var msg = el("span", "hub-up__err");
  var refresh = function () {
    send.disabled = target.fields.some(function (f) {
      var v = values[f.key];
      return f.required && (f.kind === "yesno" ? (v !== true && v !== false)
        : (v == null || v === "" || (Array.isArray(v) && !v.length)));
    });
  };
  box.appendChild(metadataForm(target, values, { onChange: refresh, lockTitle: true }));
  cancel.addEventListener("click", drawWizard);
  send.addEventListener("click", function () {
    send.disabled = true;
    api("POST", "/api/uploads/" + record.id + "/resubmit", { values: values })
      .then(function () { drawWizard(); loadMine(); })
      .catch(function (e) { msg.textContent = e.message; send.disabled = false; });
  });
  bar.appendChild(cancel);
  bar.appendChild(send);
  bar.appendChild(msg);
  box.appendChild(bar);
  refresh();
}

/* ── the sidebar entry ────────────────────────────────────────────────── */
function addUploadNav() {
  hubPermissions.then(function (granted) {
    if (granted.indexOf("upload_content") < 0 || document.getElementById("navUpload")) return;
    var request = document.getElementById("navRequestAsset");
    if (!request) return;
    var item = el("div", "orion-navitem");
    item.id = "navUpload";
    item.innerHTML = '<span class="label"><svg class="orion-ico orion-ico--sm ico-indigo">'
      + '<use href="#i-upload"/></svg> Create New Demo</span>';
    item.addEventListener("click", function () { location.hash = "#/upload"; });
    request.insertAdjacentElement("afterend", item);
    if (location.hash === "#/upload") markNav(true);
  });
}

function markNav(on) {
  var item = document.getElementById("navUpload");
  if (!item) return;
  item.classList.toggle("orion-navitem--active", on);
  // One item lit at a time, as Hub activity does.
  if (on) document.querySelectorAll(".orion-navitem--active, .orion-navitem.is-active")
    .forEach(function (n) {
      if (n !== item) n.classList.remove("orion-navitem--active", "is-active");
    });
}

export { addUploadNav, closeUpload, openUpload };
