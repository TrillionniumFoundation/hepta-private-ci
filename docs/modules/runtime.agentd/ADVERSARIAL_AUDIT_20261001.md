# runtime.agentd 对抗审计与整改记录

审计日期：2026-10-01（Asia/Shanghai）。基线：`a126987b84737dbc2ee2592442a314117bddb4a2`。本文记录该基线之后的审计候选，交付分支为 `audit/runtime-agentd-20261001`。精确源码对象由实施映射的 current-source observation 记录；原生测试执行资格仍按第 7 节保留。

## 1. 审计结论与证据口径

`runtime.agentd` 已具有真实的单 Agent 宿主、Codex App Server 组成、Fleet 代数约束、私有存储接入、本地控制协议和 run 生命周期实现。核心宿主与若干产品路径已经落地；canonical intelligence 的物理执行闭环、跨重启执行身份恢复和目标部署验收仍有缺口。

本次多轮对抗审计发现了接收目标绑定、readiness 与 drain 竞态、信任文件边界、弱验签公钥、状态转换原子性、监督任务退出认证以及异步宿主中的同步 effect 执行问题。整改已写入代码，并补充针对性回归。最终 canonical generation 精确域投影、真实 signed 七 owner / Config 回归，以及 effect worker 生命周期调整均已落盘，仍待集中原生验证。

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

当前映射明确限定自身范围：它不是整个 crate 的闭世界函数清单。`nativeSourceMappingComplete` 与 `closedWorldPublicFunctions` 不应因登记了若干组件而被改成 `true`。文档增加了实际 caller、测试入口、版本兼容和尚未接通的物理执行 / 恢复边界。

## 4. 完成度矩阵

| 能力层 | 当前源代码状态 | 本轮证据与整改 | 完成边界 |
|---|---|---|---|
| 注册身份、工作区、资源、单 writer | 已实现配置与 Fleet 绑定 | 审阅 `config.rs`、注册 geometry 与 writer lock | 不构成目标部署或 release 验收 |
| 本地控制与 typed client | 已实现 bounded frame、有限连接、能力与 owner 响应身份 | 新增接收目标绑定、Unix peer 校验、连接监督、错误代数修正 | Windows 缺少同等 peer 身份校验；legacy trusted 请求可不带目标 |
| Readiness 与 run 生命周期 | 已实现 admission、attach、dispatch marker、取消、观察、release | 完整 gate；最终检查与 mutation 共享 `runtime → runs` 锁；转换原子性修复 | run 记录不等于物理 turn 执行凭证 |
| AuthBus / Objective | 已有 signed ingress、durable journal、checkpoint 与 final-use 信任检查 | checkpoint、journal、路径边界及 helper dispatch 修复；durable / canonical admission 复用最终 gate | admission journal 不等于 dispatch ledger；跨重启产品 handoff 未闭环 |
| Cognitive read / writer 接口 | 已有实际 owner store、context、revalidation 和显式 writer seam | readiness 回归使用真实 Cognitive owner fixture | 受治理写入、HNMF、ranker 等依赖显式外部 owner 组成和当前权威 |
| Canonical intelligence | 具备 runner、七 owner invocation provider 和 Objective ingress 的显式组成 | 最终生命周期 gate；`prepare_for_run_start` 已实现精确域投影，真实 Config/Fleet/writer lock、signed Objective 与七 owner 回归已落盘 | 最后 generation 变更待验证；物理 start / interrupt 与可信 terminal observer 未组成完整产品闭环 |
| Automation / effect | 已有可选 scheduler、显式受保护 effect host、durable recovery 组成 | 信任 head、文件 currentness、恢复时间界限；有限 blocking worker、runtime 锁内 typed reservation 与 drain 计数调整 | 最后 worker 变更待验证；正常 drain 后的 App Server 终态观察 RPC 通路仍有缺口 |
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

## 7. 验证记录

| 命令 / 证据 | 当前结果 | 能说明的范围 |
|---|---|---|
| `python3 scripts/hepta_workspace.py` | 通过：193 local manifests，0 errors | 工作区 manifest / 结构校验，未执行 Rust |
| `python3 -m unittest discover -v -s scripts -p test_hepta_agentd_ci.py` | 通过：15 tests | Agentd CI 脚本行为 |
| `just fmt` | 执行成功；无关 Python formatter 变更已恢复原字节 | Rust 候选格式化；不包含无关脚本重排 |
| `CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 just fix --locked -p codex-hepta-agent-protocol -p codex-hepta-agentd --profile dev-small` | 较早候选通过，退出 0；使用独立 target cache；不包含最后 Plasticity RW mode/link 两文件补丁 | 当时协议与 Agentd production、lib tests 和 integration tests 的编译 / Clippy 检查；不是最终候选检查或测试执行通过 |
| 新测试编译修正 | 大型 fixture `json!` 已拆分；三处不存在的 `pretty_assertions` 导入已去除；较早候选原生检查通过 | 未提高 crate recursion limit、未新增依赖或改 Bazel lock；不包含最后 RW 补丁及其两项回归 |
| 最后 Plasticity RW 补丁 | `plasticity_process_file.rs` 与其测试局部 rustfmt、`git diff --check` 通过 | 最终候选 production / tests 编译、Clippy 和原生测试执行仍待 CI；不能复用较早候选的成功结果 |
| 原生测试构建前几次尝试 | 初次多依赖 SIGKILL；两次低资源构建遇到磁盘不足；一次 Clippy 依赖 core 因内存被终止 | 资源失败记录保留，不能据此声称测试通过或推断测试逻辑失败 |
| Scoped nextest execution | Protocol nextest 构建在最终链接失败（退出 101），当时共享磁盘 100% 满；没有进入测试运行。Agentd 全模块尚未取得成功执行证据 | Linux 行为 / process 回归仍须实际运行；macOS / Windows 未在本地执行 |
| `git diff --check` | 通过 | 补丁 whitespace 检查 |
| 初审 / 整改 / 独立再审 | 源码检查已实际完成，多轮局部缺陷修复后收口 | 在明示的 trusted operator-UID/root 边界内，不能证明不存在所有未来问题 |
| ingress 独立 baseline / fixed 小实验 | 0666 checkpoint 从允许读取转为拒绝；外部 symlink target mode 从被改写转为保留 | 局部边界观察，不能代替正式 crate 测试或产品资格 |

测试源码、编译 / Clippy 成功、测试执行与外部部署验收分别记录。最终交付时应检查 exact-candidate CI 输出，不能把历史结果、未运行测试或文档中的验收设计提升为当前产品完成证据。

## 8. 尚未闭环的产品与部署工作

| 未完成边界 | 已有能力 | 下一项必须产生的证据 |
|---|---|---|
| Canonical physical execution | 已认证 Objective ingress、runner + invocation provider、daemon run tuple | 相同冻结身份到实际 `turn/start` / `interrupt` 的 caller，以及可信 owner terminal observation；取消 / failure / restart 的真实闭环 |
| Durable Decision / Outcome handoff | Objective admission journal 与局部 run 生命周期 | 独立 execution / dispatch ledger 的精确身份交接与跨重启恢复；没有记录时拒绝猜测完成或重新 dispatch |
| Run recovery daemon 产品入口 | coordinator `recover_indeterminate` | 有认证 durable-owner 供给的 wire / client / caller 与重启证据；恢复只能复建不确定状态，不能自行发明终态 |
| Drain 后 external observation（P1） | 有限 recovery deadline、正常 Draining 代数允许观察、effect worker drain 计数 | App Server drain 关闭 RPC 后仍能读取历史终态的 owner-supported 通路；readonly observation 与新 admission 的明确区分 |
| 默认 Neuron / plasticity 与高阶 profiles | 显式 owner / bootstrap / currentness 接口 | 已授权的完整 owner 组成和产品调用证据；不能把存在的类型或 CLI flag 算成已组成 |
| Fleet 全目录读取的 namespace（P1） | Agentd 已检查 Fleet root、选中 home/run 和各实际文件边界 | Fleet owner 的全目录 startup traversal 仍须在打开每个 Agent 子树前验证权限漂移；可写 peer 子目录存在阻塞风险，尚未证明认证绕过 |
| 目标平台与部署验收 | 本地进程、结构和回归入口 | 目标 host 上 authenticated socket / generation、saturation、drain / restart、资源预算测量，以及独立 acceptance / promotion / release |

这些缺口涉及现有跨 owner API 或独立部署权威。它们须以真实接口与操作证据补齐，不应通过改映射布尔值、制造 trust 文件、放松 fence 或把 timeout 当作成功来关闭。

## 9. 收口标准

本次已完成多个独立领域的初审、整改与再审。较早候选的 production / tests 编译与 Clippy、格式及结构校验已通过；最后 Plasticity RW mode/link 补丁仅有局部 rustfmt 与 whitespace 检查，最终候选的编译、Clippy 和原生测试执行仍待 CI。原生测试运行曾受资源失败限制。在本轮已审阅的本地边界内，再审未发现新的可独立修补缺陷；第 8 节跨 owner 与部署资格项仍开放，不能由此声称整个模块已完成或永无新问题。

审阅阶段按依赖拆分为：控制与监督、共享文件 namespace 与启动边界、canonical 身份、effect / admission / drain 组成、Browser / Prompt 可选 profile、文档及派生绑定。最先可独立落地的是接收目标绑定与监督修复；组成层必须连同实际调用方和回归一起审阅。

后续收口顺序是：在资源充足的 CI 完成 scoped 原生测试运行；用跨 owner 的实际 observer / execution caller 关闭第 8 节对应项；在目标平台取得独立验收。只有各项证据实际存在时，才更新对应完成度断言。
