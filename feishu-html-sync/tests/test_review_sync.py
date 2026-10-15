#!/usr/bin/env python3
"""Review kit MVP: sanitizer, template-first apply, master upgrade, back-compat. Real masters when available."""
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
V41 = os.path.join(HERE, '..', 'box_v41')
sys.path.insert(0, V41)
import review_kit  # noqa: E402
import sync_pull_routed as sp  # noqa: E402
import sync_routes  # noqa: E402

STORE = '/cursor/stores/bc-53a8ae46-622d-513a-8df0-fb556621041b/artifacts'
SW_SRC = os.environ.get('SMOKE_SW_SRC') or os.path.join(STORE, '创维数字专报_入稿终稿.html')
HX_SRC = os.environ.get('SMOKE_HX_SRC') or os.path.join(STORE, '华曦达对比_排版优化.html')
REAL = os.path.isfile(SW_SRC) and os.path.isfile(HX_SRC)
PDX, FXQ = 'PdxFbDlbDorRAexT1hRcpHuCnBf', 'FXqHbFI37oGOCyxT3NkcVhjnnRg'
HOOK = 'https://webhook.site/00000000-0000-0000-0000-000000000000'
DROPS = os.path.join(HERE, 'fixtures', 'box_drops_20261015')
CAP = '总体判断：四点结论，后文各板块逐一展开'

SW_STUB = ('<!doctype html><html><head><meta name="report-name" content="skyworth-report"></head><body><main id="doc" class="doc">'
           '<header id="s-cover"><h1 data-eid="s-cover.1">创维数字｜2026H1 财报分析</h1></header>'
           '<p data-eid="p1">海外为重心——谁付钱、靠什么增长、钱卡在哪。</p></main><script>(function(){\n'
           "const SYNC_VER='v1', SAVE_FILE_TOKEN='', SAVE_URL='', SYNC_INBOX='', SYNC_WEBHOOK='', SYNC_AUTH='', SYNC_CURSOR_WEBHOOK='';\n"
           'function sync(){ const ops=[]; const text=pack(ops);\n  fetch(SYNC_WEBHOOK); }\n})();</script></body></html>')
HX_STUB = ('<!doctype html><html><head><title>华曦达 SDMC｜2026H1 财报分析</title></head><body><div id="sheet">'
           '<section id="s-concl" data-eid="31"><div class="cap" data-eid="33"><b data-eid="34">%s</b></div>'
           '<ul data-eid="40"><li data-eid="41">风险一：库存</li><li data-eid="42">风险二：汇率</li></ul></section></div>'
           '<template id="report-tpl"><section id="s-concl"><div class="cap"><b>%s</b></div>'
           '<ul><li>风险一：库存</li><li>风险二：汇率</li></ul></section></template>'
           "<script>const SYNC_VER='v46', SAVE_FILE_TOKEN='%s', SAVE_URL='', SYNC_INBOX='https://x.feishu.cn/docx/AAA';\n"
           "function editsText(ops){ const d=new Date(), ts=d.toISOString(), lines=[];\n"
           "  lines.push('SDMCSYNC1:'+b64(JSON.stringify({ver:SYNC_VER,ts,ops}))+':END');\n  return lines.join('\\n'); }\n"
           "function doCopy(open){ const ops=collectEdits();\n  const text=editsText(ops); window.__lastSync=text;\n  copyText(text); }"
           "</script></body></html>") % (CAP, CAP, FXQ)


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def sw_master():
    src = read(SW_SRC) if REAL else SW_STUB
    return sync_routes.inject_token(src, PDX, webhook=HOOK)[0]


def hx_master():
    return read(HX_SRC) if REAL else HX_STUB


def tpl_span(s):
    a = s.index('<template id="report-tpl"')
    return a, s.index('</template>', a)


class Sanitizer(unittest.TestCase):
    VECTORS = [
        '<img src=x onerror=alert(1)>', '<svg onload=alert(1)>', '<a href="javascript:alert(1)">x</a>',
        '<a href=" java&#x09;script:alert(1)">x</a>', '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
        '<script>alert(1)</script>', '<style>*{background:url(//e)}</style>', '<p style="background:url(javascript:1)">x</p>',
        '<span style="x:expression(alert(1))">x</span>', '<object data="javascript:1"></object>', '<embed src="x.swf">',
        '<form action="//e"><input name=a></form>', '<math><mtext><img src=x onerror=1></mtext></math>',
        '<svg><animate attributeName="href" to="javascript:alert(1)"/></svg>', '<svg><foreignObject><img src=x onerror=1></foreignObject></svg>',
        '<base href="//evil/">', '<meta http-equiv="refresh" content="0;url=//e">', '<link rel=stylesheet href=//e>',
        '<mark class="fx fx-cmt" data-cmt="&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;">t</mark>',
        '<div onclick="x()" onmouseover="y()">t</div>', '<a href="data:text/html,<script>alert(1)</script>">x</a>',
    ]

    def test_no_script_vector_survives(self):
        bad = re.compile(r'<(script|iframe|object|embed|style|img|form|input|base|meta|link|math|foreignobject|animate)\b|'
                         r'\son\w+=|javascript:|expression\(|url\(', re.I)
        for v in self.VECTORS:
            out = sp.clean_fragment(v)
            self.assertIsNone(bad.search(out), (v, out))

    def test_review_markup_and_report_markup_kept(self):
        for h in ['<span class="fx fx-f-hei fx-c-red">红</span><mark class="fx fx-hl fx-hl-y">黄</mark>',
                  '<mark class="fx fx-cmt" data-cmt="请核对口径" data-cmt-by="Derek" data-cmt-at="2026-10-15T03:00:00Z">口径</mark>',
                  '<b class="t f it">事实</b> 1 &amp; 2 &nbsp;{{s.gp.fy24|f2}}', '<i class="dot" style="background:var(--sdmc)"></i>x',
                  '<a href="#s-concl">核心结论</a><sup>1</sup><br>', '<span class="nd">未披露</span><span class="cal os">海外口径</span>']:
            self.assertEqual(sp.canon(sp.clean_fragment(h)), sp.canon(h), h)

    def test_fx_elements_lose_runtime_eid(self):
        self.assertEqual(sp.clean_fragment('<span class="fx fx-c-red" data-eid="9">x</span><b data-eid="10">y</b>'),
                         '<span class="fx fx-c-red">x</span><b data-eid="10">y</b>')

    def test_sanitizer_leaves_every_existing_element_of_both_masters_unchanged(self):
        for src in (sw_master(), hx_master()):
            d = sp.Doc(src)
            n = 0
            for e in d.body:
                if e.tag in ('p', 'li', 'td', 'th', 'h1', 'h2', 'h3', 'figcaption') or e.cls() & {'cap', 'src', 'note'}:
                    inner = d.inner(e)
                    if '<svg' in inner or '<img' in inner or '<button' in inner or '<input' in inner:
                        continue
                    self.assertEqual(sp.canon(sp.clean_fragment(inner)), sp.canon(inner), inner[:120])
                    n += 1
            self.assertGreater(n, 5 if REAL else 1)


class TemplateFirst(unittest.TestCase):
    def setUp(self):
        self.s = hx_master()
        self.d = sp.Doc(self.s)

    def test_edit_lands_in_template_and_mirrors_sheet(self):
        cap = self.d.by_eid('33')[0]
        old = self.d.inner(cap)
        new = old.replace(CAP, '<span class="fx fx-c-red">总体判断</span>' + CAP[4:])
        out, res = sp.apply_ops(self.s, [{'op': 'edit', 'eid': '33', 'old': old, 'new': new}])
        self.assertTrue(res[0]['ok'], res)
        a, b = tpl_span(out)
        k = '<span class="fx fx-c-red">总体判断</span>'
        self.assertEqual((out.count(k, a, b), out.count(k, 0, a)), (1, 1))
        self.assertEqual(len(re.findall('data-eid', out[a:b])), len(re.findall('data-eid', self.s[slice(*tpl_span(self.s))])))

    def test_delete_lands_in_template_and_sheet(self):
        li = [e for e in self.d.body if e.tag == 'li' and e.attrs.get('data-eid') and e.s < tpl_span(self.s)[0]][1]
        old, txt = self.d.inner(li), sp.plain(self.d.inner(li))[:12]
        out, res = sp.apply_ops(self.s, [{'op': 'del', 'eid': li.attrs['data-eid'], 'old': old}])
        self.assertTrue(res[0]['ok'], res)
        a, b = tpl_span(out)
        a0, b0 = tpl_span(self.s)
        self.assertEqual(sp.plain(out[a:b]).count(txt), sp.plain(self.s[a0:b0]).count(txt) - 1)
        self.assertEqual(sp.plain(out[:a]).count(txt), sp.plain(self.s[:a0]).count(txt) - 1)

    def test_pages_without_template_unchanged_behaviour(self):
        out, res = sp.apply_ops(SW_STUB, [{'op': 'edit', 'eid': 'p1', 'old': '海外为重心——谁付钱、靠什么增长、钱卡在哪。',
                                           'new': '<span class="fx fx-f-kai">海外为重心</span>——谁付钱、靠什么增长、钱卡在哪。'}])
        self.assertEqual((res[0]['how'], out.count('fx-f-kai')), ('eid', 1))


class Upgrade(unittest.TestCase):
    @staticmethod
    def strip(s):
        s = review_kit.KIT_RE.sub('', s)
        s = re.sub(r'\n  /\*sdmc-review-hook\*/[^\n]*', '', s)
        return s.replace("file:SAVE_FILE_TOKEN,rep:'huaxida-h1',", '')

    def test_upgrade_both_masters_only_adds_kit_hook_and_sync_constants(self):
        for src, tok, rep, hook in ((sw_master(), PDX, None, None), (hx_master(), FXQ, 'huaxida-h1', HOOK)):
            out, ch = review_kit.upgrade(src, tok, rep, hook)
            self.assertEqual(review_kit.check(out, tok), [], ch)
            again, ch2 = review_kit.upgrade(out, tok, rep, hook)
            self.assertEqual((again, ch2), (out, []))
            want = src
            if hook:
                line = sync_routes.CONST_RE.findall(src)[0]
                want = src.replace(line, sync_routes._set_const(line, 'SYNC_WEBHOOK', hook), 1)
            self.assertEqual(self.strip(out), want)
            a = src.find('<template id="report-tpl"')
            if a >= 0:
                self.assertEqual(out[out.index('<template id="report-tpl"'):].split('</template>')[0], src[a:].split('</template>')[0])

    def test_kit_replaced_not_duplicated_on_new_version(self):
        out, _ = review_kit.upgrade(sw_master(), PDX)
        older = out.replace('const KIT="r1";', 'const KIT="r0";')
        again, ch = review_kit.upgrade(older, PDX)
        self.assertEqual(again, out)
        self.assertIn('review kit replaced', ch)

    def test_kit_js_parses_and_hooks_parse(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        d = tempfile.mkdtemp()
        try:
            for src, tok, rep in ((sw_master(), PDX, None), (hx_master(), FXQ, 'huaxida-h1')):
                out, _ = review_kit.upgrade(src, tok, rep, HOOK)
                for i, sc in enumerate(re.findall(r'<script(?: id="sdmc-review")?>([\s\S]*?)</script>', out)):
                    f = os.path.join(d, 's%d.js' % i)
                    open(f, 'w', encoding='utf-8').write(sc)
                    r = subprocess.run([node, '--check', f], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr[:400])
        finally:
            shutil.rmtree(d)

    def test_unknown_client_refused(self):
        with self.assertRaises(ValueError):
            review_kit.upgrade("<html><body><script>const SYNC_VER='v9', SAVE_FILE_TOKEN='';</script></body></html>", PDX)

    def test_old_packages_still_apply_on_upgraded_master(self):
        out, _ = review_kit.upgrade(sw_master(), PDX)
        texts = [read(p) for p in sorted(glob.glob(os.path.join(DROPS, '*.txt')))]
        self.assertEqual(len(texts), 4)
        pk = [json.loads(base64.b64decode(re.search(r'SDMCSYNC1:([A-Za-z0-9+/=]+):END', t).group(1))) for t in texts]
        res = []
        for p in pk:
            out, r = sp.apply_ops(out, p['ops'])
            res += r
        self.assertTrue(all(x['ok'] for x in res), res)
        self.assertIn('创维数字｜2026H1 财报分析 1', out)


class TitleCheck(unittest.TestCase):
    def test_real_v46_header_routes_to_fxqhb(self):
        routes = sync_routes.load_routes(os.path.join(V41, 'sync_routes.json'))
        head = '【SDMC 报告同步 v46】2026/10/15 10:50:00，共 1 处修改'
        for p in ({'ver': 'v46'}, {'ver': 'v46', 'file': FXQ, 'rep': 'huaxida-h1'}):
            r, why = sync_routes.resolve(p, head, routes)
            self.assertEqual((r and r['token'], why), (FXQ, None))
        r, why = sync_routes.resolve({'ver': 'v1', 'file': FXQ}, '【创维数字 2026H1 财报分析 同步 v1】', routes)
        self.assertIsNone(r)
        self.assertIn('conflicts', why)


if __name__ == '__main__':
    unittest.main(verbosity=2)
