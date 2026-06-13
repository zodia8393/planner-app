/* sidebar-favorites.js — Sidebar favorites management (extracted from base.html) */
(function(){
 'use strict';
 const STORAGE_KEY = 'sidebar_favorites';

 function getFavorites(){
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || []; }
  catch(e){ return []; }
 }
 function saveFavorites(favs){
  localStorage.setItem(STORAGE_KEY, JSON.stringify(favs));
 }

 // Current page path
 const currentPath = window.location.pathname;

 // Toggle favorite
 window.toggleFavorite = function(href){
  const favs = getFavorites();
  const idx = favs.indexOf(href);
  if(idx > -1){ favs.splice(idx, 1); } else { favs.push(href); }
  saveFavorites(favs);
  renderFavorites();
  updateStarStates();
 };

 // Close sidebar more (details)
 window.closeSidebarMore = function(){
  const details = document.getElementById('sidebarMore');
  if(details) details.removeAttribute('open');
 };

 // Update star states in the more section
 function updateStarStates(){
 const favs = getFavorites();
 const stars = document.querySelectorAll('#sidebarMoreContent .fav-star');
 stars.forEach(function(btn){
   const row = btn.closest('[data-sidebar-href]');
   if(!row) return;
   const href = row.getAttribute('data-sidebar-href');
   const svg = btn.querySelector('svg');
   if(favs.indexOf(href) > -1){
    btn.classList.add('active');
    if(svg) svg.setAttribute('fill', 'currentColor');
   } else {
    btn.classList.remove('active');
    if(svg) svg.setAttribute('fill', 'none');
   }
  });
 }

 // Render favorites section
 function renderFavorites(){
  const container = document.getElementById('sidebarFavorites');
  if(!container) return;
  const favs = getFavorites();

  // Remove old fav items (keep the label div)
  const oldItems = container.querySelectorAll('.fav-item');
  oldItems.forEach(function(el){ el.remove(); });

  if(favs.length === 0){
   container.classList.add('hidden');
   return;
  }

  container.classList.remove('hidden');

  // For each favorite, clone the row from the more section
  favs.forEach(function(href){
   const original = document.querySelector('#sidebarMoreContent [data-sidebar-href="'+href+'"]');
   if(!original) return;

   const clone = original.cloneNode(true);
   clone.classList.add('fav-item');
   clone.removeAttribute('data-sidebar-href');

   // Update the star button in the clone to be filled and to remove on click
   const starBtn = clone.querySelector('.fav-star');
   if(starBtn){
    starBtn.classList.add('active');
    const svg = starBtn.querySelector('svg');
    if(svg) svg.setAttribute('fill', 'currentColor');
    starBtn.setAttribute('onclick', "event.preventDefault();event.stopPropagation();toggleFavorite('"+href+"')");
   }

   // Ensure nav-active is correct
   const cloneLink = clone.querySelector('a[href]');
   if(currentPath === href){
    if(cloneLink) cloneLink.classList.add('nav-active');
   } else {
    if(cloneLink) cloneLink.classList.remove('nav-active');
   }

   container.appendChild(clone);
  });
 }

 // Handle details open/close for summary visibility
 const details = document.getElementById('sidebarMore');
 if(details){
  // Use MutationObserver to detect open/close
  const observer = new MutationObserver(function(){
   const summary = details.querySelector('summary');
   const hideBtn = document.getElementById('sidebarHideBtn');
   if(details.open){
    if(summary) summary.style.display = 'none';
    if(hideBtn) hideBtn.style.display = '';
   } else {
    if(summary) summary.style.display = '';
    if(hideBtn) hideBtn.style.display = 'none';
   }
  });
  observer.observe(details, { attributes: true, attributeFilter: ['open'] });

  // Initial state
  const summary = details.querySelector('summary');
  const hideBtn = document.getElementById('sidebarHideBtn');
  if(details.open){
   if(summary) summary.style.display = 'none';
   if(hideBtn) hideBtn.style.display = '';
  } else {
   if(hideBtn) hideBtn.style.display = 'none';
  }
 }

 // Init on DOM ready
 renderFavorites();
 updateStarStates();
})();
