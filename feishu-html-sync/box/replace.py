#!/usr/bin/env python3
"""Overwrite the existing Feishu Drive HTML file in place (same file_token / same link, new version),
then republish the hosted Chrome copy (relay /chrome and the edge worker).

  python3 replace.py [--rep R] <file_token> <path.html>     # same CLI as before
  python3 replace.py [--rep R] --publish-only <path.html>   # hosted copies only (no Feishu write)

Cross-report guard: the token must be the registered Drive token of the report (config `reports`), and
the HTML's <meta name="report-id"|"report-name"> (when present) must resolve to that same report.

Gated: refused (exit 3, before any network call) unless config feishu_live_writes and the report's
derek_confirmed are both true — the same-link replace runs on the box only after Derek confirms.
Writes use Derek's user identity (feishu_auth). There is deliberately no code path that uploads
without file_token: a call that would create a new Drive file is refused.
"""
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402
import feishu_auth  # noqa: E402

B = 'https://open.feishu.cn/open-apis'
REV_RE = re.compile(rb'<meta\s+name="sync-rev"\s+content="([^"]*)"', re.I)
META_RE = re.compile(rb'<meta\s+name="report-(?:id|name)"\s+content="([^"]*)"', re.I)


def _requests():
    import requests
    return requests


def _meta(H, token):
    j = _requests().post(B + '/drive/v1/metas/batch_query', headers=H,
                         json={'request_docs': [{'doc_token': token, 'doc_type': 'file'}]}, timeout=30).json()
    m = (j.get('data') or {}).get('metas') or []
    return m[0] if m else None


def page_rev(data):
    m = REV_RE.search(data)
    return m.group(1).decode() if m else ''


def check_pair(file_token, data, rep=None):
    """Return the report key, or raise if token / HTML / rep disagree."""
    owner = config.rep_for_token(file_token)
    if not owner:
        raise RuntimeError('file_token %s is not registered to any report in sync_config reports' % file_token)
    if rep and config.resolve_rep(rep) != owner:
        raise RuntimeError('file_token %s belongs to %s, not %s' % (file_token, owner, rep))
    for m in META_RE.finditer(data[:20000]):
        named = config.resolve_rep(m.group(1).decode('utf-8', 'replace'))
        if named and named != owner:
            raise RuntimeError('HTML is report %s but file_token %s belongs to %s' % (named, file_token, owner))
    return owner


def replace_file_content(file_token, local_path, file_name=None, verify=True, identity='user', rep=None):
    if not file_token:
        raise RuntimeError('refusing to upload without file_token (would create a new Drive file)')
    with open(local_path, 'rb') as f:
        data = f.read()
    rep = check_pair(file_token, data, rep)
    config.require_live(rep, 'Drive replace of %s' % file_token)
    H = feishu_auth.headers(identity)
    if file_name is None:
        m = _meta(H, file_token)
        if not m:
            raise RuntimeError('file_token %s not visible to this identity; check Derek has edit access' % file_token)
        file_name = m.get('title') or os.path.basename(local_path)
    form = {'file_name': file_name, 'parent_type': 'explorer', 'size': str(len(data)), 'file_token': file_token}
    r = _requests().post(B + '/drive/v1/files/upload_all', headers=H, data=form,
                         files={'file': (file_name, data)}, timeout=300).json()
    if r.get('code') != 0:
        raise RuntimeError(r)
    if r['data']['file_token'] != file_token:
        raise RuntimeError('token changed! a new file was created: %s — delete it and check upload_all' % r)
    if verify:
        got = _requests().get('%s/drive/v1/files/%s/download' % (B, file_token), headers=H, timeout=300).content
        if got != data:
            raise RuntimeError('download mismatch after replace')
    pub = publish_hosted(data, rep)
    return {'file_token': file_token, 'version': r['data'].get('version'),
            'url': '%s/file/%s' % (config.get('feishu_host'), file_token), 'publish': pub}


def publish_hosted(data, rep):
    """Refresh the copy Chrome opens: relay-hosted file and (if configured) the edge worker."""
    out = {}
    r = config.report(rep)
    hosted = r['hosted_html']
    try:
        os.makedirs(os.path.dirname(hosted), exist_ok=True)
        tmp = hosted + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, hosted)
        with open(os.path.join(os.path.dirname(hosted), 'last_publish.txt'), 'w') as f:
            f.write('%s bytes=%d rev=%s\n' % (datetime.datetime.now().isoformat(timespec='seconds'), len(data), page_rev(data)))
        out['hosted'] = True
    except OSError as e:
        out['hosted'] = repr(e)
    edge, tok = (config.get('edge_url') or '').rstrip('/'), config.get('edge_admin_token')
    if edge and tok and config.get('push_edge'):
        try:
            resp = _requests().put('%s/api/report/%s' % (edge, r['slug']), data=data, timeout=60,
                                   headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'text/html; charset=utf-8',
                                            'X-Sync-Rev': page_rev(data)})
            out['edge'] = resp.status_code
        except Exception as e:
            out['edge'] = repr(e)
    return out


def main(argv):
    argv = list(argv[1:])
    rep = None
    if len(argv) >= 2 and argv[0] == '--rep':
        rep, argv = argv[1], argv[2:]
    if len(argv) == 2 and argv[0] == '--publish-only':
        with open(argv[1], 'rb') as f:
            data = f.read()
        named = [config.resolve_rep(m.group(1).decode('utf-8', 'replace')) for m in META_RE.finditer(data[:20000])]
        rep = config.resolve_rep(rep) if rep else next((n for n in named if n), None)
        if not rep:
            raise SystemExit('--publish-only needs --rep (HTML has no registered report meta)')
        if any(n and n != rep for n in named):
            raise SystemExit('HTML report meta %s does not match --rep %s' % (named, rep))
        print(publish_hosted(data, rep))
        return
    if len(argv) != 2:
        raise SystemExit(__doc__)
    try:
        print(replace_file_content(argv[0], argv[1], rep=rep))
    except config.GateClosed as e:
        print('GATED', e, file=sys.stderr)
        raise SystemExit(3)


if __name__ == '__main__':
    main(sys.argv)
