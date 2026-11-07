# Draft PR 审阅分组：最终代码候选

本稿准备以 `codex/cell-framework-20261105` 为base的stacked Draft PR，没有创建或发送PR。最终代码固定为 **b5209cfdf509e990f10922197b32540bf8c353a7**，tree **42c1dd4e1a751c690c2800dfc3868e771dc9c70b**；tested source53是 **f74be175de66a4b351cd239d39d98cd34fe9cc1b** / **440d4a8e09af4009e4d9ea067388826308da8803**。完整197路径＝183Rust＋14其他，26owner／27CI；A25、B123、C38、D9、E2分组保持，PATH-GROUPS逐项保留tested和final两份原pin。

tested source53上，R30原app-server strict／完整1345项目门及R31原no-p193工作区均自然退出0；R31为20228PASS／0FAIL／0TIMEOUT，130 reportedskip。实际26owner fix与默认fmt随后完成并导出独立差异，没有格式化后本地测试。最终代码等待exact-SHA CI，分支与PR尚未创建。原R29失败、source53诊断限定与科学HOLD／DENY_ALL保留，详见DYNAMIC-STATUS.json。

## 阅读层次

| 分组 | 完整路径数 | 主要 owner 与审阅问题 |
| --- | ---: | --- |
| A：Cell 合约与机制 | 25 | neuron、plasticity：输入与版本身份是否绑定，unknown 是否只恢复原请求，提案是否仍由已有 owner 验收 |
| B：框架 API 与生命周期 | 123 | agentd、automation、context、runtime、supervisor、Core、MCP、Linux sandbox 等：真实 owning 边界、恢复顺序、消费者与直接回归 |
| C：测试执行与前置 | 38 | app-server/client、CLI、exec-server、network-proxy、external-agent-migration、core_test_support 与 runner/CI：原 oracle、范围及测试 artifact 的真实来源 |
| D：研究与证据 | 9 | 9 个冻结研究源/文档；成熟度、历史资产、研究回执与原生证据另作附件，不算进此源码路径数 |
| E：source53 诊断观察 | 2 | app-server：固定九阶段事件与首个 child 窄日志；无行为修复主张，全部原 await／断言／预算保持 |

PATH-GROUPS.json 为每条路径列出 owner、Git blob、raw SHA 和固定 source54 链接并保留 tested source53 pins；原四组加 E 组互斥覆盖全部 197 路径，原 A–D 分组值保持。以下入口突出行为边界，省略注册对象的逐条历史列表。

## A. Cell 共同合约、Q24 与注册

| 入口 | owner | 已实现行为与审阅边界 |
| --- | --- | --- |
| [cell_roles.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell_roles.rs)、[cell_population.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell_population.rs) | codex-hepta-neuron | 七类功能职责与 capability type、expert 版本、运行实例、活动实例分别建模。职责不等于 HNMF 七类 engram，也不规定模型数量。 |
| [cell_feature_projection.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell_feature_projection.rs) | codex-hepta-neuron | 严格读取既有全局 Q24 conversion receipt，绑定独立 conversion/source/encoder/scope/frontier pins；没有把缺失的完整 FeatureBundle 张量语义补造出来。 |
| [cell_registry.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell_registry.rs)、[cell.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell.rs) | codex-hepta-neuron | 三个可替换后端家族共享版本化合约与原 owner 执行/恢复路径；registration digest 进入操作身份，防止重命名角色、家族、expert 后解释旧回执。注册表不加载模型或签发采用权限。 |
| [differentiation_plan.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-plasticity/src/differentiation_plan.rs)、[differentiation_study.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-plasticity/src/differentiation_study.rs)、[differentiation_topology.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-plasticity/src/differentiation_topology.rs) | codex-hepta-plasticity | 冻结需求、对照、保留与成本，再向现有 topology owner 产生候选；独立验收、发布及状态迁移仍归已有 owner。 |

三家族是：冻结表示＋私有 Head/Residual Adapter；生成模型＋私有 Adapter/解码状态；可训练状态模型/World Model。它们与七类职责是不同维度，不把现有历史模型资产降格为 enum，也不预设“恰好七个模型”。历史模型确有真实训练资产，但其任务指标不自动成为新注册表的资格。

新增 **14 项机制回归**分为 [7 项输入桥回归](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell_feature_projection_tests.rs) 与 [7 项注册/恢复回归](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-neuron/src/cell_registry_tests.rs)。它们验证严格输入、独立 pin、重放、当前来源、unknown 与成本边界，使用控制夹具；**不能证明真实 Encoder/Head/生成模型效能**。全局输入宽度仍是 1..512，EG2 的 768 维不能静默截断；不声明完整 tensor/token/视频/AV 对齐或非线性 Head parity。最终输出仍为 DENY_ALL 的 CellDecisionReceiptV1 提案。

## B. 框架 API、生命周期和直接消费者

| 路径入口 | owner | 为什么必要／行为与兼容性 |
| --- | --- | --- |
| [agentd/circuit_cell.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-agentd/src/circuit_cell.rs)、[automation_effect_host.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-agentd/src/automation_effect_host.rs)、[notes_primary_bootstrap.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-agentd/src/notes_primary_bootstrap.rs) | codex-hepta-agentd | 随大载荷装箱和相邻参数命名组适配真实消费者；原 admission、effect、unknown 与 owning 边界保留。Rust 源调用签名有变化，不能把 wire/digest 保持误读为源 API 完全不变。 |
| [context-compiler/v2.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-context-compiler/src/v2.rs)、[authorized_effect.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-automation/src/authorized_effect.rs)、[neural_circuit.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-automation/src/neural_circuit.rs) | context-compiler、automation | 用有意义的命名输入聚合严格门报出的参数组，入口解构并保留原校验/顺序；相关调用方和回归一起审阅，没有降低 lint policy。 |
| [supervisor.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-supervisor/src/supervisor.rs)、[restart_state.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-supervisor/src/restart_state.rs)、[supervisor_restart_recovery_tests.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/hepta-supervisor/src/supervisor_restart_recovery_tests.rs) | codex-hepta-supervisor | 恢复真实 Matrix 预算，保留 canonical main journal；未解析 release 时避免覆盖有效预算。四项原失败→候选通过的历史行为证据与当前源码资格分开。 |
| [unified_exec/process.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/src/unified_exec/process.rs)、[process_manager.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/src/unified_exec/process_manager.rs) | codex-core | 分清终止请求、原 driver 错误与实际退出；合作式确认预算不能表述为抢占同步 kill 的硬上限。保持先前失败优先及单次 request。 |
| [codex-mcp/binding.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/codex-mcp/src/binding.rs)、[hook_mcp_executor.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/src/hook_mcp_executor.rs)、[session/mod.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/src/session/mod.rs) | codex-mcp、codex-core | 为已配置隐藏 hook 复用受控绑定能力，普通模型可见性过滤仍保留；thread metadata 按真实协议位置传递，不能以 helper 接通替代授权。 |
| [owner_lifetime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/linux-sandbox/src/owner_lifetime.rs)、[linux_run_main.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/linux-sandbox/src/linux_run_main.rs)、[landlock integration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/linux-sandbox/tests/suite/landlock.rs) | codex-linux-sandbox | 持续 pidfd 绑定原 PTY owner，可信 namespace reaper 观察其退出，payload 分支显式关闭句柄；保留 PID namespace/new session/权限约束及原五秒断连 oracle。 |
| [shell-escalation socket.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/shell-escalation/src/unix/socket.rs)、[pty/unix_io.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/utils/pty/src/unix_io.rs) | codex-shell-escalation、codex-utils-pty | 对锁定 Tokio API 的 fd 所有权与注册失败路径做显式适配；不是放宽 FD 生命周期或重新定义 I/O 权限。 |

其余直接 API 消费者、单元回归和严格门所需局部修正均保留在 B 组的完整路径表；审阅时按 owner 一起看，避免只读定义而漏掉 owning 解箱或恢复调用方。

## C. 原 runner、fixture、CI 与锁

| 路径入口 | owner／范围 | 需要确认的边界 |
| --- | --- | --- |
| [scripts/run-nextest.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/scripts/run-nextest.py)、[test_run_nextest_helpers.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/scripts/test_run_nextest_helpers.py) | 原测试 runner | 从实际 Cargo artifact 给跨包 helper 接线，保留完整原门/default features/ignored；helper 路径不是另造同名占位程序。 |
| [exec-server fake_bwrap.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/exec-server/tests/common/fake_bwrap.rs)、[exec-server/Cargo.toml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/exec-server/Cargo.toml) | codex-exec-server | 测试 shim 在安装前按既有 production contract 优先解析系统 bwrap，仅无系统路径时取仓库 binary；不在实际失败后悄悄换程序，不更改 argv/FD/namespace/权限。 |
| [streaming_sse.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/tests/common/streaming_sse.rs)、[turn_input_submission.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/tests/suite/turn_input_submission.rs)、[multi_agent_resume.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/core/tests/suite/multi_agent_resume.rs) | core_test_support、codex-core | 明确原响应 headers、turn finish 与 residency fixture 的完成边界；原恢复 epoch/ID/Plan、durable 顺序、预算和断言继续保留。 |
| [app-server process_exec.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/app-server/tests/suite/v2/process_exec.rs)、[client trace fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/app-server-client/src/remote_process_indeterminate_tests.rs)、[CLI handshake fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/cli/tests/exec_server.rs) | app-server、app-server-client、CLI | 使用已有真实初始化响应与能力协商，补测试请求既有可选字段；不删响应 oracle 或放宽 production API。 |
| [marketplace migration fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/external-agent-migration/src/service_tests/plugins/marketplaces.rs) | codex-external-agent-migration | 仅隔离子进程将 canonical Git URL 改写到本地 fixture，并显式允许该子进程的 local-file Git transport；真实 import 链、canonical origin 和原断言保持。 |
| [http_proxy.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/network-proxy/src/http_proxy.rs)、[mitm_tests.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/network-proxy/src/mitm_tests.rs)、[runtime.rs（source52 唯一增量）](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/network-proxy/src/runtime.rs) | codex-network-proxy | 仅在直接 host-pattern/policy 测试状态显式配置既有 allow_local_binding，独立 DNS/localhost/private/scoped、默认拒绝与 deny-priority 测试继续保留；生产默认和 DNS 防护不变。 |
| [hepta-cell-framework-native.yml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/.github/workflows/hepta-cell-framework-native.yml)、[hepta-cell-differentiation.yml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/.github/workflows/hepta-cell-differentiation.yml) | CI | 既有 lane 覆盖 27 个包选择项，包含 26 个被改 Rust owner 及保留的 control-plane；工作流定义、已排队 CI 与最终 SHA 的成功回执分别记录。 |

source50 对测试依赖适用范围的调整已经运行原 Bazel lock recipe，Cargo 与 Bazel 两锁前后字节相同。source51 两叶及 source52 一叶均不改变依赖输入；继承的是那次锁结果，不是新的 source52 锁更新或 Rust 通过。最终 fix/fmt 已实际完成；最终发布 SHA 的 CI 验证仍待实际结果。

### source52 的单叶增量

原 r26 两项 wildcard 例得到 `Blocked(NotAllowedLocal)`，预期 `Allowed`。原块没有 DNS 回答或 resolver 错误，不能把五秒耗时叫作已证明的 DNS timeout。source52 仅给四个同类 host-pattern/allowlist 测试的初始配置显式加入 allow_local_binding；其中两项原 FAIL、两项原 PASS。完整 101 个 assertion token、requires_allowlist_match 内部独立默认配置循环和生产代码保持。单叶不改变 source51 的 194 行及 26 owner／27 CI 范围；其 source52/R28 四包原门随后完整通过，source52/R29 默认工作区仍有独立 Bedrock 失败，不能相互转授。

## D. 冻结研究与附件

[run_study.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/qualification/cell-differentiation/run_study.py)、[study_gate.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/qualification/cell-differentiation/study_gate.py)、[study_cost.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/qualification/cell-differentiation/study_cost.py) 和其余冻结研究源独立于原生机制测试。已有完整研究的冲突与冗余两个场景均 HOLD；六臂总预算不等，不宣称等预算优势。完整成本使用各自单位，retention、真实模型效能、跨主机续训和实际 owner handoff 需要独立验收。

最终报告附件继续分别保留：`MATURITY.zh-CN.md` 与 `HISTORICAL_ASSETS.json` 的历史资产边界；`study-evidence/` 的原 study/成本/读回；各 `native-evidence/` 中同源码门的原 log/raw rc/receipt/resources/guard、失败与恢复说明。它们不在 197 源码行中，最终 artifact commit 链接由根报告绑定；本文不把本地缺失旧附件重新生成后冒称原字节。源码内早期 VALIDATION.md 的 pending 叙述属于当时快照，当前资格以独立绑定的实际回执为准。

本分组没有把静态审阅、fixture PASS、历史模型训练或锁更新转成 production adoption。科学HOLD、DENY_ALL、已测试源码的完整工程结果与最终代码CI待验收保持独立。

## E. source53 Bedrock 阶段诊断（不主张修复）

[handler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs) 在四个原 await 周围增加九条固定标签；[原集成用例](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/codex-rs/app-server/tests/suite/v2/bedrock_setup.rs) 只为首个 child 设置窄 RUST_LOG。没有记录 profile、region、凭据或请求参数，也没有修改 22 个原 assertion、请求、60秒初始化／10秒等待、重试或筛选。

原R29 Bedrock为10.643秒FAIL，source53/R30同例0.352秒PASS、R31同例0.354秒PASS，各原记录独立保留。两完整门的本次通过不证明原根因已定位或修复；E组仍是两条诊断增量。格式化后没有重跑本地测试，最终SHA CI待实际结果。

建议 stacked Draft PR 以 `codex/cell-framework-20261105` 的固定 framework 输入为 base；A共同合约及直接回归、B实际 owning/API/生命周期适配、C原 runner与fixture/CI前置、D冻结研究与证据分别审阅，E诊断增量另列。原>800LoC建议由真实可审阅阶段回应，不把这197路径集成伪装成小改动；未独立验证的拆分中间版本不继承整体门结果。
