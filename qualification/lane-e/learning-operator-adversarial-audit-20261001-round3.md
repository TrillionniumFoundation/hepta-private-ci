# learning.operator 第三轮对抗审计与优化收敛

日期：2026-10-01。本轮从 PR #1305 的 `38b9ec0a6a37c389ba5ca478f520967098a30fd7` 出发，复核并整合最新 main `997e7beef8151160065df36b024bc8da5c989e93`。核心工程验证源码检查点为 `a180997d54925a77d7720246adb558224a11d318`，tree 为 `b6b33bea1ef48394d757b2482c51f21040ff750b`；真实 terminal 夹具修正后的检查点为 `f6a6e497c00807da4444fde00a74c7d111bf4f8c`，tree 为 `a24c9f580215b46454620234a72501abf75c24fb`；最终 scoped fixer 检查点为 `177bd36d4feac6d84a5ba0c3f9e6daec52a6d390`，只去掉现有 process 测试冗余借用、无生产代码变化。其后的导航与证据提交不转移历史执行资格。最终源代码差异、命令、前后 SHA256 清单和原始输出以本轮 [validation.json](learning-operator-audit-20261001-round3/validation.json) 为准。

本报告接续[第一轮](learning-operator-adversarial-audit-20261001.md)和[第二轮](learning-operator-adversarial-audit-20261001-round2.md)。前轮测试、变异、性能及 CI 结果只作为对应旧源码的历史事实，不冒充当前候选、完整合并资格或独立科学接受。

## 技术开发文档与模块位置

详细技术开发文档确实存在。[TECHNICAL.md](../../docs/modules/learning.operator/TECHNICAL.md) 定义模块边界、数据与信任、预算、fit/use 语义和算法缺口；[ADMISSION_CONTRACT.md](../../docs/modules/learning.operator/ADMISSION_CONTRACT.md) 规定 owner/root/时间与证据准入；[DEVELOPER_GUIDE.md](../../docs/modules/learning.operator/DEVELOPER_GUIDE.md) 覆盖实现和验证步骤。另有资源/shadow policy、runbook、原生符号映射、STATUS/schema、实现地图和 qualification dossier。

本轮补充了 12 个真实 owner port 的接口矩阵和 7 步完整宿主组合验收，明确 opaque proof 的持有与重新准入、独立子进程、存储不确定结果、原前驱精确 rollback，以及 locked 冷缓存准备。文档不再把 learner-owned 内存预算扩展为 backend 全历史快照/RSS 的上限，也不把 `maximum_absolute_error` 目标字段当作已经证明的拟合误差保证。

operator 在项目中是慢路径候选生成器。LedgerWriter 冻结并验证真实源集合；operator 产生有界、不可变候选；eval 的实际估计器、holdout 消费及 durable sink 产生资格；独立 selector 做选择；artifact owner 负责持久化；Agentd 只读消费。root 信任、资格、选择、存储事实、CURRENT 和最终使用时间各自独立，不能用同一个摘要或仓库自签收据互相替代。

## 对抗审计发现与修复

| 编号 | 实际反例或缺口 | 修复与验证范围 |
|---|---|---|
| R3-01 | final fit 的 `max(issued+elapsed, host)` 在宿主前跳后冻结。50s 发行、75s 宿主见证、再运行 6s，旧逻辑仍以 75s 交付，可以越过 80s root 期限。 | 私有 `FinalUseClockV1` 保留共享 fit clock，前跳重新锚定并累计微秒进度；旧见证不能覆盖新 floor，倒退/溢出 fail closed。5 个确定性时钟反例及 tabular/world 两个真实签名 owner 回归。 |
| R3-02 | 内部 root/evidence 检查后，候选 Arc 转换和大对象析构仍可能耗时；外层返回只验 deadline/cancellation，没有重新验证 evidence TTL/模型 retention。 | 私有 release 对象把真实 `IssuedEvidenceV1`、owner 借用和预算 reservation 持有到实际 outer handoff。大对象工作在最终采样前完成；采时后重新验 root、签名主体、evidence TTL 与 retention，记录实际 release 时间。3 个真实签名回归。 |
| R3-03 | issuance 在 owner 验证、canonical scratch 或 plan clone 之后才检查资源预算，极小预算仍执行这些工作。 | 私有 preflight 在 owner admission/clone 前预留有界 learner request、receipt、canonical/index scratch 和已知最小操作预算，reservation 跨 dispatch/plan drop 保留。2 个早拒绝顺序回归。未知 crypto 成本和全 ledger 历史容量没有被虚构成已计量。 |
| R3-04 | evaluated ranker 只核 CURRENT trust 摘要，缓存的真实 head 可已经过期；CURRENT signer 窗口与已知撤销未重验。 | 每次 admission、consume 和最终 guard 检查真实 opaque CURRENT head、signer 到期/已知撤销、verified floor。CURRENT 失败或已观察过期不能回拨复活。 |
| R3-05 | ranker snapshot 不保留 root-admitted trust；冻结 host now 或操作期间 root 过期可以继续消费。 | `RankerAdmissionSnapshotV2::new` 需要真实 `ActivatedLearningTrustV1`，保留精确 root distribution；每个 guard 用共享 host/monotonic 有效时间重新验证，root/epoch/runtime/distribution 变化需显式 reload。没有 bare verifier 回退。 |
| R3-06 | 排序计算后真实 item 重排发生在最终 guard 之外，错误可能留下部分变更；复制完整内容也扩大容量和 guard 后耗时。 | 在 guarded consume 内执行原位 numeric permutation transaction，最多保留 1023 个 undo swap。错误或 unwind 恢复原 item 顺序、字节、指针和容量；成功仅清空数字 tracking。限制 1024 items、单项 64KiB，与真实 store 边界一致。新增 ranker 回归合计 6 个。 |
| R3-07 | 旧 head 的 hosted owner/Linux/macOS CI 编译失败：新测试引用 Agentd 未声明的 `pretty_assertions`。后续本地 operator 测试构建又发现 3 处相同错误。 | 共 5 处改用标准断言，不增加依赖、不改 lock/Bazel 锁。保留旧 hosted raw logs 和本地真实失败；修正后执行实际完整 Agentd build 和测试构建。 |
| R3-08 | hosted native-default 的外部 API probes 在冷缓存下以 offline metadata 失败，缺 cross-target `fiat-crypto`；authoritative synthetic merge 可能有独立新 lock。 | 在 unchanged offline probes 前显式 `cargo fetch --locked`；source 与 synthetic merged lock 各自准备，禁止失败后在线兜底或放宽编译反例。 |
| R3-09 | 新 ranker 安全回归没有进入所有 operator 宿主 CI owner 阶段。 | audit owner、authoritative exact source 和 synthetic merge 三处都增加 `cognitive_ranker` suite，保留 serial 与 `--no-tests=fail`。 |
| R3-10 | 新 main 的 registry/profile/CI 控制与审计分支提取出的 Lane E contract 存在语义冲突；一个旧 legacy writer blob pin 与实际源码不一致。 | 在保留严格类型、外部接受边界、private signed API 和未完成默认循环的前提下，移植 main 的动态 operation/behavior registry 与 lexical export 控制；复核真实默认 feature/import/method 后只更新对应 writer blob pin。 |
| R3-11 | 两条真实 terminal owner 正向集成用例的 root 窗口只有 40µs，真实验证/拟合期间被正确拒绝；短时 source harness 无法代表这条完整宿主路径。 | 仅在该测试文件重签秒级 root、principal 和 evidence，统一缩放学习微秒时间、outcome/watermark；保留未来、来源和撤销拒绝语义。SQLite 与共享授权的 Unix 秒时间、共享 support 和生产门槛不变。 |

`FinalUseClockV1`、preflight、release 逻辑放入私有独立模块；没有扩大公共认证构造 API。新的测试使用真实 owner、root-signed trust、fsync artifact 和选中证据，不以伪造 DTO 替代授权对象，也没有降低科学门槛。

## 完成度与优化优先级

| 层次 | 当前结论 | 剩余工作 |
|---|---|---|
| bounded reference / tabular / discrete world | 已实现并加强算术、预算、签名和最终时间边界 | 仍不等于全部 Holder/Bellman 设计。 |
| 真实 owner fit、selected read、ranker | 已实现组件及真实当前证据 guards | provider 必须刷新未知后续撤销、owner/registry/stop 变化；本地对象不预测未来权威状态。 |
| sealed eval、durable persistence、qualified readonly load | 已有真实 owner API 和组件验收 | 独立真实测量真实性和长期科学接受仍缺，不能仓库自封。 |
| 默认宿主完整循环 | generic coordinator 和部分真实 adapters 已有 | 没有 configured default caller；fresh-process shadow 与 exact durable predecessor rollback 尚未组合成默认完整生命周期。 |
| ProductRunner 信任 bootstrap | 文档已明确实际 caller 缺口 | CLI 仅调用 `AgentdIntelligenceProductRunnerV1::new`，`with_evaluation_trust` 只在测试使用；plasticity V2 bootstrap 不配置 runner。真实路径仍返回 `host learning trust unavailable`，需要独立 pinned root 配置和实际 owner 接线。 |
| canonical transport | sensor/regularity/applicability 三个 untrusted codec 已有 | Bellman exact field schema、semantic enum/member 规范、context-bound native bridges 未完成。 |
| 容量 | learner-owned request/fit/scratch 有界 | LedgerWriter freeze/backend 历史 snapshot/replay 的完整容量与 RSS 是单独 owner 工作；实际目标宿主容量尚未接受。 |
| 科学与部署 | 未完成 | independent efficacy/bounds、真实 one/multi-step calibration、change point、future retention、prediction-error modulation、operator acceptance、canary、promotion、activation/release。 |

算法缺口仍包括 local-model integration、monotone interpolation、antithetic paths、continuous-domain hull/OOD/anisotropic reconstruction、neural branch/state/action trunks、residual amplification/support 与 optimizer 训练控制。本轮优先加强真实 read-only 消费和 owner/currentness/返回边界；后续优先组合有界真实宿主循环与独立测量，再按实际误差证据决定是否扩大神经训练分支。

没有将符号数或测试数换算为完成百分比。`defaultLoopWired=false`、`productExecutionProved=false`、完整 native `canonicalWireAdaptersImplemented=false`；production、科学、目标宿主接受和 activation/release 等状态仍为 false。实现导航可以证明源码/测试位置，不能替代执行收据。

## 实际验证与证据

| 实际检查范围 | 结果 | 边界 |
|---|---|---|
| 完整 Agentd all-target compilation | 通过 | 实际宿主依赖/V8 编译；修正后的 terminal 测试另行真实编译并执行。 |
| operator 默认与兼容 feature | 各 136 passed、2 skipped | 两种配置有重叠，不将测试数相加为独立用例。 |
| 真实 Agentd owner/consumer ports | 35 passed | 实际 Agentd library，无 source harness 替代。 |
| terminal owner | 修正后 2 passed、1 skipped | 初次两个 root-window 失败与原日志保留。 |
| cognitive ranker | 19 passed、1 环境受阻 | 包括本轮 6 个真实 root/CURRENT/rollback 回归；control socket bind EPERM 保留为失败。 |
| sealed product evaluation | 4 passed | 真实封装 qualification 消费，非独立科学接受。 |
| plasticity runtime/bootstrap | 各 3 passed | 真实 library 组件；不泛化为子进程成功。 |
| plasticity child-process E2E | 1 环境受阻 | 实际 binary 已构建并尝试启动，control socket bind EPERM；未跳过或替换该用例。 |
| 六个跨 owner 依赖库 | 654 passed、2 skipped | contracts/types/ledger/artifacts/eval/intelligence，实际 scoped unit suites。 |
| canonical JSON 三个统一 Serde feature | 12 passed | 保留 JSON 类型/排序/内部成员反例。 |
| 独立外部 API consumer | 19/19 | 3 正向与 16 compile-fail，锁与依赖 pins 保持。 |
| operator 默认/compat all-target strict Clippy | 两者通过 | `-D warnings`，不把其他 owner 既有 warnings 清零。 |
| evidence/Lane E/registry/profile/V8 Python | 27/15/8/7/6 通过 | 真实控制、类型篡改、动态 registry 和 resolver 回归。 |
| scoped just fix、最终格式 | 通过；仅一处既有测试冗余借用机械修复，生产代码无 delta | fixer 的源前后 delta 和原始输出单独保留；遵守仓库不在 fmt/fix 后重复已通过测试的要求。 |

验证清单记录真实 argv、cwd、时间、exit、日志 SHA256 和 at-run 输入前后哈希。源清单覆盖约 4685 个 Rust/TOML/lock 输入及实际 test/formatter/V8 控制；该运行清单的覆盖与 exact-source qualification projection 的全部 source/control objects 是不同事实。

保留所有真实失败和环境事件：旧 hosted CI 的 imports/offline failures；首次完整 Agentd check 因运行视图的 live-target 路径变化失败；随后成功的 check；一次用未导入临时 marker 在阶段边界暂停的环境调整；operator 新测试 imports 的实际失败与修正后重新构建；terminal 正向夹具微秒有效期导致真实 root 过期拒绝；本机 control Unix socket bind 的 EPERM 环境阻塞。没有把退出成功但带临时输入 delta 的 controlled-pause attempt 当成最终 clean qualification。

私有 pinned Rust 1.95 工具链经 2502 文件逐字节 SHA256 验证；V8 archive/binding 使用现有 checksum resolver，native cmake/pkgconf 和 OpenSSL 路径实际执行。清理的仅是已归档、无活跃 Rust 引用、可重建的旧 build/toolchain cache；没有删除源码、原始日志或审计报告。全 workspace、完整 Bazel 和独立目标宿主/科学资格没有由这些 scoped tests 替代。

已刷新 11 个确有源码/文档漂移的实现地图，以及 plasticity 的对应机器状态；另外 3 个选中地图没有差异，未机械改动。operator 地图仍保留 56 个已审查操作及全部 false 接受/完成度状态，补充本轮私有委托与 18 个回归位置。初始 clean 导航提交 `c6b885b9eb78df4235fe6768c6b746548f226578` 下的 operator projection、文档契约与 Lane E closure 通过；final fixer 后的 clean 导航提交 `d46c0e624889bd69c937d6a9c0f66fcf58e28b05` 再次通过 operator exact-source projection emit/verify、文档契约及 development 文档导航，绑定 107 个精确 Git source/control objects；closure 仍明确 `repositoryIntegrationComplete=false`。

全仓库严格文档/地图 qualification 仍受最新 main 带入的历史分支锚点阻塞。已实际 fetch `8914a46dfc5984532f03dd2d559bf547ca4f1e69` 和 `e8e81b7d541a81e75635cc1c0a713edaedb999d5` 并核验其 tree；两者与当前候选都非祖先关系。受影响的 9 个模块为 runtime.codex、inference.control、objective.compiler、utility.ndu、cognitive.read、memory.federation、automation.taskflow、control.runtime、control.engineering。缺对象的初次失败与 fetch 后真实 ancestry 结果分别保留；不通过重写来源或继承旧 execution claims 伪造全仓库 qualification。普通 development profile 的 40 模块/40 文档导航验证通过；严格资格的祖先检查失败结果单独记录，不混用两者。

## 收敛边界

本轮可复现的工程 finding 已对应修复和反例；独立 core reviewer 复核前跳时钟、preflight 与 outer release，集成 reviewer 复核 root/CURRENT、真实 item 重排及失败回滚。最后审查在上述已实现的有界范围内没有新增可复现工程缺陷。这是当前代码与证据的收敛结论，不是“整个模块 100% 完成”或“以后不会再有优化”。

默认完整循环、实际 ProductRunner root bootstrap、native Bellman wire 规范、backend 历史容量及独立科学/目标宿主接受是仍然明确的后续工程与验收项；未具备真实配置或独立权威时不构造假 owner、fake clock/measurement/acceptance 来清空这些项。PR 保持 draft，不合并 main、不部署、不改变 authority 状态。报告发布时，当前候选的 hosted CI 尚待观察，单独标为 pending；原 head 的失败及新 head 的后续运行不能拼接成成功资格。
