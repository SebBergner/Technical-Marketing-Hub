/* Admin -> Search terms (Liwei, 2026-11-13; backend/services/search_terms.py).
 *
 * Groups of terms that mean the same -- an abbreviation and its words -- so
 * a search for one also finds the demos that say the other. Everyone with
 * View Admin sees them and can try a search; Maintain content adds, changes
 * and removes them. Every change is in the Admin log.
 *
 * Part of the Admin page's script; static/js/admin/main.js loads it. */

import { $, el, session, when } from "./util.js";
import { loadChanges } from "./access.js";

var groups = [];
var bound = false;

function canEdit() {
  return (session.permissions || []).indexOf("maintain_content") >= 0;
}

function api(method, url, body) {
  return fetch(url, {
    method: method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.detail || "HTTP " + r.status);
      return d;
    });
  });
}

function split(text) {
  return text.split(",").map(function (t) { return t.trim(); }).filter(Boolean);
}

function loadTerms() {
  bind();
  $("stAdd").hidden = !canEdit();
  loadChanges("stChanges", "Search terms");
  return api("GET", "/api/admin/search-terms").then(function (d) {
    groups = d.groups;
    $("stIntro").textContent = (d.saved
      ? "Last changed " + when(d.changed_at) + "."
      : "The first version, made from the catalogue and the feedback; the first change saves it.")
      + (canEdit() ? "" : " Changing them needs Maintain content.");
    render();
  }).catch(function (err) { $("stBody").textContent = "Could not load: " + err.message; });
}

function render() {
  var host = $("stBody");
  var words = $("stFilter").value.toLowerCase().split(/\s+/).filter(Boolean);
  var shown = groups.filter(function (g) {
    var text = (g.terms.join(" ") + " " + (g.note || "")).toLowerCase();
    return words.every(function (w) { return text.indexOf(w) >= 0; });
  });
  $("stCount").textContent = shown.length === groups.length
    ? groups.length + " groups" : shown.length + " of " + groups.length + " groups";
  host.innerHTML = "";
  if (!shown.length) {
    host.appendChild(el("div", "faint", groups.length ? "No group matches." : "No groups yet."));
    return;
  }
  var table = el("table", "st-table");
  var head = el("tr");
  ["Terms that mean the same", "Note", ""].forEach(function (h) { head.appendChild(el("th", null, h)); });
  var thead = el("thead");
  thead.appendChild(head);
  table.appendChild(thead);
  var body = el("tbody");
  shown.forEach(function (g) { body.appendChild(groupRow(g)); });
  table.appendChild(body);
  host.appendChild(table);
}

function groupRow(g) {
  var tr = el("tr");
  var terms = el("td", "st-terms");
  g.terms.forEach(function (t, i) {
    if (i) terms.appendChild(el("span", "st-eq", "="));
    terms.appendChild(el("span", "st-term", t));
  });
  tr.appendChild(terms);
  var note = el("td", "st-note faint", g.note || "");
  if (g.changed_at) note.title = "Changed " + when(g.changed_at);
  tr.appendChild(note);
  var acts = el("td", "st-acts");
  if (canEdit()) {
    var edit = el("button", null, "Edit");
    edit.type = "button";
    edit.addEventListener("click", function () { tr.replaceWith(editRow(g)); });
    var del = el("button", "btn-danger", "Remove");
    del.type = "button";
    del.addEventListener("click", function () {
      if (del.dataset.armed !== "1") {
        del.dataset.armed = "1";
        del.textContent = "Remove it?";
        return;
      }
      del.disabled = true;
      api("DELETE", "/api/admin/search-terms/" + encodeURIComponent(g.id))
        .then(loadTerms)
        .catch(function (err) { del.disabled = false; del.textContent = err.message; });
    });
    acts.appendChild(edit);
    acts.appendChild(del);
  }
  tr.appendChild(acts);
  return tr;
}

function editRow(g) {
  var tr = el("tr", "st-editing");
  var td = el("td");
  td.colSpan = 3;
  var terms = el("input");
  terms.value = g.terms.join(", ");
  terms.setAttribute("aria-label", "Terms, separated by commas");
  var note = el("input");
  note.value = g.note || "";
  note.placeholder = "Note (optional)";
  note.setAttribute("aria-label", "Note");
  var save = el("button", "btn-primary", "Save");
  save.type = "button";
  var cancel = el("button", null, "Cancel");
  cancel.type = "button";
  var msg = el("span", "st-msg");
  var acts = el("div", "st-addacts");
  [save, cancel, msg].forEach(function (n) { acts.appendChild(n); });
  var box = el("div", "st-edit");
  [terms, note, acts].forEach(function (n) { box.appendChild(n); });
  td.appendChild(box);
  tr.appendChild(td);
  cancel.addEventListener("click", render);
  save.addEventListener("click", function () {
    save.disabled = true;
    api("PUT", "/api/admin/search-terms/" + encodeURIComponent(g.id),
        { terms: split(terms.value), note: note.value })
      .then(loadTerms)
      .catch(function (err) { save.disabled = false; msg.textContent = err.message; });
  });
  setTimeout(function () { terms.focus(); }, 0);
  return tr;
}

function addGroup() {
  var btn = $("stAddBtn");
  var msg = $("stAddMsg");
  msg.textContent = "";
  msg.classList.remove("st-msg--ok");
  btn.disabled = true;
  api("POST", "/api/admin/search-terms",
      { terms: split($("stAddTerms").value), note: $("stAddNote").value })
    .then(function (g) {
      $("stAddTerms").value = "";
      $("stAddNote").value = "";
      msg.textContent = "Added: " + g.terms.join(" = ");
      msg.classList.add("st-msg--ok");
      return loadTerms();
    })
    .catch(function (err) { msg.textContent = err.message; })
    .then(function () { btn.disabled = false; });
}

var tryTimer = null;
function tryQuery() {
  clearTimeout(tryTimer);
  tryTimer = setTimeout(function () {
    var q = $("stTry").value.trim();
    var out = $("stTryOut");
    if (!q) { out.textContent = "Type a search to see what else it looks for."; return; }
    api("GET", "/api/admin/search-terms/try?q=" + encodeURIComponent(q)).then(function (d) {
      if ($("stTry").value.trim() !== q) return;
      out.innerHTML = "";
      if (!d.also.length) {
        out.textContent = "No group names a word of this search: it is searched as typed.";
        return;
      }
      out.appendChild(document.createTextNode("Also looks for: "));
      d.also.forEach(function (v, i) {
        if (i) out.appendChild(document.createTextNode(", "));
        out.appendChild(el("b", null, "“" + v + "”"));
      });
    }).catch(function (err) { out.textContent = err.message; });
  }, 200);
}

function bind() {
  if (bound) return;
  bound = true;
  $("stFilter").addEventListener("input", render);
  $("stTry").addEventListener("input", tryQuery);
  $("stAddBtn").addEventListener("click", addGroup);
  $("stAddTerms").addEventListener("keydown", function (e) { if (e.key === "Enter") addGroup(); });
}

export { loadTerms };
