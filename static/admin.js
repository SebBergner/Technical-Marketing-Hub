/* The Admin page.
 *
 * Kept apart from hub-api.js on purpose: that file's whole job is taking over
 * Elio's mock-up without disturbing it, and none of that applies here. This
 * page owns its own markup, so it can be plain and direct.
 *
 * Every number on screen comes from one call to /api/admin/overview. The page
 * computes nothing it could get wrong — including, especially, anything that
 * would merge a counted population with an uncounted one.
 */
(function () {
  "use strict";

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

  /* Freshness is the one number on this page that rots by itself, so it is
   * the one with a threshold. Two days is a working tolerance for a manual
   * sync, a week is a problem worth colouring red. */
  function freshness(days) {
    if (days === null || days === undefined) return ["never", "pill--bad"];
    var label = days < 1 ? "today" : days.toFixed(1) + " days ago";
    if (days <= 2) return [label, "pill--ok"];
    if (days <= 7) return [label, "pill--warn"];
    return [label, "pill--bad"];
  }

  function syncButton(source, label) {
    var b = el("button", "btn-primary", label);
    b.addEventListener("click", function () {
      if (!window.confirm(
        "Refresh the " + source + " mirror on THIS environment now?\n\n" +
        "It re-reads the source and replaces our own cached copy. It does not " +
        "write anything back to SharePoint or Consensus.")) return;
      b.disabled = true;
      var original = b.textContent;
      b.textContent = "Syncing…";
      // No timeout on purpose: a full SharePoint sync genuinely takes minutes,
      // and a spinner that gives up first would teach people to distrust it.
      fetch(source === "SharePoint" ? "/api/graph/sync" : "/api/consensus/sync",
            { method: "POST" })
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            if (!r.ok) throw new Error(body.detail || ("HTTP " + r.status));
            return body;
          });
        })
        .then(function () { load(); })
        .catch(function (err) {
          b.disabled = false;
          b.textContent = original;
          window.alert("Sync failed:\n\n" + err.message);
        });
    });
    return b;
  }

  function detailLink(source) {
    var a = el("a", null, "Sync history and detail →");
    a.href = "#";
    a.style.cssText = "display:inline-block;margin-left:12px;font-size:12.5px";
    a.addEventListener("click", function (e) {
      e.preventDefault();
      openSourceSheet(source);
    });
    return a;
  }

  function renderEnvironment(env) {
    var isProd = env.slot && env.slot.toLowerCase() === "production";
    $("envBanner").className = "env" + (isProd ? " env--prod" : "");
    $("envTag").textContent = env.slot === "local" ? "Local" : env.slot;
    var bits = [env.site_name];
    bits.push("data in " + env.data_dir);
    if (!env.storage_is_durable) bits.push("⚠ storage is not durable");
    $("envDetail").textContent = bits.join(" · ");
  }

  function renderIntegrations(d) {
    var host = $("integrations");
    host.innerHTML = "";
    var sp = d.sharepoint, cs = d.consensus, auth = d.auth;

    // ---- SharePoint
    var c1 = card("SharePoint");
    row(c1, "Credentials", sp.configured ? "configured" : "missing",
        sp.configured ? "pill--ok" : "pill--bad");
    row(c1, "Library", sp.library || "—");
    row(c1, "Assets", sp.assets);
    var f1 = freshness(sp.days_since_success);
    row(c1, "Last successful sync", f1[0], f1[1]);
    if (sp.last_attempt_ok === false) {
      row(c1, "Last attempt", "failed", "pill--bad");
      row(c1, "Error", sp.last_error || "—");
    }
    c1.appendChild(syncButton("SharePoint", "Sync SharePoint now"));
    c1.appendChild(detailLink("sharepoint"));
    host.appendChild(c1);

    // ---- Consensus
    var c2 = card("Consensus");
    row(c2, "V1 (images, sharing)", cs.v1_configured ? "configured" : "missing",
        cs.v1_configured ? "pill--ok" : "pill--off");
    row(c2, "V2 OAuth", cs.v2_authorised ? "authorised"
        : cs.v2_configured ? "not authorised" : "not configured",
        cs.v2_authorised ? "pill--ok" : "pill--warn");
    // An expired access token is not a fault and must not read like one: the
    // stored refresh token mints a new one on the next call. Only the absence
    // of a refresh token would be a problem, and that is `v2_authorised`
    // above. Shown because a live countdown is a cheap way to see the renewal
    // working; shown as words, not a negative number, once it lapses.
    if (cs.v2_token_expires_in !== null && cs.v2_token_expires_in !== undefined) {
      row(c2, "Access token",
          cs.v2_token_expires_in > 0
            ? "valid for " + Math.round(cs.v2_token_expires_in / 60) + " min"
            : "expired — renews on the next call");
    }
    row(c2, "Assets", cs.assets);
    var f2 = freshness(cs.days_since_success);
    row(c2, "Last successful sync", f2[0], f2[1]);
    if (cs.last_attempt_ok === false) {
      row(c2, "Last attempt", "failed", "pill--bad");
      row(c2, "Error", cs.last_error || "—");
    }
    c2.appendChild(syncButton("Consensus", "Sync Consensus now"));
    c2.appendChild(detailLink("consensus"));
    host.appendChild(c2);

    // ---- Auth
    var c3 = card("Sign-in");
    row(c3, "Mode", auth.mode, auth.mode === "easyauth" ? "pill--ok" : "pill--warn");
    row(c3, "Curator role", auth.curator_groups_configured ? "configured"
        : "nobody has it", auth.curator_groups_configured ? "pill--ok" : "pill--warn");
    (auth.warnings || []).forEach(function (w) {
      var p = el("p", "muted", w);
      p.style.fontSize = "12.5px";
      c3.appendChild(p);
    });
    host.appendChild(c3);

    // ---- Not connected. Listed rather than omitted: silence about a system
    // reads as "fine", and neither of these has ever been reachable.
    var c4 = card("Not connected");
    (d.not_connected || []).forEach(function (name) {
      row(c4, name, "no integration", "pill--off");
    });
    host.appendChild(c4);
  }

  function renderCoverage(cat) {
    $("catTotal").textContent = cat.total.toLocaleString() + " assets";
    var host = $("coverage");
    host.innerHTML = "";
    var intro = el("p", "muted",
      "How much of the catalogue is missing each field. Every row links to the "
      + "assets concerned, so a gap can be worked rather than only watched.");
    intro.style.cssText = "font-size:12.5px;margin:0 0 10px";
    host.appendChild(intro);

    cat.coverage.slice().sort(function (a, b) {
      return b.percent_missing - a.percent_missing;
    }).forEach(function (c) {
      var line = el("div", "cov");
      var link = el("a", null, c.field.replace(/_/g, " "));
      // The catalogue has no "missing X" filter, so this lands on the field's
      // own filter instead -- the nearest honest destination rather than a
      // link that would 404 or silently show everything.
      link.href = "/#/";
      link.title = "Open the catalogue";
      line.appendChild(link);

      var bar = el("div", "bar");
      bar.appendChild(el("span")).style.width = c.percent_missing + "%";
      line.appendChild(bar);

      line.appendChild(el("div", "num",
        c.missing.toLocaleString() + "  (" + c.percent_missing + "%)"));
      host.appendChild(line);
    });
  }

  /* ── time ranges ──────────────────────────────────────────────────────
   *
   * Computed in the browser's own clock and sent as UTC bounds, because the
   * events are stored in UTC and "this week" is a question about where the
   * reader is sitting. Resolving it on the server would hand everyone the
   * server's week, which is nobody's.
   */
  var RANGES = [
    { id: "today", label: "Today" },
    { id: "week", label: "This week" },
    { id: "month", label: "This month" },
    { id: "quarter", label: "This quarter" },
    { id: "year", label: "This year" },
    { id: "all", label: "All time" }
  ];
  var currentRange = "month";

  function utcStamp(d) {
    // "YYYY-MM-DDTHH:MM:SS" with no zone, matching how the log writes them,
    // so the server's string comparison stays a comparison of like with like.
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 19);
  }

  function rangeBounds(id) {
    var now = new Date();
    var start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (id === "week") {
      // Monday, not Sunday: a working-week question asked by a team that
      // works Monday to Friday.
      start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    } else if (id === "month") {
      start = new Date(now.getFullYear(), now.getMonth(), 1);
    } else if (id === "quarter") {
      start = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);
    } else if (id === "year") {
      start = new Date(now.getFullYear(), 0, 1);
    } else if (id === "all") {
      return { since: null };
    }
    return { since: utcStamp(start) };
  }

  function rangeLabel() {
    for (var i = 0; i < RANGES.length; i++) {
      if (RANGES[i].id === currentRange) return RANGES[i].label;
    }
    return currentRange;
  }

  function renderRanges() {
    var host = $("ranges");
    host.innerHTML = "";
    RANGES.forEach(function (r) {
      var b = el("button", null, r.label);
      b.setAttribute("aria-pressed", String(r.id === currentRange));
      b.addEventListener("click", function () {
        currentRange = r.id;
        renderRanges();
        loadUsage();
      });
      host.appendChild(b);
    });
  }

  /* ── the chart ────────────────────────────────────────────────────────
   *
   * Hand-drawn SVG rather than a charting library: three series of daily
   * counts is not worth a dependency, and this page has no build step to
   * hide one behind.
   */
  var SERIES = [
    { key: "view", label: "Detail page opened", color: "#2f8f3f" },
    { key: "preview", label: "Previewed", color: "#4b8ec4" },
    { key: "download", label: "Downloaded", color: "#b5841f" }
  ];

  function drawChart(host, daily) {
    host.innerHTML = "";
    if (!daily || !daily.length) {
      var empty = el("p", "muted", "Nothing recorded in this window.");
      empty.style.cssText = "margin:0;font-size:13px";
      host.appendChild(empty);
      return;
    }

    var W = 900, H = 150, padL = 34, padB = 20, padT = 8;
    var max = 1;
    daily.forEach(function (d) {
      SERIES.forEach(function (s) { max = Math.max(max, d[s.key] || 0); });
    });

    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "chart");
    svg.setAttribute("preserveAspectRatio", "none");

    function add(tag, attrs, text) {
      var n = document.createElementNS(NS, tag);
      Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
      if (text !== undefined) n.textContent = text;
      svg.appendChild(n);
      return n;
    }

    // Two gridlines with their values, so a bar's height means a number and
    // not merely "taller than that one".
    [0, max].forEach(function (value) {
      var y = padT + (H - padT - padB) * (1 - value / max);
      add("line", { x1: padL, x2: W, y1: y, y2: y,
                    stroke: "#cbd3c2", "stroke-width": 1 });
      add("text", { x: 4, y: y + 4, fill: "#8a9682", "font-size": 10 },
          String(value));
    });

    var band = (W - padL) / daily.length;
    var barW = Math.max(1, Math.min(6, band / 4));
    daily.forEach(function (d, i) {
      SERIES.forEach(function (s, si) {
        var v = d[s.key] || 0;
        if (!v) return;
        var h = (H - padT - padB) * (v / max);
        var rect = add("rect", {
          x: padL + i * band + si * (barW + 0.5),
          y: H - padB - h, width: barW, height: h, fill: s.color, rx: 1
        });
        var title = document.createElementNS(NS, "title");
        title.textContent = d.day + " · " + s.label + ": " + v;
        rect.appendChild(title);
      });
    });

    // First and last day only: one label per day is unreadable across a year
    // and says nothing the two ends do not.
    add("text", { x: padL, y: H - 5, fill: "#8a9682", "font-size": 10 },
        daily[0].day);
    if (daily.length > 1) {
      add("text", { x: W, y: H - 5, fill: "#8a9682", "font-size": 10,
                    "text-anchor": "end" }, daily[daily.length - 1].day);
    }

    host.appendChild(svg);

    var legend = el("div", "chart-legend");
    SERIES.forEach(function (s) {
      var item = el("span");
      var sw = el("span", "swatch");
      sw.style.background = s.color;
      item.appendChild(sw);
      item.appendChild(document.createTextNode(s.label));
      legend.appendChild(item);
    });
    host.appendChild(legend);
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

  function renderUsage(u) {
    $("syntheticBanner").hidden = !u.synthetic;
    var prev = u.previous;
    var vs = prev
      ? "vs previous " + rangeLabel().toLowerCase().replace(/^this /, "")
      : null;

    var totals = $("usageTotals");
    totals.innerHTML = "";
    tile(totals, u.totals.views, "Detail pages opened", vs,
      delta(u.totals.views, prev && prev.views));
    tile(totals, u.totals.previews, "Files previewed", vs,
      delta(u.totals.previews, prev && prev.previews));
    tile(totals, u.totals.downloads, "Files downloaded", vs,
      delta(u.totals.downloads, prev && prev.downloads));
    // A ratio, deliberately not called a conversion rate: with no identity in
    // the log, one person opening ten demos is indistinguishable from ten
    // people opening one, so this is downloads per page-open and must never
    // be read as "x% of visitors".
    tile(totals, u.totals.views
      ? Math.round(u.totals.downloads / u.totals.views * 100) + "%" : "—",
      "Downloads per open", "not per person — the log is anonymous");
    tile(totals, u.totals.assets_touched, "Demos touched");

    drawChart($("usageChart"), u.daily);
    renderSearches(u);
  }

  /* ── the breakdown table ──────────────────
   *
   * This is the shape every analytics product converges on, for the reason
   * that forced the rewrite: a fixed "top 25 demos" answers one question and
   * hides the catalogue behind it. So -- a dimension to group by, a box to
   * search, headers that sort, a pager that admits how much is off screen,
   * and a click that drills from a group into the demos inside it.
   *
   * Rolling up is the important half. "Which product got the attention" fits
   * on a screen at any catalogue size; "which demo" stops fitting somewhere
   * around the second hundred.
   */
  var DIMS = [
    { id: "demo", label: "By demo", col: "Demo" },
    { id: "product", label: "By product", col: "Product" },
    { id: "segment", label: "By segment", col: "Segment" },
    { id: "source", label: "By source", col: "Source" },
    { id: "type", label: "By type", col: "Asset type" }
  ];
  var SORTS = [
    { key: "view", label: "Opened" },
    { key: "preview", label: "Prev." },
    { key: "download", label: "Down." }
  ];

  var bd = {
    dimension: "demo", sort: "view", q: "", offset: 0, limit: 25,
    scopeDim: null, scopeKey: null
  };

  function dimLabel(id) {
    for (var i = 0; i < DIMS.length; i++) if (DIMS[i].id === id) return DIMS[i];
    return DIMS[0];
  }

  function renderDims() {
    var host = $("breakdownDims");
    host.innerHTML = "";
    DIMS.forEach(function (d) {
      var b = el("button", null, d.label);
      b.setAttribute("aria-pressed", String(d.id === bd.dimension));
      b.addEventListener("click", function () {
        bd.dimension = d.id;
        bd.offset = 0;
        // Leaving a scope set while grouping by something else would put a
        // filtered total under an unfiltered heading.
        if (d.id !== "demo") { bd.scopeDim = null; bd.scopeKey = null; }
        renderDims();
        loadBreakdown();
      });
      host.appendChild(b);
    });
  }

  function loadBreakdown() {
    var b = rangeBounds(currentRange);
    var p = ["dimension=" + bd.dimension, "sort=" + bd.sort,
             "limit=" + bd.limit, "offset=" + bd.offset];
    if (b.since) p.push("since=" + encodeURIComponent(b.since));
    if (bd.q) p.push("q=" + encodeURIComponent(bd.q));
    if (bd.scopeKey) {
      p.push("scope_dim=" + encodeURIComponent(bd.scopeDim));
      p.push("scope_key=" + encodeURIComponent(bd.scopeKey));
    }
    return fetch("/api/admin/usage/breakdown?" + p.join("&"))
      .then(function (r) { return r.json(); })
      .then(renderBreakdown)
      .catch(function () {
        $("breakdownTable").textContent = "Could not load the breakdown.";
      });
  }

  function renderBreakdown(d) {
    var host = $("breakdownTable");
    host.innerHTML = "";

    var scope = $("breakdownScope");
    scope.innerHTML = "";
    if (bd.scopeKey) {
      var chip = el("button", "chip",
        dimLabel(bd.scopeDim).col + ": " + bd.scopeKey + " ✕");
      chip.title = "Show all demos again";
      chip.addEventListener("click", function () {
        bd.scopeDim = null;
        bd.scopeKey = null;
        bd.offset = 0;
        loadBreakdown();
      });
      scope.appendChild(chip);
    }

    if (!d.rows || !d.rows.length) {
      host.appendChild(el("p", "muted", bd.q
        ? "Nothing matching “" + bd.q + "” in this window."
        : "Nothing recorded in this window."));
      $("breakdownPager").innerHTML = "";
      return;
    }

    var t = el("table");
    var head = el("tr");
    head.appendChild(el("th", null, dimLabel(d.dimension).col));
    if (d.dimension === "demo") head.appendChild(el("th", null, "Source"));
    SORTS.forEach(function (s) {
      var th = el("th", "r sortable",
        s.label + (bd.sort === s.key ? " ▾" : ""));
      th.title = "Sort by " + s.label.toLowerCase();
      if (bd.sort === s.key) th.setAttribute("aria-sort", "descending");
      th.addEventListener("click", function () {
        bd.sort = s.key;
        bd.offset = 0;
        loadBreakdown();
      });
      head.appendChild(th);
    });
    var shareTh = el("th", "r", "Share");
    shareTh.title = "Share of the rows in this table, by the sorted column"
      + (d.dimension === "product"
        ? " — a demo listed under two products counts under both, so these "
          + "divide up attributions rather than visits."
        : ".");
    head.appendChild(shareTh);
    t.appendChild(el("thead")).appendChild(head);

    var body = el("tbody");
    d.rows.forEach(function (r) {
      var tr = el("tr", "clickable");
      tr.title = d.dimension === "demo"
        ? "Open this demo's own usage"
        : "Show the demos inside " + r.label;
      tr.addEventListener("click", function () {
        if (d.dimension === "demo") { openAssetSheet(r.key); return; }
        bd.scopeDim = d.dimension;
        bd.scopeKey = r.key;
        bd.dimension = "demo";
        bd.offset = 0;
        bd.q = "";
        $("breakdownSearch").value = "";
        renderDims();
        loadBreakdown();
      });
      tr.appendChild(el("td", null, r.label));
      if (d.dimension === "demo") {
        tr.appendChild(el("td", "faint", r.source || "—"));
      }
      SORTS.forEach(function (s) {
        tr.appendChild(el("td", "r num", r[s.key]));
      });
      var cell = el("td", "r");
      var bar = el("div", "bar");
      var fill = el("div", "bar__f");
      fill.style.width = Math.max(2, r.share) + "%";
      bar.appendChild(fill);
      cell.appendChild(bar);
      cell.appendChild(el("div", "faint num share", r.share + "%"));
      tr.appendChild(cell);
      body.appendChild(tr);
    });
    t.appendChild(body);
    // The table scrolls sideways, the page does not. Six columns do not fit a
    // phone, and a page that scrolls horizontally loses the range chips and
    // the tiles off the left edge along with them.
    var wrap = el("div", "tablewrap");
    wrap.appendChild(t);
    host.appendChild(wrap);

    renderPager(d);
  }

  function renderPager(d) {
    var host = $("breakdownPager");
    host.innerHTML = "";
    var first = d.total_rows ? d.offset + 1 : 0;
    var last = Math.min(d.offset + d.limit, d.total_rows);
    // Says the total, always. A page showing 25 rows without saying there are
    // 412 would be the kind of number that misleads because it looks whole.
    host.appendChild(el("span", "faint", "Showing " + first + "–" + last
      + " of " + d.total_rows.toLocaleString()
      + (d.dimension === "demo" ? " demos" : " groups") + " with activity"));

    var nav = el("div", "pager__nav");
    var back = el("button", null, "← Previous");
    back.disabled = d.offset <= 0;
    back.addEventListener("click", function () {
      bd.offset = Math.max(0, bd.offset - bd.limit);
      loadBreakdown();
    });
    var fwd = el("button", null, "Next →");
    fwd.disabled = last >= d.total_rows;
    fwd.addEventListener("click", function () {
      bd.offset = bd.offset + bd.limit;
      loadBreakdown();
    });
    nav.appendChild(back);
    nav.appendChild(fwd);
    host.appendChild(nav);
  }

  /* ── what nobody opened ───────────────────
   *
   * Its own panel rather than a tail of zeroes on the table above. In any
   * given week most of the catalogue is untouched, so mixed in they would
   * bury the demos that were used under hundreds of rows saying nothing.
   * Split out, the same fact turns into the more useful question: which
   * content is not earning its place.
   */
  var untouchedShown = 10;

  function loadUntouched() {
    var b = rangeBounds(currentRange);
    var p = ["limit=" + untouchedShown];
    if (b.since) p.push("since=" + encodeURIComponent(b.since));
    return fetch("/api/admin/usage/untouched?" + p.join("&"))
      .then(function (r) { return r.json(); })
      .then(renderUntouched)
      .catch(function () {});
  }

  function renderUntouched(d) {
    var host = $("usageUntouched");
    host.innerHTML = "";
    host.appendChild(el("h2", null, "Not opened at all"));
    var total = d.total_rows + d.touched;
    var lead = el("p", "muted", d.total_rows.toLocaleString() + " of "
      + total.toLocaleString() + " demos ("
      + (total ? Math.round(d.total_rows * 100 / total) : 0)
      + "%) were not opened once in this window.");
    lead.style.cssText = "font-size:12.5px;margin:6px 0 8px";
    host.appendChild(lead);

    if (!d.rows.length) {
      host.appendChild(el("p", "muted", "Every demo was opened at least once."));
      return;
    }
    var t = el("table");
    var body = el("tbody");
    d.rows.forEach(function (r) {
      var tr = el("tr", "clickable");
      tr.title = "Open this demo's own usage";
      tr.addEventListener("click", function () { openAssetSheet(r.asset_id); });
      tr.appendChild(el("td", null, r.label));
      tr.appendChild(el("td", "r faint", r.source || "—"));
      body.appendChild(tr);
    });
    t.appendChild(body);
    host.appendChild(t);

    if (d.rows.length < d.total_rows) {
      var more = el("button", null, "Show more");
      more.style.cssText = "margin-top:10px;font-size:12.5px;padding:5px 12px";
      more.addEventListener("click", function () {
        untouchedShown += 25;
        loadUntouched();
      });
      host.appendChild(more);
    }
  }

  function renderSearches(u) {
    var s2 = $("usageSearches");
    s2.innerHTML = "";
    s2.appendChild(el("h2", null, "Searches"));
    var zero = u.searches.zero_result || [];
    if (zero.length) {
      var lead = el("p", "muted",
        "Searched for, and found nothing — the most direct evidence there "
        + "is of what the catalogue is missing.");
      lead.style.cssText = "font-size:12.5px;margin:6px 0 4px";
      s2.appendChild(lead);
      var zt = el("table");
      var zh = el("tr");
      zh.appendChild(el("th", null, "No results for"));
      zh.appendChild(el("th", "r", "Times"));
      zt.appendChild(el("thead")).appendChild(zh);
      var zb = el("tbody");
      zero.slice(0, 8).forEach(function (r) {
        var tr = el("tr");
        tr.appendChild(el("td", null, r.q));
        tr.appendChild(el("td", "r num", r.zero_results));
        zb.appendChild(tr);
      });
      zt.appendChild(zb);
      s2.appendChild(zt);
    }
    if ((u.searches.top || []).length) {
      var lead2 = el("p", "muted", "Most searched");
      lead2.style.cssText = "font-size:12.5px;margin:14px 0 4px";
      s2.appendChild(lead2);
      var tt = el("table");
      var tb = el("tbody");
      u.searches.top.slice(0, 8).forEach(function (r) {
        var tr = el("tr");
        tr.appendChild(el("td", null, r.q));
        tr.appendChild(el("td", "r num", r.times));
        tb.appendChild(tr);
      });
      tt.appendChild(tb);
      s2.appendChild(tt);
    }
    if (!zero.length && !(u.searches.top || []).length) {
      s2.appendChild(el("p", "muted", "No searches recorded in this window."));
    }
  }

  /* ── drill-downs ───────────────────────────────────────────────────── */
  function openSheet(title, sub) {
    $("sheetTitle").textContent = title;
    $("sheetSub").textContent = sub || "";
    $("sheetBody").innerHTML = "";
    $("overlay").hidden = false;
    return $("sheetBody");
  }

  function syntheticNotice() {
    var warn = el("div", "synthetic");
    warn.appendChild(el("strong", null, "Synthetic data. "));
    warn.appendChild(document.createTextNode(
      "Generated for testing; not a measurement."));
    return warn;
  }

  function openAssetSheet(assetId) {
    var b = rangeBounds(currentRange);
    var qs = b.since ? "?since=" + encodeURIComponent(b.since) : "";
    fetch("/api/admin/usage/asset/" + encodeURIComponent(assetId) + qs)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var body = openSheet(d.asset.title, [d.asset.type, d.asset.source,
          rangeLabel()].filter(Boolean).join(" · "));
        if (d.synthetic) body.appendChild(syntheticNotice());

        var tiles = el("div", "tiles");
        body.appendChild(tiles);
        tile(tiles, d.totals.views, "Opened");
        tile(tiles, d.totals.previews, "Previewed");
        tile(tiles, d.totals.downloads, "Downloaded");

        var chartCard = el("div", "card");
        chartCard.style.margin = "12px 0";
        body.appendChild(chartCard);
        drawChart(chartCard, d.daily);

        var files = el("div", "card");
        files.appendChild(el("h2", null, "Files people took"));
        if (!d.files.length) {
          files.appendChild(el("p", "muted",
            "No file was previewed or downloaded in this window."));
        } else {
          var t = el("table");
          var h = el("tr");
          ["File", "Kind", "Prev.", "Down."].forEach(function (x, i) {
            h.appendChild(el("th", i > 1 ? "r" : null, x));
          });
          t.appendChild(el("thead")).appendChild(h);
          var tb = el("tbody");
          d.files.forEach(function (f) {
            var tr = el("tr");
            tr.appendChild(el("td", null, f.file));
            tr.appendChild(el("td", "faint", f.kind || "—"));
            tr.appendChild(el("td", "r num", f.preview));
            tr.appendChild(el("td", "r num", f.download));
            tb.appendChild(tr);
          });
          t.appendChild(tb);
          files.appendChild(t);
        }
        body.appendChild(files);

        var link = el("a", null, "Open this demo in the catalogue →");
        link.href = "/#/asset/" + encodeURIComponent(assetId);
        link.target = "_blank";
        link.style.cssText = "display:inline-block;margin-top:12px;font-size:13px";
        body.appendChild(link);
      });
  }

  function openSourceSheet(source) {
    fetch("/api/admin/source/" + encodeURIComponent(source))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var body = openSheet(
          source === "sharepoint" ? "SharePoint" : "Consensus", "source detail");

        if (d.plays) {
          var p = el("div", "card");
          p.style.marginBottom = "12px";
          p.appendChild(el("h2", null, "Plays on Consensus"));
          var note = el("p", "muted", d.plays.note);
          note.style.cssText = "font-size:12.5px;margin:6px 0 8px";
          p.appendChild(note);
          row(p, "Assets with counts", d.plays.assets_with_counts);
          row(p, "Total plays", d.plays.total_views.toLocaleString());
          var t = el("table");
          var h = el("tr");
          h.appendChild(el("th", null, "Most played"));
          h.appendChild(el("th", "r", "Plays"));
          t.appendChild(el("thead")).appendChild(h);
          var tb = el("tbody");
          d.plays.top.forEach(function (a) {
            var tr = el("tr");
            var td = el("td");
            var link = el("a", null, a.title);
            link.href = "/#/asset/" + encodeURIComponent(a.id);
            link.target = "_blank";
            td.appendChild(link);
            tr.appendChild(td);
            tr.appendChild(el("td", "r num", a.views.toLocaleString()));
            tb.appendChild(tr);
          });
          t.appendChild(tb);
          p.appendChild(t);
          body.appendChild(p);
        }

        var hist = el("div", "card");
        hist.appendChild(el("h2", null, "Sync history"));
        if (!d.runs.length) {
          var none = el("p", "muted",
            "No runs recorded yet. The history starts with the first sync "
            + "after 2026-09-21 — before that only a timestamp was kept.");
          none.style.cssText = "font-size:12.5px";
          hist.appendChild(none);
        } else {
          var rt = el("table");
          var rh = el("tr");
          ["When", "Result", "Indexed", "Detail"].forEach(function (x, i) {
            rh.appendChild(el("th", i === 2 ? "r" : null, x));
          });
          rt.appendChild(el("thead")).appendChild(rh);
          var rb = el("tbody");
          d.runs.forEach(function (run) {
            var tr = el("tr");
            tr.appendChild(el("td", null, (run.at || "").replace("T", " ")));
            var res = el("td");
            res.appendChild(el("span", "pill " + (run.ok ? "pill--ok" : "pill--bad"),
                               run.ok ? "ok" : "failed"));
            tr.appendChild(res);
            tr.appendChild(el("td", "r num",
              run.summary && run.summary.indexed !== undefined
                ? run.summary.indexed : "—"));
            tr.appendChild(el("td", "faint", run.error
              || (run.summary && run.summary.skipped_total !== undefined
                ? run.summary.skipped_total + " skipped" : "")));
            rb.appendChild(tr);
          });
          rt.appendChild(rb);
          hist.appendChild(rt);
        }
        body.appendChild(hist);
      });
  }

  function loadUsage() {
    // A new window means a new population: page 4 of last month is not page 4
    // of this week, and silently keeping the offset would show an empty table
    // that looks like "no activity".
    bd.offset = 0;
    untouchedShown = 10;
    var b = rangeBounds(currentRange);
    var qs = b.since ? "?since=" + encodeURIComponent(b.since) : "";
    return Promise.all([
      fetch("/api/admin/usage" + qs)
        .then(function (r) { return r.json(); })
        .then(renderUsage),
      loadBreakdown(),
      loadUntouched()
    ]);
  }

  function renderQueues(d) {
    var host = $("queues");
    host.innerHTML = "";

    var c1 = card("Asset requests");
    row(c1, "Not yet in SharePoint", d.requests.unsynced);
    host.appendChild(c1);

    var c2 = card("Metadata proposals");
    row(c2, "Pending", d.proposals.pending);
    var p = el("p", "muted",
      "Read-only here. Approving one writes into SharePoint's own columns, "
      + "which this shared sign-in deliberately cannot do — that waits for "
      + "single sign-on, where the write can be attributed to a person.");
    p.style.cssText = "font-size:12.5px;margin:8px 0 0";
    c2.appendChild(p);
    host.appendChild(c2);
  }

  function load() {
    return fetch("/api/admin/overview", { headers: { "Accept": "application/json" } })
      .then(function (r) {
        if (r.status === 401) { show("loginView"); return null; }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        renderEnvironment(d.environment);
        renderIntegrations(d.integrations);
        renderCoverage(d.catalogue);
        renderQueues(d);
        renderRanges();
        renderDims();
        loadUsage();
        $("loadedAt").textContent = "Loaded " + new Date().toLocaleString();
        show("dashView");
      })
      .catch(function (err) {
        console.error("[admin]", err);
        window.alert("Could not load the overview: " + err.message);
      });
  }

  function boot() {
    fetch("/api/admin/session").then(function (r) { return r.json(); })
      .then(function (s) {
        if (!s.configured) { show("offView"); return; }
        if (!s.signed_in) { show("loginView"); return; }
        load();
      });
  }

  $("loginForm").addEventListener("submit", function (e) {
    e.preventDefault();
    $("loginErr").textContent = "";
    fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("u").value, password: $("p").value }),
    }).then(function (r) {
      if (r.ok) { $("p").value = ""; load(); return; }
      // One message for both halves -- see the endpoint's own docstring.
      $("loginErr").textContent = r.status === 503
        ? "No admin is configured on this deployment."
        : "That username and password did not match.";
    });
  });

  $("logoutBtn").addEventListener("click", function () {
    fetch("/api/admin/logout", { method: "POST" }).then(function () {
      show("loginView");
    });
  });

  $("refreshBtn").addEventListener("click", load);

  // Typing is throttled rather than sent per keystroke: every letter would be
  // a full pass over the event log for a query the person has not finished.
  var searchTimer = null;
  $("breakdownSearch").addEventListener("input", function (e) {
    var value = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      bd.q = value;
      bd.offset = 0;
      loadBreakdown();
    }, 250);
  });

  $("sheetClose").addEventListener("click", function () {
    $("overlay").hidden = true;
  });
  $("overlay").addEventListener("click", function (e) {
    // Only the backdrop closes it: a click inside the sheet is someone
    // reading, not someone leaving.
    if (e.target === $("overlay")) $("overlay").hidden = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") $("overlay").hidden = true;
  });

  boot();
})();
