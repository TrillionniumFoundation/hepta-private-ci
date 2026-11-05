# 项目发展方向与当前执行计划 V4

**项目当前最优先的交付是一条由真实正常入口驱动、跨平台可验收、权限与效果可追踪的Hepta垂直流程。** 40模块、91工作包的方向已经齐备；当前瓶颈集中在整合候选的原平台验收、Windows严格删除边界和Root/Current到真实caller的最后接线。继续按这些具体门推进，避免从大量Draft/局部测试数推导产品完成度。

本计划以已发布主候选 **eed4d6 / ca1** 为执行基准；原canonical五文件仍沿已核固定源逐blob一致。当前23项原blocker为 **10限定闭合、12OPEN、1科学HOLD**，B13/B22的新增闭合由完整原平台证据支持。完整本轮事实见[进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)和[ledger V5](continuation-blocker-progress-v5.json)。本计划保留原退出条件，并纳入16:40:42–16:45:44读取的其他16条活跃PR来源。

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

全库原始清点在03:16–03:24 UTC完成：1103 open PR（1079 Draft/24非Draft）、5193 branches；155个PR以main为base、948个不以main为base；ref名称层级/stack-depth指标211（不是已核commit祖先跨度）。后续13:37的bounded增量和新#4884等记录分别留存，不能把初始人口统计伪装成实时总数。大量并行分支意味着整合、合同和来源管理的成本已经成为实际工程问题。[完整审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)

## 2. 当前阻塞的依赖顺序

| 批次 | 当前实际状态 | 下一具体动作 | 完成标准 |
|---|---|---|---|
| A：已发布14路径 | eed已发布、原Windows分支任务有成功，完整门未终态 | 读每个原失败的当前正文，保source/head/merge和原负控；若再失败仅修已证根因 | 同候选原assertion通过，真实到达业务，错误/skip/retry与早退分别可追 |
| B：Linux完整门 | ai395唯一firststart因可用内存不足32GiB停于源码修改前 | 原64GB磁盘/32GiB内存和全部守卫fresh通过后，对同prepared目录明确启用续接；七helper→完整catalog→无筛选full | 原193成员/1501节点、19563目录项一致；原full实际通过、终态源/锁/SDK一致 |
| C：已补原平台证据 | B13九例与B22十三例已正式CLOSED_SCOPED | 保闭合来源与有效负控；新eed资格继续独立收齐 | 不为旧feature缺证再重复3例，不借旧5b结果给新eed |
| D：最终hygiene | 新组合的full未完成，scoped fix/fmt尚未执行 | 所需原测试门完成后scoped fix→fmt；不在hygiene后追加本地测试 | 真实执行回执、最终源/锁/树与原CI一致 |
| E：原平台和main | 19新workflows已触发，required尚未全绿；仍为Draft | GNU、musl、Darwin/Intel、Windows逐原范围取终态；当前main单独重新绑定及审merge | 必需门全通过；目标base、merge、发布commit身份完整；不跳过当前失败 |
| F：Windows严格隔离 | native5原目标143PASS/10FAIL/2ignored，目录与host控制待修，真实strict外删仍在 | 先修目录ACL同对象句柄及真实无WRITE_DAC控制；同步read授权/owner/后代寿命与真实loader逐项接线 | 原严格token、合法read/write及外部四种写删拒绝全部通过；原host前提独立成立 |
| G：正常产品入口 | Foundation限定范围达标，旧driverUNKNOWN；Current/FinalUse等未闭合 | 按确切任务身份解决driver；复核donor有用源码/物理控制；继续checkpoint→Current→三池→normalUI | 同源真实Root/Session/签名Objective/provider/target完成、取消、丢ACK、重启一致 |

这些批次以实际前序终态推进。A/F/G可并行准备；B/D/E保留严格前置，资源和runner排队不预报完成时间。现有五台Linux没有已确认满足本批原容量门的主机。主机可用权限不等于产品Current/FinalUse授权。

## 3. 23项blocker逐项工作清单

以下原退出条件从冻结ledger逐字带入。十个限定闭合范围保留其证据；十二个开放项和科学HOLD按明确门推进。

| ID | 当前分类 / 范围 | 下一动作或维护重点 | 原退出条件 |
|---|---|---|---|
| B01 | CLOSED_SCOPED / 仓库与证据清单 | 后续发布与新CI继续绑定各自观察时间；不把增量观察冒充全量当前总数。 | 固定时间、固定 refs、无分页缺口、完整机器可读清单。 |
| B02 | OPEN / 单一整合候选 | 保r3 Guardian取消/截止及runtime-scoped Git缓存；最终同一次提交完整源码/锁/证据，验原required CI和合成merge树。 | 逐路径决定保留/合入/延期；manifest、vendor、Cargo 与 Bazel 锁同步；固定候选 head、目标 base 与执行 merge tree；原始必需 CI 全通过。 |
| B03 | CLOSED_SCOPED / cwd 展示语义 | 新整合树保留原语义，若改该代码才触发相应重验。 | 已满足该原始回归范围；不自动代表整个 Core 或 main 资格通过。 |
| B04 | CLOSED_SCOPED / 认知投影 oracle | 保不可变revision/当前指针、来源/更正/删除/重启等原断言；最终产品资格另归B15。 | 已满足修复后的原产品目标；生产投影协议保持不变。 |
| B05 | CLOSED_SCOPED / supervisord 子进程定位 | 新RPC失败由独立诊断记录处理，保原daemon预算和控制fence。 | 已满足原目标的子进程执行断言；不以脚本存在代替真实启动。 |
| B06 | CLOSED_SCOPED / 正向私有路径夹具 | 不得写逐case7/7或零skip/retry；TUI第二批仅按其真实原平台收据更新，不混B22。 | 原 macOS / Windows 对应正向用例通过，原负控维持通过。 |
| B07 | OPEN / Hook 元数据与工具可见性 | 最终候选原Hook/MCP/Executor/TokenBudget及allow/deny、环境错配、陈旧目录控制同源终态通过。 | binding、原 Hook executor、MCP、TokenBudget 用例通过；未配置 server、allow/deny list、环境错配和陈旧目录负控均拒绝。 |
| B08 | OPEN / 私有 attempted tool 元数据 | 在新固定head及merge的原平台执行新增namespaced原例与保留的wire/retained边界；不借B09/B10通过计数。 | 实际 prompt 已附加的内部 retained calls 与真实 output 对应、原 exact calls 断言通过；非官方 wire 无私有字段；不改变生产持久化。 |
| B09 | OPEN / 终态清理与恢复 | 保busy/lineage/exact实例/fence与恢复原负控；最终范围依独立原48映射和本候选原CI。 | 原注入、idle-steer、suspension、8 个 turn_recover 原用例（含特性门负控）和 panic/cancel/watchdog 负控通过。 |
| B10 | OPEN / WebSocket / prewarm / compact | 用同源原turn_state与身份负控验收；不修改production身份或通过放宽请求数获取绿色。 | 原连接数、请求数、工具/模型/工作区断言通过；身份变化的拒绝和重连边界保留。 |
| B11 | OPEN / Windows 原生 sandbox 与 helper | 先读取7e原完整Windows目标，逐个原失败判定；完整限制令牌还须正常有限read根、同步授权完成与全部后代资源寿命，真实loader/合法I/O/外部四种写删/取消接受。 | 在获准的修复范围内提供原生 helper 与原严格 token 契约，原攻击/权限/文件系统用例全部通过；需要超出已允许边界时明确升级审批。 |
| B12 | CLOSED_SCOPED / Windows 私有目录冻结对照 | 保留该scope闭合；不外推一般Windows权限或原strict delete三例。 | 不改生产代码和攻击断言；重建当前源的两个负控，正向 2/2、两负控各精确 1 fail + 1 pass、真实文件系统观察和干净恢复全部成立。 |
| B13 | CLOSED_SCOPED / Lease / Queue 时序夹具 | 保留该原Windows固定源scope；新eed全平台/B15及真实产品入口分别验收，不重复旧三例凑数。 | 原过期、quarantine、guardian、release=0、单发送及重启不重放断言全保留并在原平台通过。 |
| B14 | CLOSED_SCOPED / Windows exec 恢复清理开销 | 保留已完成的原Windows helper前置、source/merge各13恢复例及原业务/清理断言；新最终head的整体平台资格归B15，不重复旧scope以凑通过数。 | 保持原 90 秒限制和业务/清理断言，解决真实临时 runtime 开销；原 source 与 merge 的 13 例全部通过。 |
| B15 | OPEN / 最终 CI 与 main 资格 | 最终精确head、base和merge tree、所有required门、原失败与有效负控齐全；保全部skip/retry/cache/unknown，原48映射独立维护。 | 最新候选所有必需工作流终态成功；目标 main 基线重新核实；合成 merge 与发布 commit 树一致；保留原失败和修复回执。 |
| B16 | OPEN / 可信产品入口及外部效果 | 按独立R1–R6批次实现：arg0基础→trust/Current与inherited合同→Agentd装配→joint consumer→normal producer与paired pin→原真实接受。R0的102决策/474净差不等于编译最小闭包。 | 先完整迁移并验收Root handoff、Registry/arg0、protected checkpoint/verifier、FinalUse/issuer、listener custody和一个真实正常UI caller；再由同源实际Root/Session、原signed objective、provider/target完成任务/取消/丢ACK/重启，保留物理效果、authority、evidence、Memory一致性回执。 |
| B17 | CLOSED_SCOPED / #4578 缺失确认终稿 | 保77b244终稿与冻结903946源、全部失败与成本unknown；不为使结论变绿重训同一确认集。 | 缺失报告与结果失真问题已完成；原研究分支全部工程 CI、科学采用门槛不因此闭合。 |
| B18 | SCIENTIFIC_HOLD / 解析核心 / 参数记忆科学采用 | 保留原D−B采用门与HOLD。J有限规划作为独立有证据的组件继续评估，权重编辑保强普通默认与验证回退；新实验先冻结独立数据、拟合单位、计算成本和全部失败保留，禁止以J−C、原记录重放或移植一致性换名关闭D−B。 | 新的事前冻结 2×2 比较，重点 D−B；独立数据、充分精度、全部失败尝试与完整成本；未通过就保留强普通默认而非追求事后绿色。 |
| B19 | OPEN / HeptaBao / Chain / HIA 外部接受 | 按B19-Bao/B19-Chain/B19-HIA分开取得同源实现与真实目标接受；advisory DENY_ALL/safety_certificate=false保持。 | 固定外部版本、接口与契约、兼容/故障/安全回执，以及本产品真实调用者的独立接受。 |
| B20 | OPEN / 远程控制握手夹具 | 最新候选原19例及原平台CI以精确收据关闭；不得跳过正常HTTP或替代真实握手。 | 确定性旧源同握手错误、新源对照及原真实AppServer关闭/断连断言全部通过。 |
| B21 | OPEN / macOS Intel PTY退出和输出 | 原Intel30例、完整drain/child/FD原断言和2/5秒预算不变；同源因果与原平台结果齐全。 | 保持原2秒/5秒预算、完整drain与child退出/FD断言；修复源在原macOS Intel的30例与相关原CI通过，并解释实际Intel drain失败原因。 |
| B22 | CLOSED_SCOPED / TUI 中断与退出顺序 | 维护该已达scope；最终eed完整平台与main资格继续归B15。 | 定位真实turn/interrupt与关闭顺序，保留原断言和时间预算，以固定修复源的原用例/有效负控及原WindowsCI验收。 |
| B23 | OPEN / App Server Unix关闭信号生命周期 | 同最终source原Unix平台验收；原stdio/disabled语义和drain规则保持；首signal注册失败提前报错属已审兼容差异。 | 真实baseline丢信号窗口成立；修后3个单信号父测试与2个原drain用例通过；配置关闭/stdio及平台语义不变，最终原CI验收。 |

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

## 4A. 其他正在推进的项目线与整合边界

下表来自16:29搜索及16:40:42–16:45:44的fresh PR元数据。源码head是实际读取值；正文中的native数字在本表仅作为**作者已记录的进展**，本轮没有独立复核其全部原件，也不转授主候选资格。16条非本轮PR及原搜索响应完整保存，不能用这批结果改写03:16全库人口统计。

| 项目线 / 固定PR | 实际读取head | 发展方向与下一动作 |
|---|---|---|
| W0–W7整合 [#4855](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4855) | `3a39c799a3f776b0aeedfce350341d865d3cc1c4` | 已发展到50个按序source stages，涉及SQLx拒绝提交后的连接复用、issuer-parent、恢复和Windows原CI。正文仍列完整owner/真实UI/外部效果OPEN。按文件和依赖复核可用donor，不整包替换当前主候选。 |
| P0/P1与原CI [#4853](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4853)、[#4843](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4843) | `a3182a76…` / `7504ab32…` | 保其原44失败与图像、OpenSSH、WebSocket、恢复的实际来源；full原平台和干净镜像消费未全部通过。当前#4797只是其部分donor，不能循环借证。 |
| 40模块恢复 [#4869](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4869) → [#4888](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4888) → [#4891](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4891) | `f5813506…` → `bb55b0d7…` → `797116d6…` | 从实际1217P/1F/1timeout到作者记录的后继1219P/78skip，再修真实Codespell三字节fixture。最终797尚待自己全scope；40生产旗标仍false、拓扑DENY_ALL，371导航操作不等于371生产能力。 |
| Native Cell / Circuit V2 [#4887](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4887) | `b3d015f92166ee210fdab70a6c172cffc9cf9e61` | 准备/编码、共享模型receipt、合法masked决策、有界反馈和七阶段学习协调。正文明确尚未编译/测试，join物化、无进展与真实训练接线未完；先过原native与生命周期owner，再谈生产采用。 |
| Cell角色与分化 [#4890](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4890) | `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b` | 七功能角色与两支持类别，分别统计能力类型、expert版本、状态owner、活跃instance；六arm公平对照及迁移。30Rust/24Python是已编写控制，不是通过数；保持独立接受。 |
| Memory V15 [#4885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4885) / 标识符活性 [#4889](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4889) | `f88b826d…` / `31880a58…` | 固定真实成本/预算、隔离executor、拒绝事后协议改写；后者处理NULL/UTF8标识符使prepared不可恢复的真实缺陷。作者记录33/33及1600/1600对照；生产Control、持久实验预留、完整模型迁移和poisoned DB恢复仍需独立方案。 |
| 普通PQ外部效果 [#4877](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4877) | `9e9eaad62463f78882f986c8e90981986b4cdb89` | 170局部通过与1个真实Chain失败同时保留。正文指出最小包49,508B已超过原24,576B入口，hex99,016B超过65,536B控制帧；先做有界版本化大payload接口与双端接受，不能只抬阈值或裁包使门绿。 |
| R6观察终止 [#4870](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4870) | `bfdf51e19efdfd38f6f6825372e81a790ed40c90` | 有界真实进程终止、同manager清理、writer handoff与原CI输入；局部Operator33通过不替代被取消的完整Windows或legacy外删/LEAK缺口。 |
| HIA/NDU重复JSON [#4882](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4882) | `b8aaa6cca885b3022d0a647a9a878d211b49fe5b` | 拒绝顶层/嵌套重复字段并保收费/拒绝回执，原14+新3控制待同head CI；raw PIPE无界、真实模型/独立评价仍OPEN，DENY_ALL保持。 |
| HCSN研究 [#4873](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4873) | 当前`fe1def4a…`；正文结果源`28a61d14…` | 必须先解释最新head与正文旧源差异。CPU严格95例和45/48完成smoke不代170个CUDA任务；原弱B结果、分辨率误差、缺物理能耗继续公开。与原B18的D−B采用门分别评价。 |

还读取了[#4883](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4883)的精确60处Windows格式修补和[#4881](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4881)的ConPTY错误修补，它们仍HOLD；格式或编译前置通过不改变产品权限合同。所有整合按固定source、真实依赖和原测试逐路径进行。

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

- [全量仓库审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)与[当前23项ledger](continuation-blocker-progress-v5.json)
- [当前执行进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)与[此前详细技术计划V2](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V2.zh-CN.md)
- [canonical五文件同源桥接](reviews/canonical-product-direction-bridge-v1.json)与[原退出选择清单](reviews/original-exit-selection-5b/selection-checklist.json)
- [完整新增CI原件](generated-evidence/ci-5b633-unix-recovery-objective-v6/transport-manifest.json)、[recovery/UI](generated-evidence/ci-5b633-recovery-ui-v6/transport-manifest.json)、[最新0060–0063原API及当前终态观察](generated-evidence/current-outcomes-cut0063-v6/transport-manifest.json)
- [主产品Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)与[B11诊断Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)

## B11最新发布与历史结果

初始f02编译8E0659、后继0d65/c05的真实测试失败与label观察、3a407的8行物理机制结果均保留。当前最新为7e四路径ACL候选；主产品已经eed，实际merge582f具有两条正确父源。原Windows目标已实际143PASS/10FAIL/2ignored；两个目录错误5、host权限前提和真实strict外删继续推进。详细原始计数、分类与边界见[进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)及[精确发布回执](reviews/b11-acl-four-path-publication-v1.json)。

## 新增可复用依据与仍需完成的门

SQLx拒绝提交后连接复用的donor现在已有完整既存native红绿原件，由[独审](reviews/pr4855-refused-commit-reuse/REVIEW.zh-CN.md)核过；可复用机制与该范围原控制。本候选的两个独立构造器、物理换连接、精确531与native custody仍按原门执行。新eed Windows Core完整库2,340PASS/3ignored、retained三库532PASS以及GitQueue source/merge的逐名范围已由原件验证。它们缩小剩余验证范围，但不代替未执行的Unix integration、Intel PTY或默认全工作区；具体后续结果见[进度第7节](CONTINUATION_PROGRESS_V6.zh-CN.md)。
