# runtime.agentd 对抗审计与整改记录

审计日期：2026-10-01（UTC）。基线：`a126987b84737dbc2ee2592442a314117bddb4a2`。本文记录该基线之后的审计候选，交付分支为 `audit/runtime-agentd-20261001`。精确源码对象由实施映射的 current-source observation 记录；原生测试执行资格仍按第 7 节保留。

## 1. 审计结论与证据口径

`runtime.agentd` 已具有真实的单 Agent 宿主、Codex App Server 组成、Fleet 代数约束、私有存储接入、本地控制协议和 run 生命周期实现。核心宿主与若干产品路径已经落地；canonical intelligence 的物理执行闭环、跨重启执行身份恢复和目标部署验收仍有缺口。

本次多轮对抗审计发现了接收目标绑定、readiness 与 drain 竞态、信任文件边界、弱验签公钥、状态转换原子性、监督任务退出认证以及异步宿主中的同步 effect 执行问题。整改已写入代码，并补充针对性回归。后续复审继续关闭了 Fleet 全目录读取和正常 drain 后的历史观察边界，并修复实际 macOS CI 暴露的跨平台问题。评估消费已改为正式 learning.eval owner 的封存回执，同时补齐完整 decision 封印与消费时的定时撤销检查。验证按第 7 节逐项记录。

本文区分三类证据：源代码及调用关系可审阅；回归测试已编写但尚未执行成功；命令已执行且得到成功结果。文档齐备、测试存在、局部独立实验、产品接线和部署验收分别记录，不能相互替代。本报告不提供缺少定义和分母的完成百分比。

## 2. 在整个项目中的组成地位

Agentd 是一个 Fleet Agent 的进程宿主与组成边界。Supervisor/Fleet 决定注册身份、工作区、资源预算、启动代数和生命周期；Agentd 验证这些边界并嵌入既有 `runtime.codex` / Codex App Server 执行路径。Matrix、native inference host 等调用方通过控制端点获取该 Agent 的能力、就绪状态、session ingress 和 run 记录。

| 关系 | Agentd 的职责 | 仍由对应 owner 保有的职责 |
|---|---|---|
| Supervisor / Fleet | 验证不可变启动身份、生命周期代数、资源及注册路径；报告健康与 drain | 注册、生命周期晋升、进程替换、release 和部署决定 |
| Codex App Server / runtime.codex | 组成既有执行脊柱，管理宿主任务与 readiness | 物理 turn start / interrupt、turn 终态与 session 持久化 |
| AuthBus / Objective | 接收已认证输入，复核信任、replay witness 和冻结 run tuple | 签名信任、目标语义、durable admission / execution 身份 |
| Cognitive / Memory / learning owners | 接入实际私有 store、读取与 final-use revalidation；显式接入受治理 writer | 数据权威、撤销、来源谱系、学习与 artifact 权威 |
| Automation / TaskFlow / provider | 可选调度与显式 effect host；维护本地执行、恢复和 drain 组成 | durable effect intent、final-use grant、provider identity、终态观察与对账 |
| Intelligence / Body / Neuron / plasticity owners | 显式组合受认证的 owner 输入、有限 run 协调与宿主生命周期 | 模型、policy、Body / artifact 身份、学习变更与物理执行结果 |

这种位置要求 Agentd 特别关注 owner 生命周期和末端边界：一次本地 RPC 成功不能代替外部 owner 的物理完成；一个 owner 的 admission journal 不能代替另一个 owner 的 dispatch ledger；本地连接取消不能清除已进入物理 provider 的执行不确定性。

## 3. 技术开发文档检查

存在详细技术资料：[TECHNICAL.md](TECHNICAL.md)、[模块实施映射](IMPLEMENTATION_MAP.json)、[模块执行 dossier](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md)，以及技术指南链接的 runtime extension、AuthBus、Lane B 和产品组成资料。其内容覆盖身份、组件、接口、持久化、并发、信任、运行、恢复与测试入口。

本次检查同时发现历史映射与当前 source 不一致：部分已接线的 final-use AuthBus/Fleet 校验仍被标成缺失；组件 API 恢复曾被描述得接近 daemon 产品恢复；canonical capability 与 CLI runner 选项之间的区别不够清楚。对应技术指南、映射和 dossier 已更新。

严格源码绑定检查另发现七份基线映射引用真实但非当前 main 祖先的旁支提交。已在 [历史来源快照](../../../qualification/module-source-origins/20261001/README.md) 完整保留原 map、commit/tree/blob、角色和观察；以实际集成基线重新建立 sourceBase，再用原严格迁移器刷新当前路径对象。没有添加 Git 父关系、放松 ancestry 校验或提升 boolean 资格。迁移后的候选已通过全部 40 份实施映射和技术文档校验；最终发布对象仍按第 7 节再次精确核验。历史导航证据不成为执行凭证。

当前 Agentd map 登记 20 个边界操作，每个都有测试文件引用；这些引用不等于完整函数清单、具体分支覆盖率或测试执行成功。全项目 40 份 map 的额外审查发现部分操作仍没有测试绑定、许多引用仅到文件级，因此没有以文档存在或路径存在计算模块完成百分比。

当前映射明确限定自身范围：它不是整个 crate 的闭世界函数清单。`nativeSourceMappingComplete` 与 `closedWorldPublicFunctions` 不应因登记了若干组件而被改成 `true`。文档增加了实际 caller、测试入口、版本兼容和尚未接通的物理执行 / 恢复边界。

## 4. 完成度矩阵

| 能力层 | 当前源代码状态 | 本轮证据与整改 | 完成边界 |
|---|---|---|---|
| 注册身份、工作区、资源、单 writer | 已实现配置与 Fleet 绑定 | 审阅 `config.rs`、注册 geometry 与 writer lock | 不构成目标部署或 release 验收 |
| 本地控制与 typed client | 已实现 bounded frame、有限连接、能力与 owner 响应身份 | 新增接收目标绑定、Unix peer 校验、连接监督、错误代数修正 | Windows 缺少同等 peer 身份校验；legacy trusted 请求可不带目标 |
| Readiness 与 run 生命周期 | 已实现 admission、attach、dispatch marker、取消、观察、release | 完整 gate；最终检查与 mutation 共享 `runtime → runs` 锁；转换原子性修复 | run 记录不等于物理 turn 执行凭证 |
| AuthBus / Objective | 已有 signed ingress、durable journal、checkpoint 与 final-use 信任检查 | checkpoint、journal、路径边界及 helper dispatch 修复；durable / canonical admission 复用最终 gate | admission journal 不等于 dispatch ledger；跨重启产品 handoff 未闭环 |
| Cognitive read / writer 接口 | 已有实际 owner store、context、revalidation 和显式 writer seam | readiness 回归使用真实 Cognitive owner fixture | 受治理写入、HNMF、ranker 等依赖显式外部 owner 组成和当前权威 |
| Canonical intelligence | 具备 runner、七 owner invocation provider 和 Objective ingress 的显式组成 | 最终生命周期 gate；`prepare_for_run_start` 已实现精确域投影，真实 Config/Fleet/writer lock、signed Objective 与七 owner 回归已落盘 | 最后 generation 变更已通过编译 / Clippy，行为执行待 CI；物理 start / interrupt 与可信 terminal observer 未组成完整产品闭环 |
| Automation / effect | 已有可选 scheduler、显式受保护 effect host、durable recovery 组成 | 信任 head、文件 currentness、恢复时间界限；有限 blocking worker、runtime 锁内 typed reservation 与 drain 计数调整 | 正常 drain 后已有原 App Server owner 的只读历史 capability；原生/完整进程与目标部署验收另行记录 |
| Plasticity / Neuron | 显式 bootstrap / producer / owner 接口存在 | plasticity 使用完整 admission gate | 不是默认自动制造的 owner；`AgentdNeuronOwner` 未由默认路径完成全部产品组成 |
| 监督与 shutdown | 已有 RuntimeTasks、required / optional 策略和 bounded reconciliation | required 任务过早成功退出不再被认证为成功 shutdown；连接与 effect worker 分别管理 | 活跃任务退出、外部终态、目标平台资源与 drain 资格仍需实际验证 |
| 重启恢复 | checkpoint、frontier 与若干 owner recovery 已实现 | 恢复观察的 timeout、fence 与正常 drain 语义加强 | `recover_indeterminate` 仍为 coordinator 组件 API，无 daemon wire/client 和认证 durable-owner 产品 caller |
| 开发文档与部署资格 | 详细技术指南及显式局部映射存在，已纠正陈旧断言 | Python CI 和工作区结构校验通过；原生验证状态见第 7 节 | 目标 host、独立 acceptance、promotion、release 证据未完成 |

## 5. 威胁与兼容边界

1. **目标绑定。** 新 Rust client 每次请求都携带 `target_agent_id`，接收端在调用任何方法前核对自身 Agent 身份。错 socket，以及合法 socket 文件名被 symlink 到另一 Agent，均须在 destination mutation 前拒绝。响应身份检查继续保留。
2. **协议兼容。** 新字段是可选 additive 字段；旧 constructor 和 legacy trusted local ingress 可省略。新 typed client 必须填入目标。旧 server 的 unknown-field 拒绝会使新 client 的 targeted 请求 fail closed；新 server 保留旧 wire 兼容。自定义绝对 client socket 路径仍可使用；server 只能绑定自己的注册路径。
3. **操作系统身份。** Unix 服务端和客户端在交换协议字节前核验 kernel peer UID。Windows 尚未有同等实现，本轮保留原 transport profile。Unix 私有路径与 peer UID 不提供共享同一 OS 用户的恶意进程隔离；legacy untargeted 请求也不提供新的目标权限。
4. **信任文件。** 对 private file、namespace、handle identity、大小和 currentness 的检查约束读取当时的快照。它们不能使完全受攻击的可信 operator / file UID / root 重新可信，也不等于后续所有操作期间持续持有的权威锁。非 Unix metadata 保证弱于 Unix inode / namespace 保证。
5. **取消与外部 effect。** 连接 JoinSet 退休代表 caller 任务已停止。effect admission 在与 drain 共享的 runtime mutex 下取得 typed owned reservation，reservation 绑定其 host 并在异步操作前计入 occupied slot。物理同步 provider worker 可在 caller 取消后继续持有配额和 authority guard，直到 durable observation 完成。取消、timeout 和进程损失均不得被改写为 provider 成功或失败，也不能触发未经对账的新 attempt。
6. **恢复权威。** owner 身份、签名、当前 revocation、durable predecessor、generation 与 fence 均须在其实际边界验证。组件-only recovery 不得被算成 daemon 已经具备认证跨重启恢复产品。
7. **可选 Browser process profile。** 已验证的 service / worker artifact 以 canonical 路径交给子进程，Unix 文件 owner / root 及其受保护 namespace 是明确的可信 operator 边界。稳定 directory alias 可使用，最后一个路径分量的 symlink 仍被拒绝。Node / Bubblewrap 等配置由可信 host 供给；本轮文件快照校验不能证明子进程最终加载的全部 image，恶意可信 file UID / root 仍不在防护范围内。

## 6. 已发现并整改的问题

下表的“已修”指工作树已有实现和相应回归，原生测试是否成功另见第 7 节。

| 问题与触发条件 | 修复 | 主要回归入口 |
|---|---|---|
| Client 指向 B socket、却期望 A 身份；B 可先被修改，随后 client 才因 response mismatch 失败；仅 lexical geometry 无法阻止 symlink | 接收端 `target_agent_id` 校验；保留 client response 校验及注册 server bind | `control::tests::targeted_control_request_is_rejected_by_the_receiver_before_method_dispatch`；`tests/supervised_two_agents.rs` 错路由与 symlink 下 B federation 不变 |
| Running / AppServer-ready，但 critical stores、revocation、ports 或 admission 尚未就绪；复制 readiness 后遇到本地 drain 窗口 | 完整 run / plasticity gate；`with_live_run_admission` 持 runtime 到 runs mutation；canonical / durable caller 复用 | `state::isolation_tests::run_and_plasticity_admission_require_every_live_owner_prerequisite` 及现有 daemon lifecycle / canonical tests |
| control listener 退休后游离连接仍持 daemon state；请求代数被误写成 owner 当前代数；活性探测无 timeout | JoinSet cancel + join、cancel 优先与 accept 后复查、正确 generation、bounded probe | `control::tests::retiring_control_server_closes_all_admitted_connections`；`rejected_control_frame_reports_owner_generation_instead_of_request_generation` |
| required future 实际先以 `Ok(())` 退出，shutdown 分支可能先认证成功 | required 完成提前转成 Protocol failure | `queued_required_exit_cannot_become_a_successful_shutdown` |
| recovered revision 接近上限，phase 已变化后 revision / deadline 运算才报错；ACK 超时处置不准确 | 先完成全部 fallible 校验，再写 phase / context / cancel 字段；保持 Indeterminate | `exhausted_recovered_revision_cannot_publish_a_terminal_outcome`、`revision_overflow_preserves_each_in_flight_transition`、`cancellation_deadline_overflow_preserves_the_dispatched_run`、`cancellation_after_ack_timeout_requires_terminal_observation` |
| checkpoint 打开后 mode、parent、link count、路径身份漂移；create_new 竞争失败误删另一发布者临时文件 | 每次 read / CAS 重验 private namespace 与 regular file 的 before / handle / after 属性；只清理由自身创建的 temporary | `authbus_checkpoint::tests` 的 permission / directory / hard-link / symlink drift、predecessor publication 和 temporary conflict 回归 |
| Objective root symlink 在拒绝前被 chmod；journal dangling link、hard link、宽权限未在打开边界准确拒绝；helper 依赖 Fleet bootstrap | 先验证 owner 路径，再执行 handle 权限操作；journal 安全打开；arg0 helper 先于 Fleet/lock | `objective_runtime_tests.rs` 新路径边界回归；`tests/helper_dispatch.rs::apply_patch_helper_dispatches_*` |
| intelligence authority 先检查 metadata.len，随后无界 fs::read；路径 / inode / ancestor 可在读取间漂移；弱 Ed25519 verifier key 可接受无私钥伪造 | 固定上限 handle read、Unix 前后 inode / timestamp / namespace 校验、可信 sticky ancestor 规则；拒绝 weak key，使用严格验签 | `intelligence_product::authority_file::tests` 的 growing-source sentinel、exact byte cap、file / parent replacement、writable ancestor；`identity_and_other_small_order_verifier_keys_are_rejected_at_runner_admission`、`identity_key_signature_forgery_fails_before_current_owner_is_returned` |
| 可选 Browser active profile 的 artifact 先检查 metadata.len，随后无界 fs::read；不可信可写 namespace 可替换文件；验证后 spawn 再解析原 alias | 8KiB 栈缓冲流式 SHA256、Take(max+1) 哨兵；同 descriptor / original path / physical path 的版本复核；Unix 完整 OperatorNamespace 与 file policy；spawn 使用已验证 canonical paths，保留 8MiB service / 512MiB worker 上限而不分配同尺寸 Vec | `browser_servo::artifact::tests` 的 endless growing sentinel、exact cap、growth、same-bytes / mtime replacement、permission / parent / ancestor drift、canonical directory alias、final-component symlink 拒绝；source 已落盘，native verification pending |
| Prompt runtime public store 接受预置 lock / next symlink，open / truncate 后才 path chmod；受污染本地目录可改写外部目标，retired lock inode 仍可能参与发布 | canonical directory 与 Unix handle 权限操作；现有 regular / uid / private mode / single-link 校验先于打开和 truncate；before / handle / after inode 与 namespace；发布前复核 held lock，保留 atomic rename、directory fsync 和 reopen 语义 | `prompt_runtime::file::tests` 的外部内容 / mode 不变、hardlink / nonregular / directory symlink 拒绝、next / lock replacement、正常 owner lock / staging / stale-next / reopen；source 已落盘，native verification pending |
| effect authority 同 epoch / revision 换 head；恢复 connect / queue / 分页无统一界限；观察后未重新核 generation；调度时钟陈旧 | head drift fail closed、handle bounded currentness、恢复 connect / queue 与分页总 deadline、远端观察后 fence、操作后更新时间 | `host_dispatches_exact_wire_payload_once`；`recovery_accepts_an_admitted_observation_during_drain_but_rejects_a_replaced_owner`、`recovery_rejects_an_explicitly_fenced_observer`、`stalled_app_server_handshake_cannot_hold_recovery_indefinitely` |
| sync provider bridge 占用异步执行线程；caller 取消可能早于 durable observation；仅队列 / timer 计数可误报 drain 完成 | 每 host 有限 blocking worker；runtime readiness 锁内生成与 host 绑定的 owned reservation，消除复制 readiness 到 reserve 之间的假 drain 窗口；worker 持 quota / authority guard；drain 合并 durable pending effect 与 occupied slot | `automation_effect_host::worker_tests::cancelled_provider_caller_keeps_bounded_worker_and_durable_attempt`、`effect_reservation_is_visible_before_durable_admission_and_drain_closes_the_gate`；最终 worker / drain 实现待原生验证 |
| Plasticity 可写 bootstrap registry / journal 的 namespace 安全，但已有文件仍可能被 group/world 修改或通过 hard link 共享；native owner callback 可接到该可写 handle | `plasticity_process_file.rs` 区分只读 / 可写访问；Unix 可写输入在 open 前、opened handle 及后续 path/handle 复核均要求 `mode & 022 == 0`、`nlink == 1`，新建可写 handle 同验；只读 0644 / hard-link contract 保留，原 owner receipt / anchor / signature / recovery 校验不变 | `plasticity_process_file_tests.rs::mutable_bootstrap_files_reject_group_or_world_write_before_owner_callback`、`hardlinked_mutable_bootstrap_file_is_rejected_before_owner_callback`；最终源码已落盘，局部格式和 whitespace 检查通过，原生执行尚无通过证据 |

同类文件保护已统一扩展到 AuthBus/Evidence trust、Evidence recovery frontier、Objective journal 与启动 writer namespace、plasticity bootstrap；新增回归覆盖非 sticky 可写祖先、可信 sticky 兼容和打开前后文件替换。各 owner 的签名、receipt、anchor 和恢复权威保持原有约束。

最后 canonical generation 调整已落盘，保留不同 owner 的真实语义：Body/process launch generation 与 durable Fleet lifecycle generation 分开，只有在 Body、artifact、authority epoch 等完整身份一致后才投影 daemon run tuple。新增 `intelligence_objective_ingress_tests.rs::configured_running_objective_reaches_seven_owners_and_exact_durable_context_receipt` 从真实 Config/Fleet/writer lock 的 Starting 1 开始，经过 Running 2、signed AuthBus/Objective durable admission 和七 owner 组成，核对 ContextAttached 的完整 receipt 与实际 durable RunStart 的 lifecycle generation 2、fence、deadline，保留 immutable Body generation 1；`objective_binding_rejects_mixed_lifecycle_body_epoch_and_artifacts` 拒绝混用 lifecycle、Body epoch 和 artifacts。上述测试已写入，尚无执行通过证据。不能通过取消 generation 检查或将两个 epoch 混同来取得表面兼容。

## 7. 验证记录与候选区分

此前候选 `37bbd8c418b4f1356b0dbe0e1110de99dc2c9f8a` 的本地 Protocol 13/13 和 scoped production/tests Clippy 成功仍是历史证据。本地 Agentd codegen 的 SIGKILL/磁盘不足也保留为失败，不能视为测试通过。

该候选随后获得真实 macOS 原生结果：[source-head job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36784424472/job/110127794842) 执行了五个 package 的 448 项测试，372 passed、76 failed、0 skipped。失败包括 Prompt 目录身份检查、release 重命名权限，以及旧 macOS fixture/源文本断言。它们已经成为本轮实际整改输入。merge-candidate macOS job 因共享等价树而跳过原生步骤，其 success 不计为另一次原生通过。Linux jobs 当时仍 queued。

| 本轮检查 | 已观察结果 | 证据边界 |
|---|---|---|
| Objective scoped nextest | 61 passed，2 个原有 ignored 未执行，退出 0 | 修正 JSON fixture 与 owner 的空 legal action set 合约矛盾；没有放宽 validator |
| 全部 `scripts/test_hepta_*.py` | 最终全量 710/710 passed，32.947s，退出 0；先前 timeout 和共享磁盘满的失败记录保留 | 全量命令真实完成；相关子集成功没有替代全量；不等于原生或产品验收 |
| learning.eval 原生 library / scoped Clippy | 116 passed、0 skipped，nextest 与 `just fix -p codex-hepta-intelligence-eval` 均退出 0 | 真正执行 sealed receipt、原证据时效与 scheduled revocation 回归；不代替整个 Agentd 验证 |
| Fleet / NDU scoped native libraries | 初次 134 passed / 1 failed；修正 UID fixture 前提后 135 cases passed，nextest 0 skipped | Fleet 58 项完整行为通过；跨 UID root case 因仅映射 UID 0 明示 capability-unexecuted，不算跨 UID owner 验证；NDU 76/76 实际通过 |
| Intelligence / Automation scoped native libraries | 初次 106 passed / 1 failed；拆开两个证据到期前提后 107/107 passed、0 skipped | 精确断言 qualification 与 candidate expiry 错误，保留 0 ports / 0 append / disk unchanged；没有放宽生产校验 |
| Agentd CI wiring Python | 15/15 passed，退出 0 | 检查 source/merge、平台、依赖与终态 gate 接线，不代替实际 native jobs |
| Lane B path guard / truth | 11 modules、62 operations、20 delegated owners、86 bindings 对齐 | canonical 全局 owner 解析；仍拒绝未注册、重复、重叠和歧义根 |
| Lane E closure verify | `findingCount=0`、`ok=true`、退出 0 | 静态边界验收；不等于 native/product execution qualification |
| Fleet / Rollout dependency 与 Bazel lock | 完整 Cargo metadata 更新实际 dependency graph；官方 `just bazel-lock-update` 三次退出 0，MODULE.bazel.lock 无漂移 | 原 workspace 已有 libc / State，Cargo.lock 保留真实新增关系；未手工伪造 lock |
| Agentd native / scoped Clippy | 完整 nextest 在 dependency codegen 被 SIGKILL，退出 101；第一次 `just fix` 因磁盘满退出 101；实际 PathBuf 类型与测试依赖导入错误均已修复；最终 `just fix` 和 qualification-cognitive-write / all-targets / no-deps / `-D warnings` scoped Clippy 均退出 0 | 编译覆盖生产、library 与 integration test targets；没有 Agentd 原生 test execution，通过编译不等于行为通过 |
| State / Rollout focused native 与 scoped Clippy | 首次 codegen SIGKILL/101、无测试执行；随后 13 项执行为 11 passed / 2 failed；新 fixture 的 SQLx 0.9 动态 SQL 类型错误也已修复。最后原生重跑 15/15 passed、退出 0，337 项因筛选条件未执行；Rollout scoped fix/strict Clippy 已退出 0，State/Rollout 最后 scoped fix 和 all-targets/no-deps/`-D warnings` strict 均退出 0 | 实际执行 FIFO/plain/zstd/EOF 回归、三个 vacuum 模式下冷连接和原 owner queue/state pointer 在外部 writer+未提交 UPDATE 下读取 committed snapshot；未把筛掉的用例计为执行 |
| 格式 / workspace preflight / 精确源码绑定 | `just fmt` 和 diff 检查已执行；preflight 193 manifests、0 errors；候选 `49cc18a305` 的 40 maps 精确 SHA/tree verify、40 技术文档及 derived/index checks 均通过；最新 State 修复对象须再次绑定 | 严格校验曾拒绝已删除的 Rust 测试引用及 intelligence.control 未登记的公开 signing-payload 函数，均按真实符号和回归补齐；36 个公开函数对应36登记项，未放宽 closed-world 校验 |

原生测试、编译、文档导航、真实产品组成与目标部署验收分别记账。后续最终结果必须绑定实际发布源码对象，不能把历史成功或 skipped job 归入当前候选。

## 8. 后续复审发现与已落盘优化

| 确证问题 | 本轮修复及兼容边界 |
|---|---|
| Prompt directory 的 nlink 会随合法目录项变化，旧 generic identity 导致 macOS 首次 owner open 被判损坏 | 目录比较稳定 dev/ino/uid/mode；regular private files 保留 nlink=1。回归验证合法目录项创建后 commit/reopen，继续拒绝换 inode、硬链接与宽权限 |
| Fleet startup 遍历在校验前读取 peer 子树；text/JSON metadata 预检后仍可能无界读，FIFO/symlink 替换可阻塞 | owner 级 ControlRoot/DirectoryGuard 在 migration、scan 和每个读取边界校验完整 namespace；同 handle 有界读并前后核身份。Unix no-follow/nonblocking；信任锚是 Fleet root owner/root。保留合法 0644/0444/0555、root 读 nonroot 整树及原 hardlink crash recovery |
| Fleet 公共 constructor 捕获 canonical guard，却保留外部父目录别名作为后续写路径；别名 ABA 可让 chmod 先改错另一 root 再返回失败 | registry layout 与 guard 一次绑定解析后的 canonical root；新建根先解析实际存在祖先，保留合法父目录别名与 `/tmp` 兼容，并拒绝 final root symlink。真实 publication seal 故障注入验证受害 root mode 不变。Agentd config 已拒绝非 canonical root，本项是 Fleet 公共 owner 防护，不能称为 Agentd 接收鉴权绕过 |
| macOS 不允许 rename 已不可写的 staging directory | rename 前保留 owner write，发布后封存和 fsync。精确 pending retry 校验完整 manifest/files/digest/program/args；一般 admission 拒绝未封存根。rename 后 seal/fsync 失败保留 destination，不删除可能已被认可的 release；故障注入覆盖这些窗口 |
| App Server drain 关闭原 RPC，automation 无法获得后续历史终态 | 原 owner Rust capability 只持 SQLite SELECT owner 与 QueueStore，不持 dispatcher/manager/event sink。后台任务与线程真实 join 才开放；timeout 不 ack。当前 rollout pointer 前后纯 SELECT、完整绑定 thread/client/payload/turn；禁止 repair、resume、start、reserve、wake |
| 新 observer 若使用普通 thread read 会隐藏写入；旧 Indeterminate 可饿死后续 drain blocker；历史 JSONL 可无界分配/解压 | 使用无 repair 的 current pointer；专用 selector 优先 admitted/running；每 record 1MiB、扫描 32MiB/65536 lines/4s、zstd window 32MiB，完整扫描才接受 terminal。超界/截断/未知保留 uncertainty，Missing unknown dispatch 不重新派发 |
| 历史 rollout 在 regular metadata 预检后被替换为 FIFO，4 秒 caller deadline 返回后 blocking open 线程仍可能永久等待 | Unix 同 fd `O_NOFOLLOW | O_NONBLOCK` 打开并验证 regular/dev/ino/len/mtime/ctime，完整 EOF 再验 retained handle 与 selected path；任何变化保留 Unknown。plain/zstd 与稳定父目录 alias 兼容，拒绝 leaf symlink；真实 FIFO 故障窗口回归带受控清理。该修复不承诺强取消任意 kernel/networkFS I/O |
| 合法 zstd 空 frames 不产生 decoded 字节，外层 decoded 上限和 caller deadline 无法约束后台 encoded 读取工作 | compressed-only 新增64MiB initial encoded上限、同fd原始长度预算与128KiB physical-read上限，并在读前后检查从 public open 起的4s工作期限。预算耗尽仍以1byte探测真实EOF；追加数据报InvalidData/Unknown，不能忽略尾部或伪造前缀完成。保留正常多frame、window25、API与plainreader，任意blocked kernelIO仍不能强制取消；真实decoder四回归已落盘、scoped fix/strict均通过，原生执行待本轮命令完成 |
| TaskFlow 历史终态恢复曾混用 spawn generation，且 RPC→history receipt 与恢复 claim 后崩溃不能稳定重放 | Running/Draining 共用 owner API；核验已 Reconciled 的真实 step intent/payload/outcome，复用不可覆写 canonical receipt。有效 lease 使用原 TaskFlow fence，过期才用 owner counter 与完整原行 CAS claim；不得 dispatch、续租或改物理执行身份 |
| public 低层 evaluation V2 让 Agentd/plasticity 绕过 fenced holdout、sealed estimator 与 durable publication；receipt seal 漏 disposition/baseline/failed metrics | V2 收为 crate-internal；两个消费者和 evaluated-shadow 统一消费真实 ProductEvaluationRunner 封存回执。新封印绑定完整 decision；当前 owner verifier 重验原 Generator/Evaluator/Observer 窗口与 scheduled revocation，另验证精确 use signature。没有公共 unsigned wrapper |
| 新历史 SELECT observer 复用正确原 State owner，但连接池 lazy reconnect 重发 `auto_vacuum=INCREMENTAL`，可在另一 writer 持锁时隐式争夺写锁 | database-global vacuum 只在 startup deferred snapshot 内，对真正 zero-page 新库设置 INCREMENTAL，然后建立 WAL；后续 pool connections 不重发该 SET。保留既有 NONE/FULL/INCREMENTAL、max5/Normal/FK/busy5s，原 owner pure SELECT 不重建 store、不 repair。真实持4关1强制 cold 的 queue/state path，以及五连接/外部未提交 UPDATE 的回归均已实际通过 |
| CI 文档与 fixture 漂移，包括 operation counts、跨 lane owner、NDU/Objective/migration fixture、陈旧源字符串测试 | 按正式 registry、owner 合约、真实 runner 和原生行为同步。global outbox capacity fixture 分散 issuer 以保留原 per-issuer 512 限额；不扩大容量或删除 replay/active-row保护。原始七份历史来源快照保持不变 |
| AuthBus/Operations 绕过中央 SQLite shim，strict Clippy 拒绝 | 集中固定 WAL/FULL/FK/busy timeout 的 durable pool 和隔离 schema-reference memory pool，保留 owner 原连接上限；每连接 disk-full 故障测试仅保留明确 test-only 定点例外 |

新增 Rust API 是 embedding capability，不是新增 RPC 允许 drain 期间 admission。`AgentdQualifiedEvaluationV1` 与 v2 use-signing payload 是明确的 typed API 迁移；旧 bundle/role/gate 输入不能自行制造产品资格。回执目前是进程内封存结构，不能序列化恢复，因此本轮不宣称 evaluation 跨进程恢复完成。

## 9. 尚未闭环的产品与部署工作

| 未完成边界 | 必须补齐的真实组成与证据 |
|---|---|
| Canonical physical execution | 同一冻结身份到实际 turn/start、interrupt 和可信 terminal owner 的完整 caller；取消/failure/restart 闭环 |
| Durable Decision / Outcome handoff | 独立 dispatch/execution ledger 的精确交接与跨重启恢复；缺记录不得猜完成或 redispatch |
| Run recovery daemon 产品入口 | 有认证 durable execution owner 的 wire/client/caller；现 coordinator recovery 只能复建 Indeterminate |
| 默认 Neuron / plasticity 与高阶 profiles | 明确授权的完整 owner 组成和实际调用证据；已有类型/flag 不等于自动激活 |
| 目标平台、完整 drain 进程与部署验收 | authenticated socket/generation、饱和、真实进程 drain/restart、资源预算测量，以及独立 acceptance/promotion/release |

Fleet 全目录防护与正常 drain 历史观察的源代码 P1 已有实现及行为回归。它们的源码闭合与原生/进程验收状态不同；不能借此宣称任意 downstream effect owner 已经具备原子 shutdown 或整个项目已完成。

## 10. 迭代停止标准

本轮持续执行“独立发现→owner 修复→行为回归→再审”，新发现包括 scheduled Generator revocation、background drain 超时、隐藏 read repair、drain starvation、publication cleanup、Fleet alias ABA、历史 rollout FIFO 替换、实际 SQLite 冷连接写锁、压缩 fixture 冲突、zstd空frame encoded资源预算和编译接线错误。最后独立复审已核验 Agentd lint、Rollout fd/EOF、SQLite startup snapshot、真实 cold-reader fixture 与 zstd encoded/CPU 工作预算，未发现新的具体问题；其结论只覆盖静态审阅范围。最终源码绑定与实际执行结果仍按第 7 节分别记录；仍有确证问题则继续修复。

停止代表在已审边界与既定可信 operator/root 模型内，当前轮没有新的可独立修补发现。它不代表所有未来风险为零，也不能把第 9 节缺失的产品或部署证据改成已完成。

## 11. 审阅与落地分段

当前审计 PR 跨越 owner 边界，包含历史映射快照和派生索引，不能按总行数把它作为一个简单局部补丁。建议按实际依赖拆成以下审阅段：先审 targeted control/readiness/run 原子性；再审可信文件和 Fleet publication；然后联合审 App Server drain、原 State/Queue/Rollout 历史观察与 TaskFlow 对账；独立审 learning.eval 封存及 Agentd/plasticity 消费迁移；最后核验源码绑定、文档和 CI 真值。最小可先落地段是 additive destination target 校验及相应接收端/双 Agent 回归，其公开兼容不依赖后续历史恢复能力。当前交付保持 draft，尚未合并到 main。
