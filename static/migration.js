/* The Migration page.
 *
 * Kept apart from hub-api.js and admin.js on purpose, like admin.js is kept
 * apart from hub-api.js: this page owns its own markup and shares nothing
 * that could break another page.
 *
 * A manager's view: how much has moved, when, how far the plan has got, and
 * what the content is. Everything on screen comes from one call per source --
 * /api/migration/brightcove/status for now. The page computes no figure of
 * its own; it only formats and draws what the server counted.
 */
(function () {
  "use strict";

  /* Same watch as admin.js: an expired SSO session answers an API call with
   * 401 plus X-Sign-In, and the page follows it back to sign-in. A 401
   * without the header means "admin password not entered" and is left alone. */
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
    ["loadingView", "loginView", "offView", "dashView"].forEach(function (id) {
      $(id).hidden = id !== view;
    });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function cardHead(parent, title, pillText, pillClass) {
    var head = el("div", "card-head");
    head.appendChild(el("h2", null, title));
    if (pillText) head.appendChild(el("span", "pill " + pillClass, pillText));
    parent.appendChild(head);
  }

  function renderEnvironment(env) {
    var isProd = env.slot && env.slot.toLowerCase() === "production";
    $("envBanner").className = "env" + (isProd ? " env--prod" : "");
    $("envTag").textContent = env.slot === "local" ? "Local" : env.slot;
    $("envDetail").textContent = env.site_name;
  }

  /* ── formatting ─────────────────────────────────────────────────────── */
  function fmtInt(n) { return (n || 0).toLocaleString("en-US"); }

  function demos(n) { return fmtInt(n) + (n === 1 ? " demo" : " demos"); }

  function fmtRuntime(sec) {
    if (!sec) return "0 min";
    var h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return h ? h + " h " + m + " min" : m + " min";
  }

  function fmtSize(bytes) {
    if (!bytes) return "0 GB";
    var gb = bytes / 1e9;
    return gb >= 1 ? gb.toFixed(1) + " GB" : Math.round(bytes / 1e6) + " MB";
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  /* A server timestamp in the VIEWER's time zone. App Service runs in UTC,
   * so the raw string showed 17:31 for an upload made at 13:31 EDT
   * (Liwei, 2026-09-29). */
  function fmtStamp(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d)) return iso.replace("T", " ").slice(0, 16);
    return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric",
                                       hour: "2-digit", minute: "2-digit" });
  }

  /* ── hover tooltip, shared by every chart mark ──────────────────────── */
  function hover(node, text) {
    node.addEventListener("mousemove", function (e) {
      var t = $("tip");
      t.textContent = text;
      t.hidden = false;
      t.style.left = (e.clientX + 12) + "px";
      t.style.top = (e.clientY + 12) + "px";
    });
    node.addEventListener("mouseleave", function () { $("tip").hidden = true; });
  }

  function tile(host, value, label, note, small) {
    var t = el("div", "tile");
    t.appendChild(el("div", "tile__n" + (small ? " tile__n--small" : ""), value));
    t.appendChild(el("div", "tile__l", label));
    if (note) t.appendChild(el("div", "tile__note", note));
    host.appendChild(t);
  }

  function table(headers, rows) {
    var wrap = el("div", "tablewrap"), t = el("table"), head = el("tr");
    headers.forEach(function (h) { head.appendChild(el("th", null, h)); });
    t.appendChild(head);
    rows.forEach(function (tr) { t.appendChild(tr); });
    wrap.appendChild(t);
    return wrap;
  }

  /* ── the parts of the Brightcove section ────────────────────────────── */
  function renderTiles(s, plan) {
    var host = $("bcTiles");
    host.innerHTML = "";
    tile(host, fmtInt(s.demos), "Demos migrated",
         plan.total ? "of " + fmtInt(plan.total) + " planned" : "Plan not loaded yet");
    tile(host, fmtRuntime(s.runtime_seconds), "Video runtime");
    tile(host, fmtSize(s.size_bytes), "Stored in SharePoint");
    tile(host, fmtInt(s.internal_only), "Internal only",
         s.demos ? Math.round(s.internal_only * 100 / s.demos) + "% of demos" : null);
    tile(host, fmtDate(s.last_migrated), "Last migration",
         s.first_migrated ? "First on " + fmtDate(s.first_migrated) : null, true);
    if (s.incomplete_folders) {
      tile(host, fmtInt(s.incomplete_folders), "Folders not yet demos",
           "No Demo Type set, so not counted");
    }
  }

  function renderProgress(s, plan, batches) {
    var c = $("bcProgress");
    c.innerHTML = "";
    var running = batches.filter(function (b) { return !b.unreadable && !b.finished_at; })[0];
    cardHead(c, "Progress", running ? "Run in progress" : null, "pill--warn");
    if (!plan.total) {
      c.appendChild(el("p", "empty",
        demos(s.demos) + " migrated so far. Progress against the plan appears " +
        "once the sheet of videos to migrate is loaded and a run states how many it covers."));
      return;
    }
    var pct = Math.min(100, Math.round(s.demos * 100 / plan.total));
    var meter = el("div", "meter");
    var fill = el("span");
    fill.style.width = pct + "%";
    meter.appendChild(fill);
    hover(meter, fmtInt(s.demos) + " of " + demos(plan.total) + " (" + pct + "%)");
    c.appendChild(meter);
    c.appendChild(el("div", "muted",
      pct + "% · " + fmtInt(s.demos) + " of " + demos(plan.total) + " · " +
      fmtInt(Math.max(0, plan.total - s.demos)) + " to go"));
  }

  /* One series, one hue: shares of demos, value and percent at the bar tip.
   * "Other" and "Not set" are drawn in the muted tone so the named values
   * carry the colour. */
  function renderShare(id, title, rows, note) {
    var c = typeof id === "string" ? $(id) : id;
    c.innerHTML = "";
    cardHead(c, title);
    if (!rows.length) { c.appendChild(el("p", "empty", "No demos yet.")); return; }
    var max = Math.max.apply(null, rows.map(function (r) { return r.count; }));
    var list = el("div", "hbars");
    rows.forEach(function (r) {
      var muted = r.name === "Other" || r.name === "Not set";
      var row = el("div", "hbar" + (muted ? " hbar--other" : ""));
      var name = el("div", "hbar__name", r.name);
      name.title = r.name;
      row.appendChild(name);
      var track = el("div", "hbar__track");
      var fill = el("div", "hbar__fill");
      fill.style.width = "calc((100% - 90px) * " + (r.count / max) + ")";
      track.appendChild(fill);
      track.appendChild(el("span", "hbar__val", fmtInt(r.count) + " · " + r.percent + "%"));
      row.appendChild(track);
      hover(row, r.name + ": " + demos(r.count) + " (" + r.percent + "% of demos)");
      list.appendChild(row);
    });
    c.appendChild(list);
    if (note) c.appendChild(el("p", "chart-note", note));
  }

  function renderColumns(id, title, points, note) {
    var c = $(id);
    c.innerHTML = "";
    cardHead(c, title);
    if (!points.length) { c.appendChild(el("p", "empty", "No demos yet.")); return; }
    var max = Math.max.apply(null, points.map(function (p) { return p.count; }));
    var cols = el("div", "cols"), axis = el("div", "col-axis");
    points.forEach(function (p) {
      var col = el("div", "col" + (p.unknown ? " col--unknown" : ""));
      col.appendChild(el("div", "col__val", fmtInt(p.count)));
      var bar = el("div", "col__bar");
      bar.style.height = Math.max(2, Math.round((p.count / max) * 100)) + "%";
      col.appendChild(bar);
      hover(col, p.tip);
      cols.appendChild(col);
      axis.appendChild(el("span", null, p.label));
    });
    c.appendChild(cols);
    c.appendChild(axis);
    if (note) c.appendChild(el("p", "chart-note", note));
  }

  function renderRecent(rows) {
    var c = $("bcRecent");
    c.innerHTML = "";
    cardHead(c, "Recently migrated");
    if (!rows.length) { c.appendChild(el("p", "empty", "Nothing migrated yet.")); return; }
    c.appendChild(table(["Demo", "Segment", "Product", "Published", "Migrated", "Audience"],
      rows.map(function (r) {
        var tr = el("tr"), td = el("td");
        if (r.web_url) {
          var a = el("a", null, r.title);
          a.href = r.web_url; a.target = "_blank"; a.rel = "noopener";
          td.appendChild(a);
        } else {
          td.textContent = r.title;
        }
        tr.appendChild(td);
        tr.appendChild(el("td", null, r.segment || "—"));
        tr.appendChild(el("td", null, (r.products || []).join(", ") || "—"));
        tr.appendChild(el("td", "num", r.published || "—"));
        tr.appendChild(el("td", "num", fmtDate(r.migrated)));
        tr.appendChild(el("td", null, r.customer_facing ? "Customer-facing" : "Internal"));
        return tr;
      })));
  }

  function renderRuns(list) {
    var c = $("bcBatches");
    c.innerHTML = "";
    cardHead(c, "Migration runs");
    if (!list.length) {
      c.appendChild(el("p", "empty",
        "No runs recorded yet. Each run of the migration tool is listed here with what it did."));
      return;
    }
    c.appendChild(table(["Started", "Finished", "Kind", "Result"], list.map(function (b) {
      var tr = el("tr");
      if (b.unreadable) {
        var td = el("td", null, b.batch_id + ": this run's log could not be read.");
        td.colSpan = 4;
        tr.appendChild(td);
        return tr;
      }
      tr.appendChild(el("td", "num", fmtStamp(b.started_at) || "—"));
      tr.appendChild(el("td", "num", fmtStamp(b.finished_at) || "Still running"));
      tr.appendChild(el("td", null, b.mode === "dry-run" ? "Check only (no upload)" : "Upload"));
      tr.appendChild(el("td", "num", Object.keys(b.counts || {}).map(function (k) {
        return k + " " + fmtInt(b.counts[k]);
      }).join(" · ") || "—"));
      return tr;
    })));
  }

  function renderBrightcove(d) {
    $("bcNote").textContent = "Gallery videos moved into the SharePoint library " +
      d.library.name + ", their permanent home. Figures are read live from that library.";
    var notice = $("bcNotice"), body = $("bcBody");
    var problem = !d.graph.configured
      ? "SharePoint is not connected on this deployment, so there is nothing to show."
      : d.graph.error ? "SharePoint could not be read: " + d.graph.error
      : d.library.found === false
        ? "The library " + d.library.name + " does not exist on the site yet."
      : null;
    notice.hidden = !problem;
    body.hidden = !!problem;
    notice.innerHTML = "";
    if (problem) { notice.appendChild(el("p", "empty", problem)); return; }

    var s = d.summary;
    renderTiles(s, d.plan);
    renderProgress(s, d.plan, d.batches || []);
    renderShare("bcSegments", "Segment", s.segments,
      "A demo can belong to several segments, so shares can add up to more than 100%.");
    renderShare("bcProducts", "Product", s.products,
      "Top products; the rest are grouped as Other. A demo can name several products.");
    renderColumns("bcWeeks", "Migrated per week", s.by_week.map(function (w) {
      return { count: w.count, label: fmtDate(w.week_start).replace(/ \d{4}$/, ""),
               tip: "Week of " + fmtDate(w.week_start) + ": " + demos(w.count) };
    }));
    renderColumns("bcYears", "Originally published", s.by_publish_year.map(function (y) {
      return { count: y.count, label: y.year ? String(y.year) : "Unknown", unknown: !y.year,
               tip: (y.year ? "Published " + y.year : "No publish date") + ": " +
                    demos(y.count) };
    }), "The year each video first appeared in the Gallery, which is how old the content is.");
    renderRecent(s.recent);
    renderRuns(d.batches || []);
  }

  /* ── new migration: upload → preview → start → progress ───────────────
   *
   * Who may start a run (Liwei, 2026-09-29): an SSO curator, recorded as
   * themselves, or the shared admin sign-in with a typed operator name.
   * The server enforces both; the form only asks for what it will need. */
  var LIB = null, ACTOR = null, RUNNER = false, ACTIVE = null;
  var sheetId = null, previewTimer = null, runTimer = null, runId = null, sample = null;

  function api(method, url, body) {
    var opts = { method: method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
        return j;
      });
    });
  }

  function box(cls, text) { return el("div", cls, text); }

  function renderUpload(d) {
    var c = $("bcUpload");
    c.innerHTML = "";
    cardHead(c, "1 · Gallery workbook");
    var drop = el("label", "drop");
    var input = el("input");
    input.type = "file";
    input.accept = ".xlsx";
    drop.appendChild(input);
    drop.appendChild(el("div", null, "Drop the .xlsx here, or click to choose it"));
    drop.appendChild(el("div", "faint", "Rows ticked Delete? / Archive? are left out. Nothing is written yet."));
    ["dragenter", "dragover"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) {
      if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", function () { if (input.files[0]) uploadFile(input.files[0]); });
    c.appendChild(drop);
    var msg = el("p", "empty");
    msg.id = "uploadMsg";
    msg.style.marginTop = "8px";
    c.appendChild(msg);
    if ((d.sheets || []).length) {
      var row = el("div", "row");
      row.style.marginTop = "6px";
      row.appendChild(el("span", "muted", "Earlier uploads:"));
      var sel = el("select");
      // Nothing is opened on arrival: a previous upload shown by default
      // read as the migration in hand (Liwei, 2026-09-29). Open one on purpose.
      var none = el("option", null, "— open an earlier upload —");
      none.value = "";
      sel.appendChild(none);
      d.sheets.forEach(function (s) {
        var o = el("option", null, (s.filename || s.sheet_id) + " · " + (fmtStamp(s.uploaded_at) || "") +
                    (s.counts ? " · " + fmtInt(s.counts.new) + " new" : ""));
        o.value = s.sheet_id;
        sel.appendChild(o);
      });
      sel.value = sheetId || "";
      sel.addEventListener("change", function () {
        if (sel.value) { openSheet(sel.value); return; }
        sheetId = null;
        clearTimeout(previewTimer);
        $("uploadMsg").textContent = "";
        $("bcPreview").hidden = true;
        $("bcStart").hidden = true;
      });
      row.appendChild(sel);
      c.appendChild(row);
    }
  }

  function uploadFile(file) {
    $("uploadMsg").textContent = "Uploading " + file.name + "…";
    var form = new FormData();
    form.append("file", file);
    fetch("/api/migration/brightcove/sheets", { method: "POST", body: form })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
          return j;
        });
      })
      .then(function (j) { openSheet(j.sheet_id); })
      .catch(function (err) { $("uploadMsg").textContent = "Upload failed: " + err.message; });
  }

  function openSheet(id) {
    sheetId = id;
    clearTimeout(previewTimer);
    $("bcPreview").hidden = true;
    $("bcStart").hidden = true;
    pollPreview();
  }

  function pollPreview() {
    api("GET", "/api/migration/brightcove/sheets/" + encodeURIComponent(sheetId))
      .then(function (p) {
        var msg = $("uploadMsg");
        if (p.status === "running") {
          var pr = p.progress || {};
          msg.textContent = "Checking every video against SharePoint and Brightcove… " +
            fmtInt(pr.done) + " / " + fmtInt(pr.total);
          previewTimer = setTimeout(pollPreview, 2000);
          return;
        }
        if (p.status === "error") {
          msg.textContent = "";
          msg.appendChild(box("badbox", "The preview failed: " + p.error));
          return;
        }
        var by = (p.uploaded_by || "—").replace(/^curator:/, "")
          .replace(/^admin-session$/, "the shared admin account");
        msg.textContent = (p.filename || "Workbook") + " · uploaded " + (fmtStamp(p.uploaded_at) || "") +
          " by " + by + " · checked " + (fmtStamp(p.computed_at) || "");
        renderPreview(p);
        renderStart(p);
      })
      .catch(function (err) { $("uploadMsg").textContent = "Could not load the preview: " + err.message; });
  }

  function renderPreview(p) {
    $("bcPreview").hidden = false;
    var t = $("pvTiles");
    t.innerHTML = "";
    var c = p.counts || {};
    tile(t, fmtInt(c.scope), "2 · This migration", "videos from " + fmtInt(c.rows) + " kept rows");
    tile(t, fmtInt(c.new), "Ready to go now", "valid and not yet in the library");
    tile(t, fmtInt((c.invalid || 0) + (c.conflict || 0)), "Need fixing first", "see Problems below");
    tile(t, fmtInt(c.existing), "Already in the library", "skipped, never overwritten");
    tile(t, fmtInt((p.sheet || {}).left_out), "Left out", "ticked Delete? / Archive?");
    tile(t, fmtSize(p.volume_bytes), "To upload", fmtRuntime(p.runtime_seconds) + " of video · " +
         fmtSize(p.volume_ready_bytes) + " ready now");
    tile(t, "~" + (p.estimate_hours || 0) + " h", "Estimated time",
         "at " + p.estimate_rate_mb_s + " MB/s, measured from a workstation", true);
    renderShare($("pvSegments"), "Segment", p.segments || [],
      "Of every video in this migration, including those that need fixing. A video can have several segments.");
    renderShare($("pvProducts"), "Hub Products", p.hub_products || [],
      "A video can name several products.");
    renderShare($("pvTypes"), "Video Type", p.video_types || []);
    renderShare($("pvGalleries"), "Gallery", p.galleries || []);
    renderShare($("pvCustomers"), "Named customer", p.customers || [],
      (p.customers || []).length ? null : "No named customers.");
    renderShare($("pvAudience"), "Audience", p.audience || []);

    var pc = $("pvProblems");
    pc.innerHTML = "";
    var groups = p.problems || [];
    cardHead(pc, "Problems", groups.length ? fmtInt(groups.reduce(function (n, g) { return n + g.count; }, 0)) : "None",
             groups.length ? "pill--warn" : "pill--ok");
    var s = p.sheet || {};
    if (!s.has_segment_column) pc.appendChild(box("warnbox", "The workbook has no Segment column."));
    if (!s.has_customer_facing_column) {
      pc.appendChild(box("warnbox", "The workbook has no Customer Facing column; every video needs one (HLR-A9)."));
    }
    if (!groups.length) {
      pc.appendChild(el("p", "empty", "No problems: every kept row can be migrated."));
      return;
    }
    pc.appendChild(el("p", "empty",
      "Rows with a problem are not migrated; the others are not held up by them."));
    groups.forEach(function (g) {
      var d = el("details");
      var sum = el("summary", null, g.reason);
      sum.appendChild(el("span", "pill pill--warn", fmtInt(g.count)));
      d.appendChild(sum);
      d.appendChild(table(["Row", "Brightcove ID", "Title", "Detail"], g.rows.slice(0, 200).map(function (r) {
        var tr = el("tr");
        tr.appendChild(el("td", "num", r.row));
        tr.appendChild(el("td", "mono", r.brightcove_id));
        tr.appendChild(el("td", null, r.title));
        tr.appendChild(el("td", null, r.detail));
        return tr;
      })));
      pc.appendChild(d);
    });
    var a = el("a", null, "Download every problem as CSV (to send back to the sheet's owner)");
    a.href = "/api/migration/brightcove/sheets/" + encodeURIComponent(p.sheet_id) + "/problems.csv";
    a.style.cssText = "display:inline-block;margin-top:10px;font-size:13px";
    pc.appendChild(a);
  }

  function renderStart(p) {
    var c = $("bcStart");
    c.hidden = false;
    c.innerHTML = "";
    var n = (p.counts || {}).new || 0;
    cardHead(c, "3 · Start the migration");
    if (!RUNNER) {
      c.appendChild(box("warnbox", "Runs are switched off on this deployment. They run on the one " +
        "deployment where MIGRATION_RUNNER_ENABLED is set (staging)."));
      return;
    }
    if (ACTIVE) {
      c.appendChild(box("warnbox", "A run is in progress. Wait for it, or pause it below."));
      return;
    }
    if (!n) { c.appendChild(el("p", "empty", "Nothing new to migrate in this workbook.")); return; }
    var form = el("div", "form");
    var choice = el("div", "choice");
    function radio(value, text, checked) {
      var l = el("label"), i = el("input");
      i.type = "radio"; i.name = "mode"; i.value = value; i.checked = checked;
      l.appendChild(i); l.appendChild(document.createTextNode(text));
      choice.appendChild(l);
      return i;
    }
    var pilot = radio("pilot", "Pilot: the first " + Math.min(10, n) + " (review them in SharePoint first)", n > 10);
    radio("all", "All " + fmtInt(n) + " videos", n <= 10);
    form.appendChild(choice);

    // The library is fixed (Liwei, 2026-09-29): shown, not asked for.
    form.appendChild(el("p", "empty", "Target library: " + LIB + " — the only library this page writes to."));

    var par = el("select");
    [1, 2, 3, 4, 5].forEach(function (k) {
      var o = el("option", null, k === 1 ? "1 (one at a time)" : String(k));
      o.value = String(k);
      par.appendChild(o);
    });
    par.value = "3";
    var lp = el("label", null, "Parallel uploads");
    lp.appendChild(par);
    form.appendChild(lp);

    var operator = null;
    if (ACTOR && ACTOR.kind === "admin-session") {
      operator = el("input");
      operator.type = "text";
      operator.placeholder = "Your name";
      var lo = el("label", null, "Your name — signed in with the shared admin account, so the run is recorded under the name you type");
      lo.appendChild(operator);
      form.appendChild(lo);
    } else if (ACTOR) {
      form.appendChild(el("p", "empty", "The run is recorded as " + ACTOR.name + "."));
    }
    var go = el("button", "btn-primary", "Start migration");
    go.disabled = true;
    function check() {
      go.disabled = !!(operator && operator.value.trim().length < 2);
    }
    check();
    if (operator) operator.addEventListener("input", check);
    var err = el("p", "err");
    go.addEventListener("click", function () {
      go.disabled = true;
      err.textContent = "";
      api("POST", "/api/migration/brightcove/runs", {
        sheet_id: p.sheet_id,
        limit: pilot.checked ? Math.min(10, n) : null,
        operator: operator ? operator.value.trim() : null,
        parallel: parseInt(par.value, 10)
      }).then(function (j) {
        ACTIVE = j.batch_id;
        c.hidden = true;
        trackRun(j.batch_id);
      }).catch(function (e) { err.textContent = e.message; check(); });
    });
    var row = el("div", "row");
    row.appendChild(go);
    form.appendChild(row);
    form.appendChild(err);
    c.appendChild(form);
  }

  var RUN_STATE = { running: ["Running", "pill--warn"], paused: ["Paused", "pill--off"],
                    finished: ["Finished", "pill--ok"], stopped: ["Stopped", "pill--bad"] };
  var ITEM_STATE = { pending: "Waiting", folder_created: "Starting", uploading: "Uploading",
                     uploaded: "Writing metadata", done: "Done", failed: "Failed",
                     existing: "Already there" };

  function trackRun(id) {
    runId = id;
    sample = null;
    clearTimeout(runTimer);
    pollRun();
  }

  function pollRun() {
    api("GET", "/api/migration/brightcove/runs/" + encodeURIComponent(runId))
      .then(function (s) {
        renderRun(s);
        if (s.state === "running") {
          runTimer = setTimeout(pollRun, 3000);
        } else {
          ACTIVE = null;
          if (s.state === "finished") refreshOverview();
        }
      })
      .catch(function (err) { console.error("[migration] run", err); runTimer = setTimeout(pollRun, 6000); });
  }

  function renderRun(s) {
    var c = $("bcRun");
    c.hidden = false;
    c.innerHTML = "";
    var st = RUN_STATE[s.state] || [s.state, "pill--off"];
    cardHead(c, "4 · Progress", s.pause_requested && s.state === "running" ? "Pausing after this video" : st[0],
             s.pause_requested && s.state === "running" ? "pill--off" : st[1]);
    c.appendChild(el("p", "empty", "Started " + (fmtStamp(s.started_at) || "") + " by " + (s.operator || "—") +
      " · " + (s.parallel || 1) + " at a time" +
      (s.finished_at ? " · finished " + fmtStamp(s.finished_at) : "")));
    if (s.stopped_error) c.appendChild(box("badbox", "The run stopped: " + s.stopped_error));

    var done = (s.counts || {}).done || 0;
    var pct = s.bytes_total ? Math.min(100, Math.round(s.bytes_done * 100 / s.bytes_total)) : 0;
    var meter = el("div", "meter");
    var fill = el("span");
    fill.style.width = pct + "%";
    meter.appendChild(fill);
    c.appendChild(meter);
    var now = Date.now(), eta = "";
    if (s.state === "running") {
      if (sample && s.bytes_done > sample.bytes) {
        var rate = (s.bytes_done - sample.bytes) / ((now - sample.t) / 1000);
        sample.rate = sample.rate ? sample.rate * 0.7 + rate * 0.3 : rate;
      }
      if (!sample || s.bytes_done !== sample.bytes) {
        sample = { t: now, bytes: s.bytes_done, rate: sample && sample.rate };
      }
      if (sample.rate) {
        var left = (s.bytes_total - s.bytes_done) / sample.rate;
        eta = " · " + (sample.rate / 1e6).toFixed(1) + " MB/s · about " +
              (left > 3600 ? (left / 3600).toFixed(1) + " h" : Math.max(1, Math.round(left / 60)) + " min") + " left";
      }
    }
    c.appendChild(el("div", "muted", pct + "% · " + fmtInt(done) + " of " + demos(s.total) + " done · " +
      fmtSize(s.bytes_done) + " of " + fmtSize(s.bytes_total) + eta));
    if (s.state === "running") {
      // Several at once with parallel uploads.
      (s.current || []).forEach(function (cur) {
        var part = cur.size ? " " + Math.round((cur.uploaded_bytes || 0) * 100 / cur.size) + "%" : "";
        c.appendChild(el("p", "empty", "Now: " + cur.title + " — " +
          (ITEM_STATE[cur.status] || cur.status) + part));
      });
    }

    var row = el("div", "row");
    row.style.margin = "10px 0";
    if (s.state === "running" && !s.pause_requested) {
      var pb = el("button", null, "Pause after the current video");
      pb.addEventListener("click", function () {
        pb.disabled = true;
        api("POST", "/api/migration/brightcove/runs/" + encodeURIComponent(s.batch_id) + "/pause")
          .then(pollRun);
      });
      row.appendChild(pb);
    }
    if ((s.state === "paused" || s.state === "stopped") && RUNNER) {
      var who = null;
      if (ACTOR && ACTOR.kind === "admin-session") {
        who = el("input");
        who.type = "text";
        who.placeholder = "Your name (shared admin account)";
        who.style.cssText = "font:inherit;font-size:13.5px;padding:6px 10px;border-radius:8px;" +
                            "border:1px solid var(--border);background:var(--bg);color:var(--ink)";
        row.appendChild(who);
      }
      var rb = el("button", "btn-primary", "Resume");
      var rerr = el("span", "err");
      rb.addEventListener("click", function () {
        rb.disabled = true;
        api("POST", "/api/migration/brightcove/runs/" + encodeURIComponent(s.batch_id) + "/resume",
            { operator: who ? who.value.trim() : null })
          .then(function () { ACTIVE = s.batch_id; trackRun(s.batch_id); })
          .catch(function (e) { rerr.textContent = e.message; rb.disabled = false; });
      });
      row.appendChild(rb);
      row.appendChild(rerr);
    }
    c.appendChild(row);

    c.appendChild(table(["Video", "Status", "Size", ""], (s.items || []).map(function (i) {
      var tr = el("tr");
      var td = el("td");
      if (i.web_url && i.status === "done") {
        var a = el("a", null, i.title);
        a.href = i.web_url; a.target = "_blank"; a.rel = "noopener";
        td.appendChild(a);
      } else {
        td.textContent = i.title;
      }
      tr.appendChild(td);
      var cls = i.status === "done" ? "pill--ok" : i.status === "failed" ? "pill--bad"
              : i.status === "pending" || i.status === "existing" ? "pill--off" : "pill--warn";
      var sc = el("td");
      sc.appendChild(el("span", "pill " + cls, ITEM_STATE[i.status] || i.status));
      tr.appendChild(sc);
      tr.appendChild(el("td", "num", i.size ? fmtSize(i.size) : "—"));
      tr.appendChild(el("td", null, i.error || ""));
      return tr;
    })));
  }

  function renderMigrate(d) {
    LIB = d.library.name;
    ACTOR = d.actor;
    RUNNER = d.runner_enabled;
    ACTIVE = d.active_run;
    renderUpload(d);
    // Only what this visit opened is shown again (Refresh keeps it).
    if (sheetId) openSheet(sheetId);
    // A run is shown unasked only when it needs someone: going, or paused /
    // stopped with videos left. Finished runs are in "Migration runs" below.
    var latest = d.latest_run;
    if (d.active_run) {
      trackRun(d.active_run);
    } else if (latest && (latest.state === "paused" || latest.state === "stopped")) {
      runId = latest.batch_id;
      renderRun(latest);
    } else if (latest && runId === latest.batch_id) {
      renderRun(latest);                       // the run this visit started
    } else {
      $("bcRun").hidden = true;
    }
  }

  /* After a run finishes: redraw the library overview in place. */
  function refreshOverview() {
    api("GET", "/api/migration/brightcove/status").then(function (d) { renderBrightcove(d); });
  }

  function load() {
    show("loadingView");
    fetch("/api/migration/brightcove/status")
      .then(function (r) {
        if (r.status === 401) {
          // Neither an SSO curator nor the admin sign-in: offer the form, or
          // say plainly that this deployment has no admin account.
          return fetch("/api/admin/session").then(function (x) { return x.json(); })
            .then(function (s) { show(s.configured ? "loginView" : "offView"); return null; });
        }
        if (r.status === 403) {
          show("loginView");
          $("loginErr").textContent = "Your account is signed in but lacks the curator role. " +
            "Use the admin sign-in, or ask to be added as a curator.";
          return null;
        }
        if (r.status === 503) { show("offView"); return null; }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        renderEnvironment(d.environment);
        renderMigrate(d);
        renderBrightcove(d);
        $("loadedAt").textContent = "Loaded " + new Date().toLocaleString();
        show("dashView");
      })
      .catch(function (err) {
        console.error("[migration]", err);
        window.alert("Could not load the migration status: " + err.message);
      });
  }

  function boot() {
    load();
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

  boot();
})();
