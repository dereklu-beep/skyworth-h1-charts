#!/usr/bin/env python3
"""v71 -> v72: apply the accepted REPORT_REVIEW fixes to the 华曦达 report.

Usage: build_v72.py V71.html NOTES_SRC.json NOTES_NEW.json OUT.html

Every edit asserts its expected match count; a mismatch aborts the build so the
output never silently diverges from the reviewed source.
"""
import json
import re
import sys


def sub(s, old, new, count=1, label=''):
    n = s.count(old)
    if n != count:
        raise SystemExit(f'[{label or old[:40]}] expected {count} match(es), found {n}')
    return s.replace(old, new)


def tpl_bounds(s):
    a = s.index('<template id="report-tpl">')
    return a, s.index('</template>', a)


def in_tpl(s, fn):
    a, b = tpl_bounds(s)
    return s[:a] + fn(s[a:b]) + s[b:]


def table_span(t, tid):
    a = t.index(f'id="{tid}"')
    a = t.rindex('<table', 0, a)
    return a, t.index('</table>', a) + len('</table>')


F = '<b class="t f it">事实</b>'
C = '<b class="t c it">计算</b>'
I = '<b class="t i it">推断</b>'


def fix_annotations(t):
    t = sub(t, '<b>杨健家族（公司高管党慧、陈京华前同事）</b>', '<b>杨健家族</b>', label='t-eq group')
    a, b = table_span(t, 't-eq')
    tab = t[a:b]
    tab = sub(tab, '<td class="nw1">杨健</td><td class="nw1 num">600,000</td>',
              '<td class="nw1">杨健（曾与党慧在同洲电子共事）</td><td class="nw1 num">600,000</td>',
              label='t-eq 杨健 row')
    t = t[:a] + tab + t[b:]
    eq_note = '<p class="tnote">持股比例合计显示 100.02%，为各行四舍五入所致，非股本多计' + C + '。</p>'
    t = sub(t, eq_note, eq_note + '<p class="tnote">深圳创展 2019-11-22 增至 800.2 万股，按 2022 年送股后股数翻倍应为 1,600.4 万股，'
            '现持 1,800.4 万股，多出的 200 万股来源未披露' + C + '。</p>', label='t-eq 创展 gap')
    t = sub(t, '<td>深圳创展（公司高管党慧、陈京华前同事）</td>',
            '<td>深圳创展（杨健任普通合伙人）</td>', label='t-cost 深圳创展')
    if '前同事' in t.replace('同洲前同事属个人履历交集', ''):
        leftovers = [t[m.start() - 40:m.start() + 20] for m in re.finditer('前同事', t)]
        print('note: remaining 前同事 mentions (notes only):', leftovers)
    return t


def fix_ipo_alloc(t):
    a, b = table_span(t, 't-ipo-alloc')
    tab = t[a:b]
    tab = sub(tab, '<th class="num">占总股本</th>',
              '<th class="num">占 IPO 获配<br><small>19,207,300 股</small></th>'
              '<th class="num">占总股本<br><small>209,540,070 股</small></th>', label='alloc head')
    shares = {'1,731,800': '9.02%', '1,038,500': '5.41%', '579,100': '3.02%',
              '1,920,800': '10.00%', '13,937,100': '72.56%', '19,207,300': '100.00%'}
    rows = tab.split('<tr')
    for i, r in enumerate(rows):
        if '<td' not in r:
            continue
        cells = re.findall(r'<td\b[^>]*>.*?</td>', r)
        key = re.sub(r'<[^>]+>|事实|计算', '', cells[1]).strip()
        pct = shares.get(key)
        if pct is None:
            ins = '<td class="num">—</td>'
        elif key == '19,207,300':
            ins = f'<td class="num"><b>{pct}</b></td>'
        else:
            ins = f'<td class="num"><span class="nw">{pct}{C}</span></td>'
        rows[i] = r.replace(cells[1], cells[1] + ins, 1)
    tab = '<tr'.join(rows)
    tab = sub(tab, '<td>国泰君安 TRS（IPO 获配）</td>',
              '<td>国泰君安 TRS（总收益互换，代客户持股）</td>', label='alloc TRS gloss')
    t = t[:a] + tab + t[b:]
    return t


def fix_rounding(t):
    n = t.count('6.64%')
    t = t.replace('6.64%', '6.65%')
    print(f'6.64% -> 6.65%: {n} in template')
    t = sub(t, '<p class="tnote">浮盈按近 20 日均价 63.31 港元估算，立讯老股解禁前不能兑现' + C + '。</p>',
            '<p class="tnote">浮盈按近 20 日均价 63.31 港元估算，立讯老股解禁前不能兑现' + C
            + '。占总股本各行四舍五入后相加为 9.18%，与合计 9.17% 的差异为舍入' + C + '。</p>',
            label='alloc rounding note')
    return t


def fix_conclusions(t):
    t = sub(t, '<b>总体判断：四点结论，后文各板块逐一展开</b>',
            '<b>总体判断：五点结论，后文各板块逐一展开</b>', label='concl cap')
    t = sub(t, '2026H1 净利润 1.81 亿元人民币，经营现金流为 −6.24 亿元人民币，差额主要被存货占用',
            '同期经营现金流为 −6.24 亿元人民币，与净利润的差额主要被存货占用', label='concl 1 dedupe')
    t = sub(t, '「↶ 撤销删除」或 Ctrl+Z 恢复', 'Ctrl+Z 恢复', label='editbar undo')
    t = sub(t, '<li data-co="s"><b>在做什么：</b>按订单预测提前备货' + F,
            '<li data-co="s"><b>在做什么：</b>2026H1 收入 20.95 亿元人民币，同比增长 36.3%；净利润 1.81 亿元人民币，'
            '同比增长 75.9%，较 2025H2 增长 33.4%' + C + '。公司按订单预测提前备货' + F,
            label='concl 1')
    old2_start = t.index('<li data-co="s"><b>利润从哪来：</b>')
    old2_end = t.index('</li>', old2_start) + len('</li>')
    t = (t[:old2_start]
         + '<li data-co="s"><b>利润从哪来：</b>2026H1 毛利同比增加 1.72 亿元人民币，其中约 0.92 亿元人民币来自零件及配件转售'
         + C + '。剔除这部分超额毛利和坏账准备转回后，按 2025 年 7 月至 2026 年 6 月利润算的市盈率约 53.3 倍；'
         '再扣除低价库存带来的整机毛利（只扣了 2026H1，属上限试算）约 59.5 倍' + I
         + '。两者约为港股硬件 ODM 中位数 18.69 倍的 2.9 至 3.2 倍' + I + '。</li>'
         + t[old2_end:])
    last = t.index('</li>', t.index('<li data-co="s"><b>主要风险：</b>')) + len('</li>')
    t = (t[:last]
         + '\n<li data-co="s"><b>接下来看什么：</b>20.93 亿元人民币存货能否随客户订单出货消化，客户预付是最直接的线索'
         + I + '；7.32 亿元人民币计息借款全部一年内到期，公司要么续借、要么动用尚未使用的募资' + I
         + '；存储芯片价格一旦回落，零件及配件转售的超额毛利会随之收窄' + I + '。</li>'
         + t[last:])
    return t


def fix_leftovers(t):
    for k in ('华曦达·财务', '华曦达·供应商', '华曦达·客户'):
        t = sub(t, f'data-co="s">{k}</a>', f'data-co="s">{k.split("·")[1]}</a>', label='toc ' + k)
    t = sub(t, '主因海外生产加重' + C + '/' + F, '主因海外生产加重' + F, label='double tag')
    t = sub(t, '。2026H1 见表下说明' + F + '。', '。', label='见表下说明')
    t = sub(t, '2024 年现金净变动按招股书 162,516 千元列 1.63 亿元',
            '2024 年现金净变动按招股书列 1.63 亿元人民币', label='千元')
    t = sub(t, '该数减去本期存货撇减 0.19', '该数减去本期存货撇减（当期计提的存货跌价损失）0.19',
            label='撇减 gloss')
    t = sub(t, '未披露＝已查找但公司没有披露。', '未披露＝已查找但公司没有披露；—＝该期无此项或不适用。',
            label='legend dash')
    t = sub(t, '<td>华曦达（含 H1 第③行、H2 未估的试算 1.81）</td>',
            '<td>华曦达（再扣低价库存整机毛利的试算 1.81）</td>', label='t-val ③ label')
    t = sub(t, '再扣低价库存收益后的近 12 个月利润 1.81（含 H1 第③行、H2 未估）',
            '再扣低价库存收益后的近 12 个月利润 1.81（只扣了 2026H1，2025H2 未估）', label='t-val ③ note')
    a = t.index('<td>中国准则合计</td>')
    a = t.rindex('<tr class="pair">', 0, a)
    t = t[:a] + t[t.index('</tr>', a) + len('</tr>'):]
    t = sub(t, '<p class="tnote">中国准则合计等于利息支出减利息收入再加汇兑损益，即 A 股财务费用的算法；香港准则账面数为列报的财务成本'
            + C + '。同一笔财务成本，两种准则算出来不一样' + F + '。</p>', '', label='CN GAAP note')
    if '中国准则' in t:
        raise SystemExit('中国准则 leftover')
    return t


NOTE_EDITS = {
    'm-ipo#0': [('发行估值低于立讯、华勤而高于同口径 H 股龙旗，上市首日的估值抬升更多反映市场定价变化' + C,
                 '发行估值低于立讯、华勤而高于同口径 H 股龙旗' + C + '，上市首日的估值抬升更多反映市场定价变化' + I)],
    'm-ipo#1': [('占总股本应为 6.65%', '占总股本 6.65%')],
}


def fix_notes(t, notes):
    for key, new in notes.items():
        for old_part, new_part in NOTE_EDITS.get(key, ()):
            new = sub(new, old_part, new_part, label='note edit ' + key)
        t = sub(t, NOTES_SRC[key]['right_html'], new, label='note ' + key)
    return t


def fix_toolbar(s):
    s = sub(s, '<button class="btn" id="bPrint" type="button" title="调用浏览器打印 / 另存 PDF">打印</button>', '',
            label='bPrint')
    s = sub(s, '<button class="btn" id="bReset" type="button">恢复原始数据</button>', '', label='bReset')
    s = sub(s, '<button class="btn" id="bUndo" type="button" hidden disabled>↶ 撤销删除</button>', '', label='bUndo')
    s = re.sub(r'\s*<button class="btn" id="bCopy"[^>]*>复制修改</button>', '', s)
    if 'id="bCopy"' in s:
        raise SystemExit('bCopy still present')
    s = sub(s, "document.getElementById('bUndo').addEventListener('click',doUndo);",
            "{const _u=document.getElementById('bUndo'); if(_u) _u.addEventListener('click',doUndo);}",
            label='bUndo js')
    s = sub(s, "bReset.addEventListener('click',", "if(bReset) bReset.addEventListener('click',", label='bReset js')
    s = sub(s, "document.getElementById('bCopy').addEventListener('click',()=>doCopy(false));",
            "{const _c=document.getElementById('bCopy'); if(_c) _c.addEventListener('click',()=>doCopy(false));}",
            label='bCopy js')
    return s


LOCAL_JS = r"""
const LOCAL_KEY='sdmc_local_edits:'+location.pathname+':'+document.getElementById('report-tpl').innerHTML.length;
function saveLocal(){ try{ const ops=collectEdits(); if(ops.length) localStorage.setItem(LOCAL_KEY,JSON.stringify(ops)); else localStorage.removeItem(LOCAL_KEY); }catch(e){} }
function restoreLocal(){
  let ops=null; try{ ops=JSON.parse(localStorage.getItem(LOCAL_KEY)||'null'); }catch(e){}
  if(!Array.isArray(ops)||!ops.length) return 0;
  let n=0;
  ops.forEach(o=>{
    if(o.op==='data'){ if(String(o.key)[0]==='@') DATA[o.key.slice(1)]=o.new; else { DATA.v=DATA.v||{}; DATA.v[o.key]=o.new; } n++; return; }
    const el=tplNode(o.eid); if(!el||el.innerHTML!==o.old) return;
    if(o.op==='edit') el.innerHTML=o.new; else if(o.op==='del') el.remove();
    n++;
  });
  if(n) rebuildSheet();
  return n;
}
window.__restoredLocal=restoreLocal();
window.addEventListener('pagehide',saveLocal);
document.addEventListener('visibilitychange',()=>{ if(document.visibilityState==='hidden') saveLocal(); });
bEdit.addEventListener('click',saveLocal);
document.addEventListener('keydown',e=>{ if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){ e.preventDefault(); saveLocal(); const b=document.getElementById('bSave'); if(b) b.click(); } });
"""


def fix_local_edits(s):
    s = sub(s, '<button class="btn" id="bSync" type="button" hidden',
            '<button id="bSave" type="button" hidden aria-hidden="true" style="display:none!important"></button>'
            '<button class="btn" id="bSync" type="button" hidden', label='bSave anchor')
    s = sub(s, '\nrebuildSheet(); takeSnap();\n})();', '\nrebuildSheet(); takeSnap();\n' + LOCAL_JS + '})();',
            label='local edits js')
    s = sub(s, "a.download='华曦达_2026H1_CFO简报_'", "a.download='华曦达_2026H1财报分析_改后_'", label='download name')
    s = sub(s, '「同步修改」会保存改写和删除并写回同一飞书链接。',
            '「同步修改」会保存改写和删除并写回同一飞书链接；改动自动留在本浏览器，Ctrl+S（Mac 为 ⌘S）下载改过的页面。',
            label='editbar save')
    return s


WIDE_TABLES = ('t-s-mempx', 't-s-cycle', 't-s-c26', 't-s-c25', 't-ipo-alloc', 't-neeq', 't-cost', 't-peer')


def fix_layout(s):
    rule = '#sheet .duo{display:block!important;grid-template-columns:none!important;padding-left:0!important;padding-right:0!important}'
    wide = ','.join('#' + t for t in WIDE_TABLES)
    stack = '@media (min-width:1200px){#sheet .duo:has(' + wide + '){' + rule[len('#sheet .duo{'):]
    return sub(s, rule, '@media (max-width:1199px){' + rule + '}' + stack + '}', label='layout70')


def fix_meta(s):
    s = sub(s, '<span class="cal os">海外口径</span><span class="cal sub">子公司单体</span>', '', label='legend chips')
    return sub(s, '｜v71｜', '｜v72｜', label='version')


NOTES_SRC = {}


def main(src, notes_src_path, notes_path, out):
    global NOTES_SRC
    s = open(src, encoding='utf-8').read()
    NOTES_SRC = {o['key']: o for o in json.load(open(notes_src_path, encoding='utf-8'))}
    notes = json.load(open(notes_path, encoding='utf-8'))
    s = in_tpl(s, lambda t: fix_notes(t, notes))
    s = in_tpl(s, fix_annotations)
    s = in_tpl(s, fix_ipo_alloc)
    s = in_tpl(s, fix_rounding)
    s = in_tpl(s, fix_conclusions)
    s = in_tpl(s, fix_leftovers)
    s = fix_toolbar(s)
    s = fix_local_edits(s)
    s = fix_layout(s)
    s = fix_meta(s)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(s)
    print('wrote', out, len(s.encode()), 'bytes')


if __name__ == '__main__':
    main(*sys.argv[1:5])
