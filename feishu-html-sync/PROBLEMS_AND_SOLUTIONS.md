# 华曦达报告同步：顽固问题与解法

状态标记：**已实现** = 本分支已有代码和测试；**设计** = 只有方案，还没写代码（见 HANDOFF.md）。

总原则：每份报告不新建飞书机器人或群；box 只做出站请求（拉取），不依赖入站隧道；飞书 file_token 永远不变。

---

## 1. 飞书云盘里的 HTML 不能原地编辑

**根因**：云盘预览在沙箱里运行，不能写回；`/download` 带 `Content-Disposition: attachment`，Chrome 只会下载；`anyone_editable` 也不改变这一点。飞书没有「当作网页打开」的接口。

**方案（按推荐排序）**
1. **云盘文件只做存档、同链不变；编辑入口是一个稳定的 HTTPS 页面，从飞书入口文档链过去。** 不用下载，飞书侧只需一个永久链接（入口 docx）。
2. 飞书文档（docx 块）作为文字编辑面，HTML 只负责图表；再做 docx 块到 HTML 的回写。改动大，图表编辑会丢。
3. 在**现有**飞书应用上开启「网页应用」能力，得到稳定的 applink。每次改主页都要发版和管理员审批，而且仍然需要一个公网主机。

**推荐**：方案 1。主机的选择见第 2 条。
**风险**：入口 docx 里的链接必须能自动更新（见第 8 条）。

## 2. 「用 Chrome 打开」依赖免费 Pinggy（方案 1 **已实现**代码：`edge/worker.js`，待部署）

**根因**：免费隧道每次重启 URL 都会变，而且对浏览器显示「Enter site」提示页；box 上 cloudflared（7844 端口）、bore、ssh、loca.lt 都不通。box 能做的只有出站 443。

**方案**
1. **边缘前端加 box 拉取**：一个 Cloudflare Worker（免费），提供 `GET /r/<slug>` 托管最新 HTML（box 在 replace 之后 `PUT /publish` 推上去）、`POST /sync`、`POST /save`、`GET /rev`、`GET /status`。box 只发出站 443 请求。需要一个免费的 Cloudflare 账号（不是飞书机器人）。**风险**：`*.workers.dev` 在中国大陆常被干扰，最好绑一个自有域名；没有域名的话，先让 Derek 打开 `/health` 实测。
2. **付费 Pinggy Pro / ngrok 固定域名**（约 3 美元/月）：去掉提示页，URL 固定，现有 relay 代码零改动，第 3、4 条也一并解决。这是明天就能用的最快路径。
3. **继续用免费 Pinggy，但让它自愈**：保活脚本检测到新 URL 后，自动更新 `chrome_public_url.txt`，并用现有应用凭据修改入口 docx 的链接块。提示页仍然存在。

**推荐**：今天先做方案 3 止血；Derek 能接受小额付费就上方案 2；长期用方案 1 并绑自有域名。

**已做**：Worker 提供 `/r/<rep>`、`/sync`、`/status/<id>`、`/rev/<rep>`、`/oauth/callback`；admin 接口有 `/api/queue`、`/api/ack`、`/api/report/<rep>`、`/api/status/<id>`。box 上 `replace.py` 发布、`ws_poller.py` 拉取、relay 回推状态都已接好，`tests/test_worker.mjs` 覆盖。还差 Cloudflare 账号和域名。

## 3. SAVE_URL 整页覆盖一直是空的（**已决定：不做整页保存**）

**根因**：整页保存需要浏览器能访问到 box 的 relay `/save`，而 box 没有稳定、无提示页、带 CORS 的入站通道。

**方案**
1. **同源直存**：页面若是从 relay 的 `/chrome` 打开的，`fetch('./save')` 是同源请求，不需要 CORS。客户端先探测 `./health`，响应里 `service == 'sdmc-relay'` 就启用。现在就能用，但未验证 Pinggy 提示页是否会拦同源 POST（会拦就自动降级到 webhook）。
2. **Worker 排队**：`POST /save` 写入 KV，box 拉取后转给 relay `/save`（relay 仍用 `keys.json` 校验编辑密钥），再走同链 upload。不需要入站隧道。
3. 付费固定隧道直连 relay。

**结论**：新客户端和 relay 都删除了整页保存（relay 对 `/save` 返回 404）。只保留外科式 SDMCSYNC1 一条路径：页面由 relay 或 edge 托管时同源发送（方案 1 的思路），否则排进 edge 队列（方案 2）。这样就不会出现两条路径互相覆盖。

## 4. Cursor webhook 不能当浏览器的 SYNC_WEBHOOK（**已实现**）

**根因**：`api2.cursor.sh` 只对 `cursor.sh` 来源返回 ACAO，而且要求 Bearer 认证；在静态 HTML 里放密钥本身也不安全。

**方案**
1. **自有 CORS 前端（第 2 条方案 1 的 Worker）**：`/sync` 只做存储，`ACAO: *`，限制体积，不需要任何密钥。
2. **继续用 webhook.site，但要加固**：poller 处理完就删除对应请求（防止配额满）；客户端配置主、备两个端点依次尝试；发送失败的包放进 localStorage 待发队列，下次打开时重发。
3. Cursor webhook 只给服务端或自动化用，保持现状。

**推荐**：方案 2 立即做，方案 1 上线后作为主端点，webhook.site 降为备用。

**已做**：客户端用 `text/plain` 发送，属于不触发预检的简单请求，任何端点都能收到；读不到回执时退回 `no-cors`，靠包 `id` 去重。relay 按 origin 白名单回显 ACAO，状态接口支持 JSONP。poller 在 relay 收下之后才删除 webhook.site 上的请求或确认 edge 队列；发送失败的修改留在本机草稿里。

## 5. replace 之后，旧标签页的 eid 对不上（**已实现**）

**根因**（已在代码中确认）：
- 客户端 `ensureEids()` 在运行时按页面顺序编号，主稿里**没有**持久化的 `data-eid`。主稿每增删一个元素，后面的编号就整体平移。
- 旧版 `sync_pull` 的 eid 分支是 `while True: replace_eid_inner(...)`。只要 eid 存在，这个循环就永远不结束；eid 对不上时又会写错元素。实际上它几乎从不生效，所有修改都靠精确字符串匹配，而浏览器序列化出来的 `old` 经常和源文件对不上，于是 apply 返回 False。

**已做**：
- `--stamp` 把 `data-eid` 和 `<meta name="sync-rev">` 一次性写进主稿，eid 从此不漂移。
- eid 只在元素内容仍等于 `old` 时才采信，否则走内容匹配，旧标签页不会再写错位置。
- 包里带的 `rev` 和主稿不一致时，结果里标记 `stale_tab`。
- 每个包输出一份状态 JSON（`--status-dir`）。

**已做（客户端 `template/app.js`）**：页面带上 `rev`；打开时、切回标签时、每 2 分钟查一次 `/rev`。没有未保存修改就自动刷新；有修改就先同步（按内容匹配，不受影响），再提示刷新。同步成功后轮询 `/status?id=`，显示「已写入 3/3」或「1 处需助理确认」，不再出现「看起来同步了其实没写入」。另外，sync_pull 写入时会给新元素补上 `data-eid`，下一次打开页面时编号是稳定的。

## 6. 短字符串 old→new 多义（**已实现**）

**根因**：旧版对出现次数不超过 3 且长度至少 12 的字符串做 `html.replace` 全局替换，会同时改多处，甚至改到 `<script>` 里的图表 JSON。纯文本兜底也是全文搜索。没有任何上下文可以用来区分候选。

**已做**（`box/sync_pull.py`）：按顺序依次尝试：
1. 经过校验的 eid；
2. 规范化后的整段内容或纯文本相等，只匹配最内层的可编辑元素；
3. 变化片段加两侧锚点（12、6、3、1 字逐级缩小），只在元素文本里找，不进标签属性；
4. 有多个候选时按章节标题、行首单元格、列号、相邻文字打分，最高分必须唯一而且至少 3 分；
5. 仍然多义就记入 `sync_unresolved.json`，不猜。

另外：已经写入过的修改识别为 `already`，重复执行不会改两次；`new` 会先清理（去掉 `contenteditable` 和 `<script>`）；缺 `ts` 或 base64 损坏都不会崩溃。19 个离线测试覆盖了这些情况，「深圳创展」三处同名单元格的用例也在其中。

**风险**：旧客户端的包只带 `ctx="doc / 行首"`，同一行出现两次的短文本仍会被判为多义，这是故意的。新客户端会额外发送 `h/row/col/prev/next`。

## 7. 顶栏按钮混乱（**已实现**）

**根因**：模板和线上报告是两份副本，作者手工拷贝时把旧按钮带了回来；另外 Ctrl/⌘+S 在非编辑状态下仍会触发 `saveAs`。

**方案**
1. **运行时自愈**：`boot()` 时删掉 `.tools` 里的 `#btnSave/#btnSaveAs/#btnCopy/[data-legacy-save]`；缺 `#btnSync` 就补上。Ctrl/⌘+S 一律走同步。
2. **lint 拦截**：`check_template.py` 在 build 和 replace 之前检查：保存类按钮恰好只有一个 `#btnSync`；那一行原子的 `const SYNC_VER=…` 存在而且没有夹裸 `//`。不通过就拒绝上传。
3. 下载备份只放在同步结果面板或失败面板里，作为链接，不再占顶栏位置。这样仍满足「能下载改过的页面」的要求。

**推荐**：1 加 2 都做。

**已做**：新模板只有「修改」「同步修改」「打印」，`boot()` 会删除遗留的 `#bReset/#bCopy/#btnSaveAs/#btnSaveFeishu`；Ctrl/⌘+S 一律同步。线上 v71 用 `box/fix_live_page.py`：删掉「恢复原始数据」和「复制修改」，并给脚本引用加判空（只删标签会让脚本抛错，连「同步修改」都失灵，已在无头 Chrome 复现），同时给同步包加上 `rep`。lint（方案 2）还没做。

## 8. 运维：单一 token、保活、少打扰 Derek

**方案**
- **token 登记表**（**已实现**，放在 `config.py` 的 `reports` 中，用 `sync_config.json` 覆盖，见第 10 条）：原设计是 `reports.json`（`{file_token: {target, slug, title}}`）：relay、`sync_pull`、replace 都从这里读取，包里的 `file_token` 用来路由到对应报告。新报告只需加一行，不建机器人、不建群。replace 的包装脚本拒绝没有 file_token 的上传（不允许 upload-new）。
- **`supervise.py`**：一个进程负责拉起 relay、poller、pinggy，每 30 秒检查一次 `/health`，失败就重启。隧道 URL 一变，就自动更新 `chrome_public_url.txt` 和入口 docx。写心跳文件。用 `@reboot` 或 tmux 启动。
- relay 收到包后直接调用 `sync_pull --no-inbox --status-dir` 再 replace（带文件锁，可以和 sync_watch 共存，已处理日志保证不会重复写入）。
- 只有出现 `unresolved` 时才通知 Derek，并附上候选位置。

（`supervise.py` 仍是设计；relay 直接调用 sync_pull、串行执行、写状态这几项已实现。）

## 9. 内容流水线：Derek 的修改要在作者合稿后保留（**已实现**基础能力）

**根因**：作者从 Markdown 重新生成 HTML，会覆盖掉 Derek 在 Chrome 里做的修改。

**已做**：每条成功写入的 op 都追加到 `v41/sync_ledger.jsonl`。作者重建之后运行 `sync_pull.py --target 新稿 --replay v41/sync_ledger.jsonl`，重放靠内容匹配，不依赖 eid。重放不上的修改就是冲突，列出来交给作者处理。

**流程约定**：正文只写华曦达；创维和海外对比另出报告，各自有自己的 file_token。作者改稿前先重放 ledger，或者把 ledger 里的修改回写进 Markdown 源稿。

## 10. 多份报告共用一条同步通道（**已实现**）

**根因**：创维页面发的包带 `rep:"skyworth-report"`，但旧 relay 只认共享标记 `SDMCSYNC1`，所有包都进华曦达的 drops。创维的修改可能被写进华曦达文档。

**已做**：
- relay 按 `rep`（键名或别名）路由到各自的 drops、主稿和 token；`rep` 缺失或未登记的包进 `held/`，由人工 `relay.py release` 放行。唯一例外是 v46 旧客户端，因为线上 v71 不带 rep，固定归华曦达。
- sync_pull 用 `--rep` 过滤，误放进别家 drops 的包也不会被应用。
- `replace.py` 和 `docx_sync.py` 校验 token、HTML 里的 meta 和 rep 三者一致，不一致就拒绝。
- 每份报告单独串行执行，互不阻塞。`tests/test_relay_routing.py` 覆盖。

## 11. 群组闸门：飞书写入要等 Derek（**已实现**）

**根因**：两份飞书文档（创维 `PdxFb…`、华曦达 `FXqHb…`）都在等 Derek 确认，测试或误操作不能写到线上。

**已做**：
- 全局开关 `feishu_live_writes` 和每份报告的 `derek_confirmed` 默认都是 false。
- Drive 覆盖、docx 块写入、入口链接 relink、收件箱追加，在发出网络请求之前都会先检查闸门。
- 闸门关闭时，relay 只更新 box 主稿和本机托管页，状态记为 `gated`，页面上如实显示。
- `tests/test_gate.py` 锁定仓库默认值，并验证闸门关闭时完全不会发起网络请求。同链 replace/upload 只在 Derek 确认后、在 box 上运行（见 HANDOFF 第 0 节）。

## 12. 飞书文字面：docx 块原地更新（**已实现**代码；华曦达、创维两份报告不使用，它们的目标都是云盘 HTML 文件）

**根因**：飞书文档要能直接改文字，所以必须是普通文档块；整篇删掉重写会丢掉批注和链接，`<` `>` 还会被当成 HTML。

**已做**：`docx_sync.py` 把 HTML 的段落、标题、列表、表格单元格和 docx 块一一对应。每次只更新文字变化的块，用 `update_text_elements` 原地写入；不新建文档，也不整篇重写。块被替换导致 block_id 失效时，按原文和相邻文字重新定位。飞书侧已经被人改过的块不覆盖，记为冲突。比较号写成「低于 / 超过 / 不超过 / 不低于」。删除块需要显式加 `--allow-delete`，被拒绝的删除会挂起，等待之后执行。`tests/test_docx_sync.py` 用假 API 覆盖。
