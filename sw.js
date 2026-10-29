// Retirement worker for the old GitHub Pages PWA at /transport/.
// Keep a service worker at this path because existing installations may still
// be controlled by older workers caching dated timetable pages.
const DESTINATION = "https://transport.peluche-ebanache.com/";
const OLD_SCOPE = "/transport/";

self.addEventListener("install", event => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter(key => key.startsWith("transport-bahia-"))
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  if (event.request.mode !== "navigate") return;
  const requested = new URL(event.request.url);
  if (requested.origin !== self.location.origin ||
      !requested.pathname.startsWith(OLD_SCOPE)) return;
  // Even already-installed old PWAs should leave the frozen schedule.
  event.respondWith(Response.redirect(DESTINATION, 302));
});
