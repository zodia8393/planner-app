/**
 * Keyboard shortcuts for Planner apps.
 * Loaded in base.html; all shortcuts are registered here.
 */
(function () {
    'use strict';

    const SHORTCUTS = [
        { key: 'D', label: '대시보드', action: function () { location.href = '/'; } },
        { key: 'N', label: '할 일', action: function () { location.href = '/todos'; } },
        { key: 'C', label: '캘린더', action: function () { location.href = '/calendar'; } },
        { key: 'M', label: '메모', action: function () { location.href = '/memos'; } },
        { key: 'W', label: '업무일지', action: function () { location.href = '/worklogs'; } },
        { key: 'F', label: '양식', action: function () { location.href = '/forms'; } },
        { key: 'S', label: '설정', action: function () { location.href = '/settings'; } },
        { key: 'T', label: '할일 추가', action: function () { location.href = '/todos#new'; } },
        { key: 'E', label: '일정 추가', action: function () { location.href = '/calendar#new'; } },
    ];

    function isTyping() {
        const tag = document.activeElement && document.activeElement.tagName;
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
            (document.activeElement && document.activeElement.isContentEditable);
    }

    function closeAllModals() {
        // Close command palette
        const cp = document.getElementById('cmdPalette');
        if (cp && !cp.classList.contains('hidden')) {
            cp.classList.add('hidden');
            return true;
        }
        // Close more menu
        const moreMenu = document.getElementById('moreMenu');
        if (moreMenu && !moreMenu.classList.contains('hidden')) {
            if (typeof toggleMoreMenu === 'function') toggleMoreMenu();
            return true;
        }
        // Close sidebar on mobile
        const sb = document.getElementById('sidebar');
        if (sb && window.innerWidth < 1024 && !sb.classList.contains('-translate-x-full')) {
            if (typeof toggleSidebar === 'function') toggleSidebar();
            return true;
        }
        // Close shortcuts modal
        const shortcutsModal = document.getElementById('shortcutsHelpModal');
        if (shortcutsModal && !shortcutsModal.classList.contains('hidden')) {
            shortcutsModal.classList.add('hidden');
            return true;
        }
        // Close focus modal
        const focusModal = document.getElementById('focusModal');
        if (focusModal && !focusModal.classList.contains('hidden')) {
            focusModal.classList.add('hidden');
            return true;
        }
        // Close any other fixed modals
        const modals = document.querySelectorAll('.fixed.inset-0.z-50:not(.hidden), .fixed.inset-0.z-\\[60\\]:not(.hidden)');
        for (let i = 0; i < modals.length; i++) {
            if (modals[i].id !== 'dropOverlay') {
                modals[i].classList.add('hidden');
                return true;
            }
        }
        return false;
    }

    function showShortcutsHelp() {
        const existing = document.getElementById('shortcutsHelpModal');
        if (existing) {
            existing.classList.toggle('hidden');
            return;
        }

        const modal = document.createElement('div');
        modal.id = 'shortcutsHelpModal';
        modal.className = 'fixed inset-0 z-50 flex items-center justify-center';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-label', '키보드 단축키 도움말');

        const allShortcuts = SHORTCUTS.slice();
        // Add list-nav shortcuts to help
        allShortcuts.push({ key: 'J/K', label: '목록 항목 이동' });
        allShortcuts.push({ key: 'X/Space', label: '항목 토글/체크' });
        allShortcuts.push({ key: 'Enter', label: '항목 인라인 편집' });
        allShortcuts.push({ key: 'Ctrl+Shift+N', label: '새 메모' });
        allShortcuts.push({ key: 'Ctrl+Shift+E', label: '새 일정' });

        const rows = allShortcuts.map(function (s) {
            return '<div class="flex justify-between items-center">' +
                '<span style="color: var(--color-text-muted);">' + s.label + '</span>' +
                '<kbd class="px-2 py-0.5 rounded text-xs font-mono" style="background: var(--color-surface-elevated); color: var(--color-text);">' + s.key + '</kbd></div>';
        }).join('');

        // SAFE: no user data — all labels/keys from hardcoded SHORTCUTS array
        modal.innerHTML =
            '<div class="absolute inset-0 bg-black/50 backdrop-blur-sm" onclick="document.getElementById(\'shortcutsHelpModal\').classList.add(\'hidden\')"></div>' +
            '<div class="relative rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4 fade-in" style="background: var(--color-surface); border: 1px solid var(--color-border);">' +
            '<h3 class="font-bold text-lg mb-4" style="color: var(--color-text);">키보드 단축키</h3>' +
            '<div class="space-y-2.5 text-sm">' + rows +
            '<div class="pt-2 mt-2" style="border-top: 1px solid var(--color-border);"></div>' +
            '<div class="flex justify-between items-center"><span style="color: var(--color-text-muted);">검색</span><kbd class="px-2 py-0.5 rounded text-xs font-mono" style="background: var(--color-surface-elevated); color: var(--color-text);">Ctrl+K</kbd></div>' +
            '<div class="flex justify-between items-center"><span style="color: var(--color-text-muted);">닫기</span><kbd class="px-2 py-0.5 rounded text-xs font-mono" style="background: var(--color-surface-elevated); color: var(--color-text);">Esc</kbd></div>' +
            '<div class="flex justify-between items-center"><span style="color: var(--color-text-muted);">도움말</span><kbd class="px-2 py-0.5 rounded text-xs font-mono" style="background: var(--color-surface-elevated); color: var(--color-text);">?</kbd></div>' +
            '</div>' +
            '<button onclick="document.getElementById(\'shortcutsHelpModal\').classList.add(\'hidden\')" ' +
            'class="mt-4 w-full py-2 rounded-lg text-sm font-medium transition-colors" ' +
            'style="background: var(--color-surface-elevated); color: var(--color-text-muted);" ' +
            'aria-label="단축키 도움말 닫기">닫기</button>' +
            '</div>';
        document.body.appendChild(modal);
    }

    /* ── List keyboard navigation (j/k/x/Space/Enter) ── */
    /* Works on /todos (data-todo-nav), /habits, /worklogs, /memos (data-list-nav) */
    let _listNavIndex = -1;

    function getListNavItems() {
        // Prefer data-todo-nav on /todos, data-list-nav everywhere else
        let items = Array.from(document.querySelectorAll('[data-todo-nav]'));
        if (items.length === 0) {
            items = Array.from(document.querySelectorAll('[data-list-nav]'));
        }
        return items;
    }

    function setListNavFocus(index) {
        const items = getListNavItems();
        if (items.length === 0) return;
        // Remove old focus
        items.forEach(function (el) { el.classList.remove('todo-nav-focus', 'list-nav-focus'); });
        // Clamp index
        if (index < 0) index = 0;
        if (index >= items.length) index = items.length - 1;
        _listNavIndex = index;
        const target = items[_listNavIndex];
        const focusClass = target.hasAttribute('data-todo-nav') ? 'todo-nav-focus' : 'list-nav-focus';
        target.classList.add(focusClass);
        target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    const _LIST_NAV_PAGES = ['/todos', '/habits', '/worklogs', '/memos'];

    function isListNavPage() {
        return _LIST_NAV_PAGES.indexOf(location.pathname) >= 0;
    }

    function handleListNav(e) {
        if (!isListNavPage()) return false;
        const items = getListNavItems();
        if (items.length === 0) return false;

        const key = e.key;

        if (key === 'j') {
            e.preventDefault();
            setListNavFocus(_listNavIndex + 1);
            return true;
        }
        if (key === 'k') {
            e.preventDefault();
            setListNavFocus(_listNavIndex - 1);
            return true;
        }
        if (key === 'x' || key === ' ') {
            if (_listNavIndex < 0 || _listNavIndex >= items.length) return false;
            e.preventDefault();
            const current = items[_listNavIndex];
            // Click the toggle button (checkbox)
            const toggleBtn = current.querySelector('button[hx-post*="/toggle"]') ||
                            current.querySelector('form button[type="submit"]');
            if (toggleBtn) toggleBtn.click();
            return true;
        }
        if (key === 'Enter' && !e.ctrlKey && !e.metaKey) {
            if (_listNavIndex < 0 || _listNavIndex >= items.length) return false;
            e.preventDefault();
            const current = items[_listNavIndex];
            // Click the edit button
            const editBtn = current.querySelector('button[hx-get*="/edit"]');
            if (editBtn) editBtn.click();
            return true;
        }
        return false;
    }

    /* ── Ctrl+Enter: submit focused form ── */
    function handleCtrlEnter(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const form = document.activeElement && document.activeElement.closest('form');
            if (form) {
                e.preventDefault();
                // Find submit button or submit directly
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.click();
                } else {
                    form.requestSubmit ? form.requestSubmit() : form.submit();
                }
                return true;
            }
        }
        return false;
    }

    /* ── Modal focus trap ── */
    window.trapFocus = function (modal) {
        const focusable = modal.querySelectorAll(
            'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        modal.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            if (e.shiftKey) {
                if (document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                }
            } else {
                if (document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            }
        });
        first.focus();
    };

    // Auto-trap focus when modals become visible
    function setupModalFocusTraps() {
        const modalIds = ['confirmModal', 'focusModal', 'cmdPalette'];
        modalIds.forEach(function (id) {
            const modal = document.getElementById(id);
            if (!modal) return;
            const observer = new MutationObserver(function () {
                if (!modal.classList.contains('hidden')) {
                    trapFocus(modal);
                }
            });
            observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
        });
    }

    document.addEventListener('DOMContentLoaded', setupModalFocusTraps);

    document.addEventListener('keydown', function (e) {
        // Ctrl+Enter: submit form (works even when typing)
        if (handleCtrlEnter(e)) return;

        // Escape: close modals
        if (e.key === 'Escape') {
            closeAllModals();
            return;
        }

        // Ctrl+Shift+N: new memo
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'N' || e.key === 'n')) {
            e.preventDefault();
            if (location.pathname === '/memos') {
                const memoForm = document.querySelector('details:has(form[action="/memos"])');
                if (memoForm && !memoForm.open) memoForm.open = true;
                const memoInput = document.getElementById('memo-content');
                if (memoInput) memoInput.focus();
            } else {
                location.href = '/memos';
            }
            return;
        }

        // Ctrl+Shift+E: new calendar event
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'E' || e.key === 'e')) {
            e.preventDefault();
            if (location.pathname === '/calendar') {
                const addEventBtn = document.querySelector('[data-action="open-event-modal"]') ||
                                  document.querySelector('button[onclick*="openEventModal"]') ||
                                  document.querySelector('.fab');
                if (addEventBtn) addEventBtn.click();
            } else {
                location.href = '/calendar';
            }
            return;
        }

        // Skip if typing in input (except for list nav keys when applicable)
        if (isTyping()) return;

        // List navigation (j/k/x/Space/Enter) on list pages
        if (handleListNav(e)) return;

        // Ctrl/Cmd+K: command palette
        if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            if (typeof toggleCommandPalette === 'function') toggleCommandPalette();
            return;
        }

        // ?: show help
        if (e.key === '?') {
            e.preventDefault();
            showShortcutsHelp();
            return;
        }

        // Single key shortcuts
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const key = e.key.toUpperCase();
        for (let i = 0; i < SHORTCUTS.length; i++) {
            if (SHORTCUTS[i].key === key) {
                SHORTCUTS[i].action();
                return;
            }
        }
    });

    // Expose for inline use
    window.showShortcutsHelp = showShortcutsHelp;
})();
