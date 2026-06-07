/* today.js — extracted inline scripts from today.html */
(function() {
'use strict';

window.toggleInPlace = function(btn, type) {
 var item;
 if (type === 'todo') {
  item = btn.closest('[data-todo-id]');
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
   btn.innerHTML = '<svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
  }
 } else if (type === 'habit') {
  item = btn.closest('[data-habit-id]');
  if (!item) return;
  var wasDone2 = item.classList.contains('opacity-60');
  item.classList.toggle('opacity-60');
  var title2 = item.querySelector('span.text-sm');
  if (title2) title2.classList.toggle('line-through');
  var icon = btn.getAttribute('data-icon') || '';
  var color = btn.getAttribute('data-color') || 'var(--color-border)';
  if (wasDone2) {
   btn.style.background = 'transparent';
   btn.style.borderColor = 'var(--color-border)';
   btn.textContent = '';
  } else {
   btn.style.background = color + '20';
   btn.style.borderColor = color;
   btn.textContent = icon;
  }
 }
};

})();
