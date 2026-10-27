/* Editing a demo on its Details card (A1, Liwei 2026-10-26).
 *
 * People with "Edit metadata" (Administrators, TDD Team) get an Edit
 * button on the Details table. It opens the library's own fields in a
 * dialog -- the side card is too narrow for them -- the upload form's,
 * minus the title, plus the Demo Owner --
 * filled from SharePoint as it is now (GET /api/assets/{id}/metadata).
 * Save writes what changed to the demo's folder at once, no review; the
 * server refuses it if SharePoint changed since the editor opened.
 *
 * Two more things live here, each saved the moment it is chosen: the video
 * the demo is previewed with (several videos), and the card's picture (B5)
 * -- an image uploaded, or a frame picked from one of the demo's videos,
 * drawn in the browser from SharePoint's CORS-open address. */

import { report } from "./util.js";
import { hubPermissions } from "./permissions.js";
import { openAssetDetail } from "./detail.js";
import { refill, videoState } from "./videorules.js";

function mk(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function call(method, url, body) {
  var opts = { method: method };
  if (body instanceof FormData) opts.body = body;
  else if (body) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  return fetch(url, opts).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
      return d;
    });
  });
}

function base(asset) { return "/api/assets/" + encodeURIComponent(asset.id); }

/* Only a SharePoint kit or video: Consensus and page-only demos are read
 * only (the server says so too). */
function editable(asset) {
  return (asset.source || "sharepoint") === "sharepoint" && asset.id.indexOf("page-") !== 0
    && ["video", "ldk", "vdk"].indexOf(asset.type) >= 0;
}

/* The Edit button, shown once the person's permissions say so. */
function editButton(asset) {
  var b = mk("button", "hub-edit__open", "Edit");
  b.type = "button";
  b.hidden = true;
  if (!editable(asset)) return b;
  hubPermissions.then(function (granted) {
    if (granted.indexOf("edit_metadata") >= 0) b.hidden = false;
  });
  b.addEventListener("click", function () { openEditor(asset); });
  return b;
}

/* ------------------------------------------------------------- fields */

function control(f, value) {
  var input;
  if (f.kind === "longtext") {
    input = mk("textarea", "hub-edit__input");
    input.rows = f.key === "long_description" ? 6 : 3;
    input.value = value || "";
  } else if (f.kind === "choice" || f.kind === "yesno") {
    input = mk("select", "hub-edit__input");
    var options = f.kind === "yesno" ? [["", "—"], ["yes", "Yes"], ["no", "No"]]
      : [["", "—"]].concat((f.choices || []).map(function (c) { return [c, c]; }));
    if (f.kind === "choice" && value && (f.choices || []).indexOf(value) < 0) {
      options.push([value, value]);
    }
    options.forEach(function (o) { input.appendChild(new Option(o[1], o[0])); });
    input.value = f.kind === "yesno" ? (value === true ? "yes" : value === false ? "no" : "")
                                     : (value || "");
  } else if (f.kind === "multi") {
    return checkList(f, value || []);
  } else {
    input = mk("input", "hub-edit__input");
    input.type = f.kind === "date" ? "date" : f.key === "demo_owner" ? "email" : "text";
    input.value = value || "";
    if (f.max_length) input.maxLength = f.max_length;
    if (f.key === "product_version") input.placeholder = "e.g. Creo 12, or N/A";
    if (f.key === "demo_owner") input.placeholder = "name@ptc.com";
  }
  input.dataset.key = f.key;
  input.dataset.kind = f.kind;
  return input;
}

/* A multi-choice field as ticks; a long list (products) gets a filter. */
function checkList(f, values) {
  var box = mk("div", "hub-edit__multi");
  box.dataset.key = f.key;
  box.dataset.kind = "multi";
  var choices = (f.choices || []).slice();
  values.forEach(function (v) { if (choices.indexOf(v) < 0) choices.push(v); });
  var list = mk("div", "hub-edit__ticks");
  if (choices.length > 8) {
    var filter = mk("input", "hub-edit__input hub-edit__filter");
    filter.type = "search";
    filter.placeholder = "Filter " + f.label.toLowerCase() + "…";
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      list.querySelectorAll("label").forEach(function (l) {
        l.hidden = q && l.textContent.toLowerCase().indexOf(q) < 0 && !l.querySelector("input").checked;
      });
    });
    box.appendChild(filter);
  }
  choices.forEach(function (c) {
    var l = mk("label", "hub-edit__tick");
    var cb = mk("input");
    cb.type = "checkbox";
    cb.value = c;
    cb.checked = values.indexOf(c) >= 0;
    l.appendChild(cb);
    l.appendChild(document.createTextNode(c));
    list.appendChild(l);
  });
  box.appendChild(list);
  return box;
}

function valueOf(el) {
  var kind = el.dataset.kind;
  if (kind === "multi") {
    return Array.prototype.map.call(el.querySelectorAll("input[type=checkbox]:checked"),
                                    function (cb) { return cb.value; });
  }
  if (kind === "yesno") return el.value === "yes" ? true : el.value === "no" ? false : null;
  return el.value.trim();
}

/* ------------------------------------------------------------- editor */

function openEditor(asset) {
  var overlay = mk("div", "hub-edit__overlay");
  var editor = mk("div", "hub-edit__dialog hub-edit");
  editor.setAttribute("role", "dialog");
  editor.setAttribute("aria-label", "Edit " + asset.title);
  editor.appendChild(mk("div", "hub-edit__loading", "Reading SharePoint…"));
  overlay.appendChild(editor);
  document.body.appendChild(overlay);

  function close() {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e) { if (e.key === "Escape" && !document.querySelector(".hub-edit__frame")) close(); }
  document.addEventListener("keydown", onKey);

  call("GET", base(asset) + "/metadata").then(function (form) {
    editor.innerHTML = "";
    editor.appendChild(mk("div", "hub-edit__title", "Edit “" + form.title + "”"));
    editor.appendChild(mk("div", "hub-edit__note", form.library));
    editor.appendChild(mk("div", "hub-edit__note",
      "Saved straight to SharePoint and recorded in the Admin log. The title is the "
      + "folder's name and is not changed here."));
    var grid = mk("div", "hub-edit__grid");
    form.fields.forEach(function (f) {
      var row = mk("label", "hub-edit__row");
      var name = mk("span", "hub-edit__label", f.label + (f.required ? " *" : ""));
      row.appendChild(name);
      var c = control(f, form.values[f.key]);
      row.appendChild(c);
      if (f.help) row.appendChild(mk("span", "hub-edit__help", f.help));
      // Empty in SharePoint though the Hub shows something (Liwei,
      // 2026-10-28): left blank, and what the Hub shows said beside it.
      var shown = (form.hub_shows || {})[f.key];
      if (shown) {
        var hint = mk("span", "hub-edit__assumed");
        hint.appendChild(document.createTextNode("Not filled in SharePoint. The Hub shows "));
        hint.appendChild(mk("b", null, shown.value));
        hint.appendChild(document.createTextNode(" — " + shown.why + "."));
        row.appendChild(hint);
      }
      grid.appendChild(row);
    });
    editor.appendChild(grid);
    if (form.video_rules) followType(grid, form);

    if (form.videos.length > 1) editor.appendChild(previewChooser(asset, form));
    if (form.thumbnail.can_choose) editor.appendChild(pictureChooser(asset, form));

    var bar = mk("div", "hub-edit__bar");
    var save = mk("button", "hub-edit__save", "Save");
    save.type = "button";
    var cancel = mk("button", "hub-edit__cancel", "Cancel");
    cancel.type = "button";
    var msg = mk("span", "hub-edit__msg");
    cancel.addEventListener("click", close);
    save.addEventListener("click", function () {
      var values = {};
      grid.querySelectorAll("[data-key]").forEach(function (el) {
        values[el.dataset.key] = valueOf(el);
      });
      save.disabled = cancel.disabled = true;
      msg.textContent = "Saving…";
      call("PUT", base(asset) + "/metadata", { values: values, etag: form.etag })
        .then(function (d) {
          report(d.changed.length ? "Saved to SharePoint: " + d.changed.length
                   + (d.changed.length === 1 ? " field." : " fields.") : "Nothing changed.");
          openAssetDetail(asset.id);
        })
        .catch(function (e) {
          save.disabled = cancel.disabled = false;
          msg.textContent = e.message;
          msg.classList.add("is-error");
        });
    });
    bar.appendChild(save);
    bar.appendChild(cancel);
    bar.appendChild(msg);
    editor.appendChild(bar);
  }).catch(function (e) {
    editor.innerHTML = "";
    editor.appendChild(mk("div", "hub-edit__msg is-error", e.message));
    var back = mk("button", "hub-edit__cancel", "Back");
    back.type = "button";
    back.addEventListener("click", close);
    editor.appendChild(back);
  });
}

/* A video's subtype follows its type, and only a customer video names its
 * customer (A15, 2026-10-27). A retired subtype the video already has
 * (Release) stays on offer for its own type. */
function followType(grid, form) {
  var type = grid.querySelector('[data-key="video_type"]');
  var sub = grid.querySelector('[data-key="video_subtype"]');
  var customer = grid.querySelector('[data-key="named_customer"]');
  if (!type || !sub) return;
  var keep = { type: form.values.video_type, subtype: form.values.video_subtype };
  function sync() {
    var state = videoState(form.video_rules, { video_type: type.value, video_subtype: sub.value }, keep);
    if (state.subtypes) refill(sub, state.subtypes, "Choose…");
    else { sub.innerHTML = ""; sub.appendChild(new Option(state.fixed || "", state.fixed || "")); }
    var subRow = sub.closest(".hub-edit__row");
    subRow.hidden = !state.subtypes;
    var note = subRow.querySelector(".hub-edit__missing");
    if (state.missing.length) {
      if (!note) { note = mk("span", "hub-edit__help hub-edit__missing"); subRow.appendChild(note); }
      note.textContent = "Not in SharePoint's Video subtype list yet: " + state.missing.join(", ") + ".";
    } else if (note) note.remove();
    state = videoState(form.video_rules, { video_type: type.value, video_subtype: sub.value }, keep);
    if (customer) {
      customer.closest(".hub-edit__row").hidden = !state.customer;
      // Kept aside while hidden, so switching the type back and forth does
      // not lose the customer's name.
      if (!state.customer && customer.value) { customer.dataset.kept = customer.value; customer.value = ""; }
      if (state.customer && !customer.value && customer.dataset.kept) customer.value = customer.dataset.kept;
    }
  }
  type.addEventListener("change", sync);
  sub.addEventListener("change", sync);
  sync();
}

/* Which video the demo is previewed with: saved when chosen. */
function previewChooser(asset, form) {
  var box = mk("div", "hub-edit__section");
  box.appendChild(mk("div", "hub-edit__label", "Preview video"));
  var select = mk("select", "hub-edit__input");
  if (!form.preview) {
    var none = new Option("Not chosen yet", "");
    none.disabled = true;
    select.appendChild(none);
  }
  form.videos.slice().sort(function (a, b) { return a.name.localeCompare(b.name); })
    .forEach(function (v) {
      select.appendChild(new Option((v.subfolder ? v.subfolder + "/" : "") + v.name, v.item_id));
    });
  select.value = form.preview || "";
  var msg = mk("span", "hub-edit__help", "The video the demo opens with. Saved when chosen.");
  select.addEventListener("change", function () {
    msg.textContent = "Saving…";
    call("PUT", base(asset) + "/preview-video", { item_id: select.value })
      .then(function () { msg.textContent = "Saved."; })
      .catch(function (e) { msg.textContent = e.message; });
  });
  box.appendChild(select);
  box.appendChild(msg);
  return box;
}

/* ------------------------------------------------------- card picture */

function pictureChooser(asset, form) {
  var box = mk("div", "hub-edit__section");
  box.appendChild(mk("div", "hub-edit__label", "Card picture"));
  var state = mk("div", "hub-edit__help", form.thumbnail.chosen
    ? "A chosen picture is shown." : "Automatic: the Hub picks the picture.");
  box.appendChild(state);
  var row = mk("div", "hub-edit__pics");

  var file = mk("input");
  file.type = "file";
  file.accept = "image/jpeg,image/png,image/webp";
  file.hidden = true;
  var upload = mk("button", "hub-edit__btn", "Upload an image");
  upload.type = "button";
  upload.addEventListener("click", function () { file.click(); });
  file.addEventListener("change", function () {
    if (file.files[0]) sendPicture(asset, file.files[0], state);
  });
  row.appendChild(upload);
  row.appendChild(file);

  if (form.videos.length) {
    var frame = mk("button", "hub-edit__btn", "Pick a frame from a video");
    frame.type = "button";
    frame.addEventListener("click", function () { framePicker(asset, form.videos, state); });
    row.appendChild(frame);
  }
  if (form.thumbnail.chosen) {
    var auto = mk("button", "hub-edit__btn", "Use the automatic picture");
    auto.type = "button";
    auto.addEventListener("click", function () {
      state.textContent = "Saving…";
      call("DELETE", base(asset) + "/thumbnail")
        .then(function () { report("The card uses the automatic picture again."); openAssetDetail(asset.id); })
        .catch(function (e) { state.textContent = e.message; });
    });
    row.appendChild(auto);
  }
  box.appendChild(row);
  return box;
}

function sendPicture(asset, blob, state) {
  if (blob.size > 5 * 1024 * 1024) { state.textContent = "A picture of at most 5 MB, please."; return; }
  state.textContent = "Saving the picture to SharePoint…";
  var data = new FormData();
  data.append("file", blob, blob.name || "frame.jpg");
  call("PUT", base(asset) + "/thumbnail", data)
    .then(function () { report("The card shows the new picture."); openAssetDetail(asset.id); })
    .catch(function (e) { state.textContent = e.message; });
}

/* A video in a frame: scrub to the moment, Use this frame. The video plays
 * from SharePoint's own short-lived address (CORS open), so the frame can
 * be drawn onto a canvas and saved as a JPG. */
function framePicker(asset, videos, state) {
  var overlay = mk("div", "hub-edit__overlay hub-edit__frame");
  var dialog = mk("div", "hub-edit__dialog");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-label", "Pick a frame");
  dialog.appendChild(mk("div", "hub-edit__title", "Pick a frame for the card"));
  var select = mk("select", "hub-edit__input");
  videos.forEach(function (v) { select.appendChild(new Option(v.name, v.item_id)); });
  if (videos.length > 1) dialog.appendChild(select);
  var video = mk("video", "hub-edit__video");
  video.controls = true;
  video.crossOrigin = "anonymous";
  video.preload = "metadata";
  video.muted = true;
  dialog.appendChild(video);
  var msg = mk("div", "hub-edit__help", "Play or drag to the moment you want, then Use this frame.");
  dialog.appendChild(msg);
  var bar = mk("div", "hub-edit__bar");
  var use = mk("button", "hub-edit__save", "Use this frame");
  use.type = "button";
  var cancel = mk("button", "hub-edit__cancel", "Cancel");
  cancel.type = "button";
  bar.appendChild(use);
  bar.appendChild(cancel);
  dialog.appendChild(bar);
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  function shut() { video.pause(); video.removeAttribute("src"); video.load(); overlay.remove(); }
  function load(itemId) {
    msg.textContent = "Loading the video…";
    call("GET", base(asset) + "/files/" + encodeURIComponent(itemId) + "/frame-source")
      .then(function (d) { video.src = d.url; msg.textContent = "Play or drag to the moment you want, then Use this frame."; })
      .catch(function (e) { msg.textContent = e.message; });
  }
  select.addEventListener("change", function () { load(select.value); });
  cancel.addEventListener("click", shut);
  overlay.addEventListener("click", function (e) { if (e.target === overlay) shut(); });
  use.addEventListener("click", function () {
    if (!video.videoWidth) { msg.textContent = "The video has not loaded yet."; return; }
    var scale = Math.min(1, 1280 / video.videoWidth);
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    try {
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(function (blob) {
        if (!blob) { msg.textContent = "This frame could not be taken; try Upload an image."; return; }
        shut();
        sendPicture(asset, blob, state);
      }, "image/jpeg", 0.88);
    } catch (e) {
      msg.textContent = "The browser would not hand over this frame; try Upload an image.";
    }
  });
  load(videos[0].item_id);
}

export { editButton };
