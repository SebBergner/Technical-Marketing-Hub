/* "Recent changes" at the foot of a Content health tab: the Admin log, only
 * in that tab's areas (GET /api/content-health/changes). People with View
 * Admin get a link to the whole log.
 *
 * Part of the Content health page's script (static/content-health.html). */

import { $, el, session } from "../admin/util.js";
import { adminLogTable } from "../admin/logtable.js";

function loadChanges(hostId, category) {
  var host = $(hostId);
  if (!host) return;
  return fetch("/api/content-health/changes?limit=15&category=" + encodeURIComponent(category))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      host.innerHTML = "";
      if (!d) return;
      host.appendChild(d.items.length ? adminLogTable(d.items)
        : el("div", "faint", "No changes recorded yet."));
      if ((session.permissions || []).indexOf("view_admin") >= 0) {
        var more = el("a", null, "The whole Admin log →");
        more.href = "/admin#activity";
        more.style.cssText = "display:inline-block;margin-top:8px;font-size:13px";
        host.appendChild(more);
      }
    });
}

export {
  loadChanges
};
