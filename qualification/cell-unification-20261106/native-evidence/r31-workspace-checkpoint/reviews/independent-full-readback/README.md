# R31：独立完整闭合读回

本组独立读取实际闭合归档中的完整日志、rows、回执、资源记录、controller 和源码字节。reader 首次纯本地执行退出 0，没有导入或运行 native runner、exporter、Rust、metadata、fix 或 fmt。

## 实测结果

- 原 `just test --locked --retries 0`，默认 193 个 workspace members。
- 完整原日志重建 **20,228 个唯一 `(binary, name)` 身份，全部 PASS；0 FAIL、0 TIMEOUT，130 reported skip**。skip 身份没有从总数反推。
- 与原 R29 的 20,228 个执行身份完全相同，没有 missing、additional 或重复执行身份；当前 footer 重述为 0，真实失败块为 0。
- Starting 宣告 **366 binaries**；有实际执行行的 binary 身份组为 **323**，两者分别保留。
- nextest 执行 **1643.187 秒**；含构建等的原 tests wall 为 **1854.4279615879059 秒**。raw、effective、outer 均为 0。
- 全归档 **353 regular members / 352 INDEX entries** 完整 raw SHA256、Git blob 和 mode 读回；其中 **197 个源码文件**独立核对，原 source52 的 195 行加两份 source53 诊断文件。没有把 tar 权限位当成 Git 文件类型，也没有宣称另做完整离线 Git tree 重建。
- 原 fresh metadata 调用退出 0；193 members/default members 及 scope 的原始顺序逐项匹配。metadata 与历史相同 bytes 不改变本次调用的原回执身份。
- controller stdout **4875 B**、stderr **0 B** 由原 range/hex/text 完整拼接；开始、raw return、receipt 三条事件与原文件相等。

## 证据边界

source53 保持 `diagnostic_only=true`、`behavior_repair_claimed=false`。R29/source52 原 Bedrock 失败仍是失败；本次同 ID 实测 PASS 0.354 秒，不能仅据诊断日志新增和重跑通过声称已证明行为修复。历史 R28、同源 R30 和本次 R31 不合并计数。

本组核验工程执行证据，不授予科学结论、全平台/全部 feature/外部服务资格或 finalizer 执行权限。原测试之后未由 reader 运行任何 fix/fmt 或测试。共享文件系统空间采样不能当作该门独占资源成本。

`CLOSED-SMALL-READBACK.json` 保留最初大日志尚未传回的历史 pending 字段；本组完整报告补齐它的范围，没有重写旧原件。`EXPORTER-BINDING-READBACK.json` 仅证明当时 literal 绑定和单行 activation 字节关系，不是 exporter 执行回执。

## 复核入口

- `CLOSURE-SUMMARY.json`：简明结果及完整原证据 pins。
- `closed-readback-v1/INDEPENDENT-READBACK.json`：独立全量结果。
- `closed-readback-v1/EXECUTED-ROWS.json.gz`：完整逐 ID/耗时/原行号/字节偏移；mtime=0，无损内容与 native rows 原 bytes 一致。
- `closed-readback-v1/ARCHIVE-MEMBERS.json`、`SOURCE-FILES.json`、`ORIGINAL-PINS.json`：逐项原件映射。
- `LOCAL-EXECUTION.json`：本地 reader 实际首次执行结果。
- `review_closed_archive.py`：不依赖 producer parser 的可重现本地 reader；需要原归档和 root 只读授权原件路径。
