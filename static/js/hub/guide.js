/* How to use the Hub (#/guide), opened from the "?" button that stays in
 * the top right corner (Elio, Liwei, 2026-11-06; built 2026-11-08). The
 * welcome video goes in the frame at the top once Elio has made it.
 *
 * Its own page, apart from Get help (#/help), which is for reporting a
 * problem (Liwei's call, 2026-11-08). Redesigned the same day (Liwei: the
 * first version was plain text): a hero with the video's place, quick
 * actions that do the thing, and numbered steps with icons. */

import { hubPermissions } from "./permissions.js";
import { closeAdvancedSearch } from "./search.js";

function icon(id, cls) {
  return '<svg class="orion-ico ' + (cls || "") + '" aria-hidden="true"><use href="#' + id + '"/></svg>';
}

//: What the Hub holds, as the hero's chips.
var KINDS = [
  ["i-video", "Videos"], ["i-monitor", "Video Demo Kits"], ["i-box", "Live Demo Kits"],
  ["i-layers", "CAD datasets"], ["i-hex", "Virtual machines"]
];

//: Quick actions: [icon, title, text, href or action].
var QUICK = [
  ["i-search", "Search the Hub", "Find a demo by product, keyword or persona.", "search"],
  ["i-plus", "Ask for a new asset", "A video, VDK or LDK that is not here yet.", "#/request"],
  ["i-message-square", "Get help", "Something not working? Tell the Hub team.", "#/help"]
];

//: [icon, heading, [points]]. <b> only.
var STEPS = [
  ["i-search", "Find content", [
    "Type a product, keyword or persona in the <b>search box</b>.",
    "<b>Advanced Search</b> looks in more fields; <b>Match part of words</b> is on by default.",
    "Narrow down with <b>Asset Type</b>, <b>Product</b>, <b>Segment</b> and <b>Published</b>.",
    "Or browse from the menu: <b>by product</b> or <b>by type</b>."
  ]],
  ["i-play", "Open a demo", [
    "Click a title to open the demo's page. Videos play right there.",
    "<b>Preview</b> a file in the browser, or <b>download</b> it.",
    "<b>Share Internally</b> copies a link for a PTC colleague."
  ]],
  ["i-grid", "Tiles or table", [
    "Switch a list between <b>Tiles</b> and <b>Table</b>.",
    "In the table, click a column to sort; point at a picture to see it larger.",
    "<b>Export CSV</b> saves everything the filters match."
  ]],
  ["i-plus", "Ask for something new", [
    "Missing a video, VDK or LDK? Open <b>New Asset Inquiry</b> in the menu.",
    "Say which products, what it should show, and by when.",
    "It goes into the team's queue."
  ]],
  ["i-flag", "Tell us what is wrong", [
    "On a demo's page, <b>Share feedback</b> reaches the people who look after it.",
    "For the Hub itself, use <b>Get help</b> at the bottom of the menu.",
    "Your reports are listed there; withdraw one that is still open."
  ]],
  ["i-lock", "Customer data", [
    "Some demos use customer datasets.",
    "The <b>Customer Data Disclaimer</b> you accepted covers all of them.",
    "The Hub asks again every 12 months."
  ]]
];

function el(tag, cls, html) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}

function hero() {
  var box = el("section", "hub-guide__hero");
  var text = el("div", "hub-guide__hero-text");
  text.appendChild(el("div", "hub-guide__eyebrow", "Getting started"));
  text.appendChild(el("h1", "hub-guide__title", "How to use the Hub"));
  text.appendChild(el("p", "hub-guide__lead",
    "One place for PTC's technical demo content. Find it, open it, share it, "
    + "and ask for what is missing."));
  var kinds = el("div", "hub-guide__kinds");
  KINDS.forEach(function (k) {
    kinds.appendChild(el("span", "hub-guide__kind", icon(k[0], "orion-ico--sm") + k[1]));
  });
  text.appendChild(kinds);
  box.appendChild(text);

  // The welcome video's place (Elio is making it).
  var video = el("div", "hub-guide__video");
  video.setAttribute("aria-label", "Welcome video, coming soon");
  video.appendChild(el("span", "hub-guide__play", icon("i-play")));
  video.appendChild(el("span", "hub-guide__video-label", "Welcome video"));
  video.appendChild(el("span", "hub-guide__soon", "Coming soon"));
  box.appendChild(video);
  return box;
}

function quickActions() {
  var row = el("section", "hub-guide__quick");
  QUICK.forEach(function (q) {
    var a = el("a", "hub-guide__action");
    a.href = q[3] === "search" ? "#/" : q[3];
    a.innerHTML = '<span class="hub-guide__action-ico">' + icon(q[0]) + "</span>"
      + '<span class="hub-guide__action-text"><b>' + q[1] + "</b><span>" + q[2] + "</span></span>"
      + icon("i-chevron-right", "hub-guide__action-go");
    if (q[3] === "#/request") {
      // New Asset Inquiry is for PTC staff (2026-11-08).
      a.hidden = true;
      hubPermissions.then(function (granted) {
        a.hidden = granted.indexOf("is_partner") >= 0;
      });
    }
    if (q[3] === "search") {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        history.pushState(null, "", location.pathname + location.search);
        closeGuide();
        var input = document.getElementById("hubSearchInput");
        if (input) { input.scrollIntoView({ block: "center" }); input.focus(); }
      });
    }
    row.appendChild(a);
  });
  return row;
}

function steps() {
  var grid = el("section", "hub-guide__steps");
  STEPS.forEach(function (s, i) {
    var card = el("article", "hub-guide__step");
    var head = el("div", "hub-guide__step-head");
    head.appendChild(el("span", "hub-guide__step-ico", icon(s[0])));
    head.appendChild(el("span", "hub-guide__step-n", String(i + 1).padStart(2, "0")));
    card.appendChild(head);
    card.appendChild(el("h2", "hub-guide__h", s[1]));
    var list = el("ul", "hub-guide__points");
    s[2].forEach(function (p) { list.appendChild(el("li", null, p)); });
    card.appendChild(list);
    if (s[1] === "Open a demo") card.appendChild(ageBadges());
    grid.appendChild(card);
  });
  return grid;
}

/* The same badges the cards wear, with what each means. */
function ageBadges() {
  var box = el("div", "hub-guide__ages");
  box.appendChild(el("div", "hub-guide__ages-h", "How old is it? The badge on each card says:"));
  [["new", "New", "recent"], ["aging", "2023", "2 to 4 years old"],
   ["older", "Older UI · 2019", "older still"], ["current", "Still current", "checked, still right"]]
    .forEach(function (b) {
      var row = el("div", "hub-guide__age");
      row.appendChild(el("span", "hub-age hub-age--" + b[0], b[1]));
      row.appendChild(el("span", null, b[2]));
      box.appendChild(row);
    });
  return box;
}

function buildPage() {
  var page = document.getElementById("hubGuidePage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubGuidePage";
  page.appendChild(el("button", "vp-back",
    icon("i-chevron-left", "orion-ico--sm") + "Back to Technical Marketing Hub"));
  var wrap = el("div", "hub-guide");
  wrap.appendChild(hero());
  wrap.appendChild(quickActions());
  wrap.appendChild(steps());
  wrap.appendChild(el("p", "hub-guide__foot",
    icon("i-info", "orion-ico--sm") + "Come back here any time with the <b>?</b> in the top right corner."));
  page.appendChild(wrap);
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
