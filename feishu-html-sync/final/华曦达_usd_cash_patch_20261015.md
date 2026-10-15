---
cursor:
  subagentId: "bc-2230d4ad-8468-5a42-a726-e23ae384b7b4"
---

# 华曦达 美元现金补丁 · 2026-10-15

只补一处：在「财务费用」说明（`#m-s-fin`，汇兑亏损 0.24 亿那张卡）后面加一张说明卡，写招股书附注 21 的美元现金 2.41／3.53／1.69 亿元人民币，并写明 2026H1 美元现金和应收币种拆分未见原文。不加表；不碰智慧媒体段；不并创维表；不写敏感度净敞口。没写飞书，没跑 replace.py，没发妙搭；FXqHb、PdxFb 未动。

## 1 底稿与产出

目录：`/cursor/stores/bc-53a8ae46-622d-513a-8df0-fb556621041b/artifacts/box_masters_20261015_usd_patch/`

| 文件 | md5 | 字节 |
|---|---|---|
| 底稿 `华曦达对比_排版优化_dash_feishu.html`（未改） | `a0dadde4d255da0f3027dbeed6bed4a4` | 616,299 |
| 底稿 `华曦达对比_排版优化_report_feishu.html`（未改） | `32b99070e24d547548785448800826ac` | 593,634 |
| 新 `华曦达对比_排版优化_dash_feishu_usd20261015.html` | `a7b9ead96e8f4d5ceb8ce4723c9c610e` | 617,129 |
| 新 `华曦达对比_排版优化_report_feishu_usd20261015.html` | `f7e7a4b4d47b8b5b9b0d64f7ff00fdfe` | 594,464 |

新文件另存，没覆盖底稿；落 box 时改回原文件名即可。也可以不用新文件，直接按第 3 节在 box 文件上做两次替换。

## 2 出处

- 事实包 `internal/inputs/usd_assets_20261015/huaxida_usd_assets_cust_product_dig_20261015_6293.md`（md5 `a2f74b59eba87978a6882706d2fef2ad`）A1：`prosp_ns.txt` 附注 21「以下列货币计值」集团现金及现金等价物美元行 240,626／353,062／168,998 千元人民币（L15295；`prosp.txt` L19150 一致）。÷100,000 后四舍五入为 2.41／3.53／1.69 亿元人民币。
- 同包 A3、A6、BLK-1、BLK-2：2026-06-30 中报无按币种拆现金；贸易应收无美元行 → 未见原文。
- 分析师数字闸 `analyst_huaxida_usd_assets_dig_20261015_6b76.md`（md5 `5a3e11950949d6af8ed22d7d8e2f49b5`）：A 节上述各项「过」，阻断 0。
- 只用了 A1、A3、A6；B 节客户／产品内容没并入。

## 3 替换片段

每个文件里同一段内容有两份：静态正文 `#sheet`（不开 JS 时显示，带 `data-eid`）和 `<template id="report-tpl">`（脚本用它重绘页面）。两份各替换一次；页面上看到的只有一处。dash 和 report 两个文件的锚点、插入内容完全相同。

**锚点 T（模板里，原样字符串，每个文件恰好 1 处）**

```html
利息支出增加主要因借款和票据贴现增加<b class="t f it">事实</b>。</p></div>
```

**锚点 S（静态正文里，每个文件恰好 1 处；两个底稿里 `data-eid` 都是 1497）**

```html
利息支出增加主要因借款和票据贴现增加<b class="t f it" data-eid="1497">事实</b>。</p></div>
```

如果 box 文件的 eid 已变，用正则：`利息支出增加主要因借款和票据贴现增加<b class="t f it" data-eid="\d+">事实</b>。</p></div>`

两处锚点都在智慧媒体表 `#t-s-rp` 之前（`#m-s-fin` 内），不在智慧媒体段里。

**插入内容（紧接在锚点后面，两处相同）**

```html
<div class="judg"><p>招股书附注 21 的现金及现金等价物中，以美元计值的部分 2023、2024、2025 年末约为 2.41、3.53、1.69 亿元人民币<span class="cal">币种口径</span><b class="t f it">事实</b>；这是按计值币种的划分，不等于境外资产。2026 年 6 月末的美元现金，以及应收账款按币种的拆分，均<span class="nd">未见原文</span>。</p></div>
```

即：`锚点` → `锚点 + 插入内容`。显示效果：

> 招股书附注 21 的现金及现金等价物中，以美元计值的部分 2023、2024、2025 年末约为 2.41、3.53、1.69 亿元人民币〔币种口径〕〔事实〕；这是按计值币种的划分，不等于境外资产。2026 年 6 月末的美元现金，以及应收账款按币种的拆分，均〔未见原文〕。

`cal` 是页面已有的口径徽章样式（同「全公司合并」）；没用 `cal os`（海外口径），避免读成境外。`nd` 是已有的灰色「未披露」徽章样式，这里文字为「未见原文」。

## 4 检查

在 box 文件上替换后跑（`F` 换成 dash 或 report 文件）：

```bash
P='以美元计值的部分 2023、2024、2025 年末约为 2.41、3.53、1.69 亿元人民币'
grep -o "$P" "$F" | wc -l                                              # 应为 2（静态 1 + 模板 1；页面显示 1 处）
grep -oF '利息支出增加主要因借款和票据贴现增加<b class="t f it">事实</b>。</p></div><div class="judg"><p>招股书附注 21' "$F" | wc -l   # 应为 1
grep -oE '利息支出增加主要因借款和票据贴现增加<b class="t f it" data-eid="[0-9]+">事实</b>。</p></div><div class="judg"><p>招股书附注 21' "$F" | wc -l   # 应为 1
grep -o '深圳证监局于 2023-06-09 出具〔2023〕86 号警示函' "$F" | wc -l     # 应为 2，与底稿相同（智慧媒体表下第 4 句）
```

字节级检查（证明除插入内容外一字未改）由第 7 节脚本里的断言完成：`out.replace(NOTE, '', 2) == 底稿` 必须成立；两份智慧媒体块（从 `#t-s-rp` 所在 `.duo` 起到「深圳证监局…警示函」那句所在 `</div>`）替换前后 md5 必须相同。脚本改 `D` 和 `MASTERS` 即可用在 box 文件上；底稿 md5 不符时会直接报错停下。

本次在两个底稿上的实测结果：

| 检查 | dash | report |
|---|---|---|
| 底稿 md5 | a0dadde4… ✓ | 32b99070… ✓ |
| 锚点 T／S 各匹配 | 1／1 | 1／1 |
| 插入后新句计数（静态＋模板） | 2 | 2 |
| 去掉插入内容后与底稿逐字节相同 | 是 | 是 |
| 智慧媒体块 md5（静态／模板），替换前后相同 | `d4032c88…`／`dadb05c5…` | `d4032c88…`／`dadb05c5…` |
| 「深圳证监局…警示函」计数 | 2 → 2 | 2 → 2 |
| 无头 Chrome 1440px：页面显示次数／位置 | 1，`#m-s-fin` 右栏 | 1，`#m-s-fin` 右栏 |
| 无头 Chrome 390px：页面显示次数／位置 | 1，`#m-s-fin` 数据下方 | 1，`#m-s-fin` 数据下方 |
| 徽章 | 币种口径、事实、未见原文 | 同左 |
| 控制台错误（底稿和新文件，1440／390） | 0 | 0 |
| 页面横向溢出 | 无 | 无 |

## 5 禁项自检

| 禁项 | 结果 |
|---|---|
| 并入任何创维表 | 否。插入内容在华曦达 `#m-s-fin` 说明栏，不是表；不含「创维」；数字只来自华曦达招股书附注 21；没引用 `hist/s25`／`s24` |
| 把敏感度净敞口写成应收或美元资产合计 | 否。插入内容不含「敞口」「敏感」、8.60／8.67／8.74、「美元资产合计」「美元应收账款余额」；只写现金及现金等价物的美元行 |
| 暗示外币＝境外 | 否。明写「按计值币种的划分，不等于境外资产」；徽章用「币种口径」，没用「海外口径」 |
| 写出 2026H1 美元数或应收币种拆分 | 否。两项都标「未见原文」 |
| 并入 B 节客户／产品内容 | 否 |
| 新增表格 | 否，一张说明卡、两句话 |
| 回滚智慧媒体段 | 否。智慧媒体块逐字节未动，表下 4 句仍在 |
| 写飞书／replace.py／妙搭发布／动 FXqHb、PdxFb | 否 |

## 6 改动清单（DELTA）

| 位置 | 改前 | 改后 | 原因 |
|---|---|---|---|
| `#m-s-fin` 右栏（汇兑亏损说明卡后），静态正文和模板各一处；dash、report 两个文件相同 | 只有汇兑亏损 0.24 亿那张说明卡 | 新增一张说明卡：美元现金 2.41／3.53／1.69 亿元人民币〔币种口径〕〔事实〕，不等于境外资产；2026H1 美元现金与应收币种拆分〔未见原文〕 | 补招股书附注 21 的美元现金；明示披露缺口 |

其他均未改：数字、表格、标签、智慧媒体段、脚本、样式、本机保存键都一样。

附带影响：模板变了，页面里的 `BASE` 校验值会变，所以有人在旧底稿上存在本机浏览器里、还没同步的修改，打开新文件时不会自动载入（任何改模板的补丁都一样）。静态正文里新加的两个元素没有 `data-eid`；页面开 JS 重绘时会自动编号。

## 7 应用脚本（本次实际运行的版本）

```python
#!/usr/bin/env python3
"""Insert the 招股书附注21 USD-cash note into the 华曦达 box masters (dash + report)."""
import hashlib, re, sys

D = '/cursor/stores/bc-53a8ae46-622d-513a-8df0-fb556621041b/artifacts/box_masters_20261015_usd_patch/'
MASTERS = {
    '华曦达对比_排版优化_dash_feishu.html': 'a0dadde4d255da0f3027dbeed6bed4a4',
    '华曦达对比_排版优化_report_feishu.html': '32b99070e24d547548785448800826ac',
}
SUFFIX = '_usd20261015'

NOTE = ('<div class="judg"><p>招股书附注 21 的现金及现金等价物中，以美元计值的部分 2023、2024、2025 年末约为 2.41、3.53、1.69 亿元人民币'
        '<span class="cal">币种口径</span><b class="t f it">事实</b>；这是按计值币种的划分，不等于境外资产。'
        '2026 年 6 月末的美元现金，以及应收账款按币种的拆分，均<span class="nd">未见原文</span>。</p></div>')

ANCHOR_TPL = '利息支出增加主要因借款和票据贴现增加<b class="t f it">事实</b>。</p></div>'
ANCHOR_STATIC = re.compile(r'利息支出增加主要因借款和票据贴现增加<b class="t f it" data-eid="\d+">事实</b>。</p></div>')
PROBE = '以美元计值的部分 2023、2024、2025 年末约为 2.41、3.53、1.69 亿元人民币'
ZHMT_TAIL = '深圳证监局于 2023-06-09 出具〔2023〕86 号警示函'
FORBID = ['创维', '敞口', '敏感', '8.60', '8.67', '8.74', '美元资产合计', '美元应收账款余额', '境外资产合计', '海外口径', 'cal os']


def md5(b):
    return hashlib.md5(b).hexdigest()


def zhmt_block(region):
    i = region.index('id="t-s-rp"')
    st = region.rfind('<div class="duo', 0, i)
    en = region.index(ZHMT_TAIL, i)
    en = region.index('</div>', en)
    return region[st:en]


for name, want in MASTERS.items():
    raw = open(D + name, 'rb').read()
    assert md5(raw) == want, (name, md5(raw))
    s = raw.decode('utf-8')
    assert PROBE not in s
    tp = s.index('<template id="report-tpl">'); te = s.index('</template>', tp)
    static, tpl = s[:tp], s[tp:te]

    assert tpl.count(ANCHOR_TPL) == 1, (name, 'tpl anchor', tpl.count(ANCHOR_TPL))
    ms = ANCHOR_STATIC.findall(static)
    assert len(ms) == 1, (name, 'static anchor', len(ms))
    assert s.count(ANCHOR_TPL) == 1 and len(ANCHOR_STATIC.findall(s)) == 1

    z_before = [md5(zhmt_block(static).encode()), md5(zhmt_block(tpl).encode())]
    assert s.index(ms[0]) < s.index('id="t-s-rp"') and tpl.index(ANCHOR_TPL) < tpl.index('id="t-s-rp"')

    new_static = static.replace(ms[0], ms[0] + NOTE, 1)
    new_tpl = tpl.replace(ANCHOR_TPL, ANCHOR_TPL + NOTE, 1)
    out = new_static + new_tpl + s[te:]

    assert out.count(PROBE) == 2 and new_static.count(PROBE) == 1 and new_tpl.count(PROBE) == 1
    assert out.replace(NOTE, '', 2) == s, 'something other than the note changed'
    tp2 = out.index('<template id="report-tpl">')
    z_after = [md5(zhmt_block(out[:tp2]).encode()), md5(zhmt_block(out[tp2:out.index('</template>', tp2)]).encode())]
    assert z_before == z_after, (name, z_before, z_after)
    for w in FORBID:
        assert w not in NOTE, w

    on = name.replace('.html', SUFFIX + '.html')
    open(D + on, 'w', encoding='utf-8').write(out)
    print(name, '->', on, md5(out.encode()), len(out.encode()), 'zhmt', z_before)
```
