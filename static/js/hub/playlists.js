/* Playlists (My Hub phase 2; A3, Liwei 2026-10-23 and 2026-11-12).
 *
 * The Save button on a demo's page opens a small menu: Favorites, then
 * each of your playlists, ticked if the demo is in it, then "New
 * playlist". A playlist has its own page (#/playlist/<id>): its owner
 * renames it, reorders it, takes demos out or deletes it; anyone signed in
 * who has the link sees the demos they may open themselves and can "Save a
 * copy". Copy link gives that link. A list inside the Hub, for colleagues --
 * not something to hand a customer (that is Consensus's DemoBoard).
 *
 * Part of the Hub page's script. */

import { buildCard, cardImage, paintCoverInto } from "./cards.js";
import { isFavorite, setFavorite } from "./favorites.js";
import { closeAdvancedSearch } from "./search.js";
import { report } from "./util.js";

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function api(method, url, body) {
  return fetch(url, {
    method: method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  }).then(function (r) {
    if (r.status === 204) return null;
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
      return d;
    });
  });
}

function playlistUrl(id) {
  return location.origin + location.pathname + "#/playlist/" + encodeURIComponent(id);
}

/* ── the Save menu on a demo's page ───────────────────────────────────── */
var openMenu = null;

function closeMenu() {
  if (openMenu) { openMenu.remove(); openMenu = null; }
  document.removeEventListener("click", outside, true);
  document.removeEventListener("scroll", closeOnScroll, true);
}

/* Scrolling the page moves the button away from a menu fixed on screen;
 * scrolling the menu's own list of playlists does not count. */
function closeOnScroll(e) {
  if (openMenu && !openMenu.contains(e.target)) closeMenu();
}

function outside(e) {
  if (openMenu && !openMenu.contains(e.target)
      && !(e.target.closest && e.target.closest("#vpSave"))) closeMenu();
}

function option(label, checked, onChange) {
  var row = el("label", "hub-save__opt");
  var box = el("input");
  box.type = "checkbox";
  box.checked = checked;
  box.addEventListener("change", function () { onChange(box.checked, box); });
  row.appendChild(box);
  row.appendChild(el("span", null, label));
  return row;
}

/* What the menu says after each change (Liwei, 2026-11-12: a tick alone
 * went unnoticed, and people reached for Create instead). */
function say(status, text, playlistId) {
  status.innerHTML = "";
  status.appendChild(el("span", "hub-save__ok", text));
  if (playlistId) {
    var open = el("a", null, "Open playlist");
    open.href = "#/playlist/" + encodeURIComponent(playlistId);
    open.addEventListener("click", closeMenu);
    status.appendChild(open);
  }
  status.hidden = false;
}

function drawMenu(menu, assetId, note) {
  menu.innerHTML = "";
  menu.appendChild(el("div", "hub-save__h", "Save to"));
  var status = el("div", "hub-save__status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.hidden = true;
  menu.appendChild(option("Favorites", isFavorite(assetId), function (on) {
    setFavorite(assetId, on).then(function () {
      say(status, on ? "✓ Added to Favorites" : "Removed from Favorites");
      refreshSaved(assetId);
    });
  }));
  var lists = el("div", "hub-save__lists");
  lists.textContent = "Loading your playlists…";
  menu.appendChild(lists);
  api("GET", "/api/me/playlists").then(function (d) {
    lists.innerHTML = "";
    d.items.forEach(function (p) {
      lists.appendChild(option(p.name, p.items.indexOf(assetId) >= 0, function (on, box) {
        api(on ? "PUT" : "DELETE", "/api/me/playlists/" + encodeURIComponent(p.id)
            + "/items/" + encodeURIComponent(assetId))
          .then(function () {
            say(status, on ? "✓ Added to " + p.name : "Removed from " + p.name,
                on ? p.id : null);
            refreshSaved(assetId);
          })
          .catch(function (err) { box.checked = !on; report(err.message, true); });
      }));
    });
  }).catch(function (err) { lists.textContent = "Could not load your playlists: " + err.message; });

  var add = el("form", "hub-save__new");
  var name = el("input");
  name.placeholder = "New playlist name";
  name.maxLength = 80;
  var go = el("button", "btn-ghost", "Create");
  go.type = "submit";
  add.appendChild(name);
  add.appendChild(go);
  add.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!name.value.trim()) { name.focus(); return; }
    go.disabled = true;
    api("POST", "/api/me/playlists", { name: name.value, items: [assetId] })
      .then(function (p) {
        drawMenu(menu, assetId, { text: "✓ Created " + p.name + " and added this demo",
                                  playlist: p.id });
        refreshSaved(assetId);
      })
      .catch(function (err) { go.disabled = false; report(err.message, true); });
  });
  menu.appendChild(add);
  menu.appendChild(status);
  if (note) say(status, note.text, note.playlist);
}

/* The Save button says "Saved" while the demo is in Favorites or any of
 * your playlists, so it shows at a glance, here and next time. */
var saveBtn = null;

function drawSaveButton(saved) {
  if (!saveBtn) return;
  saveBtn.classList.toggle("hub-saved", saved);
  saveBtn.innerHTML = saved
    ? '<svg class="orion-ico--sm orion-ico"><use href="#i-check"/></svg>Saved'
    : '<svg class="orion-ico--sm orion-ico"><use href="#i-plus"/></svg>Save';
  saveBtn.title = saved
    ? "In your Favorites or playlists (My Hub). Click to change."
    : "Save this demo to Favorites or one of your playlists (My Hub)";
}

// A star changed elsewhere on the page (beside the title, on a card).
document.addEventListener("hub:favorites", function (e) {
  if (saveBtn && e.detail && saveBtn.dataset.assetId === e.detail.id) refreshSaved(e.detail.id);
});

function refreshSaved(assetId) {
  if (!saveBtn || !assetId) return;
  saveBtn.dataset.assetId = assetId;
  api("GET", "/api/me/playlists").then(function (d) {
    if (saveBtn.dataset.assetId !== assetId) return;      // another demo by now
    drawSaveButton(isFavorite(assetId) || d.items.some(function (p) {
      return p.items.indexOf(assetId) >= 0;
    }));
  }).catch(function () { drawSaveButton(isFavorite(assetId)); });
}

/* Under the button, never cut off (2026-11-12): the menu hangs from the
 * page itself, placed where the button is on screen, so the content
 * area's own edge (it scrolls, and is narrower than the window) cannot
 * clip it; then kept inside both that area and the window, and above the
 * button when there is no room below. */
function clipRight(node) {
  var right = window.innerWidth;
  for (var n = node.parentElement; n && n !== document.body; n = n.parentElement) {
    var s = getComputedStyle(n);
    if (/(auto|scroll|hidden)/.test(s.overflowX + s.overflow)) {
      right = Math.min(right, n.getBoundingClientRect().left + n.clientWidth);
    }
  }
  return right;
}

function place(menu, button) {
  var r = button.getBoundingClientRect();
  var width = menu.offsetWidth, height = menu.offsetHeight;
  var right = clipRight(button) - 10;
  var left = Math.max(8, Math.min(r.left, right - width));
  var top = r.bottom + 6;
  if (top + height > window.innerHeight - 8 && r.top - height - 6 > 8) top = r.top - height - 6;
  menu.style.left = Math.round(left) + "px";
  menu.style.top = Math.round(top) + "px";
}

/* The Save button; reads the demo on show from `current()`, since the
 * demo page's actions row is reused from one demo to the next. */
function saveButton(current) {
  var b = el("button", "btn-ghost");
  b.type = "button";
  b.id = "vpSave";
  saveBtn = b;
  drawSaveButton(false);
  b.addEventListener("click", function (e) {
    e.stopPropagation();
    if (openMenu) { closeMenu(); return; }
    var asset = current();
    if (!asset) return;
    var menu = el("div", "hub-save");
    menu.setAttribute("role", "dialog");
    menu.setAttribute("aria-label", "Save to");
    document.body.appendChild(menu);
    openMenu = menu;
    drawMenu(menu, asset.id);
    place(menu, b);
    // Its height grows once the playlists are in: place it again then.
    setTimeout(function () { if (openMenu === menu) place(menu, b); }, 400);
    setTimeout(function () {
      document.addEventListener("click", outside, true);
      window.addEventListener("resize", closeMenu, { once: true });
      document.addEventListener("scroll", closeOnScroll, true);
    }, 0);
  });
  return b;
}

/* ── My Hub's "My playlists" ──────────────────────────────────────────── */
/* A playlist's cover: one demo's picture, two side by side, or four in a
 * grid; a demo without a picture shows its product's mark, as its card does. */
function cover(p) {
  var shown = p.covers.length >= 4 ? 4 : Math.min(p.covers.length, 2);
  var box = el("div", "hub-pl__cover hub-pl__cover--" + shown);
  p.covers.slice(0, shown).forEach(function (c) {
    var cell = el("div", "hub-pl__cell");
    if (c.thumbnail_url) cell.style.backgroundImage = "url(" + cardImage(c.thumbnail_url) + ")";
    box.appendChild(cell);
    paintCoverInto(cell, c);
  });
  if (!shown) box.appendChild(el("div", "hub-pl__empty", "Empty"));
  return box;
}

function renderMyPlaylists(host) {
  host.innerHTML = "";
  host.textContent = "Loading…";
  return api("GET", "/api/me/playlists").then(function (d) {
    host.innerHTML = "";
    var grid = el("div", "hub-pl__grid");
    d.items.forEach(function (p) {
      var tile = el("a", "hub-pl__tile");
      tile.href = "#/playlist/" + encodeURIComponent(p.id);
      tile.appendChild(cover(p));
      tile.appendChild(el("div", "hub-pl__name", p.name));
      tile.appendChild(el("div", "hub-pl__count", p.count + (p.count === 1 ? " demo" : " demos")));
      grid.appendChild(tile);
    });
    var add = el("button", "hub-pl__tile hub-pl__tile--new");
    add.type = "button";
    add.innerHTML = '<span class="hub-pl__plus">+</span><span>New playlist</span>';
    add.addEventListener("click", function () {
      var name = window.prompt("Name of the new playlist");
      if (!name || !name.trim()) return;
      api("POST", "/api/me/playlists", { name: name }).then(function (p) {
        location.hash = "#/playlist/" + encodeURIComponent(p.id);
      }).catch(function (err) { report(err.message, true); });
    });
    grid.appendChild(add);
    host.appendChild(grid);
    if (!d.items.length) {
      host.appendChild(el("div", "hub-me__note", "Save demos into playlists from a demo's "
        + "page (Save), then share a playlist's link with colleagues."));
    }
  }).catch(function (err) { host.textContent = "Could not load your playlists: " + err.message; });
}

/* ── a playlist's page (#/playlist/<id>) ──────────────────────────────── */
function buildPage() {
  var page = document.getElementById("hubPlPage");
  if (page) return page;
  page = el("div", "video-preview-page");
  page.id = "hubPlPage";
  page.innerHTML =
      '<button class="vp-back" type="button"><svg class="orion-ico orion-ico--sm">'
    +   '<use href="#i-chevron-left"/></svg>Back to My Hub</button>'
    + '<div class="vp-head"><div><div class="vp-title" id="plTitle"></div>'
    +   '<div class="orion-subtle" id="plSub"></div></div>'
    +   '<div class="vp-actions" id="plActions"></div></div>'
    + '<div class="hub-pl__page" id="plBody"></div>';
  var anchor = document.getElementById("videoPreviewPage");
  if (anchor) anchor.parentNode.insertBefore(page, anchor);
  else document.body.appendChild(page);
  page.querySelector(".vp-back").addEventListener("click", function () {
    location.hash = "#/me";
  });
  return page;
}

function action(label, cls, onClick) {
  var b = el("button", cls || "btn-ghost", label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function draw(d) {
  document.getElementById("plTitle").textContent = d.name;
  var n = d.items.length;
  document.getElementById("plSub").textContent = [n + (n === 1 ? " demo" : " demos"),
    d.mine ? "your playlist" : (d.owner_name ? "by " + d.owner_name : "shared with you"),
    d.updated_at ? "updated " + new Date(d.updated_at).toLocaleDateString(undefined,
      { month: "short", day: "numeric", year: "numeric" }) : null]
    .filter(Boolean).join(" · ");
  var acts = document.getElementById("plActions");
  acts.innerHTML = "";
  var copy = action("Copy link", "btn-ghost", function () {
    navigator.clipboard.writeText(playlistUrl(d.id));
    copy.textContent = "Copied";
    setTimeout(function () { copy.textContent = "Copy link"; }, 1500);
  });
  copy.title = "A link to this playlist on the Hub, for colleagues -- not for customers. "
    + "Each of them sees only the demos they may open.";
  acts.appendChild(copy);
  if (d.mine) {
    acts.appendChild(action("Rename", "btn-ghost", function () {
      var name = window.prompt("New name", d.name);
      if (!name || !name.trim() || name === d.name) return;
      api("PATCH", "/api/me/playlists/" + encodeURIComponent(d.id), { name: name })
        .then(function () { load(d.id); })
        .catch(function (err) { report(err.message, true); });
    }));
    var del = action("Delete", "btn-ghost hub-pl__danger", function () {
      if (del.dataset.armed !== "1") {
        del.dataset.armed = "1";
        del.textContent = "Delete it?";
        return;
      }
      api("DELETE", "/api/me/playlists/" + encodeURIComponent(d.id))
        .then(function () { location.hash = "#/me"; })
        .catch(function (err) { report(err.message, true); });
    });
    acts.appendChild(del);
  } else {
    acts.appendChild(action("Save a copy", "btn-primary-sm", function () {
      api("POST", "/api/me/playlists/" + encodeURIComponent(d.id) + "/copy")
        .then(function (p) { location.hash = "#/playlist/" + encodeURIComponent(p.id); })
        .catch(function (err) { report(err.message, true); });
    }));
  }

  var body = document.getElementById("plBody");
  body.innerHTML = "";
  if (d.mine) body.appendChild(addBox(d));
  if (d.unavailable) {
    body.appendChild(el("div", "hub-pl__note", d.unavailable + (d.unavailable === 1
      ? " demo in this playlist is" : " demos in this playlist are")
      + " not available to you" + (d.mine ? " any more (archived, hidden or restricted)." : ".")));
  }
  if (!n) {
    body.appendChild(el("div", "hub-me__empty", d.mine
      ? "Empty. Add demos with Save on a demo's page." : "Nothing here you can open."));
    return;
  }
  var order = d.items.map(function (a) { return a.id; });
  var list = el("div", "hub-pl__list");
  d.items.forEach(function (a, i) {
    var row = el("div", "hub-pl__row");
    row.appendChild(el("span", "hub-pl__n", String(i + 1)));
    var card = buildCard(a);
    card.addEventListener("click", function () {
      window.hubDetailReturn = "#/playlist/" + d.id;
    }, true);
    row.appendChild(card);
    if (d.mine) {
      var tools = el("div", "hub-pl__tools");
      var move = function (to) {
        var next = order.slice();
        next.splice(to, 0, next.splice(i, 1)[0]);
        api("PATCH", "/api/me/playlists/" + encodeURIComponent(d.id), { items: next })
          .then(function () { load(d.id); })
          .catch(function (err) { report(err.message, true); });
      };
      var up = action("↑", "btn-ghost hub-pl__move", function () { move(i - 1); });
      up.title = "Move up";
      up.disabled = i === 0;
      var down = action("↓", "btn-ghost hub-pl__move", function () { move(i + 1); });
      down.title = "Move down";
      down.disabled = i === n - 1;
      var out = action("Remove", "btn-ghost hub-pl__remove", function () {
        api("DELETE", "/api/me/playlists/" + encodeURIComponent(d.id) + "/items/"
            + encodeURIComponent(a.id))
          .then(function () { load(d.id); })
          .catch(function (err) { report(err.message, true); });
      });
      tools.appendChild(up);
      tools.appendChild(down);
      tools.appendChild(out);
      row.appendChild(tools);
    }
    list.appendChild(row);
  });
  body.appendChild(list);
}

/* Find demos and add them, without leaving the playlist (Liwei,
 * 2026-11-12), the way a music app suggests songs under a playlist. The
 * Hub's own search, so close matches count ("lambo"). */
function addBox(d) {
  var box = el("div", "hub-pl__add");
  var input = el("input");
  input.type = "search";
  input.placeholder = "Find demos to add…";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Find demos to add to this playlist");
  box.appendChild(input);
  var results = el("div", "hub-pl__results");
  box.appendChild(results);
  var inList = {};
  d.items.forEach(function (a) { inList[a.id] = true; });
  var timer = null;
  var seq = 0;
  input.addEventListener("input", function () {
    clearTimeout(timer);
    var q = input.value.trim();
    timer = setTimeout(function () {
      var mine = ++seq;
      results.innerHTML = "";
      if (q.length < 2) return;
      api("GET", "/api/assets?limit=8&q=" + encodeURIComponent(q)).then(function (page) {
        if (mine !== seq) return;
        results.innerHTML = "";
        if (!page.items.length) {
          results.appendChild(el("div", "hub-me__empty", "No demo matches."));
          return;
        }
        page.items.forEach(function (a) {
          var row = el("div", "hub-pl__hit");
          var pic = el("div", "hub-pl__hitpic");
          if (a.thumbnail_url) pic.style.backgroundImage = "url(" + cardImage(a.thumbnail_url) + ")";
          paintCoverInto(pic, a);
          row.appendChild(pic);
          var info = el("div", "hub-pl__hitinfo");
          info.appendChild(el("div", "hub-pl__hittitle", a.title));
          info.appendChild(el("div", "hub-pl__count", [TYPE_WORD[a.type] || a.type,
            (a.product_families || []).join(", ")].filter(Boolean).join(" · ")));
          row.appendChild(info);
          var add = action(inList[a.id] ? "Added" : "Add", "btn-ghost hub-pl__addbtn",
            function () {
              add.disabled = true;
              api("PUT", "/api/me/playlists/" + encodeURIComponent(d.id) + "/items/"
                  + encodeURIComponent(a.id))
                .then(function () {
                  inList[a.id] = true;
                  add.textContent = "Added";
                  load(d.id, input.value);
                })
                .catch(function (err) { add.disabled = false; report(err.message, true); });
            });
          add.disabled = !!inList[a.id];
          row.appendChild(add);
          results.appendChild(row);
        });
      }).catch(function (err) { results.textContent = "Search failed: " + err.message; });
    }, 250);
  });
  return box;
}

var TYPE_WORD = { video: "Video", ldk: "LDK", vdk: "VDK", vm: "Virtual Machine",
                  cad_model: "CAD Dataset" };

/* `keepSearch`: after adding from the search box, draw the list again
 * with the same search still open, so several can be added in a row. */
function load(id, keepSearch) {
  return api("GET", "/api/me/playlists/" + encodeURIComponent(id)).then(function (d) {
    draw(d);
    if (keepSearch) {
      var input = document.querySelector("#plBody .hub-pl__add input");
      if (input) {
        input.value = keepSearch;
        input.dispatchEvent(new Event("input"));
        input.focus();
      }
    }
  })
    .catch(function (err) {
      document.getElementById("plTitle").textContent = "Playlist";
      document.getElementById("plSub").textContent = "";
      document.getElementById("plActions").innerHTML = "";
      document.getElementById("plBody").textContent = /404|No such/.test(err.message)
        ? "This playlist does not exist any more." : "Could not open it: " + err.message;
    });
}

function openPlaylist(id) {
  var page = buildPage();
  closeAdvancedSearch();
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "none";
  if (thread) thread.style.display = "none";
  page.classList.add("active");
  window.scrollTo(0, 0);
  load(id);
}

function closePlaylist() {
  var page = document.getElementById("hubPlPage");
  if (!page || !page.classList.contains("active")) return;
  page.classList.remove("active");
  var detail = document.getElementById("videoPreviewPage");
  if (detail && detail.classList.contains("active")) return;
  var topbar = document.getElementById("mainTopbar");
  var thread = document.getElementById("mainThread");
  if (topbar) topbar.style.display = "";
  if (thread) thread.style.display = "";
}

export {
  closeMenu as closeSaveMenu, closePlaylist, openPlaylist, refreshSaved, renderMyPlaylists,
  saveButton
};
