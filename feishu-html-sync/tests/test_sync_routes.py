#!/usr/bin/env python3
"""Box v41 router (sync_watch.py + sync_routes.py): smoke with the 4 real 2026-10-15 drops and a fake replace.py.

Uses the real masters when available (SMOKE_SW_SRC / SMOKE_HX_SRC, default: the project store artifacts),
else small synthetic stand-ins. Never touches Feishu: replace.py is a fake that only logs its argv.
"""
import base64
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
V41 = os.path.join(HERE, '..', 'box_v41')
DROPS = os.path.join(HERE, 'fixtures', 'box_drops_20261015')
STORE = '/cursor/stores/bc-53a8ae46-622d-513a-8df0-fb556621041b/artifacts'
SW_SRC = os.environ.get('SMOKE_SW_SRC') or os.path.join(STORE, '创维数字专报_入稿终稿.html')
HX_SRC = os.environ.get('SMOKE_HX_SRC') or os.path.join(STORE, '华曦达对比_排版优化.html')
PDX, FXQ = 'PdxFbDlbDorRAexT1hRcpHuCnBf', 'FXqHbFI37oGOCyxT3NkcVhjnnRg'
CAP = '总体判断：四点结论，后文各板块逐一展开'
sys.path.insert(0, V41)
import sync_routes  # noqa: E402

SW_STUB = ('<!doctype html><html><head><meta name="report-name" content="skyworth-report"></head><body>'
           '<header id="s-cover"><h1 data-eid="s-cover.1">创维数字｜2026H1 财报分析</h1></header>'
           '<script>const SYNC_VER=\'v1\', SAVE_FILE_TOKEN=\'\', SAVE_URL=\'\', SYNC_INBOX=\'\', SYNC_WEBHOOK=\'\', SYNC_AUTH=\'\';</script>'
           '</body></html>')
HX_STUB = ('<!doctype html><html><head><title>华曦达 SDMC｜2026H1 财报分析</title></head><body><template id="report-tpl">'
           '<main><div class="doc"><section class="blk" id="s-concl"><h2><span>核心结论</span></h2><div class="cap" data-eid="33"><b data-eid="34">%s</b></div>'
           '</section></div></main></template><script>const SYNC_VER=\'v46\', SAVE_FILE_TOKEN=\'%s\', SAVE_URL=\'\';\n'
           'function editsText(ops){ const ts=new Date().toISOString(), lines=[];\n'
           '  lines.push(\'SDMCSYNC1:\'+b64(JSON.stringify({ver:SYNC_VER,ts,ops}))+\':END\');\n  return lines.join(\'\\n\');\n}'
           '</script></body></html>') % (CAP, FXQ)

FAKE_REPLACE = r'''import hashlib, json, os, sys
tok, path = sys.argv[1], sys.argv[2]
data = open(path, 'rb').read()
with open(os.environ['FAKE_REPLACE_LOG'], 'a') as f:
    f.write(json.dumps({'token': tok, 'path': path, 'md5': hashlib.md5(data).hexdigest(), 'bytes': len(data)}) + '\n')
print({'file_token': tok, 'version': 'fake', 'url': 'https://seirobotics.feishu.cn/file/' + tok})
'''


def md5(p):
    with open(p, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def pkg_text(p, head):
    return head + '\nSDMCSYNC1:' + base64.b64encode(json.dumps(p, ensure_ascii=False).encode()).decode() + ':END\n'


class Router(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.v41 = os.path.join(self.d, 'v41')
        os.makedirs(os.path.join(self.v41, 'sync_inbox_drops'))
        for f in ('sync_watch.py', 'sync_routes.py', 'sync_pull_routed.py'):
            shutil.copy(os.path.join(V41, f), self.v41)
        self.real = os.path.isfile(SW_SRC) and os.path.isfile(HX_SRC)
        sw_src = os.path.join(self.d, 'sw_src.html')
        if self.real:
            shutil.copy(SW_SRC, sw_src)
        else:
            open(sw_src, 'w', encoding='utf-8').write(SW_STUB)
        self.sw = os.path.join(self.d, 'skyworth_report', 'opus_final_20261014', '创维数字专报_入稿终稿_feishu.html')
        self.inject = subprocess.run([sys.executable, os.path.join(self.v41, 'sync_routes.py'), 'inject-token', sw_src, self.sw, PDX,
                                      '--webhook', 'https://webhook.site/00000000-0000-0000-0000-000000000000'],
                                     capture_output=True, text=True, check=True).stdout
        self.hx = os.path.join(self.d, 'huaxida_report', '华曦达对比_排版优化_feishu.html')
        os.makedirs(os.path.dirname(self.hx))
        if self.real:
            shutil.copy(HX_SRC, self.hx)
        else:
            open(self.hx, 'w', encoding='utf-8').write(HX_STUB)
        self.routes = os.path.join(self.v41, 'sync_routes.json')
        seed = json.load(open(os.path.join(V41, 'sync_routes.json'), encoding='utf-8'))
        seed['routes'][0]['master'], seed['routes'][1]['master'] = self.sw, self.hx
        self.write_routes(seed)
        self.fake = os.path.join(self.d, 'replace.py')
        open(self.fake, 'w').write(FAKE_REPLACE)
        self.calls = os.path.join(self.d, 'replace_calls.jsonl')
        self.md5_0 = {'sw': md5(self.sw), 'hx': md5(self.hx), 'sw_src': md5(sw_src)}

    def tearDown(self):
        shutil.rmtree(self.d)

    def write_routes(self, j):
        self.seed = j
        with open(self.routes, 'w', encoding='utf-8') as f:
            json.dump(j, f, ensure_ascii=False, indent=1)

    def confirm(self, token, on=True):
        for r in self.seed['routes']:
            if r['token'] == token:
                r['derek_confirmed'] = on
        self.write_routes(self.seed)

    def watch(self, *args):
        env = dict(os.environ, SYNC_REPLACE=self.fake, FAKE_REPLACE_LOG=self.calls, SYNC_ROUTES=self.routes)
        p = subprocess.run([sys.executable, os.path.join(self.v41, 'sync_watch.py'), '--no-inbox'] + list(args),
                           capture_output=True, text=True, env=env, timeout=300)
        self.out = p.stdout + p.stderr
        return p.returncode

    def replaced(self):
        if not os.path.exists(self.calls):
            return []
        return [json.loads(l) for l in open(self.calls)]

    def drop(self, name, text):
        p = os.path.join(self.v41, 'sync_inbox_drops', name)
        open(p, 'w', encoding='utf-8').write(text)
        return p

    def test_inject_token_changes_only_the_sync_constants(self):
        a = open(SW_SRC if self.real else os.path.join(self.d, 'sw_src.html'), encoding='utf-8').read().splitlines()
        b = open(self.sw, encoding='utf-8').read().splitlines()
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(len(a), len(b))
        self.assertEqual(len(diff), 1)
        self.assertIn("SAVE_FILE_TOKEN='%s'" % PDX, diff[0][1])
        self.assertEqual(sync_routes.master_token('\n'.join(b)), [PDX])
        print('\nSMOKE inject-token: src md5 %s -> master md5 %s (1 line changed: SAVE_FILE_TOKEN, SYNC_WEBHOOK)'
              % (self.md5_0['sw_src'], self.md5_0['sw']))

    def test_real_pdxfb_drops_land_on_skyworth_only(self):
        drops = [shutil.copy(p, os.path.join(self.v41, 'sync_inbox_drops')) for p in sorted(glob.glob(os.path.join(DROPS, '*.txt')))]
        self.assertEqual(len(drops), 4)
        self.assertEqual(self.watch('--replay', *drops), 0, self.out)
        self.assertIn('GATED', self.out)
        self.assertEqual(self.replaced(), [], 'gate closed: no replace')
        self.assertIn('创维数字｜2026H1 财报分析 1', open(self.sw, encoding='utf-8').read())
        self.assertEqual(md5(self.hx), self.md5_0['hx'], 'FXqHb master must not change')
        sw_after_gate = md5(self.sw)
        self.assertEqual(self.watch('--replay', *drops), 0, self.out)
        self.assertEqual(md5(self.sw), sw_after_gate, 'replaying the same drops is idempotent')

        self.confirm(PDX)
        new = self.drop('drop_20261015_110000_000001.txt', pkg_text(
            {'ver': 'v1', 'rep': 'skyworth-report', 'file': PDX, 'ts': '2026-10-15T03:00:00.000Z',
             'ops': [{'op': 'edit', 'eid': 's-cover.1', 'ctx': 's-cover', 'old': '创维数字｜2026H1 财报分析 1', 'new': '创维数字｜2026H1 财报分析'}]},
            '【创维数字 2026H1 财报分析 同步 v1】2026/10/15 11:00:00，共 1 处修改'))
        self.assertEqual(self.watch(), 0, self.out)
        calls = self.replaced()
        self.assertEqual([(c['token'], c['path']) for c in calls], [(PDX, self.sw)])
        self.assertEqual(md5(self.hx), self.md5_0['hx'])
        self.assertTrue(os.path.exists(os.path.join(self.v41, 'sync_routed', PDX, 'last_good.html')))
        print('SMOKE PdxFb: 4 real drops → 创维 master %s -> %s (gated, 0 replace); after derek_confirmed: '
              'replace calls %s; FXqHb master md5 %s unchanged; new drop %s'
              % (self.md5_0['sw'], sw_after_gate, [(c['token'], c['md5']) for c in calls], md5(self.hx), os.path.basename(new)))

    def test_unknown_missing_and_conflicting_tokens_are_held(self):
        op = [{'op': 'edit', 'eid': 's-cover.1', 'old': '创维数字｜2026H1 财报分析', 'new': 'X'}]
        self.confirm(PDX)
        self.confirm(FXQ)
        self.drop('drop_a.txt', pkg_text({'ver': 'v1', 'file': 'ZZZZZZZZZZZZZZZZZZZZZZZZZZZ', 'ts': 't1', 'ops': op}, '【创维数字 同步 v1】'))
        self.drop('drop_b.txt', pkg_text({'ver': 'v1', 'rep': 'skyworth-report', 'ts': 't2', 'ops': op}, '【创维数字 同步 v1】'))
        self.drop('drop_c.txt', pkg_text({'ver': 'v1', 'rep': 'skyworth-report', 'file': FXQ, 'ts': 't3', 'ops': op}, '【创维数字 同步 v1】'))
        self.drop('drop_d.txt', pkg_text({'ver': 'v1', 'file': FXQ, 'ts': 't4', 'ops': op}, '【创维数字 2026H1 财报分析 同步 v1】'))
        self.assertEqual(self.watch(), 0, self.out)
        self.assertEqual(self.replaced(), [])
        self.assertEqual((md5(self.sw), md5(self.hx)), (self.md5_0['sw'], self.md5_0['hx']))
        held = sorted(os.listdir(os.path.join(self.v41, 'sync_held')))
        self.assertEqual(len(held), 4)
        for why in ('unknown file_token ZZZ', 'has no file_token', 'rep skyworth-report conflicts', 'title'):
            self.assertIn(why, self.out)
        print('SMOKE held: unknown token / missing token / rep conflict / title conflict → %d held, 0 replace, '
              'both masters unchanged' % len(held))

    def test_fxqhb_legacy_v46_edit_replaces_fxqhb_only(self):
        self.confirm(FXQ)
        self.drop('drop_hx.txt', pkg_text({'ver': 'v46', 'ts': '2026-10-15T03:00:02.000Z',
                                           'ops': [{'op': 'edit', 'eid': '34', 'ctx': 's-concl', 'old': CAP, 'new': CAP + '（测）'}]},
                                          '【报告同步 v46】华曦达 SDMC｜2026H1 财报分析 · 测试，共 1 处修改'))
        self.assertEqual(self.watch(), 0, self.out)
        self.assertEqual([(c['token'], c['path']) for c in self.replaced()], [(FXQ, self.hx)])
        self.assertEqual(md5(self.sw), self.md5_0['sw'])
        self.assertIn(CAP + '（测）', open(self.hx, encoding='utf-8').read())
        print('SMOKE FXqHb: v46 edit → 华曦达 master %s -> %s, replace calls %s, 创维 master unchanged'
              % (self.md5_0['hx'], md5(self.hx), [c['token'] for c in self.replaced()]))

    def test_shrink_guard_backup_and_rollback(self):
        self.confirm(FXQ)
        big = os.path.join(self.d, 'live_FXqHb.html')
        open(big, 'w', encoding='utf-8').write(open(self.hx, encoding='utf-8').read() + '<!--' + 'x' * (os.path.getsize(self.hx) * 2) + '-->')
        self.assertEqual(self.watch('--seed-last-good', FXQ, big), 0, self.out)
        self.drop('drop_hx.txt', pkg_text({'ver': 'v46', 'ts': 't5', 'ops': [{'op': 'edit', 'eid': '34', 'old': CAP, 'new': CAP + '（缩）'}]},
                                          '【报告同步 v46】华曦达'))
        self.assertEqual(self.watch(), 3, self.out)
        self.assertIn('REFUSED replace %s: file shrinks' % FXQ, self.out)
        self.assertEqual(self.replaced(), [])
        self.drop('drop_hx2.txt', pkg_text({'ver': 'v46', 'ts': 't6', 'ops': [{'op': 'edit', 'eid': '34', 'old': CAP + '（缩）', 'new': CAP + '（缩2）'}]},
                                           '【报告同步 v46】华曦达'))
        self.assertEqual(self.watch('--allow-shrink'), 0, self.out)
        self.assertEqual([c['token'] for c in self.replaced()], [FXQ])
        self.assertEqual(self.watch('--rollback', FXQ), 0, self.out)
        last = self.replaced()[-1]
        self.assertEqual((last['token'], last['md5']), (FXQ, md5(big)))
        self.assertEqual(md5(os.path.join(self.v41, 'sync_routed', FXQ, 'last_good.html')), md5(big))
        print('SMOKE guard: 66%% shrink refused (rc 3); --allow-shrink replaced; --rollback restored FXqHb to %s' % md5(big))

    def test_token_mismatch_refused_even_with_allow_shrink(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('sw', os.path.join(self.v41, 'sync_watch.py'))
        sw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sw)
        self.assertIn('not %s' % FXQ, sw.guard(FXQ, self.sw, allow_shrink=True))
        self.assertIsNone(sw.guard(PDX, self.sw))


class PatchClient(unittest.TestCase):
    """Optional step: the FXqHb master's client sends `file` (+ rep); no content change; fallback still routes, with a warning."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src = open(HX_SRC, encoding='utf-8').read() if os.path.isfile(HX_SRC) else HX_STUB

    def tearDown(self):
        shutil.rmtree(self.d)

    @staticmethod
    def outside_scripts(html):
        import re
        return re.sub(r'<script[\s\S]*?</script>', '', html)

    def test_patch_is_client_only_and_idempotent(self):
        out, ch = sync_routes.patch_client(self.src, FXQ, 'huaxida-h1')
        self.assertEqual(len(ch), 1)
        self.assertEqual(self.outside_scripts(out), self.outside_scripts(self.src))
        i = next(k for k in range(len(self.src)) if self.src[k] != out[k])
        ins = len(out) - len(self.src)
        self.assertEqual(out[:i] + out[i + ins:], self.src, 'exactly one insertion')
        self.assertEqual(out[i:i + ins], "file:SAVE_FILE_TOKEN,rep:'huaxida-h1',")
        self.assertEqual(sync_routes.patch_client(out, FXQ, 'huaxida-h1'), (out, []))
        self.assertEqual(sync_routes.master_token(out), [FXQ])
        print('\nSMOKE patch-client: %s -> %s (+%d bytes, one insertion in <script>, page content identical)'
              % (hashlib.md5(self.src.encode()).hexdigest(), hashlib.md5(out.encode()).hexdigest(),
                 len(out.encode()) - len(self.src.encode())))

    def test_patched_client_emits_file_token(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        import re
        out, _ = sync_routes.patch_client(self.src, FXQ, 'huaxida-h1')
        line = re.search(r"lines\.push\('SDMCSYNC1:'.*?:END'\);", out).group(0)
        js = ("const SYNC_VER='v46', SAVE_FILE_TOKEN=%r; const b64=s=>Buffer.from(s,'utf8').toString('base64');"
              "const ts='2026-10-15T03:00:00.000Z', ops=[{op:'edit',old:'a',new:'b'}], lines=[];%s"
              "process.stdout.write(lines[0]);" % (FXQ, line))
        pkg = subprocess.run([node, '-e', js], capture_output=True, text=True, check=True).stdout
        p = json.loads(base64.b64decode(pkg.split(':')[1]))
        self.assertEqual((p['file'], p['rep'], p['ver']), (FXQ, 'huaxida-h1', 'v46'))
        for i, sc in enumerate(re.findall(r'<script>([\s\S]*?)</script>', out)):
            f = os.path.join(self.d, 's%d.js' % i)
            open(f, 'w', encoding='utf-8').write(sc)
            r = subprocess.run([node, '--check', f], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_empty_token_page_gets_token_too(self):
        page = self.src.replace("SAVE_FILE_TOKEN='%s'" % FXQ, "SAVE_FILE_TOKEN=''")
        out, ch = sync_routes.patch_client(page, FXQ)
        self.assertEqual(len(ch), 2)
        self.assertEqual(sync_routes.master_token(out), [FXQ])
        self.assertIn('{ver:SYNC_VER,file:SAVE_FILE_TOKEN,ts', out)

    def test_refuses_ambiguous_client(self):
        with self.assertRaises(ValueError):
            sync_routes.patch_client("const SYNC_VER='v46', SAVE_FILE_TOKEN='%s';" % FXQ, FXQ)
        lit = "lines.push('SDMCSYNC1:'+b64(JSON.stringify({ver:SYNC_VER,ts,ops}))+':END');"
        with self.assertRaises(ValueError):
            sync_routes.patch_client("const SYNC_VER='v46', SAVE_FILE_TOKEN='%s';%s%s" % (FXQ, lit, lit), FXQ)


class PatchClientRouting(Router):
    def test_fallback_warns_token_routes_quietly_and_patch_ships_on_publish(self):
        self.confirm(FXQ)
        edit = [{'op': 'edit', 'eid': '34', 'ctx': 's-concl', 'old': CAP, 'new': CAP + '（旧）'}]
        self.drop('drop_old.txt', pkg_text({'ver': 'v46', 'ts': 't7', 'ops': edit}, '【报告同步 v46】华曦达 SDMC｜2026H1 财报分析'))
        self.assertEqual(self.watch(), 0, self.out)
        self.assertIn('WARNING routed by legacy fallback', self.out)
        self.assertEqual([c['token'] for c in self.replaced()], [FXQ])

        self.assertEqual(subprocess.run([sys.executable, os.path.join(self.v41, 'sync_routes.py'), 'patch-client', self.hx, FXQ,
                                         '--rep', 'huaxida-h1'], capture_output=True, text=True).returncode, 0)
        self.assertEqual(self.watch('--publish', FXQ), 0, self.out)
        self.assertEqual(self.replaced()[-1]['md5'], md5(self.hx), 'next confirmed publish ships the patched client')

        edit2 = [{'op': 'edit', 'eid': '34', 'ctx': 's-concl', 'old': CAP + '（旧）', 'new': CAP + '（新）'}]
        self.drop('drop_new.txt', pkg_text({'ver': 'v46', 'file': FXQ, 'rep': 'huaxida-h1', 'ts': 't8', 'ops': edit2},
                                           '【报告同步 v46】华曦达 SDMC｜2026H1 财报分析'))
        self.assertEqual(self.watch(), 0, self.out)
        self.assertNotIn('legacy fallback', self.out)
        self.assertEqual([c['token'] for c in self.replaced()], [FXQ, FXQ, FXQ])
        self.assertEqual(md5(self.sw), self.md5_0['sw'])
        print('SMOKE fallback: v46 without file → routed FXqHb + WARNING; patch-client + --publish shipped %s; '
              'package with file → routed FXqHb, no warning; 创维 master unchanged' % md5(self.hx))


class Install(unittest.TestCase):
    """install.sh on a simulated box tree: original sync_watch.py, the 4 real drops, live copies, fake replace.py."""

    def test_install_then_publish_then_rollback(self):
        d = tempfile.mkdtemp()
        try:
            root = os.path.join(d, 'sdmc_skyworth')
            v41, live = os.path.join(root, 'v41'), os.path.join(root, '_live_check_1023')
            sw_dir = os.path.join(root, 'skyworth_report', 'opus_final_20261014')
            for p in (os.path.join(v41, 'sync_inbox_drops'), live, sw_dir):
                os.makedirs(p)
            shutil.copy(os.path.join(V41, 'sync_watch.py.orig'), os.path.join(v41, 'sync_watch.py'))
            for p in sorted(glob.glob(os.path.join(DROPS, '*.txt'))):
                shutil.copy(p, os.path.join(v41, 'sync_inbox_drops'))
            real = os.path.isfile(SW_SRC) and os.path.isfile(HX_SRC)
            sw_src = os.path.join(sw_dir, '创维数字专报_入稿终稿.html')
            if real:
                shutil.copy(SW_SRC, sw_src)
                shutil.copy(HX_SRC, os.path.join(live, 'FXqHb.html'))
            else:
                open(sw_src, 'w', encoding='utf-8').write(SW_STUB)
                open(os.path.join(live, 'FXqHb.html'), 'w', encoding='utf-8').write(HX_STUB)
            fake, calls = os.path.join(d, 'replace.py'), os.path.join(d, 'calls.jsonl')
            open(fake, 'w').write(FAKE_REPLACE)
            env = dict(os.environ, ROOT=root, SW_WEBHOOK='https://webhook.site/00000000-0000-0000-0000-000000000000',
                       INBOX_FLAG='--no-inbox', SYNC_REPLACE=fake, FAKE_REPLACE_LOG=calls, FORCE='' if real else '1')
            env.pop('SYNC_ROUTES', None)
            p = subprocess.run(['bash', os.path.join(V41, 'install.sh')], capture_output=True, text=True, env=env, timeout=300)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('routes OK', p.stdout)
            self.assertFalse(os.path.exists(calls), 'install must not replace')
            sw = os.path.join(sw_dir, '创维数字专报_入稿终稿_feishu.html')
            self.assertIn('创维数字｜2026H1 财报分析 1', open(sw, encoding='utf-8').read())
            watch = [sys.executable, os.path.join(v41, 'sync_watch.py')]
            p2 = subprocess.run(watch + ['--publish', PDX], capture_output=True, text=True, env=env)
            self.assertNotEqual(p2.returncode, 0)
            self.assertIn('GATED', p2.stdout + p2.stderr)
            j = json.load(open(os.path.join(v41, 'sync_routes.json'), encoding='utf-8'))
            for r in j['routes']:
                r['derek_confirmed'] = True
            json.dump(j, open(os.path.join(v41, 'sync_routes.json'), 'w', encoding='utf-8'), ensure_ascii=False)
            p3 = subprocess.run(watch + ['--publish', PDX], capture_output=True, text=True, env=env)
            self.assertEqual(p3.returncode, 0, p3.stdout + p3.stderr)
            published = [json.loads(l) for l in open(calls)]
            self.assertEqual([(c['token'], c['path']) for c in published], [(PDX, sw)])
            p4 = subprocess.run(watch + ['--rollback', PDX], capture_output=True, text=True, env=env)
            self.assertIn('no archived good copy', p4.stdout)
            p5 = subprocess.run(watch + ['--no-inbox'], capture_output=True, text=True, env=env)
            self.assertEqual(p5.returncode, 0, p5.stdout + p5.stderr)
            self.assertEqual(len([json.loads(l) for l in open(calls)]), 1, 'old drops are baseline, not re-sent')
            print('\nSMOKE install: %s\nSMOKE publish PdxFb after confirm: %s'
                  % ([l for l in p.stdout.splitlines() if '->' in l or 'unchanged' in l or 'last good' in l],
                     [(c['token'], c['md5'], c['bytes']) for c in published]))
        finally:
            shutil.rmtree(d)


class Validator(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.m = os.path.join(self.d, 'new.html')
        open(self.m, 'w', encoding='utf-8').write(
            '<meta name="report-name" content="new-report"><script>const SYNC_VER=\'v1\', SAVE_FILE_TOKEN=\'AbCdEfGhIjKlMnOpQrStUvWxYz1\';</script>')
        self.ok = {'token': 'AbCdEfGhIjKlMnOpQrStUvWxYz1', 'label': '新报告', 'rep': 'new-report', 'master': self.m}

    def tearDown(self):
        shutil.rmtree(self.d)

    def errs(self, *routes):
        return sync_routes.check_routes(list(routes))[0]

    def test_valid_route(self):
        self.assertEqual(self.errs(self.ok), [])

    def test_each_failure(self):
        cases = {
            'not a 27-char': dict(self.ok, token='abc'),
            'master not found': dict(self.ok, master=os.path.join(self.d, 'missing.html')),
            'absolute path': dict(self.ok, master='rel/x.html'),
            'missing label': dict(self.ok, label=''),
            'does not match route token': dict(self.ok, token='ZZZZZZZZZZZZZZZZZZZZZZZZZZZ'),
            'does not match route rep': dict(self.ok, rep='skyworth-report'),
        }
        for want, r in cases.items():
            self.assertTrue(any(want in e for e in self.errs(r)), (want, self.errs(r)))
        self.assertTrue(any('duplicate token' in e for e in self.errs(self.ok, dict(self.ok, master='/x/y.html'))))
        self.assertTrue(any('no SAVE_FILE_TOKEN' in e for e in self.errs(dict(self.ok, master=self._write('<p>x</p>')))))

    def _write(self, text):
        p = os.path.join(self.d, 'other.html')
        open(p, 'w', encoding='utf-8').write(text)
        return p

    def test_cli_exit_codes(self):
        good = os.path.join(self.d, 'routes.json')
        json.dump({'routes': [self.ok]}, open(good, 'w'))
        bad = os.path.join(self.d, 'bad.json')
        json.dump({'routes': [dict(self.ok, token='short')]}, open(bad, 'w'))
        cli = [sys.executable, os.path.join(V41, 'sync_routes.py'), 'check']
        r1 = subprocess.run(cli + [good], capture_output=True, text=True)
        r2 = subprocess.run(cli + [bad], capture_output=True, text=True)
        self.assertEqual((r1.returncode, r2.returncode), (0, 1), r1.stdout + r2.stdout)
        self.assertIn('routes OK', r1.stdout)

    def test_inject_refuses_ambiguous_pages(self):
        with self.assertRaises(ValueError):
            sync_routes.inject_token('<p>no const</p>', self.ok['token'])
        two = "const SYNC_VER='v1', SAVE_FILE_TOKEN='';\nconst SYNC_VER='v1', SAVE_FILE_TOKEN='';"
        with self.assertRaises(ValueError):
            sync_routes.inject_token(two, self.ok['token'])

    def test_seed_routes_have_no_hardcoded_default(self):
        seed = json.load(open(os.path.join(V41, 'sync_routes.json'), encoding='utf-8'))['routes']
        self.assertEqual(sorted(r['token'] for r in seed), sorted([PDX, FXQ]))
        self.assertTrue(all(r['derek_confirmed'] is False for r in seed))
        src = open(os.path.join(V41, 'sync_watch.py'), encoding='utf-8').read()
        self.assertNotIn(FXQ, src)
        self.assertNotIn('v71_std', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
