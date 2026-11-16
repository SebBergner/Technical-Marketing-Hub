/* Which Hub features people open (A16; Liwei, 2026-11-16).
 *
 * The Hub is one page: My Hub, the User guide, Get help and the rest only
 * change the address bar's "#", so the server cannot see them. This tells it,
 * once per feature per browser per day (the server and the report keep the
 * same rule). The names are a fixed list the server also holds
 * (backend/services/feature_usage.py); anything else it drops.
 *
 * Fire and forget: a failure here must never touch the page.
 *
 * Part of the Hub page's script; static/js/hub/main.js loads it. */

var said = new Set();

function today() {
  return new Date().toISOString().slice(0, 10);
}

function noteFeature(name) {
  var key = "hub-feature:" + name + ":" + today();
  if (said.has(key)) return;
  said.add(key);
  try {
    if (window.localStorage.getItem(key)) return;
    // Yesterday's notes are of no use.
    Object.keys(window.localStorage).forEach(function (k) {
      if (k.indexOf("hub-feature:") === 0 && k.slice(-10) !== today()) window.localStorage.removeItem(k);
    });
    window.localStorage.setItem(key, "1");
  } catch (err) { /* private window: the in-memory note still stops repeats */ }
  try {
    fetch("/api/assets/feature-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feature: name }),
      keepalive: true
    }).catch(function () {});
  } catch (err) { /* nothing to do */ }
}

/* The features that are a page of their own: counted when the address names them. */
function fromHash() {
  var hash = location.hash || "";
  if (hash === "#/me") noteFeature("my_hub");
  else if (hash === "#/guide") noteFeature("user_guide");
  else if (hash === "#/help") noteFeature("get_help");
  else if (hash === "#/request") noteFeature("new_asset_inquiry");
  else if (hash.indexOf("#/search") === 0) noteFeature("advanced_search");
  else if (hash.indexOf("#/playlist/") === 0) noteFeature("playlists");
}

/* The features that are a button: counted on the click. These buttons are
 * built by several scripts, so one listener on the page finds them by their
 * class or id instead of each script calling in. */
function fromClick(e) {
  var t = e.target;
  if (!t || !t.closest) return;
  if (t.closest("#vpCopyLink")) noteFeature("share_internally");
  else if (t.closest(".vp-demoboard")) noteFeature("create_demoboard");
  else if (t.closest('.hub-view__seg [data-view="table"]')) noteFeature("table_view");
}

function wireFeatureUsage() {
  window.addEventListener("hashchange", fromHash);
  document.addEventListener("click", fromClick, true);
  fromHash();
}

export { noteFeature, wireFeatureUsage };
