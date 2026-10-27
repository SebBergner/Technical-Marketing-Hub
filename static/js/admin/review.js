/* The Content review tab: new uploads, collecting dust, little used,
 * Still current running out, archived.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, actorWord, demoLink, el, row, session, TYPE_WORD } from "./util.js";
import { loadChanges } from "./access.js";
import { act } from "./signins.js";

/* ── Content review (2026-10-14) ──────────────────────────────────────
 * What to look at again: collecting dust (Serge: 7+ years, not confirmed
 * Still current), little used (Elio: a year old; Seb: and not used
 * lately), Still current running out, and what is archived. Every action
 * is Hub-only: Still current lasts a year, Archive takes a demo out of the
 * Hub's lists, Restore puts it back. SharePoint is never changed. */
function canReviewContent() {
  return (session.permissions || []).indexOf("review_content") >= 0;
}

/* Archive and Restore are "Archive content" since 2026-10-28 (A8). */
function canArchive() {
  return (session.permissions || []).indexOf("archive_content") >= 0;
}

/* Where an archived demo is (A8): moved into SharePoint's _Archive, kept
   where it was (archived in the Hub before _Archive existed -- to move by
   hand), or not a SharePoint folder at all. */
var WHERE = { sharepoint: "folder in _Archive",
              hub_only: "only hidden in the Hub — folder not moved yet",
              hub: "hidden in the Hub (not a SharePoint folder)" };

/* Uploads through the Hub waiting for review (2026-10-15): listed nowhere
 * else until published. Opening the demo shows its files; Publish and Send
 * back are here and on the demo's Manage tab. */
function loadUploads() {
  var host = $("rvUploads");
  return fetch("/api/uploads?status=pending,sent_back&limit=100")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (items) {
      host.innerHTML = "";
      if (!items) { host.hidden = true; return; }
      host.hidden = false;
      var pending = items.filter(function (u) { return u.status === "pending"; });
      var head = el("div", "card-head");
      head.appendChild(el("h2", null, "New uploads"));
      head.appendChild(el("span", "faint num", pending.length + " waiting"
        + (items.length > pending.length ? " · " + (items.length - pending.length)
           + " sent back" : "")));
      host.appendChild(head);
      if (!items.length) {
        host.appendChild(el("div", "faint", "Nothing uploaded is waiting for review."));
        return;
      }
      items.forEach(function (u) {
        var row = el("div", "req-row");
        var info = el("div");
        var title = el(u.asset_id ? "a" : "span", "promo-row__title", u.title);
        if (u.asset_id) {
          title.href = "/#/asset/" + encodeURIComponent(u.asset_id);
          title.target = "_blank";
          title.rel = "noopener";
        }
        info.appendChild(title);
        var v = u.values || {};
        info.appendChild(el("div", "promo-row__meta", [
          (u.target === "demo_video" ? "Video" : (u.kind || "").toUpperCase()),
          (v.products || []).join(", "), (v.segment || []).join(", "),
          "by " + actorWord(u.uploaded_by)
            + (u.submitted_by ? " for " + u.submitted_by : ""),
          u.submitted_at ? new Date(u.submitted_at).toLocaleDateString() : null,
          u.internal ? "asks to be Internal" : null,
          u.asset_id ? null : "not in the Hub yet"
        ].filter(Boolean).join(" · ")));
        if (!u.asset_id) {
          var idx = el("button", "btn-small", "Index now");
          idx.type = "button";
          idx.title = "Read it from SharePoint now (a sync; queued if one is running)";
          idx.addEventListener("click", function () {
            idx.disabled = true;
            idx.textContent = "Indexing…";
            fetch("/api/uploads/" + encodeURIComponent(u.id) + "/index", { method: "POST" })
              .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); })
              .then(function () { setTimeout(loadUploads, 60000); })
              .catch(function (err) { idx.disabled = false; idx.textContent = "Index now";
                                      window.alert("Not started: " + err.message); });
          });
          info.appendChild(idx);
        }
        if (u.status === "sent_back") {
          info.appendChild(el("p", "req-row__reason", "Sent back: “" + (u.note || "") + "”"));
        }
        if (u.web_url) {
          var sp = el("a", null, "Open in SharePoint");
          sp.href = u.web_url;
          sp.target = "_blank";
          sp.rel = "noopener";
          sp.style.fontSize = "12.5px";
          info.appendChild(sp);
        }
        row.appendChild(info);
        var acts = el("div", "req-row__acts");
        if (u.status === "pending" && session.permissions.indexOf("review_content") >= 0) {
          var note = el("div", "req-row__note");
          var input = el("input");
          input.type = "text";
          input.placeholder = "Note (required to send back)";
          input.maxLength = 1000;
          note.appendChild(input);
          var status = el("span", "promo-status faint");
          note.appendChild(status);
          var act = function (path) {
            status.textContent = "Saving…";
            fetch("/api/uploads/" + encodeURIComponent(u.id) + "/" + path, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ note: input.value.trim() || null }),
            }).then(function (r) {
              if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
                throw new Error(b.detail || ("HTTP " + r.status));
              });
              loadUploads();
              loadChanges("rvChanges", "Content review,Uploads");
            }).catch(function (err) {
              status.textContent = "Not saved: " + err.message;
              status.className = "promo-status err";
            });
          };
          var pub = el("button", "btn-primary", "Publish");
          pub.type = "button";
          pub.addEventListener("click", function () { act("publish"); });
          var back = el("button", null, "Send back");
          back.type = "button";
          back.addEventListener("click", function () { act("send-back"); });
          acts.appendChild(pub);
          acts.appendChild(back);
          row.appendChild(acts);
          row.appendChild(note);
        } else {
          row.appendChild(acts);
        }
        host.appendChild(row);
      });
    });
}

function loadReview() {
  loadUploads();
  loadChanges("rvChanges", "Content review,Uploads");
  return fetch("/api/admin/content-review")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) renderReview(d); });
}

function reviewAction(url, body, status) {
  status.textContent = "Saving…";
  status.className = "promo-status faint";
  return fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(function (r) {
    if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
      throw new Error(b.detail || ("HTTP " + r.status));
    });
    return loadReview();
  }).catch(function (err) {
    status.textContent = "Not saved: " + err.message;
    status.className = "promo-status err";
  });
}

function reviewTable(rows, status, opts) {
  if (!rows.length) return el("div", "faint", opts.empty);
  var wrap = el("div", "rv-table");
  var t = el("table");
  var hr = t.createTHead().insertRow();
  var heads = ["Demo", "Type", "Published", "Last used", "Views 12 mo",
               "Downloads 12 mo", "People 12 mo"];
  if (opts.until) heads.push("Still current until");
  if (canReviewContent()) heads.push("");
  heads.forEach(function (h, i) {
    hr.appendChild(el("th", i >= 4 && i <= 6 ? "r" : null, h));
  });
  var tb = t.createTBody();
  rows.forEach(function (r) {
    var tr = tb.insertRow();
    var name = tr.insertCell();
    name.appendChild(demoLink(r.asset_id, r.title));
    if (r.internal) name.appendChild(el("span", "pill pill--off rv-tag", "Internal"));
    tr.insertCell().textContent = TYPE_WORD[r.type] || r.type;
    var pub = tr.insertCell();
    pub.className = "num";
    pub.textContent = r.uploaded_at || "—";
    var used = tr.insertCell();
    used.className = "num" + (r.last_used ? "" : " faint");
    used.textContent = r.last_used || "never";
    [r.views_12m, r.downloads_12m, r.people_12m].forEach(function (n) {
      var c = tr.insertCell();
      c.className = "r num" + (n ? "" : " faint");
      c.textContent = n;
    });
    if (opts.until) {
      var u = tr.insertCell();
      u.className = "num";
      u.textContent = r.still_current_until || "—";
    }
    if (canReviewContent()) {
      var act = tr.insertCell();
      act.className = "rv-actions";
      var keep = el("button", "btn-small", opts.until ? "Confirm again" : "Still current");
      keep.type = "button";
      keep.title = "The interface shown still matches today's release (lasts a year)";
      keep.addEventListener("click", function () {
        reviewAction("/api/assets/" + encodeURIComponent(r.asset_id) + "/still-current",
          { still_current: true }, status);
      });
      act.appendChild(keep);
      var arch = el("button", "btn-small", "Archive");
      arch.type = "button";
      arch.hidden = !canArchive();
      arch.title = "Out of the Hub's lists; a SharePoint demo's folder moves into _Archive.";
      arch.addEventListener("click", function () {
        // Asked in place, with an optional reason (window.prompt is
        // suppressed in some browsers, as window.confirm was).
        act.innerHTML = "";
        var reason = el("input", "rv-reason");
        reason.placeholder = "Why (optional)";
        reason.maxLength = 300;
        var yes = el("button", "btn-small btn-danger--solid", "Archive");
        yes.type = "button";
        yes.addEventListener("click", function () {
          reviewAction("/api/assets/" + encodeURIComponent(r.asset_id) + "/archive",
            { archived: true, reason: reason.value }, status);
        });
        var no = el("button", "btn-small", "Cancel");
        no.type = "button";
        no.addEventListener("click", loadReview);
        act.appendChild(reason);
        act.appendChild(yes);
        act.appendChild(no);
        reason.focus();
      });
      act.appendChild(arch);
    }
  });
  wrap.appendChild(t);
  return wrap;
}

function reviewSection(host, title, count, note, body) {
  var c = el("div", "card rv-card");
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, title));
  head.appendChild(el("span", "faint num", String(count)));
  c.appendChild(head);
  if (note) c.appendChild(el("p", "muted rv-note", note));
  c.appendChild(body);
  host.appendChild(c);
}

function renderReview(d) {
  var host = $("rvBody");
  host.innerHTML = "";
  var status = el("div", "promo-status faint");
  var since = d.usage_since ? new Date(d.usage_since).toLocaleDateString() : null;
  var recorded = since ? Math.round((Date.now() - new Date(d.usage_since)) / 86400000) : 0;
  $("rvIntro").textContent = "Usage recorded since " + (since || "—")
    + (recorded < d.idle_days
      ? " (" + recorded + " days): until that reaches " + d.idle_days + " days, "
        + "“little used” means unused since recording began."
      : ".")
    + " Still current lasts " + d.still_current_months + " months.";

  reviewSection(host, "Collecting dust", d.dust.length,
    d.dust_years + " years old or more, and not confirmed Still current. "
    + "Re-record, retire (Archive) or confirm.",
    reviewTable(d.dust, status, { empty: "Nothing collecting dust." }));
  reviewSection(host, "Little used", d.idle.length,
    "Published over " + d.min_age_days + " days ago, not confirmed Still current, "
    + "and nobody opened, previewed or downloaded it in the last " + d.idle_days + " days.",
    reviewTable(d.idle, status, { empty: "Nothing idle." }));
  reviewSection(host, "Still current running out", d.expiring.length,
    "Confirmations ending in the next 30 days, or ended in the last 30. "
    + "Confirm again, or let the age badge come back.",
    reviewTable(d.expiring, status, { until: true, empty: "None running out." }));

  var arch = el("div");
  if (!d.archived.length) {
    arch.appendChild(el("div", "faint", "Nothing archived."));
  } else {
    d.archived.forEach(function (a) {
      var r = el("div", "promo-row");
      r.appendChild(el("span", "promo-row__n", ""));
      var info = el("div");
      info.appendChild(demoLink(a.asset_id, a.title));
      info.appendChild(el("div", "promo-row__meta",
        [TYPE_WORD[a.type] || a.type,
         a.at ? "archived " + new Date(a.at).toLocaleDateString()
           + (a.by ? " by " + a.by.replace(/^(user|dev):/, "") : "") : "moved in SharePoint",
         WHERE[a.where] || "",
         a.reason ? "“" + a.reason + "”" : ""].filter(Boolean).join(" · ")));
      if (a.where === "hub_only") r.classList.add("rv-hub-only");
      r.appendChild(info);
      var acts = el("div", "promo-row__actions");
      if (canArchive()) {
        var restore = el("button", null, "Restore");
        restore.type = "button";
        restore.addEventListener("click", function () {
          reviewAction("/api/assets/" + encodeURIComponent(a.asset_id) + "/archive",
            { archived: false }, status);
        });
        acts.appendChild(restore);
      }
      r.appendChild(acts);
      arch.appendChild(r);
    });
  }
  var hubOnly = d.archived.filter(function (a) { return a.where === "hub_only"; }).length;
  reviewSection(host, "Archived", d.archived.length,
    "Out of every list and search in the Hub. A SharePoint demo archived since 2026-10-28 has "
    + "its folder in the library's _Archive, which only the team can open"
    + (hubOnly ? "; " + hubOnly + " archived before that still have their folder where it was "
       + "(to move by hand: Restore, then Archive)" : "")
    + ". People with “See archived content” can still open them.", arch);
  host.appendChild(status);
  if (!canReviewContent()) {
    host.appendChild(el("p", "faint", "Viewing only: acting on these needs the "
      + "Review content permission."));
  }
}

export {
  loadReview
};
