"""Shared settings for relay / poller / pull / replace / docx_sync.

Values come from DEFAULTS, overridden by the JSON file at $SYNC_CONFIG
(default /workspace/feishu/relay/sync_config.json), overridden by env vars SYNC_<KEY>.

`reports` is the routing registry: every sync package names its report with `rep`; each report has its
own master HTML, drop folder, state, hosted copy and Feishu links. A package is only ever applied to
the report its `rep` resolves to.
"""
import json
import os

DEFAULTS = {
    'feishu_host': 'https://seirobotics.feishu.cn',
    'inbox_docx_token': 'DqEbdn9KCozO0Kx9JrBcazCunXd',
    'entry_docx_token': 'NDFudWZQfo9Pcdx4ar2cnY8Un7d',

    'relay_dir': '/workspace/feishu/relay',
    'user_token_file': '/workspace/feishu/relay/user_token.json',
    'state_dir': '/workspace/feishu/relay/state',

    'relay_host': '127.0.0.1',
    'relay_port': 8787,
    'allowed_origins': ['null', 'https://*.feishu.cn', 'https://*.workers.dev', 'https://*.pinggy.net',
                        'https://*.pinggy.link', 'http://127.0.0.1:8787', 'http://localhost:8787'],
    'append_inbox': True,
    'auto_apply': True,
    'apply_debounce_s': 2.0,
    'push_drive': True,
    'push_docx': True,
    'push_edge': True,

    'edge_url': '',
    'edge_admin_token': '',

    'webhook_site_token_file': '/workspace/feishu/relay/webhook_site_token.txt',
    'webhook_site_delete_after_forward': True,
    'chrome_url_file': '/workspace/feishu/relay/chrome_public_url.txt',

    'default_report': 'huaxida-h1',
    'reports': {
        'huaxida-h1': {
            'title': '华曦达 SDMC｜2026H1 财报分析',
            'aliases': ['华曦达', 'sdmc', 'huaxida'],
            'drive_file_token': 'FXqHbFI37oGOCyxT3NkcVhjnnRg',
            'report_docx_token': '',
            'master_html': '/workspace/sdmc_skyworth/v71_fix/华曦达vs创维财报对比_v71_可编辑.html',
            'state_dir': '/workspace/sdmc_skyworth/v41',
            'drops_dir': '/workspace/sdmc_skyworth/v41/sync_inbox_drops',
            'hosted_html': '/workspace/feishu/relay/hosted/report.html',
            # the live v71 page (built-in v46 client) sends no `rep`; only that exact client version maps here
            'legacy_unlabelled_ver': ['v46'],
        },
        'skyworth-report': {
            'title': '创维财报分析',
            'aliases': ['创维', 'skyworth'],
            'drive_file_token': 'PdxFbDlbDorRAexT1hRcpHuCnBf',
            'report_docx_token': '',
            # confirm the live draft filename on the box; /workspace/sdmc_skyworth is the source of truth
            'master_html': '/workspace/sdmc_skyworth/skyworth/skyworth-report.html',
            'state_dir': '/workspace/sdmc_skyworth/skyworth/sync',
            'drops_dir': '/workspace/sdmc_skyworth/skyworth/sync/drops',
            'hosted_html': '/workspace/feishu/relay/hosted/skyworth-report.html',
            'legacy_unlabelled_ver': [],
        },
    },
}

_cache = {}


def path():
    return os.environ.get('SYNC_CONFIG') or os.path.join(DEFAULTS['relay_dir'], 'sync_config.json')


def load(reload=False):
    p = path()
    if not reload and _cache.get('p') == p:
        return _cache['c']
    c = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            user = json.load(f)
        reps = user.pop('reports', None)
        c.update(user)
        if reps is not None:
            if user.get('replace_reports'):
                c['reports'] = {}
            for k, v in reps.items():
                c['reports'][k] = dict(c['reports'].get(k, {}), **v)
    for k, v in list(c.items()):
        env = os.environ.get('SYNC_' + k.upper())
        if env is None or isinstance(v, dict):
            continue
        if isinstance(v, bool):
            c[k] = env.lower() in ('1', 'true', 'yes')
        elif isinstance(v, (int, float)):
            c[k] = type(v)(env)
        elif isinstance(v, list):
            c[k] = [x.strip() for x in env.split(',') if x.strip()]
        else:
            c[k] = env
    _cache.update(p=p, c=c)
    return c


def get(key):
    return load()[key]


def reports():
    return load()['reports']


def report(rep):
    """Settings for one report (registry entry + slug). KeyError if unknown."""
    r = dict(reports()[rep])
    r['rep'] = rep
    r.setdefault('slug', rep)
    return r


def resolve_rep(name):
    """Registry key for a package's `rep` (key or alias, case-insensitive); None if unknown."""
    if not name:
        return None
    n = str(name).strip().lower()
    for k, r in reports().items():
        if n == k.lower() or n in [a.lower() for a in r.get('aliases') or []]:
            return k
    return None


def rep_for_token(file_token):
    for k, r in reports().items():
        if file_token and file_token in (r.get('drive_file_token'), r.get('report_docx_token')):
            return k
    return None


def legacy_rep(ver):
    """Report that accepts packages WITHOUT `rep` from exactly this client version, if exactly one does."""
    hits = [k for k, r in reports().items() if ver and ver in (r.get('legacy_unlabelled_ver') or [])]
    return hits[0] if len(hits) == 1 else None
