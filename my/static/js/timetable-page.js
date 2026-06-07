/* timetable-page.js — extracted inline scripts from timetable.html */
(function() {
'use strict';

window.toggleTimetableTodo = function(btn) {
 var item = btn.closest('[data-todo-id]');
 if (!item) return;
 var wasDone = item.classList.contains('opacity-50');
 item.classList.toggle('opacity-50');
 var title = item.querySelector('span.text-sm');
 if (title) title.classList.toggle('line-through');
 if (wasDone) {
  btn.style.background = '';
  btn.style.borderColor = '';
  btn.innerHTML = '';
 } else {
  btn.style.background = 'var(--color-accent)';
  btn.style.borderColor = 'var(--color-accent)';
  btn.innerHTML = '<svg class="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
 }
};

/* Current time needle — only runs if is_today data attribute is set */
var ttContainer = document.getElementById('timetableContainer');
if (ttContainer && ttContainer.dataset.isToday === '1') {
 function updateNeedle() {
  var now = new Date();
  var h = now.getHours() + now.getMinutes() / 60 + now.getSeconds() / 3600;
  var angle = (h / 24) * 360;
  var needle = document.getElementById('timeNeedle');
  if (needle) needle.setAttribute('transform', 'rotate(' + angle + ', 200, 200)');
 }
 updateNeedle();
 setInterval(updateNeedle, 60000);
}

/* Block detail display */
window.showBlockDetail = function(el) {
 var detail = document.getElementById('blockDetail');
 var title = el.getAttribute('data-title');
 var type = el.getAttribute('data-type');
 var startH = parseFloat(el.getAttribute('data-start'));
 var endH = parseFloat(el.getAttribute('data-end'));
 var color = el.getAttribute('data-color');

 document.getElementById('detailDot').style.background = color;
 document.getElementById('detailTitle').textContent = title;

 var sh = Math.floor(startH);
 var sm = Math.round((startH - sh) * 60);
 var eh = Math.floor(endH);
 var em = Math.round((endH - eh) * 60);
 var dur = endH - startH;
 document.getElementById('detailTime').textContent =
  String(sh).padStart(2,'0') + ':' + String(sm).padStart(2,'0') + ' ~ ' +
  String(eh).padStart(2,'0') + ':' + String(em).padStart(2,'0') +
  ' (' + (dur >= 1 ? Math.floor(dur) + '시간' : '') + (Math.round((dur % 1)*60) > 0 ? ' ' + Math.round((dur % 1)*60) + '분' : '') + ')';

 var typeLabel = {'event':'일정','habit':'습관','user_block':'시간표'}[type] || type;
 document.getElementById('detailType').textContent = typeLabel;
 detail.classList.remove('hidden');
};

/* Click user block -> open edit form */
window.clickUserBlock = function(el) {
 window.showBlockDetail(el);
 var id = el.getAttribute('data-id');
 var rawStart = el.getAttribute('data-raw-start');
 var rawEnd = el.getAttribute('data-raw-end');
 var title = el.getAttribute('data-title');
 var color = el.getAttribute('data-color');
 var icon = el.getAttribute('data-icon') || '';
 editBlock(parseInt(id), rawStart, rawEnd, title, color, icon);
};

/* Add/Edit form logic */
var isEditing = false;

window.toggleAddForm = function() {
 var form = document.getElementById('blockForm');
 if (!form.classList.contains('hidden') && !isEditing) {
  form.classList.add('hidden');
  return;
 }
 isEditing = false;
 resetForm();
 document.getElementById('formSubmitBtn').textContent = '추가';
 document.getElementById('blockFormEl').action = '/timetable/blocks';
 var methodInput = document.getElementById('blockFormEl').querySelector('input[name="_method"]');
 if (methodInput) methodInput.remove();
 form.classList.remove('hidden');
};

function editBlock(id, startTime, endTime, title, color, icon) {
 isEditing = true;
 var form = document.getElementById('blockForm');
 form.classList.remove('hidden');
 document.getElementById('formStart').value = startTime;
 document.getElementById('formEnd').value = endTime;
 document.getElementById('formTitle').value = title;
 window.selectColor(color);
 window.selectIcon(icon || '');
 document.getElementById('editBlockId').value = id;
 document.getElementById('formSubmitBtn').textContent = '수정';

 var formEl = document.getElementById('blockFormEl');
 formEl.action = '/timetable/blocks/' + id;
 var existing = formEl.querySelector('input[name="_method"]');
 if (!existing) {
  var mi = document.createElement('input');
  mi.type = 'hidden';
  mi.name = '_method';
  mi.value = 'PUT';
  formEl.appendChild(mi);
 }
 formEl.setAttribute('hx-put', '/timetable/blocks/' + id);
 formEl.removeAttribute('action');
 formEl.removeAttribute('method');

 form.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

window.cancelForm = function() {
 var form = document.getElementById('blockForm');
 form.classList.add('hidden');
 resetForm();
 isEditing = false;
 var formEl = document.getElementById('blockFormEl');
 formEl.action = '/timetable/blocks';
 formEl.method = 'POST';
 formEl.removeAttribute('hx-put');
 var mi = formEl.querySelector('input[name="_method"]');
 if (mi) mi.remove();
};

function resetForm() {
 document.getElementById('formStart').value = '';
 document.getElementById('formEnd').value = '';
 document.getElementById('formTitle').value = '';
 window.selectColor('#6366f1');
 window.selectIcon('');
 document.getElementById('editBlockId').value = '';
}

window.selectColor = function(c) {
 document.getElementById('formColor').value = c;
 document.querySelectorAll('.color-btn').forEach(function(btn) {
  btn.style.borderColor = btn.getAttribute('data-color') === c ? 'var(--color-text)' : 'transparent';
  btn.style.transform = btn.getAttribute('data-color') === c ? 'scale(1.2)' : '';
 });
};

window.selectIcon = function(ic) {
 document.getElementById('formIcon').value = ic;
 document.querySelectorAll('.icon-btn').forEach(function(btn) {
  var match = btn.getAttribute('data-icon') === ic;
  btn.style.borderColor = match ? 'var(--color-accent)' : 'transparent';
  btn.style.background = match ? 'var(--color-accent-soft)' : 'var(--color-border-subtle)';
 });
};

/* Form submission handler for edit mode (hx-put) */
var blockFormEl = document.getElementById('blockFormEl');
if (blockFormEl) {
 blockFormEl.addEventListener('submit', function(e) {
  if (isEditing) {
   e.preventDefault();
   var formEl = this;
   var url = formEl.getAttribute('hx-put');
   if (!url) return;
   var formData = new FormData(formEl);
   fetch(url, {method: 'PUT', body: formData, headers: {'HX-Request': 'true'}})
    .then(function(r) {
     var redir = r.headers.get('HX-Redirect');
     if (redir) { htmx.ajax('GET', redir, {target:'body', swap:'innerHTML'}); }
     else if (r.ok) { htmx.ajax('GET', '/timetable' + location.search, {target:'body', swap:'innerHTML'}); }
    });
  }
 });
}

/* Free time calculation — reads data from #timetableContainer data-time-blocks */
(function() {
 var container = document.getElementById('timetableContainer');
 if (!container) return;
 var blocksJson = container.dataset.timeBlocks;
 if (!blocksJson) return;
 var blocks;
 try { blocks = JSON.parse(blocksJson); } catch(e) { return; }

 var occupied = [];
 blocks.forEach(function(b) {
  occupied.push([b.start_hour, b.end_hour]);
 });
 occupied.sort(function(a,b){ return a[0]-b[0]; });
 var merged = [];
 occupied.forEach(function(seg) {
  if (merged.length && seg[0] <= merged[merged.length-1][1]) {
   merged[merged.length-1][1] = Math.max(merged[merged.length-1][1], seg[1]);
  } else {
   merged.push([seg[0], seg[1]]);
  }
 });
 var freeSlots = [];
 var cursor = 6;
 merged.forEach(function(seg) {
  if (seg[0] > cursor) {
   var gap = seg[0] - cursor;
   if (gap >= 0.5) freeSlots.push([cursor, seg[0], gap]);
  }
  cursor = Math.max(cursor, seg[1]);
 });
 if (cursor < 23) {
  freeSlots.push([cursor, 23, 23 - cursor]);
 }

 var freeContainer = document.getElementById('freeTimeSlots');
 if (freeSlots.length === 0) {
  freeContainer.innerHTML = '<p class="text-center text-sm py-2" style="color: var(--color-text-faint);">빈 시간이 없습니다</p>';
 } else {
  var html = '<div class="space-y-1.5">';
  freeSlots.forEach(function(s) {
   var sh = Math.floor(s[0]);
   var sm = Math.round((s[0]-sh)*60);
   var eh = Math.floor(s[1]);
   var em = Math.round((s[1]-eh)*60);
   var dur = s[2];
   var durLabel = dur >= 1 ? Math.floor(dur) + '시간' : '';
   if (Math.round((dur%1)*60) > 0) durLabel += (durLabel ? ' ' : '') + Math.round((dur%1)*60) + '분';
   html += '<div class="flex items-center justify-between py-1.5 px-2 rounded-lg" style="background: var(--color-border-subtle);">';
   html += '<span class="text-xs font-medium" style="color: var(--color-text-muted);">' +
    String(sh).padStart(2,'0') + ':' + String(sm).padStart(2,'0') + ' ~ ' +
    String(eh).padStart(2,'0') + ':' + String(em).padStart(2,'0') + '</span>';
   html += '<span class="text-xs font-semibold" style="color: var(--color-success);">' + durLabel + ' 여유</span>';
   html += '</div>';
  });
  html += '</div>';
  freeContainer.innerHTML = html;
 }
})();

})();
