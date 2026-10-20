/* Hub activity (#/activity): the team showcase -- totals, the daily
 * chart, people, teams, demo creators and the most-used content.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { debounce, report } from "./util.js";
import { hubPermissions } from "./permissions.js";
import { paintCoverInto } from "./cards.js";
import { closeAdvancedSearch } from "./search.js";

/* ── Hub activity (#/activity), 2026-10-14 ────────────────────────────
 *
 * How PTC uses the Hub, for every PTC employee -- Serge's "healthy
 * competition", and a showcase for the team. Inside the Hub, in its own
 * design (Liwei: "follow the Hub main page, not the Admin page"), like
 * Advanced Search. Data: /api/reports/activity.
 *
 * What it never shows (Liwei, 2026-10-14): a bottom of the list, and
 * anything about partners beyond one anonymous count. Every figure in a
 * chart is also in a table or a label, so nothing hides behind a hover.
 */
var ACT_RANGES = [["30", "30 days"], ["90", "90 days"], ["365", "12 months"]];
var actState = { range: "30", seq: 0 };

function actEl(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function plural(n, word) {
  return n.toLocaleString() + " " + word + (n === 1 ? "" : "s");
}

function breakdown(views, downloads, searches) {
  return [plural(views, "view"), plural(downloads, "download"), plural(searches, "search")]
    .join(" · ").replace(/searchs/g, "searches");
}

function compact(n) {
  n = Number(n || 0);
  return n >= 10000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "K" : n.toLocaleString();
}

function initials(name) {
  var parts = String(name || "?").replace(/[^A-Za-zÀ-ɏ\s.-]/g, " ").trim().split(/[\s.-]+/);
  return ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function buildActivityPage() {
  var page = document.getElementById("hubActivityPage");
  if (page) return page;
  page = document.createElement("div");
  page.className = "video-preview-page";
  page.id = "hubActivityPage";
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to Technical Marketing Hub</button>'
    + '<div class="vp-head"><div>'
    +   '<div class="vp-title">Hub activity</div>'
    +   '<div class="orion-subtle">How PTC uses the Technical Marketing Hub: '
    +   'what is opened, downloaded and searched for, and by how many people.</div>'
    + '</div><div class="hub-act__ranges" role="group" aria-label="Period" id="hubActRanges"></div></div>'
    + '<div class="hub-act" id="hubAct"></div>';
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    history.pushState(null, "", location.pathname + location.search);
    closeActivity();
  });
  var ranges = page.querySelector("#hubActRanges");
  ACT_RANGES.forEach(function (r) {
    var b = actEl("button", null, r[1]);
    b.type = "button";
    b.dataset.range = r[0];
    b.addEventListener("click", function () {
      actState.range = r[0];
      loadActivity();
    });
    ranges.appendChild(b);
  });
  return page;
}

function openActivity() {
  var page = buildActivityPage();
  closeAdvancedSearch();
  document.getElementById("requestViewPage").classList.remove("active");
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  page.classList.add("active");
  markActivityNav(true);
  loadActivity();
}

function closeActivity() {
  var page = document.getElementById("hubActivityPage");
  if (!page || !page.classList.contains("active")) return;
  page.classList.remove("active");
  markActivityNav(false);
  var detail = document.getElementById("videoPreviewPage");
  var adv = document.getElementById("hubAdvancedPage");
  if ((detail && detail.classList.contains("active"))
      || (adv && adv.classList.contains("active"))) return;
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "";
  if (thread) thread.style.display = "";
}

function loadActivity() {
  var page = buildActivityPage();
  page.querySelectorAll("#hubActRanges button").forEach(function (b) {
    b.setAttribute("aria-pressed", String(b.dataset.range === actState.range));
  });
  var host = document.getElementById("hubAct");
  host.classList.add("hub-act--loading");       // keep the frame while refetching
  var seq = ++actState.seq;
  var since = new Date(Date.now() - Number(actState.range) * 86400000).toISOString();
  fetch("/api/reports/activity?since=" + encodeURIComponent(since))
    .then(function (r) {
      if (r.status === 401 || r.status === 403) return { forbidden: true };
      return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status));
    })
    .then(function (d) {
      if (seq !== actState.seq) return;
      host.classList.remove("hub-act--loading");
      if (d.forbidden) {
        host.innerHTML = "";
        host.appendChild(actEl("div", "hub-act__card hub-act__empty",
          "Your account is not in a group that may view Hub activity."));
        return;
      }
      renderActivityPage(d);
    })
    .catch(function (err) {
      host.classList.remove("hub-act--loading");
      report("Could not load Hub activity: " + err.message, true);
    });
}

function periodWord() {
  return actState.range === "365" ? "12 months" : actState.range + " days";
}

function delta(now, before) {
  var el = actEl("div", "hub-act__delta");
  if (before === null || before === undefined) return el;
  var arrow, text, kind;
  if (!before) {
    if (!now) return el;
    kind = "up"; arrow = "↑"; text = "new";
  } else {
    var pct = Math.round((now - before) / before * 100);
    kind = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
    arrow = pct > 0 ? "↑" : pct < 0 ? "↓" : "→";
    text = (pct > 0 ? "+" : "") + pct + "%";
  }
  el.className += " hub-act__delta--" + kind;
  el.appendChild(document.createTextNode(arrow + " " + text + " "));
  el.appendChild(actEl("span", null, "vs previous " + periodWord()));
  return el;
}

/* A 12-point-ish trend in the de-emphasis grey, the latest point in green. */
function sparkline(values) {
  var w = 160, h = 30, n = values.length;
  var svg = '<svg class="hub-act__spark" viewBox="0 0 ' + w + " " + h
    + '" preserveAspectRatio="none" aria-hidden="true">';
  if (n < 2) return svg + "</svg>";
  var max = Math.max.apply(null, values) || 1;
  var pts = values.map(function (v, i) {
    return [(i / (n - 1)) * (w - 4) + 2, h - 3 - (v / max) * (h - 7)];
  });
  var d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join("");
  var last = pts[n - 1];
  return svg + '<path d="' + d + '" fill="none" stroke="var(--orion-text-3)" stroke-width="1.5"'
    + ' stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
    + '<circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1)
    + '" r="3" fill="var(--orion-indigo)" stroke="var(--orion-surface)" stroke-width="1.5"/></svg>';
}

/* Weekly buckets for the sparklines (daily is too spiky at 12 months). */
function buckets(series, pick) {
  var size = series.length > 120 ? 30 : series.length > 40 ? 7 : 3;
  var out = [];
  for (var i = 0; i < series.length; i += size) {
    out.push(series.slice(i, i + size).reduce(function (s, d) { return s + pick(d); }, 0));
  }
  return out;
}

function statCard(label, value, before, values) {
  var c = actEl("div", "hub-act__card");
  c.appendChild(actEl("div", "hub-act__label", label));
  c.appendChild(actEl("div", "hub-act__n", compact(value)));
  c.appendChild(delta(value, before));
  c.insertAdjacentHTML("beforeend", sparkline(values));
  return c;
}

/* People are counted by name only from the day the Hub began recording who
 * (2026-10-16 on production); said while the period reaches back past it. */
function namedNote(day) {
  return "Counted by name since " + new Date(day + "T00:00:00").toLocaleDateString(
    "en-US", { month: "short", day: "numeric", year: "numeric" });
}

function renderActivityPage(d) {
  var host = document.getElementById("hubAct");
  host.innerHTML = "";
  var t = d.totals, prev = d.previous || {};
  var views = t.view + t.preview;
  var series = d.series || [];

  // ── the headline row
  var top = actEl("div", "hub-act__top");
  var hero = actEl("div", "hub-act__card hub-act__hero");
  hero.appendChild(actEl("div", "hub-act__label", "PTC people who used the Hub"));
  hero.appendChild(actEl("div", "hub-act__hero-n", compact(t.active_people)));
  hero.appendChild(delta(t.active_people, d.previous ? prev.active_people : null));
  hero.appendChild(actEl("div", "hub-act__sub", "in the last " + periodWord()));
  if (d.named_since) hero.appendChild(actEl("div", "hub-act__sub", namedNote(d.named_since)));
  top.appendChild(hero);
  top.appendChild(statCard("Views and previews", views,
    d.previous ? (prev.view || 0) + (prev.preview || 0) : null,
    buckets(series, function (x) { return x.view + x.preview; })));
  top.appendChild(statCard("Downloads", t.download, d.previous ? prev.download : null,
    buckets(series, function (x) { return x.download; })));
  top.appendChild(statCard("Searches", t.search, d.previous ? prev.search : null,
    buckets(series, function (x) { return x.search; })));
  host.appendChild(top);

  // ── daily activity and the leaderboard
  var mid = actEl("div", "hub-act__mid");
  var chartCard = actEl("div", "hub-act__card");
  chartCard.appendChild(actEl("h3", null, "Daily activity"));
  chartCard.appendChild(actEl("div", "hub-act__sub",
    "Views, previews, downloads and searches per day, everyone included"));
  chartCard.appendChild(dailyChart(series));
  chartCard.appendChild(dailyTable(series));
  mid.appendChild(chartCard);

  var lbCard = actEl("div", "hub-act__card");
  lbCard.appendChild(actEl("h3", null, "Most active people"));
  lbCard.appendChild(actEl("div", "hub-act__sub", "Top " + d.top + " PTC people, last "
    + periodWord() + (d.named_since ? ". " + namedNote(d.named_since) : "")));
  lbCard.appendChild(leaderboard(d.people));
  mid.appendChild(lbCard);
  host.appendChild(mid);

  // ── teams and content
  var teamCard = actEl("div", "hub-act__card");
  teamCard.appendChild(actEl("h3", null, "Teams"));
  teamCard.appendChild(actEl("div", "hub-act__sub",
    "How many of each team used the Hub, and what they did"));
  teamCard.appendChild(teams(d.teams));

  var contentCard = actEl("div", "hub-act__card");
  contentCard.appendChild(actEl("h3", null, "Most used content"));
  contentCard.appendChild(actEl("div", "hub-act__sub", "Opened and downloaded most, last "
    + periodWord()));
  contentCard.appendChild(topContent(d.content));

  var creatorCard = actEl("div", "hub-act__card");
  creatorCard.appendChild(actEl("h3", null, "Whose demos were used most"));
  creatorCard.appendChild(actEl("div", "hub-act__sub", "Creators ranked by how much their "
    + "demos were opened and downloaded, last " + periodWord() + ". Only demos used in "
    + "this period count."));
  creatorCard.appendChild(creatorBoard(d.creators || [], d.creators_known !== false));

  var bottom = actEl("div", "hub-act__mid");
  bottom.appendChild(contentCard);
  var side = actEl("div");
  side.style.cssText = "display:grid;gap:16px;align-content:start";
  side.appendChild(creatorCard);
  side.appendChild(teamCard);
  bottom.appendChild(side);
  host.appendChild(bottom);

  host.appendChild(actEl("div", "hub-act__foot",
    "Only PTC people are ranked, and only the top " + d.top + " are shown."
    + (d.external_not_ranked ? " " + d.external_not_ranked.toLocaleString()
      + " actions by partner accounts in this period are counted anonymously and not ranked." : "")
    + (t.anonymous ? " " + t.anonymous.toLocaleString()
      + " earlier actions were recorded without a name and are not ranked either." : "")
    + " Teams are the groups set up by the Hub's administrators."
    + " A demo's creator is whoever created its main video in SharePoint"
    + (d.unattributed_uses ? "; " + d.unattributed_uses.toLocaleString()
      + " uses were of demos with no recorded creator (migrated videos, Consensus)." : ".")));
}

/* One series (actions per day): a 2px line over a 10% wash, hairline
 * grid, a crosshair that snaps to the day, and a readout per day. */
function dailyChart(series) {
  var wrap = actEl("div", "hub-act__chart");
  if (!series.length) {
    wrap.appendChild(actEl("div", "hub-act__empty", "No activity in this period yet."));
    return wrap;
  }
  // Drawn at the card's real width (not a scaled viewBox, which shrank the
  // axis text to nothing on a narrow screen), once it is on the page, and
  // again when the window is resized.
  requestAnimationFrame(function () { drawDaily(wrap, series); });
  if (!window.hubActResize) {
    window.hubActResize = debounce(function () {
      var w = document.querySelector("#hubActivityPage.active .hub-act__chart");
      if (w && w.hubSeries) drawDaily(w, w.hubSeries);
    }, 150);
    window.addEventListener("resize", window.hubActResize);
  }
  wrap.hubSeries = series;
  return wrap;
}

function drawDaily(wrap, series) {
  wrap.innerHTML = "";
  var W = Math.max(280, wrap.clientWidth || 600), H = 240, L = 40, R = 12, T = 12, B = 26;
  var total = function (x) { return x.view + x.preview + x.download + x.search; };
  var vals = series.map(total);
  var max = Math.max.apply(null, vals);
  var step = max <= 5 ? 1 : Math.pow(10, Math.floor(Math.log10(max)));
  if (max / step > 5) step *= 2;
  var top = Math.max(step, Math.ceil(max / step) * step);
  var n = series.length;
  var x = function (i) { return L + (n === 1 ? (W - L - R) / 2 : i / (n - 1) * (W - L - R)); };
  var y = function (v) { return T + (1 - v / top) * (H - T - B); };
  var ns = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Actions per day; figures in the table below");
  var g = '<g class="grid">';
  for (var v = 0; v <= top; v += step) {
    g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v)
      + '" vector-effect="non-scaling-stroke"/>'
      + '<text x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">'
      + v.toLocaleString() + "</text>";
  }
  g += "</g>";
  var line = vals.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }).join("");
  var area = line + "L" + x(n - 1).toFixed(1) + " " + y(0) + "L" + x(0).toFixed(1) + " " + y(0) + "Z";
  var fmt = function (iso, long) {
    return new Date(iso + "T00:00:00").toLocaleDateString(undefined,
      long ? { weekday: "short", month: "short", day: "numeric" } : { month: "short", day: "numeric" });
  };
  var ticks = [0, Math.floor((n - 1) / 2), n - 1].filter(function (i, k, a) { return a.indexOf(i) === k; });
  var labels = ticks.map(function (i) {
    return '<text x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="'
      + (i === 0 ? "start" : i === n - 1 ? "end" : "middle") + '">' + fmt(series[i].date) + "</text>";
  }).join("");
  var peak = vals.indexOf(max);
  svg.innerHTML = g
    + '<path d="' + area + '" fill="var(--orion-indigo)" fill-opacity=".1"/>'
    + '<path d="' + line + '" fill="none" stroke="var(--orion-indigo)" stroke-width="2"'
    + ' stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
    + labels
    + '<line class="xh" y1="' + T + '" y2="' + (H - B) + '" stroke="var(--orion-border-md)"'
    + ' stroke-width="1" vector-effect="non-scaling-stroke" visibility="hidden"/>';
  wrap.appendChild(svg);

  // Dots in HTML so they stay round however the SVG stretches.
  function dot(i, cls) {
    var d = actEl("span", cls);
    d.style.cssText = "position:absolute;width:9px;height:9px;border-radius:50%;"
      + "background:var(--orion-indigo);border:2px solid var(--orion-surface);"
      + "transform:translate(-50%,-50%);pointer-events:none;left:" + (x(i) / W * 100) + "%;"
      + "top:" + (y(vals[i]) / H * 240) + "px";
    return d;
  }
  if (max > 0) {
    wrap.appendChild(dot(peak, "peak"));
    var peakLabel = actEl("span", null, "Peak " + max.toLocaleString());
    peakLabel.style.cssText = "position:absolute;font-size:11px;font-weight:600;"
      + "color:var(--orion-text-2);transform:translate(-50%,-150%);pointer-events:none;"
      + "left:" + (x(peak) / W * 100) + "%;top:" + (y(max) / H * 240) + "px";
    wrap.appendChild(peakLabel);
  }
  var hover = dot(0, "hover");
  hover.style.display = "none";
  wrap.appendChild(hover);
  var tip = actEl("div", "hub-act__tip");
  tip.style.display = "none";
  wrap.appendChild(tip);
  var xh = svg.querySelector(".xh");

  function show(i) {
    var s = series[i];
    var px = x(i) / W * 100;
    xh.setAttribute("x1", x(i));
    xh.setAttribute("x2", x(i));
    xh.setAttribute("visibility", "visible");
    hover.style.display = "";
    hover.style.left = px + "%";
    hover.style.top = (y(vals[i]) / H * 240) + "px";
    tip.innerHTML = "";
    tip.appendChild(actEl("div", null, fmt(s.date, true)));
    var b = actEl("b");
    b.appendChild(actEl("span", "k"));
    b.appendChild(document.createTextNode(vals[i].toLocaleString() + " actions"));
    tip.appendChild(b);
    tip.appendChild(actEl("div", null, breakdown(s.view + s.preview, s.download, s.search)));
    tip.appendChild(actEl("div", null, s.people + " PTC " + (s.people === 1 ? "person" : "people")));
    tip.style.display = "";
    tip.style.left = Math.min(Math.max(px, 12), 88) + "%";
    var py = y(vals[i]) / H * 240;
    tip.style.top = py + "px";
    // Near the top it would cover the card's title: show it below instead.
    tip.style.transform = py < 90 ? "translate(-50%, 14px)" : "";
  }
  function hide() {
    xh.setAttribute("visibility", "hidden");
    hover.style.display = "none";
    tip.style.display = "none";
  }
  svg.addEventListener("pointermove", function (e) {
    var box = svg.getBoundingClientRect();
    var fx = (e.clientX - box.left) / box.width * W;
    var i = Math.round((fx - L) / (W - L - R) * (n - 1));
    show(Math.max(0, Math.min(n - 1, i)));
  });
  svg.addEventListener("pointerleave", hide);
  svg.setAttribute("tabindex", "0");
  var focusAt = n - 1;
  svg.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") focusAt = Math.max(0, focusAt - 1);
    else if (e.key === "ArrowRight") focusAt = Math.min(n - 1, focusAt + 1);
    else return;
    e.preventDefault();
    show(focusAt);
  });
  svg.addEventListener("focus", function () { show(focusAt); });
  svg.addEventListener("blur", hide);
}

function dailyTable(series) {
  var det = actEl("details");
  det.appendChild(actEl("summary", null, "Show the figures as a table"));
  var tbl = actEl("table");
  var hr = tbl.createTHead().insertRow();
  ["Day", "Views", "Downloads", "Searches", "PTC people"].forEach(function (h, i) {
    hr.appendChild(actEl("th", i ? "r" : null, h));
  });
  var tb = tbl.createTBody();
  series.slice().reverse().forEach(function (s) {
    var tr = tb.insertRow();
    tr.insertCell().textContent = s.date;
    [s.view + s.preview, s.download, s.search, s.people].forEach(function (v) {
      var c = tr.insertCell();
      c.className = "r";
      c.textContent = v;
    });
  });
  det.appendChild(tbl);
  return det;
}

function leaderboard(people) {
  if (!people.length) return actEl("div", "hub-act__empty", "Nobody yet in this period.");
  var max = people[0].total || 1;
  var ol = actEl("ol", "hub-act__lb");
  people.forEach(function (p) {
    var li = actEl("li");
    li.appendChild(actEl("span", "hub-act__rank" + (p.rank <= 3 ? " hub-act__rank--" + p.rank : ""), p.rank));
    li.appendChild(actEl("span", "hub-act__avatar", initials(p.name)));
    var who = actEl("div", "hub-act__who");
    var name = actEl("b", null, p.name);
    name.title = p.user;
    who.appendChild(name);
    who.appendChild(actEl("span", null, breakdown(p.view + p.preview, p.download, p.search)));
    li.appendChild(who);
    var bar = actEl("div", "hub-act__bar");
    var track = actEl("div", "hub-act__track");
    var fill = actEl("div", "hub-act__fill");
    fill.style.width = Math.max(3, p.total / max * 100) + "%";
    track.appendChild(fill);
    bar.appendChild(track);
    bar.appendChild(actEl("span", "hub-act__val", compact(p.total)));
    li.appendChild(bar);
    ol.appendChild(li);
  });
  return ol;
}

/* SharePoint writes "Last, First"; people read "First Last". */
function personName(raw) {
  var m = /^\s*([^,]+),\s*(.+)$/.exec(raw || "");
  return m ? m[2] + " " + m[1] : (raw || "");
}

function creatorBoard(list, known) {
  if (!known) return actEl("div", "hub-act__empty",
    "No demo has a creator yet. Creators are read from SharePoint by a full sync "
    + "(Admin, Sync); this fills in after the next one.");
  if (!list.length) return actEl("div", "hub-act__empty",
    "No demo with a known creator was used in this period.");
  var max = list[0].total || 1;
  var ol = actEl("ol", "hub-act__lb");
  list.forEach(function (c) {
    var li = actEl("li");
    li.appendChild(actEl("span", "hub-act__rank" + (c.rank <= 3 ? " hub-act__rank--" + c.rank : ""), c.rank));
    var name = personName(c.creator);
    li.appendChild(actEl("span", "hub-act__avatar", initials(name)));
    var who = actEl("div", "hub-act__who");
    who.appendChild(actEl("b", null, name));
    who.appendChild(actEl("span", null, plural(c.demos, "demo") + " used · "
      + plural(c.views, "view") + " · " + plural(c.downloads, "download")
      + (c.people ? " · " + c.people + (c.people === 1 ? " person" : " people") : "")));
    li.appendChild(who);
    var bar = actEl("div", "hub-act__bar");
    var track = actEl("div", "hub-act__track");
    var fill = actEl("div", "hub-act__fill");
    fill.style.width = Math.max(3, c.total / max * 100) + "%";
    track.appendChild(fill);
    bar.appendChild(track);
    bar.appendChild(actEl("span", "hub-act__val", compact(c.total)));
    li.appendChild(bar);
    ol.appendChild(li);
  });
  return ol;
}

function teams(list) {
  var box = actEl("div");
  if (!list.length) {
    box.appendChild(actEl("div", "hub-act__empty",
      "No teams yet. Teams are the groups the Hub's administrators set up."));
    return box;
  }
  list.forEach(function (t) {
    var row = actEl("div", "hub-act__team");
    var head = actEl("div", "hub-act__team-head");
    head.appendChild(actEl("b", null, t.team));
    head.appendChild(actEl("span", null, t.active + " of " + t.members + " active"));
    row.appendChild(head);
    var meter = actEl("div", "hub-act__meter");
    var fill = actEl("i");
    fill.style.width = (t.members ? t.active / t.members * 100 : 0) + "%";
    meter.appendChild(fill);
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", t.active + " of " + t.members + " members active");
    row.appendChild(meter);
    row.appendChild(actEl("div", "hub-act__team-foot",
      breakdown(t.view + t.preview, t.download, t.search)));
    box.appendChild(row);
  });
  return box;
}

function topContent(items) {
  if (!items.length) return actEl("div", "hub-act__empty", "Nothing opened yet in this period.");
  var grid = actEl("div", "hub-act__content");
  items.forEach(function (c, i) {
    var a = actEl("a", "hub-act__item");
    a.href = "#/asset/" + encodeURIComponent(c.asset_id);
    var thumb = actEl("div", "hub-act__thumb");
    // An outside picture, or the Hub's own address for a SharePoint-hosted
    // one (/api/assets/{id}/thumbnail, 2026-10-20).
    var safe = c.thumbnail_url && /^(https?:|\/api\/assets\/)/i.test(c.thumbnail_url)
      ? c.thumbnail_url : null;
    if (safe) thumb.style.backgroundImage = 'url("' + safe.replace(/"/g, "%22") + '")';
    // The cards' own rule: a picture only if it loads (SharePoint-hosted
    // ones need a SharePoint sign-in), else the generated cover.
    try {
      paintCoverInto(thumb, { id: c.asset_id, title: c.title, type: c.type,
                             products: c.products || [], thumbnail_url: safe });
    } catch (e) { /* the grey ground is fine */ }
    thumb.appendChild(actEl("span", "hub-act__num", i + 1));
    a.appendChild(thumb);
    var body = actEl("div", "hub-act__item-body");
    body.appendChild(actEl("div", "hub-act__item-title", c.title));
    body.appendChild(actEl("div", "hub-act__item-meta", plural(c.views, "view") + " · "
      + plural(c.downloads, "download")
      + (c.people ? " · " + c.people + (c.people === 1 ? " person" : " people") : "")));
    a.appendChild(body);
    grid.appendChild(a);
  });
  return grid;
}

/* The way in: "Hub activity" in the sidebar's Discover list, for people
 * who may see it. */
function addActivityNav() {
  hubPermissions.then(function (granted) {
    if (granted.indexOf("view_reports") < 0 || document.getElementById("navActivity")) return;
    var home = document.getElementById("navHome");
    if (!home) return;
    var items = Array.prototype.slice.call(home.parentNode.querySelectorAll(".orion-navitem"));
    var after = home;
    for (var i = items.indexOf(home) + 1; i < items.length; i++) {
      if (items[i].previousElementSibling !== after) break;
      after = items[i];
    }
    var item = document.createElement("div");
    item.className = "orion-navitem";
    item.id = "navActivity";
    item.innerHTML = '<span class="label"><svg class="orion-ico orion-ico--sm">'
      + '<use href="#i-trend"/></svg> Hub activity</span>';
    item.addEventListener("click", function () { location.hash = "#/activity"; });
    after.insertAdjacentElement("afterend", item);
    // Opened straight from a link: the view came up before this entry did.
    if (location.hash === "#/activity") markActivityNav(true);
  });
}

function markActivityNav(on) {
  var item = document.getElementById("navActivity");
  if (!item) return;
  item.classList.toggle("orion-navitem--active", on);
  if (on) document.querySelectorAll(".orion-navitem--active").forEach(function (n) {
    if (n !== item) n.classList.remove("orion-navitem--active");
  });
}

export {
  addActivityNav, closeActivity, openActivity
};
