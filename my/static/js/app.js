// app.js - extracted from base.html inline scripts

 // Dark mode init — 3-mode: light / dark / auto
 function applyTheme() {
 var mode = localStorage.getItem('theme') || 'auto';
 var html = document.documentElement;
 if (mode === 'dark' || (mode === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
 html.classList.add('dark');
 } else {
 html.classList.remove('dark');
 }
 updateThemeIcon(mode);
 }
 function updateThemeIcon(mode) {
 var btn = document.getElementById('themeToggleBtn');
 var label = document.getElementById('themeLabel');
 var iconSun = document.getElementById('themeIconSun');
 var iconMoon = document.getElementById('themeIconMoon');
 var iconAuto = document.getElementById('themeIconAuto');
 if (!btn) return;
 if (iconSun) iconSun.classList.add('hidden');
 if (iconMoon) iconMoon.classList.add('hidden');
 if (iconAuto) iconAuto.classList.add('hidden');
 if (mode === 'light') { if (iconSun) iconSun.classList.remove('hidden'); if (label) label.textContent = '라이트 모드'; }
 else if (mode === 'dark') { if (iconMoon) iconMoon.classList.remove('hidden'); if (label) label.textContent = '다크 모드'; }
 else { if (iconAuto) iconAuto.classList.remove('hidden'); if (label) label.textContent = '시스템 설정'; }
 }
 function toggleDarkMode() {
 document.documentElement.style.transition = 'background 0.3s, color 0.3s';
 document.body.style.transition = 'background 0.3s, color 0.3s';
 var mode = localStorage.getItem('theme') || 'auto';
 var next = mode === 'light' ? 'dark' : mode === 'dark' ? 'auto' : 'light';
 localStorage.setItem('theme', next);
 applyTheme();
 updateBgOverlay();
 setTimeout(function(){ document.documentElement.style.transition = ''; document.body.style.transition = ''; }, 350);
 }
 // Migrate old darkMode key
 if (localStorage.getItem('darkMode') !== null && !localStorage.getItem('theme')) {
 localStorage.setItem('theme', localStorage.getItem('darkMode') === 'true' ? 'dark' : 'light');
 localStorage.removeItem('darkMode');
 }
 applyTheme();
 window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
 if ((localStorage.getItem('theme') || 'auto') === 'auto') applyTheme();
 });

 // Background overlay for dark/light
 function updateBgOverlay() {
 const isDark = document.documentElement.classList.contains('dark');
 const light = document.querySelector('.bg-overlay-light');
 const dark = document.querySelector('.bg-overlay-dark');
 if (light) { light.classList.toggle('hidden', isDark); }
 if (dark) { dark.classList.toggle('hidden', !isDark); }
 }
 updateBgOverlay();

 function toggleMoreMenu() {
 var menu = document.getElementById('moreMenu');
 var sheet = menu.querySelector(':scope > div:last-child');
 if (menu.classList.contains('hidden')) {
 menu.classList.remove('hidden');
 requestAnimationFrame(function() {
 sheet.style.transform = 'translateY(0)';
 sheet.style.transition = 'transform 350ms cubic-bezier(0.16, 1, 0.3, 1)';
 });
 sheet.style.transform = 'translateY(100%)';
 } else {
 sheet.style.transform = 'translateY(100%)';
 sheet.style.transition = 'transform 250ms cubic-bezier(0.4, 0, 0.2, 1)';
 setTimeout(function() { menu.classList.add('hidden'); sheet.style.transform = ''; }, 260);
 }
 }

 function toggleSidebar() {
 const sb = document.getElementById('sidebar');
 const ov = document.getElementById('sidebarOverlay');
 sb.classList.toggle('-translate-x-full');
 ov.classList.toggle('hidden');
 }

 // Toast notification system
 function showToast(message, type) {
 type = type || 'success';
 var container = document.getElementById('toastContainer');
 var toast = document.createElement('div');
 toast.className = 'toast toast-' + type;
 var icons = { success: '✓', error: '✕', info: 'i' };
 var iconSpan = document.createElement('span');
 iconSpan.style.fontWeight = '700';
 iconSpan.style.fontSize = '0.875rem';
 iconSpan.textContent = icons[type] || '';
 var msgSpan = document.createElement('span');
 msgSpan.textContent = message;
 toast.appendChild(iconSpan);
 toast.appendChild(msgSpan);
 container.appendChild(toast);
 setTimeout(function() {
 toast.classList.add('toast-hide');
 setTimeout(function() { toast.remove(); }, 300);
 }, 3000);
 }

 // Undo delete pattern: hide element → show undo toast → delete after 5s
 var _undoTimers = {};
 function undoDelete(el, url) {
 var id = url;
 el.style.transition = 'opacity 0.3s, max-height 0.3s';
 el.style.opacity = '0'; el.style.maxHeight = '0'; el.style.overflow = 'hidden';
 var container = document.getElementById('toastContainer');
 var toast = document.createElement('div');
 toast.className = 'toast toast-info';
 toast.style.cursor = 'pointer';
 var delSpan = document.createElement('span');
 delSpan.textContent = '삭제됨';
 var undoBtn = document.createElement('button');
 undoBtn.style.cssText = 'margin-left:8px;padding:2px 10px;background:rgba(255,255,255,0.2);border-radius:6px;font-weight:600;font-size:0.8rem;';
 undoBtn.textContent = '되돌리기';
 toast.appendChild(delSpan);
 toast.appendChild(undoBtn);
 container.appendChild(toast);
 undoBtn.onclick = function(e) {
 e.stopPropagation();
 clearTimeout(_undoTimers[id]);
 delete _undoTimers[id];
 el.style.opacity = '1'; el.style.maxHeight = ''; el.style.overflow = '';
 toast.remove();
 showToast('복구됨', 'success');
 };
 _undoTimers[id] = setTimeout(function() {
 delete _undoTimers[id];
 fetch(url, {method:'DELETE', headers:{'HX-Request':'true'}}).then(function() {
 el.remove();
 });
 toast.classList.add('toast-hide');
 setTimeout(function() { toast.remove(); }, 300);
 }, 5000);
 setTimeout(function() {
 if (!_undoTimers[id]) return;
 toast.classList.add('toast-hide');
 setTimeout(function() { toast.remove(); }, 300);
 }, 5000);
 }

 // WebSocket with exponential backoff reconnection
 var _wsReconnectDelay = 1000;
 var _wsPingInterval = null;
 var _ws = null;
 function connectWS() {
 var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
 _ws = new WebSocket(proto + '//' + location.host + '/ws');

 _ws.onopen = function() {
 _wsReconnectDelay = 1000;
 // Client-side ping every 25s to keep NAT/proxy alive
 clearInterval(_wsPingInterval);
 _wsPingInterval = setInterval(function() {
 if (_ws && _ws.readyState === WebSocket.OPEN) {
 _ws.send(JSON.stringify({type: 'ping'}));
 }
 }, 25000);
 };

 _ws.onmessage = function(e) {
 var data;
 try { data = JSON.parse(e.data); } catch(ex) { return; }
 if (data.type === 'ping' || data.type === 'pong') return;

 var cnt = parseInt(sessionStorage.getItem('_sseSkip') || '0');
 if (cnt > 0) { sessionStorage.setItem('_sseSkip', String(cnt - 1)); return; }

 // Handle both old broadcast format and new emit format
 var page = data.data || data.event || '';
 if (typeof page === 'object') page = page.type || '';
 var currentPage = window.location.pathname.split('/')[1] || 'dashboard';
 if (page === currentPage || page === 'dashboard') {
 if (document.querySelector('[hx-get]')) {
 htmx.trigger(document.body, 'sse-refresh');
 } else {
 window.location.reload();
 }
 }
 };

 _ws.onclose = function() {
 clearInterval(_wsPingInterval);
 setTimeout(function() {
 _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, 30000);
 connectWS();
 }, _wsReconnectDelay);
 };

 _ws.onerror = function() {
 if (_ws) _ws.close();
 };
 }
 connectWS();

 // Reconnect on tab visibility change
 document.addEventListener('visibilitychange', function() {
 if (!document.hidden && (!_ws || _ws.readyState !== WebSocket.OPEN)) {
 _wsReconnectDelay = 1000;
 connectWS();
 }
 });

 // Command Palette
 var _cmdDebounce = null;
 var _cmdIdx = -1;
 function toggleCommandPalette() {
 var cp = document.getElementById('cmdPalette');
 cp.classList.toggle('hidden');
 if (!cp.classList.contains('hidden')) {
 var input = document.getElementById('cmdInput');
 input.value = '';
 input.focus();
 _cmdIdx = -1;
 document.getElementById('cmdQuickActions').classList.remove('hidden');
 document.getElementById('cmdSearchResults').classList.add('hidden');
 }
 }
 document.getElementById('cmdInput').addEventListener('input', function() {
 var q = this.value.trim();
 clearTimeout(_cmdDebounce);
 if (q.length < 2) {
 document.getElementById('cmdQuickActions').classList.remove('hidden');
 document.getElementById('cmdSearchResults').classList.add('hidden');
 _cmdIdx = -1;
 return;
 }
 // Check for action prefix "할일 추가: ..." or "추가: ..."
 var addMatch = q.match(/^(?:할일\s*)?추가[:：]\s*(.+)/);
 if (addMatch) {
  var title = addMatch[1].trim();
  var sr = document.getElementById('cmdSearchResults');
  var qa = document.getElementById('cmdQuickActions');
  sr.textContent = '';
  var headerDiv = document.createElement('div');
  headerDiv.className = 'px-3 py-1 text-[10px] font-bold uppercase tracking-wider';
  headerDiv.style.color = 'var(--color-text-faint)';
  headerDiv.textContent = '빠른 추가';
  sr.appendChild(headerDiv);
  var addBtn = document.createElement('button');
  addBtn.className = 'cmd-item flex items-center gap-3 px-3 py-2 rounded-lg text-sm hover-surface transition-colors w-full text-left';
  addBtn.style.color = 'var(--color-text-muted)';
  addBtn.addEventListener('click', (function(t) { return function() { cmdPaletteAddTodo(t); }; })(title));
  var plusSpan = document.createElement('span');
  plusSpan.className = 'w-6 text-center';
  plusSpan.style.color = 'var(--color-accent)';
  plusSpan.textContent = '+';
  addBtn.appendChild(plusSpan);
  var labelSpan = document.createElement('span');
  labelSpan.textContent = '"' + title + '" 할일 추가';
  addBtn.appendChild(labelSpan);
  sr.appendChild(addBtn);
  sr.classList.remove('hidden');
  qa.classList.add('hidden');
  _cmdIdx = -1;
  return;
 }

 _cmdDebounce = setTimeout(function() {
 fetch('/api/search?q=' + encodeURIComponent(q)).then(function(r){return r.json()}).then(function(data) {
 var sr = document.getElementById('cmdSearchResults');
 var qa = document.getElementById('cmdQuickActions');
 sr.textContent = '';
 if (!data.items || data.items.length === 0) {
 // SAFE: no user data — static message
 sr.innerHTML = '<div class="px-3 py-4 text-sm text-center" style="color:var(--color-text-faint);">검색 결과 없음</div>';
 } else {
 var srHeader = document.createElement('div');
 srHeader.className = 'px-3 py-1 text-[10px] font-bold uppercase tracking-wider';
 srHeader.style.color = 'var(--color-text-faint)';
 srHeader.textContent = '검색 결과';
 sr.appendChild(srHeader);
 data.items.forEach(function(it) {
 var link = document.createElement('a');
 link.href = it.url;
 link.className = 'cmd-item flex items-center gap-3 px-3 py-2 rounded-lg text-sm hover-surface transition-colors';
 link.style.color = 'var(--color-text-muted)';
 var typeSpan = document.createElement('span');
 typeSpan.className = 'w-auto text-[10px] px-1.5 py-0.5 rounded font-medium';
 typeSpan.textContent = it.type;
 link.appendChild(typeSpan);
 var titleSpan = document.createElement('span');
 titleSpan.className = 'truncate';
 titleSpan.textContent = it.title;
 link.appendChild(titleSpan);
 sr.appendChild(link);
 });
 }
 sr.classList.remove('hidden');
 qa.classList.add('hidden');
 _cmdIdx = -1;
 });
 }, 300);
 });
 document.getElementById('cmdInput').addEventListener('keydown', function(e) {
 var items = document.querySelectorAll('#cmdResults .cmd-item:not(.hidden)');
 if (!items.length) items = document.querySelectorAll('#cmdResults .cmd-item');
 if (e.key === 'ArrowDown') {
 e.preventDefault();
 _cmdIdx = Math.min(_cmdIdx + 1, items.length - 1);
 items.forEach(function(el,i){el.classList.toggle('',i===_cmdIdx);el.classList.toggle('',i===_cmdIdx);});
 if (items[_cmdIdx]) items[_cmdIdx].scrollIntoView({block:'nearest'});
 } else if (e.key === 'ArrowUp') {
 e.preventDefault();
 _cmdIdx = Math.max(_cmdIdx - 1, 0);
 items.forEach(function(el,i){el.classList.toggle('',i===_cmdIdx);el.classList.toggle('',i===_cmdIdx);});
 if (items[_cmdIdx]) items[_cmdIdx].scrollIntoView({block:'nearest'});
 } else if (e.key === 'Enter' && _cmdIdx >= 0 && items[_cmdIdx]) {
 e.preventDefault();
 items[_cmdIdx].click();
 }
 });

 // Keyboard shortcuts are now in /static/shortcuts.js

 // HTMX: page transition effect (native-style fade-in)
 document.addEventListener('htmx:afterSwap', function(e) {
 if (e.detail && e.detail.target) {
 e.detail.target.classList.remove('page-transition');
 void e.detail.target.offsetWidth;
 e.detail.target.classList.add('page-transition');
 }
 });

 // HTMX: close mobile sidebar before navigation
 document.addEventListener('htmx:beforeRequest', function(e) {
 if (window.innerWidth < 1024) {
 var sb = document.getElementById('sidebar');
 var ov = document.getElementById('sidebarOverlay');
 if (!sb.classList.contains('-translate-x-full')) {
 sb.classList.add('-translate-x-full');
 ov.classList.add('hidden');
 }
 }
 var verb = (e.detail.requestConfig || {}).verb;
 if (verb && verb !== 'get') {
 var cnt = parseInt(sessionStorage.getItem('_sseSkip') || '0');
 sessionStorage.setItem('_sseSkip', String(cnt + 1));
 }
 });

 // HTMX: form submission feedback
 document.addEventListener('htmx:afterRequest', function(e) {
 if (!e.detail || !e.detail.requestConfig || e.detail.requestConfig.verb === 'get') return;
 var xhr = e.detail.xhr;
 var status = xhr ? xhr.status : 0;
 if (status >= 200 && status < 400) {
 var verb = e.detail.requestConfig.verb;
 showToast(verb === 'delete' ? '삭제되었습니다' : '저장되었습니다', 'success');
 } else if (status >= 400) {
 showToast('오류가 발생했습니다', 'error');
 }
 });

 // Network error handling
 document.addEventListener('htmx:sendError', function() {
 showToast('네트워크 오류: 연결을 확인해주세요', 'error');
 });

 // Global drag-drop file upload
 (function() {
 var dragCounter = 0;
 var overlay = document.createElement('div');
 overlay.id = 'dropOverlay';
 overlay.className = 'fixed inset-0 z-[9999] hidden items-center justify-center pointer-events-none';
 overlay.style.cssText = 'background: var(--color-accent-soft); border: 3px dashed var(--color-accent);';
 // SAFE: no user data — static SVG icon and fixed text
 overlay.innerHTML = '<div class="rounded-2xl shadow-xl px-8 py-6 text-center pointer-events-none" style="background: var(--color-surface);"><svg class="w-12 h-12 mx-auto mb-3" style="color: var(--color-accent);" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/></svg><p style="color: var(--color-accent-text); font-weight: 500;">파일을 놓으면 업로드합니다</p></div>';
 document.body.appendChild(overlay);

 document.addEventListener('dragenter', function(e) {
 e.preventDefault();
 dragCounter++;
 if (e.dataTransfer.types.indexOf('Files') !== -1) {
 overlay.classList.remove('hidden');
 overlay.classList.add('flex');
 }
 });
 document.addEventListener('dragleave', function(e) {
 e.preventDefault();
 dragCounter--;
 if (dragCounter <= 0) {
 dragCounter = 0;
 overlay.classList.add('hidden');
 overlay.classList.remove('flex');
 }
 });
 document.addEventListener('dragover', function(e) { e.preventDefault(); });
 document.addEventListener('drop', function(e) {
 e.preventDefault();
 dragCounter = 0;
 overlay.classList.add('hidden');
 overlay.classList.remove('flex');

 var files = e.dataTransfer.files;
 if (!files.length) return;

 var formData = new FormData();
 for (var i = 0; i < files.length; i++) formData.append('files', files[i]);

 fetch('/files', { method: 'POST', body: formData }).then(function(res) {
 if (res.ok) {
 showToast('파일 업로드 완료', 'success');
 if (location.pathname.indexOf('/files') === 0) location.reload();
 } else {
 showToast('업로드 실패', 'error');
 }
 }).catch(function() {
 showToast('업로드 실패', 'error');
 });
 });
 })();

 // Render memo markdown on page load (marked + DOMPurify loaded on demand)
 var _memoLibsLoading = false;
 function _doMemoRender() {
 marked.setOptions({ breaks: true, gfm: true });
 document.querySelectorAll('.memo-content').forEach(function(el) {
 if (el.dataset.rendered) return;
 // SAFE: sanitized by DOMPurify — no raw user data
 el.innerHTML = DOMPurify.sanitize(marked.parse(el.textContent));
 el.dataset.rendered = '1';
 });
 }
 function renderMemoMarkdown() {
 if (!document.querySelector('.memo-content:not([data-rendered])')) return;
 if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
 _doMemoRender();
 } else if (!_memoLibsLoading) {
 _memoLibsLoading = true;
 var s1 = document.createElement('script');
 s1.src = 'https://cdn.jsdelivr.net/npm/marked@12/marked.min.js';
 s1.onload = function() {
 var s2 = document.createElement('script');
 s2.src = 'https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js';
 s2.onload = function() { _memoLibsLoading = false; _doMemoRender(); };
 document.head.appendChild(s2);
 };
 document.head.appendChild(s1);
 }
 }
 renderMemoMarkdown();
 document.addEventListener('htmx:afterSettle', function() { renderMemoMarkdown(); });

 // Notification panel toggle
 function toggleNotifPanel() {
 var panel = document.getElementById('notifPanel');
 panel.classList.toggle('hidden');
 if (!panel.classList.contains('hidden')) {
 refreshNotifPanel();
 }
 }
 // Close panel on outside click
 document.addEventListener('click', function(e) {
 var panel = document.getElementById('notifPanel');
 if (panel && !panel.classList.contains('hidden') && !e.target.closest('#notifPanel') && !e.target.closest('[onclick*="toggleNotifPanel"]')) {
 panel.classList.add('hidden');
 }
 });

 // Refresh notification panel content
 function refreshNotifPanel() {
 var status = document.getElementById('notifPermStatus');
 if ('Notification' in window) {
 var perm = Notification.permission;
 status.textContent = perm === 'granted' ? '허용됨' : perm === 'denied' ? '차단됨' : '미설정';
 }
 fetch('/api/reminders').then(function(r) { return r.json(); }).catch(function(){ return []; }).then(function(items) {
 var list = document.getElementById('notifList');
 var badge = document.getElementById('notifBadge');
 list.textContent = '';
 if (!items.length) {
 // SAFE: no user data — static empty-state message
 list.innerHTML = '<p class="p-4 text-sm text-center" style="color: var(--color-text-faint);">알림이 없습니다</p>';
 badge.classList.add('hidden');
 return;
 }
 badge.textContent = items.length;
 badge.classList.remove('hidden');
 var icons = { overdue: '🔴', today: '🟡', event: '🔵' };
 items.forEach(function(item) {
 var link = document.createElement('a');
 link.href = item.url || '#';
 link.className = 'flex items-start gap-3 p-3 transition-colors';
 link.style.color = 'var(--color-text-muted)';
 link.addEventListener('mouseover', function() { this.style.background = 'var(--color-border-subtle)'; });
 link.addEventListener('mouseout', function() { this.style.background = ''; });
 var iconSpan = document.createElement('span');
 iconSpan.className = 'text-base mt-0.5';
 iconSpan.textContent = icons[item.type] || '📌';
 link.appendChild(iconSpan);
 var contentDiv = document.createElement('div');
 contentDiv.className = 'flex-1 min-w-0';
 var titleP = document.createElement('p');
 titleP.className = 'text-sm font-medium truncate';
 titleP.style.color = 'var(--color-text)';
 titleP.textContent = item.title || '';
 contentDiv.appendChild(titleP);
 var bodyP = document.createElement('p');
 bodyP.className = 'text-xs';
 bodyP.style.color = 'var(--color-text-faint)';
 bodyP.textContent = item.body || '';
 contentDiv.appendChild(bodyP);
 link.appendChild(contentDiv);
 list.appendChild(link);
 });
 }).catch(function() {});
 }

 // Browser notifications handled by /static/notifications.js

 // Offline form queuing: intercept failed form submissions
 document.addEventListener('htmx:sendError', function(e) {
 if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
 var cfg = e.detail || {};
 var requestConfig = cfg.requestConfig || {};
 if (requestConfig.verb && requestConfig.verb !== 'get') {
 navigator.serviceWorker.controller.postMessage({
 type: 'QUEUE_FORM',
 url: requestConfig.path || window.location.pathname,
 method: (requestConfig.verb || 'post').toUpperCase(),
 headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
 body: requestConfig.parameters || ''
 });
 if (typeof showToast === 'function') {
 showToast('오프라인: 연결 복구 시 자동 전송됩니다', 'warning');
 }
 }
 });

 // PWA Service Worker registration
 if ('serviceWorker' in navigator) {
 navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function() {});
 }

var _focusTimer=null,_focusTotalSec=0,_focusRemain=0,_focusSaving=false;
function _focusStart(min){
 _focusTotalSec=min*60;_focusRemain=_focusTotalSec;
 localStorage.setItem('focus_end',Date.now()+_focusTotalSec*1000);
 localStorage.setItem('focus_total',_focusTotalSec);
 localStorage.setItem('focus_title',document.getElementById('focusTitle').value);
 document.getElementById('focusSetup').classList.add('hidden');
 document.getElementById('focusRunning').classList.remove('hidden');
 document.getElementById('focusDone').classList.add('hidden');
 document.getElementById('focusLabel').textContent=localStorage.getItem('focus_title')||min+'분 집중';
 document.getElementById('focusBtn').classList.add('hidden');
 _focusTick();
 _focusTimer=setInterval(_focusTick,1000);
}
function _focusTick(){
 var end=parseInt(localStorage.getItem('focus_end')||'0');
 _focusRemain=Math.max(0,Math.round((end-Date.now())/1000));
 var m=Math.floor(_focusRemain/60),s=_focusRemain%60;
 document.getElementById('focusTime').textContent=(m<10?'0':'')+m+':'+(s<10?'0':'')+s;
 var total=parseInt(localStorage.getItem('focus_total')||'1');
 document.getElementById('focusProgress').style.width=((total-_focusRemain)/total*100)+'%';
 if(_focusRemain<=0){clearInterval(_focusTimer);_focusStop(true);}
}
function _focusStop(save){
 clearInterval(_focusTimer);
 if(save&&_focusSaving) return;
 var total=parseInt(localStorage.getItem('focus_total')||'0');
 var elapsed=total-_focusRemain;
 var min=Math.max(1,Math.round(elapsed/60));
 if(save&&min>=1){
 _focusSaving=true;
 fetch('/focus/complete',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({minutes:min,title:localStorage.getItem('focus_title')||''})
 }).then(function(){
 document.getElementById('focusDoneMsg').textContent=min+'분 업무일지에 기록됨';
 }).catch(function(){
 document.getElementById('focusDoneMsg').textContent=min+'분 집중 완료 (기록 실패)';
 }).finally(function(){
 document.getElementById('focusRunning').classList.add('hidden');
 document.getElementById('focusDone').classList.remove('hidden');
 });
 } else { _focusReset(); }
}
function _focusReset(){
 _focusSaving=false;
 localStorage.removeItem('focus_end');localStorage.removeItem('focus_total');localStorage.removeItem('focus_title');
 document.getElementById('focusSetup').classList.remove('hidden');
 document.getElementById('focusRunning').classList.add('hidden');
 document.getElementById('focusDone').classList.add('hidden');
 document.getElementById('focusBtn').classList.remove('hidden');
 document.getElementById('focusModal').classList.add('hidden');
}
function _focusRestore(){
 var end=parseInt(localStorage.getItem('focus_end')||'0');
 if(end>Date.now()){
 clearInterval(_focusTimer);
 _focusTotalSec=parseInt(localStorage.getItem('focus_total')||'0');
 _focusRemain=Math.round((end-Date.now())/1000);
 document.getElementById('focusSetup').classList.add('hidden');
 document.getElementById('focusRunning').classList.remove('hidden');
 document.getElementById('focusLabel').textContent=localStorage.getItem('focus_title')||'집중 중';
 document.getElementById('focusBtn').classList.add('hidden');
 document.getElementById('focusModal').classList.remove('hidden');
 _focusTick();_focusTimer=setInterval(_focusTick,1000);
 }
}
_focusRestore();
document.addEventListener('htmx:afterSettle',_focusRestore);

(function() {
 // Accent color: apply saved preference
 var accent = localStorage.getItem('accent_color') || 'amber';
 document.body.dataset.accent = accent;

 // Font size: apply saved preference
 var fontSize = localStorage.getItem('font_size') || 'medium';
 document.body.dataset.fontsize = fontSize;
 var fontSizeMap = { small: 'clamp(0.75rem, 0.5625rem + 0.5vw, 0.875rem)', medium: 'clamp(0.8125rem, 0.625rem + 0.5vw, 1rem)', large: 'clamp(0.9375rem, 0.75rem + 0.5vw, 1.125rem)' };
 document.documentElement.style.fontSize = fontSizeMap[fontSize] || 'clamp(0.8125rem, 0.625rem + 0.5vw, 1rem)';

 // Mobile tab bar: hide on scroll down, show on scroll up
 var lastScrollY = 0;
 var tabBar = document.getElementById('mobileTabBar');
 var focusBtn = document.getElementById('focusBtn');
 if (tabBar) {
 var mainEl = document.querySelector('main[role="main"]') || document.querySelector('main');
 if (mainEl) {
 mainEl.addEventListener('scroll', function() {
 var currentY = mainEl.scrollTop;
 if (currentY > lastScrollY && currentY > 60) {
 tabBar.style.transform = 'translateY(100%)';
 tabBar.style.transition = 'transform 0.3s ease';
 if (focusBtn) { focusBtn.style.bottom = '1rem'; focusBtn.style.transition = 'bottom 0.3s ease'; }
 } else {
 tabBar.style.transform = 'translateY(0)';
 if (focusBtn) { focusBtn.style.bottom = ''; }
 }
 lastScrollY = currentY;
 }, { passive: true });
 }
 }

 // ── L: Pull-to-Refresh (enhanced with indicator) ──
 (function() {
 var ptrIndicator = document.getElementById('ptrIndicator');
 var pullStart = 0, pulling = false, ptrTriggered = false;
 var mainEl = document.querySelector('main[role="main"]') || document.querySelector('main');
 if (!mainEl || !ptrIndicator) return;
 mainEl.addEventListener('touchstart', function(e) {
 if (mainEl.scrollTop <= 0) {
 pullStart = e.touches[0].clientY;
 pulling = true;
 ptrTriggered = false;
 }
 }, { passive: true });
 mainEl.addEventListener('touchmove', function(e) {
 if (!pulling) return;
 var pullDist = e.touches[0].clientY - pullStart;
 if (pullDist > 60 && !ptrTriggered) {
 ptrIndicator.classList.add('visible');
 }
 if (pullDist > 120 && !ptrTriggered) {
 ptrTriggered = true;
 ptrIndicator.querySelector('.ptr-text').textContent = '새로고침 중...';
 setTimeout(function() { location.reload(); }, 300);
 }
 }, { passive: true });
 mainEl.addEventListener('touchend', function() {
 pulling = false;
 if (!ptrTriggered) {
 ptrIndicator.classList.remove('visible');
 }
 }, { passive: true });
 })();

 // ── J: Sticky header scroll effect ──
 (function() {
 var header = document.querySelector('.glass-header');
 var mainEl = document.querySelector('main[role="main"]') || document.querySelector('main');
 if (!header || !mainEl) return;
 mainEl.addEventListener('scroll', function() {
 header.classList.toggle('scrolled', mainEl.scrollTop > 10);
 }, { passive: true });
 })();
})();

var _deferredInstallPrompt=null;
window.addEventListener('beforeinstallprompt',function(e){
 e.preventDefault();
 _deferredInstallPrompt=e;
 if(!localStorage.getItem('pwa_install_dismissed')){
 setTimeout(function(){document.getElementById('pwaInstallBanner').classList.remove('hidden');},3000);
 }
});
function installPwa(){
 if(_deferredInstallPrompt){_deferredInstallPrompt.prompt();_deferredInstallPrompt.userChoice.then(function(){_deferredInstallPrompt=null;});}
 document.getElementById('pwaInstallBanner').classList.add('hidden');
}
function dismissPwaInstall(){
 document.getElementById('pwaInstallBanner').classList.add('hidden');
 localStorage.setItem('pwa_install_dismissed','1');
 fetch('/api/pwa-install-dismissed',{method:'POST'}).catch(function(){});
}

function showConfetti(){
 var colors=['#d97706','#f59e0b','#10b981','#6366f1','#ec4899','#ef4444'];
 for(var i=0;i<30;i++){
 var el=document.createElement('div');
 el.className='confetti-piece';
 el.style.left=Math.random()*100+'vw';
 el.style.background=colors[Math.floor(Math.random()*colors.length)];
 el.style.borderRadius=Math.random()>0.5?'50%':'0';
 el.style.animationDelay=Math.random()*0.5+'s';
 el.style.animationDuration=(2+Math.random())+'s';
 document.body.appendChild(el);
 setTimeout(function(){el.remove()},3500);
 }
}
document.addEventListener('htmx:afterRequest',function(e){
 var cfg=e.detail&&e.detail.requestConfig;
 if(cfg&&cfg.path&&cfg.path.indexOf('/toggle')>-1&&cfg.verb==='post'){
 showConfetti();
 }
});

fetch('/api/track-visit',{method:'POST'}).catch(function(){});
setTimeout(function(){
 fetch('/api/review-prompt').then(function(r){return r.json()}).then(function(d){
 if(d.show)document.getElementById('reviewSheet').classList.remove('hidden');
 }).catch(function(){});
},5000);
function dismissReview(action){
 document.getElementById('reviewSheet').classList.add('hidden');
 fetch('/api/review-prompt/dismiss',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'action='+action}).catch(function(){});
}

/* ── I: Bottom Sheet utility ── */
var _activeSheet = null;
function openBottomSheet(contentEl) {
 if (_activeSheet) closeBottomSheet();
 var overlay = document.createElement('div');
 overlay.className = 'bottom-sheet-overlay';
 overlay.onclick = closeBottomSheet;
 var sheet = document.createElement('div');
 sheet.className = 'bottom-sheet';
 // SAFE: no user data — static handle element
 sheet.innerHTML = '<div class="bottom-sheet-handle"></div>';
 var content = contentEl.cloneNode(true);
 content.classList.remove('hidden');
 sheet.appendChild(content);
 document.body.appendChild(overlay);
 document.body.appendChild(sheet);
 document.body.classList.add('sheet-open');
 requestAnimationFrame(function() {
 overlay.classList.add('active');
 sheet.classList.add('active');
 });
 _activeSheet = { overlay: overlay, sheet: sheet };
 // Swipe-down to dismiss
 var startY = 0, currentY = 0;
 sheet.addEventListener('touchstart', function(e) {
 if (e.target.closest('input, textarea, select, button, a')) return;
 startY = e.touches[0].clientY;
 }, { passive: true });
 sheet.addEventListener('touchmove', function(e) {
 if (!startY) return;
 currentY = e.touches[0].clientY - startY;
 if (currentY > 0) {
 sheet.style.transform = 'translateY(' + currentY + 'px)';
 }
 }, { passive: true });
 sheet.addEventListener('touchend', function() {
 if (currentY > 100) {
 closeBottomSheet();
 } else {
 sheet.style.transform = '';
 }
 startY = 0; currentY = 0;
 }, { passive: true });
}
function closeBottomSheet() {
 if (!_activeSheet) return;
 _activeSheet.overlay.classList.remove('active');
 _activeSheet.sheet.classList.remove('active');
 document.body.classList.remove('sheet-open');
 var ref = _activeSheet;
 setTimeout(function() {
 ref.overlay.remove();
 ref.sheet.remove();
 }, 400);
 _activeSheet = null;
}

/* ── K: Swipe gesture for list items ── */
function initSwipeItems() {
 if (window.innerWidth > 768) return;
 document.querySelectorAll('.swipe-item').forEach(function(item) {
 if (item._swipeInit) return;
 item._swipeInit = true;
 var startX = 0, currentX = 0, threshold = 80;
 var content = item.querySelector('.swipe-content');
 if (!content) return;
 item.addEventListener('touchstart', function(e) {
 startX = e.touches[0].clientX;
 currentX = 0;
 }, { passive: true });
 item.addEventListener('touchmove', function(e) {
 currentX = e.touches[0].clientX - startX;
 if (Math.abs(currentX) > 10) {
 item.classList.add('swiping');
 content.style.transform = 'translateX(' + Math.max(-120, Math.min(120, currentX)) + 'px)';
 }
 }, { passive: true });
 item.addEventListener('touchend', function() {
 item.classList.remove('swiping');
 if (currentX > threshold) {
 // Swipe right → complete
 var completeBtn = item.querySelector('[data-swipe-complete]');
 if (completeBtn) completeBtn.click();
 } else if (currentX < -threshold) {
 // Swipe left → delete
 var deleteBtn = item.querySelector('[data-swipe-delete]');
 if (deleteBtn && confirm('삭제할까요?')) deleteBtn.click();
 }
 content.style.transform = '';
 startX = 0; currentX = 0;
 }, { passive: true });
 });
}
document.addEventListener('DOMContentLoaded', initSwipeItems);
document.addEventListener('htmx:afterSettle', function() {
 if (document.querySelector('.swipe-item:not([data-swipe-init])')) initSwipeItems();
});

/* ── Q: Long-press context menu ── */
function initLongPress() {
 if (window.innerWidth > 768) return;
 document.querySelectorAll('[data-long-press]').forEach(function(item) {
 if (item._lpInit) return;
 item._lpInit = true;
 var timer = null;
 item.addEventListener('touchstart', function(e) {
 timer = setTimeout(function() {
 if (navigator.vibrate) navigator.vibrate(30);
 var menu = item.querySelector('.context-menu');
 if (menu) {
 menu.classList.toggle('hidden');
 setTimeout(function() { menu.classList.add('hidden'); }, 3000);
 }
 }, 500);
 }, { passive: true });
 item.addEventListener('touchend', function() { clearTimeout(timer); }, { passive: true });
 item.addEventListener('touchmove', function() { clearTimeout(timer); }, { passive: true });
 });
}
document.addEventListener('DOMContentLoaded', initLongPress);
document.addEventListener('htmx:afterSettle', function() {
 if (document.querySelector('[data-long-press]:not([data-lp-init])')) initLongPress();
});

/* ── M: Skeleton Loading for HTMX ── */
document.addEventListener('htmx:beforeRequest', function(e) {
 var target = e.detail.target;
 if (target && !target.querySelector('.skeleton-card')) {
 var skeleton = document.createElement('div');
 skeleton.className = 'skeleton-card htmx-skeleton';
 // SAFE: no user data — static skeleton placeholder
 skeleton.innerHTML = '<div class="skeleton-line" style="width:70%"></div><div class="skeleton-line" style="width:50%"></div><div class="skeleton-line" style="width:85%"></div>';
 target.prepend(skeleton);
 }
});
document.addEventListener('htmx:afterSettle', function(e) {
 var target = e.detail.target;
 if (target) {
 target.querySelectorAll('.htmx-skeleton').forEach(function(s) { s.remove(); });
 }
});

/* ── Prefetch: load page on link hover ── */
(function() {
 var _prefetched = {};
 document.addEventListener('pointerenter', function(e) {
  var link = e.target.closest('a[href^="/"]');
  if (!link || _prefetched[link.href]) return;
  _prefetched[link.href] = true;
  var l = document.createElement('link');
  l.rel = 'prefetch';
  l.href = link.href;
  document.head.appendChild(l);
 }, true);
})();

/* ── Number counter roll animation ── */
(function() {
 function animateCounters() {
  document.querySelectorAll('.stat-number:not([data-counted])').forEach(function(el) {
   var text = el.textContent.trim();
   var match = text.match(/^(\d+)/);
   if (!match) return;
   var target = parseInt(match[1]);
   if (target <= 0 || target > 9999) return;
   el.dataset.counted = '1';
   var suffix = text.replace(/^\d+/, '');
   var start = 0;
   var duration = Math.min(600, target * 30);
   var startTime = null;
   function step(ts) {
    if (!startTime) startTime = ts;
    var progress = Math.min((ts - startTime) / duration, 1);
    var eased = 1 - Math.pow(1 - progress, 3);
    var current = Math.round(start + (target - start) * eased);
    el.textContent = current + suffix;
    if (progress < 1) requestAnimationFrame(step);
   }
   requestAnimationFrame(step);
  });
 }
 // Run on load and after HTMX swaps
 if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', animateCounters);
 } else {
  animateCounters();
 }
 document.addEventListener('htmx:afterSettle', animateCounters);
})();

/* ── Stagger entrance for dashboard grid children ── */
(function() {
 function applyStagger() {
  var grid = document.getElementById('dashboardGrid');
  if (!grid) return;
  var children = grid.querySelectorAll(':scope > div, :scope > section');
  children.forEach(function(child, i) {
   if (child.classList.contains('stagger-applied')) return;
   child.classList.add('stagger-applied');
   child.style.opacity = '0';
   child.style.transform = 'translateY(8px)';
   setTimeout(function() {
    child.style.transition = 'opacity 0.3s var(--ease-out), transform 0.3s var(--ease-out)';
    child.style.opacity = '1';
    child.style.transform = 'translateY(0)';
   }, i * 60);
  });
 }
 if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', applyStagger);
 } else {
  applyStagger();
 }
})();