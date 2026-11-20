# 附录：factory 的两个实际 helper 覆盖了哪些检查

## 结论更新

本附录保留 `e6_ordinary_adopt_equivalence_review_1/MANIFEST.json`（`3da3eece322862334a83bb6d7cf46f49a1fa7cf39981c4f335efa7d5b6551a24`）及其全部原字节不动。只补取两个完整定义文件，均来自精确 `1a9799686243c2be0ee393ba364e091029cfb944` 并逐字匹配该轮实际 source inventory。

**已从“定义正文未取得”推进到“直接检查范围已确定”：这两个 helper 确实实施真实 recipient / writer / lease / revocation 认证，独立 B helper 还复读真实 B 结果及同一学习 checkpoint。它们的正文没有执行 A 的完整历史 Source / Cell / RunStart / terminal-ledger 复合观察；是否由更下层 B helper 间接覆盖 A 专属实体，仍无已闭合证明。** 按本次两文件上限停止追踪，不继续扩展调用图。

因此，ordinary Adopt 的条件 74 / 原 64 阻断仍在；本次没有获得 M1 的权限等价性。也不能据这两文件断言所有未知下层 helper 都不检查 A，或宣布任何未来设计不可能。

一个必须收窄的反例是：**不能把共享 issuer revocations、writer proof / authority lease 或 recipient pidfd 的变化，直接当成 M1 必定遗漏的状态。** 实际 factory 和独立 B 回调会重新检查这些内容。尚未排除的条件反例应限定为 **A 专属物理历史实体／persistent refusal 的新拒绝**，并明确缺少的是其是否被保留的 B-native 检查等价支配的证明。

## 1. 路径是如何确定的

没有搜索默认分支，也没有根据文件名试探 fetch。

- 先从上一轮精确 primary 的 `impl HostAuthorityService` / `with_learning_profile` 调用，以及 `crate::OriginalRootIndependentBEvaluationFilesV1::with_original_completed_evaluation` 调用出发。
- 实际 1a `CALLERS.toml` 的 `root_learning_live_profile_action`（原 zero-based boundary 1108）明确给出 `authority_host_learning_registration.rs`；`root_independent_b_native_readback`（960）明确给出 `authority_host_q24_evaluation_operation.rs`，并登记前一轮实际 B transport 为 caller。
- 现存实际字节的 `lib.rs` → `authority_host_runtime.rs` → `authority_host_session.rs` 逐层重导出同一个 `OriginalRootIndependentBEvaluationFilesV1`；session 的 `#[path = "authority_host_q24_evaluation.rs"]` 也已核。它们均重新对实际 inventory 核 SHA。
- 两份取得的正文确实包含对应完整定义；B 的委托 `with_operation` 也在同一个取得文件内完整可读。

完整定位记录在 [LOCATORS.json](LOCATORS.json)，两条原边界的逐字片段在 [LOCATOR_ROWS.toml](LOCATOR_ROWS.toml)。这些定位记录不是用 policy 代替产品正文证明；实际范围结论基于下述完整函数。

## 2. `with_learning_profile`：真实 live 认证，但不是完整 A 历史读

精确源 `authority_host_learning_registration.rs:200–296`，13,510 B，SHA256 `2795e8f816f01a54732c87dcd44e54f2f755ae3d98b74e2cb807e5c1e5d4f3b7`，Git blob `ec8a5a68d025a5e23c7f5d448bb5ff3c0fa30f59`。

其直接顺序为：

1. 验证 required mount、Root authority directory、配置和登记 schema、非 Root peer uid/gid、`timeout_ms ∈ 1..=500`、`lifetime_ms ∈ 1..=300000`、state 路径与实际登记 identity。
2. 以本次 `now + timeout_ms` 构造局部 `end`；核真实 pidfd / peer process 和 logind lifetime。
3. 要求实际 retained writer 与 config 相同，进入 `writer.registration.with_live(&writer.leases, ...)`；重新读取 retained writer authorization，要求与原 proof 相等。
4. 用真实 identity / writer-proof digest 验证 learning profile，读取当前 issuer revocations；在 callback 前验证 authority lease。
5. callback 成功后，再要求 revocations / retained proof 不变，重验 lease、logind 和 pidfd。

这明确覆盖了共享 live authority 的一部分。它取得的 `initial` 是 `profile.require_binding(...)` 返回的学习 snapshot，**不是**该函数重新产生的 `RootOriginalHistoricalCompleteTaskObservationV1`。函数正文没有调用原 A 历史 handoff / Source / Cell / RunStart / terminal-ledger / persistent-refusal 的复合 observer。`RootAuthorityDirectory::open(state_dir)` 本身也不等于读取其中每个 A 业务实体。

### 时限和错误语义不能扩大描述

这个 helper 的局部 `end` 不是父 whole deadline。实际 factory transport 仍受上一轮已读的 `HostAuthorityPeerChannel::limit_original_end` / exchange 原 deadline 限制；独立 B 还使用下面的 `min(self.end, frame_end)`。本附录没有改期限，也不把局部 `now + timeout` 说成获得新 whole budget。

`let result = action(initial, proof)?;` 位于第 267 行：**callback 返回错误时会提前退出，不执行该函数之后的成功路径检查。** 不能笼统声称本 helper 在所有 callback 错误后仍执行全部 postchecks。这是原实际行为，不是本附录修改或新测试发现。

## 3. `with_original_completed_evaluation`：真实 B 读取与回调边界

精确源 `authority_host_q24_evaluation_operation.rs:48–360`，15,891 B，SHA256 `baafa3bf95a53bd6082eea2e2d6eacb0830b0d11f7f887a8ef9ef01df5105b95`，Git blob `8537fa1efbb59cd76754a14c77cf5b440b4d2c96`。

入口固定使用 `Operation::Readback`。同文件 `with_operation` 先取 `end = min(self.end, frame_end)`，进入实际 `OriginalBRecord::inspect`，try-lock 原 B owner，保留 candidate / fixed-expert locks 直到 callback、Root 成功后检查和最终物理复读之后。这里的 record 和 locks 是 B 的实体，不能仅凭“persistent”一词与 A 的拒绝记录混同。

callback 前的直接检查包括：

- 实际 learning profile 与已保存 initial 完全相同；同一 backend Arc 的 frozen-scope binding 相同。
- 从真实学习 checkpoint backend `restore` 当前 snapshot，验证 scope 和 Training prefix，要求 Training head、request、owner set 与本操作相符。
- 验证 B files / admitted protocol，恢复真实 candidate / fixed-expert cells，并持有两者原锁。
- 读取原保留的 Training attestation。`Readback` 如果没有首次 completed receipt，会在 181–185 行直接拒绝，不能启动新的首次 B Complete。
- 核原 native heads / output images；调用真实 `native.perform`，此入口的 mode 为 Readback。

随后将 `OriginalRootBEvaluationBorrowV1`（包含 initial、writer proof、actual native、completed result、verifier、`not_send`）交给同步 callback。callback 返回之后，**即使 callback 自身是 Err，也先执行一次 native Readback**，逐字段比较 receipt / attestation / execution / qualification，并再次 restore 同一 learning checkpoint。只有这些检查之后才在第 253 行对 `value?` 传播 callback 错误。

callback 成功并且 `with_learning_profile` 成功返回后，还会核 owner/end、files、同一 checkpoint、原 plan、B cell images、native heads、released-source binding、Generator / Evaluator 签名与时间、锁存在，最后再次核 owner。首次 acceptance 分支对 Readback 不可用。这里的学习 checkpoint 是 post-A learning 的原 backend，不可把它叫作已经重新读取 A 原始 terminal ledger。

这证明真实 B 的认证与物理读确实存在，并且有严格的 readback-only / 同 owner / 不重放边界。**它没有在可见正文中产生或验证 A 的完整历史 task observation。** 未检视的 B 子 helper 仍列在下一节；本附录不猜测其所有传递行为。

## 4. 检查覆盖矩阵

| 所需事实 | `with_learning_profile` 的直接证明 | `with_original_completed_evaluation` 的直接证明 | 能否据此删除原 A 前后对 |
|---|---|---|---|
| 实际 peer / recipient identity 与 pidfd | 配置、registration identity、前后 `verify_pinned_process` | 同一 helper，另有 `owner_alive(owner,end)` | 只能证明这一子集重复；不是整对等价 |
| 原 writer proof / lease / issuer revocations | callback 前认证，成功后再比对与验证 | 同一 helper 包围 B callback | 不能再用这些共享变化作为必漏反例；仍不能替代 A 实体 |
| 原期限 | 500ms 上限内的局部 deadline；完整 frame/session 限制在 caller | `self.end.min(frame_end)`，多处 owner/end 检查 | 不能延长原 absolute deadline；不节省 A 计数 |
| post-A learning checkpoint / Training cut | profile 初始绑定，不是主动 restore 每个业务 checkpoint | 真实 backend restore、scope/Training prefix、callback 前后与之后不变 | 是学习 checkpoint 证明，不等于 A terminal ledger |
| 独立 B record、native heads、输出、签名 | 不直接处理 | 实际 inspect/locks/native Readback/after/签名 | 保留该范围，不能将 B refusal 改称 A refusal |
| A 原 Source / Cell / RunStart / terminal-ledger 的 fresh 复合读 | 正文未调用 | 正文未调用；下层 B helper 的跨实体覆盖未证明 | **没有删除依据** |
| A 自身 handoff / historical persistent refusal | 正文未调用 | 可见 record 是 B record；对 A refusal 的覆盖未证明 | **没有删除依据** |

## 5. 有限剩余缺口；到此停止追踪

本次取得两个完整定义，并非仍然完全不知道它们做什么。但下列委托的完整定义不在本次两文件中：

- `HostAuthorityLearningProfileV1::require_binding`：调用点 registration:257；现有实际 policy 指向 `authority_host_learning_profile.rs`，要求解码 initial / proof / identity / frozen-scope。policy 能定位和说明已登记的必要检查，不能独自证明源码不存在其他行为。
- `OriginalBRecord::inspect`：operation:83；实际 policy 指向 `authority_host_q24_evaluation_record.rs`，登记的是 B 的 Inspecting → Ready、immutable enrollment 和错误 poison。此为 B 记录定位，不是 A 记录证明。
- `require_files`、`files.admitted_protocol`：operation:122–123、259、278；`benchmark::restore_original_cells` / `require_original_cells`：124–126、279–284；`OriginalBExecution::open` / `native.perform`：188–218、228–237；`released_source.require_original(files)`：291–295。

如果主张这些 B 内部调用同时读取了 A 的实际实体与 A refusal，则必须补出准确调用链和 identity / path / epoch / end 对应，而不是根据输入里有 Training receipt 或名字含 Root 进行推定。本次已用完 Root 授权的两份定义补读，**没有继续追取上述文件**。

## 6. 对 M1 和 64 的最终影响

可以确证的共同点是：在现有 factory/B callback 里，真实 writer/recipient/current-leases、B native projection 和 registry 动作位于同一原 owner 作用域内，且保留真实检查。这些是已有实现的认证子集，不能改称缓存，也不能重复计为新 A Historical 帧。

不能确证的是：它们能否使 Evaluation → Proposal → LocalDecision 之间原有的 A fresh physical observations 整对冗余。特别是学习 checkpoint 的不可变、B 完成记录的稳定或 writer lease 当前，并不直接推导 A 原历史实体／refusal 当前。故“只合并更大的 callback，并保留 factory / B 调用”仍没有 M1 等价资格。

原条件 74、原硬限 64、actual Adopt runs=0 均不改变；新 startup 也没有获得预算减免。没有新产品 patch、host RPC、宿主进程、Git 写、模型、native 或测试。

## 原件

- [READOUT.json](READOUT.json)：机器可读结论与有限未知。
- [SOURCE_PINS.json](SOURCE_PINS.json)：两新定义、模块定位源及 actual inventory 对照。
- [LOCATORS.json](LOCATORS.json)：无默认分支搜索的路径证据。
- [DEPENDENCIES.json](DEPENDENCIES.json)：原 3da3 / 74 表 / 实际 inventory / 前一轮三 primary 的精确引用。
- [MANIFEST.json](MANIFEST.json)：本附录成员清单，自身除外。
