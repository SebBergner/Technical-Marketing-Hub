/* The Hub page's script: fills index.html from the live API.
 *
 * Loaded by index.html as a module, after static/js/hub-ui.js (the page's
 * own controls: request form, modals, the data-action dispatcher). Each file
 * in static/js/hub/ is one part of the page -- util, permissions, cards,
 * filters, home, nav, detail, vm, activity, search, request, share -- and
 * imports what it uses from the others; until 2026-10-14 they were one
 * 6,000-line static/hub-api.js.
 *
 * This file boots the page: the sign-in watch on fetch, the person's
 * permissions, then load(), which fetches the catalogue, builds the cards
 * (window.HUB_ASSET_POOL, which hub-ui.js reads) and wires every view.
 */

import { getJSON } from "./util.js";
import { applyPermissions } from "./permissions.js";
import { buildCard } from "./cards.js";
import {
  enhanceSearchableSelect, fillPublished, fillSelect, fillSidebarCounts,
  HIDDEN_SEGMENTS, takeOverControls, wireFilterBar
} from "./filters.js";
import { buildHome } from "./home.js";
import {
  buildFamilyNav, buildSidebarFoot, familyDisplayName, HIDDEN_UMBRELLAS,
  markNavActive, markUnavailable, wireNav
} from "./nav.js";
import { wireDetailPage } from "./detail.js";
import { wireAdvancedSearch } from "./search.js";
import {
  fillProductPills, wireRequestForm, wireScopeState
} from "./request.js";
import { wireShareModal } from "./share.js";

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

/* The API caps `limit` at 200 -- a deliberate guard rail, so page through it
 * rather than asking for more. Asking for 1000 returns a 422 that looks like
 * an empty catalogue if you only check for items. */
var PAGE_SIZE = 200;
var MAX_PAGES = 20;           // 4,000 assets; the catalogue is ~950

function bootFailed(message) {
  var boot = document.getElementById("hubBoot");
  var text = document.getElementById("hubBootMessage");
  if (boot) boot.classList.add("hub-boot--failed");
  if (text) text.textContent = message;
  console.error("[hub-api] boot failed:", message);
}

/* ------------------------------------------------------------------ boot */

async function fetchAllAssets() {
  var all = [];
  for (var page = 0; page < MAX_PAGES; page++) {
    var body = await getJSON("/api/assets?limit=" + PAGE_SIZE
                           + "&offset=" + (page * PAGE_SIZE));
    var items = body.items || [];
    all = all.concat(items);
    if (all.length >= (body.total || 0) || !items.length) return all;
  }
  console.warn("[hub-api] stopped at the page guard with more to fetch");
  return all;
}

function showTotal(count) {
  var title = document.querySelector("#mainTopbar .orion-title");
  if (!title) return;
  var el = document.getElementById("hubTotal");
  if (!el) {
    el = document.createElement("span");
    el.id = "hubTotal";
    el.className = "hub-total";
    title.appendChild(el);
  }
  el.textContent = count.toLocaleString("en-US") + " assets";
}

async function load() {
  var assets, facets;
  try {
    assets = await fetchAllAssets();
    facets = await getJSON("/api/taxonomy");
  } catch (err) {
    console.error("[hub-api] could not load the catalogue", err);
    bootFailed("The catalogue could not be loaded: " + err.message);
    return;
  }

  if (!assets.length) {
    bootFailed("The catalogue is empty. Run a sync to fill it.");
    return;
  }

  // Setting this is the whole integration: hubApplyFilters() builds from the
  // hardcoded cards only when it is still unset.
  // hubApplyFilters() has already run once on load and filled the pool from
  // the hardcoded cards, so this replaces rather than pre-empts it.
  window.HUB_ASSET_POOL = assets.map(buildCard);
  buildHome(assets, facets);

  fillSelect("hubFilterProduct", (facets.product_families || facets.products || [])
    .filter(function (f) { return HIDDEN_UMBRELLAS.indexOf(f.value) === -1; }),
    familyDisplayName);
  fillSelect("hubFilterSegment", (facets.segments || []).filter(function (f) {
    return HIDDEN_SEGMENTS.indexOf(f.value) === -1;
  }));
  fillSelect("hubFilterStage", facets.funnel_stages);
  fillSelect("hubFilterVideoType", facets.content_depths);
  fillSelect("hubFilterLanguage", facets.languages);
  fillPublished(facets.published);
  fillSelect("hubFilterType", facets.types);
  fillSidebarCounts(facets);
  takeOverControls();
  // After takeOverControls, which swaps each control for a fresh clone.
  enhanceSearchableSelect("hubFilterProduct", "Search products…", "No product matches");
  wireFilterBar();
  wireShareModal();
  wireRequestForm();
  wireScopeState();
  wireAdvancedSearch();
  wireDetailPage();
  fillProductPills(facets);
  await buildFamilyNav(facets);
  wireNav(facets);
  markUnavailable(facets);
  markNavActive();
  buildSidebarFoot();

  // Real content is in place: reveal the thread. See the #mainThread rule in
  // index.html for why it also reveals itself on a timer.
  document.body.classList.add("hub-ready");

  var bySource = assets.reduce(function (acc, a) {
    acc[a.source] = (acc[a.source] || 0) + 1;
    return acc;
  }, {});
  /* The total, beside the page title; nothing floating in the corner and no
   * split by source (Liwei, 2026-09-30). The corner box stays for errors
   * only (report(..., true)). */
  showTotal(assets.length);
  console.info("[hub-api] loaded", assets.length, "assets", bySource);
}

applyPermissions();

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", load);
} else {
  load();
}
