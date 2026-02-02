// RailReach Service Worker v1
const CACHE_NAME = 'railreach-v1';
const PRECACHE = [
  '/',
  '/assets/css/shared.css',
  '/assets/js/stations-data.js',
  '/assets/js/map-core.js',
  '/favicon.svg',
  '/manifest.json'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Cache map tiles aggressively
  if (url.hostname.includes('tile.openstreetmap.org')) {
    e.respondWith(
      caches.match(e.request).then(cached => cached ||
        fetch(e.request).then(resp => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
          return resp;
        })
      )
    );
    return;
  }
  // Network-first for HTML, cache-first for assets
  if (e.request.destination === 'document') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request).then(r => r || caches.match('/')))
    );
  } else {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request))
    );
  }
});
