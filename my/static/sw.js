const CACHE_NAME = 'my-planner-v3';
const OFFLINE_URL = '/static/offline.html';
const STATIC_ASSETS = [
    '/static/offline.html',
    '/static/tailwind.css',
    '/static/htmx.min.js',
    '/static/icon-192.png',
    '/static/icon-512.png'
];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (e) => {
    const url = new URL(e.request.url);

    // Cache-first for static assets and backgrounds
    if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/backgrounds/')) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(res => {
                    if (res.ok) {
                        const clone = res.clone();
                        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
                    }
                    return res;
                }).catch(() => new Response('', { status: 408 }));
            })
        );
        return;
    }

    // Network-first for navigation and API
    if (e.request.mode === 'navigate') {
        e.respondWith(
            fetch(e.request).catch(() => caches.match(OFFLINE_URL))
        );
        return;
    }

    // Network-first for everything else
    e.respondWith(
        fetch(e.request).catch(() => caches.match(e.request))
    );
});
