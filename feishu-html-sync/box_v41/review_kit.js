/* sdmc review kit r1: format bar + comments inside 修改 mode, and a visible result for 「同步修改」.
   Formatting is class-only markup inside the element being edited, so it travels in the client's normal edit op. */
(function(){
"use strict";
if(window.SDMCReview) return;
const KIT="r1";
const TIMEOUT=+window.SDMC_REVIEW_TIMEOUT_MS||15000;
const FONTS=[["","字体"],["song","宋体"],["hei","黑体"],["kai","楷体"],["fang","仿宋"],["mono","等宽"],["-","默认字体"]];
const COLORS=[["red","红","#B42318"],["blue","蓝","#175CD3"],["green","绿","#067647"],["orange","橙","#B54708"],["gray","灰","#667085"]];
const HLS=[["y","黄","#FDEFA0"],["g","绿","#CDF0D7"],["p","粉","#FBD9E3"]];
const ATOMS=".tk,.glue,.tb,.t,.nd,.cal,.xdel,[contenteditable='false']";
const LS_OFF="sdmc-review:cmt-off", LS_WHO="sdmc-review:who";
const body=document.body;
const lsGet=k=>{try{return localStorage.getItem(k);}catch(e){return null;}};
const lsSet=(k,v)=>{try{localStorage.setItem(k,v);}catch(e){}};
function h(tag,props,kids){
  const n=document.createElement(tag);
  Object.keys(props||{}).forEach(k=>{ if(k==="text") n.textContent=props[k]; else if(k==="cls") n.className=props[k]; else if(k.slice(0,2)==="on") n.addEventListener(k.slice(2),props[k]); else n.setAttribute(k,props[k]); });
  (kids||[]).forEach(c=>n.appendChild(typeof c==="string"?document.createTextNode(c):c));
  return n;
}
const editing=()=>body.classList.contains("editing");
function rootOf(node){
  const e=node&&(node.nodeType===1?node:node.parentElement);
  return e&&e.closest?e.closest('[contenteditable="true"]'):null;
}
function changed(root){ root.dispatchEvent(new Event("input",{bubbles:true})); }

/* ───── selection → format bar ───── */
let saved=null;
function liveRange(){
  const s=window.getSelection();
  if(!s||!s.rangeCount||s.isCollapsed) return null;
  const r=s.getRangeAt(0), a=rootOf(r.startContainer), b=rootOf(r.endContainer);
  return a&&a===b&&r.toString().trim()?r:null;
}
function expandAtoms(r,root){
  const st=r.startContainer.nodeType===1?r.startContainer:r.startContainer.parentElement;
  const en=r.endContainer.nodeType===1?r.endContainer:r.endContainer.parentElement;
  const sa=st&&st.closest(ATOMS), ea=en&&en.closest(ATOMS);
  if(sa&&root.contains(sa)&&sa!==root) r.setStartBefore(sa);
  if(ea&&root.contains(ea)&&ea!==root) r.setEndAfter(ea);
}
function ancestorFx(r,root,sel){
  let n=r.commonAncestorContainer; n=n.nodeType===1?n:n.parentElement;
  while(n&&n!==root){ if(n.matches&&n.matches(sel)) return n; n=n.parentElement; }
  return null;
}
function stripFamily(frag,prefix){
  frag.querySelectorAll(".fx").forEach(n=>{
    [...n.classList].filter(c=>c.indexOf(prefix)===0).forEach(c=>n.classList.remove(c));
    if(n.tagName==="SPAN"&&[...n.classList].every(c=>c==="fx")) n.replaceWith(...n.childNodes);
  });
  frag.querySelectorAll("mark.fx-hl").forEach(n=>{ if(prefix==="fx-hl") n.replaceWith(...n.childNodes); });
}
function selectNode(n){ const r=document.createRange(); r.selectNodeContents(n); const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); }
function apply(kind,val){
  const r=saved&&saved.cloneRange(); if(!r) return;
  const root=rootOf(r.commonAncestorContainer); if(!root) return;
  expandAtoms(r,root);
  if(kind==="clear"||val==="-"){
    const anc=ancestorFx(r,root,kind==="clear"?"span.fx,mark.fx-hl":"span.fx");
    if(anc){ r.setStartBefore(anc); r.setEndAfter(anc); }
  }
  const frag=r.extractContents();
  let w;
  if(kind==="font"){ stripFamily(frag,"fx-f-"); if(val!=="-") w=h("span",{cls:"fx fx-f-"+val}); }
  else if(kind==="color"){ stripFamily(frag,"fx-c-"); w=h("span",{cls:"fx fx-c-"+val}); }
  else if(kind==="hl"){ stripFamily(frag,"fx-hl"); w=h("mark",{cls:"fx fx-hl fx-hl-"+val}); }
  else if(kind==="cmt"){ w=h("mark",{cls:"fx fx-cmt","data-cmt":val.text,"data-cmt-by":val.who,"data-cmt-at":new Date().toISOString()}); }
  else if(kind==="clear"){ stripFamily(frag,"fx-f-"); stripFamily(frag,"fx-c-"); stripFamily(frag,"fx-hl"); }
  if(w){ w.appendChild(frag); r.insertNode(w); selectNode(w); }
  else { const first=frag.firstChild, last=frag.lastChild; r.insertNode(frag); if(first){ const s=document.createRange(); s.setStartBefore(first); s.setEndAfter(last); const sl=window.getSelection(); sl.removeAllRanges(); sl.addRange(s); } }
  root.normalize();
  changed(root); refreshPill(); hideBar();
}
const bar=h("div",{id:"sdmcFxBar",role:"toolbar","aria-label":"文字格式",hidden:""});
const fontSel=h("select",{"aria-label":"字体",title:"字体"},FONTS.map(f=>h("option",{value:f[0],text:f[1]})));
fontSel.addEventListener("change",()=>{ if(fontSel.value) apply("font",fontSel.value); fontSel.value=""; });
bar.appendChild(fontSel);
const btn=(label,title,fn,kids)=>{ const b=h("button",{type:"button",title,"aria-label":title},kids||[label]); b.addEventListener("mousedown",e=>e.preventDefault()); b.addEventListener("click",fn); return b; };
COLORS.forEach(c=>bar.appendChild(btn("","文字颜色："+c[1],()=>apply("color",c[0]),[h("span",{cls:"ca",style:"color:"+c[2],text:"A"})])));
bar.appendChild(h("span",{cls:"sep"}));
HLS.forEach(c=>bar.appendChild(btn("","高亮："+c[1],()=>apply("hl",c[0]),[h("span",{cls:"sw",style:"background:"+c[2]})])));
bar.appendChild(h("span",{cls:"sep"}));
bar.appendChild(btn("批注","添加批注",()=>openCmt()));
bar.appendChild(btn("清除格式","清除字体、颜色、高亮（保留批注）",()=>apply("clear")));
function place(n,rect,below){
  n.hidden=false;
  const w=n.offsetWidth, hh=n.offsetHeight, sx=window.scrollX, sy=window.scrollY;
  let x=rect.left+sx+rect.width/2-w/2; x=Math.max(sx+8,Math.min(x,sx+document.documentElement.clientWidth-w-8));
  let y=below?rect.bottom+sy+8:rect.top+sy-hh-8; if(!below&&y<sy+4) y=rect.bottom+sy+8;
  n.style.left=x+"px"; n.style.top=y+"px";
}
function hideBar(){ bar.hidden=true; }
let selT=0;
document.addEventListener("selectionchange",()=>{ clearTimeout(selT); selT=setTimeout(()=>{
  if(document.activeElement&&(bar.contains(document.activeElement)||pop.contains(document.activeElement))) return;
  const r=editing()&&liveRange();
  if(!r){ hideBar(); return; }
  saved=r.cloneRange(); place(bar,r.getBoundingClientRect(),false);
},120); });

/* ───── comments ───── */
const popTa=h("textarea",{"aria-label":"批注内容",maxlength:"1000",placeholder:"批注内容"});
const pop=h("div",{id:"sdmcCmtPop",role:"dialog","aria-label":"添加批注",hidden:""},[popTa,
  h("div",{cls:"row"},[h("button",{type:"button",text:"取消",onclick:()=>{pop.hidden=true;}}),h("button",{type:"button",cls:"pri",text:"保存批注",onclick:saveCmt})])]);
function openCmt(){ if(!saved) return; popTa.value=""; place(pop,saved.getBoundingClientRect(),true); hideBar(); popTa.focus(); }
function saveCmt(){
  const t=popTa.value.trim(); pop.hidden=true; if(!t||!saved) return;
  let who=lsGet(LS_WHO);
  if(!who){ who=(window.prompt("批注署名（只问一次，存于本机浏览器）：","")||"").trim().slice(0,40)||"审阅"; lsSet(LS_WHO,who); }
  apply("cmt",{text:t.slice(0,1000),who});
}
const bubTxt=h("div",{cls:"txt"}), bubWho=h("div",{cls:"who"}), bubDel=h("button",{type:"button",text:"删除批注"});
const bub=h("div",{id:"sdmcBubble",role:"note",hidden:""},[bubTxt,bubWho,h("div",{cls:"row"},[bubDel,h("button",{type:"button",text:"关闭",onclick:()=>{bub.hidden=true;}})])]);
let bubFor=null;
bubDel.addEventListener("click",()=>{ const m=bubFor; bub.hidden=true; if(!m) return; const root=rootOf(m); m.replaceWith(...m.childNodes); if(root){ root.normalize(); changed(root); } refreshPill(); });
document.addEventListener("click",e=>{
  if(bub.contains(e.target)||pop.contains(e.target)||bar.contains(e.target)) return;
  const m=e.target.closest&&e.target.closest("mark.fx-cmt");
  if(!m||body.classList.contains("fx-cmt-off")){ bub.hidden=true; if(!pop.contains(e.target)) pop.hidden=true; return; }
  bubFor=m; bubTxt.textContent=m.getAttribute("data-cmt")||"";
  const at=m.getAttribute("data-cmt-at")||""; bubWho.textContent=(m.getAttribute("data-cmt-by")||"")+(at?" · "+at.slice(0,16).replace("T"," "):"");
  bubDel.hidden=!editing()||!rootOf(m);
  place(bub,m.getBoundingClientRect(),true);
});
const pill=h("button",{id:"sdmcCmtPill",type:"button",hidden:""});
pill.addEventListener("click",()=>{ const off=!body.classList.contains("fx-cmt-off"); body.classList.toggle("fx-cmt-off",off); lsSet(LS_OFF,off?"1":""); refreshPill(); });
function refreshPill(){
  const n=document.querySelectorAll("mark.fx-cmt").length, off=body.classList.contains("fx-cmt-off");
  const label="批注 "+n+(off?" · 已隐藏":" · 隐藏");
  if(pill.textContent===label&&pill.hidden===!n) return;
  pill.hidden=!n; pill.textContent=label; pill.setAttribute("aria-pressed",off?"false":"true");
}
if(lsGet(LS_OFF)==="1") body.classList.add("fx-cmt-off");

/* ───── 同步结果 ───── */
const toast=h("div",{id:"sdmcToast",hidden:""});
let toastT=0;
function notify(state,title,detail,why,actions){
  clearTimeout(toastT);
  toast.className=state; toast.setAttribute("role",state==="fail"?"alert":"status"); toast.innerHTML="";
  toast.appendChild(h("div",{cls:"ttl",text:title}));
  if(detail) toast.appendChild(h("div",{cls:"det",text:detail}));
  if(why) toast.appendChild(h("div",{cls:"why",text:why}));
  if(actions&&actions.length) toast.appendChild(h("div",{cls:"row"},actions.map(a=>h("button",{type:"button",cls:a.pri?"pri":"",text:a.label,onclick:a.fn}))));
  toast.appendChild(h("button",{type:"button",cls:"x","aria-label":"关闭",text:"×",onclick:()=>{toast.hidden=true;}}));
  toast.hidden=false;
  if(state==="ok") toastT=setTimeout(()=>{toast.hidden=true;},10000);
}
function b64d(s){ return decodeURIComponent(escape(atob(s))); }
function b64e(s){ return btoa(unescape(encodeURIComponent(s))); }
const plain=x=>{ const t=document.createElement("template"); t.innerHTML=x||""; return t.content.textContent.replace(/\s+/g," ").trim(); };
function upgradePkg(text){
  return String(text).replace(/SDMCSYNC1:([A-Za-z0-9+/=\s]+?):END/g,(all,b)=>{
    try{
      const p=JSON.parse(b64d(b.replace(/\s/g,"")));
      p.pv=2; p.caps=["fmt","cmt"]; p.kit=KIT;
      (p.ops||[]).forEach(o=>{ if(o&&o.op==="edit"&&plain(o.old)===plain(o.new)) o.fmt=1; });
      return "SDMCSYNC1:"+b64e(JSON.stringify(p))+":END";
    }catch(e){ return all; }
  });
}
function copy(text){
  const fb=()=>{ const ta=h("textarea",{style:"position:fixed;left:-9999px;top:0"}); ta.value=text; body.appendChild(ta); ta.select(); let ok=false; try{ok=document.execCommand("copy");}catch(e){} ta.remove(); return ok; };
  return navigator.clipboard&&window.isSecureContext?navigator.clipboard.writeText(text).then(()=>true,()=>fb()):Promise.resolve(fb());
}
const origin=u=>{ try{return new URL(u,location.href).origin;}catch(e){return "";} };
function send(text0,o){
  o=o||{};
  const text=upgradePkg(text0), n=o.n||0;
  const record=(state,reason)=>{ window.__sdmcLastSync={state,reason,n,at:new Date().toISOString()}; };
  const fail=(title,why)=>{
    record("fail",title);
    const acts=[{label:"重试",pri:true,fn:()=>send(text0,o)},{label:"复制修改包",fn:()=>copy(text).then(ok=>notify("warn",ok?"已复制修改包":"无法自动复制",ok?"可粘贴发给助理，或粘贴到收件箱文档最下方。":"请改用「下载改过的页面」。","",acts))}];
    if(o.download) acts.push({label:"下载改过的页面",fn:o.download});
    if(o.inbox) acts.push({label:"打开收件箱文档",fn:()=>{ try{window.open(o.inbox,"_blank","noopener");}catch(e){} }});
    notify("fail","同步失败："+title,n+" 处修改仍保存在本机浏览器，没有丢失。",why,acts);
    if(o.btn) o.btn.disabled=false;
  };
  if(!o.webhook) return fail("同步通道未配置","本页没有同步地址（SYNC_WEBHOOK）。请复制修改包发给助理。");
  if(navigator.onLine===false) return fail("设备离线","网络恢复后点「重试」。");
  if(o.btn) o.btn.disabled=true;
  notify("busy","正在同步 "+n+" 处修改…","","",null);
  const target=origin(o.webhook);
  let csp=null;
  const onV=e=>{ if(!target||String(e.blockedURI||"").indexOf(target)===0||/connect-src|default-src/.test(e.effectiveDirective||e.violatedDirective||"")) csp=e; };
  document.addEventListener("securitypolicyviolation",onV);
  const done=()=>{ document.removeEventListener("securitypolicyviolation",onV); if(o.btn) o.btn.disabled=false; };
  const payload=JSON.stringify({msg_type:"text",content:{text},text});
  const hdrs={"Content-Type":"text/plain;charset=UTF-8"}; if(o.auth) hdrs.Authorization=o.auth;
  const ac=window.AbortController?new AbortController():null; let timedOut=false;
  const t=setTimeout(()=>{ timedOut=true; if(ac) ac.abort(); },TIMEOUT);
  const ok=(state)=>{
    clearTimeout(t); done(); record(state,"");
    if(state==="ok") notify("ok","已提交 "+n+" 处修改","同步通道已收到。写回飞书需助理确认后发布；发布后刷新本链接即可看到。","",null);
    else notify("warn","已发出 "+n+" 处修改，未收到回执","浏览器拦截了同步服务的回执（跨域限制）。修改通常已送达；2 分钟后刷新本链接确认，未更新再点「同步修改」。","",null);
    if(o.onOk) try{o.onOk(state);}catch(e){}
  };
  const cspWhy=()=>"当前打开方式（例如飞书在线预览）禁止本页向外部地址发请求（"+(csp.effectiveDirective||csp.violatedDirective)+"）。请用 Chrome 打开下载的文件再同步，或复制修改包发给助理。";
  fetch(o.webhook,{method:"POST",mode:"cors",credentials:"omit",headers:hdrs,body:payload,signal:ac?ac.signal:undefined})
    .then(r=>{ if(!r.ok){ const e=new Error("http"); e.status=r.status; throw e; } ok("ok"); })
    .catch(err=>{
      clearTimeout(t);
      if(timedOut){ done(); return fail("超时",Math.round(TIMEOUT/1000)+" 秒内没有收到同步服务回应。可能是网络慢或同步服务暂时不可用；稍后点「重试」。"); }
      if(err&&err.status){ done(); return fail("同步服务返回 HTTP "+err.status,err.status>=500?"同步服务出错，稍后点「重试」。":"同步地址失效或被拒绝（webhook "+err.status+"），请告知助理。"); }
      setTimeout(()=>{
        if(csp){ done(); return fail("被页面安全策略拦截",cspWhy()); }
        fetch(o.webhook,{method:"POST",mode:"no-cors",credentials:"omit",headers:{"Content-Type":"text/plain;charset=UTF-8"},body:payload,keepalive:payload.length<60000})
          .then(()=>{ if(csp){ done(); fail("被页面安全策略拦截",cspWhy()); } else ok("warn"); })
          .catch(()=>{ setTimeout(()=>{ done(); if(csp) fail("被页面安全策略拦截",cspWhy());
            else fail("网络请求被拦截","请求没有发出去：可能是飞书预览限制了外部请求、公司网络/代理，或浏览器拦截插件。可用 Chrome 打开下载的文件再同步。"); },60); });
      },60);
    });
}

function mount(){
  [bar,pop,bub,toast,pill].forEach(n=>body.appendChild(n));
  refreshPill();
  new MutationObserver(()=>{ clearTimeout(mount.t); mount.t=setTimeout(refreshPill,200); }).observe(body,{childList:true,subtree:true});
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",mount); else mount();
window.SDMCReview={ver:KIT,send,notify,upgradePkg,apply:(k,v)=>{ const r=liveRange(); if(r){ saved=r.cloneRange(); apply(k,v); } }};
})();
