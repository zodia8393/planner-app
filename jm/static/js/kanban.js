(function() {
 var board = document.getElementById('kanbanBoard');
 if (!board) return;
 var _draggedId = null;

 // Event delegation for drag events
 board.addEventListener('dragstart', function(e) {
 if (!e.target || !e.target.closest) return;
 var card = e.target.closest('[data-todo-id]');
 if (!card) return;
 _draggedId = card.dataset.todoId;
 e.dataTransfer.effectAllowed = 'move';
 e.dataTransfer.setData('text/plain', _draggedId);
 card.style.opacity = '0.4';
 });

 board.addEventListener('dragend', function(e) {
 if (!e.target || !e.target.closest) return;
 var card = e.target.closest('[data-todo-id]');
 if (card) card.style.opacity = '1';
 board.querySelectorAll('.kanban-drop-zone').forEach(function(z) {
  z.classList.remove('kanban-drop-active');
  z.classList.add('border-transparent');
 });
 _draggedId = null;
 });

 board.addEventListener('dragover', function(e) {
 if (!e.target || !e.target.closest) return;
 var zone = e.target.closest('.kanban-drop-zone');
 if (!zone) return;
 e.preventDefault();
 e.dataTransfer.dropEffect = 'move';
 zone.classList.add('kanban-drop-active');
 zone.classList.remove('border-transparent');
 });

 board.addEventListener('dragleave', function(e) {
 if (!e.target || !e.target.closest) return;
 var zone = e.target.closest('.kanban-drop-zone');
 if (zone && !zone.contains(e.relatedTarget)) {
  zone.classList.remove('kanban-drop-active');
  zone.classList.add('border-transparent');
 }
 });

 board.addEventListener('drop', function(e) {
 e.preventDefault();
 if (!e.target || !e.target.closest) return;
 var zone = e.target.closest('.kanban-drop-zone');
 if (!zone || !_draggedId) return;
 var column = zone.dataset.column;
 var form = new FormData();
 form.append('column', column);
 fetch('/todos/' + _draggedId + '/move', {
  method: 'POST',
  body: form,
  headers: {'HX-Request': 'true'}
 }).then(function(resp) {
  var redir = resp.headers.get('HX-Redirect');
  if (redir) { htmx.ajax('GET', redir, {target:'body', swap:'innerHTML'}); }
  else if (resp.ok) { htmx.ajax('GET', '/todos/kanban', {target:'body', swap:'innerHTML'}); }
 }).catch(function(){});
 });
})();
