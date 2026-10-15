# 瘦身 v2 · USD 资产 11.85 一句补丁（2026-10-15）

**范围**：只在「4 钱卡在备料与美元净负债」块（`s-k-debt`）表下插 1 句；同块表下注去掉同一组分项（避免一页出现两次）。不改表、不改右栏两段（必改4 两段制不变）、不动看板卡片（`s-dash`）。缺口包 B 节客户／产品内容未并入。

**取数**：`internal/inputs/usd_assets_20261015/skyworth_usd_assets_11p85_cust_product_dig_20261015_7595.md`（md5 `efca2965…`）A.1／A.3：2026H1「外汇风险敞口」美元金融资产小计 1,184,657,361.37 元＝货币资金 158,087,790.74＋应收账款 1,022,472,616.19＋其他应收款 4,096,954.44（`h1` L9975–9981；外币货币性项目附注 L8986／L8994／L9004）；÷1e8＝11.85／1.58／10.22／0.04，分项相加 11.84，差 0.01。数字闸 `analyst_skyworth_usd_assets_11p85_dig_20261015_c663.md`：过，阻断 0。

---

## 适用底稿（已实测）

| 底稿 | 底稿 md5 | 补后文件（同目录，新文件名；底稿未覆盖） | 补后 md5 |
|---|---|---|---|
| `artifacts/box_masters_20261015_usd_patch/创维数字专报_入稿终稿_瘦身_v2_dash_feishu.html` | `ac35e2c57d2bc14c3c82dac7d4303279` | `…_瘦身_v2_dash_feishu_usd11p85.html` | `68a91287a7fe1479bcc54f654417351a` |
| `artifacts/box_masters_20261015_usd_patch/创维数字专报_入稿终稿_瘦身_v2_report_feishu.html` | `4a456c887abb8f2a4f156221a46d4b1b` | `…_瘦身_v2_report_feishu_usd11p85.html` | `1f0f3fd0c33ac9f2d79be727bc36ed8c` |
| `artifacts/创维数字专报_入稿终稿_瘦身_v2.html`（云端干净版） | `d7bb44d15310f238d98b5fb8fdd92db8` | 原地更新 | `ea91e66d2a5c8c33c540fa8cd3aad4bd` |
| `artifacts/创维数字专报_入稿终稿_瘦身_v2_feishu.html`（云端 token 版） | `ef07c11fc944dd126efed91a5182165a` | 原地更新 | `dbded478854bb70e78001234885f8ef6` |

每个底稿只改 1 行（`s-k-debt` 整节在同一行）。

---

## 片段 1（必改）：表下插一句

**找（逐字，全文须恰好 1 处）**：

```
−4.08</td></tr></tbody></table></div>
```

（`−` 为 U+2212；这串的 `</div>` 是 `.tscroll` 的闭合，插入点仍在 `.duo-l` 里、紧挨美元净负债行。）

**替换为（找串原样＋紧接插入）**：

```html
−4.08</td></tr></tbody></table></div><p data-eid="sl-s-k-debt.30"><span class="cal px">币种口径</span>美元资产 11.85 亿元人民币＝货币资金约 1.58＋应收约 10.22＋其他应收约 0.04（2026H1 外币货币性项目附注，按币种统计，不等于境外资产；分项四舍五入后相加差 0.01） <b class="t f">事实</b>／<b class="t c">计算</b>。</p>
```

## 片段 2（有则改）：表下注去重

**找（逐字）**：

```
美元资产含货币资金约 1.58、应收约 10.22、其他应收约 0.04，美元负债含应付约 15.69、其他应付约 0.24，分项四舍五入后相加差 0.01
```

**替换为**：

```
美元负债含应付约 15.69、其他应付约 0.24
```

（「分项四舍五入后相加差 0.01」属于资产分项，已随片段 1 写入新句。若底稿无此串则跳过；上表四个底稿均有且仅 1 处。）

---

## 一键套用（Python，两段都做断言）

```python
import sys
A1 = '−4.08</td></tr></tbody></table></div>'
I1 = ('<p data-eid="sl-s-k-debt.30"><span class="cal px">币种口径</span>美元资产 11.85 亿元人民币＝货币资金约 1.58＋应收约 10.22＋其他应收约 0.04'
      '（2026H1 外币货币性项目附注，按币种统计，不等于境外资产；分项四舍五入后相加差 0.01） <b class="t f">事实</b>／<b class="t c">计算</b>。</p>')
O2 = '美元资产含货币资金约 1.58、应收约 10.22、其他应收约 0.04，美元负债含应付约 15.69、其他应付约 0.24，分项四舍五入后相加差 0.01'
N2 = '美元负债含应付约 15.69、其他应付约 0.24'
for p in sys.argv[1:]:
    s = open(p, encoding='utf-8').read()
    assert 'data-eid="sl-s-k-debt.30"' not in s, 'already patched'
    assert s.count(A1) == 1, s.count(A1)
    assert s.count(O2) <= 1
    s = s.replace(A1, A1 + I1, 1).replace(O2, N2, 1)
    open(p, 'w', encoding='utf-8').write(s)
```

## grep 验证（每个文件期望值）

```bash
f=创维数字专报_入稿终稿_瘦身_v2_report_feishu.html   # 或 …_dash_feishu.html
grep -c 'data-eid="sl-s-k-debt.30"' "$f"                                  # 1
grep -o '美元资产 11.85 亿元人民币＝货币资金约 1.58' "$f" | wc -l            # 1
grep -o '1\.58' "$f" | wc -l                                              # 1（全页只剩新句一处）
grep -o '美元资产含货币资金约 1.58' "$f" | wc -l                            # 0
grep -o 'sl-s-k-debt.30' "$f" | wc -l                                     # 1（编号未与底稿其他单元冲突）
python3 check.py "$f"                                                      # OK（slim_v2 档）
```

---

## 禁项自查

| 禁项 | 结果 |
|---|---|
| 客户名套美元资产 | PASS：`s-k-debt` 块内 True／Nex／Vionn／STRONG／Target／Walmart／单位一～五／前五／Viettel／onn./Google 均 0 |
| 暗示外币＝境外 | PASS：新句带 `cal px` 币种口径徽章并写明「按币种统计，不等于境外资产」；无「海外资产」「外币＝境外」字样 |
| 缺口包 B 节整包并入 | PASS：B1–B8 一条未写 |
| 半口径 4.08／15.69−10.22／5.47 | PASS：均 0 |
| 一块一表／左表右判 | PASS：`s-k-debt` 仍 1 张表；新句在 `.duo-l` 表下；右栏仍 2 段 |
| 零新数 | PASS：11.85／1.58／10.22／0.04／0.01 均出自事实包 A.3，且原已在完整版／v2 表下注 |
| `check.py`（slim_v2） | dash、report、云端干净版、云端 token 版 均 OK；底稿补前亦 OK |
| 浏览器 | dash、report 补后：控制台 0 错、1440／390 无溢出、四块左表右判 |
