/* The Home page tab: Featured demos and the display switches.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, el, row, TYPE_WORD } from "./util.js";
import { act } from "./signins.js";

/* ── Promoted on Home ───────────────────────────────────────────────
 *
 * Seb's ask, built 2026-10-01: the team chooses which demos the Home page
 * features, and in which order. One ordered list, saved as a whole on
 * every change (PUT /api/admin/promoted); it lives in the Hub's own data,
 * never in SharePoint. */

function promoMeta(a) {
  return [TYPE_WORD[a.type] || a.type, (a.product_families || []).join(", ")]
    .filter(Boolean).join(" · ");
}

function loadPromoted() {
  return fetch("/api/admin/promoted")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (state) { if (state) renderPromoted(state); });
}

function renderPromoted(state) {
  var host = $("promoted");
  if (!host) return;
  host.innerHTML = "";
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "Promoted on Home"));
  head.appendChild(el("span", "faint num", state.assets.length + " of " + state.max));
  host.appendChild(head);
  host.appendChild(el("p", "muted",
    "Shown in this order in the Featured section at the top of the Hub's Home page. "
    + "Nothing promoted means no Featured section."));

  var ids = state.assets.map(function (a) { return a.id; });
  var status = el("div", "promo-status faint");
  var save = function (next) {
    status.textContent = "Saving…";
    fetch("/api/admin/promoted", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_ids: next }),
    }).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
        throw new Error(b.detail || ("HTTP " + r.status));
      });
      return r.json();
    }).then(renderPromoted).catch(function (err) {
      status.textContent = "Not saved: " + err.message;
      status.className = "promo-status err";
    });
  };
  var move = function (i, by) {
    var next = ids.slice();
    var j = i + by;
    if (j < 0 || j >= next.length) return;
    next.splice(j, 0, next.splice(i, 1)[0]);
    save(next);
  };

  var list = el("div");
  if (!state.assets.length) list.appendChild(el("div", "faint", "Nothing promoted yet."));
  state.assets.forEach(function (a, i) {
    var r = el("div", "promo-row");
    r.appendChild(el("span", "promo-row__n", i + 1));
    var info = el("div");
    var title = el("a", "promo-row__title", a.title);
    title.href = "/#/asset/" + encodeURIComponent(a.id);
    title.target = "_blank";
    title.rel = "noopener";
    info.appendChild(title);
    info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
    r.appendChild(info);
    var actions = el("div", "promo-row__actions");
    var up = el("button", null, "↑");
    up.title = "Move up";
    up.disabled = i === 0;
    up.addEventListener("click", function () { move(i, -1); });
    var down = el("button", null, "↓");
    down.title = "Move down";
    down.disabled = i === state.assets.length - 1;
    down.addEventListener("click", function () { move(i, 1); });
    var remove = el("button", null, "Remove");
    remove.addEventListener("click", function () {
      save(ids.filter(function (x) { return x !== a.id; }));
    });
    actions.appendChild(up);
    actions.appendChild(down);
    actions.appendChild(remove);
    r.appendChild(actions);
    list.appendChild(r);
  });
  host.appendChild(list);

  // Add: search the catalogue by title, promote from the results.
  var add = el("div", "promo-add");
  var label = el("label", null, "Add a demo");
  var input = el("input");
  input.type = "search";
  input.placeholder = ids.length >= state.max
    ? "The list is full — remove one first" : "Search by title…";
  input.disabled = ids.length >= state.max;
  input.autocomplete = "off";
  label.appendChild(input);
  add.appendChild(label);
  var results = el("div", "promo-results");
  add.appendChild(results);
  host.appendChild(add);
  host.appendChild(status);
  if (state.changed_at) {
    status.textContent = "Last changed " + new Date(state.changed_at).toLocaleString()
      + (state.changed_by ? " by " + state.changed_by : "");
  }

  var timer = null;
  input.addEventListener("input", function () {
    clearTimeout(timer);
    var q = input.value.trim();
    timer = setTimeout(function () {
      results.innerHTML = "";
      if (q.length < 2) return;
      fetch("/api/assets?limit=8&q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (page) {
          results.innerHTML = "";
          if (!page.items.length) { results.appendChild(el("div", "faint", "No demo matches.")); return; }
          page.items.forEach(function (a) {
            var r = el("div", "promo-row");
            r.appendChild(el("span", "promo-row__n", ""));
            var info = el("div");
            info.appendChild(el("div", "promo-row__title", a.title));
            info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
            r.appendChild(info);
            var pick = el("button", "btn-primary", ids.indexOf(a.id) === -1 ? "Promote" : "Promoted");
            pick.disabled = ids.indexOf(a.id) !== -1;
            pick.addEventListener("click", function () { save(ids.concat([a.id])); });
            var act = el("div", "promo-row__actions");
            act.appendChild(pick);
            r.appendChild(act);
            results.appendChild(r);
          });
        });
    }, 250);
  });
}

/* ── Hub display switches ─────────────────────────────────────────────
 * One for now: links from the Hub to a demo's SharePoint page. Off by
 * default while management decides whether to expose SharePoint (Liwei,
 * 2026-10-05); when off the server sends no page address at all. */
function loadHubSettings() {
  return fetch("/api/admin/hub-settings")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (s) { if (s) renderHubSettings(s); });
}

var HUB_SWITCHES = [
  { key: "show_page_only_demos", title: "Demos with only a SharePoint page",
    note: "Demos that have a page under SitePages/Demo Catalog but no project folder "
        + "(Lamborghini IPL, for example). Hidden, they are not listed in the Hub at all; "
        + "demos with a folder keep their page thumbnail either way. Shown by default." },
  { key: "show_demo_page_links", title: "Links to SharePoint demo pages",
    note: "The “Demo page” link on a demo that has a SharePoint page, and the "
        + "“Open demo page” button on a demo known only from its page. Hidden, no "
        + "page address is sent to the browser. Download Kit and Open Video are not "
        + "affected. Hidden by default." }
];

function renderHubSettings(s) {
  var host = $("hubDisplay");
  if (!host) return;
  host.innerHTML = "";
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "SharePoint demo pages"));
  host.appendChild(head);
  var status = el("div", "promo-status faint",
    s.changed_at ? "Last changed " + new Date(s.changed_at).toLocaleString()
                   + (s.changed_by ? " by " + s.changed_by : "") : "Never changed: the defaults apply.");
  HUB_SWITCHES.forEach(function (sw) {
    var row = el("div", "promo-row");
    row.style.gridTemplateColumns = "1fr auto";
    var text = el("div");
    text.appendChild(el("div", "promo-row__title", sw.title));
    text.appendChild(el("div", "promo-row__meta", sw.note));
    row.appendChild(text);
    var toggle = el("label", "switch");
    var box = el("input");
    box.type = "checkbox";
    box.checked = !!s[sw.key];
    box.setAttribute("aria-label", sw.title);
    toggle.appendChild(box);
    toggle.appendChild(el("span", "switch__track"));
    toggle.appendChild(el("span", "switch__label", s[sw.key] ? "Shown" : "Hidden"));
    row.appendChild(toggle);
    host.appendChild(row);
    box.addEventListener("change", function () {
      box.disabled = true;
      status.textContent = "Saving…";
      var body = {};
      body[sw.key] = box.checked;
      fetch("/api/admin/hub-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(renderHubSettings).catch(function (err) {
        box.checked = !box.checked;
        box.disabled = false;
        status.textContent = "Not saved: " + err.message;
        status.className = "promo-status err";
      });
    });
  });
  host.appendChild(status);
}

export {
  loadHubSettings, loadPromoted, promoMeta
};
