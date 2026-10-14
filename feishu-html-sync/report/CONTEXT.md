# 华曦达 2026H1 财报分析 · context 笔记

| 项目 | 值 |
|---|---|
| 本地 HTML（唯一正本，之后改就改这个文件） | `feishu-html-sync/report/华曦达_2026H1财报分析_可编辑.html` |
| 飞书 Drive 同链（HTML 文件） | https://seirobotics.feishu.cn/file/FXqHbFI37oGOCyxT3NkcVhjnnRg （file_token `FXqHbFI37oGOCyxT3NkcVhjnnRg`） |
| 飞书在线文档（docx，普通文档块） | 待首次发布后填写；之后「直接改」只改这一篇 |
| 同步收件箱（「同步修改」写入处） | https://seirobotics.feishu.cn/docx/DqEbdn9KCozO0Kx9JrBcazCunXd |
| 当前版本 | v72（2026-10-14 验收） |
| 构建 | `python3 build_v72.py source_v71.html notes_src_v72.json notes_v72.json 华曦达_2026H1财报分析_可编辑.html` |
| 渲染验收 | `node check_render.mjs 华曦达_2026H1财报分析_可编辑.html` |

规则：Drive 同链只用 `upload_all` 带 `file_token` 原地覆盖，不新建文件；docx 已存在时只按块更新改动的文字，不整篇删了重写。
