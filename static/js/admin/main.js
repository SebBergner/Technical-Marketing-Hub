/* The Admin page's script (static/admin.html).
 *
 * Each file in static/js/admin/ is one tab or shared part -- util, overview,
 * usage, home, content, review, access, users, signins -- and imports what
 * it uses from the others; until 2026-10-15 they were one 3,600-line
 * static/admin.js. This file holds the tabs and boots the page: the
 * sign-in watch on fetch, who is signed in, then the Overview.
 */

import { loadOptions } from "./options.js";
import { $, session, show } from "./util.js";
import {
  renderAutoSync, renderEnvironment, renderIntegrations, renderQueues
} from "./overview.js";
import { loadUsage, renderDims, renderRanges } from "./usage.js";
import { loadHubSettings, loadPromoted } from "./home.js";
import { contentState, loadContent } from "./content.js";
import { loadReview } from "./review.js";
import { loadContentAccess, loadHidden } from "./access.js";
import { loadAccess, loadTokens } from "./users.js";
import { loadActivity, renderActRanges } from "./signins.js";

/* ── when the session runs out with the page open ─────────────────────
 *
 * The server's sign-in gate (backend/oidc.py) answers an API call that
 * has no session with 401 and an X-Sign-In header. A page already open
 * would otherwise just stop loading data, with nothing to say why -- so
 * any such answer sends the person to sign in and back to exactly where
 * they were, including the #/asset/... part the server never sees.
 *
 * Keyed on the header, not on 401 alone: the Admin page's own 401 means
 * "the admin password has not been entered", and must keep meaning that.
 */
(function watchForExpiredSession() {
  var original = window.fetch;
  if (!original || original.hubSignInWatch) return;
  var watched = function () {
    return original.apply(this, arguments).then(function (response) {
      var login = response.status === 401 && response.headers.get("X-Sign-In");
      if (login) {
        var here = location.pathname + location.search + location.hash;
        location.assign(login + "?next=" + encodeURIComponent(here));
      }
      return response;
    });
  };
  watched.hubSignInWatch = true;
  window.fetch = watched;
})();

/* Overview | Content dashboard | Users & groups. The tab is in the
 * address (#content, #access), so a refresh or a shared link opens the
 * same one. */
var PANELS = { overview: "tabOverview", home: "tabHome", content: "tabContent",
               review: "tabReview", internal: "tabInternal", options: "tabOptions",
               usage: "tabUsage", access: "tabAccess", activity: "tabActivity" };

function tabFromHash() {
  var name = location.hash.replace("#", "");
  return PANELS[name] ? name : "overview";
}

function showTab(name) {
  if (!PANELS[name]) name = "overview";
  Object.keys(PANELS).forEach(function (k) { $(PANELS[k]).hidden = k !== name; });
  document.querySelectorAll("#adminTabs .tab").forEach(function (t) {
    var on = t.dataset.tab === name;
    t.classList.toggle("tab--on", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (name === "content" && !contentState.loaded) loadContent();
  if (name === "access") { loadAccess(); loadTokens(); }
  if (name === "internal") loadContentAccess();
  if (name === "review") loadReview();
  if (name === "activity") { renderActRanges(); loadActivity(); }
  if (name === "usage") loadUsage();
  if (name === "options" && !optionsShown) { optionsShown = true; loadOptions(false); }
}

var optionsShown = false;          // read once per page load; Refresh re-reads
$("optRefresh").addEventListener("click", function () { loadOptions(true); });

document.querySelectorAll("#adminTabs .tab").forEach(function (t) {
  t.addEventListener("click", function () {
    history.replaceState(null, "", t.dataset.tab === "overview" ? "#" : "#" + t.dataset.tab);
    showTab(t.dataset.tab);
  });
});

function load() {
  return fetch("/api/admin/overview", { headers: { "Accept": "application/json" } })
    .then(function (r) {
      if (r.status === 401) { show("loginView"); return null; }
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (d) {
      if (!d) return;
      renderEnvironment(d.environment);
      renderIntegrations(d.integrations);
      renderAutoSync(d.auto_sync);
      loadPromoted();
      loadHubSettings();
      loadHidden();
      contentState.loaded = false;
      showTab(tabFromHash());
      renderQueues(d);
      renderRanges();
      renderDims();
      $("loadedAt").textContent = "Loaded " + new Date().toLocaleString();
      show("dashView");
    })
    .catch(function (err) {
      console.error("[admin]", err);
      window.alert("Could not load the overview: " + err.message);
    });
}

function boot() {
  fetch("/api/admin/session").then(function (r) { return r.json(); })
    .then(function (s) {
      Object.assign(session, s);
      if (!s.signed_in) { show(s.configured ? "loginView" : "offView"); return; }
      load();
    });
}

$("loginForm").addEventListener("submit", function (e) {
  e.preventDefault();
  $("loginErr").textContent = "";
  fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: $("u").value, password: $("p").value }),
  }).then(function (r) {
    if (r.ok) { $("p").value = ""; boot(); return; }
    // One message for both halves -- see the endpoint's own docstring.
    $("loginErr").textContent = r.status === 503
      ? "No admin is configured on this deployment."
      : "That username and password did not match.";
  });
});

$("logoutBtn").addEventListener("click", function () {
  // A signed-in person leaves the Hub session itself; the shared password
  // only drops its own cookie.
  if (session.via === "sso") { location.assign("/logout"); return; }
  fetch("/api/admin/logout", { method: "POST" }).then(function () {
    show("loginView");
  });
});

$("refreshBtn").addEventListener("click", load);

$("sheetClose").addEventListener("click", function () {
  $("overlay").hidden = true;
});
$("overlay").addEventListener("click", function (e) {
  // Only the backdrop closes it: a click inside the sheet is someone
  // reading, not someone leaving.
  if (e.target === $("overlay")) $("overlay").hidden = true;
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") $("overlay").hidden = true;
});

boot();

export {
  load, showTab
};
