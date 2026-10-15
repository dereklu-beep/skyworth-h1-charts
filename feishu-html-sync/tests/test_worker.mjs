// node --test feishu-html-sync/tests/test_worker.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../edge/worker.js";

class KV {
  constructor() { this.m = new Map(); }
  async get(k, type) { const v = this.m.get(k); return v == null ? null : type === "json" ? JSON.parse(v) : v; }
  async put(k, v) { this.m.set(k, String(v)); }
  async delete(k) { this.m.delete(k); }
  async list({ prefix, limit }) { return { keys: [...this.m.keys()].filter(k => k.startsWith(prefix)).sort().slice(0, limit).map(name => ({ name })) }; }
}
const env = () => ({ SYNC: new KV(), ADMIN_TOKEN: "adm", DEFAULT_SLUG: "huaxida-h1", ALLOWED_ORIGINS: "null,https://*.feishu.cn" });
const B = "https://sdmc-sync.example.workers.dev";
const pkg = o => "SDMCSYNC1:" + Buffer.from(JSON.stringify(o)).toString("base64") + ":END";
const call = (e, path, init = {}) => worker.fetch(new Request(B + path, init), e);
const adm = { Authorization: "Bearer adm" };

test("report is served as a page, publish needs admin", async () => {
  const e = env();
  assert.equal((await call(e, "/api/report/huaxida-h1", { method: "PUT", body: "<p>x</p>" })).status, 401);
  assert.equal((await call(e, "/api/report/huaxida-h1", { method: "PUT", body: "<p>x</p>", headers: { ...adm, "X-Sync-Rev": "r1" } })).status, 200);
  const r = await call(e, "/r/huaxida-h1");
  assert.equal(r.status, 200);
  assert.match(r.headers.get("Content-Type"), /text\/html/);
  assert.equal(r.headers.get("Content-Disposition"), null);
  assert.equal(await r.text(), "<p>x</p>");
  assert.deepEqual(await (await call(e, "/rev/huaxida-h1")).json(), { rev: "r1" });
  assert.equal((await call(e, "/")).headers.get("Location"), B + "/r/huaxida-h1");
});

test("view key gates the page and is remembered by cookie", async () => {
  const e = { ...env(), VIEW_KEY: "vk1" };
  await call(e, "/api/report/huaxida-h1", { method: "PUT", body: "ok", headers: adm });
  assert.equal((await call(e, "/r/huaxida-h1")).status, 403);
  const r = await call(e, "/r/huaxida-h1?k=vk1");
  assert.equal(r.status, 200);
  assert.match(r.headers.get("Set-Cookie"), /vk=vk1/);
  assert.equal((await call(e, "/r/huaxida-h1", { headers: { Cookie: "vk=vk1" } })).status, 200);
});

test("sync queue → box poll → ack, status JSONP", async () => {
  const e = env();
  const text = pkg({ ver: "v2", rep: "skyworth-report", id: "abc", ts: "t", ops: [{ op: "edit" }] });
  const r = await call(e, "/sync", { method: "POST", body: text, headers: { "Content-Type": "text/plain", Origin: "null" } });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), "null");
  assert.deepEqual((await r.json()).ids, ["abc"]);
  const evil = await call(e, "/sync", { method: "POST", body: text, headers: { Origin: "https://evil.example" } });
  assert.equal(evil.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal((await call(e, "/api/queue")).status, 401);
  const q = await (await call(e, "/api/queue", { headers: adm })).json();
  assert.equal(q.items.length, 2);
  assert.equal(q.items[0].text, text);
  await call(e, "/api/ack", { method: "POST", body: JSON.stringify({ keys: q.items.map(i => i.key) }), headers: adm });
  assert.equal((await (await call(e, "/api/queue", { headers: adm })).json()).items.length, 0);
  await call(e, "/api/status/abc", { method: "POST", body: JSON.stringify({ stage: "feishu", applied: 1 }), headers: adm });
  const js = await (await call(e, "/status/abc?cb=__s")).text();
  assert.equal(js, '/**/__s({"stage":"feishu","applied":1});');
  assert.equal((await call(e, "/status/abc?cb=alert(1)")).headers.get("Content-Type"), "application/json; charset=utf-8");
});

test("rejects non-packages and oauth code is one-shot", async () => {
  const e = env();
  assert.equal((await call(e, "/sync", { method: "POST", body: "hello" })).status, 400);
  await call(e, "/oauth/callback?code=C1&state=sync");
  assert.deepEqual(Object.keys(await (await call(e, "/api/oauth", { headers: adm })).json()).sort(), ["at", "code"]);
  assert.deepEqual(await (await call(e, "/api/oauth", { headers: adm })).json(), {});
});
