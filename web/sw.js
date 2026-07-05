const CACHE_NAME = 'freelink-v4';
const STATIC_ASSETS = [
  '/web/telegram-web-app.js',
  '/web/chart.umd.min.js',
  '/web/font-awesome.min.css',
  '/web/inter.css',
  '/web/icon-192.png',
  '/web/icon-512.png',
  '/web/favicon.svg',
  '/web/icon-192.svg',
  '/web/fonts/inter-400.ttf',
  '/web/fonts/inter-500.ttf',
  '/web/fonts/inter-600.ttf',
  '/web/fonts/inter-700.ttf',
  '/web/fonts/inter-800.ttf'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Skip API and WebSocket requests
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) {
    return;
  }
  e.respondWith(
    fetch(e.request).then(resp => {
      const ct = resp.headers.get('content-type') || '';
      const cc = resp.headers.get('cache-control') || '';
      if (resp.ok && e.request.method === 'GET' && !ct.includes('text/html') && !cc.includes('no-store')) {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
      }
      return resp;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('/app')))
  );
});
