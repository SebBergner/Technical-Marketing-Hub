/* A demo's page (#/asset/...): layout, sections and tabs, the file
 * list and file preview, the hero player, Open/Internal, and the
 * hash router.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import {
  dateLabel, debounce, durationLabel, escapeHtml, fullDate, getJSON, LANGUAGE_LABEL, pill,
  report, setText
} from "./util.js";
import { hubPermissions } from "./permissions.js";
import { editButton } from "./edit.js";
import {
  buildCard, consensusUrl, embedInlinePlayer, paintCoverInto, previewUrl, renderAgeMark,
  stopInlinePlayer, TYPE_CHIP, videoTypeOf
} from "./cards.js";
import { familyDisplayName, openTag } from "./nav.js";
import { renderVmCards, TYPE_LONG } from "./vm.js";
import { closeActivity, openActivity } from "./activity.js";
import { closeUpload, openUpload } from "./upload.js";
import { closeReview, openReview } from "./review.js";
import { closeHelp, openHelp, openReportModal } from "./report.js";
import {
  advancedHash, advState, closeAdvancedSearch, fileTotalsText,
  openAdvancedSearch
} from "./search.js";

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

/* One view, counted when a details page opens.
 *
 * The endpoint has existed since the stats model did; nothing ever called
 * it, so `views` sat at zero everywhere and an Admin usage view built on it
 * would have read as "nobody uses this" rather than "nobody counts this".
 * Wired 2026-09-21, deliberately ahead of that view: numbers have to start
 * accumulating before anyone can look at them.
 *
 * Fire-and-forget on purpose. It is a 204 with nothing to read, the page is
 * already rendering without it, and a counter that could block a page from
 * opening would be a worse bug than an uncounted view -- so a failure is
 * logged at debug and otherwise ignored.
 *
 * What it counts is "a details page was opened", which includes reopening
 * the same asset and includes whoever built it. Good enough to rank demos
 * by interest; not an audience metric, and should not be presented as one.
 */
function recordView(id) {
  fetch("/api/assets/" + encodeURIComponent(id) + "/view", { method: "POST" })
    .catch(function (err) { console.debug("[hub-api] view not counted", err); });
}

/* `fileItemId`: arrived on a shared file link (fileHash) -- open the page
 * and then that file's preview. */
async function openAssetDetail(id, fileItemId) {
  var page0 = document.getElementById("videoPreviewPage");
  if (fileItemId && detailAsset && detailAsset.id === id
      && page0 && page0.classList.contains("active")) {
    // Already on this demo: just show the file, no reload.
    renderFileList(page0, detailAsset, tabOf(detailAsset, fileItemId));
    selectSection("files");
    openFileById(detailAsset, fileItemId);
    return;
  }
  // Back returns to Advanced Search when that is where this came from.
  var adv = document.getElementById("hubAdvancedPage");
  if (adv && adv.classList.contains("active")) {
    detailReturnHash = advancedHash(advState.q);
  } else if (window.hubDetailReturn) {
    // Content to review (review.js) closes as the hash changes, so it says
    // where it was rather than being found open.
    detailReturnHash = window.hubDetailReturn;
  } else if (!(page0 && page0.classList.contains("active"))) {
    detailReturnHash = null;
  }
  window.hubDetailReturn = null;
  var asset;
  try {
    asset = await getJSON("/api/assets/" + encodeURIComponent(id));
  } catch (err) {
    console.error("[hub-api] could not load asset", id, err);
    // A link to a demo that has been hidden or removed used to do nothing
    // at all (2026-10-06): say so, and go back to the catalogue.
    if (/HTTP 404/.test(String(err && err.message))) {
      report("That demo is not available in the Hub.", true);
      if (location.hash.indexOf("#/asset/") === 0) {
        history.replaceState(null, "", location.pathname + location.search);
      }
      closeAssetDetail();
    }
    return;
  }
  // The card's chosen picture (HubThumbnail, B5) is a file in the folder,
  // but not one of the demo's files to list.
  asset.resources = (asset.resources || []).filter(function (r) { return !r.hub_thumbnail; });
  detailAsset = asset;
  recordView(id);

  var page = document.getElementById("videoPreviewPage");
  if (!page) return;

  setText("vpTitle", asset.title);
  // Same call as the card's duration-chip, same reason to skip it for LDK
  // -- see cardShell().
  setText("vpDuration", asset.type === "ldk" ? "" : durationLabel(asset.duration_seconds));
  // Hidden when empty: its dark background otherwise shows as a small bar
  // in the corner of every LDK and of any kit without a length (2026-10-01).
  var durationChip = document.getElementById("vpDuration");
  if (durationChip) durationChip.style.display = durationChip.textContent ? "" : "none";

  /* The meta row: the two things someone decides on before pressing play,
   * what format it is and how far it goes. Everything else is in the
   * Details table under the description (see renderFactsTable). No source
   * badge -- Serge, via Liwei 2026-09-29. */
  var meta = document.getElementById("vpMeta");
  if (meta) {
    meta.innerHTML = "";
    var typeLabel = (TYPE_CHIP[asset.type] || [])[1];
    if (typeLabel) meta.appendChild(pill(typeLabel, "customer"));
    if (videoTypeOf(asset)) meta.appendChild(pill(videoTypeOf(asset), "vtype"));
    if (asset.segment) meta.appendChild(pill(asset.segment, "segment"));
    renderAccessMark(meta, asset);
    renderAgeMark(meta, asset);
    if (asset.upload_review) {
      var wait = pill(asset.upload_review === "sent_back" ? "Sent back" : "Not published",
                      "upload");
      wait.title = "Uploaded through the Hub before review was removed, and not published "
        + "yet: only its uploader and the team can see it.";
      meta.insertBefore(wait, meta.firstChild);
    }
  }

  /* Facts, and only the ones we hold. An empty stats row beats a row of
   * zeroes implying nobody has watched something we simply never counted. */
  /* File counts are not here (Liwei, 2026-10-01): the Files tab carries
   * them ("Files (9)", "6 videos \u00b7 2 documents \u00b7 1 other"), and a second,
   * differently worded count under the title only repeated it. */
  var facts = [];
  if (asset.external_views) facts.push(asset.external_views + " views");
  setText("vpStats", facts.join(" \u00b7 "));

  if (!renderStoryIntro(asset)) {
    setText("vpDesc", asset.description || "No description for this one yet.");
  }
  ensureDetailLayout(page);
  renderFactsTable(page, asset);
  renderManage(asset);

  renderFileList(page, asset, fileItemId && tabOf(asset, fileItemId));
  renderVmCards(page, asset);
  settleSectionTabs(asset);
  renderRelated(page, asset);

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
  ["vpShareBtn"].forEach(function (btnId) {
    var b = document.getElementById(btnId);
    if (b) b.style.display = "none";
  });

  var actions = page.querySelector(".vp-actions");
  if (actions) {
    actions.querySelectorAll(".vp-platform").forEach(function (b) { b.remove(); });

    var platformHref = asset.source === "consensus"
      ? consensusUrl(asset) : asset.web_url;
    // Files locked for this person (an Internal demo, 2026-10-07): no
    // Download Kit either -- it is the same files, one page further on.
    if (asset.files_locked && asset.source !== "consensus") platformHref = null;
    if (platformHref) {
      actions.insertBefore(
        linkButton("btn-primary-sm vp-platform",
                   // Consensus keeps its wording; SharePoint's changed
                   // 2026-09-08 -- Liwei/Elio: with the file list now
                   // downloadable right here, "Download Kit" says what
                   // pressing it actually gets you, better than sending
                   // someone to SharePoint to do the same thing manually.
                   //
                   // 2026-09-10: tried making this link straight to
                   // SharePoint's _layouts/15/download.aspx?SourceUrl=
                   // zip endpoint instead of the DocSetHome page, so
                   // pressing it would zip-and-download in one step and
                   // "Download all" (removed, see renderFileList) would
                   // have a real replacement. Liwei tested it against the
                   // live tenant: SharePoint returned "File Not Found" --
                   // that endpoint is for a single file's SourceUrl, not
                   // a folder/Document Set, so it cannot zip one. Reverted
                   // to the DocSetHome link: SharePoint's actual "Download
                   // a copy" zip action lives in that page's own command
                   // bar, gated behind a session-bound temp-auth token its
                   // JS mints itself, which a static link cannot forge.
                   // "Download Kit" still means "get the whole kit" --
                   // it just takes one more click, on SharePoint's page,
                   // to press the real button.
                   // No platform in the label (brief §15): "Open Demo"
                   // was "Go to Consensus"; a video opens, a kit downloads.
                   // A demo known only from its page has nothing to
                   // download: its button opens the page (2026-10-05).
                   asset.source === "consensus" ? "Open Demo"
                     : isPageOnly(asset) ? "Open demo page"
                     : asset.type === "video" ? "Open Video" : "Download Kit",
                   platformHref,
                   asset.source === "consensus" ? "i-send" : "i-file-text"),
        actions.firstChild);
    }

    // Only where a DemoBoard is possible: it needs a Consensus demo behind
    // it, and the person a Consensus licence -- on Elio's list, for now
    // (Elio, Seb, 2026-10-28; backend/consensus_licenses.py). Placed after
    // Open, before Share Internally and Share feedback.
    if (asset.consensus_uuid) {
      var shownFor = asset.id;
      hubPermissions.then(function (granted) {
        if (granted.indexOf("consensus_licensed") < 0) return;
        if (!detailAsset || detailAsset.id !== shownFor) return;
        if (actions.querySelector(".vp-demoboard")) return;
        var board = linkButton(
          "btn-ghost vp-platform vp-demoboard", "Create DemoBoard",
          "https://app.goconsensus.com/link/custom/create?demo="
            + encodeURIComponent(asset.consensus_uuid),
          "i-send",
          "Opens Consensus's own DemoBoard page for this demo. You will be "
          + "signed in as yourself, so the board is yours.");
        var open = actions.querySelector(".vp-platform:not(.vp-demoboard)");
        actions.insertBefore(board, open ? open.nextSibling : actions.firstChild);
      });
    }
  }

  // A copyable link to exactly this page -- the point of the whole page.
  //
  // "Share Internally", not "Copy link" -- Elio's note after Seb's review
  // (2026-09-08): "Copy Link" reads as if it were fine to hand to a
  // customer. It is not -- it opens the Hub itself, with no licence check
  // and no watermark, unlike "Create DemoBoard" beside it. Briefly
  // labelled "Copy Internal Link" the same day, on the reasoning that the
  // verb should still say "copy" since that's the only thing the button
  // does; Liwei's final call was Elio's original wording.
  var actions = page.querySelector(".vp-actions");
  /* The demo's SharePoint page, when it has one besides its folder: a
   * quiet text link, not a third button (Liwei, 2026-10-05). A page-only
   * demo already opens its page from the main button. */
  var pageLink = document.getElementById("vpPageLink");
  if (pageLink) pageLink.remove();
  if (actions && asset.page_url && !isPageOnly(asset)) {
    pageLink = document.createElement("a");
    pageLink.id = "vpPageLink";
    pageLink.className = "hub-page-link";
    pageLink.href = asset.page_url;
    pageLink.target = "_blank";
    pageLink.rel = "noopener";
    pageLink.title = "The demo's page on the EXT-TDD SharePoint site";
    pageLink.textContent = "Demo page \u2197";
    actions.appendChild(pageLink);
  }

  // A partner sees "Copy link" (Liwei, 2026-10-29): "Internally" means
  // PTC to them, and the link is for their colleagues on the Hub too.
  if (actions && !document.getElementById("vpCopyLink")) {
    var copy = document.createElement("button");
    var copyLabel = "Share Internally";
    var drawCopy = function () {
      copy.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-file-text"/></svg>';
      copy.appendChild(document.createTextNode(copyLabel));
    };
    copy.className = "btn-ghost";
    copy.id = "vpCopyLink";
    copy.title = "This opens the Hub itself -- for colleagues, not customers.";
    drawCopy();
    hubPermissions.then(function (granted) {
      if (granted.indexOf("is_partner") < 0) return;
      copyLabel = "Copy link";
      copy.title = "A link to this page on the Hub, for colleagues who use it -- not for customers.";
      drawCopy();
    });
    copy.addEventListener("click", function () {
      navigator.clipboard.writeText(assetUrl(detailAsset.id));
      copy.textContent = "Copied";
      setTimeout(drawCopy, 1500);
    });
    actions.appendChild(copy);
  }

  // Feedback on this demo (A2, 2026-10-28): to its segment's owners.
  // "Share feedback", at the end of the actions row and styled as a link,
  // not a button: on the Back line it was easy to miss, and it must not
  // compete with Open and Share (Elio, Seb, 2026-10-28; was "Report an
  // issue"). It replaces the sidebar's Share feedback, which did not say
  // what the feedback was about.
  if (actions && !document.getElementById("vpReport")) {
    var flag = document.createElement("button");
    flag.className = "vp-report";
    flag.id = "vpReport";
    flag.type = "button";
    flag.title = "Tell the team about this demo: something wrong, missing or out of date";
    flag.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-message-square"/></svg>Share feedback';
    flag.addEventListener("click", function () { openReportModal(detailAsset); });
    actions.appendChild(flag);
  }

  // The player is a still: embedding the Consensus viewer is a separate
  // decision, and a play button that does nothing would be a lie.
  /* No still and nothing to play is 250px of black rectangle claiming to be
   * a video. Most SharePoint kits are exactly that, so the player is only
   * shown when it has something to be. */
  var player = page.querySelector(".vp-player");
  if (player) {
    // The page is reused for every asset, so last one's cover has to go
    // before this one's is painted, or the marks stack up. Bug, found by
    // Liwei 2026-09-10: switching to a different demo left the PREVIOUS
    // one's video/iframe playing, audibly, because only the cover mark was
    // ever cleaned up here -- an inline player from embedInlinePlayer()
    // was never in this list and just sat there. Removing the node stops
    // playback in every browser (a <video> or <iframe> torn out of the
    // document does not keep running), so this alone is the fix -- no
    // separate pause() call needed.
    stopInlinePlayer(player);
    player.querySelectorAll(".hub-cover__mark")
          .forEach(function (m) { m.remove(); });
    player.classList.remove("hub-cover");
    player.style.removeProperty("--cover-hue");

    // Seb, 2026-09-03: give the assets with no thumbnail a placeholder here
    // as well. It used to hide the player outright when there was neither a
    // still nor anything to play -- true of most SharePoint kits -- so the
    // details page opened straight onto the title with no header at all.
    player.style.display = "";
    player.style.background = asset.thumbnail_url
      ? "#000 url(" + JSON.stringify(asset.thumbnail_url) + ") center/contain no-repeat"
      : "";
    // No picture, or one that does not load (a CAD Image naming a file that
    // is not there): the generated cover, as on the cards.
    paintCoverInto(player, asset);
    var play = player.querySelector(".vp-player__play");
    if (play) {
      // Seb, review: "play the video in that thumbnail frame ... same for
      // VDK's and LDK's, embed the _CF video there." This is the
      // "thumbnail" he meant -- confirmed 2026-09-10 after an initial
      // mix-up that tried this on the grid tiles instead (withdrawn, see
      // cardShell() above). No fetch needed here, unlike a grid card:
      // openAssetDetail() already has the full Asset, resources[] and
      // main_video included, since this IS the detail response.
      var videos = (asset.resources || []).filter(function (r) { return r.kind === "video"; });
      var pick = (asset.main_video
                  && videos.find(function (r) { return r.name === asset.main_video; }))
               || videos.find(function (r) { return r.audience === "customer_facing"; })
               || videos[0];
      var consensusSrc = previewUrl(asset);   // Consensus wins when both exist, as before
      var canPlay = !!consensusSrc || !!(pick && pick.item_id);
      play.style.display = canPlay ? "" : "none";
      play.title = canPlay ? "Play preview" : "";
      play.onclick = canPlay ? function () {
        if (consensusSrc) embedInlinePlayer(player, consensusSrc, "iframe");
        else embedInlinePlayer(player, fileDownloadUrl(asset.id, pick.item_id), "video");
      } : null;
    }
  }

  /* Showing the page is not enough: the catalogue has to be hidden, or the
   * details render underneath it. Elio's own openRequestView() hides both
   * the topbar and the thread, and this is the same kind of view. */
  document.getElementById("requestViewPage").classList.remove("active");
  if (adv) adv.classList.remove("active");
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
  var here = fileItemId ? fileHash(id, fileItemId) : "#/asset/" + encodeURIComponent(id);
  if (location.hash !== here) history.pushState(null, "", here);
  if (fileItemId) openFileById(asset, fileItemId);
}

/* "You may also need" at the foot of the page (A13, Summit): six demos
 * sharing this one's product family, segment or type -- the server ranks
 * them (JsonAssetRepository.related). Ordinary cards, so a click opens that
 * demo's page here. Loaded after the page shows, and dropped if the person
 * has moved on to another demo by then.
 *
 * Someone with Edit metadata may also pick demos by hand (Liwei,
 * 2026-10-28): "Add" finds one by name; a pick shows first, unmarked, on
 * both demos' pages and has Remove; a found one has Not related, which
 * keeps it off this page only, and is listed under the cards to undo. For
 * everyone else the section is absent when nothing is related. */
function renderRelated(page, asset) {
  var section = document.getElementById("vpRelated");
  if (!section) {
    section = document.createElement("div");
    section.className = "section hub-related";
    section.id = "vpRelated";
    section.innerHTML =
        '<div class="section-head"><div class="section-head__title">'
      +   '<svg class="orion-ico ico-green"><use href="#i-layers"/></svg> Related demos'
      + '</div></div>'
      + '<div class="hub-related__pick" hidden></div>'
      + '<div class="asset-grid"></div>'
      + '<div class="hub-related__marked" hidden></div>';
    page.appendChild(section);
  }
  var grid = section.querySelector(".asset-grid");
  grid.innerHTML = "";
  section.style.display = "none";
  var head = section.querySelector(".section-head");
  var oldAdd = head.querySelector(".hub-related__add");
  if (oldAdd) oldAdd.remove();
  section.querySelector(".hub-related__pick").hidden = true;
  section.querySelector(".hub-related__marked").hidden = true;

  var url = "/api/assets/" + encodeURIComponent(asset.id) + "/related";
  Promise.all([getJSON(url), hubPermissions]).then(function (got) {
    if (!detailAsset || detailAsset.id !== asset.id) return;
    var data = got[0];
    var editor = got[1].indexOf("maintain_content") >= 0;
    data.items.forEach(function (a) {
      var card = buildCard(a);
      if (editor) card.appendChild(relatedControl(asset, a, page));
      grid.appendChild(card);
    });
    if (editor) {
      head.appendChild(relatedAddButton(section, asset, data.items, page));
      renderNotRelated(section, asset, data.not_related, page);
    }
    section.style.display = data.items.length || editor ? "" : "none";
  }).catch(function (err) {
    console.warn("[hub-api] related demos not loaded", err);
  });
}

/* Remove (a pick) or Not related (a found one), at the card's foot. */
function relatedControl(asset, a, page) {
  var b = document.createElement("button");
  b.type = "button";
  b.className = "hub-related__ctl";
  b.textContent = a.picked ? "Remove" : "Not related";
  b.title = a.picked
    ? "Take this pick off both demos' pages"
    : "Stop suggesting this demo here (this page only)";
  b.addEventListener("click", function () {
    b.disabled = true;
    var base = "/api/assets/" + encodeURIComponent(asset.id);
    var done = a.picked
      ? send("DELETE", base + "/related/" + encodeURIComponent(a.id))
      : send("PUT", base + "/not-related/" + encodeURIComponent(a.id), { not_related: true });
    done.then(function () {
      report(a.picked ? "Removed from related demos." : "Marked Not related on this page.");
      renderRelated(page, asset);
    }).catch(function (err) {
      b.disabled = false;
      report(err.message, true);
    });
  });
  return b;
}

/* "Add": a name box; up to eight matching demos to pick from. */
function relatedAddButton(section, asset, items, page) {
  var add = document.createElement("button");
  add.type = "button";
  add.className = "hub-related__add";
  add.innerHTML = '<svg class="orion-ico orion-ico--sm"><use href="#i-plus"/></svg>Add';
  var box = section.querySelector(".hub-related__pick");
  add.addEventListener("click", function () {
    if (!box.hidden) { box.hidden = true; return; }
    box.innerHTML = '<input type="search" class="hub-related__q" '
      + 'placeholder="Find a demo by name" aria-label="Find a demo by name">'
      + '<div class="hub-related__hits"></div>';
    box.hidden = false;
    var input = box.querySelector("input");
    var hits = box.querySelector(".hub-related__hits");
    var shown = {};
    shown[asset.id] = true;
    items.forEach(function (a) { if (a.picked) shown[a.id] = true; });
    input.addEventListener("input", debounce(function () {
      var q = input.value.trim();
      hits.innerHTML = "";
      if (q.length < 2) return;
      getJSON("/api/assets?limit=8&q=" + encodeURIComponent(q)).then(function (page1) {
        if (input.value.trim() !== q) return;
        var found = page1.items.filter(function (a) { return !shown[a.id]; });
        if (!found.length) {
          hits.innerHTML = '<div class="hub-related__none">No other demo matches.</div>';
          return;
        }
        found.forEach(function (a) {
          var row = document.createElement("button");
          row.type = "button";
          row.className = "hub-related__hit";
          row.innerHTML = '<span>' + escapeHtml(a.title) + '</span><small>'
            + escapeHtml((TYPE_CHIP[a.type] || [])[1] || a.type || "") + '</small>';
          row.addEventListener("click", function () {
            row.disabled = true;
            send("PUT", "/api/assets/" + encodeURIComponent(asset.id) + "/related/"
                        + encodeURIComponent(a.id))
              .then(function () {
                report("Added to related demos, here and on its own page.");
                renderRelated(page, asset);
              })
              .catch(function (err) { row.disabled = false; report(err.message, true); });
          });
          hits.appendChild(row);
        });
      }).catch(function (err) { report(err.message, true); });
    }, 250));
    input.focus();
  });
  return add;
}

/* What was marked Not related here, each with Undo. */
function renderNotRelated(section, asset, marked, page) {
  var box = section.querySelector(".hub-related__marked");
  box.innerHTML = "";
  if (!marked.length) return;
  box.appendChild(document.createTextNode("Not related here: "));
  marked.forEach(function (m, i) {
    if (i) box.appendChild(document.createTextNode(" · "));
    var name = document.createElement("span");
    name.textContent = m.title + " ";
    var undo = document.createElement("button");
    undo.type = "button";
    undo.className = "hub-related__undo";
    undo.textContent = "Undo";
    undo.title = "Marked by " + whoName(m.by) + (m.at ? " on " + onDay(m.at) : "");
    undo.addEventListener("click", function () {
      undo.disabled = true;
      send("PUT", "/api/assets/" + encodeURIComponent(asset.id) + "/not-related/"
                  + encodeURIComponent(m.id), { not_related: false })
        .then(function () { renderRelated(page, asset); })
        .catch(function (err) { undo.disabled = false; report(err.message, true); });
    });
    name.appendChild(undo);
    box.appendChild(name);
  });
  box.hidden = false;
}

//: Where the details page's Back button goes when it was opened from
//: Advanced Search or Content to review; null means the catalogue, as before.
var detailReturnHash = null;

function tabOf(asset, itemId) {
  var f = (asset.resources || []).find(function (r) { return r.item_id === itemId; });
  return f ? fileTab(f) : undefined;
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
/* Where a file's own bytes come from -- resolved fresh by the server on
 * every click via GraphClient.download_url(), never stored, because that
 * URL is pre-authenticated and expires in about an hour. `item_id` is None
 * on a resource synced before this field existed, or on anything that
 * isn't a SharePoint folder in the first place; renderFileList() falls
 * back to plain text in that case rather than linking to a 404. */
function fileDownloadUrl(assetId, itemId) {
  return "/api/assets/" + encodeURIComponent(assetId) + "/files/"
       + encodeURIComponent(itemId) + "/download";
}

/* Same free-form URL trick as fileDownloadUrl(): the endpoint itself does
 * the redirect (302 to Graph's embeddable viewer), so an <iframe src> set
 * to this URL just follows it -- no fetch, no JSON, nothing async here. */
function filePreviewUrl(assetId, itemId) {
  return "/api/assets/" + encodeURIComponent(assetId) + "/files/"
       + encodeURIComponent(itemId) + "/preview";
}

/* A link to one file: it opens the demo's detail page with that file's
 * preview already showing (Liwei, 2026-09-30). Same caveat as Share
 * Internally on the page itself -- it opens the Hub, so it is for
 * colleagues, not customers. */
function fileHash(assetId, itemId) {
  return "#/asset/" + encodeURIComponent(assetId) + "/file/" + encodeURIComponent(itemId);
}

function fileShareUrl(assetId, itemId) {
  return location.origin + location.pathname + fileHash(assetId, itemId);
}

/* Copy, and say so on the button. The clipboard API only exists on a
 * secure origin (https or localhost); anywhere else the link is shown in a
 * prompt to copy by hand rather than the button pretending it worked. */
function copyShareLink(button, url) {
  var label = button.innerHTML;
  var done = function () {
    button.textContent = "Link copied";
    setTimeout(function () { button.innerHTML = label; }, 1500);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(done, function () {
      window.prompt("Copy this link", url);
    });
  } else {
    window.prompt("Copy this link", url);
  }
}

var SHARE_TITLE = "Copy a link that opens this file's preview in the Hub "
                + "-- for colleagues, not customers.";

//: What gets a Preview button at all. Datasets (zip/rar) and CAD have
//: nothing Graph's viewer can usefully show -- verified 2026-09-08 that
//: Graph does not even error on a zip, it just returns a viewer for
//: something nobody asked to look at, so the honest answer is not to
//: offer the button rather than trust Graph's silence.
var PREVIEWABLE_KINDS = ["video", "document", "image"];

//: Of those, which actually render inside OUR iframe rather than opening
//: in a new tab. Found by testing, the hard way: a video and an image both
//: play inline once the iframe drops referrerpolicy="no-referrer" (see
//: ensureFilePreviewModal()). A Word or PowerPoint file does not, even
//: then -- the exact same URL opened as a top-level navigation renders
//: Office's own viewer perfectly, but framed by a different origin it
//: shows nothing, no error either side of the frame boundary. That is
//: Office Online's own anti-framing behaviour (it is how WOPI-based
//: editors avoid being embedded somewhere a user might mistake for the
//: real thing), not a bug in this app, and not something a header on our
//: side can turn off. So "document" gets a new tab instead of the modal --
//: still a preview before download, just not inside our chrome.
var MODAL_PREVIEWABLE_KINDS = ["video", "image"];

//: { asset, files, index } for whichever file is open in the modal, or
//: null. `files` is already filtered to MODAL_PREVIEWABLE_KINDS -- Prev/
//: Next only ever steps through things that actually render there.
var filePreviewState = null;

function ensureFilePreviewModal() {
  var backdrop = document.getElementById("hubFilePreviewBackdrop");
  if (backdrop) return backdrop;

  // Same classes as the Consensus preview modal (hub-preview,
  // hub-preview__box/__bar/__frame) -- same chrome, same open/close/Esc
  // behaviour, so this looks like one feature with two content sources
  // rather than two unrelated popups. The info row and Prev/Next bar are
  // the only genuinely new pieces, added below the frame per Elio: "the
  // preview video on top and description on bottom."
  backdrop = document.createElement("div");
  backdrop.id = "hubFilePreviewBackdrop";
  backdrop.className = "hub-preview";
  // Deliberately no referrerpolicy on the iframe below, unlike the
  // Consensus one above. SharePoint's embed.aspx viewer renders
  // completely blank with "no-referrer" set -- found by testing, not
  // documented anywhere: the exact same URL opened directly in a tab
  // played fine, the same URL in this iframe with no-referrer showed
  // nothing, and removing the attribute was the entire fix. No console
  // error on either side, because a cross-origin iframe's own script
  // failures never reach the parent page's console -- without opening
  // the URL standalone to compare, this would have looked like an
  // unexplained silent failure in our own code.
  // Elio, 2026-09-08, on AMP's layout: "the preview video on top and
  // description on bottom... make it look good, but similar layout and
  // information." Everything AMP put in its Properties box is now a
  // genuine label/value table, not the one-line bullet list this used to
  // be.
  //
  // Seb, 2026-09-10, having seen that version: "I like the preview popup,
  // but maybe put the metadata from the bottom on the right ... vertical?"
  // -- Liwei's call, the right side. So the desc/table pair (still one
  // `.hub-file-preview__body`, unchanged inside) now sits beside the video
  // in `.hub-file-preview__main`, not below it -- a real side panel, the
  // shape AMP's own screenshot actually had, rather than a horizontal
  // strip under the frame.
  backdrop.innerHTML =
      '<div class="hub-preview__box">'
    +   '<div class="hub-preview__bar">'
    +     '<span class="hub-preview__title" id="hubFilePreviewTitle"></span>'
    // Download and Share in the header, left of the close button (Liwei,
    // 2026-10-01): at the foot of the side panel a long description and
    // the properties pushed them out of sight. The header is always
    // visible, whatever the panel holds. Download is a static element with
    // its href set per file in renderFilePreview(), as before.
    +     '<div class="hub-file-preview__actions">'
    +       '<a class="hub-file-preview__download" id="hubFilePreviewDownload"'
    +         ' target="_blank" rel="noopener">'
    +         '<svg class="orion-ico--sm orion-ico"><use href="#i-clock"/></svg>Download</a>'
    +       '<button type="button" class="hub-file-preview__share" id="hubFilePreviewShare"'
    +         ' title="' + SHARE_TITLE + '">'
    +         '<svg class="orion-ico--sm orion-ico"><use href="#i-send"/></svg>Share</button>'
    +     '</div>'
    +     '<button class="hub-preview__close" title="Close">&times;</button>'
    +   '</div>'
    +   '<div class="hub-file-preview__main">'
    +     '<iframe class="hub-preview__frame" id="hubFilePreviewFrame"'
    +       ' allow="fullscreen"></iframe>'
    // What stands in for the frame when the file cannot play inside it --
    // a Word/PowerPoint/PDF (Office refuses to be framed, see
    // MODAL_PREVIEWABLE_KINDS) or a zip. Reached through a shared link
    // (fileHash), where the modal opens by itself: a new tab cannot, since
    // browsers block a window.open that no click started.
    +     '<div class="hub-file-preview__stand-in" id="hubFilePreviewStandIn"></div>'
    +     '<div class="hub-file-preview__body">'
    +       '<div class="hub-file-preview__desc" id="hubFilePreviewDesc"></div>'
    +       '<div class="hub-file-preview__table" id="hubFilePreviewInfo"></div>'
    +     '</div>'
    +   '</div>'
    +   '<div class="hub-file-preview__nav">'
    +     '<button type="button" class="hub-file-preview__navbtn" id="hubFilePreviewPrev">'
    +       '<svg class="orion-ico--sm orion-ico"><use href="#i-chevron-left"/></svg>Prev</button>'
    +     '<span id="hubFilePreviewPosition"></span>'
    +     '<button type="button" class="hub-file-preview__navbtn" id="hubFilePreviewNext">'
    +       'Next<svg class="orion-ico--sm orion-ico"><use href="#i-chevron-right"/></svg></button>'
    +   '</div>'
    + '</div>';
  document.body.appendChild(backdrop);

  var shut = function () { closeFilePreview(true); };
  backdrop.querySelector(".hub-preview__close").addEventListener("click", shut);
  document.getElementById("hubFilePreviewShare").addEventListener("click", function () {
    var state = filePreviewState;
    if (state) copyShareLink(this, fileShareUrl(state.asset.id, state.files[state.index].item_id));
  });
  backdrop.addEventListener("click", function (e) { if (e.target === backdrop) shut(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && backdrop.classList.contains("open")) shut();
  });

  document.getElementById("hubFilePreviewPrev").addEventListener("click", function () {
    if (filePreviewState && filePreviewState.index > 0) {
      filePreviewState.index -= 1;
      renderFilePreview();
    }
  });
  document.getElementById("hubFilePreviewNext").addEventListener("click", function () {
    if (filePreviewState && filePreviewState.index < filePreviewState.files.length - 1) {
      filePreviewState.index += 1;
      renderFilePreview();
    }
  });
  return backdrop;
}

function renderFilePreview() {
  var state = filePreviewState;
  if (!state) return;
  var f = state.files[state.index];
  var asset = state.asset;

  var frame = document.getElementById("hubFilePreviewFrame");
  var standIn = document.getElementById("hubFilePreviewStandIn");
  if (MODAL_PREVIEWABLE_KINDS.indexOf(f.kind) !== -1) {
    frame.src = filePreviewUrl(asset.id, f.item_id);
    frame.style.display = "";
    standIn.style.display = "none";
  } else {
    frame.src = "about:blank";
    frame.style.display = "none";
    standIn.style.display = "";
    var opens = PREVIEWABLE_KINDS.indexOf(f.kind) !== -1;
    standIn.innerHTML =
        '<svg class="orion-ico"><use href="#' + (FILE_ICON[f.kind] || "i-file-text") + '"/></svg>'
      + '<div class="hub-file-preview__stand-in-name">' + escapeHtml(f.name) + '</div>'
      + '<div class="hub-file-preview__stand-in-note">'
      + (opens ? "Word, PowerPoint and PDF files open in Office's own viewer, in a new tab."
               : "This kind of file has no preview in the browser. Download it to open it.")
      + '</div>';
    if (opens) {
      var open = document.createElement("a");
      open.className = "btn-primary-sm";
      open.href = filePreviewUrl(asset.id, f.item_id);
      open.target = "_blank";
      open.rel = "noopener";
      open.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-eye"/></svg>Open in browser';
      standIn.appendChild(open);
    }
  }
  document.getElementById("hubFilePreviewTitle").textContent = f.name;
  // The address bar names the open file, so copying it shares the same
  // thing as the Share button. replaceState: stepping through files with
  // Prev/Next should not fill the Back button's history.
  if (location.hash !== fileHash(asset.id, f.item_id)) {
    history.replaceState(null, "", fileHash(asset.id, f.item_id));
  }

  // The demo's own description -- there is no per-video one in our data,
  // and inventing a shorter "what this clip shows" summary would be a
  // guess dressed as a fact, the exact thing this project keeps refusing
  // to ship. Same fallback text as the details page for the same asset.
  setText("hubFilePreviewDesc", asset.description || "No description for this one yet.");

  // The Properties table AMP's screenshot showed, built from what Graph
  // and the asset actually give us -- no invented rows (AMP has a
  // Workfront ID and a Style Template; we have neither, so neither is
  // here). Language is the asset's, not the file's -- AssetResource has
  // no per-file language and every file in one folder is the same demo.
  var rows = [];
  function row(label, value) { if (value) rows.push([label, value]); }
  row("Language", asset.language
    && (LANGUAGE_LABEL[asset.language] || asset.language.toUpperCase()));
  row("Type", f.extension && f.extension.toUpperCase());
  row("Duration", f.duration_seconds && durationLabel(f.duration_seconds));
  row("Resolution", f.width && f.height && (f.width + "×" + f.height));
  row("Size", fileSize(f.size_bytes));
  row("Created", f.created_at);
  row("Created by", f.created_by);
  row("Last modified", f.modified_at);
  row("Modified by", f.modified_by);
  row("Folder", f.subfolder);

  var table = document.getElementById("hubFilePreviewInfo");
  table.innerHTML = rows.map(function (r) {
    return '<div class="hub-file-preview__row">'
         +   '<span class="hub-file-preview__label">' + escapeHtml(r[0]) + '</span>'
         +   '<span class="hub-file-preview__value">' + escapeHtml(r[1]) + '</span>'
         + '</div>';
  }).join("");

  // f.item_id is guaranteed here -- MODAL_PREVIEWABLE_KINDS already
  // required it before this file could reach the modal at all.
  var downloadLink = document.getElementById("hubFilePreviewDownload");
  downloadLink.href = fileDownloadUrl(asset.id, f.item_id);
  downloadLink.hidden = !!asset.downloads_off;

  document.getElementById("hubFilePreviewPrev").disabled = state.index <= 0;
  document.getElementById("hubFilePreviewNext").disabled = state.index >= state.files.length - 1;
  setText("hubFilePreviewPosition", (state.index + 1) + " of " + state.files.length);
}

function openFilePreview(asset, files, index) {
  filePreviewState = { asset: asset, files: files, index: index };
  ensureFilePreviewModal();
  renderFilePreview();
  document.getElementById("hubFilePreviewBackdrop").classList.add("open");
}

/* `restoreHash`: closed by the person (×, Esc, backdrop) rather than by a
 * route change -- the address goes back to the demo's own page. */
function closeFilePreview(restoreHash) {
  var backdrop = document.getElementById("hubFilePreviewBackdrop");
  if (!backdrop || !backdrop.classList.contains("open")) return;
  backdrop.classList.remove("open");
  // Blank the src on close, or a video keeps playing behind the page.
  document.getElementById("hubFilePreviewFrame").src = "about:blank";
  var state = filePreviewState;
  filePreviewState = null;
  if (restoreHash && state && /\/file\//.test(location.hash)) {
    history.replaceState(null, "", "#/asset/" + encodeURIComponent(state.asset.id));
  }
}

/* A shared file link: open that file's preview, stepping through the
 * files of its own tab. A file no longer listed on the demo (renamed or
 * removed since the link was made) leaves the detail page open and says
 * nothing is wrong with the page -- it is the file that is gone. */
function openFileById(asset, itemId) {
  var f = (asset.resources || []).find(function (r) { return r.item_id === itemId; });
  if (!f) {
    console.warn("[hub-api] shared file is no longer listed on", asset.id, itemId);
    return;
  }
  var siblings = previewSiblings(asset, f);
  openFilePreview(asset, siblings, siblings.indexOf(f));
}

/* What Prev/Next steps through: the previewable files of the same tab. A
 * file that has no preview itself (a zip, reached by a shared link) is
 * shown on its own rather than dropped into a list it does not belong to. */
function previewSiblings(asset, f) {
  if (PREVIEWABLE_KINDS.indexOf(f.kind) === -1) return [f];
  return (asset.resources || []).filter(function (r) {
    return r.item_id && PREVIEWABLE_KINDS.indexOf(r.kind) !== -1
           && fileTab(r) === fileTab(f);
  });
}

/* ── details page layout (Liwei, 2026-10-01) ─────────────────────────
 *
 *   [ preview            | Details ]      Details beside the preview,
 *   title, actions, description           capped to its height
 *   [ Files (N) | Value Roadmap ]        one tab bar, Files first
 *
 * Built once by moving Elio's own elements -- his .vp-player and his
 * Value Roadmap card -- into wrappers, so index.html is untouched and the
 * page is reused for every asset as before. */
var ROADMAP_SHOWN = false;
var SECTIONS = [{ key: "files", label: "Files", icon: "i-file-text", pane: "vpPaneFiles" },
                { key: "roadmap", label: "Value Roadmap", icon: "i-target", pane: "vpPaneRoadmap" }];

function ensureDetailLayout(page) {
  if (document.getElementById("vpSections")) return;

  var player = page.querySelector(".vp-player");
  if (player) {
    var top = document.createElement("div");
    top.className = "hub-vp-top";
    player.parentNode.insertBefore(top, player);
    top.appendChild(player);
    var side = document.createElement("div");
    side.className = "hub-vp-side";
    side.id = "vpSide";
    top.appendChild(side);
    // A Details card from before the layout existed moves across too.
    var facts = document.getElementById("vpFacts");
    if (facts) side.appendChild(facts);
  }

  var sections = document.createElement("div");
  sections.className = "hub-sections";
  sections.id = "vpSections";
  var strip = document.createElement("div");
  strip.className = "hub-sections__tabs";
  strip.setAttribute("role", "tablist");
  sections.appendChild(strip);
  SECTIONS.forEach(function (sec) {
    var tab = document.createElement("button");
    tab.type = "button";
    tab.className = "hub-sections__tab";
    tab.setAttribute("role", "tab");
    tab.dataset.section = sec.key;
    tab.innerHTML = '<svg class="orion-ico"><use href="#' + sec.icon + '"/></svg>'
                  + '<span>' + sec.label + '</span>';
    tab.addEventListener("click", function () { selectSection(sec.key); });
    strip.appendChild(tab);
    var pane = document.createElement("div");
    pane.id = sec.pane;
    pane.setAttribute("role", "tabpanel");
    sections.appendChild(pane);
  });

  var desc = document.getElementById("vpDesc");
  if (desc) desc.parentNode.insertBefore(sections, desc.nextSibling);
  else page.appendChild(sections);

  var drivers = document.getElementById("vpValueDrivers");
  var roadmap = drivers && drivers.closest(".vp-card");
  if (roadmap) document.getElementById("vpPaneRoadmap").appendChild(roadmap);
}

function selectSection(key) {
  var sections = document.getElementById("vpSections");
  if (!sections) return;
  sections.querySelectorAll(".hub-sections__tab").forEach(function (t) {
    var on = t.dataset.section === key;
    t.classList.toggle("hub-sections__tab--active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  SECTIONS.forEach(function (sec) {
    var pane = document.getElementById(sec.pane);
    if (pane) pane.style.display = sec.key === key ? "" : "none";
  });
}

/* After a page's content is in: which tabs have something, their labels,
 * and which one shows. Files first whenever there are files. A tab with
 * nothing behind it is greyed rather than hidden, so "no files" reads as a
 * fact; a page with neither (a VM page) drops the bar altogether. */
function settleSectionTabs(asset) {
  var sections = document.getElementById("vpSections");
  if (!sections) return;
  var hasFiles = !!document.querySelector("#vpPaneFiles .vp-files");
  // Hidden until the indexing is ready (Seb, 2026-10-28: nothing is
  // indexed for the first release). Back: asset.type !== "vm".
  var hasRoadmap = ROADMAP_SHOWN && asset.type !== "vm";
  var counts = asset.resource_counts || {};
  var fileTotal = Object.keys(counts).reduce(function (n, k) { return n + (counts[k] || 0); }, 0)
                  || (asset.resources || []).length;
  sections.querySelectorAll(".hub-sections__tab").forEach(function (t) {
    if (t.dataset.section === "files") {
      t.disabled = !hasFiles;
      t.querySelector("span").textContent = "Files" + (hasFiles ? " (" + fileTotal + ")" : "");
    } else {
      t.disabled = !hasRoadmap;
      t.style.display = ROADMAP_SHOWN ? "" : "none";
    }
  });
  sections.style.display = hasFiles || hasRoadmap ? "" : "none";
  selectSection(hasFiles ? "files" : "roadmap");
}

function renderFactsTable(page, asset) {
  var card = document.getElementById("vpFacts");
  if (!card) {
    card = document.createElement("div");
    card.id = "vpFacts";
    card.className = "vp-card hub-facts";
    var side = document.getElementById("vpSide");
    var desc = document.getElementById("vpDesc");
    if (side) side.appendChild(card);
    else if (desc && desc.parentNode) desc.parentNode.insertBefore(card, desc.nextSibling);
    else return;
  }
  card.innerHTML = "";

  // Products by family only: the detailed names repeated them (Liwei, 2026-10-29).
  var families = (asset.product_families || []).map(familyDisplayName);
  var yesNo = function (v) { return v === true ? "Yes" : v === false ? "No" : null; };
  var rows = [
    ["Asset type", TYPE_LONG[asset.type] || asset.type],
    ["Video type", videoTypeOf(asset)],
    ["Products", families.join(", ")],
    // "N/A" says no version applies (A11): nothing to show.
    ["Product version", /^n\/?a$/i.test((asset.product_version || "").trim()) ? null
                        : asset.product_version],
    ["Segment", asset.segment],
    ["Stage", asset.funnel_stage],
    ["Industry", asset.industry],
    ["Customer", asset.named_customer],
    ["Language", asset.language ? (LANGUAGE_LABEL[asset.language] || asset.language.toUpperCase()) : null,
     "language"],
    ["Customer-facing", yesNo(asset.customer_facing), "customer_facing"],
    ["Narrated audio", yesNo(asset.has_narrated_audio), "has_narrated_audio"],
    ["Length", asset.type === "ldk" ? null : durationLabel(asset.duration_seconds)],
    // "Published" only for a date someone stated (dateLabel in util.js).
    [asset.date_stated ? "Published" : "Updated",
     asset.uploaded_at ? dateLabel(asset).replace(/^\S+ /, "") : null]
  ];

  var table = document.createElement("table");
  table.className = "hub-facts__table";
  rows.forEach(function (r) {
    if (!r[1]) return;
    var tr = table.insertRow();
    var th = document.createElement("th");
    th.textContent = r[0];
    tr.appendChild(th);
    var cell = tr.insertCell();
    cell.textContent = r[1];
    // Inferred, not filled in SharePoint (sharepoint_mapping.mark_assumed).
    if (r[2] && (asset.assumed || []).indexOf(r[2]) >= 0) {
      var mark = document.createElement("span");
      mark.className = "hub-facts__assumed";
      mark.textContent = "assumed";
      mark.title = "Not filled in SharePoint: the Hub worked this out "
        + (r[2] === "language" ? "(English when none is set)" : "from the file names")
        + ". Edit sets it for good.";
      cell.appendChild(mark);
    }
  });
  // Who to ask (A4, 2026-10-26): the Demo Owner, as a mail link.
  if (asset.demo_owner) {
    var owner = table.insertRow();
    var oh = document.createElement("th");
    oh.textContent = "Demo owner";
    owner.appendChild(oh);
    var mail = document.createElement("a");
    mail.href = "mailto:" + asset.demo_owner;
    mail.textContent = asset.creator || asset.demo_owner;
    mail.title = asset.demo_owner;
    owner.insertCell().appendChild(mail);
  }

  var tags = asset.extra_tags || [];
  if (tags.length) {
    var tr = table.insertRow();
    var th = document.createElement("th");
    th.textContent = "Tags";
    tr.appendChild(th);
    var td = tr.insertCell();
    tags.forEach(function (t) {
      var chip = document.createElement("span");
      chip.className = "orion-badge orion-badge--action";
      chip.textContent = t;
      chip.title = "Show every asset tagged \u201c" + t + "\u201d";
      chip.setAttribute("role", "button");
      chip.tabIndex = 0;
      chip.addEventListener("click", function () { openTag(t); });
      chip.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openTag(t); }
      });
      td.appendChild(chip);
    });
  }

  var head = document.createElement("div");
  head.className = "vp-card__head";
  head.innerHTML = '<div class="vp-card__head-title"><svg class="orion-ico">'
                 + '<use href="#i-hex"/></svg>Details</div>';
  card.appendChild(head);
  // Edit, for people with Edit metadata (A1, 2026-10-26; edit.js).
  var tools = document.createElement("div");
  tools.className = "hub-edit__tools";
  tools.appendChild(editButton(asset));
  card.appendChild(tools);
  card.appendChild(table);

  /* The sheet's Long Description, last in the section (Liwei,
   * 2026-09-30). Prose, so a block under the table rather than one more
   * row squeezed beside a 170px label. Demo Video assets only; nothing is
   * drawn when there is none. */
  if (asset.long_description && asset.long_description !== asset.description) {
    var long = document.createElement("div");
    long.className = "hub-facts__long";
    var label = document.createElement("div");
    label.className = "hub-facts__long-label";
    label.textContent = "Detail Description";
    var text = document.createElement("div");
    text.className = "hub-facts__long-text";
    text.textContent = asset.long_description;
    long.appendChild(label);
    long.appendChild(text);
    card.appendChild(long);
  }
}

var FILE_TABS = [{ key: "video", label: "Videos" },
                 { key: "document", label: "Documents" }];

function fileTab(f) { return f.kind === "video" ? "video" : "document"; }

function fileFacts(f) {
  return [f.extension && f.extension.toUpperCase(),
          f.duration_seconds && durationLabel(f.duration_seconds),
          fileSize(f.size_bytes),
          f.width && f.height && (f.width + "×" + f.height),
          f.audience === "customer_facing" ? "customer-facing"
            : f.audience === "internal" ? "internal" : null,
          f.subfolder].filter(Boolean).join(" · ");
}

/* The file name on the details page.
 *
 * Seb, review: the old "Preview" pill "looked like a tag", and asked for
 * the file name itself to be the preview link, with a real Download button
 * at the far right instead. So the name opens a preview -- the modal for
 * video/image, a new tab for Word/PowerPoint/PDF (see
 * MODAL_PREVIEWABLE_KINDS for why not the modal) -- and a CAD dataset
 * (.zip/.rar) or a resource synced before item_id existed is plain text.
 * Real <a>s, not string-built ones: an href assigned as a DOM property
 * needs no attribute-quote escaping. */
function detailFileName(asset, f) {
  var name;
  if (f.item_id && MODAL_PREVIEWABLE_KINDS.indexOf(f.kind) !== -1) {
    name = document.createElement("a");
    name.href = "#";
    name.title = "Preview";
    name.addEventListener("click", function (e) {
      e.preventDefault();
      var siblings = previewSiblings(asset, f);
      openFilePreview(asset, siblings, siblings.indexOf(f));
    });
  } else if (f.item_id && PREVIEWABLE_KINDS.indexOf(f.kind) !== -1) {
    name = document.createElement("a");
    name.href = filePreviewUrl(asset.id, f.item_id);
    name.target = "_blank";
    name.rel = "noopener";
    name.title = "Preview in a new tab";
  } else {
    name = document.createElement("span");
  }
  name.className = "vp-file__name";
  name.textContent = f.name;
  return name;
}

/* One file row: icon, name (built by the caller -- the details page and
 * Advanced Search open files differently), facts, then Download and Share
 * at the far right. `.vp-file__facts` has margin-left:auto, which pushes
 * everything after it right. Both buttons need the file's item_id: it is
 * what a download resolves and what a shared link names.
 *
 * `noActions`: Advanced Search lists files under a demo, and a Download or
 * Share there read as acting on the whole demo (Liwei, 2026-10-01). The
 * file name still opens its preview, where both buttons are. */
function buildFileRow(asset, f, nameEl, noActions) {
  var row = document.createElement("div");
  row.className = "vp-file";
  row.innerHTML =
      '<svg class="orion-ico orion-ico--sm ico-muted"><use href="#'
    +   (FILE_ICON[f.kind] || "i-file-text") + '"/></svg>'
    + '<span class="vp-file__facts">' + escapeHtml(fileFacts(f)) + '</span>';
  row.insertBefore(nameEl, row.lastChild);

  if (f.item_id && !noActions) {
    // A GXC video while Admin keeps its downloads off: no button (the
    // server refuses the download too).
    if (!asset.downloads_off) {
      var download = document.createElement("a");
      download.className = "vp-file__download";
      download.href = fileDownloadUrl(asset.id, f.item_id);
      download.target = "_blank";
      download.rel = "noopener";
      download.title = "Download";
      download.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-clock"/></svg>Download';
      row.appendChild(download);
    }

    var share = document.createElement("button");
    share.type = "button";
    share.className = "vp-file__share";
    share.title = SHARE_TITLE;
    share.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-send"/></svg>Share';
    share.addEventListener("click", function () {
      copyShareLink(share, fileShareUrl(asset.id, f.item_id));
    });
    row.appendChild(share);
  }
  return row;
}

/* ── The page's own story (Jorge, 2026-10-21) ───────────────────────────
 *
 * A demo whose SharePoint page an author laid out (Hill Helicopters IPL)
 * brings that page's intro, sections and file order along
 * (backend/integrations/graph/demo_pages.overview_of). Merged into the
 * page rather than added below it, so nothing is said twice: the intro
 * takes the description's place, clamped with "Read more"; the sections
 * take the flat file list's place, each one folding, the first open, and
 * the folder's other files last, folded. */
function storyBlocks(host, blocks) {
  var list = null;
  (blocks || []).forEach(function (b) {
    if (b.kind === "li") {
      if (!list) { list = document.createElement("ul"); host.appendChild(list); }
      var li = document.createElement("li");
      li.textContent = b.text;
      list.appendChild(li);
      return;
    }
    list = null;
    var p = document.createElement("p");
    p.textContent = b.text;
    host.appendChild(p);
  });
}

/* The page's text in place of the description. When its sections name no
 * file the Hub lists (a written guide, not a story), their headings and
 * text follow the intro here and the files keep their tabs. */
function renderStoryIntro(asset) {
  var overview = asset.overview;
  var desc = document.getElementById("vpDesc");
  if (!desc || !overview) return false;
  var intro = overview.intro || [];
  var sections = storySections(asset) ? [] : (overview.sections || []);
  if (!intro.length && !sections.length) return false;
  desc.innerHTML = "";
  var body = document.createElement("div");
  body.className = "hub-story__intro";
  storyBlocks(body, intro);
  sections.forEach(function (s) {
    if (s.title) {
      var h = document.createElement("h4");
      h.textContent = s.title;
      body.appendChild(h);
    }
    storyBlocks(body, s.text);
  });
  desc.appendChild(body);
  // Clamped once it has been laid out; "Read more" only when it overflows.
  requestAnimationFrame(function () {
    if (body.scrollHeight <= body.clientHeight + 2) return;
    var more = document.createElement("button");
    more.type = "button";
    more.className = "hub-story__more";
    more.textContent = "Read more";
    more.addEventListener("click", function () {
      var open = body.classList.toggle("hub-story__intro--open");
      more.textContent = open ? "Show less" : "Read more";
    });
    desc.appendChild(more);
  });
  return true;
}

function storyPath(f) {
  return ((f.subfolder ? f.subfolder + "/" : "") + (f.name || "")).toLowerCase();
}

/* The sections, or null when none of them names a file the Hub lists. */
function storySections(asset) {
  var sections = (asset.overview && asset.overview.sections) || [];
  var files = asset.resources || [];
  var byPath = {};
  files.forEach(function (f) { byPath[storyPath(f)] = f; });
  var used = {};
  var out = sections.map(function (s) {
    var mine = (s.files || []).map(function (p) { return byPath[String(p).toLowerCase()]; })
      .filter(function (f) { return f && !used[storyPath(f)] && (used[storyPath(f)] = true); });
    return { title: s.title, text: s.text, files: mine };
  });
  if (!out.some(function (s) { return s.files.length; })) return null;
  var rest = files.filter(function (f) { return !used[storyPath(f)]; });
  if (rest.length) out.push({ title: "Other files", text: [], files: rest, other: true });
  return out;
}

function renderStorySections(box, asset, sections) {
  var first = true;
  sections.forEach(function (s) {
    var group = document.createElement("details");
    group.className = "hub-story__section" + (s.other ? " hub-story__section--other" : "");
    group.open = first && !s.other;
    first = false;
    var head = document.createElement("summary");
    head.className = "hub-story__head";
    var title = document.createElement("span");
    title.className = "hub-story__title";
    title.textContent = s.title || "Files";
    head.appendChild(title);
    var count = document.createElement("span");
    count.className = "hub-story__count";
    count.textContent = s.files.length + (s.files.length === 1 ? " file" : " files");
    head.appendChild(count);
    group.appendChild(head);
    if (s.text && s.text.length) {
      var text = document.createElement("div");
      text.className = "hub-story__text";
      storyBlocks(text, s.text);
      group.appendChild(text);
    }
    var list = document.createElement("div");
    list.className = "vp-files__list";
    s.files.forEach(function (f) {
      list.appendChild(buildFileRow(asset, f, detailFileName(asset, f)));
    });
    group.appendChild(list);
    box.appendChild(group);
  });
}

function renderFileList(page, asset, openTab) {
  var existing = page.querySelector(".vp-files");
  if (existing) existing.remove();

  var files = asset.resources || [];
  var counts = asset.resource_counts || {};
  if (!files.length && !asset.resource_count) return;

  var box = document.createElement("div");
  box.className = "vp-card vp-files";

  // Same words and order as Advanced Search: videos, documents, others
  // (Liwei, 2026-10-01) -- not every raw kind ("dataset", "cad") A to Z.
  var summary = fileTotalsText(counts);

  box.innerHTML = '<div class="vp-card__head"><div class="vp-card__head-title">'
    + '<svg class="orion-ico"><use href="#i-file-text"/></svg>Files in this folder'
    + '</div><span class="vp-files__summary">' + escapeHtml(summary) + '</span></div>';

  // "Download all" (button here) is gone -- Liwei, 2026-09-10: Download
  // Kit, in the actions row above the fold, is the one path to the whole
  // kit now. It lands on the asset's SharePoint page rather than zipping
  // directly (see that button's own comment for why), but that page is
  // where the real "Download a copy" zip action lives.

  /* A partner on a demo whose SharePoint folder is closed to partners
   * gets the file names without the ids that open them (the server strips
   * them; 2026-10-06), so every row is plain text -- this says why. */
  if (asset.files_locked) {
    var locked = document.createElement("div");
    locked.className = "vp-files__note";
    locked.style.margin = "0 0 10px";
    locked.textContent = "These files can't be previewed or downloaded with your account. "
      + "Ask your PTC contact if you need them.";
    box.appendChild(locked);
  }

  /* Two tabs, Videos and Documents (Liwei, 2026-09-30). "Documents" is
   * everything that is not a video -- the PowerPoint and the script, and
   * also a zipped dataset or an image, since there are only two tabs and
   * a folder rarely holds more than a couple of those. A tab with nothing
   * in it stays visible, disabled, so "no videos" reads as a fact rather
   * than a missing control. */
  // The author's sections and order, when the demo's page has them.
  var story = !openTab && storySections(asset);
  if (story) {
    renderStorySections(box, asset, story);
    (document.getElementById("vpPaneFiles") || page).appendChild(box);
    return;
  }

  var byTab = { video: [], document: [] };
  files.forEach(function (f) { byTab[fileTab(f)].push(f); });
  var active = openTab || (byTab.video.length ? "video" : "document");

  var strip = document.createElement("div");
  strip.className = "hub-files-tabs";
  strip.setAttribute("role", "tablist");
  box.appendChild(strip);

  var panes = {};
  FILE_TABS.forEach(function (t) {
    var tab = document.createElement("button");
    tab.type = "button";
    tab.className = "hub-files-tab";
    tab.setAttribute("role", "tab");
    tab.dataset.tab = t.key;
    tab.textContent = t.label + " (" + byTab[t.key].length + ")";
    tab.disabled = !byTab[t.key].length;
    tab.addEventListener("click", function () { select(t.key); });
    strip.appendChild(tab);

    var list = document.createElement("div");
    list.className = "vp-files__list";
    byTab[t.key].forEach(function (f) {
      list.appendChild(buildFileRow(asset, f, detailFileName(asset, f)));
    });
    panes[t.key] = list;
    box.appendChild(list);
  });

  function select(key) {
    strip.querySelectorAll(".hub-files-tab").forEach(function (b) {
      var on = b.dataset.tab === key;
      b.classList.toggle("hub-files-tab--active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    Object.keys(panes).forEach(function (k) {
      panes[k].style.display = k === key ? "" : "none";
    });
  }
  select(active);

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

  (document.getElementById("vpPaneFiles") || page).appendChild(box);
}

/* Listed from its SharePoint page alone: no project folder, so no files
 * (backend/integrations/graph/demo_pages.py). */
function isPageOnly(asset) {
  return !!asset.page_url && asset.page_url === asset.web_url;
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

/* Arriving on a link someone shared, and the back button, are the same
 * thing: read the hash and show whatever it names. */
var REQUEST_FORM_HIDDEN = true;

function routeFromHash() {
  var hash = location.hash || "";
  // The request form is hidden for the first release (Elio, Seb,
  // 2026-10-28); an old link to it lands on Home.
  if (hash === "#/request" && REQUEST_FORM_HIDDEN) {
    history.replaceState(null, "", location.pathname + location.search);
    hash = "";
  }
  if (hash === "#/request") {
    closeFilePreview(false);
    closeAssetDetail();
    if (typeof window.openRequestView === "function") window.openRequestView();
    return;
  }
  // Any other address: the request form is not where we are (2026-10-14,
  // so Back from it, or a link elsewhere, leaves it like any other view).
  var requestPage = document.getElementById("requestViewPage");
  if (requestPage && requestPage.classList.contains("active")
      && typeof window.closeRequestView === "function") {
    window.closeRequestView();
  }
  if (hash === "#/help") {
    closeFilePreview(false);
    closeAssetDetail();
    closeUpload();
    closeActivity();
    closeReview();
    openHelp();
    return;
  }
  closeHelp();
  if (hash === "#/review") {
    closeFilePreview(false);
    closeAssetDetail();
    closeUpload();
    closeActivity();
    openReview();
    return;
  }
  closeReview();
  if (hash === "#/activity") {
    closeFilePreview(false);
    closeAssetDetail();
    closeUpload();
    openActivity();
    return;
  }
  closeActivity();
  if (hash === "#/upload") {
    closeFilePreview(false);
    closeAssetDetail();
    openUpload();
    return;
  }
  closeUpload();
  var search = /^#\/search\/(.*)$/.exec(hash);
  if (search) {
    closeFilePreview(false);
    closeAssetDetail();
    openAdvancedSearch(decodeURIComponent(search[1]));
    return;
  }
  var file = /^#\/asset\/([^/]+)\/file\/([^/]+)$/.exec(hash);
  if (file) {
    openAssetDetail(decodeURIComponent(file[1]), decodeURIComponent(file[2]));
    return;
  }
  closeFilePreview(false);
  var match = /^#\/asset\/(.+)$/.exec(hash);
  if (match) { openAssetDetail(decodeURIComponent(match[1])); return; }
  closeAdvancedSearch();
  closeAssetDetail();
}

function closeAssetDetail() {
  var page = document.getElementById("videoPreviewPage");
  if (page) {
    page.classList.remove("active");
    // Same bug as openAssetDetail() guards against, the other direction:
    // leaving the detail page entirely must not leave its video playing,
    // invisibly, behind the grid.
    var player = page.querySelector(".vp-player");
    if (player) stopInlinePlayer(player);
  }
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
  if (back) back.addEventListener("click", function (e) {
    if (detailReturnHash) {
      // Synchronously, not via hashchange, so no frame of the catalogue
      // flashes. And no further: hub-ui.js's "close-detail", on document,
      // would put the catalogue back under the view returned to (2026-10-28).
      e.stopPropagation();
      history.pushState(null, "", detailReturnHash);
      detailReturnHash = null;
      routeFromHash();
      return;
    }
    if (location.hash.indexOf("#/asset/") === 0) {
      history.pushState(null, "", location.pathname + location.search);
    }
    closeAssetDetail();
  });
  routeFromHash();          // honour a link opened cold
}

/* ── Open / Internal on a demo's page (2026-10-07) ─────────────────────
 *
 * Everyone sees a "PTC Only" tag (called Internal until Elio and Seb
 * renamed it, 2026-10-28: partners cannot open it, every PTC person can),
 * so nobody shares such a demo outside
 * PTC by mistake. People with "Manage content access" also get a small
 * switch beside it. A demo closed to partners in SharePoint is Internal
 * there and opened only there, so it gets the tag and no switch.
 */
function renderAccessMark(meta, asset) {
  // State only; changing it is the Manage card's job (renderManage).
  meta.querySelectorAll(".hub-pill--internal").forEach(function (n) { n.remove(); });
  if (!asset.internal) return;
  // A GXC video (2026-10-29) says so instead: only a few people see it.
  var tag = pill(asset.gxc ? "GXC only" : "PTC Only", "internal");
  tag.title = asset.gxc
    ? "A GXC video: only people with View GXC videos can see it on the Hub. "
      + "Share it only with them."
    : (asset.internal_source === "sharepoint"
      ? "Closed to partners in SharePoint. " : "Marked PTC Only on the Hub. ")
      + "Partners cannot open its files, and it is not customer facing.";
  meta.appendChild(tag);
}

/* ── Manage: access, review and archive, a tab beside Details (2026-10-15)
 *
 * Liwei: Make Internal, Mark Still current and Archive sat among the tags
 * under the title, looking like tags, where a click meant for one could
 * change a demo. They live in a Manage tab of the Details card now (a card
 * of their own above Details took too much of the column): a row per thing
 * that can change, its state on the left and its action on the right. The
 * tag row shows state only. The tab is there only for someone who may do
 * something in it; for everyone else the card is Details, as before.
 *
 * Access goes through requests for most people (services/access_requests.py,
 * Elio 2026-10-07: a controlled, tracked process): "Request Internal" with a
 * reason; someone with Manage content access approves or rejects it, here or
 * on Admin -> Content access. They may also change it directly, with a reason.
 * Changing access and archiving ask for confirmation; everything is in the
 * Admin log. The tab last chosen is kept from demo to demo, so a reviewer
 * working through a list stays on Manage; a waiting request puts a dot on it
 * for whoever may decide.
 */
function mk(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function whoName(actor) {
  if (actor === "admin-session") return "the admin account";
  return String(actor || "someone").replace(/^(user|dev):/, "");
}

function onDay(iso) {
  return iso ? fullDate(String(iso).slice(0, 10)) : "";
}

function manageButton(text, primary) {
  var b = mk("button", "hub-manage__btn" + (primary ? " hub-manage__btn--primary" : ""), text);
  b.type = "button";
  return b;
}

function send(method, url, body) {
  return fetch(url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
      return d;
    });
  });
}

/* An inline step under a row: a text box and Confirm / Cancel. */
function confirmStep(row, opts) {
  row.querySelectorAll(".hub-manage__form").forEach(function (n) { n.remove(); });
  var form = mk("div", "hub-manage__form");
  if (opts.lead) form.appendChild(mk("p", "hub-manage__lead", opts.lead));
  // No placeholder, no box: a plain "are you sure" (Restore, 2026-10-30).
  var box = mk("textarea", "hub-manage__input");
  box.rows = 2;
  box.maxLength = 1000;
  box.placeholder = opts.placeholder || "";
  if (opts.placeholder) form.appendChild(box);
  var err = mk("p", "hub-manage__err");
  var bar = mk("div", "hub-manage__formbar");
  var ok = manageButton(opts.confirm, true);
  var cancel = manageButton("Cancel");
  bar.appendChild(ok);
  bar.appendChild(cancel);
  form.appendChild(bar);
  form.appendChild(err);
  cancel.addEventListener("click", function () { form.remove(); });
  ok.addEventListener("click", function () {
    var text = opts.placeholder ? box.value.trim() : "";
    if (opts.required && !text) { err.textContent = "Please say why."; box.focus(); return; }
    ok.disabled = cancel.disabled = true;
    err.textContent = "";
    opts.submit(text).catch(function (e) {
      ok.disabled = cancel.disabled = false;
      err.textContent = e.message;
    });
  });
  row.appendChild(form);
  (opts.placeholder ? box : ok).focus();
}

function manageRow(label) {
  var row = mk("div", "hub-manage__row");
  var line = mk("div", "hub-manage__line");
  line.appendChild(mk("div", "hub-manage__label", label));
  var state = mk("div", "hub-manage__state");
  line.appendChild(state);
  var actions = mk("div", "hub-manage__actions");
  line.appendChild(actions);
  row.appendChild(line);
  return { row: row, state: state, actions: actions };
}

function setState(state, main, sub) {
  state.innerHTML = "";
  state.appendChild(mk("b", null, main));
  if (sub) state.appendChild(mk("span", null, sub));
}

function refreshMarks(asset) {
  var meta = document.getElementById("vpMeta");
  if (meta) { renderAccessMark(meta, asset); renderAgeMark(meta, asset); }
  renderManage(asset);
}

function accessRow(asset, may, view) {
  var r = manageRow("Access");
  var url = "/api/assets/" + encodeURIComponent(asset.id);
  var target = asset.internal ? "open" : "internal";
  var word = asset.internal ? "Open" : "PTC Only";
  if (!asset.internal) {
    setState(r.state, "Open", "Everyone who may preview and download opens its files.");
  } else if (asset.internal_source === "sharepoint") {
    setState(r.state, "PTC Only", "Closed to partners in SharePoint; it can be opened only there.");
  } else {
    setState(r.state, "PTC Only", "Marked on the Hub. Partners cannot open its files.");
  }
  var locked = asset.internal && asset.internal_source === "sharepoint";
  var pending = view && view.pending;

  if (!locked && !pending && may.manage) {
    var direct = manageButton("Make " + word);
    direct.addEventListener("click", function () {
      confirmStep(r.row, {
        lead: target === "internal"
          ? "Partners will not open its files, and it will no longer be customer facing "
            + "(Customer facing is set to No in SharePoint)."
          : "Everyone who may preview and download will open its files.",
        placeholder: "Reason (optional, kept in the log)",
        confirm: "Make " + word,
        submit: function (reason) {
          return send("PUT", url + "/access", { level: target, reason: reason || null })
            .then(function (d) {
              asset.internal = d.internal;
              asset.internal_source = d.internal_source;
              if (d.internal) asset.customer_facing = false;
              refreshMarks(asset);
            });
        }
      });
    });
    r.actions.appendChild(direct);
  }

  if (pending) {
    var box = mk("div", "hub-manage__request");
    box.appendChild(mk("div", "hub-manage__request-head",
      whoName(pending.requested_by) + " asked to make it "
      + (pending.level === "internal" ? "PTC Only" : "Open") + " · " + onDay(pending.requested_at)));
    box.appendChild(mk("q", "hub-manage__reason", pending.reason));
    var bar = mk("div", "hub-manage__formbar");
    if (may.manage) {
      var approve = manageButton("Approve", true);
      var reject = manageButton("Reject");
      var decide = function (yes) {
        confirmStep(box, {
          placeholder: yes ? "Note (optional)" : "Why not? (optional, the requester sees it)",
          confirm: yes ? "Approve and apply" : "Reject",
          submit: function (note) {
            return send("POST", "/api/admin/access-requests/" + encodeURIComponent(pending.id)
                        + "/decision", { approve: yes, note: note || null })
              .then(function () {
                if (yes) {
                  asset.internal = pending.level === "internal";
                  asset.internal_source = asset.internal ? "hub" : null;
                }
                refreshMarks(asset);
              });
          }
        });
      };
      approve.addEventListener("click", function () { decide(true); });
      reject.addEventListener("click", function () { decide(false); });
      bar.appendChild(approve);
      bar.appendChild(reject);
    }
    if (!bar.children.length) bar.appendChild(mk("span", "hub-manage__note", "Waiting for a decision."));
    box.appendChild(bar);
    r.row.appendChild(box);
  } else if (view && view.history && view.history.length) {
    var last = view.history[0];
    if (last.status !== "withdrawn") {
      var line = (last.status === "approved" ? "Last request approved" : "Last request rejected")
        + " by " + whoName(last.decided_by) + " · " + onDay(last.decided_at)
        + (last.note ? " — " + last.note : "");
      r.row.appendChild(mk("p", "hub-manage__note", line));
    }
  }
  return r.row;
}

function stillCurrentRow(asset) {
  var r = manageRow("Review");
  var on = !!asset.still_current_until;
  setState(r.state, on ? "Still current" : "Not confirmed", on
    ? "Until " + onDay(asset.still_current_until)
      + (asset.still_current_by ? " · " + whoName(asset.still_current_by) : "")
    : "Confirm the interface shown matches today's release; it lasts a year.");
  var b = manageButton(on ? "Withdraw" : "Mark Still current");
  b.addEventListener("click", function () {
    b.disabled = true;
    send("PUT", "/api/assets/" + encodeURIComponent(asset.id) + "/still-current",
         { still_current: !on })
      .then(function (d) {
        asset.still_current_until = d.still_current_until;
        asset.still_current_by = d.still_current_by;
        refreshMarks(asset);
      })
      .catch(function (e) { b.disabled = false; report("Could not change Still current: " + e.message, true); });
  });
  r.actions.appendChild(b);
  return r.row;
}

/* Archive (A8, 2026-10-28): a SharePoint demo's folder moves into its
   library's _Archive, which only the team can open; anything else leaves
   the Hub's lists only. "Archive content" decides who may. */
function inSharePoint(asset) {
  return (asset.source || "sharepoint") === "sharepoint" && asset.id.indexOf("page-") !== 0
    && ["video", "ldk", "vdk"].indexOf(asset.type) >= 0;
}

function archiveRow(asset) {
  var r = manageRow("Archive");
  var moves = inSharePoint(asset);
  setState(r.state, asset.archived ? "Archived" : "Listed", asset.archived
    ? "Out of the Hub's lists and search" + (asset.archived_at ? " since " + onDay(asset.archived_at) : "")
      + (asset.sharepoint_archived ? ". Its folder is in SharePoint's _Archive."
         : moves ? ". Its folder is still where it was in SharePoint (archived before _Archive)."
         : ".")
    : "In the Hub's lists and search.");
  var url = "/api/assets/" + encodeURIComponent(asset.id) + "/archive";
  var apply = function (on, reason) {
    return send("PUT", url, { archived: on, reason: reason || null }).then(function (d) {
      asset.archived = d.archived;
      asset.archived_at = d.archived ? new Date().toISOString() : null;
      if (moves) asset.sharepoint_archived = d.archived;
      refreshMarks(asset);
      renderManage(asset);
    });
  };
  var b = manageButton(asset.archived ? "Restore" : "Archive");
  b.addEventListener("click", function () {
    if (asset.archived) {
      // Asked first, as Archive is (Liwei 2026-10-30).
      confirmStep(r.row, {
        lead: moves && asset.sharepoint_archived
          ? "Its folder moves back out of SharePoint's _Archive, takes the library's "
            + "permissions again (partners included where the library allows them), and it "
            + "returns to the Hub's lists and search."
          : "It returns to the Hub's lists and search.",
        confirm: "Restore",
        submit: function () { return apply(false); }
      });
      return;
    }
    confirmStep(r.row, {
      lead: moves
        ? "Its folder moves into SharePoint's _Archive, which only the team can open, and it "
          + "leaves the Hub's lists and search. Checking permissions first can take a moment. "
          + "Restore moves it back."
        : "It leaves the Hub's lists and search; nothing is moved. Restore any time.",
      placeholder: "Reason (optional, kept in the log)",
      confirm: "Archive",
      submit: function (reason) { return apply(true, reason); }
    });
  });
  r.actions.appendChild(b);
  return r.row;
}

var sideTab = "details";   // the tab last chosen, kept from demo to demo

/* Turns the Details card's title into a Details | Manage tab strip, with
   everything under the title moved into the Details pane. Once per render
   of the card (renderFactsTable rebuilds it for every demo). */
function sideTabs(card) {
  var strip = card.querySelector(".hub-sidetabs");
  if (strip) return strip;
  var head = card.querySelector(".vp-card__head");
  if (!head) return null;
  var details = mk("div", "hub-sidepane");
  details.dataset.pane = "details";
  while (head.nextSibling) details.appendChild(head.nextSibling);
  var manage = mk("div", "hub-sidepane hub-manage");
  manage.dataset.pane = "manage";
  manage.id = "vpManage";
  strip = mk("div", "hub-sidetabs");
  strip.setAttribute("role", "tablist");
  [["details", "Details", "i-hex"], ["manage", "Manage", "i-flag"]].forEach(function (t) {
    var tab = mk("button", "hub-sidetabs__tab");
    tab.type = "button";
    tab.setAttribute("role", "tab");
    tab.dataset.pane = t[0];
    tab.innerHTML = '<svg class="orion-ico"><use href="#' + t[2] + '"/></svg>';
    tab.appendChild(mk("span", null, t[1]));
    tab.addEventListener("click", function () {
      sideTab = t[0];
      showSideTab(card);
    });
    strip.appendChild(tab);
  });
  head.replaceWith(strip);
  card.appendChild(details);
  card.appendChild(manage);
  return strip;
}

function showSideTab(card) {
  card.querySelectorAll(".hub-sidetabs__tab").forEach(function (t) {
    var on = t.dataset.pane === sideTab;
    t.classList.toggle("hub-sidetabs__tab--active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  card.querySelectorAll(".hub-sidepane").forEach(function (p) {
    p.hidden = p.dataset.pane !== sideTab;
  });
}

/* An upload not yet published (services/uploads.py): the reviewer's
   Publish / Send back, on the page where they can see what was uploaded. */
function uploadRow(asset, record) {
  var r = manageRow("Upload");
  var by = whoName(record.uploaded_by);
  // Left from before review was removed (2026-10-28): published by hand.
  setState(r.state, asset.upload_review === "sent_back" ? "Sent back" : "Not published",
           "Uploaded by " + by + " · " + onDay(record.submitted_at || record.created_at)
           + (record.internal ? " · asked to be Internal" : ""));
  if (record.status === "pending") {
    var publish = manageButton("Publish", true);
    publish.addEventListener("click", function () {
      confirmStep(r.row, {
        lead: "It will be listed in the Hub for everyone who may see it"
          + (record.internal ? ", as Internal." : "."),
        placeholder: "Note (optional)",
        confirm: "Publish",
        submit: function (note) {
          return send("POST", "/api/uploads/" + encodeURIComponent(record.id) + "/publish",
                      { note: note || null })
            .then(function () {
              asset.upload_review = null;
              if (record.internal) { asset.internal = true; asset.internal_source = "hub"; }
              var meta = document.getElementById("vpMeta");
              if (meta) meta.querySelectorAll(".hub-pill--upload").forEach(function (n) { n.remove(); });
              refreshMarks(asset);
            });
        }
      });
    });
    r.actions.appendChild(publish);
  } else if (record.note) {
    r.row.appendChild(mk("p", "hub-manage__note", "Note: " + record.note));
  }
  return r.row;
}

function renderManage(asset) {
  var card = document.getElementById("vpFacts");
  if (!card) return;
  hubPermissions.then(function (granted) {
    granted = granted || [];
    // One permission since 2026-10-30, Maintain content; kept apart here
    // as the three things it allows on this card.
    var on = granted.indexOf("maintain_content") >= 0;
    var may = { manage: on, review: on, archive: on };
    if (detailAsset !== asset || (!may.manage && !may.review && !may.archive)) {
      return null;
    }
    var requests = may.manage
      ? fetch("/api/assets/" + encodeURIComponent(asset.id) + "/access-requests")
          .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
      : Promise.resolve(null);
    var upload = (may.review && asset.upload_review)
      ? fetch("/api/uploads?status=pending,sent_back")
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (items) {
            return items.filter(function (u) { return u.asset_id === asset.id; })[0] || null;
          }).catch(function () { return null; })
      : Promise.resolve(null);
    return Promise.all([requests, upload]).then(function (got) {
      var view = got[0], uploadRecord = got[1];
      if (detailAsset !== asset || !sideTabs(card)) return;
      var pane = document.getElementById("vpManage");
      pane.innerHTML = "";
      if (uploadRecord) pane.appendChild(uploadRow(asset, uploadRecord));
      if (may.manage) pane.appendChild(accessRow(asset, may, view));
      if (may.review && (asset.uploaded_at || asset.still_current_until)) {
        pane.appendChild(stillCurrentRow(asset));
      }
      if (may.archive) pane.appendChild(archiveRow(asset));
      var tab = card.querySelector('.hub-sidetabs__tab[data-pane="manage"]');
      var waiting = !!(view && view.pending && may.manage)
        || !!(uploadRecord && uploadRecord.status === "pending");
      tab.classList.toggle("hub-sidetabs__tab--flag", waiting);
      tab.title = waiting ? "A request is waiting for a decision" : "";
      showSideTab(card);
    });
  });
}

export {
  buildFileRow, closeAssetDetail, closeFilePreview,
  fileDownloadUrl, fileHash, filePreviewUrl, openAssetDetail, wireDetailPage
};
