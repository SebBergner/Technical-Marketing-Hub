/* The share modal (a Consensus DemoBoard; hidden for now, see
 * SHARE_BUTTON_HIDDEN in cards.js).
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

/* ---------------------------------------------------- the share modal */

/* Elio's DemoBoard modal was a mockup and said so nowhere: two hardcoded
 * bobcat.com recipients that could not be removed, an "Add email" box wired
 * to nothing, a fake link, and -- the dangerous part -- the line "Sent to 2
 * recipients", displayed without a single network call having been made.
 *
 * The backend endpoint existed and was never called. Both halves are joined
 * here, against the contract as the live API actually answers it:
 *
 *   organization  required for a trackable DemoBoard -- Consensus rejects
 *                 the call without it. This is NOT the opportunity field.
 *   share_to[]    keyed on `contact_email`, not `email`. first_name and
 *                 last_name are the working name keys.
 *   isTest        creates the board flagged as a test so it stays out of
 *                 reporting. Default on, because the alternative emails
 *                 real people.
 */
var shareAsset = null;                 // the asset the modal is open for
var shareRecipients = [];              // {email, first_name, last_name}

/* Accepts a bare address or "Jane Doe <jane@co.com>", because that is the
 * form people paste out of a mail client. */
function parseRecipient(text) {
  var raw = String(text || "").trim().replace(/[,;]+$/, "");
  if (!raw) return null;
  var angled = raw.match(/^(.*?)<([^>]+)>$/);
  var email = (angled ? angled[2] : raw).trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;

  var out = { email: email };
  var name = angled ? angled[1].trim().replace(/^["']|["']$/g, "") : "";
  if (name) {
    var parts = name.split(/\s+/);
    out.first_name = parts[0];
    if (parts.length > 1) out.last_name = parts.slice(1).join(" ");
  }
  return out;
}

function renderRecipients() {
  var host = document.getElementById("shareChips");
  var input = document.getElementById("shareRecipientInput");
  if (!host || !input) return;
  host.querySelectorAll(".chip").forEach(function (c) { c.remove(); });

  shareRecipients.forEach(function (r, index) {
    var chip = document.createElement("span");
    chip.className = "chip";
    var label = [r.first_name, r.last_name].filter(Boolean).join(" ");
    chip.textContent = label ? label + " (" + r.email + ")" : r.email;
    var x = document.createElement("button");
    x.className = "chip__x";
    x.type = "button";
    x.textContent = "\u00d7";
    x.title = "Remove " + r.email;
    x.addEventListener("click", function () {
      shareRecipients.splice(index, 1);
      renderRecipients();
    });
    chip.appendChild(x);
    host.insertBefore(chip, input);
  });
}

function commitRecipient() {
  var input = document.getElementById("shareRecipientInput");
  var parsed = parseRecipient(input.value);
  if (!parsed) return false;
  if (!shareRecipients.some(function (r) { return r.email === parsed.email; })) {
    shareRecipients.push(parsed);
  }
  input.value = "";
  renderRecipients();
  return true;
}

function shareError(message) {
  var box = document.getElementById("shareError");
  if (!box) return;
  box.textContent = message || "";
  box.style.display = message ? "" : "none";
}

function wireShareModal() {
  var input = document.getElementById("shareRecipientInput");
  if (!input) return;

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commitRecipient(); }
    // Backspace on an empty box removes the last chip, as every chip input does.
    if (e.key === "Backspace" && !input.value && shareRecipients.length) {
      shareRecipients.pop();
      renderRecipients();
    }
  });
  // Losing focus with a half-typed address must not silently discard it.
  input.addEventListener("blur", commitRecipient);
  input.addEventListener("paste", function (e) {
    var text = (e.clipboardData || window.clipboardData).getData("text");
    if (!text || !/[,;\n]/.test(text)) return;      // single address: let it type
    e.preventDefault();
    text.split(/[,;\n]+/).forEach(function (piece) {
      var parsed = parseRecipient(piece);
      if (parsed && !shareRecipients.some(function (r) { return r.email === parsed.email; })) {
        shareRecipients.push(parsed);
      }
    });
    renderRecipients();
  });

  var button = document.getElementById("generateBtn");
  if (button) {
    button.removeAttribute("data-action");  // not the mock-up's generateShareLink()
    button.addEventListener("click", submitShare);
  }
}

async function submitShare() {
  commitRecipient();
  shareError("");

  var org = (document.getElementById("shareOrg").value || "").trim();
  var isTest = document.getElementById("shareIsTest").checked;
  if (!shareAsset) return;
  if (!org) {
    shareError("Consensus needs the account or organisation this DemoBoard is "
             + "for before it will create a trackable share.");
    return;
  }
  if (!shareRecipients.length) {
    shareError("Add at least one recipient. Each one gets their own tracked "
             + "invite, which is what makes a DemoBoard trackable.");
    return;
  }

  var button = document.getElementById("generateBtn");
  var restore = button.innerHTML;
  button.disabled = true;
  button.textContent = isTest ? "Creating test board\u2026" : "Sending\u2026";

  try {
    var response = await fetch("/api/share/consensus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: shareAsset.id,
        organization: org,
        opportunity: (document.getElementById("shareOpp").value || "").trim() || null,
        title: shareAsset.title,
        recipients: shareRecipients,
        trackable: true,
        is_test: isTest
      })
    });
    var data = await response.json();
    if (!response.ok) {
      // The endpoint's 409s explain themselves; show that text rather than
      // a generic failure, because it says what to do next.
      shareError(data.detail || ("Share failed (HTTP " + response.status + ")"));
      return;
    }

    document.getElementById("shareLinkText").textContent =
      data.url.replace(/^https?:\/\//, "");
    document.getElementById("shareResultLabel").textContent =
      data.is_test ? "Test DemoBoard created" : "DemoBoard sent";
    // A test board is kept OUT of reporting, so it must not also be
    // promised there -- the two halves of that sentence contradicted.
    document.getElementById("shareResultMeta").textContent = data.is_test
      ? "Flagged as a test: the link works, and it stays out of Consensus "
        + "reporting. Uncheck Test send to make a real one."
      : "Sent to " + shareRecipients.length + " recipient"
        + (shareRecipients.length === 1 ? "" : "s")
        + ". Engagement is visible in Consensus Reports.";
    document.getElementById("shareResult").style.display = "block";
    button.innerHTML = restore;
  } catch (err) {
    shareError("Could not reach the Hub: " + err.message);
  } finally {
    button.disabled = false;
    if (button.textContent.indexOf("\u2026") !== -1) button.innerHTML = restore;
  }
}

/* Elio's openShareModal takes three strings and knows nothing about the
 * asset. The share needs its id, so the card hands the whole thing over
 * before delegating to the original for the presentation. */
function openShareFor(asset) {
  shareAsset = asset;
  shareRecipients = [];
  var meta = [asset.segment, asset.funnel_stage].filter(Boolean).join(" \u00b7 ");
  window.openShareModal(asset.title, meta, asset.consensus_uuid);

  document.getElementById("shareOrg").value = "";
  document.getElementById("shareOpp").value = "";
  document.getElementById("shareRecipientInput").value = "";
  // Off by default now the control is hidden: a checkbox nobody can see
  // must not decide that every share is a silent test.
  document.getElementById("shareIsTest").checked = false;
  document.getElementById("shareResult").style.display = "none";
  shareError("");
  renderRecipients();
}

export {
  openShareFor, wireShareModal
};
