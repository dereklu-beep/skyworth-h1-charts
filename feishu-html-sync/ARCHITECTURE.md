# 同步链路（现状 + 本分支改动）

```
Chrome（编辑模式）「同步修改」
  └─ POST SDMCSYNC1 → webhook.site（CORS *）          [以后：自有 Worker /sync]
       └─ box ws_poller.py（出站轮询）→ relay.py 127.0.0.1:8787/sync
            ├─ drops: v41/sync_inbox_drops/drop_*.txt   （完整包，sync_pull 首选来源）
            └─ 飞书收件箱 docx append                  （备份来源）
  sync_pull.py（本分支）：校验 eid → 内容匹配 → 锚点 → 上下文打分 → 写主稿 + sync-rev + ledger + status
  replace.py：同 file_token 覆盖 FXqHbFI37oGOCyxT3NkcVhjnnRg，并刷新 relay/hosted/report.html（/chrome）
```

## 进程（box）

```bash
python3 /workspace/feishu/relay/relay.py       # :8787  /sync /save /chrome /health
python3 /workspace/feishu/relay/ws_poller.py   # 每 3 秒拉一次 webhook.site
python3 /workspace/sdmc_skyworth/sync_pull.py --no-inbox --status-dir /workspace/feishu/relay/status   # sync_watch 或 relay 调用
```

## sync_pull 常用命令

| 目的 | 命令 |
|---|---|
| 一次性写入稳定 eid 和 rev | `sync_pull.py --target T --stamp` |
| 演练（不写文件） | `sync_pull.py --target T --dry [--no-inbox] [--text pkg.txt]` |
| 正式应用 | `sync_pull.py --target T --status-dir DIR` |
| 作者重建后重放 Derek 的修改 | `sync_pull.py --target NEW --replay v41/sync_ledger.jsonl` |
| 重试未解决项 | `sync_pull.py --target T --retry-unresolved` |

各问题的取舍和后续计划见 `PROBLEMS_AND_SOLUTIONS.md`，拷贝说明见 `HANDOFF.md`。
