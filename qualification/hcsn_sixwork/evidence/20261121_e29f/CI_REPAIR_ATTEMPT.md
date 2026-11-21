# Windows runfiles follow-up: 未完成，保留两次开发尝试

基准源码：`a0b38d3d12c45a4fd254ca27fe1d4266b4c75c53`。
此项是正式科学试验结束后的独立 CI 开发任务；没有再次执行任何学习、final、N256、C2 或 HPCA 阶段。

## 实际结果

补丁尚未应用；Cargo metadata、Bazel lock update/check、formatter 和测试均未执行。没有生成或验证新的 Cargo/Bazel 锁文件。两文件 runfiles 修复目前仍是已审阅的 proposal，不能宣称已修好 Windows 或完整 CI。

| 尝试 | job | 终态 | created→terminal 秒 | 到达阶段 |
|---|---|---|---:|---|
| 首次 | `1a1fef9e7e4-ffbe-21a2` | cancelled，exit -15，非 timeout | 74.548 | 新 worktree 仅创建，没有物化文件；首个 hash-object 因路径不存在 exit 128 |
| 唯一纠正 | `1a1fefc6469-ffbe-21a5` | timed_out，exit 124 | 226.175 | 显式 `git read-tree --reset -u a0...` 未在 225 秒上限内返回 |

首试错误属于本次执行编排：`--no-checkout` 后的 sparse-checkout 配置不足以物化文件。确认新 worktree 无用户文件后，root 明确授权在同一 worktree 纠正一次，并将第二次监督上限设为剩余 225 秒。首试原件未删除或改写。

两次监督窗口的实际累计为 **300.723 秒**；首试实耗加第二次配置上限为 299.548 秒。差额 1.175 秒属于该记录口径中的启动/终止监督开销。这里报告墙钟占用，不冒充 CPU 秒，也不计入模型训练速度。

纠正后的 read-tree 没有产生 stdout/stderr；超时证明物化没有在限额内完成，不能据此进一步归因于某个网络、Git 对象、依赖或编译器问题。没有 Cargo/Bazel 结果可作推断。

## 原件与终态

- `first_attempt/receipt.json` 是首试原始回执，保留 blocked 状态及中断的 final-diff active step；同目录的 `terminal_status.json` 是 runtime 权威取消终态。
- `repair_attempt/receipt.json` 是纠正试验原始回执，保留 running 和 worktree-populate active step；同目录 `terminal_status.json` 明确记录 timed_out、exit 124、terminal publication confirmed、output complete/durable。
- 两次原始 process stdout 分别为 700 和 447 字节，stderr 均为空。命令原始错误和物化空日志分别保留，不补写成功记录。
- `formal_readback/` 保存终结后的正式 checkout HEAD 和原 sparse-checkout 的精确字节，SHA 与先前记录一致。

正式源码在纠正开始前通过 clean 检查；终结后只读回 HEAD 与 sparse 文件，没有另启动 git-status 进程，因此不把这次只读回验证夸大成全仓重新扫描。所有修改命令都只指向独立 worktree；正式五个 namespace 未触及。

本目录中的 wrapper/request、两次终态、原始回执和字节哈希清单共同构成结果记录。开发任务已停止；后续仍需完成真实锁生成，并在原生 Windows runfiles 环境运行现有两个集成用例。
