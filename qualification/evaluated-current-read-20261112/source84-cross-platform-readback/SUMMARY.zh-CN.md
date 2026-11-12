# 84ee Windows / macOS / Fence 原 CI 读回

本包保存原自动 workflow 的 9 份完整 job 日志，合计 6,134,932 字节，以 30 个连续 UTF-8 分片归档。全部分片均已重新 Git 读回，验证每片 Git/SHA-256、连续 offset 和拼合后的全日志 SHA-256。没有重跑、派发、修改 ref 或源码。

原 blocking run 为 `43293663395`，head 为 `84ee9c2ed0db8b20b792634d775f9b4f97a34578`。9 份日志中的 checkout 均为原合成 commit `3fd9ee81bb321f7f7cccd89af077678dc56a5e99`；已从 Git API 独立核实其 tree 等于 head tree `6f1d7265ef1a58a0de1cc8da75ce142111743d85`。不能把这些结果转记到后续 53b 源码。

## Windows Bazel

| 原 job | workflow 终态 | 原 Bazel target 摘要 |
|---|---|---|
| 131446361279，shard 1/4 | failure | Executed 35 / 144；92 target pass、1 fail、51 skipped |
| 131446361296，shard 2/4 | failure | Executed 60 / 151；106 target pass、3 fail、42 skipped |
| 131446361182，shard 3/4 | failure | Executed 43 / 147；100 target pass、2 fail、45 skipped |
| 131446361489，shard 4/4 | cancelled | 取消前已有 filesystem 与 core 分片失败，没有完整 target 终态摘要 |

表中是 **Bazel targets**，包含原缓存结果和跳过项，不是全部新执行 Rust 方法的分母。原 workflow 的部分目标自动重试，之后还会回显失败日志。`OBSERVATIONS.json` 保留每个原结果出现位置与方法名，重复出现不算新的独立方法或样本。

- Shard 1：`remote_windows_sandbox_process_accepts_process_write` 失败；该目标原结果为 2 passed / 1 failed / 21 ignored。原错误明确拒绝 legacy Windows sandbox，因为 ambient parent `FILE_DELETE_CHILD` 能绕过删除边界，且没有维持相同 read policy 的已资格替代方案。不能通过放宽此门修复测试。
- Shard 2：windows-sandbox 三组输出分别是 80/2/1 ignored、76/10/0 ignored、13/2/2 ignored，保留各自 filtered 分母，不互相推算完整方法覆盖。失败包括 legacy sandbox 拒绝、桌面访问、删除矩阵（原预期 PermissionDenied，实际部分返回 None）。CLI 原单方法失败原因为 disabled Windows sandbox level 不能启动 session。app-server 原分片有 turn_start deadline、imagegen 附件读取被同 sandbox 门拒绝后 mock 请求为零，以及部分尝试中的插件目录/worker 恢复失败；原所有尝试保留。
- Shard 3：queue 目标 36 passed / 3 failed，两个方法等待 `queue_blocking_prompt_hook.entered` 超时，另一个 deadline elapsed。TUI 的同一数据库恢复方法三次原尝试均失败；原差异是 `D:\\...\\logs_2.sqlite` 与 `\\\\?\\D:\\...\\logs_2.sqlite`。每次原 shard 结果为 87 passed / 1 failed / 3693 filtered。
- Shard 4：取消前 `exec-server-file_system_windows-test` 已完成 40 passed / 17 failed / 2 ignored；17 个失败原文均通向 legacy sandbox 的 `FILE_DELETE_CHILD` 拒绝。core 的 1/4/6/7/10/13 分片至少各有一个原 attempt 失败记录；取消前未输出其完整方法终态，不补造分母或根因。

Windows release build `131446360965`、Windows Clippy `131446361430`、native paths `131446360485` 三个 job 为 success，完整原日志也在本包。这些 job 成功不等于所有 unit methods 新执行成功。

## macOS

ARM 四个 job `131446360589 / 131446360937 / 131446361302 / 131446361329` 的原状态为 cancelled，API steps 为 null；没有把它们计为已执行或成功。

Intel job `131446361362` 最终 cancelled，但取消前已经有实际失败和超时，必须保留：

| 原目标 | 原方法结果或已观察边界 | 原失败内容 |
|---|---|---|
| matrix-sdk store_version_migration | 0 passed / 1 failed / 2 ignored | `login_or_restore.build.timeout` |
| agentd cognitive_product_e2e | 8 passed / 1 failed / 4 ignored | 已授权 consumer 未收到 federation 内容 |
| agentd supervisord_product_e2e | 1 passed / 1 failed | supervisord read timed out |
| agentd two_agent_turn_recovery | 1 passed / 1 failed | `queue_b.list(...).data` 不等于原 queued item |
| agentd five_agent_rolling_upgrade | 1 passed / 1 failed | 原 Agent 在最终边界不健康 |
| agentd cognitive-product-qualification | 8 passed / 1 failed / 4 ignored | 原 turn 终止内容未满足期望；与前一 cognitive 目标分别保留 |
| hepta-neuron unit | 宣告 209；208 个唯一 ok，0 failed，0 ignored，1 个无终态 | 原 target timeout |

hepta-neuron 唯一无终态方法为 `cell_generation_journal::tests::task_cost_capacity_is_reserved_before_model_work_and_kept_for_acknowledgement`。原日志先报告运行超过 60 秒，再包含 `Test timed out at 2026-11-12 20:04:20 UTC`；目标输出直到 20:08 才回显。不能把回显时间差解释成该方法的新期限，也不能写成 209/209 通过。原 208 行和该缺口在 `MAC_NEURON_PARTIAL.json`。

Intel app-server 6/15 分片另有失败 attempt，但 job 取消前未取得其完整方法结果。没有完整本 job 的 Bazel target 总分母。

## Fence 原 audit 结果

job `131446137061` 的 Fence action 和 post action 均 success。原 log 明示 action pin `c7675fea986c29f1d655753a7a61fd6b4141be8f`、bundle `v0.13.0`、source `64acdc94f531728494efbdf2d8f05faa26e90f7a`，实际 runner image `ubuntu-24.04 / 20261101.360.1`。

原 `FENCE_REPORT_JSON` 是 `mode=audit`、`result=healthy`、`readiness=ready_observation_only`、`protection_available=false`，critical findings 为 0。其原 JSON 行载荷逐字提取到 `FENCE_REPORT_ORIGINAL.json`。这是该次 audit 成功，不是主动网络封锁资格，也不证明此前 v0.10 缺失 inventory 的具体根因已由哪条变更修好；原失败历史不抹掉。

## Windows private-state 既有归档引用

独立 run `43293663313` / job `131446135835` 在 source84 上的整体结果为 failure，唯一失败 step 是 Rustfmt，两个目录攻击门随后 skipped。其原 LEARN/CURRENT 精确选择集为 36/36 passed，collector 的完整原 JSON 保留 source/head/tree、Junit 和 execution SHA、retries=0；不能把整体 job 写成成功。

该完整 370188 字节日志已由另一 agent 保全，本包不重复归档。原 tree 为 `9c967ab6b43459d0c319bfba4a1a5f01316a953f`，manifest 为 `dbafec9511886837e39b6f888de933bc58ccb185`，prefix `qualification/evaluated-current-read-20261112/source84-windows-private-result/`。本 agent 独立取得相同全日志 SHA-256 `1e4c5290e9180ee6f3c6e99610095248f86a06c1c9cfb5fd75796965e9ab07ce`。

## 后续源的边界

后续 head `53b3227a8dff5af9e39ecef6356cfce702d80b1c` 的 blocking run 是 `43297579660`。本包记录的是 source84 的实际旧结果；新源每一个 job 都需要自己的终态和原日志。所有失败原因仍待相应源码诊断，本文没有修改任何断言、权限或超时。
