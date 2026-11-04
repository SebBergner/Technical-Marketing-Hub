/* The Content access tab: Internal demos, requests to make a demo
 * Internal or Open, hidden demos, and each tab's recent changes.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, actorWord, el, gxcMark, row, session, TYPE_WORD, when } from "./util.js";
import { promoMeta } from "./home.js";
import { act, adminLogTable, al } from "./signins.js";
import { showTab } from "./main.js";

/* ── Content access: Open / Internal (2026-10-07) ─────────────────────
 * Every Internal demo and why. Two ways in, one rule out: a demo whose
 * SharePoint folder is closed to partners is Internal automatically (and
 * opened only there); any other demo can be marked Internal here or on
 * its own page. Only "Access internal content" opens an Internal demo's
 * files; everyone else sees its card and description. */
function canManageAccess() {
  return (session.permissions || []).indexOf("maintain_content") >= 0;
}

/* GXC downloads are an access decision for administrators (2026-10-30). */
function canSwitchGxc() {
  return (session.permissions || []).indexOf("manage_users") >= 0;
}

function loadContentAccess() {
  loadGxc();
  loadGxcLinks();
  loadRequests();
  loadChanges("caChanges", "Content access");
  return fetch("/api/admin/content-access")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (items) { if (items) renderContentAccess(items); });
}

/* ── Requests to make a demo Internal or Open (2026-10-15) ──────────────
 * Asked for on a demo's page, with a reason (services/access_requests.py);
 * decided here or there. Pending first, then the last decided ones. */
function loadRequests() {
  return fetch("/api/admin/access-requests?limit=60")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (items) { if (items) renderRequests(items); });
}

function renderRequests(items) {
  var host = $("caRequests");
  host.innerHTML = "";
  var pending = items.filter(function (i) { return i.status === "pending"; });
  // Nobody asks this way since 2026-10-28 (Report an issue instead): the
  // card stays only while requests from before are waiting or recent.
  host.hidden = !items.length;
  var done = items.filter(function (i) { return i.status !== "pending"; }).slice(0, 8);
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "Requests"));
  head.appendChild(el("span", "faint num", pending.length + " waiting"));
  host.appendChild(head);
  host.appendChild(el("p", "muted", "Requests made before 2026-10-28; people now ask with "
    + "Share feedback (Other) on a demo's page. Approving applies the change; both answers "
    + "are kept with the request and in the Admin log."));
  if (!pending.length) host.appendChild(el("div", "faint", "Nothing is waiting."));
  var manage = canManageAccess();
  pending.forEach(function (q) {
    var row = el("div", "req-row");
    var info = el("div");
    var title = el("a", "promo-row__title", q.title || q.asset_id);
    title.href = "/#/asset/" + encodeURIComponent(q.asset_id);
    gxcMark(title, q.asset_id);
    title.target = "_blank";
    title.rel = "noopener";
    info.appendChild(title);
    info.appendChild(el("div", "promo-row__meta", "Make " + (q.level === "internal"
      ? "PTC Only" : "Open") + " · asked by " + actorWord(q.requested_by) + " · "
      + new Date(q.requested_at).toLocaleString()));
    info.appendChild(el("p", "req-row__reason", "“" + q.reason + "”"));
    row.appendChild(info);
    var acts = el("div", "req-row__acts");
    if (manage) {
      var note = el("div", "req-row__note");
      var input = el("input");
      input.type = "text";
      input.placeholder = "Note (optional; the requester sees it)";
      input.maxLength = 1000;
      note.appendChild(input);
      var status = el("span", "promo-status faint");
      var decide = function (yes) {
        status.textContent = "Saving…";
        fetch("/api/admin/access-requests/" + encodeURIComponent(q.id) + "/decision", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve: yes, note: input.value.trim() || null }),
        }).then(function (r) {
          if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
            throw new Error(b.detail || ("HTTP " + r.status));
          });
          return loadContentAccess();
        }).catch(function (err) {
          status.textContent = "Not saved: " + err.message;
          status.className = "promo-status err";
        });
      };
      var yes = el("button", "btn-primary", "Approve");
      yes.type = "button";
      yes.addEventListener("click", function () { decide(true); });
      var no = el("button", null, "Reject");
      no.type = "button";
      no.addEventListener("click", function () { decide(false); });
      acts.appendChild(yes);
      acts.appendChild(no);
      row.appendChild(acts);
      note.appendChild(status);
      row.appendChild(note);
    } else {
      row.appendChild(acts);
    }
    host.appendChild(row);
  });
  if (done.length) {
    host.appendChild(el("div", "faint", "Recently decided"))
      .style.cssText = "margin:12px 0 4px;font-size:12px;font-weight:600";
    done.forEach(function (q) {
      var line = el("div", "promo-row__meta",
        (q.title || q.asset_id) + " · Make " + (q.level === "internal" ? "PTC Only" : "Open")
        + " · " + q.status + (q.decided_by ? " by " + actorWord(q.decided_by) : "")
        + (q.decided_at ? " · " + new Date(q.decided_at).toLocaleDateString() : "")
        + (q.note ? " — " + q.note : ""));
      line.style.padding = "3px 0";
      host.appendChild(line);
    });
  }
}

/* One area's slice of the Admin log, at the foot of its own tab: the same
 * tamper-evident log, filtered, rather than a second log to keep whole. */
function loadChanges(hostId, category) {
  var host = $(hostId);
  if (!host) return;
  return fetch("/api/admin/admin-log?limit=15&category=" + encodeURIComponent(category))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      host.innerHTML = "";
      if (!d) return;
      if (!d.items.length) {
        host.appendChild(el("div", "faint", "No changes recorded yet."));
      } else {
        host.appendChild(adminLogTable(d.items));
      }
      var more = el("a", null, "Open in the Admin log →");
      more.href = "#activity";
      more.style.cssText = "display:inline-block;margin-top:8px;font-size:13px";
      more.addEventListener("click", function (e) {
        e.preventDefault();
        // A tab may show two areas; the filter takes the first, the log shows it.
        al.category = category.split(",")[0];
        $("alCategory").value = al.category;
        al.offset = 0;
        history.replaceState(null, "", "#activity");
        showTab("activity");
        setTimeout(function () { $("alTitle").scrollIntoView({ block: "start" }); }, 600);
      });
      host.appendChild(more);
    });
}

function setAccess(assetId, level, status) {
  status.textContent = "Saving…";
  status.className = "promo-status faint";
  return fetch("/api/assets/" + encodeURIComponent(assetId) + "/access", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level: level }),
  }).then(function (r) {
    if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
      throw new Error(b.detail || ("HTTP " + r.status));
    });
    return r.json();
  }).then(function () { return loadContentAccess(); })
    .catch(function (err) {
      status.textContent = "Not saved: " + err.message;
      status.className = "promo-status err";
    });
}

/* ── GXC videos (Liwei, 2026-10-29) ─────────────────────────────────────
 * The GXC Video library's demos exist on the Hub only for groups with
 * "Access GXC videos"; this card says how many there are, which groups see
 * them, and holds the one switch: whether they can be downloaded. */
function loadGxc() {
  return fetch("/api/admin/gxc")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (s) { if (s) renderGxc(s); });
}

function renderGxc(s) {
  var host = $("gxcCard");
  host.innerHTML = "";
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "GXC videos"));
  head.appendChild(el("span", "faint num", s.library
    ? (s.videos == null ? "—" : s.videos) + " in " + s.library : "Not configured"));
  host.appendChild(head);
  host.appendChild(el("p", "muted", "Videos in the GXC Video library are for a few PTC "
    + "people only. Anyone whose groups lack Access GXC videos never finds them on the Hub: "
    + "they are not listed or searchable. Another PTC person opens one only through a "
    + "personal link somebody shared (see GXC personal links). Administrators always see "
    + "them; partners never do. SharePoint restricts the library itself, so keep its group "
    + "and these Hub groups the same people."));
  var who = el("div", "promo-row__meta");
  who.style.margin = "0 0 10px";
  who.textContent = s.groups.length
    ? "Seen by: " + s.groups.map(function (g) {
        return g.name + (g.auto ? "" : " (" + g.members + ")");
      }).join(", ")
    : "No group has Access GXC videos.";
  host.appendChild(who);

  var row = el("div", "promo-row");
  row.style.gridTemplateColumns = "1fr auto";
  var text = el("div");
  text.appendChild(el("div", "promo-row__title", "Downloads"));
  text.appendChild(el("div", "promo-row__meta", "Whether GXC videos can be downloaded "
    + "from the Hub. Off, they still play in the preview; a copy can't be fully "
    + "prevented either way. Off by default."));
  row.appendChild(text);
  var toggle = el("label", "switch");
  var box = el("input");
  box.type = "checkbox";
  box.checked = !!s.downloads;
  box.disabled = !canSwitchGxc();
  box.setAttribute("aria-label", "GXC downloads");
  toggle.appendChild(box);
  toggle.appendChild(el("span", "switch__track"));
  toggle.appendChild(el("span", "switch__label", s.downloads ? "On" : "Off"));
  row.appendChild(toggle);
  host.appendChild(row);
  var status = el("div", "promo-status faint", canSwitchGxc() ? ""
    : "Changing this needs Manage users & groups.");
  host.appendChild(status);
  box.addEventListener("change", function () {
    box.disabled = true;
    status.textContent = "Saving…";
    fetch("/api/admin/gxc", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ downloads: box.checked }),
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(renderGxc).catch(function (err) {
      box.checked = !box.checked;
      box.disabled = false;
      status.textContent = "Not saved: " + err.message;
      status.className = "promo-status err";
    });
  });
}

/* ── GXC personal links (B10 step 2, 2026-11-03) ─────────────────────────
 * Every GXC link is personal (backend/gxc_shares.py). Who opened whose
 * link, who may see which video because of it, and revoking: everything a
 * person sent, or for one video, and whatever came through it. View Admin
 * and Access GXC videos both; revoking needs Manage users & groups. */
var gxcLinksFilter = "";

function loadGxcLinks() {
  var q = gxcLinksFilter.trim();
  var params = !q ? "" : (/^gxc-/.test(q) ? "?asset_id=" : "?person=") + encodeURIComponent(q);
  return fetch("/api/admin/gxc-links" + params)
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) { renderGxcLinks(data, q, params); });
}

function revokeGxc(sender, assetId, title) {
  var what = assetId ? "the links " + sender + " sent for “" + title + "”"
                     : "every GXC link " + sender + " sent";
  if (!window.confirm("Revoke " + what + "?\n\nWhoever opened the video through them, "
      + "and anyone they passed it on to, can no longer open it. This cannot be undone; "
      + sender + " can share again later.")) return;
  fetch("/api/admin/gxc-links/revoke", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sender: sender, asset_id: assetId || null }),
  }).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (res) {
    window.alert("Revoked. " + res.grants_revoked.length + " person/video access(es) ended.");
    loadGxcLinks();
  }).catch(function (err) { window.alert("Not revoked: " + err.message); });
}

function gxcTable(heads, rows, cells) {
  var wrap = el("div", "rv-table");
  var table = el("table");
  var tr = el("tr");
  heads.forEach(function (h) { tr.appendChild(el("th", null, h)); });
  table.appendChild(tr);
  rows.forEach(function (r) {
    var line = el("tr");
    cells(r).forEach(function (c) {
      var td = el("td");
      if (c instanceof Node) td.appendChild(c); else td.textContent = c == null ? "" : c;
      line.appendChild(td);
    });
    table.appendChild(line);
  });
  wrap.appendChild(table);
  return wrap;
}

function renderGxcLinks(data, q, params) {
  var host = $("gxcLinksCard");
  if (!data) { host.style.display = "none"; return; }       // no Access GXC videos
  host.style.display = "";
  host.innerHTML = "";
  var canRevoke = canSwitchGxc();
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "GXC personal links"));
  var csv = el("button", "btn-small", "Export CSV");
  csv.addEventListener("click", function () {
    window.location.href = "/api/admin/gxc-links.csv" + params;
  });
  head.appendChild(csv);
  host.appendChild(head);
  host.appendChild(el("p", "muted", "Every GXC link is personal: it names, to the Hub, "
    + "whoever shared it. A PTC person outside the GXC group may open a video once someone's "
    + "link has opened it for them. Revoking someone's links ends that access for everyone "
    + "who came through them, and for whoever they passed it on to."));

  var bar = el("div");
  bar.style.margin = "0 0 10px";
  var input = el("input");
  input.type = "search";
  input.placeholder = "A person's email, or a video id (gxc-…)";
  input.value = q;
  input.style.width = "min(360px,100%)";
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { gxcLinksFilter = input.value; loadGxcLinks(); }
  });
  bar.appendChild(input);
  var go = el("button", "btn-small", "Show");
  go.style.marginLeft = "8px";
  go.addEventListener("click", function () { gxcLinksFilter = input.value; loadGxcLinks(); });
  bar.appendChild(go);
  if (q && !/^gxc-/.test(q) && canRevoke) {
    var all = el("button", "btn-danger", "Revoke every link " + q + " sent");
    all.style.marginLeft = "8px";
    all.addEventListener("click", function () { revokeGxc(q.toLowerCase(), null); });
    bar.appendChild(all);
  }
  host.appendChild(bar);

  host.appendChild(el("h3", null, "Opened through someone's link (" + data.opens.length + ")"));
  host.appendChild(data.opens.length ? gxcTable(
    ["When", "Video", "Opened by", "Link of", ""], data.opens.slice(0, 200), function (o) {
      return [when(o.at), o.title, o.who, o.via, o.granted ? "first time" : ""];
    }) : el("p", "faint", "None yet."));

  host.appendChild(el("h3", null, "May open because of a link (" + data.grants.length + ")"));
  host.appendChild(data.grants.length ? gxcTable(
    ["Since", "Video", "Person", "Through the link of", ""], data.grants.slice(0, 200),
    function (g) {
      var state;
      if (g.revoked_at) state = "revoked " + when(g.revoked_at);
      else if (canRevoke) {
        state = el("button", "btn-danger", "Revoke " + g.via + "'s links");
        state.title = "Revoke the links " + g.via + " sent for this video";
        state.addEventListener("click", function () { revokeGxc(g.via, g.asset_id, g.title); });
      } else state = "";
      return [when(g.at), g.title, g.who, g.via, state];
    }) : el("p", "faint", "None yet."));

  if (data.revocations.length) {
    host.appendChild(el("h3", null, "Revoked"));
    host.appendChild(gxcTable(["When", "Links of", "Video", "By", "Access ended"],
      data.revocations, function (r) {
        return [when(r.at), r.sender || r.why || "", r.asset_id ? r.title : "every video",
                actorWord(r.by), r.grants_revoked];
      }));
  }
  var only = el("div");
  only.id = "gxcGroupOnly";
  host.appendChild(only);
  loadGroupOnly();
}

/* ── GXC group only (Liwei 2026-11-02; Elio 2026-11-04) ──────────────────
 * A GXC video for the GXC group alone: no personal links, no Share
 * Internally, and the links already sent stop. The three Lamborghini
 * videos in GXC Video; anything else marked here too. */
function loadGroupOnly() {
  return fetch("/api/admin/gxc-group-only")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) renderGroupOnly(d); });
}

function setGroupOnly(assetId, title, on) {
  if (on && !window.confirm("Make “" + title + "” GXC group only?\n\n"
      + "Only the GXC group can open it. Personal links to it stop working, and anyone "
      + "outside the group who opened it through one can no longer open it.")) return;
  fetch("/api/admin/gxc-group-only/" + encodeURIComponent(assetId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: on }),
  }).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function () { loadGxcLinks(); })
    .catch(function (err) { window.alert("Not saved: " + err.message); });
}

function renderGroupOnly(d) {
  var host = $("gxcGroupOnly");
  if (!host) return;
  host.innerHTML = "";
  var canChange = canSwitchGxc();
  host.appendChild(el("h3", null, "GXC group only (" + d.marked.length + ")"));
  host.appendChild(el("p", "muted", "For the GXC group alone: no personal links and no "
    + "Share Internally, so nobody outside the group can open it, whatever link they have."));
  if (d.marked.length) {
    host.appendChild(gxcTable(["Video", "Since", "By", ""], d.marked, function (m) {
      var off = "";
      if (canChange) {
        off = el("button", "btn-small", "Remove");
        off.title = "Personal links can be shared again; earlier access does not come back.";
        off.addEventListener("click", function () { setGroupOnly(m.asset_id, m.title, false); });
      }
      return [m.title, when(m.at), actorWord(m.by), off];
    }));
  }
  if (!canChange) {
    host.appendChild(el("p", "faint", "Changing this needs Manage users & groups."));
    return;
  }
  var bar = el("div");
  bar.style.margin = "8px 0 0";
  var pick = el("select");
  pick.setAttribute("aria-label", "A GXC video to make GXC group only");
  pick.appendChild(el("option", null, "Choose a GXC video…"));
  pick.firstChild.value = "";
  d.videos.forEach(function (v) {
    var o = el("option", null, v.title);
    o.value = v.asset_id;
    pick.appendChild(o);
  });
  bar.appendChild(pick);
  var add = el("button", "btn-small", "Make GXC group only");
  add.style.marginLeft = "8px";
  add.addEventListener("click", function () {
    if (!pick.value) return;
    setGroupOnly(pick.value, pick.options[pick.selectedIndex].text, true);
  });
  bar.appendChild(add);
  host.appendChild(bar);
}

function renderContentAccess(items) {
  var host = $("caList");
  host.innerHTML = "";
  var manage = canManageAccess();
  var hub = items.filter(function (i) { return i.source === "hub"; });
  var sp = items.filter(function (i) { return i.source === "sharepoint"; });

  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "PTC Only demos"));
  head.appendChild(el("span", "faint num", hub.length + " marked here · " + sp.length
    + " closed in SharePoint"));
  host.appendChild(head);
  var status = el("div", "promo-status faint");

  var list = el("div");
  if (!items.length) list.appendChild(el("div", "faint", "Every demo is Open."));
  items.forEach(function (i) {
    var r = el("div", "promo-row");
    r.appendChild(el("span", "promo-row__n", ""));
    var info = el("div");
    var title = el("a", "promo-row__title", i.title || i.asset_id);
    title.href = "/#/asset/" + encodeURIComponent(i.asset_id);
    gxcMark(title, i.asset_id);
    title.target = "_blank";
    title.rel = "noopener";
    info.appendChild(title);
    var why = i.source === "sharepoint"
      ? "Closed to partners in SharePoint — open it there to make it Open"
      : "Marked PTC Only" + (i.marked_by ? " by " + i.marked_by.replace(/^(user|dev):/, "") : "")
        + (i.marked_at ? " · " + new Date(i.marked_at).toLocaleString() : "")
        + (i.reason ? " — " + i.reason : "");
    info.appendChild(el("div", "promo-row__meta",
      [TYPE_WORD[i.type] || i.type, why].filter(Boolean).join(" · ")));
    r.appendChild(info);
    var acts = el("div", "promo-row__actions");
    if (i.source === "sharepoint") {
      acts.appendChild(el("span", "pill pill--off", "SharePoint"));
    } else if (manage) {
      var open = el("button", null, "Make Open");
      open.type = "button";
      open.addEventListener("click", function () { setAccess(i.asset_id, "open", status); });
      acts.appendChild(open);
    }
    r.appendChild(acts);
    list.appendChild(r);
  });
  host.appendChild(list);

  if (manage) {
    var add = el("div", "promo-add");
    var label = el("label", null, "Mark a demo PTC Only");
    var input = el("input");
    input.type = "search";
    input.placeholder = "Search by title…";
    input.autocomplete = "off";
    label.appendChild(input);
    add.appendChild(label);
    var results = el("div", "promo-results");
    add.appendChild(results);
    host.appendChild(add);
    var internalIds = items.map(function (i) { return i.asset_id; });
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
            var hits = page.items.filter(function (a) { return internalIds.indexOf(a.id) < 0; });
            if (!hits.length) {
              results.appendChild(el("div", "faint", "No Open demo matches."));
              return;
            }
            hits.forEach(function (a) {
              var r = el("div", "promo-row");
              r.appendChild(el("span", "promo-row__n", ""));
              var info = el("div");
              info.appendChild(el("div", "promo-row__title", a.title));
              info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
              r.appendChild(info);
              var mark = el("button", null, "Make PTC Only");
              mark.type = "button";
              mark.addEventListener("click", function () {
                setAccess(a.id, "internal", status);
              });
              var acts2 = el("div", "promo-row__actions");
              acts2.appendChild(mark);
              r.appendChild(acts2);
              results.appendChild(r);
            });
          });
      }, 250);
    });
  } else {
    host.appendChild(el("p", "faint", "Viewing only: marking demos needs the "
      + "Maintain content permission."));
  }
  host.appendChild(status);
}

/* ── Hidden demos ─────────────────────────────────────────────────────
 * Liwei, 2026-10-06: hide a demo from the Hub from here, the way Featured
 * picks are made -- search, Hide; Unhide to bring it back. Admin sign-in
 * only. Nothing changes in SharePoint or Consensus, and a sync does not
 * bring a hidden demo back. */
function loadHidden() {
  return fetch("/api/admin/hidden")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (items) { if (items) renderHidden(items); });
}

function renderHidden(items) {
  var host = $("hiddenDemos");
  if (!host) return;
  host.innerHTML = "";
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, "Hidden from the Hub"));
  head.appendChild(el("span", "faint num", String(items.length)));
  host.appendChild(head);
  host.appendChild(el("p", "muted",
    "A hidden demo is gone from every list, search, Featured and the content dashboard, "
    + "for everyone; its old links say it is not in the Hub. SharePoint and Consensus are "
    + "not changed, and syncing does not bring it back."));
  var status = el("div", "promo-status faint");
  var act = function (method, url, body) {
    status.textContent = "Saving…";
    status.className = "promo-status faint";
    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
        throw new Error(b.detail || ("HTTP " + r.status));
      });
      return r.json();
    }).then(renderHidden).catch(function (err) {
      status.textContent = "Not saved: " + err.message;
      status.className = "promo-status err";
    });
  };

  var list = el("div");
  if (!items.length) list.appendChild(el("div", "faint", "Nothing hidden."));
  items.forEach(function (h) {
    var r = el("div", "promo-row");
    r.appendChild(el("span", "promo-row__n", ""));
    var info = el("div");
    info.appendChild(el("div", "promo-row__title", h.title || h.asset_id));
    info.appendChild(el("div", "promo-row__meta",
      [TYPE_WORD[h.type] || h.type, "hidden " + new Date(h.hidden_at).toLocaleString()]
        .filter(Boolean).join(" · ")));
    r.appendChild(info);
    var actions = el("div", "promo-row__actions");
    var unhide = el("button", null, "Unhide");
    unhide.addEventListener("click", function () {
      act("DELETE", "/api/admin/hidden/" + encodeURIComponent(h.asset_id));
    });
    actions.appendChild(unhide);
    r.appendChild(actions);
    list.appendChild(r);
  });
  host.appendChild(list);

  var add = el("div", "promo-add");
  var label = el("label", null, "Hide a demo");
  var input = el("input");
  input.type = "search";
  input.placeholder = "Search by title…";
  input.autocomplete = "off";
  label.appendChild(input);
  add.appendChild(label);
  var results = el("div", "promo-results");
  add.appendChild(results);
  host.appendChild(add);
  host.appendChild(status);

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
            var title = el("a", "promo-row__title", a.title);
            title.href = "/#/asset/" + encodeURIComponent(a.id);
            gxcMark(title, a.id);
            title.target = "_blank";
            title.rel = "noopener";
            info.appendChild(title);
            info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
            r.appendChild(info);
            var hide = el("button", null, "Hide");
            hide.addEventListener("click", function () {
              act("POST", "/api/admin/hidden", { asset_id: a.id });
            });
            var acts = el("div", "promo-row__actions");
            acts.appendChild(hide);
            r.appendChild(acts);
            results.appendChild(r);
          });
        });
    }, 250);
  });
}

export {
  loadChanges, loadContentAccess, loadHidden
};
