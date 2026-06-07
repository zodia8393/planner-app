function toggleEventRrule() {
 var sel = document.getElementById('eventRecurrence');
 var endPanel = document.getElementById('eventRecurrenceEnd');
 if (sel.value && sel.value !== '') { endPanel.classList.remove('hidden'); } else { endPanel.classList.add('hidden'); }
}
function openEventModal(dateStr) {
 document.getElementById('eventModal').classList.remove('hidden');
 document.getElementById('eventStartTime').value = dateStr + 'T09:00';
}
function closeEventModal() {
 document.getElementById('eventModal').classList.add('hidden');
}
function editEvent(eventId) {
 fetch('/events/' + eventId + '/edit', { headers: {'HX-Request': 'true'} })
 .then(function(r) { return r.text(); })
 .then(function(html) {
  var container = document.getElementById('editEventContainer');
  container.innerHTML = html;
  htmx.process(container);
 }).catch(function(){});
}
function editGcalEvent(gcalId) {
 fetch('/events/gcal/' + encodeURIComponent(gcalId) + '/edit', { headers: {'HX-Request': 'true'} })
 .then(function(r) { return r.text(); })
 .then(function(html) {
  var container = document.getElementById('editEventContainer');
  container.innerHTML = html;
  htmx.process(container);
 }).catch(function(){});
}
if (location.hash === '#new') { var ti = document.querySelector('input[name="title"]'); if (ti) { ti.scrollIntoView({block:'center'}); ti.focus(); } history.replaceState(null, '', location.pathname + location.search); }

// --- New Event Reminder Offsets ---
(function(){
 var labels = {'0_minute':'정시','5_minute':'5분 전','10_minute':'10분 전','15_minute':'15분 전','30_minute':'30분 전','1_hour':'1시간 전','2_hour':'2시간 전','1_day':'1일 전','2_day':'2일 전','1_week':'1주 전'};
 var offsets = [];
 var input = document.getElementById('newEventReminderOffsets');

 function render() {
 var c = document.getElementById('newEventOffsetChips');
 c.innerHTML = '';
 offsets.forEach(function(o, i) {
  var lbl = labels[o.value+'_'+o.unit] || (o.value+(o.unit==='minute'?'분':o.unit==='hour'?'시간':'일')+' 전');
  c.innerHTML += '<span class="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-medium rounded-full" style="background: var(--color-accent-soft); color: var(--color-accent-text);">'+lbl+' <button type="button" onclick="removeNewEventOffset('+i+')" class="hover-danger" style="color: var(--color-accent);">&times;</button></span>';
 });
 input.value = offsets.length ? JSON.stringify(offsets) : '';
 }

 window.addNewEventOffset = function() {
 var sel = document.getElementById('newEventOffsetSel');
 var o = JSON.parse(sel.value);
 if (offsets.some(function(x){return x.value===o.value&&x.unit===o.unit})) return;
 offsets.push(o);
 document.getElementById('newEventUseDefault').checked = false;
 render();
 };
 window.removeNewEventOffset = function(idx) {
 offsets.splice(idx, 1);
 render();
 };
 window.toggleNewEventDefault = function() {
 if (document.getElementById('newEventUseDefault').checked) {
  offsets = [];
  render();
 }
 };
 render();
})();
