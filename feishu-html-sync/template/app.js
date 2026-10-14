/* 感臻研究简报模板 · runtime (TOC, tables, ECharts, edit mode, save, print). No external resources. */
(function(){
"use strict";
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
const C={accent:"#1d3f8f",accent2:"#c2410c",ink:"#16191f",ink2:"#454b55",muted:"#686e78",rule:"#ddd7cb",grid:"#ece7dd",surface:"#fffefb"};
const PALETTE=["#1d3f8f","#7d9bd6","#c2410c","#2c6a4c","#b48a3c","#8c929c","#5a3f8f","#3e8a8a"];
const FONT=getComputedStyle(document.body).fontFamily;
const dataEl=$("#report-data");
let DATA={charts:{}};
try{DATA=JSON.parse(dataEl&&dataEl.textContent.trim()||"{}");DATA.charts=DATA.charts||{};}catch(e){console.warn("report-data JSON 无法解析",e);}
let dirty=false;const saveState=$("#saveState");
function setDirty(v){dirty=v;if(saveState)saveState.textContent=v?"有未同步的修改":"";setSyncBtn(syncing);}
/* Feishu Chrome-sync constants: replaced atomically by build_report.py — do not put bare // on this const line */
const SYNC_VER='v2', SAVE_FILE_TOKEN='', SAVE_URL='', SYNC_INBOX='', SYNC_WEBHOOK='', SYNC_AUTH='', SYNC_CURSOR_WEBHOOK='';
const num=v=>v===null||v===undefined||v===""||isNaN(+v)?null:+v;
const fmt=v=>v==null?"":(+v).toLocaleString("zh-CN",{maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const meta=n=>{const m=document.querySelector(`meta[name="${n}"]`);return m?m.content:"";};

/* ───── TOC ───── */
const tocList=$("#toc"), doc=$("#doc");
function tocLabel(h){
  if(h.dataset.toc)return h.dataset.toc;
  let t=h.textContent.trim().replace(/\s+/g," ");
  const cut=t.search(/[：:（(]/); if(cut>1)t=t.slice(0,cut);
  return t.length>16?t.slice(0,15)+"…":t;
}
let heads=[];
function slug(i){return "ch-"+(i+1);}
function buildToc(){
  if(!tocList||!doc)return;
  heads=$$(":scope > h2",doc);
  tocList.innerHTML="";
  heads.forEach((h,i)=>{ if(!h.id){h.id=slug(i);h.dataset.autoId="";}
    const li=document.createElement("li"),a=document.createElement("a");
    a.href="#"+h.id;a.textContent=tocLabel(h);a.title=h.textContent.trim();li.appendChild(a);tocList.appendChild(li);});
  onScroll();tocEdge();
}
function tocEdge(){if(tocList)tocList.classList.toggle("end",tocList.scrollLeft+tocList.clientWidth>=tocList.scrollWidth-4);}
if(tocList)tocList.addEventListener("scroll",tocEdge,{passive:true});
let activeIdx=-2;
function onScroll(){
  const y=window.scrollY, off=(document.querySelector(".masthead")?.offsetHeight||0)+90;
  let idx=-1; for(let i=0;i<heads.length;i++){ if(heads[i].getBoundingClientRect().top-off<=0)idx=i; else break; }
  if(idx!==activeIdx&&tocList){ activeIdx=idx;
    $$("a",tocList).forEach((a,i)=>{ if(i===idx){a.setAttribute("aria-current","true");
        const ol=tocList, l=a.offsetLeft, w=a.offsetWidth; if(l<ol.scrollLeft+16||l+w>ol.scrollLeft+ol.clientWidth-32) ol.scrollTo({left:Math.max(0,l-ol.clientWidth/2+w/2),behavior:"smooth"});}
      else a.removeAttribute("aria-current");});
  }
  const pr=$("#progress"); if(pr){const max=document.documentElement.scrollHeight-innerHeight;pr.style.transform=`scaleX(${max>0?Math.min(1,y/max):0})`;}
}
let ticking=false;
addEventListener("scroll",()=>{if(!ticking){ticking=true;requestAnimationFrame(()=>{ticking=false;onScroll();});}},{passive:true});
addEventListener("resize",()=>{activeIdx=-2;onScroll();tocEdge();});

/* ───── tables: wrap, numeric align, sort, filter ───── */
const ICON_SEARCH='<svg class="i" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>';
const toNum=s=>{const m=String(s).replace(/[,，\s]/g,"").match(/[-−]?\d+(?:\.\d+)?/);return m?parseFloat(m[0].replace("−","-")):null;};
const pureNum=s=>/^[-−+]?(?:[A-Za-z$Rp€¥￥]{0,3})\s?[\d,，]+(?:\.\d+)?\s?(?:%|k|K|万|亿|分|倍|x)?$/.test(String(s).trim());
function enhanceTables(){
  $$("table",document.querySelector("main")).forEach((t,ti)=>{
    if(t.closest(".ex-editor"))return;
    let box=t.closest(".tbl");
    if(!box){box=document.createElement("div");box.className="tbl";const sc=document.createElement("div");sc.className="tbl-scroll";t.parentNode.insertBefore(box,t);box.appendChild(sc);sc.appendChild(t);}
    else if(!t.closest(".tbl-scroll")){const sc=document.createElement("div");sc.className="tbl-scroll";t.parentNode.insertBefore(sc,t);sc.appendChild(t);}
    const ths=$$("thead th",t), body=t.tBodies[0]; if(!body)return;
    const rows=Array.from(body.rows);
    if(ths.length>=4&&!box.classList.contains("narrow"))box.classList.add("wide");
    ths.forEach((th,ci)=>{
      const cells=rows.map(r=>r.cells[ci]?r.cells[ci].textContent.trim():"").filter(x=>x&&x!=="—"&&x!=="-");
      if(ci>0&&cells.length&&cells.filter(pureNum).length/cells.length>=.75){th.classList.add("num");rows.forEach(r=>r.cells[ci]&&r.cells[ci].classList.add("num"));}
      if(rows.length>=3&&t.dataset.sort!=="off"){th.dataset.sort="";th.tabIndex=0;th.setAttribute("role","columnheader");
        const go=()=>sortTable(t,ci,th); th.addEventListener("click",go); th.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();go();}});}
    });
    rows.forEach((r,i)=>r.dataset.i=i);
    if(t.tHead&&t.dataset.sticky!=="off"&&!box.querySelector(".tbl-float"))setupFloat(box,t);
    if(rows.length>=6&&t.dataset.filter!=="off"&&!box.querySelector(".tbl-tools")){
      const tools=document.createElement("div");tools.className="tbl-tools";tools.dataset.rt="";
      tools.innerHTML=`<label>${ICON_SEARCH}<input type="search" placeholder="筛选本表…" aria-label="筛选表格"></label><span class="count">${rows.length} 行</span>`;
      box.insertBefore(tools,box.firstChild);
      const inp=$("input",tools),cnt=$(".count",tools);
      inp.addEventListener("input",()=>{const q=inp.value.trim().toLowerCase();let n=0;
        Array.from(body.rows).forEach(r=>{if(r.classList.contains("empty"))return;const hit=!q||r.textContent.toLowerCase().includes(q);r.hidden=!hit;if(hit)n++;});
        let em=body.querySelector("tr.empty"); if(!n){if(!em){em=document.createElement("tr");em.className="empty";em.dataset.rt="";em.innerHTML=`<td colspan="${ths.length||1}">没有匹配“${esc(inp.value)}”的行</td>`;body.appendChild(em);}else em.firstChild.textContent=`没有匹配“${inp.value}”的行`;} else if(em)em.remove();
        cnt.textContent=q?`${n} / ${rows.length} 行`:`${rows.length} 行`;syncFloats(true);});
    }
  });
}
/* sticky table header: a cloned floating thead (fixed, just under the masthead), synced with the
   wrapper's horizontal scroll. Native position:sticky can't escape the overflow-x wrapper. */
const floats=[];const mast=document.querySelector(".masthead");
function headH(){return mast?Math.round(mast.getBoundingClientRect().bottom):0;}
function setupFloat(box,t){
  const sc=box.querySelector(".tbl-scroll");if(!sc)return;
  const fl=document.createElement("div");fl.className="tbl-float";fl.dataset.rt="";fl.hidden=true;
  const ft=document.createElement("table");fl.appendChild(ft);box.appendChild(fl);
  const rec={box,sc,t,fl,ft,shown:false};
  sc.addEventListener("scroll",()=>{box.classList.toggle("scrolled",sc.scrollLeft>2);if(rec.shown)panFloat(rec);},{passive:true});
  fl.addEventListener("click",e=>{const th=e.target.closest("th");if(!th)return;const tr=th.parentNode,ri=Array.from(tr.parentNode.rows).indexOf(tr),ci=Array.from(tr.cells).indexOf(th);
    const o=t.tHead.rows[ri]&&t.tHead.rows[ri].cells[ci];if(o)o.click();});
  fl.addEventListener("wheel",e=>{if(Math.abs(e.deltaX)>Math.abs(e.deltaY)){sc.scrollLeft+=e.deltaX;e.preventDefault();}},{passive:false});
  floats.push(rec);markH(rec);
}
function panFloat(rec){const x=rec.sc.scrollLeft;rec.ft.style.transform=`translateX(${-x}px)`;
  if(rec.box.classList.contains("hscroll"))rec.ft.querySelectorAll("tr>th:first-child").forEach(th=>th.style.transform=`translateX(${x}px)`);}
function markH(rec){const h=rec.sc.scrollWidth>rec.sc.clientWidth+2;rec.box.classList.toggle("hscroll",h);if(!h)rec.box.classList.remove("scrolled");}
function syncFloat(rec,rebuild){
  const {t,sc,fl,ft}=rec;
  if(editing||!t.isConnected||!t.tHead){if(rec.shown){fl.hidden=true;rec.shown=false;}return;}
  const hh=headH(),r=t.getBoundingClientRect(),thh=t.tHead.getBoundingClientRect().height;
  const show=r.top<hh&&r.bottom-thh*1.5>hh;
  if(!show){if(rec.shown){fl.hidden=true;rec.shown=false;}return;}
  if(!rec.shown||rebuild){
    const c=t.tHead.cloneNode(true);c.querySelectorAll("[tabindex]").forEach(x=>x.removeAttribute("tabindex"));c.querySelectorAll("[id]").forEach(x=>x.removeAttribute("id"));
    ft.replaceChildren(c);ft.style.width=t.offsetWidth+"px";
    Array.from(t.tHead.rows).forEach((row,ri)=>Array.from(row.cells).forEach((cell,ci)=>{const d=c.rows[ri].cells[ci];if(d){const w=cell.getBoundingClientRect().width;d.style.width=d.style.minWidth=d.style.maxWidth=w+"px";}}));
  }
  const sr=sc.getBoundingClientRect();
  fl.style.top=hh+"px";fl.style.left=sr.left+"px";fl.style.width=sr.width+"px";
  panFloat(rec);
  if(rec.shown!==true){fl.hidden=false;rec.shown=true;}
}
function syncFloats(rebuild){floats.forEach(f=>{if(rebuild)markH(f);syncFloat(f,rebuild);});}
let fTick=false;
addEventListener("scroll",()=>{if(!fTick){fTick=true;requestAnimationFrame(()=>{fTick=false;syncFloats(false);});}},{passive:true});
addEventListener("resize",()=>syncFloats(true));
function sortTable(t,ci,th){
  if(document.body.classList.contains("editing"))return;
  const cur=th.getAttribute("aria-sort"),next=cur==="ascending"?"descending":cur==="descending"?"none":"ascending";
  $$("thead th",t).forEach(x=>x.removeAttribute("aria-sort")); if(next!=="none")th.setAttribute("aria-sort",next);
  const body=t.tBodies[0],rows=Array.from(body.rows).filter(r=>!r.classList.contains("empty"));
  const key=r=>r.cells[ci]?r.cells[ci].textContent.trim():"";
  rows.sort((a,b)=>{ if(next==="none")return a.dataset.i-b.dataset.i;
    const A=key(a),B=key(b),na=toNum(A),nb=toNum(B); let r;
    if(na!==null&&nb!==null&&(pureNum(A)||pureNum(B)||th.classList.contains("num")))r=na-nb;
    else if(!A||A==="—")return 1; else if(!B||B==="—")return -1; else r=A.localeCompare(B,"zh-Hans-CN");
    return next==="ascending"?r:-r;});
  rows.forEach(r=>body.appendChild(r));
  syncFloats(true);
}

/* ───── charts (ECharts, SVG renderer → crisp print) ───── */
const charts=new Map();
function normalize(s){
  if(!s)return s;
  if(s.type==="grouped")s.type="bar";
  if(s.type==="matrix")s.type="heatmap";
  if(!s.series&&s.cols){s.series=s.cols;delete s.cols;}
  if(s.type==="range"&&!s.series)s.series=[s.lo||"最低",s.hi||"最高"];
  if(!s.series)s.series=["数值"]; if(!s.rows)s.rows=[];
  return s;
}
const shortU=u=>!!u&&String(u).length<=1;
function estW(s,fs){return [...String(s)].reduce((a,c)=>a+(c.charCodeAt(0)>255?1:.6),0)*fs;}
function legendRows(names,w,fs){let rows=1,x=0;names.forEach(n=>{const iw=estW(n,fs)+30;if(x+iw>w&&x>0){rows++;x=0;}x+=iw;});return rows;}
function baseText(narrow){return {fontFamily:FONT,fontSize:narrow?11:12.5,color:C.ink2};}
function optionFor(s,w){
  const narrow=w<560, fs=narrow?11:12.5, t=baseText(narrow), unitTxt=shortU(s.unit)?s.unit:"";
  const cats=s.rows.map(r=>String(r[0])), multi=s.series.length>1;
  const legendH=multi&&s.type!=="heatmap"&&s.type!=="range"?legendRows(s.series,w-24,fs)*22+8:0;
  const legend=legendH?{show:true,top:4,left:4,right:4,icon:"roundRect",itemWidth:12,itemHeight:8,itemGap:14,textStyle:t}:{show:false};
  const labW=Math.min(narrow?96:180,Math.max(48,...cats.map(c=>estW(c,fs)))+6);
  const tooltip={trigger:"axis",axisPointer:{type:"shadow",shadowStyle:{color:"rgba(29,63,143,.06)"}},backgroundColor:"#fff",borderColor:C.rule,textStyle:{fontFamily:FONT,color:C.ink,fontSize:13},valueFormatter:v=>v==null?"—":fmt(v)+(s.unit?" "+s.unit:"")};
  const valAxis={type:"value",max:s.max??null,min:s.min??null,splitLine:{lineStyle:{color:C.grid}},axisLabel:{...t,color:C.muted,formatter:v=>fmt(v)+unitTxt},axisLine:{show:false},axisTick:{show:false}};
  const catAxisBase={type:"category",data:cats,axisTick:{show:false},axisLine:{lineStyle:{color:C.rule}},axisLabel:{...t,color:C.ink,interval:0}};
  const anim={animationDuration:700,animationEasing:"cubicOut",animationDelay:i=>i*40};
  let o={textStyle:{fontFamily:FONT},color:s.colors||PALETTE,...anim,tooltip,legend};
  if(s.type==="bar"||s.type==="stacked"){
    const horiz=s.orient? s.orient!=="v" : (multi||cats.some(c=>c.length>4)||cats.length>6);
    const barW=multi&&s.type!=="stacked"?(narrow?9:10):(narrow?14:16);
    const showLab=s.labels!==false&&(s.type!=="stacked");
    const ser=s.series.map((name,j)=>({name,type:"bar",stack:s.type==="stacked"?"t":undefined,barMaxWidth:barW,barGap:"18%",barCategoryGap:multi?"28%":"38%",
      data:s.rows.map(r=>num(r[j+1])),itemStyle:{borderRadius:s.type==="stacked"?0:(horiz?[0,3,3,0]:[3,3,0,0])},
      label:{show:showLab,position:horiz?"right":"top",distance:4,...t,fontSize:narrow?10:11.5,color:C.ink2,formatter:p=>p.value==null?"":fmt(p.value)+unitTxt},emphasis:{focus:"series"}}));
    if(!multi)ser[0].itemStyle.color=s.colors?.[0]||C.accent;
    if(s.highlight!=null&&!multi){ser[0].data=ser[0].data.map((v,i)=>cats[i]===s.highlight||i===s.highlight?{value:v,itemStyle:{color:C.accent2}}:v);}
    const grid={left:8,right:horiz?(narrow?40:56):12,top:legendH+(horiz?6:24),bottom:8,containLabel:true};
    if(horiz){o={...o,grid,xAxis:valAxis,yAxis:{...catAxisBase,inverse:true,axisLabel:{...catAxisBase.axisLabel,width:labW,overflow:"break",lineHeight:fs*1.3}},series:ser};}
    else{o={...o,grid,yAxis:valAxis,xAxis:{...catAxisBase,axisLabel:{...catAxisBase.axisLabel,width:Math.max(40,(w-60)/Math.max(1,cats.length)-6),overflow:"break",lineHeight:fs*1.3}},series:ser};}
    const per=multi&&s.type!=="stacked"?s.series.length*(barW+2)+10:barW+12;
    o._h=horiz?Math.max(160,cats.length*per+legendH+44):(s.height||(narrow?280:300));
  } else if(s.type==="line"){
    const ser=s.series.map((name,j)=>({name,type:"line",data:s.rows.map(r=>num(r[j+1])),symbol:"circle",symbolSize:7,lineStyle:{width:2.4},connectNulls:true,
      areaStyle:multi?undefined:{color:{type:"linear",x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:"rgba(29,63,143,.16)"},{offset:1,color:"rgba(29,63,143,0)"}]}},
      label:{show:cats.length<=12&&s.labels!==false,position:"top",...t,fontSize:narrow?10:11.5,color:C.ink,formatter:p=>p.value==null?"":fmt(p.value)},emphasis:{focus:"series"}}));
    if(!multi){ser[0].itemStyle={color:s.colors?.[0]||C.accent};ser[0].lineStyle.color=s.colors?.[0]||C.accent;}
    o={...o,tooltip:{...tooltip,axisPointer:{type:"line",lineStyle:{color:C.rule}}},grid:{left:8,right:narrow?16:28,top:legendH+28,bottom:8,containLabel:true},
      xAxis:{...catAxisBase,boundaryGap:false,axisLabel:{...catAxisBase.axisLabel,color:C.muted,hideOverlap:true,alignMinLabel:"left",alignMaxLabel:"right",interval:narrow?"auto":0,formatter:v=>narrow&&/^\d{4}-\d\d-\d\d$/.test(v)?v.slice(0,7):v}},yAxis:valAxis,series:ser};
    o._h=s.height||(narrow?250:290);
  } else if(s.type==="range"){
    const lo=s.rows.map(r=>num(r[1])),hi=s.rows.map(r=>num(r[2])),PF=s.prefix||"",SF=s.suffix||"";
    const a=lo.map((v,i)=>v==null||hi[i]==null?null:Math.min(v,hi[i])),b=lo.map((v,i)=>v==null||hi[i]==null?null:Math.max(v,hi[i]));
    const fmtR=i=>a[i]==null?"—":a[i]===b[i]?`${PF}${fmt(a[i])}${SF}`:`${PF}${fmt(a[i])}${SF}–${fmt(b[i])}${SF}`;
    o={...o,tooltip:{...tooltip,formatter:ps=>{const i=ps[0].dataIndex;return `<b>${esc(cats[i])}</b><br>${esc(fmtR(i))}${s.unit?" · "+esc(s.unit):""}`;}},
      grid:{left:8,right:narrow?92:150,top:10,bottom:8,containLabel:true},xAxis:{...valAxis,axisLabel:{...valAxis.axisLabel,formatter:v=>fmt(v)}},
      yAxis:{...catAxisBase,inverse:true,axisLabel:{...catAxisBase.axisLabel,width:labW,overflow:"break",lineHeight:fs*1.3}},
      series:[
        {type:"bar",stack:"r",data:a,itemStyle:{color:"transparent"},silent:true,barWidth:narrow?8:10,emphasis:{disabled:true}},
        {type:"bar",stack:"r",data:b.map((v,i)=>v==null?null:Math.max(v-a[i],0)),barWidth:narrow?8:10,itemStyle:{color:"rgba(29,63,143,.32)",borderRadius:5}},
        {type:"scatter",data:a.map((v,i)=>v==null||a[i]===b[i]?null:[v,i]),symbolSize:narrow?9:11,itemStyle:{color:"#fff",borderColor:C.accent,borderWidth:2},z:3},
        {type:"scatter",data:b.map((v,i)=>v==null?null:[v,i]),symbolSize:narrow?9:11,itemStyle:{color:C.accent},z:4,
          label:{show:true,position:"right",distance:8,...t,fontSize:narrow?10.5:12,color:C.ink,formatter:p=>fmtR(p.dataIndex)}}]};
    o._h=Math.max(150,cats.length*(narrow?36:36)+48);
  } else if(s.type==="heatmap"){
    const max=s.max??Math.max(1,...s.rows.flatMap(r=>r.slice(1).map(num).filter(v=>v!=null)));
    const xs=s.series.map((c,j)=>{if(!s.colTotal)return c;const tot=s.rows.reduce((a,r)=>a+(num(r[j+1])||0),0);return `${c}\n合计 ${fmt(tot)}`;});
    const ramp=s.ramp||["#f2eee5","#cdd9f0","#7d9bd6","#1d3f8f"];
    const pieces=[];for(let k=0;k<ramp.length;k++){const lo=max*k/ramp.length,hi=max*(k+1)/ramp.length;pieces.push({gte:k===0?-Infinity:lo,lt:k===ramp.length-1?Infinity:hi,color:ramp[k]});}
    if(Number.isInteger(max)&&max+1===ramp.length){pieces.length=0;ramp.forEach((c,k)=>pieces.push({gte:k===0?-Infinity:k-.5,lt:k===ramp.length-1?Infinity:k+.5,color:c}));}
    const data=[];s.rows.forEach((r,i)=>s.series.forEach((_,j)=>{const v=num(r[j+1]);data.push({value:[j,i,v==null?"-":v],label:{color:v!=null&&v>=max*0.9?"#fff":C.ink}});}));
    const cellW=narrow?Math.max(36,Math.min(56,(w-labW-16)/s.series.length)):Math.max(64,Math.min(120,(w-labW-40)/s.series.length));
    o={...o,tooltip:{trigger:"item",backgroundColor:"#fff",borderColor:C.rule,textStyle:{fontFamily:FONT,color:C.ink,fontSize:13},formatter:p=>`${esc(cats[p.value[1]])} · ${esc(s.series[p.value[0]])}<br><b>${p.value[2]==="-"?"—":fmt(p.value[2])}</b> ${esc(s.unit||"")}`},
      grid:{left:8,right:8,top:s.colTotal?(narrow?58:52):(narrow?44:38),bottom:8,containLabel:true},
      xAxis:{type:"category",data:xs,position:"top",splitArea:{show:false},axisTick:{show:false},axisLine:{show:false},axisLabel:{...t,color:C.ink,interval:0,width:cellW-6,overflow:"break",lineHeight:fs*1.35,fontWeight:500}},
      yAxis:{type:"category",data:cats,inverse:true,axisTick:{show:false},axisLine:{show:false},axisLabel:{...t,color:C.ink,width:labW,overflow:"break"}},
      visualMap:{type:"piecewise",show:false,pieces,dimension:2},
      series:[{type:"heatmap",data,itemStyle:{borderColor:C.surface,borderWidth:3,borderRadius:4},label:{show:true,...t,fontSize:narrow?11.5:13,fontWeight:600,formatter:p=>p.value[2]==="-"?"—":fmt(p.value[2])},
        emphasis:{itemStyle:{borderColor:C.accent2,borderWidth:2}}}]};
    o._h=s.rows.length*(narrow?38:36)+(s.colTotal?64:50); o._minW=labW+s.series.length*cellW+12;
  } else if(s.type==="pie"){
    o={...o,tooltip:{trigger:"item",backgroundColor:"#fff",borderColor:C.rule,textStyle:{fontFamily:FONT,color:C.ink},formatter:p=>`${esc(p.name)}<br><b>${fmt(p.value)}</b> ${esc(s.unit||"")}（${p.percent}%）`},legend:{show:false},
      series:[{type:"pie",radius:narrow?["38%","62%"]:["45%","70%"],center:["50%","52%"],itemStyle:{borderColor:C.surface,borderWidth:2},
        label:{...t,color:C.ink,formatter:p=>s.unit==="%"?`${p.name}\n${fmt(p.value)}%`:`${p.name}\n${fmt(p.value)}${unitTxt}（${p.percent}%）`,lineHeight:fs*1.4},labelLine:{lineStyle:{color:C.rule}},
        data:s.rows.map(r=>({name:String(r[0]),value:num(r[1])}))}]};
    o._h=s.height||(narrow?280:300);
  }
  if(s.height&&s.type!=="heatmap")o._h=s.height;
  return o;
}
function chartNote(fig,s){
  let n=fig.querySelector(".ex-note[data-rt]");
  const bits=[];
  if(s.unit&&!shortU(s.unit))bits.push("单位："+s.unit);
  if(s.type==="heatmap"&&s.legend)bits.push(s.legend.join(" · "));
  if(s.rows.some(r=>r.slice(1).some(v=>num(v)===null))&&s.type!=="range")bits.push("— = "+(s.nullLabel||"无数据"));
  if(s.note)bits.push(s.note);
  if(!bits.length){if(n)n.remove();return;}
  if(!n){n=document.createElement("p");n.className="ex-note";n.dataset.rt="";fig.querySelector(".ex-chart").after(n);}
  n.innerHTML=bits.map(b=>`<span>${esc(b)}</span>`).join("");
}
function renderChart(fig,opts={}){
  const id=fig.dataset.chart, s=normalize(DATA.charts[id]), box=fig.querySelector(".ex-chart")||(()=>{const d=document.createElement("div");d.className="ex-chart";fig.querySelector(".ex-head").after(d);return d;})();
  if(!s){box.innerHTML=`<div class="ex-fallback" data-rt>图表数据缺失：在 #report-data 的 charts 中添加 “${esc(id)}”。</div>`;return;}
  if(typeof echarts==="undefined"){box.innerHTML=`<div class="ex-fallback" data-rt>图表库未加载。数据：${esc(JSON.stringify(s.rows))}</div>`;return;}
  let cv=box.querySelector(".ex-canvas"), rec=charts.get(fig);
  const w=opts.width||box.clientWidth||720;
  const o=optionFor(s,w);
  if(!cv){cv=document.createElement("div");cv.className="ex-canvas";cv.dataset.rt="";box.appendChild(cv);}
  cv.style.height=o._h+"px"; cv.style.minWidth=o._minW&&o._minW>w?o._minW+"px":"";
  const real={...o};delete real._h;delete real._minW;
  if(opts.noAnim)real.animation=false;
  if(!rec){const inst=echarts.init(cv,null,{renderer:"svg"});rec={inst,narrow:w<560,w};charts.set(fig,rec);}
  else rec.inst.resize({width:opts.width||"auto",height:o._h});
  rec.inst.setOption(real,true);
  rec.narrow=w<560;rec.w=w;
  chartNote(fig,s);
}
function renderAll(){ $$(".exhibit[data-chart]").forEach(f=>{try{renderChart(f);}catch(e){console.error("图表渲染失败",f.dataset.chart,e);}}); }
const ro=typeof ResizeObserver!=="undefined"?new ResizeObserver(es=>{if(printing)return;es.forEach(e=>{const fig=e.target.closest(".exhibit"),rec=charts.get(fig);if(!rec)return;const w=e.contentRect.width;if(Math.abs(w-rec.w)<4)return;
  if((w<560)!==rec.narrow||true)renderChart(fig,{noAnim:true});});}):null;

/* ───── edit mode ───── */
const EDITABLE="h1,h2,h3,h4,h5,h6,p,li,td,th,dt,dd,blockquote,.ex-title,.ex-src,.summary-text,.summary-label,.callout-title,figcaption";
const ICON_DATA='<svg class="i" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M9 9.5v10"/></svg>';
function editableTargets(){
  const roots=$$("main .cover, main .doc, main .colophon");
  const out=[];roots.forEach(r=>$$(EDITABLE,r).forEach(el=>{
    if(el.closest("[data-rt],.ex-editor,.ex-chart,.tbl-tools"))return;
    const p=el.parentElement&&el.parentElement.closest(EDITABLE); if(p&&r.contains(p)&&!p.matches("figcaption.ex-head"))return;
    if(el.matches("figcaption.ex-head"))return;
    out.push(el);}));
  return out;
}
let editing=false;
function setEditing(on){
  editing=on;document.body.classList.toggle("editing",on);
  const b=$("#btnEdit");if(b){b.setAttribute("aria-pressed",on);$(".lbl",b).textContent=on?"完成修改":"修改";}
  if(on){ensureEids();if(!SNAP)takeSnap();}
  editableTargets().forEach(el=>{if(on){el.setAttribute("contenteditable","true");el.spellcheck=false;}else el.removeAttribute("contenteditable");});
  $$(".exhibit[data-chart]").forEach(fig=>{
    let btn=fig.querySelector(".ex-edit-btn");
    if(on&&!btn){btn=document.createElement("button");btn.type="button";btn.className="btn line sm ex-edit-btn";btn.dataset.rt="";btn.innerHTML=ICON_DATA+"<span>编辑数据</span>";btn.addEventListener("click",()=>toggleEditor(fig));fig.querySelector(".ex-head").appendChild(btn);}
    if(!on){const ed=fig.querySelector(".ex-editor");if(ed)ed.remove();}
  });
  $$("details.intro-note").forEach(d=>{if(on){if(!d.open){d.open=true;d.dataset.rtOpen="";}}else if("rtOpen" in d.dataset){d.open=false;delete d.dataset.rtOpen;}});
  setSyncBtn(syncing);
  if(!on)buildToc();
  syncFloats(true);
  hint(on?"修改中：点文字直接改；图表标题右侧「编辑数据」可改数字。改动会先存在本机浏览器，点「同步修改」回写飞书同一链接。":"已退出修改（未同步的改动仍保存在本机）");
}
let hintT;function hint(msg){let h=$(".edit-hint");if(!h){h=document.createElement("div");h.className="edit-hint";h.dataset.rt="";h.setAttribute("role","status");document.body.appendChild(h);}
  h.textContent=msg;h.classList.add("show");clearTimeout(hintT);hintT=setTimeout(()=>h.classList.remove("show"),3600);}
document.addEventListener("input",e=>{if(e.target.closest&&e.target.closest('[contenteditable="true"]'))setDirty(true);});
document.addEventListener("focusout",e=>{if(editing&&e.target.matches&&e.target.matches(".doc > h2"))buildToc();});
document.addEventListener("paste",e=>{if(!editing||!e.target.closest('[contenteditable="true"]'))return;e.preventDefault();const t=(e.clipboardData||window.clipboardData).getData("text/plain");document.execCommand("insertText",false,t);});

function toggleEditor(fig){
  let ed=fig.querySelector(".ex-editor"); if(ed){ed.remove();return;}
  const id=fig.dataset.chart, s=normalize(DATA.charts[id]); if(!s)return;
  ed=document.createElement("div");ed.className="ex-editor";ed.dataset.rt="";
  const types=[["bar","条形 / 柱状"],["stacked","堆叠条形"],["line","折线"],["range","区间（最低–最高）"],["heatmap","评分矩阵"],["pie","环形占比"]];
  ed.innerHTML=`<div class="row"><label>类型 <select class="t">${types.map(([v,l])=>`<option value="${v}"${v===s.type?" selected":""}>${l}</option>`).join("")}</select></label>
   <label>单位 <input type="text" class="u" value="${esc(s.unit||"")}" size="8"></label>
   <span style="flex:1"></span>
   <button type="button" class="btn line sm" data-a="addr">＋ 行</button><button type="button" class="btn line sm" data-a="delr">－ 末行</button>
   <button type="button" class="btn line sm" data-a="addc">＋ 列</button><button type="button" class="btn line sm" data-a="delc">－ 末列</button>
   <button type="button" class="btn line sm" data-a="json">JSON</button></div>
   <div class="grid-wrap"></div><textarea class="js" hidden spellcheck="false"></textarea>
   <p class="help">第一列是类别，其余每列是一个系列；空格或 — 表示无数据。修改即时生效，点「同步修改」回写主稿。</p>`;
  fig.appendChild(ed);
  const gw=$(".grid-wrap",ed), ta=$(".js",ed);
  const draw=()=>{const cols=s.series.length;
    let h=`<table><thead><tr><th><input class="cell" value="${esc(s.catLabel||"类别")}" data-k="cat"></th>${s.series.map((n,j)=>`<th><input class="cell" value="${esc(n)}" data-k="s" data-j="${j}"></th>`).join("")}</tr></thead><tbody>`;
    s.rows.forEach((r,i)=>{h+=`<tr><td><input class="cell" value="${esc(r[0])}" data-i="${i}" data-j="-1"></td>`;for(let j=0;j<cols;j++){const v=r[j+1];h+=`<td><input class="cell" inputmode="decimal" value="${v==null?"":esc(v)}" data-i="${i}" data-j="${j}"></td>`;}h+="</tr>";});
    gw.innerHTML=h+"</tbody></table>";};
  draw();
  let tm;const apply=()=>{clearTimeout(tm);tm=setTimeout(()=>{renderChart(fig,{noAnim:true});setDirty(true);},160);};
  gw.addEventListener("input",e=>{const x=e.target;if(!x.classList.contains("cell"))return;
    if(x.dataset.k==="cat"){s.catLabel=x.value;}
    else if(x.dataset.k==="s"){s.series[+x.dataset.j]=x.value;}
    else{const i=+x.dataset.i,j=+x.dataset.j;if(j<0)s.rows[i][0]=x.value;else{const t=x.value.trim().replace(/[,，]/g,"");const bad=t!==""&&t!=="—"&&t!=="-"&&isNaN(+t);x.classList.toggle("bad",bad);if(bad)return;s.rows[i][j+1]=t===""||t==="—"||t==="-"?null:+t;}}
    apply();});
  ed.addEventListener("change",e=>{if(e.target.matches(".t")){s.type=e.target.value;if(s.type==="range"){while(s.series.length<2)s.series.push("最高");s.rows.forEach(r=>{while(r.length<3)r.push(null);});}draw();apply();}
    if(e.target.matches(".u")){s.unit=e.target.value;apply();}});
  ed.addEventListener("click",e=>{const a=e.target.closest("[data-a]");if(!a)return;const k=a.dataset.a;
    if(k==="addr")s.rows.push(["新类别",...s.series.map(()=>null)]);
    if(k==="delr"&&s.rows.length>1)s.rows.pop();
    if(k==="addc"){s.series.push("新系列");s.rows.forEach(r=>r.push(null));}
    if(k==="delc"&&s.series.length>1){s.series.pop();s.rows.forEach(r=>r.length=s.series.length+1);}
    if(k==="json"){ta.hidden=!ta.hidden;if(!ta.hidden)ta.value=JSON.stringify(s,null,1);gw.hidden=!ta.hidden;return;}
    draw();apply();});
  ta.addEventListener("change",()=>{try{const n=JSON.parse(ta.value);Object.keys(s).forEach(k=>delete s[k]);Object.assign(s,normalize(n));ta.style.borderColor="";draw();apply();}catch(err){ta.style.borderColor="#a3302a";hint("JSON 格式有误："+err.message);}});
}

/* ───── download the edited page ───── */
function pageName(){
  return (meta("report-name")||document.title||"报告").replace(/[\\/:*?"<>|]/g,"_").replace(/_v\d+(_可编辑)?$/,"");
}
function serialize(){
  if(editing)$$('[contenteditable="true"]').forEach(el=>el.blur());
  const root=document.documentElement.cloneNode(true);
  root.querySelectorAll("[data-rt]").forEach(n=>n.remove());
  root.querySelectorAll("[contenteditable]").forEach(n=>n.removeAttribute("contenteditable"));
  root.querySelectorAll("[spellcheck]").forEach(n=>n.removeAttribute("spellcheck"));
  root.querySelectorAll("[_echarts_instance_]").forEach(n=>n.removeAttribute("_echarts_instance_"));
  root.querySelectorAll("tr[hidden]").forEach(n=>n.removeAttribute("hidden"));
  root.querySelectorAll("tr[data-i]").forEach(n=>n.removeAttribute("data-i"));
  root.querySelectorAll("th[data-sort]").forEach(n=>{n.removeAttribute("data-sort");n.removeAttribute("aria-sort");n.removeAttribute("tabindex");n.removeAttribute("role");});
  root.querySelectorAll("[data-auto-id]").forEach(n=>n.removeAttribute("data-auto-id"));
  const tl=root.querySelector("#toc");if(tl){tl.classList.remove("end");if(!tl.className)tl.removeAttribute("class");}
  root.querySelectorAll("details[data-rt-open],details[data-pr-open]").forEach(n=>{n.removeAttribute("open");n.removeAttribute("data-rt-open");n.removeAttribute("data-pr-open");});
  root.querySelectorAll(".tbl.hscroll,.tbl.scrolled").forEach(n=>n.classList.remove("hscroll","scrolled"));
  root.querySelectorAll("[aria-current]").forEach(n=>n.removeAttribute("aria-current"));
  const b=root.querySelector("body");b.classList.remove("editing");if(!b.className)b.removeAttribute("class");
  const toc=root.querySelector("#toc");if(toc)toc.innerHTML="";
  const pr=root.querySelector("#progress");if(pr)pr.removeAttribute("style");
  const ss=root.querySelector("#saveState");if(ss)ss.textContent="";
  const be=root.querySelector("#btnEdit");if(be){be.setAttribute("aria-pressed","false");const l=be.querySelector(".lbl");if(l)l.textContent="修改";}
  const bs=root.querySelector("#btnSync");if(bs)bs.setAttribute("hidden","");
  const de=root.querySelector("#report-data");if(de)de.textContent="\n"+JSON.stringify(DATA).replace(/</g,"\\u003c")+"\n";
  return "<!doctype html>\n"+root.outerHTML;
}
function downloadPage(){
  const file=pageName()+"_已修改_"+new Date().toISOString().slice(0,16).replace(/[-:T]/g,"")+".html";
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([serialize()],{type:"text/html;charset=utf-8"}));a.download=file;
  document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1500);
  hint("已下载 "+file);
}

/* ───── print ───── */
let printing=false;
function printPrep(on){printing=on;$$("details.intro-note").forEach(d=>{if(on){if(!d.open){d.open=true;d.dataset.prOpen="";}}else if("prOpen" in d.dataset){d.open=false;delete d.dataset.prOpen;}});charts.forEach((rec,fig)=>{try{renderChart(fig,on?{width:672,noAnim:true}:{noAnim:true});}catch(e){}});}
addEventListener("beforeprint",()=>printPrep(true));addEventListener("afterprint",()=>printPrep(false));

/* ───── 同步修改: one package → same-origin edge/relay, else edge, else webhook → box → same-link Feishu ───── */
const REP=meta("report-id")||(typeof SYNC_REP!=="undefined"?SYNC_REP:"");
const EDGE=(meta("sync-edge")||"").replace(/\/+$/,"");
const DRAFT_KEY="sync-draft:"+(REP||meta("report-name")||location.pathname);
const LS={get(k){try{return JSON.parse(localStorage.getItem(k)||"null");}catch(e){return null;}},
  set(k,v){try{localStorage.setItem(k,JSON.stringify(v));return true;}catch(e){return false;}},
  del(k){try{localStorage.removeItem(k);}catch(e){}}};
let EID=0, SNAP=null, SNAPDATA=null, REV=meta("sync-rev"), HOME=null, HOME_KIND="", syncing=false;

function ensureEids(){
  $$("[data-eid]").forEach(n=>{EID=Math.max(EID,+n.dataset.eid||0);});
  editableTargets().forEach(el=>{ if(!el.dataset.eid) el.dataset.eid=String(++EID); });
}
function cleanHTML(n){
  const c=n.cloneNode(true);
  c.querySelectorAll("[data-rt]").forEach(x=>x.remove());
  [c,...c.querySelectorAll("[contenteditable],[spellcheck]")].forEach(x=>{x.removeAttribute("contenteditable");x.removeAttribute("spellcheck");});
  return c.innerHTML;
}
function takeSnap(){
  ensureEids();
  SNAP=new Map();
  $$("[data-eid]").forEach(n=>SNAP.set(n.dataset.eid,cleanHTML(n)));
  SNAPDATA=JSON.parse(JSON.stringify(DATA));
}
function plain(h){ const d=document.createElement("div"); d.innerHTML=h; return d.textContent.replace(/\s+/g," ").trim(); }
function before(a,b){ return a===b||a.contains(b)||!!(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING); }
function sibText(n,dir){
  let s=dir<0?n.previousElementSibling:n.nextElementSibling;
  while(s&&s.matches("[data-rt]"))s=dir<0?s.previousElementSibling:s.nextElementSibling;
  return s?s.textContent.replace(/\s+/g," ").trim().slice(0,40):"";
}
function ctxOf(n){
  const root=doc||document.body;
  const sec=$$(":scope > h2[id]",root).filter(h=>before(h,n)).pop();
  const head=$$("h1,h2,h3,h4",root).filter(h=>before(h,n)).pop();
  const cell=n.closest("td,th"), tr=n.closest("tr");
  const row=tr&&tr.cells[0]?tr.cells[0].textContent.replace(/\s+/g," ").trim().slice(0,30):"";
  const c={tag:n.tagName.toLowerCase(),
    sid:sec&&!("autoId" in sec.dataset)?sec.id:"",
    h:head&&head!==n?head.textContent.replace(/\s+/g," ").trim().slice(0,40):"",
    prev:sibText(n,-1),next:sibText(n,1)};
  if(row)c.row=row;
  if(cell)c.col=cell.cellIndex;
  c.ctx=(sec?sec.id:"")+(row?" / "+row:"");
  return c;
}
function changedEls(){
  const changed=new Set();
  SNAP.forEach((html,eid)=>{const n=document.querySelector('[data-eid="'+eid+'"]');if(n&&cleanHTML(n)!==html)changed.add(n);});
  return [...changed].filter(n=>{let p=n.parentElement;while(p){if(changed.has(p))return false;p=p.parentElement;}return true;});
}
function collectEdits(){
  if(editing)$$('[contenteditable="true"]').forEach(el=>{try{el.blur();}catch(e){}});
  const ops=[]; if(!SNAP) return ops;
  SNAP.forEach((html,eid)=>{ if(!document.querySelector('[data-eid="'+eid+'"]')) ops.push({op:"del",eid,old:html}); });
  const dels=ops.filter(o=>o.op==="del"&&!ops.some(p=>p!==o&&p.old.indexOf('data-eid="'+o.eid+'"')>=0));
  const out=changedEls().map(n=>Object.assign({op:"edit",eid:n.dataset.eid,old:SNAP.get(n.dataset.eid),new:cleanHTML(n)},ctxOf(n)));
  out.push(...dels);
  if(SNAPDATA&&JSON.stringify(SNAPDATA.charts||{})!==JSON.stringify(DATA.charts||{}))
    out.push({op:"data",key:"@charts",old:SNAPDATA.charts,new:DATA.charts});
  return out;
}
function b64(str){ return btoa(unescape(encodeURIComponent(str))); }
function newId(){ try{ return crypto.randomUUID().replace(/-/g,"").slice(0,20); }catch(e){ return Date.now().toString(36)+Math.random().toString(36).slice(2,10); } }
function buildPackage(ops){
  const d=new Date();
  const pkg={ver:SYNC_VER,rep:REP,id:newId(),ts:d.toISOString(),rev:REV||"",title:meta("report-name")||document.title,ops};
  if(SAVE_FILE_TOKEN) pkg.file_token=SAVE_FILE_TOKEN;
  const lines=["【报告同步 "+SYNC_VER+"】"+pkg.title+"（"+(REP||"未标注报告")+"）· "+d.toLocaleString("zh-CN",{hour12:false})+"，共 "+ops.length+" 处修改"];
  ops.forEach((o,i)=>{
    if(o.op==="edit") lines.push((i+1)+". 修改 ["+(o.h||o.ctx||"")+"] 「"+plain(o.old).slice(0,80)+"」→「"+plain(o.new).slice(0,80)+"」");
    else if(o.op==="del") lines.push((i+1)+". 删除 「"+plain(o.old).slice(0,80)+"」");
    else lines.push((i+1)+". 数据 "+o.key);
  });
  lines.push("SDMCSYNC1:"+b64(JSON.stringify(pkg))+":END");
  return {pkg,text:lines.join("\n")};
}

/* where to send: the page's own origin when it is served by the edge worker or the relay (no CORS at all),
   then the edge worker, then the shared webhook. text/plain is a CORS "simple" request: no preflight. */
function probeHome(){
  if(HOME!==null) return Promise.resolve(HOME);
  if(!/^https?:$/.test(location.protocol)) return Promise.resolve(HOME="");
  return fetch(location.origin+"/health",{cache:"no-store"}).then(r=>r.json()).then(j=>{
    HOME=j&&(j.service==="sdmc-edge"||j.service==="sdmc-relay")?location.origin:"";
    if(HOME)HOME_KIND=j.service; return HOME;
  }).catch(()=>HOME="");
}
function targets(){
  const t=[];
  if(HOME)t.push({url:HOME+"/sync",status:HOME,kind:HOME_KIND});
  if(EDGE&&EDGE!==HOME)t.push({url:EDGE+"/sync",status:EDGE,kind:"sdmc-edge"});
  if(SYNC_WEBHOOK)t.push({url:SYNC_WEBHOOK,status:"",kind:"webhook"});
  return t;
}
function post(t,text){
  const o={method:"POST",headers:{"Content-Type":"text/plain;charset=UTF-8"},body:text,cache:"no-store",credentials:"omit"};
  return fetch(t.url,Object.assign({mode:"cors"},o)).then(r=>{ if(!r.ok&&r.status!==202) throw new Error("http "+r.status); return {t,confirmed:true}; })
    .catch(e=>{ if(String(e&&e.message).startsWith("http ")) throw e;
      return fetch(t.url,Object.assign({mode:"no-cors"},o)).then(()=>({t,confirmed:false})); });
}
function sendAll(text){
  const list=targets();
  if(!list.length) return Promise.reject(new Error("页面没有配置同步地址"));
  let i=0, errs=[];
  const next=()=>i>=list.length?Promise.reject(new Error(errs.join("；"))):post(list[i++],text).catch(e=>{errs.push(e.message||String(e));return next();});
  return next();
}
function jsonp(url){
  return new Promise((res,rej)=>{const cb="__sync_cb_"+Math.random().toString(36).slice(2);const s=document.createElement("script");
    const done=v=>{delete window[cb];s.remove();v instanceof Error?rej(v):res(v);};
    window[cb]=done;s.onerror=()=>done(new Error("jsonp"));s.src=url+(url.includes("?")?"&":"?")+"cb="+cb;document.head.appendChild(s);
    setTimeout(()=>{if(window[cb])done(new Error("timeout"));},8000);});
}
function getJSON(url){ return fetch(url,{cache:"no-store",credentials:"omit"}).then(r=>r.json()).catch(()=>jsonp(url)); }
function revURL(base,kind){ return kind==="sdmc-edge"?base+"/rev/"+encodeURIComponent(REP):base+"/rev?rep="+encodeURIComponent(REP); }

const STAGE={queued:"已送达，等待助理端取件",received:"助理端已收到，正在写回主稿",applied:"已写回主稿，正在更新飞书同一链接",
  nochange:"助理端已处理：主稿里已经是这些内容",unresolved:"部分修改没能定位到原文",held:"未写入：这份修改没有对应的报告",
  feishu:"已更新飞书同一链接",gated:"已写回主稿；飞书同一链接等 Derek 确认后由助理端更新",feishu_error:"已写回主稿，但飞书更新失败（助理端会重试）"};
function watch(base,id,ops,onDone){
  let n=0;
  const tick=()=>getJSON(base+"/status/"+encodeURIComponent(id)).then(st=>{
    const s=st&&st.stage||"unknown";
    const un=Array.isArray(st&&st.unresolved)?st.unresolved.length:0;
    if(STAGE[s])syncPanel(STAGE[s]+(s==="held"&&st.reason?"："+st.reason:"")+(un?"（"+un+" 处没能定位到原文，已留在助理端待处理）":""),s);
    if(["feishu","gated","nochange","unresolved","held","feishu_error"].includes(s)) return onDone(st);
    if(++n<45) setTimeout(tick,2000); else { syncPanel("已送达；助理端暂未回执，可稍后刷新查看","slow"); onDone(st); }
  },()=>{ if(++n<45) setTimeout(tick,2000); });
  tick();
}
function syncPanel(msg,stage,text){
  let m=document.getElementById("syncBox");
  if(!m){
    m=document.createElement("div");m.id="syncBox";m.dataset.rt="";m.setAttribute("role","status");
    m.innerHTML='<div class="sb-in"><p class="sb-m"></p><div class="sb-b"><button type="button" class="btn line" data-a="dl">下载改过的页面</button><button type="button" class="btn line" data-a="copy" hidden>复制同步文本</button><button type="button" class="btn" data-a="close">关闭</button></div><textarea readonly hidden></textarea></div>';
    m.addEventListener("click",e=>{const a=e.target.dataset&&e.target.dataset.a;
      if(a==="close")m.remove(); if(a==="dl")downloadPage();
      if(a==="copy"){const ta=m.querySelector("textarea");ta.hidden=false;ta.focus();ta.select();copyText(ta.value).then(ok=>{m.querySelector(".sb-m").textContent=ok?"已复制，可粘贴给助理。":"请在框内全选后复制。";});}});
    document.body.appendChild(m);
  }
  m.dataset.stage=stage||"";
  m.querySelector(".sb-m").textContent=msg;
  if(text!==undefined){const ta=m.querySelector("textarea");ta.value=text;m.querySelector('[data-a="copy"]').hidden=!text;}
}
function copyText(text){
  const fb=()=>{ try{ const ta=document.createElement("textarea"); ta.value=text; ta.style.cssText="position:fixed;left:-9999px;top:0"; document.body.appendChild(ta); ta.select(); const ok=document.execCommand("copy"); ta.remove(); return ok; }catch(e){ return false; } };
  if(navigator.clipboard&&window.isSecureContext){ return navigator.clipboard.writeText(text).then(()=>true,()=>fb()); }
  return Promise.resolve(fb());
}
function setSyncBtn(busy){
  const btn=$("#btnSync"); if(!btn) return;
  btn.disabled=!!busy; btn.hidden=!(editing||dirty||busy);
  const l=$(".lbl",btn); if(l) l.textContent=busy?"同步中…":"同步修改";
}
function doSync(){
  if(syncing) return;
  const ops=collectEdits();
  if(!ops.length){ syncPanel("还没有修改。","none",""); return; }
  const {pkg,text}=buildPackage(ops); window.__lastSync=text;
  syncing=true; setSyncBtn(true); syncPanel("正在发送 "+ops.length+" 处修改…","sending",text);
  probeHome().then(()=>sendAll(text)).then(({t,confirmed})=>{
    const base=t.status||(EDGE||"");
    takeSnap(); LS.del(DRAFT_KEY);
    if(base){
      syncPanel(confirmed?STAGE.queued:"已发出（浏览器不显示回执），正在确认…","queued",text);
      watch(base,pkg.id,ops,st=>{
        if(st&&st.rev){ REV=st.rev; const mr=$('meta[name="sync-rev"]'); if(mr)mr.content=REV; }
        setDirty(false);
        syncing=false; setSyncBtn(false);
      });
    }else{
      syncPanel("已发出到中转（"+(confirmed?"已确认送达":"浏览器不显示回执")+"）；助理端取件后会写回飞书同一链接。","sent",text);
      setDirty(false); syncing=false; setSyncBtn(false);
    }
  }).catch(err=>{
    saveDraft(true);
    syncPanel("自动同步没发出去（"+(err&&err.message||"网络错误")+"）。修改已保存在本机浏览器，下次打开会恢复；也可以复制下面的同步文本发给助理。","failed",text);
    syncing=false; setSyncBtn(false);
  });
}

/* drafts: unsynced edits stay in this browser and come back on reload, if the master text is unchanged */
let draftT;
function saveDraft(force){
  clearTimeout(draftT);
  const run=()=>{ if(!SNAP) return; const edits={};
    changedEls().forEach(n=>{edits[n.dataset.eid]={old:SNAP.get(n.dataset.eid),new:cleanHTML(n)};});
    const charts=SNAPDATA&&JSON.stringify(SNAPDATA.charts||{})!==JSON.stringify(DATA.charts||{})?DATA.charts:null;
    if(!Object.keys(edits).length&&!charts){ LS.del(DRAFT_KEY); return; }
    LS.set(DRAFT_KEY,{rev:REV||"",at:new Date().toISOString(),edits,charts}); };
  if(force) run(); else draftT=setTimeout(run,500);
}
function restoreDraft(){
  const d=LS.get(DRAFT_KEY); if(!d||!d.edits) return;
  let ok=0, skip=0;
  Object.entries(d.edits).forEach(([eid,e])=>{
    const n=document.querySelector('[data-eid="'+eid+'"]');
    if(n&&cleanHTML(n)===e.old){ n.innerHTML=e.new; ok++; } else skip++;
  });
  if(d.charts&&(!d.rev||d.rev===REV)){ DATA.charts=d.charts; renderAll(); ok++; }
  if(ok){ setDirty(true); setSyncBtn(false); }
  if(ok||skip) hint((ok?"已恢复本机未同步的修改 "+ok+" 处，点「同步修改」发出。":"")+(skip?" "+skip+" 处旧修改因原文已更新未套用。":""));
  if(!ok) LS.del(DRAFT_KEY);
}

/* the master moved on (someone else synced, or the assistant edited): say so instead of silently diverging */
function checkRev(){
  if(!REP) return;
  probeHome().then(()=>{
    const base=HOME||EDGE; if(!base) return;
    return getJSON(revURL(base,HOME?HOME_KIND:"sdmc-edge")).then(j=>{
      if(!j||!j.rev||!REV||j.rev===REV) return;
      if(!dirty&&!editing){ location.reload(); return; }
      syncPanel("主稿已经更新过（别人同步或助理改过）。先点「同步修改」发出你的修改，再刷新页面看最新版。","stale");
    });
  }).catch(()=>{});
}

window.__report={serialize,downloadPage,setEditing,renderAll,DATA,doSync,collectEdits,takeSnap,buildPackage};
window.__collectEdits=collectEdits; window.__editsText=()=>buildPackage(collectEdits()).text; window.__takeSnap=takeSnap;

/* ───── boot ───── */
function boot(){
  $$("#bReset,#bCopy,#btnSaveAs,#btnSaveFeishu").forEach(n=>n.remove());
  buildToc();enhanceTables();renderAll();
  if(ro)$$(".exhibit .ex-chart").forEach(b=>ro.observe(b));
  ensureEids(); takeSnap(); restoreDraft();
  $("#btnEdit")?.addEventListener("click",()=>setEditing(!editing));
  $("#btnSync")?.addEventListener("click",doSync);
  $("#btnPrint")?.addEventListener("click",()=>{if(editing)setEditing(false);printPrep(true);setTimeout(()=>window.print(),120);});
  addEventListener("keydown",e=>{
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="s"){e.preventDefault();if(e.shiftKey)downloadPage();else doSync();}
    if(e.key==="Escape"&&editing&&!e.target.closest(".ex-editor"))setEditing(false);});
  document.addEventListener("input",()=>{if(editing)saveDraft();});
  addEventListener("beforeunload",e=>{if(dirty){saveDraft(true);e.preventDefault();e.returnValue="";}});
  document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")checkRev();});
  setInterval(checkRev,120000); probeHome().then(checkRev);
  if(location.hash){const t=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(t)setTimeout(()=>t.scrollIntoView(),60);}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);else boot();
})();
