#!/usr/bin/env python3
"""Pull SDMCSYNC1 packages (relay drops + Feishu inbox) and apply them surgically to the master HTML.

Apply never re-serialises the whole page (no Playwright bSave). Each edit is resolved to ONE element:

  1. eid hint, verified: the element with data-eid must still contain `old` (or already contain `new`).
     A stale tab whose eids were renumbered can therefore never overwrite the wrong element.
  2. whole-content match: elements whose inner HTML (canonicalised) or visible text equals `old`.
  3. anchored substring: the changed span plus up to 12 chars of unchanged context on each side,
     searched inside element inner HTML only (never in <script>/report-data/attributes).
  Any step with several candidates is disambiguated by context (section heading, table row header,
  column, neighbour text). Still ambiguous -> unresolved (recorded, never guessed).

Packages without `ts` are processed under a content hash key; nothing in one package can abort another.
"""
import argparse
import base64
import bisect
import glob
import hashlib
import html as htmlmod
import json
import os
import re
import shutil
import sys
import time
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
B = 'https://open.feishu.cn/open-apis'
STATE = os.environ.get('SYNC_STATE_DIR') or os.path.join(HERE, 'v41')
DEFAULT_TARGET = os.environ.get('SYNC_TARGET') or os.path.join(HERE, 'v71_fix', '华曦达vs创维财报对比_v71_可编辑.html')
DEFAULT_DROPS = os.environ.get('SYNC_DROPS') or os.path.join(STATE, 'sync_inbox_drops')
LOG = os.path.join(STATE, 'sync_applied.json')
LEDGER = os.path.join(STATE, 'sync_ledger.jsonl')
UNRESOLVED = os.path.join(STATE, 'sync_unresolved.json')

PKG_RE = re.compile(r'SDMCSYNC1:([A-Za-z0-9+/=\s]+?):END')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
EDIT_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'td', 'th', 'dt', 'dd', 'blockquote', 'figcaption'}
EDIT_CLS = {'ex-title', 'ex-src', 'summary-text', 'summary-label', 'callout-title'}
NO_EDIT_CLS = {'ex-editor', 'ex-chart', 'tbl-tools'}
ROOT_CLS = {'cover', 'doc', 'colophon'}
RUNTIME_ATTRS = {'contenteditable', 'spellcheck', '_echarts_instance_'}
ANCHORS = (12, 6, 3, 1)
MIN_SCORE = 3


# ───────────────────────── Feishu inbox (optional source) ─────────────────────────

def _requests():
    import requests  # box-only dependency; tests and dry runs on drops never import it
    return requests


def token():
    r = _requests().post(
        B + '/auth/v3/tenant_access_token/internal',
        json={'app_id': os.environ['FEISHU_APP_ID'], 'app_secret': os.environ['FEISHU_APP_SECRET']},
        timeout=30,
    ).json()
    return r['tenant_access_token']


def inbox_token():
    p = os.path.join(STATE, 'inbox.json')
    if os.environ.get('SYNC_INBOX_TOKEN'):
        return os.environ['SYNC_INBOX_TOKEN']
    if os.path.exists(p):
        return json.load(open(p)).get('token')
    return None


def inbox_text():
    tok = inbox_token()
    if not tok:
        return ''
    r = _requests().get(
        f'{B}/docx/v1/documents/{tok}/raw_content',
        headers={'Authorization': 'Bearer ' + token()},
        timeout=30,
    ).json()
    if r.get('code'):
        raise RuntimeError('inbox read failed: %s' % r)
    return r['data']['content']


# ───────────────────────── packages ─────────────────────────

def decode_block(b64):
    s = re.sub(r'\s', '', b64)
    s += '=' * (-len(s) % 4)
    return json.loads(base64.b64decode(s).decode('utf-8'))


def blocks(text):
    """Return [(pkg, key)] de-duplicated by key. Bad blocks are reported and skipped."""
    out, seen = [], set()
    for m in PKG_RE.finditer(text or ''):
        raw = re.sub(r'\s', '', m.group(1))
        try:
            pkg = decode_block(raw)
        except Exception as e:
            print('skip bad block (truncated/garbled base64):', repr(e)[:120])
            continue
        if not isinstance(pkg, dict):
            continue
        key = pkg_key(pkg, raw)
        if key in seen:
            continue
        seen.add(key)
        out.append((pkg, key))
    return out


def pkg_key(pkg, raw=''):
    k = pkg.get('id') or pkg.get('ts')
    if k:
        return str(k)
    return 'h' + hashlib.sha1((raw or json.dumps(pkg, sort_keys=True)).encode()).hexdigest()[:16]


def is_meta_key(k):
    return str(k or '').startswith('__')


def has_real(pkg):
    return any(
        op.get('op') in ('edit', 'del') or (op.get('op') == 'data' and not is_meta_key(op.get('key')))
        for op in (pkg.get('ops') or []) if isinstance(op, dict)
    )


def is_ping(pkg):
    ops = pkg.get('ops') or []
    return bool(ops) and not has_real(pkg)


# ───────────────────────── HTML index ─────────────────────────

class El:
    __slots__ = ('tag', 'attrs', 's', 'oe', 'cs', 'ce', 'parent', 'kids')

    def __init__(self, tag, attrs, s, oe, parent):
        self.tag, self.attrs, self.s, self.oe = tag, dict(attrs), s, oe
        self.cs = self.ce = None
        self.parent, self.kids = parent, []

    def cls(self):
        return set((self.attrs.get('class') or '').split())

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent


class _Indexer(HTMLParser):
    def __init__(self, src):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.ls = [0] + [m.end() for m in re.finditer('\n', src)]
        self.stack, self.els = [], []
        self.feed(src)
        self.close()

    def _off(self):
        line, col = self.getpos()
        return self.ls[line - 1] + col

    def handle_starttag(self, tag, attrs):
        s = self._off()
        raw = self.get_starttag_text() or ''
        el = El(tag, attrs, s, s + len(raw), self.stack[-1] if self.stack else None)
        if el.parent is not None:
            el.parent.kids.append(el)
        self.els.append(el)
        if tag in VOID or raw.endswith('/>'):
            el.cs = el.ce = el.oe
        else:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        s = self._off()
        e = self.src.find('>', s) + 1 or len(self.src)
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k].tag == tag:
                el = self.stack[k]
                el.cs, el.ce = s, e
                del self.stack[k:]
                return


class _Text(HTMLParser):
    """Canonical form + visible text of an HTML fragment (entities decoded, whitespace collapsed)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canon, self.text, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        a = sorted((k, v or '') for k, v in attrs if k not in RUNTIME_ATTRS and not k.startswith('data-rt'))
        self.canon.append('<%s%s>' % (tag, ''.join(' %s="%s"' % kv for kv in a)))
        if tag == 'br':
            self.text.append(' ')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag not in VOID:
            self.canon.append('</%s>' % tag)

    def handle_data(self, d):
        self.canon.append(d)
        if not self.skip:
            self.text.append(d)


def _ws(s):
    return re.sub(r'\s+', ' ', s.replace('\xa0', ' ')).strip()


def _parse(h):
    p = _Text()
    p.feed(h or '')
    p.close()
    return p


def canon(h):
    return _ws(''.join(_parse(h).canon))


def plain(h):
    return _ws(''.join(_parse(h).text))


class Doc:
    def __init__(self, src):
        self.src = src
        self.els = [e for e in _Indexer(src).els if e.cs is not None]
        heads = [(e.s, plain(self.inner(e))) for e in self.els if e.tag in ('h1', 'h2', 'h3', 'h4')]
        self._hpos = [h[0] for h in heads]
        self._htxt = [h[1] for h in heads]
        self.body = [e for e in self.els if self._in_body(e)]

    def inner(self, el):
        return self.src[el.oe:el.cs]

    @staticmethod
    def _in_body(el):
        return el.tag not in ('head', 'script', 'style', 'template') and not any(
            a.tag in ('head', 'script', 'style', 'template') for a in el.ancestors())

    def by_eid(self, eid):
        return [e for e in self.body if e.attrs.get('data-eid') == str(eid)]

    def heading(self, el):
        i = bisect.bisect_left(self._hpos, el.s) - 1
        return self._htxt[i] if i >= 0 else ''

    def row_info(self, el):
        if el.tag in ('td', 'th') and el.parent is not None and el.parent.tag == 'tr':
            cells = [k for k in el.parent.kids if k.tag in ('td', 'th')]
            return plain(self.inner(cells[0]))[:30], cells.index(el)
        return '', -1

    def sib_text(self, el, d):
        if el.parent is None:
            return ''
        sibs = el.parent.kids
        i = sibs.index(el) + d
        return plain(self.inner(sibs[i]))[:40] if 0 <= i < len(sibs) else ''

    def editable(self, el):
        if not (el.tag in EDIT_TAGS or el.cls() & EDIT_CLS):
            return False
        if 'data-rt' in el.attrs or el.cls() & NO_EDIT_CLS:
            return False
        return not any('data-rt' in a.attrs or a.cls() & NO_EDIT_CLS for a in el.ancestors())


# ───────────────────────── op context & scoring ─────────────────────────

def op_ctx(op):
    """Context hints from new clients (h,row,col,prev,next) and old ones (ctx='id / row header')."""
    c = {k: op.get(k) for k in ('h', 'row', 'col', 'prev', 'next', 'tag')}
    legacy = op.get('ctx') or ''
    if legacy and not c.get('row') and ' / ' in legacy:
        c['row'] = legacy.split(' / ', 1)[1].strip()
    return c


def _same(a, b, n):
    a, b = _ws(a or '')[:n], _ws(b or '')[:n]
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def score(doc, el, c):
    s = 0
    if c.get('tag') and c['tag'] == el.tag:
        s += 1
    if c.get('h') and _same(doc.heading(el), c['h'], 40):
        s += 4
    row, col = doc.row_info(el)
    if c.get('row') and _same(row, c['row'], 30):
        s += 4
    if c.get('col') is not None and col >= 0 and int(c['col']) == col:
        s += 2
    if c.get('prev') and _same(doc.sib_text(el, -1), c['prev'], 40):
        s += 3
    if c.get('next') and _same(doc.sib_text(el, 1), c['next'], 40):
        s += 3
    return s


def has_hints(c):
    return any(c.get(k) for k in ('h', 'row', 'prev', 'next'))


def pick(doc, cands, c, strict=False):
    """Return (el, None) or (None, reason). strict: a lone candidate must also agree with context."""
    if not cands:
        return None, 'not found'
    if len(cands) == 1:
        if strict and has_hints(c) and score(doc, cands[0], c) < MIN_SCORE:
            return None, 'context mismatch'
        return cands[0], None
    scored = sorted(((score(doc, e, c), i, e) for i, e in enumerate(cands)), key=lambda t: (-t[0], t[1]))
    if scored[0][0] >= MIN_SCORE and scored[0][0] > scored[1][0]:
        return scored[0][2], None
    return None, 'ambiguous: %d candidates (best score %d)' % (len(cands), scored[0][0])


def innermost(doc, els):
    """Drop candidates that contain another candidate (prefer the deepest editable)."""
    ids = set(map(id, els))
    return [e for e in els if not any(id(k) in ids for k in _descendants(e))]


def _descendants(el):
    for k in el.kids:
        yield k
        yield from _descendants(k)


# ───────────────────────── edit / delete / data ─────────────────────────

def clean_fragment(h):
    h = h or ''
    h = re.sub(r'\s(?:contenteditable|spellcheck)(?:="[^"]*")?', '', h)
    h = re.sub(r'<script\b[\s\S]*?</script\s*>', '', h, flags=re.I)
    return h


def _splice(src, a, b, mid):
    return src[:a] + mid + src[b:]


def _in_tag(raw, at):
    return raw.rfind('<', 0, at) > raw.rfind('>', 0, at)


def _text_find(raw, form, start=0):
    """First occurrence of form that sits in text, not inside a tag/attribute."""
    at = raw.find(form, start)
    while at >= 0 and _in_tag(raw, at):
        at = raw.find(form, at + 1)
    return at


def _text_count(raw, form):
    n, at = 0, _text_find(raw, form)
    while at >= 0:
        n += 1
        at = _text_find(raw, form, at + len(form))
    return n


def resolve_edit(doc, op):
    """Return (new_src | None, how, reason)."""
    old, new = op.get('old') or '', clean_fragment(op.get('new') or '')
    c_old, c_new, p_old, p_new = canon(old), canon(new), plain(old), plain(new)
    if c_old == c_new:
        return None, 'noop', None
    ctx = op_ctx(op)
    eid = op.get('eid')
    cands = [e for e in doc.body if doc.editable(e) or e.attrs.get('data-eid')]

    # 1) eid hint — only trusted when the element still holds old (or already holds new)
    if eid:
        for el in doc.by_eid(eid):
            cur = doc.inner(el)
            if canon(cur) == c_old or (p_old and plain(cur) == p_old):
                return _splice(doc.src, el.oe, el.cs, new), 'eid', None
            if canon(cur) == c_new:
                return None, 'already', None

    # 2) whole-content match (canonical HTML, then visible text)
    for level, key, val in (('content', canon, c_old), ('text', plain, p_old)):
        if not val:
            continue
        hits = innermost(doc, [e for e in cands if key(doc.inner(e)) == val])
        if hits:
            el, why = pick(doc, hits, ctx)
            if el is None:
                return None, None, why
            return _splice(doc.src, el.oe, el.cs, new), level, None

    # already applied? (old gone, new present in a matching context)
    if c_new:
        done = innermost(doc, [e for e in cands if canon(doc.inner(e)) == c_new or (p_new and plain(doc.inner(e)) == p_new)])
        if done and pick(doc, done, ctx, strict=True)[0] is not None:
            return None, 'already', None

    # 3) anchored substring inside one element (master paragraph drifted, or old is a short span)
    pre = 0
    while pre < min(len(p_old), len(p_new)) and p_old[pre] == p_new[pre]:
        pre += 1
    suf = 0
    while suf < min(len(p_old), len(p_new)) - pre and p_old[-1 - suf] == p_new[-1 - suf]:
        suf += 1
    o_mid, n_mid = p_old[pre:len(p_old) - suf], p_new[pre:len(p_new) - suf]
    seen_any = False
    for w in ANCHORS:
        left = p_old[max(0, pre - w):pre]
        right = p_old[len(p_old) - suf:len(p_old) - suf + w]
        needle_o, needle_n = left + o_mid + right, left + n_mid + right
        if len(needle_o) < 2 or not (left + right):
            continue
        hits = _hits(doc, cands, needle_o)
        if not hits:
            continue
        seen_any = True
        el, why = pick(doc, [h[0] for h in hits], ctx)
        if el is None:
            return None, None, why
        form = next(h[1] for h in hits if h[0] is el)
        repl = needle_n if form == needle_o else htmlmod.escape(needle_n, quote=False)
        raw = doc.inner(el)
        at = _text_find(raw, form)
        inner = raw[:at] + repl + raw[at + len(form):]
        return _splice(doc.src, el.oe, el.cs, inner), 'anchored', None
    if not seen_any and o_mid != n_mid:
        w = ANCHORS[0]
        needle_n = p_old[max(0, pre - w):pre] + n_mid + p_old[len(p_old) - suf:len(p_old) - suf + w]
        if len(needle_n) >= 2 and _hits(doc, cands, needle_n):
            return None, 'already', None
    return None, None, 'not found'


def _hits(doc, cands, needle):
    """[(el, form, count)] for innermost elements containing needle exactly once (as text)."""
    hits = []
    for e in cands:
        raw = doc.inner(e)
        for form in dict.fromkeys((needle, htmlmod.escape(needle, quote=False))):
            n = _text_count(raw, form)
            if n:
                hits.append((e, form, n))
                break
    els = set(map(id, innermost(doc, [h[0] for h in hits])))
    return [h for h in hits if id(h[0]) in els and h[2] == 1]


def resolve_del(doc, op):
    old = op.get('old') or ''
    for el in doc.by_eid(op.get('eid')):
        if not old or canon(doc.inner(el)) == canon(old):
            return _splice(doc.src, el.s, el.ce, ''), 'eid', None
    hits = innermost(doc, [e for e in doc.body if doc.editable(e) and old and canon(doc.inner(e)) == canon(old)])
    el, why = pick(doc, hits, op_ctx(op))
    if el is None:
        return None, ('already' if why == 'not found' else None), (None if why == 'not found' else why)
    return _splice(doc.src, el.s, el.ce, ''), 'content', None


DATA_RE = re.compile(r'(<script\b[^>]*\bid="report-data"[^>]*>)([\s\S]*?)(</script>)', re.I)


def patch_report_data(src, op):
    m = DATA_RE.search(src)
    if not m:
        return None, None, 'no #report-data'
    try:
        data = json.loads(m.group(2).strip() or '{}')
    except Exception as e:
        return None, None, 'report-data unparsable: %r' % e
    key, new, old = str(op.get('key') or ''), op.get('new'), op.get('old')
    notes = []
    if key == '@charts' and isinstance(new, dict):
        cur = data.setdefault('charts', {})
        old = old if isinstance(old, dict) else {}
        touched = 0
        for cid in sorted(set(new) | set(old)):
            o, n = old.get(cid), new.get(cid)
            if o == n or cur.get(cid) == n:
                continue
            if cid in cur and o is not None and cur.get(cid) != o:
                notes.append('chart %s also changed in master; browser edit wins' % cid)
            if n is None:
                cur.pop(cid, None)
            else:
                cur[cid] = n
            touched += 1
        if not touched:
            return None, 'already', None
    elif key.startswith('@'):
        if data.get(key[1:]) == new:
            return None, 'already', None
        data[key[1:]] = new
    else:
        v = data.setdefault('v', {})
        if v.get(key) == new:
            return None, 'already', None
        v[key] = new
    body = '\n' + json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + '\n'
    return src[:m.start(2)] + body + src[m.end(2):], 'data', '; '.join(notes) or None


def apply_ops(src, ops):
    """Apply ops sequentially. Returns (src, [result dict]). Never raises on a bad op."""
    res = []
    for i, op in enumerate(ops or []):
        kind = (op or {}).get('op') if isinstance(op, dict) else None
        r = {'i': i, 'op': kind, 'eid': (op or {}).get('eid') if isinstance(op, dict) else None}
        try:
            if kind == 'edit':
                out, how, why = resolve_edit(Doc(src), op)
                r['preview'] = '%s → %s' % (plain(op.get('old'))[:40], plain(op.get('new'))[:40])
            elif kind == 'del':
                out, how, why = resolve_del(Doc(src), op)
                r['preview'] = 'del %s' % plain(op.get('old'))[:40]
            elif kind == 'data':
                if is_meta_key(op.get('key')):
                    out, how, why = None, 'meta', None
                else:
                    out, how, why = patch_report_data(src, op)
                r['preview'] = 'data %s' % op.get('key')
            else:
                out, how, why = None, None, 'unknown op'
        except Exception as e:
            out, how, why = None, None, 'error %r' % (e,)
        if out is not None:
            src = out
        r.update(ok=how is not None, how=how, reason=why)
        res.append(r)
    return src, res


# ───────────────────────── rev + eid stamping ─────────────────────────

REV_RE = re.compile(r'<meta\s+name="sync-rev"\s+content="[^"]*"\s*/?>', re.I)


def compute_rev(src):
    return hashlib.sha1(REV_RE.sub('<meta name="sync-rev" content="">', src).encode('utf-8')).hexdigest()[:12]


def get_rev(src):
    m = re.search(r'<meta\s+name="sync-rev"\s+content="([^"]*)"', src, re.I)
    return (m.group(1) if m else '') or compute_rev(src)


def set_rev(src):
    blank = '<meta name="sync-rev" content="">'
    if REV_RE.search(src):
        src = REV_RE.sub(blank, src, count=1)
    else:
        m = re.search(r'<meta\s+charset[^>]*>', src, re.I) or re.search(r'<head[^>]*>', src, re.I)
        at = m.end() if m else 0
        src = src[:at] + '\n' + blank + src[at:]
    rev = compute_rev(src)
    return src.replace(blank, '<meta name="sync-rev" content="%s">' % rev, 1), rev


def stamp_eids(src):
    """Persist data-eid on every editable element so eids never shift between tabs and replaces."""
    doc = Doc(src)
    nums = [int(e.attrs['data-eid']) for e in doc.body if str(e.attrs.get('data-eid', '')).isdigit()]
    nxt = max(nums or [0])
    todo = []
    for el in doc.body:
        if 'data-eid' in el.attrs or not doc.editable(el):
            continue
        anc = list(el.ancestors())
        if not any(a.cls() & ROOT_CLS for a in anc) or not any(a.tag == 'main' for a in anc):
            continue
        if el.tag == 'figcaption' and 'ex-head' in el.cls():
            continue
        if any(doc.editable(a) and not (a.tag == 'figcaption' and 'ex-head' in a.cls()) for a in anc
               if any(r.cls() & ROOT_CLS for r in a.ancestors())):
            continue
        nxt += 1
        todo.append((el, nxt))
    for el, n in sorted(todo, key=lambda t: -t[0].s):
        end = el.oe - (2 if src[el.oe - 2:el.oe] == '/>' else 1)
        src = src[:end] + ' data-eid="%d"' % n + src[end:]
    return src, len(todo)


# ───────────────────────── state files ─────────────────────────

def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


def _dump(path, obj):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Lock:
    def __init__(self, path):
        self.path = path + '.lock'

    def __enter__(self):
        try:
            import fcntl
            self.f = open(self.path, 'w')
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except ImportError:
            self.f = None
        return self

    def __exit__(self, *a):
        if self.f:
            self.f.close()


def gather_text(a):
    txt = ''
    if not a.no_inbox:
        try:
            txt += inbox_text()
        except Exception as e:
            print('inbox unavailable, continuing with drops:', repr(e)[:160])
    for d in a.drops:
        for f in sorted(glob.glob(os.path.join(d, '*.txt'))):
            txt += '\n' + open(f, encoding='utf-8', errors='replace').read()
    for f in a.text:
        txt += '\n' + open(f, encoding='utf-8', errors='replace').read()
    return txt


def run(a):
    with Lock(a.target):
        src = open(a.target, encoding='utf-8').read()
        before = len(src.encode('utf-8'))

        if a.stamp:
            src, n = stamp_eids(src)
            src, rev = set_rev(src)
            print('stamped %d eids, rev %s' % (n, rev))
            if not a.dry:
                shutil.copy(a.target, a.target + '.pre_stamp_' + time.strftime('%Y%m%d_%H%M%S'))
                open(a.target, 'w', encoding='utf-8').write(src)
            return {'stamped': n, 'rev': rev}

        done = set(map(str, _load(a.log, [])))
        if a.replay:
            todo = []
            for line in open(a.replay, encoding='utf-8'):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                todo.append(({'id': 'replay', 'ts': rec.get('ts', ''), 'ops': [rec['op']]}, 'replay'))
        elif a.retry_unresolved:
            un = _load(UNRESOLVED, [])
            todo = [({'id': 'retry', 'ts': '', 'ops': [u['op'] for u in un]}, 'retry')] if un else []
        else:
            allb = blocks(gather_text(a))
            fresh = [(p, k) for p, k in allb if k not in done and not (p.get('ts') and str(p['ts']) in done)]
            pings = [k for p, k in fresh if is_ping(p)]
            if pings and not a.dry:
                done |= set(pings)
                _dump(a.log, sorted(done))
                print('skip ping-only', len(pings))
            todo = [(p, k) for p, k in fresh if has_real(p)]
            todo.sort(key=lambda t: str(t[0].get('ts') or ''))
        if not todo:
            print('no new edits')
            return {'packages': []}

        rev0 = get_rev(src)
        report, ledger, unresolved = [], [], []
        for pkg, key in todo:
            ops = [op for op in (pkg.get('ops') or []) if isinstance(op, dict)]
            src, res = apply_ops(src, ops)
            stale = bool(pkg.get('rev')) and pkg.get('rev') != rev0
            ok = [r for r in res if r['ok'] and r['how'] not in ('meta', 'noop')]
            bad = [r for r in res if not r['ok']]
            print('%s %s ts=%s ops=%d ok=%d unresolved=%d%s' % (
                pkg.get('ver', '?'), key, pkg.get('ts', '-'), len(ops), len(ok), len(bad), ' (stale tab)' if stale else ''))
            for r in res:
                print('   #%d %-4s %-9s %s%s' % (r['i'], r['op'], r['how'] or 'FAIL', r.get('preview', ''),
                                                  ('  [%s]' % r['reason']) if r['reason'] else ''))
            for r in res:
                if r['ok'] and r['how'] not in ('already', 'meta', 'noop'):
                    ledger.append({'key': key, 'ts': pkg.get('ts', ''), 'how': r['how'], 'op': ops[r['i']]})
                if not r['ok']:
                    unresolved.append({'key': key, 'ts': pkg.get('ts', ''), 'reason': r['reason'],
                                       'preview': r.get('preview', ''), 'op': ops[r['i']]})
            report.append({'id': key, 'ts': pkg.get('ts', ''), 'total': len(ops), 'applied': len(ok),
                           'unresolved': [{'i': r['i'], 'reason': r['reason'], 'preview': r.get('preview', '')} for r in bad],
                           'stale_tab': stale})

        after_src = src
        changed = bool(ledger)
        rev = rev0
        if changed:
            after_src, rev = set_rev(src)
        after = len(after_src.encode('utf-8'))
        if after > before * 1.15 + 5000:
            raise SystemExit('refuse write: size balloon %s -> %s (would re-bloat)' % (before, after))
        if a.dry:
            print('dry run: would write' if changed else 'dry run: nothing to write', before, '->', after)
        else:
            if changed:
                out = a.out or a.target
                if out == a.target:
                    shutil.copy(a.target, a.target + '.pre_sync_' + time.strftime('%Y%m%d_%H%M%S'))
                open(out, 'w', encoding='utf-8').write(after_src)
                os.makedirs(os.path.dirname(LEDGER) or '.', exist_ok=True)
                with open(LEDGER, 'a', encoding='utf-8') as f:
                    for rec in ledger:
                        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                print('applied ->', out, 'bytes', before, '->', after, 'rev', rev)
            if not (a.replay or a.retry_unresolved):
                done |= {k for _, k in todo}
                _dump(a.log, sorted(done))
                if unresolved:
                    _dump(UNRESOLVED, _load(UNRESOLVED, []) + unresolved)
            elif a.retry_unresolved:
                _dump(UNRESOLVED, unresolved)
        for r in report:
            r.update(rev=rev, written=changed and not a.dry, at=time.strftime('%Y-%m-%d %H:%M:%S'))
            if a.status_dir and not a.dry:
                _dump(os.path.join(a.status_dir, re.sub(r'[^A-Za-z0-9_.-]', '_', r['id']) + '.json'), r)
        summary = {'packages': report, 'rev': rev, 'written': changed and not a.dry}
        print('SYNC_RESULT ' + json.dumps(summary, ensure_ascii=False))
        return summary


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--target', default=DEFAULT_TARGET)
    ap.add_argument('--out', help='write result here instead of overwriting --target')
    ap.add_argument('--text', nargs='*', default=[], help='extra files containing SDMCSYNC1 packages')
    ap.add_argument('--drops', nargs='*', default=None, help='drop dirs (default: %s)' % DEFAULT_DROPS)
    ap.add_argument('--no-inbox', action='store_true', help='do not read the Feishu inbox docx')
    ap.add_argument('--dry', action='store_true', help='resolve and report only; write nothing')
    ap.add_argument('--log', default=LOG, help='applied-package log')
    ap.add_argument('--status-dir', help='write one <id>.json apply result per package (served by relay /status)')
    ap.add_argument('--stamp', action='store_true', help='persist data-eid + sync-rev into --target, then exit')
    ap.add_argument('--replay', help='re-apply a sync_ledger.jsonl onto --target (after a writer rebuild)')
    ap.add_argument('--retry-unresolved', action='store_true', help='retry ops in sync_unresolved.json')
    a = ap.parse_args(argv)
    if a.drops is None:
        a.drops = [DEFAULT_DROPS] if os.path.isdir(DEFAULT_DROPS) else []
    return a


def main(argv=None):
    return run(parse_args(argv))


if __name__ == '__main__':
    main()
