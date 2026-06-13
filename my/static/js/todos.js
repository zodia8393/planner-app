/* RRULE panel controls for add form */
function toggleAddRrule() {
 var sel = document.getElementById('addRepeatType');
 var panel = document.getElementById('addRrulePanel');
 if (sel.value === 'custom') { panel.classList.remove('hidden'); } else { panel.classList.add('hidden'); }
}
function toggleAddRruleExtra() {
 var freq = document.getElementById('addRruleFreq').value;
 document.getElementById('addBydayRow').classList.toggle('hidden', freq !== 'WEEKLY');
 document.getElementById('addBymonthdayRow').classList.toggle('hidden', freq !== 'MONTHLY');
 updateAddRrulePreview();
}
function toggleAddEndFields() {
 var et = document.getElementById('addRruleEndType').value;
 document.getElementById('addRruleCount').classList.toggle('hidden', et !== 'count');
 document.getElementById('addRruleUntil').classList.toggle('hidden', et !== 'until');
 updateAddRrulePreview();
}
function updateAddRrulePreview() {
 var freq = document.getElementById('addRruleFreq').value;
 var interval = document.querySelector('[name="rrule_interval"]');
 var iv = interval ? parseInt(interval.value) || 1 : 1;
 var freqKr = {DAILY: '일', WEEKLY: '주', MONTHLY: '개월', YEARLY: '년'};
 var txt = '매 ' + (iv > 1 ? iv : '') + (freqKr[freq] || freq);
 if (freq === 'WEEKLY') {
 var days = Array.from(document.querySelectorAll('.rrule-byday-add:checked')).map(function(c) { return c.parentElement.textContent.trim(); });
 if (days.length) txt += ' ' + days.join(',');
 }
 document.getElementById('addRrulePreview').textContent = txt;
}
/* Collect byday before form submit */
document.addEventListener('submit', function(e) {
 if (!e.target || !e.target.closest) return;
 if (e.target.closest('#addForm')) {
 var checks = document.querySelectorAll('.rrule-byday-add:checked');
 var vals = Array.from(checks).map(function(c) { return c.value; });
 document.getElementById('addRruleByday').value = vals.join(',');
 }
}, true);

document.addEventListener('DOMContentLoaded', function() {
 var list = document.getElementById('todoList');
 if (list && typeof Sortable !== 'undefined') {
 Sortable.create(list, {
  animation: 150,
  handle: '.drag-handle',
  ghostClass: 'sortable-ghost',
  chosenClass: 'sortable-chosen',
  onEnd: function(evt) {
  var items = list.querySelectorAll('[data-todo-id]');
  var order = Array.from(items).map(function(el) { return el.dataset.todoId; });
  fetch('/todos/reorder', {
   method: 'POST',
   headers: {'Content-Type': 'application/json'},
   body: JSON.stringify({order: order})
  }).catch(function(){});
  }
 });
 }
});

var _bulkSelected = new Set();
function _updateBulkUI() {
 document.getElementById('bulkCount').textContent = _bulkSelected.size;
}
function bulkModeOn() {
 _bulkSelected.clear();
 document.getElementById('bulkBar').classList.remove('hidden');
 document.getElementById('bulkToggle').classList.add('hidden');
 document.querySelectorAll('[data-todo-id]').forEach(function(el) {
 el.style.cursor = 'pointer';
 el.addEventListener('click', _bulkToggleItem);
 });
 _updateBulkUI();
}
function bulkModeOff() {
 _bulkSelected.clear();
 document.getElementById('bulkBar').classList.add('hidden');
 document.getElementById('bulkToggle').classList.remove('hidden');
 document.querySelectorAll('[data-todo-id]').forEach(function(el) {
 el.style.cursor = '';
 el.classList.remove('ring-2'); el.style.removeProperty('--tw-ring-color');
 el.removeEventListener('click', _bulkToggleItem);
 });
}
function _bulkToggleItem(e) {
 if (!e.target || !e.target.closest) return;
 if (e.target.closest('button, a, input, form')) return;
 var id = this.dataset.todoId;
 if (_bulkSelected.has(id)) {
 _bulkSelected.delete(id);
 this.classList.remove('ring-2'); this.style.removeProperty('--tw-ring-color');
 } else {
 _bulkSelected.add(id);
 this.classList.add('ring-2'); this.style.setProperty('--tw-ring-color', 'var(--color-accent)');
 }
 _updateBulkUI();
}
function bulkSelectAll() {
 document.querySelectorAll('[data-todo-id]').forEach(function(el) {
 _bulkSelected.add(el.dataset.todoId);
 el.classList.add('ring-2'); el.style.setProperty('--tw-ring-color', 'var(--color-accent)');
 });
 _updateBulkUI();
}
function bulkAction(action) {
 if (_bulkSelected.size === 0) return;
 var msg = action === 'delete' ? _bulkSelected.size + '개 항목을 삭제할까요?' : _bulkSelected.size + '개 항목을 완료 처리할까요?';
 confirmAction(msg, function() { fetch('/todos/bulk', {
 method: 'POST',
 headers: {'Content-Type': 'application/json'},
 body: JSON.stringify({action: action, ids: Array.from(_bulkSelected)})
 }).then(function(r) { return r.json(); }).then(function(d) {
  if (d.ok) htmx.ajax('GET', '/todos' + location.search, {target:'body', swap:'innerHTML'});
 }).catch(function() { _partialRefresh('/todos' + location.search); });
 });
}
if (location.hash === '#new') { var ti = document.querySelector('input[name="title"]'); if (ti) { ti.scrollIntoView({block:'center'}); ti.focus(); } history.replaceState(null, '', location.pathname + location.search); }

// --- New Todo Reminder Offsets ---
(function(){
 var labels = {'0_minute':'당일 오전 9시','5_minute':'5분 전','10_minute':'10분 전','15_minute':'15분 전','30_minute':'30분 전','1_hour':'1시간 전','2_hour':'2시간 전','3_hour':'3시간 전','1_day':'1일 전','2_day':'2일 전','3_day':'3일 전','1_week':'1주 전'};
 var offsets = [];
 var input = document.getElementById('newTodoReminderOffsets');

 function render() {
 var c = document.getElementById('newTodoOffsetChips');
 c.innerHTML = '';
 offsets.forEach(function(o, i) {
  var lbl = labels[o.value+'_'+o.unit] || (o.value+(o.unit==='minute'?'분':o.unit==='hour'?'시간':o.unit==='day'?'일':'주')+' 전');
  c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">'+lbl+' <button type="button" onclick="removeNewTodoOffset('+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
 });
 input.value = offsets.length ? JSON.stringify(offsets) : '';
 }

 window.addNewTodoOffset = function() {
 var sel = document.getElementById('newTodoOffsetSel');
 var o = JSON.parse(sel.value);
 if (offsets.some(function(x){return x.value===o.value&&x.unit===o.unit})) return;
 offsets.push(o);
 document.getElementById('newTodoUseDefault').checked = false;
 render();
 };
 window.removeNewTodoOffset = function(idx) {
 offsets.splice(idx, 1);
 render();
 };
 window.toggleNewTodoDefault = function() {
 if (document.getElementById('newTodoUseDefault').checked) {
  offsets = [];
  render();
 }
 };
 render();
})();
