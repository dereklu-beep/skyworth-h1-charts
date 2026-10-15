# sync_route_fix_20261015 — box install

Replaces `/workspace/sdmc_skyworth/v41/sync_watch.py` (md5 `05f17b18…`, hard-coded to FXqHb + v71_std) with a router
that sends each sync package to the master of its own `file_token` (`sync_routes.json`). No Feishu write during install.

```bash
pkill -f '[s]ync_watch.py' || true                      # must stay off until step 3
cd /path/to/sync_route_fix_20261015
# optional, arms PdxFb shrink guard + rollback: save the current live PdxFb html as
#   /workspace/sdmc_skyworth/_live_check_1023/PdxFb.html   (FXqHb.html, md5 1b1e3c34, is already there)
bash install.sh                                          # SW_WEBHOOK=https://webhook.site/<token> if no live PdxFb copy
```

`install.sh` checks md5s, backs up the old watcher, builds the 创维 master by token injection only
(`入稿终稿` d571a690 → `入稿终稿_feishu.html`, one line changed), copies the live FXqHb copy as the 华曦达 master,
seeds last-good copies, runs `sync_routes.py check`, baselines old drops, and re-applies the four 10:24 drops to the
创维 master only (`--no-replace`). Both routes stay `derek_confirmed: false`.

After Derek confirms (per route, in `v41/sync_routes.json` set `"derek_confirmed": true`):

```bash
python3 v41/sync_watch.py --publish PdxFbDlbDorRAexT1hRcpHuCnBf      # same-link replace, guarded
nohup python3 v41/sync_watch.py --loop 30 --force-replace >> v41/sync_watch.log 2>&1 &
```

| Command | Effect |
| --- | --- |
| `python3 v41/sync_routes.py check` | validate routes (token format, master exists, master SAVE_FILE_TOKEN = route token) |
| `python3 v41/sync_watch.py --dry` | route + show what would apply, write nothing |
| `python3 v41/sync_watch.py --rollback TOKEN` | same-link replace TOKEN with the previous good copy |
| `python3 v41/sync_watch.py --seed-last-good TOKEN FILE` | record FILE as the last good published copy |
| `--allow-shrink` | one-run override of the 30 % shrink guard (`SYNC_MAX_SHRINK` changes the threshold) |

Held packages (unknown / missing token, rep or title conflict) are kept in `v41/sync_held/` with the reason.
Uninstall: `cp v41/sync_watch.py.pre_router_<ts> v41/sync_watch.py` — but do not restart the old loop.

Optional follow-up (separate step, `SYNC_ROUTE_FIX_DELTA.md` §9): `sync_routes.py patch-client` makes the FXqHb page send
its `file` token, and the router warns on every legacy-fallback route. This is superseded by
`review_sync_mvp_20261015` (`review_kit.py upgrade`), which includes the same patch.
