/* The New Asset Inquiry form's own controls (Elio's concept form): its
 * pills, what they show and hide, the Scope and "Kind of demo" outputs,
 * opening, closing and resetting the page, and the style-example modal.
 * What the form sends, its attachments and the duplicate check are in
 * request.js.
 *
 * Moved here from static/js/hub-ui.js, the page's last classic script
 * (WS-G, 2026-11-28). Until then these were globals that other modules
 * wrapped at run time (search.js around open/close, request.js around the
 * Scope box); the wrappers are folded in below, so there is one function
 * for each thing and nothing on window.
 *
 * The pills are <button type="button" aria-pressed> (they were <span>s a
 * keyboard could not reach); pressed is the same thing as
 * `stage-pill--active`, and setPill() keeps the two together.
 *
 * Part of the Hub page's script; static/js/hub/actions.js calls it. */

import { dialog } from "../shared/dialog.js";
import { closeOtherViews } from "./views.js";

/* ── pills ─────────────────────────────────────────────────────────────── */

function setPill(p, on) {
  p.classList.toggle("stage-pill--active", !!on);
  p.setAttribute("aria-pressed", on ? "true" : "false");
}

/* Every pill says whether it is pressed, as its class does; for the pills
 * in the markup, at start, and for any row rebuilt later (request.js). */
function markPills(root) {
  (root || document).querySelectorAll(".stage-pill").forEach(function (p) {
    p.setAttribute("aria-pressed", p.classList.contains("stage-pill--active") ? "true" : "false");
  });
}

function pillSelect(el) {
  Array.from(el.parentElement.children).forEach(function (p) { setPill(p, false); });
  setPill(el, true);
}

function pillToggle(el) {
  setPill(el, !el.classList.contains("stage-pill--active"));
}

/* ── what the pills show and hide ──────────────────────────────────────── */

function onAssetTypeChange(el) {
  // Nothing is picked until the requester picks (Elio, 2026-11-10: Asset
  // type is required), so `el` may be null after a reset.
  var type = el ? el.dataset.value : null;
  document.getElementById("videoDetailsSection").style.display = type === "video" ? "" : "none";
  // The brief is always required now; for Other it is the only place that
  // says what is asked for (Elio, 2026-11-09).
  var sub = document.getElementById("reqBriefSub");
  if (sub) sub.innerHTML = '<span class="req-required">required</span> · ' + (type === "other"
    ? "say what kind of asset you need"
    : "the more context the better");
}

function onCustomerChange(el) {
  document.getElementById("customerDataNote").style.display = el.dataset.value === "none" ? "none" : "";
}

function onStartingMaterialsChange(el) {
  document.getElementById("attachmentsSection").style.display = el.dataset.value === "have" ? "" : "none";
}

/* Elio's Scope box is green -- the colour of a result. While nothing is
 * picked it holds a prompt ("Select at least one product."), which then
 * read as a success (Liwei, 2026-10-01). Neutral until a product is
 * chosen. */
function computeProductScope() {
  var active = Array.from(document.querySelectorAll("#productScopeRow .stage-pill--active"))
    .map(function (p) { return p.dataset.value; });
  var valueEl = document.getElementById("productScopeValue");
  if (active.length === 0) valueEl.textContent = "Select at least one product.";
  else if (active.length === 1) valueEl.textContent = "Single product — " + active[0];
  else valueEl.textContent = "Multiple products (solution) — " + active.join(", ");
  var box = document.getElementById("productScopeResult");
  if (box) box.classList.toggle("hub-derived--pending", !active.length);
}

var VIDEO_LEVELS = ["Teaser", "Overview", "Explainer", "Walkthrough"];
var VIDEO_LEVEL_HINT = {
  Teaser: "Hook them fast — usually under 3 min",
  Overview: "What it is & why it matters — usually 3–5 min",
  Explainer: "A bit more depth for an active conversation — usually 5–10 min",
  Walkthrough: "Full step-by-step detail — usually 10+ min"
};
var CHANNEL_TO_LEVEL = {
  "Social (LinkedIn / YouTube)": "Teaser",
  "Event / trade show": "Teaser",
  "Web (PTC.com)": "Overview",
  "Share with a prospect": "Explainer",
  "Share with an existing customer": "Explainer",
  "Push to PTC Velocity": "Explainer",
  "Internal sales enablement": "Walkthrough",
  "Internal Hub only": "Walkthrough"
};

function computeKindOfDemo() {
  var activePills = Array.from(document.querySelectorAll("#distributionRow .stage-pill--active"));
  var listEl = document.getElementById("kindOfDemoList");
  // "Video types needed" is off the form until after the CK review
  // (Elio, Liwei, 2026-11-06); nothing to fill.
  if (!listEl) return;
  if (!activePills.length) {
    listEl.innerHTML = '<div class="field-hint">Pick where you\'ll use this video above to see what you\'ll need.</div>';
    return;
  }
  var groups = {};
  activePills.forEach(function (p) {
    var channel = p.textContent.trim();
    var level = CHANNEL_TO_LEVEL[channel] || "Overview";
    if (!groups[level]) groups[level] = [];
    groups[level].push(channel);
  });
  var levelsPresent = VIDEO_LEVELS.filter(function (l) { return groups[l]; });
  listEl.innerHTML = levelsPresent.map(function (level, i) {
    return '<div class="derived-output">' +
      '<div class="derived-output__label">Asset ' + (i + 1) + " of " + levelsPresent.length + " — " + level + "</div>" +
      '<div class="derived-output__value">For: ' + groups[level].join(", ") + "</div>" +
      '<div class="field-hint" style="margin-top:4px;">' + VIDEO_LEVEL_HINT[level] + "</div>" +
      '<div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">' +
        '<button type="button" class="btn-ghost" style="flex:none; padding:6px 12px;" data-action="style-example" data-level="' + level + '"><svg class="orion-ico--sm orion-ico"><use href="#i-play"/></svg>See an example of this style</button>' +
        '<button type="button" class="btn-ghost" style="flex:none; padding:6px 12px;" data-action="check-existing" data-level="' + level + '"><svg class="orion-ico--sm orion-ico"><use href="#i-search"/></svg>Check Demo Database for Similar Content</button>' +
      "</div>" +
      '<div id="existingCheck-' + level + '" style="display:none; margin-top:10px;"></div>' +
      "</div>";
  }).join("");
}

/* ── the page: open, close, reset ──────────────────────────────────────── */

function setActiveNav(id) {
  document.querySelectorAll(".orion-side .orion-navitem").forEach(function (n) {
    n.classList.remove("orion-navitem--active");
  });
  var item = document.getElementById(id);
  if (item) item.classList.add("orion-navitem--active");
}

var REQUEST_FORM_DEFAULTS = null;
function snapshotRequestFormDefaults() {
  if (REQUEST_FORM_DEFAULTS) return;
  REQUEST_FORM_DEFAULTS = {
    pillRows: Array.from(document.querySelectorAll("#requestFormCard .stage-row")).map(function (row) {
      return Array.from(row.children).map(function (p) { return p.classList.contains("stage-pill--active"); });
    })
  };
}

function resetRequestForm() {
  if (!REQUEST_FORM_DEFAULTS) return;
  var rows = document.querySelectorAll("#requestFormCard .stage-row");
  rows.forEach(function (row, ri) {
    Array.from(row.children).forEach(function (p, pi) {
      setPill(p, !!(REQUEST_FORM_DEFAULTS.pillRows[ri] || [])[pi]);
    });
  });
  ["reqBrief", "reqTargetDate", "reqCompellingEvent", "reqName", "reqEmail", "reqNotes"]
    .forEach(function (id) { document.getElementById(id).value = ""; });
  document.getElementById("attachmentList").innerHTML = "";

  onAssetTypeChange(document.querySelector("#assetTypeRow .stage-pill--active"));
  onCustomerChange(document.querySelector("#customerRow .stage-pill--active"));
  onStartingMaterialsChange(document.querySelector("#startingMaterialsRow .stage-pill--active"));
  computeProductScope();
  computeKindOfDemo();
}

function isRequestOpen() {
  var page = document.getElementById("requestViewPage");
  return !!(page && page.classList.contains("active"));
}

function openRequestView() {
  // Every other page, from views.js's one list: the form opened in the
  // lower half under the user guide (Liwei, 2026-11-08), then under My
  // Hub and a playlist (2026-11-17).
  closeOtherViews("request");
  // Opened from a details page, Advanced Search or Hub activity, the
  // address still named that page, and a refresh went back there.
  if (location.hash !== "#/request") {
    history.pushState(null, "", location.pathname + location.search + "#/request");
  }
  document.getElementById("videoPreviewPage").classList.remove("active");
  document.getElementById("mainTopbar").style.display = "none";
  document.getElementById("mainThread").style.display = "none";
  var page = document.getElementById("requestViewPage");
  page.classList.add("active");
  page.scrollTop = 0;
  setActiveNav("navRequestAsset");
  snapshotRequestFormDefaults();
  computeKindOfDemo();
  computeProductScope();
}

/* Also what moves the sidebar highlight back to Home, so nav.js calls it
 * even when the form is shut. */
function closeRequestView() {
  if (location.hash === "#/request") {
    history.pushState(null, "", location.pathname + location.search);
  }
  document.getElementById("requestViewPage").classList.remove("active");
  document.getElementById("mainTopbar").style.display = "";
  document.getElementById("mainThread").style.display = "";
  setActiveNav("navHome");
  document.getElementById("requestFormCard").style.display = "flex";
  document.getElementById("requestSuccessCard").style.display = "none";
}

/* ── the style-example modal ───────────────────────────────────────────── */

var STYLE_EXAMPLES = {
  Teaser: {
    ref: "Creo 13 Teaser",
    duration: "1:30",
    videoUrl: null,
    desc: "Fast pacing, high production polish, opens with a clear hook, and highlights business value at a glance — built to earn a click, not explain everything."
  },
  Overview: {
    ref: "The Digital Thread Powered by Creo",
    duration: "11:00",
    videoUrl: null,
    desc: "Explains what the solution is and why it matters, connecting capabilities to business value — without walking through the software step by step."
  },
  Explainer: {
    ref: null,
    duration: null,
    videoUrl: null,
    desc: 'A bit more depth than an Overview for an active conversation — gets into the "why" with more specificity, while stopping short of a full how-to.'
  },
  Walkthrough: {
    ref: "Bobcat Engineering",
    duration: "18:00",
    videoUrl: null,
    desc: "Full step-by-step detail in the actual software — built for validation and training, not a first impression."
  }
};

var styleDialog = null;
function styleExampleDialog() {
  if (!styleDialog) {
    var box = document.querySelector("#styleExampleBackdrop .modal");
    styleDialog = dialog(box, { labelledBy: "styleExampleHeading", onEscape: closeStyleExampleModal });
  }
  return styleDialog;
}

function openStyleExampleModal(level) {
  var ex = STYLE_EXAMPLES[level];
  if (!ex) return;
  document.getElementById("styleExampleTitle").textContent = level;
  document.getElementById("styleExampleRefTitle").textContent = ex.ref || "Reference example not yet designated";
  document.getElementById("styleExampleRefMeta").textContent = ex.ref
    ? (ex.duration + " · best-in-class example from the video taxonomy")
    : ("Ask the content team for a current model " + level + " to reference");
  document.getElementById("styleExampleDesc").textContent = ex.desc;

  var durationEl = document.getElementById("styleExampleDuration");
  durationEl.textContent = ex.duration || "";
  durationEl.style.display = ex.duration ? "" : "none";

  var videoTag = document.getElementById("styleExampleVideoTag");
  var playBtn = document.getElementById("styleExamplePlayBtn");
  var noteText = document.getElementById("styleExampleNoteText");
  if (ex.videoUrl) {
    videoTag.src = ex.videoUrl;
    videoTag.style.display = "block";
    playBtn.style.display = "none";
    noteText.textContent = "This is the team's reference example for this style.";
  } else {
    videoTag.pause();
    videoTag.removeAttribute("src");
    videoTag.load();
    videoTag.style.display = "none";
    playBtn.style.display = "";
    noteText.textContent = ex.ref
      ? "No playable file is linked yet for this reference — ask the content team for the actual video, or drop its URL into STYLE_EXAMPLES." + level + ".videoUrl."
      : "This is the team's reference example for this style — ask the content team for the actual file if you'd like to watch it directly.";
  }
  document.getElementById("styleExampleBackdrop").classList.add("open");
  styleExampleDialog().open();
}

function closeStyleExampleModal() {
  document.getElementById("styleExampleBackdrop").classList.remove("open");
  document.getElementById("styleExampleVideoTag").pause();
  styleExampleDialog().close();
}

export {
  closeRequestView, closeStyleExampleModal, computeKindOfDemo, computeProductScope,
  isRequestOpen, markPills, onAssetTypeChange, onCustomerChange, onStartingMaterialsChange,
  openRequestView, openStyleExampleModal, pillSelect, pillToggle, resetRequestForm
};
