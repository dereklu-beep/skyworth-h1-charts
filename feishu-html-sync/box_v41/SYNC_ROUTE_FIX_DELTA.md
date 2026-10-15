# SYNC_ROUTE_FIX_DELTA — 2026-10-15 misroute fix (box v41)

## 1. Root cause (confirmed against the box files)

- Box `v41/sync_watch.py` (md5 `05f17b18f23050660a03df9082bc9da1`) hard-codes
  `TARGET = v71_std/华曦达vs创维财报对比_v71_可编辑.html` and `MASTER = 'FXqHbFI37oGOCyxT3NkcVhjnnRg'`.
  It never reads the package's `file` token, so every drop from every report goes to 华曦达.
- The four 10:24 CST drops are 创维 packages (`file: PdxFb…`, `rep: skyworth-report`, op `edit s-cover.1`).
  `sync_watch.log` lines 5558–5573: ops not found in v71 (`False`), yet the old `sync_pull.py` printed
  `applied -> … bytes 302514 -> 302514` and the watcher ran
  `replace.py FXqHb… v71_std/…_v71_可编辑.html` **twice** (02:24:38Z and 02:24:50Z). That is the 577,426 → 302,514
  byte overwrite of FXqHb (rolled back by the assistant at 10:33 CST from `_live_check_1023/FXqHb.html`, md5 `1b1e3c34`).
- PdxFb was never replaced and no 创维 master received the edit, so Derek's edit was gone after refresh.

## 2. Changed files (all in `sync_route_fix_20261015/`)

| File | What |
| --- | --- |
| `sync_watch.py` | router: package `file` → route → that route's master; held queue; md5 change check; Derek gate; pre-replace guard; last-good + rollback; `--publish` (diff vs box: `sync_watch.py.diff`) |
| `sync_routes.py` | routes loader, resolver, `check` validator, `inject-token` |
| `sync_routes.json` | external routing table (seed below) |
| `sync_pull_routed.py` | PR #3 `sync_pull.py` verbatim (prints `applied` only when the file really changed); run per route with its own state dir |
| `install.sh`, `README.md` | box install, exact commands |
| `test_sync_routes.py`, `smoke_output.txt`, `fixtures/` | smoke with the four real drops |

No report analysis content is changed. The only edit to a report file is the sync constants line of the 创维 copy.

## 3. Routing table (`v41/sync_routes.json`)

| token | label | rep / title check | master | derek_confirmed |
| --- | --- | --- | --- | --- |
| `PdxFbDlbDorRAexT1hRcpHuCnBf` | 创维数字专报 | `skyworth-report` / 创维数字 | `skyworth_report/opus_final_20261014/创维数字专报_入稿终稿_feishu.html` | false |
| `FXqHbFI37oGOCyxT3NkcVhjnnRg` | 华曦达对比 | — / 华曦达; accepts token-less `v46` packages | `huaxida_report/华曦达对比_排版优化_feishu.html` (copy of live FXqHb, md5 `1b1e3c34`; **not** v71_std) | false |

Unknown token, missing token (other than the listed legacy client), or a rep/title that contradicts the token:
package is kept in `v41/sync_held/` (first line `REASON: …`) with a warning in the log; nothing is applied or replaced.
There is no default route — `sync_watch.py` contains no token and no master path (a test enforces this).

## 4. Pre-replace guard, last-good backup, rollback

Every Feishu replace (loop, `--publish`) goes through one function and is refused (exit 3, `REFUSED replace …`) when:

1. the master's `SAVE_FILE_TOKEN` is not exactly the target token (no override), or
2. the new file is more than 30 % smaller than the last good published copy (`v41/sync_routed/<token>/last_good.html`).
   Override for one run: `--allow-shrink`; threshold: env `SYNC_MAX_SHRINK` (default `0.30`).

A replace runs only if the master md5 actually changed during this pass and the route has `derek_confirmed: true`.
After a successful replace the previous last-good is archived to `sync_routed/<token>/backups/good_<ts>_<md5>.html`
and the published file becomes the new last-good. Rollback is one command:

```bash
python3 v41/sync_watch.py --rollback FXqHbFI37oGOCyxT3NkcVhjnnRg
```

It same-link replaces the token with the newest archived good copy (token check still applies) and prints the `cp`
to restore the local master if wanted. `install.sh` seeds last-good from `_live_check_1023/<token-prefix>.html`
(FXqHb.html present; PdxFb.html: save the current live copy there before install, otherwise the PdxFb shrink guard
and rollback arm only after the first replace).

## 5. How `--force-replace` behaves under the new router

- Old: in `--loop`, `--force-replace` meant "after any pass that printed `applied`, replace FXqHb with v71_std".
- New: `--force-replace` only allows the loop to replace at all (without it the loop applies locally and never
  writes Feishu). A replace still needs **all** of: package routed to that token, that master's md5 changed,
  `derek_confirmed: true` on that route, and the guard in §4. It can never replace a token other than the one the
  package carries, never replace FXqHb because of a 创维 package, and never publish a file more than 30 % smaller
  without `--allow-shrink`. One-shot runs (no `--loop`) behave the same; `--no-replace` turns replace off.

## 6. Smoke results (`smoke_output.txt`, fake `replace.py`, no Feishu)

12/12 router tests pass with the real masters (store artifacts) and with synthetic ones; full repo suite 72/72.

| Check | Result |
| --- | --- |
| inject-token | `入稿终稿` `d571a690…` → `_feishu.html` `fa844dc9…` (1 line: SAVE_FILE_TOKEN, SYNC_WEBHOOK; md5 on box differs with the real webhook URL) |
| four real 10:24 drops, gate closed | 创维 master `fa844dc9…` → `394f83ce…` (`s-cover.1` edit applied); 0 replace; FXqHb master `1b1e3c34…` unchanged; replay idempotent |
| after `derek_confirmed` | replace calls = `[(PdxFb, 创维 master)]` only |
| v46 华曦达 edit | 华曦达 master `1b1e3c34…` → `a8944e6e…`; replace calls = `[FXqHb]`; 创维 master unchanged |
| unknown / missing / rep-conflict / title-conflict token | 4 held, 0 replace, both masters unchanged |
| shrink guard | 66 % shrink refused (rc 3); `--allow-shrink` replaced; `--rollback` restored the seeded copy |
| token mismatch | refused even with `--allow-shrink` |
| `install.sh` on a simulated box | md5 checks, 创维 master built, FXqHb last-good `1b1e3c34` (577,426 B), 4 drops → 创维 only, 华曦达 unchanged, `--publish` gated → after confirm replaces PdxFb once (`394f83ce…`, 172,797 B), old drops not re-sent |
| validator | bad token format, missing master, relative path, missing label, token/rep mismatch, duplicate token, no SAVE_FILE_TOKEN → errors; CLI exit 0 / 1 |

## 7. 给新报告加一行路由

1. Give the new master its Feishu token (sync constants only, content untouched):

   ```bash
   python3 v41/sync_routes.py inject-token 新报告.html 新报告_feishu.html <27位file_token> --webhook https://webhook.site/<token>
   ```

2. Add one object to `"routes"` in `v41/sync_routes.json`:

   ```json
   {"token": "<27位file_token>", "label": "新报告名", "rep": "<meta report-name>", "title_keywords": ["标题关键词"], "master": "/workspace/sdmc_skyworth/.../新报告_feishu.html", "derek_confirmed": false}
   ```

3. Validate (exit 0 = OK; it checks token format, master exists, master SAVE_FILE_TOKEN = route token, rep):

   ```bash
   python3 v41/sync_routes.py check
   ```

4. Seed the guard with the current live copy: `python3 v41/sync_watch.py --seed-last-good <token> <live.html>`.
   Set `derek_confirmed: true` only after Derek confirms. No code change, no restart needed (routes are re-read every pass).

## 8. Derek operating path

Open the report from its own Feishu link → 修改 → edit → 同步修改. The page sends a package carrying its own
`file` token; the box applies it to that report's master and, once the route is confirmed, same-link replaces that
same link. Refresh the Feishu file a minute later to see the edit. If the Feishu preview blocks the page's network
call, use 「下载改过的页面」 or open the file in Chrome and press 同步修改 there — routing is identical.

## 9. Optional follow-up: FXqHb `file` token patch + fallback warning (separate step)

Not part of the install above. The box E2E showed the live 华曦达 v46 page sends packages **without** `file`, so they
route only by the legacy title/version fallback. Two small changes, no report content change:

1. **Router warning (code only, safe to install any time).** `sync_watch.py` prints
   `WARNING routed by legacy fallback, package has no file token (ver …, title …) → <label> (<token>); patch that client: sync_routes.py patch-client`
   for every package routed without `file`. Routing behaviour is unchanged. Also in this step:
   - `sync_routes.py` title check: a title is a conflict only when it names another route's keyword and none of this
     route's. The real v46 header `【SDMC 报告同步 v46】<date>` was being held before this fix.
   - `sync_pull_routed.py` applies v46 edits/deletes to `<template id="report-tpl">` first and mirrors them to `#sheet`.
     Before this fix, an applied edit landed only in the stale rendered copy and was lost on refresh.
2. **Token-only patch of the FXqHb master, applied with the next Derek-confirmed publish:**

   ```bash
   HX=/workspace/sdmc_skyworth/huaxida_report/华曦达对比_排版优化_feishu.html
   python3 v41/sync_routes.py patch-client "$HX" FXqHbFI37oGOCyxT3NkcVhjnnRg --rep huaxida-h1   # backup "$HX".pre_client_<ts>
   python3 v41/sync_routes.py check
   python3 v41/sync_watch.py --publish FXqHbFI37oGOCyxT3NkcVhjnnRg                             # after Derek confirms
   ```

   It sets `SAVE_FILE_TOKEN` if it is empty and makes the client package `{ver, file:SAVE_FILE_TOKEN, rep:'huaxida-h1', …}`.
   Nothing else changes, and re-running it is a no-op. Tabs opened before the publish keep routing through the fallback,
   with the warning, until they are refreshed.

**Superseded by `review_sync_mvp_20261015`:** `review_kit.py upgrade` runs this same patch and adds the review kit and
webhook channel. If that upgrade is installed, skip step 2 here.
