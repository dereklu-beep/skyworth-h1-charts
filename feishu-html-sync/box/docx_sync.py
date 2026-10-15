#!/usr/bin/env python3
"""Push text changes from the HTML master into the EXISTING Feishu docx (same link), changed blocks only.

  python3 docx_sync.py --doc <docx_token> --html master.html --init [--dry] [--push-diffs]
  python3 docx_sync.py --doc <docx_token> --html master.html [--dry] [--allow-delete]
  python3 docx_sync.py relink --doc <entry_docx_token> --new https://<durable-url>/r/<slug>

How a change is found and written:
  * The previous HTML snapshot (state file) is diffed against the current master → a change set
    (edited / inserted / deleted paragraphs, edited table cells). Unchanged blocks are never touched.
  * Each changed unit is located in the live docx: first by the block_id remembered from the last run,
    accepted only if that block still holds the old text (a block that was replaced in Feishu gets a new
    block_id, so the stale id is rejected); otherwise re-anchored by unique old text + neighbour context.
    Still ambiguous → reported, never guessed.
  * Edits are PATCHed in place (update_text_elements); inserts go next to their located neighbour;
    deletes only with --allow-delete and only if the block still holds the old text.
  * The live docx is never deleted, recreated or bulk-rewritten, and no new document is ever created.
  * Text sent to Feishu writes comparisons as 低于 / 超过 (no angle brackets).
Writes use Derek's user identity (feishu_auth).
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import quote, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402
import sync_pull as sp  # noqa: E402

B = 'https://open.feishu.cn/open-apis'

PAGE, TEXT, BULLET, ORDERED, QUOTE, TODO, CALLOUT, TABLE, CELL, QUOTE_CONTAINER = 1, 2, 12, 13, 15, 17, 19, 31, 32, 34
HEADINGS = {2 + n: n for n in range(1, 10)}
KEYNAME = {TEXT: 'text', BULLET: 'bullet', ORDERED: 'ordered', QUOTE: 'quote', TODO: 'todo'}
KEYNAME.update({t: 'heading%d' % n for t, n in HEADINGS.items()})
CONTAINERS = {PAGE, CALLOUT, QUOTE_CONTAINER, 24, 25}


# ───────────────────────── text normalisation ─────────────────────────

def cmp_words(s):
    """Comparisons as words so Feishu text never carries angle brackets."""
    s = s.replace('<->', '↔').replace('->', '→').replace('<-', '←').replace('=>', '⇒')
    s = re.sub(r'\s*(?:<=|≤|⩽)\s*', '不超过', s)
    s = re.sub(r'\s*(?:>=|≥|⩾)\s*', '不低于', s)
    s = re.sub(r'\s*<\s*', '低于', s)
    s = re.sub(r'\s*>\s*', '超过', s)
    return s


def norm(s):
    return re.sub(r'\s+', ' ', cmp_words((s or '').replace('\xa0', ' '))).strip()


class _Inline(HTMLParser):
    STYLE = {'b': 'bold', 'strong': 'bold', 'i': 'italic', 'em': 'italic', 'u': 'underline',
             's': 'strikethrough', 'del': 'strikethrough', 'code': 'inline_code'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.runs, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        elif tag == 'br':
            self._add('\n')
        elif tag in self.STYLE:
            self.stack.append((tag, {self.STYLE[tag]: True}))
        elif tag == 'a':
            href = dict(attrs).get('href') or ''
            self.stack.append((tag, {'link': href} if href.startswith(('http://', 'https://')) else {}))
        else:
            self.stack.append((tag, {}))

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
            return
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][0] == tag:
                del self.stack[k:]
                return

    def handle_data(self, d):
        if not self.skip:
            self._add(d)

    def _add(self, d):
        st = {}
        for _, s in self.stack:
            st.update(s)
        if self.runs and self.runs[-1][1] == st:
            self.runs[-1][0] += d
        else:
            self.runs.append([d, st])


def html_to_elements(inner):
    p = _Inline()
    p.feed(inner or '')
    p.close()
    els, runs = [], [[re.sub(r'[ \t\r\f\v]+', ' ', t.replace('\xa0', ' ')), st] for t, st in p.runs]
    if runs:
        runs[0][0] = runs[0][0].lstrip()
        runs[-1][0] = runs[-1][0].rstrip()
    for t, st in runs:
        t = cmp_words(t)
        if not t:
            continue
        style = {k: v for k, v in st.items() if k != 'link'}
        if st.get('link'):
            style['link'] = {'url': quote(st['link'], safe='')}
        run = {'text_run': {'content': t}}
        if style:
            run['text_run']['text_element_style'] = style
        els.append(run)
    return els or [{'text_run': {'content': ''}}]


def elements_text(els):
    out = []
    for e in els or []:
        if 'text_run' in e:
            out.append(e['text_run'].get('content', ''))
        elif 'mention_doc' in e:
            out.append(e['mention_doc'].get('title', ''))
        elif 'equation' in e:
            out.append(e['equation'].get('content', ''))
    return ''.join(out)


# ───────────────────────── units: HTML side ─────────────────────────

def _li_kind(el):
    return 'ordered' if el.parent is not None and el.parent.tag == 'ol' else 'bullet'


def html_units(src, roots=('doc',)):
    """Paragraph-like units and tables (document order) from the HTML master."""
    doc = sp.Doc(src)
    roots = set(roots)

    def in_root(el):
        return any((a.attrs.get('id') in roots) or (a.cls() & roots) for a in el.ancestors())

    paras, tables = [], []
    for el in doc.body:
        if el.tag == 'table' and in_root(el) and not any(a.tag == 'table' for a in el.ancestors()):
            rows = []
            for tr in [e for e in sp._descendants(el) if e.tag == 'tr']:
                rows.append([{'eid': c.attrs.get('data-eid'), 'inner': doc.inner(c), 'text': norm(sp.plain(doc.inner(c)))}
                             for c in tr.kids if c.tag in ('td', 'th')])
            tables.append({'rows': rows})
            continue
        if not doc.editable(el) or not in_root(el) or el.tag in ('td', 'th'):
            continue
        anc = list(el.ancestors())
        if any(a.tag == 'table' for a in anc):
            continue
        if el.tag == 'figcaption' and 'ex-head' in el.cls():
            continue
        if any(doc.editable(a) and not (a.tag == 'figcaption' and 'ex-head' in a.cls()) for a in anc):
            continue
        inner = doc.inner(el)
        m = re.match(r'h([1-6])$', el.tag)
        kind = 'heading%s' % m.group(1) if m else (_li_kind(el) if el.tag == 'li' else 'quote' if el.tag == 'blockquote' else 'text')
        paras.append({'eid': el.attrs.get('data-eid'), 'kind': kind, 'fam': 'h' if m else 'p',
                      'inner': inner, 'text': norm(sp.plain(inner))})
    return paras, tables


# ───────────────────────── units: docx side ─────────────────────────

def docx_units(blocks):
    by = {b['block_id']: b for b in blocks}
    page = next((b for b in blocks if b.get('block_type') == PAGE), None)
    paras, tables = [], []

    def text_of(b):
        k = KEYNAME.get(b.get('block_type'))
        return elements_text((b.get(k) or {}).get('elements')) if k else ''

    def walk(bid):
        b = by.get(bid)
        if not b:
            return
        for i, cid in enumerate(b.get('children') or []):
            c = by.get(cid)
            if not c:
                continue
            t = c.get('block_type')
            if t in KEYNAME:
                paras.append({'bid': cid, 'parent': bid, 'index': i, 'type': t,
                              'fam': 'h' if t in HEADINGS else 'p', 'text': norm(text_of(c))})
                walk(cid)
            elif t == TABLE:
                prop = (c.get('table') or {}).get('property') or {}
                ids = (c.get('table') or {}).get('cells') or c.get('children') or []
                ncol = int(prop.get('column_size') or 0) or 1
                rows = []
                for k in range(0, len(ids), ncol):
                    row = []
                    for cell_id in ids[k:k + ncol]:
                        cell = by.get(cell_id) or {}
                        kids = [by[x] for x in cell.get('children') or [] if x in by]
                        txt = [x for x in kids if x.get('block_type') in KEYNAME]
                        row.append({'cell': cell_id, 'bid': txt[0]['block_id'] if txt else None,
                                    'n': len(txt), 'text': norm(' '.join(text_of(x) for x in txt))})
                    rows.append(row)
                tables.append({'bid': cid, 'rows': rows})
            elif t in CONTAINERS:
                walk(cid)

    if page:
        walk(page['block_id'])
    return paras, tables


# ───────────────────────── Feishu API (user identity) ─────────────────────────

class FeishuDocx:
    def __init__(self, headers=None, min_interval=0.4, rep=None):
        self._h, self.rep = headers, rep
        self.min_interval, self._last = min_interval, 0.0

    def _headers(self):
        if self._h:
            return self._h
        import feishu_auth
        return feishu_auth.headers('user')

    def _call(self, method, path, params=None, body=None, write=False):
        if write:
            config.require_live(self.rep, 'docx %s %s' % (method, path))
        import requests
        for attempt in range(5):
            if write:
                wait = self.min_interval - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.time()
            r = requests.request(method, B + path, headers=self._headers(), params=params, json=body, timeout=60)
            try:
                j = r.json()
            except ValueError:
                j = {'code': r.status_code, 'msg': r.text[:200]}
            if r.status_code == 429 or j.get('code') in (99991400, 1770004):
                time.sleep(1.5 * (attempt + 1))
                continue
            if j.get('code') != 0:
                raise RuntimeError('%s %s → %s' % (method, path, {k: j.get(k) for k in ('code', 'msg')}))
            return j.get('data') or {}
        raise RuntimeError('%s %s rate limited' % (method, path))

    def list_blocks(self, doc):
        items, tok = [], None
        while True:
            p = {'page_size': 500, 'document_revision_id': -1}
            if tok:
                p['page_token'] = tok
            d = self._call('GET', '/docx/v1/documents/%s/blocks' % doc, params=p)
            items += d.get('items') or []
            if not d.get('has_more'):
                return items
            tok = d.get('page_token')

    def batch_update(self, doc, requests_):
        for k in range(0, len(requests_), 200):
            self._call('PATCH', '/docx/v1/documents/%s/blocks/batch_update' % doc,
                       params={'document_revision_id': -1}, body={'requests': requests_[k:k + 200]}, write=True)

    def create_children(self, doc, parent, index, children):
        d = self._call('POST', '/docx/v1/documents/%s/blocks/%s/children' % (doc, parent),
                       params={'document_revision_id': -1, 'client_token': str(uuid.uuid4())},
                       body={'children': children, 'index': index}, write=True)
        return [c['block_id'] for c in d.get('children') or []]

    def delete_children(self, doc, parent, start, end):
        self._call('DELETE', '/docx/v1/documents/%s/blocks/%s/children/batch_delete' % (doc, parent),
                   params={'document_revision_id': -1}, body={'start_index': start, 'end_index': end}, write=True)


# ───────────────────────── planning ─────────────────────────

def _block_for(kind, inner):
    t = {'text': TEXT, 'bullet': BULLET, 'ordered': ORDERED, 'quote': QUOTE}.get(kind)
    if t is None:
        t = 2 + int(kind[-1])
    return {'block_type': t, KEYNAME[t]: {'elements': html_to_elements(inner), 'style': {}}}


def _locate(dparas, by_bid, old, hint_bid, prev_text, next_text, taken):
    """Find the live docx block that still holds `old` (dict unit). Returns (unit, how) or (None, reason)."""
    if hint_bid and hint_bid in by_bid and hint_bid not in taken:
        u = by_bid[hint_bid]
        if u['text'] == old['text'] and u['fam'] == old['fam']:
            return u, 'block_id'
    cands = [u for u in dparas if u['text'] == old['text'] and u['fam'] == old['fam'] and u['bid'] not in taken]
    if len(cands) == 1:
        return cands[0], 'text'
    if not cands:
        return None, 'not in docx (block replaced or never synced)'
    pos = {u['bid']: i for i, u in enumerate(dparas)}

    def ctx_score(u):
        i, s = pos[u['bid']], 0
        if prev_text is not None and i > 0 and dparas[i - 1]['text'] == prev_text:
            s += 1
        if next_text is not None and i + 1 < len(dparas) and dparas[i + 1]['text'] == next_text:
            s += 1
        return s

    sc = sorted(((ctx_score(u), u) for u in cands), key=lambda t: -t[0])
    if sc[0][0] > 0 and sc[0][0] > sc[1][0]:
        return sc[0][1], 'context'
    return None, 'ambiguous: %d docx blocks hold this text' % len(cands)


def plan(old_paras, old_tables, new_paras, new_tables, dparas, dtables, state, allow_delete=False):
    """Return (requests, inserts, deletes, report, new_state_partial)."""
    by_bid = {u['bid']: u for u in dparas}
    old_bids = state.get('paras_bid') or [None] * len(old_paras)
    reqs, inserts, deletes, report = [], [], [], []
    retry_paras, retry_cells, pending_del = {}, [], []
    taken = set()
    new_bids = [None] * len(new_paras)

    def text_at(lst, i):
        return lst[i]['text'] if 0 <= i < len(lst) else None

    sm = difflib.SequenceMatcher(a=[u['fam'] + '|' + u['text'] for u in old_paras],
                                 b=[u['fam'] + '|' + u['text'] for u in new_paras], autojunk=False)
    located = {}

    def locate_old(i):
        if i in located:
            return located[i]
        u, how = _locate(dparas, by_bid, old_paras[i], old_bids[i] if i < len(old_bids) else None,
                         text_at(old_paras, i - 1), text_at(old_paras, i + 1), taken)
        located[i] = (u, how)
        if u:
            taken.add(u['bid'])
        return u, how

    pending_ins = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                u, _ = locate_old(i1 + k)
                new_bids[j1 + k] = u['bid'] if u else None
            continue
        pairs = []
        a, b = list(range(i1, i2)), list(range(j1, j2))
        while a and b and old_paras[a[0]]['fam'] == new_paras[b[0]]['fam']:
            pairs.append((a.pop(0), b.pop(0)))
        for i, j in pairs:
            u, how = locate_old(i)
            if not u:
                done = [d for d in dparas if d['text'] == new_paras[j]['text'] and d['bid'] not in taken]
                if len(done) == 1:
                    taken.add(done[0]['bid'])
                    new_bids[j] = done[0]['bid']
                    report.append({'op': 'edit', 'ok': True, 'how': 'already', 'text': new_paras[j]['text'][:60]})
                    continue
                report.append({'op': 'edit', 'ok': False, 'reason': how, 'old': old_paras[i]['text'][:60],
                               'new': new_paras[j]['text'][:60]})
                retry_paras[j] = i
                continue
            new_bids[j] = u['bid']
            reqs.append({'block_id': u['bid'], 'update_text_elements': {'elements': html_to_elements(new_paras[j]['inner'])}})
            report.append({'op': 'edit', 'ok': True, 'how': how, 'old': old_paras[i]['text'][:60], 'new': new_paras[j]['text'][:60]})
        for j in b:
            pending_ins.append(j)
        for i in a:
            u, how = locate_old(i)
            if not u:
                report.append({'op': 'del', 'ok': True, 'how': 'already', 'old': old_paras[i]['text'][:60]})
            elif allow_delete:
                deletes.append(u)
                report.append({'op': 'del', 'ok': True, 'how': how, 'old': old_paras[i]['text'][:60]})
            else:
                report.append({'op': 'del', 'ok': False, 'reason': 'delete needs --allow-delete', 'old': old_paras[i]['text'][:60]})
                pending_del.append({'fam': old_paras[i]['fam'], 'text': old_paras[i]['text'], 'bid': u['bid']})

    for j in pending_ins:
        anchor = next((new_bids[k] for k in range(j - 1, -1, -1) if new_bids[k]), None)
        if anchor is None or anchor not in by_bid:
            report.append({'op': 'insert', 'ok': False, 'reason': 'no located neighbour above', 'new': new_paras[j]['text'][:60]})
            continue
        au = by_bid[anchor]
        inserts.append({'j': j, 'parent': au['parent'], 'after': anchor, 'block': _block_for(new_paras[j]['kind'], new_paras[j]['inner'])})
        report.append({'op': 'insert', 'ok': True, 'how': 'after ' + anchor, 'new': new_paras[j]['text'][:60]})

    # tables: same ordinal + same shape → cell-level edits; located cell must still hold the old text
    t_bids = state.get('tables_bid') or []
    for ti, nt in enumerate(new_tables):
        ot = old_tables[ti] if ti < len(old_tables) else None
        if ot is None:
            report.append({'op': 'table', 'ok': False, 'reason': 'new table %d: add it in Feishu manually' % ti})
            continue
        shape = lambda t: [len(r) for r in t['rows']]  # noqa: E731
        changed = [(r, c) for r, row in enumerate(nt['rows']) for c, cell in enumerate(row)
                   if r < len(ot['rows']) and c < len(ot['rows'][r]) and ot['rows'][r][c]['text'] != cell['text']]
        if shape(ot) != shape(nt):
            report.append({'op': 'table', 'ok': False, 'reason': 'table %d rows/cols changed; edit structure in Feishu' % ti})
            continue
        if not changed:
            continue
        hint = t_bids[ti] if ti < len(t_bids) else None
        dt = next((t for t in dtables if t['bid'] == hint), None)
        if dt is None or [len(r) for r in dt['rows']] != shape(ot):
            same = [t for t in dtables if [len(r) for r in t['rows']] == shape(ot)]
            score = lambda t: sum(1 for r, row in enumerate(t['rows']) for c, cell in enumerate(row)  # noqa: E731
                                  if cell['text'] in (ot['rows'][r][c]['text'], nt['rows'][r][c]['text']))
            same.sort(key=lambda t: -score(t))
            dt = same[0] if same and (len(same) == 1 or score(same[0]) > score(same[1])) else None
        if dt is None:
            report.append({'op': 'table', 'ok': False, 'reason': 'table %d not located in docx' % ti})
            retry_cells += [(ti, r, c) for r, c in changed]
            continue
        for r, c in changed:
            cell, o, n = dt['rows'][r][c], ot['rows'][r][c], nt['rows'][r][c]
            if cell['text'] == n['text']:
                report.append({'op': 'cell', 'ok': True, 'how': 'already', 'rc': [r, c]})
            elif cell['text'] != o['text']:
                report.append({'op': 'cell', 'ok': False, 'rc': [r, c], 'reason': 'docx cell was edited in Feishu; not overwritten',
                               'docx': cell['text'][:40], 'new': n['text'][:40]})
                retry_cells.append((ti, r, c))
            elif not cell['bid'] or cell['n'] != 1:
                report.append({'op': 'cell', 'ok': False, 'rc': [r, c], 'reason': 'cell has %d paragraphs' % cell['n']})
                retry_cells.append((ti, r, c))
            else:
                reqs.append({'block_id': cell['bid'], 'update_text_elements': {'elements': html_to_elements(n['inner'])}})
                report.append({'op': 'cell', 'ok': True, 'how': 'table', 'rc': [r, c], 'new': n['text'][:40]})
    tables_bid = []
    for ti in range(len(new_tables)):
        hint = t_bids[ti] if ti < len(t_bids) else None
        tables_bid.append(hint if any(t['bid'] == hint for t in dtables) else (dtables[ti]['bid'] if ti < len(dtables) else None))
    return reqs, inserts, deletes, report, {'paras_bid': new_bids, 'tables_bid': tables_bid,
                                            'retry_paras': retry_paras, 'retry_cells': retry_cells, 'pending_del': pending_del}


def initial_map(new_paras, new_tables, dparas, dtables):
    """First run: align HTML units to docx blocks by content (no writes)."""
    sm = difflib.SequenceMatcher(a=[u['fam'] + '|' + u['text'] for u in new_paras],
                                 b=[u['fam'] + '|' + u['text'] for u in dparas], autojunk=False)
    bids, diffs = [None] * len(new_paras), []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                bids[i1 + k] = dparas[j1 + k]['bid']
        elif tag == 'replace':
            for k in range(min(i2 - i1, j2 - j1)):
                if new_paras[i1 + k]['fam'] == dparas[j1 + k]['fam']:
                    diffs.append((i1 + k, dparas[j1 + k]))
    tables_bid = [dtables[i]['bid'] if i < len(dtables) else None for i in range(len(new_tables))]
    return bids, tables_bid, diffs


# ───────────────────────── run ─────────────────────────

def state_path(doc):
    return os.path.join(config.get('state_dir'), 'docx_sync_%s.json' % doc)


def _load_state(doc):
    try:
        with open(state_path(doc), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(doc, st):
    p = state_path(doc)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(p + '.tmp', p)


def _apply(api, doc, reqs, inserts, deletes, blocks):
    if reqs:
        api.batch_update(doc, reqs)
    created = {}
    children_of = {b['block_id']: list(b.get('children') or []) for b in blocks}
    for ins in inserts:
        kids = children_of.get(ins['parent'], [])
        idx = kids.index(ins['after']) + 1 if ins['after'] in kids else len(kids)
        bid = api.create_children(doc, ins['parent'], idx, [ins['block']])[0]
        kids.insert(idx, bid)
        created[ins['j']] = bid
    for u in sorted(deletes, key=lambda u: -children_of.get(u['parent'], []).index(u['bid'])):
        kids = children_of.get(u['parent'], [])
        if u['bid'] in kids:
            i = kids.index(u['bid'])
            api.delete_children(doc, u['parent'], i, i + 1)
            kids.pop(i)
    return created


def sync(doc, html_src, api=None, dry=False, init=False, push_diffs=False, allow_delete=False, roots=('doc',)):
    api = api or FeishuDocx(rep=config.rep_for_token(doc) or 'unregistered:' + doc)
    if not doc:
        raise SystemExit('no docx token: set report_docx_token in sync_config.json (never auto-created)')
    blocks = api.list_blocks(doc)
    dparas, dtables = docx_units(blocks)
    new_paras, new_tables = html_units(html_src, roots)
    st = _load_state(doc)
    snap = lambda: {'paras': [{k: u[k] for k in ('eid', 'kind', 'fam', 'inner', 'text')} for u in new_paras],  # noqa: E731
                    'tables': [{'rows': [[{'inner': c['inner'], 'text': c['text']} for c in r] for r in t['rows']]} for t in new_tables]}
    if init or not st.get('paras'):
        bids, tbids, diffs = initial_map(new_paras, new_tables, dparas, dtables)
        report = [{'op': 'init', 'mapped': sum(1 for b in bids if b), 'of': len(new_paras), 'docx_blocks': len(dparas),
                   'tables_mapped': sum(1 for b in tbids if b)}]
        reqs = []
        for i, du in diffs:
            report.append({'op': 'diff', 'html': new_paras[i]['text'][:60], 'docx': du['text'][:60]})
            if push_diffs:
                reqs.append({'block_id': du['bid'], 'update_text_elements': {'elements': html_to_elements(new_paras[i]['inner'])}})
                bids[i] = du['bid']
        if not dry:
            if reqs:
                api.batch_update(doc, reqs)
            _save_state(doc, dict(snap(), paras_bid=bids, tables_bid=tbids, doc=doc, at=time.strftime('%Y-%m-%d %H:%M:%S')))
        return {'doc': doc, 'init': True, 'writes': len(reqs) if not dry else 0, 'report': report}
    old_paras = st['paras']
    old_tables = st.get('tables') or []
    reqs, inserts, deletes, report, part = plan(old_paras, old_tables, new_paras, new_tables, dparas, dtables, st, allow_delete)
    live = {u['bid']: u for u in dparas}
    for pd in st.get('pending_del') or []:
        u = live.get(pd['bid'])
        if not u or u['text'] != pd['text'] or u['bid'] in {d['bid'] for d in deletes}:
            continue
        if allow_delete:
            deletes.append(u)
            report.append({'op': 'del', 'ok': True, 'how': 'pending', 'old': pd['text'][:60]})
        else:
            part['pending_del'].append(pd)
    writes = len(reqs) + len(inserts) + len(deletes)
    if not dry:
        created = _apply(api, doc, reqs, inserts, deletes, blocks) if writes else {}
        for j, bid in created.items():
            part['paras_bid'][j] = bid
        # unresolved edits keep the OLD snapshot text so the next run retries them
        s = snap()
        for j, i in part.pop('retry_paras').items():
            s['paras'][j] = old_paras[i]
        for ti, r, c in part.pop('retry_cells'):
            s['tables'][ti]['rows'][r][c] = old_tables[ti]['rows'][r][c]
        _save_state(doc, dict(s, **part, doc=doc, at=time.strftime('%Y-%m-%d %H:%M:%S')))
    return {'doc': doc, 'writes': writes if not dry else 0, 'planned': writes, 'report': report}


# ───────────────────────── entry-doc relink (Pinggy URL churn) ─────────────────────────

URL_RE = r'https?://[A-Za-z0-9.-]+\.(?:pinggy\.(?:net|link|online|io)|free\.pinggy\.net)[^\s"\'）)】]*'


def relink(doc, new_url, pattern=URL_RE, api=None, dry=False):
    """Rewrite old Chrome links in the entry docx to new_url — only the blocks that contain them."""
    api = api or FeishuDocx()
    rx = re.compile(pattern)
    reqs = []
    for b in api.list_blocks(doc):
        k = KEYNAME.get(b.get('block_type'))
        if not k:
            continue
        els = (b.get(k) or {}).get('elements') or []
        hit, out = False, []
        for e in els:
            e = json.loads(json.dumps(e))
            tr = e.get('text_run')
            if tr:
                c = tr.get('content', '')
                if rx.search(c) and new_url not in c:
                    tr['content'], hit = rx.sub(new_url, c), True
                link = (tr.get('text_element_style') or {}).get('link')
                if link and rx.search(unquote(link.get('url', ''))) and unquote(link['url']) != new_url:
                    link['url'], hit = quote(new_url, safe=''), True
            out.append(e)
        if hit:
            reqs.append({'block_id': b['block_id'], 'update_text_elements': {'elements': out}})
    if reqs and not dry:
        api.batch_update(doc, reqs)
    return {'doc': doc, 'blocks_updated': len(reqs), 'dry': dry}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'relink':
        ap = argparse.ArgumentParser(prog='docx_sync.py relink')
        ap.add_argument('--doc', default=config.get('entry_docx_token'))
        ap.add_argument('--new', required=True)
        ap.add_argument('--pattern', default=URL_RE)
        ap.add_argument('--dry', action='store_true')
        a = ap.parse_args(argv[1:])
        r = relink(a.doc, a.new, a.pattern, dry=a.dry)
    else:
        ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
        ap.add_argument('--rep', help='report key (defaults --doc/--html from the registry)')
        ap.add_argument('--doc')
        ap.add_argument('--html')
        ap.add_argument('--root', nargs='*', default=['doc'], help='id/class of HTML containers mirrored in the docx')
        ap.add_argument('--init', action='store_true', help='(re)build the HTML↔block map from content; no writes unless --push-diffs')
        ap.add_argument('--push-diffs', action='store_true', help='with --init: patch blocks whose text differs from HTML')
        ap.add_argument('--allow-delete', action='store_true')
        ap.add_argument('--dry', action='store_true')
        a = ap.parse_args(argv)
        owner = config.rep_for_token(a.doc) if a.doc else None
        rep = config.resolve_rep(a.rep) if a.rep else owner
        if not rep:
            raise SystemExit('unknown report: pass --rep or a --doc registered in sync_config reports')
        r = config.report(rep)
        a.doc, a.html = a.doc or r.get('report_docx_token'), a.html or r['master_html']
        if a.doc != r.get('report_docx_token'):
            raise SystemExit('docx %s is not the registered docx of %s (cross-report write refused)' % (a.doc, rep))
        with open(a.html, encoding='utf-8') as f:
            src = f.read()
        for m in re.finditer(r'<meta\s+name="report-(?:id|name)"\s+content="([^"]*)"', src[:20000], re.I):
            named = config.resolve_rep(m.group(1))
            if named and named != rep:
                raise SystemExit('HTML is report %s, docx belongs to %s (cross-report write refused)' % (named, rep))
        r = sync(a.doc, src, dry=a.dry, init=a.init, push_diffs=a.push_diffs, allow_delete=a.allow_delete, roots=a.root)
    print('DOCX_RESULT ' + json.dumps(r, ensure_ascii=False))
    return r


if __name__ == '__main__':
    try:
        main()
    except config.GateClosed as e:
        print('GATED', e, file=sys.stderr)
        raise SystemExit(3)
