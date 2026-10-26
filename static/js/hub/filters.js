/* Searching and filtering the catalogue: the filter controls and their
 * searchable dropdown, the API query, Published and Sort, Load more,
 * the active-filter chips, and the sidebar counts.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { debounce, escapeHtml, getJSON, pill, report } from "./util.js";
import { hubPermissions } from "./permissions.js";
import { buildCard } from "./cards.js";
import { exportCsv, rememberView, renderRows, tableView } from "./table.js";
import {
  markNavActive, NAV_TYPE, NO_COUNT_GROUPS, renderSegmentHeader,
  umbrellaDisplayName
} from "./nav.js";
import { renderSuggestions } from "./search.js";

/* ------------------------------------------------------------- filters UI */

/* Segments the filter does not offer.
 *
 * IoT held 78 assets until the divested products left the catalogue on
 * 2026-09-02; it now holds 1. An option that narrows 807 results to one is a
 * dead end rather than a filter.
 *
 * This hides the control, not the content: the asset is still searchable,
 * still counted in the facet, and still has a segment page. If the answer is
 * that it should not be in the Hub at all, the fix belongs in
 * backend/services/taxonomy.py, where one change reaches search, filters,
 * pages and counts together. */
//: The divested lines' segments (taxonomy.RETIRED_SEGMENTS): IoT, AR.
var HIDDEN_SEGMENTS = ["IoT", "AR"];

/* Fill a <select> from a facet, keeping whatever "all" option is already
 * there as the first entry. Counts come along because "Creo (319)" tells you
 * whether a filter is worth clicking. */
function fillSelect(id, facet, displayName) {
  var el = document.getElementById(id);
  if (!el || !facet || !facet.length) return;
  displayName = displayName || function (v) { return v; };

  // Keep the labels already in the markup. Our facet values are storage
  // keys -- "video", "vdk" -- and rebuilding from them turned Elio's
  // "Video / LDK / VDK" into lower case. The data decides which options
  // exist and what they count; the markup still decides what they are
  // called, and an unlabelled value falls back to itself.
  var labels = {};
  Array.prototype.forEach.call(el.options, function (o) {
    if (o.value) labels[o.value] = o.textContent.replace(/\s*\(\d+\)\s*$/, "");
  });

  var keep = el.options.length ? el.options[0] : null;
  el.innerHTML = "";
  if (keep) el.appendChild(keep);
  facet.slice().sort(function (a, b) { return b.count - a.count; })
    .forEach(function (f) {
      var o = document.createElement("option");
      o.value = f.value;
      // A rename in our display maps wins over the markup's label, so a
      // product name is changed in one place (IPE: Elio's markup still
      // says "PTC Ignite"; the name is "PTC Ignition", 2026-10-06).
      var renamed = displayName(f.value);
      var label = renamed !== f.value ? renamed : (labels[f.value] || f.value);
      o.textContent = label + " (" + f.count + ")";
      el.appendChild(o);
    });
}

/* ------------------------------------------------- a searchable dropdown
 *
 * Liwei, 2026-09-29: the Product dropdown has grown too long to scan, so it
 * gets a search box, and products counting (0) are left out of the list.
 *
 * The native <select> stays the one source of truth. It is only hidden:
 * applyFilters, clearAll, the left nav and rescoreSelect all keep reading
 * and writing it, exactly as before, and this is a view over it. Elio's
 * markup is untouched (his file is integrated non-invasively). A value set
 * from code fires no event, so the select's own `value` / `selectedIndex`
 * are wrapped to refresh the label, and a MutationObserver catches the
 * option texts rescoreSelect rewrites.
 *
 * The left nav's product shortcuts are unchanged: they are the main
 * products on purpose.
 */
function enhanceSearchableSelect(id, placeholder, noneText) {
  var sel = document.getElementById(id);
  if (!sel || sel.dataset.hubCombo) return;
  sel.dataset.hubCombo = "1";
  var pill = sel.parentNode;
  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "hub-combo__btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  sel.style.display = "none";
  sel.parentNode.insertBefore(btn, sel.nextSibling);

  var pop = document.createElement("div");
  pop.className = "hub-combo__pop";
  pop.hidden = true;
  var input = document.createElement("input");
  input.type = "search";
  input.className = "hub-combo__search";
  input.placeholder = placeholder;
  input.setAttribute("aria-label", placeholder);
  var list = document.createElement("ul");
  list.className = "hub-combo__list";
  list.setAttribute("role", "listbox");
  pop.appendChild(input);
  pop.appendChild(list);
  pill.appendChild(pop);

  var shown = [], active = -1;

  function label() { var o = sel.options[sel.selectedIndex]; btn.textContent = o ? o.textContent : ""; }
  function count(o) { var m = /\((\d+)\)\s*$/.exec(o.textContent); return m ? +m[1] : null; }

  function setActive(k) {
    shown.forEach(function (li, n) { li.classList.toggle("is-active", n === k); });
    active = k;
    if (shown[k]) shown[k].scrollIntoView({ block: "nearest" });
  }

  function render() {
    var q = input.value.trim().toLowerCase();
    list.innerHTML = "";
    shown = [];
    Array.prototype.forEach.call(sel.options, function (o, i) {
      var current = i === sel.selectedIndex;
      if (o.value && count(o) === 0 && !current) return;          // (0) is noise
      if (q && (!o.value || o.textContent.toLowerCase().indexOf(q) === -1)) return;
      var li = document.createElement("li");
      li.className = "hub-combo__opt";
      li.setAttribute("role", "option");
      li.textContent = o.textContent;
      li.dataset.i = String(i);
      if (current) li.setAttribute("aria-selected", "true");
      li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
      list.appendChild(li);
      shown.push(li);
    });
    if (!shown.length) {
      var none = document.createElement("li");
      none.className = "hub-combo__none";
      none.textContent = noneText;
      list.appendChild(none);
    }
    var at = -1;
    shown.forEach(function (li, n) { if (+li.dataset.i === sel.selectedIndex) at = n; });
    setActive(q ? 0 : Math.max(at, 0));
  }

  function open() {
    if (!pop.hidden) return;
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    input.value = "";
    render();
    input.focus();
  }
  function close() {
    pop.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }
  function choose(i) {
    close();
    if (sel.selectedIndex !== i) {
      sel.selectedIndex = i;
      sel.dispatchEvent(new Event("change", { bubbles: true }));   // the existing filters run
    }
    label();
    btn.focus();
  }

  // The whole pill opens it, as the native select did; its own label
  // behaviour would only focus the hidden select.
  pill.addEventListener("click", function (e) {
    if (pop.contains(e.target)) return;
    e.preventDefault();
    pop.hidden ? open() : close();
  });
  input.addEventListener("input", render);
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(active + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(active - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) choose(+shown[active].dataset.i); }
    else if (e.key === "Escape") { e.preventDefault(); close(); btn.focus(); }
    else if (e.key === "Tab") { close(); }
  });
  btn.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
  document.addEventListener("mousedown", function (e) {
    if (!pop.hidden && !pill.contains(e.target)) close();
  });

  // Values set from code (clearAll, the left nav) fire no event.
  ["value", "selectedIndex"].forEach(function (prop) {
    var d = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, prop);
    Object.defineProperty(sel, prop, {
      configurable: true,
      get: function () { return d.get.call(this); },
      set: function (v) { d.set.call(this, v); label(); }
    });
  });
  new MutationObserver(label).observe(sel, { childList: true, subtree: true, characterData: true });
  label();
}

/* ------------------------------------------------------------- the sidebar */

/* The left nav ships with hardcoded counts -- Creo 24, Videos 86. Against a
 * real catalogue of 382 and 491 those are not merely stale, they contradict
 * what the same page shows two panels away. Numbers nobody can reconcile are
 * worse than no numbers, so each one is either corrected or removed. */
/* Which group a nav item sits under: walk back to the nearest .orion-group,
 * because the sidebar is a flat list of siblings rather than nested. */
function inNoCountGroup(item) {
  var node = item.previousElementSibling;
  while (node) {
    if (node.classList.contains("orion-group")) {
      return NO_COUNT_GROUPS.indexOf(node.textContent.trim().toLowerCase()) !== -1;
    }
    node = node.previousElementSibling;
  }
  return false;
}

function fillSidebarCounts(facets) {
  if (!baselineFacets) baselineFacets = facets;

  /* Which nav labels the catalogue knows about at all, from the unfiltered
   * counts. It is the difference between "zero here" and "we have no such
   * number", and the sidebar has to be able to say both. */
  var knownValues = {};
  ["product_families", "segments", "funnel_stages", "content_depths"]
    .forEach(function (k) {
      (baselineFacets[k] || []).forEach(function (f) { knownValues[f.value] = 1; });
    });
  (baselineFacets.types || []).forEach(function (f) {
    Object.keys(NAV_TYPE).forEach(function (label) {
      if (NAV_TYPE[label] === f.value) knownValues[label] = 1;
    });
  });
  var counts = {};
  // Families, segments and funnel stages all label themselves in the nav, so
  // one flat lookup keyed by the displayed name covers every group.
  ["product_families", "segments", "funnel_stages", "content_depths"]
    .forEach(function (key) {
      (facets[key] || []).forEach(function (f) { counts[f.value] = f.count; });
    });

  // The type labels the nav uses are not our type values.
  var typeLabels = { "Videos": "video", "LDKs": "ldk", "VDKs": "vdk",
                     "CAD Dataset": "cad_model", "Virtual Machines": "vm" };
  (facets.types || []).forEach(function (f) {
    Object.keys(typeLabels).forEach(function (label) {
      if (typeLabels[label] === f.value) counts[label] = f.count;
    });
  });

  var updated = 0, cleared = 0;
  document.querySelectorAll(".orion-navitem").forEach(function (item) {
    var label = item.querySelector(".label");
    if (!label) return;
    if (inNoCountGroup(item)) return;

    /* The Funnel Stage items ship without a .count element at all, so they
     * were skipped and sat there numberless beside four groups that all show
     * one. Create the element rather than skip: the number exists, and an
     * inconsistent sidebar reads as a bug in the data. */
    var count = item.querySelector(".count");
    if (!count) {
      count = document.createElement("span");
      count.className = "count";
      item.appendChild(count);
    }
    // Some labels carry a sub-caption -- "LDKs Live Demo Kits" -- so the
    // full textContent matches nothing. Take the first text node, which is
    // the name itself.
    var name = "";
    label.childNodes.forEach(function (n) {
      if (!name && n.nodeType === Node.TEXT_NODE && n.textContent.trim()) {
        name = n.textContent.trim();
      }
    });
    if (!name) name = label.textContent.trim();

    if (counts[name] !== undefined) {
      count.textContent = counts[name];
      updated++;
    } else if (knownValues[name]) {
      // The value exists in the catalogue but nothing in the current slice
      // matches it. That is a real zero, and blank would read as "unknown".
      count.textContent = "0";
      updated++;
    } else {
      // No honest number for this one -- Favorites needs per-user state we
      // do not collect. Drop the figure rather than leave a fabricated one.
      count.textContent = "";
      cleared++;
    }
  });
  if (facets === baselineFacets) {
    console.info("[hub-api] sidebar: %d counts corrected, %d removed",
                 updated, cleared);
  }
}

/* ------------------------------------------------- API-driven filtering */

/* The page originally filtered a client-side array with title.indexOf().
 * Two things that cannot fix: the facet counts stay global, so with Type=VDK
 * chosen "Creo (382)" still claims the whole catalogue; and there is no
 * ranking, so a search returns matches in whatever order the array happened
 * to be in. Both are already solved on the server, so the filters query it.
 */

var CONTROLS = ["hubSearchInput", "hubFilterType", "hubFilterProduct",
                "hubFilterSegment", "hubFilterStage", "hubFilterLanguage",
                "hubFilterCf", "hubFilterVideoType", "hubFilterPublished",
                "hubFilterArchived"];
var LANDING = ["hubHome"];
//: One request's ceiling, enforced server-side (`le=200` in assets.py) --
//: not a UI choice, so raising it here would just get clamped back. A
//: filter or a search that matches more than this needs a second request,
//: which is what `loadMoreState` below is for.
var RESULT_LIMIT = 200;
var inFlight = 0;
var baselineFacets = null;     // whole-catalogue counts, for when all clear
/* The filters that have no control in the filter bar: navigation sets them
 * (Home, the sidebar, a tag chip, a VM's links) and Reset clears them. One
 * object so that those modules can set them (2026-10-14).
 *
 * sort: an explicit sort, when something other than the default is wanted
 *   -- the Recently published view, and the segment pages, whose grid must
 *   NOT repeat the ten cards already in the rail above it. Both default to
 *   recency otherwise, and the overlap was exactly 10 of 10.
 *
 * umbrella: the umbrella family the nav has taken you to. Not a dropdown,
 *   because there is no umbrella control in the filter bar -- Browse by
 *   Product is the only way in, and the reset button is the way out.
 *
 * tag: the tag a chip on a details page has taken you to, held the same way
 *   and for the same reason. The results heading says which tag is on, so a
 *   narrowed grid always explains itself -- a filter that is invisible AND
 *   unexplained is the trap this pattern exists to avoid. Liwei, 2026-09-16.
 *
 * order: which way a table column is sorted (asc/desc, 2026-10-26), set
 *   only by clicking a column; anything else that sets `sort` clears it. */
var navFilter = { sort: null, umbrella: null, tag: null, order: null };

/* What "Load more" repeats. Liwei asked about this one filtering Creo down
 * to "showing 200 of 422" with no way to reach the other 222 -- the grid
 * fetched exactly one page and stopped, silently, with nothing on screen
 * saying more existed.
 *
 * `baseParams` is the filter/search query alone, WITHOUT limit or offset, so
 * every subsequent page asks the same question with a moving offset. Reset
 * to null whenever applyFilters() runs for a new filter, search or nav
 * click, so a stale click on an old button can never append the wrong
 * asset's next page onto a grid that has since changed underneath it. */
var loadMoreState = null;

function val(id) {
  var el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

function currentQuery() {
  var params = new URLSearchParams();
  var q = val("hubSearchInput");
  if (q) params.set("q", q);
  if (val("hubFilterType")) params.append("type", val("hubFilterType"));
  if (val("hubFilterProduct")) params.append("family", val("hubFilterProduct"));
  if (val("hubFilterSegment")) params.append("segment", val("hubFilterSegment"));
  if (val("hubFilterStage")) params.append("stage", val("hubFilterStage"));
  if (val("hubFilterLanguage")) params.append("language", val("hubFilterLanguage"));
  if (val("hubFilterPublished")) params.append("published", val("hubFilterPublished"));
  if (val("hubFilterArchived")) params.set("archived", "true");
  // Elio's "Video Type", which is `content_depth` under its own name.
  if (val("hubFilterVideoType")) params.append("depth", val("hubFilterVideoType"));
  var cf = val("hubFilterCf");
  if (cf === "yes") params.set("customer_facing", "true");
  if (cf === "no") params.set("customer_facing", "false");
  if (navFilter.umbrella) params.append("umbrella", navFilter.umbrella);
  if (navFilter.tag) params.append("tag", navFilter.tag);
  if (val("hubFilterType") === "vm" && val("hubFilterVmVersions") === "all") {
    params.set("include_older_vms", "true");
  }
  return params;
}

/* The sort is not part of the facet query -- counts do not depend on order
 * -- so it is added only where results are fetched. */
function effectiveSort() {
  if (navFilter.sort) return navFilter.sort;
  // On a segment page the rail above already shows the ten newest, so the
  // grid lists the whole segment alphabetically instead of repeating them.
  if (val("hubFilterSegment") && !val("hubSearchInput")) return "title";
  return null;
}

/* Rewrite each option's count in place, keeping the selection. A value the
 * current filters exclude entirely shows as (0) rather than disappearing:
 * options vanishing as you type is disorienting, and (0) is the honest
 * answer to "what would I get". */
function rescoreSelect(id, facet) {
  var el = document.getElementById(id);
  if (!el || !facet) return;
  var counts = {};
  facet.forEach(function (f) { counts[f.value] = f.count; });
  Array.prototype.forEach.call(el.options, function (o) {
    if (!o.value) return;                        // the "All" entry
    var base = o.textContent.replace(/\s*\(\d+\)\s*$/, "");
    o.textContent = base + " (" + (counts[o.value] || 0) + ")";
  });
}

/* Elio, 2026-09-10: "when they select Video, another filter appears,
 * 'Video Type'". Show it while Asset Type is Video; hide it otherwise, and
 * clear it on the way out — a hidden filter that is still narrowing the
 * grid is a trap, and this runs at the top of applyFilters() so the reset
 * lands before currentQuery() reads the value.
 *
 * It filters for real since 2026-09-15 (see the markup in index.html).
 *
 * Only-on-Video is Elio's rule, kept as asked, but worth revisiting with
 * him: `content_depth` is also set on 53 LDKs and 89 VDKs (measured
 * 2026-09-15), and those are unreachable while the control is bound to
 * Video. Renaming it would be his call, not a silent fix here. */
function updateVideoTypeFilterVisibility() {
  var pill = document.getElementById("hubVideoTypeFilterPill");
  if (!pill) return;
  var isVideo = val("hubFilterType") === "video";
  pill.style.display = isVideo ? "" : "none";
  if (!isVideo) {
    var sel = document.getElementById("hubFilterVideoType");
    if (sel) sel.value = "";
  }
}

/* Paul and Scott, 2026-09-25: VMs list only the newest version of each --
 * one Windchill, not five -- with a way to see the rest. Built here rather
 * than in the markup, next to Video Type and on the same rule: shown only
 * while Asset Type is Virtual Machine, and reset on the way out so a hidden
 * control never keeps narrowing (or widening) the grid. */
function updateVmVersionFilter() {
  var pill = document.getElementById("hubVmVersionsPill");
  if (!pill) {
    var anchor = document.getElementById("hubVideoTypeFilterPill");
    if (!anchor) return;
    pill = document.createElement("label");
    pill.className = "filter-pill";
    pill.id = "hubVmVersionsPill";
    pill.appendChild(document.createTextNode("Versions: "));
    var select = document.createElement("select");
    select.id = "hubFilterVmVersions";
    [["", "Latest only"], ["all", "All versions"]].forEach(function (o) {
      var option = document.createElement("option");
      option.value = o[0];
      option.textContent = o[1];
      select.appendChild(option);
    });
    select.addEventListener("change", applyFilters);
    pill.appendChild(select);
    pill.insertAdjacentHTML("beforeend",
      '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#i-chevron-down"/></svg>');
    anchor.insertAdjacentElement("afterend", pill);
  }
  var isVm = val("hubFilterType") === "vm";
  pill.style.display = isVm ? "" : "none";
  if (!isVm) document.getElementById("hubFilterVmVersions").value = "";
}

/* ── Published and Sort (Serge, 2026-10-13) ───────────────────────────
 *
 * "Search TMH by date" and "sort by date published, latest first". Both
 * built here rather than in Elio's markup, like Versions above.
 *
 * Published narrows by age band -- the same bands as the age badges
 * (backend/services/content_age.py) -- or by year, with counts like every
 * other filter. Sort is a visible handle on the sort the page already
 * keeps (`sortOverride`): Latest Uploads shows "Newest first", Home and
 * Reset put it back, and choosing one on Home lists everything that way.
 */
var PUBLISHED_BANDS = [["new", "Under 1 year"], ["recent", "1\u20132 years"],
                       ["aging", "2\u20134 years"], ["older", "4 years or more"]];
var SORTS = [["relevance", "Best match"], ["recent", "Newest first"],
             ["oldest", "Oldest first"], ["most_viewed", "Most viewed"],
             ["title", "A\u2013Z"]];

function ensurePublishedFilter() {
  var select = document.getElementById("hubFilterPublished");
  if (select) return select;
  // In the main bar after Segment, not under "More filters": finding the
  // newest is what Serge asked for, so it is in plain sight.
  var segment = document.getElementById("hubFilterSegment");
  var anchor = segment && segment.closest("label");
  if (!anchor) return null;
  var pill = document.createElement("label");
  pill.className = "filter-pill";
  pill.id = "hubPublishedPill";
  pill.appendChild(document.createTextNode("Published: "));
  select = document.createElement("select");
  select.id = "hubFilterPublished";
  var any = document.createElement("option");
  any.value = "";
  any.textContent = "Any time";
  select.appendChild(any);
  select.addEventListener("change", applyFilters);
  pill.appendChild(select);
  pill.insertAdjacentHTML("beforeend",
    '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#i-chevron-down"/></svg>');
  anchor.insertAdjacentElement("afterend", pill);
  return select;
}

/* Bands first, always all four (at 0 too, so the control keeps its
 * shape), then each year with content, newest first. */
function fillPublished(facet) {
  var select = ensurePublishedFilter();
  if (!select || !facet) return;
  var counts = {};
  facet.forEach(function (f) { counts[f.value] = f.count; });
  var chosen = select.value;
  while (select.options.length > 1) select.remove(1);
  Array.prototype.slice.call(select.querySelectorAll("optgroup")).forEach(function (g) {
    g.remove();
  });
  function group(label, entries) {
    var g = document.createElement("optgroup");
    g.label = label;
    entries.forEach(function (e) {
      var o = document.createElement("option");
      o.value = e[0];
      o.textContent = e[1] + " (" + (counts[e[0]] || 0) + ")";
      g.appendChild(o);
    });
    select.appendChild(g);
  }
  group("Age", PUBLISHED_BANDS);
  var years = facet.filter(function (f) { return /^\d{4}$/.test(f.value); })
    .map(function (f) { return [f.value, f.value]; });
  if (years.length) group("Year", years);
  select.value = chosen;
  if (select.value !== chosen) select.value = "";
}

function ensureSortControl() {
  var select = document.getElementById("hubSort");
  if (select) return select;
  var head = document.querySelector("#allAssetsSection .section-head");
  if (!head) return null;
  var pill = document.createElement("label");
  pill.className = "filter-pill hub-sort";
  pill.style.marginLeft = "auto";
  pill.appendChild(document.createTextNode("Sort: "));
  select = document.createElement("select");
  select.id = "hubSort";
  SORTS.forEach(function (o) {
    var option = document.createElement("option");
    option.value = o[0];
    option.textContent = o[1];
    select.appendChild(option);
  });
  select.addEventListener("change", function () {
    navFilter.sort = select.value;
    navFilter.order = null;
    applyFilters();
  });
  pill.appendChild(select);
  pill.insertAdjacentHTML("beforeend",
    '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#i-chevron-down"/></svg>');
  head.appendChild(pill);
  return select;
}

/* Show the sort actually in force -- including the A-Z a segment page
 * uses -- rather than whatever was last picked. */
function reflectSort() {
  var select = ensureSortControl();
  if (select) select.value = effectiveSort() || "relevance";
  ensureViewToggle();
}

/* Tiles or a table (Serge, 2026-10-23), beside Sort. In the table the
 * columns sort, so the Sort control steps aside, and Export CSV appears. */
var COLUMN_ONLY_SORTS = ["type", "product", "segment", "language"];

function ensureViewToggle() {
  var sortPill = document.getElementById("hubSort");
  sortPill = sortPill && sortPill.closest("label");
  var head = document.querySelector("#allAssetsSection .section-head");
  if (!head || !sortPill) return;
  var box = document.getElementById("hubViewToggle");
  if (!box) {
    box = document.createElement("div");
    box.id = "hubViewToggle";
    box.className = "hub-view";
    var exportBtn = document.createElement("button");
    exportBtn.type = "button";
    exportBtn.className = "hub-view__export";
    exportBtn.id = "hubExportCsv";
    exportBtn.textContent = "Export CSV";
    exportBtn.addEventListener("click", function () {
      exportCsv(fetchParams(currentQuery()), exportBtn);
    });
    box.appendChild(exportBtn);
    var seg = document.createElement("div");
    seg.className = "hub-view__seg";
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Show results as");
    [["tiles", "Tiles"], ["table", "Table"]].forEach(function (v) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.view = v[0];
      b.textContent = v[1];
      b.addEventListener("click", function () {
        var table = v[0] === "table";
        if (table === tableView()) return;
        rememberView(table);
        // A column-only sort has no tile equivalent: back to the default.
        if (!table && COLUMN_ONLY_SORTS.indexOf(navFilter.sort) >= 0) {
          navFilter.sort = null;
          navFilter.order = null;
        }
        applyFilters();
      });
      seg.appendChild(b);
    });
    box.appendChild(seg);
    head.insertBefore(box, sortPill);
  }
  var table = tableView();
  box.querySelectorAll("[data-view]").forEach(function (b) {
    var on = (b.dataset.view === "table") === table;
    b.classList.toggle("is-on", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  document.getElementById("hubExportCsv").style.display = table ? "" : "none";
  sortPill.style.display = table ? "none" : "";
}

/* The query plus the order results come in: what the grid, Load more and
 * the CSV export all ask for. */
function fetchParams(params) {
  var p = new URLSearchParams(params);
  var sort = effectiveSort();
  if (sort) p.set("sort", sort);
  if (navFilter.order) p.set("order", navFilter.order);
  return p;
}

/* Cards, or rows of the table: fresh, or appended by Load more. */
function renderResults(grid, items, append) {
  var table = tableView();
  grid.classList.toggle("is-table", table);
  if (table) {
    renderRows(grid, items, append, {
      sort: effectiveSort() || (val("hubSearchInput").length >= 2 ? "relevance" : "recent"),
      order: navFilter.order,
      onSort: function (next) {
        navFilter.sort = next.sort;
        navFilter.order = next.order;
        applyFilters();
      }
    });
    return;
  }
  if (!append) grid.innerHTML = "";
  items.forEach(function (a) { grid.appendChild(buildCard(a)); });
}

/* "Archived: Show" under More filters, only for people who may see
 * archived content (2026-10-14); the server ignores the ask otherwise. */
function ensureArchivedFilter() {
  if (document.getElementById("hubFilterArchived")) return;
  var panel = document.getElementById("hubMoreFilters");
  if (!panel) return;
  var pill = document.createElement("label");
  pill.className = "filter-pill";
  pill.appendChild(document.createTextNode("Archived: "));
  var select = document.createElement("select");
  select.id = "hubFilterArchived";
  [["", "Hide"], ["true", "Show"]].forEach(function (o) {
    var option = document.createElement("option");
    option.value = o[0];
    option.textContent = o[1];
    select.appendChild(option);
  });
  select.addEventListener("change", applyFilters);
  pill.appendChild(select);
  pill.insertAdjacentHTML("beforeend",
    '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#i-chevron-down"/></svg>');
  panel.appendChild(pill);
}

/* The filters in the address (2026-10-26): what is on screen can be copied
 * and sent, and another system -- Pathfinder, opening the Hub on a
 * pre-filtered list (Serge's meeting, 2026-10-23) -- can link straight to
 * it: /?family=Creo&type=video&sort=recent. The query string, not the hash,
 * which already says which page is open (#/asset/..., #/search/...). */
var URL_CONTROLS = [["q", "hubSearchInput"], ["type", "hubFilterType"],
                    ["family", "hubFilterProduct"], ["segment", "hubFilterSegment"],
                    ["stage", "hubFilterStage"], ["language", "hubFilterLanguage"],
                    ["published", "hubFilterPublished"], ["depth", "hubFilterVideoType"]];

function writeUrl(params) {
  var p = new URLSearchParams(params);
  p.delete("archived");             // a permission, not something to pass on
  p.delete("include_older_vms");
  if (navFilter.sort) p.set("sort", navFilter.sort);
  if (navFilter.order) p.set("order", navFilter.order);
  var qs = p.toString();
  var url = location.pathname + (qs ? "?" + qs : "") + location.hash;
  if (url !== location.pathname + location.search + location.hash) {
    history.replaceState(history.state, "", url);
  }
}

/* A link opened cold: put its filters on the controls and show them.
 * False when the address carries none. */
function restoreFiltersFromUrl() {
  var p = new URLSearchParams(location.search);
  var any = false;
  URL_CONTROLS.forEach(function (pair) {
    var value = p.get(pair[0]);
    var el = document.getElementById(pair[1]);
    if (!value || !el) return;
    el.value = value;
    // A select keeps its old value for an option it does not have.
    if (el.value === value) any = true;
  });
  var cf = p.get("customer_facing");
  var cfEl = document.getElementById("hubFilterCf");
  if (cfEl && (cf === "true" || cf === "false")) { cfEl.value = cf === "true" ? "yes" : "no"; any = true; }
  ["umbrella", "tag", "sort", "order"].forEach(function (key) {
    if (p.get(key)) { navFilter[key] = p.get(key); any = true; }
  });
  if (any) applyFilters();
  return any;
}

async function applyFilters() {
  updateVideoTypeFilterVisibility();
  updateVmVersionFilter();
  ensurePublishedFilter();
  hubPermissions.then(function (granted) {
    if (granted.indexOf("view_archived") >= 0) ensureArchivedFilter();
  });
  reflectSort();
  var params = currentQuery();
  var active = params.toString().length > 0 || !!navFilter.sort;
  writeUrl(params);

  markNavActive();
  renderActiveFilters();
  renderSuggestions(val("hubSearchInput"));
  // The catalogue total reads as a second, contradicting result count
  // beside "showing 200 of 285" (2026-10-01); it shows on Home only.
  var total = document.getElementById("hubTotal");
  if (total) total.style.display = active ? "none" : "";
  renderSegmentHeader();
  var reset = document.getElementById("hubResetBtn");
  if (reset) reset.style.display = active ? "inline-flex" : "none";
  LANDING.forEach(function (id) {
    var el = document.getElementById(id);
    // Never re-show a section hidden for want of honest data.
    if (el && !el.classList.contains("hub-hidden")) {
      el.style.display = active ? "none" : "";
    }
  });
  var all = document.getElementById("allAssetsSection");
  if (all) all.style.display = active ? "" : "none";
  if (!active) {
    // Put the dropdowns back to whole-catalogue counts as well, not just the
    // sidebar. They carry SCOPED counts from whatever was last selected --
    // browse Creo and the Segment list reads "CAD (399), ALM (0)" -- and
    // clearing the filter used to leave those numbers sitting there,
    // describing a slice the page is no longer showing.
    //
    // Latest Uploads never had the bug because a sort counts as active, so
    // it takes the branch below and rescores on the way through. Home is the
    // one path that clears everything and then returns early.
    if (baselineFacets) {
      rescoreSelect("hubFilterType", baselineFacets.types);
      rescoreSelect("hubFilterProduct", baselineFacets.product_families
                                     || baselineFacets.products);
      rescoreSelect("hubFilterSegment", baselineFacets.segments);
      rescoreSelect("hubFilterStage", baselineFacets.funnel_stages);
      rescoreSelect("hubFilterVideoType", baselineFacets.content_depths);
      rescoreSelect("hubFilterLanguage", baselineFacets.languages);
      fillPublished(baselineFacets.published);
      fillSidebarCounts(baselineFacets);
    }
    loadMoreState = null;
    hideLoadMoreBar();
    return;
  }
  if (all) all.style.display = "";

  var ticket = ++inFlight;
  var assetParams = fetchParams(params);
  assetParams.set("limit", RESULT_LIMIT);
  var sort = effectiveSort();

  var page, facets;
  try {
    page = await getJSON("/api/assets?" + assetParams);
    facets = await getJSON("/api/taxonomy?" + params);
  } catch (err) {
    console.error("[hub-api] filter request failed", err);
    report("Filtering failed - " + err.message, true);
    return;
  }
  if (ticket !== inFlight) return;   // a slower earlier reply must not win

  var grid = document.getElementById("allAssetsGrid");
  renderResults(grid, page.items, false);
  ensureViewToggle();

  // "All Assets" under a PLM page is misleading -- they are all PLM assets.
  var heading = document.querySelector("#allAssetsSection .section-head__title");
  if (heading) {
    var seg = val("hubFilterSegment");
    var node = heading.firstChild;
    while (node) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
        node.textContent = navFilter.sort === "recent" ? " Recently published "
                         : navFilter.tag ? " All assets tagged “" + navFilter.tag + "” "
                         : navFilter.umbrella ? " All " + umbrellaDisplayName(navFilter.umbrella) + " assets "
                         : seg ? " All " + seg + " assets "
                         : " All Assets ";
        break;
      }
      node = node.nextSibling;
    }
  }

  var count = document.getElementById("allAssetsCount");
  if (count) count.textContent = formatAssetCount(page.items.length, page.total);

  // The next page repeats this exact question with a moving offset, so what
  // is saved is the query BEFORE limit/sort were added to it, not
  // assetParams itself. sort lives separately because "" is a real value
  // here (recency, the default) and URLSearchParams.get() cannot tell an
  // absent key from an empty one.
  loadMoreState = page.total > page.items.length
    ? { baseParams: params, sort: sort || "", order: navFilter.order || "",
        offset: page.items.length, total: page.total }
    : null;
  updateLoadMoreBar();

  // Scoped counts: this is what makes the panel honest once anything is on.
  rescoreSelect("hubFilterType", facets.types);
  rescoreSelect("hubFilterProduct", facets.product_families);
  rescoreSelect("hubFilterSegment", facets.segments);
  rescoreSelect("hubFilterStage", facets.funnel_stages);
  rescoreSelect("hubFilterVideoType", facets.content_depths);
  rescoreSelect("hubFilterLanguage", facets.languages);
  fillPublished(facets.published);
  // The sidebar shows the same three dimensions, so it takes the same
  // numbers. Leaving it on whole-catalogue counts would reintroduce, one
  // panel over, exactly the contradiction this is meant to remove.
  fillSidebarCounts(facets);

  var none = document.querySelector(".hub-noresults");
  if (none) none.classList.toggle("show", page.total === 0);

  noteSearch(val("hubSearchInput"), page.total);
}

/* What somebody searched for, once they have stopped typing.
 *
 * Two seconds, not the 200ms the grid itself uses: the grid should react to
 * every keystroke, but the log should hold the question, not its prefixes.
 * Without the delay "windchill" arrives as w, wi, win, wind… and the real
 * query is buried in nine fragments of itself.
 *
 * The zero-result ones are the reason this exists (Liwei, 2026-09-21) —
 * "people keep searching for X and we have nothing" is the most direct
 * evidence there is for what to commission next, and it cannot be
 * reconstructed after the fact.
 */
var searchNoteTimer = null;
var lastNotedSearch = "";

function noteSearch(query, total) {
  query = (query || "").trim();
  clearTimeout(searchNoteTimer);
  // Two characters is where the grid itself starts searching; below that
  // there is no question being asked yet.
  if (query.length < 2 || query === lastNotedSearch) return;
  searchNoteTimer = setTimeout(function () {
    lastNotedSearch = query;
    fetch("/api/assets/search-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: query, results: total }),
    }).catch(function (err) {
      console.debug("[hub-api] search not recorded", err);
    });
  }, 2000);
}

function formatAssetCount(shown, total) {
  return shown < total ? "(showing " + shown + " of " + total + ")" : "(" + total + ")";
}

/* Injected rather than added to Elio's markup: this control exists nowhere
 * in his file, so it goes in ours rather than turning a merge with his next
 * revision into a place to remember what to keep. Created once and reused,
 * the same shape as renderFileList()'s box. */
function ensureLoadMoreBar() {
  var bar = document.getElementById("hubLoadMoreBar");
  if (bar) return bar;
  var grid = document.getElementById("allAssetsGrid");
  if (!grid) return null;
  bar = document.createElement("div");
  bar.className = "hub-load-more";
  bar.id = "hubLoadMoreBar";
  bar.style.display = "none";
  var btn = document.createElement("button");
  btn.type = "button";
  btn.id = "hubLoadMoreBtn";
  btn.className = "hub-load-more__btn";
  btn.textContent = "Load more";
  btn.addEventListener("click", loadMoreAssets);
  bar.appendChild(btn);
  grid.parentNode.insertBefore(bar, grid.nextSibling);
  return bar;
}

function hideLoadMoreBar() {
  var bar = document.getElementById("hubLoadMoreBar");
  if (bar) bar.style.display = "none";
}

function updateLoadMoreBar() {
  var bar = ensureLoadMoreBar();
  if (!bar) return;
  if (!loadMoreState) { bar.style.display = "none"; return; }
  bar.style.display = "flex";
  var btn = document.getElementById("hubLoadMoreBtn");
  if (btn) {
    btn.disabled = false;
    var remaining = loadMoreState.total - loadMoreState.offset;
    btn.textContent = "Load " + Math.min(remaining, RESULT_LIMIT) + " more";
  }
}

/* Appends the next page onto the grid already on screen -- it does not
 * re-render, so scroll position and everything already loaded survive.
 *
 * `ticket` is read, not incremented: applyFilters() owns `inFlight` and
 * bumps it the moment a filter, search box or nav click changes, which is
 * synchronous and happens before this function's await ever resolves. So a
 * filter changed mid-fetch is caught the same way an overlapping
 * applyFilters() call already was, with no separate flag to keep in sync. */
async function loadMoreAssets() {
  if (!loadMoreState) return;
  var ticket = inFlight;
  var btn = document.getElementById("hubLoadMoreBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }

  var params = new URLSearchParams(loadMoreState.baseParams);
  params.set("limit", RESULT_LIMIT);
  params.set("offset", loadMoreState.offset);
  if (loadMoreState.sort) params.set("sort", loadMoreState.sort);
  if (loadMoreState.order) params.set("order", loadMoreState.order);

  var page;
  try {
    page = await getJSON("/api/assets?" + params);
  } catch (err) {
    console.error("[hub-api] load more failed", err);
    report("Could not load more - " + err.message, true);
    if (btn) { btn.disabled = false; btn.textContent = "Load more"; }
    return;
  }
  if (ticket !== inFlight || !loadMoreState) return;   // the filter moved on

  var grid = document.getElementById("allAssetsGrid");
  renderResults(grid, page.items, true);

  loadMoreState.offset += page.items.length;
  loadMoreState.total = page.total;
  if (!page.items.length || loadMoreState.offset >= loadMoreState.total) {
    loadMoreState = null;
  }

  var count = document.getElementById("allAssetsCount");
  if (count) {
    count.textContent = loadMoreState
      ? formatAssetCount(loadMoreState.offset, loadMoreState.total)
      : "(" + page.total + ")";
  }
  updateLoadMoreBar();
}

/* The filter controls are ours outright (2026-10-14), so they are simply
 * wired here; before that each one was cloned to shed the concept mock-up's
 * own listeners. Reset -- the Reset button and the chips' Clear all --
 * is clearAll(), which clears every control, Published and the sort
 * included. */
function takeOverControls() {
  var debounced = debounce(applyFilters, 200);
  CONTROLS.forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener(el.tagName === "INPUT" ? "input" : "change", debounced);
  });
  window.hubApplyFilters = applyFilters;   // for anything else that calls it
  window.hubResetFilters = clearAll;       // data-action="reset-filters"
}

/* ── the filter bar (Liwei, 2026-10-01) ──────────────────────────────
 *
 * One row: search, Advanced Search, Asset Type (+ Video Type when it
 * applies), Product, Segment, and "More filters" for Stage, Language and
 * Customer-Facing. Under it, every filter that is on as a chip that can be
 * removed on its own -- including the two the bar has no control for (the
 * product the sidebar took you to, the tag a details page took you to),
 * which used to show only as a sidebar highlight or a heading. "Clear all"
 * at the end of the chips replaces the separate Reset link.
 *
 * Elio's controls are moved, not rebuilt, so his markup and the existing
 * filter wiring (takeOverControls) are untouched. */
var MORE_FILTERS = ["hubFilterStage", "hubFilterLanguage", "hubFilterCf"];

//: Chip label per control. Values come from the option the person sees,
//: minus its count: "Windchill (156)" -> "Windchill".
var CHIP_LABELS = [
  ["hubFilterType", "Type"], ["hubFilterVideoType", "Video type"],
  ["hubFilterProduct", "Product"], ["hubFilterSegment", "Segment"],
  ["hubFilterStage", "Stage"], ["hubFilterLanguage", "Language"],
  ["hubFilterCf", "Customer-facing"], ["hubFilterPublished", "Published"],
  ["hubFilterArchived", "Archived"]
];

function wireFilterBar() {
  var bar = document.querySelector("#mainTopbar .hero-search");
  if (!bar || document.getElementById("hubMoreFilters")) return;

  var panel = document.createElement("div");
  panel.className = "hero-search hub-more-panel";
  panel.id = "hubMoreFilters";
  panel.hidden = true;
  MORE_FILTERS.forEach(function (id) {
    var control = document.getElementById(id);
    var pillEl = control && control.closest(".filter-pill");
    if (pillEl) panel.appendChild(pillEl);
  });

  var more = document.createElement("button");
  more.type = "button";
  more.id = "hubMoreBtn";
  more.className = "hub-more-btn";
  more.setAttribute("aria-expanded", "false");
  more.setAttribute("aria-controls", "hubMoreFilters");
  more.innerHTML = 'More filters<span class="hub-more-btn__n" hidden></span>'
                 + '<svg class="orion-ico orion-ico--sm"><use href="#i-chevron-down"/></svg>';
  more.addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    more.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
  });
  var reset = document.getElementById("hubResetBtn");
  bar.insertBefore(more, reset && reset.parentNode === bar ? reset : null);
  bar.parentNode.insertBefore(panel, bar.nextSibling);

  var chips = document.createElement("div");
  chips.className = "hub-chips";
  chips.id = "hubActiveFilters";
  panel.parentNode.insertBefore(chips, panel.nextSibling);
  renderActiveFilters();
}

function optionLabel(id) {
  var el = document.getElementById(id);
  if (!el || !el.value) return "";
  var o = el.options && el.options[el.selectedIndex];
  return (o ? o.textContent : el.value).replace(/\s*\(\d[\d,]*\)\s*$/, "").trim();
}

function renderActiveFilters() {
  var host = document.getElementById("hubActiveFilters");
  if (!host) return;
  host.innerHTML = "";
  var add = function (name, value, clear) {
    var chip = document.createElement("button");
    chip.type = "button";
    chip.className = "hub-chip";
    chip.title = "Remove this filter";
    chip.innerHTML = "<b>" + escapeHtml(name) + ":</b> " + escapeHtml(value)
                   + '<span class="hub-chip__x" aria-hidden="true">&times;</span>';
    chip.setAttribute("aria-label", "Remove " + name + ": " + value);
    chip.addEventListener("click", function () { clear(); applyFilters(); });
    host.appendChild(chip);
  };
  if (navFilter.umbrella) {
    add("Product", umbrellaDisplayName(navFilter.umbrella), function () { navFilter.umbrella = null; });
  }
  CHIP_LABELS.forEach(function (c) {
    var text = optionLabel(c[0]);
    if (text) add(c[1], text, function () {
      var el = document.getElementById(c[0]);
      if (el) el.value = "";
    });
  });
  if (navFilter.tag) add("Tag", navFilter.tag, function () { navFilter.tag = null; });
  if (val("hubFilterType") === "vm" && val("hubFilterVmVersions") === "all") {
    add("Versions", "Older VM versions too", function () {
      var el = document.getElementById("hubFilterVmVersions");
      if (el) el.value = "";
    });
  }
  if (host.children.length) {
    var clear = document.createElement("button");
    clear.type = "button";
    clear.className = "hub-chips__clear";
    clear.textContent = "Clear all";
    clear.addEventListener("click", clearAll);
    host.appendChild(clear);
  }

  var n = MORE_FILTERS.filter(function (id) { return !!val(id); }).length;
  var badge = document.querySelector("#hubMoreBtn .hub-more-btn__n");
  if (badge) { badge.hidden = !n; badge.textContent = n; }
}

function clearAll() {
  CONTROLS.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.value = "";
  });
  navFilter.sort = null;
  navFilter.order = null;
  navFilter.umbrella = null;
  navFilter.tag = null;
  applyFilters();
}

export {
  applyFilters, clearAll, CONTROLS, enhanceSearchableSelect, fillPublished,
  fillSelect, fillSidebarCounts, HIDDEN_SEGMENTS, navFilter, restoreFiltersFromUrl,
  takeOverControls, val, wireFilterBar
};
