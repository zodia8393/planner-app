/* ============================================================
   DashGrid — Dashboard Grid Layout Engine (Rewritten)
   Unified Pointer Events, Single State, Event Delegation
   ============================================================ */
var DashGrid = (function() {
    'use strict';

    /* ── Constants ── */
    var STORAGE_KEY = { pc: 'dashboard_layout_pc', mobile: 'dashboard_layout_mobile', tablet: 'dashboard_layout_tablet' };
    var COLS = { pc: 12, tablet: 3, mobile: 2 };
    var ROW_H = { pc: 64, tablet: 56, mobile: 48, landscape: 40 };
    var BREAKPOINT = 1024;
    var TABLET_BP = 768;
    var LAYOUT_VERSION = 6;
    var LONG_PRESS_MS = 300;
    var JITTER_PX = 12;
    var SAVE_DEBOUNCE_MS = 200;

    var WIDGET_LABELS = {
        'widget-row': 'Today / 오늘',
        'stat-cards': '통계 카드',
        'quick-add': '빠른 추가',
        'plan-view': '플랜 뷰',
        'timetable': '시간표',
        'time-budgets': '시간 예산',
        'notices': '공지',
        'worklogs': '업무일지',
        'events': '일정',
        'progress': '진행률'
    };

    var WIDGET_ICONS = {
        'widget-row': '☀️', 'stat-cards': '📊', 'quick-add': '✍️',
        'plan-view': '📅', 'timetable': '⏰', 'time-budgets': '⏳',
        'notices': '📢', 'worklogs': '📝', 'events': '📅', 'progress': '📈'
    };

    var MOBILE_SIZE_MAP = { 'C': {w:1,h:1}, 'H': {w:1,h:2}, 'FM': {w:2,h:2}, 'T': {w:2,h:3} };

    /* ── Default Layouts ── */
    var DEFAULTS = {
        pc: {
            'widget-row':   {col:1,  row:1,  w:12, h:2, visible:true},
            'stat-cards':   {col:1,  row:3,  w:6,  h:2, visible:true},
            'quick-add':    {col:7,  row:3,  w:6,  h:1, visible:true},
            'plan-view':    {col:1,  row:5,  w:12, h:4, visible:true},
            'timetable':    {col:1,  row:9,  w:6,  h:4, visible:true},
            'time-budgets': {col:7,  row:9,  w:6,  h:2, visible:true},
            'notices':      {col:1,  row:13, w:6,  h:2, visible:true},
            'worklogs':     {col:7,  row:13, w:6,  h:2, visible:true},
            'events':       {col:1,  row:15, w:6,  h:2, visible:true},
            'progress':     {col:7,  row:15, w:6,  h:2, visible:true}
        },
        mobile: {
            'widget-row':   {col:1, row:1,  w:2, h:3, visible:true},
            'quick-add':    {col:1, row:4,  w:2, h:1, visible:true},
            'timetable':    {col:1, row:5,  w:2, h:5, visible:true},
            'stat-cards':   {col:1, row:10, w:2, h:2, visible:true},
            'events':       {col:1, row:12, w:2, h:2, visible:true},
            'plan-view':    {col:1, row:14, w:2, h:4, visible:false},
            'time-budgets': {col:1, row:18, w:2, h:2, visible:false},
            'notices':      {col:1, row:20, w:2, h:2, visible:false},
            'worklogs':     {col:1, row:22, w:2, h:2, visible:false},
            'progress':     {col:1, row:24, w:2, h:2, visible:false}
        },
        tablet: {
            'widget-row':   {col:1, row:1,  w:3, h:3, visible:true},
            'quick-add':    {col:1, row:4,  w:3, h:1, visible:true},
            'stat-cards':   {col:1, row:5,  w:2, h:2, visible:true},
            'timetable':    {col:3, row:5,  w:1, h:2, visible:true},
            'plan-view':    {col:1, row:7,  w:3, h:5, visible:true},
            'events':       {col:1, row:12, w:2, h:2, visible:true},
            'time-budgets': {col:3, row:12, w:1, h:2, visible:true},
            'notices':      {col:1, row:14, w:2, h:2, visible:true},
            'worklogs':     {col:3, row:14, w:1, h:2, visible:true},
            'progress':     {col:1, row:16, w:3, h:2, visible:true}
        }
    };

    /* ── State (Single Source of Truth) ── */
    var state = {
        editMode: false,
        viewport: 'pc',
        drag: null,      // { name, widget, startX, startY, origCol, origRow, colW, rowH, snapshot, isResize }
        longPress: null,  // { timer, startX, startY }
        saveTimer: null
    };

    /* ── Viewport Detection ── */
    function detectViewport() {
        var w = window.innerWidth, h = window.innerHeight;
        if (w < BREAKPOINT && w > h) return 'landscape';
        if (w >= TABLET_BP && w < BREAKPOINT) return 'tablet';
        if (w < TABLET_BP) return 'mobile';
        return 'pc';
    }

    function getCols() {
        var vp = state.viewport;
        if (vp === 'landscape' || vp === 'tablet') return COLS.tablet;
        return COLS[vp] || COLS.pc;
    }

    function getRowH() {
        return ROW_H[state.viewport] || ROW_H.pc;
    }

    function isMobile() {
        return state.viewport !== 'pc';
    }

    function getStorageKey() {
        var vp = state.viewport;
        if (vp === 'landscape') return STORAGE_KEY.tablet;
        return STORAGE_KEY[vp] || STORAGE_KEY.pc;
    }

    /* ── Layout Persistence ── */
    function cloneLayout(src) {
        var out = {};
        for (var k in src) out[k] = {col:src[k].col, row:src[k].row, w:src[k].w, h:src[k].h, visible:src[k].visible};
        return out;
    }

    function getDefaultLayout() {
        var vp = state.viewport;
        if (vp === 'landscape' || vp === 'tablet') return cloneLayout(DEFAULTS.tablet);
        return cloneLayout(DEFAULTS[vp] || DEFAULTS.pc);
    }

    function loadLayout() {
        try {
            var raw = localStorage.getItem(getStorageKey());
            if (raw) {
                var parsed = JSON.parse(raw);
                if (parsed._v !== LAYOUT_VERSION) return getDefaultLayout();
                delete parsed._v;
                var defaults = getDefaultLayout();
                for (var k in defaults) {
                    if (!parsed[k]) parsed[k] = cloneLayout({x: defaults[k]}).x
                        ? {col:defaults[k].col, row:defaults[k].row, w:defaults[k].w, h:defaults[k].h, visible:defaults[k].visible}
                        : defaults[k];
                }
                return parsed;
            }
        } catch(e) {}
        return getDefaultLayout();
    }

    function saveLayoutDebounced(layout) {
        clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(function() {
            try {
                var copy = cloneLayout(layout);
                copy._v = LAYOUT_VERSION;
                localStorage.setItem(getStorageKey(), JSON.stringify(copy));
            } catch(e) {}
        }, SAVE_DEBOUNCE_MS);
    }

    function saveLayoutImmediate(layout) {
        clearTimeout(state.saveTimer);
        try {
            var copy = cloneLayout(layout);
            copy._v = LAYOUT_VERSION;
            localStorage.setItem(getStorageKey(), JSON.stringify(copy));
        } catch(e) {}
    }

    /* ── DOM Helpers ── */
    function getGrid() { return document.getElementById('dashboardGrid'); }
    function getWidgets() { return getGrid().querySelectorAll('.dashboard-widget[data-widget]'); }
    function getWidget(name) { return getGrid().querySelector('.dashboard-widget[data-widget="' + name + '"]'); }

    /* ── Collision Resolution (single pass, push-down) ── */
    function resolveCollisions(layout) {
        var items = [];
        for (var k in layout) {
            if (layout[k] && layout[k].visible) items.push({name: k, cfg: layout[k]});
        }
        items.sort(function(a, b) { return a.cfg.row - b.cfg.row || a.cfg.col - b.cfg.col; });

        var maxDepth = items.length * 2;
        var changed = true;
        while (changed && maxDepth-- > 0) {
            changed = false;
            for (var i = 0; i < items.length; i++) {
                for (var j = i + 1; j < items.length; j++) {
                    if (overlaps(items[i].cfg, items[j].cfg)) {
                        items[j].cfg.row = items[i].cfg.row + items[i].cfg.h;
                        changed = true;
                    }
                }
            }
        }
    }

    function overlaps(a, b) {
        return !(a.col + a.w <= b.col || b.col + b.w <= a.col ||
                 a.row + a.h <= b.row || b.row + b.h <= a.row);
    }

    /* ── Compact Layout (pull up) ── */
    function compactLayout(layout) {
        var items = [];
        for (var k in layout) {
            if (layout[k] && layout[k].visible) items.push({name: k, cfg: layout[k]});
        }
        items.sort(function(a, b) { return a.cfg.row - b.cfg.row || a.cfg.col - b.cfg.col; });

        for (var i = 0; i < items.length; i++) {
            var cfg = items[i].cfg;
            var minRow = 1;
            for (var j = 0; j < i; j++) {
                var other = items[j].cfg;
                if (!(cfg.col + cfg.w <= other.col || other.col + other.w <= cfg.col)) {
                    var endRow = other.row + other.h;
                    if (endRow > minRow) minRow = endRow;
                }
            }
            cfg.row = minRow;
        }
    }

    /* ── Apply Layout to DOM ── */
    function applyLayout() {
        state.viewport = detectViewport();
        var layout = loadLayout();
        var widgets = getWidgets();

        // Mark widgets missing from DOM as invisible, then compact to fill gaps
        var domNames = new Set();
        widgets.forEach(function(el) { domNames.add(el.dataset.widget); });
        for (var k in layout) {
            if (layout[k] && layout[k].visible && !domNames.has(k)) {
                layout[k].visible = false;
            }
        }
        compactLayout(layout);

        widgets.forEach(function(el) {
            var name = el.dataset.widget;
            var cfg = layout[name];
            if (!cfg || !cfg.visible) {
                el.style.display = 'none';
                return;
            }
            el.style.display = '';
            el.style.gridColumn = cfg.col + ' / span ' + cfg.w;
            el.style.gridRow = cfg.row + ' / span ' + cfg.h;

            el.classList.toggle('widget-rows-1', cfg.h === 1);
            el.classList.toggle('widget-rows-2', cfg.h === 2);
            el.classList.toggle('widget-rows-3', cfg.h >= 3);

            if (isMobile()) {
                var presets = el.querySelectorAll('.widget-size-presets button');
                presets.forEach(function(btn) {
                    var sz = MOBILE_SIZE_MAP[btn.dataset.size];
                    btn.classList.toggle('active', sz && sz.w === cfg.w && sz.h === cfg.h);
                });
            }
        });

        var addBtn = document.getElementById('addWidgetBtn');
        if (addBtn) {
            var showAdd = state.editMode && isMobile();
            addBtn.style.display = showAdd ? '' : 'none';
            if (showAdd) {
                var maxRow = 1;
                for (var k in layout) {
                    if (layout[k] && layout[k].visible) {
                        var endRow = layout[k].row + layout[k].h;
                        if (endRow > maxRow) maxRow = endRow;
                    }
                }
                addBtn.style.gridRow = maxRow + ' / span 1';
            }
        }
    }

    /* ── Edit Mode ── */
    function toggleEditMode() {
        state.editMode = !state.editMode;
        document.body.classList.toggle('dash-edit-mode', state.editMode);

        var banner = document.getElementById('editBanner');
        if (banner) banner.classList.toggle('hidden', !state.editMode);

        var editBtn = document.getElementById('editModeBtn');
        if (editBtn) {
            editBtn.style.color = state.editMode ? 'var(--color-accent)' : '';
            editBtn.style.background = state.editMode ? 'var(--color-accent-soft)' : '';
        }

        var config = document.getElementById('widgetConfig');
        if (config) {
            if (state.editMode && !isMobile()) {
                config.classList.remove('hidden');
                renderWidgetToggles();
            } else {
                config.classList.add('hidden');
            }
        }
        applyLayout();
    }

    /* ── Widget Toggles ── */
    function renderWidgetToggles() {
        var container = document.getElementById('widgetToggles');
        if (!container) return;
        var layout = loadLayout();
        var html = '';
        for (var name in WIDGET_LABELS) {
            if (!getWidget(name)) continue;
            var cfg = layout[name];
            var active = cfg && cfg.visible;
            html += '<button type="button" data-action="toggle-visibility" data-widget="' + name + '" ' +
                    'class="px-3 py-2 text-xs rounded-lg border transition-all ' +
                    (active
                        ? 'border-amber-300 dark:border-amber-600 text-amber-700 dark:text-amber-300" style="background: var(--color-accent-soft);"'
                        : 'border-slate-200 dark:border-slate-600 text-slate-400" style="background: var(--color-border-subtle);"') +
                    '>' + (WIDGET_LABELS[name] || name) + '</button>';
        }
        container.innerHTML = html;
    }

    function toggleWidgetVisibility(name) {
        var layout = loadLayout();
        if (!layout[name]) {
            var defaults = getDefaultLayout();
            layout[name] = defaults[name] || {col:1, row:1, w:getCols(), h:2, visible:true};
        }
        layout[name].visible = !layout[name].visible;
        if (layout[name].visible) {
            var maxRow = 1;
            for (var k in layout) {
                if (layout[k] && layout[k].visible && k !== name) {
                    var endRow = layout[k].row + layout[k].h;
                    if (endRow > maxRow) maxRow = endRow;
                }
            }
            layout[name].row = maxRow;
        }
        saveLayoutImmediate(layout);
        applyLayout();
        renderWidgetToggles();
    }

    /* ── Remove Widget ── */
    function removeWidget(name) {
        var el = getWidget(name);
        if (el) {
            el.classList.add('removing');
            setTimeout(function() {
                var layout = loadLayout();
                if (layout[name]) layout[name].visible = false;
                compactLayout(layout);
                saveLayoutImmediate(layout);
                applyLayout();
                renderWidgetToggles();
            }, 200);
        }
    }

    /* ── Reset Layout ── */
    function resetLayout() {
        for (var k in STORAGE_KEY) localStorage.removeItem(STORAGE_KEY[k]);
        applyLayout();
        renderWidgetToggles();
    }

    /* ── Mobile Size Presets ── */
    function setMobileSize(name, size) {
        if (!isMobile()) return;
        var sz = MOBILE_SIZE_MAP[size];
        if (!sz) return;
        var layout = loadLayout();
        if (!layout[name]) return;
        layout[name].w = sz.w;
        layout[name].h = sz.h;
        resolveCollisions(layout);
        saveLayoutImmediate(layout);
        applyLayout();
    }

    /* ── Preview Element ── */
    function showPreview(cfg) {
        var grid = getGrid();
        var preview = document.getElementById('dashGridPreview');
        if (!preview) {
            preview = document.createElement('div');
            preview.className = 'grid-preview';
            preview.id = 'dashGridPreview';
            grid.appendChild(preview);
        }
        preview.style.gridColumn = cfg.col + ' / span ' + cfg.w;
        preview.style.gridRow = cfg.row + ' / span ' + cfg.h;
    }

    function hidePreview() {
        var preview = document.getElementById('dashGridPreview');
        if (preview) preview.remove();
    }

    /* ── Unified Pointer Events (drag + resize) ── */
    function initPointerEvents() {
        var grid = getGrid();
        if (!grid) return;

        /* Pointer Down */
        grid.addEventListener('pointerdown', function(e) {
            if (!state.editMode) return;
            if (e.target.closest('[data-action]')) return;  // let event delegation handle clicks

            var isResize = !!e.target.closest('.widget-resize-handle');
            var header = e.target.closest('.widget-header');

            if (!isResize && !header) return;
            if (header && e.target.closest('.widget-remove-btn')) return;

            var widget = e.target.closest('.dashboard-widget');
            if (!widget) return;
            var name = widget.dataset.widget;

            // Mobile: require long-press for header drag (not resize)
            if (!isResize && isMobile()) {
                state.longPress = {
                    timer: setTimeout(function() {
                        if (navigator.vibrate) navigator.vibrate(50);
                        startDrag(e, widget, name, false);
                    }, LONG_PRESS_MS),
                    startX: e.clientX,
                    startY: e.clientY
                };
                return;
            }

            e.preventDefault();
            startDrag(e, widget, name, isResize);
        });

        function startDrag(e, widget, name, isResize) {
            var layout = loadLayout();
            var cfg = layout[name];
            if (!cfg) return;

            var rect = grid.getBoundingClientRect();
            var colW = rect.width / getCols();
            var rowH = getRowH();

            // Take an immutable snapshot of the layout
            var snapshot = cloneLayout(layout);

            state.drag = {
                name: name,
                widget: widget,
                startX: e.clientX,
                startY: e.clientY,
                origCol: cfg.col,
                origRow: cfg.row,
                origW: cfg.w,
                origH: cfg.h,
                colW: colW,
                rowH: rowH,
                snapshot: snapshot,
                isResize: isResize
            };

            widget.classList.add(isResize ? 'dragging' : (isMobile() ? 'lifting' : 'dragging'));
            widget.setPointerCapture(e.pointerId);

            if (!isResize) {
                showPreview(cfg);
            }
        }

        /* Pointer Move */
        document.addEventListener('pointermove', function(e) {
            // Cancel long-press if finger moved
            if (state.longPress && !state.drag) {
                var dist = Math.abs(e.clientX - state.longPress.startX) + Math.abs(e.clientY - state.longPress.startY);
                if (dist > JITTER_PX) {
                    clearTimeout(state.longPress.timer);
                    state.longPress = null;
                }
                return;
            }

            if (!state.drag) return;
            e.preventDefault();

            var d = state.drag;
            var dx = e.clientX - d.startX;
            var dy = e.clientY - d.startY;

            if (d.isResize) {
                // Resize: change width/height
                var newW = Math.max(3, Math.min(getCols() - d.origCol + 1, d.origW + Math.round(dx / d.colW)));
                var newH = Math.max(1, Math.min(6, d.origH + Math.round(dy / d.rowH)));

                showPreview({col: d.origCol, row: d.origRow, w: newW, h: newH});
                d.widget.style.gridColumn = d.origCol + ' / span ' + newW;
                d.widget.style.gridRow = d.origRow + ' / span ' + newH;
            } else {
                // Move: change col/row
                var cfg = d.snapshot[d.name];
                var newCol = Math.max(1, Math.min(getCols() - cfg.w + 1, d.origCol + Math.round(dx / d.colW)));
                var newRow = Math.max(1, d.origRow + Math.round(dy / d.rowH));

                showPreview({col: newCol, row: newRow, w: cfg.w, h: cfg.h});

                if (isMobile()) {
                    d.widget.style.gridColumn = newCol + ' / span ' + cfg.w;
                    d.widget.style.gridRow = newRow + ' / span ' + cfg.h;
                } else {
                    d.widget.style.opacity = '0.3';
                }
            }
        });

        /* Pointer Up */
        document.addEventListener('pointerup', function(e) {
            if (state.longPress) {
                clearTimeout(state.longPress.timer);
                state.longPress = null;
            }
            if (!state.drag) return;

            var d = state.drag;
            var dx = e.clientX - d.startX;
            var dy = e.clientY - d.startY;

            // Apply from immutable snapshot
            var layout = cloneLayout(d.snapshot);

            if (d.isResize) {
                var cfg = layout[d.name];
                cfg.w = Math.max(3, Math.min(getCols() - cfg.col + 1, d.origW + Math.round(dx / d.colW)));
                cfg.h = Math.max(1, Math.min(6, d.origH + Math.round(dy / d.rowH)));
            } else {
                var cfg = layout[d.name];
                cfg.col = Math.max(1, Math.min(getCols() - cfg.w + 1, d.origCol + Math.round(dx / d.colW)));
                cfg.row = Math.max(1, d.origRow + Math.round(dy / d.rowH));
            }

            resolveCollisions(layout);
            compactLayout(layout);
            saveLayoutImmediate(layout);

            d.widget.classList.remove('dragging', 'lifting');
            d.widget.style.opacity = '';
            hidePreview();

            state.drag = null;
            applyLayout();
        });

        /* Pointer Cancel */
        document.addEventListener('pointercancel', function() {
            if (state.longPress) {
                clearTimeout(state.longPress.timer);
                state.longPress = null;
            }
            if (state.drag) {
                state.drag.widget.classList.remove('dragging', 'lifting');
                state.drag.widget.style.opacity = '';
                hidePreview();
                state.drag = null;
                applyLayout();
            }
        });
    }

    /* ── Bottom Sheet ── */
    function openBottomSheet() {
        var sheet = document.getElementById('widgetBottomSheet');
        if (!sheet) return;
        var container = document.getElementById('bottomSheetWidgets');
        if (!container) return;

        var layout = loadLayout();
        var html = '';
        for (var name in WIDGET_LABELS) {
            if (!getWidget(name)) continue;
            var cfg = layout[name];
            if (cfg && cfg.visible) continue;
            html += '<button data-action="restore-widget" data-widget="' + name + '" ' +
                    'class="w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors text-left" ' +
                    'style="background: var(--color-border-subtle); min-height: 44px;">' +
                    '<span class="text-lg">' + (WIDGET_ICONS[name] || '') + '</span>' +
                    '<span class="text-sm font-medium" style="color: var(--color-text);">' + (WIDGET_LABELS[name] || name) + '</span>' +
                    '</button>';
        }
        if (!html) {
            html = '<p class="text-sm text-center py-4" style="color: var(--color-text-faint);">모든 위젯이 표시 중입니다</p>';
        }
        container.innerHTML = html;
        sheet.classList.remove('hidden');
        requestAnimationFrame(function() { sheet.classList.add('active'); });
    }

    function closeBottomSheet() {
        var sheet = document.getElementById('widgetBottomSheet');
        if (!sheet) return;
        sheet.classList.remove('active');
        setTimeout(function() { sheet.classList.add('hidden'); }, 300);
    }

    function restoreWidget(name) {
        var layout = loadLayout();
        if (!layout[name]) {
            var defaults = getDefaultLayout();
            layout[name] = defaults[name] || {col:1, row:1, w:getCols(), h:2, visible:true};
        }
        layout[name].visible = true;
        var maxRow = 1;
        for (var k in layout) {
            if (layout[k] && layout[k].visible && k !== name) {
                var endRow = layout[k].row + layout[k].h;
                if (endRow > maxRow) maxRow = endRow;
            }
        }
        layout[name].row = maxRow;
        saveLayoutImmediate(layout);
        applyLayout();
        closeBottomSheet();
        renderWidgetToggles();
    }

    /* ── Event Delegation ── */
    function initEventDelegation() {
        document.addEventListener('click', function(e) {
            var target = e.target.closest('[data-action]');
            if (!target) return;
            var action = target.dataset.action;
            var widgetName = target.dataset.widget;

            switch (action) {
                case 'toggle-edit':
                    toggleEditMode();
                    break;
                case 'remove':
                    if (widgetName) removeWidget(widgetName);
                    break;
                case 'resize':
                    if (widgetName && target.dataset.size) setMobileSize(widgetName, target.dataset.size);
                    break;
                case 'reset-layout':
                    resetLayout();
                    break;
                case 'open-sheet':
                    openBottomSheet();
                    break;
                case 'close-sheet':
                    closeBottomSheet();
                    break;
                case 'toggle-config':
                    var panel = document.getElementById('widgetConfig');
                    if (panel) panel.classList.toggle('hidden');
                    break;
                case 'dismiss-onboarding':
                    document.getElementById('onboardingChecklist').style.display = 'none';
                    fetch('/api/onboarding/dismiss', {method: 'POST'}).catch(function(){});
                    break;
                case 'onboarding-step':
                    var step = parseInt(target.dataset.step);
                    if (step) completeOnboardingStep(step);
                    break;
                case 'toggle-visibility':
                    if (widgetName) toggleWidgetVisibility(widgetName);
                    break;
                case 'restore-widget':
                    if (widgetName) restoreWidget(widgetName);
                    break;
                case 'toggle-todo':
                    var todoId = target.dataset.id;
                    if (todoId) toggleDashTodo(target, parseInt(todoId));
                    break;
                case 'focus-start':
                    var mins = parseInt(target.dataset.minutes);
                    if (mins) {
                        var fi = document.getElementById('focusCustomMin');
                        if (fi) fi.value = mins;
                        var ft = document.getElementById('focusTitle');
                        if (ft) ft.value = '';
                        if (typeof _focusStart === 'function') _focusStart(mins);
                    }
                    break;
            }
        });
    }

    /* ── Onboarding ── */
    function markOnboardingDone(step) {
        var el = document.getElementById('ob-step' + step);
        if (!el) return;
        var check = el.querySelector('.ob-check');
        if (check) {
            check.style.background = 'var(--color-accent)';
            check.style.borderColor = 'var(--color-accent)';
            check.innerHTML = '<svg class="w-3 h-3" style="color:var(--color-text-inverse, #fff)" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
        }
        el.style.opacity = '0.6';
    }

    function completeOnboardingStep(step) {
        var links = [null, '/todos', '/calendar', null, '/forms'];
        fetch('/api/onboarding/step/' + step, {method: 'POST'}).then(function() {
            markOnboardingDone(step);
            var prog = document.getElementById('onboardingProgress');
            var w = parseInt(prog.style.width) || 0;
            prog.style.width = Math.min(100, w + 25) + '%';
            if (parseInt(prog.style.width) >= 100) setTimeout(function() { document.getElementById('onboardingChecklist').style.display = 'none'; }, 1000);
        }).catch(function(){});
        if (links[step]) window.location.href = links[step];
    }

    function initOnboarding() {
        fetch('/api/onboarding').then(function(r) { return r.json(); }).then(function(d) {
            if (d.dismissed) return;
            var done = 0;
            for (var i = 1; i <= 4; i++) {
                if (d['step' + i]) { done++; markOnboardingDone(i); }
            }
            if (done < 4) {
                document.getElementById('onboardingChecklist').classList.remove('hidden');
                document.getElementById('onboardingProgress').style.width = (done / 4 * 100) + '%';
            }
        }).catch(function(){});
    }

    /* ── Dashboard Todo Toggle ── */
    function toggleDashTodo(btn, todoId) {
        fetch('/todos/' + todoId + '/toggle', {
            method: 'POST',
            headers: {'X-No-Redirect': '1'}
        }).then(function(res) {
            if (!res.ok) return;
            var wasCompleted = btn.dataset.completed === 'true';
            btn.dataset.completed = wasCompleted ? 'false' : 'true';

            if (wasCompleted) {
                btn.classList.remove('bg-amber-500', 'border-amber-500');
                btn.classList.add('border-slate-300', 'dark:border-slate-500');
                btn.innerHTML = '';
            } else {
                btn.classList.add('bg-amber-500', 'border-amber-500');
                btn.classList.remove('border-slate-300', 'dark:border-slate-500');
                btn.innerHTML = '<svg class="w-2 h-2 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
            }

            var row = btn.closest('.flex');
            var titleEl = row ? row.querySelector('span.text-xs') : null;
            if (titleEl) {
                titleEl.classList.toggle('line-through');
                titleEl.classList.toggle('text-slate-400');
                if (wasCompleted) {
                    titleEl.classList.add('text-slate-700', 'dark:text-slate-200');
                } else {
                    titleEl.classList.remove('text-slate-700', 'dark:text-slate-200');
                }
            }

            var card = btn.closest('.work-card');
            if (card) {
                var badge = card.querySelector('.border-b span.text-xs.font-medium');
                if (badge && badge.textContent.includes('/')) {
                    var allBtns = card.querySelectorAll('[data-action="toggle-todo"]');
                    var completed = Array.from(allBtns).filter(function(b) { return b.dataset.completed === 'true'; }).length;
                    badge.textContent = completed + '/' + allBtns.length;
                }
            }
        }).catch(function(){});
    }

    /* ── Quick Add Natural Language ── */
    function initQuickAdd() {
        var DAY_MAP = {'월':1,'화':2,'수':3,'목':4,'금':5,'토':6,'일':0};
        var todayEl = document.getElementById('quickDueDate');
        if (!todayEl) return;
        var TODAY_ISO = todayEl.value;

        function parseNaturalDate(text) {
            var today = new Date(TODAY_ISO + 'T00:00:00');
            var patterns = [
                {regex: /^내일까지\s+/, days: 1}, {regex: /^모레까지\s+/, days: 2}, {regex: /^오늘까지\s+/, days: 0},
                {regex: /^내일\s+/, days: 1}, {regex: /^모레\s+/, days: 2}, {regex: /^오늘\s+/, days: 0}
            ];
            for (var i = 0; i < patterns.length; i++) {
                if (patterns[i].regex.test(text)) {
                    var d = new Date(today); d.setDate(d.getDate() + patterns[i].days);
                    return {title: text.replace(patterns[i].regex, '').trim(), dueDate: fmtDate(d)};
                }
            }
            var m = text.match(/^이번\s*주\s*(월|화|수|목|금|토|일)\s+/);
            if (m) return {title: text.replace(m[0], '').trim(), dueDate: fmtDate(getWeekday(today, DAY_MAP[m[1]], false))};
            m = text.match(/^다음\s*주\s*(월|화|수|목|금|토|일)\s+/);
            if (m) return {title: text.replace(m[0], '').trim(), dueDate: fmtDate(getWeekday(today, DAY_MAP[m[1]], true))};
            m = text.match(/^(월|화|수|목|금|토|일)요일\s+/);
            if (m) return {title: text.replace(m[0], '').trim(), dueDate: fmtDate(getWeekday(today, DAY_MAP[m[1]], false))};
            m = text.match(/\s+(오늘|내일|모레)까지$/);
            if (m) {
                var off = m[1] === '오늘' ? 0 : m[1] === '내일' ? 1 : 2;
                var d2 = new Date(today); d2.setDate(d2.getDate() + off);
                return {title: text.replace(m[0], '').trim(), dueDate: fmtDate(d2)};
            }
            return {title: text.trim(), dueDate: null};
        }
        function getWeekday(today, target, next) {
            var d = new Date(today), diff = target - d.getDay();
            if (next) { diff += 7; if (diff > 13) diff -= 7; } else { if (diff < 0) diff += 7; }
            d.setDate(d.getDate() + diff); return d;
        }
        function fmtDate(d) {
            return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
        }

        var titleInput = document.getElementById('quickTitle');
        var previewEl = document.getElementById('datePreview');
        var dueDateInput = document.getElementById('quickDueDate');

        if (titleInput) {
            titleInput.addEventListener('input', function() {
                var text = this.value;
                if (!text.trim()) {
                    previewEl.classList.add('hidden');
                    dueDateInput.value = TODAY_ISO;
                    return;
                }
                var result = parseNaturalDate(text);
                if (result.dueDate && result.dueDate !== TODAY_ISO) {
                    previewEl.textContent = '마감: ' + result.dueDate;
                    previewEl.classList.remove('hidden');
                    dueDateInput.value = result.dueDate;
                } else {
                    previewEl.classList.add('hidden');
                    dueDateInput.value = TODAY_ISO;
                }
            });
        }

        var form = document.getElementById('quickAddForm');
        if (form) {
            form.addEventListener('submit', function(e) {
                var result = parseNaturalDate(titleInput.value);
                if (result.dueDate) dueDateInput.value = result.dueDate;
                if (result.title && result.title !== titleInput.value) titleInput.value = result.title;
            });
        }
    }

    /* ── Timetable Needle ── */
    function initTimetableNeedle() {
        var needle = document.getElementById('miniNeedle');
        var mt = document.getElementById('miniTime');
        if (!needle && !mt) return;
        var now = new Date();
        var h = now.getHours() + now.getMinutes() / 60;
        var angle = (h / 24) * 360;
        if (needle) needle.setAttribute('transform', 'rotate(' + angle + ',100,100)');
        if (mt) mt.textContent = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
    }

    /* ── Responsive Resize ── */
    var resizeDebounce = null;
    function onResize() {
        clearTimeout(resizeDebounce);
        resizeDebounce = setTimeout(function() {
            state.viewport = detectViewport();
            applyLayout();
        }, 200);
    }

    /* ── Initialize ── */
    function init() {
        state.viewport = detectViewport();
        applyLayout();
        initPointerEvents();
        initEventDelegation();
        initQuickAdd();
        initOnboarding();
        initTimetableNeedle();
        window.addEventListener('resize', onResize);
    }

    document.addEventListener('DOMContentLoaded', init);

    /* ── Public API ── */
    return {
        toggleEditMode: toggleEditMode,
        removeWidget: removeWidget,
        resetLayout: resetLayout,
        setMobileSize: setMobileSize,
        openBottomSheet: openBottomSheet,
        closeBottomSheet: closeBottomSheet,
        restoreWidget: restoreWidget,
        toggleWidgetVisibility: toggleWidgetVisibility,
        applyLayout: applyLayout
    };
})();
