/* Advanced Search (#/search), which also reads file names, and the
 * suggestion strip under the search box.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import {
  debounce, escapeHtml, getJSON, LANGUAGE_LABEL, pill, TYPE_LABELS
} from "./util.js";
import { paintCoverInto, TYPE_CHIP, videoTypeOf } from "./cards.js";
import { val } from "./filters.js";
import { familyDisplayName } from "./nav.js";
import { buildFileRow, closeFilePreview, fileHash } from "./detail.js";
import { closeActivity } from "./activity.js";

/* ---------------------------------------------------- advanced search
 *
 * Liwei, 2026-09-30: a search that also looks inside each demo -- the name
 * of every file in its folder (videos, PowerPoint, PDF, Word...) -- and
 * shows one full-width row per demo, with the files that matched listed
 * under it, instead of cards. Two ways in: a button beside the main search
 * box, and an offer in the suggestion strip while someone is searching.
 *
 * Its own view (#/search/<query>), built here like everything else, so
 * index.html stays Elio's. The address carries the query, so a search can
 * be bookmarked, and Back from a demo opened here returns to the results.
 */
var ADV_PAGE_SIZE = 30;
var advState = { q: "", type: "", items: [], total: 0, seq: 0 };

function advancedHash(q) { return "#/search/" + encodeURIComponent(q || ""); }

/* The query's words, split the way the server splits them
 * (relevance.terms: letters and digits, underscore a separator). */
function queryTerms(q) {
  return ((q || "").toLowerCase().match(/[\p{L}\p{N}]+/gu) || []);
}

/* Text with every query term marked. Split on the raw text and escape each
 * piece, so nothing from the catalogue is ever inserted as HTML. */
function highlightHtml(text, q) {
  var ts = queryTerms(q).sort(function (a, b) { return b.length - a.length; });
  if (!text || !ts.length) return escapeHtml(text || "");
  // Words of one or two letters only as whole words, as the server
  // matches them (relevance.SHORT_TERM): "e" from "E&HT" must not light up
  // every "e" on the page.
  var re = new RegExp("(" + ts.map(function (t) {
    var esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return t.length <= 2 ? "(?<![\\p{L}\\p{N}])" + esc + "(?![\\p{L}\\p{N}])" : esc;
  }).join("|") + ")", "giu");
  return text.split(re).map(function (part, i) {
    return i % 2 ? '<mark class="hub-hl">' + escapeHtml(part) + "</mark>" : escapeHtml(part);
  }).join("");
}

function mentions(text, q) {
  var words = queryTerms(text);
  var joined = " " + words.join(" ") + " ";
  return queryTerms(q).some(function (w) {
    return w.length <= 2 ? joined.indexOf(" " + w + " ") !== -1 : joined.indexOf(w) !== -1;
  });
}

function buildAdvancedPage() {
  var page = document.getElementById("hubAdvancedPage");
  if (page) return page;
  page = document.createElement("div");
  page.className = "video-preview-page";
  page.id = "hubAdvancedPage";
  var typeOptions = ['<option value="">All asset types</option>'].concat(
    Object.keys(TYPE_LABELS).map(function (k) {
      return '<option value="' + escapeHtml(k) + '">' + escapeHtml(TYPE_LABELS[k]) + "</option>";
    })).join("");
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to Technical Marketing Hub</button>'
    + '<div class="vp-head"><div>'
    +   '<div class="vp-title">Advanced Search</div>'
    +   '<div class="orion-subtle">Searches every demo’s title, description and tags, '
    +   'and the name of every file inside it — videos, PowerPoint, PDF, Word and more.</div>'
    + '</div></div>'
    + '<form class="hub-adv__bar" id="hubAdvForm">'
    +   '<div class="hero-search__field"><svg class="orion-ico ico-muted"><use href="#i-search"/></svg>'
    +     '<input type="text" id="hubAdvInput" autocomplete="off"'
    +     ' placeholder="Search titles, descriptions, tags and file names…"></div>'
    +   '<label class="filter-pill">Asset Type: <select id="hubAdvType">' + typeOptions + '</select>'
    +     '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#i-chevron-down"/></svg></label>'
    + '</form>'
    + '<div class="hub-adv__summary" id="hubAdvSummary"></div>'
    + '<div class="hub-adv__list" id="hubAdvList"></div>'
    + '<div class="hub-adv__more"><button type="button" class="btn-ghost" id="hubAdvMore"'
    +   ' style="display:none">Show more</button></div>';

  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);

  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeAdvancedSearch();
  });
  var input = page.querySelector("#hubAdvInput");
  var run = debounce(function () {
    // replaceState: every keystroke is not a place to go Back to.
    history.replaceState(null, "", advancedHash(input.value.trim()));
    runAdvancedSearch(input.value.trim(), false);
  }, 300);
  input.addEventListener("input", run);
  page.querySelector("#hubAdvForm").addEventListener("submit", function (e) {
    e.preventDefault();
    runAdvancedSearch(input.value.trim(), false);
  });
  page.querySelector("#hubAdvType").addEventListener("change", function () {
    advState.type = this.value;
    runAdvancedSearch(input.value.trim(), false);
  });
  page.querySelector("#hubAdvMore").addEventListener("click", function () {
    runAdvancedSearch(advState.q, true);
  });
  return page;
}

function openAdvancedSearch(q) {
  var page = buildAdvancedPage();
  document.getElementById("requestViewPage").classList.remove("active");
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  var wasOpen = page.classList.contains("active");
  page.classList.add("active");
  var input = document.getElementById("hubAdvInput");
  // Coming back from a demo: the results are still here, and where you
  // were in them matters more than a fresh fetch.
  if (wasOpen && q === advState.q) return;
  if (q === advState.q && advState.items.length) { input.value = q; return; }
  input.value = q;
  page.scrollTop = 0;
  runAdvancedSearch(q, false);
  if (!q) input.focus();
}

function closeAdvancedSearch() {
  var page = document.getElementById("hubAdvancedPage");
  if (!page || !page.classList.contains("active")) return;
  page.classList.remove("active");
  var detail = document.getElementById("videoPreviewPage");
  var request = document.getElementById("requestViewPage");
  if ((detail && detail.classList.contains("active"))
      || (request && request.classList.contains("active"))) return;
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "";
  if (thread) thread.style.display = "";
}

async function runAdvancedSearch(q, more) {
  var summary = document.getElementById("hubAdvSummary");
  var list = document.getElementById("hubAdvList");
  var moreBtn = document.getElementById("hubAdvMore");
  var seq = ++advState.seq;          // a slower, older answer must not win
  if (!more) {
    advState.q = q;
    advState.items = [];
    advState.total = 0;
    list.innerHTML = "";
    moreBtn.style.display = "none";
  }
  if (queryTerms(q).join("").length < 2) {
    summary.textContent = "Type at least two characters.";
    return;
  }
  summary.textContent = "Searching…";
  var params = new URLSearchParams({ q: q, limit: ADV_PAGE_SIZE,
                                     offset: advState.items.length });
  if (advState.type) params.append("type", advState.type);
  var page;
  try {
    page = await getJSON("/api/assets/advanced-search?" + params.toString());
  } catch (err) {
    if (seq !== advState.seq) return;
    console.error("[hub-api] advanced search failed", err);
    summary.textContent = "The search could not be run: " + err.message;
    return;
  }
  if (seq !== advState.seq) return;
  advState.total = page.total;
  page.items.forEach(function (hit) {
    advState.items.push(hit);
    list.appendChild(renderAdvancedHit(hit, q));
  });
  var fileHits = advState.items.reduce(function (n, h) { return n + h.files.length; }, 0);
  summary.textContent = page.total
    ? page.total + (page.total === 1 ? " demo" : " demos") + " match “" + q + "”"
      + (fileHits ? " · " + fileHits + " matching file" + (fileHits === 1 ? "" : "s")
                    + (advState.items.length < page.total ? " in the demos shown" : "") : "")
    : "No demo or file matches “" + q + "”.";
  moreBtn.style.display = advState.items.length < page.total ? "" : "none";
}

/* "2 videos · 2 documents · 3 others" -- everything in the demo's folder,
 * from the complete per-kind counts (resource_counts), so CAD parts that
 * are counted but never listed are in "others" too. A kind with none is
 * left out; a demo with no folder (Consensus) gets no line at all rather
 * than "0 videos", which would claim we looked. */
function fileTotalsText(counts) {
  counts = counts || {};
  var videos = 0, documents = 0, others = 0;
  Object.keys(counts).forEach(function (kind) {
    var n = counts[kind] || 0;
    if (kind === "video") videos += n;
    else if (kind === "document") documents += n;
    else others += n;
  });
  return [[videos, "video"], [documents, "document"], [others, "other"]]
    .filter(function (p) { return p[0] > 0; })
    .map(function (p) { return p[0] + " " + p[1] + (p[0] === 1 ? "" : "s"); })
    .join(" · ");
}

function renderAdvancedHit(hit, q) {
  var a = hit.asset;
  var href = "#/asset/" + encodeURIComponent(a.id);
  var row = document.createElement("div");
  row.className = "hub-adv__hit";

  var thumb = document.createElement("a");
  thumb.className = "hub-adv__thumb";
  thumb.href = href;
  thumb.setAttribute("aria-label", a.title);
  if (a.thumbnail_url) thumb.style.backgroundImage = "url(" + JSON.stringify(a.thumbnail_url) + ")";
  row.appendChild(thumb);
  paintCoverInto(thumb, a);

  var main = document.createElement("div");
  main.className = "hub-adv__main";
  row.appendChild(main);

  var head = document.createElement("div");
  head.className = "hub-adv__head";
  head.innerHTML = '<a class="hub-adv__title" href="' + escapeHtml(href) + '">'
                 + highlightHtml(a.title, q) + "</a>";
  var typeLabel = (TYPE_CHIP[a.type] || [])[1];
  if (typeLabel) head.appendChild(pill(typeLabel, "customer"));
  if (a.language) head.appendChild(pill(LANGUAGE_LABEL[a.language] || a.language.toUpperCase(), "lang"));
  var totals = fileTotalsText(a.resource_counts);
  if (totals) {
    var count = document.createElement("span");
    count.className = "hub-adv__count";
    count.textContent = totals;
    head.appendChild(count);
  }
  main.appendChild(head);

  var desc = document.createElement("div");
  desc.className = "hub-adv__desc";
  desc.innerHTML = highlightHtml(a.description || "No description for this one yet.", q);
  main.appendChild(desc);

  // Every tag the demo carries, the ones the query names outlined, so a
  // hit on "details" shows where.
  var tagValues = [];
  [videoTypeOf(a), a.segment].concat((a.product_families || []).map(familyDisplayName),
                                      a.tags || [], a.named_customer ? [a.named_customer] : [])
    .forEach(function (t) { if (t && tagValues.indexOf(t) === -1) tagValues.push(t); });
  if (tagValues.length) {
    var tags = document.createElement("div");
    tags.className = "hub-adv__tags";
    tagValues.forEach(function (t) {
      var p = pill(t, "tag");
      if (mentions(t, q)) { p.classList.add("hub-pill--hit"); p.innerHTML = highlightHtml(t, q); }
      tags.appendChild(p);
    });
    main.appendChild(tags);
  }

  if (hit.files.length) {
    var box = document.createElement("div");
    box.className = "hub-adv__files";
    box.innerHTML = '<div class="hub-adv__files-head">Matching files (' + hit.files.length + ")</div>";
    var list = document.createElement("div");
    list.className = "vp-files__list";
    hit.files.forEach(function (f) {
      var name;
      if (f.item_id) {
        // Opens the demo with this file's preview showing -- the same
        // place a shared file link lands.
        name = document.createElement("a");
        name.href = fileHash(a.id, f.item_id);
        name.title = "Open the demo and preview this file";
      } else {
        name = document.createElement("span");
      }
      name.className = "vp-file__name";
      name.innerHTML = highlightHtml(f.name, q);
      list.appendChild(buildFileRow(a, f, name, true));
    });
    box.appendChild(list);
    main.appendChild(box);
  }
  return row;
}

/* The logo and "Technical Marketing Hub" in the sidebar go Home from
 * anywhere -- a details page, Advanced Search, the request form, a
 * filtered grid (Liwei, 2026-10-01). It presses the Home nav item rather
 * than repeating it, so the two can never disagree about what Home is. */
function wireBrandHome() {
  var lockup = document.querySelector(".orion-side__brand .lockup");
  if (!lockup || lockup.classList.contains("hub-brand-home")) return;
  lockup.classList.add("hub-brand-home");
  lockup.setAttribute("role", "link");
  lockup.setAttribute("tabindex", "0");
  lockup.title = "Home";
  var goHome = function () {
    var home = document.getElementById("navHome");
    if (home) home.click();
    var thread = document.getElementById("mainThread");
    if (thread) thread.scrollTop = 0;
  };
  lockup.addEventListener("click", goHome);
  lockup.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goHome(); }
  });
}

function wireAdvancedSearch() {
  wireBrandHome();
  // Entry 1: beside the main search box.
  var field = document.querySelector("#mainTopbar .hero-search__field");
  if (field && !document.getElementById("hubAdvOpen")) {
    var open = document.createElement("button");
    open.type = "button";
    open.id = "hubAdvOpen";
    open.className = "hub-adv-open";
    open.title = "Also search the names of the files inside every demo";
    open.innerHTML = '<svg class="orion-ico orion-ico--sm"><use href="#i-file-text"/></svg>Advanced Search';
    open.addEventListener("click", function () {
      location.hash = advancedHash(val("hubSearchInput").trim());
    });
    field.appendChild(open);
  }
  // Elio's Request view knows nothing of this page; opening it must still
  // take this page down, or both would show.
  var openRequest = window.openRequestView;
  if (typeof openRequest === "function" && !openRequest.hubWrapped) {
    window.openRequestView = function () {
      closeAdvancedSearch();
      closeActivity();
      closeFilePreview(false);
      // Opened from a details page, Advanced Search or Hub activity, the
      // address still named that page, and a refresh went back there.
      if (location.hash !== "#/request") {
        history.pushState(null, "", location.pathname + location.search + "#/request");
      }
      return openRequest.apply(this, arguments);
    };
    window.openRequestView.hubWrapped = true;
  }
  var closeRequest = window.closeRequestView;
  if (typeof closeRequest === "function" && !closeRequest.hubWrapped) {
    window.closeRequestView = function () {
      if (location.hash === "#/request") {
        history.pushState(null, "", location.pathname + location.search);
      }
      return closeRequest.apply(this, arguments);
    };
    window.closeRequestView.hubWrapped = true;
  }
}

/* ------------------------------------------------- the suggestion strip */

function renderSuggestions(query) {
  var host = document.getElementById("hubSuggest");
  if (!host) return;
  var items = [];
  // While someone is searching, offer the search that also reads file
  // names (Liwei, 2026-09-30) -- last, after any category offer.
  var q = (query || "").trim();
  if (queryTerms(q).join("").length >= 2) {
    items = items.concat([{ page: true,
      text: "Try Advanced Search for “" + q + "” — also searches file names",
      run: function () { location.hash = advancedHash(q); } }]);
  }
  if (!items.length) { host.style.display = "none"; host.innerHTML = ""; return; }

  host.innerHTML = "";
  items.forEach(function (it) {
    var b = document.createElement("button");
    b.className = "hub-suggest__btn" + (it.page ? " hub-suggest__btn--page" : "");
    b.innerHTML = escapeHtml(it.text)
      + ' <svg class="orion-ico orion-ico--sm"><use href="#i-chevron-right"/></svg>';
    b.addEventListener("click", it.run);
    host.appendChild(b);
  });
  host.style.display = "";
}

export {
  advancedHash, advState, closeAdvancedSearch, fileTotalsText,
  openAdvancedSearch, renderSuggestions, wireAdvancedSearch
};
