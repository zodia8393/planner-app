/**
 * Keyboard shortcuts for Planner apps.
 * Loaded in base.html; all shortcuts are registered here.
 */
(function () {
    'use strict';

    var SHORTCUTS = [
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
        var tag = document.activeElement && document.activeElement.tagName;
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
            (document.activeElement && document.activeElement.isContentEditable);
    }

    function closeAllModals() {
        // Close command palette
        var cp = document.getElementById('cmdPalette');
        if (cp && !cp.classList.contains('hidden')) {
            cp.classList.add('hidden');
            return true;
        }
        // Close more menu
        var moreMenu = document.getElementById('moreMenu');
        if (moreMenu && !moreMenu.classList.contains('hidden')) {
            if (typeof toggleMoreMenu === 'function') toggleMoreMenu();
            return true;
        }
        // Close sidebar on mobile
        var sb = document.getElementById('sidebar');
        if (sb && window.innerWidth < 1024 && !sb.classList.contains('-translate-x-full')) {
            if (typeof toggleSidebar === 'function') toggleSidebar();
            return true;
        }
        // Close shortcuts modal
        var shortcutsModal = document.getElementById('shortcutsHelpModal');
        if (shortcutsModal && !shortcutsModal.classList.contains('hidden')) {
            shortcutsModal.classList.add('hidden');
            return true;
        }
        // Close focus modal
        var focusModal = document.getElementById('focusModal');
        if (focusModal && !focusModal.classList.contains('hidden')) {
            focusModal.classList.add('hidden');
            return true;
        }
        // Close any other fixed modals
        var modals = document.querySelectorAll('.fixed.inset-0.z-50:not(.hidden), .fixed.inset-0.z-\\[60\\]:not(.hidden)');
        for (var i = 0; i < modals.length; i++) {
            if (modals[i].id !== 'dropOverlay') {
                modals[i].classList.add('hidden');
                return true;
            }
        }
        return false;
    }

    function showShortcutsHelp() {
        var existing = document.getElementById('shortcutsHelpModal');
        if (existing) {
            existing.classList.toggle('hidden');
            return;
        }

        var modal = document.createElement('div');
        modal.id = 'shortcutsHelpModal';
        modal.className = 'fixed inset-0 z-50 flex items-center justify-center';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-label', '키보드 단축키 도움말');

        var allShortcuts = SHORTCUTS.slice();
        // Add todo-nav shortcuts to help
        allShortcuts.push({ key: 'J/K', label: '할일 항목 이동' });
        allShortcuts.push({ key: 'X/Space', label: '할일 완료 토글' });
        allShortcuts.push({ key: 'Enter', label: '할일 인라인 편집' });

        var rows = allShortcuts.map(function (s) {
            return '<div class="flex justify-between items-center">' +
                '<span class="text-slate-600 dark:text-slate-300">' + s.label + '</span>' +
                '<kbd class="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-xs font-mono">' + s.key + '</kbd></div>';
        }).join('');

        // SAFE: no user data — all labels/keys from hardcoded SHORTCUTS array
        modal.innerHTML =
            '<div class="absolute inset-0 bg-black/50 backdrop-blur-sm" onclick="document.getElementById(\'shortcutsHelpModal\').classList.add(\'hidden\')"></div>' +
            '<div class="relative bg-white dark:bg-slate-800 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4 border border-slate-200 dark:border-slate-700 fade-in">' +
            '<h3 class="font-bold text-lg text-slate-800 dark:text-white mb-4">키보드 단축키</h3>' +
            '<div class="space-y-2.5 text-sm">' + rows +
            '<div class="border-t border-slate-200 dark:border-slate-700 pt-2 mt-2"></div>' +
            '<div class="flex justify-between items-center"><span class="text-slate-600 dark:text-slate-300">검색</span><kbd class="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-xs font-mono">Ctrl+K</kbd></div>' +
            '<div class="flex justify-between items-center"><span class="text-slate-600 dark:text-slate-300">닫기</span><kbd class="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-xs font-mono">Esc</kbd></div>' +
            '<div class="flex justify-between items-center"><span class="text-slate-600 dark:text-slate-300">도움말</span><kbd class="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-xs font-mono">?</kbd></div>' +
            '</div>' +
            '<button onclick="document.getElementById(\'shortcutsHelpModal\').classList.add(\'hidden\')" ' +
            'class="mt-4 w-full py-2 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg text-sm font-medium hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors" ' +
            'aria-label="단축키 도움말 닫기">닫기</button>' +
            '</div>';
        document.body.appendChild(modal);
    }

    /* ── Todo keyboard navigation (j/k/x/Space/Enter) ── */
    var _todoNavIndex = -1;

    function getTodoNavItems() {
        return Array.from(document.querySelectorAll('[data-todo-nav]'));
    }

    function setTodoNavFocus(index) {
        var items = getTodoNavItems();
        if (items.length === 0) return;
        // Remove old focus
        items.forEach(function (el) { el.classList.remove('todo-nav-focus'); });
        // Clamp index
        if (index < 0) index = 0;
        if (index >= items.length) index = items.length - 1;
        _todoNavIndex = index;
        var target = items[_todoNavIndex];
        target.classList.add('todo-nav-focus');
        target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function isTodoPage() {
        return location.pathname === '/todos';
    }

    function handleTodoNav(e) {
        if (!isTodoPage()) return false;
        var items = getTodoNavItems();
        if (items.length === 0) return false;

        var key = e.key;

        if (key === 'j') {
            e.preventDefault();
            setTodoNavFocus(_todoNavIndex + 1);
            return true;
        }
        if (key === 'k') {
            e.preventDefault();
            setTodoNavFocus(_todoNavIndex - 1);
            return true;
        }
        if (key === 'x' || key === ' ') {
            if (_todoNavIndex < 0 || _todoNavIndex >= items.length) return false;
            e.preventDefault();
            var current = items[_todoNavIndex];
            // Click the toggle button (checkbox)
            var toggleBtn = current.querySelector('button[hx-post*="/toggle"]');
            if (toggleBtn) toggleBtn.click();
            return true;
        }
        if (key === 'Enter' && !e.ctrlKey && !e.metaKey) {
            if (_todoNavIndex < 0 || _todoNavIndex >= items.length) return false;
            e.preventDefault();
            var current = items[_todoNavIndex];
            // Click the edit button
            var editBtn = current.querySelector('button[hx-get*="/edit"]');
            if (editBtn) editBtn.click();
            return true;
        }
        return false;
    }

    /* ── Ctrl+Enter: submit focused form ── */
    function handleCtrlEnter(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            var form = document.activeElement && document.activeElement.closest('form');
            if (form) {
                e.preventDefault();
                // Find submit button or submit directly
                var submitBtn = form.querySelector('button[type="submit"]');
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
        var focusable = modal.querySelectorAll(
            'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
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
        var modalIds = ['confirmModal', 'focusModal', 'cmdPalette'];
        modalIds.forEach(function (id) {
            var modal = document.getElementById(id);
            if (!modal) return;
            var observer = new MutationObserver(function () {
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

        // Skip if typing in input (except for todo nav keys when applicable)
        if (isTyping()) return;

        // Todo navigation (j/k/x/Space/Enter) on /todos page
        if (handleTodoNav(e)) return;

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
        var key = e.key.toUpperCase();
        for (var i = 0; i < SHORTCUTS.length; i++) {
            if (SHORTCUTS[i].key === key) {
                SHORTCUTS[i].action();
                return;
            }
        }
    });

    // Expose for inline use
    window.showShortcutsHelp = showShortcutsHelp;
})();
