var WEEKDAYS = ['월요일','화요일','수요일','목요일','금요일','토요일','일요일'];

function updateTriggerUI() {
 var type = document.getElementById('triggerType').value;
 var weekdaySel = document.getElementById('triggerWeekday');
 var daySel = document.getElementById('triggerDay');
 var extraLabel = document.querySelector('#triggerExtra label');
 var rrulePanel = document.getElementById('rruleTriggerPanel');
 if (type === 'daily') {
 weekdaySel.style.display = 'none';
 daySel.style.display = 'none';
 rrulePanel.style.display = 'none';
 extraLabel.textContent = '';
 } else if (type === 'weekly') {
 weekdaySel.style.display = '';
 daySel.style.display = 'none';
 rrulePanel.style.display = 'none';
 extraLabel.textContent = '요일';
 } else if (type === 'monthly') {
 weekdaySel.style.display = 'none';
 daySel.style.display = '';
 rrulePanel.style.display = 'none';
 extraLabel.textContent = '날짜';
 } else if (type === 'rrule') {
 weekdaySel.style.display = 'none';
 daySel.style.display = 'none';
 rrulePanel.style.display = '';
 extraLabel.textContent = '';
 }
}
function updateRruleExtra() {
 var freq = document.getElementById('rruleFreq').value;
 document.getElementById('rruleBydayRow').style.display = (freq === 'WEEKLY') ? '' : 'none';
 document.getElementById('rruleBymonthdayRow').style.display = (freq === 'MONTHLY') ? '' : 'none';
}

document.getElementById('automationForm').addEventListener('submit', function() {
 var type = document.getElementById('triggerType').value;
 document.getElementById('hiddenTriggerType').value = type;
 var tc = {};
 if (type === 'weekly') tc = {weekday: parseInt(document.getElementById('triggerWeekday').value)};
 else if (type === 'monthly') tc = {day: parseInt(document.getElementById('triggerDay').value)};
 else if (type === 'rrule') {
 var freq = document.getElementById('rruleFreq').value;
 var interval = parseInt(document.getElementById('rruleInterval').value) || 1;
 var parts = ['FREQ=' + freq];
 if (interval > 1) parts.push('INTERVAL=' + interval);
 if (freq === 'WEEKLY') {
  var days = Array.from(document.querySelectorAll('.rrule-byday-auto:checked')).map(function(c) { return c.value; });
  if (days.length) parts.push('BYDAY=' + days.join(','));
 } else if (freq === 'MONTHLY') {
  var md = document.getElementById('rruleBymonthday').value.trim();
  if (md) parts.push('BYMONTHDAY=' + md);
 }
 tc = {rrule: parts.join(';')};
 }
 document.getElementById('hiddenTriggerConfig').value = JSON.stringify(tc);

 var ac = {
 title: document.getElementById('actionTitle').value.trim(),
 priority: parseInt(document.getElementById('actionPriority').value),
 category_id: document.getElementById('actionCategory').value ? parseInt(document.getElementById('actionCategory').value) : null,
 description: '',
 tags: ''
 };
 document.getElementById('hiddenActionConfig').value = JSON.stringify(ac);
});
