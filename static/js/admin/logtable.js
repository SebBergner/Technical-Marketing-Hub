/* The Admin log as a table: the Sign-ins tab's whole log, and the
 * "Recent changes" at the foot of Admin and Content health tabs. No imports
 * but util.js, so either page can load it (2026-11-11).
 *
 * Shared by static/js/admin/ and static/js/content-health/. */

import { actorWord, el } from "./util.js";

function detailWord(d) {
  var parts = [];
  var add = function (obj) {
    Object.keys(obj || {}).forEach(function (k) {
      var v = obj[k];
      parts.push(k + ": " + (typeof v === "object" ? JSON.stringify(v) : v));
    });
  };
  add(d && d.query);
  add(d && d.body);
  if (d && d.body_bytes) parts.push("upload, " + d.body_bytes + " bytes");
  return parts.join(" · ");
}

function adminLogTable(items, withArea) {
  var t = el("table");
  var hr = t.createTHead().insertRow();
  var heads = ["When", "Who"].concat(withArea ? ["Area"] : [])
    .concat(["What", "Demo / group", "Details", "Result"]);
  heads.forEach(function (h) { hr.appendChild(el("th", null, h)); });
  var tb = t.createTBody();
  items.forEach(function (e) {
    var tr = tb.insertRow();
    var w = tr.insertCell();
    w.className = "num faint";
    w.textContent = new Date(e.at).toLocaleString();
    tr.insertCell().textContent = actorWord(e.actor);
    if (withArea) tr.insertCell().textContent = e.category || "—";
    tr.insertCell().textContent = e.action;
    tr.insertCell().textContent = e.target || "—";
    var det = tr.insertCell();
    det.className = "al-detail";
    det.textContent = detailWord(e.detail) || "—";
    det.title = det.textContent;
    var res = tr.insertCell();
    var ok = e.status >= 200 && e.status < 400;
    res.textContent = ok ? "Done" : (e.status === 401 || e.status === 403
      ? "Refused (" + e.status + ")" : "Failed (" + e.status + ")");
    if (!ok) res.className = "al-refused";
  });
  return t;
}

export {
  adminLogTable
};
