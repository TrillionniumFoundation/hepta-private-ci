# 原始 Evaluator 能力与普通入口装配审计

固定源码：`48844493c046fdd79734ddd2c1866314023a15cb`  
Root tree：`360375952ff4fa51e817f2c773e5a5bc2a842a27`  
Agentd src tree：`cbef415e03b9b32ed4f959f1c93399c4b5893471`  
审计日期：2026-11-12 UTC

## 结论与实际验证范围

现有 Linux 普通生产启动会接收原 Root 的 learning checkpoint 能力，但该 handoff 不携带真实 T/E/S/Version/Observer owner 或 B 的执行能力。收到 checkpoint 后若没有装配实际阶段 owner，`require_root_learning_assembled` 会拒绝启动。这个拒绝符合当前真实输入，不能用公开快照、任意回调、OS root 身份或新建 role key 补齐。

这次完整读取了固定提交下 `codex-rs/hepta-agentd/src/**` 的 **926 个 Rust 文件、9,402,011 字节**，含三个 bin、native_g2_entry、测试与 fixture。每个文件都按返回的完整 UTF-8 内容独立计算 Git blob SHA-1，与 Git tree 和 API 返回的 SHA 逐一匹配；全部相等。递归 src tree 未截断。先读取并验证 122 提交的 923 个文件，再用真实 122→488 Git diff 检查 10 个修改和 3 个新增文件，最终重新核对 488 的完整 src tree。

标识符检索屏蔽注释和字符串；所有关键命中再区分定义、导入、重导出、类型引用、实际调用与测试。该检查不是 Rust 编译、完整 typed caller scanner 或 Python source QA。没有运行 native，没有运行普通验收；正向采用、NoUpdate/回退、全新 C、daemon/Root 冷重启的普通验收仍均为 **0**。

范围没有扩大为整个 workspace 或部署主机。附加读取的 17 个原依赖/文档文件均保留完整 blob 身份。仓库外原 launcher 是否存在仍未知。

## 真实启动路径

| 原生产路径 | 实际保留/消费的输入 | 当前结果 |
| --- | --- | --- |
| main → AgentdProductionStartup::from_process_environment | 原 Config、原 inherited FD、原进程身份 | 没有从普通 JSON 生成阶段 owner |
| AgentdProductionStartup::receive | 原 five-lane Root bootstrap、Root pidfd；可选 learning handoff | 接入既有 Root checkpoint |
| RootLearningHandoffV1::connect | 原 sealed bootstrap、同 Root pidfd、固定 scope/request/socket | restore 实际 CURRENT 后得到 AgentdRootLearningInputsV1 |
| AgentdConfig::with_root_learning_inputs | 上述原 checkpoint client、initial、identity、scope | 仅保留输入 |
| AgentdConfig::with_root_learning_stage_owners | 还必须消费真实 StageOwnerPorts、原 verifier | 在完整 926 文件域只有定义，无调用 |
| AgentdProductionLaunch::run / runtime::run | 当前 Config | 原 checkpoint 未完成装配即拒绝 |

原 `RootLearningHandoffV1` 的实际字段只有 bootstrap File、root_pidfd、root_pid。对应 SCM_RIGHTS 接收只接受两个有序 rights。其 sealed `HostAuthorityLearningBootstrapV1` 只含 schema、operation、Root/consumer 生存期、registered identity、writer proof、initial snapshot、可选 frozen scope、checkpoint socket。它没有 stage streams、role signer、模型执行 control、Source writer 或未来 T/E/S/C receipt。

证据位置：

- [main.rs](../../../codex-rs/hepta-agentd/src/main.rs)
- [production_launcher.rs](../../../codex-rs/hepta-agentd/src/production_launcher.rs)：receive 144–191，run 197–207。
- [root_production_learning_handoff.rs](../../../codex-rs/hepta-agentd/src/root_production_learning_handoff.rs)：10–14、43–56、60–104。
- [authority_host_learning_profile.rs](../../../codex-rs/hepta-agentd/src/authority_host_learning_profile.rs)：155–170。
- [root_production_learning_inputs.rs](../../../codex-rs/hepta-agentd/src/root_production_learning_inputs.rs)：25–33、93–125、173–211。
- [config_root_learning.rs](../../../codex-rs/hepta-agentd/src/config_root_learning.rs)：28–51。

所有引用的完整 path、blob、行位置和命中记录均见相邻 JSON。这里的相对文档链接仅方便阅读；固定 blob 身份以 JSON 为准。

## 普通 resident 链的实际缺口

Resident V3 使用独立 purpose：

- `runtime.learning.resident-admission.v3`
- `runtime.learning.resident-readback.v3`
- 原 wire operation `runtime.learning.resident.v3`

V1/V2 checkpoint 连接不能改扮为这些连接。Resident profile 要求 A 已完成，并要求原 Root 已签发的 intent 和已登记的 exact-purpose lease。profile 构造器只验数据，不签发、不安装权限。

以下七个方法在完整 926 文件域均只有一个定义，没有调用：

1. `AgentdConfig::with_root_learning_stage_owners`
2. `AgentdConfig::with_root_resident_learning_enrollment`
3. `AgentdRootResidentEnrollmentV3::enroll_original_root`
4. `AgentdRootResidentLearningClientV3::from_original_root_stream`
5. `AgentdRootResidentLearningClientV3::recover_original_root_stream`
6. `RootResidentLearningRegistrationV3::into_candidate_runtime`
7. `OriginalCellEvaluationReceiptOwnerV1::into_host_from_original_training_readback`

`runtime.rs` 确有实际 `run_original_resident_delivery` 调用，但它只在 Config 已持有 optional resident delivery 时启动。默认 Config 不创建该值。`with_root_resident_learning_enrollment` 还要求已安装普通 Circuit bootstrap/invocation、Objective profile 和 AuthBus trust，并与既有 learning checkpoint 模式互斥。因此不能只打开一个默认布尔值使 ordinary 链成立。

原 T bootstrap 的 from/recover 原 custody 调用仅见测试；原 S create/recover 也仅见机制 fixture。positive Version host 在该域只有定义、impl、import/export，没有外部构造调用。Version 内部对真实 PublishedCell/Source 建立 read owner 的代码存在，但它不能证明 Version 宿主已经启动。

## 模型身份：三个不同的承诺域

### 原 RunStart model_tuple_digest

`objective_submission.rs` 先验证整个 ObjectiveStart 签名，再从原 body 解析 `model_tuple_digest`。Intelligence 的 `compile_and_publish_objective_run_v1` 原样放入 RunStartSnapshot；原 RunStart journal 和 Source codec 完整保留它。

Notes 的既有具体派生域是 `hepta.notes.original-model-tuple.v2`，Desktop 是 `hepta.desktop.original-model-tuple.v1`。两者都承诺原 Core model/provider、catalog、SessionMeta、execution profile/cwd、core config、environments。它们不是 Q24 候选 heads 的摘要。

### 实际 Q24 模型与 bundle

`LoadedCellQ24ModelV1::open_files` 消费已打开的原文件，解析真实矩阵并建立 base/adapter/encoder/heads components。有效权重身份使用 `hepta.cell.composed-q24.effective-factor-graph.v1\0`，完整 bundle 使用 `hepta.cell.compatibility-bundle.v1\0`。

`CellQ24FeatureWorkerV1::new` 独立校验 actual loaded components、bundle、CellDefinition 和 runtime 的 model_id、manifest、generation、encoder/head、effective weights、tokenizer、normalizer、numeric profile、runtime profile、维度。因此外层 model_tuple 不变化，不表示实际 Cell 模型没有变化；也不能直接要求两个不同摘要域相等。

### 未由上述数据提供的绑定

当前 Circuit 请求校验原 run/objective/generation/time，Source journal 保留原 request/input；旧 require_arm 独立要求同 held-out input、同 ndu_snapshot 及正确 candidate/baseline bundle。该路线没有定义“RunStart 的 Core model_tuple 必须等于 Q24 bundle”的关系。这里需要保全各自原值和显式语义，不能把没有跨域相等检查理解成已经具备 candidate 执行权限。

新 paired producer可以比较完整原 RunStart 和独立 actual candidate/baseline 模型字段。它不得通过修改快照、复制 Source 结果或调用裸 worker 产生所谓已授权 B。

## E 的现有权限边界

`OriginalCellQ24CandidateMaterialV1` 只能来自原 Trainer lane 或完整原 peer 读回，验证真实训练材料；其 authority 明确为 DENY_ALL。model()/bundle()/heads() 是数据访问，不能构造普通任务准入。

`CellEvaluationRunnerV1` 先要求 candidate/fixed-expert 的原 Cell journals 已 drained，再调用独立 Product 的 temporal comparison。原 E execution signer 的签名覆盖统计评估请求；原 cohort 持有 B 的原 Ledger 和 Source readback，不提供 Source 发布或任务提交接口。

底层确有 `ControlledNeuronFeaturePortV1`、`DurableInferenceControl` 和 generic Circuit/Cell composition。它们消费调用方已有的原 control/Cell owner，不代表任何 E 角色自动拥有这些 capabilities。现有普通 Q24 profile 还显式要求 sealed PublishedCircuitFeatureTaskV1，并在原 CURRENT/FinalUse owner 下打开 Cell、创建受控推理。此次没有发现一个在生产启动中已持有并交付的、FinalUse 之前的 E-only B task/inference capability。

所以“能加载候选权重”“E 可以签统计评价”“存在 generic worker/control 构造器”与“已有实际 B 的原执行许可”是不同事实。Version/S/C 源码存在，不能据此报告正向 native 或 ordinary 验收完成。

## 最小合法装配决定

详细交付矩阵见 [ordinary-bootstrap-custody-map.md](ordinary-bootstrap-custody-map.md)。

当前 receive 路径实际没有满足这些原构造器的 owned 参数。没有修改生产 Rust，也没有再添加无人调用 factory。现有真实拒绝保持。下一步必须先在原部署层确认实际 owner 和已获准交付的原连接，再在接收它们的普通入口消费：

- 已有基线 A 的 PublishedTask、原 Source/Cell 文件/witness/control。
- 原 T/E/S/Model/Version/C host 已固定的连接、peer、held pidfd、absolute deadline。
- 原 Root resident 注册、intent/lease、与已完成 A 对应的实际 profile 和独立 resident stream。
- 独立 B 的实际任务执行能力、终态 Source/Cell journals、Outcome 及 freeze；这些不能从 LEARN 或 E 统计签名派生。

先接普通 Config/enrollment 的调用但不给原参数，只会得到相同拒绝，不会补齐用户验收。

## H 与执行证据限度

此次没有启动/修改 H 进程，没有重启、签发权限、生成 keys、改变 UID/policy，也没有运行 Rust。前次授权的 h_search_list 元数据不带 query，无法把共享记录可靠归属于本任务，因此没有打开不相关结果。源文档给出的配置是原 launcher 显式输入，尚未确定本任务 T/E/S/Version 的实际 unit/config 路径。

**不能由源域零调用推出 H 上没有外部 launcher。** 原主机的相应实例和 custody 交付仍需用真实部署身份核实。

本目录只固定源代码观察与其限制，不提供新增授权，不作为 ordinary acceptance。
