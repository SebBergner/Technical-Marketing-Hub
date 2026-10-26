/* Home: the landing page's rails and slices.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { escapeHtml, fullDate, getJSON } from "./util.js";
import { buildCard, paintCoverInto, TYPE_CHIP, videoTypeOf } from "./cards.js";
import { applyFilters, CONTROLS, navFilter } from "./filters.js";
import {
  familyDisplayName, HIDDEN_UMBRELLAS, navMarkHtml, openFamily,
  umbrellaDisplayName
} from "./nav.js";

/* ── Home (Liwei, 2026-10-01: option A of the Home discussion) ────────
 *
 * Search is the main job, so the page under the search bar only does what
 * the sidebar and the filters cannot:
 *
 *   What's in the Hub      the catalogue by type, each a way in
 *   Featured               chosen on the Admin page (Seb's "promote"),
 *                          in that order; absent when nothing is promoted
 *   Start from a product   the same products as the sidebar, with what
 *                          each holds
 *   Recently published     every type (Liwei, 2026-10-01). A video's
 *                          date is when it was published; a SharePoint
 *                          kit's is its folder's last edit (381 kits read
 *                          2024-05 from one bulk edit, measured
 *                          2026-10-01), so a kit's row says "updated"
 *                          rather than passing an edit off as new.
 *
 * Built here, replacing Elio's rails; shown only while nothing is
 * searched or filtered (LANDING). */
var HOME_RECENT = 6;
var HOME_TYPE_ORDER = ["video", "ldk", "vdk", "cad_model", "vm"];
var HOME_TYPE_WORD = { video: ["video", "videos"], ldk: ["LDK", "LDKs"],
                       vdk: ["VDK", "VDKs"], cad_model: ["CAD dataset", "CAD datasets"],
                       vm: ["virtual machine", "virtual machines"] };

function homeSection(id, icon, title, sub) {
  var section = document.createElement("div");
  section.className = "section";
  section.id = id;
  section.innerHTML =
      '<div class="section-head"><div class="section-head__title">'
    +   '<svg class="orion-ico ico-green"><use href="#' + icon + '"/></svg> '
    +   escapeHtml(title)
    +   (sub ? ' <span class="section-head__sub">' + escapeHtml(sub) + '</span>' : '')
    + '</div></div>';
  return section;
}

/* "today", "3 days ago", "2 weeks ago"; past a month, the date itself. */
function whenLabel(iso) {
  var then = new Date(String(iso).slice(0, 10) + "T00:00:00");
  var days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (isNaN(days)) return "";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return days + " days ago";
  if (days < 31) return Math.floor(days / 7) + " weeks ago";
  return fullDate(iso);
}

/* Go to a filtered view of the catalogue from Home. */
function homeGo(set) {
  CONTROLS.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.value = "";
  });
  navFilter.umbrella = null;
  navFilter.tag = null;
  navFilter.sort = null;
  navFilter.order = null;
  set();
  applyFilters();
  var thread = document.getElementById("mainThread");
  if (thread) thread.scrollTop = 0;
}

function buildHome(assets, facets) {
  var thread = document.getElementById("mainThread");
  if (!thread || document.getElementById("hubHome")) return;
  var home = document.createElement("div");
  home.id = "hubHome";
  thread.appendChild(home);

  // What's in the Hub
  var counts = {};
  (facets.types || []).forEach(function (t) { counts[t.value] = t.count; });
  var typesSection = homeSection("hubHomeTypes", "i-layers", "What's in the Hub");
  var types = document.createElement("div");
  types.className = "hub-home-types";
  HOME_TYPE_ORDER.forEach(function (t) {
    var n = counts[t];
    if (!n) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "hub-home-type";
    b.innerHTML = "<b>" + n.toLocaleString() + "</b>" + escapeHtml(HOME_TYPE_WORD[t][n === 1 ? 0 : 1]);
    b.addEventListener("click", function () {
      homeGo(function () { document.getElementById("hubFilterType").value = t; });
    });
    types.appendChild(b);
  });
  typesSection.appendChild(types);
  home.appendChild(typesSection);

  // Featured -- filled when the promoted list arrives; absent if empty.
  var featured = homeSection("hubHomeFeatured", "i-star", "Featured",
                             "picked by the Technical Marketing team");
  featured.style.display = "none";
  var grid = document.createElement("div");
  grid.className = "asset-grid";
  featured.appendChild(grid);
  home.appendChild(featured);
  getJSON("/api/assets/promoted").then(function (items) {
    if (!items.length) return;
    items.forEach(function (a) { grid.appendChild(buildCard(a)); });
    featured.style.display = "";
  }).catch(function (err) {
    console.warn("[hub-api] promoted demos not loaded", err);
  });

  // Start from a product
  var byUmbrella = {};
  assets.forEach(function (a) {
    (a.umbrella_families || []).forEach(function (u) {
      var c = byUmbrella[u] || (byUmbrella[u] = { videos: 0, kits: 0 });
      if (a.type === "video") c.videos += 1;
      else if (a.type === "ldk" || a.type === "vdk") c.kits += 1;
    });
  });
  var productsSection = homeSection("hubHomeProducts", "i-box", "Start from a product");
  var tiles = document.createElement("div");
  tiles.className = "hub-home-products";
  (facets.umbrella_families || []).forEach(function (f) {
    if (HIDDEN_UMBRELLAS.indexOf(f.value) !== -1 || !f.count) return;
    var c = byUmbrella[f.value] || { videos: 0, kits: 0 };
    var split = [c.videos && (c.videos + (c.videos === 1 ? " video" : " videos")),
                 c.kits && (c.kits + (c.kits === 1 ? " kit" : " kits"))]
      .filter(Boolean).join(" · ");
    var b = document.createElement("button");
    b.type = "button";
    b.className = "hub-home-product";
    b.innerHTML = navMarkHtml(f.value)
      + '<span><span class="hub-home-product__name">' + escapeHtml(umbrellaDisplayName(f.value))
      + '</span><br><span class="hub-home-product__meta">'
      + f.count + (f.count === 1 ? " demo" : " demos") + (split ? " · " + split : "")
      + "</span></span>";
    b.addEventListener("click", function () { openFamily(f.value); });
    tiles.appendChild(b);
  });
  productsSection.appendChild(tiles);
  home.appendChild(productsSection);

  // Recently published videos
  var recent = assets.filter(function (a) { return a.uploaded_at; })
    .sort(function (a, b) { return String(b.uploaded_at).localeCompare(String(a.uploaded_at)); })
    .slice(0, HOME_RECENT);
  if (recent.length) {
    var recentSection = homeSection("hubHomeRecent", "i-clock", "Recently published demos",
                                    "videos by publish date · kits by last update");
    var list = document.createElement("div");
    list.className = "hub-home-recent";
    recent.forEach(function (a) {
      var row = document.createElement("a");
      row.className = "hub-home-recent__row";
      row.href = "#/asset/" + encodeURIComponent(a.id);
      var thumb = document.createElement("span");
      thumb.className = "hub-home-recent__thumb";
      if (a.thumbnail_url) thumb.style.backgroundImage = "url(" + JSON.stringify(a.thumbnail_url) + ")";
      paintCoverInto(thumb, a);
      row.appendChild(thumb);
      var text = document.createElement("span");
      text.className = "hub-home-recent__text";
      text.innerHTML = '<div class="hub-home-recent__title">' + escapeHtml(a.title) + '</div>'
        + '<div class="hub-home-recent__meta">'
        + escapeHtml([(TYPE_CHIP[a.type] || [])[1], videoTypeOf(a),
                      (a.product_families || []).map(familyDisplayName).join(", ")]
                       .filter(Boolean).join(" · "))
        + '</div>';
      row.appendChild(text);
      var when = document.createElement("span");
      when.className = "hub-home-recent__when";
      var dated = a.date_stated ? "Published " : "Updated ";
      when.textContent = (a.date_stated ? "" : "updated ") + whenLabel(a.uploaded_at);
      when.title = dated + fullDate(a.uploaded_at);
      row.appendChild(when);
      list.appendChild(row);
    });
    recentSection.appendChild(list);
    var more = document.createElement("button");
    more.type = "button";
    more.className = "hub-home-more";
    more.style.marginTop = "10px";
    more.textContent = "Everything, newest first →";
    more.addEventListener("click", function () {
      homeGo(function () { navFilter.sort = "recent"; });
    });
    recentSection.appendChild(more);
    home.appendChild(recentSection);
  }
}

export {
  buildHome
};
