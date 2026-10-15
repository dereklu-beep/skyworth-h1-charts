#!/usr/bin/env python3
"""创维数字｜2026H1 财报分析 HTML 自检（只用标准库）。

报告主体：创维数字股份有限公司（000810.SZ，简称创维数字）。创维集团（00751.HK）只允许出现在
9 股权与资本结构（s-k-eq），作为间接控股股东。

用法：
  python3 check.py [skyworth-report.html]             # 自检，有 FAIL 时退出码 1
  python3 check.py [skyworth-report.html] --fix-eids  # 给新加的可改元素补 data-eid（原地改文件）
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = [
    "s-cover", "s-concl",
    "s-k-ops", "s-k-prod", "s-k-region", "s-k-cf", "s-k-inv", "s-k-cust", "s-k-supp", "s-k-debt", "s-k-eq",
    "s-cmp-intro", "s-cmp-region", "s-cmp-cust", "s-cmp-prod", "s-cmp-wc",
    "s-method",
]
OPTIONAL = ["s-cmp-val"]
# 瘦身版（<meta name="report-profile" content="slim">）：海外四块＋同业对照要点，正文不放表
REQUIRED_SLIM = ["s-cover", "s-concl", "s-k-region", "s-k-cust", "s-k-ar", "s-k-debt", "s-cmp-os", "s-method"]
# 瘦身 v2（content="slim_v2"）：同一章节骨架；四拍核心块各恰好 1 张表，左表（.duo-l）右判（.duo-r .judg）；
# 核心结论恰好 4 句；结论与华曦达对照不放表
CORE_SLIM = ["s-k-region", "s-k-cust", "s-k-ar", "s-k-debt"]
DATE_H = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")
FLOW_H = ["2024 全年", "2025 全年", "2025H1", "2025H2（计算）", "2026H1"]
# 期末余额表按日历排列；「2025H2 变化」＝2025-12-31 减 2025-06-30，只放期末差额
BAL_H = ["2024-12-31", "2025-06-30", "2025-12-31", "2025H2 变化（计算）", "2026-06-30"]
EDITABLE = {"h1", "h2", "h3", "h4", "p", "li", "td", "th", "caption", "dt", "dd", "figcaption"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
ANGLE = re.compile(r"[<>＜＞≤≥]")
GATE_WORDS = re.compile(r"硬闸|限措辞|挡|可写")
FORECAST = re.compile(r"预测|情景|2026H2|2026 ?年下半年|全年展望|核实清单")
TAG_WORDS = re.compile(r"事实|计算|推断|代理口径")
GROUP = re.compile(r"创维集团|00751")
BARE = re.compile(r"创维(?!数字|集团)")


class Node:
    __slots__ = ("tag", "attrs", "parent", "children", "text")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.text = tag, dict(attrs), parent, [], []

    def cls(self):
        return self.attrs.get("class", "").split()

    def all_text(self):
        out = list(self.text)
        for c in self.children:
            out.append(c.all_text())
        return "".join(out)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def anc(self):
        p = self.parent
        while p:
            yield p
            p = p.parent


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root
        self.texts = []  # (text, node) outside script/style

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.text.append(data)
        if self.cur.tag not in ("script", "style", "title"):
            self.texts.append((data, self.cur))


def header_text(th):
    t = th.all_text()
    return re.sub(r"\s+", " ", t).replace(" （", "（").strip()


def num(td):
    t = TAG_WORDS.sub("", td.all_text())
    t = re.sub(r"[,，\s]", "", t).replace("−", "-").replace("–", "-")
    return float(t) if re.fullmatch(r"-?\d+(\.\d+)?", t) else None


def section_of(n):
    for a in n.anc():
        if a.tag == "section" and a.attrs.get("id"):
            return a
    return None


def check(path):
    src = path.read_text(encoding="utf-8")
    tree = Tree()
    tree.feed(src)
    nodes = list(tree.root.walk())
    fails, warns, info = [], [], []

    ids = [n.attrs["id"] for n in nodes if "id" in n.attrs]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        fails.append(f"重复 id：{dup}")
    profile = next((n.attrs.get("content") for n in nodes if n.tag == "meta" and n.attrs.get("name") == "report-profile"), "")
    slim = profile in ("slim", "slim_v2")
    required, optional = (REQUIRED_SLIM, []) if slim else (REQUIRED, OPTIONAL)
    sec_ids = [n.attrs["id"] for n in nodes if n.tag == "section" and "id" in n.attrs]
    missing = [s for s in required if s not in sec_ids]
    if missing:
        fails.append(f"缺少章节 id：{missing}")
    order = [s for s in sec_ids if s in required + optional]
    expect = [s for s in required[:-1] + optional + required[-1:] if s in order]
    if order != expect:
        fails.append(f"章节顺序与骨架不符：{order}")
    pos = {s: i for i, s in enumerate(sec_ids)}
    first_cmp = next((s for s in required if s.startswith("s-cmp-")), None)
    if first_cmp in pos and any(pos.get(s, -1) > pos[first_cmp] for s in required if s.startswith("s-k-")):
        fails.append("创维数字本体章节出现在对比章节之后")
    tables = [n for n in nodes if n.tag == "table" and section_of(n)]
    if profile == "slim" and tables:
        fails.append(f"瘦身版正文不放表，实有 {len(tables)} 张：{[t.attrs.get('id', '?') for t in tables][:5]}")
    if profile == "slim_v2":
        secs = {n.attrs["id"]: n for n in nodes if n.tag == "section" and "id" in n.attrs}
        for sid in CORE_SLIM:
            sec = secs.get(sid)
            if not sec:
                continue
            ts = [t for t in tables if section_of(t) is sec]
            if len(ts) != 1:
                fails.append(f"{sid} 应恰好 1 张表（禁 0 表、最多 1 表），实有 {len(ts)} 张")
                continue
            dl = [a for a in ts[0].anc() if "duo-l" in a.cls()]
            duo = dl[0].parent if dl else None
            if not duo or "duo" not in duo.cls():
                fails.append(f"{sid} 的表不在 .duo > .duo-l 里（应左表右判）")
                continue
            kids = [c for c in duo.children if c.tag == "div"]
            if len(kids) != 2 or "duo-l" not in kids[0].cls() or "duo-r" not in kids[1].cls() \
                    or not any("judg" in c.cls() for c in kids[1].walk()):
                fails.append(f"{sid} 的 .duo 应为 .duo-l（表）在前、.duo-r（含 .judg 判断）在后")
            h2 = next((c for c in sec.children if c.tag == "h2"), None)
            if not h2 or sec.children.index(h2) > sec.children.index(duo):
                fails.append(f"{sid} 应先有判断标题（h2）再见表")
        for sid in ("s-concl", "s-cmp-os"):
            ts = [t for t in tables if secs.get(sid) is not None and section_of(t) is secs[sid]]
            if ts:
                fails.append(f"{sid} 不放表，实有 {len(ts)} 张")
        concl = secs.get("s-concl")
        if concl:
            lis = [c for c in concl.walk() if c.tag == "li"]
            if len(lis) != 4:
                fails.append(f"核心结论应恰好 4 句（主线四拍），实有 {len(lis)} 条")
        for t in tables:
            ths = [header_text(c) for c in t.walk() if c.tag == "th"]
            dates = [DATE_H.search(h).groups() for h in ths if DATE_H.search(h)]
            if dates != sorted(dates):
                fails.append(f"{t.attrs.get('id', '?')} 日期列须按日历从早到晚：{[h for h in ths if DATE_H.search(h)]}")
            if "t5" not in t.cls() and any("变化" in h for h in ths):
                fails.append(f"{t.attrs.get('id', '?')} 紧凑表不放变化列")

    eids = [n.attrs["data-eid"] for n in nodes if "data-eid" in n.attrs]
    dup = sorted({e for e in eids if eids.count(e) > 1})
    if dup:
        fails.append(f"重复 data-eid：{dup[:10]}")
    for n in nodes:
        if "data-eid" in n.attrs and any("data-eid" in a.attrs for a in n.anc()):
            fails.append(f"data-eid 嵌套：{n.attrs['data-eid']}")
    doc = next((n for n in nodes if n.attrs.get("id") == "doc"), None)
    if doc:
        loose = [n for n in doc.walk() if n.tag in EDITABLE and "data-eid" not in n.attrs
                 and not any("data-eid" in a.attrs for a in n.anc()) and n.all_text().strip()]
        if loose:
            warns.append(f"{len(loose)} 个正文元素没有 data-eid（修改后无法保存）；运行 --fix-eids 补齐")

    syncs = [n for n in nodes if n.attrs.get("id") == "btnSync"]
    sync_btns = [n for n in nodes if n.tag == "button" and n.all_text().strip() == "同步修改"]
    if len(syncs) != 1 or len(sync_btns) != 1:
        fails.append(f"「同步修改」按钮应恰好一个（id=btnSync {len(syncs)}，文字按钮 {len(sync_btns)}）")
    if not any(n.attrs.get("id") == "btnEdit" for n in nodes):
        fails.append("缺少「修改」按钮 #btnEdit")

    for n in nodes:
        if n.tag in ("script", "link", "img", "iframe") and re.match(r"(https?:)?//", n.attrs.get("src", "") or n.attrs.get("href", "")):
            fails.append(f"引用了外部资源：<{n.tag}> {n.attrs.get('src') or n.attrs.get('href')}")
        if n.tag in ("canvas", "img") and section_of(n):
            warns.append(f"{section_of(n).attrs['id']} 含 <{n.tag}>：读者要改的数字须同时写在表格里")

    for t in [n for n in nodes if n.tag == "table" and "t5" in n.cls()]:
        tid = t.attrs.get("id", "?")
        want = BAL_H if "t5b" in t.cls() else FLOW_H
        ths = [c for c in t.walk() if c.tag == "th"]
        got = [header_text(c) for c in ths[1:]]
        if got != want:
            fails.append(f"{tid} 表头应为 {' | '.join(want)}，实为 {' | '.join(got)}")
        for tr in [c for c in t.walk() if c.tag == "tr"]:
            cells = [c for c in tr.children if c.tag in ("td", "th")]
            span = sum(int(c.attrs.get("colspan", 1)) for c in cells)
            if span != 6:
                fails.append(f"{tid} 有一行不是 6 格：「{cells[0].all_text().strip()[:20] if cells else ''}」")
                continue
            bal = "t5b" in t.cls()
            if bal and tr.attrs.get("data-k") == "ratio" and num(cells[4]) is not None:
                fails.append(f"{tid}「{cells[0].all_text().strip()[:20]}」变化列放了期间数 {num(cells[4])}：只放期末差额，期间数写脚注，该格写「—」")
            if tr.attrs.get("data-k") == "amt":
                a, b, h = num(cells[2]), num(cells[3]), num(cells[4])
                if bal:
                    a, b = b, a
                if None not in (a, b, h) and abs(a - b - h) > 0.011:
                    fails.append(f"{tid}「{cells[0].all_text().strip()[:20]}」2025H2（计算）{h} 不等于 {a} 减 {b}")
                if h is not None and "计算" not in cells[4].all_text() and "计算" not in header_text(ths[4]):
                    warns.append(f"{tid} 2025H2 格缺【计算】标签")
            for c in cells[1:]:
                if c.children == [] and not c.all_text().strip():
                    fails.append(f"{tid}「{cells[0].all_text().strip()[:20]}」有空白格：请写数字、未披露或—")
                    break

    for text, n in tree.texts:
        if GATE_WORDS.search(text):
            fails.append(f"{section_of(n).attrs.get('id') if section_of(n) else '页外'} 出现内部闸语言「{GATE_WORDS.search(text).group(0)}」：老板版不得出现")
        if ANGLE.search(text):
            fails.append(f"正文含尖括号或比较符，请改写为「低于／超过」：「{text.strip()[:40]}」")
    front = [n for n in nodes if n.tag == "section" and (n.attrs.get("data-part") == "k" or n.attrs.get("id") == "s-cover")]
    for s in front:
        if "华曦达" in s.all_text():
            fails.append(f"前半 {s.attrs.get('id')} 出现「华曦达」：对比只放后半")
    for text, n in tree.texts:
        sec = section_of(n)
        sid = sec.attrs.get("id") if sec else "页外"
        if GROUP.search(text) and sid != "s-k-eq":
            fails.append(f"{sid} 出现「{GROUP.search(text).group(0)}」：创维集团只在 9 股权与资本结构 作为间接控股股东出现")
        if BARE.search(text):
            warns.append(f"{sid} 出现简称「创维」：本报统一写「创维数字」，全称创维数字股份有限公司（000810.SZ）")
    for text, n in tree.texts:
        m = FORECAST.search(text)
        if m:
            sec = section_of(n)
            warns.append(f"{sec.attrs.get('id') if sec else '页外'} 出现「{m.group(0)}」：本报不做预测、情景表和核实清单，请确认")

    body_text = "".join(t for t, _ in tree.texts)
    info.append("待填 %d · 待算 %d · 待引 %d · 未披露 %d" % tuple(body_text.count(k) for k in ("待填", "待算", "待引", "未披露")))
    filled = sum(1 for n in nodes if n.tag == "td" and "num" in n.cls() and num(n) is not None)
    info.append(f"已填数值格 {filled}")
    return fails, warns, info


def fix_eids(path):
    src = path.read_text(encoding="utf-8")
    used = {}
    for m in re.finditer(r'data-eid="([^"]+)\.(\d+)"', src):
        used[m.group(1)] = max(used.get(m.group(1), 0), int(m.group(2)))
    out, sec = [], "doc"
    pat = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>")
    stack = []
    pos, added = 0, 0
    for m in pat.finditer(src):
        out.append(src[pos:m.start()])
        closing, tag, rest = m.group(1), m.group(2).lower(), m.group(3)
        tok = m.group(0)
        if not closing:
            idm = re.search(r'\bid="([^"]+)"', rest)
            if tag == "section" and idm:
                sec = idm.group(1)
            in_unit = any(u for _, u in stack)
            is_unit = "data-eid=" in rest
            if tag in EDITABLE and not is_unit and not in_unit:
                used[sec] = used.get(sec, 0) + 1
                tok = f'<{m.group(2)} data-eid="{sec}.{used[sec]}"{rest}>'
                is_unit = True
                added += 1
            if tag not in VOID and not rest.rstrip().endswith("/"):
                stack.append((tag, is_unit))
        else:
            if tag == "section":
                sec = "doc"
            while stack:
                t, _ = stack.pop()
                if t == tag:
                    break
        out.append(tok)
        pos = m.end()
    out.append(src[pos:])
    path.write_text("".join(out), encoding="utf-8")
    print(f"已补 {added} 个 data-eid")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else HERE / "skyworth-report.html"
    if "--fix-eids" in sys.argv:
        fix_eids(path)
    fails, warns, info = check(path)
    for f in fails:
        print("FAIL", f)
    for w in warns:
        print("WARN", w)
    for i in info:
        print("INFO", i)
    print("OK" if not fails else f"{len(fails)} 项不通过")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
