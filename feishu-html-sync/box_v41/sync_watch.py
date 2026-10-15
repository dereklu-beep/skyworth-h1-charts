#!/usr/bin/env python3
"""Poll Feishu sync inbox + local drops, route each SDMCSYNC1 package by its Feishu file_token to that
report's master (v41/sync_routes.json), apply via sync_pull_routed, then optionally replace that same link.

Usage (from /workspace/sdmc_skyworth):
  python3 v41/sync_watch.py              # one pass; replace only if the routed master really changed
  python3 v41/sync_watch.py --dry
  python3 v41/sync_watch.py --loop 30    # poll; never auto-replace unless --force-replace
  python3 v41/sync_watch.py --no-replace
  python3 v41/sync_watch.py --force-replace  # allow Feishu overwrite on real ops
  python3 v41/sync_watch.py --check-routes   # validate v41/sync_routes.json and exit
  python3 v41/sync_watch.py --mark-seen      # install baseline: mark current inbox/drop packages as handled
  python3 v41/sync_watch.py --replay v41/sync_inbox_drops/drop_X.txt ...   # re-route these drops now
  python3 v41/sync_watch.py --seed-last-good TOKEN FILE   # record FILE as the last good published copy
  python3 v41/sync_watch.py --rollback TOKEN              # same-link replace TOKEN with the previous good copy
  python3 v41/sync_watch.py --publish TOKEN               # guarded same-link replace of TOKEN's master (needs derek_confirmed)

Unknown / missing file_token, or a rep / title that contradicts the token: the package is kept in
v41/sync_held/ with a WARNING and nothing is applied or replaced. There is no default report.
Feishu replace also needs "derek_confirmed": true on that route, and passes a guard: the master's
SAVE_FILE_TOKEN must equal the route token, and the file may not shrink more than SYNC_MAX_SHRINK (0.30)
against the last good published copy unless --allow-shrink. Every replace first archives the last good
copy under v41/sync_routed/<token>/backups/.
"""
import os, sys, json, time, argparse, subprocess, hashlib, glob, re, base64

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sync_routes  # noqa: E402

DROPS = os.path.join(HERE, 'sync_inbox_drops')
STATE = os.path.join(HERE, 'sync_watch_state.json')
ROUTED = os.path.join(HERE, 'sync_routed')
HELD = os.path.join(HERE, 'sync_held')
PULL = os.path.join(HERE, 'sync_pull_routed.py')
REPLACE = os.environ.get('SYNC_REPLACE') or '/workspace/feishu/replace.py'
MAX_SHRINK = float(os.environ.get('SYNC_MAX_SHRINK') or 0.30)


def load_state():
    if os.path.exists(STATE):
        st = json.load(open(STATE))
        st.setdefault('seen_pkgs', {})
        return st
    return {'seen_drops': {}, 'last_inbox_hash': '', 'passes': 0, 'seen_pkgs': {}}


def save_state(st):
    json.dump(st, open(STATE, 'w'), ensure_ascii=False, indent=2)


def new_drops(st):
    os.makedirs(DROPS, exist_ok=True)
    out = []
    for path in sorted(glob.glob(os.path.join(DROPS, 'drop_*.txt'))):
        try:
            mtime = os.path.getmtime(path)
            size = os.path.getsize(path)
        except OSError:
            continue
        prev = st['seen_drops'].get(path)
        if prev and prev.get('mtime') == mtime and prev.get('size') == size:
            continue
        out.append(path)
    return out


def inbox_raw():
    import requests
    B = 'https://open.feishu.cn/open-apis'
    inbox = json.load(open(os.path.join(HERE, 'inbox.json')))['token']
    r = requests.post(
        B + '/auth/v3/tenant_access_token/internal',
        json={'app_id': os.environ['FEISHU_APP_ID'], 'app_secret': os.environ['FEISHU_APP_SECRET']},
        timeout=30,
    ).json()
    tok = r['tenant_access_token']
    j = requests.get(
        f'{B}/docx/v1/documents/{inbox}/raw_content',
        headers={'Authorization': 'Bearer ' + tok},
        timeout=30,
    ).json()
    if j.get('code'):
        raise RuntimeError('inbox read failed: %s' % j)
    return (j.get('data') or {}).get('content') or ''


def inbox_hash_and_content():
    content = inbox_raw()
    return hashlib.sha256(content.encode()).hexdigest(), content


def count_packages(text):
    return len(re.findall(r'SDMCSYNC1:', text or ''))


def md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def _put(dirpath, name, text):
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)
    return p


def route_packages(texts, routes, st, force=False, dry=False):
    """Split every package found in `texts` to its route queue or to sync_held/. Returns {token: route}."""
    invalid = {r.get('token'): '; '.join(sync_routes.check_routes([r])[0]) for r in routes
               if sync_routes.check_routes([r])[0]}
    touched = {}
    for src, text in texts:
        for raw, p, head in sync_routes.packages(text):
            k = sync_routes.pkg_key(raw)
            if k in st['seen_pkgs'] and not force:
                continue
            if p is not None and sync_routes.is_ping(p):
                st['seen_pkgs'][k] = {'src': src, 'ping': True}
                continue
            r, why = sync_routes.resolve(p, head, routes)
            if r and r['token'] in invalid:
                r, why = None, 'route %s invalid: %s' % (r['token'], invalid[r['token']])
            ts = (p or {}).get('ts') or ''
            name = 'pkg_%s_%s.txt' % (re.sub(r'[^0-9A-Za-z]', '', ts)[:17] or 'nots', k)
            body = (head + '\n' if head else '') + 'SRC: %s\n%s\n' % (src, raw)
            if not r:
                print('WARNING held (not applied, not replaced): %s — %s' % (os.path.basename(src), why), flush=True)
                if not dry:
                    _put(HELD, name, 'REASON: %s\n' % why + body)
            else:
                print('route %s → %s (%s)' % (os.path.basename(src), r['label'], r['token']), flush=True)
                if not dry:
                    _put(os.path.join(ROUTED, r['token'], 'queue'), name, body)
                touched[r['token']] = r
            if not dry:
                st['seen_pkgs'][k] = {'src': src, 'route': r and r['token'], 'held': why}
    return touched


def run_pull(r, dry=False):
    base = os.path.join(ROUTED, r['token'])
    cmd = [sys.executable, PULL, '--target', r['master'], '--no-inbox', '--drops', os.path.join(base, 'queue'),
           '--log', os.path.join(base, 'state', 'sync_applied.json')]
    if dry:
        cmd.append('--dry')
    print('+', ' '.join(cmd), flush=True)
    os.makedirs(os.path.join(base, 'state'), exist_ok=True)
    env = dict(os.environ, SYNC_STATE_DIR=os.path.join(base, 'state'))
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600, env=env)
    sys.stdout.write(p.stdout or '')
    sys.stderr.write(p.stderr or '')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def run_replace(token, path):
    cmd = [sys.executable, REPLACE, token, path]
    print('+', ' '.join(cmd), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    sys.stdout.write(p.stdout or '')
    sys.stderr.write(p.stderr or '')
    return p.returncode


def last_good(token):
    return os.path.join(ROUTED, token, 'last_good.html')


def guard(token, path, allow_shrink=False):
    """None if `path` may be published to `token`, else the reason it may not."""
    with open(path, encoding='utf-8', errors='replace') as f:
        toks = sync_routes.master_token(f.read())
    if set(toks) != {token}:
        return 'SAVE_FILE_TOKEN in %s is %s, not %s' % (path, ','.join(sorted(set(toks))) or 'missing', token)
    lg = last_good(token)
    if os.path.exists(lg) and not allow_shrink:
        old, new = os.path.getsize(lg), os.path.getsize(path)
        if new < old * (1 - MAX_SHRINK):
            return 'file shrinks %d -> %d bytes (more than %d%% vs last good); pass --allow-shrink if intended' % (
                old, new, MAX_SHRINK * 100)
    return None


def record_good(token, path):
    """Archive the previous last-good copy, then make `path` the new last-good copy."""
    d = os.path.join(ROUTED, token)
    os.makedirs(os.path.join(d, 'backups'), exist_ok=True)
    lg = last_good(token)
    if os.path.exists(lg):
        os.replace(lg, os.path.join(d, 'backups', 'good_%s_%s.html' % (time.strftime('%Y%m%d_%H%M%S'), md5(lg)[:8])))
    with open(path, 'rb') as f, open(lg, 'wb') as g:
        g.write(f.read())
    print('last good for %s = %s (%d bytes)' % (token, md5(lg), os.path.getsize(lg)))


def guarded_replace(token, path, allow_shrink=False):
    why = guard(token, path, allow_shrink)
    if why:
        print('REFUSED replace %s: %s' % (token, why), flush=True)
        return 3
    rc = run_replace(token, path)
    if rc == 0:
        record_good(token, path)
    return rc


def rollback(token):
    """Same-link replace `token` with the newest archived good copy (the one before the current last good)."""
    b = sorted(glob.glob(os.path.join(ROUTED, token, 'backups', 'good_*.html')))
    if not b:
        print('no archived good copy for', token)
        return 1
    src = b[-1]
    print('rollback %s -> %s (%s)' % (token, src, md5(src)))
    why = guard(token, src, allow_shrink=True)
    if why:
        print('REFUSED rollback:', why)
        return 3
    rc = run_replace(token, src)
    if rc == 0:
        lg = last_good(token)
        with open(src, 'rb') as f, open(lg, 'wb') as g:
            g.write(f.read())
        os.replace(src, src + '.rolled_back_to')
        print('Feishu %s restored; master not touched — restore it with: cp %s <master>' % (token, lg))
    return rc


def apply_route(r, dry=False, no_replace=False, allow_shrink=False):
    before = md5(r['master'])
    rc, out = run_pull(r, dry=dry)
    if dry or rc != 0:
        if rc:
            print('[%s] pull failed rc %s' % (r['label'], rc))
        return rc
    after = md5(r['master'])
    if before == after:
        print('[%s] master unchanged (%s); no replace' % (r['label'], after))
        return 0
    print('[%s] master changed %s -> %s' % (r['label'], before, after))
    if no_replace:
        print('[%s] applied locally; --no-replace set, skip Feishu overwrite' % r['label'])
        return 0
    if not r.get('derek_confirmed'):
        print('[%s] GATED: derek_confirmed=false in sync_routes.json; applied locally, Feishu %s not replaced'
              % (r['label'], r['token']))
        return 0
    return guarded_replace(r['token'], r['master'], allow_shrink)


def one_pass(dry=False, no_replace=False, no_inbox=False, replay=None, mark_seen=False, allow_shrink=False):
    st = load_state()
    routes = sync_routes.load_routes()
    errs, _ = sync_routes.check_routes(routes, exists=lambda p: True, read=lambda p: 'SAVE_FILE_TOKEN=""')
    dup = [e for e in errs if 'duplicate' in e or 'shared' in e or 'also claimed' in e]
    if dup:
        print('ROUTES ERROR (ambiguous, nothing routed):', '; '.join(dup))
        return 2
    drops = list(replay) if replay else new_drops(st)
    ih, content, inbox_changed = st.get('last_inbox_hash'), '', False
    if not no_inbox and not replay:
        try:
            ih, content = inbox_hash_and_content()
            inbox_changed = ih != st.get('last_inbox_hash')
        except Exception as e:
            print('WARNING inbox read failed (drops still processed):', repr(e)[:200])
    print(f'inbox packages(SDMCSYNC1)={count_packages(content)} new_drops={len(drops)} inbox_changed={inbox_changed}')
    if not drops and not inbox_changed:
        print('no new drops / inbox unchanged')
        return 0
    texts = []
    for path in drops:
        try:
            texts.append((path, open(path, encoding='utf-8').read()))
        except OSError as e:
            print('WARNING cannot read', path, e)
    if inbox_changed:
        texts.append(('feishu-inbox', content))
    if mark_seen:
        n = 0
        for _, text in texts:
            for raw, _p, _h in sync_routes.packages(text):
                st['seen_pkgs'].setdefault(sync_routes.pkg_key(raw), {'src': 'baseline'})
                n += 1
        touched = {}
        print('baseline: marked %d packages as already handled' % n)
    else:
        touched = route_packages(texts, routes, st, force=bool(replay), dry=dry)
    if not dry:
        for path in drops:
            try:
                st['seen_drops'][path] = {'mtime': os.path.getmtime(path), 'size': os.path.getsize(path)}
            except OSError:
                pass
        st['last_inbox_hash'] = ih
        st['passes'] = st.get('passes', 0) + 1
        save_state(st)
    rc = 0
    for r in touched.values():
        rc = apply_route(r, dry=dry, no_replace=no_replace, allow_shrink=allow_shrink) or rc
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--loop', type=int, default=0, help='poll interval seconds; 0 = once')
    ap.add_argument('--dry', action='store_true', help='list/detect only; no apply, no replace')
    ap.add_argument('--no-replace', action='store_true', help='apply to local HTML but do not call replace.py')
    ap.add_argument('--force-replace', action='store_true', help='allow Feishu overwrite on real ops (needed for loop)')
    ap.add_argument('--no-inbox', action='store_true', help='drops only; do not read the Feishu inbox')
    ap.add_argument('--check-routes', action='store_true', help='validate sync_routes.json and exit')
    ap.add_argument('--mark-seen', action='store_true', help='mark current inbox/drop packages handled (install baseline)')
    ap.add_argument('--replay', nargs='+', help='route these drop files now, even if seen before')
    ap.add_argument('--allow-shrink', action='store_true', help='override the shrink guard for this run')
    ap.add_argument('--seed-last-good', nargs=2, metavar=('TOKEN', 'FILE'), help='record FILE as last good copy')
    ap.add_argument('--rollback', metavar='TOKEN', help='replace TOKEN with the previous good copy')
    ap.add_argument('--publish', metavar='TOKEN', help="guarded replace of TOKEN with its route's master")
    a = ap.parse_args()
    if a.check_routes:
        sys.exit(sync_routes.main(['check']))
    if a.seed_last_good:
        record_good(*a.seed_last_good)
        sys.exit(0)
    if a.rollback:
        sys.exit(rollback(a.rollback))
    if a.publish:
        r = sync_routes.by_token(sync_routes.load_routes()).get(a.publish)
        if not r:
            sys.exit('no route for %s in sync_routes.json' % a.publish)
        if not r.get('derek_confirmed'):
            sys.exit('GATED: derek_confirmed=false for %s (%s); not replaced' % (r['token'], r['label']))
        sys.exit(guarded_replace(r['token'], r['master'], a.allow_shrink))
    if a.loop and not a.force_replace:
        a.no_replace = True
        print('loop: Feishu replace disabled (pass --force-replace to enable)', flush=True)
    kw = dict(dry=a.dry, no_replace=a.no_replace, no_inbox=a.no_inbox, allow_shrink=a.allow_shrink)
    if a.loop <= 0:
        sys.exit(one_pass(replay=a.replay, mark_seen=a.mark_seen, **kw) or 0)
    print(f'watching every {a.loop}s …', flush=True)
    while True:
        try:
            one_pass(**kw)
        except Exception as e:
            print('watch error', e, flush=True)
        time.sleep(a.loop)


if __name__ == '__main__':
    main()
