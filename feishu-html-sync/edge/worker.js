// Cloudflare Worker: durable public front for the editable reports.
//   GET  /r/<slug>          the report as a normal web page (no interstitial, never an attachment)
//   POST /sync              queue an SDMCSYNC1 package (same-origin from /r/<slug>; CORS allowlist otherwise)
//   GET  /status/<id>       apply status pushed by the box (JSON, or JSONP with ?cb=)
//   GET  /rev/<slug>        current master sync-rev
//   GET  /oauth/callback    one-time Feishu user authorisation: stores the code for the box to collect
//   admin (Authorization: Bearer ADMIN_TOKEN), called only by the box over outbound HTTPS:
//   GET /api/queue · POST /api/ack · PUT /api/report/<slug> · POST /api/status/<id> · GET /api/oauth
// Bindings: KV namespace SYNC; secrets ADMIN_TOKEN, optional VIEW_KEY; vars DEFAULT_SLUG, ALLOWED_ORIGINS.

const MAX_SYNC = 2_000_000;
const TTL = 14 * 86400;
const PKG_RE = /SDMCSYNC1:([A-Za-z0-9+/=\s]+?):END/g;
const CB_RE = /^[A-Za-z_$][\w$.]{0,63}$/;
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

function originAllowed(origin, env) {
  if (!origin) return false;
  const list = (env.ALLOWED_ORIGINS || "*").split(",").map(s => s.trim()).filter(Boolean);
  return list.some(p => p === "*" || p === origin ||
    (p.includes("*") && new RegExp("^" + p.split("*").map(x => x.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join("[A-Za-z0-9.-]+") + "$").test(origin)));
}

function cors(req, env, h = new Headers()) {
  const o = req.headers.get("Origin");
  if (originAllowed(o, env)) {
    h.set("Access-Control-Allow-Origin", o);
    h.set("Vary", "Origin");
    h.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    h.set("Access-Control-Allow-Headers", "content-type");
    h.set("Access-Control-Max-Age", "600");
  }
  return h;
}

function json(req, env, obj, status = 200, cb = "") {
  const h = cors(req, env);
  h.set("Cache-Control", "no-store");
  if (cb && CB_RE.test(cb)) {
    h.set("Content-Type", "application/javascript; charset=utf-8");
    return new Response(`/**/${cb}(${JSON.stringify(obj)});`, { status, headers: h });
  }
  h.set("Content-Type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(obj), { status, headers: h });
}

function admin(req, env) {
  const a = req.headers.get("Authorization") || "";
  return !!env.ADMIN_TOKEN && a === "Bearer " + env.ADMIN_TOKEN;
}

function pkgIds(text) {
  const ids = [];
  for (const m of text.matchAll(PKG_RE)) {
    try {
      const raw = m[1].replace(/\s/g, "");
      const p = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(raw), c => c.charCodeAt(0))));
      if (p && (p.id || p.ts)) ids.push(String(p.id || p.ts).replace(/[^A-Za-z0-9_.-]/g, "_"));
    } catch (e) { /* undecodable packages are still queued; the box decides */ }
  }
  return ids;
}

function extractText(raw) {
  try {
    const j = JSON.parse(raw);
    if (typeof j.text === "string") return j.text;
    if (j.content && typeof j.content.text === "string") return j.content.text;
  } catch (e) { /* raw text/plain body */ }
  return raw;
}

function cookie(req, name) {
  const m = (req.headers.get("Cookie") || "").match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[1]) : "";
}

async function serveReport(req, env, slug, url) {
  if (!SLUG_RE.test(slug)) return new Response("not found", { status: 404 });
  const h = new Headers({ "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store, max-age=0",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex" });
  if (env.VIEW_KEY) {
    const k = url.searchParams.get("k");
    if (k === env.VIEW_KEY) {
      h.set("Set-Cookie", `vk=${encodeURIComponent(k)}; Path=/; Max-Age=31536000; Secure; HttpOnly; SameSite=Lax`);
    } else if (cookie(req, "vk") !== env.VIEW_KEY) {
      return new Response("需要访问密钥：请从飞书入口文档里的链接打开。", { status: 403, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
  }
  const html = await env.SYNC.get("html:" + slug);
  if (html == null) return new Response("报告还没有发布到这里（box 尚未 PUT /api/report/" + slug + "）", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  return new Response(html, { headers: h });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    const cb = url.searchParams.get("cb") || "";

    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req, env) });

    if (req.method === "GET") {
      if (p === "/") return Response.redirect(url.origin + "/r/" + (env.DEFAULT_SLUG || "huaxida-h1") + url.search, 302);
      if (p.startsWith("/r/")) return serveReport(req, env, p.slice(3).replace(/\/$/, ""), url);
      if (p === "/health") return json(req, env, { ok: true, service: "sdmc-edge" });
      if (p.startsWith("/status/")) {
        const st = await env.SYNC.get("st:" + p.slice(8), "json");
        return json(req, env, st || { stage: "unknown" }, st ? 200 : 404, cb);
      }
      if (p.startsWith("/rev/")) return json(req, env, { rev: (await env.SYNC.get("rev:" + p.slice(5))) || "" }, 200, cb);
      if (p === "/oauth/callback") {
        const code = url.searchParams.get("code") || "";
        if (!code) return new Response("missing code", { status: 400 });
        await env.SYNC.put("oauth:code", JSON.stringify({ code, at: new Date().toISOString() }), { expirationTtl: 600 });
        return new Response("<!doctype html><meta charset=utf-8><p>飞书授权已收到，box 会在一分钟内完成登记。可以关闭此页。</p>",
          { headers: { "Content-Type": "text/html; charset=utf-8" } });
      }
      if (p === "/api/queue") {
        if (!admin(req, env)) return json(req, env, { error: "unauthorised" }, 401);
        const list = await env.SYNC.list({ prefix: "q:", limit: 50 });
        const items = [];
        for (const k of list.keys) {
          const v = await env.SYNC.get(k.name, "json");
          if (v) items.push({ key: k.name, text: v.text, recv_ts: v.recv_ts, origin: v.origin });
        }
        return json(req, env, { items });
      }
      if (p === "/api/oauth") {
        if (!admin(req, env)) return json(req, env, { error: "unauthorised" }, 401);
        const v = await env.SYNC.get("oauth:code", "json");
        if (v) await env.SYNC.delete("oauth:code");
        return json(req, env, v || {});
      }
      return new Response("not found", { status: 404 });
    }

    if (req.method === "POST" && p === "/sync") {
      const raw = await req.text();
      if (raw.length > MAX_SYNC) return json(req, env, { error: "too big" }, 413);
      const text = extractText(raw);
      if (!text.includes("SDMCSYNC1:")) return json(req, env, { error: "no SDMCSYNC1 package" }, 400);
      const recv_ts = new Date().toISOString();
      const key = "q:" + recv_ts + ":" + crypto.randomUUID();
      await env.SYNC.put(key, JSON.stringify({ text, recv_ts, origin: req.headers.get("Origin") || "" }), { expirationTtl: TTL });
      const ids = pkgIds(text);
      for (const id of ids) {
        if (!(await env.SYNC.get("st:" + id))) {
          await env.SYNC.put("st:" + id, JSON.stringify({ id, stage: "queued", recv_ts }), { expirationTtl: TTL });
        }
      }
      return json(req, env, { ok: true, ids, recv_ts });
    }

    if (!admin(req, env)) return json(req, env, { error: "unauthorised" }, 401);
    if (req.method === "POST" && p === "/api/ack") {
      const { keys = [] } = await req.json();
      for (const k of keys) if (String(k).startsWith("q:")) await env.SYNC.delete(k);
      return json(req, env, { ok: true, acked: keys.length });
    }
    if (req.method === "PUT" && p.startsWith("/api/report/")) {
      const slug = p.slice(12);
      if (!SLUG_RE.test(slug)) return json(req, env, { error: "bad slug" }, 400);
      await env.SYNC.put("html:" + slug, await req.text());
      await env.SYNC.put("rev:" + slug, req.headers.get("X-Sync-Rev") || "");
      return json(req, env, { ok: true, slug });
    }
    if (req.method === "POST" && p.startsWith("/api/status/")) {
      const id = p.slice(12).replace(/[^A-Za-z0-9_.-]/g, "_");
      await env.SYNC.put("st:" + id, JSON.stringify(await req.json()), { expirationTtl: TTL });
      return json(req, env, { ok: true });
    }
    return new Response("not found", { status: 404 });
  },
};
