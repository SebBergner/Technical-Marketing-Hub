/* Content to review (#/review; A6, Liwei 2026-10-23/28): every demo the Hub
 * lists, with its age, its last use and why it may need a look, for the
 * team to judge and to archive, or confirm Still current, several at a
 * time. Each step can be undone and is in the Admin log.
 *
 * Why (2026-10-28), worked out by the server: Admin -> Content review's own
 * rules (collecting dust, little used, Still current running out), and the
 * columns the Data Clean list counts as empty (Demo owner, Publish date...).
 * Every demo is listed; those with the most reasons come first.
 *
 * Only for Review content or Archive content (the sidebar item, and the
 * server: /api/reports/content-to-review). Each button needs its own: Archive
 * needs Archive content, Still current needs Review content. No figures about
 * who used a demo, only when it was last used.
 *
 * Part of the Hub page's script; static/js/hub/main.js loads it through
 * nav.js and detail.js. */

import { dateLabel, escapeHtml, fullDate, report } from "./util.js";
import { hubPermissions } from "./permissions.js";
import { TYPE_CHIP } from "./cards.js";
import { closeAdvancedSearch } from "./search.js";

var state = {
  items: null, usageSince: null, months: 12,
  scope: null,            // "mine" | "all"; Mine first when there are any
  type: "", age: "", why: "", q: "",
  sort: ["why", "desc"],
  missingLabels: {},
  picked: {}, granted: [], busy: false, last: null
};

var AGE_LABEL = { "new": "Under 1 year", recent: "1–2 years", aging: "2–4 years",
                  older: "4 years or more" };

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function may(p) { return state.granted.indexOf(p) >= 0; }

/* "3 yr", "8 mo": how long since a date. */
function since(iso) {
  if (!iso) return "";
  var days = (Date.now() - new Date(iso + "T00:00:00").getTime()) / 86400000;
  if (days < 0) return "";
  if (days < 60) return Math.max(1, Math.round(days)) + " d";
  if (days < 730) return Math.round(days / 30.4) + " mo";
  return (days / 365).toFixed(days < 3650 ? 1 : 0).replace(/\.0$/, "") + " yr";
}

/* ── the page ─────────────────────────────────────────────────────────── */
function buildPage() {
  var page = document.getElementById("hubReviewPage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubReviewPage";
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to Technical Marketing Hub</button>'
    + '<div class="vp-head"><div>'
    +   '<div class="vp-title">Content to review</div>'
    +   '<div class="orion-subtle">Every demo in the Hub, with why it may need a look: old, '
    +   'little used, Still current running out, or details missing in SharePoint. Archive what '
    +   'is out of date, or confirm it is still current. Both can be undone.</div>'
    + '</div></div>'
    + '<div class="hub-rvw" id="hubRvw"></div>';
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeReview();
  });
  return page;
}

function openReview() {
  var page = buildPage();
  closeAdvancedSearch();
  var request = document.getElementById("requestViewPage");
  if (request) request.classList.remove("active");
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  page.classList.add("active");
  markNav(true);
  load();
}

function closeReview() {
  var page = document.getElementById("hubReviewPage");
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

/* Fetched on every visit (a demo archived from its own page leaves the
 * list); the filters and the selection's absence are kept. */
function load() {
  var host = document.getElementById("hubRvw");
  if (!state.items) host.textContent = "Loading…";
  Promise.all([hubPermissions, fetch("/api/reports/content-to-review").then(function (r) {
    if (r.status === 401 || r.status === 403) return { forbidden: true };
    return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status));
  })]).then(function (both) {
    state.granted = both[0] || [];
    var d = both[1];
    if (d.forbidden) {
      host.textContent = "Content to review needs Review content or Archive content.";
      return;
    }
    state.items = d.items || [];
    state.usageSince = d.usage_since;
    state.months = d.still_current_months || 12;
    state.missingLabels = d.missing_labels || {};
    if (!state.scope) {
      state.scope = state.items.some(function (r) { return r.mine; }) ? "mine" : "all";
    }
    state.picked = {};
    render();
  }).catch(function (err) {
    host.textContent = "";
    report("Could not load Content to review: " + err.message, true);
  });
}

function shown() {
  var q = state.q.trim().toLowerCase();
  var rows = state.items.filter(function (r) {
    if (state.scope === "mine" && !r.mine) return false;
    if (state.type && r.type !== state.type) return false;
    if (state.age && (r.age_band || "none") !== state.age) return false;
    if (state.why && !hasWhy(r, state.why)) return false;
    if (q && ((r.title || "") + " " + (r.products || []).join(" ") + " " + (r.owner || ""))
        .toLowerCase().indexOf(q) < 0) return false;
    return true;
  });
  var key = state.sort[0], dir = state.sort[1] === "asc" ? 1 : -1;
  if (key === "why") {
    // The most reasons first (a review reason outweighs any number of
    // missing columns); then the least recently used, the oldest.
    var weight = function (r) { return r.reasons.length * 100 + r.missing.length; };
    rows.sort(function (a, b) {
      var w = (weight(a) - weight(b)) * dir;
      if (w) return w;
      if ((a.last_used || "") !== (b.last_used || "")) return (a.last_used || "") < (b.last_used || "") ? -1 : 1;
      return (a.uploaded_at || "") < (b.uploaded_at || "") ? -1 : 1;
    });
    return rows;
  }
  rows.sort(function (a, b) {
    // Never used reads as the oldest use; no date as the oldest demo.
    var x = key === "used" ? (a.last_used || "") : (a.uploaded_at || "");
    var y = key === "used" ? (b.last_used || "") : (b.uploaded_at || "");
    if (x !== y) return x < y ? -dir : dir;
    return (a.uploaded_at || "") < (b.uploaded_at || "") ? -1 : 1;
  });
  return rows;
}

function render() {
  var host = document.getElementById("hubRvw");
  host.innerHTML = "";
  host.appendChild(toolbar());
  var rows = shown();
  host.appendChild(bulkBar(rows));
  if (state.last) host.appendChild(lastResult());
  if (!rows.length) {
    host.appendChild(el("div", "hub-rvw__empty", state.scope === "mine"
      ? "None of the demos credited to you match. Try All demos."
      : "No demo matches these filters."));
    return;
  }
  var wrap = el("div", "hub-table-wrap");
  var table = el("table", "hub-table hub-rvw__table");
  table.appendChild(head(rows));
  var body = el("tbody");
  rows.forEach(function (r) { body.appendChild(row(r)); });
  table.appendChild(body);
  wrap.appendChild(table);
  host.appendChild(wrap);
  if (state.usageSince) {
    host.appendChild(el("div", "hub-rvw__note",
      "Last used counts opening, previewing or downloading a demo in the Hub, since the Hub "
      + "began recording it on " + fullDate(state.usageSince) + "."));
  }
}

function toolbar() {
  var bar = el("div", "hub-rvw__bar");
  var seg = el("div", "hub-rvw__scope");
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", "Whose demos");
  var mine = state.items.filter(function (r) { return r.mine; }).length;
  [["mine", "Mine (" + mine + ")"], ["all", "All demos (" + state.items.length + ")"]]
    .forEach(function (s) {
      var b = el("button", null, s[1]);
      b.type = "button";
      b.setAttribute("aria-pressed", String(state.scope === s[0]));
      b.addEventListener("click", function () { state.scope = s[0]; state.picked = {}; render(); });
      seg.appendChild(b);
    });
  bar.appendChild(seg);

  var types = {};
  state.items.forEach(function (r) { types[r.type] = 1; });
  bar.appendChild(select("Type", "type", [["", "All types"]].concat(Object.keys(types).sort()
    .map(function (t) { return [t, (TYPE_CHIP[t] || [])[1] || t]; }))));
  bar.appendChild(select("Age", "age", [["", "Any age"]].concat(Object.keys(AGE_LABEL)
    .map(function (k) { return [k, AGE_LABEL[k]]; })).concat([["none", "No date"]])));
  bar.appendChild(select("Why", "why", [["", "With or without a reason"], ["review", "Old, little used or Still current"],
    ["dust", "Collecting dust"], ["idle", "Little used"], ["still_current", "Still current running out"],
    ["missing", "Any detail missing"]].concat(Object.keys(state.missingLabels).map(function (k) {
      return ["m:" + k, "Missing " + state.missingLabels[k]];
    })).concat([["none", "Nothing to review"]])));

  var search = el("input", "hub-rvw__search");
  search.type = "search";
  search.placeholder = "Filter by title, product or owner";
  search.value = state.q;
  search.addEventListener("input", function () {
    state.q = search.value;
    var at = search.selectionStart;
    render();
    var again = document.querySelector("#hubRvw .hub-rvw__search");
    again.focus();
    try { again.setSelectionRange(at, at); } catch (e) { /* type=search */ }
  });
  bar.appendChild(search);
  return bar;
}

function select(label, key, options) {
  var s = el("select", "hub-rvw__select");
  s.setAttribute("aria-label", label);
  options.forEach(function (o) {
    var opt = el("option", null, o[1]);
    opt.value = o[0];
    s.appendChild(opt);
  });
  s.value = state[key];
  s.addEventListener("change", function () { state[key] = s.value; state.picked = {}; render(); });
  return s;
}

function head(rows) {
  var thead = el("thead");
  var tr = thead.insertRow();
  var th0 = el("th", "hub-rvw__pick");
  var all = el("input");
  all.type = "checkbox";
  all.setAttribute("aria-label", "Select every demo shown");
  var picked = rows.filter(function (r) { return state.picked[r.asset_id]; }).length;
  all.checked = picked > 0 && picked === rows.length;
  all.indeterminate = picked > 0 && picked < rows.length;
  all.disabled = !canAct();
  all.addEventListener("change", function () {
    state.picked = {};
    if (all.checked) rows.forEach(function (r) { state.picked[r.asset_id] = r; });
    document.querySelectorAll("#hubRvw tbody input[type=checkbox]").forEach(function (b) {
      b.checked = all.checked;
    });
    picked();
  });
  th0.appendChild(all);
  tr.appendChild(th0);
  [["title", "Title"], ["why", "Why review", true], ["type", "Type"], ["owner", "Owner"],
   ["age", "Age", true],
   ["used", "Last used", true], ["current", "Still current"]].forEach(function (c) {
    var th = el("th", "hub-table__th--" + c[0]);
    if (!c[2]) { th.appendChild(el("span", "hub-rvw__th", c[1])); tr.appendChild(th); return; }
    var b = el("button", null, c[1]);
    b.type = "button";
    var on = state.sort[0] === c[0];
    if (on) b.className = "is-sorted is-" + state.sort[1];
    th.setAttribute("aria-sort", on ? (state.sort[1] === "asc" ? "ascending" : "descending") : "none");
    b.addEventListener("click", function () {
      // Most reasons, oldest and least recently used first are where each starts.
      var first = c[0] === "why" ? "desc" : "asc";
      state.sort = [c[0], on && state.sort[1] === first ? (first === "asc" ? "desc" : "asc") : first];
      render();
    });
    th.appendChild(b);
    tr.appendChild(th);
  });
  return thead;
}

function row(r) {
  var tr = el("tr");
  var td0 = el("td", "hub-rvw__pick");
  var box = el("input");
  box.type = "checkbox";
  box.checked = !!state.picked[r.asset_id];
  box.disabled = !canAct();
  box.setAttribute("aria-label", "Select " + (r.title || r.asset_id));
  box.addEventListener("change", function () {
    if (box.checked) state.picked[r.asset_id] = r; else delete state.picked[r.asset_id];
    picked();
  });
  td0.appendChild(box);
  tr.appendChild(td0);

  var title = el("td", "hub-table__td--title");
  var a = el("a", null, r.title || r.asset_id);
  a.href = "#/asset/" + encodeURIComponent(r.asset_id);
  a.addEventListener("click", function () { window.hubDetailReturn = "#/review"; });
  title.appendChild(a);
  if ((r.products || []).length) title.appendChild(el("div", "hub-rvw__sub", r.products.join(", ")));
  tr.appendChild(title);
  tr.appendChild(whyCell(r));
  tr.appendChild(el("td", "hub-table__td--type", (TYPE_CHIP[r.type] || [])[1] || r.type || ""));
  tr.appendChild(el("td", "hub-rvw__owner", r.owner || ""));

  var age = el("td", "hub-rvw__age");
  if (r.uploaded_at) {
    age.appendChild(el("b", null, since(r.uploaded_at)));
    age.appendChild(el("div", "hub-rvw__sub", dateLabel(r)));
  } else {
    age.appendChild(el("span", "hub-rvw__sub", "No date"));
  }
  tr.appendChild(age);

  var used = el("td", "hub-rvw__used");
  if (r.last_used) {
    used.appendChild(el("b", null, since(r.last_used) + " ago"));
    used.appendChild(el("div", "hub-rvw__sub", fullDate(r.last_used)));
  } else {
    used.appendChild(el("span", "hub-rvw__never", "Never"));
  }
  tr.appendChild(used);
  tr.appendChild(el("td", "hub-rvw__current",
    r.still_current_until ? "Until " + fullDate(r.still_current_until) : ""));
  return tr;
}

function hasWhy(r, want) {
  if (want === "none") return !r.reasons.length && !r.missing.length;
  if (want === "review") return r.reasons.length > 0;
  if (want === "missing") return r.missing.length > 0;
  if (want.indexOf("m:") === 0) return r.missing.indexOf(want.slice(2)) >= 0;
  return r.reasons.some(function (x) { return x.key === want; });
}

/* Review reasons as tags; the empty columns as one line under them. */
function whyCell(r) {
  var td = el("td", "hub-rvw__why");
  r.reasons.forEach(function (x) {
    var tag = el("span", "hub-rvw__tag hub-rvw__tag--" + x.key, x.label);
    tag.title = x.until ? "Confirmed Still current until " + fullDate(x.until) : (x.why || "");
    td.appendChild(tag);
  });
  if (r.missing.length) {
    var line = el("div", "hub-rvw__missing", "Missing: " + r.missing.map(function (k) {
      return state.missingLabels[k] || k;
    }).join(", "));
    line.title = "Empty in SharePoint. Fill in with Edit on the demo's Details card.";
    td.appendChild(line);
  }
  return td;
}

/* A tick changes the bar and the header's box, not 1,300 rows (a full
 * render took ~150 ms and lost the scroll position). */
function picked() {
  var rows = shown();
  var bar = document.querySelector("#hubRvw .hub-rvw__bulk");
  if (bar) bar.replaceWith(bulkBar(rows));
  var all = document.querySelector("#hubRvw thead input[type=checkbox]");
  var n = rows.filter(function (r) { return state.picked[r.asset_id]; }).length;
  if (all) {
    all.checked = n > 0 && n === rows.length;
    all.indeterminate = n > 0 && n < rows.length;
  }
}

function canAct() {
  return may("archive_content") || may("review_content");
}

/* ── several at a time ────────────────────────────────────────────────── */
function bulkBar(rows) {
  var bar = el("div", "hub-rvw__bulk");
  var ids = Object.keys(state.picked);
  if (!canAct()) {
    bar.appendChild(el("span", null, rows.length + " shown"));
    return bar;
  }
  bar.appendChild(el("span", "hub-rvw__count", ids.length
    ? ids.length + " selected" : rows.length + " shown · select demos to act on them"));
  if (!ids.length || state.busy) return bar;
  if (may("archive_content")) {
    var arch = el("button", "btn-primary-sm", "Archive…");
    arch.type = "button";
    arch.addEventListener("click", function () { askArchive(bar, ids); });
    bar.appendChild(arch);
  }
  if (may("review_content")) {
    var cur = el("button", "btn-ghost", "Still current");
    cur.type = "button";
    cur.title = "The interface these show still matches today's release, for "
      + state.months + " months";
    cur.addEventListener("click", function () { run("current", ids, true); });
    bar.appendChild(cur);
  }
  var clear = el("button", "btn-ghost", "Clear");
  clear.type = "button";
  clear.addEventListener("click", function () {
    state.picked = {};
    document.querySelectorAll("#hubRvw input[type=checkbox]").forEach(function (b) {
      b.checked = false;
      b.indeterminate = false;
    });
    picked();
  });
  bar.appendChild(clear);
  return bar;
}

/* Asked once for the batch: what it does, and a reason for the log. */
function askArchive(bar, ids) {
  bar.innerHTML = "";
  var moving = ids.filter(function (id) { return state.picked[id].in_sharepoint; }).length;
  bar.appendChild(el("span", "hub-rvw__count", "Archive " + ids.length + " demo"
    + (ids.length === 1 ? "" : "s") + "?"));
  bar.appendChild(el("span", "hub-rvw__lead", (moving
    ? moving + " move into SharePoint's _Archive, which only the team can open. " : "")
    + "They leave the Hub's lists and search; Undo or Restore brings them back."));
  var reason = el("input", "hub-rvw__reason");
  reason.placeholder = "Reason (kept in the log)";
  bar.appendChild(reason);
  var go = el("button", "btn-primary-sm", "Archive " + ids.length);
  go.type = "button";
  go.addEventListener("click", function () { run("archive", ids, true, reason.value.trim()); });
  bar.appendChild(go);
  var cancel = el("button", "btn-ghost", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", picked);
  bar.appendChild(cancel);
  reason.focus();
}

function call(kind, id, on, reason) {
  var url = "/api/assets/" + encodeURIComponent(id) + (kind === "archive" ? "/archive" : "/still-current");
  var body = kind === "archive" ? { archived: on, reason: reason || null } : { still_current: on };
  return fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(body) })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
        return d;
      });
    });
}

/* One at a time: an archive checks a folder's permissions and moves it, and
 * a refusal says why for that demo alone. */
function run(kind, ids, on, reason) {
  var titles = {};
  ids.forEach(function (id) {
    var r = state.picked[id] || find(id);
    titles[id] = r ? r.title : id;
  });
  state.busy = true;
  var done = [], failed = [];
  var bar = document.querySelector("#hubRvw .hub-rvw__bulk");
  var i = 0;
  function next() {
    if (i >= ids.length) return finish();
    var id = ids[i++];
    if (bar) bar.innerHTML = "<span class='hub-rvw__count'>" + escapeHtml(verb(kind, on, true))
      + " " + i + " of " + ids.length + "…</span>";
    return call(kind, id, on, reason).then(function () { done.push(id); },
      function (e) { failed.push({ id: id, title: titles[id], why: e.message }); }).then(next);
  }
  function finish() {
    state.busy = false;
    state.last = { kind: kind, on: on, done: done, failed: failed, titles: titles };
    // An undo puts back what this page knows; a fresh list says the rest.
    load();
  }
  next();
}

function find(id) {
  return (state.items || []).filter(function (r) { return r.asset_id === id; })[0];
}

function verb(kind, on, ing) {
  if (kind === "archive") return on ? (ing ? "Archiving" : "Archived") : (ing ? "Restoring" : "Restored");
  return on ? (ing ? "Confirming" : "Confirmed Still current:") : (ing ? "Undoing" : "Withdrew Still current:");
}

function lastResult() {
  var l = state.last;
  var box = el("div", "hub-rvw__result" + (l.failed.length ? " hub-rvw__result--warn" : ""));
  var line = el("div");
  line.appendChild(document.createTextNode(verb(l.kind, l.on) + " " + l.done.length
    + " demo" + (l.done.length === 1 ? "" : "s") + "."));
  if (l.done.length && !state.busy) {
    var undo = el("button", "btn-ghost", "Undo");
    undo.type = "button";
    undo.addEventListener("click", function () { run(l.kind, l.done.slice(), !l.on); });
    line.appendChild(undo);
  }
  var x = el("button", "hub-rvw__dismiss", "×");
  x.type = "button";
  x.setAttribute("aria-label", "Dismiss");
  x.addEventListener("click", function () { state.last = null; render(); });
  line.appendChild(x);
  box.appendChild(line);
  if (l.failed.length) {
    box.appendChild(el("div", null, l.failed.length + " could not be "
      + (l.kind === "archive" ? (l.on ? "archived" : "restored") : "changed") + ":"));
    var list = el("ul");
    l.failed.forEach(function (f) {
      var li = el("li");
      li.appendChild(el("b", null, f.title));
      li.appendChild(document.createTextNode(" — " + f.why));
      list.appendChild(li);
    });
    box.appendChild(list);
  }
  return box;
}

/* ── the sidebar item, under Dashboard ────────────────────────────────── */
function addReviewNav() {
  hubPermissions.then(function (granted) {
    if ((granted.indexOf("review_content") < 0 && granted.indexOf("archive_content") < 0)
        || document.getElementById("navReview")) return;
    var after = document.getElementById("navActivity") || document.getElementById("navHome");
    if (!after) return;
    var item = el("div", "orion-navitem");
    item.id = "navReview";
    item.innerHTML = '<span class="label"><svg class="orion-ico orion-ico--sm">'
      + '<use href="#i-flag"/></svg> Content to review</span>';
    item.addEventListener("click", function () { location.hash = "#/review"; });
    after.insertAdjacentElement("afterend", item);
    if (location.hash === "#/review") markNav(true);
  });
}

function markNav(on) {
  var item = document.getElementById("navReview");
  if (!item) return;
  item.classList.toggle("orion-navitem--active", on);
  if (on) document.querySelectorAll(".orion-navitem--active, .orion-navitem.is-active")
    .forEach(function (n) {
      if (n !== item) n.classList.remove("orion-navitem--active", "is-active");
    });
}

export { addReviewNav, closeReview, openReview };
