/* Talking to the Hub's API: one error path for every page (WS-G,
 * 2026-11-28), and the watch for a session that runs out with a page open.
 *
 * Until then each page -- and several Hub modules -- had its own copy of
 * "fetch, parse, throw `detail` or HTTP <status>". The copies agreed except
 * on what nobody had looked at: a FastAPI validation error (422) carries
 * `detail` as an ARRAY of {loc, msg, type}, and `new Error(array)` read
 * "[object Object]" in the corner of the page. */

/* What a FastAPI `detail` says, in words. A string is the server's own
 * message. An array is a 422's list of problems: each one as
 * "field: message", the location's "body"/"query"/"path" prefix left off. */
function detailMessage(detail) {
  if (detail == null || detail === "") return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(function (d) {
      if (!d || typeof d !== "object") return String(d);
      var loc = (d.loc || []).filter(function (part, i) {
        return !(i === 0 && (part === "body" || part === "query" || part === "path"));
      }).join(".");
      var msg = d.msg || d.message || "";
      return loc ? loc + ": " + msg : msg;
    }).filter(Boolean).join("; ");
  }
  if (typeof detail === "object" && detail.message) return String(detail.message);
  try { return JSON.stringify(detail); } catch (e) { return String(detail); }
}

/* Fetch and parse JSON, treating a non-2xx as the failure it is.
 *
 * options: what fetch takes, except that `body` may be a plain object,
 * sent as JSON with its Content-Type. FormData, Blob and strings go as
 * they are.
 *
 * Resolves with the parsed body, {} when there is none (a 204).
 * Rejects with an Error whose message is the server's `detail` in words,
 * else "HTTP <status>"; it carries `.status` and `.body`. A request that
 * never got an answer rejects with fetch's own error, marked `.network`,
 * so a caller can say "could not reach..." in its own words. */
function fetchJSON(url, options) {
  var opts = Object.assign({}, options || {});
  var body = opts.body;
  if (body !== undefined && body !== null && typeof body === "object"
      && !(body instanceof FormData) && !(body instanceof Blob)
      && !(body instanceof URLSearchParams) && !(body instanceof ArrayBuffer)) {
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    opts.body = JSON.stringify(body);
  }
  return fetch(url, opts).catch(function (err) {
    err.network = true;
    throw err;
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) {
        var err = new Error(detailMessage(d && d.detail) || ("HTTP " + r.status));
        err.status = r.status;
        err.body = d;
        throw err;
      }
      return d;
    });
  });
}

/* When the session runs out with the page open.
 *
 * The server's sign-in gate (backend/oidc.py) answers an API call that has
 * no session with 401 and an X-Sign-In header. A page already open would
 * otherwise just stop loading data, with nothing to say why -- so any such
 * answer sends the person to sign in and back to exactly where they were,
 * including the #/asset/... part the server never sees.
 *
 * Keyed on the header, not on 401 alone: the Admin page's own 401 means
 * "the admin password has not been entered", and must keep meaning that.
 * Installed once per page, whichever script asks first. */
function watchForExpiredSession() {
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
}

export { detailMessage, fetchJSON, watchForExpiredSession };
