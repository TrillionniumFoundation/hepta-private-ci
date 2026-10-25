# 原生 owner、学习账本与真实部署交接

## 本轮实际到达的边界

本轮对固定历史输入执行原始 `NeuronRuntime` 的完整 1,600-tick 连续流。在新登记的动力学配置下，800 个 ID tick 获准，800 个完整缺失 tick 弃权；同一个 subject/objective 跨 13 个 journal 分段，完成 12 次 rollover。流在 sequence 800 首次符合注册条件的 ID anchor 上暂停，实际调用原生 owner resolver、候选生成器及提案持久化接口，再从同一 anchor 恢复继续至 1,600，连同预定的中途及最终恢复共完成三次恢复。完整结果见 [LIVE_OLD_PREFLIGHT.json](LIVE_OLD_PREFLIGHT.json)，该文件属于旧的 508→32 当前输出正确率头，不能用来声称新未来预测头已经执行同一条链。

原始 `resolve_agentd_plasticity_admission_v1` 的实际拒绝顺序是：

| 调用时的真实材料 | 实际第一结果 | 可以得出的结论 |
| --- | --- | --- |
| 空 research ledger，真实 artifact registry | `ArtifactBinding` | 非零资格 frontier 尚未提供 |
| `Incomplete` 的 singleton head 执行记录 | `Semantic(IncompleteCandidateSet)`，发生于原账本 append | 尚未到后续 Dataset owner；不能说它已经检查失败 |
| 显式 `Complete` 的 singleton head 执行记录 | `Semantic(MissingAbstainCandidate)`，发生于原账本 append | 原 ledger 契约还要求 reserved `abstain` |
| 真实已完成 tick 的二元 gate `{admit_neuron_signal, abstain}`，选择直接来自保留的 `tick.abstain`；随后保留同 context 的真实上游观测 | 两条原 V1 记录实际追加、恢复；产品调用返回 `OwnerEvidence(Unavailable)` | 本次首次到达 Dataset owner 查询；当前 resolver 未接入此权威 owner |

最后一行来自另一个独立的 observed-history 诊断，其真实账本 head 为 `a70441ffafb78651ed767d8974b313e4499bb23908589fd25c03576dae6ad2fd`，绑定旧 head 在 sequence 1,600 的 native anchor `458994a90ee8b1049b3574cd10ab0f4d252fa1ec5d77d65503b0bedf2ffa6c1c`。该 head 来自两次实际追加及原 API 的 acknowledged recovery，未任意填写非零 digest。[OBSERVED_HISTORY_RESULTS.json](OBSERVED_HISTORY_RESULTS.json) 保留了这个 head、context digest、记录数量及两个产品调用结果；它与 live smoke 在 sequence 800 暂停的证据分别保留。

这个二元决策边界只覆盖一个**已经完成**的 native tick 的信号发布门。它不覆盖 bootstrap/model-execution error，不证明 head 选择、生成动作或 plasticity 候选空间完整。确定性 propensity=1 是给定完整已执行上下文的条件概率。随后的 utility 来自此前的真实生成结果，**不是本次 head 调用造成的收益**；没有生成 credit batch 或声称因果收益。

这些是 `qualification-legacy-write` 下原 `DurableLedger::append_qualification` 的无签名研究记录。它们没有激活正式根信任，没有 Generator/Observer/Evaluator 签名，没有独立 DatasetSnapshot owner，也没有获得更新应用权限。研究账本的非零 head 与正式生产资格不能混同。

`OwnerEvidence(Unavailable)` 是本次真实第一 owner 边界。它不是“所有后续检查都已失败”，也不证明其他部署环境不存在合格材料。原 resolver 在检查完 ledger/artifact 绑定后首先查询 Dataset；本轮接入的动态 resolver 只提供 NDU、eligibility、broadcast 和参数信号。

## 原生产写入 API 的可调用路径

本轮执行的 core 源保持在原固定 ref [`9595221c21f1fe0775295a9c8756a1ba4d69ea49`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9595221c21f1fe0775295a9c8756a1ba4d69ea49)。`hepta-learning-ledger/src/trust_distribution.rs` 与 `production.rs` 明确提供以下正式路径：

```rust
// 输入来自既有部署 authority；示意调用顺序，不生成测试身份。
let trust = activate_learning_trust(
    &host_pinned_root,
    root_signed_distribution,
    previous_activated_trust.as_ref(),
    now,
)?;
let mut writer = LedgerWriter::from_durable(
    durable_ledger,
    independent_witness,
    trust,
    &ledger_directory,  // 已打开目录的 std::fs::File。
    &witness_directory, // 独立 witness 目录的已打开 File。
)?;
let decision = writer.append_decision(
    actual_predecessor,
    actual_production_decision,
    &generator_signed_evidence,
    now,
)?;
let outcome = writer.append_outcome(
    decision.chain_digest,
    actual_independent_observation,
    &observer_signed_evidence,
    later,
)?;
// 按所声明学习任务补齐真实 lineage/credit/frontier，再冻结实际 dataset。
let dataset_receipt = writer.freeze_dataset(
    actual_freeze_plan,
    &evaluator_signed_evidence,
    frozen_at,
)?;
```

`activate_learning_trust` 验证 host 固定根公钥、根签署的 signer distribution、scope、有效期及单调 rotation。`LedgerWriter` 不接受随意构造的裸 signer list 作为正式信任。`append_decision` 验证 Generator 角色及其完整候选契约；`append_outcome` 验证 Observer 签名和与 Generator 的独立性；`freeze_dataset` 验证 Evaluator 角色并从实际 ledger snapshot 派生 receipt。真实部署应让已有角色服务签署事实，不向报告或 agent 提供私钥。

本轮没有用研究记录冒充 `AuthenticatedDecisionV2`、`AuthenticatedOutcomeV2` 或正式 evaluator 签名。即使本地可以构造这些 Rust event/record 值，这也不能替代上述来源和信任证明。

## 仓库已有的 process bootstrap 入口

另外对远端源码做了只读审计，固定在较新的 [`f8c9419df6ddeb36ff8b522a50219981fb8d9345`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f8c9419df6ddeb36ff8b522a50219981fb8d9345)。这不是把本轮执行切换到新 main；22-crate 实际实验仍使用前述原固定 core。

该 ref 的 [`plasticity_process_bootstrap.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs) 已实现 `load_plasticity_process_bootstrap_v1(path, expected_descriptor_digest, identity)`。Git blob 为 `f44c8858a55886c7997562a02ba87b9a7d359bf2`。[`main.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/codex-rs/hepta-agentd/src/main.rs) 的 blob 为 `60595420f4bf42089b5745830ac611df1c7ec2c2`，实际接受这两个成对参数：

```bash
# 在已有合格 Agentd identity / generation 环境中运行。
codex-hepta-agentd \
  --plasticity-bootstrap-descriptor "$HEPTA_PLASTICITY_DESCRIPTOR" \
  --plasticity-bootstrap-descriptor-digest "$HEPTA_PLASTICITY_DESCRIPTOR_SHA256"
```

Descriptor schema 是 `hepta.agentd.plasticity-bootstrap.v1`。它不是“填一个非零 frontier”的开关；loader 逐项恢复和校验下列真实输入。

| Descriptor 字段 | 必须提供的真实材料 / 原生检查 |
| --- | --- |
| `agent_id`, `spawn_generation`, `objective_digest` | 与 host identity、generation、任务 objective 一致 |
| `artifacts` | 实际 artifact registry snapshot、独立 receipt 中的 binding/head/file digest/record 数，update-rule、mutation-policy、broadcast artifact ID 与生产者 |
| `ledger` | 实际 ledger 文件、binding、容量与独立 acknowledged sequence/chain digest |
| `dataset` | 外部真实 owner 从 ledger 派生的 `DatasetSnapshotReceiptV3`：snapshot/source-record digests、eligible frontier、outcome watermark、producer principal、correction/revocation cut、inclusion policy；loader 在此验证 receipt 自洽及 ledger head 一致 |
| `ndu` | 实际 projection journal、subject/objective、owner 与真实 modulator 值 |
| `neuron` | 实际 journal、独立 acknowledged anchor、原 `SparseConfig`、subject/objective；这个固定 loader 的 descriptor 显式只接收单一 journal，未展示本轮跨段链的恢复组合 |
| `signal_bindings` | layer/parameter/eligibility-index 与 modulator weights 的显式映射 |
| `trust` | host 选定且 digest 固定的真实 principal/controller/verifying-key/role/epoch/scope 信任描述 |
| `owner_policy` | Dataset、规则、NDU、broadcast、eligibility、signal、mutation-policy 的真实 owner identity，与相应材料 producer 一致 |
| `parameter_registry`, `topology_registry` | 正式 registry 与独立 anchor store；明确 `bootstrap_new`、`resume_unacknowledged` 或 `reopen_anchored` |

Loader 拒绝 descriptor byte substitution、错误 identity/generation、mutable path alias、损坏或缺失的 acknowledged history。恢复失败不能回退为一个新的空 registry。这个新 bootstrap 中的 verifier 来自**host 固定的 descriptor 信任输入**；它不能被误称为已经运行了前一节的根签署 distribution 激活。正式 ledger 生产者仍应走 `LedgerWriter` 的信任路径。

这里有两个不能省略的范围限制。首先，固定 loader 从 descriptor 构造 Dataset receipt，检查 `verify_dataset_snapshot_receipt_v3` 和 recovered ledger head；它没有在此调用 `verify_dataset_snapshot_receipt_against_ledger_v3`、从 ledger 重建 source records 或验证 Evaluator 签名。真实生产派生及签署来源仍须由前述 `LedgerWriter` 流程提供。其次，这个固定 descriptor 只有单一 `journal_path`，loader 直接调用 `SparseJournal::open_anchored`，未展示本轮 13 段、sequence 802/1,600 的完整 chain 恢复路径。不能仅补一个外部 bundle 就声称本轮同 anchor 可直接导入，也不能把长链裁成一个新的空 journal。完整段链恢复接口和产品组合是另一项必须实际完成的部署工作；本轮研究 driver 已通过原 segment-chain API 恢复自己的真实链，两者范围不同。

## 本轮新增的完整段链适配交付

针对上面的单 journal 接口不足，已在独立的 [production_handoff](../production_handoff/README.md) 交付 exact-base bootstrap patch 和 `neuron_chain_recovery.rs`。目标固定为同一 `f8c9419…` loader blob；原 single-file descriptor 保持兼容，新表示显式提供按顺序排列的 `segment_chain`，拒绝与旧字段混用、空 chain、缺段、错序、路径及 inode alias。所有段加入原 mutable-owner 路径分离检查；最后一段使用 anchored recovery，并再次要求最终 sequence/digest 精确相等。

新增 helper 与独立 probe 已实际编译执行，依赖本轮固定 `9595221…` 的原 journal rlib。验证使用已经完成的新 future head 流的 13 段**副本**，恢复到 sequence 1,600，最终 anchor `f0d9280bf614d3b27572e1ce9806d26f39541b3310b2e4f08967de12ecef15c2` 及 33 维 eligibility 与真实保留 context 完全一致；旧单文件恢复和 19 项拒绝检查也通过，共 21 项。原 13 段 SHA 均未改变，没有新增 native tick 或统计 N。[CHAIN_RECOVERY_VALIDATION.json](../production_handoff/CHAIN_RECOVERY_VALIDATION.json) 保留每项结果、源/依赖/binary 身份及 exact-base patch 应用检查。

这已经提供可审阅、可执行的最小 chain 恢复适配，超过单纯指出缺少接口。**较新完整 Agentd crate 尚未编译验证，该 patch 尚未合入或部署。** 中间段使用原 API，可能修复不完整尾帧；不能宣称所有失败输入的字节绝不变化。正式 product owner 组合、独立 witness 存储、Dataset 来源、角色签名和 applied-update 资格仍需各自真实材料，helper 的恢复成功不能授予这些权限。

该版本的 [OPERATIONS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/docs/modules/learning.plasticity/OPERATIONS.md) 与 [CURRENT_IMPLEMENTATION](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f8c9419df6ddeb36ff8b522a50219981fb8d9345/docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md) 还指出：`AgentdLearningPlasticityProducerV1` 是命名的产品 producer，但上游 self-iteration/control.engineering coordinator 仍需要产品组合；提交请求必须来自已经冻结、独立评价的候选。proposal 本身不授予 selection、install 或 activation。

## 当前缺少什么，哪些检查尚未到达

本次被提供的研究材料没有与当前 objective/context 绑定的正式 Dataset owner receipt、正式角色签名与既有部署 bootstrap bundle。仓库源码检索找到了上述接口与测试，不产生可用的生产身份。本轮没有读取或探测服务端凭据管理器，也没有把测试 signer 用作生产 authority。

最具体的下一份输入是：**由现有部署 owner 生成、绑定实际 ledger/head/context 的 bootstrap descriptor 及其可信 digest，以及其中引用的真实 owner stores/receipts**。若正式 ledger 尚未产生，则应先让已有 Generator、独立 Observer 和 Evaluator 服务按真实执行事实调用前述生产 API。需要的是服务生成的签名证据与可恢复存储，不是用户口头再次批准研究动作。

当前研究流程实际停在 Dataset owner；其他正式签名、Evaluator 独立接受、daemon 部署、主机独立回滚域、更新应用及后续收益均不能报告为已经通过或已经逐项执行失败。这里给出了可调用入口及每个缺失输入的来源，保留原 gate 的拒绝事实。
