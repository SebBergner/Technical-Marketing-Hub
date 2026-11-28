/* The Hub page's script: fills index.html from the live API.
 *
 * Loaded by index.html as a module, the page's only script of its own
 * (static/js/hub-ui.js, the classic script before it, was folded into
 * actions.js and inquiry.js on 2026-11-28). Each file in static/js/hub/ is
 * one part of the page -- util, permissions, cards, filters, home, nav,
 * detail, vm, activity, search, request, share, review, report -- and
 * imports what it uses from the others; until 2026-10-14 they were one
 * 6,000-line static/hub-api.js. Helpers every page shares are in
 * static/js/shared/.
 *
 * This file boots the page: the page's own controls (actions.js), the
 * sign-in watch on fetch, the person's permissions, then load(), which
 * fetches the catalogue, builds Home and wires every view.
 */

import { fetchJSON, watchForExpiredSession } from "../shared/http.js";
import { applyPermissions } from "./permissions.js";
import {
  enhanceSearchableSelect, fillPublished, fillSelect, fillSidebarCounts,
  HIDDEN_SEGMENTS, restoreFiltersFromUrl, takeOverControls, wireFilterBar
} from "./filters.js";
import { buildHome } from "./home.js";
import {
  buildFamilyNav, buildSidebarFoot, familyDisplayName, HIDDEN_UMBRELLAS,
  markNavActive, markUnavailable, wireNav
} from "./nav.js";
import { wireDetailPage } from "./detail.js";
import { wireAdvancedSearch } from "./search.js";
import { fillProductPills, wireRequestForm } from "./request.js";
import { wirePageActions } from "./actions.js";
import { wireShareModal } from "./share.js";
import { addUploadNav } from "./upload.js";
import { addHelpNav } from "./report.js";
import { addMyHubNav } from "./me.js";
import { addGuideButton } from "./guide.js";
import { askDisclaimerIfDue } from "./disclaimer.js";
import { askWelcomeIfDue } from "./welcome.js";
import { wireFeatureUsage } from "./features.js";

/* When the session runs out with the page open: off to sign in and back
 * to exactly here (static/js/shared/http.js). */
watchForExpiredSession();

// Every data-action control and the phone sidebar, before anything loads:
// the markup is already on screen.
wirePageActions();

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

/* The first page says how many there are; the rest are asked for at once
 * (2026-11-04: one after another they took ~2.5 s of a first load, and the
 * thumbnails waited for them). Kept in order, so the pool is the same. */
async function fetchAllAssets() {
  function page(n) {
    return fetchJSON("/api/assets?limit=" + PAGE_SIZE + "&offset=" + (n * PAGE_SIZE));
  }
  var first = await page(0);
  var all = first.items || [];
  var pages = Math.min(Math.ceil((first.total || 0) / PAGE_SIZE), MAX_PAGES);
  if (Math.ceil((first.total || 0) / PAGE_SIZE) > MAX_PAGES) {
    console.warn("[hub-api] stopped at the page guard with more to fetch");
  }
  var rest = [];
  for (var n = 1; n < pages; n++) rest.push(page(n));
  (await Promise.all(rest)).forEach(function (body) {
    all = all.concat(body.items || []);
  });
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
    var both = await Promise.all([fetchAllAssets(), fetchJSON("/api/taxonomy")]);
    assets = both[0];
    facets = both[1];
  } catch (err) {
    console.error("[hub-api] could not load the catalogue", err);
    bootFailed("The catalogue could not be loaded: " + err.message);
    return;
  }

  if (!assets.length) {
    bootFailed("The catalogue is empty. Run a sync to fill it.");
    return;
  }

  // No window.HUB_ASSET_POOL any more (2026-11-26): ~950 cards, each
  // thumbnail registered with the lazy-load observer, built at boot for a
  // pool nothing has read since the page's old script stopped filtering.
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
  wireAdvancedSearch();
  wireDetailPage();
  wireFeatureUsage();
  fillProductPills(facets);
  await buildFamilyNav(facets);
  wireNav(facets);
  markUnavailable(facets);
  markNavActive();
  buildSidebarFoot();
  addUploadNav();
  addHelpNav();
  addMyHubNav();
  addGuideButton();
  // A shared link's filters (/?family=Creo&type=video): last, once every
  // control has its options.
  restoreFiltersFromUrl();

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
// At once, beside the catalogue load: nothing waits for it, it waits for nothing.
// The welcome (first visit, or after a big update) follows the disclaimer.
askDisclaimerIfDue().then(askWelcomeIfDue);

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", load);
} else {
  load();
}
