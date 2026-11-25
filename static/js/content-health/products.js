/* Content health -> Health check -> Fix products (Liwei, 2026-11-25): every
 * demo with no product that the Hub can fill in, many at once, each with a
 * suggestion from its own title (ticked) or description (shown, not ticked).
 * GET / POST /api/content-health/products; nothing is written until Save,
 * and each save is in the Admin log.
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, demoLink, el, TYPE_WORD } from "../admin/util.js";

var state = null;           // {rows, choices, segments, libraries, fallback}
var picks = {};             // asset id -> {on, products: [], segment}

function choicesFor(row) {
  return (state.choices[row.fix] || []).slice();
}

function allChoices() {
  var seen = {};
  Object.keys(state.choices).forEach(function (k) {
    state.choices[k].forEach(function (p) { seen[p] = true; });
  });
  return Object.keys(seen).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
}

function option(select, value, text) {
  var o = el("option", null, text == null ? value : text);
  o.value = value;
  select.appendChild(o);
  return o;
}

function ticked() {
  return state.rows.filter(function (r) { return picks[r.asset_id].on; });
}

function countLine() {
  var n = ticked().length;
  $("pfSave").textContent = n ? "Save " + n + (n === 1 ? " demo" : " demos") : "Save";
  $("pfSave").disabled = !ticked().some(function (r) { return picks[r.asset_id].products.length; });
}

function productCell(row, cell) {
  cell.innerHTML = "";
  var pick = picks[row.asset_id];
  pick.products.forEach(function (p) {
    var chip = el("span", "pf-chip", p);
    var x = el("button", "pf-chip__x", "×");
    x.type = "button";
    x.title = "Remove " + p;
    x.addEventListener("click", function () {
      pick.products = pick.products.filter(function (q) { return q !== p; });
      productCell(row, cell);
      countLine();
    });
    chip.appendChild(x);
    cell.appendChild(chip);
  });
  var add = el("select", "pf-add");
  option(add, "", pick.products.length ? "+ add" : "Choose…");
  choicesFor(row).forEach(function (p) {
    if (pick.products.indexOf(p) < 0) option(add, p);
  });
  add.addEventListener("change", function () {
    if (!add.value) return;
    pick.products.push(add.value);
    pick.on = true;
    var box = $("pf-on-" + row.asset_id);
    if (box) box.checked = true;
    productCell(row, cell);
    countLine();
  });
  cell.appendChild(add);
  if (row.suggested) {
    cell.appendChild(el("div", "faint pf-from", "Suggested from its " + row.suggested.from
      + ": " + row.suggested.products.join(", ")));
  }
}

function segmentCell(row, cell) {
  if (row.segment) {
    cell.textContent = row.segment;
    cell.className = "faint";
    return;
  }
  var s = el("select");
  option(s, "", "—");
  state.segments.forEach(function (v) { option(s, v); });
  s.value = picks[row.asset_id].segment || "";
  s.addEventListener("change", function () { picks[row.asset_id].segment = s.value || null; });
  cell.appendChild(s);
}

function render() {
  var host = $("hcFix");
  host.innerHTML = "";
  var rows = state.rows;
  var card = el("details", "card hc-card" + (rows.length ? "" : " hc-card--ok"));
  card.open = rows.length > 0;
  var sum = el("summary", "card-head");
  sum.appendChild(el("h2", null, "Fix products"));
  sum.appendChild(el("span", "pill " + (rows.length ? "pill--warn" : "pill--on"),
    rows.length ? String(rows.length) : "None"));
  card.appendChild(sum);
  var fromTitle = rows.filter(function (r) { return r.suggested && r.suggested.from === "title"; }).length;
  var fromText = rows.filter(function (r) { return r.suggested && r.suggested.from === "description"; }).length;
  card.appendChild(el("p", "muted hc-why",
    "Demos with no product are under no product in the navigation and never related by product. "
    + "Suggestions come from each demo's own words: " + fromTitle + " from the title (ticked), "
    + fromText + " from the description (not ticked), " + (rows.length - fromTitle - fromText)
    + " with none. Check them, then Save: SharePoint demos are written to their folder, "
    + "Consensus demos are set on the Hub. Every save is in the Admin log. GXC videos are not "
    + "listed: IoT and AR videos keep Product empty on purpose."));
  if ((state.fallback || []).length) {
    card.appendChild(el("p", "faint hc-why", "SharePoint's product list could not be read just now; "
      + "the products shown come from the catalogue, and Save still checks them against SharePoint."));
  }
  if (!rows.length) { host.appendChild(card); return; }

  var bar = el("div", "pf-bar");
  var all = el("button", "btn-small", "Tick title suggestions");
  all.type = "button";
  all.addEventListener("click", function () {
    rows.forEach(function (r) {
      picks[r.asset_id].on = !!(r.suggested && r.suggested.from === "title");
    });
    render();
  });
  var none = el("button", "btn-small", "Untick all");
  none.type = "button";
  none.addEventListener("click", function () {
    rows.forEach(function (r) { picks[r.asset_id].on = false; });
    render();
  });
  var setProduct = el("select");
  option(setProduct, "", "Product…");
  allChoices().forEach(function (p) { option(setProduct, p); });
  var setSegment = el("select");
  option(setSegment, "", "Segment…");
  state.segments.forEach(function (v) { option(setSegment, v); });
  var apply = el("button", "btn-small", "Use for ticked");
  apply.type = "button";
  apply.addEventListener("click", function () {
    ticked().forEach(function (r) {
      if (setProduct.value && choicesFor(r).indexOf(setProduct.value) >= 0) {
        picks[r.asset_id].products = [setProduct.value];
      }
      if (setSegment.value && !r.segment) picks[r.asset_id].segment = setSegment.value;
    });
    render();
  });
  var save = el("button", "btn-primary", "Save");
  save.id = "pfSave";
  save.type = "button";
  save.addEventListener("click", saveTicked);
  var msg = el("span", "faint");
  msg.id = "pfMsg";
  [all, none, el("span", "faint", "Set for ticked:"), setProduct, setSegment, apply, save, msg]
    .forEach(function (n) { bar.appendChild(n); });
  card.appendChild(bar);

  var t = el("table", "pf-table");
  var hr = t.createTHead().insertRow();
  ["", "Demo", "Library", "Products", "Segment", ""].forEach(function (h) {
    hr.appendChild(el("th", null, h));
  });
  var tb = t.createTBody();
  rows.forEach(function (r) {
    var tr = tb.insertRow();
    var pick = picks[r.asset_id];
    var box = el("input");
    box.type = "checkbox";
    box.id = "pf-on-" + r.asset_id;
    box.checked = pick.on;
    box.setAttribute("aria-label", "Save " + r.title);
    box.addEventListener("change", function () { pick.on = box.checked; countLine(); });
    tr.insertCell().appendChild(box);
    var demo = tr.insertCell();
    demo.appendChild(demoLink(r.asset_id, r.title));
    demo.appendChild(el("div", "faint pf-from", TYPE_WORD[r.type] || r.type || ""));
    tr.insertCell().textContent = r.library;
    productCell(r, tr.insertCell());
    segmentCell(r, tr.insertCell());
    var result = tr.insertCell();
    result.id = "pf-res-" + r.asset_id;
    result.className = "pf-res";
  });
  var wrap = el("div", "tablewrap");
  wrap.appendChild(t);
  card.appendChild(wrap);
  host.appendChild(card);
  countLine();
}

function saveTicked() {
  var items = ticked().filter(function (r) { return picks[r.asset_id].products.length; })
    .map(function (r) {
      var p = picks[r.asset_id];
      return { asset_id: r.asset_id, products: p.products, segment: r.segment ? null : p.segment };
    });
  if (!items.length) return;
  var chunks = [];
  for (var i = 0; i < items.length; i += 100) chunks.push(items.slice(i, i + 100));
  $("pfSave").disabled = true;
  $("pfMsg").textContent = "Saving…";
  var saved = 0, failed = 0;
  chunks.reduce(function (prev, chunk) {
    return prev.then(function () {
      return fetch("/api/content-health/products", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: chunk })
      }).then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
          d.results.forEach(function (x) {
            var cell = $("pf-res-" + x.asset_id);
            if (x.ok) {
              saved++;
              picks[x.asset_id].on = false;
              if (cell) { cell.textContent = "Saved"; cell.className = "pf-res pf-res--ok"; }
            } else {
              failed++;
              if (cell) { cell.textContent = x.error; cell.className = "pf-res pf-res--bad"; }
            }
          });
        });
      });
    });
  }, Promise.resolve()).then(function () {
    $("pfMsg").textContent = saved + " saved" + (failed ? ", " + failed + " not saved (see each row)" : "")
      + ". The list refreshes when you open Health check again.";
  }).catch(function (e) {
    $("pfMsg").textContent = "Not saved: " + e.message;
  }).then(countLine);
}

function loadProducts() {
  var host = $("hcFix");
  if (!host) return Promise.resolve();
  return fetch("/api/content-health/products")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      state = d;
      picks = {};
      d.rows.forEach(function (r) {
        var s = r.suggested;
        picks[r.asset_id] = {
          on: !!(s && s.from === "title"),
          products: s ? s.products.slice() : [],
          segment: r.segment ? null : (r.suggested_segment || null)
        };
      });
      render();
    });
}

export {
  loadProducts
};
