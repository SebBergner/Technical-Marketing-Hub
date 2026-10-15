/* The Overview tab: connected systems and their syncs, the daily
 * sync, sign-in mode, and the queues.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, card, el, localHour, openSheet, row, two, when } from "./util.js";
import { load } from "./main.js";

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
  // Who may do what is Users & groups' business; this says how people
  // prove who they are.
  var MODES = { oidc: "Microsoft sign-in", easyauth: "App Service sign-in",
                disabled: "Off (local only)" };
  row(c3, "Method", MODES[auth.mode] || auth.mode,
      auth.mode === "disabled" ? "pill--warn" : "pill--ok");
  (auth.warnings || []).forEach(function (w) {
    var p = el("p", "muted", w);
    p.style.fontSize = "12.5px";
    c3.appendChild(p);
  });
  host.appendChild(c3);
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

function renderQueues(d) {
  var host = $("queues");
  host.innerHTML = "";

  var c1 = card("Asset requests");
  row(c1, "Not yet in SharePoint", d.requests.unsynced);
  host.appendChild(c1);

  var c2 = card("Metadata proposals");
  row(c2, "Pending", d.proposals.pending);
  var p = el("p", "muted",
    "Suggested changes to SharePoint metadata. Deciding one needs Edit metadata "
    + "and writes the value into SharePoint under that person's name; there is "
    + "no review screen for them here yet.");
  p.style.cssText = "font-size:12.5px;margin:8px 0 0";
  c2.appendChild(p);
  host.appendChild(c2);
}

export {
  renderAutoSync, renderEnvironment, renderIntegrations, renderQueues
};
