const CACHE_NAME = 'my-planner-v5';
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

// ── Notification click handler ──
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    const url = e.notification.data?.url || '/';
    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
            // Focus existing window if available
            for (const client of clientList) {
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    client.focus();
                    client.navigate(url);
                    return;
                }
            }
            // Open new window
            return clients.openWindow(url);
        })
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

// ── Scheduled notification timers ──
let scheduledTimers = {};

function scheduleNotification(item) {
    const notifyAt = item.notify_at ? new Date(item.notify_at).getTime() : Date.now();
    const now = Date.now();
    const delay = notifyAt - now;
    const key = item.type + '_' + item.id + '_' + (item.notify_at || item.time);

    if (scheduledTimers[key]) return; // Already scheduled
    if (delay < -60000) return; // Too far in the past
    if (delay > 600000) return; // More than 10 min in future - will be re-scheduled next poll

    const fireDelay = Math.max(0, delay);
    scheduledTimers[key] = setTimeout(() => {
        delete scheduledTimers[key];
        self.registration.showNotification(item.title || 'Planner', {
            body: item.body || '',
            icon: '/static/icon-192.png',
            tag: key,
            data: { url: item.url || '/' },
            requireInteraction: false
        });
    }, fireDelay);
}

// ── Periodic self-poll for reminders (keep SW alive for notifications) ──
let pollInterval = null;

function startReminderPoll() {
    if (pollInterval) return;
    pollInterval = setInterval(async () => {
        try {
            const resp = await fetch('/api/reminders');
            if (!resp.ok) return;
            const items = await resp.json();
            if (!Array.isArray(items)) return;
            items.forEach(item => scheduleNotification(item));
        } catch (e) {}
    }, 60000); // Every minute
}

// ── Message handler: queue forms + schedule notifications ──
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
            if (self.registration.sync) {
                self.registration.sync.register('sync-forms');
            }
        }).catch(() => {});
    }

    if (e.data && e.data.type === 'SCHEDULE_NOTIFICATIONS') {
        const reminders = e.data.reminders || [];
        reminders.forEach(item => scheduleNotification(item));
        // Start background poll to keep delivering notifications
        startReminderPoll();
    }
});

// Start polling on SW activation if notifications are likely expected
self.addEventListener('activate', () => {
    // Do an initial poll shortly after activation
    setTimeout(() => {
        fetch('/api/reminders').then(r => r.json()).then(items => {
            if (Array.isArray(items) && items.length > 0) {
                items.forEach(item => scheduleNotification(item));
                startReminderPoll();
            }
        }).catch(() => {});
    }, 5000);
});

// ── VAPID Web Push handler ──
self.addEventListener('push', (e) => {
    if (!e.data) return;
    let payload;
    try {
        payload = e.data.json();
    } catch (err) {
        payload = { title: 'MY PLANNER', body: e.data.text() };
    }
    const options = {
        body: payload.body || '',
        icon: payload.icon || '/static/icon-192.png',
        badge: '/static/icon-96.png',
        tag: payload.tag || 'planner-push',
        data: { url: payload.url || '/' },
        vibrate: [200, 100, 200],
        requireInteraction: false,
    };
    e.waitUntil(
        self.registration.showNotification(payload.title || 'MY PLANNER', options)
    );
});

// ── Push notification click handler ──
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    const url = (e.notification.data && e.notification.data.url) || '/';
    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
            for (const client of windowClients) {
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    client.navigate(url);
                    return client.focus();
                }
            }
            return clients.openWindow(url);
        })
    );
});
