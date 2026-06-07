/* actions.js — Event delegation + achievements + confirm modal (extracted from base.html) */
(function(){
 'use strict';

 /* ══ Achievement & Gamification ══ */
 let _completionCount = 0;
 let _completionResetTimer = null;

 // Listen for HTMX responses from todo toggle
 document.body.addEventListener('htmx:afterRequest', function(evt){
  const path = (evt.detail.pathInfo || {}).requestPath || evt.detail.requestConfig?.path || '';
  if(!path.match(/\/todos\/\d+\/toggle/)) return;

  _completionCount++;
  clearTimeout(_completionResetTimer);
  _completionResetTimer = setTimeout(function(){ _completionCount = 0; }, 5000);

  // Particle effect on the toggled element
  const target = evt.detail.target || evt.detail.elt;
  if(target){
   const rect = target.getBoundingClientRect();
   const cx = rect.left + 24, cy = rect.top + 24;
   spawnParticles(cx, cy, _completionCount >= 3 ? 12 : 5);
  }

  // Check for new achievements (non-blocking)
  fetch('/api/achievements/check').then(function(r){return r.json()}).then(function(data){
   // Show achievement toasts
   if(data.new_achievements && data.new_achievements.length > 0){
    data.new_achievements.forEach(function(a, i){
     setTimeout(function(){
      showAchievementToast(a.icon, a.title, a.desc);
     }, i * 800);
    });
    // Full confetti for achievements
    if(typeof launchConfetti === 'function') launchConfetti();
   }
   // Update streak badge if visible
   const streakEl = document.querySelector('[data-widget="streak"]');
   if(streakEl && data.streak !== undefined){
    const numEl = streakEl.querySelector('.text-lg.font-extrabold');
    if(numEl) numEl.textContent = data.streak;
   }
  }).catch(function(){});

  // Check if all today's todos are done — full confetti
  setTimeout(function(){
   const todayTodos = document.querySelectorAll('[data-todo-id]:not(.opacity-50)');
   if(todayTodos.length === 0){
    const allTodos = document.querySelectorAll('[data-todo-id]');
    if(allTodos.length > 0 && typeof launchConfetti === 'function'){
     launchConfetti();
     showToast('오늘 할일 모두 완료!', 'success');
    }
   }
  }, 300);
 });

 // Particle burst effect
 function spawnParticles(x, y, count){
  const colors = ['#f59e0b','#ef4444','#10b981','#6366f1','#ec4899','#8b5cf6'];
  for(let i = 0; i < count; i++){
   const p = document.createElement('div');
   p.className = 'particle';
   p.style.left = x + 'px';
   p.style.top = y + 'px';
   p.style.background = colors[i % colors.length];
   const angle = (Math.PI * 2 / count) * i;
   const dist = 20 + Math.random() * 30;
   const dx = Math.cos(angle) * dist;
   const dy = Math.sin(angle) * dist;
   p.style.animation = 'none';
   document.body.appendChild(p);
   p.animate([
    { transform: 'translate(0,0) scale(1)', opacity: 1 },
    { transform: 'translate('+dx+'px,'+dy+'px) scale(0)', opacity: 0 }
   ], { duration: 500 + Math.random()*200, easing: 'ease-out', fill: 'forwards' });
   setTimeout((function(el){return function(){el.remove();}})(p), 800);
  }
 }

 // Full confetti (reuse existing or create)
 window.launchConfetti = function(){
  const colors = ['#f59e0b','#ef4444','#10b981','#6366f1','#ec4899','#8b5cf6','#14b8a6','#f97316'];
  for(let i = 0; i < 40; i++){
   const c = document.createElement('div');
   c.className = 'confetti-piece';
   c.style.left = Math.random()*100+'vw';
   c.style.background = colors[Math.floor(Math.random()*colors.length)];
   c.style.width = (6+Math.random()*8)+'px';
   c.style.height = (6+Math.random()*8)+'px';
   c.style.borderRadius = Math.random()>0.5?'50%':'2px';
   c.style.animationDuration = (2+Math.random()*2)+'s';
   c.style.animationDelay = Math.random()*0.5+'s';
   document.body.appendChild(c);
   setTimeout((function(el){return function(){el.remove();}})(c), 4500);
  }
 };

 // Achievement toast
 function showAchievementToast(icon, title, desc){
  const container = document.getElementById('toastContainer');
  if(!container) return;
  const toast = document.createElement('div');
  toast.className = 'achievement-toast';
  const iconEl = document.createElement('span');
  iconEl.style.fontSize = '1.5rem';
  iconEl.textContent = icon;
  const wrapDiv = document.createElement('div');
  const titleP = document.createElement('p');
  titleP.style.cssText = 'font-weight:700;font-size:0.875rem;color:var(--color-text);';
  titleP.textContent = title;
  const descP = document.createElement('p');
  descP.style.cssText = 'font-size:0.75rem;color:var(--color-text-muted);';
  descP.textContent = desc;
  wrapDiv.appendChild(titleP);
  wrapDiv.appendChild(descP);
  toast.appendChild(iconEl);
  toast.appendChild(wrapDiv);
  container.appendChild(toast);
  setTimeout(function(){
   toast.style.opacity = '0';
   toast.style.transform = 'translateY(-1rem)';
   toast.style.transition = 'all 0.3s ease';
   setTimeout(function(){ toast.remove(); }, 300);
  }, 4000);
 }

 /* ══ Event Delegation Handler (click) ══ */
 document.addEventListener('click', function(e) {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.getAttribute('data-action');
  switch(action) {
   case 'close-sidebar-more': closeSidebarMore(); break;
   case 'toggle-dark-mode': toggleDarkMode(); break;
   case 'toggle-sidebar': toggleSidebar(); break;
   case 'toggle-notif-panel': toggleNotifPanel(); break;
   case 'toggle-more-menu': toggleMoreMenu(); break;
   case 'toggle-command-palette': toggleCommandPalette(); break;
   case 'cmd-quick-add-todo': cmdQuickAddTodo(); break;
   case 'cmd-start-focus': cmdStartFocus(parseInt(el.getAttribute('data-minutes'))||25); break;
   case 'toggle-dark-mode-and-cmd': toggleDarkMode(); toggleCommandPalette(); break;
   case 'toggle-dark-mode-and-more': toggleDarkMode(); toggleMoreMenu(); break;
   case 'focus-start': _focusStart(parseInt(el.getAttribute('data-minutes'))||25); break;
   case 'focus-start-custom':
    _focusStart(parseInt(document.getElementById('focusCustomMin').value)||25); break;
   case 'focus-stop':
    _focusStop(el.getAttribute('data-complete') === 'true'); break;
   case 'focus-reset': _focusReset(); break;
   case 'open-focus-modal':
    document.getElementById('focusModal').classList.remove('hidden'); break;
   case 'close-focus-modal':
    document.getElementById('focusModal').classList.add('hidden'); break;
   case 'dismiss-pwa-install': dismissPwaInstall(); break;
   case 'install-pwa': installPwa(); break;
   case 'dismiss-review': dismissReview(el.getAttribute('data-mode')); break;
   case 'close-event-modal': closeEventModal(); break;
   case 'add-new-event-offset': addNewEventOffset(); break;
   case 'open-preview':
    openPreview(el.getAttribute('data-preview-url'), el.getAttribute('data-name'), el.getAttribute('data-type')); break;
   case 'close-preview': closePreview(); break;
   case 'hide-status': hideStatus(); break;
   case 'toggle-add-form': toggleAddForm(); break;
   case 'add-specific-time': addSpecificTime(); break;
   case 'add-tpl-item': addTplItem(); break;
   case 'bulk-mode-on': bulkModeOn(); break;
   case 'bulk-select-all': bulkSelectAll(); break;
   case 'bulk-mode-off': bulkModeOff(); break;
   case 'bulk-action': bulkAction(el.getAttribute('data-bulk-type')); break;
   case 'toggle-desc-field':
    document.getElementById('descField').classList.toggle('hidden'); break;
   case 'add-new-todo-offset': addNewTodoOffset(); break;
   case 'toggle-dark-mode-settings': toggleDarkMode(); break;
   case 'set-accent-color': setAccentColor(el.getAttribute('data-color')); break;
   case 'set-font-size': setFontSize(el.getAttribute('data-size')); break;
   case 'add-offset': addOffset(el.getAttribute('data-offset-type')); break;
   case 'request-notif-permission': requestNotifPermission(); break;
   case 'toggle-push-subscription': togglePushSubscription(); break;
   case 'test-push': testPush(); break;
   case 'save-morning-brief': saveMorningBrief(); break;
   /* -- onclick->data-action (calendar) -- */
   case 'open-event-modal':
    if (typeof openEventModal === 'function') openEventModal(el.getAttribute('data-date'));
    break;
   case 'edit-event':
    e.stopPropagation();
    if (typeof editEvent === 'function') editEvent(parseInt(el.getAttribute('data-event-id')));
    break;
   case 'edit-gcal-event':
    e.stopPropagation();
    if (typeof editGcalEvent === 'function') editGcalEvent(el.getAttribute('data-gcal-id'));
    break;
   /* -- onclick->data-action (timetable) -- */
   case 'click-user-block':
    if (typeof clickUserBlock === 'function') clickUserBlock(el);
    break;
   case 'show-block-detail':
    if (typeof showBlockDetail === 'function') showBlockDetail(el);
    break;
   case 'edit-block':
    if (typeof editBlock === 'function') editBlock(
     parseInt(el.getAttribute('data-block-id')),
     el.getAttribute('data-start'),
     el.getAttribute('data-end'),
     el.getAttribute('data-title'),
     el.getAttribute('data-color'),
     el.getAttribute('data-icon') || ''
    );
    break;
   case 'select-color':
    if (typeof selectColor === 'function') selectColor(el.getAttribute('data-color'));
    break;
   case 'select-icon':
    if (typeof selectIcon === 'function') selectIcon(el.getAttribute('data-icon'));
    break;
   case 'cancel-block-form':
    if (typeof cancelForm === 'function') cancelForm();
    break;
   /* -- onclick->data-action (worklogs) -- */
   case 'set-wl-hours':
    { const wlH = document.getElementById('wlHours');
    if (wlH) wlH.value = el.getAttribute('data-hours'); }
    break;
   /* -- onclick->data-action (habits) -- */
   case 'open-habit-form':
    { const hf = document.getElementById('habitAddForm');
    if (hf) { hf.open = true; setTimeout(function(){ const inp = document.querySelector('#habitAddForm input[name=name]'); if (inp) inp.focus(); }, 100); } }
    break;
   /* -- favorites toggle -- */
   case 'toggle-favorite':
    e.preventDefault(); e.stopPropagation();
    if (typeof toggleFavorite === 'function') toggleFavorite(el.getAttribute('data-href'));
    break;
   /* -- subtask form toggle -- */
   case 'toggle-subtask-form':
    { const sf = document.getElementById('subtaskForm-' + el.getAttribute('data-todo-id'));
    if (sf) { sf.classList.toggle('hidden'); if (!sf.classList.contains('hidden')) sf.querySelector('input[name=title]').focus(); } }
    break;
   /* -- subtask inline edit -- */
   case 'inline-edit-subtask':
    (function(s) {
     const inp = document.createElement('input');
     inp.type = 'text'; inp.value = s.textContent.trim();
     inp.className = 'text-xs px-1 py-0.5 border rounded focus-accent flex-1 min-w-0';
     inp.style.background = 'var(--color-surface)';
     s.replaceWith(inp); inp.focus(); inp.select();
     let saving = false;
     function save() {
      if (saving) return; saving = true;
      const v = inp.value.trim();
      if (!v) { inp.replaceWith(s); return; }
      htmx.ajax('PUT', '/subtasks/' + el.getAttribute('data-sub-id'), {target: '#todo-' + el.getAttribute('data-todo-id'), swap: 'outerHTML', values: {title: v}});
     }
     inp.addEventListener('blur', function() { setTimeout(save, 100); });
     inp.addEventListener('keydown', function(ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); save(); }
      if (ev.key === 'Escape') { ev.preventDefault(); inp.replaceWith(s); }
     });
    })(el);
    break;
   /* -- todo edit form: notification offset -- */
   case 'add-edit-todo-offset':
    if (typeof addEditTodoOffset === 'function') addEditTodoOffset(parseInt(el.getAttribute('data-todo-id')));
    break;
   /* -- todo edit form: byday collect+submit -- */
   case 'collect-edit-byday':
    if (typeof collectEditByday === 'function') collectEditByday(parseInt(el.getAttribute('data-todo-id')));
    break;
   /* -- event edit modal close -- */
   case 'close-edit-event':
    document.getElementById('editEventContainer').innerHTML = '';
    break;
   /* -- event notification offset -- */
   case 'add-event-offset':
    if (typeof addEventOffset === 'function') addEventOffset(parseInt(el.getAttribute('data-event-id')));
    break;
   /* -- event delete -- */
   case 'delete-event':
    confirmAction('삭제할까요?', function() {
     fetch('/events/' + el.getAttribute('data-event-id'), {method: 'DELETE', headers: {'HX-Request': 'true'}})
      .then(function() { htmx.ajax('GET', '/calendar' + location.search, {target: 'body', swap: 'innerHTML'}); });
    });
    break;
   /* -- Google event delete -- */
   case 'delete-gcal-event':
    confirmAction('삭제할까요?', function() {
     fetch('/events/gcal/' + el.getAttribute('data-gcal-id'), {method: 'DELETE', headers: {'HX-Request': 'true'}})
      .then(function() { htmx.ajax('GET', '/calendar' + location.search, {target: 'body', swap: 'innerHTML'}); });
    });
    break;
   /* -- calendar todo toggle -- */
   case 'toggle-cal-todo':
    e.stopPropagation();
    (function(btn) {
     const todoId = btn.getAttribute('data-todo-id');
     const p = btn.closest('.flex');
     fetch('/todos/' + todoId + '/toggle', {method: 'POST'}).then(function() {
      const done = !btn.style.background;
      if (done) {
       btn.style.background = 'var(--color-success)'; btn.style.borderColor = 'var(--color-success)';
       btn.innerHTML = '<svg class="w-2 h-2 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
      } else {
       btn.style.background = ''; btn.style.borderColor = ''; btn.innerHTML = '';
      }
      const s = p.querySelector('span'); if (s) s.classList.toggle('line-through');
     });
    })(el);
    break;
   /* -- category delete -- */
   case 'delete-category':
    (function(catId) {
     confirmAction('삭제할까요?', function() {
      fetch('/settings/categories/' + catId, {method: 'DELETE'}).then(function() {
       const row = document.querySelector('[data-cat-id="' + catId + '"]');
       if (row) row.remove();
      });
     });
    })(el.getAttribute('data-cat-id'));
    break;
   /* -- Google calendar list fetch -- */
   case 'fetch-gcal-calendars':
    fetch('/api/gcal/calendars').then(function(r) { return r.json(); }).then(function(cals) {
     const s = document.getElementById('gcalSelect'); s.innerHTML = '';
     cals.forEach(function(c) { const o = document.createElement('option'); o.value = c.id; o.textContent = c.summary; s.appendChild(o); });
    }).catch(function() { alert('캘린더 목록을 불러올 수 없습니다'); });
    break;
   /* -- Google calendar ID save -- */
   case 'save-gcal-id':
    document.getElementById('gcalIdInput').value = document.getElementById('gcalSelect').value;
    break;
   /* -- iCal URL copy -- */
   case 'copy-ical-url':
    navigator.clipboard.writeText(document.getElementById('icalUrl').value).then(function() {
     el.textContent = '복사됨!'; setTimeout(function() { el.textContent = '복사'; }, 1500);
    });
    break;
   /* -- notice delete -- */
   case 'delete-notice':
    (function(nid) {
     confirmAction('삭제할까요?', function() {
      fetch('/notices/' + nid, {method: 'DELETE'}).then(function() {
       const row = document.querySelector('[data-notice-id="' + nid + '"]');
       if (row) row.remove();
      });
     });
    })(el.getAttribute('data-notice-id'));
    break;
   /* -- scroll to form -- */
   case 'scroll-to-add-form':
    { const formEl = document.getElementById(el.getAttribute('data-form-id'));
    if (formEl) { formEl.scrollIntoView({behavior:'smooth'}); const inp2 = formEl.querySelector('input[name=title]'); if (inp2) inp2.focus(); } }
    break;
   case 'scroll-to-form-input':
    { const formSel = 'form[action="' + el.getAttribute('data-form-action') + '"] input[name=' + el.getAttribute('data-input-name') + ']';
    const tgtInp = document.querySelector(formSel);
    if (tgtInp) { tgtInp.scrollIntoView({behavior:'smooth'}); tgtInp.focus(); } }
    break;
   case 'focus-input':
    { const fi = document.querySelector(el.getAttribute('data-target'));
    if (fi) fi.focus(); }
    break;
   /* -- worklog undo delete -- */
   case 'undo-delete-worklog':
    if (typeof undoDelete === 'function') undoDelete(el.closest('[data-log-id]'), '/worklogs/' + el.getAttribute('data-log-id'));
    break;
  }
 });

 /* ══ Event Delegation Handler (change) ══ */
 document.addEventListener('change', function(e) {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.getAttribute('data-action');
  switch(action) {
   case 'toggle-event-rrule':
    if (typeof toggleEventRrule === 'function') toggleEventRrule();
    break;
   case 'toggle-new-event-default':
    if (typeof toggleNewEventDefault === 'function') toggleNewEventDefault();
    break;
   case 'update-tracking-ui':
    if (typeof updateTrackingUI === 'function') updateTrackingUI();
    break;
   case 'save-wl-category':
    localStorage.setItem('wl_last_cat', el.value);
    break;
   case 'navigate-wl-date':
    if (el.value) location.href = '/worklogs?date=' + el.value;
    break;
   case 'handle-image-file':
    if (typeof handleImageFileSelect === 'function') handleImageFileSelect(el);
    break;
   /* -- todo recurrence settings -- */
   case 'toggle-add-rrule':
    if (typeof toggleAddRrule === 'function') toggleAddRrule();
    break;
   case 'toggle-add-rrule-extra':
    if (typeof toggleAddRruleExtra === 'function') toggleAddRruleExtra();
    break;
   case 'toggle-add-end-fields':
    if (typeof toggleAddEndFields === 'function') toggleAddEndFields();
    break;
   case 'toggle-new-todo-default':
    if (typeof toggleNewTodoDefault === 'function') toggleNewTodoDefault();
    break;
   /* -- todo edit form recurrence -- */
   case 'toggle-edit-rrule':
    if (typeof toggleEditRrule === 'function') toggleEditRrule(parseInt(el.getAttribute('data-todo-id')));
    break;
   case 'toggle-edit-rrule-extra':
    if (typeof toggleEditRruleExtra === 'function') toggleEditRruleExtra(parseInt(el.getAttribute('data-todo-id')));
    break;
   case 'toggle-edit-end-fields':
    if (typeof toggleEditEndFields === 'function') toggleEditEndFields(parseInt(el.getAttribute('data-todo-id')));
    break;
   case 'toggle-edit-todo-default':
    if (typeof toggleEditTodoDefault === 'function') toggleEditTodoDefault(parseInt(el.getAttribute('data-todo-id')));
    break;
   /* -- event edit form default toggle -- */
   case 'toggle-event-default':
    if (typeof toggleEventDefault === 'function') toggleEventDefault(parseInt(el.getAttribute('data-event-id')));
    break;
   /* -- automation trigger UI -- */
   case 'update-trigger-ui':
    if (typeof updateTriggerUI === 'function') updateTriggerUI();
    break;
   case 'update-rrule-extra':
    if (typeof updateRruleExtra === 'function') updateRruleExtra();
    break;
   /* -- file upload -- */
   case 'upload-files':
    if (typeof uploadFiles === 'function') uploadFiles(el.files);
    break;
   /* -- background preview -- */
   case 'update-bg-preview':
    if (typeof updateBgPreview === 'function') updateBgPreview();
    break;
  }
 });

 /* ══ Confirm Modal ══ */
 const modal = document.getElementById('confirmModal');
 const msgEl = document.getElementById('confirmMessage');
 const okBtn = document.getElementById('confirmOk');
 const cancelBtn = document.getElementById('confirmCancel');
 let _cb = null;
 window.confirmAction = function(message, callback) {
  msgEl.textContent = message;
  _cb = callback;
  modal.classList.remove('hidden');
 };
 function closeConfirm() { modal.classList.add('hidden'); _cb = null; }
 okBtn.addEventListener('click', function() { const cb = _cb; closeConfirm(); if (cb) cb(); });
 cancelBtn.addEventListener('click', closeConfirm);
 modal.addEventListener('click', function(e) { if (e.target === modal) closeConfirm(); });
 document.addEventListener('submit', function(e) {
  const form = e.target;
  const msg = form.getAttribute('data-confirm');
  if (!msg) return;
  e.preventDefault();
  confirmAction(msg, function() { form.removeAttribute('data-confirm'); form.submit(); });
 });
})();
