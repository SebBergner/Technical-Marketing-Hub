/* Hub activity (2026-10-14). Everything on the page comes from
 * /api/reports/activity, which ranks PTC people only, lists no bottom of the
 * table, and counts partner activity without naming anyone. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var RANGES = [
    { id: "30", label: "30 days" },
    { id: "90", label: "90 days" },
    { id: "365", label: "12 months" }
  ];
  var current = "30";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function table(headers, rows, right) {
    if (!rows.length) return el("div", "faint", "Nothing yet in this period.");
    var t = el("table");
    var hr = t.createTHead().insertRow();
    headers.forEach(function (h, i) { hr.appendChild(el("th", right(i) ? "r" : null, h)); });
    var tb = t.createTBody();
    rows.forEach(function (cells) {
      var tr = tb.insertRow();
      cells.forEach(function (c, i) {
        var td = tr.insertCell();
        if (right(i)) td.className = "r num";
        if (c instanceof Node) td.appendChild(c); else td.textContent = c;
      });
    });
    return t;
  }

  function tile(host, n, label) {
    var t = el("div", "tile");
    t.appendChild(el("div", "tile__n num", Number(n || 0).toLocaleString()));
    t.appendChild(el("div", "tile__l", label));
    host.appendChild(t);
  }

  function renderRanges() {
    var host = $("ranges");
    host.innerHTML = "";
    RANGES.forEach(function (r) {
      var b = el("button", null, r.label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(r.id === current));
      b.addEventListener("click", function () { current = r.id; renderRanges(); load(); });
      host.appendChild(b);
    });
  }

  function load() {
    var since = new Date(Date.now() - Number(current) * 86400000).toISOString();
    fetch("/api/reports/activity?since=" + encodeURIComponent(since))
      .then(function (r) {
        if (r.status === 403 || r.status === 401) { $("noAccess").hidden = false; return null; }
        return r.ok ? r.json() : null;
      })
      .then(function (d) { if (d) render(d); });
  }

  function render(d) {
    $("content").hidden = false;
    var tiles = $("tiles");
    tiles.innerHTML = "";
    tile(tiles, d.totals.active_people, "PTC people active");
    tile(tiles, d.totals.view + d.totals.preview, "Views and previews");
    tile(tiles, d.totals.download, "Downloads");
    tile(tiles, d.totals.search, "Searches");

    $("peopleTitle").textContent = "Most active people · top " + d.top;
    var people = $("people");
    people.innerHTML = "";
    people.appendChild(table(["#", "Name", "Views", "Downloads", "Searches"],
      d.people.map(function (p) {
        var rank = el("span", "rank" + (p.rank === 1 ? " rank--1" : ""), p.rank);
        var name = el("span", null, p.name);
        name.title = p.user;
        return [rank, name, p.view + p.preview, p.download, p.search];
      }), function (i) { return i >= 2; }));

    var teams = $("teams");
    teams.innerHTML = "";
    teams.appendChild(d.teams.length
      ? table(["Team", "Active", "Views", "Downloads"], d.teams.map(function (t) {
        return [t.team, t.active + " of " + t.members, t.view + t.preview, t.download];
      }), function (i) { return i >= 1; })
      : el("div", "faint", "No teams yet: teams are the groups set up on the Admin page."));

    var content = $("topContent");
    content.innerHTML = "";
    content.appendChild(table(["Demo", "Views", "Downloads", "People"],
      d.content.map(function (c) {
        var a = el("a", null, c.title);
        a.href = "/#/asset/" + encodeURIComponent(c.asset_id);
        return [a, c.views, c.downloads, c.people];
      }), function (i) { return i >= 1; }));

    $("footnote").textContent = "Only PTC people are ranked, and only the top "
      + d.top + " are shown. "
      + (d.external_not_ranked
        ? d.external_not_ranked.toLocaleString() + " actions by partner accounts in this "
          + "period are counted anonymously and not ranked. "
        : "")
      + (d.totals.anonymous
        ? d.totals.anonymous.toLocaleString() + " older actions carry no name and are not "
          + "ranked either. "
        : "")
      + "Teams are the groups set up on the Admin page.";
  }

  renderRanges();
  load();
})();
