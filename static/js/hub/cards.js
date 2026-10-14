/* A catalogue card: its markup (cardShell), platform buttons, tags,
 * language and age badges, and the generated cover when there is no
 * thumbnail.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import {
  durationLabel, LANGUAGE_LABEL, pill, report, uploadedLabel
} from "./util.js";
import { hubPermissions } from "./permissions.js";
import { familyDisplayName } from "./nav.js";
import { detailAsset, openAssetDetail } from "./detail.js";
import { openShareFor } from "./share.js";

/* ---------------------------------------------------------------- mapping */

/* The stats line, assembled from whatever the record actually has.
 * `external_views` is the source platform's count, not ours, and most
 * SharePoint assets have none — so the line is built from the parts that
 * exist rather than printing "0 views" for everything. */
function statsLine(a) {
  var bits = [];
  if (a.external_views) bits.push(a.external_views + " views");
  if (a.resource_count) bits.push(a.resource_count + " files");
  // A video's date is when it was published; a kit's is its SharePoint
  // folder's last edit (see buildHome), so it says "Updated".
  if (a.uploaded_at) bits.push((a.type === "video" ? "Published " : "Updated ")
                               + uploadedLabel(a.uploaded_at));
  return bits.join(" · ");
}

/* A language tag on the tile, so a French-only recording is not discovered
 * by opening it. Skipped for English on purpose: 727 of 807 assets are
 * English, and a badge on 90% of the grid would be repetition, not a
 * signal -- the one non-English badge is what someone is actually
 * scanning for. Same principle the detail page already applied to its own
 * facts row (`language !== "en"`) before this tile-level tag existed.
 * Liwei, 2026-09-08. */
function addLanguageTag(card, a) {
  if (!a.language || a.language === "en") return;
  // On the thumbnail, not in .asset-card__meta -- that row is a flex line
  // with no wrap, already sharing its width with the platform badge and
  // the product/funnel text, and Liwei found it does exactly what a
  // no-wrap row does when one more thing joins it: whatever runs out of
  // room, silently clips against the card's own overflow:hidden. The
  // thumbnail's top-right corner has nothing else on a real card --
  // .new-dot lives at that same spot but only in Elio's static sample
  // markup, never on a card built from real data -- so a fixed position
  // there can never be squeezed out by how much other text a card has.
  var thumb = card.querySelector(".asset-card__thumb");
  if (!thumb) return;
  var tag = document.createElement("span");
  tag.className = "hub-lang-tag";
  tag.textContent = LANGUAGE_LABEL[a.language] || a.language.toUpperCase();
  thumb.appendChild(tag);
}

/* ------------------------------------------------------------------ tags
 *
 * Liwei, 2026-09-29/30, after Serge's gallery mockup
 * (Highlevel/Gallery_to_TMH_Import_Playbook.html):
 *
 *   * No source anywhere a user looks. Serge no longer wants to see where a
 *     demo lives -- no SharePoint or Consensus badge, and no badge as a
 *     link either, since the detail page's own button opens the demo.
 *     Which source holds what is admin knowledge (/admin, /migration).
 *   * The card is layered: one row of tags, always in the same order
 *     (Video Type, Segment, named customer) and all in one neutral style,
 *     then one plain line "Creo, Codebeamer and 2 more · Consideration".
 *     Coloured pills per kind were tried first and withdrawn the same day
 *     (Liwei, 2026-09-30): unreadable on the dark theme, and cards with
 *     one, two or no tags in different colours looked disordered.
 *   * The detail page lists every tag in a field : value table (below).
 *   * No "+N" chip. It read as a tag of its own (Bobcat's "+1" was
 *     ServiceMax). On the card the overflow is words, with every product in
 *     the tooltip; the detail page names them all.
 *
 * "ProENGINEER Wildfire" stays off CAD Dataset cards: 240 of 280 carry it,
 * an old pre-rebrand Creo name, and repeating it on nearly every tile is
 * noise (Liwei, 2026-09-10).
 */

/* The Video Type, only for a video (Liwei, 2026-10-01). `content_depth` is
 * also set on many LDKs and VDKs, and "Video type: Technical Teaser" on a
 * Live Demo Kit reads as a contradiction. The stored value is untouched;
 * only where it shows changes. */
function videoTypeOf(a) {
  return a && a.type === "video" ? a.content_depth : null;
}

/* The families a card names, in display form, minus the CAD-tile noise. */
function cardFamilies(a) {
  return (a.product_families || []).map(familyDisplayName).filter(function (f) {
    return !(a.type === "cad_model" && f === "ProENGINEER Wildfire");
  });
}

/* "Creo, Codebeamer and 2 more": words, never a "+2" chip. */
function familiesText(families, shown) {
  if (families.length <= shown) return families.join(", ");
  return families.slice(0, shown).join(", ")
       + " and " + (families.length - shown) + " more";
}

function renderCardTags(card, a) {
  var meta = card.querySelector(".asset-card__meta");
  if (!meta) return;

  var pills = document.createElement("div");
  pills.className = "hub-card-pills";
  if (videoTypeOf(a)) pills.appendChild(pill(videoTypeOf(a), "vtype"));
  if (a.segment) pills.appendChild(pill(a.segment, "segment"));
  if (a.named_customer) pills.appendChild(pill(a.named_customer, "customer"));
  meta.parentNode.insertBefore(pills, meta);

  var families = cardFamilies(a);
  var line = [familiesText(families, 2), a.funnel_stage].filter(Boolean).join(" · ");
  meta.innerHTML = "";
  if (line) {
    var text = document.createElement("span");
    text.className = "hub-card-line";
    text.textContent = line;
    if (families.length > 2) text.title = families.join(", ");
    meta.appendChild(text);
  }
}

/* Elio's static cards established the convention: a kit is a box, a VDK
 * a monitor, a recording a video camera. */
var TYPE_CHIP = {
  video: ["i-video", "Video"],
  ldk:   ["i-box", "LDK"],
  vdk:   ["i-monitor", "VDK"],
  vm:    ["i-monitor", "Virtual Machine"],
  cad_model: ["i-layers", "CAD Dataset"]
};

/* A card's markup, right the first time (2026-10-14). Until then it came
 * from the concept mock-up's videoAssetFromData(), which made every card a
 * Consensus video -- Video chip, an inert play button, a Share button or a
 * "No audio track" badge -- and buildCard() then corrected each of those.
 * The rest (platform buttons, cover, tags, badges) is filled in by
 * buildCard() below. */
function cardShell(a) {
  var card = document.createElement("div");
  card.className = "asset-card";
  card.dataset.type = a.type || "video";      // the type filter reads this
  card.dataset.source = a.source || "";
  card.dataset.assetId = a.id || "";

  var thumb = document.createElement("div");
  thumb.className = "asset-card__thumb";
  if (a.thumbnail_url) {
    thumb.style.background = "url(" + JSON.stringify(a.thumbnail_url) + ") center / cover";
  }

  var spec = TYPE_CHIP[a.type] || TYPE_CHIP.video;
  var chip = document.createElement("span");
  chip.className = "type-chip";
  chip.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#' + spec[0] + '"/></svg>';
  chip.appendChild(document.createTextNode(spec[1]));
  thumb.appendChild(chip);

  /* A Consensus record IS a recording, so it plays -- in the Consensus
   * player, where the video lives. A SharePoint kit is a folder of files
   * with nothing single to play, so it gets no control at all.
   *
   * Card-level inline playback was tried 2026-09-10 and withdrawn the same
   * day: Seb's "play it in that thumbnail frame" was about the DETAIL
   * PAGE's hero player (.vp-player), not the grid tile. See
   * openAssetDetail() for where that landed. */
  if (previewUrl(a)) {
    var play = document.createElement("button");
    play.className = "play-btn";
    play.type = "button";
    play.title = "Play preview";
    play.innerHTML = '<svg><use href="#i-play"/></svg>';
    play.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      openPreview(a);
    });
    thumb.appendChild(play);
  }

  // Not for an LDK. Seb, in review: he'd assume a 13:15 badge means the
  // demo takes 13:15, but that number is the recording's own length --
  // a live demo can run well past it. Elio: hide it; time only matters
  // for a customer-facing (i.e. actually-watched) video.
  var duration = a.type === "ldk" ? "" : durationLabel(a.duration_seconds);
  if (duration) {
    var time = document.createElement("span");
    time.className = "duration-chip";
    time.textContent = duration;
    thumb.appendChild(time);
  }

  /* The name opens a details page inside the Hub, not the platform.
   * Seb: "we should create a details page for each of those... behind a
   * unique link so you can share this link internally". Serge: "when you
   * click on the name, it should take you to the details page." */
  var title = document.createElement("div");
  title.className = "asset-card__title";
  var open = document.createElement("a");
  open.href = "#/asset/" + encodeURIComponent(a.id);
  open.className = "hub-detail-link";
  open.textContent = a.title || "";
  open.addEventListener("click", function (e) {
    e.preventDefault();
    openAssetDetail(a.id);
  });
  title.appendChild(open);

  var meta = document.createElement("div");
  meta.className = "asset-card__meta";          // renderCardTags() fills it

  var stats = document.createElement("div");
  stats.className = "asset-card__stats";
  stats.textContent = a.description || statsLine(a);

  var actions = document.createElement("div");
  actions.className = "asset-card__actions";    // platformActions() fills it

  var body = document.createElement("div");
  body.className = "asset-card__body";
  [title, meta, stats, actions].forEach(function (n) { body.appendChild(n); });
  card.appendChild(thumb);
  card.appendChild(body);
  return card;
}

/* Plays in a thumbnail-like frame itself, not a popup -- used by the
 * detail page's own hero player (openAssetDetail() below). Seb, review:
 * "instead of forwarding to Consensus for Videos when clicking the play
 * button on the thumbnail could you just play the video in that thumbnail
 * frame? same for VDK's and LDK's can we just embed the _CF video there
 * and play it as a preview." Confirmed after an initial mix-up (2026-09-10)
 * that "thumbnail" meant `.vp-player`, not a grid tile -- openPreview()
 * below is what the grid still uses, unchanged.
 *
 * An overlay layered on top of the existing content (absolute, inset:0)
 * rather than replacing it -- both `.vp-player` and `.asset-card__thumb`
 * are already `position:relative`, and layering means the close button
 * can just remove the overlay to get the original cover or thumbnail
 * image back, with nothing to reconstruct.
 */
function embedInlinePlayer(thumb, url, tag) {
  if (thumb.querySelector(".hub-inline-player")) return;   // already playing

  var wrap = document.createElement("div");
  wrap.className = "hub-inline-player";

  var media = document.createElement(tag);
  media.className = "hub-inline-player__media";
  media.src = url;
  if (tag === "video") {
    media.controls = true;
    media.autoplay = true;
    media.playsInline = true;
  } else {
    media.setAttribute("allow", "fullscreen; autoplay");
    media.setAttribute("allowfullscreen", "");
  }

  var close = document.createElement("button");
  close.type = "button";
  close.className = "hub-inline-player__close";
  close.title = "Close";
  close.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-x"/></svg>';
  close.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    wrap.remove();
  });

  wrap.appendChild(media);
  wrap.appendChild(close);
  thumb.appendChild(wrap);
}

//: Removing the node is enough to stop it -- a <video> or <iframe> torn
//: out of the document does not keep playing in any browser -- but every
//: caller that might replace or hide `thumb` needs to remember to call
//: this first, which is exactly the bug Liwei found 2026-09-10: switching
//: detail pages left the previous asset's video audibly playing because
//: nothing removed it.
function stopInlinePlayer(thumb) {
  var wrap = thumb.querySelector(".hub-inline-player");
  if (wrap) wrap.remove();
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
 * Nothing at all is rendered for a platform the asset is NOT on (the
 * mock-up put a "No audio track" badge here): labelling every absence does
 * not scale -- with three platforms each card would carry a row of things
 * it is not.
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
  var card = cardShell(a);
  platformActions(card, a);
  clampDescription(card, a);
  paintCover(card, a);
  addLanguageTag(card, a);
  addAgeBadge(card, a);
  renderCardTags(card, a);
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
// `sales`, not `marketing` -- flipped 2026-09-08, Elio via Seb's review:
// marketing "performed poorly" after ten days live. This mirrors
// sales_view() in consensus_sync.py; if this parameter changes a third
// time, it is worth reading from one place instead of two.
function previewUrl(a) {
  if (a.source === "consensus") return a.web_url;
  return a.consensus_uuid
    ? "https://play.goconsensus.com/" + a.consensus_uuid + "?preview=sales"
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
//: Orbit/Jetstream/IPE have no dedicated hex mark art (their only source
//: files are full wordmark lockups, not a standalone icon) -- these three
//: fall back to the real PTC corporate mark instead (Liwei supplied
//: data/media/ptc_master_logo_RGB_color.svg 2026-09-10; logo-ptc-mark is
//: just its "LOGO" group -- the two-polygon diamond -- with the "ptc"
//: wordmark half of that file left out and a tight viewBox recomputed
//: around the polygons, same treatment as the -side- logos got earlier).
//: Keyed by the RAW family name (product_families[0], via coverFamily())
//: -- unlike the nav map below this is not the umbrella facet, so
//: Orbit/Jetstream carry no "PTC " prefix here.
var FAMILY_MARK = {
  "Windchill": ["logo-windchill-mark", "0 0 259.46 299.60"],
  "Creo": ["logo-creo-mark", "0 0 397.21 449.90"],
  "ServiceMax": ["logo-servicemax-mark", "0 0 71.14 82.15"],
  "Codebeamer": ["logo-codebeamer-mark", "0 0 261.71 300.76"],
  "Orbit": ["logo-ptc-mark", "0 0 284.42 325.42"],
  "Jetstream": ["logo-ptc-mark", "0 0 284.42 325.42"],
  "IPE": ["logo-ptc-mark", "0 0 284.42 325.42"]
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
  paintCoverInto(card.querySelector(".asset-card__thumb"), a);
}

/* The mark itself, split out so both the no-thumbnail case and the
 * thumbnail-failed-to-load case (below) paint the identical cover rather
 * than two implementations drifting apart. */
function renderCoverMark(thumb, a) {
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

/* Split out from paintCover so the details page can use the same cover.
 * Seb asked for the placeholder there too, and the alternative was a second
 * implementation that would drift from this one. */
function paintCoverInto(thumb, a) {
  if (!thumb) return;
  if (!a.thumbnail_url) { renderCoverMark(thumb, a); return; }

  /* A real picture only wins once it actually loads. CAD Model thumbnails
   * (added 2026-09-09) point straight at SharePoint's own SiteAssets, not
   * a pre-authenticated Graph URL like preview()/download_url() use -- they
   * only render for a viewer who is themselves signed into SharePoint in
   * that browser. cardShell() has already set this as a
   * background-image with no fallback if it 404s, so an unauthenticated
   * viewer would otherwise see a blank tile instead of any cover at all.
   * Preloading costs nothing extra for the common case: the browser's own
   * cache serves the background-image request that already fired for the
   * same URL. */
  var probe = new Image();
  probe.onerror = function () {
    thumb.style.backgroundImage = "";
    renderCoverMark(thumb, a);
  };
  probe.src = a.thumbnail_url;
}

/* ── Age badges (Serge, 2026-10-13) ───────────────────────────────────
 *
 * "Software interfaces change fast. The badge tells you how old a
 * recording is, not whether the content is still valid." His spec:
 *
 *   under 1 year   New                 green, sparkle
 *   1 to 2 years   (no badge)          so the badges keep their meaning
 *   2 to 4 years   2023                amber, hourglass, the year
 *   4+ years       Older UI · 2019     grey, history icon
 *   any age        Still current       blue, set by a reviewer, replaces
 *                                      the age badge while it lasts
 *
 * The band comes from the server (`age_band`, services/content_age.py),
 * so the Published filter and the badge can never disagree. Collecting
 * dust (7+ years) is a review-view word only, never shown here.
 */
var AGE_ICONS = {
  spark: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'
       + '<path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  glass: '<path d="M6 2h12M6 22h12M7 2v3a5 5 0 0 0 10 0V2M7 22v-3a5 5 0 0 1 10 0v3"/>',
  clock: '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  box: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11h14V8M10 12h4"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.2l2.4 2.4 4.6-4.9"/>'
};

function publishedYear(a) {
  var m = /^(\d{4})/.exec(a.uploaded_at || "");
  return m ? m[1] : "";
}

function friendlyDate(iso) {
  var d = new Date(iso + "T00:00:00");
  return isNaN(d) ? iso : d.toLocaleDateString(undefined,
    { year: "numeric", month: "short", day: "numeric" });
}

/* The badge for one demo, or null (1-2 years old, or no date). */
function ageBadge(a) {
  var kind, text, icon, title;
  var year = publishedYear(a);
  if (a.archived) {
    kind = "archived"; icon = "box"; text = "Archived";
    title = "Archived in the Hub" + (a.archived_at ? " on " + friendlyDate(
      String(a.archived_at).slice(0, 10)) : "") + ": out of every list and search."
      + " Still in SharePoint.";
  } else if (a.still_current_until) {
    kind = "current"; icon = "check"; text = "Still current";
    title = "A reviewer confirmed the interface shown still matches today's release"
      + " (until " + friendlyDate(a.still_current_until) + ")."
      + (year ? " Published " + year + "." : "");
  } else if (a.age_band === "new") {
    kind = "new"; icon = "spark"; text = "New";
    title = "Recent recording: shows the current software interface.";
  } else if (a.age_band === "aging") {
    kind = "aging"; icon = "glass"; text = year;
    title = "Published " + year + ". The interface may have changed since.";
  } else if (a.age_band === "older") {
    kind = "older"; icon = "clock"; text = "Older UI · " + year;
    title = "Published " + year + ". The software interface has likely changed;"
      + " the capabilities shown may still apply.";
  } else {
    return null;
  }
  var el = document.createElement("span");
  el.className = "hub-age hub-age--" + kind;
  el.title = title;
  el.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + AGE_ICONS[icon] + "</svg>";
  el.appendChild(document.createTextNode(text));
  return el;
}

function addAgeBadge(card, a) {
  var thumb = card.querySelector(".asset-card__thumb");
  var badge = thumb && ageBadge(a);
  if (badge) thumb.appendChild(badge);
}

/* On a demo's page: the same badge in the tag row, and for people with
 * "Review content" a switch to confirm or withdraw Still current. */
function renderAgeMark(meta, asset) {
  meta.querySelectorAll(".hub-age, .hub-review-btn").forEach(function (n) { n.remove(); });
  var badge = ageBadge(asset);
  // With the tags, ahead of any buttons, however often it is redrawn.
  if (badge) meta.insertBefore(badge, meta.querySelector(
    ".hub-pill--internal, .hub-access-btn, .hub-review-btn"));
  if (!asset.uploaded_at && !asset.still_current_until) return;
  hubPermissions.then(function (granted) {
    if (granted.indexOf("review_content") < 0 || detailAsset !== asset) return;
    var on = !!asset.still_current_until;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "hub-review-btn";
    btn.textContent = on ? "Withdraw Still current" : "Mark Still current";
    btn.title = on
      ? "The interface shown no longer matches today's release: show its age again"
      : "The interface shown still matches today's release (lasts a year)";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      fetch("/api/assets/" + encodeURIComponent(asset.id) + "/still-current", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ still_current: !on }),
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (d) {
        asset.still_current_until = d.still_current_until;
        asset.still_current_by = d.still_current_by;
        renderAgeMark(meta, asset);
      }).catch(function (err) {
        btn.disabled = false;
        report("Could not change Still current: " + err.message, true);
      });
    });
    meta.appendChild(btn);

    var arch = document.createElement("button");
    arch.type = "button";
    arch.className = "hub-review-btn";
    arch.textContent = asset.archived ? "Restore" : "Archive";
    arch.title = asset.archived
      ? "Put it back in the Hub's lists and search"
      : "Take it out of the Hub's lists and search. SharePoint is not changed.";
    arch.addEventListener("click", function () {
      arch.disabled = true;
      fetch("/api/assets/" + encodeURIComponent(asset.id) + "/archive", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived: !asset.archived }),
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (d) {
        asset.archived = d.archived;
        asset.archived_at = d.archived ? new Date().toISOString() : null;
        renderAgeMark(meta, asset);
      }).catch(function (err) {
        arch.disabled = false;
        report("Could not change the archive: " + err.message, true);
      });
    });
    meta.appendChild(arch);
  });
}

export {
  buildCard, consensusUrl, embedInlinePlayer, paintCoverInto, previewUrl,
  renderAgeMark, stopInlinePlayer, TYPE_CHIP, videoTypeOf
};
