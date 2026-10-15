// Drives the review kit on the real masters; run through review_e2e.py (it provides BASE, SHOTS, PASS_CMD).
import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { launch, decodePackages } from "./cdp.mjs";

const { BASE, SHOTS, PASS_CMD, PDX, FXQ } = process.env;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) fails.push(what); };

const b = await launch();
await b.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 860, deviceScaleFactor: 1, mobile: false });
const shot = async name => {
  const r = await b.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(SHOTS, name), Buffer.from(r.data, "base64"));
  console.log("shot " + name);
};
const until = async (expr, ms = 8000) => { for (let t = 0; t < ms; t += 100) { if (await b.eval(expr)) return true; await sleep(100); } return false; };
const clearLS = async key => { await b.goto(`${BASE}/blank`); await b.eval(`localStorage.removeItem(${JSON.stringify(key)})`); };
const pass = () => { const out = execSync(PASS_CMD, { env: process.env, encoding: "utf8" }); console.log(out.split("\n").filter(l => /route|WARNING|REFUSED|changed|unchanged|held/.test(l)).map(l => "  | " + l).join("\n")); return out; };
await b.initScript("try{localStorage.setItem('sdmc-review:who','Derek')}catch(e){}");

// Select chars [i, j) of the first long text node inside the n-th matching editable element.
const SELECT = `window.__sel=(q,k,i,j)=>{ const el=[...document.querySelectorAll(q)].filter(e=>e.textContent.trim().length>30)[k];
  el.scrollIntoView({block:'center'});
  const w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.data.trim().length>j?1:3}); const t=w.nextNode();
  const r=document.createRange(); r.setStart(t,i); r.setEnd(t,j); const s=getSelection(); s.removeAllRanges(); s.addRange(r);
  return t.data.slice(i,j); };`;
const fmt = async (q, k, i, j, action) => {
  await b.eval("document.getElementById('sdmcFxBar').hidden=true");
  const txt = await b.eval(`window.__sel(${JSON.stringify(q)},${k},${i},${j})`);
  check(await until("!document.getElementById('sdmcFxBar').hidden", 3000), "format bar shows for 「" + txt + "」");
  await b.eval(action);
  await sleep(150);
  return txt;
};
const FONT = v => `(()=>{const s=document.querySelector('#sdmcFxBar select'); s.value='${v}'; s.dispatchEvent(new Event('change'));})()`;
const CLICK = t => `document.querySelector('#sdmcFxBar button[title="${t}"]').click()`;
const COMMENT = text => `(()=>{document.querySelector('#sdmcFxBar button[title="添加批注"]').click();
  const p=document.getElementById('sdmcCmtPop'); p.querySelector('textarea').value=${JSON.stringify(text)}; p.querySelector('button.pri').click();})()`;

// ───── 创维 PdxFb: format + comment → 同步修改 → success toast → box applies → published → reload ─────
await b.goto(`${BASE}/${PDX}.html`);
await b.eval("localStorage.removeItem('rep-edits:skyworth-report')");
await b.goto(`${BASE}/${PDX}.html`);
check(await b.eval("window.SDMCReview&&SDMCReview.ver==='r1'"), "创维: kit loaded");
await b.eval("document.getElementById('btnEdit').click()");
const U = "#doc p[contenteditable='true']";
await b.eval(SELECT);
const t1 = await fmt(U, 0, 0, 8, FONT("hei"));
await fmt(U, 0, 0, 8, CLICK("文字颜色：红"));
await fmt(U, 0, 10, 18, CLICK("高亮：黄"));
await b.eval("document.getElementById('sdmcFxBar').hidden=true");
await b.eval(`window.__sel(${JSON.stringify(U)},1,2,12)`);
await until("!document.getElementById('sdmcFxBar').hidden", 3000);
await sleep(300);
console.log("bar", JSON.stringify(await b.eval("(()=>{const r=document.getElementById('sdmcFxBar').getBoundingClientRect(), s=getSelection().getRangeAt(0).getBoundingClientRect(); return {bar:[r.x,r.y,r.width,r.height],sel:[s.x,s.y,s.width],scroll:[scrollX,scrollY],pos:getComputedStyle(document.body).position, mt:getComputedStyle(document.body).marginTop}})()")));
await shot("review-sync-format-bar.png");
await b.eval(COMMENT("这里的口径请再确认（e2e 批注）"));
await sleep(200);
const marks = await b.eval("[document.querySelectorAll('#doc span.fx.fx-f-hei').length,document.querySelectorAll('#doc span.fx.fx-c-red').length,document.querySelectorAll('#doc mark.fx-hl-y').length,document.querySelectorAll('#doc mark.fx-cmt').length]");
check(marks.every(n => n >= 1), "创维: font/colour/highlight/comment applied in page " + JSON.stringify(marks) + " on 「" + t1 + "」");
await b.eval("document.getElementById('btnSync').click()");
check(await until("document.getElementById('sdmcToast').className==='ok'"), "创维: success toast");
check(await b.eval("window.__sdmcLastSync&&window.__sdmcLastSync.state==='ok'"), "创维: sync state ok");
await shot("review-sync-success-toast.png");
const out1 = pass();
check(/master changed/.test(out1) && !/legacy fallback/.test(out1), "创维: box routed by file token and applied");
await clearLS('rep-edits:skyworth-report');
await b.goto(`${BASE}/${PDX}.html`);
const after = await b.eval("[document.querySelectorAll('#doc span.fx.fx-f-hei').length,document.querySelectorAll('#doc span.fx.fx-c-red').length,document.querySelectorAll('#doc mark.fx-hl-y').length,document.querySelectorAll('#doc mark.fx-cmt').length]");
check(JSON.stringify(after) === JSON.stringify(marks), "创维: formatting + comment survive reload from the published copy " + JSON.stringify(after));
await b.eval("(()=>{const m=document.querySelector('#doc mark.fx-cmt'); m.scrollIntoView({block:'center'}); m.click();})()");
check(await until("!document.getElementById('sdmcBubble').hidden&&document.querySelector('#sdmcBubble .txt').textContent.includes('e2e 批注')"), "创维: comment bubble after reload");
await shot("review-sync-after-reload.png");

// ───── failure reasons ─────
const failCase = async (query, init, file, reason) => {
  if (init) await b.initScript(init);
  await b.goto(`${BASE}/${PDX}.html?${query}`);
  await b.eval("document.getElementById('btnEdit').click()");
  await b.eval(SELECT);
  await fmt(U, 2, 0, 6, CLICK("文字颜色：蓝"));
  await b.eval("document.getElementById('btnSync').click()");
  const ok = await until(`(document.getElementById('sdmcToast').className==='fail'||document.getElementById('sdmcToast').className==='warn')&&document.getElementById('sdmcToast').textContent.includes(${JSON.stringify(reason)})`, 12000);
  check(ok, "创维 " + query + ": toast 「" + reason + "」 → " + (await b.eval("document.getElementById('sdmcToast').innerText.replace(/\\n+/g,' | ')")));
  await shot(file);
  await b.eval("localStorage.removeItem('rep-edits:skyworth-report')");
};
await failCase("hook=500", "", "review-sync-fail-http500.png", "HTTP 500");
await failCase("csp=1", "", "review-sync-fail-csp.png", "安全策略");
await failCase("hook=slow", "window.SDMC_REVIEW_TIMEOUT_MS=1500;", "review-sync-fail-timeout.png", "超时");
await failCase("hook=nocors", "window.SDMC_REVIEW_TIMEOUT_MS=15000;", "review-sync-warn-no-receipt.png", "未收到回执");
pass();

// ───── 华曦达 FXqHb: v46 client now sends file → routed by token, no fallback warning ─────
await b.goto(`${BASE}/${FXQ}.html`);
await b.eval("localStorage.removeItem('huaxida_2026h1_layout_edits')");
await b.goto(`${BASE}/${FXQ}.html`);
await sleep(500);
check(await b.eval("window.SDMCReview&&SDMCReview.ver==='r1'"), "华曦达: kit loaded");
await b.eval("document.getElementById('bEdit').click()");
const H = "#sheet p[contenteditable='true']";
await b.eval(SELECT);
await fmt(H, 0, 0, 6, FONT("kai"));
await fmt(H, 0, 0, 6, CLICK("文字颜色：绿"));
await b.eval(`window.__sel(${JSON.stringify(H)},1,0,8)`);
await until("!document.getElementById('sdmcFxBar').hidden", 3000);
await b.eval(COMMENT("华曦达 e2e 批注"));
await sleep(300);
const pkgs = decodePackages(await b.eval("window.__editsText()"));
check(pkgs.length === 1 && pkgs[0].file === FXQ && pkgs[0].rep === "huaxida-h1", "华曦达: package carries file + rep");
await b.eval("document.getElementById('bSync').click()");
check(await until("document.getElementById('sdmcToast').className==='ok'"), "华曦达: success toast");
const out2 = pass();
check(/华曦达对比\] master changed/.test(out2) && !/legacy fallback/.test(out2), "华曦达: routed by file token (no fallback warning) and applied");
await clearLS('huaxida_2026h1_layout_edits');
await b.goto(`${BASE}/${FXQ}.html`);
await sleep(800);
check(!(await b.eval("!!localStorage.getItem('huaxida_2026h1_layout_edits')")), "华曦达: reload has no local draft");
const hx = await b.eval("[document.querySelectorAll('#sheet span.fx.fx-f-kai').length,document.querySelectorAll('#sheet span.fx.fx-c-green').length,document.querySelectorAll('#sheet mark.fx-cmt').length]");
check(hx.every(n => n >= 1), "华曦达: formatting + comment survive reload " + JSON.stringify(hx));
await b.eval("(()=>{const m=document.querySelector('#sheet mark.fx-cmt'); m.scrollIntoView({block:'center'}); m.click();})()");
await until("!document.getElementById('sdmcBubble').hidden");
await shot("review-sync-huaxida-after-reload.png");

check(b.errors.length === 0, "no page errors " + JSON.stringify(b.errors.slice(0, 3)));
await b.close();
console.log(fails.length ? "E2E FAILED: " + fails.length : "E2E OK");
process.exit(fails.length ? 1 : 0);
