# 项目发展方向与当前执行计划 V3

**项目当前最优先的交付是一条由真实正常入口驱动、跨平台可验收、权限与效果可追踪的Hepta垂直流程。** 40模块、91工作包的方向已经齐备；当前瓶颈集中在整合候选的原平台验收、Windows严格删除边界和Root/Current到真实caller的最后接线。继续按这些具体门推进，避免从大量Draft/局部测试数推导产品完成度。

本计划以主产品5b/treeb265为基准，canonical五文件与固定ff72源逐blob一致，候选e78只改Core/musl两路径，未改项目方向。原23项仍8限定闭合、14OPEN、1科学HOLD；完整最新执行事实见[进度V5](CONTINUATION_PROGRESS_V5.zh-CN.md)。本文件更新执行安排；原canonical文档维持原身份与职责。[五文档精确桥接](reviews/canonical-product-direction-bridge-v1.json)

## 1. 项目全局结构和实际成熟度

已核canonical范围为40模块、205接口合同、58协议、67领域、91工作包。91工作包中25为source_implemented、20为execution_pending、2为semantic_pending、43为planned、1为external。source_implemented描述源码存在状态，不等于产品接受通过；模块中production_implementation=false是声明边界，也不等于仓库没有生产代码。不得用25/91或当前job成功率作为项目完成百分比。

| 实现线 | 模块 / 工作包 | 后续交付重点 | 必须取得的接受 |
|---|---:|---|---|
| Foundation | 7 / 14 | authority、身份、协议、Registry/arg0、继承资源与保护存储 | 同源Root handoff、权限拒绝、取消/重启/资源托管及物理效果 |
| Runtime | 11 / 19 | Agentd装配、Codex会话和工具、监督、Queue/Lease、上下文与外部效果 | 原平台恢复/终态合同、exact owner/fence、正常caller而非shadow |
| Memory | 9 / 13 | 当前指针/不可变revision、三池/恢复checkpoint、投影和事务可用性 | 真实Current、提交否决后的连接复用、取消仍持锁及重启一致性 |
| Objective | 3 / 7 | 签名目标、FinalUse、计划与任务装配 | 真实issuer、目标期限/撤销、独立provider/target效果 |
| Learning | 4 / 14 | 只读因果shadow、参数记忆、模型改进和回退 | 事前冻结独立数据、充分精度、完整失败/成本；原D−B科学门 |
| Adaptive | 5 / 12 | 资源调度、可塑性、环境和工程反馈 | 固定预算、多规模负载、质量/尾延迟/成本与回滚 |
| Engineering | 1 / 12 | CI、构建、跨平台资格、证据与交付 | 同head/base/merge全量门、可复现完整原件、真实发布接受 |

Codex AppServer继续拥有session/thread/turn、模型和工具执行；Agentd负责Hepta装配、生命周期和组合。优化、学习、shadow admission不能自行扩大authority。正常入口主线保持`P0.8D-VERTICAL-SLICE`和`INT-2-AGENTD-CODEX-COMPOSITION`：UI/API → Objective → 有界Memory/Context → Agentd → Codex执行 → 可观察且可恢复的终态。

全库原始清点在03:16–03:24 UTC完成：1103 open PR（1079 Draft/24非Draft）、5193 branches；155个PR以main为base、948个不以main为base；最大祖先跨度211。后续13:37的bounded增量和新#4884等记录分别留存，不能把初始人口统计伪装成实时总数。大量并行分支意味着整合、合同和来源管理的成本已经成为实际工程问题。[完整审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)

## 2. 当前阻塞的依赖顺序

| 批次 | 当前实际状态 | 下一具体动作 | 完成标准 |
|---|---|---|---|
| A：当前失败归因/最小修复 | e78隔离原例已PASS，owning仍5个输出失败、parallel仍1个用户记录超时 | 取得当前host startup来源；审最窄测试环境隔离；给恢复树fixture本地provider并保原5秒/真实事件 | 原断言与业务合同不变，原失败链可解释，owning和同进程parallel一次实际通过 |
| B：冷构建与full | C0完成，C1因29.9GB可用内存低于32GiB未执行 | 一次只读容量/身份复核，审C1-only续接；不清缓存、不抢未知进程 | 原七helper构建成功、完整source/index/locks/SDK终态一致；然后才启用C2原full |
| C：遗漏的feature范围 | 53个remaining原名字在default full，B13第九个不在 | full实际通过后、hygiene前一次运行原3个Agentd qualification_例 | 真实一次执行全部3名及对应feature；不以1＋3重复凑PASS |
| D：hygiene与发布树 | e78未执行fix/fmt | 原测试门齐全后scoped fix→fmt；不再本地重测；保存最终树 | 最终提交/普通index/锁可追溯，实际head与CI消费源码一致 |
| E：原平台和main | 5b仍2FAIL、1cancel、14Q；新B11诊断queued | 收齐真实原平台，修复具体失败；完成目标main更新与实际merge核验 | 原required全部成功，原负控有效，无缺失/early-return伪装业务PASS |
| F：Windows严格隔离 | 现token外部delete允许；#4884探针待实测 | 读8物理行和原5控制，选择满足read/合法write/外部delete拒绝的最小生产接口 | 原攻击/权限/文件系统所有合同真实Windows通过；探针本身不构成闭合 |
| G：正常产品入口 | Foundation限定范围QUALIFIED；driver状态UNKNOWN | 先解决可归属任务身份；随后driver→pool→checkpoint→owning，独立推进Current/normal caller代码 | 真Root/Session/签名Objective/provider/target任务、取消、丢ACK、重启的实际效果一致 |

这些批次以实际前序终态推进，不能预报资源或CI何时完成。A/B/F可并行准备，C/D/E有明确前置；G不得把另一任务的build通过当作自己的driver完成。原full包含193workspace成员/1501解析节点与原19563目录项的范围应按实际catalog再核，不能以selected/project catalog替换。

## 3. 23项blocker逐项工作清单

以下原退出条件从冻结ledger逐字带入；新增证据只更新进度。限定闭合的八项维护已达范围，相关代码没有变化时不为增加计数重复执行。

| ID | 当前分类 / 范围 | 下一动作或维护重点 | 原退出条件 |
|---|---|---|---|
| B01 | CLOSED_SCOPED / 仓库与证据清单 | 维护固定时点的全分页、refs和增量，不以最新小窗口改写全库总数。 | 固定时间、固定 refs、无分页缺口、完整机器可读清单。 |
| B02 | OPEN / 单一整合候选 | 收敛主候选，完成A–E；新诊断分支只供取证，审完逐路径回入。 | 逐路径决定保留/合入/延期；manifest、vendor、Cargo 与 Bazel 锁同步；固定候选 head、目标 base 与执行 merge tree；原始必需 CI 全通过。 |
| B03 | CLOSED_SCOPED / cwd 展示语义 | 保持cwd展示与canonical路径原合同，原7例范围不扩张。 | 已满足该原始回归范围；不自动代表整个 Core 或 main 资格通过。 |
| B04 | CLOSED_SCOPED / 认知投影 oracle | 保持投影revision/current、更正/删除/重启，新的事务资格独立验收。 | 已满足修复后的原产品目标；生产投影协议保持不变。 |
| B05 | CLOSED_SCOPED / supervisord 子进程定位 | 保持绝对helper/runfile定位，真实RPC失败按其阶段处理。 | 已满足原目标的子进程执行断言；不以脚本存在代替真实启动。 |
| B06 | CLOSED_SCOPED / 正向私有路径夹具 | 保持原正向权限前置及负控，平台不适用继续显式记录。 | 原 macOS / Windows 对应正向用例通过，原负控维持通过。 |
| B07 | OPEN / Hook 元数据与工具可见性 | 用默认full覆盖22个Core integration＋6个MCP原名并保负控。 | binding、原 Hook executor、MCP、TokenBudget 用例通过；未配置 server、allow/deny list、环境错配和陈旧目录负控均拒绝。 |
| B08 | OPEN / 私有 attempted tool 元数据 | 补remaining Core integration原名和namespaced/wire/replay合同。 | 实际 prompt 已附加的内部 retained calls 与真实 output 对应、原 exact calls 断言通过；非官方 wire 无私有字段；不改变生产持久化。 |
| B09 | OPEN / 终态清理与恢复 | 补Core/AppServer（含8个turn_recover）原名及原panic/cancel/watchdog负控。 | 原注入、idle-steer、suspension、8 个 turn_recover 原用例（含特性门负控）和 panic/cancel/watchdog 负控通过。 |
| B10 | OPEN / WebSocket / prewarm / compact | 保持连接/请求/身份/工具语义，修复fixture的外部依赖须单独解释。 | 原连接数、请求数、工具/模型/工作区断言通过；身份变化的拒绝和重连边界保留。 |
| B11 | OPEN / Windows 原生 sandbox 与 helper | 读取#4884原目标和8物理行，设计最小满足合法read/write及outside拒绝的生产修复。 | 在获准的修复范围内提供原生 helper 与原严格 token 契约，原攻击/权限/文件系统用例全部通过；需要超出已允许边界时明确升级审批。 |
| B12 | CLOSED_SCOPED / Windows 私有目录冻结对照 | 保存53例新补证、两冻结负控和恢复，不借此关闭严格delete。 | 不改生产代码和攻击断言；重建当前源的两个负控，正向 2/2、两负控各精确 1 fail + 1 pass、真实文件系统观察和干净恢复全部成立。 |
| B13 | OPEN / Lease / Queue 时序夹具 | 保8个Queue原名PASS，补qualification feature的Agentd第九门。 | 原过期、quarantine、guardian、release=0、单发送及重启不重放断言全保留并在原平台通过。 |
| B14 | CLOSED_SCOPED / Windows exec 恢复清理开销 | 保持原90秒及source/merge13resume范围；新head各388范围分列。 | 保持原 90 秒限制和业务/清理断言，解决真实临时 runtime 开销；原 source 与 merge 的 13 例全部通过。 |
| B15 | OPEN / 最终 CI 与 main 资格 | 收齐实际full/hygiene/平台和main merge，不把排队、取消或no-run计业务PASS。 | 最新候选所有必需工作流终态成功；目标 main 基线重新核实；合成 merge 与发布 commit 树一致；保留原失败和修复回执。 |
| B16 | OPEN / 可信产品入口及外部效果 | 按driver→pool→checkpoint→owning→Current/FinalUse→normal UI推进；旧driver未知先解身份。 | 先完整迁移并验收Root handoff、Registry/arg0、protected checkpoint/verifier、FinalUse/issuer、listener custody和一个真实正常UI caller；再由同源实际Root/Session、原signed objective、provider/target完成任务/取消/丢ACK/重启，保留物理效果、authority、evidence、Memory一致性回执。 |
| B17 | CLOSED_SCOPED / #4578 缺失确认终稿 | 保已交终稿及全部失败/成本未知，不重训暴露确认集。 | 缺失报告与结果失真问题已完成；原研究分支全部工程 CI、科学采用门槛不因此闭合。 |
| B18 | SCIENTIFIC_HOLD / 解析核心 / 参数记忆科学采用 | 维持HOLD和强普通默认；新实验先冻结独立D−B输入/精度/成本。 | 新的事前冻结 2×2 比较，重点 D−B；独立数据、充分精度、全部失败尝试与完整成本；未通过就保留强普通默认而非追求事后绿色。 |
| B19 | OPEN / HeptaBao / Chain / HIA 外部接受 | Bao/Chain/HIA分别接真实外部版本、consumer和签名/撤销故障接受。 | 固定外部版本、接口与契约、兼容/故障/安全回执，以及本产品真实调用者的独立接受。 |
| B20 | OPEN / 远程控制握手夹具 | 补同源原19握手/EOF与实际AppServer断连，早退不算执行。 | 确定性旧源同握手错误、新源对照及原真实AppServer关闭/断连断言全部通过。 |
| B21 | OPEN / macOS Intel PTY退出和输出 | 原Intel30例与drain/child/FD/2秒5秒门；ARM recovery不可替代。 | 保持原2秒/5秒预算、完整drain与child退出/FD断言；修复源在原macOS Intel的30例与相关原CI通过，并解释实际Intel drain失败原因。 |
| B22 | OPEN / TUI 中断与退出顺序 | 原Windows13个interrupt/shutdown名字及负控，真实stdout-ready/5秒不变。 | 定位真实turn/interrupt与关闭顺序，保留原断言和时间预算，以固定修复源的原用例/有效负控及原WindowsCI验收。 |
| B23 | OPEN / App Server Unix关闭信号生命周期 | 原Unix3signal＋2drain、stdio/disabled同源CI；保原真实丢信号反例。 | 真实baseline丢信号窗口成立；修后3个单信号父测试与2个原drain用例通过；配置关闭/stdio及平台语义不变，最终原CI验收。 |

## 4. 正常产品入口要完成的接线

Foundation的限定QUALIFIED证明了native连接生命周期、custody、取消、SQLite提交门与物理锁的原范围。它没有签发Current，也没有替代Root来源和真实caller。旧driver调用结果未知必须按原key与可归属身份解决，不能猜PID、改key重复执行或将无owned文件等价为未启动。

| 接线 | 代码与控制可以继续推进 | 必须取得的真实接受 |
|---|---|---|
| 继承资源 → Root checkpoint transport | R2f1三路径/386新增候选的原编译与控制；FD/CLOEXEC、同步preflight与异步runtime注册分离 | 独立Root来源、host namespace、UID/PID/boot+birth/pidfd以及父死亡/错误lane拒绝 |
| checkpoint → Current | 私有binder验证完整head CAS、继任、owner、epoch/generation、期限/撤销、独立floor/exact cut | 有权authority提供真实当前材料；可解码receipt或本地签名不自行产生权限 |
| Current → 三池与恢复writer | 两个state/Memory pool与private recovery checkpoint绑定同一cut/owner；取消/替换/借出事务生命周期 | 真实SQLite所有受管写路径与跨进程/重启一致性，不能只靠池内门 |
| writer → original_sender → ACK | 保bootstrap ACK、普通peer gate、exact duplicate比较、不同效果ACK各自语义 | 重复提交/取消/丢ACK/重启后的真实效果与authority/evidence/Memory一致 |
| signed Objective / FinalUse → effect entry | 接实际issuer、scope/session、期限/撤销及单次进入；generation漂移拒绝 | 真实provider/target接受；shadow admission、SSH权限不授予FinalUse |
| listener custody → normal UI | 原子发布、目录身份、inode/FD持有、peer与匹配inode cleanup、Registry/arg0/helper、paired Desktop pin | 正常Root→Agentd→Core/Session→UI完成任务与拒绝/恢复，不用临时mock冒充正常入口 |

Memory拒绝COMMIT后的SQLx tracked transaction depth候选，需两个显式入口真实物理红绿：占住其它四连接，第五连接TEMP marker，真实SQLite531否决，证明autocommit与tracked状态分离；修后旧marker消失、读事务恢复、未提交数据不可见，新连接仍被原gate拒绝。候选只有静态资格；已有raw SQL Foundation通过不能补这条Transaction bookkeeping路径。保持默认pool、权限与driver边界，作为独立批次验收。

## 5. 后续发展阶段与优先级

| 阶段 | 交付目标 | 进入下一阶段的判断 |
|---|---|---|
| P0 跨平台基线 | 完成当前A–F，固定可复现候选/完整原件/必需CI | 同源产品回归与原权限合同通过；不以selected或诊断任务代全量 |
| P1 正常垂直流程 | 一条真实UI/API目标到Agentd/Codex的有界任务，终态/取消/恢复都可用 | 实际Root/Current/FinalUse、provider/target、物理效果、Memory回执同链 |
| P2 共享计算与可靠数据 | 明确逻辑Cells、真实并发、队列/Memory/上下文资源和持久化 | 64/256/1024/4096逻辑规模分别报告实测并发、CPU/RSS、p50/p95/p99、queue age、质量/token/完整成本 |
| P3 固定预算shadow | 强普通基线下读取建议、规划与资源分配比较 | 独立预注册数据、预算、公平基线、全部失败；shadow不接生产authority |
| P4 只读因果学习 | 小范围可解释改进、可审证书与受控评估 | 先达到有限组件接受，保独立未来holdout；不把记录重放当新实验 |
| P5 长期学习与回滚 | 学习状态、遗忘/撤销、恢复、不可复活 | 漂移/污染/删除负控、回退到强普通默认、长期成本可算 |
| P6 可塑性与工程自迭代 | 经审查的模块/调度/工程候选生成与验证 | 独立评价、受控变更范围、可靠回滚；优化不自授执行权 |
| P7 具身与物理目标 | 真实环境的窄域任务与安全边界 | 明确真实传感/动作/目标接受，不由模拟分数外推 |
| P8 外部系统兼容 | Bao/Chain/HIA按固定版本、接口与消费者渐进接入 | Bao真实consumer、Chain/WAN故障、HIA证书/撤销等分别闭合 |

B18的原科学门始终是新的事前冻结2×2与重点D−B。现有J−C的有限规划正结果、验证拒绝后回退C、工程移植、重放一致性都不能重命名为D−B通过；OOD曾用于VAL、完整成本不足的限制继续保留。已有五fit不是数百世界的新独立fit；CPU/F32小模型也不能外推BF16/vLLM生产接受。新的研究采用独立未来数据和完整成本记录，未经采用门维持强普通默认。

## 6. 执行纪律、进度汇报与完成定义

每次集成只按真实路径差异和依赖接受，保reviewed ancestry，避免整包导入donor旧计划。#4855等donor已有通过必须取得自己的原raw与同源接受，不能借正文数字给本产品晋升。native任务仅操作可归属owned目录；资源门临近失效时停止启动，保已有证据与缓存。

每批报告应有固定head/tree、原target与名字、selected/ignored/early-return、attempt/cache、有效负控、精确恢复与最终守卫。JUnit PASS与真实业务到达分开；compile/link-only与test execution分开；同一名字跨source/merge/feature重复执行不变成多个独立定义。

全部blocker闭合的定义是原23项各自达到原退出条件，包括真实产品与外部接受，且新整合树通过required gates。当前尚未达到；资源前置、排队、任务身份未知与科学HOLD都有具体记录，不会靠删项、松断言、改退出条件或虚构证据消除。

### 固定来源

- [全量仓库审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)与[当前23项ledger](continuation-blocker-progress-v4.json)
- [当前执行进度V5](CONTINUATION_PROGRESS_V5.zh-CN.md)与[此前详细技术计划V2](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V2.zh-CN.md)
- [canonical五文件同源桥接](reviews/canonical-product-direction-bridge-v1.json)与[原退出选择清单](reviews/original-exit-selection-5b/selection-checklist.json)
- [完整新增CI原件](generated-evidence/ci-5b633-unix-recovery-objective-v6/transport-manifest.json)、[recovery/UI](generated-evidence/ci-5b633-recovery-ui-v6/transport-manifest.json)、[最新0060–0063原API及当前终态观察](generated-evidence/current-outcomes-cut0063-v6/transport-manifest.json)
- [主产品Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)与[B11诊断Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)

## B11原生编译增量与已发布纠错

初始诊断headf02b9ae的真实Windows job127320081049于14:56:49结束failure：既有`unified_exec/delete_permission_tests.rs`有8处`assert_eq!`宏导入歧义E0659，测试尚未开始。原完整log和11成员ZIP保留。修复只新增同一`pretty_assertions::assert_eq`显式导入，删除该34字节行即逐字恢复原文件；八条断言、生产权限与预算不变。workflow另增加该既有文件的触发路径，保证纠错实际进入同一原目标。

纠错已发布至同一Draft #4884，第4commit **`0d65de9bf1e28a7b313a344ebba71ba8378d0f5a`**，tree **`f13680916b9a7f773dcc95e4ce6ee6785021ead4`**，相对5b总5路径/+607−0。fresh PR/ref读取已确认，主#4797未变；新的原Windows结果待取得。上文初始4路径/3commit/排队状态均为其明确历史阶段，不代表最新head已通过。[纠错精确发布收据](reviews/b11-macro-correction-publication-v1.json)
