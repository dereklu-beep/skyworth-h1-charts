#!/usr/bin/env python3
"""Route SDMCSYNC1 packages by Feishu file_token to the right local master (no hard-coded report).

Routes live in an external JSON file (default: v41/sync_routes.json next to this script, or $SYNC_ROUTES):

  {"routes": [
     {"token": "PdxFbDlbDorRAexT1hRcpHuCnBf", "label": "创维数字专报", "rep": "skyworth-report",
      "title_keywords": ["创维数字"], "master": "/workspace/.../创维数字专报_入稿终稿_feishu.html",
      "derek_confirmed": false},
     ...]}

A package goes to the route whose `token` equals the package `file` (or `file_token`). A package with no
token, an unknown token, or a `rep` / title that contradicts its token is HELD (kept on disk, warned) and
never applied or replaced. `legacy_unlabelled_ver` lets one route accept token-less packages from an old
client version that cannot send `file` (the 华曦达 v46 page) — configured per route, not in code.
Replace runs only for routes with "derek_confirmed": true.

CLI:
  python3 sync_routes.py check [routes.json]                       # validate the routes file (exit 1 on error)
  python3 sync_routes.py inject-token SRC DST TOKEN [--webhook URL] [--inbox URL]
                                                                   # copy SRC→DST, setting only the sync constants
  python3 sync_routes.py patch-client MASTER TOKEN [--rep REP]     # in place (backup MASTER.pre_client_<ts>): token
                                                                   # constant + client sends `file` (and `rep`) in SDMCSYNC1
"""
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROUTES = os.environ.get('SYNC_ROUTES') or os.path.join(HERE, 'sync_routes.json')
PKG_RE = re.compile(r'SDMCSYNC1:([A-Za-z0-9+/=\s]+?):END')
TOKEN_RE = re.compile(r'^[A-Za-z0-9]{27}$')
SAVE_TOKEN_RE = re.compile(r'''\bSAVE_FILE_TOKEN\s*=\s*(['"])([^'"]*)\1''')
CONST_RE = re.compile(r'''const\s+SYNC_VER\s*=[^;\n]*;''')
META_REP_RE = re.compile(r'<meta\s+name="report-(?:id|name)"\s+content="([^"]*)"', re.I)


# ───────────────────────── routes file ─────────────────────────

def load_routes(path=None):
    with open(path or DEFAULT_ROUTES, encoding='utf-8') as f:
        j = json.load(f)
    return j.get('routes') or []


def by_token(routes):
    return {r['token']: r for r in routes if r.get('token')}


def master_token(src):
    """All SAVE_FILE_TOKEN values assigned in the HTML (normally exactly one)."""
    return [m.group(2) for m in SAVE_TOKEN_RE.finditer(src)]


def _read(p):
    with open(p, encoding='utf-8', errors='replace') as f:
        return f.read()


def check_routes(routes, exists=os.path.isfile, read=None):
    """Return (errors, warnings). Errors make the routes file unusable."""
    read = read or _read
    errs, warns = [], []
    seen_tok, seen_master, legacy = {}, {}, {}
    if not routes:
        errs.append('no routes')
    for i, r in enumerate(routes):
        tag = 'route[%d] %s' % (i, r.get('label') or r.get('token') or '?')
        tok, master = r.get('token') or '', r.get('master') or ''
        if not TOKEN_RE.match(tok):
            errs.append('%s: token %r is not a 27-char Feishu file_token' % (tag, tok))
        if not r.get('label'):
            errs.append('%s: missing label' % tag)
        if tok in seen_tok:
            errs.append('%s: duplicate token (also %s)' % (tag, seen_tok[tok]))
        seen_tok[tok] = tag
        if not master or not os.path.isabs(master):
            errs.append('%s: master must be an absolute path' % tag)
            continue
        if master in seen_master:
            errs.append('%s: master shared with %s' % (tag, seen_master[master]))
        seen_master[master] = tag
        for v in r.get('legacy_unlabelled_ver') or []:
            if v in legacy:
                errs.append('%s: legacy client ver %s also claimed by %s' % (tag, v, legacy[v]))
            legacy[v] = tag
        if not exists(master):
            errs.append('%s: master not found: %s' % (tag, master))
            continue
        src = read(master)
        toks = master_token(src)
        if not toks:
            errs.append('%s: master has no SAVE_FILE_TOKEN (run inject-token)' % tag)
        elif len(set(toks)) != 1 or toks[0] != tok:
            errs.append('%s: master SAVE_FILE_TOKEN=%s does not match route token %s' % (tag, ','.join(sorted(set(toks))) or "''", tok))
        reps = [m.group(1) for m in META_REP_RE.finditer(src[:30000])]
        if r.get('rep') and reps and r['rep'] not in reps:
            errs.append('%s: master meta report-id/name %s does not match route rep %s' % (tag, reps, r['rep']))
        if not r.get('derek_confirmed'):
            warns.append('%s: derek_confirmed=false → applied to the box master only, no Feishu replace' % tag)
    return errs, warns


# ───────────────────────── packages ─────────────────────────

def decode(b64):
    return json.loads(base64.b64decode(re.sub(r'\s', '', b64)).decode('utf-8'))


def packages(text):
    """[(raw 'SDMCSYNC1:…:END', pkg dict or None, header line)] in text order."""
    out = []
    for m in PKG_RE.finditer(text or ''):
        head = ''
        for line in reversed(text[:m.start()].splitlines()[-8:]):
            if line.strip().startswith('【'):
                head = line.strip()
                break
        try:
            p = decode(m.group(1))
        except Exception:
            p = None
        out.append((m.group(0), p, head))
    return out


def pkg_key(raw):
    return hashlib.sha1(re.sub(r'\s', '', raw).encode()).hexdigest()[:20]


def is_ping(p):
    ops = (p or {}).get('ops') or []
    return not ops or all(o.get('op') == 'data' and o.get('key') in ('__ping', 'ping') for o in ops)


def resolve(p, head, routes):
    """(route, None) or (None, reason). Never falls back to a default report."""
    if not isinstance(p, dict):
        return None, 'undecodable package'
    toks = by_token(routes)
    tok = p.get('file') or p.get('file_token') or ''
    if tok:
        r = toks.get(tok)
        if not r:
            return None, 'unknown file_token %s (add a route to sync_routes.json)' % tok
    else:
        hits = [x for x in routes if p.get('ver') and p.get('ver') in (x.get('legacy_unlabelled_ver') or [])]
        if len(hits) != 1:
            return None, 'package has no file_token (client ver %r is not a registered legacy client)' % p.get('ver')
        r = hits[0]
    rep = str(p.get('rep') or '').strip()
    if rep and r.get('rep') and rep != r['rep'] and rep not in (r.get('rep_aliases') or []):
        return None, 'rep %s conflicts with token %s (%s)' % (rep, r['token'], r['label'])
    title = str(p.get('title') or head or '')
    kws = r.get('title_keywords') or []
    others = [k for x in routes if x is not r for k in (x.get('title_keywords') or []) if k not in kws]
    if title and not any(k in title for k in kws) and any(k in title for k in others):
        return None, 'title %r conflicts with token %s (%s)' % (title[:40], r['token'], r['label'])
    return r, None


# ───────────────────────── inject-token ─────────────────────────

def _set_const(line, name, value):
    rx = re.compile(r'''(\b%s\s*=\s*)(['"])[^'"]*\2''' % name)
    if rx.search(line):
        return rx.sub(lambda m: m.group(1) + "'" + value + "'", line, 1)
    return line[:-1] + ", %s='%s';" % (name, value)


def inject_token(src, token, webhook=None, inbox=None):
    """Set SAVE_FILE_TOKEN (and optionally SYNC_WEBHOOK / SYNC_INBOX) on the single `const SYNC_VER=…;`
    line. Nothing else in the page changes."""
    if not TOKEN_RE.match(token):
        raise ValueError('bad token %r' % token)
    lines = CONST_RE.findall(src)
    if len(lines) != 1:
        raise ValueError('expected exactly one `const SYNC_VER=…;` line, found %d' % len(lines))
    old = lines[0]
    new = _set_const(old, 'SAVE_FILE_TOKEN', token)
    if webhook is not None:
        new = _set_const(new, 'SYNC_WEBHOOK', webhook)
    if inbox is not None:
        new = _set_const(new, 'SYNC_INBOX', inbox)
    return src.replace(old, new, 1), old, new


CLIENT_RE = re.compile(r"(SDMCSYNC1:'\+b64\(JSON\.stringify\(\{)ver:SYNC_VER,")


def patch_client(src, token, rep=None):
    """Make an old client (e.g. 华曦达 v46) send its own token: set SAVE_FILE_TOKEN if needed and add
    `file:SAVE_FILE_TOKEN` (+ `rep`) to the one SDMCSYNC1 package literal. Returns (html, list of changes)."""
    changes = []
    if master_token(src) != [token]:
        src, old, new = inject_token(src, token)
        changes.append((old, new))
    if re.search(r"SDMCSYNC1:'\+b64\(JSON\.stringify\(\{ver:SYNC_VER,file:", src):
        return src, changes
    hits = CLIENT_RE.findall(src)
    if len(hits) != 1:
        raise ValueError('expected exactly one SDMCSYNC1 package literal `{ver:SYNC_VER,…}`, found %d' % len(hits))
    add = 'file:SAVE_FILE_TOKEN,' + ("rep:'%s'," % rep if rep else '')
    if rep and not re.match(r'^[A-Za-z0-9_-]+$', rep):
        raise ValueError('bad rep %r' % rep)
    src = CLIENT_RE.sub(lambda m: m.group(1) + 'ver:SYNC_VER,' + add, src, count=1)
    changes.append(('{ver:SYNC_VER,', '{ver:SYNC_VER,' + add))
    return src, changes


def _md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'check':
        path = argv[1] if len(argv) > 1 else DEFAULT_ROUTES
        routes = load_routes(path)
        errs, warns = check_routes(routes)
        for r in routes:
            print('route %s  %-14s rep=%-16s confirmed=%-5s master=%s' % (
                r.get('token'), r.get('label'), r.get('rep') or '-', bool(r.get('derek_confirmed')), r.get('master')))
        for w in warns:
            print('WARN ', w)
        for e in errs:
            print('ERROR', e)
        print('routes OK' if not errs else 'routes INVALID (%d errors)' % len(errs))
        return 1 if errs else 0
    if argv and argv[0] == 'inject-token' and len(argv) >= 4:
        src_p, dst_p, token = argv[1:4]
        opt = dict(zip(argv[4::2], argv[5::2]))
        with open(src_p, encoding='utf-8') as f:
            src = f.read()
        out, old, new = inject_token(src, token, opt.get('--webhook'), opt.get('--inbox'))
        if os.path.abspath(src_p) != os.path.abspath(dst_p) and os.path.exists(dst_p):
            raise SystemExit('refusing to overwrite existing %s' % dst_p)
        os.makedirs(os.path.dirname(os.path.abspath(dst_p)), exist_ok=True)
        with open(dst_p, 'w', encoding='utf-8') as f:
            f.write(out)
        print('src', _md5(src_p), src_p)
        print('dst', _md5(dst_p), dst_p)
        print('-', old)
        print('+', new)
        return 0
    if argv and argv[0] == 'patch-client' and len(argv) >= 3:
        path, token = argv[1:3]
        opt = dict(zip(argv[3::2], argv[4::2]))
        with open(path, encoding='utf-8') as f:
            src = f.read()
        out, changes = patch_client(src, token, opt.get('--rep'))
        print('master', _md5(path), path)
        if not changes:
            print('already sends file=%s; unchanged' % token)
            return 0
        bak = '%s.pre_client_%s' % (path, time.strftime('%Y%m%d_%H%M%S'))
        shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        for old, new in changes:
            print('-', old)
            print('+', new)
        print('patched', _md5(path), '(backup %s)' % bak)
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
