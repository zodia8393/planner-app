/* slash-commands.js — Slash command autocomplete + quick actions (extracted from base.html) */
(function(){
 'use strict';

 // Quick add todo from command palette
 window.cmdQuickAddTodo = function(){
  toggleCommandPalette();
  // If on todos page, focus the add input
  const todoInput = document.querySelector('input[name="title"][form], #quickAddInput, input[name="title"]');
  if(todoInput){ todoInput.focus(); return; }
  // Otherwise navigate to todos with hash to trigger new
  location.href = '/todos#new';
 };

 // Start focus from command palette
 window.cmdStartFocus = function(min){
  toggleCommandPalette();
  if(typeof _focusStart === 'function') _focusStart(min);
  else {
   document.getElementById('focusModal').classList.remove('hidden');
  }
 };

 // Slash commands in todo title input
 const _slashCmds = [
  {cmd:'/오늘', label:'오늘 마감', icon:'📅'},
  {cmd:'/내일', label:'내일 마감', icon:'📆'},
  {cmd:'/다음주', label:'다음주 월요일', icon:'📆'},
  {cmd:'/높음', label:'우선순위 높음', icon:'🔴'},
  {cmd:'/보통', label:'우선순위 보통', icon:'🟡'},
  {cmd:'/낮음', label:'우선순위 낮음', icon:'🟢'},
 ];
 let _slashDropdown = null;
 let _slashActiveIdx = -1;

 function _createSlashDropdown(){
  if(_slashDropdown) return _slashDropdown;
  const d = document.createElement('div');
  d.id = 'slashAutocomplete';
  d.style.cssText = 'position:absolute;z-index:100;width:220px;border-radius:0.75rem;overflow:hidden;display:none;background:var(--color-surface);border:1px solid var(--color-border);box-shadow:var(--shadow-lg);';
  document.body.appendChild(d);
  _slashDropdown = d;
  return d;
 }

 function _showSlashDropdown(inp, filter){
  const dd = _createSlashDropdown();
  const q = (filter || '').toLowerCase();
  const items = _slashCmds.filter(function(c){ return !q || c.cmd.indexOf(q) === 0; });
  if(items.length === 0){ dd.style.display='none'; return; }
  dd.innerHTML = '';
  _slashActiveIdx = -1;
  items.forEach(function(c, i){
   const row = document.createElement('div');
   row.className = 'slash-ac-item';
   row.setAttribute('data-cmd', c.cmd);
   row.style.cssText = 'padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:0.8125rem;color:var(--color-text-muted);transition:background 0.1s;';
   row.innerHTML = '<span style="font-size:1rem;">'+c.icon+'</span><span style="font-weight:600;">'+c.cmd+'</span><span style="opacity:0.6;font-size:0.75rem;margin-left:auto;">'+c.label+'</span>';
   row.addEventListener('mouseenter', function(){ _highlightSlashItem(dd, i); });
   row.addEventListener('mousedown', function(e){ e.preventDefault(); _applySlashCmd(inp, c.cmd); });
   dd.appendChild(row);
  });
  const rect = inp.getBoundingClientRect();
  dd.style.left = rect.left + 'px';
  dd.style.top = (rect.bottom + 4) + 'px';
  dd.style.position = 'fixed';
  dd.style.display = '';
 }

 function _highlightSlashItem(dd, idx){
  const rows = dd.querySelectorAll('.slash-ac-item');
  rows.forEach(function(r, i){ r.style.background = i === idx ? 'var(--color-accent-soft)' : ''; });
  _slashActiveIdx = idx;
 }

 function _hideSlashDropdown(){
  if(_slashDropdown) _slashDropdown.style.display = 'none';
  _slashActiveIdx = -1;
 }

 function _applySlashCmd(inp, cmd){
  _hideSlashDropdown();
  const form = inp.closest('form');
  if(!form) return;
  const slashMap = {
   '/오늘': function(){ setFormDate(form, new Date().toISOString().slice(0,10)); },
   '/내일': function(){ const d=new Date();d.setDate(d.getDate()+1);setFormDate(form, d.toISOString().slice(0,10)); },
   '/다음주': function(){ const d=new Date();d.setDate(d.getDate()+(8-d.getDay())%7||7);setFormDate(form, d.toISOString().slice(0,10)); },
   '/높음': function(){ setFormPriority(form, 0); },
   '/보통': function(){ setFormPriority(form, 2); },
   '/낮음': function(){ setFormPriority(form, 3); },
  };
  if(slashMap[cmd]){ slashMap[cmd](); inp.value=''; showToast('설정 완료','info'); }
 }

 document.addEventListener('input', function(e){
  const inp = e.target;
  if(inp.tagName !== 'INPUT' || inp.name !== 'title') return;
  const val = inp.value;
  if(val.startsWith('/')){ _showSlashDropdown(inp, val.trim().toLowerCase()); }
  else { _hideSlashDropdown(); }
 });

 document.addEventListener('keydown', function(e){
  if(!_slashDropdown || _slashDropdown.style.display === 'none') return;
  const inp = e.target;
  if(inp.tagName !== 'INPUT' || inp.name !== 'title') return;
  const rows = _slashDropdown.querySelectorAll('.slash-ac-item');
  if(!rows.length) return;
  if(e.key === 'ArrowDown'){ e.preventDefault(); _highlightSlashItem(_slashDropdown, Math.min(_slashActiveIdx+1, rows.length-1)); }
  else if(e.key === 'ArrowUp'){ e.preventDefault(); _highlightSlashItem(_slashDropdown, Math.max(_slashActiveIdx-1, 0)); }
  else if(e.key === 'Enter' && _slashActiveIdx >= 0){ e.preventDefault(); _applySlashCmd(inp, rows[_slashActiveIdx].getAttribute('data-cmd')); }
  else if(e.key === 'Escape'){ _hideSlashDropdown(); }
 });

 document.addEventListener('blur', function(e){
  if(e.target.tagName === 'INPUT' && e.target.name === 'title') setTimeout(_hideSlashDropdown, 150);
 }, true);

 function setFormDate(form, dateStr){
  const dateInput = form.querySelector('input[name="due_date"]');
  if(dateInput) dateInput.value = dateStr;
 }
 function setFormPriority(form, p){
  const priInput = form.querySelector('select[name="priority"]');
  if(priInput) priInput.value = p;
 }

 // Quick add todo from command palette
 window.cmdPaletteAddTodo = function(title){
  toggleCommandPalette();
  fetch('/api/quick-add', {
   method: 'POST',
   headers: {'Content-Type': 'application/json'},
   body: JSON.stringify({title: title})
  }).then(function(r){return r.json()}).then(function(data){
   if(data.ok){
    showToast('"' + data.title + '" 추가됨' + (data.due_date ? ' (' + data.due_date + ')' : ''), 'success');
    // Refresh if on todos or dashboard
    const path = location.pathname;
    if(path === '/' || path === '/todos'){
     _partialRefresh(path);
    }
   } else {
    showToast(data.error || '오류', 'error');
   }
  }).catch(function(){ showToast('추가 실패', 'error'); });
 };
})();
