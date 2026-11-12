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

function drawMenu(menu, assetId) {
  menu.innerHTML = "";
  menu.appendChild(el("div", "hub-save__h", "Save to"));
  menu.appendChild(option("Favorites", isFavorite(assetId), function (on) {
    setFavorite(assetId, on);
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
      .then(function () { drawMenu(menu, assetId); })
      .catch(function (err) { go.disabled = false; report(err.message, true); });
  });
  menu.appendChild(add);
}

/* The Save button; reads the demo on show from `current()`, since the
 * demo page's actions row is reused from one demo to the next. */
function saveButton(current) {
  var b = el("button", "btn-ghost");
  b.type = "button";
  b.id = "vpSave";
  b.title = "Save this demo to Favorites or one of your playlists (My Hub)";
  b.innerHTML = '<svg class="orion-ico--sm orion-ico"><use href="#i-plus"/></svg>Save';
  b.addEventListener("click", function (e) {
    e.stopPropagation();
    if (openMenu) { closeMenu(); return; }
    var asset = current();
    if (!asset) return;
    var menu = el("div", "hub-save");
    menu.setAttribute("role", "dialog");
    menu.setAttribute("aria-label", "Save to");
    b.parentNode.insertBefore(menu, b.nextSibling);
    menu.style.left = b.offsetLeft + "px";        // under the button
    openMenu = menu;
    drawMenu(menu, asset.id);
    setTimeout(function () { document.addEventListener("click", outside, true); }, 0);
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

function load(id) {
  return api("GET", "/api/me/playlists/" + encodeURIComponent(id)).then(draw)
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

export { closeMenu as closeSaveMenu, closePlaylist, openPlaylist, renderMyPlaylists, saveButton };
