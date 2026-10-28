/* Reports and Get help (A2, Seb 2026-10-07; Liwei 2026-10-23/28).
 *
 * "Report an issue", a quiet link at the top of a demo's page, opens a
 * small form about that demo, which goes to the owners of its segment (set
 * on Admin -> Report owners, services/support_reports.py). "Get help", at
 * the foot of the sidebar beside Share feedback (#/help), is about the Hub
 * itself -- it will not load, the list is out of date -- and goes to the
 * Hub team; it has its own categories. Below it, "My reports": everything
 * this person reported and where it stands. Both are handled in the Hub
 * Tasks list and their status is read back from there. Partners may report
 * too and are recorded only as "partner".
 *
 * Part of the Hub page's script; static/js/hub/main.js loads it through
 * nav.js and detail.js. */

import { fullDate, report as complain } from "./util.js";
import { hubPermissions } from "./permissions.js";
import { closeAdvancedSearch } from "./search.js";

var categories = null;          // {demo: [...], hub: [...]}, from /api/support/options, once

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function options() {
  if (categories) return Promise.resolve(categories);
  return fetch("/api/support/options").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) { categories = d; return categories; });
}

/* The form, for a demo (asset) or for help (null). onDone(answer) after it
 * was sent; onCancel when there is somewhere to go back to. */
function reportForm(asset, onDone, onCancel) {
  var form = el("form", "hub-rpt__form");
  form.noValidate = true;
  var host = el("div", "hub-rpt__cats");
  host.setAttribute("role", "radiogroup");
  host.setAttribute("aria-label", "What kind of problem");
  var label = el("div", "hub-rpt__label", asset ? "What is wrong with this demo?"
                                                : "What is wrong with the Hub?");
  form.appendChild(label);
  form.appendChild(host);
  options().then(function (sets) {
    (asset ? sets.demo : sets.hub).forEach(function (c) {
      var opt = el("label", "hub-rpt__cat");
      var radio = el("input");
      radio.type = "radio";
      radio.name = "category";
      radio.value = c;
      opt.appendChild(radio);
      opt.appendChild(el("span", null, c));
      host.appendChild(opt);
    });
  }).catch(function (err) { host.textContent = "Could not load the categories: " + err.message; });

  var text = el("textarea", "hub-rpt__details");
  text.rows = 5;
  text.maxLength = 2000;
  text.placeholder = asset
    ? "What happened, which file, what you expected. A link or file name helps."
    : "What happened, where, and what you expected. For a problem with one demo, use "
      + "Report an issue on its page.";
  text.setAttribute("aria-label", "Details");
  form.appendChild(el("div", "hub-rpt__label", "Details"));
  form.appendChild(text);

  var note = el("div", "hub-rpt__note", asset
    // Asking for a demo to be made Internal or Open is "Other" (Liwei,
    // 2026-10-28: rare, no category of its own; the request flow is gone).
    ? "It goes to the team that looks after this demo's segment, not to the person who uploaded "
      + "it. To ask for it to be made Internal or Open, choose Other and say why."
    : "It goes to the team that runs the Hub.");
  form.appendChild(note);
  var error = el("div", "hub-rpt__error");
  error.setAttribute("role", "alert");
  form.appendChild(error);

  var foot = el("div", "hub-rpt__foot");
  if (onCancel) {
    var cancel = el("button", "btn-ghost", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", onCancel);
    foot.appendChild(cancel);
  }
  var send = el("button", "btn-primary-sm", "Send");
  send.type = "submit";
  foot.appendChild(send);
  form.appendChild(foot);

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var picked = form.querySelector("input[name=category]:checked");
    error.textContent = "";
    if (!picked) { error.textContent = "Choose what kind of problem it is."; return; }
    if (text.value.trim().length < 5) { error.textContent = "Say a little more in Details."; return; }
    send.disabled = true;
    send.textContent = "Sending…";
    fetch("/api/support/reports", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: picked.value, details: text.value.trim(),
                             asset_id: asset ? asset.id : null })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
        return d;
      });
    }).then(onDone).catch(function (err) {
      send.disabled = false;
      send.textContent = "Send";
      error.textContent = err.message;
    });
  });
  return form;
}

function sentNote(answer) {
  var box = el("div", "hub-rpt__sent");
  box.innerHTML = '<svg class="orion-ico orion-ico--sm"><use href="#i-check"/></svg>';
  box.appendChild(el("span", null, "Sent to the " + (answer.segment === "General"
    ? "Hub team" : answer.segment + " owners") + ". "));
  var a = el("a", null, "See it under My reports");
  a.href = "#/help";
  box.appendChild(a);
  return box;
}

/* ── Report an issue, on a demo's page ────────────────────────────────── */
function openReportModal(asset) {
  var back = document.getElementById("hubReportBackdrop");
  if (back) back.remove();
  back = el("div", "modal-backdrop open");
  back.id = "hubReportBackdrop";
  var modal = el("div", "modal");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "hubReportTitle");
  modal.innerHTML = '<div class="modal__head"><div class="modal__head-title" id="hubReportTitle">'
    + '<svg class="orion-ico ico-indigo"><use href="#i-flag"/></svg> Report an issue</div>'
    + '<button class="modal__close" type="button" aria-label="Close"><svg class="orion-ico">'
    + '<use href="#i-x"/></svg></button></div>';
  var body = el("div", "modal__body");
  var about = el("div", "hub-rpt__about");
  about.appendChild(el("span", null, "About"));
  about.appendChild(el("b", null, asset.title || asset.id));
  body.appendChild(about);
  function close() {
    back.remove();
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e) { if (e.key === "Escape") close(); }
  body.appendChild(reportForm(asset, function (answer) {
    body.innerHTML = "";
    body.appendChild(sentNote(answer));
    var ok = el("button", "btn-primary-sm hub-rpt__done", "Done");
    ok.type = "button";
    ok.addEventListener("click", close);
    body.appendChild(ok);
    ok.focus();
  }, close));
  modal.appendChild(body);
  back.appendChild(modal);
  back.addEventListener("click", function (e) { if (e.target === back) close(); });
  modal.querySelector(".modal__close").addEventListener("click", close);
  modal.addEventListener("click", function (e) {
    if (e.target.closest("a[href='#/help']")) close();
  });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(back);
}

/* ── Get help and My reports (#/help) ─────────────────────────────────── */
function buildPage() {
  var page = document.getElementById("hubHelpPage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubHelpPage";
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to Technical Marketing Hub</button>'
    + '<div class="vp-head"><div>'
    +   '<div class="vp-title">Get help</div>'
    +   '<div class="orion-subtle">Tell the Hub team when the Hub itself is not working: '
    +   'it will not load, the demo list is out of date, you cannot sign in or find something. '
    +   'For a problem with one demo, use Report an issue on its page.</div>'
    + '</div></div>'
    + '<div class="hub-rpt"><section class="hub-rpt__card" id="hubHelpForm"></section>'
    + '<section class="hub-rpt__card"><h2 class="hub-rpt__h">My reports</h2>'
    + '<div id="hubMyReports"></div></section></div>';
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeHelp();
  });
  return page;
}

function openHelp() {
  var page = buildPage();
  closeAdvancedSearch();
  var request = document.getElementById("requestViewPage");
  if (request) request.classList.remove("active");
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  page.classList.add("active");
  markNav(true);
  freshForm();
  loadMine();
}

function freshForm() {
  var host = document.getElementById("hubHelpForm");
  host.innerHTML = "";
  host.appendChild(reportForm(null, function (answer) {
    host.innerHTML = "";
    host.appendChild(sentNote(answer));
    var again = el("button", "btn-ghost hub-rpt__done", "Ask something else");
    again.type = "button";
    again.addEventListener("click", freshForm);
    host.appendChild(again);
    loadMine();
  }));
}

function closeHelp() {
  var page = document.getElementById("hubHelpPage");
  if (!page || !page.classList.contains("active")) return;
  page.classList.remove("active");
  markNav(false);
  var detail = document.getElementById("videoPreviewPage");
  if (detail && detail.classList.contains("active")) return;
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "";
  if (thread) thread.style.display = "";
}

var STATUS_CLASS = { Open: "open", Done: "done", Rejected: "closed", Withdrawn: "closed",
                     Cancelled: "closed" };

function loadMine() {
  var host = document.getElementById("hubMyReports");
  if (!host.childNodes.length) host.textContent = "Loading…";
  fetch("/api/support/reports/mine").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) {
    var items = d.items || [];
    host.innerHTML = "";
    if (!items.length) {
      host.appendChild(el("div", "hub-rpt__empty",
        "Nothing yet. What you report, here or on a demo's page, is listed here with its status."));
      return;
    }
    var wrap = el("div", "hub-table-wrap");
    var table = el("table", "hub-table hub-rpt__table");
    table.innerHTML = "<thead><tr><th><span class='hub-rvw__th'>Sent</span></th>"
      + "<th><span class='hub-rvw__th'>About</span></th>"
      + "<th><span class='hub-rvw__th'>Category</span></th>"
      + "<th><span class='hub-rvw__th'>Status</span></th></tr></thead>";
    var body = el("tbody");
    items.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", "hub-rpt__when", fullDate((r.at || "").slice(0, 10))));
      var about = el("td", "hub-table__td--title");
      if (r.asset_id) {
        var a = el("a", null, r.title || r.asset_id);
        a.href = "#/asset/" + encodeURIComponent(r.asset_id);
        a.addEventListener("click", function () { window.hubDetailReturn = "#/help"; });
        about.appendChild(a);
      } else {
        about.appendChild(el("b", null, "Get help"));
      }
      about.appendChild(el("div", "hub-rvw__sub hub-rpt__text", r.details || ""));
      tr.appendChild(about);
      tr.appendChild(el("td", null, r.category || ""));
      var st = el("td");
      st.appendChild(el("span", "hub-rpt__status hub-rpt__status--"
        + (STATUS_CLASS[r.status] || "open"), r.status || "Open"));
      tr.appendChild(st);
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    host.appendChild(wrap);
    host.appendChild(el("div", "hub-rvw__note",
      "The status is set by whoever handles the report; it can take a minute to show here."));
  }).catch(function (err) {
    host.textContent = "";
    complain("Could not load your reports: " + err.message, true);
  });
}

/* ── at the foot of the sidebar, beside Share feedback (2026-10-28) ──── */
function addHelpNav() {
  hubPermissions.then(function (granted) {
    if (granted.indexOf("view_hub") < 0 || document.getElementById("navHelp")) return;
    var feedback = document.querySelector(".orion-side__foot .hub-foot__feedback");
    if (!feedback) return;
    var item = el("a", "hub-foot__feedback");
    item.id = "navHelp";
    item.href = "#/help";
    item.title = "When the Hub itself is not working";
    item.innerHTML =
        '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
      + '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.3"/>'
      + '<path d="M6.3 6.3a1.8 1.8 0 1 1 2.5 1.6c-.5.2-.8.6-.8 1.1v.4" fill="none"'
      + ' stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>'
      + '<circle cx="8" cy="11.4" r=".8" fill="currentColor"/></svg>'
      + "<span>Get help</span>";
    feedback.insertAdjacentElement("beforebegin", item);
    if (location.hash === "#/help") markNav(true);
  });
}

function markNav(on) {
  var item = document.getElementById("navHelp");
  if (!item) return;
  item.classList.toggle("hub-foot__feedback--on", on);
  if (on) document.querySelectorAll(".orion-navitem--active, .orion-navitem.is-active")
    .forEach(function (n) { n.classList.remove("orion-navitem--active", "is-active"); });
}

export { addHelpNav, closeHelp, openHelp, openReportModal };
