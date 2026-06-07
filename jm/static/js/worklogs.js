/* -- Image upload helper -- */
async function uploadWorklogImage(file, textarea, previewEl) {
 var status = document.getElementById('uploadStatus');
 if (status) { status.textContent = '업로드 중...'; status.classList.remove('hidden'); }

 try {
 var formData = new FormData();
 formData.append('file', file);
 var res = await fetch('/worklogs/upload-image', {method: 'POST', body: formData});
 if (!res.ok) {
  var err = await res.text();
  if (status) status.textContent = '업로드 실패: ' + (res.status === 400 ? err : '서버 오류');
  setTimeout(function() { if (status) status.classList.add('hidden'); }, 3000);
  return;
 }
 var data = await res.json();
 var imgTag = '\n![image](' + data.url + ')\n';
 if (textarea) {
  var pos = textarea.selectionStart || textarea.value.length;
  textarea.value = textarea.value.slice(0, pos) + imgTag + textarea.value.slice(pos);
  textarea.focus();
 }
 if (previewEl) {
  previewEl.classList.remove('hidden');
  var img = document.createElement('img');
  img.src = data.url;
  img.className = 'w-20 h-20 object-cover rounded-lg border';
  previewEl.appendChild(img);
 }
 if (status) { status.textContent = '업로드 완료'; setTimeout(function() { status.classList.add('hidden'); }, 2000); }
 } catch (err) {
 if (status) { status.textContent = '업로드 실패: 네트워크 오류'; setTimeout(function() { status.classList.add('hidden'); }, 3000); }
 }
}

/* -- Paste handler -- */
function setupImagePaste(textarea, previewEl) {
 if (!textarea) return;
 textarea.addEventListener('paste', async function(e) {
 var items = e.clipboardData?.items;
 if (!items) return;
 for (var i = 0; i < items.length; i++) {
  if (items[i].type.startsWith('image/')) {
  e.preventDefault();
  await uploadWorklogImage(items[i].getAsFile(), textarea, previewEl);
  break;
  }
 }
 });
}

/* -- File select handler -- */
async function handleImageFileSelect(input) {
 var textarea = document.getElementById('worklogContent');
 var previewEl = document.getElementById('imagePreview');
 for (var i = 0; i < input.files.length; i++) {
 await uploadWorklogImage(input.files[i], textarea, previewEl);
 }
 input.value = '';
}

function initWorklogPage() {
 var ta = document.getElementById('worklogContent');
 if (ta && !ta.dataset.pasteReady) {
 setupImagePaste(ta, document.getElementById('imagePreview'));
 ta.dataset.pasteReady = '1';
 }
 var cat = document.getElementById('wlCategory');
 if (cat && !cat.value) {
 var last = localStorage.getItem('wl_last_cat');
 if (last) { for (var o of cat.options) { if (o.value === last) { cat.value = last; break; } } }
 }
}

if (document.readyState === 'loading') {
 document.addEventListener('DOMContentLoaded', initWorklogPage);
} else {
 initWorklogPage();
}
document.addEventListener('htmx:afterSettle', initWorklogPage);
