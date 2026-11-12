/* Content health -> Searches (2026-11-11; redesigned 2026-11-12 on the
 * pattern of search-analytics products: Algolia, Search Console, Coveo).
 *
 * Top to bottom: four figures against the period before; how searches
 * ended, over time; what needs doing -- not in the Hub, near misses, thin
 * results, found but nothing opened; what people search for most; what is
 * rising; every search, folded away. The numbers are worked out on the
 * server (backend/services/search_insights.py), which says how; counts of
 * people, never who.
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, delta, el, tile } from "../admin/util.js";

var RANGES = [["7d", "7 days", 7], ["30d", "30 days", 30], ["90d", "90 days", 90],
              ["all", "All time", null]];
var range = "30d";

var SERIES = [
  { key: "opened", label: "Opened a result", color: "#2a78d6" },
  { key: "not_opened", label: "Found, nothing opened", color: "#9cc1ee" },
  { key: "unknown", label: "Found (who was not recorded)", color: "#c9c7bf" },
  { key: "nothing", label: "Found nothing", color: "#e34948" }
];

function days() {
  return RANGES.filter(function (x) { return x[0] === range; })[0][2];
}


function renderRanges() {
  var host = $("srRanges");
  host.innerHTML = "";
  RANGES.forEach(function (r) {
    var b = el("button", null, r[1]);
    b.type = "button";
    b.setAttribute("aria-pressed", String(r[0] === range));
    b.addEventListener("click", function () { range = r[0]; loadSearches(); });
    host.appendChild(b);
  });
}

function pct(n, of) {
  return of ? Math.round(n / of * 100) + "%" : "—";
}

/* A share against the period before, in points ("+3 pts"), and a rise
 * in a bad share shown red, not green. */
function pointsDelta(now, before) {
  if (before === null || before === undefined) return null;
  var diff = now - before;
  if (!diff) return { text: "level", dir: "flat" };
  return { text: (diff > 0 ? "+" : "") + diff + " pts", dir: diff > 0 ? "down" : "up" };
}

function renderTiles(d) {
  var host = $("srTiles");
  host.innerHTML = "";
  var t = d.totals, p = d.previous;
  var vs = p ? "vs the " + days() + " days before" : null;
  tile(host, t.searches, "Searches", (t.typing ? t.typing + " typing left out" : vs),
       p && delta(t.searches, p.searches));
  // Before mid-October searches did not record who searched: no people to
  // compare with, which is not the same as nobody.
  var peopleKnown = p && (p.people || !p.searches);
  tile(host, t.people, "People searching", peopleKnown ? vs : "no earlier record of who",
       peopleKnown && delta(t.people, p.people));
  var nothing = t.searches ? Math.round(t.no_results / t.searches * 100) : 0;
  var before = p && p.searches ? Math.round(p.no_results / p.searches * 100) : null;
  tile(host, pct(t.no_results, t.searches), "Found nothing",
       t.no_results + " of " + t.searches, p && pointsDelta(nothing, before));
  var unopened = t.opened_known
    ? Math.round((t.opened_known - t.opened) / t.opened_known * 100) : 0;
  var beforeU = p && p.opened_known
    ? Math.round((p.opened_known - p.opened) / p.opened_known * 100) : null;
  tile(host, pct(t.opened_known - t.opened, t.opened_known), "Found, nothing opened",
       "within " + d.open_minutes + " min, where we know who searched",
       p && pointsDelta(unopened, beforeU));
}

function renderChart(d) {
  var host = $("srChart");
  host.innerHTML = "";
  var buckets = d.over_time.buckets;
  if (!buckets.length) {
    host.appendChild(el("p", "muted", "No searches in this period."));
    return;
  }
  var W = 900, H = 170, padL = 34, padB = 22, padT = 8;
  var max = 1;
  buckets.forEach(function (b) {
    max = Math.max(max, SERIES.reduce(function (s, x) { return s + (b[x.key] || 0); }, 0));
  });
  var NS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("class", "chart sr-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Searches per " + d.over_time.by + ", by how they ended");
  function add(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text !== undefined) n.textContent = text;
    svg.appendChild(n);
    return n;
  }
  [0, max].forEach(function (v) {
    var y = padT + (H - padT - padB) * (1 - v / max);
    add("line", { x1: padL, x2: W, y1: y, y2: y, stroke: "#dedcd4", "stroke-width": 1 });
    add("text", { x: 4, y: y + 4, fill: "#898781", "font-size": 10 }, String(v));
  });
  var band = (W - padL) / buckets.length;
  var barW = Math.min(28, band * 0.6);
  var every = Math.max(1, Math.ceil(buckets.length / 10));
  buckets.forEach(function (b, i) {
    var y = H - padB;
    var x = padL + i * band + (band - barW) / 2;
    var tip = [(d.over_time.by === "week" ? "Week of " : "") + b.start];
    SERIES.forEach(function (s) {
      var v = b[s.key] || 0;
      if (v) tip.push(s.label + ": " + v);
      if (!v) return;
      var h = (H - padT - padB) * (v / max);
      y -= h;
      add("rect", { x: x, y: y, width: barW, height: Math.max(0.5, h - 1.5), fill: s.color,
                    rx: 2 });
    });
    // One invisible column per bar carries the tooltip, so a thin segment
    // need not be hit exactly.
    var hit = add("rect", { x: padL + i * band, y: padT, width: band,
                            height: H - padT - padB, fill: "transparent" });
    var title = document.createElementNS(NS, "title");
    title.textContent = tip.join("\n");
    hit.appendChild(title);
    if (i % every === 0) {
      add("text", { x: x + barW / 2, y: H - 6, fill: "#898781", "font-size": 10,
                    "text-anchor": "middle" }, b.start.slice(5));
    }
  });
  host.appendChild(svg);
  var legend = el("div", "chart-legend");
  SERIES.forEach(function (s) {
    if (s.key === "unknown" && !buckets.some(function (b) { return b.unknown; })) return;
    var item = el("span");
    var sw = el("span", "swatch");
    sw.style.background = s.color;
    item.appendChild(sw);
    item.appendChild(document.createTextNode(s.label));
    legend.appendChild(item);
  });
  host.appendChild(legend);
}

function tryLink(q, text) {
  var a = el("a", null, text || q);
  a.href = "/#/search/" + encodeURIComponent(q);
  a.target = "_blank";
  a.rel = "noopener";
  a.title = "Search the Hub for this now";
  return a;
}

function meta(r) {
  return [r.people + (r.people === 1 ? " person" : " people"),
          r.times + (r.times === 1 ? " search" : " searches"),
          r.last_at ? "last " + r.last_at : null].filter(Boolean).join(" · ");
}

/* How many rows a "what needs doing" card shows before "Show N more". */
var SHOWN = 8;

/* One of the four "what needs doing" cards. */
function problemCard(host, tone, title, why, rows, line, empty) {
  var c = el("div", "card sr-card");
  var head = el("div", "card-head");
  var h = el("h2");
  h.appendChild(el("span", "sr-dot sr-dot--" + tone));
  h.appendChild(document.createTextNode(title));
  head.appendChild(h);
  head.appendChild(el("span", "faint num", String(rows.length)));
  c.appendChild(head);
  c.appendChild(el("p", "muted sr-why", why));
  if (!rows.length) {
    c.appendChild(el("div", "faint sr-empty", empty));
  } else {
    var list = el("ul", "sr-list");
    rows.forEach(function (r, i) {
      var li = el("li");
      line(li, r);
      if (i >= SHOWN) li.hidden = true;
      list.appendChild(li);
    });
    c.appendChild(list);
    if (rows.length > SHOWN) {
      // The rest open in place (Liwei, 2026-11-12), and close again.
      var more = el("button", "sr-more", "Show " + (rows.length - SHOWN) + " more");
      more.type = "button";
      more.setAttribute("aria-expanded", "false");
      more.addEventListener("click", function () {
        var open = more.getAttribute("aria-expanded") !== "true";
        Array.prototype.forEach.call(list.children, function (li, i) {
          if (i >= SHOWN) li.hidden = !open;
        });
        more.setAttribute("aria-expanded", String(open));
        more.textContent = open ? "Show fewer" : "Show " + (rows.length - SHOWN) + " more";
      });
      c.appendChild(more);
    }
  }
  host.appendChild(c);
}

function wordWithFilters(li, r) {
  var top = el("div", "sr-q");
  top.appendChild(tryLink(r.q));
  if (r.filters) top.appendChild(el("span", "pill sr-filter", r.filters));
  li.appendChild(top);
}

function renderProblems(d) {
  var host = $("srProblems");
  host.innerHTML = "";
  problemCard(host, "red", "Not in the Hub",
    "Still finds nothing today. Worth a new demo, or a request to the team.",
    d.gaps, function (li, r) {
      wordWithFilters(li, r);
      var m = el("div", "sr-meta", meta(r));
      if (!r.filters) {
        var req = el("a", "sr-act", "Request it");
        req.href = "/#/request";
        req.target = "_blank";
        req.rel = "noopener";
        m.appendChild(req);
      }
      li.appendChild(m);
    }, "Nothing: every search finds something today.");
  problemCard(host, "amber", "Near misses",
    "The Hub has it under another word: cut short or misspelt. Add the word as a keyword, "
    + "or teach the search to forgive it.",
    d.near_misses, function (li, r) {
      var top = el("div", "sr-q");
      top.appendChild(tryLink(r.q));
      top.appendChild(el("span", "faint", " → "));
      top.appendChild(tryLink(r.suggestion, r.suggestion + " (" + r.finds_suggestion + ")"));
      li.appendChild(top);
      li.appendChild(el("div", "sr-meta", meta(r)));
    }, "None.");
  problemCard(host, "amber", "Thin results",
    "Finds only 1–" + d.few_results_max + " today. A better title, description or tag may "
    + "bring the rest in; or there really is little.",
    d.thin, function (li, r) {
      wordWithFilters(li, r);
      li.appendChild(el("div", "sr-meta", "finds " + r.finds_now + " · " + meta(r)));
    }, "None.");
  problemCard(host, "gray", "Found, nothing opened",
    "Searched at least twice with results, and nobody opened one within " + d.open_minutes
    + " minutes. The right demo may be missing, or its card does not look like the answer.",
    d.not_opened, function (li, r) {
      wordWithFilters(li, r);
      li.appendChild(el("div", "sr-meta", meta(r)));
    }, "None: what was found was opened.");
}

function trendMark(now, before) {
  if (!before) return el("span", "sr-trend sr-trend--new", "new");
  if (now > before) return el("span", "sr-trend sr-trend--up", "↑ " + before + " → " + now);
  if (now < before) return el("span", "sr-trend sr-trend--down", "↓ " + before + " → " + now);
  return el("span", "sr-trend", "=");
}

function renderTop(d) {
  var host = $("srTop");
  host.innerHTML = "";
  if (!d.top.length) {
    host.appendChild(el("div", "faint", "No searches in this period."));
    return;
  }
  var max = d.top[0].people || 1;
  var t = el("table", "sr-top");
  var hr = t.createTHead().insertRow();
  [["", ""], ["Searched for", ""], ["People", ""], ["Searches", "r"],
   [d.trending.enough_data ? "Before" : "", ""], ["Opened", "r"], ["Finds today", "r"]]
    .forEach(function (h) { hr.appendChild(el("th", h[1] || null, h[0])); });
  var tb = t.createTBody();
  d.top.forEach(function (r, i) {
    var tr = tb.insertRow();
    tr.insertCell().appendChild(el("span", "faint num", String(i + 1)));
    var w = tr.insertCell();
    w.appendChild(tryLink(r.term));
    if (r.variants.length) w.appendChild(el("div", "sr-meta", "also " + r.variants.join(", ")));
    var bar = tr.insertCell();
    bar.className = "sr-barcell";
    var b = el("span", "sr-bar");
    b.style.width = Math.max(4, Math.round(r.people / max * 100)) + "%";
    bar.appendChild(b);
    bar.appendChild(el("span", "num sr-barn", String(r.people)));
    var s = tr.insertCell();
    s.className = "r num";
    s.textContent = r.times;
    var tcell = tr.insertCell();
    if (d.previous && d.trending.enough_data) tcell.appendChild(trendMark(r.people, r.prev_people));
    var o = tr.insertCell();
    o.className = "r num" + (r.opened_rate === null ? " faint" : "");
    o.textContent = r.opened_rate === null ? "—" : Math.round(r.opened_rate * 100) + "%";
    var f = tr.insertCell();
    f.className = "r num" + (r.finds_now ? "" : " sr-zero");
    f.textContent = r.finds_now === null || r.finds_now === undefined ? "—" : r.finds_now;
  });
  var wrap = el("div", "tablewrap");
  wrap.appendChild(t);
  host.appendChild(wrap);
}

function renderTrending(d) {
  var host = $("srTrending");
  host.innerHTML = "";
  var tr = d.trending;
  if (!days()) {
    host.appendChild(el("p", "faint", "Choose a period to compare it with the one before."));
    return;
  }
  if (!tr.enough_data) {
    host.appendChild(el("p", "faint", "Not enough to call a trend yet: this period and the "
      + "one before both need searches by more people, and searches before mid-October did "
      + "not record who searched. A shorter period may work."));
    return;
  }
  [["Rising", tr.rising, "A larger share of the people searching asked for it than in the "
     + "period before."],
   ["New this period", tr.new, "Nobody searched for it in the period before; at least "
     + d.trend_min_people + " people did now."]].forEach(function (part) {
    var box = el("div", "sr-trendbox");
    box.appendChild(el("h3", null, part[0]));
    box.appendChild(el("p", "muted sr-why", part[2]));
    if (!part[1].length) {
      box.appendChild(el("div", "faint sr-empty", "None."));
    } else {
      var list = el("ul", "sr-list");
      part[1].forEach(function (r) {
        var li = el("li");
        var top = el("div", "sr-q");
        top.appendChild(tryLink(r.term));
        top.appendChild(trendMark(r.people, r.prev_people));
        li.appendChild(top);
        li.appendChild(el("div", "sr-meta", r.people + " people · finds "
          + (r.finds_now === null ? "—" : r.finds_now) + " today"));
        list.appendChild(li);
      });
      box.appendChild(list);
    }
    host.appendChild(box);
  });
}

function renderAll(d) {
  var host = $("srAll");
  host.innerHTML = "";
  $("srAllCount").textContent = d.rows.length + " different searches";
  var t = el("table");
  var hr = t.createTHead().insertRow();
  [["Searched for"], ["With filters"], ["People", "r"], ["Searches", "r"],
   ["Nothing found", "r"], ["1–" + d.few_results_max + " found", "r"], ["Opened", "r"],
   ["Last"]].forEach(function (h) {
    hr.appendChild(el("th", h[1] || null, h[0]));
  });
  var tb = t.createTBody();
  d.rows.forEach(function (r) {
    var tr = tb.insertRow();
    tr.insertCell().appendChild(tryLink(r.q));
    var f = tr.insertCell();
    f.textContent = r.filters || "—";
    if (!r.filters) f.className = "faint";
    [r.people, r.times, r.no_results, r.few_results].forEach(function (n) {
      var c = tr.insertCell();
      c.className = "r num" + (n ? "" : " faint");
      c.textContent = n;
    });
    var o = tr.insertCell();
    o.className = "r num" + (r.opened_rate === null ? " faint" : "");
    o.textContent = r.opened_rate === null ? "—" : Math.round(r.opened_rate * 100) + "%";
    tr.insertCell().textContent = r.last_at || "—";
  });
  var wrap = el("div", "tablewrap");
  wrap.appendChild(t);
  host.appendChild(wrap);
}

function render(d) {
  $("srIntro").textContent = d.totals.searches.toLocaleString() + " searches by "
    + d.totals.people + " people"
    + (d.totals.typing ? "; " + d.totals.typing + " more were someone still typing and are "
       + "left out" : "")
    + ". Variants of a word (lambo, Lamborghini) count as one under Most searched. "
    + "Worked out once a day; this is as of "
    + new Date(d.computed_at).toLocaleString(undefined, { dateStyle: "medium",
                                                          timeStyle: "short" }) + ".";
  renderTiles(d);
  renderChart(d);
  renderProblems(d);
  renderTop(d);
  renderTrending(d);
  renderAll(d);
}

function loadSearches() {
  renderRanges();
  $("srIntro").textContent = "Loading…";
  var d = days();
  return fetch("/api/content-health/searches" + (d ? "?days=" + d : ""))
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(render)
    .catch(function (err) { $("srIntro").textContent = "Could not load: " + err.message; });
}

export {
  loadSearches
};
