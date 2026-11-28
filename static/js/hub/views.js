/* Which full page is on screen: the one list of them all (2026-11-17).
 *
 * The Hub's pages are not routes of their own: each is a block that its
 * openX() shows and its closeX() hides, putting the catalogue
 * (#mainTopbar, #mainThread) back as it goes. Opening one page therefore
 * means closing every other, and the list of "every other" used to be
 * written out by hand in five places -- the router, the request form's
 * wrapper, exitOverlays(), openAssetDetail() and the pages themselves.
 * Each new page had to be added to all five, and My Hub and the playlist
 * page (2026-11-12) were missed in two: New Asset Inquiry and a demo card
 * opened from them showed in the lower half of the screen with them still
 * in the upper half (Liwei, 2026-11-17).
 *
 * A new full page is one line here, and nowhere else.
 *
 * Order: every closeX() puts the catalogue back, so call this BEFORE the
 * page being opened hides the catalogue -- after, and the catalogue
 * reappears under it.
 *
 * Imports only the closers, so the modules that call this (detail.js,
 * search.js, nav.js) add no new cycle of their own. */

import { closeAssetDetail, closeFilePreview } from "./detail.js";
import { closeAdvancedSearch } from "./search.js";
import { closeActivity } from "./activity.js";
import { closeReview } from "./review.js";
import { closeHelp } from "./report.js";
import { closeGuide } from "./guide.js";
import { closeUpload } from "./upload.js";
import { closeMyHub } from "./me.js";
import { closePlaylist } from "./playlists.js";
import { closeRequestView, isRequestOpen } from "./inquiry.js";

/* Elio's request form (inquiry.js). Only when it is open: its
 * closeRequestView() also moves the sidebar highlight to Home. */
function closeRequest() {
  if (isRequestOpen()) closeRequestView();
}

/* Every full page but the catalogue, by the name callers use to keep one
 * open. Each closer does nothing when its page is already shut. */
var VIEWS = [
  ["request",  closeRequest],
  ["preview",  function () { closeFilePreview(false); }],   // modal, over a demo
  ["asset",    function () { closeAssetDetail(); }],
  ["search",   function () { closeAdvancedSearch(); }],
  ["activity", function () { closeActivity(); }],
  ["review",   function () { closeReview(); }],
  ["help",     function () { closeHelp(); }],
  ["guide",    function () { closeGuide(); }],
  ["upload",   function () { closeUpload(); }],
  ["me",       function () { closeMyHub(); }],
  ["playlist", function () { closePlaylist(); }]
];

/* Close every full page except `keep`: one name, a list of names, or
 * nothing (back to the catalogue). */
function closeOtherViews(keep) {
  var spare = [].concat(keep || []);
  VIEWS.forEach(function (v) {
    if (spare.indexOf(v[0]) < 0) v[1]();
  });
}

export { closeOtherViews };
