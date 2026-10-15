# Review formatting + sync feedback — plan and MVP (2026-10-15)

Scope: the sync front end (page client), the package, and the box apply layer only. No report text, numbers or
口径 change. Same channel as today: page → webhook.site → ws_poller → relay drops → `v41/sync_watch.py` (routes by
`file` token) → `sync_pull_routed.py` (applies to the master) → `replace.py` (same link, Derek-gated).

## 0. What the two live clients do today (read from the masters)

| | 创维 PdxFb (`入稿终稿_feishu.html`, client `v1`) | 华曦达 FXqHb (`排版优化`, client `v46`) |
| --- | --- | --- |
| edit unit | every `[data-eid]` element, diff of `innerHTML` | template node per `TXT_SEL` element, diff of `innerHTML` |
| package | `{ver,rep,file,ts,ops}` | `{ver,ts,ops}` — no `file`, no `rep` |
| channel | `fetch(SYNC_WEBHOOK)` JSON (CORS preflight) | `location.origin/sync` only when relay-hosted, otherwise copy box + open inbox doc |
| feedback | small status text on success; copy box on failure | copy box only |
| local persistence | `localStorage` per eid | `localStorage` copy of the template |

Both clients already send an element's full new `innerHTML`, so inline markup inside an element travels in a normal
`edit` op and survives reload once it is in the master. Formatting therefore needs **no new op type**.

Three problems found while reading and testing (all fixed in this MVP):

1. **Box apply does not sanitize.** `clean_fragment()` only strips `<script>` and `contenteditable`; `onerror=`,
   `javascript:` links, `<iframe>` and `<style>` in an op's `new` would be written into the master and published.
2. **Router held every real 华曦达 package.** The 排版优化 client header is `【SDMC 报告同步 v46】<date>`, which does not
   contain 「华曦达」, so `title_keywords` flagged it as a conflict (with or without `file`). Fixed: a title is a
   conflict only when it names another report and not this one.
3. **Box apply lost every 华曦达 edit on reload.** The v46 page renders `#sheet` from `<template id="report-tpl">` on
   every load. The saved master's `#sheet` carries runtime `data-eid`s, while the template has none. The box matched
   the eid in the stale `#sheet` copy and never touched the template, so a refresh re-rendered the old text. This
   affected plain text edits and deletes too, not only formatting. Fixed: when a page has `#report-tpl`, the box applies
   the edit or delete to the template first, matching by canonical HTML or text without eids, and mirrors it to
   `#sheet`. It never patches only the rendered copy. Pages without a template behave exactly as before.

## 1. UI (both pages, same kit)

- **Format bar** appears above a text selection while in 修改 mode:
  - 字体: 默认 / 宋体 / 黑体 / 楷体 / 仿宋 / 等宽;
  - 颜色: 红 / 蓝 / 绿 / 橙 / 灰;
  - 高亮: 黄 / 绿 / 粉;
  - 「批注」;
  - 「清除格式」, which removes font, colour and highlight and keeps comments.
- **批注 (comments):** select text, press 「批注」, type the note and press 保存. The text gets a dotted underline and a
  small 「注」 marker. Clicking it in any mode shows the note with its author and time; in 修改 mode the bubble also
  has 「删除批注」. A 「批注 n」 button toggles comment marks on or off for that reader only (stored in
  `localStorage`). Comment marks are hidden in print. The author name is asked once and kept in `localStorage`.
- **Sync result toast**, fixed at the bottom of the page and visible in the Feishu preview:
  - 「已提交 N 处修改」 + 「写回飞书需助理确认后发布；发布后刷新本链接即可看到」. Auto-hides after 10 s.
  - 「已发出，未收到回执」 when the request left the browser but the reply was unreadable (opaque `no-cors`).
  - Failure, which stays until closed, with the reason, the 修改 count still kept in this browser, and actions
    「重试」「复制修改包」「下载改过的页面」(+「打开收件箱文档」 when configured). Reasons:
    - 设备离线;
    - 被页面安全策略拦截 (CSP, e.g. the Feishu preview);
    - 网络请求被拦截 (preview, proxy, extension);
    - 同步服务返回 HTTP xxx;
    - 超时 (15 s);
    - 同步通道未配置.

## 2. Package schema (back-compatible)

```text
SDMCSYNC1:<base64 JSON>:END
{ "ver": "<client ver>", "rep": "...", "file": "<27-char token>", "ts": "...",
  "pv": 2, "caps": ["fmt", "cmt"], "ops": [ {"op":"edit","eid":"…","old":"…","new":"…","fmt":1}, … ] }
```

- `pv` (package version) and `caps` are new and optional; old packages (no `pv`) route and apply exactly as before.
- `fmt:1` marks an edit whose visible text is unchanged (format or comment only). It is informational: the box
  applies it like any `edit`, via eid first and then canonical HTML or plain text.
- Formatting is **class-only** markup inside an element:
  - `<span class="fx fx-f-hei fx-c-red">`;
  - `<mark class="fx fx-hl fx-hl-y">`;
  - `<mark class="fx fx-cmt" data-cmt="…" data-cmt-by="…" data-cmt-at="ISO">`.

  The client writes no `style=` attribute and no `data-eid` on these elements.
- 华曦达 additionally starts sending `file` + `rep:'huaxida-h1'` (the queued FXqHb token patch).

## 3. Applying safely on the box

`sync_pull*.py` `clean_fragment()` becomes a real sanitizer for every `edit` `new` (old and new packages alike). It
re-serialises the fragment with `HTMLParser`:

- **Dropped with their content:** `script style iframe frame frameset object embed applet noscript template
  textarea select option math foreignObject portal`.
- **Dropped:** void or active tags `base link meta input button img video audio source track canvas form`.
- **Attributes:**
  - `on*`, `srcdoc`, `formaction`, `action`, `contenteditable` and `spellcheck` are dropped;
  - URL attributes (`href`, `xlink:href`, `src`, `action`, `poster`, `background`, `ping`, `data`) are kept only
    when they are `#…`, `http(s):`, `mailto:` or relative without a scheme;
  - `style` is kept only when no declaration contains `url(`, `expression`, `javascript:`, `behavior`, `binding`,
    `@import`, `\`, `<`, `>` or `position`, otherwise the attribute is dropped;
  - `data-cmt*` values are capped at 1,000 characters;
  - `data-eid` is removed from `.fx` elements, so the 华曦达 client re-stamps them per browser.
- **Text and existing markup:** text, entities, `{{tokens}}` and the report's existing inline markup are kept:
  - `b`, `span.t`, `.nd`, `.cal`, `i.dot style="background:var(--sdmc)"`;
  - `sup`, `a href="#…"`;
  - svg shapes without `<script>` or `foreignObject`.
- **Anchored path:** the anchored-substring path (plain-text splice) now always HTML-escapes text containing `<` or `>`.
- **Template first:** for `#report-tpl` pages, edits and deletes land in the template, as in §0 problem 3.

On the page, the kit renders comment text with `textContent` only, and the CSS for the `fx-*` classes ships inside the
master. No `<style>` arrives through a package.

## 4. Back-compat

- Old packages (`v1`, `v46` without `file`) still route and apply; the four real 10:24 drops are in the tests.
- The legacy fallback stays, and the router warns `routed by legacy fallback` (already shipped).
- Existing drafts in readers' browsers survive the upgrade. The kit is injected outside the 创维 `[data-eid]` units
  and outside the 华曦达 `#report-tpl`, so the 创维 per-eid hash and the 华曦达 `BASE` hash are unchanged.
- A page without the kit still works: each client hook is `if(window.SDMCReview){…; return;}` in front of the
  old code.

## 5. What gets injected into the masters (`review_kit.py upgrade`, idempotent; re-running replaces the kit)

| | PdxFb 创维 | FXqHb 华曦达 |
| --- | --- | --- |
| `<style id="sdmc-review-css">` + `<script id="sdmc-review">` before `</body>` | yes | yes |
| sync hook in the client | 1 line after `const text=pack(ops);` | 1 line after `const text=editsText(ops); window.__lastSync=text;` |
| package gains `pv`, `caps` | yes (in `pack`) | yes (in `editsText`) |
| `file` + `rep` in the package | already | added (`patch-client`) |
| `SYNC_WEBHOOK` constant | already set | added, same webhook.site URL as 创维 (inbox copy box stays as the failure fallback) |
| report text, numbers, `report-data`, `#report-tpl` | untouched (tested: identical outside the injected blocks) | untouched |

## 6. Re-publish (writer onboarding order)

Both masters change, so both need one Derek-confirmed same-link publish:

1. **PdxFb first.** It is already on the webhook channel and already sends `file`, so the change is smallest. Upgrade,
   check, publish, then Derek edits, formats and comments on PdxFb and presses 同步修改. The assistant confirms the drop
   applied and publishes again.
2. **FXqHb second**, after PdxFb passes. This also switches its channel to the webhook and starts sending `file`.
   Existing open tabs keep the old client until refreshed; their packages still route through the fallback, with a
   warning.

## 7. Defaults chosen (no blocker for Derek; easy to change later)

- Comments are visible to everyone who opens the link (that is what "travel with 同步修改" implies). Each reader can
  hide them with 「批注 n」, and they are hidden in print.
- The font list uses system font stacks, so no web fonts are loaded in the Feishu preview.
- The success toast says 「已提交」, never 「已写回」: the Derek gate still decides when Feishu is replaced.

## 8. MVP deliverables (this folder)

- `review_kit.js`, `review_kit.css`, `review_kit.py` (`upgrade` / `check`);
- the sanitizing, template-first `sync_pull_routed.py` (+ PR #3 `box/sync_pull.py`);
- `sync_routes.py` with the title fix;
- tests and `smoke_output.txt`;
- `README.md` (box upgrade + publish order + smoke steps);
- screenshots `media/review-sync-*.png`: success toast, failure toasts, and formatted/commented text after reload.
