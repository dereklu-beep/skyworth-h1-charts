// Browser half of template_e2e.py. argv: <relay base url> <temp box dir>
import { launch, FETCH_SPY, decodePackages } from "./cdp.mjs";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import assert from "node:assert/strict";

const [base, dir] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const read = p => readFileSync(join(dir, p), "utf8");
const step = (name) => console.log("✓", name);

async function waitFor(b, expr, ms = 20000) {
  const t0 = Date.now();
  for (;;) {
    const v = await b.eval(expr);
    if (v) return v;
    if (Date.now() - t0 > ms) throw new Error("timeout waiting for " + expr + " — panel: " + await b.eval(`document.querySelector('#syncBox .sb-m')?.textContent`));
    await sleep(250);
  }
}

const editCell = (b, sel, text) => b.eval(`(()=>{const el=${sel}; el.focus(); el.textContent=${JSON.stringify(text)};
  el.dispatchEvent(new InputEvent('input',{bubbles:true})); return el.dataset.eid;})()`);

const b = await launch();
try {
  // spy only on the fetches we want to inspect; everything else goes to the real relay
  await b.initScript(FETCH_SPY + "window.__passthrough=()=>true;");

  await b.goto(base + "/r/huaxida-h1");
  const bar = await b.eval(`[...document.querySelectorAll('.tools button')].map(x=>x.hidden?'('+x.textContent.trim()+')':x.textContent.trim())`);
  assert.deepEqual(bar, ["修改", "(同步修改)", "打印"]);
  step("toolbar: 修改 / 同步修改 (hidden until there is something to sync) / 打印 — no 恢复原始数据 / 复制修改");

  await b.eval(`document.getElementById('btnEdit').click()`);
  // the second "9.8" cell and the second "同上。" are textual duplicates: only context can place them
  await editCell(b, `document.querySelectorAll('tbody tr')[1].cells[1]`, "10.4");
  await editCell(b, `[...document.querySelectorAll('#doc > p')].filter(p=>p.textContent==='同上。')[1]`, "同上（风险段）。");
  // filter/sort must keep working while editing
  const filt = await b.eval(`(()=>{const i=document.querySelector('.tbl-tools input'); if(!i) return 'no-filter';
    i.value='TIM'; i.dispatchEvent(new Event('input',{bubbles:true})); const vis=[...document.querySelectorAll('tbody tr')].filter(r=>!r.hidden).length;
    i.value=''; i.dispatchEvent(new Event('input',{bubbles:true})); return vis;})()`);
  assert.equal(filt, 1, "table filter broken by edit");
  step("edited duplicate cell + duplicate paragraph; table filter still works (" + filt + ")");

  await b.eval(`document.getElementById('btnSync').click()`);
  const done = await waitFor(b, `(()=>{const m=document.querySelector('#syncBox');return m&&['feishu','gated','feishu_error','unresolved','held','nochange'].includes(m.dataset.stage)&&m.dataset.stage+' | '+m.querySelector('.sb-m').textContent;})()`);
  console.log("  panel:", done);
  assert.match(done, /^gated/, "test box keeps the group gate closed: master patched, Feishu untouched");
  const sent = (await b.eval(`window.__sent`)).filter(s => s.url.endsWith("/sync"));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, base + "/sync", "page served by relay must post same-origin");
  assert.equal(sent[0].ctype, "text/plain;charset=UTF-8");
  const pk = decodePackages(sent[0].body)[0];
  assert.equal(pk.rep, "huaxida-h1");
  assert.ok(pk.id && pk.ts && pk.ops.length === 2);
  const cellOp = pk.ops.find(o => o.new === "10.4");
  assert.equal(cellOp.row, "TIM"); assert.equal(cellOp.col, 1); assert.equal(cellOp.sid, "s-rev");
  const pOp = pk.ops.find(o => o.new.includes("风险段"));
  assert.equal(pOp.sid, "s-risk");
  step("one same-origin text/plain POST; package has rep/id/ts/rev + row/col/sid context");

  const master = read("hx/master.html");
  const has = (re, what) => assert.ok(re.test(master), what + " — master excerpt: " + master.slice(master.indexOf('id="doc"'), master.indexOf('id="doc"') + 900));
  has(/<td[^>]*>Claro<\/td><td[^>]*>9\.8<\/td>/, "Claro 9.8 untouched");
  has(/<td[^>]*>TIM<\/td><td[^>]*>10\.4<\/td>/, "TIM → 10.4");
  has(/<h2 id="s-rev"[^>]*>[\s\S]*<p[^>]*>同上。<\/p>[\s\S]*<h2 id="s-risk"[^>]*>[\s\S]*<p[^>]*>同上（风险段）。<\/p>/, "second 同上 edited, first kept");
  has(/<meta name="sync-rev" content="[0-9a-f]{12}">/, "sync-rev set");
  assert.equal(read("sw/master.html").includes("10.4"), false);
  assert.equal(read("relay/hosted/hx.html"), master, "hosted Chrome copy republished");
  step("master patched surgically (right duplicate each time), sync-rev set, hosted copy republished, 创维 untouched");

  // reload: page now carries the new rev and stable eids; a draft survives a reload without syncing
  await b.goto(base + "/r/huaxida-h1");
  const rev = await b.eval(`document.querySelector('meta[name=sync-rev]').content`);
  assert.equal(rev, master.match(/sync-rev" content="([0-9a-f]{12})"/)[1]);
  await b.eval(`document.getElementById('btnEdit').click()`);
  await editCell(b, `[...document.querySelectorAll('li')].find(l=>l.textContent==='客户集中。')`, "客户集中（前五大 61%）。");
  await sleep(800);
  await b.goto(base + "/r/huaxida-h1");
  const restored = await b.eval(`[...document.querySelectorAll('li')].map(l=>l.textContent)`);
  assert.ok(restored.includes("客户集中（前五大 61%）。"), "draft not restored: " + restored);
  assert.equal(await b.eval(`!document.getElementById('btnSync').hidden`), true);
  step("unsynced edit kept in the browser and restored after reload; 同步修改 visible");

  // download of the edited page
  const dl = await b.eval(`(()=>{const d=new DOMParser().parseFromString(window.__report.serialize(),'text/html');
    return {edit:[...d.querySelectorAll('li')].some(l=>l.textContent==='客户集中（前五大 61%）。'),ce:d.querySelectorAll('[contenteditable]').length,
      rt:d.querySelectorAll('[data-rt],#syncBox').length,sync:d.getElementById('btnSync').hidden,ids:[...d.querySelectorAll('#doc > h2')].map(h=>h.id)};})()`);
  assert.deepEqual(dl, { edit: true, ce: 0, rt: 0, sync: true, ids: ["s-rev", "s-risk"] });
  step("download serialises the edited page cleanly");

  // a page without a report id is held on the box, never applied anywhere
  await b.goto(base + "/r/unlabelled");
  await b.eval(`document.getElementById('btnEdit').click()`);
  await editCell(b, `document.querySelectorAll('tbody tr')[0].cells[1]`, "99.9");
  await b.eval(`document.getElementById('btnSync').click()`);
  const held = await waitFor(b, `(()=>{const m=document.querySelector('#syncBox');return m&&m.dataset.stage==='held'&&m.querySelector('.sb-m').textContent;})()`);
  console.log("  panel:", held);
  assert.equal(read("hx/master.html").includes("99.9"), false);
  assert.equal(read("sw/master.html").includes("99.9"), false);
  assert.ok(existsSync(join(dir, "relay/held")) && readdirSync(join(dir, "relay/held")).length >= 1);
  step("package without rep → held, shown as held in the page, no master touched");

  assert.deepEqual(b.errors, [], "page errors: " + b.errors.join(" | "));
  console.log("OK template e2e");
} finally {
  await b.close();
}
