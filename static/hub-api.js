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

  function buildCard(a) {
    var card = window.videoAssetFromData(toCardData(a));
    // videoAssetFromData hardcodes type=video, which is right for Consensus
    // but wrong for the demo kits; the type filter reads this attribute.
    card.dataset.type = a.type || "video";
    card.dataset.source = a.source || "";
    card.dataset.assetId = a.id || "";

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
    var keep = el.options.length ? el.options[0] : null;
    el.innerHTML = "";
    if (keep) el.appendChild(keep);
    facet.slice().sort(function (a, b) { return b.count - a.count; })
      .forEach(function (f) {
        var o = document.createElement("option");
        o.value = f.value;
        o.textContent = f.value + " (" + f.count + ")";
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
  function fillSidebarCounts(facets, assets) {
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
      } else {
        // No honest number for this one -- Favorites needs per-user state we
        // do not collect. Drop the figure rather than leave a fabricated one.
        count.textContent = "";
        cleared++;
      }
    });
    console.info("[hub-api] sidebar: %d counts corrected, %d removed",
                 updated, cleared);
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
    fillSidebarCounts(facets, assets);

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
