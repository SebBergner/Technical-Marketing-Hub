/* Admin -> GXC videos: the GXC download switch, personal links and GXC
 * group only, plus loadChanges, each tab's slice of the Admin log. The rest
 * of the old Content access tab (PTC Only demos, requests, hidden demos)
 * moved to Content health on 2026-11-11 (static/js/content-health/).
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, actorWord, el, gxcMark, row, session, TYPE_WORD, when } from "./util.js";
import { al } from "./signins.js";
import { adminLogTable } from "./logtable.js";
import { showTab } from "./main.js";

/* GXC downloads are an access decision for administrators (2026-10-30). */
function canSwitchGxc() {
  return (session.permissions || []).indexOf("manage_users") >= 0;
}

/* Admin -> GXC videos (Content access until 2026-11-11, when the rest of
 * it moved to Content health). */
function loadGxcTab() {
  loadGxc();
  loadGxcLinks();
  loadChanges("caChanges", "Content access");
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

export {
  loadChanges, loadGxcTab
};
