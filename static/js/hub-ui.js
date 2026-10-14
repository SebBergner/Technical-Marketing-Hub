/* The page's own behaviour: the request form, the share and style-example
 * modals, the card template hub-api.js fills, and the sidebar's view switches.
 * Split out of index.html 2026-10-14; loaded before static/hub-api.js. */
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


var videoData = {
  'dup-parts': {
    title: 'Eliminate Duplicate Parts with Windchill AI Parts Classification',
    logo: 'windchill', logoViewBox: '0 0 1299.67 299.6', metaText: 'Consideration · EN',
    stats: '214 views · Uploaded Jul 21', uuid: '7a19-3c02', duration: '4:12',
    desc: 'Walks through detecting and eliminating duplicate parts with Windchill AI Parts Classification — searching the part library, reviewing AI-ranked similarity candidates, and consolidating matches into a single canonical part.',
    drivers: ['Efficiency', 'Quality & Regulatory'],
    capabilities: [
      { phase: 'DEFINE', title: 'Parts Classification & Reuse', chips: ['AI Similarity Search', 'Attribute-Based Classification', 'Reuse Recommendations'], narration: 'Narration runs the AI classifier against the part library and reviews similarity-ranked candidates.' },
      { phase: 'DESIGN', title: 'Duplicate Resolution & Consolidation', chips: ['Part Merge', 'Where-Used Impact Check'], narration: 'Demo merges the duplicate into the canonical part and checks where-used impact across active assemblies.' }
    ]
  },
  'creo-composites': {
    title: 'Creo Chapters S1E4 — Composites Deep Dive (Replay)',
    logo: 'creo', logoViewBox: '0 0 1334.88 449.9', metaText: 'Awareness · EN',
    stats: '402 views · Uploaded Jul 14', uuid: '4f61-88ab', duration: '6:47',
    desc: 'Fourth episode of the Creo Chapters series — a deep dive into composite layup design, core-zone modeling, and a generative pass to trim laminate mass.',
    drivers: ['Innovation', 'Efficiency'],
    capabilities: [
      { phase: 'DESIGN', title: 'Composite Layup Design', chips: ['Ply Definition', 'Core Zone Modeling', 'Flat Pattern Output'], narration: 'Episode builds up composite plies and core zones directly on the bracket model.' },
      { phase: 'IMPROVE', title: 'Structural Optimization', chips: ['Generative Design', 'Topology Study'], narration: 'Replay covers a generative design pass to trim laminate mass while holding the load case.' }
    ]
  },
  'walkthrough-audio': {
    title: 'Windchill AI Parts Rationalization — Walkthrough with Audio',
    logo: 'windchill', logoViewBox: '0 0 1299.67 299.6', metaText: 'Consideration · EN',
    stats: '1,204 views · 38 shares', uuid: '8f3c-19ea', duration: '6:58',
    desc: 'Narrated walkthrough of the Windchill AI Parts Rationalization flow — searching, classifying, and consolidating duplicate parts, then routing the change for review.',
    drivers: ['Efficiency', 'Quality & Regulatory'],
    capabilities: [
      { phase: 'DEFINE', title: 'Parts Classification & Reuse', chips: ['AI Similarity Search', 'Attribute-Based Classification', 'Reuse Recommendations'], narration: 'Narration runs the AI classifier against the part library and reviews similarity-ranked candidates.' },
      { phase: 'VALIDATE', title: 'Rationalization Review & Sign-off', chips: ['Review Queue', 'Approval Workflow'], narration: 'Walkthrough finishes by routing the consolidated part through review and capturing sign-off.' }
    ]
  },
  'exec-overview': {
    title: 'The Intelligent Product Lifecycle — Executive Overview',
    logo: 'windchill', logoViewBox: '0 0 1299.67 299.6', metaText: 'Awareness · EN',
    stats: '967 views · 51 shares', uuid: 'c015-6b7d', duration: '3:35',
    desc: 'A single narrative arc across Windchill, CodeBeamer, and Creo — built for first-call, cross-portfolio pitches on the intelligent product lifecycle.',
    drivers: ['Efficiency', 'Innovation', 'Quality & Regulatory'],
    capabilities: [
      { phase: 'PLAN', title: 'Enterprise Change Management', chips: ['Closed-Loop Change Management', 'Change Impact Analysis', 'Release Management'], narration: 'Frames show the Windchill Change Request workflow — reviewing and approving the ECR, then creating a change notice with an implementation plan.' },
      { phase: 'DEFINE', title: 'Requirements Management & Review', chips: ['Requirements Definition & Governance', 'Compliance-Driven Requirements'], narration: 'CodeBeamer frames show updating requirements and validating them with the AI requirements assistant against customer and industry rules.' },
      { phase: 'DESIGN', title: 'Detailed Design in Creo', chips: ['Generative Design', 'MBD', 'GD&T Advisor'], narration: 'Creo frames cover generative design, model-based definition, and the GD&T advisor on the updated part.' },
      { phase: 'VALIDATE', title: 'Verification & Validation', chips: ['Test Management', 'Product Verification'], narration: 'Closes with the CodeBeamer test coverage report and a traceability view linking requirements to tests and changes.' }
    ]
  },
  'cad-illustrations': {
    title: 'Rapid CAD-Based Illustrations — Demo Script',
    logo: 'creo', logoViewBox: '0 0 1334.88 449.9', metaText: 'Decision · EN',
    stats: '640 views · 22 shares', uuid: 'a207-f453', duration: '2:48',
    desc: 'Demo script for generating exploded, callout-annotated illustrations directly from the Creo model for sales and support collateral.',
    drivers: ['Efficiency'],
    capabilities: [
      { phase: 'DESIGN', title: '3D PDF & Illustration Export', chips: ['3D PDF Export', 'Exploded Views', 'Auto-Callouts'], narration: 'Script covers generating an exploded, callout-annotated illustration straight from the Creo model.' }
    ]
  },
  'zh-overview': {
    title: 'Windchill AI Parts Rationalization Overview — Chinese',
    logo: 'windchill', logoViewBox: '0 0 1299.67 299.6', metaText: 'Awareness · ZH',
    stats: '588 views · 14 shares', uuid: '', duration: '3:50',
    desc: 'Localized (Chinese) overview cut of the Windchill AI Parts Rationalization story, covering search, classification, and consolidation.',
    drivers: ['Efficiency', 'Quality & Regulatory'],
    capabilities: [
      { phase: 'DEFINE', title: 'Parts Classification & Reuse', chips: ['AI Similarity Search', 'Attribute-Based Classification'], narration: 'Overview reuses the same classification and consolidation flow as the English walkthrough, translated for the ZH region.' }
    ]
  }
};

function openVideoPreview(id) {
  var v = videoData[id];
  if (!v) return;
  document.getElementById('vpTitle').textContent = v.title;
  document.getElementById('vpDuration').textContent = v.duration;
  document.getElementById('vpMeta').innerHTML = '<span class="meta-logo-chip"><svg class="meta-logo" viewBox="' + v.logoViewBox + '"><use href="#logo-' + v.logo + '"/></svg></span> ' + v.metaText;
  document.getElementById('vpStats').innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-eye"/></svg> ' + v.stats +
    (v.uuid ? ' <span>·</span> Consensus UUID <span class="orion-mono">' + v.uuid + '</span>' : '');
  document.getElementById('vpDesc').textContent = v.desc;
  var vpShareBtn = document.getElementById('vpShareBtn');
  vpShareBtn.style.display = v.uuid ? '' : 'none';
  vpShareBtn.onclick = function() { openShareModal(v.title, v.metaText, v.uuid); };

  document.getElementById('vpValueDrivers').innerHTML = v.drivers.map(function(d) {
    return '<span class="value-driver-chip">' + d + '</span>';
  }).join('');

  document.getElementById('vpCapabilities').innerHTML = v.capabilities.map(function(c) {
    var chips = c.chips.map(function(ch) { return '<span class="capability-chip">' + ch + '</span>'; }).join('');
    return '<div class="capability-card"><div class="capability-card__head"><span class="phase-tag">' + c.phase + '</span>' +
      '<span class="capability-card__title">' + c.title + '</span></div>' +
      '<div class="capability-chips">' + chips + '</div>' +
      '<div class="capability-narration">' + c.narration + '</div></div>';
  }).join('');

  document.getElementById('requestViewPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = 'none';
  document.getElementById('mainThread').style.display = 'none';
  document.getElementById('videoPreviewPage').classList.add('active');
  document.getElementById('videoPreviewPage').scrollTop = 0;
}
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
  document.getElementById('videoDetailsSection').style.display = el.dataset.value === 'video' ? '' : 'none';
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
var EXISTING_ASSET_MATCHES = {
  'Windchill|Teaser': {
    title: 'Windchill Launch',
    subtitle: 'Windchill 13 Launch Sizzle Video',
    meta: 'Single video · Windchill · Teaser',
    stats: '38 uses · 38 DemoBoards',
    updated: 'Updated Nov 4, 2025',
    owner: 'Elio Nicolosi'
  },
  'Windchill|Overview': {
    title: 'Windchill AI Parts Rationalization',
    subtitle: 'PLM | Windchill | Overview | 4:48',
    meta: 'Single video · Windchill · Overview',
    stats: '27 uses · 22 DemoBoards · 5 public link views',
    updated: 'Updated Feb 23, 2026',
    owner: 'Elio Nicolosi'
  },
  'Windchill|Walkthrough': {
    title: 'Windchill PDM Overview',
    subtitle: 'PLM | Windchill | Walkthrough | 12:29',
    meta: 'Single video · Windchill · Walkthrough',
    stats: '27 uses · 26 DemoBoards · 1 public link view',
    updated: 'Updated Jul 3, 2025',
    owner: 'Cody Wiltrout'
  }
};
function checkExistingAsset(btn, level) {
  btn.disabled = true;
  btn.style.opacity = '.6';
  btn.textContent = 'Checking Demo Database…';
  var resultEl = document.getElementById('existingCheck-' + level);
  var products = Array.from(document.querySelectorAll('#productScopeRow .stage-pill--active')).map(function(p) { return p.dataset.value; });
  var key = (products[0] || 'Other') + '|' + level;
  setTimeout(function() {
    var match = EXISTING_ASSET_MATCHES[key];
    btn.style.display = 'none';
    resultEl.style.display = '';
    if (match) {
      resultEl.innerHTML =
        '<div class="modal__note" style="align-items:flex-start; background:var(--orion-warn-bg);">' +
          '<svg class="orion-ico orion-ico--sm" style="color:var(--orion-warn-ink); margin-top:2px;"><use href="#i-info"/></svg>' +
          '<div>' +
            '<div style="font-weight:700; margin-bottom:4px; color:var(--orion-warn-ink);">Found something similar in the Demo Database</div>' +
            '<div style="font-weight:600;">' + match.title + '</div>' +
            '<div class="orion-subtle" style="margin:2px 0 6px; font-size:12px;">' + match.subtitle + '</div>' +
            '<div style="font-size:12px; color:var(--orion-text-2);">' + match.meta + ' · ' + match.stats + '<br>' + match.updated + ' · owner ' + match.owner + '</div>' +
            '<div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">' +
              '<button class="btn-ghost" style="flex:none; padding:6px 12px;" data-action="asset-decision" data-level="' + level + '" data-decision="use-as-is">Use as-is</button>' +
              '<button class="btn-ghost" style="flex:none; padding:6px 12px;" data-action="asset-decision" data-level="' + level + '" data-decision="refresh">Needs a quick refresh</button>' +
              '<button class="btn-primary-sm" style="flex:none; padding:6px 12px;" data-action="asset-decision" data-level="' + level + '" data-decision="new">Create new anyway</button>' +
            '</div>' +
          '</div>' +
        '</div>';
    } else {
      resultEl.innerHTML =
        '<div class="modal__note"><svg class="orion-ico orion-ico--sm" style="color:var(--orion-green-ink);"><use href="#i-check"/></svg>' +
        '<span>No similar asset found in the Demo Database for this product and style — clear to create something new.</span></div>';
    }
  }, 700);
}
function recordAssetDecision(level, decision) {
  var resultEl = document.getElementById('existingCheck-' + level);
  var labels = { 'use-as-is': 'Use the existing asset as-is', 'refresh': 'Refresh the existing asset', 'new': 'Create a new asset anyway' };
  resultEl.innerHTML = '<div class="share-result"><div class="share-result__label"><svg class="orion-ico orion-ico--sm"><use href="#i-check"/></svg>Decision recorded</div>' +
    '<div class="share-result__meta">' + labels[decision] + ' — the content team will see this when they review your request.</div></div>';
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
/* Replaced at runtime by hub-api.js, which keeps the File objects and uploads
   them. This version used to render a chip and then clear the input,
   discarding every file; it now refuses rather than pretending, for the case
   where that script fails to load. */
function handleAttachmentFiles(input) {
  var list = document.getElementById('attachmentList');
  input.value = '';
  list.innerHTML = '<span class="attach-warn">The Hub could not be reached, so '
    + 'files cannot be attached. Reload the page and try again.</span>';
}
/* Replaced at runtime by hub-api.js, which actually posts the answers. This
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

function escAttr(s) { return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;'); }


function videoAssetFromData(data) {
  var product = data.product || '';
  var segment = data.segment || '';
  var funnel = data.funnel || '';
  var cf = data.cf || '';

  var card = document.createElement('div');
  card.className = 'asset-card';
  card.dataset.type = 'video';
  card.dataset.product = product;
  card.dataset.segment = segment;
  card.dataset.stage = funnel;
  card.dataset.cf = cf;

  var logoMap = { Windchill: ['logo-windchill', '0 0 1299.67 299.6'], Creo: ['logo-creo', '0 0 1334.88 449.9'] };
  var logo = logoMap[product];
  var metaHtml = logo
    ? '<span class="meta-logo-chip"><svg class="meta-logo" viewBox="' + logo[1] + '"><use href="#' + logo[0] + '"/></svg></span> ' + escAttr(funnel)
    : escAttr(product || 'Cross-Portfolio') + (funnel ? ' \u00b7 ' + escAttr(funnel) : '');

  var actionsHtml = data.share
    ? '<button class="btn-primary-sm" data-share-title="' + escAttr(data.share.title) + '" data-share-meta="' + escAttr(data.share.meta) + '" data-share-uuid="' + escAttr(data.share.uuid) + '" data-action="share"><svg class="orion-ico--sm orion-ico"><use href="#i-send"/></svg>Share</button>'
    : '<span class="orion-badge orion-badge--open" title="Silent cut \u2014 no narration">No audio track</span>';

  card.innerHTML =
    '<div class="asset-card__thumb">' +
      '<span class="type-chip"><svg class="orion-ico--sm orion-ico"><use href="#i-video"/></svg>Video</span>' +
      '<div class="play-btn" style="cursor:default;"><svg><use href="#i-play"/></svg></div>' +
      (data.duration ? '<span class="duration-chip">' + escAttr(data.duration) + '</span>' : '') +
    '</div>' +
    '<div class="asset-card__body">' +
      '<div class="asset-card__title">' + data.title + '</div>' +
      '<div class="asset-card__meta">' + metaHtml + '</div>' +
      '<div class="asset-card__stats">' + (data.desc || '') + '</div>' +
      '<div class="asset-card__actions">' + actionsHtml + '</div>' +
    '</div>';

  var thumbEl = card.querySelector('.asset-card__thumb');
  thumbEl.style.backgroundImage = "url('" + data.thumb + "')";
  thumbEl.style.backgroundSize = 'cover';
  thumbEl.style.backgroundPosition = 'center';

  return card;
}

// Filled with real cards by static/hub-api.js, which also owns filtering;
// the mock-up's own filter over sample cards was removed 2026-10-14.
var HUB_ASSET_POOL = null;
function hubApplyFilters() {}

function hubResetFilters() {
  document.getElementById('hubSearchInput').value = '';
  // hubApplyFilters() is window.hubApplyFilters by the time this runs --
  // hub-api.js points it at its own applyFilters() at boot -- so this
  // function's own job is only clearing every control's value, and a new
  // control needs adding here or Reset silently leaves it set.
  ['hubFilterType', 'hubFilterProduct', 'hubFilterSegment', 'hubFilterStage',
   'hubFilterLanguage', 'hubFilterCf'].forEach(function(id) {
    document.getElementById(id).value = '';
  });
  hubApplyFilters();
}

document.getElementById('hubSearchInput').addEventListener('input', hubApplyFilters);
['hubFilterType','hubFilterProduct','hubFilterSegment','hubFilterStage','hubFilterCf'].forEach(function(id) {
  document.getElementById(id).addEventListener('change', hubApplyFilters);
});
hubApplyFilters();

/* ── One listener for every control on the page (2026-10-14) ──────────────
 * The markup names what a control does (data-action="..."); this table says
 * how. Functions are looked up on window at click time, so static/hub-api.js
 * can still wrap one (openRequestView, submitAssetRequest...) and be called.
 * Replaces the inline onclick attributes the concept mock-up carried. */
var HUB_ACTIONS = {
  "pill-select": function (el) { pillSelect(el); },
  "pill-toggle-kind": function (el) { pillToggle(el); computeKindOfDemo(); },
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
  "check-existing": function (el) { window.checkExistingAsset(el, el.dataset.level); },
  "asset-decision": function (el) {
    window.recordAssetDecision(el.dataset.level, el.dataset.decision);
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

