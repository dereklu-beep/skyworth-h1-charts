#!/usr/bin/env python3
"""Feishu user identity (user_access_token) for every write in the sync pipeline.

The pipeline writes as Derek, not as the app/bot. One-time setup (no new bot, uses the existing app):

  python3 feishu_auth.py login              # prints an authorize URL; open it in Chrome, approve
  python3 feishu_auth.py exchange '<url or code>'   # paste the redirected URL (or just the code)
  python3 feishu_auth.py status

After that, refresh tokens rotate automatically (each refresh returns a new refresh_token, saved atomically).
Tenant (bot) identity is only used when FEISHU_ALLOW_TENANT=1 is set explicitly.
"""
import json
import os
import sys
import time
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402

OPEN = 'https://open.feishu.cn/open-apis'
AUTHORIZE = 'https://accounts.feishu.cn/open-apis/authen/v1/authorize'
SCOPES = 'offline_access docx:document drive:drive'


class AuthError(RuntimeError):
    pass


def _requests():
    import requests
    return requests


def _app():
    try:
        return os.environ['FEISHU_APP_ID'], os.environ['FEISHU_APP_SECRET']
    except KeyError:
        raise AuthError('FEISHU_APP_ID / FEISHU_APP_SECRET not set')


def token_file():
    return config.get('user_token_file')


def redirect_uri():
    edge = (config.get('edge_url') or '').rstrip('/')
    return os.environ.get('FEISHU_REDIRECT_URI') or (edge + '/oauth/callback' if edge else
                                                     'http://127.0.0.1:%d/oauth/callback' % config.get('relay_port'))


class _Lock:
    def __init__(self, path):
        self.path = path + '.lock'

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        self.f = open(self.path, 'w')
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *a):
        self.f.close()


def _load():
    try:
        with open(token_file(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(tok):
    p = token_file()
    os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
    tmp = p + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(tok, f, indent=1)
    os.replace(tmp, p)


def _store(resp, now=None):
    now = now or time.time()
    if resp.get('code') not in (0, None) or not resp.get('access_token'):
        raise AuthError('token endpoint error: %s' % {k: resp.get(k) for k in ('code', 'error', 'error_description', 'msg')})
    tok = {
        'access_token': resp['access_token'],
        'expires_at': now + int(resp.get('expires_in') or 7200) - 300,
        'refresh_token': resp.get('refresh_token', ''),
        'refresh_expires_at': now + int(resp.get('refresh_token_expires_in') or 0) - 600,
        'scope': resp.get('scope', ''),
        'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    _save(tok)
    return tok


def _post_token(body):
    app_id, secret = _app()
    body = dict(body, client_id=app_id, client_secret=secret)
    return _requests().post(OPEN + '/authen/v2/oauth/token', json=body, timeout=30).json()


def authorize_url(state='sync'):
    app_id, _ = _app()
    return '%s?client_id=%s&response_type=code&redirect_uri=%s&scope=%s&state=%s' % (
        AUTHORIZE, app_id, quote(redirect_uri(), safe=''), quote(SCOPES, safe=''), state)


def exchange(code_or_url):
    code = code_or_url.strip()
    if code.startswith('http'):
        code = (parse_qs(urlparse(code).query).get('code') or [''])[0]
    if not code:
        raise AuthError('no code found')
    with _Lock(token_file()):
        return _store(_post_token({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri()}))


def user_access_token(now=None):
    now = now or time.time()
    tok = _load()
    if tok.get('access_token') and tok.get('expires_at', 0) > now:
        return tok['access_token']
    with _Lock(token_file()):
        tok = _load()
        if tok.get('access_token') and tok.get('expires_at', 0) > now:
            return tok['access_token']
        if not tok.get('refresh_token'):
            raise AuthError('no user token on box; run: python3 feishu_auth.py login')
        if tok.get('refresh_expires_at') and tok['refresh_expires_at'] < now:
            raise AuthError('user refresh token expired; run: python3 feishu_auth.py login')
        return _store(_post_token({'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token']}), now)['access_token']


_tenant = {'v': None, 'exp': 0}


def tenant_access_token():
    if os.environ.get('FEISHU_ALLOW_TENANT') != '1':
        raise AuthError('tenant identity disabled (writes must be user identity); set FEISHU_ALLOW_TENANT=1 to override')
    if time.time() > _tenant['exp']:
        app_id, secret = _app()
        r = _requests().post(OPEN + '/auth/v3/tenant_access_token/internal',
                             json={'app_id': app_id, 'app_secret': secret}, timeout=30).json()
        _tenant.update(v=r['tenant_access_token'], exp=time.time() + r['expire'] - 300)
    return _tenant['v']


def headers(identity='user'):
    t = tenant_access_token() if identity == 'tenant' else user_access_token()
    return {'Authorization': 'Bearer ' + t}


def status():
    tok = _load()
    if not tok:
        return {'ok': False, 'why': 'no token file', 'file': token_file()}
    now = time.time()
    return {'ok': bool(tok.get('refresh_token')) and tok.get('refresh_expires_at', now + 1) > now,
            'access_valid_s': int(tok.get('expires_at', 0) - now),
            'refresh_valid_days': round((tok.get('refresh_expires_at', 0) - now) / 86400, 1),
            'scope': tok.get('scope'), 'saved_at': tok.get('saved_at'), 'file': token_file()}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'status'
    if cmd == 'login':
        print('1) In the Feishu developer console, add this redirect URL to the EXISTING app (no new bot):')
        print('   ' + redirect_uri())
        print('2) Open in Chrome while logged in as Derek and approve:')
        print('   ' + authorize_url())
        print('3) Copy the address-bar URL you land on (even if the page fails to load) and run:')
        print("   python3 feishu_auth.py exchange '<that url>'")
    elif cmd == 'exchange':
        t = exchange(argv[2])
        print('saved user token; scope=%s' % t.get('scope'))
    elif cmd == 'refresh':
        p = _load()
        p['expires_at'] = 0
        _save(p)
        user_access_token()
        print(json.dumps(status(), ensure_ascii=False))
    else:
        print(json.dumps(status(), ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv)
