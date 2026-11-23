"use strict";
(function(){
  const button=document.getElementById("text-size-toggle");if(!button)return;
  function current(){try{return localStorage.getItem("runwise-font-large")==="1";}catch{return false;}}
  function set(large){document.documentElement.classList.toggle("reader-large",large);button.setAttribute("aria-pressed",String(large));button.textContent=large?"A−":"A+";button.title=large?"恢复正常字体":"放大页面文字";}
  set(current());button.addEventListener("click",()=>{const large=!document.documentElement.classList.contains("reader-large");set(large);try{localStorage.setItem("runwise-font-large",large?"1":"0");}catch{}});
})();

(function(){
 const b=document.getElementById("motion-toggle");if(!b)return;
 const root=document.documentElement;
 function saved(){try{return localStorage.getItem("runwise-motion-paused")==="1";}catch{return false;}}
 function update(paused){root.classList.toggle("motion-paused",paused);b.setAttribute("aria-pressed",String(!paused));b.setAttribute("aria-label",paused?"恢复动态渐变":"暂停动态渐变");b.title=paused?"恢复动态渐变":"暂停动态渐变";b.textContent=paused?"▷":"◈";}
 update(saved());
 b.addEventListener("click",()=>{const paused=!root.classList.contains("motion-paused");update(paused);try{localStorage.setItem("runwise-motion-paused",paused?"1":"0");}catch{}});
})();
