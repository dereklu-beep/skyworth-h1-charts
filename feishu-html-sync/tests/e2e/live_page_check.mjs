// Verifies a live v46-client report after fix_live_page.py, in headless Chrome:
//   node feishu-html-sync/tests/e2e/live_page_check.mjs <fixed.html> [expected-rep]
// Checks: page script runs without errors; toolbar has「同步修改」and neither「恢复原始数据」nor「复制修改」;
// an edit + click on「同步修改」sends one SDMCSYNC1 package carrying `rep` and a `ts`.
import { launch, FETCH_SPY, decodePackages } from "./cdp.mjs";
import { resolve } from "node:path";
import assert from "node:assert/strict";

const file = process.argv[2];
const rep = process.argv[3] || "huaxida-h1";
if (!file) { console.log("usage: live_page_check.mjs <html> [rep]"); process.exit(2); }

const b = await launch();
try {
  await b.initScript(FETCH_SPY + "window.alert=()=>{};window.confirm=()=>true;");
  await b.goto("file://" + resolve(file));
  const bar = await b.eval(`[...document.querySelectorAll('header button, .bar button, .tools button, .toolbar button')].map(x=>x.textContent.trim())`);
  console.log("toolbar:", bar);
  assert.ok(bar.some(t => t.includes("同步修改")), "同步修改 missing");
  assert.ok(!bar.some(t => t.includes("恢复原始数据") || t.includes("复制修改")), "legacy buttons still present");
  await b.eval(`document.getElementById('bEdit').click()`);
  const target = await b.eval(`(()=>{const el=[...document.querySelectorAll('[contenteditable="true"]')].find(n=>n.textContent.trim().length>6&&!n.querySelector('[contenteditable]'));
    if(!el) return null; const before=el.textContent; el.textContent=before+'（e2e）'; el.dispatchEvent(new InputEvent('input',{bubbles:true})); el.dispatchEvent(new FocusEvent('focusout',{bubbles:true})); return before.slice(0,40);})()`);
  assert.ok(target, "no editable text found after clicking edit");
  await b.eval(`document.getElementById('bSync').click()`);
  await new Promise(r => setTimeout(r, 800));
  const sent = await b.eval(`window.__sent`);
  const pk = sent.flatMap(s => decodePackages(typeof s.body === "string" ? s.body : ""));
  assert.ok(pk.length >= 1, "no package sent: " + JSON.stringify(sent).slice(0, 300));
  assert.equal(pk[0].rep, rep);
  assert.ok(pk[0].ts, "package without ts");
  assert.ok(pk[0].ops.length >= 1);
  assert.deepEqual(b.errors, [], "page errors: " + b.errors.join(" | "));
  console.log("OK live page:", { edited: target, sentTo: sent.map(s => s.url), rep: pk[0].rep, ops: pk[0].ops.length });
} finally {
  await b.close();
}
