/* stats.js — extracted inline scripts from stats.html */
(function() {
'use strict';

var container = document.getElementById('statsContainer');
if (!container) return;

var isDark = document.documentElement.classList.contains('dark');
var gridColor = isDark ? 'rgba(148,163,184,0.1)' : 'rgba(226,232,240,0.8)';
var textColor = isDark ? '#94a3b8' : '#64748b';
var cs = getComputedStyle(document.documentElement);

/* ── Weekly chart ── */
var weeklyCtx = document.getElementById('weeklyChart');
if (weeklyCtx) {
 var chartLabels = JSON.parse(container.dataset.chartLabels || '[]');
 var chartCompleted = JSON.parse(container.dataset.chartCompleted || '[]');
 var chartTotal = JSON.parse(container.dataset.chartTotal || '[]');
 new Chart(weeklyCtx, {
  type: 'bar',
  data: {
   labels: chartLabels,
   datasets: [
    {
     label: '완료',
     data: chartCompleted,
     backgroundColor: cs.getPropertyValue('--color-accent').trim(),
     borderRadius: 4,
    },
    {
     label: '전체',
     data: chartTotal,
     backgroundColor: cs.getPropertyValue('--color-border').trim(),
     borderRadius: 4,
    }
   ]
  },
  options: {
   responsive: true,
   maintainAspectRatio: false,
   plugins: { legend: { labels: { color: textColor } } },
   scales: {
    x: { grid: { display: false }, ticks: { color: textColor } },
    y: { grid: { color: gridColor }, ticks: { color: textColor, stepSize: 1 } }
   }
  }
 });
}

/* ── Monthly chart ── */
var monthlyCtx = document.getElementById('monthlyChart');
if (monthlyCtx) {
 var monthlyData = JSON.parse(container.dataset.monthlyData || '[]');
 new Chart(monthlyCtx, {
  type: 'line',
  data: {
   labels: monthlyData.map(function(d){ return d.label; }),
   datasets: [
    {
     label: '등록',
     data: monthlyData.map(function(d){ return d.total; }),
     borderColor: cs.getPropertyValue('--color-info').trim(),
     backgroundColor: cs.getPropertyValue('--color-info').trim() + '14',
     borderWidth: 1,
     fill: true,
     tension: 0.3,
    },
    {
     label: '완료',
     data: monthlyData.map(function(d){ return d.done; }),
     borderColor: cs.getPropertyValue('--color-success').trim(),
     backgroundColor: cs.getPropertyValue('--color-success').trim() + '14',
     borderWidth: 2.5,
     fill: true,
     tension: 0.3,
    }
   ]
  },
  options: {
   responsive: true,
   maintainAspectRatio: false,
   plugins: { legend: { labels: { color: textColor } } },
   scales: {
    x: { grid: { display: false }, ticks: { color: textColor } },
    y: { grid: { color: gridColor }, ticks: { color: textColor, stepSize: 1 } }
   }
  }
 });
}

/* ── Category chart ── */
var catCtx = document.getElementById('catChart');
if (catCtx) {
 var catStats = JSON.parse(container.dataset.catStats || '[]');
 var catData = catStats.filter(function(c){ return c.total > 0; });
 if (catData.length > 0) {
  new Chart(catCtx, {
   type: 'doughnut',
   data: {
    labels: catData.map(function(c){ return c.name; }),
    datasets: [{
     data: catData.map(function(c){ return c.total; }),
     backgroundColor: catData.map(function(c){ return c.color; }),
     borderWidth: 2,
     borderColor: isDark ? '#1e293b' : '#ffffff',
    }]
   },
   options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
     legend: { position: 'bottom', labels: { color: textColor, padding: 16 } }
    }
   }
  });
 }
}

/* ── Heatmap ── */
(function() {
 var heatmapData = JSON.parse(container.dataset.heatmap || '{}');
 var heatmapEl = document.getElementById('heatmap');
 if (!heatmapEl) return;
 var today = new Date(container.dataset.heatmapToday);
 var start = new Date(container.dataset.heatmapStart);
 var dayOfWeek = start.getDay();
 var mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
 start.setDate(start.getDate() + mondayOffset);
 var emptyColor = cs.getPropertyValue('--color-border').trim() || (isDark ? '#3c3835' : '#ddd9d6');
 var accentColor = cs.getPropertyValue('--color-accent').trim() || '#d97706';
 var colors = [emptyColor, accentColor+'40', accentColor+'80', accentColor+'BF', accentColor];
 var current = new Date(start);
 while (current <= today) {
  var col = document.createElement('div');
  col.style.cssText = 'display:flex;flex-direction:column;gap:3px';
  for (var d = 0; d < 7; d++) {
   var cell = document.createElement('div');
   var dateStr = current.getFullYear() + '-' + String(current.getMonth()+1).padStart(2,'0') + '-' + String(current.getDate()).padStart(2,'0');
   var count = heatmapData[dateStr] || 0;
   var level = count === 0 ? 0 : count <= 2 ? 1 : count <= 4 ? 2 : count <= 7 ? 3 : 4;
   cell.style.cssText = 'width:12px;height:12px;border-radius:2px;background:' + (current > today ? 'transparent' : colors[level]);
   cell.title = dateStr + ': ' + count + '건 완료';
   col.appendChild(cell);
   current.setDate(current.getDate() + 1);
  }
  heatmapEl.appendChild(col);
 }
})();

})();
