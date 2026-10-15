# review_sync_mvp_20261015 — box upgrade

This upgrade adds review formatting (fonts, colours, highlights, comments) and visible sync-result toasts to the two
report masters, and makes the 华曦达 page send its own `file` token. It changes no report text, numbers or 口径. Design
and schema are in `PLAN.md`. It sits on top of `sync_route_fix_20261015`, which is already installed. Nothing here
writes to Feishu until a Derek-confirmed `--publish`.

| Path | What |
| --- | --- |
| `box_v41/review_kit.{py,js,css}` | new: the kit, plus `upgrade` / `check` for a master |
| `box_v41/sync_pull_routed.py` | real sanitizer for applied HTML; 华曦达 edits and deletes go to `#report-tpl` first |
| `box_v41/sync_routes.py` | `patch-client`; title check holds only when the title names another report |
| `box_v41/sync_watch.py` | warns when a package is routed by the legacy (no `file`) fallback |
| `box_v41_since_route_fix.patch` | the same three `.py` changes as a diff against the installed route-fix version |
| `box_v41/sync_routes.json`, `install.sh`, `sync_watch.py.orig` | reference copies for the tests; **do not copy over the box's live `sync_routes.json`** |
| `tests/` | unit tests and the headless-Chrome e2e (`tests/e2e/review_e2e.py`) |
| `smoke_output.txt` | the run below, done in the cloud with a fake `replace.py` |

## 1. Install the code (no Feishu write)

```bash
cd /workspace/sdmc_skyworth
pkill -f '[s]ync_watch.py --loop' || true          # keep the loop off while masters are edited
TS=$(date +%Y%m%d_%H%M%S); K=/path/to/review_sync_mvp_20261015
for f in sync_pull_routed.py sync_routes.py sync_watch.py; do cp v41/$f v41/$f.pre_review_$TS; done
cp $K/box_v41/review_kit.py $K/box_v41/review_kit.js $K/box_v41/review_kit.css \
   $K/box_v41/sync_pull_routed.py $K/box_v41/sync_routes.py $K/box_v41/sync_watch.py v41/
python3 v41/sync_routes.py check                   # routes still valid, exit 0
```

Optional box-side tests, using the box originals: `SMOKE_SW_SRC` is the `d571a690` 入稿终稿 source and `SMOKE_HX_SRC`
is the `1b1e3c34` FXqHb copy.

```bash
cd $K && SMOKE_SW_SRC=<入稿终稿.html> SMOKE_HX_SRC=/workspace/sdmc_skyworth/_live_check_1023/FXqHb.html \
  python3 -m unittest discover -s tests            # 36 tests
python3 tests/e2e/review_e2e.py /tmp/review_shots  # needs node 22 + Chrome (CHROME=/path if not standard)
```

## 2. Re-publish order (writer onboarding order)

Both masters change, so each needs **one** Derek-confirmed same-link publish. Do PdxFb first: it already sends `file`
and already uses the webhook, so it is the smaller change. Do FXqHb only after PdxFb passes a real writer round trip.

### 2a. PdxFb 创维数字专报

```bash
SW=/workspace/sdmc_skyworth/skyworth_report/opus_final_20261014/创维数字专报_入稿终稿_feishu.html
python3 v41/review_kit.py upgrade "$SW" --token PdxFbDlbDorRAexT1hRcpHuCnBf   # backup "$SW".pre_review_<ts>
python3 v41/review_kit.py check "$SW" --token PdxFbDlbDorRAexT1hRcpHuCnBf     # "review kit OK"
python3 v41/sync_routes.py check
# Derek confirms (route derek_confirmed: true) →
python3 v41/sync_watch.py --publish PdxFbDlbDorRAexT1hRcpHuCnBf               # guarded same-link replace
```

`upgrade` adds about 20 KB, so the shrink guard does not fire. Expected on the cloud copy: 172,749 → 193,253 bytes, with
`+ sync hook (skyworth-v1)` and `+ review kit added`. A second run prints `already up to date`.

Writer check on the Feishu link:

1. Refresh the page and press 修改.
2. Select a few characters. Pick 黑体 + 红, then 高亮 黄 on other text, then 批注 → type → 保存.
3. Press 同步修改. A green toast should read 「已提交 N 处修改」.
4. Start the loop (section 3) or run `python3 v41/sync_watch.py` once. Check that the log shows `route … → 创维数字专报`
   and `master changed`. It should **not** show a `WARNING routed by legacy fallback`.
5. The loop republishes PdxFb. Refresh the link: the formatting and the 「注」 marker are still there, and clicking the
   marker shows the comment.

### 2b. FXqHb 华曦达对比 (after 2a passes)

```bash
HX=/workspace/sdmc_skyworth/huaxida_report/华曦达对比_排版优化_feishu.html
WH=$(grep -o "SYNC_WEBHOOK='https://[^']*'" "$SW" | head -1 | cut -d"'" -f2); echo "$WH"   # same webhook as 创维
python3 v41/review_kit.py check "$HX" --token FXqHbFI37oGOCyxT3NkcVhjnnRg    # before: NOT READY (4 errors)
python3 v41/review_kit.py upgrade "$HX" --token FXqHbFI37oGOCyxT3NkcVhjnnRg --rep huaxida-h1 --webhook "$WH"
python3 v41/review_kit.py check "$HX" --token FXqHbFI37oGOCyxT3NkcVhjnnRg    # "review kit OK"
python3 v41/sync_routes.py check
# Derek confirms →
python3 v41/sync_watch.py --publish FXqHbFI37oGOCyxT3NkcVhjnnRg
```

This also performs the queued FXqHb `file`-token patch (`sync_routes.py patch-client`). The package now carries
`file:SAVE_FILE_TOKEN, rep:'huaxida-h1'`, and the page now posts to the webhook instead of copy + inbox. The copy box
and inbox stay as the failure fallback. Expected on the cloud copy: 577,426 → 598,099 bytes. Tabs that were opened
before the publish still send old packages until they are refreshed. Those packages still route via the title
fallback, and the log warns `routed by legacy fallback`.

Run the same writer check as in 2a. On 华曦达, the box now writes the edit into `<template id="report-tpl">` and
mirrors it to `#sheet`. Before this fix, a refresh threw away any edit that reached this master. The writer needs no
extra step. The page keys its local draft by a hash of the template, so once the box publish changes the template, an
old draft is ignored. The upgrade publish itself leaves the template unchanged, so unsent drafts survive it.

## 3. Restart the loop

```bash
nohup python3 v41/sync_watch.py --loop 30 --force-replace >> v41/sync_watch.log 2>&1 &   # --loop needs the interval
```

## 4. Failure toasts (what the writer sees)

| Toast | Cause | Writer action |
| --- | --- | --- |
| 被页面安全策略拦截 | page CSP, e.g. the Feishu in-app preview | 下载改过的页面, or open the link in Chrome, then 同步修改 |
| 网络请求被拦截 | preview sandbox, proxy, extension | 重试 / 复制修改包 |
| 同步服务返回 HTTP xxx | webhook.site down or the token expired | 重试 later; the assistant checks the webhook |
| 超时（15 秒） | slow network | 重试 |
| 设备离线 / 同步通道未配置 | offline / no `SYNC_WEBHOOK` in the master | reconnect / rerun `review_kit.py upgrade --webhook` |
| 已发出，未收到回执 (amber) | request sent, reply unreadable (cross-origin) | refresh in 2 minutes; if unchanged, 同步修改 again |

In every failure case the edits stay in the browser's local draft. The toast shows how many edits are still pending.

## 5. Rollback

- **Local master:** `cp "$SW".pre_review_<ts> "$SW"`, and likewise for `$HX`.
- **Feishu:** `python3 v41/sync_watch.py --rollback <token>`, which restores the last good published copy.
- **Code:** `cp v41/<f>.pre_review_$TS v41/<f>` for the three `.py` files. The `review_kit.*` files can stay; a master
  without the kit ignores them.

## 6. Smoke done in the cloud (`smoke_output.txt`)

- Upgrade, check, re-upgrade, check on copies of both real masters, as in 2a and 2b.
- 36 tests in this folder pass. The full repo suite passes 96/96, with the real masters and with stub masters.
- Headless Chrome e2e: real router + `sync_pull_routed.py`; a fake `replace.py` copies the master to a local
  "published" page; the webhook is on another origin.
  - Both pages: the format bar, the 「已提交」 toast, and formatting + comment surviving a reload from the published
    copy.
  - 华曦达 is routed by `file` with no fallback warning.
  - Failure toasts were produced for HTTP 500, CSP, timeout, and no-receipt.
  - Replace calls were `PdxFb, PdxFb, FXqHb` and nothing else.
- Screenshots are in `media/`:
  - `review-sync-format-bar.png`, `review-sync-success-toast.png`;
  - `review-sync-after-reload.png` (创维), `review-sync-huaxida-after-reload.png`;
  - `review-sync-fail-http500.png`, `review-sync-fail-csp.png`, `review-sync-fail-timeout.png`,
    `review-sync-warn-no-receipt.png`.
