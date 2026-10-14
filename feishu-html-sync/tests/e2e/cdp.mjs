// Minimal Chrome DevTools Protocol driver (Node 22 global WebSocket, no npm deps).
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME || ["/usr/local/bin/google-chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"].find(existsSync);
const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function launch() {
  const dir = mkdtempSync(join(tmpdir(), "cdp-"));
  const proc = spawn(CHROME, ["--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run", "--remote-debugging-port=0",
    "--user-data-dir=" + dir, "about:blank"], { stdio: "ignore" });
  let port;
  for (let i = 0; i < 100 && !port; i++) {
    await sleep(100);
    try { port = readFileSync(join(dir, "DevToolsActivePort"), "utf8").split("\n")[0]; } catch (e) { /* not yet */ }
  }
  if (!port) throw new Error("chrome did not start");
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find(t => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let seq = 0;
  const pending = new Map(), listeners = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
    else if (m.method) listeners.forEach(fn => fn(m));
  };
  const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
  const errors = [];
  listeners.push(m => {
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map(a => a.value ?? a.description).join(" "));
  });
  await send("Page.enable");
  await send("Runtime.enable");
  const api = {
    send, errors,
    async goto(url) {
      const loaded = new Promise(r => { const fn = m => { if (m.method === "Page.loadEventFired") { listeners.splice(listeners.indexOf(fn), 1); r(); } }; listeners.push(fn); });
      await send("Page.navigate", { url });
      await loaded;
      await sleep(300);
    },
    async eval(expr) {
      const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error("eval failed: " + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
      return r.result.value;
    },
    async initScript(src) { await send("Page.addScriptToEvaluateOnNewDocument", { source: src }); },
    async close() { try { ws.close(); } catch (e) { /* ignore */ } proc.kill("SIGKILL"); await sleep(200); rmSync(dir, { recursive: true, force: true }); },
  };
  return api;
}

// Records every fetch()/sendBeacon so tests can inspect what the page would send.
export const FETCH_SPY = `
window.__sent=[];
const __f=window.fetch;
window.fetch=function(u,o){ window.__sent.push({url:String(u),mode:(o||{}).mode,body:(o||{}).body,ctype:((o||{}).headers||{})['Content-Type']});
  if(window.__passthrough&&window.__passthrough(String(u))) return __f.apply(this,arguments);
  return Promise.resolve(new Response(JSON.stringify({ok:true}),{status:200,headers:{'Content-Type':'application/json'}})); };`;

export function decodePackages(text) {
  return [...String(text).matchAll(/SDMCSYNC1:([A-Za-z0-9+/=\s]+?):END/g)].map(m => JSON.parse(Buffer.from(m[1].replace(/\s/g, ""), "base64").toString("utf8")));
}
