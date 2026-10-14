#!/usr/bin/env python3
"""docx_sync: changed blocks only, stale block_id re-anchoring, conflicts, 低于/超过. Offline (fake Feishu API)."""
import itertools
import json
import unittest

from helpers import Box, write

import docx_sync as ds

HTML = '''<html><head><meta name="report-name" content="huaxida-h1"></head><body><main><article class="doc" id="doc">
<h2 id="s1">一、营收</h2>
<p>营收 41.3 亿元。</p>
<p>毛利率 21.5%。</p>
<table><tr><th>客户</th><th>营收</th></tr><tr><td>Claro</td><td>9.8</td></tr></table>
<h2 id="s2">二、风险</h2>
<ul><li>汇率波动。</li><li>客户集中。</li></ul>
<p>小结。</p>
</article></main></body></html>'''


def tr(t):
    return {'elements': [{'text_run': {'content': t}}], 'style': {}}


class FakeDocx:
    """In-memory docx: page → heading2/text/table/bullet blocks, enough of the API surface for docx_sync."""

    def __init__(self):
        self.ids = itertools.count(100)
        self.b = {}
        self.writes = []
        self.page = self.add({'block_type': ds.PAGE, 'page': tr('标题')}, None)
        self.add_text(4, '一、营收')
        self.add_text(2, '营收 41.3 亿元。')
        self.add_text(2, '毛利率 21.5%。')
        self.add_table([['客户', '营收'], ['Claro', '9.8']])
        self.add_text(4, '二、风险')
        self.add_text(12, '汇率波动。')
        self.add_text(12, '客户集中。')
        self.add_text(2, '小结。')

    def nid(self):
        return 'blk%d' % next(self.ids)

    def add(self, block, parent, index=None):
        bid = self.nid() if parent else 'DOC'
        block = dict(block, block_id=bid, parent_id=parent or '', children=block.get('children', []))
        self.b[bid] = block
        if parent:
            kids = self.b[parent]['children']
            kids.insert(len(kids) if index is None else index, bid)
        return bid

    def add_text(self, t, text, parent='DOC'):
        return self.add({'block_type': t, ds.KEYNAME[t]: tr(text)}, parent)

    def add_table(self, rows):
        tid = self.add({'block_type': ds.TABLE, 'table': {'cells': [], 'property': {'row_size': len(rows), 'column_size': len(rows[0])}}}, 'DOC')
        for row in rows:
            for txt in row:
                cid = self.add({'block_type': ds.CELL, 'table_cell': {}}, tid)
                self.b[tid]['table']['cells'].append(cid)
                self.add_text(2, txt, cid)
        return tid

    def find(self, text):
        return [k for k, v in self.b.items() if ds.KEYNAME.get(v['block_type']) and
                ds.elements_text(v[ds.KEYNAME[v['block_type']]]['elements']) == text]

    def text(self, bid):
        v = self.b[bid]
        return ds.elements_text(v[ds.KEYNAME[v['block_type']]]['elements'])

    def replace_block(self, bid):
        """What Feishu does on cut/paste or a delete+retype: same text, NEW block_id."""
        old = self.b.pop(bid)
        kids = self.b[old['parent_id']]['children']
        i = kids.index(bid)
        kids.pop(i)
        return self.add({k: v for k, v in old.items() if k not in ('block_id', 'parent_id')}, old['parent_id'], i)

    # API surface
    def list_blocks(self, doc):
        return json.loads(json.dumps(list(self.b.values())))

    def batch_update(self, doc, reqs):
        for r in reqs:
            v = self.b[r['block_id']]
            v[ds.KEYNAME[v['block_type']]]['elements'] = r['update_text_elements']['elements']
            self.writes.append(('patch', r['block_id']))

    def create_children(self, doc, parent, index, children):
        out = []
        for k, c in enumerate(children):
            out.append(self.add(c, parent, index + k))
            self.writes.append(('create', out[-1]))
        return out

    def delete_children(self, doc, parent, start, end):
        kids = self.b[parent]['children']
        for bid in kids[start:end]:
            self.b.pop(bid)
            self.writes.append(('delete', bid))
        del kids[start:end]


class DocxSync(unittest.TestCase):
    def setUp(self):
        self.box = Box()
        self.api = FakeDocx()
        r = ds.sync('DOCH', HTML, api=self.api, init=True)
        self.assertEqual(r['report'][0]['mapped'], 7)
        self.assertEqual(self.api.writes, [])

    def tearDown(self):
        self.box.close()

    def run_sync(self, html, **kw):
        self.api.writes.clear()
        return ds.sync('DOCH', html, api=self.api, **kw)

    def test_only_the_changed_block_is_patched(self):
        r = self.run_sync(HTML.replace('营收 41.3 亿元。', '营收 41.5 亿元。'))
        self.assertEqual(r['writes'], 1)
        self.assertEqual(self.api.writes, [('patch', self.api.find('营收 41.5 亿元。')[0])])
        self.assertEqual(self.run_sync(HTML.replace('营收 41.3 亿元。', '营收 41.5 亿元。'))['writes'], 0)

    def test_stale_block_id_after_block_replace_is_reanchored(self):
        old = self.api.find('毛利率 21.5%。')[0]
        new = self.api.replace_block(old)
        r = self.run_sync(HTML.replace('毛利率 21.5%。', '毛利率 22.0%。'))
        self.assertEqual(self.api.writes, [('patch', new)])
        self.assertEqual(r['report'][0]['how'], 'text')
        self.assertEqual(self.api.text(new), '毛利率 22.0%。')

    def test_feishu_side_edit_is_not_overwritten(self):
        bid = self.api.find('小结。')[0]
        self.api.batch_update('DOCH', [{'block_id': bid, 'update_text_elements': {'elements': [{'text_run': {'content': '小结（Derek 在飞书改）。'}}]}}])
        r = self.run_sync(HTML.replace('<p>小结。</p>', '<p>小结 v2。</p>'))
        self.assertEqual(self.api.writes, [])
        self.assertFalse(r['report'][0]['ok'])
        r2 = self.run_sync(HTML.replace('<p>小结。</p>', '<p>小结 v2。</p>'))
        self.assertFalse(r2['report'][0]['ok'], 'unresolved edit must be retried, not forgotten')

    def test_duplicate_text_resolved_by_neighbours(self):
        html = HTML.replace('<p>毛利率 21.5%。</p>', '<p>毛利率 21.5%。</p><p>同上。</p>').replace('<p>小结。</p>', '<p>同上。</p><p>小结。</p>')
        self.api.add_text(2, '同上。')
        kids = self.api.b['DOC']['children']
        dup = kids.pop()
        kids.insert(kids.index(self.api.find('毛利率 21.5%。')[0]) + 1, dup)
        last = self.api.add_text(2, '同上。')
        kids.pop()
        kids.insert(kids.index(self.api.find('小结。')[0]), last)
        ds.sync('DOCH', html, api=self.api, init=True)
        self.run_sync(html.replace('<p>同上。</p><p>小结。</p>', '<p>同上（风险）。</p><p>小结。</p>'))
        self.assertEqual(self.api.writes, [('patch', last)])
        self.assertEqual(self.api.text(dup), '同上。')

    def test_table_cell_patch_and_conflict(self):
        r = self.run_sync(HTML.replace('<td>9.8</td>', '<td>10.1</td>'))
        cell = self.api.find('10.1')
        self.assertEqual(len(cell), 1)
        self.assertEqual(r['writes'], 1)
        bid = cell[0]
        self.api.batch_update('DOCH', [{'block_id': bid, 'update_text_elements': {'elements': [{'text_run': {'content': '10.0'}}]}}])
        r = self.run_sync(HTML.replace('<td>9.8</td>', '<td>10.2</td>'))
        self.assertEqual(self.api.writes, [])
        self.assertIn('edited in Feishu', r['report'][0]['reason'])

    def test_comparisons_written_as_words(self):
        self.run_sync(HTML.replace('毛利率 21.5%。', '毛利率 &lt;22%，费用率 &gt;= 9%。'))
        self.assertEqual(self.api.find('毛利率低于22%，费用率不低于9%。'), [self.api.writes[0][1]])
        self.assertFalse(any('<' in self.api.text(b) or '>' in self.api.text(b) for b in self.api.find('毛利率低于22%，费用率不低于9%。')))

    def test_inline_bold_and_link(self):
        self.run_sync(HTML.replace('<p>小结。</p>', '<p><b>小结</b>见<a href="https://x.cn/a?b=1">附表</a>。</p>'))
        els = self.api.b[self.api.writes[0][1]]['text']['elements']
        self.assertEqual(els[0]['text_run']['text_element_style'], {'bold': True})
        self.assertEqual(els[2]['text_run']['text_element_style']['link']['url'], 'https%3A%2F%2Fx.cn%2Fa%3Fb%3D1')

    def test_new_paragraph_inserted_after_its_neighbour(self):
        self.run_sync(HTML.replace('<p>毛利率 21.5%。</p>', '<p>毛利率 21.5%。</p><p>新增：费用率 9%。</p>'))
        self.assertEqual([w[0] for w in self.api.writes], ['create'])
        kids = self.api.b['DOC']['children']
        self.assertEqual(kids.index(self.api.writes[0][1]), kids.index(self.api.find('毛利率 21.5%。')[0]) + 1)
        self.assertEqual(self.run_sync(HTML.replace('<p>毛利率 21.5%。</p>', '<p>毛利率 21.5%。</p><p>新增：费用率 9%。</p>'))['writes'], 0)

    def test_delete_needs_flag(self):
        html = HTML.replace('<li>客户集中。</li>', '')
        r = self.run_sync(html)
        self.assertEqual(self.api.writes, [])
        self.assertIn('allow-delete', r['report'][0]['reason'])
        self.run_sync(html, allow_delete=True)
        self.assertEqual([w[0] for w in self.api.writes], ['delete'])
        self.assertEqual(self.api.find('客户集中。'), [])

    def test_never_creates_documents_or_bulk_rewrites(self):
        self.run_sync(HTML.replace('营收 41.3', '营收 41.6').replace('汇率波动。', '汇率波动（对冲）。'))
        self.assertEqual(sorted(w[0] for w in self.api.writes), ['patch', 'patch'])
        self.assertIn('DOC', self.api.b)

    def test_cmp_words(self):
        self.assertEqual(ds.cmp_words('a<b, c>d, e<=f, g≥h, x->y'), 'a低于b, c超过d, e不超过f, g不低于h, x→y')


class Relink(unittest.TestCase):
    def setUp(self):
        self.box = Box()

    def tearDown(self):
        self.box.close()

    def test_relink_only_touches_blocks_with_old_tunnel_url(self):
        api = FakeDocx()
        bid = api.add_text(2, '用 Chrome 打开')
        api.b[bid]['text']['elements'][0]['text_run']['text_element_style'] = {
            'link': {'url': 'https%3A%2F%2Fhrevb-2a09.free.pinggy.net%2Fchrome'}}
        url_txt = api.add_text(2, '备用：https://hrevb-2a09.free.pinggy.net/chrome')
        r = ds.relink('ENTRY', 'https://sync.example.workers.dev/r/huaxida-h1', api=api)
        self.assertEqual(r['blocks_updated'], 2)
        self.assertEqual(sorted(w[1] for w in api.writes), sorted([bid, url_txt]))
        self.assertEqual(api.b[bid]['text']['elements'][0]['text_run']['text_element_style']['link']['url'],
                         'https%3A%2F%2Fsync.example.workers.dev%2Fr%2Fhuaxida-h1')
        self.assertEqual(ds.relink('ENTRY', 'https://sync.example.workers.dev/r/huaxida-h1', api=api)['blocks_updated'], 0)


class Guard(unittest.TestCase):
    def setUp(self):
        self.box = Box()

    def tearDown(self):
        self.box.close()

    def test_cli_refuses_cross_report_docx(self):
        write(self.box.j('hx', 'x.html'), HTML)
        with self.assertRaisesRegex(SystemExit, 'cross-report'):
            ds.main(['--doc', 'DOCS', '--html', self.box.j('hx', 'x.html')])
        with self.assertRaisesRegex(SystemExit, 'unknown report'):
            ds.main(['--doc', 'NEWDOC', '--html', self.box.j('hx', 'x.html')])


if __name__ == '__main__':
    unittest.main()
