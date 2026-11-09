# 下一次真实私有 head 实验：owner 装配依赖审计

状态：**审计与未执行计划**。本文件没有执行模型训练、安装 owner、签发资格或发布权重。

## 1. 审计范围与源码身份

- 基线为 `hepta-private-ci@e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5`。
- scoped V2 的对照原件固定在 `7ee86741ea3da28de9528ae173cd5f76caa77bda`；历史运行结果不替代新装配的验证。
- 本轮 Cell 恢复桥已提交 [#5539](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5539)，固定代码 `bc6b9ff0a6436c5aacc3a3f0fb1edca7b5dd115b`；原生验证见同目录 `README.md`。它增加 Cell 对 Product 签名结果恢复的调用，没有建立完整学习 owner 装配。
- 结论仅适用于上述源码及下列固定 PR 原件，不表示其它分支、机器或后续提交没有进展。新证据需要按其实际源码与 owner 身份重新核对。

## 2. 先整合评价 profile，再整合 scoped V2

`e2e20033` 的 `LearningIterationRequestV1` 没有预冻结 `evaluation_profile`；Evaluation 校验匹配的是候选 lineage 中的 profile。普通装配应先获得请求级的原 owner 预注册约束。[基线类型与校验][iteration-types] [#5357 原件][profile-pr]

| 依赖 | 已核实的作用 | 集成时必须保留 |
|---|---|---|
| #5357，固定 head `36d5eff44f4071bb1f250b1c7706dc690cf0a875` | 在原 request 中冻结非零 evaluation profile；Training 与 Evaluation 都必须匹配；升级为 HEPLCP02。 | 旧 HEPLCP01 不得靠推断字段或重写取得新资格；恢复仍绑定原 operation、预算和期限。 |
| #5419，`eba4601966388af65f811d31077fabd00886e4e1` | `FrozenLearningScopeV2::freeze` 冻结完整 request、owner 集合、Cell/Organ 范围和 update rule。 | scope 是组件身份约束；仍需实际 tensor/material 校验，不能单靠声明证明冻结底座。 |
| #5420，`d81cb97c5b01aea0df03d84d40336b25576337de` | scoped channel、schema-2 checkpoint owner 与运行/恢复阶段的 scope 校验。 | 后来的 NoUpdate 不得追认此前越界候选；V1/V2 checkpoint 不得静默互换。 |

来源：[profile PR][profile-pr]、[scope PR][scope-pr]、[scoped runtime PR][scope-runtime-pr]、[固定 scoped V2 合同][scope-contract]。这些分支与当前 Root 栈存在接口差异，不能把研究测试原样当成普通 host caller。

## 3. scoped V2 与当前 Root 接口的具体差异

| 当前基线文件/接口 | 当前绑定 | 下一项代码工作 |
|---|---|---|
| `authority_host_learning_registration.rs::learning_store` | 使用 `vacant` / `from_registered` 的 V1 owner。 | 增加明确的 scoped 注册/重开选择，使用原 scope 的 `vacant_scoped_v2` / `from_registered_scoped_v2`；不重新注册旧 operation。 |
| `learning_iteration_checkpoint_transport.rs` | 请求/响应 schema 为 1，binding 使用 `initial.head_digest`。 | 在有版本区别的 wire contract 中传递并核对 scoped binding；scope 改变、降级或错误 schema 必须拒绝。 |
| `learning_iteration_checkpoint_ports.rs` | 将原 Root checkpoint capability 与 `LearningIterationStageOwnerPortsV1` 组合。 | 保留原 writer/独立 anchor；将原 scope binding 一致地传给 scoped owner ports，不能由 stage adapter 自报取代 Root 证明。 |
| `root_production_learning_inputs.rs::into_learning_runtime` | 调用 `learning_iteration_channel_v1` 并安装 Circuit learning delivery。 | 新的 scoped 入口必须消费同一 Root handoff、原 request/owners/verifier，并走 `learning_iteration_channel_scoped_v2` 的检查。 |

上述四个文件均在 `codex-rs/hepta-agentd/src/`。[Root 注册][root-registration] [Root transport][root-transport] [Root 输入][root-inputs]

`config_root_learning.rs::with_root_learning_stage_owners` 是现成装配入口，但基线生产源码没有实际 `LearningIterationStageOwnerPortsV1` 实现。`main.rs` 也没有该装配调用。[装配接口][root-config]

## 4. 现有 trainer 与“只更新一个私有 head”不等价

| 已核实实现 | 实际范围 | 首个 head 实验仍需完成 |
|---|---|---|
| `hepta-agentd/src/terminal_learning.rs::AgentdTerminalLearningOwnerV1` | 从已授权 Ledger/Memory 源执行 tabular terminal-value fit；不是 Cell compatibility bundle，也没有普通 optimizer steps。 | 不能把表格拟合计为私有 linear/low-rank head 训练。其 source/withdrawal 复核可作为接入参考。 |
| `scripts/ndu_real_runtime/training.py` 的 frozen 模式 | 冻结 content，但训练 utility、transition、duration、light 多个 auxiliary heads。 | 需要精确单 head 参数白名单、普通优化器、uniform replay，以及所有未选参数前后相等的材料证据。 |
| scoped V2 的 `neuron_generation_real_learning_tests.rs` | 研究 harness 更新 SmolLM 的 LoRA `cell_adapter`，使用外部模型/driver 文件。 | 不能直接称为单 head；需实际私有 head trainer、原预算、候选材料校验和与普通任务的接线。 |

来源：[终端学习][terminal-learning]、[NDU trainer][ndu-training]、[固定 scoped V2 原件][scoped-evidence]。研究 driver 的模型文件不随该证据包完整提供。

原 archive index 给出的绝对目录为 `/home/qq/hepta-scoped-v2-20261109-d81cb97c`，含 `native-no-update-v1/model-config.json` 和 `model/frozen.json`。对 desktop 的这些精确路径只读检查返回 `/home/qq` 不存在；没有据此断言其它已授权 host 上也不存在，也未猜查其它目录或启动训练。[原文件索引][scoped-index]

## 5. NoUpdate 不免除原 authority

`learning_iteration_auth.rs` 对负结果同样要求：Evaluation 与 Training 分离；Selection 与 Training/Evaluation 分离；NextUse 与 Training/Selection 分离。签名必须通过原 trust、当前时间、主体及目标绑定。[原认证路径][iteration-auth]

NoUpdate 跳过候选 Proposal，但仍进入 Selection 和 NextUse。后者必须证明同一 principal/agent/cell 的不同任务实际使用原 baseline，不能用“没有安装候选”推断下一任务已经完成。[协调器状态机][iteration-state]

scoped 研究 trust 明确由一个 operator 控制所有角色，并按 operation/role 构造测试 keys 和 controller 标签。它证明机制调用，不证明真实独立保管；不可复制成生产 owner。[研究 trust][research-trust]

## 6. 真正装配需要的外部输入与可写代码

| 环节 | 可复用代码 | 必须由原 owner 提供的真实输入 |
|---|---|---|
| Experience / Dataset | `append_neuron_generation_outcome_v1`、原 `LedgerWriter::freeze_dataset`、source/withdrawal 复核。 | 已完成普通任务与实际 outcome、训练用途授权、原签名 dataset cut；不能由训练器自己补标签或授权。 |
| Training | 原预算/operation 约束和 scoped 验证；需要新增实际单 head trainer adapter。 | 已选底座/head 材料、固定参数白名单、原训练 job 身份与完整成本；不确定结果必须对账原 job。 |
| Evaluation | `CellEvaluationRunnerV1`、本轮 Product signed execution readback、原 qualification sink。 | 未向 trainer 暴露的 holdout provider、原 fenced consume owner、原 evaluator 签发 capability、当前 verifier/clock。 |
| Selection / NextUse | `prepare_agentd_generation_same_model_task_v1`、published generation 的 selection/next-use readback。 | 当前 baseline selection、原 FinalUse/CURRENT、独立 witness、不同下一任务及其已提交 use receipt。 |
| 普通 caller | `with_root_learning_stage_owners`、`with_circuit_task_bootstrap`。 | 原 Circuit input/invocation providers、AuthBus/objective/replay 配置，以及实际 governed plasticity owner。 |

`runtime.rs` 即使最终 NoUpdate 也要求学习 bootstrap 配有 governed plasticity；Root delivery 另要求 Circuit profile。当前 Root launcher 的 primary 是 Android/Notes/Desktop，Notes/Desktop 的有限任务 profile 与 Circuit 不兼容。应做明确的普通 Circuit host 装配，不能删除这些校验来让实验启动。[Circuit 配置][circuit-config]

## 7. Cell 恢复桥之后的最小 typed bridge

建议下一切口是“已签发 qualification → 原 iteration Evaluation observation”，而不是再增加可填写 `qualified=true` 的描述文件。

1. 消费 sealed `CellEvaluationQualificationV1` / `ProductQualificationReceiptV1` 和原完整签名证据，调用 `revalidate_product_qualification_v1` 重新核对当前 trust/time。
2. 绑定原 iteration operation/predecessor、候选与 baseline manifest 的完整 bundle digest、原 Training receipt，以及预冻结 evaluation profile；不能只匹配 candidate 名称。
3. 对实际 `Ineligible` 或 `InsufficientEvidence` 产生保守 NoUpdate observation；缺少签名、失效 authority、未知持久化状态仍返回错误，不能当成已完成的 NoUpdate。
4. 将 observation 交原 evaluator 对既有 `learning_iteration_receipt_signing_bytes_v1` 签发；qualification 的签名不能直接冒充另一 signing domain 的 stage attestation。
5. 沿原 Selection → RetainedModelNextUse 完成不同任务消费；恢复重读原 evidence 与 publication，不重放 holdout 或更新任务期限。

预计此桥可按约 100–180 行生产逻辑及 150–220 行定向测试独立审查；这是设计估算，尚未实现或验证。必须先补 profile 预冻结与真实 owner 输入，不能宣称写出 bridge 就完成实验。

[iteration-types]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-learning-artifacts/src/learning_iteration_types.rs
[profile-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5357
[scope-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5419
[scope-runtime-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5420
[scope-contract]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7ee86741ea3da28de9528ae173cd5f76caa77bda/codex-rs/hepta-agentd/SCOPED_LEARNING_V2.md
[root-registration]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/authority_host_learning_registration.rs
[root-transport]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/learning_iteration_checkpoint_transport.rs
[root-inputs]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/root_production_learning_inputs.rs
[root-config]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/config_root_learning.rs
[terminal-learning]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/terminal_learning.rs
[ndu-training]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/scripts/ndu_real_runtime/training.py
[scoped-evidence]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7ee86741ea3da28de9528ae173cd5f76caa77bda/codex-rs/hepta-agentd/acceptance/2026-11-09-scoped-learning-v2/README.md
[scoped-index]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7ee86741ea3da28de9528ae173cd5f76caa77bda/codex-rs/hepta-agentd/acceptance/2026-11-09-scoped-learning-v2/actual-scoped-runs.index.json
[iteration-auth]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/learning_iteration_auth.rs
[iteration-state]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-learning-artifacts/src/learning_iteration.rs
[research-trust]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7ee86741ea3da28de9528ae173cd5f76caa77bda/codex-rs/hepta-agentd/src/neuron_generation_real_learning_trust.rs
[circuit-config]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5/codex-rs/hepta-agentd/src/config_circuit_task.rs
