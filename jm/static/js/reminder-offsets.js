/* reminder-offsets.js — extracted from todo_edit_form.html & event_edit_form.html partials */
(function() {
'use strict';

var labels = {
 '0_minute':'당일 오전 9시','5_minute':'5분 전','10_minute':'10분 전',
 '15_minute':'15분 전','30_minute':'30분 전',
 '1_hour':'1시간 전','2_hour':'2시간 전','3_hour':'3시간 전',
 '1_day':'1일 전','2_day':'2일 전','3_day':'3일 전','1_week':'1주 전'
};

function getLabel(o) {
 var lbl = labels[o.value+'_'+o.unit];
 if (lbl) return lbl;
 return o.value + (o.unit==='minute'?'분':o.unit==='hour'?'시간':o.unit==='day'?'일':'주') + ' 전';
}

/* ── Todo reminder offsets ── */
function initTodoOffset(el) {
 var tid = parseInt(el.dataset.todoId);
 var input = document.getElementById('todoReminderOffsets_'+tid);
 if (!input) return;
 var offsets = [];
 try { offsets = JSON.parse(input.value || '[]'); } catch(e) { offsets = []; }
 if (!Array.isArray(offsets)) offsets = [];

 function render() {
  var c = document.getElementById('todoOffsetChips_'+tid);
  c.innerHTML = '';
  offsets.forEach(function(o, i) {
   c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">' + getLabel(o) + ' <button type="button" onclick="removeEditTodoOffset('+tid+','+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
  });
  input.value = offsets.length ? JSON.stringify(offsets) : '';
 }
 window['_todoOff'+tid] = offsets;
 render();
}

window.addEditTodoOffset = function(id) {
 var sel = document.getElementById('todoOffsetSel_'+id);
 var o = JSON.parse(sel.value);
 var arr = window['_todoOff'+id];
 if (arr.some(function(x){return x.value===o.value&&x.unit===o.unit})) return;
 arr.push(o);
 document.getElementById('todoUseDefault_'+id).checked = false;
 var input = document.getElementById('todoReminderOffsets_'+id);
 var c = document.getElementById('todoOffsetChips_'+id);
 c.innerHTML = '';
 arr.forEach(function(oo, i) {
  c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">' + getLabel(oo) + ' <button type="button" onclick="removeEditTodoOffset('+id+','+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
 });
 input.value = arr.length ? JSON.stringify(arr) : '';
};

window.removeEditTodoOffset = function(id, idx) {
 window['_todoOff'+id].splice(idx, 1);
 var arr = window['_todoOff'+id];
 var input = document.getElementById('todoReminderOffsets_'+id);
 var c = document.getElementById('todoOffsetChips_'+id);
 c.innerHTML = '';
 arr.forEach(function(oo, i) {
  c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">' + getLabel(oo) + ' <button type="button" onclick="removeEditTodoOffset('+id+','+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
 });
 input.value = arr.length ? JSON.stringify(arr) : '';
};

window.toggleEditTodoDefault = function(id) {
 if (document.getElementById('todoUseDefault_'+id).checked) {
  window['_todoOff'+id] = [];
  var input = document.getElementById('todoReminderOffsets_'+id);
  var c = document.getElementById('todoOffsetChips_'+id);
  c.innerHTML = '';
  input.value = '';
 }
};

window.toggleEditRrule = function(tid) {
 var sel = document.getElementById('editRepeatType_' + tid);
 var panel = document.getElementById('editRrulePanel_' + tid);
 if (sel.value === 'custom') { panel.classList.remove('hidden'); } else { panel.classList.add('hidden'); }
};

window.toggleEditRruleExtra = function(tid) {
 var freq = document.getElementById('editRruleFreq_' + tid).value;
 document.getElementById('editBydayRow_' + tid).classList.toggle('hidden', freq !== 'WEEKLY');
 document.getElementById('editBymonthdayRow_' + tid).classList.toggle('hidden', freq !== 'MONTHLY');
};

window.toggleEditEndFields = function(tid) {
 var et = document.getElementById('editRruleEndType_' + tid).value;
 document.getElementById('editRruleCount_' + tid).classList.toggle('hidden', et !== 'count');
 document.getElementById('editRruleUntil_' + tid).classList.toggle('hidden', et !== 'until');
};

window.collectEditByday = function(tid) {
 var checks = document.querySelectorAll('.rrule-byday-edit-' + tid + ':checked');
 var vals = Array.from(checks).map(function(c) { return c.value; });
 document.getElementById('editRruleByday_' + tid).value = vals.join(',');
};

/* ── Event reminder offsets ── */
function initEventOffset(el) {
 var eid = parseInt(el.dataset.eventId);
 var input = document.getElementById('eventReminderOffsets_'+eid);
 if (!input) return;
 var offsets = [];
 try { offsets = JSON.parse(input.value || '[]'); } catch(e) { offsets = []; }
 if (!Array.isArray(offsets)) offsets = [];

 function render() {
  var c = document.getElementById('eventOffsetChips_'+eid);
  c.innerHTML = '';
  offsets.forEach(function(o, i) {
   c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">' + getLabel(o) + ' <button type="button" onclick="removeEventOffset('+eid+','+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
  });
  input.value = offsets.length ? JSON.stringify(offsets) : '';
 }
 window['_evOff'+eid] = offsets;
 render();
}

window.addEventOffset = function(id) {
 var sel = document.getElementById('eventOffsetSel_'+id);
 var o = JSON.parse(sel.value);
 var arr = window['_evOff'+id];
 if (arr.some(function(x){return x.value===o.value&&x.unit===o.unit})) return;
 arr.push(o);
 document.getElementById('eventUseDefault_'+id).checked = false;
 var input = document.getElementById('eventReminderOffsets_'+id);
 var c = document.getElementById('eventOffsetChips_'+id);
 c.innerHTML = '';
 arr.forEach(function(oo, i) {
  c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">' + getLabel(oo) + ' <button type="button" onclick="removeEventOffset('+id+','+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
 });
 input.value = arr.length ? JSON.stringify(arr) : '';
};

window.removeEventOffset = function(id, idx) {
 window['_evOff'+id].splice(idx, 1);
 var arr = window['_evOff'+id];
 var input = document.getElementById('eventReminderOffsets_'+id);
 var c = document.getElementById('eventOffsetChips_'+id);
 c.innerHTML = '';
 arr.forEach(function(oo, i) {
  c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">' + getLabel(oo) + ' <button type="button" onclick="removeEventOffset('+id+','+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
 });
 input.value = arr.length ? JSON.stringify(arr) : '';
};

window.toggleEventDefault = function(id) {
 if (document.getElementById('eventUseDefault_'+id).checked) {
  window['_evOff'+id] = [];
  var input = document.getElementById('eventReminderOffsets_'+id);
  var c = document.getElementById('eventOffsetChips_'+id);
  c.innerHTML = '';
  input.value = '';
 }
};

/* ── Auto-init on DOM ready and htmx swaps ── */
function initAllOffsets() {
 document.querySelectorAll('[data-init-todo-offset]').forEach(initTodoOffset);
 document.querySelectorAll('[data-init-event-offset]').forEach(initEventOffset);
}

initAllOffsets();
document.addEventListener('htmx:afterSettle', initAllOffsets);

})();
