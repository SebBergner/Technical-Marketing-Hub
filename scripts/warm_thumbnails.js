/* Warm the Hub's card pictures after a swap (2026-11-05, before the stress
 * test of 2026-11-06). Read-only: it only GETs what a visitor's browser would.
 *
 * Why: D18 shrinks SharePoint pictures to JPEGs at most 640 px wide, but a
 * picture cached by the old code is only shrunk the first time someone asks
 * for it, and each gunicorn worker builds its catalogue on its first request.
 * Run this once and twenty people opening Home at once do not do that work.
 *
 * How: sign in to the slot (tmh.ptcxc.com), open the browser's DevTools
 * console on any Hub page, paste this whole file, press Enter. It asks for at
 * most four pictures at a time and prints a count when done. Brightcove
 * covers come from Brightcove's own servers and are skipped.
 *
 * Run it after step 13's SharePoint sync has finished. Pictures the server
 * was too busy to fetch are tried again one at a time; "busy" in the final
 * count is what was still left after three such rounds (run it again). */
(async function warmThumbnails() {
  const PAGE = 200, AT_ONCE = 4;
  const started = performance.now();

  async function json(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error(url + " -> HTTP " + r.status);
    return r.json();
  }

  // The whole catalogue, as Home asks for it; a few rounds reach more workers.
  let items = [];
  const first = await json("/api/assets?limit=" + PAGE + "&offset=0");
  items = items.concat(first.items || []);
  for (let offset = PAGE; offset < (first.total || 0); offset += PAGE) {
    const page = await json("/api/assets?limit=" + PAGE + "&offset=" + offset);
    items = items.concat(page.items || []);
  }
  for (let i = 0; i < 6; i++) await json("/api/assets?limit=1&offset=0");

  const urls = [...new Set(items.map((a) => a.thumbnail_url)
    .filter((u) => typeof u === "string" && u.startsWith("/api/")))];
  console.log("[warm] " + items.length + " demos, " + urls.length + " Hub pictures to fetch");

  const tally = { ok: 0, busy: 0, missing: 0, error: 0 };
  let busy = [];
  async function one(url) {
    try {
      const r = await fetch(url, { credentials: "same-origin", cache: "reload" });
      if (r.ok) { await r.arrayBuffer(); tally.ok++; }
      else if (r.status === 404 && (r.headers.get("Cache-Control") || "").includes("no-store")) busy.push(url);
      else if (r.status === 404) tally.missing++;
      else tally.error++;
    } catch (e) {
      tally.error++;
    }
  }
  let next = 0, done = 0;
  async function lane() {
    while (next < urls.length) {
      await one(urls[next++]);
      if (++done % 50 === 0) console.log("[warm] " + done + " / " + urls.length);
    }
  }
  await Promise.all(Array.from({ length: AT_ONCE }, lane));

  // "Busy": every one of the server's four SharePoint fetch slots was taken
  // (the server's own warm-up holds one). Those go again one at a time,
  // which always finds a slot; measured locally 2026-11-05, 64 of 507 were
  // busy in the four-at-a-time pass.
  for (let round = 1; busy.length && round <= 3; round++) {
    const again = busy;
    busy = [];
    console.log("[warm] " + again.length + " were busy; one at a time, round " + round);
    await new Promise((r) => setTimeout(r, 2000));
    for (const url of again) await one(url);
  }
  tally.busy = busy.length;
  const seconds = ((performance.now() - started) / 1000).toFixed(0);
  console.log("[warm] done in " + seconds + " s:", tally);
  return tally;
})();
