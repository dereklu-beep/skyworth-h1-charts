#!/usr/bin/env python3
"""Relay routing by `rep`, held packages, CORS/JSONP, per-report pipeline. Offline."""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request

from helpers import Box, pkg, write

import config
import relay
import replace

EDIT_HX = {'op': 'edit', 'old': '客户集中度高。', 'new': '客户集中度偏高。'}
EDIT_SW = {'op': 'edit', 'old': '创维营收 280 亿元。', 'new': '创维营收 281 亿元。'}
SHARED_CELL = {'op': 'edit', 'tag': 'td', 'col': 0, 'next': '代工', 'old': '深圳创展', 'new': '深圳创展（改）'}


class Routing(unittest.TestCase):
    def setUp(self):
        self.box = Box()

    def tearDown(self):
        self.box.close()

    def test_skyworth_rep_lands_only_in_skyworth_drops(self):
        code, body = relay.receive(pkg([EDIT_SW], rep='skyworth-report', id='s1', ts='2026-10-14T01:00:00.000Z'))
        self.assertEqual(code, 200)
        self.assertEqual(body['routed'], [{'id': 's1', 'rep': 'skyworth-report', 'route': 'rep'}])
        self.assertEqual(len(self.box.files('sw', 'drops')), 1)
        self.assertEqual(self.box.files('hx', 'drops'), [])

    def test_alias_resolves(self):
        _, body = relay.receive(pkg([EDIT_SW], rep='创维', id='s2'))
        self.assertEqual(body['routed'][0]['rep'], 'skyworth-report')

    def test_live_v71_client_without_rep_is_legacy_routed_to_huaxida(self):
        _, body = relay.receive(pkg([EDIT_HX], ver='v46', ts='2026-10-14T01:00:00.000Z'))
        self.assertEqual(body['routed'][0]['rep'], 'huaxida-h1')
        self.assertEqual(body['routed'][0]['route'], 'legacy-ver')

    def test_missing_rep_from_other_client_is_held(self):
        code, body = relay.receive(pkg([EDIT_SW], ver='v1', id='m1'))
        self.assertEqual(code, 202)
        self.assertFalse(body['ok'])
        self.assertIn('missing rep', body['held'][0]['reason'])
        self.assertEqual(self.box.files('hx', 'drops') + self.box.files('sw', 'drops'), [])
        self.assertEqual(relay.read_status('m1')['stage'], 'held')

    def test_unknown_rep_is_held(self):
        _, body = relay.receive(pkg([EDIT_HX], rep='some-other-report', id='u1'))
        self.assertIn('unknown rep', body['held'][0]['reason'])
        self.assertEqual(len(self.box.files('relay', 'held', 'some-other-report')), 1)

    def test_file_token_of_other_report_is_held(self):
        _, body = relay.receive(pkg([EDIT_SW], rep='skyworth-report', file='TOKH', id='t1'))
        self.assertIn('does not belong', body['held'][0]['reason'])
        self.assertEqual(self.box.files('sw', 'drops'), [])

    def test_unprovisioned_report_is_held(self):
        os.remove(self.box.j('sw', 'master.html'))
        _, body = relay.receive(pkg([EDIT_SW], rep='skyworth-report', id='p1'))
        self.assertIn('not provisioned', body['held'][0]['reason'])

    def test_mixed_text_is_split_per_package(self):
        text = pkg([EDIT_HX], rep='huaxida-h1', id='a') + '\n' + pkg([EDIT_SW], rep='skyworth-report', id='b')
        _, body = relay.receive(text)
        self.assertEqual({(r['id'], r['rep']) for r in body['routed']}, {('a', 'huaxida-h1'), ('b', 'skyworth-report')})
        self.assertNotIn('创维营收', ''.join(self.box.read('hx', 'drops', f) for f in self.box.files('hx', 'drops')))

    def test_release_held_package(self):
        relay.receive(pkg([EDIT_SW], ver='v1', id='r1'))
        held = self.box.j('relay', 'held', '_missing', self.box.files('relay', 'held', '_missing')[0])
        self.assertEqual(relay.release(held, '创维'), 'r1')
        self.assertEqual(len(self.box.files('sw', 'drops')), 1)
        self.assertEqual(relay.read_status('r1')['rep'], 'skyworth-report')

    def test_pipeline_applies_skyworth_edit_to_skyworth_master_only(self):
        relay.receive(pkg([SHARED_CELL], rep='skyworth-report', id='c1', ts='2026-10-14T02:00:00.000Z'))
        res = relay.PIPE.once('skyworth-report')
        self.assertTrue(res['written'], res)
        self.assertIn('<td data-eid="3">深圳创展（改）</td>', self.box.read('sw', 'master.html'))
        self.assertIn('<td>深圳创展</td><td>华南</td>', self.box.read('hx', 'master.html'))
        self.assertEqual(relay.read_status('c1')['stage'], 'gated')
        self.assertTrue(os.path.isfile(self.box.j('relay', 'hosted', 'sw.html')))
        self.assertFalse(os.path.exists(self.box.j('relay', 'hosted', 'hx.html')))

    def test_pipeline_for_huaxida_never_picks_up_skyworth_package_even_if_misfiled(self):
        os.makedirs(self.box.j('hx', 'drops'))
        write(self.box.j('hx', 'drops', 'x.txt'), pkg([SHARED_CELL | {'col': 0, 'next': '华南'}], rep='skyworth-report', id='bad'))
        res = relay.PIPE.once('huaxida-h1')
        self.assertEqual(res['packages'], [])
        self.assertIn('<td>深圳创展</td><td>华南</td>', self.box.read('hx', 'master.html'))

    def test_replace_refuses_cross_report_pairs(self):
        with self.assertRaisesRegex(RuntimeError, 'belongs to'):
            replace.check_pair('TOKH', self.box.read('sw', 'master.html').encode(), None)
        with self.assertRaisesRegex(RuntimeError, 'not registered'):
            replace.check_pair('NEWFILE', b'<html></html>')
        self.assertEqual(replace.check_pair('TOKS', self.box.read('sw', 'master.html').encode(), 'skyworth-report'),
                         'skyworth-report')

    def test_ts_missing_gets_recv_ts(self):
        relay.receive(pkg([EDIT_HX], ver='v46', id='n1'), recv_ts='2026-10-14T03:04:05.000Z')
        st = relay.read_status('n1')
        self.assertTrue(st['ts_missing'])
        self.assertEqual(st['ts'], '2026-10-14T03:04:05.000Z')
        res = relay.PIPE.once('huaxida-h1')
        self.assertEqual(res['packages'][0]['ts'], '2026-10-14T03:04:05.000Z')

    def test_inbox_append_is_batched_not_truncated(self):
        calls = []

        class FakeReq:
            @staticmethod
            def post(url, **kw):
                calls.append(len(kw['json']['children']))
                return type('R', (), {'json': lambda self: {'code': 0}})()

        import sys
        import config
        import feishu_auth
        config.load()['feishu_live_writes'] = True
        sys.modules['requests'], old = FakeReq, sys.modules.get('requests')
        orig, feishu_auth.headers = feishu_auth.headers, lambda identity='user': {}
        relay.time.sleep, sleep = (lambda s: None), relay.time.sleep
        try:
            r = relay.append_inbox('\n'.join('line %d' % i for i in range(120)) + '\n' + 'x' * 4000)
        finally:
            feishu_auth.headers, relay.time.sleep = orig, sleep
            if old is not None:
                sys.modules['requests'] = old
        self.assertEqual(r['code'], 0)
        self.assertEqual(sum(calls), 123)
        self.assertTrue(all(n <= 50 for n in calls))


class Http(unittest.TestCase):
    def setUp(self):
        self.box = Box(allowed_origins=['null', 'https://*.feishu.cn'])
        self.srv = relay.serve('127.0.0.1', 0)
        self.base = 'http://127.0.0.1:%d' % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.box.close()

    def req(self, path, data=None, headers=None, method=None):
        r = urllib.request.Request(self.base + path, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def test_text_plain_post_and_cors_allowlist(self):
        body = pkg([EDIT_SW], rep='skyworth-report', id='h1').encode()
        code, hdr, txt = self.req('/sync', body, {'Content-Type': 'text/plain', 'Origin': 'null'})
        self.assertEqual(code, 200, txt)
        self.assertEqual(hdr.get('Access-Control-Allow-Origin'), 'null')
        code, hdr, _ = self.req('/sync', body, {'Content-Type': 'text/plain', 'Origin': 'https://evil.example'})
        self.assertNotIn('Access-Control-Allow-Origin', hdr)
        _, hdr, _ = self.req('/sync', None, {'Origin': 'https://seirobotics.feishu.cn',
                                             'Access-Control-Request-Method': 'POST'}, 'OPTIONS')
        self.assertEqual(hdr.get('Access-Control-Allow-Origin'), 'https://seirobotics.feishu.cn')

    def test_status_jsonp_and_rev(self):
        self.req('/sync', json.dumps({'text': pkg([EDIT_SW], rep='skyworth-report', id='j1')}).encode(),
                 {'Content-Type': 'application/json'})
        code, hdr, txt = self.req('/status/j1?cb=__s1')
        self.assertEqual(code, 200)
        self.assertTrue(txt.startswith('/**/__s1({'), txt)
        self.assertIn('javascript', hdr['Content-Type'])
        _, _, txt = self.req('/status/j1?cb=alert(1)//')
        self.assertTrue(txt.startswith('{'))
        _, _, txt = self.req('/rev?rep=skyworth-report')
        self.assertEqual(json.loads(txt)['rep'], 'skyworth-report')

    def test_removed_full_page_routes(self):
        for p in ('/save', '/saveas'):
            code, _, _ = self.req(p, b'{}', {'Content-Type': 'application/json'})
            self.assertEqual(code, 404)

    def test_health_lists_reports(self):
        _, _, txt = self.req('/health')
        h = json.loads(txt)
        self.assertEqual(set(h['reports']), {'huaxida-h1', 'skyworth-report'})


if __name__ == '__main__':
    unittest.main()
