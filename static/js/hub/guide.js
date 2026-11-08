/* How to use the Hub (#/guide), opened from the "?" button that stays in
 * the top right corner (Elio, Liwei, 2026-11-06; built 2026-11-08). A
 * welcome video goes at the top once Elio has made it; until then the page
 * says what the Hub holds and where things are.
 *
 * Its own page, apart from Get help (#/help), which is for reporting a
 * problem (Liwei's call, 2026-11-08). */

import { hubPermissions } from "./permissions.js";
import { closeAdvancedSearch } from "./search.js";

//: [heading, [paragraphs]]. Plain text; <b> only.
var SECTIONS = [
  ["Find content", [
    "Type a product, keyword or persona in the search box. <b>Advanced Search</b> searches more fields at once; "
    + "<b>Match part of words</b> beside it is on by default.",
    "Narrow the list with the filters under the search box: <b>Asset Type</b>, <b>Product</b>, <b>Segment</b>, "
    + "<b>Published</b> and <b>More filters</b>. <b>Clear all</b> starts again.",
    "Or start from the left: <b>Browse by product</b> and <b>Browse by type</b> open a list of their own."
  ]],
  ["Open a demo", [
    "Click a demo's title to open its page: what it shows, its files and its details. A video plays on the page.",
    "<b>Preview</b> a file in your browser, or <b>download</b> it where you have permission. "
    + "<b>Share Internally</b> copies a link for a PTC colleague.",
    "The badge on a card says how old the recording is: <b>New</b> for recent content, the year for "
    + "content 2 to 4 years old, <b>Older UI</b> after that. <b>Still current</b> means someone checked "
    + "that an older demo still matches the product."
  ]],
  ["Lists and tables", [
    "Switch a list between <b>Tiles</b> and <b>Table</b> above it. In the table, click a column to sort by it, "
    + "and point at a picture to see it larger.",
    "<b>Export CSV</b> saves every demo the current filters match, for a deck or a spreadsheet."
  ]],
  ["Ask for something new", [
    "Missing a video, a VDK or an LDK? <b>New Asset Inquiry</b>, in the menu on the left, sends it to the "
    + "team's queue. Say which products, what it should show, and by when."
  ]],
  ["Tell us what is wrong", [
    "On a demo's page, <b>Share feedback</b> reaches the people who look after that demo.",
    "For the Hub itself, use <b>Get help</b> at the bottom of the menu. Your reports are listed there "
    + "with their status, and you can withdraw one that is still open."
  ]],
  ["Customer data", [
    "Demos may use customer datasets. The <b>Customer Data Disclaimer</b> you accepted applies to all of "
    + "them; the Hub asks again every 12 months."
  ]]
];

function el(tag, cls, html) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}

function buildPage() {
  var page = document.getElementById("hubGuidePage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubGuidePage";
  page.appendChild(el("button", "vp-back",
    '<svg class="orion-ico orion-ico--sm"><use href="#i-chevron-left"/></svg>'
    + "Back to Technical Marketing Hub"));
  var head = el("div", "vp-head");
  var inner = el("div");
  inner.appendChild(el("div", "vp-title", "How to use the Hub"));
  inner.appendChild(el("div", "orion-subtle",
    "One place for PTC's technical demo content: videos, Video Demo Kits (VDK), Live Demo Kits "
    + "(LDK), CAD datasets and virtual machines. A short welcome video will be added here."));
  head.appendChild(inner);
  page.appendChild(head);
  var grid = el("div", "hub-guide");
  SECTIONS.forEach(function (s) {
    var card = el("section", "hub-guide__card");
    card.appendChild(el("h2", "hub-guide__h", s[0]));
    s[1].forEach(function (p) { card.appendChild(el("p", null, p)); });
    grid.appendChild(card);
  });
  page.appendChild(grid);
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeGuide();
  });
  return page;
}

function openGuide() {
  var page = buildPage();
  closeAdvancedSearch();
  var request = document.getElementById("requestViewPage");
  if (request) request.classList.remove("active");
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  page.classList.add("active");
  page.scrollTop = 0;
  markButton(true);
}

function closeGuide() {
  var page = document.getElementById("hubGuidePage");
  if (!page || !page.classList.contains("active")) return;
  page.classList.remove("active");
  markButton(false);
  var detail = document.getElementById("videoPreviewPage");
  if (detail && detail.classList.contains("active")) return;
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "";
  if (thread) thread.style.display = "";
}

/* The "?" in the top right corner, on every page of the Hub. */
function addGuideButton() {
  hubPermissions.then(function (granted) {
    if (granted.indexOf("view_hub") < 0 || document.getElementById("hubGuideBtn")) return;
    var b = el("a", "hub-guide-btn", "?");
    b.id = "hubGuideBtn";
    b.href = "#/guide";
    b.title = "How to use the Hub";
    b.setAttribute("aria-label", "How to use the Hub");
    document.body.appendChild(b);
    if (location.hash === "#/guide") markButton(true);
  });
}

function markButton(on) {
  var b = document.getElementById("hubGuideBtn");
  if (b) b.classList.toggle("is-on", on);
}

export { addGuideButton, closeGuide, openGuide };
