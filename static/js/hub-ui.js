/* The page's own behaviour: the request form, the share and style-example
 * modals, and the sidebar's view switches.
 * Split out of index.html 2026-10-14; loaded before static/js/hub/main.js. */
function openShareModal(title, meta, uuid) {
  document.getElementById('shareAssetTitle').textContent = title;
  document.getElementById('shareAssetMeta').textContent = meta;
  document.getElementById('shareAssetUuid').textContent = 'demo_uuid: ' + uuid;
  document.getElementById('shareResult').style.display = 'none';
  document.getElementById('generateBtn').innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-send"/></svg>Generate &amp; Send DemoBoard';
  document.getElementById('shareBackdrop').classList.add('open');
}
function closeShareModal() {
  document.getElementById('shareBackdrop').classList.remove('open');
}
function generateShareLink() {
  document.getElementById('shareResult').style.display = 'block';
  document.getElementById('generateBtn').innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-send"/></svg>Regenerate link';
}
function copyShareLink() {
  var text = 'https://' + document.getElementById('shareLinkText').textContent;
  navigator.clipboard.writeText(text);
  var btn = document.getElementById('copyBtn');
  var original = btn.textContent;
  btn.textContent = 'Copied';
  setTimeout(function(){ btn.textContent = original; }, 1500);
}


/* The demo page's Back ("close-detail"). Elio's mock opener beside it, fed
 * from a hard-coded videoData object, was removed 2026-11-26: the page is
 * filled by openAssetDetail() in static/js/hub/detail.js. */
function closeVideoPreview() {
  document.getElementById('videoPreviewPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = '';
  document.getElementById('mainThread').style.display = '';
}

/* ============================================================
   REQUEST NEW ASSET
   ============================================================ */
function setActiveNav(id) {
  document.querySelectorAll('.orion-side .orion-navitem').forEach(function(n) { n.classList.remove('orion-navitem--active'); });
  document.getElementById(id).classList.add('orion-navitem--active');
}
var REQUEST_FORM_DEFAULTS = null;
function snapshotRequestFormDefaults() {
  if (REQUEST_FORM_DEFAULTS) return;
  REQUEST_FORM_DEFAULTS = {
    pillRows: Array.from(document.querySelectorAll('#requestFormCard .stage-row')).map(function(row) {
      return Array.from(row.children).map(function(p) { return p.classList.contains('stage-pill--active'); });
    })
  };
}
function resetRequestForm() {
  if (!REQUEST_FORM_DEFAULTS) return;
  var rows = document.querySelectorAll('#requestFormCard .stage-row');
  rows.forEach(function(row, ri) {
    Array.from(row.children).forEach(function(p, pi) {
      p.classList.toggle('stage-pill--active', !!REQUEST_FORM_DEFAULTS.pillRows[ri][pi]);
    });
  });
  document.getElementById('reqBrief').value = '';
  document.getElementById('reqTargetDate').value = '';
  document.getElementById('reqCompellingEvent').value = '';
  document.getElementById('reqName').value = '';
  document.getElementById('reqEmail').value = '';
  document.getElementById('reqNotes').value = '';
  document.getElementById('attachmentList').innerHTML = '';

  onAssetTypeChange(document.querySelector('#assetTypeRow .stage-pill--active'));
  onCustomerChange(document.querySelector('#customerRow .stage-pill--active'));
  onStartingMaterialsChange(document.querySelector('#startingMaterialsRow .stage-pill--active'));
  computeProductScope();
  computeKindOfDemo();
}
function openRequestView() {
  document.getElementById('videoPreviewPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = 'none';
  document.getElementById('mainThread').style.display = 'none';
  document.getElementById('requestViewPage').classList.add('active');
  document.getElementById('requestViewPage').scrollTop = 0;
  setActiveNav('navRequestAsset');
  snapshotRequestFormDefaults();
  computeKindOfDemo();
  computeProductScope();
}
function closeRequestView() {
  document.getElementById('requestViewPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = '';
  document.getElementById('mainThread').style.display = '';
  setActiveNav('navHome');
  document.getElementById('requestFormCard').style.display = 'flex';
  document.getElementById('requestSuccessCard').style.display = 'none';
}
function pillSelect(el) {
  Array.from(el.parentElement.children).forEach(function(p) { p.classList.remove('stage-pill--active'); });
  el.classList.add('stage-pill--active');
}
function pillToggle(el) {
  el.classList.toggle('stage-pill--active');
}
function onAssetTypeChange(el) {
  // Nothing is picked until the requester picks (Elio, 2026-11-10: Asset
  // type is required), so `el` may be null after a reset.
  var type = el ? el.dataset.value : null;
  document.getElementById('videoDetailsSection').style.display = type === 'video' ? '' : 'none';
  // The brief is always required now; for Other it is the only place that
  // says what is asked for (Elio, 2026-11-09).
  var sub = document.getElementById('reqBriefSub');
  if (sub) sub.innerHTML = '<span class="req-required">required</span> · ' + (type === 'other'
    ? 'say what kind of asset you need'
    : 'the more context the better');
}
function onCustomerChange(el) {
  document.getElementById('customerDataNote').style.display = el.dataset.value === 'none' ? 'none' : '';
}
var VIDEO_LEVELS = ['Teaser', 'Overview', 'Explainer', 'Walkthrough'];
var VIDEO_LEVEL_HINT = {
  Teaser: 'Hook them fast — usually under 3 min',
  Overview: 'What it is & why it matters — usually 3–5 min',
  Explainer: 'A bit more depth for an active conversation — usually 5–10 min',
  Walkthrough: 'Full step-by-step detail — usually 10+ min'
};
var CHANNEL_TO_LEVEL = {
  'Social (LinkedIn / YouTube)': 'Teaser',
  'Event / trade show': 'Teaser',
  'Web (PTC.com)': 'Overview',
  'Share with a prospect': 'Explainer',
  'Share with an existing customer': 'Explainer',
  'Push to PTC Velocity': 'Explainer',
  'Internal sales enablement': 'Walkthrough',
  'Internal Hub only': 'Walkthrough'
};
var STYLE_EXAMPLES = {
  Teaser: {
    ref: 'Creo 13 Teaser',
    duration: '1:30',
    videoUrl: null,
    desc: 'Fast pacing, high production polish, opens with a clear hook, and highlights business value at a glance — built to earn a click, not explain everything.'
  },
  Overview: {
    ref: 'The Digital Thread Powered by Creo',
    duration: '11:00',
    videoUrl: null,
    desc: 'Explains what the solution is and why it matters, connecting capabilities to business value — without walking through the software step by step.'
  },
  Explainer: {
    ref: null,
    duration: null,
    videoUrl: null,
    desc: 'A bit more depth than an Overview for an active conversation — gets into the "why" with more specificity, while stopping short of a full how-to.'
  },
  Walkthrough: {
    ref: 'Bobcat Engineering',
    duration: '18:00',
    videoUrl: null,
    desc: 'Full step-by-step detail in the actual software — built for validation and training, not a first impression.'
  }
};
function openStyleExampleModal(level) {
  var ex = STYLE_EXAMPLES[level];
  document.getElementById('styleExampleTitle').textContent = level;
  document.getElementById('styleExampleRefTitle').textContent = ex.ref || 'Reference example not yet designated';
  document.getElementById('styleExampleRefMeta').textContent = ex.ref
    ? (ex.duration + ' · best-in-class example from the video taxonomy')
    : ('Ask the content team for a current model ' + level + ' to reference');
  document.getElementById('styleExampleDesc').textContent = ex.desc;

  var durationEl = document.getElementById('styleExampleDuration');
  durationEl.textContent = ex.duration || '';
  durationEl.style.display = ex.duration ? '' : 'none';

  var videoTag = document.getElementById('styleExampleVideoTag');
  var playBtn = document.getElementById('styleExamplePlayBtn');
  var noteText = document.getElementById('styleExampleNoteText');
  if (ex.videoUrl) {
    videoTag.src = ex.videoUrl;
    videoTag.style.display = 'block';
    playBtn.style.display = 'none';
    noteText.textContent = "This is the team's reference example for this style.";
  } else {
    videoTag.pause();
    videoTag.removeAttribute('src');
    videoTag.load();
    videoTag.style.display = 'none';
    playBtn.style.display = '';
    noteText.textContent = ex.ref
      ? 'No playable file is linked yet for this reference — ask the content team for the actual video, or drop its URL into STYLE_EXAMPLES.' + level + '.videoUrl.'
      : "This is the team's reference example for this style — ask the content team for the actual file if you'd like to watch it directly.";
  }
  document.getElementById('styleExampleBackdrop').classList.add('open');
}
function closeStyleExampleModal() {
  document.getElementById('styleExampleBackdrop').classList.remove('open');
  var videoTag = document.getElementById('styleExampleVideoTag');
  videoTag.pause();
}
function computeKindOfDemo() {
  var activePills = Array.from(document.querySelectorAll('#distributionRow .stage-pill--active'));
  var listEl = document.getElementById('kindOfDemoList');
  // "Video types needed" is off the form until after the CK review
  // (Elio, Liwei, 2026-11-06); nothing to fill.
  if (!listEl) return;
  if (!activePills.length) {
    listEl.innerHTML = '<div class="field-hint">Pick where you\'ll use this video above to see what you\'ll need.</div>';
    return;
  }
  var groups = {};
  activePills.forEach(function(p) {
    var channel = p.textContent.trim();
    var level = CHANNEL_TO_LEVEL[channel] || 'Overview';
    if (!groups[level]) groups[level] = [];
    groups[level].push(channel);
  });
  var levelsPresent = VIDEO_LEVELS.filter(function(l) { return groups[l]; });
  listEl.innerHTML = levelsPresent.map(function(level, i) {
    return '<div class="derived-output">' +
      '<div class="derived-output__label">Asset ' + (i + 1) + ' of ' + levelsPresent.length + ' — ' + level + '</div>' +
      '<div class="derived-output__value">For: ' + groups[level].join(', ') + '</div>' +
      '<div class="field-hint" style="margin-top:4px;">' + VIDEO_LEVEL_HINT[level] + '</div>' +
      '<div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">' +
        '<button class="btn-ghost" style="flex:none; padding:6px 12px;" data-action="style-example" data-level="' + level + '"><svg class="orion-ico--sm orion-ico"><use href="#i-play"/></svg>See an example of this style</button>' +
        '<button class="btn-ghost" style="flex:none; padding:6px 12px;" data-action="check-existing" data-level="' + level + '"><svg class="orion-ico--sm orion-ico"><use href="#i-search"/></svg>Check Demo Database for Similar Content</button>' +
      '</div>' +
      '<div id="existingCheck-' + level + '" style="display:none; margin-top:10px;"></div>' +
      '</div>';
  }).join('');
}
function computeProductScope() {
  var active = Array.from(document.querySelectorAll('#productScopeRow .stage-pill--active')).map(function(p) { return p.dataset.value; });
  var valueEl = document.getElementById('productScopeValue');
  if (active.length === 0) valueEl.textContent = 'Select at least one product.';
  else if (active.length === 1) valueEl.textContent = 'Single product — ' + active[0];
  else valueEl.textContent = 'Multiple products (solution) — ' + active.join(', ');
}
function onStartingMaterialsChange(el) {
  document.getElementById('attachmentsSection').style.display = el.dataset.value === 'have' ? '' : 'none';
}
/* Replaced at runtime by static/js/hub/request.js, which keeps the File objects and uploads
   them. This version used to render a chip and then clear the input,
   discarding every file; it now refuses rather than pretending, for the case
   where that script fails to load. */
function handleAttachmentFiles(input) {
  var list = document.getElementById('attachmentList');
  input.value = '';
  list.innerHTML = '<span class="attach-warn">The Hub could not be reached, so '
    + 'files cannot be attached. Reload the page and try again.</span>';
}
/* Replaced at runtime by static/js/hub/request.js, which actually posts the answers. This
   remains as the fallback for the case where that script fails to load: it is
   better to say the Hub is unavailable than to show a success screen for a
   request that went nowhere, which is what this function used to do. */
function submitAssetRequest(e) {
  e.preventDefault();
  var box = document.getElementById('reqError');
  if (box) {
    box.textContent = 'The Hub could not be reached, so this was not submitted. '
                    + 'Please reload the page and try again.';
    box.style.display = '';
  }
}

/* ── One listener for every control on the page (2026-10-14) ──────────────
 * The markup names what a control does (data-action="..."); this table says
 * how. Functions are looked up on window at click time, so static/js/hub/
 * can still wrap one (openRequestView, submitAssetRequest...) and be called.
 * Replaces the inline onclick attributes the concept mock-up carried. */
var HUB_ACTIONS = {
  "pill-select": function (el) { pillSelect(el); },
  "pill-toggle-kind": function (el) { pillToggle(el); computeKindOfDemo(); },
  "pill-toggle": function (el) { pillToggle(el); },
  "pill-toggle-scope": function (el) { pillToggle(el); computeProductScope(); },
  "pill-customer": function (el) { pillSelect(el); onCustomerChange(el); },
  "pill-asset-type": function (el) { pillSelect(el); onAssetTypeChange(el); },
  "pill-starting-materials": function (el) { pillSelect(el); onStartingMaterialsChange(el); },
  "open-request": function () { window.openRequestView(); },
  "close-request": function () { window.closeRequestView(); },
  "submit-request": function (el, e) { window.submitAssetRequest(e); },
  "reset-request": function () { window.resetRequestForm(); },
  "reset-filters": function () { window.hubResetFilters(); },
  "close-detail": function () { window.closeVideoPreview(); },
  "share": function (el) {
    window.openShareModal(el.dataset.shareTitle, el.dataset.shareMeta, el.dataset.shareUuid);
  },
  "close-share": function () { window.closeShareModal(); },
  "generate-share-link": function () { window.generateShareLink(); },
  "copy-share-link": function () { window.copyShareLink(); },
  "style-example": function (el) { window.openStyleExampleModal(el.dataset.level); },
  "close-style-example": function () { window.closeStyleExampleModal(); },
  // Defined by static/js/hub/request.js, which asks the catalogue. The mock
  // that answered from three hard-coded matches is gone (2026-11-26), and
  // with it the "asset-decision" buttons only it drew.
  "check-existing": function (el) {
    if (window.checkExistingAsset) window.checkExistingAsset(el, el.dataset.level);
  }
};

document.addEventListener("click", function (e) {
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
});

document.addEventListener("change", function (e) {
  if (e.target.dataset && e.target.dataset.change === "attachments") {
    window.handleAttachmentFiles(e.target);
  }
});

/* Phones (D10, 2026-10-30): the sidebar is off screen until asked for, and
 * leaves again when something in it is chosen, or on the scrim or Esc. */
(function () {
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
  // This file has no <html> tag of its own to say so.
  document.documentElement.lang = "en";
})();
