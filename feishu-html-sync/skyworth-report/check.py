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
FLOW_H = ["2024 全年", "2025 全年", "2025H1", "2025H2（计算）", "2026H1"]
BAL_H = ["2024-12-31", "2025-12-31", "2025-06-30", "2025H2 变化（计算）", "2026-06-30"]
EDITABLE = {"h1", "h2", "h3", "h4", "p", "li", "td", "th", "caption", "dt", "dd", "figcaption"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
ANGLE = re.compile(r"[<>＜＞≤≥]")
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
    sec_ids = [n.attrs["id"] for n in nodes if n.tag == "section" and "id" in n.attrs]
    missing = [s for s in REQUIRED if s not in sec_ids]
    if missing:
        fails.append(f"缺少章节 id：{missing}")
    order = [s for s in sec_ids if s in REQUIRED + OPTIONAL]
    expect = [s for s in REQUIRED[:-1] + OPTIONAL + REQUIRED[-1:] if s in order]
    if order != expect:
        fails.append(f"章节顺序与骨架不符：{order}")
    pos = {s: i for i, s in enumerate(sec_ids)}
    if "s-cmp-intro" in pos and any(pos.get(s, -1) > pos["s-cmp-intro"] for s in REQUIRED if s.startswith("s-k-")):
        fails.append("创维数字本体章节出现在对比导读之后")

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
            if tr.attrs.get("data-k") == "amt":
                a, b, h = num(cells[2]), num(cells[3]), num(cells[4])
                if None not in (a, b, h) and abs(a - b - h) > 0.011:
                    fails.append(f"{tid}「{cells[0].all_text().strip()[:20]}」2025H2（计算）{h} 不等于 {a} 减 {b}")
                if h is not None and "计算" not in cells[4].all_text() and "计算" not in header_text(ths[4]):
                    warns.append(f"{tid} 2025H2 格缺【计算】标签")
            for c in cells[1:]:
                if c.children == [] and not c.all_text().strip():
                    fails.append(f"{tid}「{cells[0].all_text().strip()[:20]}」有空白格：请写数字、未披露或—")
                    break

    for text, n in tree.texts:
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
