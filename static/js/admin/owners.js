/* The Report owners tab (A2, Liwei 2026-10-23/28): who is told about the
 * reports on each segment's demos, and how many each segment has had.
 *
 * One card per segment (CAD, PLM, ALM, SLM, SCO, General). Owners have a
 * name, a PTC address and a Notify switch; the addresses of those with
 * Notify on are written into each report's Hub Tasks row (NotifyTo), which
 * the Power Automate flow mails. A segment with nobody notified hands its
 * reports to General, and says so in red. Changing owners needs Manage
 * users & groups; every change is in the Admin log.
 *
 * Part of the Admin page's script; static/js/admin/main.js loads it. */

import { $, demoLink, el, openSheet, session, when } from "./util.js";
import { loadChanges } from "./access.js";

function canManage() {
  return (session.permissions || []).indexOf("manage_users") >= 0;
}

function loadOwners() {
  loadChanges("roChanges", "Reports");
  return fetch("/api/admin/report-owners")
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
    .then(render)
    .catch(function (err) { $("roBody").textContent = "Could not load: " + err.message; });
}

function render(d) {
  var host = $("roBody");
  host.innerHTML = "";
  $("roIntro").textContent = canManage() ? ""
    : "You can see the owners; changing them needs Manage users & groups.";
  d.segments.forEach(function (s) { host.appendChild(segmentCard(s, d.general)); });
}

function segmentCard(s, general) {
  var card = el("div", "card ro-card");
  var head = el("div", "ro-head");
  head.appendChild(el("h2", null, s.segment === general ? "General" : s.segment));
  var nums = el("div", "ro-nums");
  [["open", "open"], ["total", "total"], ["last_30", "last 30 days"]].forEach(function (n) {
    var b = el("button", "ro-num");
    b.type = "button";
    b.appendChild(el("b", null, s[n[0]]));
    b.appendChild(document.createTextNode(" " + n[1]));
    b.title = "List " + s.segment + "'s reports";
    b.disabled = !s.total;
    b.addEventListener("click", function () { showReports(s.segment); });
    nums.appendChild(b);
  });
  head.appendChild(nums);
  card.appendChild(head);
  card.appendChild(el("p", "faint ro-what", s.segment === general
    ? "Get help, demos in no listed segment (IoT, none), and any segment with nobody notified."
    : "Reports on " + s.segment + " demos."));
  if (!s.notified) {
    card.appendChild(el("div", "ro-alert", s.segment === general
      ? "Nobody is notified: General's reports reach nobody until someone here has Notify on."
      : "Nobody is notified: " + s.segment + "'s reports go to General."));
  }

  var people = s.owners.map(function (o) { return { name: o.name, email: o.email, notify: o.notify }; });
  var status = el("span", "promo-status faint");
  var list = el("div", "ro-list");
  card.appendChild(list);

  function save() {
    status.textContent = "Saving…";
    status.className = "promo-status faint";
    return fetch("/api/admin/report-owners/" + encodeURIComponent(s.segment), {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owners: people })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) {
        if (!r.ok) throw new Error(b.detail || ("HTTP " + r.status));
        return b;
      });
    }).then(function () {
      status.textContent = "Saved";
      loadOwners();
    }).catch(function (err) {
      status.textContent = err.message;
      status.className = "promo-status err";
      people = s.owners.map(function (o) { return { name: o.name, email: o.email, notify: o.notify }; });
      draw();
      throw err;
    });
  }

  function draw() {
    list.innerHTML = "";
    if (!people.length) list.appendChild(el("div", "faint ro-none", "No owners yet."));
    people.forEach(function (p, i) {
      var row = el("div", "ro-row");
      var who = el("div", "ro-who");
      who.appendChild(el("div", "ro-name", p.name));
      var mail = el("a", "ro-mail", p.email);
      mail.href = "mailto:" + p.email;
      who.appendChild(mail);
      row.appendChild(who);
      var toggle = el("label", "switch");
      var box = el("input");
      box.type = "checkbox";
      box.checked = !!p.notify;
      box.disabled = !canManage();
      box.setAttribute("aria-label", "Notify " + p.name);
      toggle.appendChild(box);
      toggle.appendChild(el("span", "switch__track"));
      toggle.appendChild(el("span", "switch__label", p.notify ? "Notify on" : "Notify off"));
      box.addEventListener("change", function () {
        p.notify = box.checked;
        box.disabled = true;
        save().catch(function () { /* said in the status */ });
      });
      row.appendChild(toggle);
      if (canManage()) {
        var rm = el("button", "btn-danger", "Remove");
        rm.type = "button";
        rm.addEventListener("click", function () {
          people.splice(i, 1);
          rm.disabled = true;
          save().catch(function () { /* said in the status */ });
        });
        row.appendChild(rm);
      }
      list.appendChild(row);
    });
  }
  draw();

  if (canManage()) {
    var add = el("form", "ro-add");
    var name = el("input");
    name.placeholder = "Name";
    name.setAttribute("aria-label", "Owner's name");
    var email = el("input");
    email.type = "email";
    email.placeholder = "name@ptc.com";
    email.setAttribute("aria-label", "Owner's email");
    var go = el("button", "btn-primary btn-small", "Add owner");
    go.type = "submit";
    add.appendChild(name);
    add.appendChild(email);
    add.appendChild(go);
    add.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!email.value.trim()) { email.focus(); return; }
      people.push({ name: name.value.trim(), email: email.value.trim(), notify: true });
      go.disabled = true;
      save().catch(function () { go.disabled = false; });
    });
    card.appendChild(add);
  }
  card.appendChild(status);
  return card;
}

var STATUS_PILL = { Open: "pill--warn", Done: "pill--ok" };

function showReports(segment) {
  var body = openSheet(segment + " reports", "Newest first. The status is changed in the Hub Tasks list.");
  body.textContent = "Loading…";
  fetch("/api/admin/report-owners/" + encodeURIComponent(segment) + "/reports")
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
    .then(function (d) {
      body.innerHTML = "";
      var table = el("table");
      table.innerHTML = "<thead><tr><th>Sent</th><th>About</th><th>Category</th>"
        + "<th>By</th><th>Status</th></tr></thead>";
      var tb = el("tbody");
      d.items.forEach(function (r) {
        var tr = el("tr");
        tr.appendChild(el("td", null, when(r.at)));
        var about = el("td");
        about.appendChild(r.asset_id ? demoLink(r.asset_id, r.title) : el("b", null, "Get help"));
        about.appendChild(el("div", "faint", r.details));
        if (r.fell_back) about.appendChild(el("div", "faint", "Sent to General: nobody notified."));
        tr.appendChild(about);
        tr.appendChild(el("td", null, r.category));
        tr.appendChild(el("td", null, r.reported_by || "partner"));
        var st = el("td");
        st.appendChild(el("span", "pill " + (STATUS_PILL[r.status] || "pill--off"), r.status));
        tr.appendChild(st);
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      body.appendChild(table);
    })
    .catch(function (err) { body.textContent = "Could not load: " + err.message; });
}

export { loadOwners };
