# 第四批发布源的第二批原 CI 原件增量

本包继续绑定已发布头 `0e139b599f0fe451f80fb7db4b2913bb9c679dce`、树 `091e659e0da6602299fd14cfa93889191405edd8`，普通合成检出为 `e93aefbbb33438f6ec67e995adcfe88657158487`，全部原运行 `run_attempt=1`。它补充首批归档，没有覆盖或更改首批原件。

API 快照查询在 **2026-11-05 07:13:06–07:14:11 UTC** 完成。第二批共 **101 件原件、29,126,247 字节**；压缩后 **11,454,207 字节**，59 个严格 base64 块。完整原 ZIP、完整 job 日志、逐成员哈希、具名用例投影及原 API 均保留。后续独审文件的生成时间可以晚于 API 截止，不能据此把后来作业结果混入该快照。

| 原范围 | 实际结果与边界 |
| --- | --- |
| Intel PTY | 当前 31 项为 30 通过、1 失败；原 30 项为 29 通过、1 失败，新增 collector 控制通过。唯一失败为 `pty_dropped_output_receiver_keeps_draining_child`，原 2 秒期限内未退出，日志记 `python_started`。失败早于通用取消信息，不能被取消结论抹去。 |
| Supervisor Linux | 原 3 项与 14 项测试实际通过；作业因 Rust 1.95.0 格式检查的单处折行失败。 |
| Codespell | 原失败实际为 572 条注释、153 个冻结证据文件；完整原注释与精确路径保留。候选排除方案属于静态修复，不是已经重验通过。 |
| V8 Mac ARM / Intel release | 两者均为原 6 项 smoke 中 5 通过、1 失败，真实运行检查发现 native sandbox 为 false、Cargo feature 期望为 true。最小参数修复尚未执行。 |
| Windows Queue source / merge | 两个完整原 ZIP 各自证明 Queue 36 项通过、Git utilities 35 个不同用例通过。原 B13 的 8 个 Queue 名称全部各出现一次通过；嵌套 self-exec 的重复打印和 collector 的相同副本都不重复计数。XML 是目标包装，逐项结论来自完整正文。 |
| Exec Mac ARM source | 原 resume 13、rollout 125、server 383 通过；resume 的 76 个筛选跳过仍保留。 |
| Exec Windows source / merge | 两个被取消的作业在取消前各完成 rollout 121、server 254 通过，含 authorized-read 真实权限用例。resume 只有编译日志，缺结果和 JUnit；未生成最终 retained 回执，不能补称 whole job 或 13 项 resume 通过。Windows proxy 的早返也不计为实际 CONNECT 行为。 |
| Exec Linux merge | 归档只有部分 server 编译日志和 source 身份；没有结果 XML，不作通过判断。 |

同时冻结的具名退出范围投影包含 **142 个不同名称**：旧七项索引 97、B10 原失败 10 与 turn-state 4、B21 原 Intel 30 与新增 1。当前可见的限定通过是 B08 Windows 3/4、B09 Windows 9/19、B13 Windows 8/9；B21 有上述实际失败。B07、B10、B20、B22、B23 尚缺本次完整具名正文。这里没有更改原 23 项的状态、退出条件、测试预算或闭合类别。

取消的操作者与原因没有明确原证据，保持未知。没有执行重跑、取消、dispatch、产品构建或修改分支。

## 复核入口

```sh
python3 generated-evidence/batch-02/verify_archive.py generated-evidence/batch-02
```

该命令只验证归档。见 [原件清单](generated-evidence/batch-02/original-files-manifest.json)、[传输清单](generated-evidence/batch-02/transport-manifest.json) 和 [实际 Git 回读收据](generated-evidence/batch-02/blob-upload-receipts.json)。全部 59 块必须按顺序严格解码，重建压缩包和 101 个成员均须匹配固定长度、SHA-256 与 Git blob 身份。
