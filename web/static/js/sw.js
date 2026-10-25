/**
 * Universal Clipboard AI — Progressive Web App Service Worker
 * ============================================================
 * Privacy & Security Architecture:
 * - NEVER caches clipboard text, tokens, session data, or API responses.
 * - Authenticated views (/dashboard, /settings, /api/*) are strictly NETWORK-ONLY.
 * - Cache Storage is used ONLY for static styling, UI scripts, icons, and a safe /offline fallback.
 * - On network disconnect during page navigation, serves the static /offline fallback.
 */

const STATIC_CACHE_NAME = "uca-static-v1";

// Safe, non-sensitive static assets only
const PRECACHE_ASSETS = [
  "/static/css/style.css",
  "/static/js/app.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-192.png",
  "/static/icons/icon-maskable-512.png",
  "/offline",
];

// Install: pre-cache static application shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

// Activate: purge legacy caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== STATIC_CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: enforce strict security boundaries
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. Only process GET requests; never intercept mutations (POST, DELETE, etc.)
  if (req.method !== "GET") {
    return;
  }

  // 2. Ignore third-party / cross-origin requests completely (Google Auth, Firebase, CDNs)
  // Let browser native network handle external requests without service worker proxying
  if (url.origin !== self.location.origin) {
    return;
  }

  // 3. Strict Network-Only for all API calls: bypass directly to native browser networking
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // 4. Navigation requests (HTML pages like /dashboard, /login, /settings)
  // Enforce Network-First. If offline, display the safe /offline fallback.
  if (req.mode === "navigate" || req.headers.get("accept")?.includes("text/html")) {
    event.respondWith(
      fetch(req).catch(() => {
        return caches.match("/offline").then((cached) => {
          return cached || new Response("You are currently offline.", {
            status: 503,
            statusText: "Offline",
            headers: { "Content-Type": "text/plain" },
          });
        });
      })
    );
    return;
  }

  // 5. Safe Static Assets (/static/*)
  // Serve from cache first, fall back to network, and update cache if valid
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(req).then((cachedResponse) => {
        if (cachedResponse) {
          // Stale-while-revalidate in background
          fetch(req).then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(STATIC_CACHE_NAME).then((cache) => {
                cache.put(req, networkResponse);
              });
            }
          }).catch(() => {
            // Ignore background revalidation errors when offline
          });
          return cachedResponse;
        }

        return fetch(req).then((networkResponse) => {
          if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== "basic") {
            return networkResponse;
          }
          const responseToCache = networkResponse.clone();
          caches.open(STATIC_CACHE_NAME).then((cache) => {
            cache.put(req, responseToCache);
          });
          return networkResponse;
        });
      })
    );
    return;
  }
});
