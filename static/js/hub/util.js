/* Small helpers every part of the Hub page uses: the message corner,
 * dates and durations, pills, and the shared labels for languages and
 * types. Fetching JSON, escaping and plain date formatting are the
 * shared ones, in static/js/shared/ (WS-G, 2026-11-28).
 *
 * Part of the Hub page's script, split out of static/hub-api.js on
 * 2026-10-14; static/js/hub/main.js loads it. */

import { fullDate } from "../shared/dates.js";
import { toaster } from "../shared/toast.js";

function durationLabel(seconds) {
  if (!seconds) return "";
  var m = Math.floor(seconds / 60), s = seconds % 60;
  return m + ":" + (s < 10 ? "0" : "") + s;
}

function pill(text, kind) {
  var el = document.createElement("span");
  el.className = "hub-pill hub-pill--" + kind;
  el.textContent = text;
  return el;
}

function debounce(fn, ms) {
  var t;
  return function () { clearTimeout(t); t = setTimeout(fn, ms); };
}

/* A demo's date as a tile and a table say it (Serge, 2026-10-23):
 * "Published Mar 12, 2024" when someone stated it (date_stated), else
 * "Updated Dec 2018" -- read off the files, so to the month only, and not
 * passed off as a publication date. "" without a date. */
function dateLabel(a) {
  if (!a || !a.uploaded_at) return "";
  if (a.date_stated) return "Published " + fullDate(a.uploaded_at);
  var d = new Date(a.uploaded_at + "T00:00:00");
  return isNaN(d) ? ""
    : "Updated " + d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function setText(id, text) {
  var el = document.getElementById(id);
  if (el) el.textContent = text || "";
}

/* Below the search box while someone types: one offer, Advanced Search
 * (which also reads file names). The category offers that used to sit
 * here ("Show all 274 Windchill demos", "Browse all 285 Windchill") were
 * removed on 2026-10-01 (Liwei): two more counts beside the result count,
 * telling people little the filters and Advanced Search do not. */
var TYPE_LABELS = { video: "Videos", ldk: "LDKs", vdk: "VDKs",
                    vm: "Virtual Machines", cad_model: "CAD Datasets" };

//: The eight codes LANG_MAP (sharepoint_mapping.py) and Consensus's
//: `language.code` both produce, measured against the live catalogue --
//: not a guess at what languages might exist. A code missing from here
//: still shows, just as itself (see languageBadge()'s fallback).
var LANGUAGE_LABEL = { en: "English", zh: "Chinese", de: "German",
                      fr: "French", es: "Spanish", it: "Italian",
                      ja: "Japanese", ko: "Korean" };

/* The corner of the page: a toast, read out by screen readers
 * (static/js/shared/toast.js). Errors stay until the next message. */
var corner = toaster("hubApiStatus", "hub-api-status", "hub-api-status--error");
function report(text, isError) {
  corner.show(text, isError);
}

export {
  dateLabel, debounce, durationLabel, LANGUAGE_LABEL, pill, report, setText, TYPE_LABELS
};
