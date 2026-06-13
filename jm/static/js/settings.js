/* settings.js — extracted inline scripts from settings.html */
(function() {
'use strict';

/* ── Push subscription management ── */
(function initPush() {
 var pushBtn = document.getElementById('pushToggleBtn');
 var pushStatus = document.getElementById('pushStatus');
 var pushTestBtn = document.getElementById('pushTestBtn');
 if (!pushBtn) return;

 function updatePushUI(){
  if(!('serviceWorker' in navigator) || !('PushManager' in window)){
   pushStatus.textContent = '이 브라우저에서는 푸시 알림을 지원하지 않습니다.';
   pushBtn.style.display = 'none';
   return;
  }
  navigator.serviceWorker.ready.then(function(reg){
   reg.pushManager.getSubscription().then(function(sub){
    if(sub){
     pushBtn.textContent = '비활성화';
     pushBtn.style.background = 'var(--color-border)';
     pushBtn.style.color = 'var(--color-text-muted)';
     pushStatus.textContent = '푸시 알림 활성화됨';
     pushStatus.style.color = 'var(--color-success)';
     pushTestBtn.classList.remove('hidden');
    } else {
     pushBtn.textContent = '활성화';
     pushBtn.style.background = 'var(--color-accent)';
     pushBtn.style.color = '#fff';
     pushStatus.textContent = '';
     pushTestBtn.classList.add('hidden');
    }
   });
  });
 }

 window.togglePushSubscription = function(){
  navigator.serviceWorker.ready.then(function(reg){
   reg.pushManager.getSubscription().then(function(sub){
    if(sub){
     sub.unsubscribe().then(function(){
      fetch('/api/push/unsubscribe', {
       method: 'POST',
       headers: {'Content-Type':'application/json'},
       body: JSON.stringify({endpoint: sub.endpoint})
      });
      updatePushUI();
      if(typeof showToast === 'function') showToast('푸시 알림 비활성화됨', 'info');
     });
    } else {
     fetch('/api/push/vapid-key').then(function(r){return r.json()}).then(function(data){
      var key = data.publicKey;
      var padding = '='.repeat((4 - key.length % 4) % 4);
      var base64 = (key + padding).replace(/-/g, '+').replace(/_/g, '/');
      var raw = atob(base64);
      var arr = new Uint8Array(raw.length);
      for(var i=0;i<raw.length;i++) arr[i]=raw.charCodeAt(i);

      reg.pushManager.subscribe({
       userVisibleOnly: true,
       applicationServerKey: arr
      }).then(function(newSub){
       fetch('/api/push/subscribe', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({subscription: newSub.toJSON()})
       });
       updatePushUI();
       if(typeof showToast === 'function') showToast('푸시 알림 활성화됨!', 'success');
      }).catch(function(){
       if(typeof showToast === 'function') showToast('알림 권한이 필요합니다', 'error');
      });
     });
    }
   });
  });
 };

 window.testPush = function(){
  fetch('/api/push/test', {method:'POST'}).then(function(){
   if(typeof showToast === 'function') showToast('테스트 알림 전송됨', 'success');
  });
 };

 updatePushUI();
})();

/* ── Notification offset management ── */
(function initNotifOffsets() {
 var notifSettings = {};
 var offsetLabels = {
  '0_minute': '정시', '5_minute': '5분 전', '10_minute': '10분 전',
  '15_minute': '15분 전', '30_minute': '30분 전',
  '1_hour': '1시간 전', '2_hour': '2시간 전',
  '1_day': '1일 전', '2_day': '2일 전', '3_day': '3일 전',
  '1_week': '1주 전'
 };

 function getLabel(off) {
  var key = off.value + '_' + off.unit;
  return offsetLabels[key] || (off.value + (off.unit === 'minute' ? '분' : off.unit === 'hour' ? '시간' : off.unit === 'day' ? '일' : '주') + ' 전');
 }

 function renderOffsets(type) {
  var container = document.getElementById(type + 'Offsets');
  if (!container) return;
  var offsets = (notifSettings[type] && notifSettings[type].offsets) || [];
  container.innerHTML = '';
  offsets.forEach(function(off, idx) {
   var chip = document.createElement('span');
   chip.className = 'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full';
   chip.style.cssText = 'background: var(--color-accent-soft); color: var(--color-accent-text);';
   chip.innerHTML = getLabel(off) + ' <button onclick="removeOffset(\'' + type + '\',' + idx + ')" class="ml-0.5 hover-danger" style="color: var(--color-accent);">&times;</button>';
   container.appendChild(chip);
  });
 }

 window.addOffset = function(type) {
  var sel = document.getElementById(type + 'OffsetSelect');
  if (!sel) return;
  var off = JSON.parse(sel.value);
  if (!notifSettings[type]) notifSettings[type] = {target_type: type, offsets: [], enabled: true};
  var exists = notifSettings[type].offsets.some(function(o) { return o.value === off.value && o.unit === off.unit; });
  if (exists) return;
  notifSettings[type].offsets.push(off);
  renderOffsets(type);
  saveOffsets(type);
 };

 window.removeOffset = function(type, idx) {
  if (!notifSettings[type]) return;
  notifSettings[type].offsets.splice(idx, 1);
  renderOffsets(type);
  saveOffsets(type);
 };

 function saveOffsets(type) {
  fetch('/api/notification-settings', {
   method: 'POST',
   headers: {'Content-Type': 'application/json'},
   body: JSON.stringify({
    target_type: type,
    offsets: notifSettings[type].offsets,
    enabled: true
   })
  }).then(function(){ if(typeof showToast==='function') showToast('알림 설정 저장됨','success'); })
   .catch(function(){ if(typeof showToast==='function') showToast('저장 실패','error'); });
 }

 fetch('/api/notification-settings').then(function(r){return r.json()}).then(function(data){
  notifSettings = data;
  ['event','todo','dday'].forEach(function(t){ renderOffsets(t); });
 }).catch(function(){});
})();

/* ── Accent color & font size ── */
(function initAccentFont() {
 function applyStoredAppearance() {
  if (typeof window.applyAppearancePreferences === 'function') {
   window.applyAppearancePreferences();
   return;
  }
  document.body.dataset.accent = localStorage.getItem('accent_color') || 'amber';
  document.body.dataset.uiTheme = localStorage.getItem('appearance_theme') || 'classic';
  document.body.dataset.sidebarStyle = localStorage.getItem('sidebar_style') || 'standard';
 }

 window.setAccentColor = function(color) {
  localStorage.setItem('accent_color', color);
  applyStoredAppearance();
  updateAccentUI();
  if (typeof showToast === 'function') showToast('액센트 색상이 변경되었습니다', 'success');
 };

 window.setAppearanceTheme = function(theme, preferredSidebar) {
  if (!theme) return;
  localStorage.setItem('appearance_theme', theme);
  if (preferredSidebar) localStorage.setItem('sidebar_style', preferredSidebar);
  applyStoredAppearance();
  updateAppearanceThemeUI();
  updateSidebarStyleUI();
  if (typeof showToast === 'function') showToast('화면 분위기가 변경되었습니다', 'success');
 };

 window.setSidebarStyle = function(style) {
  if (!style) return;
  localStorage.setItem('sidebar_style', style);
  applyStoredAppearance();
  updateSidebarStyleUI();
  if (typeof showToast === 'function') showToast('사이드탭 스타일이 변경되었습니다', 'success');
 };

 window.setFontSize = function(size) {
  localStorage.setItem('font_size', size);
  document.body.dataset.fontsize = size;
  var fontSizeMap = { small: '13px', medium: '14px', large: '16px' };
  document.documentElement.style.fontSize = fontSizeMap[size] || '14px';
  updateFontSizeUI();
  if (typeof showToast === 'function') showToast('글꼴 크기가 변경되었습니다', 'success');
 };

 function updateAccentUI() {
  var current = localStorage.getItem('accent_color') || 'amber';
  document.querySelectorAll('#accentPicker button').forEach(function(btn) {
   if (btn.dataset.color === current) {
    btn.style.outline = '3px solid var(--color-text)';
    btn.style.outlineOffset = '3px';
   } else {
    btn.style.outline = 'none';
    btn.style.outlineOffset = '';
   }
  });
 }

 function updateFontSizeUI() {
  var current = localStorage.getItem('font_size') || 'medium';
  document.querySelectorAll('#fontSizePicker button').forEach(function(btn) {
   if (btn.dataset.size === current) {
    btn.style.background = 'var(--color-accent)';
    btn.style.color = '#fff';
    btn.style.borderColor = 'var(--color-accent)';
   } else {
    btn.style.background = 'var(--color-surface)';
    btn.style.color = 'var(--color-text-muted)';
    btn.style.borderColor = 'var(--color-border)';
   }
  });
 }

 function updateAppearanceThemeUI() {
  var current = localStorage.getItem('appearance_theme') || 'classic';
  document.querySelectorAll('#appearanceThemePicker button').forEach(function(btn) {
   btn.setAttribute('aria-pressed', btn.dataset.theme === current ? 'true' : 'false');
  });
 }

 function updateSidebarStyleUI() {
  var current = localStorage.getItem('sidebar_style') || 'standard';
  document.querySelectorAll('#sidebarStylePicker button').forEach(function(btn) {
   btn.setAttribute('aria-pressed', btn.dataset.sidebarStyle === current ? 'true' : 'false');
  });
 }

 applyStoredAppearance();
  updateAccentUI();
 updateAppearanceThemeUI();
 updateSidebarStyleUI();
 updateFontSizeUI();
})();

/* ── Background preview toggle ── */
window.updateBgPreview = function() {
 var type = document.querySelector('input[name="type"]:checked');
 type = type ? type.value : 'none';
 document.getElementById('presetSection').classList.toggle('hidden', type !== 'preset');
 document.getElementById('uploadSection').classList.toggle('hidden', type !== 'upload');
 document.getElementById('opacitySection').classList.toggle('hidden', type === 'none');
};

/* ── Morning brief settings ── */
(function initMorningBrief() {
 var mbEnabled = document.getElementById('mbEnabled');
 var mbTime = document.getElementById('mbTime');
 if (!mbEnabled) return;

 fetch('/api/morning-brief/settings').then(function(r){return r.json()}).then(function(d){
  mbEnabled.checked = d.enabled;
  mbTime.value = (d.hour<10?'0':'') + d.hour + ':' + (d.minute<10?'0':'') + d.minute;
 }).catch(function(){});

 window.saveMorningBrief = function(){
  var enabled = mbEnabled.checked ? 1 : 0;
  var time = mbTime.value.split(':');
  fetch('/api/morning-brief/settings', {
   method: 'POST',
   headers: {'Content-Type':'application/x-www-form-urlencoded'},
   body: 'enabled=' + enabled + '&hour=' + parseInt(time[0]) + '&minute=' + parseInt(time[1])
  }).then(function(){ showToast('모닝 브리핑 설정 저장됨','success'); })
   .catch(function(){ showToast('저장 실패','error'); });
 };
})();

/* ── QR code ── */
(function initQR() {
 var qrLoading = document.getElementById('qrLoading');
 if (!qrLoading) return;

 fetch('/api/qr-code').then(function(r){return r.json()}).then(function(d){
  qrLoading.classList.add('hidden');
  var img = document.getElementById('qrImg');
  img.src = 'data:image/png;base64,' + d.qr_base64;
  img.classList.remove('hidden');
  var u = document.getElementById('qrUrl');
  u.textContent = d.url;
  u.classList.remove('hidden');
 }).catch(function(){ qrLoading.textContent = 'QR 생성 실패'; });
})();

/* ── Data import ── */
window.handleImport = function(e) {
 e.preventDefault();
 var file = document.getElementById('importFile').files[0];
 if (!file) { showToast('파일을 선택하세요', 'error'); return false; }
 var source = document.getElementById('importSource').value;
 var formData = new FormData();
 formData.append('file', file);
 formData.append('source', source);
 fetch('/api/import/todos', { method: 'POST', body: formData })
  .then(function(r){return r.json()})
  .then(function(data){
   var el = document.getElementById('importResult');
   el.classList.remove('hidden');
   if(data.ok){
    el.style.color = 'var(--color-success)';
    el.textContent = data.count + '건 가져오기 완료';
    showToast(data.count + '건 가져옴', 'success');
   } else {
    el.style.color = 'var(--color-danger)';
    el.textContent = data.error || '오류 발생';
   }
  });
 return false;
};

})();
