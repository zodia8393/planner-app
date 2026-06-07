/* files.js — extracted inline scripts from files.html */
(function() {
'use strict';

var filesContainer = document.getElementById('filesContainer');
if (!filesContainer) return;
var UPLOAD_URL = '/files/upload/' + (filesContainer.dataset.currentPath || '');
var statusEl = document.getElementById('fileStatus');
var statusTitle = document.getElementById('statusTitle');
var statusDetail = document.getElementById('statusDetail');
var statusBar = document.getElementById('statusBar');
var statusPercent = document.getElementById('statusPercent');
var statusSpinner = document.getElementById('statusSpinner');
var statusCheck = document.getElementById('statusCheck');
var hideTimer = null;

function showStatus(title, detail) {
 clearTimeout(hideTimer);
 statusTitle.textContent = title;
 statusDetail.textContent = detail || '';
 statusBar.style.width = '0%';
 statusPercent.textContent = '';
 statusSpinner.classList.remove('hidden');
 statusCheck.classList.add('hidden');
 statusEl.classList.remove('hidden');
}

function updateProgress(pct, detail) {
 statusBar.style.width = pct + '%';
 statusPercent.textContent = pct + '%';
 if (detail) statusDetail.textContent = detail;
}

function showComplete(title) {
 statusTitle.textContent = title;
 statusBar.style.width = '100%';
 statusPercent.textContent = '';
 statusSpinner.classList.add('hidden');
 statusCheck.classList.remove('hidden');
 hideTimer = setTimeout(hideStatus, 2500);
}

function hideStatus() {
 statusEl.classList.add('hidden');
}

function formatBytes(b) {
 if (b < 1024) return b + ' B';
 if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
 return (b/1048576).toFixed(1) + ' MB';
}

window.uploadFiles = function(fileList) {
 if (!fileList || fileList.length === 0) return;
 var fd = new FormData();
 var totalSize = 0;
 for (var i = 0; i < fileList.length; i++) { fd.append('files', fileList[i]); totalSize += fileList[i].size; }

 var count = fileList.length;
 var names = count === 1 ? fileList[0].name : count + '개 파일';
 showStatus('업로드 중...', names + ' (' + formatBytes(totalSize) + ')');

 var xhr = new XMLHttpRequest();
 xhr.open('POST', UPLOAD_URL);
 xhr.upload.onprogress = function(e) {
  if (e.lengthComputable) {
   var pct = Math.round(e.loaded / e.total * 100);
   updateProgress(pct, formatBytes(e.loaded) + ' / ' + formatBytes(e.total));
  }
 };
 xhr.onload = function() {
  showComplete('업로드 완료 (' + names + ')');
  setTimeout(function(){ _partialRefresh(window.location.pathname); }, 800);
 };
 xhr.onerror = function() {
  statusTitle.textContent = '업로드 실패';
  statusBar.style.width = '100%';
  statusBar.style.background = 'var(--color-danger)';
  statusSpinner.classList.add('hidden');
 };
 xhr.send(fd);
};

window.downloadFile = function(e, el) {
 e.preventDefault();
 var url = el.getAttribute('href');
 var fname = decodeURIComponent(url.split('/').pop());
 showStatus('다운로드 중...', fname);

 fetch(url).then(function(resp) {
  var total = parseInt(resp.headers.get('content-length') || '0');
  var reader = resp.body.getReader();
  var loaded = 0;
  var chunks = [];

  function pump() {
   return reader.read().then(function(result) {
    if (result.done) {
     var blob = new Blob(chunks);
     var a = document.createElement('a');
     a.href = URL.createObjectURL(blob);
     a.download = fname;
     a.click();
     URL.revokeObjectURL(a.href);
     showComplete('다운로드 완료 (' + fname + ')');
     return;
    }
    chunks.push(result.value);
    loaded += result.value.length;
    if (total > 0) {
     var pct = Math.round(loaded / total * 100);
     updateProgress(pct, formatBytes(loaded) + ' / ' + formatBytes(total));
    } else {
     statusDetail.textContent = formatBytes(loaded);
    }
    return pump();
   });
  }
  return pump();
 }).catch(function() {
  statusTitle.textContent = '다운로드 실패';
  statusSpinner.classList.add('hidden');
 });
 return false;
};

/* Preview */
window.openPreview = function(url, name, type) {
 var modal = document.getElementById('previewModal');
 var content = document.getElementById('previewContent');
 var title = document.getElementById('previewTitle');
 title.textContent = name;
 content.innerHTML = '<div class="flex items-center justify-center h-full"><div class="animate-spin w-8 h-8 border-3 border-t-transparent rounded-full" style="border-color: var(--color-accent); border-top-color: transparent;"></div></div>';
 modal.classList.remove('hidden');
 document.body.style.overflow = 'hidden';

 if (type === 'image') {
  var img = new Image();
  img.onload = function() {
   content.innerHTML = '';
   content.className = 'flex-1 overflow-auto flex items-center justify-center p-4';
   img.className = 'max-w-full max-h-full object-contain rounded-lg shadow-lg';
   content.appendChild(img);
  };
  img.onerror = function() { content.innerHTML = '<div class="flex items-center justify-center h-full text-sm">이미지를 불러올 수 없습니다</div>'; };
  img.src = url;
 } else if (type === 'pdf') {
  content.className = 'flex-1 overflow-hidden p-0';
  content.innerHTML = '<iframe src="' + url + '" class="w-full h-full border-0"></iframe>';
 } else {
  fetch(url).then(function(r){ return r.text(); }).then(function(text) {
   content.className = 'flex-1 overflow-auto p-0';
   var pre = document.createElement('pre');
   pre.className = 'p-5 text-sm font-mono leading-relaxed whitespace-pre-wrap break-words min-h-full';
   pre.textContent = text;
   content.innerHTML = '';
   content.appendChild(pre);
  }).catch(function() {
   content.innerHTML = '<div class="flex items-center justify-center h-full text-sm">파일을 불러올 수 없습니다</div>';
  });
 }
};

window.closePreview = function() {
 document.getElementById('previewModal').classList.add('hidden');
 document.getElementById('previewContent').innerHTML = '';
 document.body.style.overflow = '';
};

document.addEventListener('keydown', function(e) {
 if (e.key === 'Escape') window.closePreview();
});

/* Drag & drop */
var dz = document.getElementById('dropZone');
if (dz) {
 var dragCount = 0;
 document.body.addEventListener('dragenter', function(e) { e.preventDefault(); dragCount++; dz.classList.remove('hidden'); });
 document.body.addEventListener('dragleave', function(e) { e.preventDefault(); dragCount--; if (dragCount <= 0) { dz.classList.add('hidden'); dragCount = 0; } });
 document.body.addEventListener('dragover', function(e) { e.preventDefault(); });
 document.body.addEventListener('drop', function(e) {
  e.preventDefault();
  dz.classList.add('hidden');
  dragCount = 0;
  if (e.dataTransfer.files.length > 0) window.uploadFiles(e.dataTransfer.files);
 });
}

})();
