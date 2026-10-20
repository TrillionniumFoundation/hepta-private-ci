# P5 只读盘点与阻断交接

观察日期：2026-10-20 UTC。审计者：`/root/security_p0`。本报告冻结后，新 Operations 候选仅写入 `operations_candidate/`。

## 结论与审计范围

本轮完成了指定旧 PR 的源头刷新、当前 HEPTA 调用方定位、代表性失败任务原始日志读取，以及 Organ/Desktop 当前主干完整文件树盘点和关键 owner 源码核验。**未完成整个 9,166 条目仓库的逐文件代码审计，也未执行目标内核、原生 Windows/macOS/ARM64/移动设备或硬件验收。** 本轮没有远端写入、CI dispatch、分支切换、生产代码修改或新 Rust 大编译。

HEPTA main 固定为 `f8c9419df6ddeb36ff8b522a50219981fb8d9345`。Organ/Desktop main 固定为 `dd1478e1f7c5528d81ed91a94e4db86c45971623`。十个已核对的 HEPTA 调用方/owner 文件在本地 #2917 与 main 的 blob 完全一致，详见 `hepta/current_source_manifest.json`。PR、检查和源码是各自观察时刻的身份，不将旧检查继承到新的合成 merge。

| ID | 当前状态 | 核心结论 | 下一 owner / 依赖 |
| --- | --- | --- | --- |
| P5-TF-LEGACY | DEFERRED_WITH_OWNER | #1063 的 NoTask 编译失配属于旧中间分支；现行 #1311/main 为 Idle | automation-platform；不要另修旧接口 |
| P5-TF-MIGRATION | BLOCKED | #1063 与 #1311 的 SQL 20–22 是不同历史；main 目前到 19 | automation-platform；P0 收敛后在唯一历史上迁移 |
| P5-OPS-ORACLE | BLOCKED | #996 source process qualification 的 22/23 失败直接来自生产 schema oracle mismatch | durability-kernel + Memory；先去重后准备真实模式修复 |
| P5-OPS-TURN | UNVERIFIED | 剩余 1 例 physical turn start 未出现，根因尚未由日志独立证实 | 同上；生产库能打开后重跑原例 |
| P5-AUTHBUS | BLOCKED | #1272 staging/source caller contract 在编译前拒绝 Bao 公共 operation_id 字段 | identity-access；精确 source/merge 重新资格化 |
| P5-ORGAN-A05 | BLOCKED；四操作 UNIMPLEMENTED | 内核当前只实现 QueryAbi，四项资源操作明确 EOPNOTSUPP | A05/A06；可信 grant、原 owner 锁下准入 |
| P5-ORGAN-A07 | BLOCKED；效果适配 UNIMPLEMENTED | 当前服务是只读投影与可选单次 ObjectiveStart 输送，没有真实持久 K↔D→内核执行闭环 | A07 + 原 HEPTA Operations；依赖 P0 和四操作 |
| P5-BROKER | BLOCKED；候选仅默认拒绝 seam | #210 为 Draft，SubmitEffect/CancelEffect 永远拒绝；K 定义与 durable owner 合同有差异 | A00/A07/broker；先收敛身份合同再接 owner |
| P5-TARGETS | UNVERIFIED / UNSUPPORTED | Linux 主机只读客户端已存在；其他 host 路径返回 UnsupportedPlatform；目标设备验收缺失 | A01/A04/A08/A09/A10，各自真实平台 |
| P5-CODEX-SPLIT | DEFERRED_WITH_OWNER | exec / exec-server / protocol 模块已存在；没有本轮 IPC、授权、冷启动 perf/failure 数据 | Codex execution owner；不以目录独立决定重构 |

以上 BLOCKED 不等于运行时错误都能由 P0 自动修复。P0 资源、安全、Windows fixture 与 resolver 必须先形成可验证基线；旧 SQL 及真实能力缺口还需各自 owner 处理。生产授权位全部保持 `false`，未给出部署、激活或 release 接受结论。

## 1. TaskFlow：避免修复已淘汰的中间接口

#1063 当前 head `91cdb16d0674f9fd363711a50488984bd3d66c2a`。其真实 Linux focused 任务 [109794734555](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36670062367/job/109794734555) 原始日志显示：

- 第 6415–6428 行：`multi_scheduler_race.rs:124` 和 `:138` 引用不存在的 `AutomationTick::NoTask`，E0599；这是编译错误。
- 第 4172–4203 行：两个 Python 合同测试拒绝 focused workflow 缺失 “TaskFlow Linux exact head” source-navigation 标记；88 项中 2 errors。
- 同一日志的 format receipt 失败。其后 Bazel 结果不能覆盖前述失败，也不能记成全量 native 通过。

#1311 当前 head `dfac7171cb3d159e3cb2804227ae9a198c3492cd`。已读取其 [model.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/dfac7171cb3d159e3cb2804227ae9a198c3492cd/codex-rs/hepta-automation/src/model.rs)、scheduler 和 tests 目录。model blob `9a9b25df05f87ccf61d3990bcda2ab6f5e28aadd` 与当前 main/#2917 完全相同；接口为 `Idle`。#1311 与当前 main 均不存在上述 `multi_scheduler_race.rs`。因此 **旧 NoTask 不生成同义补丁**；不能把不存在旧文件写成现行测试通过。

#1311 的 [CI required 111222447293](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37126278595/job/111222447293) 原始日志第 236 行明确拒绝 `bazel: cancelled, cargo-deny: failure, sdk: cancelled`，同时 Rust 汇总 success。父级全量快照还记录其三个 Windows Bazel shard 失败。它不能作为当前 live-main 合成 merge 的全绿证据。1311 recorded base `c6f90d48…` 早于 live main；当前 synthetic merge 是 `788f0178…`。

SQL 历史冲突已经按文件名与 blob 精确核验：

| 序号 | #1063 | #1311 |
| --- | --- | --- |
| 20 | recovery_sweeps / 2df4cb1c… | timer_retirement_drain / f661071c… |
| 21 | recovery_frontier_indexes / 0743bf5b… | provider_identity_version / 470651ce… |
| 22 | durable_neural_circuit / a92b7547… | provider_contract_binding / 9abb55aa… |
| 23 | 无 | provider_admission_continuity / c63193c7… |
| 24 | 无 | effect_preparation_evidence / 6b39e6c2… |

main 到 migration 19；本轮已冻结的 migration fixture 修复未增加 SQL。完整身份见 `migration_identities.json`。需要根据真实应用历史设计升级/恢复路径，不能按编号拼接两条支线。

当前调用链已定位：`runtime.rs` → `spawn_automation_service` → `run_automation_scheduler` → 原 App Server queue/AutomationStore。当前 mapping 明确列出真实 FinalUse signer/provider、DST/multi-scheduler、目标机与独立接受尚未完成。调度公平、sibling attempt、unknown 不重派、长历史分页及 provider 真实最后入场本轮未重新运行，保留各自验收要求。

## 2. Operations：生产模式指纹不一致，无法由本轮测试夹具修复覆盖

#996 当前 head `b5b31f82d9ef7f3717df4a88d486a434b18cc9d6`，recorded base `7ddbfac88525196e7a4b31387ceae194958275f5`，当前 merge 为 null。原 source Linux process qualification [108436525730](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36252485730/job/108436525730) 实际执行 **361 项：338 passed，23 failed，0 skipped**；重试后仍失败。

完整 23 例逐例分类在 `hepta/operations_996_failure_classification.json`：

- **22 例直接相同异常**：`Corrupt("required cognitive schema definition oracle mismatch: 2d85becf3c319bd9816dabf00219ee2a5c61892cb2d1a20cb176ff201f416ca5")`。包括 21 个 panic 和 1 个返回 Error 的测试，覆盖 AuthBus relay、Automation/Runtime、Memory context/ranker、native App Server。
- **1 例独立保留**：`cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start` 在 `native_app_server_tests.rs:411` 未观测到 physical turn start。没有把它直接算作 oracle 同源，也没有放松最后入场断言。

#996 新增 [Memory migration0016](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5b31f82d9ef7f3717df4a88d486a434b18cc9d6/codex-rs/hepta-memory/migrations/0016_kernel_operation_destination_terminal.sql)，增加 immutable destination terminal table、UPDATE/DELETE 拒绝 trigger 和索引；同时在 [cognitive_store.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5b31f82d9ef7f3717df4a88d486a434b18cc9d6/codex-rs/hepta-memory/src/cognitive_store.rs) 的 required object 集中增加四项并将固定 oracle 设为 `f76aecab2b3d5a969ca1ac58b6543b64549a437d49ab7c6eeb7d246dd6ab1a66`。实际原生建库算出的 `2d85becf…` 与它不符。

**已证根因层级是生产 schema 定义/固定指纹不一致；具体遗漏或错误生成输入仍须比对 compiled migrations，尚未仅凭报错改 digest。** 本轮 migration fixture、Memory 三文件和 cargo-bin resolver 都不修改此生产 fingerprint 或 SQL，因此不能声称覆盖这 22 例。

当前主线有唯一 configured operation reconciler：`runtime.rs:252–256` 仅在显式配置 host 后启动 `run_production_operation_reconciler`；writer 仍在原 CognitiveStore/production_writer 体系。当前 docs 映射继续列出 exact-head/synthetic-merge 验证、未接入目的端、长期有界 compaction、可信权限与真实存储断电资格缺口。下一项按父级授权在 `operations_candidate/` 做去重、完整 compiled migration/required object 分析与最小可审阅候选；不改此报告冻结内容、不改主工作树、不大编译。

## 3. AuthBus：staging caller 合同阻断

#1272 head `77947715a768b925d417103b2945e95c2f939460`，base 是 #1176 的 `5f6a7177fd6169da47dd8b96d9001f0965ae38ef`，base ref 为 `auth-authbus-boundary-convergence-20260928`；**它不直接针对 main**。

[Exact source job109881374384](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36713710777/job/109881374384) 第 3299–3314 行记录：

`authbus-evidence-projection.py --candidate-kind exact_head --expected-commit 77947715…` 在测试/编译前失败：`caller bao_kv_v2_read contains forbidden tokens: ['pub operation_id: StableId']`。

[汇总 gate109890577459](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36713710777/job/109890577459) 的 SOURCE_RESULT 与 MERGE_RESULT 均为 failure。故不能只看汇总认定是 Cargo、ENOSPC 或 credential 不可用；这是已读取的 caller-source 合同不一致。合同要求 Bao 接受 sealed entered operations handle、原 durable identity 和 FinalUse，而非 caller 自铸 operation metadata；本轮没有放宽 forbidden token，也未断言该文本发现本身已证明可利用漏洞。

当前 main 的 runtime 确实启动 `authbus-relay`，所以旧 IMPLEMENTATION_MAP 的 `not_composed` 不能直接概括当前所有调用方。新 staging 合同引用的 `hepta-bao-adapter/src/durable_authbus.rs` 不在本地当前 #2917；其新 Bao 集成不能按旧 main 的已有 relay 替代资格化。issuer epoch/PK、quota/reservation、不可变 dispatch 时间、late settlement、timeout hold、rotate/revoke、可信时间、真实凭证和网络 last-use 仍需当前唯一 owner 的精确原生和目标机证据。

## 4. Organ/Desktop：源码实际能力与边界

完整 Git tree：9,166 entries，`truncated=false`。已保存架构/集成/安全恢复/验证/状态、A05 手册、control API/native seam、真实 hepta_control、CPU controller、只读服务与 ObjectiveTransport、session/panel，以及 #210 broker 候选。逐份内容按 Git blob 重新计算校验；清单见 `organ/source_manifest.json` 与 `source_manifest_additional.json`。

### A05 五操作

[hepta_control.rs](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/dd1478e1f7c5528d81ed91a94e4db86c45971623/kernel/asterinas/kernel/core/src/device/misc/hepta_control.rs) 第 200–205 行直接拒绝非 QueryAbi；第 220 行 supported_ops 只有 QueryAbi bit。故这是明确的未实现能力，不仅是测试证据不足。

| 操作 | 当前设备实现 | 实际结论 |
| --- | --- | --- |
| QueryAbi | 已实现 bounded copyin/codec/copyout | 当前 Process Arc 与镜像 key 校验；open 不授管理权 |
| ReadUsage | EOPNOTSUPP | UNIMPLEMENTED |
| InstallBudget | EOPNOTSUPP | UNIMPLEMENTED |
| QueryDelivery | EOPNOTSUPP | UNIMPLEMENTED |
| RetireThrough | EOPNOTSUPP | UNIMPLEMENTED |

`check_session` 保留精确 Process Arc、epoch/nonce 校验；复制 bounded 完整请求之后解释。此只读实现不证明未来 effect 的授权/撤销原子性、可信 activation、copyout 后重取或历史退役成立。

### A06 与已有真实证据

当前 main 的最新 STATUS 记录 #205 G1-b 内部纳秒记账和 #207 G1-c Process 映像生命周期已正常合入，且保留各自旧 run/源码/分母。真实 CPU cgroup owner 与账务代码存在；不能把整个内核工作标成“仅文档”。**本轮只读了这些记录和 owner 源码，没有重新下载校验完整历史 artifact 或重跑 QEMU**，不转写历史记录为本轮验证通过。

这些切片仍明确不含四项 HOS2 操作、不可变镜像认证和生产 grant、完整 SMP/physical switch、A07 K↔D 或移动设备资格。完整 G1/G2 不能由内部 quota 或只读 QueryAbi 单项代替。

### A07、UI 与其他平台

[services/hepta-os/src/lib.rs](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/dd1478e1f7c5528d81ed91a94e4db86c45971623/services/hepta-os/src/lib.rs) 只导出四个固定读取方法；公开声明是投影边界。ObserverClient 在非 Linux 平台 `new/poll/run_status` 返回 UnsupportedPlatform。Linux peer UID 不等于独立应用身份或 FinalUse authority。

可选 ObjectiveTransport 是单次、保留不确定状态的原 ObjectiveStart 输送，源码第 274 行明确不是 crash-durable；没有建立新 durable ledger，也没有实现 HOS2 effect adapter。ControlCore/native seam 只携带原 owner 绑定和历史 ack primitive；API 合同明确 A07 仍须在原持久 owner 验证 K、D 和 fsync，不能让 value-only HistoryAck 赋予退役权。

当前已查看 session/panel 调用源，不让 renderer 拿 Agentd endpoint 或设备句柄。Windows/macOS/Android 路径不是已资格化客户端；本轮没有 Linux/ARM64/macOS/Windows/移动设备上完整 Hepta→新内核→持久恢复端到端原始结果。S1 原生块存储耐久、真实 revoke/kill/reboot 和独立恢复资源仍是 G2 前置条件。

### 当前 CI 与 #210 broker 去重

main exact head 仅有四条检查：两个 Python 分析 success，一个 JS/TS CodeQL failure，一个 Upload Results skipped；两个 workflow run。失败 [118122567281](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/actions/runs/39270887554/job/118122567281) 原始日志第 1040 行为 CodeQL detected JavaScript/TypeScript but could not process any，exit32。下一条 disk-space 提示是通用可能原因，**本轮日志没有证明 ENOSPC 根因**。这些检查不提供当前 head G1/G2 全套成功证据。

共有 21 个 open PR 已完整取回当前页，新增候选：

- #210 head `bb71c17dea658bb34a615050aca0db80f0c662a4`，Draft，5 files；5 checks success（本轮只读 API 状态，未读其测试日志）。[broker源](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/bb71c17dea658bb34a615050aca0db80f0c662a4/ui/broker/src/lib.rs) 只授 Observe/OfflineDraft/Reconcile，永远拒绝 SubmitEffect/CancelEffect，不可作为 A05/A07 完成。
- #211 head `0ad15cc8dfe77b56370da68cf6857d3b7976b907`，ReadUsage fail-closed 文档，Draft。
- #209 head `49afc66beb37be5c943815d3bfb4fcfff7734bf3`，HistoryAck 边界文档，Draft。

**#210 后续整合前的合同差异**：broker 的 OperationKey 把 `payload_digest` 与 scope_id/operation_id 一同用于 BTreeMap key；当前 main 的 HEPTA_INTEGRATION 与 control API 合同则要求持久 K 只由 scope/operation 两个 StableId 查找，再独立比较 digest。它目前是默认拒绝、进程内观察缓存，不能称为已开启的 effect 绕过；但不能原样把这个缓存 key 提升为 durable owner 身份。需 A07/broker owner 明确修正映射或命名与查找规则，保留同 K 改内容冲突检查。

## 5. Codex 执行层与未扩大的范围

已盘点当前源码存在 `codex-rs/exec`、`exec-server`、`core/src/exec.rs`、`protocol` 和 `app-server-protocol` 等实际模块。本轮没有沿全部 IPC 调用逐段审计、没有完整历史拆分时间线或 perf/failure paired measurements。因此不提出整仓解耦重构。下一调查需绑定实际运行 profile，测授权检查、序列化/拷贝、IPC、冷启动和错误恢复，保留原 control/data 权责。

UI #2885、Agentd #2915 已交各自 owner，本报告保留身份但不重复修复。Chain/Game 不纳入此 release gate。

## 6. 证据索引与下一步

- `snapshot.json`：P5 PR source/base/merge、两仓 main、Organ tree/current checks/runs/open PR。
- `additional_api.json`、`organ/recent_prs.json`：1311目录、AuthBus job列表、#210 files/checks 与后续头。
- `hepta/logs/*.raw.log`：5 份完整原始任务日志；`organ/logs/*.raw.log`：当前 main CodeQL 原始失败。
- `hepta/operations_996_failure_classification.json`：真实 23 例身份与首发异常，不转移 P0 验证。
- `migration_identities.json`：两条 TaskFlow 历史与 #996 Memory 16份 migration blob。
- `host_observation.json`：本轮仅可见共享 Linux container，未运行 Organ guest/physical targets。
- `security_p0/` 与 `memory_p0/`：已另行冻结交接的 P0 修复/7tests/历史 Windows 证据，不因本报告扩写而改动。

接下来唯一获授权的新准备项是 Operations oracle/compiled migration 去重分析；先查全量 PR 清单与后继 source，宣布精确文件范围后才动候选。最终要有未篡改 schema 正向打开、tamper 拒绝、destination immutable proof 的 UPDATE/DELETE/REPLACE 负例和原 23 例回归。P0 尚未收敛，旧 SQL 历史保持暂停。

