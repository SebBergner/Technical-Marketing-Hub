/* What the signed-in person may do (backend/access.py), and the
 * html.hub-no-* classes that hide what they may not.
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

/* ── what this person may do (backend/access.py, 2026-10-06) ─────────
 *
 * The server refuses whatever a person's groups do not allow; this only
 * hides the controls that would be refused, so nobody is offered a button
 * that answers "not permitted". One class on <html> per missing
 * permission, and CSS does the hiding -- the links are built in many
 * places, but every one of them points at the same two endpoints, and the
 * request form is opened from one nav item. Nothing is hidden until the
 * answer arrives, and nothing at all if it never does.
 */
/* What this person may do, once known; [] if it never arrives. */
var hubPermissions = Promise.resolve([]);

function applyPermissions() {
  hubPermissions = fetch("/api/auth/me")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      var granted = d && d.user && d.user.permissions;
      if (!granted) return [];
      // Not a permission: being on Elio's Consensus licence list
      // (backend/consensus_licenses.py, 2026-10-28), which shows Create
      // DemoBoard. Carried here so the page asks in one place.
      granted = granted.slice();
      if (d.consensus_licensed) granted.push("consensus_licensed");
      // Nor is being a partner, which renames Share Internally (2026-10-29).
      if (d.user.is_partner) granted.push("is_partner");
      ["download", "preview", "create_demo"].forEach(function (p) {
        document.documentElement.classList.toggle("hub-no-" + p, granted.indexOf(p) < 0);
      });
      return granted;
    })
    .catch(function () { return []; });
}

export {
  applyPermissions, hubPermissions
};
