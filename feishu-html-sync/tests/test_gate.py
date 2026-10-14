#!/usr/bin/env python3
"""Group gate: no Feishu write/upload unless feishu_live_writes AND the report's derek_confirmed. Offline."""
import sys
import unittest

from helpers import Box, pkg

import config
import docx_sync
import feishu_auth
import relay
import replace


class NoNetwork:
    """Stands in for `requests`: any use is a test failure."""

    def __getattr__(self, name):
        raise AssertionError('network used while gated: requests.%s' % name)


class Gate(unittest.TestCase):
    def setUp(self):
        self.box = Box()
        self._req = sys.modules.get('requests')
        sys.modules['requests'] = NoNetwork()
        self._hdr, feishu_auth.headers = feishu_auth.headers, self._no_token

    def tearDown(self):
        feishu_auth.headers = self._hdr
        if self._req is not None:
            sys.modules['requests'] = self._req
        else:
            sys.modules.pop('requests', None)
        self.box.close()

    @staticmethod
    def _no_token(identity='user'):
        raise AssertionError('user token requested while gated')

    def test_repo_defaults_keep_the_gate_closed(self):
        self.assertIs(config.DEFAULTS['feishu_live_writes'], False)
        self.assertTrue(all(r.get('derek_confirmed') is False for r in config.DEFAULTS['reports'].values()))
        self.assertEqual(config.DEFAULTS['reports']['skyworth-report']['drive_file_token'], 'PdxFbDlbDorRAexT1hRcpHuCnBf')
        self.assertEqual(config.DEFAULTS['reports']['huaxida-h1']['drive_file_token'], 'FXqHbFI37oGOCyxT3NkcVhjnnRg')
        self.assertEqual(config.DEFAULTS['reports']['skyworth-report']['master_html'],
                         '/workspace/sdmc_skyworth/skyworth_report/创维财报分析_v1_可编辑.html')
        self.assertTrue(all(r['feishu_kind'] == 'drive_html' for r in config.DEFAULTS['reports'].values()))

    def test_replace_refused_before_any_network_call(self):
        with self.assertRaisesRegex(config.GateClosed, 'feishu_live_writes is off'):
            replace.replace_file_content('TOKH', self.box.j('hx', 'master.html'), rep='huaxida-h1')
        config.load()['feishu_live_writes'] = True
        with self.assertRaisesRegex(config.GateClosed, 'not confirmed by Derek'):
            replace.replace_file_content('TOKS', self.box.j('sw', 'master.html'), rep='skyworth-report')

    def test_replace_cli_exits_3(self):
        with self.assertRaises(SystemExit) as cm:
            replace.main(['replace.py', '--rep', 'huaxida-h1', 'TOKH', self.box.j('hx', 'master.html')])
        self.assertEqual(cm.exception.code, 3)

    def test_docx_block_writes_and_relink_refused(self):
        api = docx_sync.FeishuDocx(headers={}, rep='huaxida-h1')
        with self.assertRaises(config.GateClosed):
            api.batch_update('DOCH', [{'block_id': 'b', 'update_text_elements': {'elements': []}}])
        with self.assertRaises(config.GateClosed):
            docx_sync.FeishuDocx(headers={}).create_children('ENTRY', 'ENTRY', 0, [])

    def test_inbox_append_skipped(self):
        r = relay.append_inbox('hello')
        self.assertIn(r.get('skipped'), (True, 'gated'))

    def test_pipeline_only_publishes_locally_until_confirmed(self):
        steps = []
        orig = relay.PIPE.step
        relay.PIPE.step = lambda args: steps.append(args[1:]) or 'ok'
        try:
            config.load().update(push_drive=True, push_docx=True)
            relay.receive(pkg([{'op': 'edit', 'old': '创维营收 280 亿元。', 'new': '创维营收 281 亿元。'}], rep='skyworth-report', id='g1', ts='t'))
            relay.PIPE.once('skyworth-report')
            self.assertEqual(steps, [['--rep', 'skyworth-report', '--publish-only', self.box.j('sw', 'master.html')]])
            self.assertEqual(relay.read_status('g1')['stage'], 'gated')
            self.assertIn('281', self.box.read('sw', 'master.html'))

            steps.clear()
            config.load()['feishu_live_writes'] = True
            config.reports()['skyworth-report']['derek_confirmed'] = True
            relay.receive(pkg([{'op': 'edit', 'old': '创维营收 281 亿元。', 'new': '创维营收 282 亿元。'}], rep='skyworth-report', id='g2', ts='t2'))
            relay.PIPE.once('skyworth-report')
            self.assertEqual(steps[0], ['--rep', 'skyworth-report', 'TOKS', self.box.j('sw', 'master.html')])
            self.assertEqual(relay.read_status('g2')['stage'], 'feishu')
        finally:
            relay.PIPE.step = orig


if __name__ == '__main__':
    unittest.main()
