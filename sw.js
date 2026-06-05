// App Megatrend (Azioni + ETF) · Service Worker v1.0
const CACHE_NAME = 'app-megatrend-v1';
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

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  // Dati JSON: network-first per averli sempre freschi, fallback cache
  const isDataFile = url.pathname.endsWith('stocks_data.json') || 
                     url.pathname.endsWith('sector_data.json') ||
                     url.pathname.endsWith('ranking_history.json');
  
  if (isDataFile) {
    event.respondWith(
      fetch(event.request)
        .then(res => {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, resClone));
          return res;
        })
        .catch(() => caches.match(event.request))
    );
  } else {
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request))
    );
  }
});
