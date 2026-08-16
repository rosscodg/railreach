// RailReach Service Worker. Cache name is stamped per build by _build/generate-pages.py
const CACHE_NAME = 'railreach-d60fae7b36';
const PRECACHE = [
  '/',
  '/assets/css/shared.css?v=059a3256',
  '/assets/js/map-ui.js?v=5e70ab40',
  '/assets/js/home-map.js?v=a0a10d3a',
  '/assets/js/stations-data.js?v=7c6cc3f4',
  '/assets/js/map-core.js?v=06f0a00f',
  '/favicon.svg',
  '/manifest.json'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  // Map tiles: cache-first, they never change
  if (url.hostname.endsWith('tile.openstreetmap.org')) {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(resp => {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return resp;
      }))
    );
    return;
  }

  // Leave third-party requests (fonts, unpkg, analytics) to the browser
  if (url.origin !== self.location.origin) return;

  // HTML: network-first so content updates land immediately
  if (e.request.destination === 'document') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request).then(r => r || caches.match('/')))
    );
    return;
  }

  // Own assets: stale-while-revalidate, fast but never stale for more than one visit
  e.respondWith(
    caches.match(e.request).then(cached => {
      const network = fetch(e.request).then(resp => {
        if (resp && resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
