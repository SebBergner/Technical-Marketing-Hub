/* Small helpers every tab of the Admin page uses: building elements,
 * cards and rows, dates, the drill-down sheet, and who is signed in
 * (session).
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

var $ = function (id) { return document.getElementById(id); };

function show(view) {
  ["loginView", "offView", "dashView"].forEach(function (id) {
    $(id).hidden = id !== view;
  });
}

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function card(titleText) {
  var c = el("div", "card");
  // Not `section-head`: a card title sits one level below a section title,
  // and sharing the class gave every card the section's accent bar, which
  // flattened the two back into one.
  var head = el("div", "card-head");
  head.appendChild(el("h2", null, titleText));
  c.appendChild(head);
  return c;
}

function row(parent, label, value, pillClass) {
  var d = el("div", "kv");
  d.appendChild(el("dt", null, label));
  var dd = el("dd");
  if (pillClass) {
    dd.appendChild(el("span", "pill " + pillClass, value));
  } else {
    dd.textContent = value === null || value === undefined ? "—" : String(value);
    dd.className = "num";
  }
  d.appendChild(dd);
  parent.appendChild(d);
  return d;
}

/* The daily sync (backend/auto_sync.py). First in "Connected systems"
 * because it is about both of the cards after it: it presses their two
 * sync buttons once a day. Liwei, 2026-09-28. */
function two(n) { return (n < 10 ? "0" : "") + n; }

function localHour(hourUtc) {
  var d = new Date();
  d.setUTCHours(hourUtc, 0, 0, 0);
  return two(d.getHours()) + ":" + two(d.getMinutes());
}

function when(iso) {
  if (!iso) return "—";
  var d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function tile(host, n, label, note, d) {
  var t = el("div", "tile");
  var top = el("div", "tile__top");
  top.appendChild(el("div", "tile__n",
    typeof n === "number" ? n.toLocaleString() : String(n)));
  if (d) top.appendChild(el("span", "trend trend--" + d.dir, d.text));
  t.appendChild(top);
  t.appendChild(el("div", "tile__l", label));
  if (note) t.appendChild(el("div", "tile__note", note));
  host.appendChild(t);
}

function delta(now, before) {
  /* "+18%" only where there is something to compare with, and never a
   * percentage of zero: 0 -> 4 is "new", not "+400%". */
  if (before === null || before === undefined) return null;
  if (!before) return now ? { text: "new", dir: "up" } : null;
  var pct = Math.round((now - before) / before * 100);
  if (pct === 0) return { text: "level", dir: "flat" };
  return { text: (pct > 0 ? "+" : "") + pct + "%", dir: pct > 0 ? "up" : "down" };
}
function openSheet(title, sub) {
  $("sheetTitle").textContent = title;
  $("sheetSub").textContent = sub || "";
  $("sheetBody").innerHTML = "";
  $("overlay").hidden = false;
  return $("sheetBody");
}
var TYPE_WORD = { video: "Video", ldk: "LDK", vdk: "VDK", vm: "Virtual Machine",
                  cad_model: "CAD Dataset" };

function demoLink(id, title) {
  var a = el("a", null, title || id);
  a.href = "/#/asset/" + encodeURIComponent(id);
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}

function actorWord(actor) {
  if (actor === "admin-session") return "Admin password";
  if (actor === "anonymous") return "Not signed in";
  return String(actor || "—").replace(/^(user|dev):/, "");
}

/* How this browser got in -- a signed-in person with View Admin ("sso")
 * or the shared password ("password") -- and what it may do. */
var session = { via: null, permissions: [] };

export {
  $, actorWord, card, delta, demoLink, el, localHour, openSheet, row, session,
  show, tile, two, TYPE_WORD, when
};
