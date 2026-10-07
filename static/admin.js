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

  /* ── when the session runs out with the page open ─────────────────────
   *
   * The server's sign-in gate (backend/oidc.py) answers an API call that
   * has no session with 401 and an X-Sign-In header. A page already open
   * would otherwise just stop loading data, with nothing to say why -- so
   * any such answer sends the person to sign in and back to exactly where
   * they were, including the #/asset/... part the server never sees.
   *
   * Keyed on the header, not on 401 alone: the Admin page's own 401 means
   * "the admin password has not been entered", and must keep meaning that.
   */
  (function watchForExpiredSession() {
    var original = window.fetch;
    if (!original || original.hubSignInWatch) return;
    var watched = function () {
      return original.apply(this, arguments).then(function (response) {
        var login = response.status === 401 && response.headers.get("X-Sign-In");
        if (login) {
          var here = location.pathname + location.search + location.hash;
          location.assign(login + "?next=" + encodeURIComponent(here));
        }
        return response;
      });
    };
    watched.hubSignInWatch = true;
    window.fetch = watched;
  })();

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
    /* One row per library the sync indexes, each with its own count
     * (Liwei, 2026-09-30): the card used to name the Demo Catalog alone. */
    var libs = sp.libraries || [{ name: sp.library, assets: sp.assets }];
    libs.forEach(function (lib) {
      var bad = lib.ok === false;
      row(c1, lib.name || "—",
          (lib.text || (lib.assets == null ? "—"
                        : lib.assets.toLocaleString() + " " + (lib.unit || "assets")))
            + (bad ? " · last sync failed" : ""),
          bad ? "pill--bad" : null);
      if (bad && lib.error) row(c1, lib.name + " error", lib.error);
    });
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
    // Named by what it can do, not by how it was set up: a hand-supplied
    // token syncs exactly as well as OAuth, it just cannot renew itself.
    row(c2, "V2 access",
        cs.v2_route === "oauth" ? "authorised (OAuth)"
        : cs.v2_route === "token" ? "manual token"
        : cs.v2_configured ? "not authorised" : "not configured",
        cs.v2_route ? "pill--ok" : "pill--warn");
    if (cs.v2_route === "token") {
      var note = el("div", "faint");
      note.style.cssText = "font-size:11.5px;margin:-2px 0 6px";
      note.textContent = "Expires without warning \u2014 a sync then refuses "
        + "rather than downgrading. Replace it in both slots.";
      c2.appendChild(note);
    }
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

  function sourceWord(name, r) {
    if (!r) return null;
    if (r.ok === true) return name + " ✓";
    if (r.ok === false) return name + " failed";
    return name + " skipped";
  }

  function renderAutoSync(a) {
    var host = $("integrations");
    if (!a || !host) return;
    var c = card("Automatic sync, twice a day");
    c.classList.add("card--wide");
    var head = c.querySelector(".card-head");

    var toggle = el("label", "switch");
    var box = el("input");
    box.type = "checkbox";
    box.checked = !!a.enabled;
    box.setAttribute("aria-label", "Automatic sync, twice a day");
    toggle.appendChild(box);
    toggle.appendChild(el("span", "switch__track"));
    toggle.appendChild(el("span", "switch__label", a.enabled ? "On" : "Off"));
    head.appendChild(toggle);

    /* Two runs a day, both hours chosen here, one switch for both (Seb /
     * Liwei, 2026-09-30). */
    var hoursNow = a.hours_utc || [a.hour_utc];
    var pickers = hoursNow.map(function (selected, i) {
      var sel = el("select");
      sel.setAttribute("aria-label", (i === 0 ? "First" : "Second") + " daily run");
      for (var h = 0; h < 24; h++) {
        var o = el("option", null, two(h) + ":00 UTC  (" + localHour(h) + " your time)");
        o.value = String(h);
        if (h === selected) o.selected = true;
        sel.appendChild(o);
      }
      return sel;
    });

    function setDisabled(v) {
      box.disabled = v;
      pickers.forEach(function (p) { p.disabled = v; });
    }

    function save() {
      setDisabled(true);
      fetch("/api/admin/auto-sync", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: box.checked,
                               hours_utc: pickers.map(function (p) { return +p.value; }) })
      })
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            if (!r.ok) throw new Error(body.detail || ("HTTP " + r.status));
            return body;
          });
        })
        .then(function () { load(); })
        .catch(function (err) {
          setDisabled(false);
          box.checked = !!a.enabled;
          window.alert("Could not change the schedule:\n\n" + err.message);
        });
    }
    box.addEventListener("change", save);
    pickers.forEach(function (p) { p.addEventListener("change", save); });

    pickers.forEach(function (p, i) {
      var t = row(c, i === 0 ? "First run daily at" : "Second run daily at", "");
      t.querySelector("dd").textContent = "";
      t.querySelector("dd").appendChild(p);
    });

    row(c, "Next run", a.enabled ? when(a.next_run_at) : "off",
        a.enabled ? null : "pill--off");

    var last = a.last_run;
    if (!last) {
      row(c, "Last scheduled run", "never", "pill--off");
    } else if (!last.finished_at) {
      row(c, "Last scheduled run", "running since " + when(last.started_at), "pill--warn");
    } else {
      var res = last.results || {};
      var words = [sourceWord("SharePoint", res.sharepoint),
                   sourceWord("Consensus", res.consensus)].filter(Boolean);
      row(c, "Last scheduled run", when(last.started_at) + " · " + words.join(" · "),
          last.ok ? "pill--ok" : "pill--bad");
      ["sharepoint", "consensus"].forEach(function (k) {
        if (res[k] && res[k].ok === false) {
          row(c, (k === "sharepoint" ? "SharePoint" : "Consensus") + " error", res[k].error || "—");
        }
      });
    }
    if (a.changed_by) {
      row(c, "Last changed", when(a.changed_at) + " by " + a.changed_by);
    }
    if (!a.scheduler_running) {
      row(c, "Scheduler", "not running in this process", "pill--bad");
    }

    var note = el("p", "muted");
    note.style.cssText = "font-size:12px;margin:10px 0 0;line-height:1.5";
    note.textContent = "Twice a day, at the two hours above, runs the syncs below — "
      + "SharePoint (the Demo Catalog, Demo Video and the VM pages), then Consensus — "
      + "on this environment only; staging and production each have their own "
      + "switch, and it turns both runs on or off. Turning it on does not sync now: "
      + "the first run is the next time one of the hours comes round. If App Service has put the site to sleep "
      + "at that hour (\"Always On\" off), the run happens on the next visit instead.";
    c.appendChild(note);

    host.insertBefore(c, host.firstChild);
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

  /* One line per run: what each part of the SharePoint sync did. The
   * summary held them all along; only "N skipped" was ever shown. */
  function syncDetail(s) {
    if (!s) return "";
    var parts = [];
    if (s.skipped_total !== undefined) parts.push(s.skipped_total + " skipped");
    var named = [["demo_video", "Demo Video"], ["vm_pages", "VM pages"], ["demo_pages", "Demo pages"]];
    named.forEach(function (n) {
      var p = s[n[0]];
      if (!p) return;
      var n2 = p.indexed != null ? p.indexed : p.vms;      // VM pages count "vms"
      parts.push(n[1] + (p.ok === false ? " failed" : p.ok === true
        ? (n2 != null ? " " + n2 : " ✓") : " skipped"));
    });
    var pa = s.partner_access;
    if (pa) parts.push(pa.ok === false ? "Partner check failed"
      : "Partners: " + pa.restricted + " of " + pa.folders + " closed"
        + (pa.errors && pa.errors.length ? " (" + pa.errors.length + " unread)" : ""));
    return parts.join(" · ");
  }

  function openSourceSheet(source) {
    fetch("/api/admin/source/" + encodeURIComponent(source))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var body = openSheet(
          source === "sharepoint" ? "SharePoint" : "Consensus", "source detail");

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
            tr.appendChild(el("td", "faint", run.error || syncDetail(run.summary)));
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

  /* ── Promoted on Home ───────────────────────────────────────────────
   *
   * Seb's ask, built 2026-10-01: the team chooses which demos the Home page
   * features, and in which order. One ordered list, saved as a whole on
   * every change (PUT /api/admin/promoted); it lives in the Hub's own data,
   * never in SharePoint. */
  var TYPE_WORD = { video: "Video", ldk: "LDK", vdk: "VDK", vm: "Virtual Machine",
                    cad_model: "CAD Dataset" };

  function promoMeta(a) {
    return [TYPE_WORD[a.type] || a.type, (a.product_families || []).join(", ")]
      .filter(Boolean).join(" · ");
  }

  function loadPromoted() {
    return fetch("/api/admin/promoted")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (state) { if (state) renderPromoted(state); });
  }

  function renderPromoted(state) {
    var host = $("promoted");
    if (!host) return;
    host.innerHTML = "";
    var head = el("div", "card-head");
    head.appendChild(el("h2", null, "Promoted on Home"));
    head.appendChild(el("span", "faint num", state.assets.length + " of " + state.max));
    host.appendChild(head);
    host.appendChild(el("p", "muted",
      "Shown in this order in the Featured section at the top of the Hub's Home page. "
      + "Nothing promoted means no Featured section."));

    var ids = state.assets.map(function (a) { return a.id; });
    var status = el("div", "promo-status faint");
    var save = function (next) {
      status.textContent = "Saving…";
      fetch("/api/admin/promoted", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_ids: next }),
      }).then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
          throw new Error(b.detail || ("HTTP " + r.status));
        });
        return r.json();
      }).then(renderPromoted).catch(function (err) {
        status.textContent = "Not saved: " + err.message;
        status.className = "promo-status err";
      });
    };
    var move = function (i, by) {
      var next = ids.slice();
      var j = i + by;
      if (j < 0 || j >= next.length) return;
      next.splice(j, 0, next.splice(i, 1)[0]);
      save(next);
    };

    var list = el("div");
    if (!state.assets.length) list.appendChild(el("div", "faint", "Nothing promoted yet."));
    state.assets.forEach(function (a, i) {
      var r = el("div", "promo-row");
      r.appendChild(el("span", "promo-row__n", i + 1));
      var info = el("div");
      var title = el("a", "promo-row__title", a.title);
      title.href = "/#/asset/" + encodeURIComponent(a.id);
      title.target = "_blank";
      title.rel = "noopener";
      info.appendChild(title);
      info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
      r.appendChild(info);
      var actions = el("div", "promo-row__actions");
      var up = el("button", null, "↑");
      up.title = "Move up";
      up.disabled = i === 0;
      up.addEventListener("click", function () { move(i, -1); });
      var down = el("button", null, "↓");
      down.title = "Move down";
      down.disabled = i === state.assets.length - 1;
      down.addEventListener("click", function () { move(i, 1); });
      var remove = el("button", null, "Remove");
      remove.addEventListener("click", function () {
        save(ids.filter(function (x) { return x !== a.id; }));
      });
      actions.appendChild(up);
      actions.appendChild(down);
      actions.appendChild(remove);
      r.appendChild(actions);
      list.appendChild(r);
    });
    host.appendChild(list);

    // Add: search the catalogue by title, promote from the results.
    var add = el("div", "promo-add");
    var label = el("label", null, "Add a demo");
    var input = el("input");
    input.type = "search";
    input.placeholder = ids.length >= state.max
      ? "The list is full — remove one first" : "Search by title…";
    input.disabled = ids.length >= state.max;
    input.autocomplete = "off";
    label.appendChild(input);
    add.appendChild(label);
    var results = el("div", "promo-results");
    add.appendChild(results);
    host.appendChild(add);
    host.appendChild(status);
    if (state.changed_at) {
      status.textContent = "Last changed " + new Date(state.changed_at).toLocaleString()
        + (state.changed_by ? " by " + state.changed_by : "");
    }

    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      timer = setTimeout(function () {
        results.innerHTML = "";
        if (q.length < 2) return;
        fetch("/api/assets?limit=8&q=" + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (page) {
            results.innerHTML = "";
            if (!page.items.length) { results.appendChild(el("div", "faint", "No demo matches.")); return; }
            page.items.forEach(function (a) {
              var r = el("div", "promo-row");
              r.appendChild(el("span", "promo-row__n", ""));
              var info = el("div");
              info.appendChild(el("div", "promo-row__title", a.title));
              info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
              r.appendChild(info);
              var pick = el("button", "btn-primary", ids.indexOf(a.id) === -1 ? "Promote" : "Promoted");
              pick.disabled = ids.indexOf(a.id) !== -1;
              pick.addEventListener("click", function () { save(ids.concat([a.id])); });
              var act = el("div", "promo-row__actions");
              act.appendChild(pick);
              r.appendChild(act);
              results.appendChild(r);
            });
          });
      }, 250);
    });
  }

  /* ── Content dashboard (HLR-F1) ─────────────────────────────────────
   *
   * Serge's ask: what the Hub holds by type, product, segment, stage,
   * customer, industry and age, every chart drilling into the matching
   * demos. One ranked bar list per dimension -- a single series, so one
   * hue, with the count written on each row so it reads as a table too.
   * "Not set" is drawn in grey, last: it is the catalogue's own gap. */
  var DIM_SHOWN = 8;
  var contentLoaded = false;

  function loadContent() {
    return fetch("/api/admin/content")
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(renderContent)
      .catch(function (err) {
        $("contentCharts").textContent = "The dashboard could not be loaded: " + err.message;
      });
  }

  function renderContent(d) {
    contentLoaded = true;
    $("contentAsOf").textContent = d.total.toLocaleString() + " demos · counted "
      + new Date(d.as_of + "T00:00:00").toLocaleDateString();
    var totals = $("contentTotals");
    totals.innerHTML = "";
    var byType = d.dimensions.find(function (x) { return x.key === "type"; });
    (byType ? byType.buckets : []).forEach(function (b) {
      tile(totals, b.count, b.label);
    });
    var host = $("contentCharts");
    host.innerHTML = "";
    d.dimensions.forEach(function (dim) {
      if (dim.key === "type") return;          // the tiles above carry it
      host.appendChild(dimCard(dim));
    });
  }

  function dimCard(dim) {
    var c = card(dim.title);
    c.querySelector(".card-head").appendChild(el("span", "faint num", dim.of.toLocaleString()));
    var max = dim.buckets.reduce(function (m, b) { return Math.max(m, b.count); }, 0) || 1;
    var list = el("div");
    var rows = dim.buckets.map(function (b) {
      var unset = b.value === "Not set";
      var r = el("button", "dim-row" + (unset ? " dim-row--unset" : ""));
      r.type = "button";
      var pct = dim.of ? Math.round(b.count / dim.of * 100) : 0;
      r.title = b.label + ": " + b.count.toLocaleString() + " (" + pct + "% of "
        + dim.of.toLocaleString() + ") — click to list them";
      r.appendChild(el("span", "dim-row__label", b.label));
      var bar = el("span", "dim-row__bar");
      var fill = el("span");
      fill.style.width = Math.max(1, Math.round(b.count / max * 100)) + "%";
      bar.appendChild(fill);
      r.appendChild(bar);
      r.appendChild(el("span", "dim-row__n", b.count.toLocaleString()));
      r.addEventListener("click", function () { openContentSheet(dim, b); });
      list.appendChild(r);
      return r;
    });
    c.appendChild(list);
    // Long tails (customers) show the top rows; "Not set" stays visible.
    var hidden = rows.filter(function (r, i) {
      return i >= DIM_SHOWN && !r.classList.contains("dim-row--unset");
    });
    if (hidden.length) {
      hidden.forEach(function (r) { r.hidden = true; });
      var more = el("button", "dim-more", "Show " + hidden.length + " more");
      more.type = "button";
      more.addEventListener("click", function () {
        hidden.forEach(function (r) { r.hidden = false; });
        more.remove();
      });
      c.appendChild(more);
    }
    if (dim.note) c.appendChild(el("p", "dim-note", dim.note));
    return c;
  }

  function openContentSheet(dim, b) {
    var body = openSheet(dim.title + ": " + b.label, b.count.toLocaleString() + " demos, newest first");
    body.textContent = "Loading…";
    fetch("/api/admin/content/assets?dim=" + encodeURIComponent(dim.key)
          + "&value=" + encodeURIComponent(b.value))
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (items) {
        body.innerHTML = "";
        var t = el("table");
        var head = t.createTHead().insertRow();
        ["Demo", "Type", "Date"].forEach(function (h) { head.appendChild(el("th", null, h)); });
        var tb = t.createTBody();
        items.forEach(function (a) {
          var tr = tb.insertRow();
          var link = el("a", null, a.title);
          link.href = "/#/asset/" + encodeURIComponent(a.id);
          link.target = "_blank";
          link.rel = "noopener";
          tr.insertCell().appendChild(link);
          tr.insertCell().textContent = TYPE_WORD[a.type] || a.type;
          var when = tr.insertCell();
          when.className = "num faint";
          when.textContent = a.uploaded_at || "—";
        });
        body.appendChild(t);
      })
      .catch(function (err) { body.textContent = "Could not load: " + err.message; });
  }

  /* Overview | Content dashboard | Users & groups. The tab is in the
   * address (#content, #access), so a refresh or a shared link opens the
   * same one. */
  var PANELS = { overview: "tabOverview", content: "tabContent", access: "tabAccess",
                 activity: "tabActivity" };

  function tabFromHash() {
    var name = location.hash.replace("#", "");
    return PANELS[name] ? name : "overview";
  }

  function showTab(name) {
    if (!PANELS[name]) name = "overview";
    Object.keys(PANELS).forEach(function (k) { $(PANELS[k]).hidden = k !== name; });
    document.querySelectorAll("#adminTabs .tab").forEach(function (t) {
      var on = t.dataset.tab === name;
      t.classList.toggle("tab--on", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    if (name === "content" && !contentLoaded) loadContent();
    if (name === "access") loadAccess();
    if (name === "activity") { renderActRanges(); loadActivity(); }
  }

  document.querySelectorAll("#adminTabs .tab").forEach(function (t) {
    t.addEventListener("click", function () {
      history.replaceState(null, "", t.dataset.tab === "overview" ? "#" : "#" + t.dataset.tab);
      showTab(t.dataset.tab);
    });
  });

  /* ── Users & groups (backend/access.py, 2026-10-06) ───────────────────
   * Groups on the left, the chosen one on the right. Built-in groups keep
   * their names; PTC employees and Partners have no member list (sign-in
   * fills them); Administrators always have every permission. Whatever the
   * server refuses comes back as a message beside the Save button. */
  var ug = { data: null, selected: "administrators", draft: null };

  function canManageUsers() {
    return (session.permissions || []).indexOf("manage_users") >= 0;
  }

  function loadAccess() {
    return fetch("/api/admin/access")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) renderAccess(d); });
  }

  function renderAccess(d) {
    ug.data = d;
    if (ug.selected !== null && !groupById(ug.selected)) ug.selected = d.groups[0].id;
    ug.draft = null;
    renderGroups();
    renderAudit(d.audit);
  }

  function groupById(id) {
    return ug.data.groups.filter(function (g) { return g.id === id; })[0];
  }

  function memberCount(g) {
    if (g.auto === "members") return "everyone with a PTC account";
    if (g.auto === "guests") return "everyone with a guest account";
    var n = g.members.length;
    if (g.id === "administrators") {
      n += ug.data.bootstrap_admins.filter(function (e) {
        return g.members.indexOf(e) < 0;
      }).length;
    }
    return n + " member" + (n === 1 ? "" : "s");
  }

  function renderGroups() {
    var host = $("ugGroups");
    host.innerHTML = "";
    var list = el("div", "ug-list");
    ug.data.groups.forEach(function (g) {
      var b = el("button", "ug-item" + (g.id === ug.selected ? " ug-item--on" : ""));
      b.type = "button";
      b.appendChild(el("div", "ug-item__name", g.name));
      b.appendChild(el("div", "ug-item__meta",
        memberCount(g) + " · " + g.permissions.length + " permission"
        + (g.permissions.length === 1 ? "" : "s")));
      b.addEventListener("click", function () {
        ug.selected = g.id;
        ug.draft = null;
        ug.editing = false;
        ug.flash = "";
        ug.memberFilter = "";
        renderGroups();
      });
      list.appendChild(b);
    });
    if (canManageUsers()) {
      var add = el("button", null, "+ New group");
      add.type = "button";
      add.addEventListener("click", function () {
        ug.selected = null;
        ug.draft = { name: "", description: "", permissions: ["view_hub"], members: [] };
        ug.editing = true;
        ug.flash = "";
        renderGroups();
      });
      list.appendChild(add);
    }
    host.appendChild(list);
    host.appendChild(renderEditor());
  }

  function textField(label, value, max, onInput) {
    var l = el("label", null, label);
    var input = el("input");
    input.value = value;
    input.maxLength = max;
    input.addEventListener("input", function () { onInput(input.value); });
    l.appendChild(input);
    return l;
  }

  function renderEditor() {
    var creating = ug.selected === null;
    var g = creating ? { id: null, name: "", builtin: false, auto: null,
                         description: "", permissions: [], members: [] }
                     : groupById(ug.selected);
    if (!ug.draft) {
      ug.draft = { name: g.name, description: g.description || "",
                   permissions: g.permissions.slice(), members: g.members.slice() };
    }
    var draft = ug.draft;
    /* Read-only until Edit is pressed, and read-only again once saved
     * (Liwei, 2026-10-07): with every field always open, a saved group
     * looked exactly like an unsaved one. A new group starts in Edit. */
    var canManage = canManageUsers();
    var editable = canManage && (ug.editing || creating);
    var c = el("div", "card");

    var head = el("div", "card-head");
    if (g.builtin || !editable) {
      var title = el("div", "ug-title");
      title.appendChild(el("h2", null, g.name));
      if (g.builtin) title.appendChild(el("span", "pill pill--off", "built in"));
      head.appendChild(title);
      if (canManage && !editable) {
        var tools = el("div", "ug-title");
        if (ug.flash) tools.appendChild(el("span", "ug-flash", ug.flash));
        // Administrators' permissions and members are fixed or come from
        // settings except the member list, so Edit is offered everywhere.
        var edit = el("button", "btn-small", "Edit");
        edit.type = "button";
        edit.addEventListener("click", function () {
          ug.editing = true;
          ug.flash = "";
          ug.draft = null;
          renderGroups();
        });
        tools.appendChild(edit);
        head.appendChild(tools);
      } else if (editable) {
        head.appendChild(el("span", "pill pill--warn", "editing"));
      }
      c.appendChild(head);
      if (g.description) c.appendChild(el("p", "muted", g.description));
    } else {
      var editHead = el("div", "card-head");
      editHead.appendChild(el("h2", null, creating ? "New group" : "Edit group"));
      editHead.appendChild(el("span", "pill pill--warn", "editing"));
      c.appendChild(editHead);
      c.appendChild(textField(creating ? "New group name" : "Name", draft.name, 80,
        function (v) { draft.name = v; }));
      var desc = textField("Description", draft.description, 300,
        function (v) { draft.description = v; });
      desc.style.marginTop = "10px";
      c.appendChild(desc);
    }

    // Permissions
    var pf = el("div", "ug-field");
    pf.appendChild(el("h3", null, "Permissions"));
    var perms = el("div", "ug-perms");
    var fixed = g.id === "administrators" || !editable;
    ug.data.catalogue.forEach(function (p) {
      var row = el("label", "ug-perm");
      var box = el("input");
      box.type = "checkbox";
      box.checked = draft.permissions.indexOf(p.id) >= 0;
      box.disabled = fixed;
      box.addEventListener("change", function () {
        draft.permissions = draft.permissions.filter(function (x) { return x !== p.id; });
        if (box.checked) draft.permissions.push(p.id);
      });
      row.appendChild(box);
      var text = el("span", null, p.label);
      text.appendChild(el("small", null, p.description));
      row.appendChild(text);
      perms.appendChild(row);
    });
    pf.appendChild(perms);
    if (g.id === "administrators") {
      pf.appendChild(el("div", "faint", "Administrators always have every permission."));
    }
    c.appendChild(pf);

    // Members
    var mf = el("div", "ug-field");
    mf.appendChild(el("h3", null, "Members"));
    if (g.auto) {
      mf.appendChild(el("div", "muted", g.auto === "guests"
        ? "Everyone who signs in with a guest account (a partner). Filled at sign-in."
        : "Everyone who signs in with a PTC account. Filled at sign-in."));
    } else {
      mf.appendChild(renderMembers(g, draft, editable));
    }
    c.appendChild(mf);

    if (!canManage) {
      c.appendChild(el("p", "faint", "Viewing only: changing groups needs the "
        + "Manage users & groups permission."));
      return c;
    }
    if (!editable) return c;
    var actions = el("div", "ug-actions");
    var status = el("span", "promo-status faint");
    var save = el("button", "btn-primary", creating ? "Create group" : "Save");
    save.type = "button";
    save.addEventListener("click", function () {
      var body = {};
      if (g.id !== "administrators") body.permissions = draft.permissions;
      if (!g.builtin) { body.name = draft.name; body.description = draft.description; }
      if (!g.auto) body.members = draft.members;
      sendAccess(creating ? "POST" : "PUT",
        creating ? "/api/admin/access/groups"
                 : "/api/admin/access/groups/" + encodeURIComponent(g.id),
        body, status, creating ? draft.name : null);
    });
    actions.appendChild(save);
    // Cancel drops the changes and leaves Edit; for a new group, it drops the group.
    var cancel = el("button", null, "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", function () {
      ug.draft = null;
      ug.editing = false;
      ug.flash = "";
      if (creating) ug.selected = ug.data.groups[0].id;
      renderGroups();
    });
    actions.appendChild(cancel);
    actions.appendChild(status);
    /* Rarely used, so small, red and pushed to the far right, away from
     * Save (Liwei, 2026-10-07). Confirmed in place rather than with
     * window.confirm(), which some browsers suppress -- the Claude browser
     * pane answers it "cancel" without showing anything. */
    if (!g.builtin && !creating) {
      var danger = el("div", "ug-danger");
      var del = el("button", "btn-danger", "Delete group");
      del.type = "button";
      del.addEventListener("click", function () {
        danger.innerHTML = "";
        danger.appendChild(el("span", "ug-danger__q",
          "Delete “" + g.name + "”? Its members lose whatever only this group gave them."));
        var yes = el("button", "btn-danger btn-danger--solid", "Delete");
        yes.type = "button";
        yes.addEventListener("click", function () {
          ug.selected = "administrators";
          sendAccess("DELETE", "/api/admin/access/groups/" + encodeURIComponent(g.id),
            null, status);
        });
        var no = el("button", "btn-small", "Cancel");
        no.type = "button";
        no.addEventListener("click", function () { renderGroups(); });
        danger.appendChild(yes);
        danger.appendChild(no);
        no.focus();
      });
      danger.appendChild(del);
      actions.appendChild(danger);
    }
    c.appendChild(actions);
    return c;
  }

  /* Members as a table, not tags (Liwei, 2026-10-07): a group of a hundred
   * has to stay readable. A count and a filter on top, a list that scrolls
   * inside a fixed height, and an add box that takes many addresses at once
   * -- pasted from Outlook as "Name <a@ptc.com>; ..." or one per line. The
   * filter only redraws the rows, so typing in it keeps its focus. */
  var EMAILS = /[^\s<>,;"'()]+@[^\s<>,;"'()]+\.[^\s<>,;"'()]+/g;

  function renderMembers(g, draft, editable) {
    var box = el("div");
    var byEmail = {};
    ug.data.users.forEach(function (u) {
      [u.email, u.username].forEach(function (e) { if (e) byEmail[e] = u; });
    });
    var fixed = g.id === "administrators" ? ug.data.bootstrap_admins.filter(function (e) {
      return draft.members.indexOf(e) < 0;
    }) : [];
    var saved = g.members;
    var added = draft.members.filter(function (m) { return saved.indexOf(m) < 0; });
    var removed = saved.filter(function (m) { return draft.members.indexOf(m) < 0; });

    var bar = el("div", "ug-mbar");
    bar.appendChild(el("span", "ug-mbar__count",
      (draft.members.length + fixed.length) + " member"
      + (draft.members.length + fixed.length === 1 ? "" : "s")));
    var filter = el("input");
    filter.type = "search";
    filter.placeholder = "Filter by name or email…";
    filter.value = ug.memberFilter || "";
    bar.appendChild(filter);
    box.appendChild(bar);

    if (added.length || removed.length) {
      box.appendChild(el("div", "ug-pending",
        [added.length ? added.length + " to add" : "",
         removed.length ? removed.length + " to remove" : ""].filter(Boolean).join(", ")
        + " — not saved yet. Press Save to apply."));
    }

    var wrap = el("div", "ug-mtable");
    var t = el("table");
    var hr = t.createTHead().insertRow();
    ["Email", "Name", "Last sign-in", ""].forEach(function (h) { hr.appendChild(el("th", null, h)); });
    var tb = t.createTBody();
    wrap.appendChild(t);
    box.appendChild(wrap);
    var shown = el("div", "faint ug-mfoot");
    box.appendChild(shown);

    var rows = fixed.map(function (e) { return { email: e, fixed: true }; })
      .concat(draft.members.map(function (e) {
        return { email: e, fresh: added.indexOf(e) >= 0 };
      }));

    function drawRows() {
      var q = (filter.value || "").trim().toLowerCase();
      ug.memberFilter = filter.value;
      tb.innerHTML = "";
      var n = 0;
      rows.forEach(function (r) {
        var u = byEmail[r.email];
        var name = (u && u.name) || "";
        if (q && r.email.indexOf(q) < 0 && name.toLowerCase().indexOf(q) < 0) return;
        n += 1;
        var tr = tb.insertRow();
        var em = tr.insertCell();
        em.textContent = r.email;
        if (r.fresh) em.appendChild(el("span", "pill pill--warn ug-tag", "new"));
        tr.insertCell().textContent = name || "—";
        var when = tr.insertCell();
        when.className = "num faint";
        when.textContent = u && u.last_seen ? new Date(u.last_seen).toLocaleDateString()
                                            : "never";
        var act = tr.insertCell();
        act.className = "r";
        if (r.fixed) {
          var note = el("span", "faint", "HUB_ADMIN_EMAILS");
          note.title = "Named in the app settings; change it in Azure.";
          act.appendChild(note);
        } else if (editable) {
          var x = el("button", "ug-remove", "Remove");
          x.type = "button";
          x.addEventListener("click", function () {
            draft.members = draft.members.filter(function (v) { return v !== r.email; });
            renderGroups();
          });
          act.appendChild(x);
        }
      });
      if (!rows.length) {
        var empty = tb.insertRow().insertCell();
        empty.colSpan = 4;
        empty.className = "faint";
        empty.textContent = "No members yet.";
      }
      shown.textContent = q ? n + " of " + rows.length + " shown" : "";
    }
    filter.addEventListener("input", drawRows);
    drawRows();

    if (editable) {
      var addRow = el("div", "ug-add");
      var input = el("textarea");
      input.rows = 2;
      input.placeholder = "Add people: one or more addresses, e.g. pasted from Outlook "
        + "(“Name <a@ptc.com>; …”) or one per line";
      input.setAttribute("aria-label", "Addresses to add");
      var addBtn = el("button", null, "Add");
      addBtn.type = "button";
      var msg = el("div", "faint ug-mfoot");
      var addMembers = function () {
        var found = (input.value.toLowerCase().match(EMAILS) || []);
        if (!found.length) { msg.textContent = "No email address found in that text."; return; }
        var fresh = found.filter(function (e, i) {
          return found.indexOf(e) === i && draft.members.indexOf(e) < 0;
        });
        draft.members = draft.members.concat(fresh);
        ug.memberFilter = "";
        renderGroups();
      };
      addBtn.addEventListener("click", addMembers);
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addMembers(); }
      });
      addRow.appendChild(input);
      addRow.appendChild(addBtn);
      box.appendChild(addRow);
      box.appendChild(msg);

      // People who have signed in and are not in the group yet, one click each.
      var candidates = ug.data.users.filter(function (u) {
        var e = u.email || u.username;
        return e && draft.members.indexOf(e) < 0 && fixed.indexOf(e) < 0;
      });
      if (candidates.length) {
        var pick = el("select", "ug-pick");
        var first = document.createElement("option");
        first.value = "";
        first.textContent = "…or add someone who has signed in (" + candidates.length + ")";
        pick.appendChild(first);
        candidates.forEach(function (u) {
          var o = document.createElement("option");
          o.value = u.email || u.username;
          o.textContent = (u.name ? u.name + " — " : "") + o.value;
          pick.appendChild(o);
        });
        pick.addEventListener("change", function () {
          if (!pick.value) return;
          draft.members = draft.members.concat([pick.value]);
          renderGroups();
        });
        box.appendChild(pick);
      }
    }
    return box;
  }

  function sendAccess(method, url, body, status, createdName) {
    status.textContent = "Saving…";
    status.className = "promo-status faint";
    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
        var detail = b.detail;
        if (Array.isArray(detail)) detail = detail.map(function (x) { return x.msg; }).join("; ");
        throw new Error(detail || ("HTTP " + r.status));
      });
      return r.json();
    }).then(function (d) {
      if (createdName) {
        var made = d.groups.filter(function (g) { return g.name === createdName.trim(); })[0];
        if (made) ug.selected = made.id;
      }
      // Back to read-only, saying so.
      ug.editing = false;
      ug.flash = method === "DELETE" ? "Group deleted" : method === "POST" ? "Group created"
                                                                         : "Saved";
      renderAccess(d);
    }).catch(function (err) {
      status.textContent = "Not saved: " + err.message;
      status.className = "promo-status err";
    });
  }

  function groupNames(ids) {
    return ids.map(function (id) {
      var g = groupById(id);
      return g ? g.name : id;
    }).join(", ");
  }

  /* A bulk add of a hundred people is one change; its log line names the
   * first few and counts the rest (the full list is on hover). */
  function shortList(items) {
    return items.length <= 3 ? items.join(", ")
      : items.slice(0, 3).join(", ") + " and " + (items.length - 3) + " more";
  }

  function fullChange(e) {
    // A create or delete records the group's lists as they were, not a diff.
    return ["permissions", "members"].map(function (k) {
      if (!e[k]) return "";
      if (Array.isArray(e[k])) return e[k].length ? k + ": " + e[k].join(", ") : "";
      return [e[k].added.length ? k + " added: " + e[k].added.join(", ") : "",
              e[k].removed.length ? k + " removed: " + e[k].removed.join(", ") : ""]
        .filter(Boolean).join("\n");
    }).filter(Boolean).join("\n");
  }

  function describeChange(e) {
    if (e.action === "create") return "created";
    if (e.action === "delete") return "deleted";
    var parts = [];
    if (e.name) parts.push("renamed from “" + e.name.from + "”");
    ["permissions", "members"].forEach(function (k) {
      if (!e[k]) return;
      if (e[k].added.length) parts.push(k + " added: " + shortList(e[k].added));
      if (e[k].removed.length) parts.push(k + " removed: " + shortList(e[k].removed));
    });
    return parts.join("; ") || "updated";
  }

  function renderAudit(entries) {
    var host = $("ugAudit");
    host.innerHTML = "";
    if (!entries.length) {
      host.appendChild(el("div", "faint", "No changes yet."));
      return;
    }
    var t = el("table");
    var hr = t.createTHead().insertRow();
    ["When", "Who", "Group", "Change"].forEach(function (h) { hr.appendChild(el("th", null, h)); });
    var tb = t.createTBody();
    entries.forEach(function (e) {
      var tr = tb.insertRow();
      var when = tr.insertCell();
      when.className = "num faint";
      when.textContent = new Date(e.at).toLocaleString();
      tr.insertCell().textContent = (e.actor || "").replace(/^(user|dev):/, "");
      tr.insertCell().textContent = e.group_name || e.group;
      var what = tr.insertCell();
      what.textContent = describeChange(e);
      what.title = fullChange(e);
    });
    host.appendChild(t);
  }

  /* ── Sign-ins (backend/activity.py, 2026-10-07) ───────────────────────
   * Who is active now, who signed in over a period, and the log itself.
   * One period drives the tiles, People and the log, so the three always
   * agree; it sits in a bar that stays in view, and every heading names it
   * (Liwei, 2026-10-07). "Active" is a request in the last few minutes: the
   * server keeps no session, so it cannot know who still has a tab open.
   * What anyone viewed or downloaded is not on this tab -- that waits for
   * management's answer on per-user tracking. */
  var ACT_RANGES = [
    { id: "today", label: "Today" },
    { id: "7d", label: "7 days" },
    { id: "30d", label: "30 days" },
    { id: "all", label: "All time" },
    { id: "custom", label: "Custom" }
  ];
  var act = { range: "7d", from: "", to: "", q: "", pq: "", user: null, userLabel: "",
              offset: 0, limit: 50, people: [] };
  var actTimer = null;

  function startOfToday() {
    var d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function dateInput(d) {
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;
  }

  /* A yyyy-mm-dd from a date input, as the reader's own midnight. */
  function localDay(value) {
    var p = value.split("-");
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }

  function actBounds() {
    var today = startOfToday();
    if (act.range === "all") return {};
    if (act.range === "today") return { since: today.toISOString() };
    if (act.range === "custom") {
      var out = {};
      if (act.from) out.since = localDay(act.from).toISOString();
      // "To" includes that whole day.
      if (act.to) out.until = new Date(localDay(act.to).getTime() + 86400000).toISOString();
      return out;
    }
    var days = act.range === "30d" ? 30 : 7;
    return { since: new Date(today.getTime() - (days - 1) * 86400000).toISOString() };
  }

  function periodLabel() {
    if (act.range !== "custom") {
      return ACT_RANGES.filter(function (r) { return r.id === act.range; })[0].label;
    }
    var fmt = function (v) {
      return localDay(v).toLocaleDateString(undefined, { month: "short", day: "numeric",
                                                         year: "numeric" });
    };
    if (act.from && act.to) return act.from === act.to ? fmt(act.from)
                                                       : fmt(act.from) + " – " + fmt(act.to);
    if (act.from) return "since " + fmt(act.from);
    if (act.to) return "until " + fmt(act.to);
    return "All time";
  }

  function ago(iso) {
    var mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    var hours = Math.round(mins / 60);
    if (hours < 24) return hours + " h ago";
    return new Date(iso).toLocaleDateString();
  }

  function account(external) { return external ? "Guest" : "PTC"; }

  function loadActivity() {
    var params = actBounds();
    params.today = startOfToday().toISOString();
    params.offset = act.offset;
    params.limit = act.limit;
    if (act.q) params.q = act.q;
    if (act.user) params.user = act.user;
    var qs = Object.keys(params).map(function (k) {
      return k + "=" + encodeURIComponent(params[k]);
    }).join("&");
    // Group names for the People table come from the Users & groups data.
    var groupsReady = ug.data ? Promise.resolve() : fetch("/api/admin/access")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) ug.data = d; });
    return groupsReady.then(function () {
      return fetch("/api/admin/activity?" + qs);
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) renderActivity(d); });
  }

  function setRange(id) {
    act.range = id;
    act.offset = 0;
    if (id === "custom" && !act.from && !act.to) {
      // Start from the last seven days, which the person then narrows.
      var today = startOfToday();
      act.from = dateInput(new Date(today.getTime() - 6 * 86400000));
      act.to = dateInput(today);
    }
    renderActRanges();
    loadActivity();
  }

  function renderActRanges() {
    var host = $("actRanges");
    host.innerHTML = "";
    ACT_RANGES.forEach(function (r) {
      var b = el("button", null, r.label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(r.id === act.range));
      b.addEventListener("click", function () { setRange(r.id); });
      host.appendChild(b);
    });
    $("actCustom").hidden = act.range !== "custom";
    $("actFrom").value = act.from;
    $("actTo").value = act.to;
    $("actFrom").max = $("actTo").max = dateInput(new Date());
  }

  ["actFrom", "actTo"].forEach(function (id) {
    $(id).addEventListener("change", function () {
      act.from = $("actFrom").value;
      act.to = $("actTo").value;
      if (act.from && act.to && act.from > act.to) {
        // Swapped rather than refused: the intent is plain.
        var t = act.from; act.from = act.to; act.to = t;
        $("actFrom").value = act.from;
        $("actTo").value = act.to;
      }
      act.offset = 0;
      loadActivity();
    });
  });

  function actGroups(ids) {
    return ug.data ? groupNames(ids || []) : "";
  }

  function renderActivity(d) {
    var label = periodLabel();
    $("actTitle").textContent = "Sign-ins · " + label;
    $("actPeopleTitle").textContent = "People · " + label;
    $("actLogTitle").textContent = "Sign-in log · " + label;

    var tiles = $("actTiles");
    tiles.innerHTML = "";
    tile(tiles, d.counts.active, "Active now", "a request in the last " + d.active_minutes + " min");
    tile(tiles, d.counts.today_people, "Signed in today", "people");
    tile(tiles, d.counts.window_people, "People", d.counts.guests + " guest"
      + (d.counts.guests === 1 ? "" : "s"));
    tile(tiles, d.counts.window_sign_ins, "Sign-ins", null);

    // Active now -- always the last few minutes, whatever the period.
    $("actActiveNote").textContent = "a request in the last " + d.active_minutes
      + " minutes, whatever the period";
    var host = $("actActive");
    host.innerHTML = "";
    if (!d.active.length) {
      host.appendChild(el("div", "faint", "Nobody right now."));
    } else {
      var t = el("table");
      var hr = t.createTHead().insertRow();
      ["Name", "Email", "Account", "Groups", "Last request"].forEach(function (h) {
        hr.appendChild(el("th", null, h));
      });
      var tb = t.createTBody();
      d.active.forEach(function (a) {
        var tr = tb.insertRow();
        var name = tr.insertCell();
        name.appendChild(el("span", "act-dot"));
        name.appendChild(document.createTextNode(a.name || "—"));
        tr.insertCell().textContent = a.user || "—";
        tr.insertCell().textContent = account(a.external);
        tr.insertCell().textContent = actGroups(a.groups) || "—";
        var when = tr.insertCell();
        when.className = "num faint";
        when.textContent = ago(a.last_active);
      });
      host.appendChild(t);
    }

    act.people = d.people;
    drawPeople();
    renderLogFilter();

    // The log
    host = $("actLog");
    host.innerHTML = "";
    var log = d.log;
    if (!log.items.length) {
      host.appendChild(el("div", "faint", act.user
        ? "No sign-ins by this person in this period."
        : "No sign-ins match."));
    } else {
      var lt = el("table");
      var lhr = lt.createTHead().insertRow();
      ["When", "Name", "Email", "Account"].forEach(function (h) {
        lhr.appendChild(el("th", null, h));
      });
      var ltb = lt.createTBody();
      log.items.forEach(function (e) {
        var tr = ltb.insertRow();
        var when = tr.insertCell();
        when.className = "num faint";
        when.textContent = new Date(e.at).toLocaleString();
        tr.insertCell().textContent = e.name || "—";
        tr.insertCell().textContent = e.user || "—";
        tr.insertCell().textContent = account(e.external);
      });
      host.appendChild(lt);
    }
    var pager = $("actPager");
    pager.innerHTML = "";
    var first = log.total ? log.offset + 1 : 0;
    var lastRow = Math.min(log.offset + log.limit, log.total);
    pager.appendChild(el("span", "faint", "Showing " + first + "–" + lastRow + " of "
      + log.total.toLocaleString() + " sign-ins"));
    var nav = el("div", "pager__nav");
    var back = el("button", null, "← Previous");
    back.disabled = log.offset <= 0;
    back.addEventListener("click", function () {
      act.offset = Math.max(0, act.offset - act.limit);
      loadActivity();
    });
    var fwd = el("button", null, "Next →");
    fwd.disabled = lastRow >= log.total;
    fwd.addEventListener("click", function () {
      act.offset += act.limit;
      loadActivity();
    });
    nav.appendChild(back);
    nav.appendChild(fwd);
    pager.appendChild(nav);

    $("actNote").textContent = (d.recorded_since
      ? "Sign-ins recorded since " + new Date(d.recorded_since).toLocaleString() + ". "
      : "No sign-ins recorded yet. ")
      + "What people view or download is counted on the Overview, not per person.";
  }

  /* People in the period, filtered in the browser: the whole list is
   * already here, so typing narrows it at once. A click narrows the log to
   * that person. */
  function drawPeople() {
    var host = $("actPeople");
    host.innerHTML = "";
    var q = act.pq.toLowerCase();
    var rows = act.people.filter(function (p) {
      return !q || (p.user || "").indexOf(q) >= 0 || (p.name || "").toLowerCase().indexOf(q) >= 0;
    });
    $("actPeopleCount").textContent = q
      ? rows.length + " of " + act.people.length + " people shown"
      : act.people.length + " " + (act.people.length === 1 ? "person" : "people");
    if (!rows.length) {
      host.appendChild(el("div", "faint", act.people.length
        ? "Nobody matches." : "Nobody signed in in this period."));
      return;
    }
    var pt = el("table");
    var phr = pt.createTHead().insertRow();
    ["Name", "Email", "Account", "Groups", "Sign-ins", "Last sign-in", "Last active"]
      .forEach(function (h, i) { phr.appendChild(el("th", i === 4 ? "r" : null, h)); });
    var ptb = pt.createTBody();
    rows.forEach(function (p) {
      var tr = ptb.insertRow();
      tr.className = "act-person";
      tr.title = "Show this person's sign-ins in the log";
      tr.insertCell().textContent = p.name || "—";
      tr.insertCell().textContent = p.user || "—";
      tr.insertCell().textContent = account(p.external);
      tr.insertCell().textContent = actGroups(p.groups) || "—";
      var n = tr.insertCell();
      n.className = "r num";
      n.textContent = p.sign_ins;
      var last = tr.insertCell();
      last.className = "num faint";
      last.textContent = p.last_sign_in ? new Date(p.last_sign_in).toLocaleString() : "—";
      var seen = tr.insertCell();
      seen.className = "num faint";
      seen.textContent = p.last_active ? ago(p.last_active) : "—";
      tr.addEventListener("click", function () {
        act.user = p.oid;
        act.userLabel = p.name || p.user || p.oid;
        act.offset = 0;
        loadActivity().then(function () {
          $("actLog").scrollIntoView({ behavior: "smooth", block: "center" });
        });
      });
    });
    host.appendChild(pt);
  }

  /* Who the log is narrowed to, in which period, and the ways out. */
  function renderLogFilter() {
    var filter = $("actFilter");
    filter.innerHTML = "";
    filter.hidden = !act.user;
    if (!act.user) return;
    filter.appendChild(el("span", null, "Showing sign-ins of " + act.userLabel
      + " · " + periodLabel()));
    if (act.range !== "all") {
      var all = el("button", null, "All time for this person");
      all.type = "button";
      all.addEventListener("click", function () { setRange("all"); });
      filter.appendChild(all);
    }
    var clear = el("button", null, "Show everyone");
    clear.type = "button";
    clear.addEventListener("click", function () {
      act.user = null;
      act.offset = 0;
      loadActivity();
    });
    filter.appendChild(clear);
  }

  $("actSearch").addEventListener("input", function (e) {
    var value = e.target.value;
    clearTimeout(actTimer);
    actTimer = setTimeout(function () {
      act.q = value.trim();
      act.offset = 0;
      loadActivity();
    }, 250);
  });

  $("actPeopleSearch").addEventListener("input", function (e) {
    act.pq = e.target.value.trim();
    drawPeople();
  });

  /* ── Hub display switches ─────────────────────────────────────────────
   * One for now: links from the Hub to a demo's SharePoint page. Off by
   * default while management decides whether to expose SharePoint (Liwei,
   * 2026-10-05); when off the server sends no page address at all. */
  function loadHubSettings() {
    return fetch("/api/admin/hub-settings")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) renderHubSettings(s); });
  }

  var HUB_SWITCHES = [
    { key: "show_page_only_demos", title: "Demos with only a SharePoint page",
      note: "Demos that have a page under SitePages/Demo Catalog but no project folder "
          + "(Lamborghini IPL, for example). Hidden, they are not listed in the Hub at all; "
          + "demos with a folder keep their page thumbnail either way. Shown by default." },
    { key: "show_demo_page_links", title: "Links to SharePoint demo pages",
      note: "The “Demo page” link on a demo that has a SharePoint page, and the "
          + "“Open demo page” button on a demo known only from its page. Hidden, no "
          + "page address is sent to the browser. Download Kit and Open Video are not "
          + "affected. Hidden by default." }
  ];

  function renderHubSettings(s) {
    var host = $("hubDisplay");
    if (!host) return;
    host.innerHTML = "";
    var head = el("div", "card-head");
    head.appendChild(el("h2", null, "SharePoint demo pages"));
    host.appendChild(head);
    var status = el("div", "promo-status faint",
      s.changed_at ? "Last changed " + new Date(s.changed_at).toLocaleString()
                     + (s.changed_by ? " by " + s.changed_by : "") : "Never changed: the defaults apply.");
    HUB_SWITCHES.forEach(function (sw) {
      var row = el("div", "promo-row");
      row.style.gridTemplateColumns = "1fr auto";
      var text = el("div");
      text.appendChild(el("div", "promo-row__title", sw.title));
      text.appendChild(el("div", "promo-row__meta", sw.note));
      row.appendChild(text);
      var toggle = el("label", "switch");
      var box = el("input");
      box.type = "checkbox";
      box.checked = !!s[sw.key];
      box.setAttribute("aria-label", sw.title);
      toggle.appendChild(box);
      toggle.appendChild(el("span", "switch__track"));
      toggle.appendChild(el("span", "switch__label", s[sw.key] ? "Shown" : "Hidden"));
      row.appendChild(toggle);
      host.appendChild(row);
      box.addEventListener("change", function () {
        box.disabled = true;
        status.textContent = "Saving…";
        var body = {};
        body[sw.key] = box.checked;
        fetch("/api/admin/hub-settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        }).then(renderHubSettings).catch(function (err) {
          box.checked = !box.checked;
          box.disabled = false;
          status.textContent = "Not saved: " + err.message;
          status.className = "promo-status err";
        });
      });
    });
    host.appendChild(status);
  }

  /* ── Hidden demos ─────────────────────────────────────────────────────
   * Liwei, 2026-10-06: hide a demo from the Hub from here, the way Featured
   * picks are made -- search, Hide; Unhide to bring it back. Admin sign-in
   * only. Nothing changes in SharePoint or Consensus, and a sync does not
   * bring a hidden demo back. */
  function loadHidden() {
    return fetch("/api/admin/hidden")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (items) { if (items) renderHidden(items); });
  }

  function renderHidden(items) {
    var host = $("hiddenDemos");
    if (!host) return;
    host.innerHTML = "";
    var head = el("div", "card-head");
    head.appendChild(el("h2", null, "Hidden from the Hub"));
    head.appendChild(el("span", "faint num", String(items.length)));
    host.appendChild(head);
    host.appendChild(el("p", "muted",
      "A hidden demo is gone from every list, search, Featured and the content dashboard, "
      + "for everyone; its old links say it is not in the Hub. SharePoint and Consensus are "
      + "not changed, and syncing does not bring it back."));
    var status = el("div", "promo-status faint");
    var act = function (method, url, body) {
      status.textContent = "Saving…";
      status.className = "promo-status faint";
      fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      }).then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
          throw new Error(b.detail || ("HTTP " + r.status));
        });
        return r.json();
      }).then(renderHidden).catch(function (err) {
        status.textContent = "Not saved: " + err.message;
        status.className = "promo-status err";
      });
    };

    var list = el("div");
    if (!items.length) list.appendChild(el("div", "faint", "Nothing hidden."));
    items.forEach(function (h) {
      var r = el("div", "promo-row");
      r.appendChild(el("span", "promo-row__n", ""));
      var info = el("div");
      info.appendChild(el("div", "promo-row__title", h.title || h.asset_id));
      info.appendChild(el("div", "promo-row__meta",
        [TYPE_WORD[h.type] || h.type, "hidden " + new Date(h.hidden_at).toLocaleString()]
          .filter(Boolean).join(" · ")));
      r.appendChild(info);
      var actions = el("div", "promo-row__actions");
      var unhide = el("button", null, "Unhide");
      unhide.addEventListener("click", function () {
        act("DELETE", "/api/admin/hidden/" + encodeURIComponent(h.asset_id));
      });
      actions.appendChild(unhide);
      r.appendChild(actions);
      list.appendChild(r);
    });
    host.appendChild(list);

    var add = el("div", "promo-add");
    var label = el("label", null, "Hide a demo");
    var input = el("input");
    input.type = "search";
    input.placeholder = "Search by title…";
    input.autocomplete = "off";
    label.appendChild(input);
    add.appendChild(label);
    var results = el("div", "promo-results");
    add.appendChild(results);
    host.appendChild(add);
    host.appendChild(status);

    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      timer = setTimeout(function () {
        results.innerHTML = "";
        if (q.length < 2) return;
        fetch("/api/assets?limit=8&q=" + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (page) {
            results.innerHTML = "";
            if (!page.items.length) { results.appendChild(el("div", "faint", "No demo matches.")); return; }
            page.items.forEach(function (a) {
              var r = el("div", "promo-row");
              r.appendChild(el("span", "promo-row__n", ""));
              var info = el("div");
              var title = el("a", "promo-row__title", a.title);
              title.href = "/#/asset/" + encodeURIComponent(a.id);
              title.target = "_blank";
              title.rel = "noopener";
              info.appendChild(title);
              info.appendChild(el("div", "promo-row__meta", promoMeta(a)));
              r.appendChild(info);
              var hide = el("button", null, "Hide");
              hide.addEventListener("click", function () {
                act("POST", "/api/admin/hidden", { asset_id: a.id });
              });
              var acts = el("div", "promo-row__actions");
              acts.appendChild(hide);
              r.appendChild(acts);
              results.appendChild(r);
            });
          });
      }, 250);
    });
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
        renderAutoSync(d.auto_sync);
        loadPromoted();
        loadHubSettings();
        loadHidden();
        contentLoaded = false;
        showTab(tabFromHash());
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

  /* How this browser got in -- a signed-in person with View Admin ("sso")
   * or the shared password ("password") -- and what it may do. */
  var session = { via: null, permissions: [] };

  function boot() {
    fetch("/api/admin/session").then(function (r) { return r.json(); })
      .then(function (s) {
        session = s;
        if (!s.signed_in) { show(s.configured ? "loginView" : "offView"); return; }
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
      if (r.ok) { $("p").value = ""; boot(); return; }
      // One message for both halves -- see the endpoint's own docstring.
      $("loginErr").textContent = r.status === 503
        ? "No admin is configured on this deployment."
        : "That username and password did not match.";
    });
  });

  $("logoutBtn").addEventListener("click", function () {
    // A signed-in person leaves the Hub session itself; the shared password
    // only drops its own cookie.
    if (session.via === "sso") { location.assign("/logout"); return; }
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
