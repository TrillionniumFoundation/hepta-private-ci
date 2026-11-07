# r28 闭合归档器：惰性准备

`export-r28-closed-template.py` 为 **33,547 B / SHA256 `6e3b27eb70806ce69ac66fc4d6c2b9ca61a76d41d5072063f069a7c2e7780452`**。已做 Python AST 检查，没有 import 或执行该归档器，也没有运行 Rust、Cargo、metadata、formatter 或任何 native 作业。

模板保持 `FROZEN = False`。实际 source52 commit `1e0910becc37383e6d17ecf861ea844fd07d8862`、tree `211f15baff19095e8c98bcea2b0ed99ca2270ade`、195 条完整 manifest、原 runner `a7b64eb8…`、job `1a1b1e9bee0-fc05-7b7c` 已固定；三个闭合输入映射仍为 `None`，未经 root/native 审核绑定不能运行。

## 三个待绑定字段

| 字段 | 所需值 |
| --- | --- |
| `TERMINAL_PIN` | 原 `E/native-source52-project-r28-terminal-process-status.json` 的 `{bytes, sha256}`；可带 `git_blob`。路径在代码中固定。 |
| `CLOSED_ORIGINAL_PINS` | `{E相对文件名: {bytes, sha256}}`；实际 r29 `ACTUAL-BINDINGS.json` 的 `R28_INPUT_PINS` 26 项可直接使用。模板分别核原 receipt、raw rc、完整 log/resources、前后 source guard、原 rows/review、complete/incomplete。 |
| `CONTROLLER_ORIGINAL_PINS` | 五个已落盘的平铺 `E/r28-controller-closed-<原名>` 对应 pins；原名为 `launch.json`、`terminal-process-status.json`、`read-000000.json`、`read-002995.json`、`read-005725.json`。这些是原 controller 字节，不是生成的新 terminal。 |

没有复制本轮实际结果到模板常量。它依据绑定原件重建真实状态，保留通过、失败或未形成完整 nextest summary 时的边界；不会把 compile failure 表述为运行了零测试。

## 读回与归档范围

1. 在任何 evidence 读写或 Git 子进程之前拒绝 `FROZEN=False`、未绑定映射或 Python optimization。
2. 独立绑定自然外层终态和原 controller 五件，核 stdout/stderr 的 hex/text、连续 offsets 与 terminal `seen/stored` 总数。
3. 核 native HEAD 仍为 `bef6fa…`、实际 staged tree、195 个 raw SHA/Git blob/Git mode、无额外变更、双锁；收集后再次核验，并重读全部输入保证字节未变化。
4. 原 r28 的 `clean_lines`、`review_python`、`review_tests` 三函数逐字复制。复算原 Python 32 项、各阶段命令/返回码/resources、完整 nextest 唯一 ID、Summary、baseline 接受条件与 footer 复述。仅复用解析函数，没有导入或执行原 gate runner。
5. 保存195源码、双锁、nearest AGENTS、原完整阶段日志和 receipts、baseline、冻结 runner、source52 五成员输入包和完整 apply 原目录；保留 source50 原 lock 证据链、source50/source51 两份祖先 manifest、source51 apply 四原件及 r24/r26 既有失败前置。
6. 输出精确 failure blocks；通过时 failure 列表为空。所有计数来自原日志，不预填 r26 的失败数字，也不把归档器成功当作新 Rust 门。

潜在执行仅允许显式 Git 读取：`rev-parse`、`write-tree`（读取现有 index 身份）、`diff`、`ls-files`、`ls-tree`。没有 apply/add/reset/commit、Rust、metadata 或格式化命令。不会改源码、原日志、原回执或原 runner。

## 新输出位置

- `E/r28-closed-export/`：新派生 failure blocks、独立结果和源码验证；create-only。
- `E/checkpoint-r28-closed.tar.gz`：原件与195源码及 INDEX；gzip mtime=0，每个成员的 raw hash、Git blob 和 transport mode 记录，完成后解包逐字自验；create-only。
- `E/checkpoint-r28-export.json`：实际 archive pins、成员数和原门结果；create-only。

归档期间可以有独立的同源 r29 正在执行。证明字段仅记录“本归档器未启动 workspace/fix/fmt”，不声称整个 native 当前没有其他作业，也不把共享空闲磁盘差值归因于 r28。

`references/export-r26-closed.py` 保留原55,067 B脚本及历史嵌入的 source51 controller 原件，**只作为旧实现参考，不会执行或复制为本轮结果**。`history/pre-review-v1/` 是未交审、未执行的第一份准备产物；冻结当前版补齐原 reader 需要的 `ANSI` 常量。所有原 r26 与 r28 gate 文件不变。

此包本身只证明准备与 AST/字节复核；实际归档仍需 native/root 绑定、审核和一次授权执行。原 r29 启动链继续直接依据其26份真实闭合输入，不依赖本归档器。
