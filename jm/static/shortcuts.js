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

        var rows = SHORTCUTS.map(function (s) {
            return '<div class="flex justify-between items-center">' +
                '<span class="text-slate-600 dark:text-slate-300">' + s.label + '</span>' +
                '<kbd class="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-xs font-mono">' + s.key + '</kbd></div>';
        }).join('');

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

    document.addEventListener('keydown', function (e) {
        // Escape: close modals
        if (e.key === 'Escape') {
            closeAllModals();
            return;
        }

        // Skip if typing in input
        if (isTyping()) return;

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
