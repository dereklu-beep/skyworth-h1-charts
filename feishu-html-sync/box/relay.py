#!/usr/bin/env python3
"""Box relay: receives SDMCSYNC1 packages and drives apply → same-link Feishu updates.

  POST /sync            package (JSON {text}/{content:{text}} or raw text/plain) → drop + status + apply
  GET  /status/<id>     apply result for one package (JSON; ?cb=fn for JSONP — works without CORS)
  GET  /rev             current master sync-rev (JSON / JSONP)
  GET  /, /chrome       hosted editable report (text/html, never an attachment)
  GET  /health
  GET  /oauth/callback  one-time user-identity authorisation (feishu_auth)

No route uploads a new Drive file or creates a docx: every Feishu write targets the configured tokens.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402

B = 'https://open.feishu.cn/open-apis'
PKG_RE = re.compile(r'SDMCSYNC1:([A-Za-z0-9+/=\s]+?):END')
RECV_RE = re.compile(r'^RECV_TS:\s*(\S+)', re.M)
CB_RE = re.compile(r'^[A-Za-z_$][\w$.]{0,63}$')
ID_RE = re.compile(r'[^A-Za-z0-9_.-]')
MAX_BODY = 5_000_000


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def log(msg):
    sys.stderr.write('[relay %s] %s\n' % (datetime.now().strftime('%H:%M:%S'), msg))


# ───────────────────────── packages ─────────────────────────

def extract_sync_text(body):
    """Accept raw text, {text}, or Feishu-bot style {msg_type, content:{text}}."""
    if isinstance(body, str):
        return body
    if not isinstance(body, dict):
        return ''
    if isinstance(body.get('text'), str):
        return body['text']
    c = body.get('content')
    if isinstance(c, dict) and isinstance(c.get('text'), str):
        return c['text']
    if isinstance(c, str):
        try:
            c2 = json.loads(c)
            if isinstance(c2, dict) and isinstance(c2.get('text'), str):
                return c2['text']
        except ValueError:
            return c
    return body.get('msg') or ''


def packages(text):
    """[(pkg, raw_base64)] for every decodable package in text."""
    out = []
    for m in PKG_RE.finditer(text or ''):
        try:
            raw = re.sub(r'\s', '', m.group(1))
            p = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4)).decode('utf-8'))
            if isinstance(p, dict):
                out.append((p, raw))
        except Exception:
            continue
    return out


def encode_pkg(p):
    return base64.b64encode(json.dumps(p, ensure_ascii=False).encode('utf-8')).decode()


def route(p):
    """(rep, how, None) or (None, None, reason). Only `rep` decides the report — never the shared marker."""
    name = p.get('rep') or p.get('report')
    if name:
        rep = config.resolve_rep(name)
        if not rep:
            return None, None, 'unknown rep %r' % str(name)[:40]
        how = 'rep'
    else:
        rep = config.legacy_rep(p.get('ver'))
        if not rep:
            return None, None, 'missing rep (client ver %r is not a registered legacy client)' % p.get('ver')
        how = 'legacy-ver'
    r = config.report(rep)
    tok = p.get('file_token') or p.get('file')
    own = {r.get('drive_file_token'), r.get('report_docx_token')} - {'', None}
    if tok and own and tok not in own:
        return None, None, 'file token %s does not belong to %s' % (tok, rep)
    if tok and not own and config.rep_for_token(tok):
        return None, None, 'file token %s belongs to %s, not %s' % (tok, config.rep_for_token(tok), rep)
    if not os.path.isfile(r['master_html']):
        return None, None, 'report %s not provisioned on box (no master_html)' % rep
    return rep, how, None


def is_real(p):
    return any(isinstance(o, dict) and (o.get('op') in ('edit', 'del') or
                                        (o.get('op') == 'data' and not str(o.get('key', '')).startswith('__')))
               for o in p.get('ops') or [])


def pkg_id(p):
    return ID_RE.sub('_', str(p.get('id') or p.get('ts') or ''))


# ───────────────────────── status files ─────────────────────────

def status_dir():
    return os.path.join(config.get('state_dir'), 'sync_status')


def held_dir():
    return os.path.join(config.get('relay_dir'), 'held')


def read_status(pid):
    try:
        with open(os.path.join(status_dir(), ID_RE.sub('_', pid) + '.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_status(pid, **fields):
    if not pid:
        return
    d = status_dir()
    os.makedirs(d, exist_ok=True)
    cur = read_status(pid) or {'id': pid}
    cur.update(fields, updated=now_iso())
    p = os.path.join(d, ID_RE.sub('_', pid) + '.json')
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False)
    os.replace(p + '.tmp', p)
    push_edge_status(pid, cur)


def push_edge_status(pid, st):
    edge, tok = (config.get('edge_url') or '').rstrip('/'), config.get('edge_admin_token')
    if not (edge and tok):
        return
    try:
        import requests
        requests.post('%s/api/status/%s' % (edge, pid), json=st, timeout=15, headers={'Authorization': 'Bearer ' + tok})
    except Exception as e:
        log('edge status push failed: %r' % (e,))


def master_rev(rep=None):
    try:
        with open(config.report(rep or config.get('default_report'))['master_html'], encoding='utf-8') as f:
            head = f.read(4000)
        m = re.search(r'<meta\s+name="sync-rev"\s+content="([^"]*)"', head, re.I)
        return m.group(1) if m else ''
    except (OSError, KeyError):
        return ''


# ───────────────────────── Feishu inbox (audit copy, user identity) ─────────────────────────

def inbox_children(text, chunk=1800):
    kids = []
    for line in text.split('\n'):
        for i in range(0, max(1, len(line)), chunk):
            kids.append({'block_type': 2, 'text': {'elements': [{'text_run': {'content': line[i:i + chunk] or ' '}}], 'style': {}}})
    return kids


def append_inbox(text, batch=50):
    """Append every line (in batches of 50 blocks) — the old 40-block cap truncated packages mid-base64."""
    tok = config.get('inbox_docx_token')
    if not tok:
        return {'skipped': True}
    import requests
    import feishu_auth
    kids, codes = inbox_children(text), []
    for k in range(0, len(kids), batch):
        r = requests.post('%s/docx/v1/documents/%s/blocks/%s/children' % (B, tok, tok), headers=feishu_auth.headers('user'),
                          params={'document_revision_id': -1}, json={'index': -1, 'children': kids[k:k + batch]}, timeout=60).json()
        codes.append(r.get('code'))
        if r.get('code') != 0:
            break
        time.sleep(0.35)
    return {'code': next((c for c in codes if c != 0), 0), 'batches': len(codes)}


# ───────────────────────── apply pipeline (per report, serialised) ─────────────────────────

class Pipeline:
    def __init__(self):
        self.lock = threading.Lock()
        self.timers, self.pending, self.last = {}, set(), {}
        self.plock = threading.Lock()

    def kick(self, rep, delay=None):
        delay = config.get('apply_debounce_s') if delay is None else delay
        with self.plock:
            t = self.timers.get(rep)
            if t:
                t.cancel()
            t = self.timers[rep] = threading.Timer(delay, self._run, args=(rep,))
            t.daemon = True
            t.start()

    def _run(self, rep):
        with self.plock:
            self.pending.add(rep)
        with self.lock:
            with self.plock:
                if rep not in self.pending:
                    return
                self.pending.discard(rep)
            try:
                self.last[rep] = self.once(rep)
            except Exception as e:
                log('pipeline error %s %r' % (rep, e))
                self.last[rep] = {'error': repr(e)}

    def once(self, rep):
        r = config.report(rep)
        names = [rep] + list(r.get('aliases') or [])
        cmd = [sys.executable, os.path.join(HERE, 'sync_pull.py'), '--target', r['master_html'], '--no-inbox',
               '--drops', r['drops_dir'], '--status-dir', status_dir(), '--log', os.path.join(r['state_dir'], 'sync_applied.json'),
               '--rep'] + names
        if r.get('legacy_unlabelled_ver'):
            cmd += ['--accept-unlabelled-ver'] + list(r['legacy_unlabelled_ver'])
        env = dict(os.environ, SYNC_STATE_DIR=r['state_dir'])
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
        out = (p.stdout or '') + (p.stderr or '')
        os.makedirs(r['state_dir'], exist_ok=True)
        with open(os.path.join(r['state_dir'], 'last_apply.log'), 'w', encoding='utf-8') as f:
            f.write(out)
        m = re.search(r'^SYNC_RESULT (.*)$', out, re.M)
        res = json.loads(m.group(1)) if m else {'packages': [], 'error': out[-400:]}
        ids = [x['id'] for x in res.get('packages') or []]
        for pid in ids:
            st = read_status(pid) or {}
            write_status(pid, rep=rep, stage='applied' if st.get('written') else ('unresolved' if st.get('unresolved') else 'nochange'))
        if not res.get('written'):
            return res
        res['drive'] = res['docx'] = None
        if config.get('push_drive') and r.get('drive_file_token'):
            res['drive'] = self.step([os.path.join(HERE, 'replace.py'), '--rep', rep, r['drive_file_token'], r['master_html']])
        else:
            res['drive'] = self.step([os.path.join(HERE, 'replace.py'), '--rep', rep, '--publish-only', r['master_html']])
        if config.get('push_docx') and r.get('report_docx_token'):
            res['docx'] = self.step([os.path.join(HERE, 'docx_sync.py'), '--doc', r['report_docx_token'], '--html', r['master_html']])
        for pid in ids:
            write_status(pid, stage='feishu' if all(v in (None, 'ok') for v in (res['drive'], res['docx'])) else 'feishu_error',
                         drive=res['drive'], docx=res['docx'])
        return res

    @staticmethod
    def step(args):
        p = subprocess.run([sys.executable] + args, capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            log('step failed %s: %s' % (os.path.basename(args[0]), (p.stderr or p.stdout)[-300:]))
            return 'error: ' + ((p.stderr or p.stdout).strip().splitlines() or ['?'])[-1][:200]
        return 'ok'


PIPE = Pipeline()


def status_key(p, raw):
    """Same key sync_pull uses: id, else ts, else a hash of the package text."""
    return pkg_id(p) or 'h' + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _write_drop(d, recv_ts, source, raw, extra=''):
    os.makedirs(d, exist_ok=True)
    drop = os.path.join(d, 'drop_%s_%s.txt' % (datetime.now().strftime('%Y%m%d_%H%M%S_%f'), source))
    with open(drop + '.tmp', 'w', encoding='utf-8') as f:
        f.write('RECV_TS: %s\nSOURCE: %s\n%sSDMCSYNC1:%s:END\n' % (recv_ts, source, extra, raw))
    os.replace(drop + '.tmp', drop)
    return drop


def receive(text, recv_ts=None, source='direct'):
    """Route each package by its `rep` to that report's drops; unknown/missing rep → held. (http_code, body)."""
    if 'SDMCSYNC1:' not in (text or ''):
        return 400, {'error': 'no SDMCSYNC1 package', 'len': len(text or '')}
    pk = [(p, raw) for p, raw in packages(text) if is_real(p)]
    if not pk:
        return 400, {'error': 'no real edit/del ops (ping ignored or package truncated)', 'len': len(text)}
    recv_ts = recv_ts or now_iso()
    routed, held, kick = [], [], set()
    for p, raw in pk:
        pid = status_key(p, raw)
        rep, how, why = route(p)
        base = dict(ts=p.get('ts') or recv_ts, ts_missing=not p.get('ts'), recv_ts=recv_ts, source=source,
                    ops=len(p.get('ops') or []), rep_sent=p.get('rep') or p.get('report') or '')
        if rep is None:
            d = os.path.join(held_dir(), ID_RE.sub('_', str(base['rep_sent']) or '_missing')[:40])
            drop = _write_drop(d, recv_ts, source, raw, 'HELD: %s\n' % why)
            write_status(pid, stage='held', reason=why, held=drop, **base)
            held.append({'id': pid, 'reason': why})
            log('HELD %s: %s' % (pid, why))
            continue
        _write_drop(config.report(rep)['drops_dir'], recv_ts, source, raw, 'REP: %s (%s)\n' % (rep, how))
        if not read_status(pid):
            write_status(pid, stage='received', rep=rep, route=how, **base)
        routed.append({'id': pid, 'rep': rep, 'route': how})
        kick.add(rep)
    inbox = None
    if config.get('append_inbox'):
        try:
            inbox = append_inbox(text)
        except Exception as e:
            inbox = {'error': repr(e)[:200]}
    if config.get('auto_apply'):
        for rep in kick:
            PIPE.kick(rep)
    code = 200 if routed else 202
    return code, {'ok': bool(routed), 'routed': routed, 'held': held, 'ids': [x['id'] for x in routed + held],
                  'inbox': inbox, 'recv_ts': recv_ts}


def release(held_file, rep):
    """Operator action: re-label a held package with `rep` and queue it for that report."""
    rep = config.resolve_rep(rep) or rep
    config.report(rep)
    with open(held_file, encoding='utf-8') as f:
        text = f.read()
    (p, raw), = packages(text)
    p['rep'] = rep
    p.setdefault('id', status_key(p, raw))
    rec = (RECV_RE.search(text) or [None, now_iso()])[1]
    _write_drop(config.report(rep)['drops_dir'], rec, 'release', encode_pkg(p), 'REP: %s (released)\n' % rep)
    os.replace(held_file, held_file + '.released')
    write_status(p['id'], stage='received', rep=rep, route='released')
    return p['id']


# ───────────────────────── HTTP ─────────────────────────

def origin_allowed(origin):
    if not origin:
        return False
    for pat in config.get('allowed_origins'):
        if pat == origin:
            return True
        if '*' in pat and re.fullmatch(re.escape(pat).replace(r'\*', r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*'), origin):
            return True
    return False


class R(BaseHTTPRequestHandler):
    server_version = 'sdmc-relay/2'

    def log_message(self, fmt, *args):
        log(fmt % args)

    def cors(self):
        o = self.headers.get('Origin')
        if origin_allowed(o):
            self.send_header('Access-Control-Allow-Origin', o)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Headers', 'content-type')
            self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Access-Control-Max-Age', '600')

    def out(self, code, obj, cb=None):
        if cb and CB_RE.match(cb):
            b = ('/**/%s(%s);' % (cb, json.dumps(obj, ensure_ascii=False))).encode()
            ctype = 'application/javascript; charset=utf-8'
        else:
            b = json.dumps(obj, ensure_ascii=False).encode()
            ctype = 'application/json; charset=utf-8'
        self.send_response(code)
        self.cors()
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def send_html(self, path):
        if not os.path.isfile(path):
            return self.out(404, {'error': 'hosted html missing'})
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store, max-age=0')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        cb = (q.get('cb') or [''])[0]
        if u.path in ('/', '/chrome', '/report', '/report.html'):
            return self.send_html(config.report(config.get('default_report'))['hosted_html'])
        if u.path.startswith('/r/'):
            rep = config.resolve_rep(u.path[3:].strip('/'))
            if not rep:
                return self.out(404, {'error': 'unknown report'})
            return self.send_html(config.report(rep)['hosted_html'])
        if u.path == '/health':
            return self.out(200, {'ok': True, 'service': 'sdmc-relay', 'edge': bool(config.get('edge_url')),
                                  'reports': {k: {'rev': master_rev(k), 'provisioned': os.path.isfile(r['master_html']),
                                                  'drive': bool(r.get('drive_file_token')), 'docx': bool(r.get('report_docx_token')),
                                                  'last': PIPE.last.get(k)} for k, r in config.reports().items()},
                                  'held': sum(1 for _, _, fs in os.walk(held_dir()) for f in fs if f.endswith('.txt'))})
        if u.path == '/rev':
            rep = config.resolve_rep((q.get('rep') or [''])[0]) or config.get('default_report')
            return self.out(200, {'rep': rep, 'rev': master_rev(rep)}, cb)
        if u.path.startswith('/status/'):
            st = read_status(u.path[len('/status/'):])
            return self.out(200 if st else 404, st or {'error': 'unknown id', 'stage': 'unknown'}, cb)
        if u.path == '/oauth/callback':
            code = (q.get('code') or [''])[0]
            try:
                import feishu_auth
                feishu_auth.exchange(code)
                return self.out(200, {'ok': True, 'msg': 'user identity saved on box'})
            except Exception as e:
                return self.out(400, {'error': repr(e)[:200]})
        self.out(404, {'error': 'nf'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            return self.out(413, {'error': 'too big'})
        raw = self.rfile.read(n).decode('utf-8', 'replace')
        u = urlparse(self.path)
        if u.path not in ('/sync', '/inbox'):
            return self.out(404, {'error': 'nf (full-page save/saveas removed: sync is surgical, same link only)'})
        try:
            j = json.loads(raw)
        except ValueError:
            j = None
        text = extract_sync_text(j) if j is not None else raw
        recv = self.headers.get('X-Recv-Ts') or (j.get('recv_ts') if isinstance(j, dict) else None)
        src = (j.get('source') if isinstance(j, dict) else None) or self.headers.get('X-Sync-Source') or 'direct'
        code, body = receive(text, recv, ID_RE.sub('_', str(src))[:20])
        self.out(code, body)


def serve(host=None, port=None):
    c = config.load()
    srv = ThreadingHTTPServer((host or c['relay_host'], int(port or c['relay_port'])), R)
    log('listening %s:%s master=%s' % (srv.server_address[0], srv.server_address[1], c['master_html']))
    return srv


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'release':
        print('released as', release(sys.argv[2], sys.argv[3]))
    else:
        serve().serve_forever()
