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

var dsrRooms = [
  { name: 'Bobcat – Windchill AI Expansion FY26Q3', meta: '3 assets · updated yesterday' },
  { name: 'Acme Robotics – PLM Modernization', meta: '7 assets · updated Jul 20' }
];
var dsrSelected = null;
function openDsrModal(title, meta) {
  document.getElementById('dsrAssetTitle').textContent = title;
  document.getElementById('dsrAssetMeta').textContent = meta;
  document.getElementById('dsrConfirm').style.display = 'none';
  dsrSelected = null;
  renderDsrRooms();
  document.getElementById('dsrBackdrop').classList.add('open');
}
function closeDsrModal() {
  document.getElementById('dsrBackdrop').classList.remove('open');
}
function renderDsrRooms() {
  var list = document.getElementById('dsrRoomList');
  list.innerHTML = '';
  dsrRooms.forEach(function(r, i) {
    var row = document.createElement('div');
    row.className = 'dsr-room-row' + (dsrSelected === i ? ' dsr-room-row--selected' : '');
    row.onclick = function() { dsrSelected = i; renderDsrRooms(); };
    row.innerHTML = '<span class="dsr-room-row__radio"></span><div><div class="dsr-room-row__name">' + r.name + '</div><div class="dsr-room-row__meta">' + r.meta + '</div></div>';
    list.appendChild(row);
  });
  var newRow = document.createElement('div');
  newRow.className = 'dsr-room-row dsr-room-row--new' + (dsrSelected === 'new' ? ' dsr-room-row--selected' : '');
  newRow.onclick = function() { dsrSelected = 'new'; renderDsrRooms(); };
  newRow.innerHTML = '<span class="dsr-room-row__radio"></span><div><div class="dsr-room-row__name">+ Create a new Digital Sales Room</div></div>';
  list.appendChild(newRow);
}
function addToDsr() {
  if (dsrSelected === null) return;
  var label = dsrSelected === 'new' ? 'a new Digital Sales Room' : dsrRooms[dsrSelected].name;
  document.getElementById('dsrConfirmText').textContent = 'Added to ' + label;
  document.getElementById('dsrConfirm').style.display = 'block';
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
  var vpDsrBtn = document.getElementById('vpDsrBtn');
  vpShareBtn.style.display = v.uuid ? '' : 'none';
  vpDsrBtn.style.display = v.uuid ? '' : 'none';
  vpShareBtn.onclick = function() { openShareModal(v.title, v.metaText, v.uuid); };
  vpDsrBtn.onclick = function() { openDsrModal(v.title, v.metaText); };

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
function openRequestView() {
  document.getElementById('videoPreviewPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = 'none';
  document.getElementById('mainThread').style.display = 'none';
  document.getElementById('requestViewPage').classList.add('active');
  document.getElementById('requestViewPage').scrollTop = 0;
  setActiveNav('navRequestAsset');
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
  'eStore': 'Overview',
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
        '<button class="btn-ghost" style="flex:none; padding:6px 12px;" onclick="openStyleExampleModal(\'' + level + '\')"><svg class="orion-ico--sm orion-ico"><use href="#i-play"/></svg>See an example of this style</button>' +
        '<button class="btn-ghost" style="flex:none; padding:6px 12px;" onclick="checkExistingAsset(this, \'' + level + '\')"><svg class="orion-ico--sm orion-ico"><use href="#i-search"/></svg>Check Consensus for something similar</button>' +
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
  btn.textContent = 'Checking Consensus…';
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
            '<div style="font-weight:700; margin-bottom:4px; color:var(--orion-warn-ink);">Found something similar in Consensus</div>' +
            '<div style="font-weight:600;">' + match.title + '</div>' +
            '<div class="orion-subtle" style="margin:2px 0 6px; font-size:12px;">' + match.subtitle + '</div>' +
            '<div style="font-size:12px; color:var(--orion-text-2);">' + match.meta + ' · ' + match.stats + '<br>' + match.updated + ' · owner ' + match.owner + '</div>' +
            '<div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">' +
              '<button class="btn-ghost" style="flex:none; padding:6px 12px;" onclick="recordAssetDecision(\'' + level + '\', \'use-as-is\')">Use as-is</button>' +
              '<button class="btn-ghost" style="flex:none; padding:6px 12px;" onclick="recordAssetDecision(\'' + level + '\', \'refresh\')">Needs a quick refresh</button>' +
              '<button class="btn-primary-sm" style="flex:none; padding:6px 12px;" onclick="recordAssetDecision(\'' + level + '\', \'new\')">Create new anyway</button>' +
            '</div>' +
          '</div>' +
        '</div>';
    } else {
      resultEl.innerHTML =
        '<div class="modal__note"><svg class="orion-ico orion-ico--sm" style="color:var(--orion-green-ink);"><use href="#i-check"/></svg>' +
        '<span>No similar asset found in Consensus for this product and style — clear to create something new.</span></div>';
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
function handleAttachmentFiles(input) {
  var list = document.getElementById('attachmentList');
  Array.from(input.files).forEach(function(f) {
    var chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = '<svg class="orion-ico orion-ico--sm"><use href="#i-file-text"/></svg> ' + f.name;
    list.appendChild(chip);
  });
  input.value = '';
}
function submitAssetRequest(e) {
  e.preventDefault();
  document.getElementById('requestFormCard').style.display = 'none';
  document.getElementById('requestSuccessCard').style.display = '';
  document.getElementById('requestViewPage').scrollTop = 0;
}

/* ============================================================
   DEMO VIDEO GALLERY (Discover > Demo Video Gallery)
   ============================================================ */
function openDemoGalleryView() {
  document.getElementById('videoPreviewPage').classList.remove('active');
  document.getElementById('requestViewPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = 'none';
  document.getElementById('mainThread').style.display = 'none';
  document.getElementById('demoGalleryPage').classList.add('active');
  document.getElementById('demoGalleryPage').scrollTop = 0;
  setActiveNav('navDemoGallery');
}
function closeDemoGalleryView() {
  document.getElementById('demoGalleryPage').classList.remove('active');
  document.getElementById('mainTopbar').style.display = '';
  document.getElementById('mainThread').style.display = '';
  setActiveNav('navHome');
}

function dvgShowPopover(cardEl) {
  if (!cardEl) return;
  var pop = document.getElementById('dvgCardPopover');
  var title = cardEl.querySelector('.dvg-card__title').textContent;
  var desc = cardEl.dataset.desc || '';
  var segment = cardEl.dataset.segment || '';
  var industry = cardEl.dataset.industry || '';
  var product = cardEl.dataset.product || '';
  var driver = cardEl.dataset.driver || '';
  var funnel = cardEl.dataset.funnel || '';
  var cf = cardEl.dataset.cf || '';
  var reasonEl = cardEl.querySelector('.dvg-card__reason');
  var reasonText = reasonEl ? reasonEl.textContent.trim() : '';

  document.getElementById('dvgPopTitle').textContent = title;
  document.getElementById('dvgPopDesc').textContent = desc;
  document.getElementById('dvgPopTags').innerHTML =
    '<span class="dvg-tag">' + segment + '</span>' +
    '<span class="dvg-tag">' + industry + '</span>' +
    '<span class="dvg-tag">' + product + '</span>' +
    '<span class="dvg-tag dvg-tag--driver">' + driver + '</span>' +
    '<span class="dvg-tag">' + funnel + '</span>';

  var cfLabel = cf === 'yes' ? 'Yes — cleared to share' : ('No' + (reasonText ? ' — ' + reasonText : ''));
  document.getElementById('dvgPopMeta').innerHTML =
    '<div class="dvg-popover__meta-row"><span>Customer-Facing</span><b>' + cfLabel + '</b></div>';

  dvgPositionPopover(cardEl, pop);
  pop.classList.add('open');
}
function dvgHidePopover() {
  document.getElementById('dvgCardPopover').classList.remove('open');
}
function dvgPositionPopover(cardEl, pop) {
  var rect = cardEl.getBoundingClientRect();
  var popWidth = Math.min(300, window.innerWidth - 24);
  pop.style.width = popWidth + 'px';
  var left = rect.left + rect.width / 2 - popWidth / 2;
  left = Math.max(12, Math.min(left, window.innerWidth - popWidth - 12));
  var estHeight = 220;
  var top;
  if (rect.bottom + estHeight + 12 < window.innerHeight) { top = rect.bottom + 8; }
  else if (rect.top - estHeight - 12 > 0) { top = rect.top - estHeight - 8; }
  else { top = Math.max(12, rect.top); }
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
}

function dvgApplyFilters() {
  var q = document.getElementById('dvgSearchInput').value.trim().toLowerCase();
  var segment = document.getElementById('dvgFilterSegment').value;
  var industry = document.getElementById('dvgFilterIndustry').value;
  var product = document.getElementById('dvgFilterProduct').value;
  var driver = document.getElementById('dvgFilterDriver').value;
  var funnel = document.getElementById('dvgFilterFunnel').value;
  var cf = document.getElementById('dvgFilterCf').value;

  var anyActive = !!(q || segment || industry || product || driver || funnel || cf);
  document.getElementById('dvgResetBtn').style.display = anyActive ? 'inline-flex' : 'none';

  var cards = document.querySelectorAll('.dvg-card');
  var visibleCount = 0;
  cards.forEach(function(card) {
    var title = (card.querySelector('.dvg-card__title').textContent || '').toLowerCase();
    var desc = (card.dataset.desc || '').toLowerCase();
    var matchesText = !q || title.indexOf(q) !== -1 || desc.indexOf(q) !== -1;
    var matchesSegment = !segment || card.dataset.segment === segment;
    var matchesIndustry = !industry || card.dataset.industry === industry;
    var matchesProduct = !product || card.dataset.product === product;
    var matchesDriver = !driver || card.dataset.driver === driver;
    var matchesFunnel = !funnel || card.dataset.funnel === funnel;
    var matchesCf = !cf || card.dataset.cf === cf;
    var visible = matchesText && matchesSegment && matchesIndustry && matchesProduct && matchesDriver && matchesFunnel && matchesCf;
    card.style.display = visible ? '' : 'none';
    if (visible) visibleCount++;
  });

  document.querySelectorAll('.dvg-rail').forEach(function(rail) {
    var anyVisible = Array.prototype.some.call(rail.querySelectorAll('.dvg-card'), function(c) { return c.style.display !== 'none'; });
    rail.style.display = anyVisible ? '' : 'none';
  });

  document.getElementById('dvgResultCount').textContent = visibleCount + ' of ' + cards.length + ' videos';
}
function dvgResetFilters() {
  document.getElementById('dvgSearchInput').value = '';
  document.getElementById('dvgFilterSegment').value = '';
  document.getElementById('dvgFilterIndustry').value = '';
  document.getElementById('dvgFilterProduct').value = '';
  document.getElementById('dvgFilterDriver').value = '';
  document.getElementById('dvgFilterFunnel').value = '';
  document.getElementById('dvgFilterCf').value = '';
  dvgApplyFilters();
}

document.getElementById('dvgSearchInput').addEventListener('input', dvgApplyFilters);
['dvgFilterSegment','dvgFilterIndustry','dvgFilterProduct','dvgFilterDriver','dvgFilterFunnel','dvgFilterCf'].forEach(function(id) {
  document.getElementById(id).addEventListener('change', dvgApplyFilters);
});
document.getElementById('dvgResetBtn').addEventListener('click', dvgResetFilters);

document.querySelectorAll('.js-dvg-share').forEach(function(btn) {
  btn.addEventListener('click', function() {
    openShareModal(btn.dataset.shareTitle, btn.dataset.shareMeta, btn.dataset.shareUuid);
  });
});

document.querySelectorAll('.dvg-card__thumb').forEach(function(thumb) {
  var card = thumb.closest('.dvg-card');
  thumb.addEventListener('mouseenter', function() { dvgShowPopover(card); });
  thumb.addEventListener('mouseleave', dvgHidePopover);
  thumb.addEventListener('focus', function() { dvgShowPopover(card); });
  thumb.addEventListener('blur', dvgHidePopover);
});
document.querySelectorAll('.dvg-rail__track').forEach(function(track) {
  track.addEventListener('scroll', dvgHidePopover);
});

