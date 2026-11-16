# 固定 453：普通入口可完成的接线与原输入边界

源码：`4537458b51b6ca936264aecea7cfe384b941d0d1`；tree：`8cbd7b269c9c39df4ee3ffcefed8473060696184`。完整静态审计 blob：`782a41774414237ab06df421c3184e24b8ca0e9d`，含 40 个固定源码/机制文件 pins、20 条准确为空的 caller 登记及上下游证明链。本次未改源码、未运行 H/测试，普通验收为 0。

## 1. 可以局部接通的真实代码路径

Root 的 `authority_host_learning_resident_stages.rs::require_stage` 在 Candidate 的 Selection/NextUse 前直接拒绝。其下 `execute_original_stage` 已经选择 `execute_original_evidence`，继而进入实际 `original_selection` / `original_next_use`，返回同一 operation 的 opaque evidence。这里不需要开放通用 `LearningIterationStageOwnerPortsV1::execute_stage` 或 `receipt_attestation` 的 Candidate 正向分支。

最小建议是只把该 blanket deny 改为对既有 concrete Candidate private route 的资格检查。若需要显式 predicate，可在 `cell_q24_candidate_stage_adoption.rs` 增加 crate-private wrapper，复用现有 `require_adoption_cut(snapshot, stage, Action::Execute)` 的 exact5/6、Fresh、next-stage、完整 model cut 与原期限检查，并要求已经安装原 Root gate。这个检查只确定上下文与已有 custody；它不替代稍后的实际 CURRENT、peer、issuer 或效果检查。普通 trait 的拒绝、NoUpdate 路径和 recovery/read-only 拒绝全部保留。尚未实施此建议。

必须同步迁移该函数的完整 protected record 和准确 caller，以及旧 source QA 的 blanket-deny 反例；不能删除旧反例类别或用无条件 `Ok(())` 代替全部保护。

## 2. 原有权限与证据链继续约束每一步

原 signed resident intent、exact-purpose lease 和完整 initial/scope/verifier → 原 Root config 中既有 directory/registry/issuer → 每次 `perform` 实读当前 lease、保持 issuer fence、检查原 PID/时间/取消/read-only → 实际 Fresh admission CAS → 一次性安装 private gate → `gate.begin` 提交完整 predecessor/stage → 真实 Model/E、Version、S、C/readiness 原连接 → 同 operation 原 E/D/T 首尾实读与完整比对 → opaque evidence 同 owner 消费 → 原 Root fresh clock 重验全 panel、签名与独立 principals → checkpoint → 原 post-CAS clock 再验。

Version 的真正 publish 还必须经过实际 Artifact/CURRENT 与 typed Prepared，再向既有 issuer 请求 `agentd.cell-generation.replace-drained`；原 issuer 可拒绝，不能由 LEARN/S 凭据替代。C 的 Ready 只读完成状态，不执行 C。S 必须独立于 T/E，C Observer 必须独立于 T/E/S。

因此，此局部设计无需增加 grant、lease、key、UID、principal、公开 owner 接口或连接构造。它确实会扩大现有代码的可达效果范围；静态检查不能替代完整正向及拒绝路径验真，也不能先承诺“整条路径完全没有权限回归”。

## 3. 仍缺实际 caller 的位置

| 位置 | 可以消费的现有原输入 | 最小接线与当前缺口 |
| --- | --- | --- |
| `main.rs:33 receive → :238 run` | 原 `CircuitQ24TaskProfileV1`，含 sealed baseline task、Source/Cell 文件与 witness、实际 inference control/model | 在普通启动前装入 profile，再调用现有 resident enrollment；或 checkpoint 模式消费实际 stage owners。当前 main/19 个 inherited flags 没有这些输入，只有 checkpoint handoff。 |
| 原 Material/Trainer host | 完整 pre-B PanelPolicyV2 与原 files/witness/key、同原 D/T 连接 | 已有 `freeze → ConfigV2::from_original → create_v2/from_original_custody_v2`。原 owner 的真实生产 caller 尚未接上；冻结方法存在不代表 A/B 前执行过。 |
| 原 Root service 与 launcher | 已批准 intent/lease、原 Root config custody、初始已连接 stage streams、held pidfd | 已有 `register → into_candidate_runtime → serve_original_stream → original client → enroll_original_root`。实际 delivery actor 已在 runtime 调用；其上游 enrollment/registration/constructor 登记仍为空。 |
| 原 Version host | 原 Model client、Artifact/operation/CURRENT、完成 A、原 C task inputs、已持 issuer transport | 已有 `from_original_owners → serve_original_ordinary` 及三种实际读服务，发布后调用普通 C runtime。其实际生产构造与服务 caller 尚未接上。 |

可以在真正持有这些参数的原 owner/launcher 中完成上述调用，无需另建签名体系。当前 `receive` 仅交付 sealed checkpoint File 和原 Root pidfd，不能从它推导其余对象。仅新增接收工厂或一个无人调用的 wrapper，不构成普通入口装配；不能把所有角色私钥集中进新容器。

## 4. 必须由原部署给出的不同输入

- **B 采用前执行**：实际获准运行 exact candidate/baseline 的独立 task/inference owner、各臂真实 RunStart、Source/Cell/ledger 和终态 Outcome。现有 `read_original_v2` 消费的是已完成事实，它没有执行能力。普通 Q24 profile 又要求 sealed PublishedTask，不能用作 E-only 绕行。
- **C 发布与执行**：原 Version/Artifact 资源、允许实际 Prepared binding 的原 issuer policy/连接，和新会话 C 独立鉴权 RunStart/实际内容。LEARN、S、模型字节和 Ready 都不替代它。
- **有效评价与冷重启**：原 owner 给出事前冻结、可真实达到原资格条件的 primary+非空 retention profile 和独立 principals；原服务给出真实 daemon/Root 生命周期与持久化恢复入口。不能改阈值、拿 fixture profile 或 owner reopen 补证。

## 5. 可复用的核验与尚缺证明

现有 source QA 保护完整 Model 前缀、原 channels/Finish/effects、S/C 签名和 no-reconnect/no-signer/no-rearm；原 native 机制已有 absent-root-gate、取消后不可复用、Fresh CAS、同 epoch 撤销、lease 撤销、lost ACK/read-only、Model 五 cut、checkpoint 后过期，以及实际 Selector 采用/恢复/撤销等案例。完整名称见 JSON 审计。

这些不是已跑通的 resident cut5→6→7 普通验收。真正接通后仍须同一候选源码证明完整原 owner 路径，并验证 issuer Denied、错误原 peer/purpose、完整 Model/panel/S/C 变化、过期/撤销/取消和 recovery 禁止新 work。部署缺口不能用作跳过可实现接线的理由，源码接线也不能冒充部署输入或普通成功。

范围限定：本次只核明确列出的源码与旧审计，不重扫全仓或主机。“尚未定位”不等于外部 launcher 不存在。
