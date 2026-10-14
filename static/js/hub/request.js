/* The request intake: the form, its product scope, attachments, and
 * the check for demos that already exist.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { durationLabel, escapeHtml, pill } from "./util.js";
import { videoTypeOf } from "./cards.js";
import { familyDisplayName } from "./nav.js";

/* The product pills shipped as a hand-typed five: Windchill, Creo,
 * ServiceMax, Codebeamer, Other. The catalogue has NINETEEN families, and
 * three of the largest were missing -- ThingWorx with 111 assets, Mathcad
 * with 43, Arbortext with 15 -- so anyone wanting a ThingWorx video had to
 * file it as "Other". The single most useful field for routing a request
 * was the one most likely to be useless.
 *
 * Built from the same facets the rest of the page uses, so it cannot drift
 * again: a family that appears in the catalogue appears here the same day.
 * Ordered by how much of the catalogue each one holds, because that is also
 * roughly the order people look for them in.
 */
//: Removed outright from Product Scope, 2026-09-10 -- singleton families
//: (CAD-software-as-a-family, from CAD Model's free-text CAD_x0020_Product,
//: §9's "V2 scope") that are noise for someone filing a new request, not
//: products anyone requests. Liwei's call.
var PRODUCT_SCOPE_EXCLUDED = ["ProENGINEER Wildfire", "Division MOCKUP",
                              "ProENGINEER", "Catia", "CoCreate", "SolidWorks"];

//: Pulled to the front, in exactly this order, 2026-09-10 -- Liwei's call,
//: not a re-derivation of anything. Everything else that survives
//: PRODUCT_SCOPE_EXCLUDED (Mathcad, Arbortext, PTC Modeler, Servigistics,
//: ...) still follows behind them, sorted by count as before: this is a
//: priority order, not a replacement of the list -- explicitly confirmed
//: with Liwei rather than assumed, since dropping the rest silently would
//: have undone keeping Servigistics here on purpose (§8.6).
var PRODUCT_SCOPE_PRIORITY = ["Creo", "Codebeamer", "Windchill", "Jetstream",
                              "IPE", "ServiceMax", "Orbit"];

/* Elio's Scope box is green -- the colour of a result. While nothing is
 * picked it holds a prompt ("Select at least one product."), which then
 * read as a success (Liwei, 2026-10-01). Neutral until a product is
 * chosen. Wraps his computeProductScope(), which his inline handlers
 * look up on window at call time. */
function wireScopeState() {
  var compute = window.computeProductScope;
  if (typeof compute !== "function" || compute.hubWrapped) return;
  var mark = function () {
    var box = document.getElementById("productScopeResult");
    var picked = document.querySelectorAll("#productScopeRow .stage-pill--active").length;
    if (box) box.classList.toggle("hub-derived--pending", !picked);
  };
  window.computeProductScope = function () {
    var out = compute.apply(this, arguments);
    mark();
    return out;
  };
  window.computeProductScope.hubWrapped = true;
  mark();
}

function fillProductPills(facets) {
  var row = document.getElementById("productScopeRow");
  if (!row) return;
  var families = (facets.product_families || []).slice()
    .filter(function (f) { return PRODUCT_SCOPE_EXCLUDED.indexOf(f.value) === -1; })
    .sort(function (a, b) {
      var pa = PRODUCT_SCOPE_PRIORITY.indexOf(a.value);
      var pb = PRODUCT_SCOPE_PRIORITY.indexOf(b.value);
      if (pa !== -1 || pb !== -1) {
        if (pa === -1) return 1;
        if (pb === -1) return -1;
        return pa - pb;
      }
      return b.count - a.count;
    });
  if (!families.length) return;          // keep the markup rather than empty it

  row.innerHTML = "";
  families.forEach(function (f) {
    var pill = document.createElement("span");
    pill.className = "stage-pill";
    // The value submitted stays the raw family name -- taxonomy.py and
    // every stored request still call it "IPE"/"Jetstream"/"Orbit"; only
    // the label a person reads changes, same rule as the nav/dropdown
    // rename (§8.6). See FAMILY_DISPLAY above.
    pill.dataset.value = f.value;
    pill.textContent = familyDisplayName(f.value);
    pill.title = f.count + " asset" + (f.count === 1 ? "" : "s") + " today";
    row.appendChild(pill);
  });
  // "Other" is not a family and has no count; it is the honest home for a
  // product the catalogue has never carried, which is exactly when someone
  // is most likely to be requesting one.
  var other = document.createElement("span");
  other.className = "stage-pill";
  other.dataset.value = "Other";
  other.textContent = "Other";
  row.appendChild(other);

  // Elio's pills call pillToggle + computeProductScope through inline
  // onclick; rebuilt ones need the same behaviour bound directly.
  row.querySelectorAll(".stage-pill").forEach(function (pill) {
    pill.addEventListener("click", function () {
      window.pillToggle(pill);
      if (window.computeProductScope) window.computeProductScope();
    });
  });
}

/* Files the requester chose, kept as File objects until submission.
 *
 * The original handler rendered a chip and then cleared the input, which
 * discarded every File — the whole point of holding them here. Nothing left
 * the browser and the chip made it look attached.
 *
 * They are screened client-side against the same limits the server applies.
 * That is not the security boundary — the server's check is — it is so
 * someone learns their 30 MB video is too large before they fill in the
 * rest of the form, rather than after.
 */
var MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024;
var BLOCKED_EXTENSIONS = [
  ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs",
  ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".hta", ".cpl", ".jar",
  ".reg", ".lnk", ".iso", ".img", ".sh"
];
var pendingFiles = [];

function attachmentProblem(file) {
  var dot = file.name.lastIndexOf(".");
  var ext = dot === -1 ? "" : file.name.slice(dot).toLowerCase();
  if (BLOCKED_EXTENSIONS.indexOf(ext) !== -1) {
    return ext + " files are not accepted.";
  }
  if (file.size > MAX_ATTACHMENT_BYTES) {
    return (file.size / 1048576).toFixed(1) + " MB is over the 4 MB limit — "
         + "link it in the notes instead.";
  }
  if (!file.size) return "the file is empty.";
  return null;
}

function renderAttachments(problems) {
  var list = document.getElementById("attachmentList");
  if (!list) return;
  list.innerHTML = "";

  pendingFiles.forEach(function (file, index) {
    var chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = '<svg class="orion-ico orion-ico--sm"><use href="#i-file-text"/></svg> '
      + escapeHtml(file.name)
      + ' <span class="attach-size">' + (file.size / 1024).toFixed(0) + ' KB</span>';
    var x = document.createElement("button");
    x.type = "button";
    x.className = "chip__x";
    x.textContent = "\u00d7";
    x.title = "Remove " + file.name;
    x.addEventListener("click", function () {
      pendingFiles.splice(index, 1);
      renderAttachments([]);
    });
    chip.appendChild(x);
    list.appendChild(chip);
  });

  (problems || []).forEach(function (message) {
    var warn = document.createElement("span");
    warn.className = "attach-warn";
    warn.textContent = message;
    list.appendChild(warn);
  });
}

function takeAttachments(input) {
  var problems = [];
  Array.prototype.forEach.call(input.files, function (file) {
    var problem = attachmentProblem(file);
    if (problem) { problems.push(file.name + ": " + problem); return; }
    var duplicate = pendingFiles.some(function (f) {
      return f.name === file.name && f.size === file.size;
    });
    if (!duplicate) pendingFiles.push(file);
  });
  // Clearing the input is what lets the same file be chosen again after
  // being removed; the File objects are safe in pendingFiles by now.
  input.value = "";
  renderAttachments(problems);
}

/* -------------------------------------------------- the request intake */

/* submitAssetRequest() hid the form and showed the success card. No request
 * was made and nothing was written anywhere -- the same shape as the
 * DemoBoard modal before it was wired. A form that says "submitted" and
 * loses the answer is worse than one with no button.
 *
 * It posts to /api/requests now, which appends the submission locally
 * BEFORE touching Graph and then writes it to the Demo Requests list on
 * EXT-TDD. The two outcomes are different promises and the screen says
 * which one it is: recorded here, or visible to the team.
 */
var REQ_ROWS = {
  asset_type: "assetTypeRow",
  products: "productScopeRow",
  narrative: "narrativeAngleRow",
  target_length: "desiredLengthRow",
  customer_involvement: "customerRow",
  distribution_channels: "distributionRow",
  starting_materials: "startingMaterialsRow"
};

/* Pills carry data-value where one exists and otherwise mean their own
 * text. Reading textContent as the fallback keeps the two rows that were
 * built without data-value working, rather than silently sending nothing. */
function pillValues(rowId) {
  var row = document.getElementById(rowId);
  if (!row) return [];
  return Array.prototype.map.call(
    row.querySelectorAll(".stage-pill--active"),
    function (p) { return p.dataset.value || p.textContent.trim(); });
}

function fieldValue(id) {
  var el = document.getElementById(id);
  return el && el.value.trim() ? el.value.trim() : null;
}

function collectRequest() {
  var body = {
    asset_type: pillValues(REQ_ROWS.asset_type)[0] || "video",
    products: pillValues(REQ_ROWS.products),
    brief: fieldValue("reqBrief"),
    narrative: pillValues(REQ_ROWS.narrative)[0] || null,
    target_length: pillValues(REQ_ROWS.target_length)[0] || null,
    customer_involvement: pillValues(REQ_ROWS.customer_involvement)[0] || null,
    distribution_channels: pillValues(REQ_ROWS.distribution_channels),
    starting_materials: pillValues(REQ_ROWS.starting_materials),
    needed_by: fieldValue("reqTargetDate"),
    compelling_event: fieldValue("reqCompellingEvent"),
    requester_name: fieldValue("reqName"),
    requester_email: fieldValue("reqEmail"),
    notes: fieldValue("reqNotes")
  };
  // The starting-materials pills are ours to label; the list column expects
  // the words a person would read.
  var materials = { have: "Have materials", liberty: "Team has creative liberty" };
  body.starting_materials = body.starting_materials.map(function (v) {
    return materials[v] || v;
  });
  return body;
}

function requestProblem(message) {
  var box = document.getElementById("reqError");
  if (!box) return;
  box.textContent = message || "";
  box.style.display = message ? "" : "none";
  if (message) box.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function submitRequest(event) {
  if (event) event.preventDefault();
  requestProblem("");

  var body = collectRequest();
  if (!body.products.length) {
    requestProblem("Choose at least one product. It is what routes the request "
                 + "to the person who can scope it.");
    return;
  }

  var button = document.querySelector('[data-action="submit-request"]');
  var restore = button ? button.innerHTML : null;
  if (button) { button.disabled = true; button.textContent = "Submitting\u2026"; }

  try {
    var response;
    if (pendingFiles.length) {
      // multipart: the request itself travels as one JSON field, so the
      // server validates it against exactly the same model either way.
      var form = new FormData();
      form.append("request", JSON.stringify(body));
      pendingFiles.forEach(function (f) { form.append("files", f, f.name); });
      response = await fetch("/api/requests/with-files",
                             { method: "POST", body: form });
    } else {
      response = await fetch("/api/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
    }
    var data = await response.json();
    if (!response.ok) {
      requestProblem(data.detail
        || ("The request was not saved (HTTP " + response.status + ")."));
      return;
    }

    document.getElementById("requestFormCard").style.display = "none";
    var card = document.getElementById("requestSuccessCard");
    card.style.display = "";

    /* The reference is the point of the success screen: without it the
     * requester has nothing to quote when they chase it. */
    var note = document.getElementById("reqOutcome");
    if (note) {
      var lines = ["Reference " + data.id + "."];
      lines.push(data.synced
        ? "It is in the team's Demo Requests list."
        : (data.warning || "") + " Nothing has been lost — the team will pick it up.");
      var stored = (data.attachments || []).length;
      if (stored) {
        lines.push(stored + " file" + (stored === 1 ? "" : "s") + " attached.");
      }
      // A dropped attachment is never left for the requester to discover.
      (data.attachments_rejected || []).forEach(function (r) { lines.push(r); });
      note.textContent = lines.join(" ");
      note.className = "req-outcome"
        + ((data.synced && !(data.attachments_rejected || []).length)
           ? "" : " req-outcome--warn");
    }
    pendingFiles = [];
    document.getElementById("requestViewPage").scrollTop = 0;
  } catch (err) {
    requestProblem("Could not reach the Hub: " + err.message
                 + ". Nothing was submitted, so nothing was lost — try again.");
  } finally {
    if (button) { button.disabled = false; button.innerHTML = restore; }
  }
}

/* The page's actions call window.submitAssetRequest and
 * window.handleAttachmentFiles when used (static/js/hub-ui.js), so replacing
 * the globals is enough here. */
function wireRequestForm() {
  window.submitAssetRequest = submitRequest;
  window.handleAttachmentFiles = takeAttachments;
}

/* ── the duplicate check on the request form ──────────────────
 *
 * index.html ships a placeholder: it waits 700ms and looks the answer up in
 * a three-entry table, all Windchill, carrying invented usage figures under
 * real colleagues' names. Every other product fell through to "nothing
 * similar found", which is the worse of the two answers -- a clearance to
 * build something that may already exist, issued without looking.
 *
 * This asks the catalogue instead. Overriding the global rather than
 * editing index.html keeps the one-script-tag contract: the button's inline
 * onclick calls whatever window.checkExistingAsset is when it is clicked,
 * and this file is deferred, so it always wins.
 */
var DUPLICATE_LIMIT = 5;

function requestScopeProducts() {
  // "Other" is a real option on the form and matches no product facet, so
  // it widens the search rather than narrowing it to nothing.
  return Array.prototype.slice.call(
    document.querySelectorAll("#productScopeRow .stage-pill--active"))
    .map(function (p) { return p.dataset.value; })
    .filter(function (v) { return v && v !== "Other"; });
}

function duplicateRow(asset) {
  var row = document.createElement("div");
  row.style.cssText = "padding:8px 0;border-top:1px solid var(--orion-border)";

  var link = document.createElement("a");
  link.href = "#/asset/" + encodeURIComponent(asset.id);
  link.target = "_blank";
  link.rel = "noopener";
  link.style.cssText = "font-weight:600;text-decoration:none";
  link.textContent = asset.title || asset.id;
  row.appendChild(link);

  var bits = [videoTypeOf(asset), (asset.product_families || []).join(", "),
              asset.type === "ldk" ? "" : durationLabel(asset.duration_seconds)];
  var meta = document.createElement("div");
  meta.className = "orion-subtle";
  meta.style.cssText = "margin:2px 0;font-size:12px";
  meta.textContent = bits.filter(Boolean).join(" · ");
  row.appendChild(meta);

  var facts = [];
  // Named for what it is. This is Consensus's own tally on its own
  // platform, not anything the Hub measured, and calling it "uses" -- as
  // the placeholder did -- would invent a meaning it does not have.
  if (asset.external_views) {
    facts.push(asset.external_views
      + (asset.external_views === 1 ? " play" : " plays"));
  }
  if (asset.uploaded_at) facts.push("added " + asset.uploaded_at);
  if (facts.length) {
    var stats = document.createElement("div");
    stats.style.cssText = "font-size:12px;color:var(--orion-text-2)";
    stats.textContent = facts.join(" · ");
    row.appendChild(stats);
  }
  return row;
}

function renderDuplicateCheck(page, products, level, host, relaxed) {
  var who = (products.length ? products.join(", ") : "any product")
    + " · English";
  var scope = relaxed ? who : who + " · " + (level || "any style");

  var note = document.createElement("div");
  note.className = "modal__note";
  note.style.alignItems = "flex-start";

  if (!page.total) {
    var ok = document.createElement("span");
    ok.textContent = "Nothing in the catalogue matches " + scope
      + " — clear to create something new.";
    note.appendChild(ok);
    return note;
  }

  note.style.background = "var(--orion-warn-bg)";
  var body = document.createElement("div");
  body.style.width = "100%";

  var head = document.createElement("div");
  head.style.cssText = "font-weight:700;margin-bottom:2px;color:var(--orion-warn-ink)";
  head.textContent = page.total === 1
    ? "1 similar demo already exists"
    : page.total + " similar demos already exist";
  body.appendChild(head);

  var sub = document.createElement("div");
  sub.className = "orion-subtle";
  sub.style.cssText = "font-size:12px;margin-bottom:4px";
  // When the style filter was dropped, say so. "Nothing at this exact
  // style, but here is what exists for the product" and "here is what
  // matches exactly" support different decisions, and collapsing them
  // would overstate how close these are.
  sub.textContent = (relaxed
    ? "Nothing classified as “" + level + "” — showing everything for " + scope
    : "Matching " + scope)
    + (page.total > DUPLICATE_LIMIT
      ? " — " + DUPLICATE_LIMIT + " newest shown" : "");
  body.appendChild(sub);

  (page.items || []).forEach(function (a) { body.appendChild(duplicateRow(a)); });

  var actions = document.createElement("div");
  actions.style.cssText = "margin-top:10px";
  var proceed = document.createElement("button");
  proceed.className = "btn-primary-sm";
  proceed.type = "button";
  proceed.style.cssText = "flex:none;padding:6px 12px";
  proceed.textContent = "Create new anyway";
  // Dismisses the panel and nothing else. The placeholder's three buttons
  // answered "Decision recorded" and recorded nothing; a button that lies
  // about persisting something is worse than no button.
  proceed.addEventListener("click", function () { host.style.display = "none"; });
  actions.appendChild(proceed);
  body.appendChild(actions);

  note.appendChild(body);
  return note;
}

window.checkExistingAsset = function (btn, level) {
  var host = document.getElementById("existingCheck-" + level);
  if (!host) return;
  var products = requestScopeProducts();
  btn.disabled = true;
  btn.style.opacity = ".6";
  btn.textContent = "Checking Demo Database…";

  function query(depth) {
    var params = new URLSearchParams();
    products.forEach(function (p) { params.append("product", p); });
    if (depth) params.append("depth", depth);
    // Newest first. NOT sort=most_viewed, which looks like the obvious
    // choice and is not: it orders by our own stats.views, a counter
    // nothing has updated since usage moved to the event log, so every row
    // scores zero and the order is arbitrary while looking deliberate.
    params.append("sort", "recent");
    // English only, and the scope line says so. Without it a single demo
    // published in eight languages fills every slot with translations of
    // itself, pushing the genuinely different work off the list -- which
    // is the opposite of what a duplicate check is for.
    params.append("language", "en");
    params.append("limit", String(DUPLICATE_LIMIT));
    return fetch("/api/assets?" + params.toString()).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // The form offers four styles (VIDEO_LEVELS in index.html); assets carry
  // the five Video Types, and the server maps Teaser / Overview /
  // Walkthrough onto theirs (models.video_type_filter, 2026-09-30).
  // "Explainer" has no counterpart and therefore matches nothing, and filtering on it would hand
  // out a clean bill of health that only means the word is unused. So an
  // empty exact match falls back to the product alone, labelled as such.
  query(level)
    .then(function (page) {
      if (page.total || !level || !products.length) {
        return { page: page, relaxed: false };
      }
      return query(null).then(function (wider) {
        return { page: wider, relaxed: wider.total > 0 };
      });
    })
    .then(function (out) {
      btn.style.display = "none";
      host.style.display = "";
      host.innerHTML = "";
      host.appendChild(renderDuplicateCheck(
        out.page, products, level, host, out.relaxed));
    })
    .catch(function (err) {
      // "Could not check" and "nothing found" mean opposite things to
      // somebody deciding whether to build, so a failure never renders as
      // an all-clear. The button comes back so they can retry.
      console.warn("[hub-api] duplicate check failed", err);
      btn.disabled = false;
      btn.style.opacity = "";
      btn.textContent = "Check Demo Database for Similar Content";
      host.style.display = "";
      host.innerHTML = "";
      var warn = document.createElement("div");
      warn.className = "modal__note";
      var text = document.createElement("span");
      text.textContent = "Could not reach the catalogue, so nothing was "
        + "checked — this is not an all-clear. Try again in a moment.";
      warn.appendChild(text);
      host.appendChild(warn);
    });
};

export {
  fillProductPills, wireRequestForm, wireScopeState
};
