/* Virtual machine pages: what a VM contains, its documents and
 * credentials, and the demos that use it.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { getJSON } from "./util.js";
import { TYPE_CHIP } from "./cards.js";
import { applyFilters, CONTROLS, navFilter } from "./filters.js";
import { exitOverlays } from "./nav.js";
import { fileDownloadUrl, filePreviewUrl, openAssetDetail } from "./detail.js";

/* ── virtual machines ─────────────────────────────────────────────────
 *
 * A VM's detail is the page the TDD team keeps for it on EXT-TDD, read
 * into sections by backend/integrations/graph/vm_pages.py. Pages there
 * have no shared template -- one has a dozen sections, another two and a
 * PDF -- so this renders whatever headings the page has, folded, with a
 * table of contents, rather than assuming any particular one exists.
 *
 * Nothing from SharePoint is ever inserted as HTML. Text goes in as text,
 * tables are built cell by cell, and a link is only made for http(s) and
 * ftp addresses.
 *
 * Credentials are "sealed" server-side: the public record carries a marker
 * where each one was, and /api/vms/<id>/credentials returns the content to
 * someone signed in. Until SSO is on, nobody on Azure is signed in, so the
 * marker says where the details can be found instead.
 */
var VIA_LABEL = {
  page: "Linked from the VM page",
  supports: "Listed on the page as a supported demo",
  inferred: "Same dataset and product — likely related, not stated"
};

function safeHref(url) {
  return /^(https?|ftp):\/\//i.test(url || "") ? url : null;
}

function vmEl(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function vmCard(icon, title) {
  var box = vmEl("div", "vp-card hub-vm-card");
  var head = vmEl("div", "vp-card__head");
  var t = vmEl("div", "vp-card__head-title");
  t.innerHTML = '<svg class="orion-ico"><use href="#' + icon + '"/></svg>';
  t.appendChild(document.createTextNode(title));
  head.appendChild(t);
  box.appendChild(head);
  return { box: box, head: head };
}

function assetLink(id, title, typeLabel) {
  var a = vmEl("a", "hub-vm-link");
  a.href = "#/asset/" + encodeURIComponent(id);
  if (typeLabel) a.appendChild(vmEl("span", "orion-badge", typeLabel));
  a.appendChild(vmEl("span", null, title));
  a.addEventListener("click", function (e) {
    e.preventDefault();
    openAssetDetail(id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  return a;
}

function renderVmCards(page, asset) {
  page.querySelectorAll(".hub-vm-card").forEach(function (n) { n.remove(); });
  // The Value Roadmap describes a demo's message; a VM has none to index.
  var drivers = document.getElementById("vpValueDrivers");
  var roadmap = drivers && drivers.closest(".vp-card");
  if (roadmap) roadmap.style.display = asset.type === "vm" ? "none" : "";

  var anchor = asset.type !== "vm"
    ? (document.getElementById("vpSections") || roadmap)
    : document.getElementById("vpDesc");
  if (!anchor) return;
  var cards = [];
  if (asset.type === "vm" && asset.vm) {
    cards.push(vmActionsCard(asset));
    cards.push(vmSupportsCard(asset));
    cards.push(vmContentsCard(asset));
    cards.push(vmDocumentsCard(asset));
  } else if ((asset.used_by_vms || []).length) {
    cards.push(usedByVmsCard(asset));
  }
  var after = anchor;
  cards.filter(Boolean).forEach(function (card) {
    after.insertAdjacentElement("afterend", card);
    after = card;
  });
}

function vmActionsCard(asset) {
  var vm = asset.vm;
  var c = vmCard("i-monitor", "Get this environment");
  var row = vmEl("div", "hub-vm-actions");
  (vm.actions || []).forEach(function (a) {
    var href = safeHref(a.url);
    if (!href) return;
    var btn = vmEl("a", a.kind === "cloud_portal" ? "btn-primary-sm" : "btn-ghost", a.label);
    btn.href = href;
    btn.target = "_blank";
    btn.rel = "noopener noreferrer";
    row.appendChild(btn);
  });
  if (safeHref(asset.web_url)) {
    var page = vmEl("a", "btn-ghost", "Open the full page in SharePoint");
    page.href = asset.web_url;
    page.target = "_blank";
    page.rel = "noopener noreferrer";
    row.appendChild(page);
  }
  c.box.appendChild(row);

  var facts = [];
  if (vm.version) facts.push("Version " + vm.version);
  if (asset.uploaded_at) {
    facts.push("Page updated " + asset.uploaded_at
               + (vm.page_modified_by ? " by " + vm.page_modified_by : ""));
  }
  if (vm.ptc_only) facts.push("PTC only — not for partners");
  if (facts.length) c.box.appendChild(vmEl("div", "hub-vm-facts", facts.join(" · ")));

  // Listings show only the newest version of a VM, so an older one is
  // reached from here -- and an older one says plainly that it is.
  var others = vm.other_versions || [];
  if (vm.superseded_by) {
    var newer = others.filter(function (o) { return o.asset_id === vm.superseded_by; })[0];
    var note = vmEl("div", "hub-vm-notice hub-vm-notice--older");
    note.appendChild(document.createTextNode("An older version. The current one is "));
    note.appendChild(assetLink(vm.superseded_by, newer ? newer.title : "the newest version"));
    c.box.appendChild(note);
  }
  if (others.length) {
    c.box.appendChild(vmEl("div", "vp-label hub-vm-sub",
      vm.superseded_by ? "Other versions" : "Older versions"));
    var list = vmEl("div", "hub-vm-list");
    others.forEach(function (o) {
      list.appendChild(assetLink(o.asset_id, o.title));
    });
    c.box.appendChild(list);
  }
  return c.box;
}

function vmSupportsCard(asset) {
  var vm = asset.vm;
  var demos = vm.related_demos || [];
  var others = vm.related_vms || [];
  var slices = vm.supports || [];
  if (!demos.length && !others.length && !slices.length) return null;
  var c = vmCard("i-box", "Demos you can run on it");

  slices.forEach(function (f) {
    // "Every PLM LDK" is a slice of the catalogue, not a list to scroll:
    // a button that applies the filter, with the count filled in once
    // known.
    var btn = vmEl("button", "btn-ghost hub-vm-slice", f.label + " →");
    btn.type = "button";
    btn.addEventListener("click", function () { openSlice(f); });
    c.box.appendChild(btn);
    var qs = [];
    if (f.segment) qs.push("segment=" + encodeURIComponent(f.segment));
    if (f.type) qs.push("type=" + encodeURIComponent(f.type));
    getJSON("/api/assets?limit=1&" + qs.join("&")).then(function (r) {
      btn.textContent = f.label + " (" + r.total + ") →";
    }).catch(function () {});
  });

  ["page", "supports", "inferred"].forEach(function (via) {
    var group = demos.filter(function (d) { return d.via === via; });
    if (!group.length) return;
    c.box.appendChild(vmEl("div", "vp-label hub-vm-sub", VIA_LABEL[via]));
    var list = vmEl("div", "hub-vm-list");
    group.forEach(function (d) {
      list.appendChild(assetLink(d.asset_id, d.title, (TYPE_CHIP[d.type] || [])[1] || d.type));
    });
    c.box.appendChild(list);
  });

  if (others.length) {
    c.box.appendChild(vmEl("div", "vp-label hub-vm-sub", "Related virtual machines"));
    var vms = vmEl("div", "hub-vm-list");
    others.forEach(function (v) { vms.appendChild(assetLink(v.asset_id, v.title, "VM")); });
    c.box.appendChild(vms);
  }
  return c.box;
}

function openSlice(f) {
  exitOverlays();
  CONTROLS.forEach(function (id) {
    var control = document.getElementById(id);
    if (control) control.value = "";
  });
  navFilter.umbrella = null;
  navFilter.sort = null;
  navFilter.tag = null;
  var type = document.getElementById("hubFilterType");
  var segment = document.getElementById("hubFilterSegment");
  if (type && f.type) type.value = f.type;
  if (segment && f.segment) segment.value = f.segment;
  applyFilters();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderVmBlocks(host, blocks, sectionId) {
  var list = null;
  (blocks || []).forEach(function (b, i) {
    if (b.sealed) {
      list = null;
      var lock = vmEl("div", "hub-vm-sealed", "🔒 Login detail hidden");
      lock.setAttribute("data-seal", sectionId + ":" + i);
      host.appendChild(lock);
      return;
    }
    if (b.kind === "li") {
      if (!list) { list = vmEl("ul", "hub-vm-ul"); host.appendChild(list); }
      var li = vmEl("li", null, b.text || "");
      appendBlockLinks(li, b.links);
      list.appendChild(li);
      return;
    }
    list = null;
    if (b.kind === "table" && b.rows && b.rows.length) {
      var wrap = vmEl("div", "hub-vm-table-wrap");
      var table = vmEl("table", "hub-vm-table");
      b.rows.forEach(function (row, r) {
        var tr = vmEl("tr");
        row.forEach(function (cell) { tr.appendChild(vmEl(r === 0 ? "th" : "td", null, cell)); });
        table.appendChild(tr);
      });
      wrap.appendChild(table);
      host.appendChild(wrap);
    } else {
      var p = vmEl("p", "hub-vm-p", b.text || "");
      appendBlockLinks(p, b.links);
      host.appendChild(p);
    }
  });
}

// The text already holds each link's words; link them where they stand
// rather than repeating them after the sentence. Only a link whose words
// are not in the text (an icon, an image) is appended.
function appendBlockLinks(host, links) {
  (links || []).forEach(function (l) {
    var href = safeHref(l.url);
    if (!href || !l.label) return;
    var a = vmEl("a", "hub-vm-inline-link", l.label);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    var node = [].slice.call(host.childNodes).find(function (n) {
      return n.nodeType === 3 && n.nodeValue.indexOf(l.label) !== -1;
    });
    if (node) {
      var rest = node.splitText(node.nodeValue.indexOf(l.label));
      rest.nodeValue = rest.nodeValue.slice(l.label.length);
      host.insertBefore(a, rest);
    } else {
      a.textContent = "↗ " + l.label;
      host.appendChild(document.createTextNode(" "));
      host.appendChild(a);
    }
  });
}

function vmContentsCard(asset) {
  var vm = asset.vm;
  var sections = vm.sections || [];
  if (!sections.length) return null;
  var c = vmCard("i-file-text", "What the VM page says");
  var toggle = vmEl("button", "btn-ghost hub-vm-toggle", "Expand all");
  toggle.type = "button";
  c.head.appendChild(toggle);

  var notice = null;
  if (vm.sealed_count) {
    notice = vmEl("div", "hub-vm-notice");
    c.box.appendChild(notice);
  }

  // Contents first: on a dozen-section page, "where is System
  // Requirements" is the question, and scrolling folded sections to find
  // it is the slow answer.
  if (sections.length > 2) {
    var toc = vmEl("div", "hub-vm-toc");
    sections.forEach(function (s) {
      if (!s.heading) return;
      var chip = vmEl("button", "orion-badge orion-badge--action", s.heading);
      chip.type = "button";
      chip.addEventListener("click", function () {
        var target = c.box.querySelector('[data-section="' + s.id + '"]');
        if (!target) return;
        target.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      toc.appendChild(chip);
    });
    c.box.appendChild(toc);
  }

  var details = [];
  sections.forEach(function (s, i) {
    var d = vmEl("details", "hub-vm-section");
    d.setAttribute("data-section", s.id);
    // The first section is open: it is usually what the environment IS --
    // unless that is only the description again, already shown above.
    var said = (s.blocks || []).map(function (b) { return b.text || ""; }).join(" ").trim();
    if (i === 0 && said && (asset.description || "").indexOf(said) === -1) d.open = true;
    d.appendChild(vmEl("summary", null, s.heading || "Overview"));
    var body = vmEl("div", "hub-vm-section__body");
    if (s.sealed) {
      var lock = vmEl("div", "hub-vm-sealed", "🔒 This section holds login details");
      lock.setAttribute("data-seal-section", s.id);
      body.appendChild(lock);
    } else {
      renderVmBlocks(body, s.blocks, s.id);
    }
    d.appendChild(body);
    c.box.appendChild(d);
    details.push(d);
  });

  toggle.addEventListener("click", function () {
    var open = details.some(function (d) { return !d.open; });
    details.forEach(function (d) { d.open = open; });
    toggle.textContent = open ? "Collapse all" : "Expand all";
  });

  if (notice) fillVmCredentials(asset, c.box, notice);
  return c.box;
}

function fillVmCredentials(asset, box, notice) {
  var count = asset.vm.sealed_count;
  var noun = count === 1 ? "login detail is" : "login details are";
  fetch("/api/vms/" + encodeURIComponent(asset.id) + "/credentials")
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (data) {
      box.querySelectorAll("[data-seal]").forEach(function (lock) {
        var block = (data.blocks || {})[lock.getAttribute("data-seal")];
        if (!block) return;
        var host = vmEl("div", "hub-vm-revealed");
        renderVmBlocks(host, [Object.assign({}, block, { sealed: false })], "x");
        lock.replaceWith(host);
      });
      box.querySelectorAll("[data-seal-section]").forEach(function (lock) {
        var blocks = (data.sections || {})[lock.getAttribute("data-seal-section")];
        if (!blocks) return;
        var host = vmEl("div", "hub-vm-revealed");
        renderVmBlocks(host, blocks.map(function (b) {
          return Object.assign({}, b, { sealed: false });
        }), "x");
        lock.replaceWith(host);
      });
      notice.className = "hub-vm-notice hub-vm-notice--open";
      notice.textContent = "Showing " + count + " login detail" + (count === 1 ? "" : "s")
        + " because you're signed in. Please keep them inside PTC.";
    })
    .catch(function () {
      getJSON("/api/auth/me").then(function (me) {
        notice.textContent = "";
        if (me.mode === "oidc") {
          notice.appendChild(document.createTextNode(count + " " + noun + " hidden. "));
          var a = vmEl("a", null, "Sign in to see them");
          a.href = "/login?next=" + encodeURIComponent(location.pathname + location.hash);
          notice.appendChild(a);
        } else {
          // Before SSO nobody can sign in here, so point at where the
          // details already live for anyone with access to the site.
          notice.appendChild(document.createTextNode(
            count + " " + noun + " kept off the Hub until sign-in is available. "));
          var href = safeHref(asset.web_url);
          if (href) {
            var link = vmEl("a", null, "They're on the SharePoint page");
            link.href = href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            notice.appendChild(link);
          }
        }
      }).catch(function () {
        notice.textContent = count + " " + noun + " hidden.";
      });
    });
}

function vmDocumentsCard(asset) {
  var docs = asset.vm.documents || [];
  if (!docs.length) return null;
  var c = vmCard("i-file-text", "Documents");
  var list = vmEl("div", "vp-files__list");
  docs.forEach(function (d) {
    var row = vmEl("div", "vp-file");
    var name = vmEl("a", "vp-file__name", d.name);
    // Mirrored files open through the Hub's own preview; the rest in
    // SharePoint, where the person's own access decides.
    var href = d.asset_id && d.item_id ? filePreviewUrl(d.asset_id, d.item_id) : safeHref(d.url);
    if (!href) return;
    name.href = href;
    name.target = "_blank";
    name.rel = "noopener noreferrer";
    row.appendChild(name);
    if (d.asset_id && d.item_id) {
      var dl = vmEl("a", "vp-file__download hub-vm-dl", "Download");
      dl.href = fileDownloadUrl(d.asset_id, d.item_id);
      row.appendChild(dl);
    }
    list.appendChild(row);
  });
  c.box.appendChild(list);
  return c.box;
}

function usedByVmsCard(asset) {
  var c = vmCard("i-monitor", "Runs on these virtual machines");
  var list = vmEl("div", "hub-vm-list");
  asset.used_by_vms.forEach(function (u) {
    var row = vmEl("div", "hub-vm-used");
    row.appendChild(assetLink(u.asset_id, u.title, "VM"));
    row.appendChild(vmEl("span", "hub-vm-via", u.via === "supports" ? "listed on the VM page"
                       : u.via === "page" ? "linked from the VM page"
                       : "likely — same dataset and product"));
    list.appendChild(row);
  });
  c.box.appendChild(list);
  return c.box;
}

/* The detail page's Details table: every tag the asset carries, one row
 * each, after Serge's mockup. Rows we hold nothing for are left out rather
 * than shown empty. Products are named in full -- this is where "and 2
 * more" on the card is answered. Tags stay clickable, as they were in the
 * old chip row (Liwei, 2026-09-16). */
var TYPE_LONG = { video: "Video", ldk: "Live Demo Kit (LDK)", vdk: "Video Demo Kit (VDK)",
                  vm: "Virtual Machine", cad_model: "CAD Dataset" };

export {
  renderVmCards, TYPE_LONG
};
