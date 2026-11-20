# 普通 Adopt：现有证据能否保持完整权限且不超过 64 帧

**本次有限复核没有得到一个保持原语义、实际可实施且 ≤64 帧的方案。** 可确认的仍是条件完整路径 74、原上限 64；若只作未经批准的乐观假设，删去两个 DATA 操作的整对，也仅降至 70。实际 Adopt 执行仍为 0。这不是所有未来设计都不可能的结论。

本次只读取已保留的 111 成员档案中的原表、五操作复核、14 成员 helper 附录及 Root 复核，并复读其中 14 份精确 1a 源码的相关函数。这里的 111 和附录的 14 是档案成员数，不能误写成 111 个调用或 14 个新取得的 helper。原表共 38 组；原 NoUpdate12 日志确有 1…64，但整父仍失败。74 是 fresh／独立 B／Artifact Reserve／新 C 分支的条件需求，不是曾执行了 74 次。[原表](originals/CALL_TABLE.json)、[本次计数及日志读回](ORIGINAL_TABLE_READBACK.json)

## 已存在、可以复用的检查

| 守卫 | 已核实的真实作用 | 对 64 帧的影响 |
| --- | --- | --- |
| `OriginalHistoricalOperationV1::read_for` | 同 trust/receipt 指针、当前 session/recipient activation 与传入数据复核；私有同步借用、不可跨线程逃逸 | 使用的是借入 `self.data`，不是新增 A 物理观察。原来已不额外消耗 A RPC，继续去重不会再省一对 |
| factory `require_current` / `with_learning_profile` | 真实 Observe→Confirm，pidfd、writer proof/lease、issuer revocations、logind、时间检查 | 不能贬为缓存；但也没有证明这些返回值等价于 A Source/Cell/RunStart/terminal-ledger/refusal 的完整新观察 |
| `with_original_completed_evaluation` | B record/locks、同 Training cut、真实 native Readback、heads/images、checkpoint 和签名等 | B 记录和 post-A learning checkpoint 不能改称 A 历史实体；未知下层 helper 不推定覆盖或遗漏 A |
| Training completion 双读 | 两次真实 body read、B-finish 已共享同一个 Prepared 操作 | 本来只有一对 A 帧，不是可再次合并的两对 |
| publication 前后检查 | 原 B material、successor proof、原 lane、取消、effect_started/CommitUncertain | 单一 publish 已共享原操作；不能把另一个效果的旧授权跨独立等待搬来 |

错误路径也保留准确区别：原 `with_current_read` 对 callback Err 仍执行 A 后观察并 fence；B helper 对 callback Err 先再做 native Readback/checkpoint 比对，之后才传播。`with_learning_profile` 的 `action(...)?` 会在 callback Err 时先退出，不能声称其所有成功路径 postchecks 在任意错误后都执行。[完整守卫矩阵](GUARD_MATRIX.json)

## 哪些精确 caller 仍未获得删除 fresh 观察的依据

| 原表组 | Caller / 原效果 | 保留原因 |
| --- | --- | --- |
| 21，+2 | `run_original_historical_stage` → Proposal → `CommitProposal` | 新 Proposal effect、receipt 和 checkpoint 之前仍需原 A 新物理检查；Evaluation 已完成及 factory/B live 检查未证明完全支配它 |
| 22，+2 | 上一 receipt 为 Proposal 时，Selection 分派 `CommitDecision` | 这是新的 LocalDecisionV2 effect/checkpoint，不是之后实际 C Selection 的替代；其前后边界仍独立 |
| 24，+2 | `for_qualified_adoption` → `read_original_publication_material` | 原实际 B manifest 在等待 candidate head **之前**固定；移到等待后需证明旧 pin 与拒绝时点等价，当前未证 |
| 25，+2 | `publish_candidate` → `with_original_root_publication` → `artifacts.publish` | 真实独占持久发布。早期 DATA 或后来的独立 selection 都不能授权它；Recover 不能替代 Reserve 来省预算 |
| 27，+2 | `open_original_new_task` → `actual_model` → `read_original_training_material` | 原 C source/target/ingress 到齐后读取真实 candidate model，随后才 open 新 C files 和另读 A completion。两次 completion 读已共用一对；没有安全搬到不同 owner 的已证接口 |

[精确 caller/源码位置](FIVE_CALLER_MAP.json)。三项额外 durable effect 的原对继续保留；即便假定两项 DATA 对各省 2，仍是 `64 + 3×2 = 70`。这只是限定假设的算术，不是承认 DATA 对可删，也不是全系统最优下界。把共同路径的 issuer、CURRENT publish、Source open 合并再凑余数，超出五项已证等价范围，不能暗中计作已省帧。

## 若要合并，实际原 owner 还必须支持什么

当前 `with_original_operation` 的 token 持有的是原 trust 与数据借用；它没有“中途刷新完整 A 物理观察并消费下一阶段”的接口，也没有把 Root 的完整 A 物理事务持有到 consumer 端。Root 的完整观察实际进入 handoff、Source/Cell、RunStart、terminal ledger 以及其 refusal/时限上下文；Source 一侧还复读 witness、publication、Cell decision、FilePin、物理 metadata 和退休状态。[原 A 物理观察](source/authority_host_historical_task.rs)、[实际 Source/Cell 后检查](source/authority_host_historical_task_data.rs)、[当前私有借用](source/root_historical_learning_operation.rs)

要把前一个 effect 的后观察同时用作下一个的前观察，原 owner 需要明确的共同线性化点或实际持有同一 A 物理/refusal/live-authority 保护；保留每个中间效果和 checkpoint 的拒绝顺序、错误 postchecks、取消、fence、CommitUncertain，以及原 scope/recipient/absolute end。不能只留最初和最后两次查询，也不能带旧借用跨 candidate head、Selector 或 C 输入的独立等待。原同步 owner 内既有的 `block_on` 不等于获得了更大的原子权限事务。

最短条件反例是：Evaluation checkpoint 已提交，随后 A 专属物理事实或 refusal 在原 Proposal 前观察时会拒绝。原路径不做 Proposal；只有较早借用和最终 postcheck 的合并版本可能先持久化 Proposal，之后才拒绝。最终均失败不代表持久状态相同。此处没有假定所有 A 状态都能任意变化，也不再把已由 factory/B 真正检查的共享租约或 revocation 当成必漏项；缺口是 **同一 A 复合观察的等价覆盖证明**。

新原 owner 支持还必须继续使用同一真实请求序列、64 上限与原帧/绝对期限，不能另开不计数 client、重放或把多个逻辑观察改名成一帧。现有证据没有给出满足这些条件的具体实现及完整 ≤64 调用图。因此保持 ordinary Adopt hold；本次到此停止，不写 patch、不扩取、不启动试跑。[机器可读结论](READOUT.json)、[14 源 pins](SOURCE_PINS.json)

新增 host、网络、Git API/变更、源码修改、模型/训练、编译、native 和测试均为 0；仅本云原件读回、哈希、日志字段与表算术检查。所有旧原件、预算和准入身份保持。
