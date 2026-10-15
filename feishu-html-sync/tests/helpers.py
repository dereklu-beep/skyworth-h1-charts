import base64
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BOX = os.path.join(HERE, '..', 'box')
sys.path.insert(0, BOX)

FIXTURE = open(os.path.join(HERE, 'fixture_report.html'), encoding='utf-8').read()
SKYWORTH = '''<!doctype html><html><head><meta charset="utf-8"><meta name="report-name" content="skyworth-report"></head>
<body><main><article class="doc" id="doc"><h2 id="sec-a">一、创维概览</h2><p>创维营收 280 亿元。</p>
<table><tr><td>深圳创展</td><td>代工</td></tr></table></article></main></body></html>'''


def write(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def pkg(ops, **kw):
    p = {'ver': 'v2', 'ops': ops}
    p.update(kw)
    return 'SDMCSYNC1:%s:END' % base64.b64encode(json.dumps(p, ensure_ascii=False).encode()).decode()


class Box:
    """Temp box layout with two registered reports and a sync_config.json pointing at it."""

    def __init__(self, **over):
        self.d = tempfile.mkdtemp()
        j = lambda *p: os.path.join(self.d, *p)  # noqa: E731
        for sub in ('hx', 'sw', 'relay'):
            os.makedirs(j(sub))
        write(j('hx', 'master.html'), FIXTURE)
        write(j('sw', 'master.html'), SKYWORTH)
        cfg = {
            'relay_dir': j('relay'), 'state_dir': j('relay', 'state'), 'user_token_file': j('relay', 'user_token.json'),
            'append_inbox': False, 'auto_apply': False, 'push_drive': False, 'push_docx': False, 'push_edge': False,
            'apply_debounce_s': 0.05, 'replace_reports': True,
            'reports': {
                'huaxida-h1': {'aliases': ['华曦达'], 'drive_file_token': 'TOKH', 'report_docx_token': 'DOCH',
                               'master_html': j('hx', 'master.html'), 'state_dir': j('hx', 'state'),
                               'drops_dir': j('hx', 'drops'), 'hosted_html': j('relay', 'hosted', 'hx.html'),
                               'legacy_unlabelled_ver': ['v46']},
                'skyworth-report': {'aliases': ['创维'], 'drive_file_token': 'TOKS', 'report_docx_token': 'DOCS',
                                    'master_html': j('sw', 'master.html'), 'state_dir': j('sw', 'state'),
                                    'drops_dir': j('sw', 'drops'), 'hosted_html': j('relay', 'hosted', 'sw.html'),
                                    'legacy_unlabelled_ver': []},
            },
        }
        cfg.update(over)
        self.cfg_path = j('relay', 'sync_config.json')
        write(self.cfg_path, json.dumps(cfg, ensure_ascii=False))
        self._old = os.environ.get('SYNC_CONFIG')
        os.environ['SYNC_CONFIG'] = self.cfg_path
        import config
        config.load(reload=True)
        self.j = j

    def read(self, *p):
        with open(self.j(*p), encoding='utf-8') as f:
            return f.read()

    def files(self, *p):
        d = self.j(*p)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def close(self):
        if self._old is None:
            os.environ.pop('SYNC_CONFIG', None)
        else:
            os.environ['SYNC_CONFIG'] = self._old
        import config
        config.load(reload=True)
        shutil.rmtree(self.d)
