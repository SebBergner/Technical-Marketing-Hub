/* One listener for every control the markup names (data-action="..."),
 * and the phone sidebar.
 *
 * index.html carries no handlers of its own (CSP: script-src 'self', so no
 * onclick=); a control says what it does in data-action, and the table
 * below says how. Until WS-G (2026-11-28) this was static/js/hub-ui.js, a
 * classic script that looked each function up on window at click time so
 * the modules could wrap them; now every action is an import.
 *
 * Part of the Hub page's script; main.js calls wirePageActions() first. */

import {
  closeRequestView, closeStyleExampleModal, computeKindOfDemo, computeProductScope,
  markPills, onAssetTypeChange, onCustomerChange, onStartingMaterialsChange,
  openRequestView, openStyleExampleModal, pillSelect, pillToggle, resetRequestForm
} from "./inquiry.js";
import { checkExistingAsset, submitRequest, takeAttachments } from "./request.js";
import { closeShareModal, copyShareLink } from "./share.js";
import { clearAll } from "./filters.js";

/* The demo page's Back. detail.js's own listener on the button does the
 * routing (and stops this one when it returns to another page); this puts
 * the catalogue back. */
function closeVideoPreview() {
  document.getElementById("videoPreviewPage").classList.remove("active");
  document.getElementById("mainTopbar").style.display = "";
  document.getElementById("mainThread").style.display = "";
}

var HUB_ACTIONS = {
  "pill-select": function (el) { pillSelect(el); },
  "pill-toggle-kind": function (el) { pillToggle(el); computeKindOfDemo(); },
  "pill-toggle": function (el) { pillToggle(el); },
  "pill-toggle-scope": function (el) { pillToggle(el); computeProductScope(); },
  "pill-customer": function (el) { pillSelect(el); onCustomerChange(el); },
  "pill-asset-type": function (el) { pillSelect(el); onAssetTypeChange(el); },
  "pill-starting-materials": function (el) { pillSelect(el); onStartingMaterialsChange(el); },
  "open-request": function () { openRequestView(); },
  "close-request": function () { closeRequestView(); },
  "submit-request": function (el, e) { submitRequest(e); },
  "reset-request": function () { resetRequestForm(); },
  "reset-filters": function () { clearAll(); },
  "close-detail": function () { closeVideoPreview(); },
  "close-share": function () { closeShareModal(); },
  "copy-share-link": function () { copyShareLink(); },
  "style-example": function (el) { openStyleExampleModal(el.dataset.level); },
  "close-style-example": function () { closeStyleExampleModal(); },
  "check-existing": function (el) { checkExistingAsset(el, el.dataset.level); }
};

function onClick(e) {
  // A backdrop closes its modal only when the click lands on the backdrop
  // itself, not on the dialog inside it.
  var backdrop = e.target.closest("[data-backdrop]");
  if (backdrop && e.target === backdrop) {
    HUB_ACTIONS[backdrop.dataset.backdrop](backdrop, e);
    return;
  }
  var el = e.target.closest("[data-action]");
  if (!el) return;
  var action = HUB_ACTIONS[el.dataset.action];
  if (action) action(el, e);
}

function onChange(e) {
  if (e.target.dataset && e.target.dataset.change === "attachments") {
    takeAttachments(e.target);
  }
}

/* Phones (D10, 2026-10-30): the sidebar is off screen until asked for, and
 * leaves again when something in it is chosen, or on the scrim or Esc. */
function wirePhoneSidebar() {
  var open = document.getElementById("hubNavOpen");
  var scrim = document.getElementById("hubNavScrim");
  if (!open || !scrim) return;
  function show(on) {
    document.documentElement.classList.toggle("hub-nav-shown", on);
    open.setAttribute("aria-expanded", String(on));
  }
  open.addEventListener("click", function () {
    show(!document.documentElement.classList.contains("hub-nav-shown"));
  });
  scrim.addEventListener("click", function () { show(false); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") show(false);
  });
  var side = document.querySelector(".orion-side");
  side.addEventListener("click", function (e) {
    if (e.target.closest(".orion-navitem")) show(false);
  });

  /* Keyboard and screen readers (D10): the nav items are divs, filled in and
   * rebuilt by static/js/hub/nav.js, so they are marked as they appear. */
  function markItems() {
    side.querySelectorAll(".orion-navitem:not([tabindex])").forEach(function (item) {
      item.tabIndex = 0;
      item.setAttribute("role", "button");
    });
  }
  markItems();
  new MutationObserver(markItems).observe(side, { childList: true, subtree: true });
  side.addEventListener("keydown", function (e) {
    var item = e.target.closest && e.target.closest(".orion-navitem");
    if (item && e.target === item && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      item.click();
    }
  });
}

var wired = false;
function wirePageActions() {
  if (wired) return;
  wired = true;
  document.addEventListener("click", onClick);
  document.addEventListener("change", onChange);
  wirePhoneSidebar();
  markPills(document.getElementById("requestFormCard"));
  // index.html has no <html> tag of its own to say so.
  document.documentElement.lang = "en";
}

export { wirePageActions };
