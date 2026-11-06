# 当前 67cc 候选的单次 CI 快照与已结束原生任务原件

本包绑定 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` 及树 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。源提交和实际合并提交 `b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae` 均有独立 Git API 原件。每项 API 响应保留自己的请求及观察时间；这是一次有界快照，不是原子全局状态。

## 快照与原始结果

20 份完整 runs/jobs API 响应覆盖 19 个 run、53 个 job：10 成功、10 执行中、30 排队、1 取消、2 跳过，实际失败 job 为 0。Linux Supervisor 的全工作区格式检查 job 尚在排队，runner 为 0、步骤为空；Windows Supervisor 仍在执行，不能将任何一项标为已通过。

当前源 Windows Core 原始任务已结束。完整八个 shard 日志共列出 2,343 个不同用例名，2,340 通过、3 ignored、0 失败。额外一条同名 PASS 属于阻塞快照用例的受控子进程，不增加 catalog 数。独立原始控制为 4 项 resume/environment、1 项 sanitized fork、3 项 runtime ownership；归档中残留的非分片三项 ownership 日志属于此前独立控制，未计入完整 shard 统计。

其余已结束任务的原始结果为：Windows retained recovery 299 Memory、209 State、24 Path，共 532 通过，原日志另报 7 skipped；Windows business 三库在源提交和实际合并提交上各 78、19、21 通过；Git/Queue 在两种 checkout 上分别为 35、36 个不同用例通过，Git 子进程的重复输出不增加用例数；Windows operator 40 通过，原生 macOS x86_64 operator Bazel 33 通过。Windows Keyring 的成功范围为 Cargo resolver/lock 诊断及空差异，没有转为产品安全验收。

## 可复核范围

本包保留 9 份完整原始 job log、10 份完整原始 ZIP，以及全部查询原件与检验记录。所有 ZIP 均经过官方 SHA-256、大小和所有成员 CRC 验证。为避免重复存储，ZIP 内的提取副本不再次收入传输包；ZIP 本身包含全部原始日志、XML 和已生成的 compact execution 文件。

Core 的这两份 ZIP 只提供完整原始日志，没有 XML 或 compact execution log。其余目标的 compact execution 原件完整保留，但本次有界检查未解码，所以没有据此新增逐 action 环境、缓存命中或执行位置结论。也没有逐项重新审计所有成功测试的运行时提前返回分支。本包不宣称全仓库、全工作区或所有 blocker 已完成，旧 `eed` 结果没有转移给当前候选。

## 还原与检查

按 [`transport-manifest.json`](transport-manifest.json) 的顺序拼接 base64 分片，base64 解码、gzip 解压并读取 JSON。将每个成员的 `content_base64` 解码至其相对路径，同时核对字节数、SHA-256 和 Git blob 摘要。完整成员清单见 [`members-manifest.json`](members-manifest.json)。

还原后运行 `python verify_current_cut.py <还原目录>` 可直接从原始 ZIP 和 API 验证当前结果；不必先解压 ZIP 成员。检查器不执行 Rust、Bazel、原生测试、网络请求或 Git 操作。机器可读结果见 [`summary.json`](summary.json)。
