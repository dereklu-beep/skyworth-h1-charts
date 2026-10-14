# HANDOFF → 助理（Grok Bot）

分支：`cursor/feishu-html-sync-ea83` · 目录：`feishu-html-sync/`

## 本分支已完成、可直接拷回

| 本仓库文件 | 拷到 box | 说明 |
|---|---|---|
| `feishu-html-sync/box/sync_pull.py` | `/workspace/sdmc_skyworth/sync_pull.py`（relay.py 里 `PULL` 指向的就是它） | 加固版外科回写，命令行参数向下兼容 |
| `feishu-html-sync/tests/test_sync_pull.py` + `tests/fixture_report.html` | `/workspace/sdmc_skyworth/tests/`（可选） | 离线测试，不需要 `requests` 和飞书凭据 |

拷贝前先备份：

```bash
cp /workspace/sdmc_skyworth/sync_pull.py /workspace/sdmc_skyworth/sync_pull.py.bak_$(date +%Y%m%d_%H%M%S)
cp feishu-html-sync/box/sync_pull.py /workspace/sdmc_skyworth/sync_pull.py
```

拷完按顺序跑：

```bash
cd /workspace/sdmc_skyworth
T=v71_fix/华曦达vs创维财报对比_v71_可编辑.html
# 1) 演练：读取 drops + 收件箱，只出报告不写文件
python3 sync_pull.py --target "$T" --dry
# 2) 正式应用，然后同链覆盖（file_token 永远不变）
python3 sync_pull.py --target "$T" && python3 /workspace/feishu/replace.py FXqHbFI37oGOCyxT3NkcVhjnnRg "$T"
```

`--stamp`（把 data-eid 和 sync-rev 写进主稿）**只用于新模板 `report_template` 生成的报告**，v71 不要跑（原因见下文「v71 报告审稿」）。对新模板报告跑过 stamp 并 replace 之后，已经打开的 Chrome 标签页要刷新一次。

## 与旧版的行为差异（relay / sync_watch 无需改动也能用）

- 默认同时读 `v41/sync_inbox_drops/*.txt` 和飞书收件箱。drops 是完整包，收件箱读失败只告警、不退出。加 `--no-inbox` 可以只读 drops。
- 缺 `ts` 的包按内容哈希作 key 照常处理；base64 损坏的块会跳过；单个坏 op 不会中断整包。
- eid 只当提示用：只有该元素当前内容仍等于 `old` 才写。旧版 `while True: replace_eid_inner` 的死循环和写错元素的问题都已去掉。
- 短而多义的 `old`（如「深圳创展」）先按章节标题、行首单元格、列号、相邻文字打分来定位。仍然多义就记入 `v41/sync_unresolved.json`，**不猜**。
- 文本兜底只在可编辑元素内部做，不碰 `<script>`、`#report-data` 和属性。
- `@charts` 按图表 id 合并，不再整块覆盖。
- 成功写入时会更新 `<meta name="sync-rev">`，追加一行到 `v41/sync_ledger.jsonl`，并输出 `applied ->` 一行（relay 的 `kick_apply` 靠它判断是否 replace），外加一行 `SYNC_RESULT {json}`。
- 新开关：`--status-dir DIR`（每个包写一份 `<id>.json` 结果）、`--replay v41/sync_ledger.jsonl`（作者重建 HTML 后重放 Derek 的 Chrome 修改）、`--retry-unresolved`、`--out`。
- 体积膨胀保护（超过 1.15 倍 + 5000 字节就拒写）保留。

## v71 报告审稿

见 `feishu-html-sync/REPORT_REVIEW.md`。结论是有条件放行，有 3 个阻断项：
1. 「前同事」仍挂在 `#t-eq`「杨健家族」和 `#t-cost`「深圳创展」上；
2. 国际发售其余占总股本应为 6.65%，报告 4 处写成 6.64%；
3. 顶栏仍有「恢复原始数据」等按钮。

`sync_pull.py` 已修正为能处理 v71 的 `<template id="report-tpl">` 正文。修正前，内容匹配会把整份 v71 正文漏掉；拷贝时请务必用本分支的最新版本。

注意：v71 是自带客户端（v46、`bSync`）的旧结构，**不要**对它跑 `--stamp`。stamp 的编号规则是按新模板的 `main .doc` 结构写的，v71 上会写入 0 个；即使写入，也可能和 v46 客户端运行时的编号冲突。

## 尚未在本分支实现（只有设计，见 PROBLEMS_AND_SOLUTIONS.md）

为了不和 Project「华曦达／创维并行交付」的线程撞车，我停在这里。下面几项**未写代码**，需要认领：

1. 浏览器端 `template_app.js` 的同步段：发送 `h/row/col/prev/next/tag/rev/id`，成功后显示状态条而不是复制框，用 localStorage 存草稿和待发队列，Ctrl/⌘+S 不再触发另存，开页时自动清掉多余的旧按钮。现有客户端发的旧格式包，新版 `sync_pull.py` 照样能处理（`ctx` 会被解析成行首提示）。
2. `relay.py`：`append_inbox` 要分批（每批不超过 50 个块），不能截断到 40 块。这正是收件箱里出现「缺 ts / 坏块」的根因。另外要加 `/status?id=`、`/rev`，并在调用 `sync_pull` 时传 `--status-dir`。
3. `ws_poller.py`：转发后删除 webhook.site 上已处理的请求，避免配额满。
4. Cloudflare Worker 前端（同步入口 + 托管页面 + SAVE_URL 排队），以及 `supervise.py` 保活脚本。

本分支**没有**改 `/workspace/templates/report_template` 下的任何文件。

## 测试

```bash
python3 -m unittest discover -s feishu-html-sync/tests -v   # 19 个测试，全部离线
```
