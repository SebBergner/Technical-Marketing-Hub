/* Favourites: the star on every card and on a demo's page (A3; Liwei,
 * 2026-10-28 and 2026-11-12). Starred demos are listed on My Hub.
 *
 * The ids are read once (GET /api/me/favorites) and kept here; a star
 * flips at once and the server is told after, and every star for the same
 * demo on the page follows. A star that could not be saved flips back.
 *
 * Part of the Hub page's script. */

var ids = null;                 // Set of asset ids, once read
var loading = null;

function load() {
  if (loading) return loading;
  loading = fetch("/api/me/favorites", { headers: { "Accept": "application/json" } })
    .then(function (r) { return r.ok ? r.json() : { ids: [] }; })
    .then(function (d) { ids = new Set(d.ids || []); paintAll(); return ids; })
    .catch(function () { ids = new Set(); return ids; });
  return loading;
}

function isFavorite(id) {
  return !!ids && ids.has(id);
}

function paint(button, on) {
  button.classList.toggle("hub-star--on", on);
  button.setAttribute("aria-pressed", String(on));
  var label = on ? "Remove from favorites" : "Add to favorites";
  button.title = label;
  button.setAttribute("aria-label", label);
}

function paintAll(id) {
  document.querySelectorAll(".hub-star").forEach(function (b) {
    if (!id || b.dataset.assetId === id) paint(b, isFavorite(b.dataset.assetId));
  });
}

function setFavorite(id, on) {
  if (!ids) ids = new Set();
  if (on) ids.add(id); else ids.delete(id);
  paintAll(id);
  return fetch("/api/me/favorites/" + encodeURIComponent(id), { method: on ? "PUT" : "DELETE" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (d) {
      ids = new Set(d.ids || []);
      paintAll(id);
      document.dispatchEvent(new CustomEvent("hub:favorites", { detail: { id: id, on: on } }));
    })
    .catch(function () {
      if (on) ids.delete(id); else ids.add(id);
      paintAll(id);
    });
}

/* A star button for one demo. `cls` adds a placement class. */
function starButton(id, cls) {
  var b = document.createElement("button");
  b.type = "button";
  b.className = "hub-star" + (cls ? " " + cls : "");
  b.dataset.assetId = id;
  b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/></svg>';
  paint(b, isFavorite(id));
  b.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    setFavorite(id, !isFavorite(id));
  });
  load();
  return b;
}

export { isFavorite, load as loadFavorites, setFavorite, starButton };
