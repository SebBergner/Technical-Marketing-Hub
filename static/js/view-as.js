/* "Viewing as <group> - Exit": the bar on every page while an administrator
 * previews the Hub as a group (A9, backend/view_as.py).
 *
 * A plain script, not a module, so the Hub, Admin, Content health and
 * Migration pages can all load it the same way. It asks /api/auth/me whether a
 * preview is on, draws the bar, and shows the server's "Read-only" text as a
 * toast when a click is refused during one (the buttons stay visible on
 * purpose: the preview shows what the group would be offered). */
(function () {
  "use strict";
  if (window.__hubViewAs) return;
  window.__hubViewAs = true;

  var style = document.createElement("style");
  style.textContent =
    "#hubViewAsBar{position:fixed;top:0;left:0;right:0;z-index:2147483000;display:flex;" +
    "gap:12px;align-items:center;justify-content:center;padding:6px 12px;background:#7a2e00;" +
    "color:#fff;font:600 13px/1.3 system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)}" +
    "#hubViewAsBar button{background:#fff;color:#7a2e00;border:0;border-radius:4px;" +
    "padding:3px 10px;font:600 12px system-ui,sans-serif;cursor:pointer}" +
    "#hubViewAsBar span small{font-weight:400;opacity:.85;margin-left:6px}" +
    "#hubViewAsToast{position:fixed;top:48px;left:50%;transform:translateX(-50%);" +
    "z-index:2147483001;max-width:min(560px,92vw);background:#222;color:#fff;" +
    "padding:10px 14px;border-radius:6px;font:13px/1.4 system-ui,sans-serif;" +
    "box-shadow:0 2px 10px rgba(0,0,0,.35)}" +
    "body.hub-view-as{padding-top:34px}";
  document.head.appendChild(style);

  function exitPreview() {
    fetch("/api/admin/view-as/exit", { method: "POST" })
      .catch(function () {})
      .then(function () { location.href = "/admin#access"; });
  }

  function drawBar(view) {
    var bar = document.createElement("div");
    bar.id = "hubViewAsBar";
    bar.setAttribute("role", "status");
    var text = document.createElement("span");
    text.textContent = "Viewing the Hub as " + view.label;
    var small = document.createElement("small");
    small.textContent = "read-only, not counted as use";
    text.appendChild(small);
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "Exit";
    button.addEventListener("click", exitPreview);
    bar.appendChild(text);
    bar.appendChild(button);
    document.body.appendChild(bar);
    document.body.classList.add("hub-view-as");
  }

  var toastTimer = null;
  function toast(message) {
    var old = document.getElementById("hubViewAsToast");
    if (old) old.remove();
    var t = document.createElement("div");
    t.id = "hubViewAsToast";
    t.setAttribute("role", "alert");
    t.textContent = message;
    document.body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.remove(); }, 5000);
  }

  // A refused write says why, once, wherever it came from.
  var original = window.fetch;
  if (original) {
    window.fetch = function () {
      return original.apply(this, arguments).then(function (response) {
        if (response.status === 403 && response.headers.get("X-Hub-View-As") === "read-only") {
          response.clone().json().then(function (d) { toast(d.detail); }).catch(function () {});
        }
        return response;
      });
    };
  }

  function start() {
    original("/api/auth/me", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.user && d.user.view_as) drawBar(d.user.view_as); })
      .catch(function () {});
  }
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();
