// Acceptance render check: node check_render.mjs REPORT.html [shotDir]
// Launches headless Chrome, renders at 1440px and 390px, toggles edit mode,
// and prints a JSON verdict (script errors, toolbar, overflow, leftovers).
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const file = path.resolve(process.argv[2]);
const shotDir = process.argv[3];
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu',
  `--remote-debugging-port=${port}`, '--user-data-dir=/tmp/cr-' + port, 'about:blank'], { stdio: 'ignore' });

let ws, seq = 0;
const pending = new Map(), errors = [];
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result.value;
};

const PROBE = `(() => {
  const vis = el => el && !el.hidden && getComputedStyle(el).display !== 'none' && el.offsetParent !== null;
  const tb = document.querySelector('.toolbar');
  const buttons = [...(tb ? tb.querySelectorAll('button') : [])].filter(vis).map(b => b.textContent.trim());
  const sheet = document.getElementById('sheet');
  const text = sheet ? sheet.innerText : '';
  const over = [...document.querySelectorAll('#sheet .tscroll')].filter(w => w.scrollWidth > w.clientWidth + 2)
    .map(w => (w.querySelector('table') || {}).id || '?');
  const duo = document.querySelector('#sheet .duo');
  return {
    buttons,
    pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    tableOverflow: over,
    duoLayout: duo ? getComputedStyle(duo).display : null,
    placeholders: (text.match(/\\{\\{/g) || []).length,
    has664: text.includes('6.64%'),
    qianTongshi: [...document.querySelectorAll('#sheet td, #sheet th')].filter(td => /前同事|共事/.test(td.textContent)).map(td => td.textContent.trim()),
    textLen: text.length,
  };
})()`;

try {
  let target;
  for (let i = 0; i < 50 && !target; i++) {
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page'); }
    catch { await sleep(200); }
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map(a => a.value ?? a.description).join(' '));
  });
  await send('Runtime.enable'); await send('Page.enable');
  const out = { file, errors };
  for (const [name, width] of [['desktop', 1440], ['laptop', 1280], ['phone', 390]]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 500 });
    await send('Page.navigate', { url: 'file://' + file });
    await sleep(3500);
    out[name] = await evaluate(PROBE);
    await evaluate(`document.getElementById('bEdit').click()`); await sleep(400);
    out[name].editButtons = (await evaluate(PROBE)).buttons;
    out[name].editable = await evaluate(`document.querySelectorAll('#sheet [contenteditable="true"]').length`);
    if (shotDir) {
      mkdirSync(shotDir, { recursive: true });
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(path.join(shotDir, `${name}_edit.png`), Buffer.from(shot.data, 'base64'));
    }
    await evaluate(`document.getElementById('bEdit').click()`);
  }
  try {
  // persistence: edit one paragraph, reload, expect it restored and still counted as a sync edit
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await evaluate(`localStorage.clear()`);
  await send('Page.navigate', { url: 'file://' + file }); await sleep(3000);
  await evaluate(`(() => { document.getElementById('bEdit').click();
    const el = [...document.querySelectorAll('#sheet [contenteditable="true"]')].find(n => n.textContent.includes('接下来看什么'));
    el.innerHTML = el.innerHTML.replace('接下来看什么', '接下来要看'); el.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('bEdit').click(); })()`);
  await send('Page.navigate', { url: 'file://' + file }); await sleep(3000);
  out.persist = await evaluate(`({ restored: window.__restoredLocal, text: document.getElementById('sheet').innerText.includes('接下来要看'),
    ops: window.__collectEdits().map(o => o.op) })`);
  if (shotDir) {
    await send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: path.resolve(shotDir) });
    await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true, bubbles: true }))`);
    await sleep(1500);
    out.download = (await import('node:fs')).readdirSync(shotDir).filter(f => f.endsWith('.html'));
  }
  await evaluate(`localStorage.clear()`);
  } catch (e) { out.persistError = String(e.message || e).slice(0, 300); }
  console.log(JSON.stringify(out, null, 1));
} finally {
  try { ws && ws.close(); } catch {}
  chrome.kill('SIGKILL');
  process.exit(0);
}
