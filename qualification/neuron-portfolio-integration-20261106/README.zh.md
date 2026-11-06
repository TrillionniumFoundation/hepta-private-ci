# NDU / Joint generation 与既有 owner 的显式集成

## 1. 本轮交付与验证状态

本轮为已有 Cell / Agentd generation 路径增加完整 owner 观察、冻结 episode 合同、显式 NDU 动作组合及独立 outcome 交接。状态、输出、成本、推理请求和学习事实仍由原 owner 提交；没有增加同时持有这些资源的 portfolio 服务。

这是 **opt-in 接入候选**。固定源码 `61921427` 已完成本轮 Linux 原生验证：**982 项执行并通过，66 项既有 `#[ignore]` 在顶层跳过，新增 16 项全部实际通过**。五阶段原回执、必要的同范围暖复验、实际 helper 身份、原始 JUnit 与历史失败均已保留；详见 [机器可读结果](STATUS.json) 与第 6 节。此结果只覆盖明确列出的包与用例。

| 身份或状态 | 固定值 / 当前含义 |
| --- | --- |
| 本轮 PR | [#4944](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4944)，草稿，依赖 #4935 |
| 继承候选 | [#4935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4935)：既有 owner inventory、V13 学习与 Joint 生命周期候选；不继承其分支测试资格 |
| 初始工作基线 | `1dc387ceaa51dbf472b702bab76e787ef9fe5de9`，tree `f5dc90c9365c1ea7abc88e8c909b26aa375d71e4` |
| 已合并的 #4935 donor | 源码 donor `862f8dca2ea24ca41abbb0edf6926732e2bc6ec2` 经 `27928bf8` 合并；后续仅新增 qualification 的 `9f73f82c` 经 `2415aa24` 合并，相关代码对象保持一致，见 [SOURCE_BINDING](SOURCE_BINDING.json) |
| 历史中间源码 | `f73e638b5c0c1813767333e07e30de2d8b178499`，tree `3b5656e439f9d58f13c546981e33bc8506c96475`；后续发现同 operation 不同 request 的规划成本拒绝路径需修复，因此它不是最终资格源码 |
| **实际执行源码 / tree** | **`61921427dc19223fd8c9d0ded1a4723b255c5df5` / `31d99be67393619aca47436d82f9dca909cba359`** |
| 原生测试、Clippy、helper 构建与原始 JUnit | **PASS（本节声明范围）**：三包 `just fix`、四包严格 Clippy、实际 helper 构建与四包 `just test`；最终 helper hash / mtime / size 前后一致 |
| 文档与证据提交 | 与执行源码分开提交；必须保留执行源码 SHA，不把后续证据提交 SHA 冒充已执行代码 |

源码按三个可独立审查的阶段组织：`4567218e` 的 owner observation / planned-step，`525074cb` 的冻结 episode / 独立 outcome，`8d21b56c` 的显式 Joint / NDU 组合。后续合并与修订形成同一候选；测试资格来自上述固定源码的实际回执，不由阶段名称或继承关系推断。

## 2. 七项职责与实际接入位置

| 能力 | 原有职责与本轮接点 | 保留的所有权边界 |
| --- | --- | --- |
| 多模态编码、生成状态推进 | [Joint worker proposal](../../codex-rs/hepta-infer-worker-host/src/joint_generation/proposal.rs)、[真实进程适配器](../../codex-rs/hepta-neuron/src/cell_joint_generation.rs) | worker 只计算 successor state、output delta 和成本事实；没有 journal / outbox 写权限 |
| Hepta 共享状态与局部 Cell 计算 | [Cell generation reducer](../../codex-rs/hepta-neuron/src/cell_generation_state.rs)、[Neuron 导出](../../codex-rs/hepta-neuron/src/lib.rs) | 状态推进继续经过既有 Cell 计算及提交接口，不建立第二份模型或状态 owner |
| NDU 价值定义与评估 | [NDU V2 evaluator](../../codex-rs/hepta-ndu/src/evaluator.rs)、[policy-bound receipt](../../codex-rs/hepta-ndu/src/model.rs) | objective、generation、utility profile、聚合规则、阈值与 scalarization 进入既有评价；返回建议，不产生执行或采用权限 |
| 动作选择和资源规划 | [现有 control-plane NDU planner](../../codex-rs/hepta-control-plane/src/planner_ndu.rs)、[本轮 Joint request composer](../../codex-rs/hepta-intelligence/src/joint_generation_plan_v1.rs) | 本轮 composer 直接组合既有 NDU evaluator 与显式 Joint 请求，不持有全局预算、不分配真实资源，也不替代 control-plane 的 owner 汇总、可行计划与授权机制 |
| 单次 dispatch、取消、未知结果与恢复 | [durable generation control](../../codex-rs/hepta-neuron/src/cell_generation_control.rs)、[Agentd generation owner](../../codex-rs/hepta-agentd/src/neuron_generation.rs) | 请求 admission / worker readback 仍由原 durable control 负责；重启不把未决请求重新当作新任务执行 |
| state、prefix、outbox 与成本提交 | [Cell journal](../../codex-rs/hepta-neuron/src/cell_generation_journal.rs)、[atomic observation](../../codex-rs/hepta-neuron/src/cell_generation_observation.rs)、[Agentd actor](../../codex-rs/hepta-agentd/src/neuron_generation_service.rs) | 既有 journal 唯一提交；`observe_generation` 同时读取状态、pending、outbox、成本与连续性 checkpoint；`step_planned` 在同一 actor 命令内处理成本和 admission |
| outcome、credit 与参数候选 | [冻结 episode bridge](../../codex-rs/hepta-intelligence/src/generation_episode.rs)、[既有 outcome/credit closure](../../codex-rs/hepta-intelligence/src/outcome_credit_v2.rs)、[LedgerWriter](../../codex-rs/hepta-learning-ledger/src/production.rs)、[Cell update proposal](../../codex-rs/hepta-neuron/src/cell_update.rs) | 独立 observer 签名与 LedgerWriter 保持唯一学习事实入口；credit、dataset、训练候选、独立评价和版本采用继续走已有边界 |

没有修改 V2 journal / config / manifest 的持久化 schema，没有新增依赖，也没有切换默认 provider。该候选不使尚未组合的全局资源规划、真实模型授权、跨机生命周期或学习采用自动合格。

## 3. 实现保证与限制

### 3.1 冻结合同与实际 Init 分开验证

`FrozenGenerationEpisodeV1` 固定 episode ID、Cell run ID、Decision record ID、objective、planning policy、独立评价 profile、sampler 声明、source frontier 及完整初始 snapshot。初始 snapshot 含 scope、generation、writer epoch 和 backend manifest 身份；manifest 继续绑定模型、encoder、runtime、设备、schema 及 learning / evolution 引用。

`task_digest` 从规范编码的合同派生，再写入 `CellGenerationConfigV2`。合同输入不包含自身的 task digest，避免自引用。签名 Decision 的 `run_snapshot_digest` 使用 `contract_digest()`，`support_digest` 使用 `decision_support_digest()`。Cell 的 `scope.run_id` 与学习账本的 Decision record ID 是两个明确的字段。

通用合同中的 `sampler_digest` 只是冻结配置声明。Joint 专用 composer 进一步把真实 `Init { seed, sampler }` 与 host-bound `public_digest` 编码后校验。owner 从已有 admission / commit 事件重建 `first_advance_input_digest`：仅首次实际采纳的 `Advanced` 或 `Stopped` 结果可以设置它；失败、取消或超期未采用的计算不计入。每次 `plan_advance` 都比较该输入摘要与冻结的 Init，因此通过旧 V2 接口提交不同 seed 后再进入新 planner 会被拒绝，重开 journal 后也一样。

这证明的是请求、已采用输入与冻结配置的对应。原通用 `step` 和 worker `Auto` 仍可用，因此首个 Init 一致不证明后续所有历史动作均经过冻结的 NDU planner；本轮不提供全历史 policy provenance 证明。数值内核和模型内容的正确性仍依赖固定 worker 的适用验证；不能把 request hash 当作质量证明。

### 3.2 一个 owner cut 包含全部已记录事实

`CellGenerationObservationV1` 由健康 journal 唯一构造，字段私有、可克隆和序列化，没有公共反序列化构造器。Agentd 的 `observe_generation()` 在单个 actor 命令中取得：

- task、source frontier、初始 snapshot 和已采用首输入身份；
- 当前完整 snapshot，包括不可撤回的 committed prefix；
- 原请求的 pending digest、待 ACK outbox；
- 所有已记录成本，以及覆盖 config 和全部已保留事件的 owner continuity checkpoint。

这避免分别读取 snapshot 和 cost 时拼接出不存在的一致状态。即使仅新增成本、snapshot revision 未变，owner checkpoint 也会变化。提交或 witness 状态不确定时不能导出新的观察，须先经过原恢复过程。

这个 sealed Rust 值不是远端签名、硬件证明或新的权限。它保留原 owner 的本地观察边界，独立学习事实仍需要后续签名和 LedgerWriter 验证。

### 3.3 规划建议、真实费用与 dispatch 分开

Joint composer 对 `abstain/audio/image/shared/stop/text/verify/video` 的完整候选集合运行原 `evaluate_candidates_with_policy`。policy digest 覆盖 utility / normalization、required organs、risk / resource ceilings、聚合规则、Pareto tolerance 和可选 scalarization。contribution 的 support 绑定这次 owner cut；旧 cut 的预测不能套到新观察上。

建议被映射为明确的 `Advance { action }`。无唯一建议或选择 `abstain` 时返回无请求，不隐式转换成 STOP，也不发 worker `Auto`。原研究 `Auto` 接口仍存在；新路径不会调用它。

每次真正发生的规划使用独立 `planning_attempt_id`，与 worker 的 `operation_id` 分开。进入评价阶段后，无论成功、无动作还是失败，返回的 attempt 都带实际计时的 Planning entry。调用端必须保存并提交它；不能先对 `attempt.result` 使用 `?` 而丢弃失败费用。已记录 attempt 在新的 owner observation 上拒绝重复计算，精确重试应保留原返回值。

`step_planned(expected_owner_checkpoint, planning_cost, request)` 把成本处理与请求 admission 放在原 Agentd actor 内。其实现与回归验证的行为包括：

- 当前 cut 匹配时，先由原 journal 保留成本，再沿原 owner / control 提交请求；
- cut 已变化时，保留合法且实际发生的规划费用，拒绝过时请求，不 dispatch；
- 已有原请求但又产生新的 planning attempt 时，保留新费用并拒绝把它变成第二次执行；
- 同 operation ID 对应不同 request digest 时，仍保留合法新规划费用，再报告冲突，不 dispatch；
- 同成本 event ID 更换内容会被原成本 owner 拒绝，不能借“重试”覆盖已计费用；
- admission、期限或后续阶段失败，不撤销已实际发生的成本；原请求的精确重试只查询或返回原回执。

其中同 operation / 不同 request 的拒绝成本修订已进入 `61921427dc19223fd8c9d0ded1a4723b255c5df5`，并由第 15 项原生回归实际通过。成本仍须是合法、实际发生且身份正确的 meter 事实；这不把调用端声明变成独立成本认证。

### 3.4 合法动作与 backend feasibility 的证据边界

composer 检查命名集合、objective / generation、policy、owner cut、聚合完整性和输入绑定；这些属于本轮实际实现的拒绝条件。`UtilityContribution.feasibility`、预测 utility / risk / resource 值仍由已经获得准入的调用端提供。

因此，**caller 标记 `Feasible` 不是 backend 当前状态合法性的证明**，也不是资源已预留的凭据。真实 worker 仍执行自身的状态、动作、期限及资源准入检查。新真实 helper 回归在固定 fixture 中先执行 shared 再 STOP，并显式给出该 fixture 的 feasibility；不能据此宣称所有模型、所有状态和所有候选动作都已自动证明合法。

本轮也没有把 composer 变成全局 resource allocator。需要 control-plane 的 owner coverage、有效期、资源预留与 final-use 授权时，仍须走其既有接口，不能用 NDU advice 绕过。

### 3.5 未知、恢复和前缀

`task_cost()` 仍是已记录费用的视图。它的已知部分不能单独代表 episode 全成本；应读取 `observe_generation()`。本适配器中的 `is_terminal()` 仅在已提交 STOP、无 pending worker 且无待 ACK 输出时成立。`complete_metrics()` 还要求记录的全部阶段和指标没有缺测；CPU、energy 或其它测量缺失继续是 `None` / unknown，而不是零。

未知 worker 结果继续保留原请求标识和前驱。`reconcile(expected_request_digest)` 只读原计算；重启后不能通过换 operation ID、清空 journal 或重新 Init 来规避未决请求。取消请求不证明 worker 未执行，也不抹去已发生费用。

committed prefix 是原 owner 已提交的精确字节。outbox 交付和重试保留相同 operation、request digest、offset 与 bytes；ACK 仅确认原 chunk。后续修复可以产生新增内容，不能静默替换历史 prefix。新 outcome support 同时绑定该 prefix、成本及 ACK 所处的 owner cut。

### 3.6 独立 outcome，不由生成器自评写入

`outcome_evidence()` 仅把冻结合同与 settled / delivered owner observation 绑定成支持摘要，不生成质量、reward 或 credit。`append_generation_outcome_v1()` 进一步要求：

1. 活动的 authenticated Decision 与 decision ID / episode 相同，且其 run snapshot、objective、policy 和 decision support 精确匹配冻结合同；
2. 独立 outcome 的 support 是本次 owner evidence，unit profile 是冻结的独立评价 profile；
3. 调用既有 `append_observed_outcome_v2` / LedgerWriter 验证签名、observer 与 generator 独立性、账本前驱及 outcome 纠正链。

允许保存“输出已结束，但成本仍缺测”的独立观察事实；这不会获得完整净收益资格。延迟 quality 的 Pending / Censored 语义仍由原账本验证。本轮新 bridge 的成功输出终态是 STOP + 已 ACK；没有 STOP 的失败 / 取消 episode 不能被此 bridge 冒充已交付完成。

## 4. Opt-in 生命周期接入示例

下面展示真实公开 API 的组合顺序。`config`、`profile`、`public_digest`、worker / witness / handle、签名及传输回执均由既有 host 准入提供；示例不新建服务或可信签名者。代码片段是接入说明，完整可运行的 worker / Agentd 样例见 [真实 helper 集成回归](../../codex-rs/hepta-agentd/src/neuron_generation_joint_tests.rs)，签名账本样例见 [episode 回归](../../codex-rs/hepta-intelligence/src/generation_episode_tests.rs)。

### 4.1 在打开 owner 前冻结身份

```rust
let frozen = FrozenGenerationEpisodeV1::new(FrozenGenerationEpisodeInputV1 {
    episode_id,
    run_id: StableId::new(&config.initial.scope.run_id)?,
    decision_id,
    objective_digest,
    policy_digest: profile.digest()?,
    evaluation_profile_digest,
    sampler_digest: joint_generation_sampler_digest_v1(public_digest, seed, sampler)?,
    source_frontier: Digest32::from_array(config.source_frontier),
    initial: config.initial.clone(),
})?;
config.task_digest = frozen.task_digest().into_array();
let plan = JointGenerationEpisodePlanV1::new(
    frozen.clone(), public_digest, seed, sampler, profile,
)?;
```

将原 config 交给 `CellGenerationJournalV2::open`，把同一个 journal、既有 inference control 和 host clock 交给公开的 `neuron_generation_channel_v2`。其返回的 bootstrap 通过既有 [配置入口 `with_neuron_generation_bootstrap`](../../codex-rs/hepta-agentd/src/config.rs) 装入 Agentd，再由 [正常 runtime 启动](../../codex-rs/hepta-agentd/src/runtime.rs) 内部服务。真实 helper fixture 在 crate 内直接启动同一服务；其中 `spawn_neuron_generation_service` 是内部实现，不是外部调用者的公开 API。不要在恢复时重建新的初始合同或丢弃旧 witness。

在实际执行前，由已有 generator 对生产 Decision 签名并交 LedgerWriter。除了原有真实候选集合、选择概率与 completeness 证明，其字段必须为：

| Decision 字段 | 值 |
| --- | --- |
| `record_id` | `frozen.input().decision_id` |
| `episode_id` | `frozen.input().episode_id` |
| `run_snapshot_digest` | `frozen.contract_digest()` |
| `objective_digest` / `policy_digest` | 对应 frozen 字段 |
| `support_digest` | `frozen.decision_support_digest()` |

只有非零摘要还不够；原 LedgerWriter 仍会验证真实签名、generator 权限及候选完整性。

### 4.2 提交 Init，未知时只查原请求

```rust
let initial = handle.observe_generation().await?;
let init = plan.initialize(&initial, init_step)?;
let expected = init.digest()?;
let result = handle.step(init.clone()).await;
```

`init_step` 使用正数 host monotonic admission time、有效 deadline、稳定 operation ID 和独立 attempt ID。若返回 Pending、连接中断或结果未知，保留原 request 和 `expected`，通过 `pending_request()` / `reconcile(expected)` 对账；不要再调用 `plan.initialize` 创造新计算。只有原请求得到实际结算后才取得新的 observation 进入动作选择。

```rust
let pending = handle.pending_request().await?;
if let Some(original) = pending {
    let result = handle.reconcile(original.digest()?).await;
    // result 仍可能 Pending / Unavailable；保留原身份，等待既有恢复流程。
}
```

### 4.3 规划并保留每次尝试的费用

调用端使用当前 backend 观察形成 `ContributionSet`，包含全部八个命名候选和所需 organs。每个 support 使用 `joint_generation_contribution_support_v1(&observed, &candidate, &organ)`；每个真实新规划分配新的 `planning_attempt_id`。不能把 worker retry 误记成新的规划，也不能把实际重算隐藏在旧 attempt 下。

```rust
let observed = handle.observe_generation().await?;
let attempt = plan.plan_advance(&observed, contributions, step)?;
let charge = attempt.planning_cost;
match attempt.result {
    Ok(planned) => match planned.request {
        Some(request) => {
            let original_digest = request.digest()?;
            let result = handle.step_planned(
                observed.owner_checkpoint(), charge.clone(), request.clone(),
            ).await;
            // 保留 request、charge、original_digest 和 result。
            // 未知只查原请求；先对账，不以新身份绕过未决 / 冲突。
        }
        None => {
            handle.record_cost(charge).await?;
            // abstain / tie：无 worker 请求；由既有控制流程继续或停止。
        }
    },
    Err(error) => {
        handle.record_cost(charge).await?;
        // 评价失败费用已保留，再把 error 交给既有控制流程。
    }
}
```

以上外层 `plan_advance` 前置拒绝尚未进入评价阶段；内层 `attempt.result` 才是带计时费用的尝试结果。若 `record_cost` 或整个调用的回执丢失，必须读回相同 event ID 与内容；没有回执不能推定零成本，也不能无条件重新执行 planner。planner 本身是纯组合器，不是新的 durable attempt owner；进程在返回费用前退出的测量仍是未知覆盖。

### 4.4 STOP、outbox、取消与重开

STOP 也是显式候选，经 NDU 建议和原 worker 执行后由 journal 结算。若存在 outbox，使用原交付路径发送或查询精确 chunk。只在获得实际 ACK 及对应交付成本事实后调用：

```rust
let chunk = handle.pending_output().await?.ok_or(missing_chunk_error)?;
// 既有 transport 按 chunk 的 operation/request/offset/bytes 执行或读回交付。
// acknowledgement 和 delivery_cost 来自其实际回执，不能在此合成成功。
handle.acknowledge(chunk, acknowledgement, delivery_cost).await?;
let terminal = handle.observe_generation().await?;
let support = frozen.outcome_evidence(&terminal)?;
```

未知交付保持 outbox；重启后只能恢复相同 chunk。`drain()` 会关闭新 admission，pending 计算及未 ACK 输出仍须对账，返回 false 不是失败结果可丢弃的理由。取消用 `cancel(original_request_digest)`，随后仍读回原任务。重开使用原 config / journal / witness / control；已经成功的 STOP 原请求重放返回原 receipt，不重新运行模型。

### 4.5 独立观察、credit 与后续候选

将 `support.support_digest()`、不可变输出及成本缺测信息交给既有独立 observer。它根据冻结评价 profile 观察实际结果，在签名前填入正确 `episode_id`、support 和 `unit_profile_digest`，自行生成真实 value / terminality / correction lineage。不要修改已经签名的 outcome 字段。

```rust
// signed_request: ObservedOutcomeRequestV2，来自独立 observer 的真实签名。
// 旧 API 中 run_id 指 Decision record ID，因此必须等于 frozen.decision_id。
let outcome_receipt = append_generation_outcome_v1(
    &mut ledger, &frozen, &terminal, signed_request, now,
)?;

// credit_batch / credit_evidence 来自既有独立 credit 流程，并满足守恒。
let credit_receipt = ledger.append_credit_batch(
    outcome_receipt.chain_digest, credit_batch, &credit_evidence, now,
)?;
```

若 outcome 已写入而 credit 失败，保留 outcome receipt，重试相同身份进行对账，不能重新 dispatch episode。后续 dataset freeze、训练候选、独立 evaluation 与版本选择复用现有 learning ledger / artifacts / plasticity 接口。这个 bridge 不会因 outcome 有值而自动训练或采用新参数。

## 5. 实际通过的 16 项新增测试

下表 16 项在最终同源 JUnit 中均**唯一出现并通过**；没有 missing、重复或 ignored 项。其 `(binary_id, test_name)` 与同源完整 nextest 清单逐项匹配，详见 [final-analysis](evidence/native/final-analysis.json) 和 [最终原始 JUnit](evidence/native/records/formal-61921427-tests-rebound/junit.xml)。

| # | 测试名称 | 必须观察的行为 |
| --- | --- | --- |
| 1 | `pending_cancel_reopen_stop_and_ack_gate_complete_task_cost` | 完整旧小计遇到新 pending 不能成为完整 episode 成本；取消、重开、STOP 与 ACK 的状态/费用边界正确 |
| 2 | `uncertain_owner_never_mints_an_observation_before_witness_recovery` | 提交/witness 不确定时拒绝 owner observation，恢复后才可导出 |
| 3 | `first_adopted_input_is_rebuilt_without_promoting_failed_or_cancelled_initialization` | 只有实际采用输入进入 first-advance 身份，失败/取消不冒充 Init；重开保持一致 |
| 4 | `owner_terminal_and_delivery_cut_precedes_independently_signed_outcome` | pending、未 ACK 拒绝 outcome；真实 journal 结算后独立签名写入，重开与账本重放不重复 |
| 5 | `frozen_versions_and_actual_owner_initial_state_cannot_be_substituted` | 所有冻结版本漂移及相同 task 声明下的真实初态替换被拒绝 |
| 6 | `signed_decision_must_bind_the_exact_frozen_contract` | 即使签名合法，错误 run snapshot、policy 或 decision support 也不能接入 |
| 7 | `signed_outcome_must_bind_the_owner_cut_evaluator_and_observer` | 错误 cut、评价 profile、observer 身份或签名拒绝，账本不改变 |
| 8 | `explicit_ndu_stop_reaches_existing_owner_and_keeps_planning_charge_on_reopen` | 真实 NDU evaluator 选显式 STOP，经既有 journal 提交和 ACK，规划费用跨重开保留 |
| 9 | `pending_work_and_stale_prediction_cuts_are_refused_before_planning` | 未决计算、旧预测 cut、不完整候选集合不能得到可提交建议 |
| 10 | `frozen_sampler_and_policy_drift_cannot_build_joint_requests` | seed、sampler 和 profile 变化不能构造冻结合同下的请求 |
| 11 | `abstention_or_tie_does_not_become_an_unrecorded_worker_auto_action` | abstain / tie 没有请求，仍返回规划计量，不转成 worker Auto |
| 12 | `actual_init_cannot_silently_change_the_frozen_sampler_even_after_reopen` | 旧通用入口写入不同真实 Init 后，新 composer 在重开后仍拒绝 |
| 13 | `failed_planning_attempts_are_charged_separately_and_recorded_attempts_are_not_recomputed` | 不同失败尝试分别计费；已记录 attempt 不重新计算 |
| 14 | `owner_observation_rpc_retains_unknown_work_cost_and_delivery_across_reopen` | 普通 Agentd RPC 保持原请求、成本、outbox 和 owner cut，未知状态跨重开不丢失 |
| 15 | `planned_step_rejects_changed_cost_cut_and_replays_only_exact_recorded_work` | stale / expired / conflicting 请求保留合法实际规划成本且不派发；原请求、原成本的精确重放仅查询原计算 |
| 16 | `frozen_ndu_plan_executes_real_joint_worker_and_exports_settled_episode` | 编译出的真实 Joint helper → 普通 Agentd → 显式 shared/STOP → outbox → 重开 → ACK → episode evidence，输出读回与规划费用对应 |

测试源码分布：[Neuron 3 项](../../codex-rs/hepta-neuron/src/cell_generation_observation_tests.rs)、[episode 4 项](../../codex-rs/hepta-intelligence/src/generation_episode_tests.rs)、[Joint planner 6 项](../../codex-rs/hepta-intelligence/src/joint_generation_plan_v1_tests.rs)、[Agentd observation / planned-step 2 项](../../codex-rs/hepta-agentd/src/neuron_generation_observation_tests.rs)、[真实 helper 1 项](../../codex-rs/hepta-agentd/src/neuron_generation_joint_tests.rs)。

第 16 项使用合成模型 fixture，但执行真实编译 helper、控制、journal 和输出协议。其 utility / feasibility 是可解释的固定测试输入，不是学习出来的真实任务效用。该 case 终止于 `outcome_evidence()`；真实 LedgerWriter 的独立签名 append 由第 4–7 项的另一组测试覆盖。即使两组在相同 source SHA 上通过，也不能把它们表述为同一个 case 中“真实 worker 生成 → 独立签名质量观察 → 学习更新”全程成功。

继承候选中的 historical trained Joint 生命周期测试是另一项资产回收验证，不能替代该新路线的真实任务质量和净收益实验。

## 6. 原生验证结果与保留证据

### 6.1 固定源码上的实际结果

执行源码为 `61921427dc19223fd8c9d0ded1a4723b255c5df5`，tree 为 `31d99be67393619aca47436d82f9dca909cba359`。正式检查、两轮测试和只枚举 metadata 的步骤均记录该来源，工作树前后干净。工具链为 Rust / Cargo 1.96.0、Just 1.45.0、Nextest 0.9.146，主机为 ai395 / x86_64 Linux；使用默认 features 和仓库原有 `local` profile，没有调整优化、debug、超时或 ignored 规则。

| 包 | 顶层枚举 | 执行并通过 | 既有 ignored 在顶层跳过 |
| --- | ---: | ---: | ---: |
| `codex-hepta-agentd` | 718 | 652 | 66 |
| `codex-hepta-infer-worker-host` | 54 | 54 | 0 |
| `codex-hepta-intelligence` | 95 | 95 | 0 |
| `codex-hepta-neuron` | 181 | 181 | 0 |
| **合计** | **1,048** | **982** | **66** |

最终 JUnit 的 982 个唯一 testcase 与完整清单的 982 个 selected 集合精确相等。XML 中没有 failure、error、skipped 或 flaky / rerun 子元素，原日志中也没有 RETRY / FLAKY / FAIL；`1 slow` 是慢测试标记。66 项全部是 Agentd 中已有的 `ignored=true` / `filter-match.reason=ignored`，没有其他名称过滤。部分 ignored 是由父测试调用的子进程入口，其余包括明确要求 Root、GUI、外部模型或专门资格环境的测试；它们不作为本轮顶层 PASS 计数。完整名称与源码原因见 [skip 清单](evidence/native/records/formal-61921427-test-inventory/skipped-tests.json) 和 [ignore 原因](evidence/native/records/formal-61921427-test-inventory/ignored-source-reasons.json)。

| 正式阶段 | 实测 wall | 结果 |
| --- | ---: | --- |
| 三个修改包 `just fix` | 34.303 s | exit 0，源码未变 |
| 四包 `cargo clippy --tests … -- -D warnings` | 106.139 s | exit 0，源码未变 |
| 仓库 canonical Joint helper builder | 148.093 s | exit 0，保留真实 Cargo compiler-artifact |
| Agentd normal-bin build | 7.304 s | exit 0，保留真实 Cargo compiler-artifact |
| 首轮四包 `just test` | 285.461 s | 982 PASS / 66 ignored，保留首次报告及后续产物差异 |
| **最终同范围暖 `just test`** | **60.549 s** | **982 PASS / 66 ignored；实际双 helper 前后身份相同** |

最终命令为：

```bash
just test --locked --offline \
  -p codex-hepta-neuron \
  -p codex-hepta-intelligence \
  -p codex-hepta-agentd \
  -p codex-hepta-infer-worker-host
```

命令 wall 包含构建或启动等阶段；最终 nextest 测试执行本身记录为 58.807 s。没有把 wall 换算成 CPU。child rusage、能耗和完整历史费用未测，仍为 unknown，不能折算成零。

### 6.2 真实产物与必要的第二轮验证

首轮测试编译期间 Cargo 重链了 Agentd normal bin：预构建摘要 `60ef211d…` 变为实际 test-profile 的 `16fa27fe…`，Joint helper 未变。原来仅在命令开始前核对 helper 的证据不足以覆盖这个变化，因此第一次 982 PASS、原 manifest、导出时的失败诊断和修改时间全部保留。

随后用同源、同包选择的 `nextest list --cargo-message-format json` 获取真实 test-profile compiler-artifact，仅枚举而未执行测试体；建立独立 rebound manifest，再执行一次相同的四包测试。最终 runner 同时核对执行前后的 hash、mtime 和 size，完全一致。没有重跑 fix / fmt，没有改变测试 profile、源码或范围。

| 真实 helper | 最终 SHA-256 |
| --- | --- |
| `hepta-joint-propose` | `1f7ebc34b814fd0264fe1158f1cc4a67a87d609bc50a6e398f8b72b76229134a` |
| `codex-hepta-agentd` | `16fa27fe6b985d0b332bedb2db1a17f63412cac3dcf6261066d4207dd3a7d51a` |

最终 JUnit SHA-256 为 `716be7504d72801992de962dbad5b2c108a9434ea9d93569a07b64c12f47cadd`。实际报告在 workspace 的 `codex-rs/target/nextest/local/junit.xml`，与构建用的独立 `CARGO_TARGET_DIR` 不同；首次收集路径修正独立记录，未改写原 receipt。最终报告 mtime 晚于本次运行开始，UUID 与首轮不同，完整 testcase 集合相同。

### 6.3 可追溯的原件

| 证据 | 原件与结论 |
| --- | --- |
| 汇总与源码对应 | [STATUS.json](STATUS.json)、[SOURCE_BINDING.json](SOURCE_BINDING.json)；后续证据提交不冒充实际执行源码 |
| 完整文件清单 | [DELIVERY_INVENTORY.json](DELIVERY_INVENTORY.json)；覆盖本目录除自身外的全部交付文件 |
| 最终运行 | [receipt](evidence/native/records/formal-61921427-tests-rebound/receipt.json)、[stdout](evidence/native/records/formal-61921427-tests-rebound/stdout.log)、[stderr](evidence/native/records/formal-61921427-tests-rebound/stderr.log)、[fresh JUnit](evidence/native/records/formal-61921427-tests-rebound/junit.xml) |
| 工具链、host 与最终资源快照 | [final-environment](evidence/native/records/final-environment.json)；资源快照不代表单任务 CPU / 能耗 |
| 实际 helper 与原始编译记录 | [rebound manifest](evidence/native/records/rebound-helper-manifest.json)、[test-profile Cargo output](evidence/native/records/formal-61921427-test-profile-artifacts/stdout.jsonl)、[原 Joint Cargo output](evidence/native/records/formal-61921427-joint-helper/helpers/codex-hepta-infer-worker-host.jsonl) |
| 实际执行 runner | [native-command-v3.py](evidence/native/native-command-v3.py)；源码身份、实际产物、fresh report 前后核对 |
| 完整测试清单与逐项统计 | [nextest-list](evidence/native/records/formal-61921427-test-inventory/nextest-list.json)、[final-analysis](evidence/native/final-analysis.json) |
| 原始远端导出包 | [native evidence archive](evidence/native/native-evidence-final-61921427.tar.gz)，565,660 bytes，SHA-256 `5471d536faea84afd7c9a4561f2ac7a24b3082cf3670308662d3613b750cf806`；其 88 份原文件逐项匹配 [原 inventory](evidence/native/evidence-inventory.json) |
| 功能及独立学习事实 | 固定源码 + JUnit 证明相应断言实际执行；新增用例中的临时 journal、prefix / ACK、签名账本与回执原件未单独留存，不宣称它们已作为独立产物提交 |

历史准备中稀疏 checkout 缺 docs、旧 `27928bf8` 自动修复使工作树变脏，以及首次 Agentd helper 重链诊断均保留，没有覆盖成成功。原始准备源码与本轮资格源码区分，不能继承或转移旧 run 资格。

## 7. 本轮没有得到的结论

本轮不能证明生产可用、40 模块全部合格、完整 GPU/CPU/energy 成本、NDU 相对强基线净收益、生成内容质量提升、跨机规模收益、全局指令或策略最优、自动持续学习采用，也不能证明所有 caller feasibility 声明真实、整个历史只使用冻结策略，或单一 case 已连通真实 worker 与独立签名学习闭环。

仍需在相同任务信息、模型、输入、预算和评价版本下比较普通强基线与 NDU 控制，保留失败、取消、未知、队列、规划、编码、推理、持久化、传输、评价和训练成本。已知成本是下界；缺测、未决或进程丢失不能折算成零。独立 observer 的事实与候选评价通过前，不升级版本采用状态。

当前成功输出的 episode bridge 要求 STOP + 无 pending + 已 ACK。取消或失败后的非 STOP 终局、独立 durable planning attempt 准入与进程丢失恢复、真实全局资源分配和更完整的 backend 合法性来源仍需各自的原 owner 路径和实际证据；本说明不将这些缺口计为关闭。
