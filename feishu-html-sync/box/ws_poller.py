#!/usr/bin/env python3
"""Pull queued browser packages from the public front and hand them to the box relay /sync.

Sources (both outbound HTTPS from the box — no inbound tunnel needed):
  edge         Cloudflare Worker queue  GET {edge_url}/api/queue → POST /api/ack   (preferred)
  webhook.site legacy CORS catcher      GET /token/<t>/requests  → DELETE /request/<uuid>

  python3 ws_poller.py                   # auto: edge if edge_url is configured, plus webhook.site if a token exists
  python3 ws_poller.py --source edge --once

A request is acknowledged/deleted only after the relay accepted it (HTTP 200) or rejected it as
not-a-sync (400). If the relay is down, it is retried next round.
"""
import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402


def _requests():
    import requests
    return requests


def log(msg):
    line = '%s %s' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(os.path.join(config.get('relay_dir'), 'ws_poller.log'), 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass


def relay_url():
    return 'http://%s:%s/sync' % (config.get('relay_host'), config.get('relay_port'))


def forward(text, recv_ts, source):
    """True when the item is finished (accepted or permanently rejected)."""
    try:
        r = _requests().post(relay_url(), json={'text': text, 'recv_ts': recv_ts, 'source': source}, timeout=60)
    except Exception as e:
        log('relay unreachable (%r); will retry' % (e,))
        return False
    log('forward %s → relay %s %s' % (source, r.status_code, r.text[:160]))
    return r.status_code in (200, 400, 413)


# ───────────────────────── webhook.site ─────────────────────────

def ws_token():
    p = config.get('webhook_site_token_file')
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return ''


def ws_text(req):
    body = req.get('content') or ''
    if not body and req.get('content_base64'):
        body = base64.b64decode(req['content_base64']).decode('utf-8', 'replace')
    try:
        j = json.loads(body)
    except (ValueError, TypeError):
        return body if isinstance(body, str) else ''
    if isinstance(j, dict):
        if isinstance(j.get('text'), str):
            return j['text']
        c = j.get('content')
        if isinstance(c, dict) and isinstance(c.get('text'), str):
            return c['text']
        if isinstance(c, str):
            return c
    return body


def ws_recv_ts(req):
    """webhook.site created_at is 'YYYY-MM-DD HH:MM:SS' in UTC."""
    c = req.get('created_at') or ''
    return c.replace(' ', 'T') + '.000Z' if len(c) == 19 else None


class Seen:
    def __init__(self, path):
        self.path = path
        try:
            with open(path) as f:
                self.s = list(json.load(f))
        except (OSError, ValueError):
            self.s = []

    def __contains__(self, k):
        return k in self.s

    def add(self, k):
        self.s.append(k)
        self.s = self.s[-1000:]
        with open(self.path + '.tmp', 'w') as f:
            json.dump(self.s, f)
        os.replace(self.path + '.tmp', self.path)


def poll_webhook_site(seen, tok):
    api = 'https://webhook.site/token/%s' % tok
    r = _requests().get(api + '/requests', params={'sorting': 'oldest', 'per_page': 50}, timeout=30)
    r.raise_for_status()
    for req in (r.json() or {}).get('data') or []:
        rid = req.get('uuid')
        if not rid or rid in seen:
            continue
        text = ws_text(req)
        if 'SDMCSYNC1:' not in text:
            done = True
        else:
            done = forward(text, ws_recv_ts(req), 'webhook.site')
        if not done:
            break
        seen.add(rid)
        if config.get('webhook_site_delete_after_forward'):
            try:
                _requests().delete('%s/request/%s' % (api, rid), timeout=30)
            except Exception as e:
                log('webhook.site delete failed %r' % (e,))


# ───────────────────────── edge worker ─────────────────────────

def poll_edge(edge, tok):
    H = {'Authorization': 'Bearer ' + tok}
    r = _requests().get(edge + '/api/queue', headers=H, timeout=30)
    r.raise_for_status()
    acked = []
    for it in (r.json() or {}).get('items') or []:
        if not forward(it.get('text') or '', it.get('recv_ts'), 'edge'):
            break
        acked.append(it['key'])
    if acked:
        _requests().post(edge + '/api/ack', headers=H, json={'keys': acked}, timeout=30)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', choices=('auto', 'edge', 'webhook.site'), default='auto')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--interval', type=float, default=3.0)
    a = ap.parse_args(argv)
    seen = Seen(os.path.join(config.get('relay_dir'), 'ws_poller_seen.json'))
    log('poller start source=%s' % a.source)
    while True:
        edge, etok, wtok = (config.get('edge_url') or '').rstrip('/'), config.get('edge_admin_token'), ws_token()
        if a.source in ('auto', 'edge') and edge and etok:
            try:
                poll_edge(edge, etok)
            except Exception as e:
                log('edge poll err %r' % (e,))
        if a.source in ('auto', 'webhook.site') and wtok:
            try:
                poll_webhook_site(seen, wtok)
            except Exception as e:
                log('webhook.site poll err %r' % (e,))
        if a.once:
            return
        time.sleep(a.interval)


if __name__ == '__main__':
    main()
