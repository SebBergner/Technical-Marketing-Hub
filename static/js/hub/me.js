/* My Hub (#/me; A3, Liwei 2026-11-12): each person's own starting point.
 *
 * One page, top to bottom, as a library page in a media app is: what you
 * viewed lately and what you starred, as cards; then what you asked for --
 * New Asset Inquiries with the status the team gives them, your feedback --
 * and, for people who create demos, what you created. Playlists come next
 * (phase 2), between Favorites and the lists.
 *
 * Everything is the signed-in person's own (GET /api/me...). My feedback
 * and My demos are drawn by report.js and upload.js, which own them.
 *
 * Part of the Hub page's script. */

import { buildCard } from "./cards.js";
import { hubPermissions } from "./permissions.js";
import { renderMyFeedback } from "./report.js";
import { renderMyDemos } from "./upload.js";
import { closeAdvancedSearch } from "./search.js";

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

/* The request statuses, in the order a request moves (the Status column's
 * choices), with the words a requester reads beside each. */
var STEPS = ["New", "Triaged", "Scoped", "In production", "Delivered"];
var STATUS_NOTE = {
  "New": "Received; the team has not looked at it yet.",
  "Triaged": "The team has looked at it and is deciding what it needs.",
  "Scoped": "Agreed what will be made.",
  "In production": "Being made.",
  "Delivered": "Done.",
  "Declined": "The team will not make this one.",
  "Not sent yet": "Saved, but it has not reached the team's list yet; it will be sent again."
};

function section(id, title, sub) {
  var s = el("section", "hub-me__section");
  s.id = id;
  var head = el("div", "hub-me__head");
  head.appendChild(el("h2", "hub-me__h", title));
  if (sub) head.appendChild(el("span", "hub-me__sub", sub));
  s.appendChild(head);
  var body = el("div", "hub-me__body");
  s.appendChild(body);
  return s;
}

function buildPage() {
  var page = document.getElementById("hubMePage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubMePage";
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to Technical Marketing Hub</button>'
    + '<div class="vp-head"><div>'
    +   '<div class="vp-title">My Hub</div>'
    +   '<div class="orion-subtle">What you viewed, starred and asked for. Only you see this page.</div>'
    + '</div></div>'
    + '<div class="hub-me"></div>';
  var host = page.querySelector(".hub-me");
  host.appendChild(section("meRecent", "Recently viewed"));
  host.appendChild(section("meFavorites", "Favorites", "Star a demo on its card or page"));
  host.appendChild(section("meRequests", "My requests", "New Asset Inquiries"));
  host.appendChild(section("meFeedback", "My feedback"));
  host.appendChild(section("meDemos", "My demos", "Demos you created in the Hub"));
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeMyHub();
  });
  // A star taken off on this page takes the card away at once.
  document.addEventListener("hub:favorites", function () {
    if (page.classList.contains("active")) loadCards();
  });
  return page;
}

function cardRow(host, items, empty) {
  host.innerHTML = "";
  if (!items.length) {
    host.appendChild(el("div", "hub-me__empty", empty));
    return;
  }
  var row = el("div", "asset-row hub-me__row");
  items.forEach(function (a) {
    var card = buildCard(a);
    card.addEventListener("click", function () { window.hubDetailReturn = "#/me"; }, true);
    row.appendChild(card);
  });
  host.appendChild(row);
}

function loadCards() {
  return fetch("/api/me").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) {
    cardRow(document.querySelector("#meRecent .hub-me__body"), d.recent,
      "Nothing yet: the demos you open will be listed here, newest first.");
    cardRow(document.querySelector("#meFavorites .hub-me__body"), d.favorites,
      "No favorites yet. Star a demo on its card or its page to keep it here.");
    document.getElementById("meRequests").hidden = !d.sections.requests;
    document.getElementById("meDemos").hidden = !d.sections.demos;
    return d;
  }).catch(function (err) {
    document.querySelector("#meRecent .hub-me__body").textContent =
      "Could not load My Hub: " + err.message;
  });
}

/* A request's progress: the steps so far, the current one named. */
function progress(status) {
  var wrap = el("div", "hub-me__steps");
  var at = STEPS.indexOf(status);
  if (status === "Declined" || status === "Not sent yet" || at < 0) {
    wrap.appendChild(el("span", "hub-me__status hub-me__status--"
      + (status === "Declined" ? "closed" : "waiting"), status));
    return wrap;
  }
  STEPS.forEach(function (s, i) {
    var dot = el("span", "hub-me__step" + (i < at ? " hub-me__step--done"
      : i === at ? " hub-me__step--now" : ""));
    dot.title = s;
    wrap.appendChild(dot);
  });
  wrap.appendChild(el("span", "hub-me__status hub-me__status--"
    + (status === "Delivered" ? "done" : "open"), status));
  return wrap;
}

function delivered(value) {
  var v = (value || "").trim();
  if (!v) return null;
  var box = el("div", "hub-me__delivered");
  box.appendChild(document.createTextNode("Delivered: "));
  if (/^https?:\/\//i.test(v)) {
    var a = el("a", null, "Open it");
    a.href = v;
    if (!/\/\/[^/]*tmh\.ptcxc\.com\//i.test(v) && v.indexOf(location.origin) !== 0) {
      a.target = "_blank";
      a.rel = "noopener";
    }
    box.appendChild(a);
  } else {
    box.appendChild(document.createTextNode(v));
  }
  return box;
}

function loadRequests() {
  var host = document.querySelector("#meRequests .hub-me__body");
  if (document.getElementById("meRequests").hidden) return;
  if (!host.childNodes.length) host.textContent = "Loading…";
  fetch("/api/me/requests").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) {
    host.innerHTML = "";
    if (!d.readable) {
      host.appendChild(el("div", "hub-me__note",
        "The team's list could not be read just now, so statuses may be missing."));
    }
    if (!d.items.length) {
      var none = el("div", "hub-me__empty");
      none.appendChild(document.createTextNode("No requests yet. Ask for a demo that is not "
        + "in the Hub with "));
      var a = el("a", null, "New Asset Inquiry");
      a.href = "#/request";
      none.appendChild(a);
      none.appendChild(document.createTextNode("."));
      host.appendChild(none);
      return;
    }
    var list = el("div", "hub-me__requests");
    d.items.forEach(function (r) {
      var row = el("div", "hub-me__req");
      var info = el("div", "hub-me__reqinfo");
      var what = [r.asset_type, r.products].filter(Boolean).join(" · ");
      info.appendChild(el("div", "hub-me__reqtitle", what || r.title || r.request_id));
      if (r.brief) info.appendChild(el("div", "hub-me__reqbrief", r.brief));
      info.appendChild(el("div", "hub-me__reqmeta", [r.request_id,
        r.created_at ? "sent " + new Date(r.created_at).toLocaleDateString(undefined,
          { month: "short", day: "numeric", year: "numeric" }) : null]
        .filter(Boolean).join(" · ")));
      var d2 = delivered(r.delivered);
      if (d2) info.appendChild(d2);
      row.appendChild(info);
      var side = el("div", "hub-me__reqside");
      side.appendChild(progress(r.status));
      side.appendChild(el("div", "hub-me__reqnote", STATUS_NOTE[r.status] || ""));
      row.appendChild(side);
      list.appendChild(row);
    });
    host.appendChild(list);
    host.appendChild(el("div", "hub-me__note", "The team sets the status in their list; a "
      + "change can take two minutes to show here."));
  }).catch(function (err) {
    host.textContent = "Could not load your requests: " + err.message;
  });
}

function openMyHub() {
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
  window.scrollTo(0, 0);
  loadCards().then(function () {
    loadRequests();
    if (!document.getElementById("meDemos").hidden) {
      renderMyDemos(document.querySelector("#meDemos .hub-me__body"), false);
    }
  });
  renderMyFeedback(document.querySelector("#meFeedback .hub-me__body"));
}

function closeMyHub() {
  var page = document.getElementById("hubMePage");
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

/* ── the sidebar item: first, above Home ──────────────────────────────── */
function addMyHubNav() {
  hubPermissions.then(function (granted) {
    if (granted.indexOf("view_hub") < 0 || document.getElementById("navMyHub")) return;
    var home = document.getElementById("navHome");
    if (!home) return;
    var item = el("div", "orion-navitem");
    item.id = "navMyHub";
    item.innerHTML = '<span class="label"><svg class="orion-ico orion-ico--sm">'
      + '<use href="#i-star"/></svg> My Hub</span>';
    item.addEventListener("click", function () { location.hash = "#/me"; });
    home.parentNode.insertBefore(item, home);
    if (location.hash === "#/me") markNav(true);
  });
}

function markNav(on) {
  var item = document.getElementById("navMyHub");
  if (!item) return;
  item.classList.toggle("orion-navitem--active", on);
  if (on) document.querySelectorAll(".orion-navitem--active, .orion-navitem.is-active")
    .forEach(function (n) {
      if (n !== item) n.classList.remove("orion-navitem--active", "is-active");
    });
}

export { addMyHubNav, closeMyHub, openMyHub };
