#!/usr/bin/env python3
"""Surgical toolbar fix for live reports that carry their own (v46-style) client, e.g. the 华曦达 v71 page.

  python3 fix_live_page.py <master.html> --rep huaxida-h1 [--dry]

* removes the「恢复原始数据」(#bReset) and dead「复制修改」(#bCopy) buttons, so「同步修改」is the only sync control;
* guards every script reference to the removed buttons — deleting the tags alone makes
  `bReset.addEventListener(...)` throw, which aborts the script before「同步修改」gets its click handler;
* stamps `rep:"<rep>"` into the SDMCSYNC1 package so the relay routes it by report id, not by client version.
Idempotent; writes a .pre_fix_<time> backup; touches nothing else in the page.
"""
import argparse
import re
import shutil
import sys
import time

REMOVE = {'bReset': '恢复原始数据', 'bCopy': '复制修改'}


def remove_button(src, bid):
    rx = re.compile(r'[ \t]*<button\b[^>]*\bid="%s"[^>]*>[\s\S]*?</button>[ \t]*\n?' % re.escape(bid))
    return rx.subn('', src)


def guard_refs(src, bid):
    n = 0
    q = r'''(?:'%s'|"%s")''' % (bid, bid)
    src, k = re.subn(r'document\.getElementById\(%s\)\.addEventListener\(' % q,
                     "(document.getElementById('%s')||{addEventListener(){}}).addEventListener(" % bid, src)
    n += k
    for var in set(re.findall(r'\b(\w+)\s*=\s*document\.getElementById\(%s\)' % q, src)):
        src, k = re.subn(r'(?<![\w.&|])(?<!if\(%s\))%s\.addEventListener\(' % (var, var),
                         'if(%s)%s.addEventListener(' % (var, var), src)
        n += k
    return src, n


def stamp_rep(src, rep):
    if re.search(r'JSON\.stringify\(\{ver:SYNC_VER,rep:', src):
        return src, 0
    return re.subn(r'JSON\.stringify\(\{ver:SYNC_VER,', 'JSON.stringify({ver:SYNC_VER,rep:%s,' % repr(rep), src)


def fix(src, rep):
    report = {}
    for bid in REMOVE:
        src, report['removed_' + bid] = remove_button(src, bid)
        src, report['guarded_' + bid] = guard_refs(src, bid)
    if rep:
        src, report['rep_stamped'] = stamp_rep(src, rep)
    left = [label for bid, label in REMOVE.items() if re.search(r'<button\b[^>]*\bid="%s"' % bid, src)]
    if left:
        raise SystemExit('buttons still present: %s' % left)
    return src, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('html')
    ap.add_argument('--rep', required=True)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args(argv)
    with open(a.html, encoding='utf-8') as f:
        src = f.read()
    out, rep = fix(src, a.rep)
    print(rep)
    if out != src and not a.dry:
        shutil.copy(a.html, a.html + '.pre_fix_' + time.strftime('%Y%m%d_%H%M%S'))
        with open(a.html, 'w', encoding='utf-8') as f:
            f.write(out)
        print('written', a.html)
    return rep


if __name__ == '__main__':
    main(sys.argv[1:])
