/* ============================================================
   Dashboard Widget Interactions (Simplified)
   No layout engine — pure CSS grid handles positioning.
   Only widget-level interactivity remains.
   ============================================================ */
(function() {
    'use strict';

    /* ── Event Delegation ── */
    function initEventDelegation() {
        document.addEventListener('click', function(e) {
            var target = e.target.closest('[data-action]');
            if (!target) return;
            var action = target.dataset.action;

            switch (action) {
                case 'dismiss-onboarding':
                    var ob = document.getElementById('onboardingChecklist');
                    if (ob) ob.style.display = 'none';
                    localStorage.setItem('onboarding_done', '1');
                    fetch('/api/onboarding/dismiss', {method: 'POST'}).catch(function(){});
                    break;
                case 'onboarding-step':
                    var step = parseInt(target.dataset.step);
                    if (step) completeOnboardingStep(step);
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
            if (parseInt(prog.style.width) >= 100) { localStorage.setItem('onboarding_done', '1'); setTimeout(function() { document.getElementById('onboardingChecklist').style.display = 'none'; }, 1000); }
        }).catch(function(){});
        if (links[step]) window.location.href = links[step];
    }

    function initOnboarding() {
        if (localStorage.getItem('onboarding_done')) return;
        fetch('/api/onboarding').then(function(r) { return r.json(); }).then(function(d) {
            if (d.dismissed) { localStorage.setItem('onboarding_done', '1'); return; }
            var done = 0;
            for (var i = 1; i <= 4; i++) {
                if (d['step' + i]) { done++; markOnboardingDone(i); }
            }
            if (done >= 4) {
                localStorage.setItem('onboarding_done', '1');
                return;
            }
            var checklist = document.getElementById('onboardingChecklist');
            if (checklist) {
                checklist.style.display = '';
                var prog = document.getElementById('onboardingProgress');
                if (prog) prog.style.width = (done / 4 * 100) + '%';
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
            form.addEventListener('submit', function() {
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

    /* ── Initialize ── */
    function init() {
        initEventDelegation();
        initQuickAdd();
        initOnboarding();
        initTimetableNeedle();
        /* Update timetable needle every minute */
        setInterval(initTimetableNeedle, 60000);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
