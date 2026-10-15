/* The Metadata options tab: which Product, Segment, Language and Owned by
 * options Create New Demo offers, in what order, and the defaults
 * (backend/services/upload_options.py, 2026-10-15).
 *
 * The options are SharePoint's own: a new one is added there and appears
 * here after Refresh. Here an option is offered or not, moved up or down,
 * and -- for a single-choice field -- made the default. Options the Hub's
 * own rules keep out (products no longer sold, retired segments) are shown
 * locked. Saved per field; live at once.
 *
 * Part of the Admin page's script; static/js/admin/main.js loads it. */

import { $, el, session } from "./util.js";

var opt = { data: null, drafts: {} };

function canManage() {
  return (session.permissions || []).indexOf("manage_upload_options") >= 0;
}

function loadOptions(fresh) {
  var host = $("optList");
  host.innerHTML = "";
  host.appendChild(el("div", "faint", fresh ? "Reading the options from SharePoint again…"
                                            : "Reading the options…"));
  return fetch("/api/admin/upload-options" + (fresh ? "?fresh=true" : ""))
    .then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
        return d;
      });
    })
    .then(function (d) { opt.data = d; opt.drafts = {}; renderOptions(); })
    .catch(function (err) {
      host.innerHTML = "";
      host.appendChild(el("div", "faint", "Could not read the options: " + err.message));
    });
}

/* A field's options in the order the form shows them: the order saved
   here first, then SharePoint's. */
function draftFor(f) {
  if (opt.drafts[f.key]) return opt.drafts[f.key];
  var s = f.settings || {};
  var hidden = (s.hidden || []).slice();
  var saved = (s.order || []).filter(function (o) { return f.options.indexOf(o) >= 0; });
  var all = saved.concat(f.options.filter(function (o) { return saved.indexOf(o) < 0; }));
  // A hidden option keeps its place, after the offered ones.
  // Nothing chosen here yet: the form's own default (English, TDD) shows.
  opt.drafts[f.key] = { order: all, hidden: hidden,
                        default: s["default"] || f.builtin_default || null, dirty: false };
  return opt.drafts[f.key];
}

function renderOptions() {
  var host = $("optList");
  host.innerHTML = "";
  opt.data.forEach(function (f) { host.appendChild(fieldCard(f)); });
}

function fieldCard(f) {
  var box = el("div", "card opt-card");
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, f.label));
  if (f.libraries) head.appendChild(el("span", "faint", f.libraries.join(" · ")));
  box.appendChild(head);
  if (f.error) {
    box.appendChild(el("div", "faint", "Not available: " + f.error));
    return box;
  }
  var d = draftFor(f);
  var manage = canManage();
  var offered = d.order.filter(function (o) { return d.hidden.indexOf(o) < 0; }).length;
  box.appendChild(el("p", "dim-note", offered + " of " + d.order.length + " offered"
    + (f.single ? " · single choice: one may be the default" : "")
    + ". To add an option, add it to the column in SharePoint, then Refresh."));

  var filter = null;
  if (d.order.length > 12) {
    filter = el("input", "opt-filter");
    filter.type = "search";
    filter.placeholder = "Filter " + f.label.toLowerCase().split(" —")[0] + "…";
    box.appendChild(filter);
  }
  var list = el("div", "opt-list");
  d.order.forEach(function (o, i) {
    var on = d.hidden.indexOf(o) < 0;
    var row = el("div", "opt-row" + (on ? "" : " opt-row--off"));
    row.dataset.name = o.toLowerCase();
    var tick = el("input");
    tick.type = "checkbox";
    tick.checked = on;
    tick.disabled = !manage;
    tick.title = on ? "Offered: untick to stop offering it" : "Not offered: tick to offer it";
    tick.addEventListener("change", function () {
      if (tick.checked) d.hidden = d.hidden.filter(function (h) { return h !== o; });
      else {
        d.hidden.push(o);
        if (d["default"] === o) d["default"] = null;
      }
      d.dirty = true;
      renderOptions();
    });
    row.appendChild(tick);
    row.appendChild(el("span", "opt-name", o));
    if (f.single) {
      var def = el("label", "opt-default");
      var radio = el("input");
      radio.type = "radio";
      radio.name = "opt-default-" + f.key;
      radio.checked = d["default"] === o;
      radio.disabled = !manage || !on;
      radio.addEventListener("change", function () { d["default"] = o; d.dirty = true; renderOptions(); });
      def.appendChild(radio);
      def.appendChild(document.createTextNode(" default"));
      row.appendChild(def);
    } else {
      row.appendChild(el("span"));
    }
    var moves = el("span", "opt-moves");
    [["↑", -1, "Move up"], ["↓", 1, "Move down"]].forEach(function (m) {
      var b = el("button", "btn-small", m[0]);
      b.type = "button";
      b.title = m[2];
      b.disabled = !manage || (m[1] < 0 ? i === 0 : i === d.order.length - 1);
      b.addEventListener("click", function () {
        var j = i + m[1];
        var tmp = d.order[i];
        d.order[i] = d.order[j];
        d.order[j] = tmp;
        d.dirty = true;
        renderOptions();
      });
      moves.appendChild(b);
    });
    row.appendChild(moves);
    list.appendChild(row);
  });
  (f.locked || []).forEach(function (l) {
    var row = el("div", "opt-row opt-row--locked");
    row.dataset.name = l.option.toLowerCase();
    var tick = el("input");
    tick.type = "checkbox";
    tick.disabled = true;
    row.appendChild(tick);
    row.appendChild(el("span", "opt-name", l.option));
    row.appendChild(el("span", "faint", l.why));
    row.appendChild(el("span"));
    list.appendChild(row);
  });
  box.appendChild(list);
  if (filter) {
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      list.querySelectorAll(".opt-row").forEach(function (r) {
        r.hidden = q && r.dataset.name.indexOf(q) < 0;
      });
    });
  }

  if (!manage) {
    box.appendChild(el("p", "faint", "Changing these needs Manage metadata options."));
    return box;
  }
  var bar = el("div", "opt-bar");
  var save = el("button", "btn-primary", "Save");
  save.type = "button";
  save.disabled = !d.dirty;
  var reset = el("button", "btn-small", "SharePoint's order");
  reset.type = "button";
  reset.title = "Put the options back in the order SharePoint lists them";
  reset.addEventListener("click", function () {
    d.order = f.options.slice();
    d.dirty = true;
    renderOptions();
  });
  var status = el("span", "promo-status faint");
  if (f.settings && f.settings.by) {
    status.textContent = "Last changed " + new Date(f.settings.at).toLocaleString() + " by "
      + String(f.settings.by).replace(/^(user|dev):/, "");
  }
  save.addEventListener("click", function () {
    save.disabled = true;
    status.textContent = "Saving…";
    fetch("/api/admin/upload-options/" + encodeURIComponent(f.key), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hidden: d.hidden, order: d.order, "default": d["default"] }),
    }).then(function (r) {
      return r.json().then(function (b) {
        if (!r.ok) throw new Error(b.detail || ("HTTP " + r.status));
        return b;
      });
    }).then(function (saved) {
      f.settings = saved;
      delete opt.drafts[f.key];
      renderOptions();
    }).catch(function (err) {
      save.disabled = false;
      status.textContent = "Not saved: " + err.message;
      status.className = "promo-status err";
    });
  });
  bar.appendChild(save);
  bar.appendChild(reset);
  bar.appendChild(status);
  box.appendChild(bar);
  return box;
}

export { loadOptions };
