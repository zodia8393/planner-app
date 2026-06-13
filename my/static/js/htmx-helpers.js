/* htmx-helpers.js — Double-submit prevention + offline banner (extracted from base.html) */
(function(){
 'use strict';

 /* ══ Double-submit prevention ══ */
 document.body.addEventListener('htmx:beforeRequest', function(e){
  if (!e.detail.elt || !e.detail.elt.closest) return;
  const btn = e.detail.elt.closest('button[type="submit"],button[hx-post],button[hx-delete],button[hx-put]');
  if(btn) btn.disabled = true;
 });
 document.body.addEventListener('htmx:afterRequest', function(e){
  if (!e.detail.elt || !e.detail.elt.closest) return;
  const btn = e.detail.elt.closest('button[type="submit"],button[hx-post],button[hx-delete],button[hx-put]');
  if(btn) setTimeout(function(){ btn.disabled = false; }, 300);
 });
 document.querySelectorAll('form:not([hx-post])').forEach(function(f){
  f.addEventListener('submit', function(){ const b=this.querySelector('button[type=submit]'); if(b) b.disabled=true; });
 });

 /* ══ Sidebar active state update on htmx navigation ══ */
 document.body.addEventListener('htmx:afterSettle', function(e){
  if(e.detail.target && e.detail.target.id === 'mainContent'){
   const path = window.location.pathname;
   // Update sidebar nav-active
   document.querySelectorAll('#sidebar .nav-item, #sidebar .sidebar-more-item').forEach(function(a){
    const href = a.getAttribute('href');
    if(!href) return;
    if(href === path || (path === '/' && href === '/')) {
     a.classList.add('nav-active');
    } else {
     a.classList.remove('nav-active');
    }
   });
   // Update mobile tab bar active
   document.querySelectorAll('#mobileTabBar .mobile-tab-item').forEach(function(a){
    const href = a.getAttribute('href');
    if(!href) return;
    if(href === path || (path === '/' && href === '/')) {
     a.classList.add('active');
    } else {
     a.classList.remove('active');
    }
   });
   // Close mobile sidebar if open
   const sidebar = document.getElementById('sidebar');
   const overlay = document.getElementById('sidebarOverlay');
   if(sidebar) sidebar.classList.add('-translate-x-full');
   if(overlay) overlay.classList.add('hidden');
   // Close more menu if open
   const moreMenu = document.getElementById('moreMenu');
   if(moreMenu) moreMenu.classList.add('hidden');
  }
 });

 /* ══ Offline banner ══ */
 const banner = document.getElementById('offlineBanner');
 if(banner){
  function updateOnlineStatus(){
   if (typeof window.updateSyncStatus === 'function') {
    if (!navigator.onLine) window.updateSyncStatus('offline');
    return;
   }
   if(navigator.onLine){
    banner.classList.add('hidden');
   } else {
    banner.classList.remove('hidden');
   }
  }
  window.addEventListener('online', updateOnlineStatus);
  window.addEventListener('offline', updateOnlineStatus);
  updateOnlineStatus();
 }
})();
