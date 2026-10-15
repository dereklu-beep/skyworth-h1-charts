#!/usr/bin/env bash
# Install the file_token router into $ROOT/v41 (box). Makes no Feishu write and does not start the watcher.
#   bash install.sh            # from the unpacked sync_route_fix_20261015/ folder
# Overrides: ROOT, LIVE_DIR, SW_SRC, SW_WEBHOOK, HX_SRC, HX_MASTER, FORCE=1 (skip md5 expectations),
#            INBOX_FLAG=--no-inbox (baseline drops only, when the Feishu inbox is unreadable)
set -euo pipefail
PKG=$(cd "$(dirname "$0")" && pwd)
ROOT=${ROOT:-/workspace/sdmc_skyworth}
V41=$ROOT/v41
LIVE=${LIVE_DIR:-$ROOT/_live_check_1023}
SW_DIR=$ROOT/skyworth_report/opus_final_20261014
SW_SRC=${SW_SRC:-$SW_DIR/创维数字专报_入稿终稿.html}
SW=$SW_DIR/创维数字专报_入稿终稿_feishu.html
HX_SRC=${HX_SRC:-$LIVE/FXqHb.html}
HX=${HX_MASTER:-$ROOT/huaxida_report/华曦达对比_排版优化_feishu.html}
PDX=PdxFbDlbDorRAexT1hRcpHuCnBf
FXQ=FXqHbFI37oGOCyxT3NkcVhjnnRg
TS=$(date +%Y%m%d_%H%M%S)

die() { echo "INSTALL STOP: $*" >&2; exit 1; }
m5() { md5sum "$1" | cut -c1-32; }
expect_md5() {  # file want what
  local got; got=$(m5 "$1")
  [ "$got" = "$2" ] || { [ "${FORCE:-}" = 1 ] && echo "WARN $3 md5 $got (expected $2), FORCE=1" || die "$3 $1 md5 $got, expected $2 (FORCE=1 to accept)"; }
}
tok_of() { python3 -c "import sys,re;m=re.findall(r\"SAVE_FILE_TOKEN='([^']*)'\",open(sys.argv[1],encoding='utf-8',errors='replace').read());print(','.join(sorted(set(m))))" "$1"; }

pgrep -af '[s]ync_watch.py' && die "sync_watch.py is running; stop it first"
[ -d "$V41" ] || die "$V41 not found"

echo "== 1. back up and install scripts into $V41"
expect_md5 "$V41/sync_watch.py" 05f17b18f23050660a03df9082bc9da1 "box sync_watch.py"
cp -p "$V41/sync_watch.py" "$V41/sync_watch.py.pre_router_$TS"
[ -f "$V41/sync_watch_state.json" ] && mv "$V41/sync_watch_state.json" "$V41/sync_watch_state.json.pre_router_$TS"
install -m 755 "$PKG/sync_watch.py" "$PKG/sync_routes.py" "$PKG/sync_pull_routed.py" "$V41/"
if [ -f "$V41/sync_routes.json" ]; then
  echo "keeping existing $V41/sync_routes.json"
else
  python3 - "$PKG/sync_routes.json" "$V41/sync_routes.json" "$SW" "$HX" <<'EOF'
import json, sys
src, dst, sw, hx = sys.argv[1:]
j = json.load(open(src, encoding='utf-8'))
for r in j['routes']:
    r['master'] = {'PdxFbDlbDorRAexT1hRcpHuCnBf': sw, 'FXqHbFI37oGOCyxT3NkcVhjnnRg': hx}[r['token']]
json.dump(j, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
EOF
fi

echo "== 2. 创维 master $SW"
if [ -f "$SW" ] && [ "$(tok_of "$SW")" = "$PDX" ]; then
  echo "exists with SAVE_FILE_TOKEN=$PDX, kept ($(m5 "$SW"))"
else
  [ -f "$SW" ] && mv "$SW" "$SW.pre_router_$TS"
  expect_md5 "$SW_SRC" d571a690c03ff82b81467b314535335a "创维 入稿终稿"
  WH=${SW_WEBHOOK:-}
  if [ -z "$WH" ] && [ -f "$LIVE/PdxFb.html" ]; then
    WH=$(grep -o "SYNC_WEBHOOK='[^']*'" "$LIVE/PdxFb.html" | head -1 | cut -d"'" -f2 || true)
  fi
  [ -n "$WH" ] || die "no SYNC_WEBHOOK for 创维: set SW_WEBHOOK=https://webhook.site/<token> (the one the live PdxFb page uses)"
  python3 "$V41/sync_routes.py" inject-token "$SW_SRC" "$SW" "$PDX" --webhook "$WH"
fi

echo "== 3. 华曦达 master $HX"
if [ -f "$HX" ] && [ "$(tok_of "$HX")" = "$FXQ" ]; then
  echo "exists with SAVE_FILE_TOKEN=$FXQ, kept ($(m5 "$HX"))"
else
  expect_md5 "$HX_SRC" 1b1e3c34aae544af1ae2b18d7a083ca3 "华曦达 排版优化 (live FXqHb)"
  mkdir -p "$(dirname "$HX")"
  cp -p "$HX_SRC" "$HX"
  echo "copied $HX_SRC -> $HX ($(m5 "$HX")); v71_std is NOT used"
fi

echo "== 4. last good published copy per token (shrink guard baseline, rollback source)"
seed() {  # token file
  if [ -f "$V41/sync_routed/$1/last_good.html" ]; then echo "$1 last good exists, kept"
  elif [ -f "$2" ]; then python3 "$V41/sync_watch.py" --seed-last-good "$1" "$2"
  else echo "WARN $1: no live copy at $2 - shrink guard inactive until the first replace (seed: python3 $V41/sync_watch.py --seed-last-good $1 FILE)"; fi
}
seed "$FXQ" "$LIVE/FXqHb.html"
seed "$PDX" "$LIVE/PdxFb.html"

echo "== 5. validate routes"
python3 "$V41/sync_routes.py" check "$V41/sync_routes.json"

echo "== 6. baseline: everything already in the inbox / drop folder counts as handled"
python3 "$V41/sync_watch.py" --mark-seen ${INBOX_FLAG:-}

echo "== 7. re-apply the four 10:24 创维 drops to the 创维 master only (no Feishu replace)"
SW0=$(m5 "$SW"); HX0=$(m5 "$HX")
python3 "$V41/sync_watch.py" --no-inbox --no-replace --replay "$V41"/sync_inbox_drops/drop_20261015_1024*.txt
echo "创维 master $SW0 -> $(m5 "$SW")"
[ "$(m5 "$HX")" = "$HX0" ] || die "华曦达 master changed during 创维 replay"
echo "华曦达 master unchanged $HX0"

cat <<EOF

INSTALLED. Gate is still closed (derek_confirmed=false on both routes) - nothing will be replaced on Feishu.
After Derek confirms, set "derek_confirmed": true for that route in $V41/sync_routes.json, then:
  python3 $V41/sync_watch.py --publish $PDX     # guarded same-link replace of the 创维 master
  nohup python3 $V41/sync_watch.py --loop --force-replace >> $V41/sync_watch.log 2>&1 &
Rollback of a bad replace:  python3 $V41/sync_watch.py --rollback <TOKEN>
Uninstall:  cp $V41/sync_watch.py.pre_router_$TS $V41/sync_watch.py   (do not restart the old loop)
EOF
