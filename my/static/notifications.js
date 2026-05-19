/**
 * Planner Notification System
 *
 * Client-side scheduled notifications using the Notification API.
 * No server push (VAPID) -- purely polls /api/reminders and fires
 * browser notifications for upcoming items.
 */
(function () {
    'use strict';

    var CHECK_INTERVAL = 5 * 60 * 1000; // 5 minutes
    var STORAGE_KEY = 'planner_notif_schedule';
    var ENABLED_KEY = 'planner_notif_enabled';
    var NOTIFIED_KEY = 'planner_notified';

    // ── Helpers ──

    function isEnabled() {
        var val = localStorage.getItem(ENABLED_KEY);
        // Default to enabled if not explicitly disabled
        return val !== 'false';
    }

    function getNotified() {
        try {
            return JSON.parse(sessionStorage.getItem(NOTIFIED_KEY) || '{}');
        } catch (e) {
            return {};
        }
    }

    function setNotified(obj) {
        sessionStorage.setItem(NOTIFIED_KEY, JSON.stringify(obj));
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
                // Start checking immediately after grant
                checkAndNotify();
            }
        });
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

                var notified = getNotified();
                var schedules = [];

                items.forEach(function (item) {
                    var key = item.type + '_' + item.id;
                    schedules.push({ key: key, title: item.title, time: item.time });

                    if (notified[key]) return;

                    // For events, only notify if within 30 minutes
                    if (item.type === 'event' && item.time) {
                        var eventTime = new Date(item.time).getTime();
                        var now = Date.now();
                        var diff = eventTime - now;
                        // Skip if event is more than 30 min away
                        if (diff > 30 * 60 * 1000) return;
                        // Skip if event already passed more than 5 min ago
                        if (diff < -5 * 60 * 1000) return;
                    }

                    // Fire notification
                    try {
                        var n = new Notification(item.title || 'Planner', {
                            body: item.body || '',
                            icon: '/static/icon-192.png',
                            tag: key,
                            renotify: false
                        });
                        n.onclick = function () {
                            window.focus();
                            if (item.url) window.location.href = item.url;
                            n.close();
                        };
                    } catch (e) {
                        // Notification constructor can fail in some contexts
                    }

                    notified[key] = true;
                });

                setNotified(notified);

                // Store schedules for dedup tracking
                try {
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(schedules));
                } catch (e) { }

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

    // Expose for settings page button
    window.requestNotifPermission = function () {
        requestPermission(function () {
            updateNotifSettingsUI();
        });
    };

    // Start polling if permission granted
    if ('Notification' in window && Notification.permission === 'granted' && isEnabled()) {
        setTimeout(checkAndNotify, 3000);
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
