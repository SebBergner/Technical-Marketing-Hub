/* Feeds Elio's UI from the live API.
 *
 * Deliberately a separate file with a one-line hook in index.html. Elio owns
 * that file and is still working in it; every line this adds there is a merge
 * conflict waiting to happen, so the integration lives out here instead.
 *
 * How it attaches
 * ---------------
 * index.html already has the seam. `hubApplyFilters()` reads a module-level
 * `HUB_ASSET_POOL`, and only builds it from the hardcoded cards when it is
 * still empty:
 *
 *     if (!HUB_ASSET_POOL) buildAssetPool();
 *
 * So filling that variable before anyone touches a filter is enough. Nothing
 * in the existing filter code changes, and if this file fails or the API is
 * down the page falls back to the static cards on its own.
 *
 * The cards themselves are built by Elio's `videoAssetFromData()`, not by a
 * copy of it here — his markup and CSS stay the single source of truth, and a
 * redesign on his side carries over without anyone editing this file.
 */
(function () {
  "use strict";

  /* The API caps `limit` at 200 -- a deliberate guard rail, so page through it
   * rather than asking for more. Asking for 1000 returns a 422 that looks like
   * an empty catalogue if you only check for items. */
  var PAGE_SIZE = 200;
  var MAX_PAGES = 20;           // 4,000 assets; the catalogue is ~950
  var FUNNEL_UNKNOWN = "";
  var RAIL_SIZE = 6;

  /* Sections the landing page shows that we have no honest data for. Editor's
   * Picks needs curation nobody has done; Continue needs per-user history we
   * do not collect. Leaving them filled with sample cards would put invented
   * content beside real content with nothing to tell them apart, which is
   * worse than a shorter page. Set to [] to show them again. */
  var HIDE_UNTIL_REAL = ["editorsPicksSection", "continueSection"];

  /* ---------------------------------------------------------------- mapping */

  function durationLabel(seconds) {
    if (!seconds) return "";
    var m = Math.floor(seconds / 60), s = seconds % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function uploadedLabel(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return "";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  /* The stats line, assembled from whatever the record actually has.
   * `external_views` is the source platform's count, not ours, and most
   * SharePoint assets have none — so the line is built from the parts that
   * exist rather than printing "0 views" for everything. */
  function statsLine(a) {
    var bits = [];
    if (a.external_views) bits.push(a.external_views + " views");
    if (a.resource_count) bits.push(a.resource_count + " files");
    if (a.uploaded_at) bits.push("Uploaded " + uploadedLabel(a.uploaded_at));
    return bits.join(" · ");
  }

  /* Our asset -> the shape videoAssetFromData() expects. */
  function toCardData(a) {
    var product = (a.products && a.products[0]) || "";
    return {
      title: a.title || "",
      desc: a.description || statsLine(a),
      thumb: a.thumbnail_url || "",
      duration: durationLabel(a.duration_seconds),
      product: product,
      segment: a.segment || "",
      industry: a.industry || "",
      funnel: a.funnel_stage || FUNNEL_UNKNOWN,
      // The UI's yes/no; anything not explicitly customer-facing is "no".
      cf: a.customer_facing ? "yes" : "no",
      // Only offer Share when a share is actually possible. Without a Consensus
      // uuid the button would be a dead end, and the UI already has a sensible
      // fallback badge for that case.
      share: a.consensus_uuid ? {
        title: a.title,
        meta: [a.segment, a.funnel_stage].filter(Boolean).join(" · "),
        uuid: a.consensus_uuid
      } : null
    };
  }

  /* Where a result came from. Two platforms hold different things — a kit to
   * run versus a recording to send — so a card that does not say which is
   * asking the reader to guess. */
  function sourceBadge(source) {
    var badge = document.createElement("span");
    badge.className = "orion-badge hub-source hub-source--" + source;
    badge.textContent = source === "consensus" ? "Consensus" : "SharePoint";
    badge.title = source === "consensus"
      ? "A recorded video, ready to send to a customer"
      : "A demo kit from SharePoint, to run yourself";
    return badge;
  }

  /* Elio's own static cards already establish the convention: a kit is a box,
   * a VDK a monitor, a recording a video camera. videoAssetFromData() hardcodes
   * the video one because it was written for Consensus content. */
  var TYPE_CHIP = {
    video: ["i-video", "Video"],
    ldk:   ["i-box", "LDK"],
    vdk:   ["i-monitor", "VDK"],
    vm:    ["i-monitor", "Virtual Machine"]
  };

  function retypeCard(card, a) {
    var chip = card.querySelector(".type-chip");
    var spec = TYPE_CHIP[a.type] || TYPE_CHIP.video;
    if (chip) {
      chip.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#'
                     + spec[0] + '"/></svg>' + spec[1];
    }

    /* The play button was on every card and did nothing on most of them.
     * A Consensus record IS a recording, so it plays -- in the Consensus
     * player, which is where the video actually lives. A SharePoint demo kit
     * is a folder of files with no single thing to play, so the control is
     * removed rather than left there inert. */
    var play = card.querySelector(".play-btn");
    if (!play) return;
    if (a.source === "consensus" && a.web_url) {
      var link = document.createElement("a");
      link.className = "play-btn";
      link.href = a.web_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.title = "Play in Consensus";
      link.innerHTML = play.innerHTML;
      link.style.cursor = "pointer";
      play.replaceWith(link);
    } else {
      play.remove();
    }
  }

  /* Distribution platforms an asset can be acted on, keyed by the field that
   * proves it is actually there. Adding Brightcove or Velocity later means one
   * entry here and nothing else.
   *
   * `sprite` is looked up in the page's SVG symbol set. Consensus has no mark
   * in there yet, so the button falls back to an icon and the platform name --
   * and the moment someone drops a <symbol id="logo-consensus"> into
   * index.html it starts using it, with no change here. */
  /* Distribution platforms an asset can be acted on.
   *
   * `field` is what proves the asset is really there; `home` is the source
   * value for which this platform IS the asset's home rather than a
   * cross-reference. Adding Brightcove later means one entry here and nothing
   * else.
   */
  var PLATFORMS = [
    {
      key: "consensus",
      field: "consensus_uuid",
      home: "consensus",
      label: "Consensus",
      verb: "Share Demo",
      sprite: "logo-consensus",
      icon: "i-send"
    }
  ];

  function spriteExists(id) {
    return !!document.getElementById(id);
  }

  /* Rebuild the card's action area from the platforms the asset is genuinely
   * on -- and in the form that matches what the platform IS to that asset.
   *
   * A Consensus demo exists in order to be shared, so Consensus is its home
   * and it keeps the full "Share Demo" button, in Consensus colours. A
   * SharePoint kit that merely happens to have a Consensus recording gets the
   * mark alone: a real but secondary affordance, and one that stays legible
   * when a third and fourth platform appear beside it. Home platforms get the
   * verb, references get the logo.
   *
   * Nothing at all is rendered for a platform the asset is NOT on.
   * videoAssetFromData() shipped a "No audio track" badge in this slot, which
   * was the mockup's only reason for being unshareable and the wrong reason
   * here. Labelling every absence does not scale either -- with three
   * platforms each card would carry a row of things it is not.
   */
  function platformActions(card, a) {
    var actions = card.querySelector(".asset-card__actions");
    if (!actions) return;

    var available = PLATFORMS.filter(function (p) { return a[p.field]; });
    if (!available.length) {
      actions.remove();          // say nothing rather than say "not available"
      return;
    }

    // The home platform first: it is the primary action on the card.
    available.sort(function (x, y) {
      return (y.home === a.source) - (x.home === a.source);
    });

    actions.innerHTML = "";
    available.forEach(function (p) {
      var isHome = p.home === a.source;
      var btn = document.createElement("button");
      btn.className = "btn-primary-sm hub-platform hub-platform--" + p.key
                    + (isHome ? " hub-platform--home" : " hub-platform--ref");
      btn.title = isHome ? p.verb : "Also on " + p.label + " -- share that copy";
      btn.setAttribute("aria-label", btn.title);

      if (isHome) {
        // Text alone: at a third of the tile there is no room for a mark
        // beside it, and the orange outline already says which platform.
        btn.textContent = p.verb;
      } else {
        btn.innerHTML = spriteExists(p.sprite)
          ? '<svg class="hub-platform__logo"><use href="#' + p.sprite + '"/></svg>'
          : '<svg class="orion-ico--sm orion-ico"><use href="#' + p.icon
            + '"/></svg>' + p.label;
      }

      btn.addEventListener("click", function () { openShareFor(a); });
      actions.appendChild(btn);
    });
  }

  /* The description lands in Elio's stats slot, which in the mockup holds one
   * short line -- "214 views - Uploaded Jul 21", about 80 characters. Real
   * SharePoint descriptions run to a median of 166 and a maximum of 1194, with
   * no clamp on them, so cards ranged from 286px to 709px and the grid came
   * out ragged.
   *
   * Three lines, and the full text on hover so nothing is actually lost. The
   * class matters: the same element holds a real stats line on the static
   * cards, and clamping that would be wrong.
   */
  function clampDescription(card, a) {
    var el = card.querySelector(".asset-card__stats");
    if (!el || !a.description) return;
    el.classList.add("hub-desc");
    el.title = a.description;
  }

  function buildCard(a) {
    var card = window.videoAssetFromData(toCardData(a));
    // videoAssetFromData hardcodes type=video, which is right for Consensus
    // but wrong for the demo kits; the type filter reads this attribute.
    card.dataset.type = a.type || "video";
    card.dataset.source = a.source || "";
    card.dataset.assetId = a.id || "";

    retypeCard(card, a);
    platformActions(card, a);
    clampDescription(card, a);
    paintCover(card, a);

    var meta = card.querySelector(".asset-card__meta");
    if (meta) meta.insertBefore(sourceBadge(a.source), meta.firstChild);

    // A Consensus result is useless without a way to open it.
    if (a.web_url) {
      var title = card.querySelector(".asset-card__title");
      if (title) {
        var link = document.createElement("a");
        link.href = a.web_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = title.textContent;
        title.textContent = "";
        title.appendChild(link);
      }
    }
    return card;
  }

  /* ------------------------------------------------------------- filters UI */

  /* Fill a <select> from a facet, keeping whatever "all" option is already
   * there as the first entry. Counts come along because "Creo (319)" tells you
   * whether a filter is worth clicking. */
  function fillSelect(id, facet) {
    var el = document.getElementById(id);
    if (!el || !facet || !facet.length) return;

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
        o.textContent = (labels[f.value] || f.value) + " (" + f.count + ")";
        el.appendChild(o);
      });
  }

  /* -------------------------------------------------------------- the rails */

  /* Replace the cards inside one curated row, leaving its heading alone. */
  function fillRail(sectionId, assets) {
    var row = document.querySelector("#" + sectionId + " .asset-row");
    if (!row) return 0;
    row.innerHTML = "";
    assets.forEach(function (a) { row.appendChild(buildCard(a)); });
    return assets.length;
  }

  function byNewest(a, b) {
    return String(b.uploaded_at || "").localeCompare(String(a.uploaded_at || ""));
  }

  function byViews(a, b) {
    return (b.external_views || b.stats?.views || 0)
         - (a.external_views || a.stats?.views || 0);
  }

  function fillRails(assets) {
    fillRail("latestUploadsSection",
             assets.filter(function (a) { return a.uploaded_at; })
                   .sort(byNewest).slice(0, RAIL_SIZE));

    // Only Consensus reports view counts, so this rail is Consensus-heavy by
    // nature rather than by choice. Assets with none are excluded outright
    // instead of padding the row with zeroes.
    fillRail("mostViewedSection",
             assets.filter(function (a) { return (a.external_views || 0) > 0; })
                   .sort(byViews).slice(0, RAIL_SIZE));

    // A class, not an inline style: hubApplyFilters() resets
    // `style.display = ''` on these sections every time no filter is active,
    // so an inline hide lasts only until the next keystroke.
    HIDE_UNTIL_REAL.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.add("hub-hidden");
    });
  }

  /* ------------------------------------------------------------- the sidebar */

  /* The left nav ships with hardcoded counts -- Creo 24, Videos 86. Against a
   * real catalogue of 382 and 491 those are not merely stale, they contradict
   * what the same page shows two panels away. Numbers nobody can reconcile are
   * worse than no numbers, so each one is either corrected or removed. */
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
                       "Virtual Machines": "vm" };
    (facets.types || []).forEach(function (f) {
      Object.keys(typeLabels).forEach(function (label) {
        if (typeLabels[label] === f.value) counts[label] = f.count;
      });
    });

    var updated = 0, cleared = 0;
    document.querySelectorAll(".orion-navitem").forEach(function (item) {
      var label = item.querySelector(".label");
      var count = item.querySelector(".count");
      if (!label || !count) return;
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
                  "hubFilterSegment", "hubFilterStage", "hubFilterCf"];
  var LANDING = ["continueSection", "latestUploadsSection", "mostViewedSection",
                 "browseByProductSection", "editorsPicksSection"];
  var RESULT_LIMIT = 200;        // the API's own ceiling, and plenty to scroll
  var inFlight = 0;
  var baselineFacets = null;     // whole-catalogue counts, for when all clear
  /* An explicit sort, when something other than the default is wanted -- the
   * Latest Uploads view, and the segment pages, whose grid must NOT repeat the
   * ten cards already in the rail above it. Both default to recency otherwise,
   * and the overlap was exactly 10 of 10. */
  var sortOverride = null;

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
    var cf = val("hubFilterCf");
    if (cf === "yes") params.set("customer_facing", "true");
    if (cf === "no") params.set("customer_facing", "false");
    return params;
  }

  /* The sort is not part of the facet query -- counts do not depend on order
   * -- so it is added only where results are fetched. */
  function effectiveSort() {
    if (sortOverride) return sortOverride;
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

  async function applyFilters() {
    var params = currentQuery();
    var active = params.toString().length > 0 || !!sortOverride;

    markNavActive();
    renderSuggestions(val("hubSearchInput"));
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
      if (baselineFacets) fillSidebarCounts(baselineFacets);
      return;
    }
    if (all) all.style.display = "";

    var ticket = ++inFlight;
    var assetParams = new URLSearchParams(params);
    assetParams.set("limit", RESULT_LIMIT);
    var sort = effectiveSort();
    if (sort) assetParams.set("sort", sort);

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
    grid.innerHTML = "";
    page.items.forEach(function (a) { grid.appendChild(buildCard(a)); });

    // "All Assets" under a PLM page is misleading -- they are all PLM assets.
    var heading = document.querySelector("#allAssetsSection .section-head__title");
    if (heading) {
      var seg = val("hubFilterSegment");
      var node = heading.firstChild;
      while (node) {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
          node.textContent = sortOverride === "recent" ? " Latest uploads "
                           : seg ? " All " + seg + " assets "
                           : " All Assets ";
          break;
        }
        node = node.nextSibling;
      }
    }

    var count = document.getElementById("allAssetsCount");
    if (count) {
      count.textContent = page.total > page.items.length
        ? "(showing " + page.items.length + " of " + page.total + ")"
        : "(" + page.total + ")";
    }

    // Scoped counts: this is what makes the panel honest once anything is on.
    rescoreSelect("hubFilterType", facets.types);
    rescoreSelect("hubFilterProduct", facets.product_families);
    rescoreSelect("hubFilterSegment", facets.segments);
    rescoreSelect("hubFilterStage", facets.funnel_stages);
    // The sidebar shows the same three dimensions, so it takes the same
    // numbers. Leaving it on whole-catalogue counts would reintroduce, one
    // panel over, exactly the contradiction this is meant to remove.
    fillSidebarCounts(facets);

    var none = document.querySelector(".hub-noresults");
    if (none) none.classList.toggle("show", page.total === 0);
  }

  function debounce(fn, ms) {
    var t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  /* Elio binds his handler with addEventListener, which captures the function
   * reference -- reassigning the global would leave his version still wired up
   * and fighting this one. Cloning each control drops its listeners outright,
   * which is the only reliable way to take them over. */
  function takeOverControls() {
    var debounced = debounce(applyFilters, 200);
    CONTROLS.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var fresh = el.cloneNode(true);
      el.replaceWith(fresh);
      fresh.addEventListener(fresh.tagName === "INPUT" ? "input" : "change",
                             debounced);
    });
    var reset = document.getElementById("hubResetBtn");
    if (reset) {
      var freshReset = reset.cloneNode(true);
      reset.replaceWith(freshReset);
      freshReset.addEventListener("click", clearAll);
    }
    window.hubApplyFilters = applyFilters;   // for anything else that calls it
  }

  function clearAll() {
    CONTROLS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = "";
    });
    sortOverride = null;
    applyFilters();
  }

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
                   "Virtual Machines": "vm" };
  var navTargets = {};   // nav label -> {control, value, page}

  function wireNav(facets) {
    var families = {}, stages = {}, segments = {};
    (facets.product_families || []).forEach(function (f) { families[f.value] = 1; });
    (facets.funnel_stages || []).forEach(function (f) { stages[f.value] = 1; });
    (facets.segments || []).forEach(function (f) { segments[f.value] = 1; });

    navTargets = {};
    document.querySelectorAll(".orion-navitem").forEach(function (item) {
      var name = navLabel(item);
      var target = null;
      if (name === "Home") target = { control: null };
      else if (name === "Latest Uploads") target = { control: null, sort: "recent" };
      else if (NAV_TYPE[name]) target = { control: "hubFilterType", value: NAV_TYPE[name] };
      // A segment is a destination, not a filter toggle: it opens a page and
      // clears everything else, because that is what a nav item promises.
      else if (segments[name]) target = { control: "hubFilterSegment", value: name,
                                          page: true };
      else if (families[name]) target = { control: "hubFilterProduct", value: name };
      else if (stages[name]) target = { control: "hubFilterStage", value: name };
      if (!target) return;              // Favorites, Request New Asset, ...

      navTargets[name] = target;
      item.style.cursor = "pointer";
      item.addEventListener("click", function () {
        if (!target.control) {
          clearAll();
          if (target.sort) { sortOverride = target.sort; applyFilters(); }
        }
        else if (target.page) { openSegment(target.value); }
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
  var UNAVAILABLE = {
    "Favorites": "Favourites need a per-user store, which the Hub does not have yet",
    "Most Viewed": "No view counts for SharePoint assets yet, so any ranking "
                 + "would show Consensus only",
    "Virtual Machines": "No virtual machines in the catalogue yet",
    "Post-Sale": "No assets are tagged Post-Sale yet"
  };

  function markUnavailable(facets) {
    var live = {};
    ["types", "funnel_stages", "product_families", "segments"].forEach(function (k) {
      (facets[k] || []).forEach(function (f) { if (f.count) live[f.value] = 1; });
    });
    Object.keys(NAV_TYPE).forEach(function (label) {
      if (live[NAV_TYPE[label]]) live[label] = 1;
    });

    document.querySelectorAll(".orion-navitem").forEach(function (item) {
      var name = navLabel(item);
      var reason = UNAVAILABLE[name];
      // Only dim it if the catalogue really has nothing -- if VMs appear
      // tomorrow the item must come back to life on its own.
      if (!reason || live[name]) return;
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
    var anyOn = !!sortOverride || CONTROLS.some(function (id) {
      var el = document.getElementById(id);
      return el && el.value;
    });
    document.querySelectorAll(".orion-navitem").forEach(function (item) {
      var target = navTargets[navLabel(item)];
      var on = false;
      if (target && !target.control) on = !anyOn;                  // Home
      else if (target) {
        var el = document.getElementById(target.control);
        on = !!el && el.value === target.value;
      }
      item.classList.toggle("is-active", on);
    });
  }

  /* ---------------------------------------------------- the share modal */

  /* Elio's DemoBoard modal was a mockup and said so nowhere: two hardcoded
   * bobcat.com recipients that could not be removed, an "Add email" box wired
   * to nothing, a fake link, and -- the dangerous part -- the line "Sent to 2
   * recipients", displayed without a single network call having been made.
   *
   * The backend endpoint existed and was never called. Both halves are joined
   * here, against the contract as the live API actually answers it:
   *
   *   organization  required for a trackable DemoBoard -- Consensus rejects
   *                 the call without it. This is NOT the opportunity field.
   *   share_to[]    keyed on `contact_email`, not `email`. first_name and
   *                 last_name are the working name keys.
   *   isTest        creates the board flagged as a test so it stays out of
   *                 reporting. Default on, because the alternative emails
   *                 real people.
   */
  var shareAsset = null;                 // the asset the modal is open for
  var shareRecipients = [];              // {email, first_name, last_name}

  /* Accepts a bare address or "Jane Doe <jane@co.com>", because that is the
   * form people paste out of a mail client. */
  function parseRecipient(text) {
    var raw = String(text || "").trim().replace(/[,;]+$/, "");
    if (!raw) return null;
    var angled = raw.match(/^(.*?)<([^>]+)>$/);
    var email = (angled ? angled[2] : raw).trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;

    var out = { email: email };
    var name = angled ? angled[1].trim().replace(/^["']|["']$/g, "") : "";
    if (name) {
      var parts = name.split(/\s+/);
      out.first_name = parts[0];
      if (parts.length > 1) out.last_name = parts.slice(1).join(" ");
    }
    return out;
  }

  function renderRecipients() {
    var host = document.getElementById("shareChips");
    var input = document.getElementById("shareRecipientInput");
    if (!host || !input) return;
    host.querySelectorAll(".chip").forEach(function (c) { c.remove(); });

    shareRecipients.forEach(function (r, index) {
      var chip = document.createElement("span");
      chip.className = "chip";
      var label = [r.first_name, r.last_name].filter(Boolean).join(" ");
      chip.textContent = label ? label + " (" + r.email + ")" : r.email;
      var x = document.createElement("button");
      x.className = "chip__x";
      x.type = "button";
      x.textContent = "\u00d7";
      x.title = "Remove " + r.email;
      x.addEventListener("click", function () {
        shareRecipients.splice(index, 1);
        renderRecipients();
      });
      chip.appendChild(x);
      host.insertBefore(chip, input);
    });
  }

  function commitRecipient() {
    var input = document.getElementById("shareRecipientInput");
    var parsed = parseRecipient(input.value);
    if (!parsed) return false;
    if (!shareRecipients.some(function (r) { return r.email === parsed.email; })) {
      shareRecipients.push(parsed);
    }
    input.value = "";
    renderRecipients();
    return true;
  }

  function shareError(message) {
    var box = document.getElementById("shareError");
    if (!box) return;
    box.textContent = message || "";
    box.style.display = message ? "" : "none";
  }

  function wireShareModal() {
    var input = document.getElementById("shareRecipientInput");
    if (!input) return;

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commitRecipient(); }
      // Backspace on an empty box removes the last chip, as every chip input does.
      if (e.key === "Backspace" && !input.value && shareRecipients.length) {
        shareRecipients.pop();
        renderRecipients();
      }
    });
    // Losing focus with a half-typed address must not silently discard it.
    input.addEventListener("blur", commitRecipient);
    input.addEventListener("paste", function (e) {
      var text = (e.clipboardData || window.clipboardData).getData("text");
      if (!text || !/[,;\n]/.test(text)) return;      // single address: let it type
      e.preventDefault();
      text.split(/[,;\n]+/).forEach(function (piece) {
        var parsed = parseRecipient(piece);
        if (parsed && !shareRecipients.some(function (r) { return r.email === parsed.email; })) {
          shareRecipients.push(parsed);
        }
      });
      renderRecipients();
    });

    var button = document.getElementById("generateBtn");
    if (button) {
      button.onclick = null;               // drop Elio's generateShareLink()
      button.addEventListener("click", submitShare);
    }
  }

  async function submitShare() {
    commitRecipient();
    shareError("");

    var org = (document.getElementById("shareOrg").value || "").trim();
    var isTest = document.getElementById("shareIsTest").checked;
    if (!shareAsset) return;
    if (!org) {
      shareError("Consensus needs the account or organisation this DemoBoard is "
               + "for before it will create a trackable share.");
      return;
    }
    if (!shareRecipients.length) {
      shareError("Add at least one recipient. Each one gets their own tracked "
               + "invite, which is what makes a DemoBoard trackable.");
      return;
    }

    var button = document.getElementById("generateBtn");
    var restore = button.innerHTML;
    button.disabled = true;
    button.textContent = isTest ? "Creating test board\u2026" : "Sending\u2026";

    try {
      var response = await fetch("/api/share/consensus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_id: shareAsset.id,
          organization: org,
          opportunity: (document.getElementById("shareOpp").value || "").trim() || null,
          title: shareAsset.title,
          recipients: shareRecipients,
          trackable: true,
          is_test: isTest
        })
      });
      var data = await response.json();
      if (!response.ok) {
        // The endpoint's 409s explain themselves; show that text rather than
        // a generic failure, because it says what to do next.
        shareError(data.detail || ("Share failed (HTTP " + response.status + ")"));
        return;
      }

      document.getElementById("shareLinkText").textContent =
        data.url.replace(/^https?:\/\//, "");
      document.getElementById("shareResultLabel").textContent =
        data.is_test ? "Test DemoBoard created" : "DemoBoard sent";
      // A test board is kept OUT of reporting, so it must not also be
      // promised there -- the two halves of that sentence contradicted.
      document.getElementById("shareResultMeta").textContent = data.is_test
        ? "Flagged as a test: the link works, and it stays out of Consensus "
          + "reporting. Uncheck Test send to make a real one."
        : "Sent to " + shareRecipients.length + " recipient"
          + (shareRecipients.length === 1 ? "" : "s")
          + ". Engagement is visible in Consensus Reports.";
      document.getElementById("shareResult").style.display = "block";
      button.innerHTML = restore;
    } catch (err) {
      shareError("Could not reach the Hub: " + err.message);
    } finally {
      button.disabled = false;
      if (button.textContent.indexOf("\u2026") !== -1) button.innerHTML = restore;
    }
  }

  /* Elio's openShareModal takes three strings and knows nothing about the
   * asset. The share needs its id, so the card hands the whole thing over
   * before delegating to the original for the presentation. */
  function openShareFor(asset) {
    shareAsset = asset;
    shareRecipients = [];
    var meta = [asset.segment, asset.funnel_stage].filter(Boolean).join(" \u00b7 ");
    window.openShareModal(asset.title, meta, asset.consensus_uuid);

    document.getElementById("shareOrg").value = "";
    document.getElementById("shareOpp").value = "";
    document.getElementById("shareRecipientInput").value = "";
    document.getElementById("shareIsTest").checked = true;
    document.getElementById("shareResult").style.display = "none";
    shareError("");
    renderRecipients();
  }

  /* ------------------------------------------------------- cover images */

  /* Not one of the 455 SharePoint assets has a thumbnail, so half the grid was
   * empty rectangles that read as broken rather than as absent. There is also
   * nothing in the folders to make one from: 4 assets contain an image and all
   * four are documentation screenshots (image1.bmp, logo.png,
   * not-ok-warning.png), and no file anywhere is named like a cover.
   *
   * So the cover is derived from what is already known -- product family,
   * type, title -- rather than fetched. Every asset gets one, instantly, with
   * no request and nothing to store, and it can never fail or expire.
   *
   * This is deliberately an identifier and not a photograph. An LDK is a
   * folder of CAD files and a script; there is no picture of it, and a frame
   * grabbed from its walkthrough video would imply it is something to watch.
   * A real poster frame from Consensus still wins where one exists -- this
   * fills in behind it, and behind any future Graph thumbnail too.
   */

  /* Hand-picked for the families people already associate with a colour;
   * everything else is hashed from the name below, so all nineteen get one
   * without nineteen lines of guesswork. */
  var FAMILY_HUE = {
    "Windchill": 212, "Creo": 152, "ThingWorx": 268, "Codebeamer": 22,
    "Mathcad": 194, "ServiceMax": 340, "Arbortext": 42
  };
  var FAMILY_MARK = {
    "Windchill": ["logo-windchill-mark", "0 0 259.46 299.60"],
    "Creo": ["logo-creo-mark", "0 0 397.21 449.90"],
    "ServiceMax": ["logo-servicemax-mark", "0 0 71.14 82.15"],
    "Codebeamer": ["logo-codebeamer-mark", "0 0 261.71 300.76"]
  };

  /* The family comes from the API, not from matching product strings here.
   * The first attempt did match them, and got Kepware wrong: its product is
   * "KEPServerEX", which contains the family name nowhere. The rule that knows
   * that lives in backend/services/taxonomy.py, so the summary now carries its
   * answer and this reads it. One rule, in one place. */
  function coverFamily(a) {
    return (a.product_families || [])[0] || null;
  }

  /* Same name, same colour, always -- an asset must not change appearance
   * between two renders of the same grid. */
  function hueFor(name) {
    if (!name) return 220;
    if (FAMILY_HUE[name] !== undefined) return FAMILY_HUE[name];
    var h = 0;
    for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
    return h;
  }

  function paintCover(card, a) {
    var thumb = card.querySelector(".asset-card__thumb");
    if (!thumb || a.thumbnail_url) return;      // a real picture always wins

    var family = coverFamily(a);
    thumb.classList.add("hub-cover");
    thumb.style.setProperty("--cover-hue", hueFor(family));

    /* What the cover says is which product this is.
     *
     * The first attempt put the title's initials here and they collided badly:
     * SharePoint titles follow "<Product> <Module> Overview VDK v.N", so three
     * neighbouring cards all read "NOV". The title is printed in full directly
     * underneath anyway, which made it redundant as well as ambiguous.
     *
     * Product identity is neither. A wall of Windchill marks beside a wall of
     * Creo marks is scannable at a glance, which is the one job a cover has
     * here. Four families have a mark in the sprite -- 75% of assignments --
     * and the rest show the family name, which is still distinctive per
     * family and never collides meaninglessly.
     */
    var mark = document.createElement("span");
    mark.className = "hub-cover__mark";
    mark.setAttribute("aria-hidden", "true");
    var logo = family && FAMILY_MARK[family];
    if (logo && document.getElementById(logo[0])) {
      mark.innerHTML = '<svg viewBox="' + logo[1] + '"><use href="#'
                     + logo[0] + '"/></svg>';
    } else {
      mark.className += " hub-cover__mark--text";
      // The type is never the fallback: its chip is already in the corner, and
      // a cover reading "VDK" says nothing the card has not already said.
      mark.textContent = family || (a.products || [])[0] || "";
    }
    thumb.insertBefore(mark, thumb.firstChild);
  }

  /* ------------------------------------------------- the suggestion strip */

  /* Someone who searches "windchill" wants the 203 Windchill demos, not to
   * scroll 165 result cards deciding whether they got them. So when a query
   * names a category, offer the category above the results.
   *
   * The offer is deliberately not always "go to a page". Pages exist for
   * segments only, and routing a product name to a segment page would lose
   * assets silently: ThingWorx genuinely splits 64 IoT / 44 PLM, and Arbortext
   * 11 SLM / 4 PLM, so "go to the IoT page" would quietly drop 44 ThingWorx
   * demos. A family therefore offers a scope -- show all 111 -- which is
   * complete, and a segment offers its page, which exists.
   *
   *   query names a segment  ->  open that segment's page
   *   query names a family   ->  filter to all of it, no page needed
   *   query names a type     ->  same
   *
   * One mechanism, and it does not force nineteen pages into being just to
   * satisfy the search box.
   */
  var TYPE_LABELS = { video: "Videos", ldk: "LDKs", vdk: "VDKs",
                      vm: "Virtual Machines" };

  //: Below this a suggestion is noise. "Show all 1 Consensus Introduction
  //: demos" costs a click to learn nothing; the results already show it.
  var SUGGEST_MIN = 5;

  /* Whole-word containment, so "creo overview" still offers Creo while "score"
   * does not offer SCO.
   *
   * Plus a prefix rule for the singular/plural case -- "video" must reach
   * "Videos", "ldk" must reach "LDKs" -- which only runs one way round: a
   * query word may extend a label, never the reverse. That direction is what
   * keeps "score" away from SCO, and it lets three characters be enough, which
   * this vocabulary needs (ldk, vdk, plm, alm are all three).
   */
  function namesCategory(query, label) {
    var words = query.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ");
    var l = label.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (l.length < 3) return false;
    if ((" " + words.join(" ") + " ").indexOf(" " + l + " ") !== -1) return true;
    return words.some(function (w) {
      return w.length >= 3 && l.indexOf(w) === 0;
    });
  }

  function suggestionsFor(query) {
    if (!query || query.trim().length < 3 || !baselineFacets) return [];
    var out = [];
    var seg = document.getElementById("hubFilterSegment");
    var fam = document.getElementById("hubFilterProduct");
    var typ = document.getElementById("hubFilterType");

    (baselineFacets.product_families || []).forEach(function (f) {
      if (f.count >= SUGGEST_MIN && namesCategory(query, f.value)
          && (!fam || fam.value !== f.value)) {
        out.push({ rank: 1, size: f.value.length, label: f.value,
                   text: "Show all " + f.count + " " + f.value + " demos",
                   run: function () { if (fam) fam.value = f.value;
                                      clearSearchOnly(); applyFilters(); } });
      }
    });
    (baselineFacets.segments || []).forEach(function (f) {
      if (f.count >= SUGGEST_MIN && namesCategory(query, f.value)
          && (!seg || seg.value !== f.value)) {
        out.push({ rank: 2, size: f.value.length, label: f.value,
                   text: "Go to the " + f.value + " page",
                   page: true, run: function () { openSegment(f.value); } });
      }
    });
    (baselineFacets.types || []).forEach(function (f) {
      var label = TYPE_LABELS[f.value];
      if (label && f.count >= SUGGEST_MIN && namesCategory(query, label)
          && (!typ || typ.value !== f.value)) {
        out.push({ rank: 3, size: label.length, label: label,
                   text: "Show all " + f.count + " " + label,
                   run: function () { if (typ) typ.value = f.value;
                                      clearSearchOnly(); applyFilters(); } });
      }
    });

    // A product name beats a segment name beats a type; the longest match wins
    // within a kind, so "Consensus Introduction" is not shadowed by a shorter
    // family that happens to share a word.
    out.sort(function (a, b) { return a.rank - b.rank || b.size - a.size; });
    return out.slice(0, 2);
  }

  /* Applying a category replaces the free-text search rather than adding to
   * it: "windchill" AND family=Windchill is the same set, and leaving the text
   * in place makes the filter bar look like it is doing two things. */
  function clearSearchOnly() {
    var el = document.getElementById("hubSearchInput");
    if (el) el.value = "";
  }

  function renderSuggestions(query) {
    var host = document.getElementById("hubSuggest");
    if (!host) return;
    var items = suggestionsFor(query);
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
  var segmentIndex = {};       // key -> the /api/segments row

  function escapeHtml(text) {
    var d = document.createElement("div");
    d.textContent = text == null ? "" : String(text);
    return d.innerHTML;
  }

  async function buildSegmentNav() {
    var heading = null;
    document.querySelectorAll(".orion-group").forEach(function (g) {
      if (g.textContent.trim().toLowerCase() === "browse by product") heading = g;
    });
    if (!heading) return null;

    var payload;
    try { payload = await getJSON("/api/segments"); }
    catch (err) {
      console.error("[hub-api] segments unavailable, leaving the nav alone", err);
      return null;
    }
    segmentIndex = {};
    (payload.segments || []).forEach(function (sg) { segmentIndex[sg.key] = sg; });

    // Drop the product items that followed the heading, then insert segments.
    var node = heading.nextElementSibling;
    while (node && node.classList.contains("orion-navitem")) {
      var next = node.nextElementSibling;
      node.remove();
      node = next;
    }
    heading.textContent = "Browse by Segment";

    var anchor = heading;
    (payload.segments || []).forEach(function (sg) {
      var item = document.createElement("div");
      item.className = "orion-navitem";
      // No icon. Six identical marks in a column carry no information and
      // read as noise; the product group had distinct logos, which is what
      // made icons worth having there.
      item.innerHTML = '<span class="label">' + escapeHtml(sg.label) + '</span>'
        + '<span class="count">' + sg.total + '</span>';
      anchor.after(item);
      anchor = item;
    });
    return payload;
  }

  /* Opening a segment clears every other filter. That is the whole difference
   * between a nav item and a dropdown: one takes you somewhere, the other
   * narrows where you already are. Choosing Creo and then Windchill in the nav
   * used to leave you the intersection, which is not what a sidebar promises.
   */
  function openSegment(key) {
    CONTROLS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = "";
    });
    var sel = document.getElementById("hubFilterSegment");
    if (sel) sel.value = key;
    applyFilters();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* The page header: derived facts always, editorial content only when a
   * person has actually written it. An unwritten description renders as a
   * visible gap rather than a plausible sentence nobody stands behind -- a
   * hand-typed number already lied on this page once, claiming Creo had 24
   * demos against a real 382. */
  async function renderSegmentHeader() {
    var host = document.getElementById("hubSegmentPage");
    if (!host) return;
    var sel = document.getElementById("hubFilterSegment");
    var key = sel ? sel.value : "";
    if (!key) { host.style.display = "none"; host.innerHTML = ""; return; }

    /* Once someone starts searching inside a segment they are looking for a
     * result, not reading the introduction, and a full-height header pushes
     * every result below the fold. Collapse to a single line they can reopen.
     * Re-render only when the segment itself changes, so typing does not
     * rebuild ten cards on every keystroke. */
    var searching = !!val("hubSearchInput");
    if (host.dataset.segment === key) {
      host.classList.toggle("hub-seg--collapsed", searching && !host.dataset.pinned);
      return;
    }
    host.dataset.segment = key;
    delete host.dataset.pinned;

    var sg;
    try { sg = await getJSON("/api/segments/" + encodeURIComponent(key)); }
    catch (err) { host.style.display = "none"; return; }

    var families = (sg.families || []).slice()
      .sort(function (a, b) { return b.count - a.count; }).slice(0, 4);
    var byType = {};
    (sg.types || []).forEach(function (t) { byType[t.value] = t.count; });
    var kits = (byType.ldk || 0) + (byType.vdk || 0);

    var ed = sg.editorial || {};
    var blurb = ed.blurb
      ? '<p class="hub-seg__blurb">' + escapeHtml(ed.blurb) + '</p>'
      : '<p class="hub-seg__blurb hub-seg__blurb--empty">No description written '
        + 'yet &mdash; whoever owns ' + escapeHtml(sg.label) + ' should add one '
        + 'so this page says what the segment is for.</p>';

    var owner = ed.owner
      ? '<strong>' + escapeHtml(ed.owner.name) + '</strong>'
        + (ed.owner.email ? ' <a href="mailto:' + escapeHtml(ed.owner.email)
            + '">' + escapeHtml(ed.owner.email) + '</a>' : '')
      : '<span class="hub-seg__empty">no owner recorded</span>';

    var stamp = ed.updated_at
      ? '<span class="hub-seg__stamp">updated ' + escapeHtml(ed.updated_at)
        + (ed.updated_by ? ' by ' + escapeHtml(ed.updated_by) : '') + '</span>'
      : '';

    host.innerHTML =
        '<button class="hub-seg__toggle" id="hubSegToggle" aria-expanded="true">'
      +   '<svg class="orion-ico orion-ico--sm"><use href="#i-chevron-right"/></svg>'
      +   '<span class="hub-seg__toggle-label">' + escapeHtml(sg.label) + '</span>'
      +   '<span class="hub-seg__toggle-count">' + sg.total + '</span></button>'
      + '<button class="hub-seg__back" id="hubSegBack">'
      +   '<svg class="orion-ico orion-ico--sm"><use href="#i-chevron-right"/></svg>'
      +   ' All demos</button>'
      + '<div class="hub-seg__head">'
      +   '<h2 class="hub-seg__title">' + escapeHtml(sg.label) + '</h2>'
      +   '<span class="hub-seg__count">' + sg.total + ' assets'
      +     (byType.video ? ' &middot; ' + byType.video + ' videos' : '')
      +     (kits ? ' &middot; ' + kits + ' kits' : '') + '</span>'
      + '</div>'
      + blurb
      + '<div class="hub-seg__foot">'
      +   '<span class="hub-seg__fams">'
      +     families.map(function (f) {
              return '<button class="hub-seg__fam" data-family="'
                + escapeHtml(f.value) + '">' + escapeHtml(f.value)
                + ' <em>' + f.count + '</em></button>'; }).join('')
      +   '</span>'
      +   '<span class="hub-seg__contact">Contact: ' + owner + stamp + '</span>'
      + '</div>'
      + '<div class="hub-seg__latest"><h3>Latest in ' + escapeHtml(sg.label)
      +   '</h3><div class="asset-row" id="hubSegLatest"></div></div>';
    host.style.display = "";

    var back = document.getElementById("hubSegBack");
    if (back) back.addEventListener("click", clearAll);

    /* Reopening it while searching pins it open: the collapse is a default,
     * not a rule, and someone who deliberately expands it should not have it
     * shut again by their next keystroke. */
    var toggle = document.getElementById("hubSegToggle");
    if (toggle) toggle.addEventListener("click", function () {
      var collapsed = host.classList.toggle("hub-seg--collapsed");
      toggle.setAttribute("aria-expanded", String(!collapsed));
      if (collapsed) delete host.dataset.pinned; else host.dataset.pinned = "1";
    });

    host.classList.toggle("hub-seg--collapsed", !!val("hubSearchInput"));

    host.querySelectorAll(".hub-seg__fam").forEach(function (b) {
      b.addEventListener("click", function () {
        var el = document.getElementById("hubFilterProduct");
        if (el) el.value = b.dataset.family;
        applyFilters();
      });
    });

    var rail = document.getElementById("hubSegLatest");
    (sg.latest || []).forEach(function (a) { rail.appendChild(buildCard(a)); });
  }

  /* --------------------------------------------------- browse-by-product */

  /* The product tiles ship with counts typed in by hand -- "24 videos, 9 kits,
   * 1 VDE" for Windchill, which really has 203 assets. Same problem as the
   * sidebar, and the same answer: ask for the counts, or show none.
   *
   * The breakdown per family is exactly what a scoped facet call returns, so
   * one request per tile gives the real split. Four small parallel requests on
   * a page that already fetched 946 assets is not worth optimising away.
   */
  var TILE_FAMILY = { "logo-windchill": "Windchill", "logo-creo": "Creo",
                      "logo-servicemax": "ServiceMax",
                      "logo-codebeamer": "Codebeamer",
                      "logo-seismic": "Seismic" };

  async function fillProductTiles() {
    var tiles = document.querySelectorAll("#browseByProductSection .product-tile");
    await Promise.all(Array.prototype.map.call(tiles, async function (tile) {
      var use = tile.querySelector("use");
      var href = use ? (use.getAttribute("href") || "").replace("#", "") : "";
      var family = TILE_FAMILY[href];
      var out = tile.querySelector(".product-tile__count");
      if (!out) return;
      if (!family) { out.textContent = ""; return; }

      try {
        var facets = await getJSON("/api/taxonomy?family=" + encodeURIComponent(family));
        var byType = {};
        (facets.types || []).forEach(function (t) { byType[t.value] = t.count; });
        var kits = (byType.ldk || 0) + (byType.vdk || 0);
        var parts = [];
        if (byType.video) parts.push(byType.video + " videos");
        if (kits) parts.push(kits + " kits");
        out.textContent = parts.join(" \u00b7 ") || facets.total + " assets";
      } catch (err) {
        out.textContent = "";      // no number beats a wrong one
      }

      // The tile looks clickable and now behaves that way, matching the nav.
      tile.style.cursor = "pointer";
      tile.addEventListener("click", function () {
        var el = document.getElementById("hubFilterProduct");
        if (el) el.value = family;
        applyFilters();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    }));
  }

  /* ------------------------------------------------------------------ boot */

  /* Fetch and parse, treating a non-2xx as the failure it is. Reading `.items`
   * off an error body yields undefined, which reads downstream as "no assets"
   * -- a 422 then looks exactly like an empty catalogue. */
  async function getJSON(url) {
    var response = await fetch(url);
    if (!response.ok) {
      throw new Error("HTTP " + response.status + " from " + url);
    }
    return response.json();
  }

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

  function report(text, isError) {
    var el = document.getElementById("hubApiStatus");
    if (!el) return;
    el.textContent = text;
    el.className = "hub-api-status" + (isError ? " hub-api-status--error" : "");
  }

  async function load() {
    if (typeof window.videoAssetFromData !== "function") {
      // The hook is gone. Say so rather than silently leaving the static cards
      // in place and letting everyone believe the data is live.
      console.error("[hub-api] videoAssetFromData() not found — index.html has "
                  + "changed shape. The page is showing hardcoded data.");
      report("Showing sample data — could not attach to the page", true);
      return;
    }

    var assets, facets;
    try {
      assets = await fetchAllAssets();
      facets = await getJSON("/api/taxonomy");
    } catch (err) {
      console.error("[hub-api] could not load the catalogue", err);
      report("Showing sample data — " + err.message, true);
      return;   // Elio's static cards remain; the page still works.
    }

    if (!assets.length) {
      report("The catalogue is empty — run a sync from /debug", true);
      return;
    }

    // Setting this is the whole integration: hubApplyFilters() builds from the
    // hardcoded cards only when it is still unset.
    // hubApplyFilters() has already run once on load and filled the pool from
    // the hardcoded cards, so this replaces rather than pre-empts it.
    window.HUB_ASSET_POOL = assets.map(buildCard);
    fillRails(assets);

    fillSelect("hubFilterProduct", facets.product_families || facets.products);
    fillSelect("hubFilterSegment", facets.segments);
    fillSelect("hubFilterStage", facets.funnel_stages);
    fillSelect("hubFilterType", facets.types);
    fillSidebarCounts(facets);
    takeOverControls();
    wireShareModal();
    await buildSegmentNav();
    wireNav(facets);
    markUnavailable(facets);
    markNavActive();
    fillProductTiles();

    var bySource = assets.reduce(function (acc, a) {
      acc[a.source] = (acc[a.source] || 0) + 1;
      return acc;
    }, {});
    report(assets.length + " assets · "
         + (bySource.sharepoint || 0) + " SharePoint · "
         + (bySource.consensus || 0) + " Consensus");
    console.info("[hub-api] loaded", assets.length, "assets", bySource);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
