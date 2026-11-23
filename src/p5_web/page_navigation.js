"use strict";
/* V2.9: independent, hash-addressable views. No stacked-page anchor scrolling. */
(()=>{
  const $=id=>document.getElementById(id);
  const definitions=[
   {key:"overview",label:"训练概况",anchor:"overview",ids:[".page-intro","initial-error","local-controls","overview","focus-panel"]},
   {key:"running",label:"跑步趋势",anchor:"running-panel",ids:["running-panel"]},
   {key:"advanced",label:"进阶分析",anchor:"load-panel",ids:["load-panel","data-quality"]},
   {key:"weekly",label:"七天计划",anchor:"weekly",ids:["weekly","timeline-panel"]},
   {key:"risk",label:"风险提醒",anchor:"risk-panel",ids:["risk-panel","followup"]},
   {key:"review",label:"我的训练报告",anchor:"review-panel",ids:["review-panel","ai-panel"]},
   {key:"history",label:"历史报告",anchor:"history-panel",ids:["history-panel"]},
   {key:"import",label:"上传数据",anchor:"import-panel",ids:["import-panel"]}
  ];
  const byAnchor=new Map(definitions.map(d=>[d.anchor,d.key]));
  const byKey=new Map(definitions.map(d=>[d.key,d]));
  const otherAnchors={"runner-kpis":"overview","running-chart":"running","metrics":"overview","risk-list":"risk","review-content":"review","week-content":"weekly","csv-form":"import","history-list":"history","answer-form":"risk","questions":"risk","quality":"import","compare-box":"history","ai-settings":"review"};
  let active="overview",stage=null;
  const hasReducedMotion=()=>matchMedia("(prefers-reduced-motion: reduce)").matches;
  function derive(hash){const id=String(hash||"").replace(/^#/,"");if(!id)return "overview";if(byKey.has(id))return id;if(byAnchor.has(id))return byAnchor.get(id);if(otherAnchors[id])return otherAnchors[id];const node=$(id);const view=node?.closest(".rw-page");return view?.dataset.page||"overview";}
  function setNav(key){for(const item of document.querySelectorAll('.side-nav a,.mobile-nav a')){const on=derive(item.getAttribute('href'))===key;item.classList.toggle('active',on);if(on)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');}const heading=$('rw-page-label');if(heading)heading.textContent=byKey.get(key)?.label||"训练概况";}
  function go(key,{push=true,animate=true}={}){
    if(!byKey.has(key))key=derive(key);
    const entry=byKey.get(key);if(!entry)return;
    const previous=active,changing=key!==previous;
    if(changing){
      for(const page of stage.querySelectorAll(':scope > .rw-page'))page.hidden=page.dataset.page!==key;
      active=key;
      const next=stage.querySelector(`.rw-page[data-page="${key}"]`);
      next.classList.remove('rw-slide-forward','rw-slide-back');
      if(animate&&!hasReducedMotion()){
        void next.offsetWidth;
        next.classList.add(definitions.findIndex(d=>d.key===key)>definitions.findIndex(d=>d.key===previous)?'rw-slide-forward':'rw-slide-back');
      }
    }
    setNav(key);
    if(push&&location.hash.slice(1)!==entry.anchor)history.pushState({rwPage:key},'',`#${entry.anchor}`);
    // Page changes should begin at the top of the right content, not deep inside a long stacked document.
    if(window.scrollY>0)window.scrollTo({top:0,behavior:'instant'});
    if(key==='running')requestAnimationFrame(()=>window.RunWiseCharts?.drawRunning?.());
    if(key==='advanced')requestAnimationFrame(()=>window.RunWiseCharts?.drawLoad?.());
    const sidebar=$('app-sidebar'),menu=$('menu-toggle');sidebar?.classList.remove('open');menu?.setAttribute('aria-expanded','false');
  }
  function init(){
    const main=$('main'),grid=main?.querySelector('.content-grid');if(!main||!grid)return;
    stage=document.createElement('div');stage.id='rw-stage';stage.className='rw-stage';main.insertBefore(stage,grid);
    definitions.forEach((d,i)=>{
      const page=document.createElement('div');page.className='rw-page';page.dataset.page=d.key;page.id=`rw-page-${d.key}`;
      page.setAttribute('aria-label',d.label);page.setAttribute('role','region');page.hidden=i!==0;
      const body=document.createElement('div');body.className='rw-page-body';
      for(const id of d.ids){const n=id.startsWith('.')?document.querySelector(id):$(id);if(n)body.append(n);}
      page.append(body);stage.append(page);
    });
    grid.remove();
    // Page names and internal contextual links share the same route mapping.
    document.addEventListener('click',e=>{
      const anchor=e.target.closest('a[href^="#"]');if(!anchor)return;
      const hash=anchor.getAttribute('href');if(hash==='#main')return;
      const id=hash.slice(1),node=$(id);if(!node&&!byAnchor.has(id))return;
      e.preventDefault();const key=derive(hash);go(key);
      // For links targeting a section within an already-visible page, scroll to that section.
      if(node&&!node.closest('.rw-page')?.hidden&&!byAnchor.has(id)&&node!==stage)node.scrollIntoView({block:'start',behavior:hasReducedMotion()?'instant':'smooth'});
    });
    window.addEventListener('popstate',()=>go(derive(location.hash),{push:false}));
    window.addEventListener('hashchange',()=>go(derive(location.hash),{push:false}));
    go(derive(location.hash),{push:false,animate:false});
  }
  window.RunWisePages={go,derive,get active(){return active;}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
