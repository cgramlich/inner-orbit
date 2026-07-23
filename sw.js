/* Orbit service worker — OFFLINE PHASE 1 (app shell + data reads).
   ===========================================================================
   Adapted from MenuCaptain's sw.js. Same rules, minus map tiles (Orbit V1 has
   no maps) and minus Leaflet from the critical assets.

   The one rule that matters most: never trap a user on a stale build.
   - The app document (index.html) is NETWORK-FIRST: online users always get
     the freshest file, so the in-app version checker keeps working; the cached
     copy is only served when the network truly fails.
   - Cache names are tied to VERSION, and `activate` deletes every cache that
     does not match, so each deploy cleanly rolls the cache.
   - VERSION is bumped in lockstep with APP_VERSION in index.html.

   Scope by request type:
   - app document            -> network-first, fall back to cached shell
   - version check (?vcheck=) -> NOT intercepted (always real network)
   - GET /api/collection/*    -> network-first, fall back to last cached copy
                                 (PUT writes are never intercepted)
   - immutable assets (cdnjs libs, fonts, our images) -> cache-first
   - everything else          -> default network
*/

const VERSION     = "0.2.2";                 // keep in lockstep with APP_VERSION
const SHELL_CACHE = "orbit-shell-" + VERSION;
const ASSET_CACHE = "orbit-assets-" + VERSION;
const DATA_CACHE  = "orbit-data-v1";         // user collections; un-versioned so it
                                             // survives app updates (only a manual
                                             // clearCache / logout wipes it)
const SHELL_URL   = "/";                     // canonical key for the app document

// Primed on install so even the very first offline open works.
// Each is a Request with SRI (integrity) + CORS mode, mirroring the <script>
// tags in index.html — the fetch fails (and is skipped by allSettled) if the
// CDN response doesn't hash-match, so a tampered copy never enters the cache.
const CRITICAL_ASSETS = [
  new Request("https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js", {
    integrity: "sha384-tMH8h3BGESGckSAVGZ82T9n90ztNXxvdwvdM6UoR56cYcf+0iGXBliJ29D+wZ/x8",
    mode: "cors",
  }),
  new Request("https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js", {
    integrity: "sha384-bm7MnzvK++ykSwVJ2tynSE5TRdN+xL418osEVF2DE/L/gfWHj91J2Sphe582B1Bh",
    mode: "cors",
  }),
  new Request("https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.6/babel.min.js", {
    integrity: "sha384-sw98ksifz4z7bpf5bssQYm0RlqkUsNXcYh7KqhO3+SIrvf3+mf0kQRNxaCWcgzjG",
    mode: "cors",
  }),
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const assets = await caches.open(ASSET_CACHE);
    await Promise.allSettled(CRITICAL_ASSETS.map((u) => assets.add(u)));
    try {
      const shell = await caches.open(SHELL_CACHE);
      const r = await fetch(SHELL_URL, { cache: "no-store" });
      if (r && r.ok) await shell.put(SHELL_URL, r.clone());
    } catch (e) { /* offline at install — fine, fill on first online load */ }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter((k) => k !== SHELL_CACHE && k !== ASSET_CACHE && k !== DATA_CACHE)
          .map((k) => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

// Lets the app force a full cache wipe (e.g. on logout or "Check for updates").
self.addEventListener("message", (event) => {
  const data = event.data;
  if (data === "clearCache" || (data && data.type === "clearCache")) {
    event.waitUntil((async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    })());
  }
});

function isImmutableAsset(url) {
  if (url.hostname === "cdnjs.cloudflare.com") return true;            // versioned libs
  if (url.hostname === "fonts.googleapis.com") return true;            // font css
  if (url.hostname === "fonts.gstatic.com") return true;               // font files
  if (url.origin === self.location.origin &&
      /\.(png|jpe?g|webp|gif|svg|ico|woff2?)$/i.test(url.pathname)) return true;  // our images
  return false;
}

async function shellNetworkFirst(req) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) cache.put(SHELL_URL, fresh.clone());
    return fresh;
  } catch (e) {
    const cached = await cache.match(SHELL_URL);
    return cached || Response.error();
  }
}

async function dataNetworkFirst(req) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const fresh = await Promise.race([
      fetch(req),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 5000)),
    ]);
    if (fresh && fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (e) {
    const cached = await cache.match(req);
    if (cached) return cached;
    throw e;
  }
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const fresh = await fetch(req);
    if (fresh && (fresh.ok || fresh.type === "opaque")) cache.put(req, fresh.clone());
    return fresh;
  } catch (e) {
    return cached || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                                    // never cache writes
  let url;
  try { url = new URL(req.url); } catch (e) { return; }

  const isAppDoc = url.origin === self.location.origin &&
                   (url.pathname === "/" || url.pathname === "/index.html");

  // App document: network-first. The version check (?vcheck=) is a query'd,
  // non-navigation fetch, so it is excluded and hits the real network.
  if (isAppDoc && (req.mode === "navigate" || !url.search)) {
    event.respondWith(shellNetworkFirst(req));
    return;
  }

  // User collections -> keep the last good copy for offline reads (GETs only).
  if (url.pathname.indexOf("/api/collection/") !== -1) {
    event.respondWith(dataNetworkFirst(req));
    return;
  }

  if (isImmutableAsset(url)) {
    event.respondWith(cacheFirst(req, ASSET_CACHE));
    return;
  }
  // Everything else -> default network.
});
