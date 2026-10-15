#!/usr/bin/env python3
"""Inject the review kit (format bar, comments, sync result toast) into a report master. Report content is untouched.

  python3 review_kit.py upgrade MASTER --token TOKEN [--rep REP] [--webhook URL]   # in place, backup MASTER.pre_review_<ts>
  python3 review_kit.py check MASTER [--token TOKEN]                               # exit 1 if not ready

`upgrade` is idempotent: an existing kit block is replaced by the current one. It knows the two live clients:
  创维 template client (`const text=pack(ops);`) and 华曦达 v46 client (`const text=editsText(ops); window.__lastSync=text;`).
For the v46 client it also makes the package carry `file` + `rep` and sets SYNC_WEBHOOK, so it uses the same channel.
"""
import hashlib
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sync_routes  # noqa: E402

KIT_RE = re.compile(r'\n?<style id="sdmc-review-css">[\s\S]*?</style>\n?<script id="sdmc-review">[\s\S]*?</script>\n?')
HOOK = '/*sdmc-review-hook*/'
CLIENTS = {
    'skyworth-v1': ('const text=pack(ops);',
                    '\n  ' + HOOK + 'if(window.SDMCReview){ SDMCReview.send(text,{n:ops.length,webhook:SYNC_WEBHOOK,auth:SYNC_AUTH,'
                    'inbox:SYNC_INBOX,btn:btnSync,download:download,onOk:()=>status("已提交同步 "+ops.length+" 处修改")}); return; }'),
    'huaxida-v46': ('const text=editsText(ops); window.__lastSync=text;',
                    '\n  ' + HOOK + "if(window.SDMCReview&&typeof SYNC_WEBHOOK!=='undefined'&&SYNC_WEBHOOK){ SDMCReview.send(text,"
                    "{n:ops.length,webhook:SYNC_WEBHOOK,inbox:SYNC_INBOX,btn:document.getElementById('bSync'),"
                    "download:()=>{ const b=document.getElementById('bSave'); if(b) b.click(); }}); return; }"),
}


def kit_block():
    with open(os.path.join(HERE, 'review_kit.css'), encoding='utf-8') as f:
        css = f.read()
    with open(os.path.join(HERE, 'review_kit.js'), encoding='utf-8') as f:
        js = f.read()
    if '</style' in css.lower() or '</script' in js.lower():
        raise ValueError('kit source must not contain a closing style/script tag')
    return '\n<style id="sdmc-review-css">\n%s</style>\n<script id="sdmc-review">\n%s</script>\n' % (css, js)


def client_kind(src):
    kinds = [k for k, (anchor, _) in CLIENTS.items() if src.count(anchor) == 1]
    if len(kinds) != 1:
        raise ValueError('unknown or ambiguous sync client (found %s)' % (kinds or 'none'))
    return kinds[0]


def upgrade(src, token, rep=None, webhook=None):
    """Return (html, [change descriptions]). Raises ValueError rather than guessing."""
    changes = []
    kind = client_kind(src)
    if kind == 'huaxida-v46':
        src, ch = sync_routes.patch_client(src, token, rep)
        changes += ['%s -> %s' % c for c in ch]
    elif sync_routes.master_token(src) != [token]:
        src, old, new = sync_routes.inject_token(src, token)
        changes.append('%s -> %s' % (old, new))
    if webhook:
        line = sync_routes.CONST_RE.findall(src)
        if len(line) != 1:
            raise ValueError('expected one `const SYNC_VER=…;` line')
        new = sync_routes._set_const(line[0], 'SYNC_WEBHOOK', webhook)
        if new != line[0]:
            src = src.replace(line[0], new, 1)
            changes.append('SYNC_WEBHOOK=%s' % webhook)
    if HOOK not in src:
        anchor, hook = CLIENTS[kind]
        src = src.replace(anchor, anchor + hook, 1)
        changes.append('sync hook (%s)' % kind)
    n = len(KIT_RE.findall(src))
    if n > 1:
        raise ValueError('page has %d kit blocks' % n)
    stripped = KIT_RE.sub('', src)
    at = stripped.lower().rfind('</body>')
    if at < 0:
        raise ValueError('no </body>')
    out = stripped[:at] + kit_block() + stripped[at:]
    if out != src:
        changes.append('review kit %s' % ('replaced' if n else 'added'))
    return out, changes


def check(src, token=None):
    errs = []
    try:
        kind = client_kind(src)
    except ValueError as e:
        return ['%s' % e]
    toks = sync_routes.master_token(src)
    if len(set(toks)) != 1 or (token and toks[0] != token):
        errs.append('SAVE_FILE_TOKEN %s' % (','.join(toks) or 'missing'))
    if HOOK not in src:
        errs.append('sync hook missing')
    if len(KIT_RE.findall(src)) != 1:
        errs.append('review kit block missing')
    if not re.search(r"SYNC_WEBHOOK='https://[^']+'", src):
        errs.append('SYNC_WEBHOOK not set')
    if kind == 'huaxida-v46' and 'file:SAVE_FILE_TOKEN' not in src:
        errs.append('client does not send file')
    return errs


def _md5(p):
    with open(p, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 2 and a[0] in ('upgrade', 'check'):
        path, opt = a[1], dict(zip(a[2::2], a[3::2]))
        with open(path, encoding='utf-8') as f:
            src = f.read()
        if a[0] == 'check':
            errs = check(src, opt.get('--token'))
            for e in errs:
                print('ERROR', e)
            print('%s: %s' % (path, 'review kit OK' if not errs else 'NOT READY'))
            return 1 if errs else 0
        if not opt.get('--token'):
            raise SystemExit('--token is required')
        out, changes = upgrade(src, opt['--token'], opt.get('--rep'), opt.get('--webhook'))
        print('master', _md5(path), len(src.encode()), 'bytes', path)
        if out == src:
            print('already up to date')
            return 0
        bak = '%s.pre_review_%s' % (path, time.strftime('%Y%m%d_%H%M%S'))
        shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        for c in changes:
            print(' +', c)
        print('upgraded', _md5(path), len(out.encode()), 'bytes (backup %s)' % bak)
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
