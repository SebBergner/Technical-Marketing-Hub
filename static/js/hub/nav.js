/* The left nav: Browse by type/product/segment, the views it opens,
 * the segment header, the sidebar foot, and exitOverlays() -- the one
 * way out of any view.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { escapeHtml } from "./util.js";
import { applyFilters, clearAll, CONTROLS, navFilter } from "./filters.js";
import { closeAssetDetail, closeFilePreview } from "./detail.js";
import { addActivityNav, closeActivity } from "./activity.js";
import { addReviewNav, closeReview } from "./review.js";
import { closeHelp } from "./report.js";
import { closeAdvancedSearch } from "./search.js";
import { closeUpload } from "./upload.js";

/* ---------------------------------------------------------- the left nav */

/* The left nav and the filter bar were two independent filter systems aimed
 * at the same three dimensions, and that is what made the panel feel broken:
 * pick "Videos" in the nav and the Type dropdown still read "All", while
 * every other Type option read (0). Both were telling the truth and together
 * they were incoherent.
 *
 * Every nav group maps exactly onto a control that already exists -- BROWSE
 * BY TYPE onto Type, BROWSE BY PRODUCT onto Product, FUNNEL STAGE onto
 * Stage. So the nav stops being a filter of its own and becomes a second
 * view of the same state: clicking it sets the dropdown, and the dropdown
 * lights the nav. One source of truth per dimension, and they can no longer
 * disagree because there is nothing left to disagree with.
 *
 * (The other half of the fix is in the API: a facet is now counted over
 * every filter EXCEPT its own, so with Type=Video the Type dropdown still
 * offers LDK 259 and VDK 196 rather than two dead zeroes.)
 */
var NAV_TYPE = { "Videos": "video", "LDKs": "ldk", "VDKs": "vdk",
                 "CAD Dataset": "cad_model", "Virtual Machines": "vm" };
var navTargets = {};   // nav label -> {control, value, page}

/* Umbrella families the sidebar and dropdown show under a different name
 * than the one the API, the URL query string and every facet count use.
 * Keyed by the real value, so the API vocabulary stays the single source
 * of truth and this is a display layer on top of it rather than a second
 * copy of it. Same shape as the LDK/VDK relabelling on the Type filter --
 * the option's value is the code, its text is whatever reads best.
 *
 * "PTC Ignite" -- Elio and Seb's rename of IPE, 2026-09-08. The backend
 * still calls it "IPE" everywhere (taxonomy.py, the umbrella facet, the
 * ?umbrella= query param); only the label changes here. */
//: "PTC Ignition" since 2026-10-06 (feedback to Liwei: "it's PTC
//: Ignition not PTC Ignite"); "PTC Ignite" before that.
var UMBRELLA_DISPLAY = { "IPE": "PTC Ignition" };
function umbrellaDisplayName(value) { return UMBRELLA_DISPLAY[value] || value; }

/* The same kind of display-only rename, for `product_families` rather
 * than `umbrella_families` -- the Request form's Product Scope pills and
 * the filter bar's Product dropdown, both built from the derived
 * 19-family list rather than the curated 8-umbrella one (breadth: see the
 * comment above fillProductPills()). "Jetstream"/"Orbit" are what
 * SharePoint's own Product column and family_of() call them; "PTC
 * Jetstream"/"PTC Orbit" is Seb's umbrella spelling, applied today only
 * inside taxonomy.py's umbrella_of() via FAMILY_ROLLUP. Liwei, 2026-09-09:
 * these two should read with the "PTC " prefix everywhere a person sees
 * them, not only in the umbrella nav.
 *
 * Deliberately a SEPARATE map from UMBRELLA_DISPLAY, not folded into it:
 * that map has a reverse lookup (umbrellaCanonicalName) tuned for the
 * nav's own label<->value matching, where the umbrella facet already
 * returns "PTC Jetstream" as the real value. Adding "Jetstream" alongside
 * "PTC Jetstream" into the same table would make that reverse lookup
 * resolve "PTC Jetstream" back to the wrong canonical value and break the
 * nav's own PTC Jetstream destination. No reverse lookup is needed here --
 * both call sites below only ever submit the raw family value, never the
 * label -- so a plain one-way map is enough and cannot collide with the
 * umbrella one. */
var FAMILY_DISPLAY = { "IPE": "PTC Ignition", "Jetstream": "PTC Jetstream",
                       "Orbit": "PTC Orbit" };
function familyDisplayName(value) { return FAMILY_DISPLAY[value] || value; }

function umbrellaCanonicalName(label) {
  for (var value in UMBRELLA_DISPLAY) {
    if (UMBRELLA_DISPLAY[value] === label) return value;
  }
  return label;
}

/* Umbrella families hidden from the sidebar and the Product dropdown
 * outright -- a business decision, not an empty-category one. IPE gets
 * the opposite treatment for exactly that reason: it has zero assets
 * today but demos are being made, so markUnavailable() keeps it visible
 * and merely dims it if it goes quiet. Servigistics has assets; Elio and
 * Seb asked for it gone regardless, 2026-09-08. */
var HIDDEN_UMBRELLAS = ["Servigistics"];

/* Leave whatever view is covering the catalogue, whoever opened it.
 *
 * Three separate reports in Seb's 2026-09-03 review turned out to be this
 * one omission: the nav was never taken over from Elio the way the filter
 * controls were, and only two of his seventeen nav items carry a handler at
 * all.
 *
 *   <div class="orion-navitem orion-navitem--active" id="navHome"
 *        onclick="closeRequestView();">
 *
 * - "the sidebar does not switch the page": Creo, Windchill and the other
 *   fourteen have NO handler of Elio's. Ours set the filter underneath, but
 *   #mainThread was still display:none from the details page, so a click
 *   changed state nobody could see.
 * - "the details page becomes half-size with home above it": Home's inline
 *   onclick runs Elio's closeRequestView(), which restores the topbar and
 *   the thread. It knows nothing about #videoPreviewPage, which our code
 *   opened, so both ended up on screen at once.
 * - "the highlight stays on Home": orion-navitem--active is written into
 *   Home's markup, and markNavActive() was toggling `is-active`, a class
 *   with no rule behind it anywhere in the stylesheet. The highlight was
 *   never ours to move.
 *
 * Both closers run, because either view can be the one in front, and each
 * is safe to call when its own view is already shut. */
function exitOverlays() {
  if (typeof window.closeRequestView === "function") {
    try { window.closeRequestView(); } catch (err) {
      console.warn("[hub-api] closeRequestView threw", err);
    }
  }
  closeFilePreview(false);
  closeAssetDetail();
  closeAdvancedSearch();
  closeActivity();
  closeReview();
  closeHelp();
  closeUpload();
  // The hash has to follow, or a refresh reopens the page we just left.
  if (/^#\/(asset|search|activity|review|help|upload)/.test(location.hash || "")) {
    history.pushState(null, "", location.pathname + location.search);
  }
}

/* The sidebar's newest-first item (2026-10-01): a kit's date is its last
 * edit, so this is "recently published or updated" -- not uploads.
 * wireNav() finds items by the text on screen. */
var RECENT_NAV_LABEL = "Recently published";

function wireNav(facets) {
  var families = {}, stages = {}, umbrellas = {};
  (facets.product_families || []).forEach(function (f) { families[f.value] = 1; });
  (facets.funnel_stages || []).forEach(function (f) { stages[f.value] = 1; });
  // Every umbrella, including the ones at zero: IPE has no demos yet and
  // must still be clickable, or it looks broken rather than empty.
  (facets.umbrella_families || []).forEach(function (f) { umbrellas[f.value] = 1; });

  navTargets = {};
  document.querySelectorAll(".orion-navitem").forEach(function (item) {
    var name = navLabel(item);
    // What the sidebar shows may not be what the API calls it -- see
    // UMBRELLA_DISPLAY. Every lookup against facet data or a query value
    // uses this; `name` itself is kept only for indexing navTargets and
    // markNavActive(), which look a nav item up by what is on screen.
    var canonical = umbrellaCanonicalName(name);

    if (HIDDEN_UMBRELLAS.indexOf(canonical) !== -1) {
      item.style.display = "none";
      return;
    }

    var target = null;
    if (canonical === "Home") target = { control: null };
    else if (canonical === RECENT_NAV_LABEL)
      target = { control: null, sort: "recent" };
    else if (NAV_TYPE[canonical]) target = { control: "hubFilterType", value: NAV_TYPE[canonical] };
    // A product family is a destination, not a filter toggle: it clears
    // everything else, because that is what a nav item promises.
    else if (umbrellas[canonical]) target = { control: "umbrella", value: canonical,
                                              page: true };
    else if (families[canonical]) target = { control: "hubFilterProduct", value: canonical };
    else if (stages[canonical]) target = { control: "hubFilterStage", value: canonical };
    if (!target) return;              // Favorites, Request New Asset, ...

    navTargets[name] = target;
    item.style.cursor = "pointer";

    // Home's own action (close-request in static/js/hub-ui.js) only
    // half-restores the catalogue from underneath a details page;
    // exitOverlays() below does the whole job, that half included.
    if (name === "Home") item.removeAttribute("data-action");

    item.addEventListener("click", function () {
      // Every nav click leaves the details page. Seb asked for a sidebar
      // that switches the page; the alternative -- an inert sidebar while a
      // details page is open -- is the behaviour he reported as broken.
      exitOverlays();
      if (!target.control) {
        clearAll();
        if (target.sort) { navFilter.sort = target.sort; navFilter.order = null; applyFilters(); }
      }
      else if (target.page) { openFamily(target.value); }
      else {
        // Re-read the control every time: takeOverControls() replaces these
        // nodes to drop Elio's listeners, so a captured reference would be
        // pointing at an element no longer in the document.
        var el = document.getElementById(target.control);
        if (!el) return;
        // Clicking the group you are already in leaves it, so the nav has
        // an exit of its own rather than only the dropdown beside it.
        el.value = (el.value === target.value) ? "" : target.value;
        applyFilters();
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

/* Nav entries that cannot do anything.
 *
 * Elio's sidebar promises five things this catalogue cannot deliver, and a
 * control that looks live and does nothing is the most expensive kind of
 * wrong: the reader concludes the app is broken rather than that the data is
 * missing. Each is dimmed, made unclickable, and given the reason on hover.
 *
 * Two are empty categories and may fill up later; three need data nobody
 * collects yet. Either way the honest state is visible rather than implied.
 */
//: Nav items whose count is deliberately absent, so fillSidebarCounts leaves
//: them alone rather than clearing an element that was never there.
var NO_COUNT_GROUPS = ["browse by product"];

var UNAVAILABLE = {
  "Favorites": "Favourites need a per-user store, which the Hub does not have yet",
  "Most Viewed": "No view counts for most assets yet, so a ranking would "
               + "leave most of the catalogue out",
  "Virtual Machines": "No virtual machines in the catalogue yet",
  "Post-Sale": "No assets are tagged Post-Sale yet"
};

/* Of the unavailable items, the ones removed outright rather than dimmed.
 *
 * Dimming says "not yet"; it is the right answer for Virtual Machines and
 * Post-Sale, which are empty categories that will light up on their own the
 * day something lands in them. These two are not waiting on the catalogue --
 * Favorites needs a per-user store and Most Viewed needs SharePoint view
 * counts, and neither is being built -- so a permanently greyed row is just
 * a promise the sidebar cannot keep. Liwei's call, 2026-09-03.
 *
 * Remove a label from this list to get its dimmed version back; the reason
 * text in UNAVAILABLE is kept either way. */
var HIDE_UNAVAILABLE = ["Most Viewed", "Favorites"];

function markUnavailable(facets) {
  var live = {};
  ["types", "funnel_stages", "product_families", "segments"].forEach(function (k) {
    (facets[k] || []).forEach(function (f) { if (f.count) live[f.value] = 1; });
  });
  Object.keys(NAV_TYPE).forEach(function (label) {
    if (live[NAV_TYPE[label]]) live[label] = 1;
  });
  // Every umbrella counts as live, including the empty ones. IPE is on the
  // list because its demos are being made now, so dimming it would report a
  // plan as a fault.
  (facets.umbrella_families || []).forEach(function (f) { live[f.value] = 1; });

  document.querySelectorAll(".orion-navitem").forEach(function (item) {
    var name = navLabel(item);
    var reason = UNAVAILABLE[name];
    // Only dim it if the catalogue really has nothing -- if VMs appear
    // tomorrow the item must come back to life on its own.
    if (!reason || live[name]) return;
    // An inline style, not a class: Elio's .orion-navitem sets its own
    // display, and a stylesheet rule of equal specificity loses to whichever
    // is declared later in a 2.5 MB file. Inline always wins.
    if (HIDE_UNAVAILABLE.indexOf(name) !== -1) {
      item.style.display = "none";
      return;
    }
    item.classList.add("hub-nav--dead");
    item.title = reason;
    item.style.cursor = "default";
    item.addEventListener("click", function (e) {
      e.stopImmediatePropagation(); e.preventDefault();
    }, true);
  });
}

function navLabel(item) {
  var label = item.querySelector(".label");
  if (!label) return "";
  var name = "";
  label.childNodes.forEach(function (n) {
    if (!name && n.nodeType === Node.TEXT_NODE && n.textContent.trim()) {
      name = n.textContent.trim();
    }
  });
  return name || label.textContent.trim();
}

/* Derived from the controls rather than set alongside them, so the highlight
 * is correct however the filter was chosen -- nav, dropdown, or product
 * tile. Home lights up when nothing is filtered at all. */
function markNavActive() {
  var anyOn = !!navFilter.sort || !!navFilter.umbrella || !!navFilter.tag || CONTROLS.some(function (id) {
    var el = document.getElementById(id);
    return el && el.value;
  });
  document.querySelectorAll(".orion-navitem").forEach(function (item) {
    var target = navTargets[navLabel(item)];
    var on = false;
    if (target && !target.control) {
      // Home and Latest Uploads both have control:null, so one test used to
      // cover both -- lighting the pair together on the home page, and
      // neither once Latest Uploads set a sort. The sort is what tells them
      // apart: Home is "nothing is on", Latest Uploads is "this sort is on".
      on = target.sort ? navFilter.sort === target.sort : !anyOn;
    }
    else if (target && target.control === "umbrella") {
      on = navFilter.umbrella === target.value;
    }
    else if (target) {
      var el = document.getElementById(target.control);
      on = !!el && el.value === target.value;
    }
    item.classList.toggle("is-active", on);
    // The class that actually shows. `is-active` is ours and has no rule
    // behind it in 2.5 MB of stylesheet; orion-navitem--active is Elio's and
    // is what draws the highlight. Toggling only ours meant the highlight
    // sat wherever his markup left it, which was Home, for ever.
    item.classList.toggle("orion-navitem--active", on);
  });
}

/* ------------------------------------------------------ segment pages */

/* Elio's nav browses by product. Nineteen product families exist and the
 * tail runs down to one asset each, so a page per product would be mostly
 * empty rooms. Six segments cover the same catalogue at a size worth
 * visiting -- CAD 402, PLM 250, ALM 102, IoT 78, SLM 35, SCO 1 -- so the
 * group becomes Browse by Segment and products stay a filter.
 *
 * Built from the API rather than edited into the markup, because the
 * hardcoded list was already wrong: it offers IPL, which matches nothing in
 * the catalogue, and omits IoT, which has 78 demos.
 */

/* The page shows a spinner until this succeeds, and Elio's placeholder cards
 * are never revealed -- Liwei's rule: a blank screen is fine, the mock-up is
 * not, not even for a frame. Placeholder data is indistinguishable from real
 * data to anyone who has not read the source, and a tile claiming 1,204
 * views is worse than an empty page.
 *
 * So a failure has to SAY so. Every early return in boot() lands here. */
/* ── the sidebar foot: feedback, and which build this is ──────────────
 *
 * Both requested by Seb (2026-09-22) ahead of opening the Hub to the whole
 * team, and they work as a pair: the version is what makes a piece of
 * feedback actionable, because "the filter is broken" and "the filter is
 * broken on v2026.1.47" are different reports.
 *
 * Built here rather than in index.html for the usual reason -- that file is
 * Elio's, and the integration contract is one script tag and no edits. The
 * foot already exists and holds the PTC mark; this appends to it.
 */
var FEEDBACK_URL =
  "https://app.smartsheet.com/b/form/019fd30ea3ee75c7aaf4abf2e58a0342";

/* "3 h ago", "2 days ago": how long since, roughly. */
function agoLabel(when) {
  var minutes = Math.max(0, Math.round((Date.now() - when.getTime()) / 60000));
  if (minutes < 60) return minutes <= 1 ? "just now" : minutes + " min ago";
  var hours = Math.round(minutes / 60);
  if (hours < 24) return hours + " h ago";
  var days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : days + " days ago";
}

function buildSidebarFoot() {
  var foot = document.querySelector(".orion-side__foot");
  if (!foot || foot.querySelector(".hub-foot__row")) return;

  var link = document.createElement("a");
  link.className = "hub-foot__feedback";
  link.href = FEEDBACK_URL;
  // A new tab, not a navigation: somebody writing feedback has the thing
  // they are describing on screen, and taking the page away from them to
  // show a form is how half-written feedback gets lost.
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.innerHTML =
    '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    + '<path d="M2 3.2A1.2 1.2 0 0 1 3.2 2h9.6A1.2 1.2 0 0 1 14 3.2v7.1'
    + 'a1.2 1.2 0 0 1-1.2 1.2H6.3L3.2 14v-2.5A1.2 1.2 0 0 1 2 10.3z"'
    + ' fill="none" stroke="currentColor" stroke-width="1.3"'
    + ' stroke-linejoin="round"/></svg>'
    + "<span>Share feedback</span>";
  // The shared form covers more than this Hub, so say where it goes rather
  // than let the click be a surprise.
  link.title = "Opens PTC's feedback form in a new tab";

  var row = document.createElement("div");
  row.className = "hub-foot__row";
  var mark = foot.querySelector(".orion-logo");
  if (mark) row.appendChild(mark);
  var version = document.createElement("span");
  version.className = "hub-foot__version";
  version.textContent = "";
  row.appendChild(version);

  foot.insertBefore(link, foot.firstChild);
  foot.appendChild(row);

  addActivityNav();
  addReviewNav();

  // Fire-and-forget: an unreachable version endpoint leaves the label empty
  // rather than an apology, and nothing else on the page depends on it.
  fetch("/api/version")
    .then(function (r) { return r.json(); })
    .then(function (d) { version.textContent = d.version || ""; })
    .catch(function () {});

  // How fresh the catalogue is (Summit, 2026-10): SharePoint is read twice
  // a day, so a change made there shows up after the next run.
  fetch("/api/assets/freshness")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || !d.updated_at) return;
      var when = new Date(d.updated_at.replace(/Z?$/, "Z"));
      if (isNaN(when)) return;
      var line = document.createElement("div");
      line.className = "hub-foot__fresh";
      line.textContent = "Catalogue updated " + agoLabel(when);
      var hours = (d.hours_utc || []).map(function (h) {
        var t = new Date(); t.setUTCHours(h, 0, 0, 0);
        return t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      });
      line.title = "Updated " + when.toLocaleString() + ". "
        + (hours.length ? "Refreshed from SharePoint twice a day, at " + hours.join(" and ")
                          + " your time; c" : "C")
        + "hanges made in SharePoint appear after the next refresh. "
        + "Demos created in the Hub appear at once.";
      foot.insertBefore(line, row);
    })
    .catch(function () {});

  // Who is signed in, and the way out -- only when the app does its own
  // sign-in (AUTH_MODE=oidc). Under Easy Auth the platform owns sign-out,
  // and locally there is nobody to sign out, so nothing is shown.
  // Seb, 2026-09-25: between Share feedback and the PTC mark rather than
  // under the mark, and the name easy to read -- it was muted 11.5px.
  fetch("/api/auth/me")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || d.mode !== "oidc" || !d.user || !d.user.is_authenticated) return;
      var who = document.createElement("div");
      who.className = "hub-foot__who";
      var name = document.createElement("span");
      name.textContent = d.user.name || d.user.email || "Signed in";
      name.title = d.user.email || "";
      var out = document.createElement("a");
      out.href = "/logout";
      out.textContent = "Sign out";
      who.appendChild(name);
      who.appendChild(out);
      foot.insertBefore(who, row);
    })
    .catch(function () {});
}

/* Browse by Product, from the umbrella list.
 *
 * This replaces Browse by Segment, which all three of them asked for in the
 * review -- Elio "I would remove the segment", Seb "I would do it by
 * product", Serge "I agree, remove the segment". The objection that sent us
 * to segments in the first place was that nineteen derived families have a
 * tail of ones and twos; a curated list of eight answers it, which is why
 * the reversal is coherent rather than a change of mind.
 *
 * Built from the API in the team's own order, including families at zero:
 * IPE is on the list because its demos are being made now, and a family
 * that appeared only once content landed would look like a bug.
 */

//: Product hex marks for the Browse by Product nav, keyed by the umbrella
//: facet's own value -- so Orbit/Jetstream carry the "PTC " prefix
//: FAMILY_ROLLUP (taxonomy.py) already bakes into that facet, same
//: gotcha as FAMILY_MARK's comment above but the opposite convention.
//: Reuses the four existing sprite hex marks (logo-*-mark, the same ones
//: FAMILY_MARK draws on card covers) plus, for the three products with no
//: dedicated mark art, the real PTC corporate mark (logo-ptc-mark -- see
//: FAMILY_MARK's comment above) -- Liwei, 2026-09-10, after the
//: full-wordmark "logo-only button" version read too small/inconsistent
//: (see git history same date): back to Elio's original icon+text
//: nav-mark pattern, matching index.mockup.original.html.
var NAV_MARK = {
  "Windchill":     ["logo-windchill-mark", "0 0 259.46 299.60"],
  "Creo":          ["logo-creo-mark", "0 0 397.21 449.90"],
  "ServiceMax":    ["logo-servicemax-mark", "0 0 71.14 82.15"],
  "Codebeamer":    ["logo-codebeamer-mark", "0 0 261.71 300.76"],
  "PTC Orbit":     ["logo-ptc-mark", "0 0 284.42 325.42"],
  "PTC Jetstream": ["logo-ptc-mark", "0 0 284.42 325.42"],
  "IPE":           ["logo-ptc-mark", "0 0 284.42 325.42"]
};

function navMarkHtml(value) {
  var m = NAV_MARK[value];
  if (!m) return "";
  return '<svg class="nav-mark" viewBox="' + m[1] + '"><use href="#' + m[0] + '"/></svg> ';
}

async function buildFamilyNav(facets) {
  var heading = null;
  document.querySelectorAll(".orion-group").forEach(function (g) {
    var t = g.textContent.trim().toLowerCase();
    if (t === "browse by product" || t === "browse by segment") heading = g;
  });
  if (!heading) return;

  var families = facets.umbrella_families || [];
  if (!families.length) return;      // keep the markup rather than empty it

  var node = heading.nextElementSibling;
  while (node && node.classList.contains("orion-navitem")) {
    var next = node.nextElementSibling;
    node.remove();
    node = next;
  }
  heading.textContent = "Browse by Product";

  var anchor = heading;
  families.forEach(function (f) {
    // A business decision, not a data one -- Servigistics has assets.
    // See HIDDEN_UMBRELLAS.
    if (HIDDEN_UMBRELLAS.indexOf(f.value) !== -1) return;

    var item = document.createElement("div");
    item.className = "orion-navitem";
    /* No count, deliberately.
     *
     * There are two honest numbers for "Creo" and they disagree: 422 as an
     * umbrella (Mathcad rolls into it) and 379 as a derived family. The
     * sidebar was showing the second while the results showed the first,
     * because fillSidebarCounts looks a label up across several facets and
     * `product_families` came first in that list.
     *
     * Fixing the lookup would have made the number right and still left it
     * confusing: these counts are scoped to the active filters, so choosing
     * Codebeamer correctly showed Creo as 0 — "Creo AND Codebeamer" really
     * is empty — which reads as though Creo had emptied out. A navigation
     * group is a set of destinations, and a destination does not need a
     * quantity. The results heading already says how many are there.
     *
     * Marks added 2026-09-10 -- Seb, review: "Can we add the product
     * logos for the Products?" See NAV_MARK above. Servigistics is hidden
     * from this nav regardless (§8.6).
     */
    item.innerHTML = '<span class="label">' + navMarkHtml(f.value)
      + escapeHtml(umbrellaDisplayName(f.value)) + '</span>';
    anchor.after(item);
    anchor = item;
  });
}

/* Opening a segment clears every other filter. That is the whole difference
 * between a nav item and a dropdown: one takes you somewhere, the other
 * narrows where you already are. Choosing Creo and then Windchill in the nav
 * used to leave you the intersection, which is not what a sidebar promises.
 */
function openFamily(name) {
  CONTROLS.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.value = "";
  });
  navFilter.umbrella = name;
  applyFilters();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* A tag chip on a details page: show everything else carrying that tag.
 *
 * Clears the other filters for the same reason openFamily() does -- this is
 * a destination, not a narrowing of wherever you happened to be, and
 * landing on "3 results" because a stale Segment was still set would read
 * as the tag being rare rather than the filters being stacked. It also
 * leaves the details page, since the grid it is about to change is behind
 * it. */
function openTag(tag) {
  exitOverlays();
  CONTROLS.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.value = "";
  });
  navFilter.umbrella = null;
  navFilter.sort = null;
  navFilter.tag = tag;
  applyFilters();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* The segment landing page is gone. All three of them asked for segments
 * to stop being the way in, and a page for a dimension nobody browses by is
 * a page nobody opens. What it did well -- a description and an owner --
 * belongs on whatever replaces it, and /api/segments still serves both.
 */
function renderSegmentHeader() {
  var host = document.getElementById("hubSegmentPage");
  if (host) { host.style.display = "none"; host.innerHTML = ""; }
}

export {
  buildFamilyNav, buildSidebarFoot, exitOverlays, familyDisplayName,
  HIDDEN_UMBRELLAS, markNavActive, markUnavailable, NAV_TYPE, navMarkHtml,
  NO_COUNT_GROUPS, openFamily, openTag, renderSegmentHeader,
  umbrellaDisplayName, wireNav
};
