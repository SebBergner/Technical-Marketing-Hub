/* The Sign-ins tab: sign-ins, active now, people and their usage,
 * the sample activity, and the Admin log.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, actorWord, el, row, session, tile, when } from "./util.js";
import { groupNames, ug } from "./users.js";

/* ── Sign-ins (backend/activity.py, 2026-10-07) ───────────────────────
 * Who is active now, who signed in over a period, and the log itself.
 * One period drives the tiles, People and the log, so the three always
 * agree; it sits in a bar that stays in view, and every heading names it
 * (Liwei, 2026-10-07). "Active" is a request in the last few minutes: the
 * server keeps no session, so it cannot know who still has a tab open.
 * What anyone viewed or downloaded is not on this tab -- that waits for
 * management's answer on per-user tracking. */
var ACT_RANGES = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "all", label: "All time" },
  { id: "custom", label: "Custom" }
];
var act = { range: "7d", from: "", to: "", q: "", pq: "", user: null, email: null,
            userLabel: "", offset: 0, personOffset: 0, limit: 50, people: [] };
var actTimer = null;

function startOfToday() {
  var d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

function dateInput(d) {
  var m = d.getMonth() + 1, day = d.getDate();
  return d.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;
}

/* A yyyy-mm-dd from a date input, as the reader's own midnight. */
function localDay(value) {
  var p = value.split("-");
  return new Date(+p[0], +p[1] - 1, +p[2]);
}

function actBounds() {
  var today = startOfToday();
  if (act.range === "all") return {};
  if (act.range === "today") return { since: today.toISOString() };
  if (act.range === "custom") {
    var out = {};
    if (act.from) out.since = localDay(act.from).toISOString();
    // "To" includes that whole day.
    if (act.to) out.until = new Date(localDay(act.to).getTime() + 86400000).toISOString();
    return out;
  }
  var days = act.range === "30d" ? 30 : 7;
  return { since: new Date(today.getTime() - (days - 1) * 86400000).toISOString() };
}

function periodLabel() {
  if (act.range !== "custom") {
    return ACT_RANGES.filter(function (r) { return r.id === act.range; })[0].label;
  }
  var fmt = function (v) {
    return localDay(v).toLocaleDateString(undefined, { month: "short", day: "numeric",
                                                       year: "numeric" });
  };
  if (act.from && act.to) return act.from === act.to ? fmt(act.from)
                                                     : fmt(act.from) + " – " + fmt(act.to);
  if (act.from) return "since " + fmt(act.from);
  if (act.to) return "until " + fmt(act.to);
  return "All time";
}

function ago(iso) {
  var mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return mins + " min ago";
  var hours = Math.round(mins / 60);
  if (hours < 24) return hours + " h ago";
  return new Date(iso).toLocaleDateString();
}

function account(external) { return external ? "Guest" : "PTC"; }

function loadActivity() {
  var params = actBounds();
  params.today = startOfToday().toISOString();
  params.offset = act.offset;
  params.limit = act.limit;
  if (act.q) params.q = act.q;
  if (act.user) params.user = act.user;
  var qs = Object.keys(params).map(function (k) {
    return k + "=" + encodeURIComponent(params[k]);
  }).join("&");
  // Group names for the People table come from the Users & groups data.
  var groupsReady = ug.data ? Promise.resolve() : fetch("/api/admin/access")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) ug.data = d; });
  return groupsReady.then(function () {
    return fetch("/api/admin/activity?" + qs);
  }).then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) renderActivity(d); })
    .then(loadAdminLog);
}

/* ── The Admin log (backend/admin_log.py, 2026-10-14) ──────────────────
 * Every change made through the Admin page -- and every refused attempt --
 * in the Sign-ins period. Read-only by design: the server has no way to
 * change or delete an entry, and says whether the hash chain still holds. */
var al = { q: "", category: "", result: "", offset: 0, limit: 50 };

function alQuery(paged) {
  var params = actBounds();
  if (paged) { params.offset = al.offset; params.limit = al.limit; }
  if (al.q) params.q = al.q;
  if (al.category) params.category = al.category;
  if (al.result) params.result = al.result;
  return Object.keys(params).map(function (k) {
    return k + "=" + encodeURIComponent(params[k]);
  }).join("&");
}

function loadAdminLog() {
  var qs = alQuery(true);
  // The export carries the same filters, so what downloads is what is shown.
  $("alExport").href = "/api/admin/admin-log.csv?" + alQuery(false);
  return fetch("/api/admin/admin-log?" + qs)
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) renderAdminLog(d); });
}

function detailWord(d) {
  var parts = [];
  var add = function (obj) {
    Object.keys(obj || {}).forEach(function (k) {
      var v = obj[k];
      parts.push(k + ": " + (typeof v === "object" ? JSON.stringify(v) : v));
    });
  };
  add(d && d.query);
  add(d && d.body);
  if (d && d.body_bytes) parts.push("upload, " + d.body_bytes + " bytes");
  return parts.join(" · ");
}

function adminLogTable(items, withArea) {
  var t = el("table");
  var hr = t.createTHead().insertRow();
  var heads = ["When", "Who"].concat(withArea ? ["Area"] : [])
    .concat(["What", "Demo / group", "Details", "Result"]);
  heads.forEach(function (h) { hr.appendChild(el("th", null, h)); });
  var tb = t.createTBody();
  items.forEach(function (e) {
    var tr = tb.insertRow();
    var w = tr.insertCell();
    w.className = "num faint";
    w.textContent = new Date(e.at).toLocaleString();
    tr.insertCell().textContent = actorWord(e.actor);
    if (withArea) tr.insertCell().textContent = e.category || "—";
    tr.insertCell().textContent = e.action;
    tr.insertCell().textContent = e.target || "—";
    var det = tr.insertCell();
    det.className = "al-detail";
    det.textContent = detailWord(e.detail) || "—";
    det.title = det.textContent;
    var res = tr.insertCell();
    var ok = e.status >= 200 && e.status < 400;
    res.textContent = ok ? "Done" : (e.status === 401 || e.status === 403
      ? "Refused (" + e.status + ")" : "Failed (" + e.status + ")");
    if (!ok) res.className = "al-refused";
  });
  return t;
}

function renderAdminLog(d) {
  $("alTitle").textContent = "Admin log · " + periodLabel();
  var cat = $("alCategory");
  if (cat.options.length <= 1 && d.categories) {
    d.categories.forEach(function (c) { cat.appendChild(new Option(c, c)); });
    cat.value = al.category;
  }
  var host = $("alLog");
  host.innerHTML = "";
  if (!d.items.length) {
    host.appendChild(el("div", "faint", al.q || al.category || al.result
      ? "No Admin log entries match." : "No Admin changes in this period."));
  } else {
    host.appendChild(adminLogTable(d.items, true));
  }

  var pager = $("alPager");
  pager.innerHTML = "";
  var first = d.total ? d.offset + 1 : 0;
  var last = Math.min(d.offset + al.limit, d.total);
  pager.appendChild(el("span", "faint", "Showing " + first + "–" + last + " of "
    + d.total.toLocaleString() + " entries"));
  var nav = el("div", "pager__nav");
  var back = el("button", null, "← Previous");
  back.disabled = d.offset <= 0;
  back.addEventListener("click", function () {
    al.offset = Math.max(0, al.offset - al.limit);
    loadAdminLog();
  });
  var fwd = el("button", null, "Next →");
  fwd.disabled = last >= d.total;
  fwd.addEventListener("click", function () {
    al.offset += al.limit;
    loadAdminLog();
  });
  nav.appendChild(back);
  nav.appendChild(fwd);
  pager.appendChild(nav);

  var note = $("alNote");
  var check = d.integrity || {};
  note.className = "faint act-note" + (check.intact === false ? " al-broken" : "");
  note.textContent = check.intact === false
    ? "The log file has been altered outside the Hub: entry " + check.broken_at
      + " does not follow from the one before it. Entries from there on cannot be trusted."
    : "Append-only: entries cannot be edited or deleted from the Hub, and each one "
      + "carries the hash of the one before it, so a change to the file itself shows here. "
      + (check.entries || 0).toLocaleString() + " entries in all; passwords are never written.";
}

["alCategory", "alResult"].forEach(function (id) {
  $(id).addEventListener("change", function () {
    al.category = $("alCategory").value;
    al.result = $("alResult").value;
    al.offset = 0;
    loadAdminLog();
  });
});

var alTimer = null;
$("alSearch").addEventListener("input", function (e) {
  var value = e.target.value;
  clearTimeout(alTimer);
  alTimer = setTimeout(function () {
    al.q = value.trim();
    al.offset = 0;
    loadAdminLog();
  }, 250);
});

function setRange(id) {
  act.range = id;
  act.offset = 0;
  al.offset = 0;
  if (id === "custom" && !act.from && !act.to) {
    // Start from the last seven days, which the person then narrows.
    var today = startOfToday();
    act.from = dateInput(new Date(today.getTime() - 6 * 86400000));
    act.to = dateInput(today);
  }
  renderActRanges();
  loadActivity();
}

function renderActRanges() {
  var host = $("actRanges");
  host.innerHTML = "";
  ACT_RANGES.forEach(function (r) {
    var b = el("button", null, r.label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(r.id === act.range));
    b.addEventListener("click", function () { setRange(r.id); });
    host.appendChild(b);
  });
  $("actCustom").hidden = act.range !== "custom";
  $("actFrom").value = act.from;
  $("actTo").value = act.to;
  $("actFrom").max = $("actTo").max = dateInput(new Date());
}

["actFrom", "actTo"].forEach(function (id) {
  $(id).addEventListener("change", function () {
    act.from = $("actFrom").value;
    act.to = $("actTo").value;
    if (act.from && act.to && act.from > act.to) {
      // Swapped rather than refused: the intent is plain.
      var t = act.from; act.from = act.to; act.to = t;
      $("actFrom").value = act.from;
      $("actTo").value = act.to;
    }
    act.offset = 0;
    loadActivity();
  });
});

function actGroups(ids) {
  return ug.data ? groupNames(ids || []) : "";
}

function renderActivity(d) {
  var label = periodLabel();
  $("actTitle").textContent = "Sign-ins · " + label;
  $("actPeopleTitle").textContent = "PTC people · " + label;
  $("actLogTitle").textContent = "Sign-in log · " + label;

  var tiles = $("actTiles");
  tiles.innerHTML = "";
  /* PTC people are named; external users (partners) are anonymous -- only
   * counted, never listed (meeting 2026-10-07; backend/activity.py). */
  tile(tiles, d.counts.active, "PTC people active now",
    d.external_active ? "+ external users active" : "in the last " + d.active_minutes + " min");
  tile(tiles, d.counts.today_people, "PTC people signed in today",
    d.counts.today_external_sign_ins
      ? "+ " + d.counts.today_external_sign_ins + " external sign-ins" : null);
  tile(tiles, d.counts.window_people, "PTC people", null);
  tile(tiles, d.counts.window_sign_ins, "Sign-ins", d.counts.window_external_sign_ins
    ? d.counts.window_external_sign_ins + " by external users" : null);
  var u = d.counts.window_usage || {};
  tile(tiles, (u.view || 0) + (u.preview || 0) + (u.download || 0) + (u.search || 0),
    "Views, previews, downloads, searches",
    (u.download || 0) + " downloads"
      + (d.counts.window_external_usage
        ? " · " + d.counts.window_external_usage + " by external users" : ""));

  // Active now -- always the last few minutes, whatever the period.
  $("actActiveNote").textContent = "a request in the last " + d.active_minutes
    + " minutes, whatever the period";
  var host = $("actActive");
  host.innerHTML = "";
  host.appendChild(el("div", "act-ext faint", d.external_active
    ? "External users: active (latest request " + ago(d.external_last_active)
      + "). Partners are anonymous, so they are not listed."
    : "External users: none in the last " + d.active_minutes + " minutes."
      + " Partners are anonymous, so they are never listed."));
  if (!d.active.length) {
    host.appendChild(el("div", "faint", "No PTC people right now."));
  } else {
    var t = el("table");
    var hr = t.createTHead().insertRow();
    ["Name", "Email", "Groups", "Last request"].forEach(function (h) {
      hr.appendChild(el("th", null, h));
    });
    var tb = t.createTBody();
    d.active.forEach(function (a) {
      var tr = tb.insertRow();
      var name = tr.insertCell();
      name.appendChild(el("span", "act-dot"));
      name.appendChild(document.createTextNode(a.name || "—"));
      tr.insertCell().textContent = a.user || "—";
      tr.insertCell().textContent = actGroups(a.groups) || "—";
      var when = tr.insertCell();
      when.className = "num faint";
      when.textContent = ago(a.last_active);
    });
    host.appendChild(t);
  }

  renderSample(!!d.sample_loaded);
  act.people = d.people;
  drawPeople();
  renderLogFilter();
  loadPerson();

  // The log
  host = $("actLog");
  host.innerHTML = "";
  var log = d.log;
  if (!log.items.length) {
    host.appendChild(el("div", "faint", act.user
      ? "No sign-ins by this person in this period."
      : "No sign-ins match."));
  } else {
    var lt = el("table");
    var lhr = lt.createTHead().insertRow();
    ["When", "Name", "Email", "Account"].forEach(function (h) {
      lhr.appendChild(el("th", null, h));
    });
    var ltb = lt.createTBody();
    log.items.forEach(function (e) {
      var tr = ltb.insertRow();
      var when = tr.insertCell();
      when.className = "num faint";
      when.textContent = new Date(e.at).toLocaleString();
      var who = tr.insertCell();
      who.textContent = e.external ? "External user" : (e.name || "—");
      if (e.external) who.className = "faint";
      tr.insertCell().textContent = e.external ? "—" : (e.user || "—");
      tr.insertCell().textContent = account(e.external);
    });
    host.appendChild(lt);
  }
  var pager = $("actPager");
  pager.innerHTML = "";
  var first = log.total ? log.offset + 1 : 0;
  var lastRow = Math.min(log.offset + log.limit, log.total);
  pager.appendChild(el("span", "faint", "Showing " + first + "–" + lastRow + " of "
    + log.total.toLocaleString() + " sign-ins"));
  var nav = el("div", "pager__nav");
  var back = el("button", null, "← Previous");
  back.disabled = log.offset <= 0;
  back.addEventListener("click", function () {
    act.offset = Math.max(0, act.offset - act.limit);
    loadActivity();
  });
  var fwd = el("button", null, "Next →");
  fwd.disabled = lastRow >= log.total;
  fwd.addEventListener("click", function () {
    act.offset += act.limit;
    loadActivity();
  });
  nav.appendChild(back);
  nav.appendChild(fwd);
  pager.appendChild(nav);

  $("actNote").textContent = (d.recorded_since
    ? "Sign-ins recorded since " + new Date(d.recorded_since).toLocaleString() + ". "
    : "No sign-ins recorded yet. ")
    + "PTC people are recorded by name (views, previews, downloads, searches); "
    + "external users (partners) only anonymously: when and what, never who.";
}

/* People in the period, filtered in the browser: the whole list is
 * already here, so typing narrows it at once. A click narrows the log to
 * that person: their sign-ins in the log, and what they used above it. */
var USAGE_COLS = [
  { key: "view", label: "Views" },
  { key: "preview", label: "Previews" },
  { key: "download", label: "Downloads" },
  { key: "search", label: "Searches" }
];

function lastSeen(p) {
  var times = [p.last_active, p.last_sign_in, (p.usage || {}).last_used]
    .filter(Boolean).sort();
  return times.length ? times[times.length - 1] : null;
}

function drawPeople() {
  var host = $("actPeople");
  host.innerHTML = "";
  var q = act.pq.toLowerCase();
  var rows = act.people.filter(function (p) {
    return !q || (p.user || "").indexOf(q) >= 0 || (p.name || "").toLowerCase().indexOf(q) >= 0;
  });
  $("actPeopleCount").textContent = q
    ? rows.length + " of " + act.people.length + " people shown"
    : act.people.length + " " + (act.people.length === 1 ? "person" : "people")
      + " · click a person to see what they used";
  if (!rows.length) {
    host.appendChild(el("div", "faint", act.people.length
      ? "Nobody matches." : "No PTC people used the Hub in this period."));
    return;
  }
  var pt = el("table");
  var phr = pt.createTHead().insertRow();
  ["Name", "Email", "Groups", "Sign-ins"].concat(USAGE_COLS.map(function (c) {
    return c.label;
  })).concat(["Last seen"]).forEach(function (h, i) {
    phr.appendChild(el("th", i >= 3 && i <= 7 ? "r" : null, h));
  });
  var ptb = pt.createTBody();
  rows.forEach(function (p) {
    var tr = ptb.insertRow();
    tr.className = "act-person" + (act.email === p.user ? " act-person--on" : "");
    tr.title = "Show what this person used, and their sign-ins";
    tr.insertCell().textContent = p.name || "—";
    tr.insertCell().textContent = p.user || "—";
    tr.insertCell().textContent = actGroups(p.groups) || "—";
    var n = tr.insertCell();
    n.className = "r num";
    n.textContent = p.sign_ins;
    USAGE_COLS.forEach(function (c) {
      var cell = tr.insertCell();
      var v = (p.usage || {})[c.key] || 0;
      cell.className = "r num" + (v ? "" : " faint");
      cell.textContent = v;
    });
    var seen = tr.insertCell();
    seen.className = "num faint";
    var when = lastSeen(p);
    seen.textContent = when ? ago(when) : "—";
    tr.addEventListener("click", function () {
      // Somebody who used the Hub without signing in during the period has
      // no sign-ins to show; "-" matches none rather than everyone.
      act.user = p.oid || "-";
      act.email = p.user;
      act.userLabel = p.name || p.user || p.oid;
      act.offset = 0;
      act.personOffset = 0;
      loadActivity().then(function () {
        $("actPersonSection").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  });
  host.appendChild(pt);
}

/* One person's views, previews, downloads and searches in the period. */
var EVENT_WORD = { view: "Opened", preview: "Previewed", download: "Downloaded",
                   search: "Searched" };

function loadPerson() {
  var section = $("actPersonSection");
  section.hidden = !act.email;
  if (!act.email) return Promise.resolve();
  var params = actBounds();
  params.email = act.email;
  params.offset = act.personOffset || 0;
  params.limit = 50;
  var qs = Object.keys(params).map(function (k) {
    return k + "=" + encodeURIComponent(params[k]);
  }).join("&");
  return fetch("/api/admin/activity/person?" + qs)
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) renderPerson(d); });
}

function renderPerson(d) {
  $("actPersonTitle").textContent = "What " + act.userLabel + " used · " + periodLabel();
  var tiles = $("actPersonTiles");
  tiles.innerHTML = "";
  USAGE_COLS.forEach(function (c) { tile(tiles, d.counts[c.key], c.label, null); });
  var host = $("actPerson");
  host.innerHTML = "";
  if (!d.items.length) {
    host.appendChild(el("div", "faint", "Nothing used in this period. What each person "
      + "uses is recorded from October 2026 on."));
  } else {
    var t = el("table");
    var hr = t.createTHead().insertRow();
    ["When", "What", "Demo or search", "Detail"].forEach(function (h) {
      hr.appendChild(el("th", null, h));
    });
    var tb = t.createTBody();
    d.items.forEach(function (e) {
      var tr = tb.insertRow();
      var when = tr.insertCell();
      when.className = "num faint";
      when.textContent = new Date(e.at).toLocaleString();
      tr.insertCell().textContent = EVENT_WORD[e.event] || e.event;
      var what = tr.insertCell();
      if (e.event === "search") {
        what.textContent = "“" + (e.q || "") + "”";
      } else if (e.asset_id) {
        var a = el("a", null, e.title || e.asset_id);
        a.href = "/#/asset/" + encodeURIComponent(e.asset_id);
        a.target = "_blank";
        a.rel = "noopener";
        what.appendChild(a);
      } else {
        what.textContent = "—";
      }
      var detail = tr.insertCell();
      detail.className = "faint";
      detail.textContent = e.event === "search"
        ? (e.results === 0 ? "no results" : e.results + " result" + (e.results === 1 ? "" : "s"))
        : (e.file || "");
    });
    host.appendChild(t);
  }
  var pager = $("actPersonPager");
  pager.innerHTML = "";
  var first = d.total ? d.offset + 1 : 0;
  var last = Math.min(d.offset + d.limit, d.total);
  pager.appendChild(el("span", "faint", "Showing " + first + "–" + last + " of "
    + d.total.toLocaleString()));
  var nav = el("div", "pager__nav");
  var back = el("button", null, "← Previous");
  back.disabled = d.offset <= 0;
  back.addEventListener("click", function () {
    act.personOffset = Math.max(0, d.offset - d.limit);
    loadPerson();
  });
  var fwd = el("button", null, "Next →");
  fwd.disabled = last >= d.total;
  fwd.addEventListener("click", function () {
    act.personOffset = d.offset + d.limit;
    loadPerson();
  });
  nav.appendChild(back);
  nav.appendChild(fwd);
  pager.appendChild(nav);
}

function clearPerson() {
  act.user = null;
  act.email = null;
  act.offset = 0;
  loadActivity();
}

$("actPersonClose").addEventListener("click", clearPerson);

/* Who the log is narrowed to, in which period, and the ways out. */
function renderLogFilter() {
  var filter = $("actFilter");
  filter.innerHTML = "";
  filter.hidden = !act.user;
  if (!act.user) return;
  filter.appendChild(el("span", null, "Showing sign-ins of " + act.userLabel
    + " · " + periodLabel()));
  if (act.range !== "all") {
    var all = el("button", null, "All time for this person");
    all.type = "button";
    all.addEventListener("click", function () { setRange("all"); });
    filter.appendChild(all);
  }
  var clear = el("button", null, "Show everyone");
  clear.type = "button";
  clear.addEventListener("click", clearPerson);
  filter.appendChild(clear);
}

/* Sample activity for demonstrating Hub activity (2026-10-14): written
 * to its own file, flagged synthetic, made-up people; removing it leaves
 * real usage untouched (services/sample_activity.py). */
var sampleNote = "";   // set after loading, when no demo had a creator

function renderSample(loaded) {
  var host = $("actSample");
  host.innerHTML = "";
  host.appendChild(el("p", "muted", loaded
    ? "Sample activity is loaded: about 90 days of made-up usage by 24 sample people "
      + "on real demos. Hub activity and these tables show a banner while it is "
      + "in the period. Remove it before reading any figure as real."
    : "For demonstrating Hub activity while real usage is still building up. "
      + "Adds about 90 days of made-up usage by 24 sample people (“Sample User 01”...) "
      + "on real demos, flagged as sample data everywhere it shows. Real usage is kept "
      + "apart and is never changed."));
  if (loaded && sampleNote) host.appendChild(el("p", "promo-status", sampleNote));
  var status = el("span", "promo-status faint");
  if ((session.permissions || []).indexOf("manage_users") < 0) {
    host.appendChild(el("p", "faint", "Loading or removing it needs Manage users & groups."));
    return;
  }
  var row = el("div", "ug-actions");
  var btn = el("button", loaded ? "btn-small" : "btn-primary", loaded
    ? "Remove sample activity" : "Load sample activity");
  btn.type = "button";
  btn.addEventListener("click", function () {
    status.textContent = loaded ? "Removing…" : "Loading…";
    fetch("/api/admin/sample-activity", { method: loaded ? "DELETE" : "POST" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        sampleNote = d.loaded && d.with_creator === 0
          ? "No demo has a creator yet, so “Whose demos were used most” stays empty. "
            + "Creators are read from SharePoint by a full sync: run Sync, then load "
            + "the sample again."
          : "";
        return loadActivity();
      })
      .catch(function (err) { status.textContent = "Did not work: " + err.message; });
  });
  row.appendChild(btn);
  row.appendChild(status);
  host.appendChild(row);
}

$("actSearch").addEventListener("input", function (e) {
  var value = e.target.value;
  clearTimeout(actTimer);
  actTimer = setTimeout(function () {
    act.q = value.trim();
    act.offset = 0;
    loadActivity();
  }, 250);
});

$("actPeopleSearch").addEventListener("input", function (e) {
  act.pq = e.target.value.trim();
  drawPeople();
});

export {
  act, adminLogTable, al, loadActivity, renderActRanges
};
