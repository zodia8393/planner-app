const CACHE_NAME = 'jm-planner-v4';
const OFFLINE_URL = '/static/offline.html';
const STATIC_ASSETS = [
    '/static/offline.html',
    '/static/tailwind.css',
    '/static/htmx.min.js',
    '/static/notifications.js',
    '/static/icon-192.png',
    '/static/icon-512.png'
];
const PAGE_URLS = [
    '/',
    '/todos',
    '/calendar',
    '/memos',
    '/notices'
];

// ── Install: pre-cache static assets + offline page ──
self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

// ── Activate: clean old caches ──
self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

// ── Fetch: strategy by request type ──
self.addEventListener('fetch', (e) => {
    const url = new URL(e.request.url);

    // Skip non-http(s) schemes (chrome-extension://, etc.)
    if (!url.protocol.startsWith('http')) return;

    // Skip non-GET requests (let POST/PUT/DELETE go to network)
    if (e.request.method !== 'GET') return;

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

    // Network-first for HTML navigation, cache successful responses
    if (e.request.mode === 'navigate' || e.request.headers.get('accept')?.includes('text/html')) {
        e.respondWith(
            fetch(e.request).then(res => {
                if (res.ok) {
                    const clone = res.clone();
                    caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
                }
                return res;
            }).catch(() =>
                caches.match(e.request).then(cached =>
                    cached || caches.match(OFFLINE_URL)
                )
            )
        );
        return;
    }

    // Network-first for API calls (no cache)
    if (url.pathname.startsWith('/api/')) {
        e.respondWith(
            fetch(e.request).catch(() => caches.match(e.request))
        );
        return;
    }

    // Network-first for everything else
    e.respondWith(
        fetch(e.request).then(res => {
            if (res.ok) {
                const clone = res.clone();
                caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
            }
            return res;
        }).catch(() => caches.match(e.request))
    );
});

// ── Background Sync: replay queued form submissions ──
self.addEventListener('sync', (e) => {
    if (e.tag === 'sync-forms') {
        e.waitUntil(replayQueuedForms());
    }
});

async function replayQueuedForms() {
    try {
        const db = await openSyncDB();
        const tx = db.transaction('outbox', 'readwrite');
        const store = tx.objectStore('outbox');
        const all = await idbGetAll(store);

        for (const entry of all) {
            try {
                const res = await fetch(entry.url, {
                    method: entry.method,
                    headers: entry.headers,
                    body: entry.body
                });
                if (res.ok || res.status < 500) {
                    const delTx = db.transaction('outbox', 'readwrite');
                    delTx.objectStore('outbox').delete(entry.id);
                }
            } catch (err) {
                // Will retry on next sync
                break;
            }
        }
    } catch (e) {
        // IndexedDB not available
    }
}

function openSyncDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('planner-sync', 1);
        req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains('outbox')) {
                db.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true });
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

function idbGetAll(store) {
    return new Promise((resolve, reject) => {
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

// ── Message handler: queue forms from main thread ──
self.addEventListener('message', (e) => {
    if (e.data && e.data.type === 'QUEUE_FORM') {
        openSyncDB().then(db => {
            const tx = db.transaction('outbox', 'readwrite');
            tx.objectStore('outbox').add({
                url: e.data.url,
                method: e.data.method,
                headers: e.data.headers || {},
                body: e.data.body,
                timestamp: Date.now()
            });
            // Request background sync if available
            if (self.registration.sync) {
                self.registration.sync.register('sync-forms');
            }
        }).catch(() => {});
    }
});
