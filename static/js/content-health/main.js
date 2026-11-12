/* The Content health page's script (static/content-health.html; Liwei,
 * 2026-11-11): the content tools, out of the Admin page, for the people
 * with Maintain content. Four tabs -- Health check, Content review,
 * Content access, Searches -- each its own file here; the small helpers
 * (util.js) and the Admin log table (logtable.js) are shared with Admin.
 * The tab is in the address (#review, #access, #searches). */

import { $, session } from "../admin/util.js";
import { loadChecks } from "./checks.js";
import { loadReview } from "./review.js";
import { loadContentAccess } from "./access.js";
import { loadSearches } from "./searches.js";

/* A session that runs out with the page open: off to sign in and back here,
 * as on the Hub and Admin pages (the server's 401 carries X-Sign-In). */
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

var PANELS = { checks: "tabChecks", review: "tabReview", access: "tabAccess",
               searches: "tabSearches" };
var LOAD = { checks: loadChecks, review: loadReview, access: loadContentAccess,
             searches: loadSearches };

function tabFromHash() {
  var name = location.hash.replace("#", "");
  return PANELS[name] ? name : "checks";
}

function showTab(name) {
  Object.keys(PANELS).forEach(function (k) { $(PANELS[k]).hidden = k !== name; });
  document.querySelectorAll("#chTabs .tab").forEach(function (t) {
    var on = t.dataset.tab === name;
    t.classList.toggle("tab--on", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
    if (on) $("pageTitle").textContent = t.textContent.trim();
  });
  LOAD[name]();
}

document.querySelectorAll("#chTabs .tab").forEach(function (t) {
  t.addEventListener("click", function () {
    history.replaceState(null, "", t.dataset.tab === "checks" ? "#" : "#" + t.dataset.tab);
    showTab(t.dataset.tab);
  });
});

window.addEventListener("hashchange", function () { showTab(tabFromHash()); });

$("refreshBtn").addEventListener("click", function () {
  showTab(tabFromHash());
  $("loadedAt").textContent = "Loaded " + new Date().toLocaleString();
});

fetch("/api/auth/me").then(function (r) { return r.ok ? r.json() : null; })
  .then(function (me) {
    var user = (me && me.user) || {};
    session.permissions = user.permissions || [];
    session.name = user.name || null;
    session.email = user.email || null;
    session.via = "sso";
    if (session.permissions.indexOf("maintain_content") < 0) {
      $("offView").hidden = false;
      return;
    }
    $("adminLink").hidden = session.permissions.indexOf("view_admin") < 0;
    $("dashView").hidden = false;
    $("loadedAt").textContent = "Loaded " + new Date().toLocaleString();
    showTab(tabFromHash());
  });
