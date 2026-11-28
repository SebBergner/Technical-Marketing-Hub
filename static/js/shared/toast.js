/* A short message in the corner of the page, read out by screen readers
 * (WS-G, 2026-11-28; it was the Hub's silent "status corner").
 *
 * The element is the page's own (index.html's #hubApiStatus, styled as
 * before) and is a live region from the start: role="status" for news,
 * switched to role="alert" for an error, so an error interrupts and news
 * waits its turn.
 *
 * News leaves by itself after a few seconds; an error stays until the
 * next message or a click on it, as every message used to. */

var NEWS_MS = 8000;

function toaster(id, baseClass, errorClass) {
  var timer = null;
  var writing = null;

  function box() { return document.getElementById(id); }

  function clear() {
    var b = box();
    if (!b) return;
    clearTimeout(timer);
    clearTimeout(writing);
    b.textContent = "";
    b.className = baseClass;
  }

  function show(text, isError) {
    var b = box();
    if (!b) return;
    if (!b.hubToastWired) {
      b.hubToastWired = true;
      b.addEventListener("click", clear);
    }
    clearTimeout(timer);
    clearTimeout(writing);
    b.setAttribute("role", isError ? "alert" : "status");
    b.setAttribute("aria-live", isError ? "assertive" : "polite");
    b.setAttribute("aria-atomic", "true");
    b.className = baseClass + (isError ? " " + errorClass : "");
    // Emptied first and written a moment later, so the same words twice in
    // a row are still announced twice.
    b.textContent = "";
    if (!text) return;
    writing = setTimeout(function () { b.textContent = text; }, 30);
    if (!isError) timer = setTimeout(clear, NEWS_MS);
  }

  return { show: show, clear: clear };
}

export { toaster };
