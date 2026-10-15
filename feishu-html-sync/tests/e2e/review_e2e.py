#!/usr/bin/env python3
"""Headless-Chrome e2e for the review kit on the two real masters (no Feishu, no tunnel):

  python3 feishu-html-sync/tests/e2e/review_e2e.py [SCREENSHOT_DIR]

Serves the "published" copy of each master (the same link), a fake webhook.site (ok / HTTP 500 / slow / no CORS)
and a CSP-locked variant (Feishu-preview stand-in). The real v41 router + sanitizing puller apply the drops; a fake
replace.py copies the master to the published path. review_e2e.mjs drives the page and takes screenshots.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
V41 = os.path.join(HERE, '..', '..', 'box_v41')
STORE = '/cursor/stores/bc-53a8ae46-622d-513a-8df0-fb556621041b/artifacts'
SW_SRC = os.environ.get('SMOKE_SW_SRC') or os.path.join(STORE, '创维数字专报_入稿终稿.html')
HX_SRC = os.environ.get('SMOKE_HX_SRC') or os.path.join(STORE, '华曦达对比_排版优化.html')
PDX, FXQ = 'PdxFbDlbDorRAexT1hRcpHuCnBf', 'FXqHbFI37oGOCyxT3NkcVhjnnRg'
FAKE_REPLACE = r'''import json, os, shutil, sys
tok, path = sys.argv[1], sys.argv[2]
shutil.copy(path, os.path.join(os.environ['PUBLISHED'], tok + '.html'))
with open(os.environ['FAKE_REPLACE_LOG'], 'a') as f:
    f.write(json.dumps({'token': tok, 'path': path, 'bytes': os.path.getsize(path)}) + '\n')
print({'file_token': tok, 'version': 'fake'})
'''


def main():
    shots = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), 'review_shots')
    os.makedirs(shots, exist_ok=True)
    if not (os.path.isfile(SW_SRC) and os.path.isfile(HX_SRC)):
        print('SKIP: real masters not available')
        return 0
    d = tempfile.mkdtemp()
    v41, pub = os.path.join(d, 'v41'), os.path.join(d, 'published')
    for p in (os.path.join(v41, 'sync_inbox_drops'), pub):
        os.makedirs(p)
    for f in ('sync_watch.py', 'sync_routes.py', 'sync_pull_routed.py', 'review_kit.py', 'review_kit.js', 'review_kit.css'):
        shutil.copy(os.path.join(V41, f), v41)

    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    srv.pub, srv.v41, srv.n = pub, v41, 0
    port = srv.server_address[1]
    hook = 'http://localhost:%d/hook' % port
    sw, hx = os.path.join(d, 'sw_master.html'), os.path.join(d, 'hx_master.html')
    run([sys.executable, os.path.join(v41, 'sync_routes.py'), 'inject-token', SW_SRC, sw, PDX, '--webhook', hook])
    shutil.copy(HX_SRC, hx)
    run([sys.executable, os.path.join(v41, 'review_kit.py'), 'upgrade', sw, '--token', PDX])
    run([sys.executable, os.path.join(v41, 'review_kit.py'), 'upgrade', hx, '--token', FXQ, '--rep', 'huaxida-h1', '--webhook', hook])
    for tok, m in ((PDX, sw), (FXQ, hx)):
        shutil.copy(m, os.path.join(pub, tok + '.html'))
    seed = json.load(open(os.path.join(V41, 'sync_routes.json'), encoding='utf-8'))
    seed['routes'][0]['master'], seed['routes'][1]['master'] = sw, hx
    for r in seed['routes']:
        r['derek_confirmed'] = True
    json.dump(seed, open(os.path.join(v41, 'sync_routes.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    fake = os.path.join(d, 'replace.py')
    open(fake, 'w').write(FAKE_REPLACE)
    calls = os.path.join(d, 'replace_calls.jsonl')
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    env = dict(os.environ, BASE='http://127.0.0.1:%d' % port, SHOTS=shots, PDX=PDX, FXQ=FXQ,
               PASS_CMD=' '.join([sys.executable, os.path.join(v41, 'sync_watch.py'), '--no-inbox']),
               SYNC_REPLACE=fake, FAKE_REPLACE_LOG=calls, PUBLISHED=pub, SYNC_ROUTES=os.path.join(v41, 'sync_routes.json'))
    p = subprocess.run(['node', os.path.join(HERE, 'review_e2e.mjs')], env=env, text=True, capture_output=True, timeout=600)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    srv.shutdown()
    print('workdir', d)
    published = {t: open(os.path.join(pub, t + '.html'), encoding='utf-8').read() for t in (PDX, FXQ)}
    for t, s in published.items():
        if not ('class="fx ' in s and 'fx-cmt' in s):
            print('FAIL formatting/comment not in published %s' % t)
            p.returncode = 1
    print('replace calls:', [json.loads(l)['token'][:5] for l in open(calls)] if os.path.exists(calls) else [])
    if not os.environ.get('KEEP'):
        shutil.rmtree(d)
    return p.returncode


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    return r.stdout


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self, on=True):
        if on:
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'content-type, authorization')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path, _, q = self.path.partition('?')
        name = path.strip('/')
        if name == 'blank':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<!doctype html><title>blank</title>')
            return
        f = os.path.join(self.server.pub, name)
        if not re.match(r'^[A-Za-z0-9]{27}\.html$', name) or not os.path.exists(f):
            self.send_response(404)
            self.end_headers()
            return
        html = open(f, encoding='utf-8').read()
        args = dict(x.split('=', 1) for x in q.split('&') if '=' in x)
        if args.get('hook'):
            html = re.sub(r"(SYNC_WEBHOOK=')[^']*'", lambda m: m.group(1) + 'http://localhost:%d/hook_%s' % (
                self.server.server_address[1], args['hook']) + "'", html, count=1)
        if args.get('csp'):
            html = html.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="connect-src \'none\'">', 1)
        b = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _post(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode('utf-8', 'replace')
        kind = self.path.strip('/')
        if kind == 'hook_500':
            self.send_response(500)
            self._cors()
            self.end_headers()
            return
        if kind == 'hook_slow':
            time.sleep(4)
        if kind in ('hook', 'hook_nocors'):
            try:
                text = json.loads(body).get('text') or body
            except ValueError:
                text = body
            self.server.n += 1
            name = 'drop_%s_%06d.txt' % (time.strftime('%Y%m%d_%H%M%S'), self.server.n)
            with open(os.path.join(self.server.v41, 'sync_inbox_drops', name), 'w', encoding='utf-8') as f:
                f.write(text)
        self.send_response(200)
        self._cors(kind != 'hook_nocors')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


if __name__ == '__main__':
    sys.exit(main())
