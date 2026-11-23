"use strict";
// Only cache public application shell. Never persist health reports, uploads or API responses.
const SHELL="runwise-shell-v35-plan-inputs";
const PUBLIC=["/live","/dashboard.css","/dashboard.js","/page_navigation.js","/page_navigation.css","/theme_unified.css","/professional_analysis.js","/professional_analysis.css","/training_review.js","/readability.js","/icon.svg","/icon-192.png","/icon-512.png","/manifest.webmanifest"];
self.addEventListener("install", event=>{event.waitUntil(caches.open(SHELL).then(cache=>cache.addAll(PUBLIC)).then(()=>self.skipWaiting()));});
self.addEventListener("activate",event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==SHELL).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));});
self.addEventListener("fetch",event=>{
 const request=event.request;
 if(request.method!=="GET")return;
 const url=new URL(request.url);
 if(url.origin!==self.location.origin||!PUBLIC.includes(url.pathname))return;
 event.respondWith(fetch(request).then(response=>{if(response.ok){const copy=response.clone();caches.open(SHELL).then(cache=>cache.put(request,copy));}return response;}).catch(()=>caches.match(request)));
});
