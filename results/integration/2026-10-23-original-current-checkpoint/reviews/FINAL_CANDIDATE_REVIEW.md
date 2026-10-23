# 冻结 checkpoint-current 候选独立源码审查

## 结论与身份

**冻结的 10 文件候选中，未发现阻止进入原 owning-package 验证的明确源码缺陷。** 这不是测试或 CI 通过结论；本次 reviewer 没有运行 Cargo、Rust 测试、guest、GitHub 或产品代码，也没有修改候选。

候选基线为 Hepta `45f1e7d471c9e0720ce2c149da92629f785a01a4`，tree `62e0c4a173763426a0a6d4e5c3d1fb8df7ce653d`。冻结清单位于 `work/checkpoint-current/publication/manifest.json`，SHA-256 为 `cbe60bc2e7133b4a0011bef45d76007f1c507843e6e1f5ec58d4c7a5df6fbca0`。

独立核对结果见 `candidate-final-review.json`：

- 10 个 candidate 文件的 mode、Git blob、SHA-256、字节数均与冻结清单相符，全部 preimage 相符。
- 其中 9 个前像直接对固定 db91 Git object；Agentd bridge test 前像对已发布的 active-helper 修复。45f1 的关联使用 root 已保留的完整 9,251-leaf readback 证明，没有重复访问远端。
- 独立读取并验证另一 agent 的 8 个 Rust formatter 原始 stdout/stderr：退出码均 0，stdout 与最终源码逐字节相同；每个 stderr 有 106 字节，未宣传零警告。formatter 执行属于原作者，不是本 reviewer 新运行的结果。
- 原 test 函数名称和属性全部保留。仅源码清单计数：memory sender 文件 15→20，Agentd composition 7→9，Notes 5→6，bridge 3→3。这些数字不是原包实际通过数。

## 关键实现检查

| 检查 | 最终候选位置 | 独审结果 |
| --- | --- | --- |
| 原 active writer 的无请求入口 | `hepta-memory/src/objective_sender.rs:133–154` | 检查期限、原 live authority，使用原 `BEGIN IMMEDIATE`；不打开新 DB、不建立新 writer、不写 event、不发 ticket |
| 原 lease / authority fence | 同文件 187–208 | 沿原 `require_current_transaction`，继承 active/expiry/identity 校验；没有放宽 terminal writer |
| 锁内完整 ACK | 同文件 210 起 | full-cut capture、pre-live、原注入 ACK、exact equality、post-live 均在同一个原事务；rollback 后再 live check |
| 发送 unknown 不退回 | 原 `retain_before_send` / append 调用共享入口 | 已 commit 后错误仍映射 unknown，原 durable fence 不删除、一次 permission 不重新授予 |
| 已确认 snapshot 身份 | 同文件 `snapshot_acknowledged:360` | snapshot 与完整 cut 使用同一事务，helper 复用没有引入先读后单独 ACK 的竞态 |
| 必需 checkpoint | `hepta-agentd/src/production_composition.rs:34–48,135–146` | `Arc<C>` 和期限是必需字段，无 `None`、默认 echo 或旧成功 overload；重复安装检查先执行 |
| 初始恢复信任 | 同文件 current_cut 检查与 `open_with_recovery` | 继续先消费宿主独立 current-cut，没有从待恢复 DB 现场 capture 初始授权 |
| 相同 provider / owner | 同文件 234–245 | 同一个 recovered writer 先 `checkpoint_current(inputs.checkpoint.as_ref(), …)`，再将原同一个 `Arc<C>` 移入返回 sender |
| 最后安装顺序 | 同文件 247 起 + 未改原 `config.rs:332–359` | ACK 和 sender 构造均先完成；原 metadata 验证和最终 protected live check 后才连续发布两个 handle，之后没有可失败构造 |
| Notes identity | 同文件 Notes 分支、typed attachment | `attached` ACK 可以先发生；仅成功安装后返回 Notes identity。注释和文档明确它不是 CognitiveStore row |

新公共入口在共享 ACK 前增加一次原 `verify_current_authority()`，比旧内部 ACK 路径多一次原 hot-path 检查；没有放宽权限，但必须由最终原 memory 回归验证，不能复用 db91 的旧 322 项结果。

## 用例是否针对真实边界

| 用例 | 最终源码位置 | 本次源码审查确认的检查逻辑 |
| --- | --- | --- |
| 无请求确认 | `objective_sender_tests.rs:12` | 两次原 checkpoint 返回同 cut；原 full cut 不变；sender request+event 总行数为零 |
| terminal / 期限反向 | 同文件 60 | 真正调用原 release 与 rollback，再要求 checkpoint 失败、publisher 零调用、终态 cut 不变；非法期限同样不调用 publisher |
| refusal / timeout / mismatch / live 撤销 | 同文件 98 | 区分 ACK unknown 与原 writer 拒绝，保留 cut，允许后续显式 ACK，不制造重发 |
| 原数据库写锁 | 同文件 140 | 另一个真实 SqliteConnection 的 `BEGIN IMMEDIATE` 得到 BUSY(5)；原 ACK 完成后可进入并回滚 |
| 取消 | 同文件 183 | abort 真实挂起 future，要求取消、可重新取得原 store lock、无 sender 行，再显式 ACK |
| early / post-ACK factory 拒绝 | `production_composition_tests.rs:244,268` | 非法期限时所有外部 probe 为零；真实恢复后的 changed cut 在 refusal/timeout/mismatch/live fault 时不安装两个 config handle |
| Notes ACK 后 checkpoint 失败 | `production_composition_notes_tests.rs:256` | 原 socket/SCM_RIGHTS offer 已返回真实 `attached`；失败后两 handle 为空，实际 application stream EOF，零 effect/issuer bytes |
| 同 Arc sender 接线 | `objective_sender_host_tests.rs:59` | 使用 strict attachment 返回的 sender；同一 checkpoint probe 先看到 bootstrap ACK，再看到真实 retention 后的 changed cut；兼容 getter 仍指同原 writer |

这些 fixture 验证的是原 owner 逻辑和真实本地锁/descriptor 边界。`Hold` future 被取消并不能验证不存在于仓库中的真实 remote backend 不会迟到发布；文档已经保留此区别。

## 仍不可关闭的范围

1. **生产 checkpoint / latest-read backend 仍缺。** 注入 trait 不是生产实现；没有新增 signer、数据库、第二 ledger 或 trust root。
2. **取消后的迟到发布依赖真实 provider 的契约。** cooperative timeout 不抢占同步 callback 或 future poll，且不覆盖 begin/capture/verify/rollback 的总耗时。
3. **返回值是锁内确认时点的 cut。** 后续任何原 registered-table mutation 都可能使它过期。
4. **终态 lease 发布仍缺。** 当前 active-only 入口正确拒绝 Released/RolledBack/expired/superseded，不能事后拿它发布终态。
5. **连续原 owner mutation 与外部 receipt retirement 未自动接线。** Notes 与 HOS2 的后续 terminal/retirement、dispatch 内多次写入、reconcile、semantic mutation 等见 `MUTATION_TERMINAL_GAPS.md`。
6. **same-provider 保证属于 canonical strict attachment。** 显式 trusted-embedding getter 仍允许调用者提供另一个 checkpoint；文档没有声称全局禁止。
7. **必须分别取得最终 memory 与 Agentd 原包执行证据。** 新源码格式化、本文代码审查、旧 memory 测试或现有 CI workflow 文件都不能代替本候选实际门禁。

当前候选正确收敛在“原 active writer 的完整 cut 发布入口 + 必需 ACK 的 strict bootstrap”。建议保持该范围进入原包验证，并继续如实保留上面的生产与运行期缺口。
