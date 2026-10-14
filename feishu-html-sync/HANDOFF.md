# HANDOFF → 助理（Grok Bot）

分支：`cursor/feishu-html-sync-ea83`（PR #1，外科回写 `sync_pull.py` 加 v71 审稿）→ 叠加 `cursor/feishu-html-sync-hardening-54a3`（PR #3：relay 路由、闸门、docx 块同步、edge、模板客户端）。目录：`feishu-html-sync/`。

## 0. 先读：真源与闸门

### 真源在 box，不在仓库

assistant 的 box 路径 **`/workspace/sdmc_skyworth` 仍然是在编草稿的唯一真源**：

| 报告 | rep | 飞书同链 | box 主稿 |
|---|---|---|---|
| 华曦达 | `huaxida-h1` | 飞书文档 file_token `FXqHbFI37oGOCyxT3NkcVhjnnRg` | `/workspace/sdmc_skyworth/v71_fix/华曦达vs创维财报对比_v71_可编辑.html` |
| 创维 | `skyworth-report` | 创维草稿 file_token `PdxFbDlbDorRAexT1hRcpHuCnBf` | `/workspace/sdmc_skyworth/skyworth/skyworth-report.html`（**请在 box 上核对实际文件名**，改 `sync_config.json`） |

Cloud agent 只能看到 GitHub 仓库和附件，看不到 box。因此：
- 需要云端审稿时，必须先把草稿从 box **导出或作为附件**交给 cloud agent；
- 仓库里的任何 HTML（`tests/fixture_report.html`、e2e 生成页等）都只是测试样本，**不是权威版本**，不要拿它们覆盖 box 草稿，也不要据此判断线上内容。

### 群组闸门：两份飞书文档都在等 Derek

创维（`PdxFb…`）和华曦达（`FXqHb…`）两份文档目前都**被闸门挡着，等 Derek 确认**。

- **同链 replace/upload 只在 Derek 确认后、且只在 box 上运行。** 在此之前不跑 `replace.py`，也不做任何飞书写入或上传（Drive 覆盖、docx 块更新、入口链接 relink、收件箱追加都算）。
- 测试一律用 mock 或 dry-run：`python3 -m unittest …`（全部是假 API）、`sync_pull.py --dry`、`docx_sync.py --dry`。
- 代码层面也上了锁，默认就是关的：
  - `config.py` 的 `feishu_live_writes: false`，每份报告 `derek_confirmed: false`；
  - `replace.py` 在发出任何网络请求、拿 token 之前就拒绝，退出码 3（`GATED …`）；
  - `docx_sync.py` 的写接口和 `relay.append_inbox` 同样拒绝；
  - relay 在闸门关闭时照常把 Chrome 修改写进 **box 主稿**并刷新本机托管页，状态记为 `gated`，页面显示「已写回主稿；飞书同一链接等 Derek 确认后由助理端更新」。
- `tests/test_gate.py` 锁定了这些默认值：谁把仓库默认改成开，测试就会失败。

**Derek 确认之后**（只在 box 上，逐份报告开）：

```bash
cd /workspace/feishu
# 1) 在 /workspace/feishu/relay/sync_config.json 里：
#    "feishu_live_writes": true，并且只给 Derek 确认过的那份报告设 "derek_confirmed": true
# 2) 先演练
python3 sync_pull.py --target "$T" --dry
# 3) 同链覆盖（file_token 不变，不会新建文件）
python3 replace.py --rep huaxida-h1 FXqHbFI37oGOCyxT3NkcVhjnnRg "$T"
```

relay 会在下一次同步时自动走 Drive 覆盖。上面第 3 步只用于手动补一次。

## 1. 报告路由：rep → 各自的飞书同链

relay 只按包里的 `rep` 分流。每个 rep 对应自己的主稿、drops 目录和飞书 token：

| rep（及别名） | Drive file_token | docx token | drops |
|---|---|---|---|
| `huaxida-h1`（华曦达 / sdmc / huaxida） | `FXqHbFI37oGOCyxT3NkcVhjnnRg` | 未登记 | `/workspace/sdmc_skyworth/v41/sync_inbox_drops/` |
| `skyworth-report`（创维 / skyworth） | `PdxFbDlbDorRAexT1hRcpHuCnBf` | 未登记 | `/workspace/sdmc_skyworth/skyworth/sync/drops/` |

规则：
- `rep` 缺失或未登记的包，放进 `/workspace/feishu/relay/held/`，**哪份主稿都不写**。唯一的例外是线上 v71 页面自带的旧客户端：它发的包只有 `ver:"v46"`、没有 `rep`，会按 `legacy_unlabelled_ver` 归到华曦达。对 v71 跑过 `fix_live_page.py` 之后，它也会带上 `rep:"huaxida-h1"`。
- `replace.py` 和 `docx_sync.py` 会再查一遍：token、HTML 里的 `report-id` / `report-name`、`--rep` 三者必须指向同一份报告，否则拒绝。创维的修改不可能落到华曦达文档上，反之亦然。
- 放行一个 held 包：`python3 relay.py release /workspace/feishu/relay/held/<文件>.txt skyworth-report`。
- 新增报告：在 `sync_config.json` 的 `reports` 下加一项。不建飞书机器人，也不建群。
- 状态查询：`curl 127.0.0.1:8787/health`，可以看到每份报告的 rev、是否已配置主稿和 token、最近一次结果，以及 held 的数量。

## 2. 拷到 box

先备份，再整目录拷贝（这些模块互相 import，必须放在同一个目录）：

```bash
ts=$(date +%Y%m%d_%H%M%S)
mkdir -p /workspace/feishu/bak_$ts && cp /workspace/feishu/*.py /workspace/feishu/bak_$ts/ 2>/dev/null
cp /workspace/sdmc_skyworth/sync_pull.py /workspace/sdmc_skyworth/sync_pull.py.bak_$ts
cp feishu-html-sync/box/*.py /workspace/feishu/
ln -sf /workspace/feishu/sync_pull.py /workspace/sdmc_skyworth/sync_pull.py   # 旧的 sync_watch 仍然能找到它
[ -f /workspace/feishu/relay/sync_config.json ] || cp feishu-html-sync/box/sync_config.example.json /workspace/feishu/relay/sync_config.json
```

| 仓库文件 | box 位置 | 作用 |
|---|---|---|
| `box/config.py` | `/workspace/feishu/` | 报告登记表、闸门、默认值；用 `relay/sync_config.json` 覆盖 |
| `box/relay.py` | 同上 | `/sync` 收包，按 rep 分流或 held，按报告串行执行 sync_pull，再 replace / docx；提供 `/status/<id>`、`/rev`、`/health`、`/r/<rep>` |
| `box/sync_pull.py` | 同上（软链到 `sdmc_skyworth`） | 外科回写（PR #1），另加 `sid` 定位、`--rep` 过滤、写入时补 eid |
| `box/replace.py` | 同上 | 同链覆盖，CLI 与旧版一致；加了跨报告校验和闸门 |
| `box/docx_sync.py` | 同上 | HTML 到飞书 docx：只更新变化的块；比较号写成「低于 / 超过」；`relink` 用于更新入口链接 |
| `box/feishu_auth.py` | 同上 | Derek 用户身份（refresh token 自动轮换） |
| `box/ws_poller.py` | 同上 | 从 webhook.site 或 edge 队列拉包；relay 收下后才删除或确认 |
| `box/fix_live_page.py` | 同上 | v71 顶栏修正（见第 4 节） |
| `template/app.js`、`template/shell.html` | `/workspace/templates/report_template/template_app.js`、`template_shell.html` | 新模板客户端（见第 5 节） |
| `edge/worker.js`、`edge/wrangler.toml` | Cloudflare（可选） | 稳定的公网入口（见第 6 节） |

启动（tmux）：`python3 /workspace/feishu/relay.py` 和 `python3 /workspace/feishu/ws_poller.py`。

## 3. 用户身份（一次性，需要 Derek 点一下）

```bash
python3 /workspace/feishu/feishu_auth.py login      # 打印授权链接，Derek 在 Chrome 打开并同意
python3 /workspace/feishu/feishu_auth.py exchange '<回跳 URL 或 code>'
python3 /workspace/feishu/feishu_auth.py status
```

用现有应用，不新建机器人。授权只是登记身份，不写文档；写入仍受第 0 节的闸门约束。

## 4. 线上 v71 页面：只留「同步修改」

```bash
python3 /workspace/feishu/fix_live_page.py "$T" --rep huaxida-h1 --dry   # 先看报告
python3 /workspace/feishu/fix_live_page.py "$T" --rep huaxida-h1         # 自动备份 .pre_fix_<时间>
```

脚本删除「恢复原始数据」(`#bReset`) 和失效的「复制修改」(`#bCopy`)，并给脚本里对这两个按钮的引用加上判空。**不能只删按钮标签**：那样 `bReset.addEventListener` 会抛错，后面的脚本整段中断，「开启编辑」和「同步修改」都会失灵（已在无头 Chrome 里复现）。脚本还会给同步包加上 `rep:"huaxida-h1"`，其余内容一字不动，重复运行也安全。

改的只是 box 上的主稿文件；上传到飞书仍要等 Derek 确认。

## 5. 新模板客户端（`template/`）

- 顶栏只有「修改」「同步修改」「打印」。「同步修改」在有改动时才出现。
- 每个包都带 `rep`（`<meta name="report-id">`）、`id`、`ts`、`rev`，以及上下文 `sid/h/row/col/prev/next/tag`。
- 发送用 `text/plain`，属于不触发预检的 CORS 简单请求。页面如果由 relay 或 edge 托管，就同源发送，完全不涉及 CORS；否则依次尝试 edge 和 webhook。
- 发出后通过 JSON 或 JSONP 轮询 `/status/<id>`，结果显示在面板里（已写回 / gated / held / 未定位）。面板里可以「下载改过的页面」；Ctrl/⌘+S 同步，Ctrl/⌘+Shift+S 下载。
- 未同步的修改保存在本机 localStorage，重新打开后，原文没变的部分会自动恢复。主稿 rev 变了就提示刷新；页面上没有未同步修改时直接自动刷新。
- 筛选、排序不受修改模式影响（e2e 已验证）。
- `build_report.py` 需要填 `{{REPORT_ID}}`（如 `skyworth-report`）和 `{{SYNC_EDGE}}`（没有就留空）。原有那一行 `const SYNC_VER=…` 保持不变。

## 6. 稳定的「用 Chrome 打开」链接与长期 CORS（可选，需要 Derek 决定）

`edge/worker.js` 是一个 Cloudflare Worker：`/r/<rep>` 以普通网页的形式托管报告（没有 Pinggy 提示页，也不会被当成附件下载）；`/sync` 把包排进队列；box 只发出站请求，拉取 `/api/queue` 并发布 `/api/report/<rep>`。部署需要一个免费的 Cloudflare 账号，最好绑自有域名（`*.workers.dev` 在大陆可能不稳）。部署前，box 和现有的 Pinggy 加 webhook.site 照常工作。

## 7. 与旧版的行为差异（PR #1，仍然有效）

- 同时读 drops 和飞书收件箱；收件箱读失败只告警，不退出。`--no-inbox` 只读 drops（relay 用的就是这个）。
- 缺 `ts` 时用转发时间（`recv_ts`）补上；base64 损坏的块跳过；单个坏 op 不会中断整个包。
- eid 只当提示：只有元素当前内容仍等于 `old` 时才写。短而多义的 `old` 按 `sid`、章节标题、行首、列号、相邻文字打分定位，分数不唯一就记入 `sync_unresolved.json`，**不猜**。
- `@charts` 按图表 id 合并；成功写入后更新 `sync-rev` 和 `sync_ledger.jsonl`；保留体积膨胀保护。
- `--stamp` 只用于新模板生成的报告，**v71 不要跑**。

## 8. v71 报告审稿

见 `feishu-html-sync/REPORT_REVIEW.md`（PR #1）。3 个阻断项里的第 3 项（顶栏按钮）由第 4 节的脚本解决；另外两项（「前同事」、6.65%）是内容问题，由作者在 box 主稿上改。

## 9. 还没做

- `supervise.py` 保活脚本，以及 Pinggy URL 变化时自动 `docx_sync.py relink` 入口链接（relink 也受闸门约束）。
- `check_template.py`：build 或 replace 前检查顶栏按钮。
- 两份报告的 docx token 还没登记（`report_docx_token` 为空，所以 docx 块同步不会运行）。
- 创维主稿在 box 上的实际文件名，需要在 `sync_config.json` 里核对。

## 10. 测试（全部离线，不连飞书）

```bash
python3 -m unittest discover -s feishu-html-sync/tests      # 60 个：sync_pull、路由、闸门、docx 块同步、poller
node --test feishu-html-sync/tests/test_worker.mjs          # 4 个：edge worker
python3 feishu-html-sync/tests/e2e/template_e2e.py          # 无头 Chrome + 真 relay（闸门关闭），端到端
node feishu-html-sync/tests/e2e/live_page_check.mjs <跑过 fix_live_page 的 v71.html>
```
