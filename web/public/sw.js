// Loupebox service worker: makes the app installable and the shell load offline.
//
// Deliberately narrow: it only ever touches an allow-list of same-origin GETs (the page shell,
// hashed /assets/*, icons, manifest). API calls, /config.js (runtime config) and anything
// authenticated pass straight through to the network and are never cached.
const VERSION = "v3"; // bump when cached shell assets (icons, manifest) change so installed apps refresh
const SHELL = `loupebox-shell-${VERSION}`;
const ASSETS = `loupebox-assets-${VERSION}`;
const MAX_ASSETS = 60;
const STATIC = ["/loupebox-icon.svg", "/brand/loupebox-icon-neon-light.svg", "/brand/loupebox-icon-neon-dark.svg", "/icon-192.png", "/icon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", ...STATIC])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, ASSETS]);
      for (const key of await caches.keys()) if (!keep.has(key)) await caches.delete(key);
      await self.clients.claim();
    })(),
  );
});

// The cached shell is always refreshed from an explicit fetch of "/", never from whatever a
// navigation happened to return: opening an API URL in a tab must not replace the app shell.
async function refreshShell() {
  try {
    const res = await fetch("/", { cache: "no-cache" });
    if (res.ok && (res.headers.get("content-type") || "").includes("text/html")) {
      await (await caches.open(SHELL)).put("/", res);
    }
  } catch {
    /* offline: keep the old copy */
  }
}

async function shell(event) {
  const cached = () => caches.open(SHELL).then((c) => c.match("/"));
  try {
    const res = await fetch(event.request);
    if (res.ok) {
      event.waitUntil(refreshShell());
      return res;
    }
    // e.g. 502 from the proxy while the server restarts: prefer the cached shell over an error page
    return (await cached()) || res;
  } catch {
    const hit = await cached();
    if (hit) return hit;
    throw new Error("offline and no cached shell");
  }
}

async function hashedAsset(request) {
  const cache = await caches.open(ASSETS);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok && res.type === "basic") {
    await cache.put(request, res.clone());
    const keys = await cache.keys();
    for (const old of keys.slice(0, Math.max(0, keys.length - MAX_ASSETS))) await cache.delete(old);
  }
  return res;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request);
  const refresh = fetch(request)
    .then((res) => (res.ok && res.type === "basic" ? (cache.put(request, res.clone()), res) : res))
    .catch(() => hit);
  return hit || refresh;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") event.respondWith(shell(event));
  else if (url.pathname.startsWith("/assets/")) event.respondWith(hashedAsset(request));
  else if (STATIC.includes(url.pathname)) event.respondWith(staleWhileRevalidate(request));
  // everything else (API, /config.js, /sw.js, ...): not intercepted
});
