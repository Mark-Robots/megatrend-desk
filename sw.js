// App Megatrend (Azioni + ETF) · Service Worker v2.0
// v2: HTML e JSON network-first (aggiornamenti immediati), cache solo fallback offline.
const CACHE_NAME = 'app-megatrend-v2';
const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './cliente.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(ASSETS_TO_CACHE).catch(err => console.warn('[SW] addAll failed:', err)))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// network-first: prova la rete, salva in cache, fallback alla cache se offline
function networkFirst(request) {
  return fetch(request)
    .then(res => {
      const resClone = res.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(request, resClone));
      return res;
    })
    .catch(() => caches.match(request));
}

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // 1) Navigazioni e pagine HTML -> network-first (aggiornamenti subito)
  const isHTML = event.request.mode === 'navigate' ||
                 url.pathname.endsWith('.html') ||
                 url.pathname.endsWith('/');

  // 2) Tutti i JSON dei dati -> network-first (sempre freschi)
  const isDataFile = url.pathname.includes('/data/') ||
                     url.pathname.endsWith('.json');

  if (isHTML || isDataFile) {
    event.respondWith(networkFirst(event.request));
  } else {
    // 3) Asset statici (icone, chart.js, font...) -> cache-first
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request))
    );
  }
});
