/**
 * Planner Notification System v2
 *
 * Client-side scheduled notifications using the Notification API + Service Worker.
 * Polls /api/reminders (which now returns notify_at) and fires
 * browser notifications at the precise configured time.
 * Also sends schedules to SW for background notification delivery.
 */
(function () {
    'use strict';

    var CHECK_INTERVAL = 60 * 1000; // 1 minute (more precise than old 5 min)
    var STORAGE_KEY = 'planner_notif_schedule';
    var ENABLED_KEY = 'planner_notif_enabled';
    var NOTIFIED_KEY = 'planner_notified_v2';

    // ── Helpers ──

    function isEnabled() {
        var val = localStorage.getItem(ENABLED_KEY);
        return val !== 'false';
    }

    function getNotified() {
        try {
            var data = JSON.parse(localStorage.getItem(NOTIFIED_KEY) || '{}');
            // Prune old entries (older than 24 hours)
            var now = Date.now();
            var cleaned = {};
            Object.keys(data).forEach(function(key) {
                if (now - data[key] < 86400000) {
                    cleaned[key] = data[key];
                }
            });
            return cleaned;
        } catch (e) {
            return {};
        }
    }

    function markNotified(key) {
        var notified = getNotified();
        notified[key] = Date.now();
        try {
            localStorage.setItem(NOTIFIED_KEY, JSON.stringify(notified));
        } catch (e) {}
    }

    function wasNotified(key) {
        var notified = getNotified();
        return !!notified[key];
    }

    // ── Permission ──

    function requestPermission(callback) {
        if (!('Notification' in window)) {
            if (callback) callback('unsupported');
            return;
        }
        if (Notification.permission === 'granted') {
            if (callback) callback('granted');
            return;
        }
        if (Notification.permission === 'denied') {
            if (callback) callback('denied');
            return;
        }
        Notification.requestPermission().then(function (perm) {
            if (callback) callback(perm);
            if (perm === 'granted') {
                checkAndNotify();
            }
        });
    }

    // ── Send schedule to Service Worker for background notifications ──

    function sendToSW(reminders) {
        if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
        try {
            navigator.serviceWorker.controller.postMessage({
                type: 'SCHEDULE_NOTIFICATIONS',
                reminders: reminders
            });
        } catch (e) {}
    }

    // ── Core: fetch reminders and fire notifications ──

    function checkAndNotify() {
        if (!isEnabled()) return;
        if (!('Notification' in window)) return;
        if (Notification.permission !== 'granted') return;

        fetch('/api/reminders')
            .then(function (r) { return r.json(); })
            .then(function (items) {
                if (!Array.isArray(items)) return;

                var now = Date.now();
                var pendingForSW = [];

                items.forEach(function (item) {
                    var key = item.type + '_' + item.id + '_' + (item.notify_at || item.time);

                    if (wasNotified(key)) return;

                    // Check if we should fire now based on notify_at
                    var notifyAt = item.notify_at ? new Date(item.notify_at).getTime() : now;
                    var diff = notifyAt - now;

                    // Fire if within the polling window (-60s to +60s)
                    if (diff >= -60000 && diff <= 60000) {
                        fireNotification(item, key);
                    } else if (diff > 60000 && diff < 600000) {
                        // Schedule for SW if within next 10 minutes
                        pendingForSW.push(item);
                        // Also set a local timeout
                        scheduleLocal(item, key, diff);
                    }
                });

                // Send upcoming notifications to SW
                if (pendingForSW.length > 0) {
                    sendToSW(pendingForSW);
                }

                // Update badge
                var badge = document.getElementById('notifBadge');
                if (badge) {
                    if (items.length > 0) {
                        badge.textContent = items.length;
                        badge.classList.remove('hidden');
                    } else {
                        badge.classList.add('hidden');
                    }
                }
            })
            .catch(function () { });
    }

    function fireNotification(item, key) {
        if (wasNotified(key)) return;
        try {
            var n = new Notification(item.title || 'My Planner', {
                body: item.body || '',
                icon: '/static/icon-192.png',
                tag: key,
                renotify: false,
                data: { url: item.url || '/' }
            });
            n.onclick = function () {
                window.focus();
                if (item.url) window.location.href = item.url;
                n.close();
            };
        } catch (e) {
            // Fallback: use SW showNotification
            if (navigator.serviceWorker && navigator.serviceWorker.ready) {
                navigator.serviceWorker.ready.then(function(reg) {
                    reg.showNotification(item.title || 'My Planner', {
                        body: item.body || '',
                        icon: '/static/icon-192.png',
                        tag: key,
                        data: { url: item.url || '/' }
                    });
                });
            }
        }
        markNotified(key);
    }

    var localTimers = {};

    function scheduleLocal(item, key, delayMs) {
        if (localTimers[key]) return;
        localTimers[key] = setTimeout(function() {
            delete localTimers[key];
            fireNotification(item, key);
        }, delayMs);
    }

    // ── Settings page helper ──

    function updateNotifSettingsUI() {
        var statusEl = document.getElementById('settingsNotifStatus');
        var btnEl = document.getElementById('settingsNotifBtn');
        if (!statusEl) return;

        if (!('Notification' in window)) {
            statusEl.textContent = '이 브라우저에서 지원되지 않습니다';
            if (btnEl) btnEl.style.display = 'none';
            return;
        }

        var perm = Notification.permission;
        if (perm === 'granted') {
            statusEl.textContent = '허용됨';
            statusEl.className = 'text-xs text-green-600 dark:text-green-400 mt-0.5';
            if (btnEl) {
                btnEl.textContent = '허용됨';
                btnEl.disabled = true;
                btnEl.className = 'px-4 py-2 bg-green-100 text-green-700 text-sm font-medium rounded-lg cursor-default';
            }
        } else if (perm === 'denied') {
            statusEl.textContent = '차단됨 - 브라우저 설정에서 변경하세요';
            statusEl.className = 'text-xs text-red-500 dark:text-red-400 mt-0.5';
            if (btnEl) {
                btnEl.textContent = '차단됨';
                btnEl.disabled = true;
                btnEl.className = 'px-4 py-2 bg-red-100 text-red-600 text-sm font-medium rounded-lg cursor-default';
            }
        } else {
            statusEl.textContent = '미설정';
            statusEl.className = 'text-xs text-slate-400 mt-0.5';
            if (btnEl) {
                btnEl.textContent = '알림 허용하기';
                btnEl.disabled = false;
            }
        }
    }

    // ── Init ──

    window.requestNotifPermission = function () {
        requestPermission(function () {
            updateNotifSettingsUI();
        });
    };

    // Start polling if permission granted
    if ('Notification' in window && Notification.permission === 'granted' && isEnabled()) {
        setTimeout(checkAndNotify, 2000);
        setInterval(checkAndNotify, CHECK_INTERVAL);
    }

    // Update settings UI if on settings page
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', updateNotifSettingsUI);
    } else {
        updateNotifSettingsUI();
    }

    // Re-check after HTMX navigation
    document.addEventListener('htmx:afterSettle', function () {
        updateNotifSettingsUI();
    });
})();
