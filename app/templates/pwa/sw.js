/* Service worker de Voyage Voyage (généré par app/pwa.py). Version {{ version }}.
 *
 * - fichiers statiques, bibliothèques comprises : cache d'abord (leurs URL changent avec leur contenu) ;
 * - pages et API : réseau d'abord, dernière réponse en cache si le réseau manque, sinon page hors ligne ;
 * - le cache des pages est vidé à la déconnexion (main.js), il ne survit pas à la session.
 */
const VERSION = "{{ version }}";
const STATIC_CACHE = `static-${VERSION}`;
const PAGES_CACHE = "pages";
const PRECACHE = {{ precache|tojson }};
const OFFLINE_URL = {{ offline_url|tojson }};
const NETWORK_ONLY = {{ network_only|tojson }};

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll([...PRECACHE, OFFLINE_URL])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    // Ancien cache des CDN (bibliothèques désormais servies par le site) supprimé aussi.
    await Promise.all(names.filter((name) => (name.startsWith("static-") && name !== STATIC_CACHE) || name === "cdn")
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

function storable(response) {
  return response.ok && !response.redirected && response.type !== "opaque"
    && !(response.headers.get("Cache-Control") || "").includes("no-store");
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (storable(response)) (await caches.open(cacheName)).put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (storable(response)) (await caches.open(PAGES_CACHE)).put(request, response.clone());
    return response;
  } catch (error) {
    const cache = await caches.open(PAGES_CACHE);
    // Filtres différents de la dernière visite : à défaut, la dernière réponse de la même adresse.
    const cached = await cache.match(request) || await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    if (request.mode === "navigate") return caches.match(OFFLINE_URL);
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (NETWORK_ONLY.some((prefix) => url.pathname.startsWith(prefix))) return;
    if (url.pathname.startsWith("/static/")) {
      event.respondWith(cacheFirst(request, STATIC_CACHE));
    } else if (request.mode === "navigate" || url.pathname.startsWith("/api/")) {
      event.respondWith(networkFirst(request));
    }
  }
  // Tuiles de carte et autres origines : réseau seulement (réponses opaques, trop lourdes à garder).
});
