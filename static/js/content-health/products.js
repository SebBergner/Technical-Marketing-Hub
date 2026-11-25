/* Content health -> Health check -> Fix products (Liwei, 2026-11-25): every
 * demo with no product that the Hub can fill in (GET / POST
 * /api/content-health/products).
 *
 * Three groups by how good the suggestion is, each with one action that
 * saves at once (redesigned the same day: a tick-then-save toolbar with five
 * controls read as unclear):
 *   1. the title names the product -- check, change any, "Accept all";
 *   2. only the description mentions products -- one at a time;
 *   3. no suggestion -- choose per row, or select several and set them.
 * A saved demo leaves the list; one that fails stays, with the reason.
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, demoLink, el, TYPE_WORD } from "../admin/util.js";

var state = null;        // {rows, choices, segments, fallback}
var rows = [];           // [{row, products, segment, editing, error, picked}]
var note = "";           // the last save's outcome, shown at the top

function button(text, cls, onClick) {
  var b = el("button", cls || "btn-small", text);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function option(select, value, text) {
  var o = el("option", null, text == null ? value : text);
  o.value = value;
  select.appendChild(o);
}

function choicesFor(item) {
  return state.choices[item.row.fix] || [];
}

function group(item) {
  var s = item.row.suggested;
  return s ? s.from : "none";
}

function chip(text, cls) {
  return el("span", "pf-chip" + (cls ? " " + cls : ""), text);
}

/* ------------------------------------------------------------- saving */

function save(items) {
  items = items.filter(function (it) { return it.products.length; });
  if (!items.length) return;
  items.forEach(function (it) { it.error = null; it.saving = true; });
  render();
  var chunks = [];
  for (var i = 0; i < items.length; i += 100) chunks.push(items.slice(i, i + 100));
  var saved = 0, failed = 0;
  chunks.reduce(function (prev, chunk) {
    return prev.then(function () {
      return fetch("/api/content-health/products", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: chunk.map(function (it) {
          return { asset_id: it.row.asset_id, products: it.products,
                   segment: it.row.segment ? null : it.segment };
        }) })
      }).then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
          var byId = {};
          d.results.forEach(function (x) { byId[x.asset_id] = x; });
          chunk.forEach(function (it) {
            var x = byId[it.row.asset_id] || { ok: false, error: "No answer for it." };
            it.saving = false;
            if (x.ok) { it.done = true; saved++; } else { it.error = x.error; failed++; }
          });
        });
      });
    });
  }, Promise.resolve()).catch(function (e) {
    items.forEach(function (it) {
      if (it.saving) { it.saving = false; it.error = "Not saved: " + e.message; failed++; }
    });
  }).then(function () {
    rows = rows.filter(function (it) { return !it.done; });
    note = saved + (saved === 1 ? " demo saved" : " demos saved")
      + (failed ? "; " + failed + " not saved, the reason is on each row." : ".");
    render();
  });
}

/* ------------------------------------------------------------ one row */

function editor(item) {
  var box = el("div", "pf-edit");
  var chips = el("div", "pf-chips");
  item.products.forEach(function (p) {
    var c = chip(p);
    c.appendChild(button("×", "pf-chip__x", function () {
      item.products = item.products.filter(function (q) { return q !== p; });
      render();
    }));
    chips.appendChild(c);
  });
  var add = el("select");
  add.setAttribute("aria-label", "Add a product");
  option(add, "", item.products.length ? "Add a product" : "Choose a product");
  choicesFor(item).forEach(function (p) {
    if (item.products.indexOf(p) < 0) option(add, p);
  });
  add.addEventListener("change", function () {
    if (add.value) { item.products.push(add.value); render(); }
  });
  chips.appendChild(add);
  box.appendChild(chips);
  if (!item.row.segment) {
    var seg = el("select");
    seg.setAttribute("aria-label", "Segment");
    option(seg, "", "No segment");
    state.segments.forEach(function (v) { option(seg, v); });
    seg.value = item.segment || "";
    seg.addEventListener("change", function () { item.segment = seg.value || null; });
    box.appendChild(seg);
  }
  return box;
}

function summary(item) {
  var box = el("div", "pf-chips");
  item.products.forEach(function (p) { box.appendChild(chip(p, "pf-chip--on")); });
  var seg = item.row.segment || item.segment;
  if (seg) box.appendChild(el("span", "faint", seg + (item.row.segment ? "" : " (suggested)")));
  return box;
}

function line(item, actions) {
  var r = el("div", "pf-row");
  var who = el("div", "pf-who");
  who.appendChild(demoLink(item.row.asset_id, item.row.title));
  who.appendChild(el("div", "faint pf-meta",
    [TYPE_WORD[item.row.type] || item.row.type, item.row.library].filter(Boolean).join(" · ")));
  r.appendChild(who);
  var what = el("div", "pf-what");
  what.appendChild(item.editing || !item.products.length && group(item) === "none"
    ? editor(item) : summary(item));
  if (item.error) what.appendChild(el("div", "pf-err", item.error));
  r.appendChild(what);
  var act = el("div", "pf-act");
  if (item.saving) act.appendChild(el("span", "faint", "Saving…"));
  else actions.forEach(function (a) { act.appendChild(a); });
  r.appendChild(act);
  return r;
}

/* ------------------------------------------------------------- groups */

function section(icon, titleText, count, help, headAction) {
  var box = el("div", "pf-group");
  var head = el("div", "pf-group__head");
  head.appendChild(el("span", "pf-group__icon " + icon));
  head.appendChild(el("span", "pf-group__title", titleText));
  head.appendChild(el("span", "faint", count + (count === 1 ? " demo" : " demos")));
  head.appendChild(el("span", "pf-grow"));
  if (headAction) head.appendChild(headAction);
  box.appendChild(head);
  box.appendChild(el("p", "muted pf-help", help));
  return box;
}

function titleGroup(items) {
  var ready = items.filter(function (it) { return it.products.length && !it.saving; });
  var all = ready.length
    ? button("Accept all " + ready.length, "btn-primary", function () { save(ready); })
    : null;
  var box = section("pf-ok", "1. The title names the product", items.length,
    "Check the list and change any that are wrong, then accept them together.", all);
  items.forEach(function (it) {
    box.appendChild(line(it, [
      it.editing ? button("Done", null, function () { it.editing = false; render(); })
                 : button("Change", null, function () { it.editing = true; render(); })
    ]));
  });
  return box;
}

function descriptionGroup(items) {
  var box = section("pf-maybe", "2. Only the description mentions products", items.length,
    "A weaker hint, so one at a time: accept it, or change it and save.");
  items.forEach(function (it) {
    var actions = it.editing
      ? [button("Save", "btn-primary btn-small", function () { save([it]); }),
         button("Cancel", null, function () {
           it.editing = false;
           it.products = it.row.suggested.products.slice();
           render();
         })]
      : [button("Accept", null, function () { save([it]); }),
         button("Change", null, function () { it.editing = true; render(); })];
    box.appendChild(line(it, actions));
  });
  return box;
}

function noneGroup(items) {
  var box = section("pf-none", "3. No suggestion", items.length,
    "Choose a product for each, or select several and set them together.");
  var picked = items.filter(function (it) { return it.picked; });
  if (picked.length) {
    var bar = el("div", "pf-selbar");
    bar.appendChild(el("span", null, picked.length + " selected"));
    var prod = el("select");
    prod.setAttribute("aria-label", "Product for the selected demos");
    option(prod, "", "Product");
    var common = null;
    picked.forEach(function (it) {
      var c = choicesFor(it);
      common = common === null ? c.slice() : common.filter(function (p) { return c.indexOf(p) >= 0; });
    });
    (common || []).forEach(function (p) { option(prod, p); });
    var seg = el("select");
    seg.setAttribute("aria-label", "Segment for the selected demos");
    option(seg, "", "Segment");
    state.segments.forEach(function (v) { option(seg, v); });
    var msg = el("span", "pf-err");
    bar.appendChild(prod);
    bar.appendChild(seg);
    bar.appendChild(button("Set for " + picked.length, "btn-primary btn-small", function () {
      if (!prod.value) { msg.textContent = "Choose a product first."; return; }
      picked.forEach(function (it) {
        it.products = [prod.value];
        if (seg.value && !it.row.segment) it.segment = seg.value;
      });
      save(picked);
    }));
    bar.appendChild(msg);
    bar.appendChild(el("span", "pf-grow"));
    bar.appendChild(button("Clear", "pf-link", function () {
      items.forEach(function (it) { it.picked = false; });
      render();
    }));
    box.appendChild(bar);
  }
  items.forEach(function (it) {
    var pick = el("input");
    pick.type = "checkbox";
    pick.checked = !!it.picked;
    pick.setAttribute("aria-label", "Select " + it.row.title);
    pick.addEventListener("change", function () { it.picked = pick.checked; render(); });
    var actions = it.products.length
      ? [button("Save", "btn-primary btn-small", function () { save([it]); })] : [];
    var r = line(it, actions);
    r.insertBefore(pick, r.firstChild);
    r.classList.add("pf-row--pick");
    box.appendChild(r);
  });
  return box;
}

/* ------------------------------------------------------------- render */

function render() {
  var host = $("hcFix");
  if (!host || !state) return;
  host.innerHTML = "";
  var card = el("details", "card hc-card" + (rows.length ? "" : " hc-card--ok"));
  card.open = rows.length > 0;
  var sum = el("summary", "card-head");
  sum.appendChild(el("h2", null, "Fix products"));
  sum.appendChild(el("span", "pill " + (rows.length ? "pill--warn" : "pill--on"),
    rows.length ? String(rows.length) : "None"));
  card.appendChild(sum);
  card.appendChild(el("p", "muted hc-why",
    "Demos with no product are under no product in the navigation and never related by "
    + "product. Saving writes a SharePoint demo's folder, or sets a Consensus demo on the Hub, "
    + "and is in the Admin log. GXC videos are not listed: IoT and AR videos keep Product "
    + "empty on purpose."));
  if ((state.fallback || []).length) {
    card.appendChild(el("p", "faint hc-why", "SharePoint's product list could not be read just "
      + "now; the products offered come from the catalogue, and saving still checks them."));
  }
  if (note) card.appendChild(el("p", "pf-note", note));
  var by = { title: [], description: [], none: [] };
  rows.forEach(function (it) { by[group(it)].push(it); });
  if (by.title.length) card.appendChild(titleGroup(by.title));
  if (by.description.length) card.appendChild(descriptionGroup(by.description));
  if (by.none.length) card.appendChild(noneGroup(by.none));
  host.appendChild(card);
}

function loadProducts() {
  if (!$("hcFix")) return Promise.resolve();
  return fetch("/api/content-health/products")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      state = d;
      note = "";
      rows = d.rows.map(function (r) {
        var s = r.suggested;
        return { row: r, products: s ? s.products.slice() : [],
                 segment: r.segment ? null : (r.suggested_segment || null),
                 editing: false, error: null, picked: false };
      });
      render();
    });
}

export {
  loadProducts
};
