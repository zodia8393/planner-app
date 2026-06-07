/* habits.js — extracted inline scripts from habits.html */
(function() {
'use strict';

var specificTimes = [];

window.updateTrackingUI = function() {
 var type = document.querySelector('input[name="tracking_type"]:checked').value;
 document.getElementById('counterOptions').classList.toggle('hidden', type !== 'counter');
 document.getElementById('intervalOptions').classList.toggle('hidden', type !== 'interval');
 document.getElementById('specificOptions').classList.toggle('hidden', type !== 'specific');
 document.getElementById('weeklyOptions').classList.toggle('hidden', type !== 'weekly');
};

window.addSpecificTime = function() {
 var input = document.getElementById('newSpecificTime');
 var time = input.value;
 if (!time || specificTimes.indexOf(time) >= 0) return;
 specificTimes.push(time);
 specificTimes.sort();
 renderSpecificTimes();
};

window.removeSpecificTime = function(idx) {
 specificTimes.splice(idx, 1);
 renderSpecificTimes();
};

function renderSpecificTimes() {
 var c = document.getElementById('specificTimesList');
 c.innerHTML = '';
 specificTimes.forEach(function(t, i) {
  c.innerHTML += '<span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-full" style="background:var(--color-accent-soft);color:var(--color-accent-text);">' + t +
   ' <button type="button" onclick="removeSpecificTime(' + i + ')" class="hover-danger">&times;</button>' +
   '<input type="hidden" name="specific_times" value="' + t + '"></span>';
 });
}

})();
