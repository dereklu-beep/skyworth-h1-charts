#!/usr/bin/env python3
"""Real-browser end-to-end for the template client against a real relay (no Feishu, no tunnel):

  python3 feishu-html-sync/tests/e2e/template_e2e.py

builds a page from template/shell.html + app.js, starts relay.py on a temp box config, then drives headless
Chrome (template_e2e.mjs): edit → 同步修改 → relay → sync_pull → master + hosted copy → status back in the page.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
BOX = os.path.join(ROOT, 'box')

DOC = '''<h2 id="s-rev">一、营收</h2>
<p>营收 41.3 亿元，同比增长 12%。</p>
<p>同上。</p>
<table><thead><tr><th>客户</th><th>营收</th></tr></thead><tbody><tr><td>Claro</td><td>9.8</td></tr><tr><td>TIM</td><td>9.8</td></tr><tr><td>Vivo</td><td>3.1</td></tr><tr><td>Oi</td><td>2.2</td></tr><tr><td>MTN</td><td>1.9</td></tr><tr><td>其他</td><td>14.3</td></tr></tbody></table>
<h2 id="s-risk">二、风险</h2>
<p>同上。</p>
<ul><li>汇率波动。</li><li>客户集中。</li></ul>'''


def build(rep, edge=''):
    shell = open(os.path.join(ROOT, 'template', 'shell.html'), encoding='utf-8').read()
    app = open(os.path.join(ROOT, 'template', 'app.js'), encoding='utf-8').read()
    fill = {'{{NAME}}': '华曦达 SDMC｜2026H1 财报分析', '{{VERSION}}': '3', '{{REPORT_ID}}': rep, '{{SYNC_EDGE}}': edge,
            '{{TITLE}}': '华曦达 e2e', '{{SHORT_TITLE}}': '华曦达', '{{BAR_SUB}}': 'e2e', '{{COVER}}': '<section class="cover"><h1>华曦达</h1></section>',
            '{{DOC}}': DOC, '{{COLOPHON}}': '测试', '{{DATA}}': '{"charts":{}}',
            '/*@@CSS@@*/': '[hidden]{display:none!important}', '/*@@ECHARTS@@*/': 'window.echarts={init(){return{setOption(){},resize(){},dispose(){}}}};',
            '/*@@APP@@*/': app}
    for k, v in fill.items():
        shell = shell.replace(k, v)
    return shell


def main():
    d = tempfile.mkdtemp()
    j = lambda *p: os.path.join(d, *p)  # noqa: E731
    for s in ('hx', 'sw', 'relay/hosted'):
        os.makedirs(j(s))
    page = build('huaxida-h1')
    for p in (j('hx', 'master.html'), j('relay', 'hosted', 'hx.html')):
        open(p, 'w', encoding='utf-8').write(page)
    sw = build('skyworth-report')
    for p in (j('sw', 'master.html'), j('relay', 'hosted', 'sw.html')):
        open(p, 'w', encoding='utf-8').write(sw)
    open(j('relay', 'hosted', 'unlabelled.html'), 'w', encoding='utf-8').write(build(''))
    port = 18000 + os.getpid() % 1000
    cfg = {'relay_dir': j('relay'), 'state_dir': j('relay', 'state'), 'user_token_file': j('relay', 'user_token.json'),
           'relay_port': port, 'append_inbox': False, 'auto_apply': True, 'push_drive': False, 'push_docx': False,
           'push_edge': False, 'apply_debounce_s': 0.2, 'default_report': 'huaxida-h1',
           'reports': {
               'huaxida-h1': {'drive_file_token': 'TOKH', 'master_html': j('hx', 'master.html'), 'state_dir': j('hx', 'state'),
                              'drops_dir': j('hx', 'drops'), 'hosted_html': j('relay', 'hosted', 'hx.html')},
               'skyworth-report': {'drive_file_token': 'TOKS', 'master_html': j('sw', 'master.html'), 'state_dir': j('sw', 'state'),
                                   'drops_dir': j('sw', 'drops'), 'hosted_html': j('relay', 'hosted', 'sw.html')},
               'unlabelled': {'master_html': j('relay', 'hosted', 'unlabelled.html'), 'state_dir': j('relay', 'ux'),
                              'drops_dir': j('relay', 'ux', 'drops'), 'hosted_html': j('relay', 'hosted', 'unlabelled.html')},
           }}
    open(j('relay', 'sync_config.json'), 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False))
    env = dict(os.environ, SYNC_CONFIG=j('relay', 'sync_config.json'))
    relay = subprocess.Popen([sys.executable, os.path.join(BOX, 'relay.py')], env=env, stdout=open(j('relay.log'), 'w'), stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen('http://127.0.0.1:%d/health' % port, timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        r = subprocess.run(['node', os.path.join(HERE, 'template_e2e.mjs'), 'http://127.0.0.1:%d' % port, d], timeout=180)
        if r.returncode:
            print(open(j('relay.log'), encoding='utf-8').read()[-3000:])
        return r.returncode
    finally:
        relay.terminate()
        relay.wait(5)


if __name__ == '__main__':
    sys.exit(main())
