# 40 模块本轮集成与验证总览

本轮已形成固定合并候选 **`8658210499706130788c216ff14fd342809b45a4`**，tree 为 `6bc86196d10cf83b010f9917e5e9cb471b5f6b68`，草稿集成 PR 为 [#4893](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4893)。该候选完成了自己的 Linux 原七包回归：**1,219 项通过、78 项跳过；69 项必需案例 clean，整体 CLEAN；7 项严格仓库检查及 8 项外层检查均 exit 0。** 外层检查包括原 Codespell、格式、Clippy、库/进程回归及 28 项 Python CI 回执控制检查。[固定源码](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8658210499706130788c216ff14fd342809b45a4)；[七包原汇总](native/seven-package-run5-summary.json)；[外层总回执](native/complete-canonical-run1-summary.json)

源码报告覆盖 **40 个模块、371 项操作映射**。这轮修复了记忆最终使用竞态、精确学习账本 ACK 对账与 witness 恢复、Supervisor 锁所有权，以及完整集成与平台检查暴露的接口、fixture、拼写和 Windows 名称引用问题。最后合入了固定并发分支 3a39，保留其 Windows CI 与 OpenSSH 诊断变更，并在合并后重新执行。真实有序父提交为 `775bf555b0a7faf6eed17627acb0d0433294b737`、`3a39c799a3f776b0aeedfce350341d865d3cc1c4`；早期候选及其失败、通过和排队结果分别保留。[源码重建与合并核对](BUILD-SOURCE-REPORT.md)

**全部 40 个 `productionImplementation` 仍为 false；公共拓扑继续 DENY_ALL。** 当前结论支持固定源码和相应 Linux/Python 命令范围。真实 provider、完整默认 daemon 生命周期、Windows/Darwin 平台、目标宿主部署和独立 custody/接收方验收仍按原门槛记录。371 是操作导航条目数，不是已完成的生产功能数。[完整源码事实](MODULES40-SOURCE-FACTS.json)；[371 项操作与原门槛](MODULES40-OPERATIONS-AND-GATES.zh.md)

## 一、固定候选分别记账

| 候选 | 固定身份与主要结果 | 保留的边界 |
| --- | --- | --- |
| bb55 原集成候选 | `bb55b0d7d263c396ec504c45393d938c3428dae5` / tree `19116ccdf440a1cddc2a29f3d709ebe1a3cd06c1`；Linux 七包 1,219 passed、78 skipped，相关检查通过 | 平台 Codespell、Windows 测试编译及 Bazel 实际失败分别保留；Windows 私有状态专用成功也只归属于本候选和其选择范围。 |
| 797 拼写修复候选 | `797116d61cf422c26274ffef31297dce84a53a80` / tree `67ce024db1679aa6cd301856ba3a694ea18bc4b6`；独立七包 1,219 passed、78 skipped、原 Codespell/格式/Clippy 及指定库/进程回归通过 | 原始文件和独立读取 custody 已核对；Windows 编译与 Bazel 的后续实际失败仍保留。[797 历史](SPELLING797-EXECUTION-HISTORY.zh.md) |
| 775 Windows 名称引用候选 | `775bf555b0a7faf6eed17627acb0d0433294b737` / tree `e6f4644152d11a06457fdd92d8e5066675b26565`；独立七包 1,219 passed、78 skipped、相关原检查通过 | 仅 Linux 结果；Windows-only 引用修复不因本次 Linux 回归而取得平台执行资格。[775 历史](WINDOWS775-EXECUTION-HISTORY.zh.md) |
| 865 最终固定合并候选 | `8658210499706130788c216ff14fd342809b45a4` / tree `6bc86196d10cf83b010f9917e5e9cb471b5f6b68`；真实有序合并后独立七包 1,219 passed、78 skipped、7 项严格检查与 8 项外层检查通过 | 平台流水线按其实际状态单列，Linux/Python 结果不升级为 Windows、Darwin 或生产部署通过。[本候选总回执](native/complete-canonical-run1-summary.json) |

bb55 已封存于 [不可变检查点 f038947f](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f038947fd20992e15213d41f7f6d8ac1d2ca10fc/qualification/module-execution-dossiers/modules40-20261105-da8578)。PR head、PR 合并对象、原生直接执行的 commit 以及报告证据提交保持各自身份；相同 tree 不替代实际执行记录。

## 二、最终候选实际验证范围

下列结果来自最终 865 的独立执行。Native job `1a1aca9512d-fc05-5638` 的权威终态为 `succeeded / exit 0`，输出完整且已持久化，无外层超时、取消或自动重试；18 份命令回执的执行前后源码身份一致且工作区干净，日志字节数和 SHA256 均核对一致。独立审计从原始 JUnit 再次匹配全部 69 个唯一必需案例，结论为 CLEAN_WITHIN_RECORDED_SCOPE。[运行服务终态](runtime/complete-canonical-865-runtime-status.json)；[报告核对](COMPLETE865-EXECUTION-VALIDATION.json)；[独立审计](audit/865/FINAL-NATIVE-AUDIT.json)

| 命令或审计范围 | 最终 865 的结果 | 证据与准确范围 |
| --- | --- | --- |
| 七个完整包、原 `local` profile、无测试名过滤 | **1,219 passed（1 slow）、78 skipped；0 failed、0 timed out**；36.472 秒 | [原日志](native/seven-package-run5-original-test.log)、[JUnit](native/seven-package-run5.junit.xml)；原包选择、超时、重试与断言保持。 |
| 69 项必需案例与完整 JUnit 失败检查 | **69/69 clean、整体 CLEAN；exit 0** | [审计](native/seven-package-run5-required-tests.69.native-audit.json)；69 项用于核对整套结果，不能覆盖套件其余失败。 |
| 七项严格仓库检查 | **7/7 exit 0** | [汇总](native/seven-package-run5-summary.json)；Map qualification、status facts、registry、documents qualification、Chef custody、Rust CI feedback、module docs metadata。 |
| Codespell 2.4.3 原仓库命令 | **exit 0** | [回执](native/complete-canonical-run1-original-codespell.json)；原 ignore/配置和命令选项未扩充。 |
| 原全工作区与四包格式检查 | **均 exit 0** | [全工作区回执](native/complete-canonical-run1-original-workspace-format.json)、[四包回执](native/complete-canonical-run1-original-four-package-format.json)；稳定版忽略 nightly-only `imports_granularity=Item` 的原告警保留。 |
| 原 CI Clippy 三项 deny policy | **exit 0** | [回执](native/complete-canonical-run1-original-ci-policy-clippy.json)；`correctness`、`await_holding_lock`、`await_holding_invalid_type`，不称 `-D warnings` 全警告通过。 |
| ExecServer 与 AppServerClient 两个完整 library target | **319 passed（1 slow）、0 skipped；exit 0**；45.015 秒 | [原日志](native/complete-canonical-run1-two-library-regression.log)、[回执](native/complete-canonical-run1-two-library-regression.json)；不搬运旧候选的通过数。 |
| AppServer `process_exec` 选择范围 | **5 passed、1,016 skipped；exit 0**；0.451 秒 | [原日志](native/complete-canonical-run1-app-server-process-regression.log)、[回执](native/complete-canonical-run1-app-server-process-regression.json)；选择之外的案例保持 skipped。 |
| 原 Windows CI 回执控制测试命令 | **28 tests，OK；exit 0**；0.068 秒 | [原日志](native/complete-canonical-run1-original-windows-ci-receipt-controls.log)、[回执](native/complete-canonical-run1-original-windows-ci-receipt-controls.json)；在 Linux 上运行 Python unittest，不代表 Windows 编译或原生执行。 |

七个完整包为 `codex-hepta-agent-protocol`、`codex-hepta-agentd`、`codex-hepta-infer-worker-host`、`codex-hepta-runtime`、`codex-hepta-contracts`、`codex-hepta-learning-ledger`、`codex-hepta-supervisor`。69 项清单分布为 protocol 3、Agentd 15、runtime 3、worker 40、ledger 5、supervisor 3；Contracts 仍参加完整包执行。不同命令、不同候选和重叠案例的数量不相加成一个无法核对的“总通过数”。[最终七包执行范围](native/seven-package-run5-summary.json)

### 平台 CI 仍有未验收项

固定 865 的最后一轮只读平台快照观察于 **2026-11-05 17:04:02–17:04:24 UTC**，跨 API 非原子。已生成 39 个 job：**37 queued、1 in_progress、1 skipped**。唯一运行中的 ARM64 release job 当时仍处于 `Set up job`，没有该候选的平台编译或测试结果；未观测到失败也不写成平台通过。[平台原始快照](platform-865/summary.snapshot.json)；[分工作流状态](platform-865/PLATFORM-SNAPSHOT.zh.md)

旧 bb55 的 Windows 私有状态安全专用检查实际成功，5 个过滤范围共 33 个不同 PASS，另有重复正例与故意破坏对照；该结果只证明 bb55 的相应安全范围。797 的平台 Codespell 实际成功，但其 Windows PTY 的 3 处 E0034 和沙箱测试 8 处 E0659 编译错误，以及 Bazel 的 bootstrap/远程执行问题仍分别记录。最终 865 已包含名称引用修复；实际平台执行继续等待其原始回执。Bazel 路由问题保持开放，没有改配置或关闭检查来替代资格证据。[历史平台证据索引](platform-current-audit/PLATFORM-EVIDENCE-INDEX.json)

## 三、这轮源码实际推进


### 记忆最终使用与学习恢复

Agentd 在 retrieval/ranker 回调之后、成功回执之前，重新读取实际 SQLite owner cut，防止准备阶段通过后发生的删除、纠正、到期、撤销或 owner 变化继续借旧快照成功。原 store owner、同事务 provenance 与 Fact-only 能力边界保持。这是已补齐的局部最终使用校验；真实 retrieval provider 到物理模型请求的载荷附加仍需对应产品路径验收。[固定源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8658210499706130788c216ff14fd342809b45a4/codex-rs/hepta-agentd/src/cognitive_context.rs)

学习账本新增精确已提交记录 `CommittedLearningAppendV1`，绑定 ledger、record ID、event digest 和 predecessor chain digest，为历史已认证 Decision/Outcome 提供丢 ACK 对账。该路径不为缺失正文追加新事件，不续发过期权限，也不恢复已撤销授权。Witness 恢复在向 owner 暴露完整帧之前完成同步，并保留真实只读 I/O 失败。默认 daemon 的完整 D/O 与 pending-intent 恢复、独立 witness 和物理断电资格继续开放。[ACK 对账源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8658210499706130788c216ff14fd342809b45a4/codex-rs/hepta-learning-ledger/src/production_reconciliation.rs)；[witness 源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8658210499706130788c216ff14fd342809b45a4/codex-rs/hepta-learning-ledger/src/witness.rs)

### 进程接管与完整回归

Supervisor 的 handoff 锁由实际获取它的 PID 管理，显式释放不能由被动复制或 fork 继承的描述符冒充；原代次、授权和恢复围栏保持。完整七包随后暴露了受控子进程 fixture 的 Drain 协议与私有镜像准备问题，修复分别保留了真实 Draining 状态、spawn 身份和既有代次规则，以及原 60 秒预算和安装/摘要/执行/接管断言。[锁源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8658210499706130788c216ff14fd342809b45a4/codex-rs/hepta-supervisor/src/writer_handoff_lock.rs)；[配对子进程源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8658210499706130788c216ff14fd342809b45a4/codex-rs/hepta-supervisor/tests/paired_process_product.rs)

私有测试镜像由 GNU `strip -S` 从约 313 MB 缩为约 48 MB。缺工具、非零退出或输出缺失均失败，没有静默回退；父测试二进制与构建 profile 不变。测试启动真实 OS 子进程，但子进程协议仍为受控 fixture，不等同于真实 Agentd、Matrix homeserver 或 Darwin 签名二进制部署。

### CI 接口、格式与流式前缀

集成修复涵盖实际 AppServer 初始化 API 返回值、AppServerClient 的 `trace: None`、ExecServer 测试的 process-map lock/异步边界，以及跨盘 timing/source-custody 上传。原全工作区 formatter 修正了额外 10 个 Rust 文件；独立源码审阅确认这些变化限于格式与等价布局。原 CI Clippy 策略没有降低。[详细源码变更记录](CHANGELOG.zh.md)

Codespell 实际失败来自一个用于流式测试的 `"hel"` 前缀。修复把源码字面量写为 `"he\x6c"`，运行时仍是同一个 `&str` 和三个字节 `68 65 6c`，测试通知顺序与所有断言保持。原 Codespell 在 bb55 上重现 exit 65，在代码修复父提交上得到 exit 0，之后 797 重新运行也通过；未修改拼写忽略配置。[固定源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8658210499706130788c216ff14fd342809b45a4/codex-rs/hepta-infer-worker-host/src/native_output_tests.rs)

### Windows 名称引用的修复与并发合并

实际 Windows x64/ARM64 检查发现两类编译错误：PTY 测试中的 `as_raw_handle` 同时可由标准 Windows trait 与 `portable_pty::Child` 解析，出现 E0034；沙箱测试的 `assert_eq!` 由父模块 glob 与 prelude 形成歧义，出现 E0659。后继补丁只把三处 HANDLE 读取显式指定为 `AsRawHandle::as_raw_handle(&self.child)`，并为子测试模块显式导入原本使用的 `pretty_assertions::assert_eq`。[Windows 源码审阅](review/windows-name-resolution/REVIEW.md)

补丁保留 `DuplicateHandle` access mask、unsafe 范围、等待与错误分支、所有 8 个删除权限断言，以及原 5 秒/10 秒预算。实际 Windows 编译、ACL/私有状态、目标架构和完整平台资格必须由后继候选自己的原始检查决定；Linux 格式或源码审阅不能代替它们。

最后与固定并发分支 3a39 作真实有序双父合并，保留 4 份 Windows CI 文件的原始字节及 OpenSSH 的受 cfg(test) 限制诊断。唯一 PTY 冲突保留 775 已审阅的显式方法选择和原生格式；OpenSSH 另外只有 4 处 formatter 布局与 2 个尾逗号变化。相对 775 的精确 GitHub compare 仅有这 5 个路径，所有 40 张 Map 原字节未变。合并后执行的是 canonical 865，其成功没有从 775 转移。[源码合并与重建记录](BUILD-SOURCE-REPORT.md)

## 四、40 模块的发展情况

完整正文逐项保留固定源码根、owner、caller/writer 原状态、操作映射和下一门槛：[40 模块逐项正文](MODULES40-DEVELOPMENT-BODY.zh.md)、[owner 与源码映射](MODULES40-OWNER-AND-MAPPING.zh.md)、[371 项操作及全部原门槛](MODULES40-OPERATIONS-AND-GATES.zh.md)。分组规模及判断如下。

| 模块组 | 模块数 / 操作条目 | 已形成的能力 | 当前优先闭合的门槛 |
| --- | --- | --- | --- |
| 契约与内核 | 5 / 41 | 规范类型、wire、final-use authority、持久 operation/outbox、evidence owner | 补齐三项缺失目标协议，接真实 authority/provider，按目的端验证去重、apply、ACK 与终态对账。 |
| 执行运行时 | 4 / 29 | Supervisor 生命周期/接管，Fleet 租约骨架，Agentd RunStart，Codex/AppServer 适配 | 完整物理 start/interrupt/terminal 路径、真实容量、当前信任及宿主恢复。 |
| 身份、密钥与推理 | 4 / 14 | AuthBus、Bao 租约准备/对账、推理调度、Worker Host 私有调用与重开不重发 | 真实 endpoint、经济配额、硬件/模型 grant、模型权重、usage 与未知派发对账。 |
| 目标与决策 | 8 / 85 | Objective、NDU、Neuron、策略/Prompt/Context 与 canonical-run 源码组合 | 真实 payload 授权绑定、认证 V2 caller、daemon owner 生命周期、默认 D/O 与 pending-intent 恢复。 |
| 认知与记忆 | 7 / 52 | Store、SQLite 当前性读取、retrieval、图、只读 federation 与 compact 候选 | 真实上下文 provider；删除/纠正/过期/回滚/旧代拒绝到物理请求的完整路径；区分 tombstone、物理删除与派生产物撤回。 |
| 学习与演化 | 5 / 102 | 账本、评估、产物 owner、参数和拓扑候选；局部 ACK/witness 恢复增强 | 默认完整学习环、独立未来窗口与 selector、真实自迭代 coordinator、独立回滚域和故障 canary。 |
| 外部器官与交互 | 5 / 17 | TaskFlow 持久调度/outbox、Matrix 持久通道、浏览器 owner、Web/native UI 边界 | 真实 homeserver、Servo 二进制、目的端效果终态、认证 UI 与签名/公证/平台更新恢复。 |
| 全局控制与工程 | 2 / 31 | 计划/journal、工程 owner、候选生成与队列生命周期 | 完整 Control lifecycle、路由/代次 CAS、独立 custody、review/批准链和平台集成验收。 |

这些判断是依据固定 Map 的原始声明做出的工程归纳。`not_composed` 表示命名产品组合关系尚未完成，不能读成“没有源码”；只读或无状态模块也不应凭空添加 writer。`inference.worker` 已有私有 Agent/App Server 调用与重开不重发源码，`intelligence.control` 已有 ObjectiveStart 到 canonical-run 的源码接线；两者仍缺各自完整物理执行与恢复资格。[源码事实及原 claimBoundary](MODULES40-SOURCE-FACTS.json)

## 五、接下来八条关键路径

1. 按固定 commit/tree 收齐新候选的完整原生、平台 CI、有序合并与独立审计证据，明确标记排队和未执行项目。
2. 接通独立授权、可信时钟、撤销 frontier、Bao endpoint、真实容量/经济配额与模型设备 grant。
3. 贯通 Objective → RunStart → Agentd → App Server → provider 的物理生命周期，覆盖 Drain、接管、丢 ACK、取消与未知终态。
4. 在物理请求发送前绑定实际 tokenizer/serializer/provider owner、当前 authority、owner cut、来源 revision 与精确 payload。
5. 补齐默认 Decision/Outcome 与 pending-intent 恢复，贯通数据集冻结、训练、独立评估、选择和新进程加载 shadow。
6. 建立非测试自迭代 coordinator，验证独立 anchor/fence、writer handoff、路由/代次更新及强制故障恢复。
7. 按每个效果 owner 验收 TaskFlow、Matrix、Servo 和 UI，保留目的端去重、终态与对账的独立责任。
8. 完成选定宿主的断电/文件系统/容量、Windows/Darwin、签名/更新回滚与独立接收方验收。

各条的完成判据、模块依赖和范围见 [跨模块关键路径](MODULES40-CRITICAL-PATH.zh.md)。原 Map 中 **108 条 repository gate 与 140 条 external gate** 均完整保留；它们包含跨模块重叠和不同层级要求，不能计为 248 个独立 bug，也不能用于推算生产完成百分比。

## 六、历史失败、导航与证据完整性

早期行为 RED、f581 完整七包失败、Drain 中间候选超时、原 CI 和平台失败均继续保留。`f5813506` 的原运行是 1,217 passed、1 failed、1 timed out、78 skipped，69 项 clean 但整体 NOT_CLEAN；后来的成功不改写这次结果。[run1 不可变检查点](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/acf11067530fc12386b090e7e067e518b182088f/qualification/module-execution-dossiers/modules40-20261105-da8578)

固定 775 与最终 865 分别执行了原始导航 helper，均实际返回 0 changed Maps、written=false、ledger=null；40 张 Map 和三份既有 history 的摘要全部保持。相对 775 的 5 个合并变化路径均不属于当前 Map 观察根，因此没有新增导航 ledger。历史 `sourceBase`、owner、caller/writer、claimBoundary、371 条操作及原 gate 不因报告重绑而变化。bb55、797、775 三个旧报告目录共 175 个文件逐字节保留。[最终原生 preview](native/complete-canonical-run1-navigation-preview.json)；[历史保护核对](FINAL-PREDECESSOR-PRESERVATION-VALIDATION.json)

797 的一次独立归档 shell 请求进入 `launch_unknown`，随后查询未获得可证明完成的归档文件。这属于证据打包请求状态，不能改写已成功的原生测试终态，也不能凭空声明归档成功。后续只读 file API 采集按每个文件的版本、字节数和 SHA256 核对；跨文件采集不称为原子快照，不以新 key 重放该不确定归档动作。

报告的证据提交用于保存文件，不作为源码已执行的身份。最终发布须同时列出 canonical source commit/tree、实际执行对象、原始回执/日志/JUnit、独立审计和平台快照；公开链接固定到相应不可变对象。

## 七、原始证据与复核入口

最终 865 原生归档为 [native-865-checkpoint.tar.gz](native/native-865-checkpoint.tar.gz)，共 **81 个文件 / 80 个 MANIFEST 条目**，大小 **325,679 字节**，SHA256 `ba0299e0531d3a3fe4b0c5c5320233e696d5e5436303bc8d082d4fb0d627b430`。全部条目已核对；原始 JUnit 为 **280,619 字节、34 个 suite、1,219 个 testcase**，SHA256 `f17813bb320d0583756f9b19edf87b50b4f2e734028d694c5ec577fa4510c851`。[归档与逐命令核对](COMPLETE865-EXECUTION-VALIDATION.json)；[完整独立审核](audit/865/FINAL-NATIVE-AUDIT.zh.md)

源码报告的全部固定输入、历史快照、原始 Git 对象、构建/核对脚本和文件摘要另存于 [source-report-rebuild.tar.gz](source-report-rebuild.tar.gz)。完整交付清单见 [REPORT-PUBLICATION-MANIFEST.json](REPORT-PUBLICATION-MANIFEST.json)。原始失败、历史通过、当前平台排队和本次 Linux/Python 回归分别可追溯；证据发布提交仅为文件载体。
