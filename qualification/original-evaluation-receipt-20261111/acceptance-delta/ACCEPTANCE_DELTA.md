# c1d6537：普通学习闭环验收差异

固定 commit：`c1d6537f7d979e1ad792eee796c6709d23a86697`；tree：`e7762b742e6baff12e447a89f40ae1cfb68aa7e1`。工作树 clean；本审计 **0 源码修改、0 测试执行**，不改变普通完整链、正向采用、NoUpdate、rollback 计数。

**结论：前四段仍缺具体生产代码或装配；后两段关键组件已经存在，仍缺普通独立消费与双进程重启证据。** 这些结论均限定当前固定仓库源码及本轮可采纳证据，不推断外部所有 host 的状态。

| 段 | 判定 | 已落地，不能沿用旧缺口说法 | 仍缺什么 |
| --- | --- | --- | --- |
| 普通任务 → 经验 / Dataset | 仍缺具体生产代码/装配 | 普通 Q24 driver、原 source/Cell 输入输出、LedgerWriter 的签名 decision/outcome 与 freeze/read/revalidate 已有。 | 缺普通 A → 原 ledger → 事前冻结的 Q24 input/target materializer 和具体 stage；真实标签、freeze 签名、trust、witness 与任务 profile 必须来自原 host。 |
| 持久 Trainer | 仍缺具体生产代码/装配 | 真实 Q24 SGD、durable claim/heads/NoUpdate、Pending 禁重跑、冷读，以及原 Generator 签名收据 owner 均已有。 | 缺真实 Dataset/batch/rule 与原 Generator custody、evidence 连接和生产 stage 装配；不能再描述为缺持久 Trainer 本体。 |
| 独立 B / holdout / 原收据 | 仍缺具体生产代码/装配 | 冻结 comparison、原两臂执行/恢复、资格落点接口、原 execution attestor 和 learning Evaluation 收据 owner 均已有。 | 缺真实 B/retention provider、holdout/CAS、成本与原 journals、签名/sink custody 和 stage 接线。仓库具体 provider impl 仅见 fixtures；原 receipt owner 不提供评价数据。 |
| Model Proposal / Selector / 发布撤回 | 仍缺具体生产代码/装配 | 新 Model 材料 owner 已有真实 admission/commit/anchor/readback；通用 artifact、selection、CURRENT、FinalUse 与撤回检查也已有。 | 仍缺 Model 生产 payload/dispatch、版本化 Root profile/schema 与原 Proposal 角色 owner 注册/装配、live Dataset/withdrawal/artifact 重验；随后需真实 Selector 输入与普通发布/回滚证据。 |
| 普通 C FinalUse | 代码入口/组件已存在但普通证据缺失 | 已发布 initial/update CURRENT 能进入普通 Q24 driver；Selection/NextUse 从实际 source、private Cell commit 和当前 owner 重读，含保留旧模型分支。 | 需真实 successor task/run、原 publication/FinalUse grant、Selector/Observer 收据和独立普通 C 执行证据。共享 stage 仍待装配；同 actor 不同 run、ACK 或再次读取不能证明独立节点采用。 |
| daemon + Root 真实退出重启 | 代码入口/组件已存在但普通证据缺失 | Root 显式注册/open-only reopen、sealed handoff、进程绑定、原 Feature predecessor ACK 文件恢复与各新 owner 的 recover 均已有。 | 需原 host 让两个真实进程退出，以新 PID/start ticks 重新鉴权并重接原 owners，核对 CURRENT/state/task/uncertain effects。文件冷读或 Root 组件用例不能替代此验收。 |

## 每段最直接的原路径

1. **普通任务 → 真实经验 / Dataset**：[codex-rs/hepta-agentd/src/circuit_q24_task_profile.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/circuit_q24_task_profile.rs)；[codex-rs/hepta-learning-ledger/src/production.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-learning-ledger/src/production.rs)。
2. **Experience / Dataset → 持久 Trainer**：[codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs)；[codex-rs/hepta-agentd/src/cell_q24_training_receipt_owner.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/cell_q24_training_receipt_owner.rs)。
3. **独立 B / holdout / 原 Evaluation 收据**：[codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs)；[codex-rs/hepta-agentd/src/neuron_cell_evaluation_receipt_owner.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/neuron_cell_evaluation_receipt_owner.rs)。
4. **Model Proposal → Selector / 发布 / 撤回**：[codex-rs/hepta-agentd/src/learning_iteration_ports.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/learning_iteration_ports.rs)；[codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs)。
5. **普通 C 从已发布 owner 消费 / FinalUse**：[codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs)；[codex-rs/hepta-agentd/src/neuron_generation_current.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/neuron_generation_current.rs)。
6. **daemon + Root 真实退出 / 重启恢复**：[codex-rs/hepta-agentd/src/authority_host_learning_registration.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/authority_host_learning_registration.rs)；[codex-rs/hepta-agentd/src/circuit_feature_current_recovery.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c1d6537f7d979e1ad792eee796c6709d23a86697/codex-rs/hepta-agentd/src/circuit_feature_current_recovery.rs)。

## CALLERS 与 Model 协议的关键区别

- 当前 `CALLERS.toml` 是 **225 个受控边界、219 个 protected files**；225 不是已执行的生产调用数。本审计只读解析清单，未重跑 scanner。
- Training、Model、Evaluation 三种新 owner 各四个入口仍 `product_callers = []`。`root_learning_original_stage_assembly`、原 evidence-client constructor，以及 Evaluation/Generation 的 learning readback adapter 也无登记生产 caller。普通 runtime 的 `into_learning_runtime` 与 Q24 factory 确有受控 caller，因此缺的是具体原 stages 和 custody 装配，不能写成完全没有 runtime。
- **Model material owner 已存在，生产 Model Proposal 路由仍不存在。** `LearningIterationProposalPayloadV1` 生产分支只有 Parameter/Topology；研究 artifact 分支仅 `cfg(test, unix)`。材料 receipt 明确 `DENY_ALL`。已有通用 Root V1/V2 checkpoint/scope schema 不代表已有 Q24 Model proposal profile、payload/dispatch 或原 Proposal 角色注册。
- 新材料 owner 不自动取得 Proposal 角色授权。原 Proposal 阶段本来不另走 learning 签名角色；需回原 durable owner/anchor 与登记 custody 验证，不能新造一把签名 key 补洞。已有 SGD 候选也不能事后伪装成 governed Parameter V3。
- 第5、6段的组件判断以第1—4段共享生产装配为前提：原 launcher 仍拒绝“已收 learning handoff 但 stages 未装配”，Root registration 仍 `production_ready=false`。这不是可以删除或绕过的测试障碍。

相邻 `ACCEPTANCE_DELTA.json` 保存逐段完整理由、准确类型/符号、源码 SHA-256、相关 CALLERS id 与 caller 列表，以及 shared context 原路径。Native CI 状态由独立证据包记录；本报告不把静态审计、Clippy 或组件恢复提升为普通闭环验收。
