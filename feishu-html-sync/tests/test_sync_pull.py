#!/usr/bin/env python3
"""Offline tests for box/sync_pull.py. Run: python3 -m unittest discover -s feishu-html-sync/tests -v"""
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'box'))
import sync_pull as sp  # noqa: E402

FIXTURE = open(os.path.join(HERE, 'fixture_report.html'), encoding='utf-8').read()


def pkg_text(ops, **kw):
    pkg = {'ver': 'v1', 'ops': ops}
    pkg.update(kw)
    return '【报告同步】test\nSDMCSYNC1:%s:END\n' % base64.b64encode(json.dumps(pkg, ensure_ascii=False).encode()).decode()


def cells(src, text):
    return len(re.findall(r'<td[^>]*>%s</td>' % re.escape(text), src))


class ApplyOps(unittest.TestCase):
    def test_browser_serialised_old_matches_source(self):
        op = {'op': 'edit', 'tag': 'p', 'old': '上半年营收 41.3 亿元，海外占比 &nbsp;62%。<br>主要客户集中在拉美。',
              'new': '上半年营收 41.5 亿元，海外占比 62%。<br>主要客户集中在拉美。'}
        out, res = sp.apply_ops(FIXTURE, [op])
        self.assertTrue(res[0]['ok'], res)
        self.assertIn('41.5 亿元', out)
        self.assertNotIn('41.3 亿元', out)

    def test_stale_eid_never_overwrites_other_element(self):
        stamped, _ = sp.stamp_eids(FIXTURE)
        claro = re.search(r'<td data-eid="(\d+)">Claro</td>', stamped).group(1)
        op = {'op': 'edit', 'eid': claro, 'tag': 'li', 'old': '汇率波动影响毛利。', 'new': '汇率波动影响毛利（已对冲 60%）。'}
        out, res = sp.apply_ops(stamped, [op])
        self.assertTrue(res[0]['ok'])
        self.assertEqual(res[0]['how'], 'content')
        self.assertIn('>Claro</td>', out)
        self.assertIn('已对冲 60%', out)

    def test_verified_eid_path(self):
        stamped, _ = sp.stamp_eids(FIXTURE)
        eid = re.search(r'<li data-eid="(\d+)">客户集中度高。</li>', stamped).group(1)
        out, res = sp.apply_ops(stamped, [{'op': 'edit', 'eid': eid, 'old': '客户集中度高。', 'new': '客户集中度高（前五 71%）。'}])
        self.assertEqual(res[0]['how'], 'eid')
        self.assertIn('<li data-eid="%s">客户集中度高（前五 71%%）。</li>' % eid, out)

    def test_ambiguous_short_cell_legacy_ctx_is_not_guessed(self):
        op = {'op': 'edit', 'eid': '999', 'ctx': 'doc / 深圳创展', 'old': '深圳创展', 'new': '深圳创展科技'}
        out, res = sp.apply_ops(FIXTURE, [op])
        self.assertFalse(res[0]['ok'])
        self.assertIn('ambiguous', res[0]['reason'])
        self.assertEqual(out, FIXTURE)

    def test_ambiguous_short_cell_resolved_by_heading_and_column(self):
        op = {'op': 'edit', 'tag': 'td', 'h': '二、供应链', 'row': '深圳创展', 'col': 2, 'old': '深圳创展', 'new': '深圳创展（独家）'}
        out, res = sp.apply_ops(FIXTURE, [op])
        self.assertTrue(res[0]['ok'], res)
        self.assertIn('<td>整机代工</td><td>深圳创展（独家）</td>', out)
        self.assertEqual(cells(out, '深圳创展'), 2)

    def test_first_column_cell_in_first_table(self):
        op = {'op': 'edit', 'tag': 'td', 'h': '一、营收结构', 'row': '深圳创展', 'col': 0, 'next': '华南', 'old': '深圳创展', 'new': '深圳创展电子'}
        out, res = sp.apply_ops(FIXTURE, [op])
        self.assertTrue(res[0]['ok'], res)
        self.assertIn('<td>深圳创展电子</td><td>华南</td>', out)
        self.assertIn('<td>深圳创展</td><td>整机代工</td>', out)

    def test_scripts_and_report_data_never_touched_by_text_edits(self):
        op = {'op': 'edit', 'tag': 'td', 'h': '一、营收结构', 'row': '深圳创展', 'col': 0, 'old': '深圳创展', 'new': 'X公司'}
        out, _ = sp.apply_ops(FIXTURE, [op])
        self.assertIn('var note = "深圳创展 <p>not an element</p>";', out)
        self.assertIn('["深圳创展",3.2]', out)

    def test_anchored_substring_when_master_paragraph_drifted(self):
        drifted = FIXTURE.replace('占采购额 34%。', '占采购额 35%。（助理更新）')
        op = {'op': 'edit', 'tag': 'p', 'h': '二、供应链', 'old': '核心代工伙伴为深圳创展，占采购额 34%。',
              'new': '核心代工伙伴为深圳创展精密，占采购额 34%。'}
        out, res = sp.apply_ops(drifted, [op])
        self.assertEqual(res[0]['how'], 'anchored', res)
        self.assertIn('核心代工伙伴为深圳创展精密，占采购额 35%。（助理更新）', out)
        self.assertEqual(cells(out, '深圳创展'), 3)

    def test_idempotent_already_applied(self):
        op = {'op': 'edit', 'tag': 'li', 'old': '汇率波动影响毛利。', 'new': '汇率波动影响毛利（已对冲）。'}
        once, _ = sp.apply_ops(FIXTURE, [op])
        twice, res = sp.apply_ops(once, [op])
        self.assertEqual(once, twice)
        self.assertEqual(res[0]['how'], 'already')

    def test_new_html_is_sanitised(self):
        op = {'op': 'edit', 'old': '客户集中度高。', 'new': '客户<b contenteditable="true">集中</b>度高。<script>alert(1)</script>'}
        out, res = sp.apply_ops(FIXTURE, [op])
        self.assertTrue(res[0]['ok'])
        self.assertIn('<li>客户<b>集中</b>度高。</li>', out)
        self.assertNotIn('alert(1)', out)

    def test_delete(self):
        out, res = sp.apply_ops(FIXTURE, [{'op': 'del', 'eid': 'r9', 'old': '客户集中度高。'}])
        self.assertTrue(res[0]['ok'])
        self.assertNotIn('客户集中度高', out)

    def test_chart_merge_keeps_concurrent_master_change(self):
        m = sp.DATA_RE.search(FIXTURE)
        tab_old = json.loads(m.group(2))['charts']
        tab_new = json.loads(json.dumps(tab_old))
        tab_new['c1']['rows'][0][1] = 3.6
        master = FIXTURE.replace('["国内",38]', '["国内",40]')
        out, res = sp.apply_ops(master, [{'op': 'data', 'key': '@charts', 'old': tab_old, 'new': tab_new}])
        self.assertTrue(res[0]['ok'], res)
        charts = json.loads(sp.DATA_RE.search(out).group(2))['charts']
        self.assertEqual(charts['c1']['rows'][0][1], 3.6)
        self.assertEqual(charts['c2']['rows'][1][1], 40)

    def test_bad_ops_do_not_abort_package(self):
        ops = [None, {'op': 'weird'}, {'op': 'edit'}, {'op': 'edit', 'old': '客户集中度高。', 'new': '集中度高。'}]
        out, res = sp.apply_ops(FIXTURE, ops)
        self.assertTrue(res[-1]['ok'])
        self.assertIn('<li>集中度高。</li>', out)


class StampAndRev(unittest.TestCase):
    def test_stamp_targets_editables_only(self):
        out, n = sp.stamp_eids(FIXTURE)
        self.assertGreater(n, 15)
        self.assertRegex(out, r'<span class="ex-title" data-eid="\d+">')
        self.assertRegex(out, r'<p class="ex-src" data-eid="\d+">')
        self.assertIn('<figcaption class="ex-head">', out)
        self.assertNotRegex(out, r'<button[^>]*data-eid')
        self.assertEqual(sp.stamp_eids(out)[1], 0)
        ids = re.findall(r'data-eid="(\d+)"', out)
        self.assertEqual(len(ids), len(set(ids)))

    def test_rev_roundtrip(self):
        out, rev = sp.set_rev(FIXTURE)
        self.assertEqual(sp.get_rev(out), rev)
        self.assertEqual(sp.compute_rev(out), rev)
        again, rev2 = sp.set_rev(out)
        self.assertEqual(rev, rev2)


class CliRun(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.target = os.path.join(self.d, 'master.html')
        open(self.target, 'w', encoding='utf-8').write(FIXTURE)
        sp.LEDGER = os.path.join(self.d, 'ledger.jsonl')
        sp.UNRESOLVED = os.path.join(self.d, 'unresolved.json')
        self.drops = os.path.join(self.d, 'drops')
        os.makedirs(self.drops)

    def tearDown(self):
        shutil.rmtree(self.d)

    def drop(self, name, text):
        open(os.path.join(self.drops, name), 'w', encoding='utf-8').write(text)

    def run_pull(self, *extra):
        return sp.main(['--target', self.target, '--no-inbox', '--drops', self.drops,
                        '--log', os.path.join(self.d, 'applied.json'), '--status-dir', os.path.join(self.d, 'status'), *extra])

    def test_missing_ts_garbage_and_dedupe(self):
        good = pkg_text([{'op': 'edit', 'old': '客户集中度高。', 'new': '客户集中度偏高。'}])
        self.drop('a.txt', good + 'SDMCSYNC1:!!!notbase64:END\nSDMCSYNC1:aGVsbG8=:END\n')
        self.drop('b.txt', good)
        r = self.run_pull()
        self.assertEqual(len(r['packages']), 1)
        self.assertEqual(r['packages'][0]['applied'], 1)
        self.assertIn('客户集中度偏高', open(self.target, encoding='utf-8').read())
        self.assertEqual(self.run_pull()['packages'], [])

    def test_status_file_unresolved_and_ledger_replay(self):
        self.drop('a.txt', pkg_text([
            {'op': 'edit', 'old': '汇率波动影响毛利。', 'new': '汇率波动影响毛利（对冲）。'},
            {'op': 'edit', 'ctx': 'doc / 深圳创展', 'old': '深圳创展', 'new': '深圳创展科技'},
        ], ts='2026-10-14T09:00:00.000Z', id='abc123', rev='stale0000000'))
        r = self.run_pull()
        p = r['packages'][0]
        self.assertEqual((p['applied'], len(p['unresolved']), p['stale_tab']), (1, 1, True))
        st = json.load(open(os.path.join(self.d, 'status', 'abc123.json'), encoding='utf-8'))
        self.assertEqual(st['rev'], sp.get_rev(open(self.target, encoding='utf-8').read()))
        self.assertEqual(len(json.load(open(sp.UNRESOLVED, encoding='utf-8'))), 1)

        rebuilt = os.path.join(self.d, 'rebuilt.html')
        open(rebuilt, 'w', encoding='utf-8').write(FIXTURE)
        sp.main(['--target', rebuilt, '--replay', sp.LEDGER, '--log', os.path.join(self.d, 'x.json')])
        self.assertIn('汇率波动影响毛利（对冲）。', open(rebuilt, encoding='utf-8').read())

    def test_dry_run_writes_nothing(self):
        self.drop('a.txt', pkg_text([{'op': 'edit', 'old': '客户集中度高。', 'new': 'Z'}], ts='t1'))
        self.run_pull('--dry')
        self.assertEqual(open(self.target, encoding='utf-8').read(), FIXTURE)
        self.assertFalse(os.path.exists(os.path.join(self.d, 'applied.json')))

    def test_ping_only_package_ignored(self):
        self.drop('a.txt', pkg_text([{'op': 'data', 'key': '__ping', 'new': 1}], ts='p1'))
        self.assertEqual(self.run_pull()['packages'], [])
        self.assertEqual(open(self.target, encoding='utf-8').read(), FIXTURE)


if __name__ == '__main__':
    unittest.main()
