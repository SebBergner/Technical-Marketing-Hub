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
  /* The platform label is the action.
   *
   * Serge, 2026-09-02: "instead of share demo, you could remove that
   * altogether and just click consensus and it would take you to the video in
   * consensus. That way you're saving real estate and it's super logical,
   * because it's implying if you're at SharePoint, you click on SharePoint, it
   * takes you to SharePoint."
   *
   * So the badge stops being decoration and becomes the link. That also
   * removes the separate share control from the card entirely, which is what
   * made the actions row worth its space in the first place.
   */
  var PLATFORM_LABEL = {
    consensus: ["Consensus", "Open this demo in Consensus"],
    sharepoint: ["SharePoint", "Open this demo kit's folder in SharePoint"]
  };

  function platformBadge(source, href) {
    var spec = PLATFORM_LABEL[source] || [source, "Open in " + source];
    // Without somewhere to go it stays a label; a link that goes nowhere is
    // worse than a badge that never claimed to be one.
    var el = document.createElement(href ? "a" : "span");
    el.className = "orion-badge hub-source hub-source--" + source
                 + (href ? " hub-source--link" : "");
    el.textContent = spec[0];
    el.title = href ? spec[1] : spec[0];
    if (href) {
      el.href = href;
      el.target = "_blank";
      el.rel = "noopener";
      // The card's own click opens the details page; this one must not.
      el.addEventListener("click", function (e) { e.stopPropagation(); });
    }
    return el;
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
    var url = previewUrl(a);
    if (!url) { play.remove(); return; }   // nothing to play: no control

    var button = document.createElement("button");
    button.className = "play-btn";
    button.type = "button";
    button.title = "Play preview";
    button.innerHTML = play.innerHTML;
    button.style.cursor = "pointer";
    button.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      openPreview(a);
    });
    play.replaceWith(button);
  }

  /* Plays inside the Hub rather than in a tab.
   *
   * Elio: "I'd rather do a popup, and everything's hidden." A browser popup
   * cannot do that any more -- Chrome ignores `location=no` and still shows a
   * copyable origin bar -- but an iframe genuinely can, and Consensus permits
   * it: neither play.goconsensus.com nor app.goconsensus.com sends
   * X-Frame-Options or a frame-ancestors policy. Checked 2026-09-02.
   */
  function openPreview(a) {
    var url = previewUrl(a);
    if (!url) return;

    var backdrop = document.getElementById("hubPreviewBackdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "hubPreviewBackdrop";
      backdrop.className = "hub-preview";
      backdrop.innerHTML =
          '<div class="hub-preview__box">'
        +   '<div class="hub-preview__bar">'
        +     '<span class="hub-preview__title" id="hubPreviewTitle"></span>'
        +     '<button class="hub-preview__close" title="Close">&times;</button>'
        +   '</div>'
        +   '<iframe class="hub-preview__frame" id="hubPreviewFrame"'
        +     ' allow="fullscreen; autoplay" referrerpolicy="no-referrer"></iframe>'
        + '</div>';
      document.body.appendChild(backdrop);

      var shut = function () {
        backdrop.classList.remove("open");
        // Blank the src on close, or the demo keeps playing behind the page.
        document.getElementById("hubPreviewFrame").src = "about:blank";
      };
      backdrop.querySelector(".hub-preview__close").addEventListener("click", shut);
      backdrop.addEventListener("click", function (e) {
        if (e.target === backdrop) shut();
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && backdrop.classList.contains("open")) shut();
      });
    }

    document.getElementById("hubPreviewTitle").textContent = a.title || "";
    document.getElementById("hubPreviewFrame").src = url;
    backdrop.classList.add("open");
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
  /* HIDDEN, not deleted.
   *
   * Seb, 2026-09-02: "don't remove the current share functionality that you
   * have. Just hide it." The DemoBoard modal works and is verified against the
   * live API; what it cannot do without SSO is create the board as the person
   * pressing the button, and until then every board would be filed under one
   * name. Serge's interim answer -- click the Consensus badge, make the board
   * there, logged in as yourself -- is what the card offers instead.
   *
   * Flip this to false the day Easy Auth is configured. Nothing else needs to
   * change: the `as_user` plumbing behind it is already in place and tested.
   */
  var SHARE_BUTTON_HIDDEN = true;

  function platformActions(card, a) {
    var actions = card.querySelector(".asset-card__actions");
    if (!actions) return;

    var available = SHARE_BUTTON_HIDDEN
      ? [] : PLATFORMS.filter(function (p) { return a[p.field]; });
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

    /* One badge per platform the asset is actually on, each linking there.
     * A SharePoint kit that also has a Consensus recording gets both, which is
     * the honest picture and replaces the small logo button that used to say
     * the same thing less clearly. */
    var meta = card.querySelector(".asset-card__meta");
    if (meta) {
      var anchor = meta.firstChild;
      if (a.consensus_uuid && a.source !== "consensus") {
        meta.insertBefore(platformBadge("consensus", consensusUrl(a)), anchor);
      }
      meta.insertBefore(
        platformBadge(a.source,
                      a.source === "consensus" ? consensusUrl(a) : a.web_url),
        meta.firstChild);
    }

    /* The name opens a details page inside the Hub, not the platform.
     *
     * Seb: "we should create a details page for each of those... behind a
     * unique link so you can share this link internally". Serge: "when you
     * click on the name, it should take you to the details page."
     */
    var title = card.querySelector(".asset-card__title");
    if (title) {
      var open = document.createElement("a");
      open.href = "#/asset/" + encodeURIComponent(a.id);
      open.className = "hub-detail-link";
      open.textContent = title.textContent;
      open.addEventListener("click", function (e) {
        e.preventDefault();
        openAssetDetail(a.id);
      });
      title.textContent = "";
      title.appendChild(open);
    }
    return card;
  }

  /* A card has three doors and they lead to three different places.
   *
   *   play button  -> watch it here, in a popup, without leaving the Hub
   *   the name     -> the details page
   *   the platform -> that platform, as yourself
   *
   * The distinction between the first and the third is the one worth keeping
   * straight. The preview plays a demo; the platform link puts the person in
   * Consensus, signed in as themselves, where they can build a DemoBoard that
   * is actually theirs. Sending the platform badge to the preview would look
   * identical and quietly do the wrong thing.
   */

  //: Watch it here. A preview: no engagement is recorded, which Liwei
  //: confirmed is acceptable for browsing.
  function previewUrl(a) {
    if (a.source === "consensus") return a.web_url;
    return a.consensus_uuid
      ? "https://play.goconsensus.com/" + a.consensus_uuid + "?preview=marketing"
      : null;
  }

  /* Go to Consensus. The demo library with the title pre-searched, rather than
   * a direct link to the demo, because arriving through the library means
   * Consensus checks the licence: no licence, nothing found, and the Hub never
   * had to ask who they are. Elio wanted exactly that automation and this gets
   * it without a permissions lookup of our own.
   *
   * The cost is that a title is not an identifier. 17 titles are shared by
   * more than one demo and 66 demos differ only by a language or version
   * suffix, so about one in eight searches lands on a short list rather than a
   * single result. A UUID-addressable library URL would be strictly better if
   * one exists.
   */
  function consensusUrl(a) {
    if (!a.consensus_uuid && a.source !== "consensus") return null;
    /* Search by internalTitle, not title.
     *
     * `title` is the friendly display name and it is not unique: three
     * separate demos are called "Benefits of Mathcad Prime". The Consensus
     * library lists and searches by the pipe-delimited convention --
     * "Role-Based Demonstration | Mathcad Prime | Capabilities Playlist |
     * Select a Role" -- so a query built from the friendly name found nothing
     * at all. Liwei hit exactly that.
     *
     * Falls back to the title for the 41 Consensus demos whose internalTitle
     * is empty, and for a SharePoint kit, which has no internal title to use.
     */
    return "https://app.goconsensus.com/demos/demo-library?query="
         + encodeURIComponent(a.internal_title || a.title || "");
  }

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
  var HIDDEN_SEGMENTS = ["IoT"];

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
                       "Virtual Machines": "vm" };
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
  /* The umbrella family the nav has taken you to. Not a dropdown, because
   * there is no umbrella control in the filter bar -- Browse by Product is the
   * only way in, and the reset button is the way out. */
  var umbrellaFilter = null;

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
    if (umbrellaFilter) params.append("umbrella", umbrellaFilter);
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
        fillSidebarCounts(baselineFacets);
      }
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
                           : umbrellaFilter ? " All " + umbrellaFilter + " assets "
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
    umbrellaFilter = null;
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
    var families = {}, stages = {}, umbrellas = {};
    (facets.product_families || []).forEach(function (f) { families[f.value] = 1; });
    (facets.funnel_stages || []).forEach(function (f) { stages[f.value] = 1; });
    // Every umbrella, including the ones at zero: IPE has no demos yet and
    // must still be clickable, or it looks broken rather than empty.
    (facets.umbrella_families || []).forEach(function (f) { umbrellas[f.value] = 1; });

    navTargets = {};
    document.querySelectorAll(".orion-navitem").forEach(function (item) {
      var name = navLabel(item);
      var target = null;
      if (name === "Home") target = { control: null };
      else if (name === "Latest Uploads") target = { control: null, sort: "recent" };
      else if (NAV_TYPE[name]) target = { control: "hubFilterType", value: NAV_TYPE[name] };
      // A product family is a destination, not a filter toggle: it clears
      // everything else, because that is what a nav item promises.
      else if (umbrellas[name]) target = { control: "umbrella", value: name,
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
    "Most Viewed": "No view counts for SharePoint assets yet, so any ranking "
                 + "would show Consensus only",
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
    var anyOn = !!sortOverride || !!umbrellaFilter || CONTROLS.some(function (id) {
      var el = document.getElementById(id);
      return el && el.value;
    });
    document.querySelectorAll(".orion-navitem").forEach(function (item) {
      var target = navTargets[navLabel(item)];
      var on = false;
      if (target && !target.control) on = !anyOn;                  // Home
      else if (target && target.control === "umbrella") {
        on = umbrellaFilter === target.value;
      }
      else if (target) {
        var el = document.getElementById(target.control);
        on = !!el && el.value === target.value;
      }
      item.classList.toggle("is-active", on);
    });
  }

  /* The product pills shipped as a hand-typed five: Windchill, Creo,
   * ServiceMax, Codebeamer, Other. The catalogue has NINETEEN families, and
   * three of the largest were missing -- ThingWorx with 111 assets, Mathcad
   * with 43, Arbortext with 15 -- so anyone wanting a ThingWorx video had to
   * file it as "Other". The single most useful field for routing a request
   * was the one most likely to be useless.
   *
   * Built from the same facets the rest of the page uses, so it cannot drift
   * again: a family that appears in the catalogue appears here the same day.
   * Ordered by how much of the catalogue each one holds, because that is also
   * roughly the order people look for them in.
   */
  function fillProductPills(facets) {
    var row = document.getElementById("productScopeRow");
    if (!row) return;
    var families = (facets.product_families || []).slice()
      .sort(function (a, b) { return b.count - a.count; });
    if (!families.length) return;          // keep the markup rather than empty it

    row.innerHTML = "";
    families.forEach(function (f) {
      var pill = document.createElement("span");
      pill.className = "stage-pill";
      pill.dataset.value = f.value;
      pill.textContent = f.value;
      pill.title = f.count + " asset" + (f.count === 1 ? "" : "s") + " today";
      row.appendChild(pill);
    });
    // "Other" is not a family and has no count; it is the honest home for a
    // product the catalogue has never carried, which is exactly when someone
    // is most likely to be requesting one.
    var other = document.createElement("span");
    other.className = "stage-pill";
    other.dataset.value = "Other";
    other.textContent = "Other";
    row.appendChild(other);

    // Elio's pills call pillToggle + computeProductScope through inline
    // onclick; rebuilt ones need the same behaviour bound directly.
    row.querySelectorAll(".stage-pill").forEach(function (pill) {
      pill.addEventListener("click", function () {
        window.pillToggle(pill);
        if (window.computeProductScope) window.computeProductScope();
      });
    });
  }

  /* Files the requester chose, kept as File objects until submission.
   *
   * The original handler rendered a chip and then cleared the input, which
   * discarded every File — the whole point of holding them here. Nothing left
   * the browser and the chip made it look attached.
   *
   * They are screened client-side against the same limits the server applies.
   * That is not the security boundary — the server's check is — it is so
   * someone learns their 30 MB video is too large before they fill in the
   * rest of the form, rather than after.
   */
  var MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024;
  var BLOCKED_EXTENSIONS = [
    ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs",
    ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".hta", ".cpl", ".jar",
    ".reg", ".lnk", ".iso", ".img", ".sh"
  ];
  var pendingFiles = [];

  function attachmentProblem(file) {
    var dot = file.name.lastIndexOf(".");
    var ext = dot === -1 ? "" : file.name.slice(dot).toLowerCase();
    if (BLOCKED_EXTENSIONS.indexOf(ext) !== -1) {
      return ext + " files are not accepted.";
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      return (file.size / 1048576).toFixed(1) + " MB is over the 4 MB limit — "
           + "link it in the notes instead.";
    }
    if (!file.size) return "the file is empty.";
    return null;
  }

  function renderAttachments(problems) {
    var list = document.getElementById("attachmentList");
    if (!list) return;
    list.innerHTML = "";

    pendingFiles.forEach(function (file, index) {
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = '<svg class="orion-ico orion-ico--sm"><use href="#i-file-text"/></svg> '
        + escapeHtml(file.name)
        + ' <span class="attach-size">' + (file.size / 1024).toFixed(0) + ' KB</span>';
      var x = document.createElement("button");
      x.type = "button";
      x.className = "chip__x";
      x.textContent = "\u00d7";
      x.title = "Remove " + file.name;
      x.addEventListener("click", function () {
        pendingFiles.splice(index, 1);
        renderAttachments([]);
      });
      chip.appendChild(x);
      list.appendChild(chip);
    });

    (problems || []).forEach(function (message) {
      var warn = document.createElement("span");
      warn.className = "attach-warn";
      warn.textContent = message;
      list.appendChild(warn);
    });
  }

  function takeAttachments(input) {
    var problems = [];
    Array.prototype.forEach.call(input.files, function (file) {
      var problem = attachmentProblem(file);
      if (problem) { problems.push(file.name + ": " + problem); return; }
      var duplicate = pendingFiles.some(function (f) {
        return f.name === file.name && f.size === file.size;
      });
      if (!duplicate) pendingFiles.push(file);
    });
    // Clearing the input is what lets the same file be chosen again after
    // being removed; the File objects are safe in pendingFiles by now.
    input.value = "";
    renderAttachments(problems);
  }

  /* ------------------------------------------------------- the details page */

  /* Seb, 2026-09-02: "we should create a details page for each of those...
   * behind a unique link so that you can also share this link internally. So
   * you can tell someone, hey, look at this demo asset, and it brings them
   * back to that exact demo details page."
   *
   * Elio's markup already contains the page -- #videoPreviewPage, with a
   * player, title, meta, description and a Value Roadmap card. It was driven
   * by his mock `videoData` object, so this fills it from the catalogue
   * instead. Building a second one would have thrown away his layout for no
   * gain.
   *
   * The unique link is `#/asset/<id>`, on the hash rather than the path,
   * because the app is served as one static file: a real path would 404 on a
   * hard refresh, and a link that only works if you arrive by clicking is not
   * the shareable link Seb asked for.
   */
  var detailAsset = null;

  function assetUrl(id) {
    return location.origin + location.pathname + "#/asset/" + encodeURIComponent(id);
  }

  function durationLabel(seconds) {
    if (!seconds) return "";
    var m = Math.floor(seconds / 60), sec = seconds % 60;
    return m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  async function openAssetDetail(id) {
    var asset;
    try {
      asset = await getJSON("/api/assets/" + encodeURIComponent(id));
    } catch (err) {
      console.error("[hub-api] could not load asset", id, err);
      return;
    }
    detailAsset = asset;

    var page = document.getElementById("videoPreviewPage");
    if (!page) return;

    setText("vpTitle", asset.title);
    setText("vpDuration", durationLabel(asset.duration_seconds));

    /* The meta row carries the platform badges, so the details page offers the
     * same two doors as the card and nobody has to go back to find them. */
    var meta = document.getElementById("vpMeta");
    if (meta) {
      meta.innerHTML = "";
      meta.appendChild(platformBadge(
        asset.source,
        asset.source === "consensus" ? consensusUrl(asset) : asset.web_url));
      if (asset.consensus_uuid && asset.source !== "consensus") {
        meta.appendChild(platformBadge("consensus", consensusUrl(asset)));
      }
      [asset.type && (TYPE_CHIP[asset.type] || [])[1],
       (asset.product_families || [])[0],
       asset.segment, asset.funnel_stage].filter(Boolean).forEach(function (t) {
        var chip = document.createElement("span");
        chip.className = "orion-badge";
        chip.textContent = t;
        meta.appendChild(chip);
      });
    }

    /* Facts, and only the ones we hold. An empty stats row beats a row of
     * zeroes implying nobody has watched something we simply never counted. */
    var facts = [];
    if (asset.external_views) facts.push(asset.external_views + " views on Consensus");
    if (asset.resource_count) facts.push(asset.resource_count + " files");
    if (asset.video_count) facts.push(asset.video_count + " videos");
    if (asset.uploaded_at) facts.push("Uploaded " + asset.uploaded_at);
    if (asset.language && asset.language !== "en") facts.push(asset.language.toUpperCase());
    setText("vpStats", facts.join(" \u00b7 "));

    setText("vpDesc", asset.description
      || "No description in " + (asset.source === "consensus" ? "Consensus" : "SharePoint")
         + " for this one yet.");

    renderFileList(page, asset);

    var drivers = document.getElementById("vpValueDrivers");
    if (drivers) {
      drivers.innerHTML = "";
      (asset.value_drivers || []).forEach(function (d) {
        var chip = document.createElement("span");
        chip.className = "value-driver-chip";
        chip.textContent = d;
        drivers.appendChild(chip);
      });
      if (!(asset.value_drivers || []).length) {
        drivers.innerHTML = '<span class="hub-empty">Not indexed yet.</span>';
      }
    }

    /* The Value Roadmap is the feature Serge called "very powerful", and
     * nothing in the catalogue has been indexed -- 0 of 946. A placeholder
     * rather than a hidden panel, because the panel is the point: Serge should
     * see where it will be, and that it is empty for a reason rather than
     * missing. Seb is going to show how AMP does the indexing; when that lands
     * this branch stops being taken and nothing else changes.
     */
    var caps = document.getElementById("vpCapabilities");
    var indexed = asset.value_roadmap && asset.value_roadmap.capabilities
                  && asset.value_roadmap.capabilities.length;
    if (caps && !indexed) {
      caps.innerHTML =
          '<div class="vr-placeholder">'
        +   '<svg class="orion-ico"><use href="#i-target"/></svg>'
        +   '<div><strong>Not indexed yet.</strong>'
        +     '<div>The Value Roadmap index maps a demo onto the processes and '
        +     'capabilities it demonstrates. Nothing in the catalogue carries '
        +     'one yet &mdash; the indexing approach is being reused from AMP.</div>'
        +   '</div>'
        + '</div>';
    }

    /* Velocity is hidden — it cannot act as the person pressing it — and so
     * is our own Share modal. What replaces them are two plain links out to
     * the platform, where the person is signed in as themselves:
     *
     *   Go to SharePoint / Go to Consensus   the asset where it lives
     *   Create DemoBoard                     Consensus's own creation page,
     *                                        pre-loaded with this demo
     *
     * The DemoBoard link is the interim answer to the identity problem Serge
     * proposed in the review: three steps instead of one, and every board
     * belongs to whoever made it.
     */
    ["vpShareBtn", "vpDsrBtn"].forEach(function (btnId) {
      var b = document.getElementById(btnId);
      if (b) b.style.display = "none";
    });

    var actions = page.querySelector(".vp-actions");
    if (actions) {
      actions.querySelectorAll(".vp-platform").forEach(function (b) { b.remove(); });

      var platformHref = asset.source === "consensus"
        ? consensusUrl(asset) : asset.web_url;
      if (platformHref) {
        actions.insertBefore(
          linkButton("btn-primary-sm vp-platform",
                     asset.source === "consensus" ? "Go to Consensus"
                                                  : "Go to SharePoint",
                     platformHref,
                     asset.source === "consensus" ? "i-send" : "i-file-text"),
          actions.firstChild);
      }

      // Only where a DemoBoard is possible: it needs a Consensus demo behind it.
      if (asset.consensus_uuid) {
        actions.appendChild(linkButton(
          "btn-ghost vp-platform", "Create DemoBoard",
          "https://app.goconsensus.com/link/custom/create?demo="
            + encodeURIComponent(asset.consensus_uuid),
          "i-send",
          "Opens Consensus's own DemoBoard page for this demo. You will be "
          + "signed in as yourself, so the board is yours."));
      }
    }

    // A copyable link to exactly this page -- the point of the whole page.
    var actions = page.querySelector(".vp-actions");
    if (actions && !document.getElementById("vpCopyLink")) {
      var copy = document.createElement("button");
      copy.className = "btn-ghost";
      copy.id = "vpCopyLink";
      copy.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-file-text"/></svg>Copy link';
      copy.addEventListener("click", function () {
        navigator.clipboard.writeText(assetUrl(detailAsset.id));
        copy.textContent = "Copied";
        setTimeout(function () { copy.innerHTML =
          '<svg class="orion-ico--sm orion-ico"><use href="#i-file-text"/></svg>Copy link'; }, 1500);
      });
      actions.appendChild(copy);
    }

    // The player is a still: embedding the Consensus viewer is a separate
    // decision, and a play button that does nothing would be a lie.
    /* No still and nothing to play is 250px of black rectangle claiming to be
     * a video. Most SharePoint kits are exactly that, so the player is only
     * shown when it has something to be. */
    var player = page.querySelector(".vp-player");
    if (player) {
      var playable = !!previewUrl(asset);
      player.style.display = (asset.thumbnail_url || playable) ? "" : "none";
      player.style.background = asset.thumbnail_url
        ? "#000 url(" + JSON.stringify(asset.thumbnail_url) + ") center/contain no-repeat"
        : "";
      var play = player.querySelector(".vp-player__play");
      if (play) {
        var canPlay = !!previewUrl(asset);
        play.style.display = canPlay ? "" : "none";
        play.onclick = canPlay ? function () { openPreview(asset); } : null;
        play.title = canPlay ? "Play preview" : "";
      }
    }

    /* Showing the page is not enough: the catalogue has to be hidden, or the
     * details render underneath it. Elio's own openRequestView() hides both
     * the topbar and the thread, and this is the same kind of view. */
    document.getElementById("requestViewPage").classList.remove("active");
    var topbar = document.getElementById("mainTopbar");
    var thread = document.getElementById("mainThread");
    if (topbar) topbar.style.display = "none";
    if (thread) thread.style.display = "none";
    // Not setActiveNav(null): Elio's version does getElementById(id).classList
    // with no guard, so a null id throws and takes the rest of this function
    // with it -- the catalogue hid and the details page never appeared.
    document.querySelectorAll(".orion-side .orion-navitem")
      .forEach(function (n) { n.classList.remove("orion-navitem--active"); });

    page.classList.add("active");
    page.scrollTop = 0;
    if (location.hash !== "#/asset/" + encodeURIComponent(id)) {
      history.pushState(null, "", "#/asset/" + encodeURIComponent(id));
    }
  }

  var FILE_ICON = { video: "i-video", document: "i-file-text", image: "i-panel",
                   cad: "i-box", dataset: "i-grid", other: "i-file-text" };

  function fileSize(bytes) {
    if (!bytes) return "";
    return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB"
                            : Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  /* What is actually in the folder.
   *
   * Liwei asked for this on the SharePoint page: an asset is a folder, and
   * knowing whether it holds a script and a 60 MB video or forty CAD parts is
   * most of what you want before opening it.
   *
   * Size and duration come free with the sync -- Graph returns `size` and a
   * `video` facet on every file it lists -- so a row says how long a video
   * runs and how big it is without a single extra request.
   *
   * CAD is counted but not listed. It is 42% of the catalogue by file count
   * and nobody picks a `part.prt.1` out of a list; the counts line says how
   * many there are.
   */
  function renderFileList(page, asset) {
    var existing = page.querySelector(".vp-files");
    if (existing) existing.remove();

    var files = asset.resources || [];
    var counts = asset.resource_counts || {};
    if (!files.length && !asset.resource_count) return;

    var box = document.createElement("div");
    box.className = "vp-card vp-files";

    var summary = Object.keys(counts).sort().map(function (kind) {
      return counts[kind] + " " + kind + (counts[kind] === 1 ? "" : "s");
    }).join(" \u00b7 ");

    box.innerHTML = '<div class="vp-card__head"><div class="vp-card__head-title">'
      + '<svg class="orion-ico"><use href="#i-file-text"/></svg>Files in this folder'
      + '</div><span class="vp-files__summary">' + escapeHtml(summary) + '</span></div>';

    var list = document.createElement("div");
    list.className = "vp-files__list";
    files.forEach(function (f) {
      var facts = [f.extension && f.extension.toUpperCase(),
                   f.duration_seconds && durationLabel(f.duration_seconds),
                   fileSize(f.size_bytes),
                   f.width && f.height && (f.width + "\u00d7" + f.height),
                   f.audience === "customer_facing" ? "customer-facing"
                     : f.audience === "internal" ? "internal" : null,
                   f.subfolder].filter(Boolean).join(" \u00b7 ");
      var row = document.createElement("div");
      row.className = "vp-file";
      row.innerHTML =
          '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#'
        +   (FILE_ICON[f.kind] || "i-file-text") + '"/></svg>'
        + '<span class="vp-file__name">' + escapeHtml(f.name) + '</span>'
        + '<span class="vp-file__facts">' + escapeHtml(facts) + '</span>';
      list.appendChild(row);
    });
    box.appendChild(list);

    // Only counted, never listed, and said so rather than left as a gap
    // between "9 files" and four rows.
    var hidden = (asset.resource_count || 0) - files.length;
    if (hidden > 0) {
      var note = document.createElement("div");
      note.className = "vp-files__note";
      note.textContent = hidden + " more file" + (hidden === 1 ? "" : "s")
        + " not listed \u2014 mostly CAD parts, which are counted rather than "
        + "browsed. Open the folder in SharePoint to see everything.";
      box.appendChild(note);
    }

    page.appendChild(box);
  }

  function linkButton(className, label, href, icon, title) {
    var a = document.createElement("a");
    a.className = className;
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    if (title) a.title = title;
    a.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#' + icon
                + '"/></svg>' + escapeHtml(label);
    return a;
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text || "";
  }

  /* Arriving on a link someone shared, and the back button, are the same
   * thing: read the hash and show whatever it names. */
  function routeFromHash() {
    var match = /^#\/asset\/(.+)$/.exec(location.hash || "");
    if (match) { openAssetDetail(decodeURIComponent(match[1])); return; }
    closeAssetDetail();
  }

  function closeAssetDetail() {
    var page = document.getElementById("videoPreviewPage");
    if (page) page.classList.remove("active");
    // Put the catalogue back, unless the request form is what is showing.
    var request = document.getElementById("requestViewPage");
    if (request && request.classList.contains("active")) return;
    var topbar = document.getElementById("mainTopbar");
    var thread = document.getElementById("mainThread");
    if (topbar) topbar.style.display = "";
    if (thread) thread.style.display = "";
  }

  function wireDetailPage() {
    window.addEventListener("hashchange", routeFromHash);
    // Elio's Back button clears the view; the hash has to follow, or the page
    // reappears on the next refresh.
    var back = document.querySelector("#videoPreviewPage .vp-back");
    if (back) back.addEventListener("click", function () {
      if (location.hash.indexOf("#/asset/") === 0) {
        history.pushState(null, "", location.pathname + location.search);
      }
      closeAssetDetail();
    });
    routeFromHash();          // honour a link opened cold
  }

  /* -------------------------------------------------- the request intake */

  /* submitAssetRequest() hid the form and showed the success card. No request
   * was made and nothing was written anywhere -- the same shape as the
   * DemoBoard modal before it was wired. A form that says "submitted" and
   * loses the answer is worse than one with no button.
   *
   * It posts to /api/requests now, which appends the submission locally
   * BEFORE touching Graph and then writes it to the Demo Requests list on
   * EXT-TDD. The two outcomes are different promises and the screen says
   * which one it is: recorded here, or visible to the team.
   */
  var REQ_ROWS = {
    asset_type: "assetTypeRow",
    products: "productScopeRow",
    narrative: "narrativeAngleRow",
    target_length: "desiredLengthRow",
    customer_involvement: "customerRow",
    distribution_channels: "distributionRow",
    starting_materials: "startingMaterialsRow"
  };

  /* Pills carry data-value where one exists and otherwise mean their own
   * text. Reading textContent as the fallback keeps the two rows that were
   * built without data-value working, rather than silently sending nothing. */
  function pillValues(rowId) {
    var row = document.getElementById(rowId);
    if (!row) return [];
    return Array.prototype.map.call(
      row.querySelectorAll(".stage-pill--active"),
      function (p) { return p.dataset.value || p.textContent.trim(); });
  }

  function fieldValue(id) {
    var el = document.getElementById(id);
    return el && el.value.trim() ? el.value.trim() : null;
  }

  function collectRequest() {
    var body = {
      asset_type: pillValues(REQ_ROWS.asset_type)[0] || "video",
      products: pillValues(REQ_ROWS.products),
      brief: fieldValue("reqBrief"),
      narrative: pillValues(REQ_ROWS.narrative)[0] || null,
      target_length: pillValues(REQ_ROWS.target_length)[0] || null,
      customer_involvement: pillValues(REQ_ROWS.customer_involvement)[0] || null,
      distribution_channels: pillValues(REQ_ROWS.distribution_channels),
      starting_materials: pillValues(REQ_ROWS.starting_materials),
      needed_by: fieldValue("reqTargetDate"),
      compelling_event: fieldValue("reqCompellingEvent"),
      requester_name: fieldValue("reqName"),
      requester_email: fieldValue("reqEmail"),
      notes: fieldValue("reqNotes")
    };
    // The starting-materials pills are ours to label; the list column expects
    // the words a person would read.
    var materials = { have: "Have materials", liberty: "Team has creative liberty" };
    body.starting_materials = body.starting_materials.map(function (v) {
      return materials[v] || v;
    });
    return body;
  }

  function requestProblem(message) {
    var box = document.getElementById("reqError");
    if (!box) return;
    box.textContent = message || "";
    box.style.display = message ? "" : "none";
    if (message) box.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function submitRequest(event) {
    if (event) event.preventDefault();
    requestProblem("");

    var body = collectRequest();
    if (!body.products.length) {
      requestProblem("Choose at least one product. It is what routes the request "
                   + "to the person who can scope it.");
      return;
    }

    var button = document.querySelector('[onclick*="submitAssetRequest"]');
    var restore = button ? button.innerHTML : null;
    if (button) { button.disabled = true; button.textContent = "Submitting\u2026"; }

    try {
      var response;
      if (pendingFiles.length) {
        // multipart: the request itself travels as one JSON field, so the
        // server validates it against exactly the same model either way.
        var form = new FormData();
        form.append("request", JSON.stringify(body));
        pendingFiles.forEach(function (f) { form.append("files", f, f.name); });
        response = await fetch("/api/requests/with-files",
                               { method: "POST", body: form });
      } else {
        response = await fetch("/api/requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
      }
      var data = await response.json();
      if (!response.ok) {
        requestProblem(data.detail
          || ("The request was not saved (HTTP " + response.status + ")."));
        return;
      }

      document.getElementById("requestFormCard").style.display = "none";
      var card = document.getElementById("requestSuccessCard");
      card.style.display = "";

      /* The reference is the point of the success screen: without it the
       * requester has nothing to quote when they chase it. */
      var note = document.getElementById("reqOutcome");
      if (note) {
        var lines = ["Reference " + data.id + "."];
        lines.push(data.synced
          ? "It is in the team's Demo Requests list."
          : (data.warning || "") + " Nothing has been lost — the team will pick it up.");
        var stored = (data.attachments || []).length;
        if (stored) {
          lines.push(stored + " file" + (stored === 1 ? "" : "s") + " attached.");
        }
        // A dropped attachment is never left for the requester to discover.
        (data.attachments_rejected || []).forEach(function (r) { lines.push(r); });
        note.textContent = lines.join(" ");
        note.className = "req-outcome"
          + ((data.synced && !(data.attachments_rejected || []).length)
             ? "" : " req-outcome--warn");
      }
      pendingFiles = [];
      document.getElementById("requestViewPage").scrollTop = 0;
    } catch (err) {
      requestProblem("Could not reach the Hub: " + err.message
                   + ". Nothing was submitted, so nothing was lost — try again.");
    } finally {
      if (button) { button.disabled = false; button.innerHTML = restore; }
    }
  }

  /* Elio binds the submit through an inline onclick, so replacing the global
   * is enough here -- unlike the filter controls, which use addEventListener
   * and had to be cloned to drop their handlers. */
  function wireRequestForm() {
    window.submitAssetRequest = submitRequest;
    window.handleAttachmentFiles = takeAttachments;
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
    // Off by default now the control is hidden: a checkbox nobody can see
    // must not decide that every share is a silent test.
    document.getElementById("shareIsTest").checked = false;
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
    (baselineFacets.umbrella_families || []).forEach(function (f) {
      if (f.count >= SUGGEST_MIN && namesCategory(query, f.value)) {
        out.push({ rank: 2, size: f.value.length, label: f.value,
                   text: "Browse all " + f.count + " " + f.value,
                   page: true, run: function () { openFamily(f.value); } });
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

  /* The page shows a spinner until this succeeds, and Elio's placeholder cards
   * are never revealed -- Liwei's rule: a blank screen is fine, the mock-up is
   * not, not even for a frame. Placeholder data is indistinguishable from real
   * data to anyone who has not read the source, and a tile claiming 1,204
   * views is worse than an empty page.
   *
   * So a failure has to SAY so. Every early return in boot() lands here. */
  function bootFailed(message) {
    var boot = document.getElementById("hubBoot");
    var text = document.getElementById("hubBootMessage");
    if (boot) boot.classList.add("hub-boot--failed");
    if (text) text.textContent = message;
    console.error("[hub-api] boot failed:", message);
  }

  function escapeHtml(text) {
    var d = document.createElement("div");
    d.textContent = text == null ? "" : String(text);
    return d.innerHTML;
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
       * No icon either: eight identical marks in a column carry no
       * information, and only four of the eight products have a logo.
       */
      item.innerHTML = '<span class="label">' + escapeHtml(f.value) + '</span>';
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
    umbrellaFilter = name;
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
      bootFailed("The page could not be wired to the catalogue. "
               + "index.html has changed shape — see the console.");
      return;
    }

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
    fillRails(assets);

    fillSelect("hubFilterProduct", facets.product_families || facets.products);
    fillSelect("hubFilterSegment", (facets.segments || []).filter(function (f) {
      return HIDDEN_SEGMENTS.indexOf(f.value) === -1;
    }));
    fillSelect("hubFilterStage", facets.funnel_stages);
    fillSelect("hubFilterType", facets.types);
    fillSidebarCounts(facets);
    takeOverControls();
    wireShareModal();
    wireRequestForm();
    wireDetailPage();
    fillProductPills(facets);
    await buildFamilyNav(facets);
    wireNav(facets);
    markUnavailable(facets);
    markNavActive();
    fillProductTiles();

    // Real content is in place: reveal the thread. See the #mainThread rule in
    // index.html for why it also reveals itself on a timer.
    document.body.classList.add("hub-ready");

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
