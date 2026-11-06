# 项目发展方向与当前执行计划 V7

**当前应交付的主线是：正常 UI/API 接收真实目标，经明确授权、可靠 Memory 和 Agentd/Codex 执行，产生可核实、可取消、可恢复的实际效果。** 项目已有大量实现与局部原生验证；完整跨平台产品资格、Windows 严格外部权限边界和正常授权入口仍是交付瓶颈。

原23项 blocker 累计为 **16项限定范围闭合、6项开放、1项科学验证暂停**。本版仅B23按原退出条件新增闭合，原23项ID和字面退出条件逐项保留。B23的独立fresh GNU结果与最终原GNU CI形成两条接受链；诊断收件失败和其它平台失败均未被改绿。完整 ledger 见[当前机器清单](continuation-blocker-progress-v8.json)，本轮证据索引见[evidence-index-v10-registered.json](evidence-index-v10-registered.json)。本文为固定来源和有界观察窗的项目计划，不能把历史全库清点或单个通过的诊断任务当成实时全库/产品完成率。

主产品固定在67cc/3982；Windows权限诊断为daa21e7a/fbaf12d5；Intel/GNU收件修补当前分别为84cc7345/tree45858bc9与2ac89eaf/tree9a6fd02a；其原终态仍绑定ebd31e2b/46fca3e6与e63ed76c/a6831e26。Windows原因链原生证据属于340fbc06/78b817fe，其当前格式修补head为18bbef4f/treed611fe96；cargo-deny留存修补为476653f8/06c4e2f8，arg0 clippy修补为3c9e2bba/e60df9b5。主产品PR4797的实际base是integration/ui-objective-20261103-product/63652be6；这些后续支线的base都是fix/r3-original-product-contracts-20261104/67cc。实际默认main仍为732e934b/tree75dc1c1f，未把整合分支或诊断支线记成已合入main。各切点时间、完整/部分job分母与最新状态见第6节和机器台账current_v10。

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

当前元数据采用2026-11-06两份完整REST遍历。03:31:39–03:35:10的开放PR普查取得3555个不同PR（3506 Draft/49非Draft），360个以main为base、3195个使用其它base，共2220个base ref；35页各100条、第36页55条、第37页为空。首末成员与次序一致，#4907的head/merge/更新时间在末锚发生变化，原值和新值均保留。03:42:06–03:43:26的branches普查取得5333个不同名称、4946个不同commit：前53页各100、第54页33、第55–58页为空，首/末/空页锚正文逐字节相同。窗口之后新增的修补分支由各自发布回执记录，不能把该数称为随后实时总数。[PR完整包](repository-metadata/open-pr-census-20261106T0331/registry.actual.json)；[分支完整包](repository-metadata/branches-census-20261106T0342/registry.actual.json)。

旧2026-11-05观察报告1103开放PR、5193分支。实际旧摘要已完整读回：1103个PR全部包含于新清单，但2452差额中只有88条创建于旧上界之后，2364条的更新时间早于或等于旧上界。旧摘要声明相同查询参数、连续分页及空终页；本轮未重开旧原始分页归档，因此差异原因仍UNKNOWN，不能称作一天新增2452个PR，也不能擅断为旧filter或分页错误。旧名称层级211不是commit祖先跨度，保留在历史报告中。[旧摘要窄补审](repository-metadata/open-pr-census-20261106T0331/OLD_SUMMARY_REVIEW.json)。

上述是完整已取分页的元数据与ref清单；首末锚不能排除中间页并发变化，也不等于逐行审阅3555个PR的源码与原生结果。架构结论来自同源canonical文件，实际接受来自指定目标的原件。大量非main整合分支和Draft使来源、合同、可合入顺序成为当前主要工程成本。

## 2. 当前交付瓶颈及推进顺序

| 工作线 | 已实际验证的进展 | 仍缺的结果 | 下一步 |
|---|---|---|---|
| 单一整合候选 B02/B15 | 67cc相对父源3路径、相对5b累计15路径；最新完整93job、历史六原ZIP与失败动作已绑定；B23原范围已闭合 | cargo-deny新unmaintained、Windows Core/Queue/sandbox、Intel PTY、MacARM两目标和原GNU clippy失败；最终required仍缺 | 整合原Clippy已成功的arg0修补，按实际依赖及平台失败原件继续修复，再整合一个精确候选核required |
| Windows严格权限 B11 | native13宿主Neither控制已正确拒绝，四原正控、物理负控、精确还原和21helper均可复核 | strict/legacy ParentOnly与Both仍实际删除；whole147P/7F/2I | 需要在真实对象I/O边界执行不可绕过的授权；现有无路径/操作输入的token工厂未提供完整局部修复。新实现须保原ambient read、inside I/O、外部四类拒绝及后代寿命 |
| Intel PTY B21 | 原单target31P保留；两个完整上下文实际30P/1F，新增partial drain/errno观察 | 4MiB drain/child退出在原期限内成立及实际失败因果 | 以已保留原件定位reader/child调度或I/O边界，维护原2秒/5秒、完整目标/默认retry；收件修补另验 |
| Linux信号 B23 | 原因果及5例历史接受、fresh GNU 8shard307P/1I与原main GNU完整CI成功已独审；仅B23闭合 | 原范围已满足；whole B15及收件器缺件仍独立保留 | 维护原stdio/disabled/平台语义；不得把新的XML/收件绿色条件追加入原产品退出 |
| Linux默认full B02/B15 | 原19563用例清单（19506eligible/57ignored）和固定准备入口已有；首次执行在编译前被原RAM门拒绝 | 满足64GB磁盘/32GiB RAM/jobs4的真实容量证据和完整终态 | 新容量依据到位后才续接原入口；未因另一个GitHub runner成功而宣称该主机达标，不重复探测或降门 |
| 正常产品入口 B16 | Foundation限定原生接受、Root/FinalUse等并行源码接线已有 | 真实Root/Current/issuer/provider/正常UI的完整接受与旧driver确定身份 | 按Root→Current→受保护writer→FinalUse→listener→正常caller逐段整合；每段取得其原负控及物理回执 |
| 外部系统 B19 | 固定Hepta/Chain packet-v1两端路径已实现并完成源码窄审 | 固定配对原生、可信binary来源、真实consumer及Bao/HIA各自接受 | 恢复精确配对构建/执行原件，再接普通授权入口；不同外部系统分别关闭 |
| 科学采用 B18 | 报告失真/缺失范围B17已处理，已有有限规划结果保留 | 新事前冻结2×2的D−B、独立数据与完整失败/成本 | 单列科学计划；未过门继续强普通默认，不用工程绿色替换科学结论 |

执行器的原工作目录在恢复期间丢失。已登记的Git对象可完整读回；未登记的Intel863a草稿没有恢复证明，因此按固定输入重新构建并重做静态与反例审查。执行器恢复只证明本地进程能力恢复，不证明私人原生主机容量、Windows产品接受或任何未执行测试已经通过。

## 3. 23项blocker与原退出条件

下表分类和退出条件来自冻结ledger。限定闭合只对应原范围；没有把未取得的平台、真实产品、外部或科学接受移入已关闭项。

| ID | 范围 | 当前分类 | 原退出条件 |
|---|---|---|---|
| B01 | 仓库与证据清单 | CLOSED_SCOPED | 固定时间、固定 refs、无分页缺口、完整机器可读清单。 |
| B02 | 单一整合候选 | OPEN | 逐路径决定保留/合入/延期；manifest、vendor、Cargo 与 Bazel 锁同步；固定候选 head、目标 base 与执行 merge tree；原始必需 CI 全通过。 |
| B03 | cwd 展示语义 | CLOSED_SCOPED | 已满足该原始回归范围；不自动代表整个 Core 或 main 资格通过。 |
| B04 | 认知投影 oracle | CLOSED_SCOPED | 已满足修复后的原产品目标；生产投影协议保持不变。 |
| B05 | supervisord 子进程定位 | CLOSED_SCOPED | 已满足原目标的子进程执行断言；不以脚本存在代替真实启动。 |
| B06 | 正向私有路径夹具 | CLOSED_SCOPED | 原 macOS / Windows 对应正向用例通过，原负控维持通过。 |
| B07 | Hook 元数据与工具可见性 | CLOSED_SCOPED | binding、原 Hook executor、MCP、TokenBudget 用例通过；未配置 server、allow/deny list、环境错配和陈旧目录负控均拒绝。 |
| B08 | 私有 attempted tool 元数据 | CLOSED_SCOPED | 实际 prompt 已附加的内部 retained calls 与真实 output 对应、原 exact calls 断言通过；非官方 wire 无私有字段；不改变生产持久化。 |
| B09 | 终态清理与恢复 | CLOSED_SCOPED | 原注入、idle-steer、suspension、8 个 turn_recover 原用例（含特性门负控）和 panic/cancel/watchdog 负控通过。 |
| B10 | WebSocket / prewarm / compact | CLOSED_SCOPED | 原连接数、请求数、工具/模型/工作区断言通过；身份变化的拒绝和重连边界保留。 |
| B11 | Windows 原生 sandbox 与 helper | OPEN | 在获准的修复范围内提供原生 helper 与原严格 token 契约，原攻击/权限/文件系统用例全部通过；需要超出已允许边界时明确升级审批。 |
| B12 | Windows 私有目录冻结对照 | CLOSED_SCOPED | 不改生产代码和攻击断言；重建当前源的两个负控，正向 2/2、两负控各精确 1 fail + 1 pass、真实文件系统观察和干净恢复全部成立。 |
| B13 | Lease / Queue 时序夹具 | CLOSED_SCOPED | 原过期、quarantine、guardian、release=0、单发送及重启不重放断言全保留并在原平台通过。 |
| B14 | Windows exec 恢复清理开销 | CLOSED_SCOPED | 保持原 90 秒限制和业务/清理断言，解决真实临时 runtime 开销；原 source 与 merge 的 13 例全部通过。 |
| B15 | 最终 CI 与 main 资格 | OPEN | 最新候选所有必需工作流终态成功；目标 main 基线重新核实；合成 merge 与发布 commit 树一致；保留原失败和修复回执。 |
| B16 | 可信产品入口及外部效果 | OPEN | 先完整迁移并验收Root handoff、Registry/arg0、protected checkpoint/verifier、FinalUse/issuer、listener custody和一个真实正常UI caller；再由同源实际Root/Session、原signed objective、provider/target完成任务/取消/丢ACK/重启，保留物理效果、authority、evidence、Memory一致性回执。 |
| B17 | #4578 缺失确认终稿 | CLOSED_SCOPED | 缺失报告与结果失真问题已完成；原研究分支全部工程 CI、科学采用门槛不因此闭合。 |
| B18 | 解析核心 / 参数记忆科学采用 | SCIENTIFIC_HOLD | 新的事前冻结 2×2 比较，重点 D−B；独立数据、充分精度、全部失败尝试与完整成本；未通过就保留强普通默认而非追求事后绿色。 |
| B19 | HeptaBao / Chain / HIA 外部接受 | OPEN | 固定外部版本、接口与契约、兼容/故障/安全回执，以及本产品真实调用者的独立接受。 |
| B20 | 远程控制握手夹具 | CLOSED_SCOPED | 确定性旧源同握手错误、新源对照及原真实AppServer关闭/断连断言全部通过。 |
| B21 | macOS Intel PTY退出和输出 | OPEN | 保持原2秒/5秒预算、完整drain与child退出/FD断言；修复源在原macOS Intel的30例与相关原CI通过，并解释实际Intel drain失败原因。 |
| B22 | TUI 中断与退出顺序 | CLOSED_SCOPED | 定位真实turn/interrupt与关闭顺序，保留原断言和时间预算，以固定修复源的原用例/有效负控及原WindowsCI验收。 |
| B23 | App Server Unix关闭信号生命周期 | CLOSED_SCOPED | 真实baseline丢信号窗口成立；修后3个单信号父测试与2个原drain用例通过；配置关闭/stdio及平台语义不变，最终原CI验收。 |

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

现有Root/FinalUse源码增量不能提供独立authority。最新#4855固定1a2add86已推进到stage88，涉及Root journal、实际FinalUse/Worker路径及原54正控/3负控，但Current/normal Notes/共享writer与CNS CAS、回滚后新进程、90/91物理撤销红绿仍未获得当前独立原生接受。不能将作者正文或另一个候选的通过数累计到主产品。

旧B16 driver在同一个key下三次调用均超时，未取得可归属job身份；现有2463份metadata的五字段不足以补齐该身份。状态继续UNKNOWN。不会第四次重放、改key再执行、猜测PID或从无owned文件推断从未启动。恢复需要原key对应的真实任务身份和终态，或可验证的未启动凭据。

## 4A. 并行项目线：固定来源与整合决策

00:44–00:47增量核对16条固定PR和14条其它PR，共30份完整元数据；7组compare最长95commits/206files，10份固定Hepta源码及协议已读。搜索返回19条且incomplete=false，直接REST两页50条所取bounded union仍多出#4849/#4888/#4891；这批观察不构成新的全库穷尽人口统计，也没有逐行审完全部206文件。完整源与原响应见[增量记录](generated-evidence/concurrent-pr-increment-20261106-0044/INCREMENT.zh-CN.md)。

| 项目线 / PR | 固定来源与本轮进展 | 整合决定及下一步 |
|---|---|---|
| W0–W7 / #4855 | 1a2add869929ef0c1a32f42689359176480b3a1d，stage88，38commits/93paths增量 | 逐路径引入已独立接受的donor；Root/Current/真实UI和撤销门继续开放，保reviewed ancestry |
| P0/P1 / #4843、#4853 | #4843 b60af4fa…增13commits/32paths；原44失败来源继续保留 | 原平台全量和干净镜像消费未完；避免在互相引用的正文间循环借证 |
| 40模块 / #4869→#4888→#4891→#4893 | #4893 865821049970…作者记录1219P/78skip，40 production_implementation仍false、DENY_ALL、merge dirty | 先固定干净整合树并取得其原测试；导航操作数不等于生产能力数 |
| Native Cell / #4887 | bef6fa7645df9df12b69fda499e97eed25de6c75，新110个测试定义，0次本轮执行，DENY_ALL | 编译、原native和生命周期owner优先；尚未取得训练采用证据 |
| Cell角色 / #4890 | 七功能角色/两支持类别，区分能力类型、expert版本、state owner和活跃instance | 六arm公平对照和迁移分别验收，已编写测试不作通过数 |
| Memory / #4885、#4889 | 固定成本/预算、隔离执行及NULL/UTF8 prepared可恢复性修复 | Current、持久实验预留、模型迁移和poisoned DB恢复须独立原native |
| PQ/Chain / #4877→#4895 | Hepta09de43ba与真实Cargo.lock固定Chain254033da，17源码完整对象和Chain全tree已核 | 双端64KiB raw-body已接；原24KiB inline和64KiB JSON帧门保持。paired原生、binary build provenance和正常consumer仍缺 |
| HIA/NDU / #4882 | 重复JSON字段拒绝方向保持；收费/拒绝回执与原14+3控制分开 | 真实模型、独立评价和未解决的I/O边界仍OPEN，DENY_ALL不变 |
| HCSN / #4873 | f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b，真实GPU UUID解析并拒绝ordinal/MIG/歧义 | 不转成170CUDA任务、物理能耗或D−B接受；保弱B、精度和完整成本限制 |
| H4 / #4894 | 4d5f73ce2043…作者记录301执行/276paired，绑定Hepta6db78×Chain8df4；8组whole均HOLD | 105MB原生原件未本轮取得；不转授本产品或科学资格 |
| H1/H2与诊断 / #4896–#4901 | H1fail；#4897 b3a1bd…两路径联合stdout/stderr预算；H2timeout；CMD raw_arg待原生；fake-sudo只负控；fmt109hunk/29file dirty | 对实际缺陷按固定范围继续，保fail/timeout/dirty；两路径预算或格式差异不代完整权限/格式原CI |

Chain源审表明公开client通过有界header、完整raw body与EOF进入真实控制socket；先检查长度并从容量为2的闸门取得一个permit，再分配/read_exact/EOF/digest；由状态readiness/fencing、普通PQ FinalUse进入现有taskflow/nonce/durable attempt，再以submit --packet-stdin调用Chain的Packet::decode、admit和activate。原零交易完整包为49508字节，其hex为99016字符。该路径解决已有传输尺寸冲突，但配对测试仍#[ignore]且要求精确外部binary；fixture明确app_server_launched=false、evidence_startup_executed=false、chain_task_profile_is_pq=false、independent_trust_deployment_qualified=false、production_activation=false。源码上的40hex版本格式和binary hash不是可信build provenance；超时后的外部效果UNKNOWN继续保留。详见[固定Chain双端补审](generated-evidence/concurrent-pr-increment-20261106-chain254-addendum/REVIEW.zh-CN.md)。

## 5. 后续发展阶段与优先级

| 阶段 | 交付目标 | 进入下一阶段的判断 |
|---|---|---|
| P0 跨平台基线 | 完成第7节P0.1–P0.5，固定可复现候选/完整原件/必需CI | 同源产品回归与原权限合同通过；不以selected或诊断任务代全量 |
| P1 正常垂直流程 | 一条真实UI/API目标到Agentd/Codex的有界任务，终态/取消/恢复都可用 | 实际Root/Current/FinalUse、provider/target、物理效果、Memory回执同链 |
| P2 共享计算与可靠数据 | 明确逻辑Cells、真实并发、队列/Memory/上下文资源和持久化 | 64/256/1024/4096逻辑规模分别报告实测并发、CPU/RSS、p50/p95/p99、queue age、质量/token/完整成本 |
| P3 固定预算shadow | 强普通基线下读取建议、规划与资源分配比较 | 独立预注册数据、预算、公平基线、全部失败；shadow不接生产authority |
| P4 只读因果学习 | 小范围可解释改进、可审证书与受控评估 | 先达到有限组件接受，保独立未来holdout；不把记录重放当新实验 |
| P5 长期学习与回滚 | 学习状态、遗忘/撤销、恢复、不可复活 | 漂移/污染/删除负控、回退到强普通默认、长期成本可算 |
| P6 可塑性与工程自迭代 | 经审查的模块/调度/工程候选生成与验证 | 独立评价、受控变更范围、可靠回滚；优化不自授执行权 |
| P7 具身与物理目标 | 真实环境的窄域任务与安全边界 | 明确真实传感/动作/目标接受，不由模拟分数外推 |
| P8 外部系统兼容 | Bao/Chain/HIA按固定版本、接口与消费者渐进接入 | Bao真实consumer、Chain/WAN故障、HIA证书/撤销等分别闭合 |

B18的原科学门始终是新的事前冻结2×2与重点D−B。现有J−C的有限规划正结果、验证拒绝后回退C、工程移植、重放一致性都不能重命名为D−B通过；OOD曾用于VAL、完整成本不足的限制继续保留。已有五fit不是数百世界的新独立fit；CPU/F32小模型也不能外推BF16/vLLM生产接受。新的研究采用独立未来数据和完整成本记录，未经采用门维持强普通默认。

## 6. 当前原生结果如何影响计划

### 6.1 Windows：已排除宿主前提误判，真实权限缺口仍在

native13实际source daa21e7a、merge f8e97e16、tree fbaf12d5，run42140578464/job127639593751。whole147P/7F/2I；四种ACL布局的host Rust/CMD在Neither都拒绝、其余三格允许，物理结果成立。strict Rust与legacy CMD在Neither/TargetOnly拒绝，但ParentOnly/Both实际删除成功，原断言保持失败。七个失败包含两组矩阵、一项broad identity strict，以及四个锁poison后续错误；不能将七个失败全部当作独立根因，也不能因后四项是后续错误忽略前三项。

根审核对完整84成员ZIP/CRC、48份完整对象DACL观察、七份compact共39672条记录、7个实际local/noncache TestRunner动作和分别的XML wrapper。四项exact原正控、acl_tests.rs:597物理身份反例、源码全文精确还原、无筛选21项helper和11pins保留。Rust before-token输出有一条交错，未伪装成完整JSON；严格返回后的推论只按固定源和后续原断言范围表达。CMD实际primary token、唯一输入释放和有界job清理Active=0均有可核材料。

新可执行性审计说明所有相关产品入口仍使用同类DISABLE_MAX_PRIVILEGE/LUA/WRITE_RESTRICTED token工厂，参数只有token与SID集合，没有逐对象路径与操作掩码。有限RX夹具、提升/降低IL、启动时ACL或Job管理都没有同时覆盖原任意ambient read和所有outside写删/后代行为。结论限定为当前实现和证据内没有合格局部修复；没有宣称Windows所有API均不可能。平台级新机制必须先有可审实现、生命周期/不可绕过性和原生部署接受，不能以诊断支线已通过部分测试代替。

### 6.2 Intel：完整上下文已出现真实失败，原预算不放宽

原单target run42138373221/job127632180031在真实macOS15.7.9 Intel x86_64完成31P/0F/0I，包含原30名称；actual darwin-sandbox/noncache、原300000ms外层预算与17成员原件保留。成功日志未显露全部被capture的reader细节，不能补造。旧job127089468985的4MiB drain在2.023066511秒耗尽原2秒，reader字节/errno不足，原因果仍UNKNOWN。

完整上下文native2是另一条实际失败：run42154464909/job127685180579，source ebd31e2b/tree46fca3e6、原//...及两项排除、并发/default retry保持。PTY 30P/1F/0I，portable backend等待2.01948407秒，read=discard1,827,840字节；完整产品源archive的10,583叶/模式重算46fca3e6，剥唯一workflow后为原10,582叶3982。原Bazel exit3，job failure；原131份XML缺件和一个合法重复Fetch被旧collector拒绝均保留，不把缺件写成完整收齐。

主67的原Intel job127679861660也在同一PTY原例失败，但它是独立执行：等待2.228741523秒，6,549次read，read=discard3,358,720字节，最后errno35；child仍python_started、has_exited=false/exit=None。不能用这组数替换native2，也不能把partial drain观测直接归因于FD泄漏或放宽2秒。该job的Core shard1首次320P/1F（startup delivery boundary超时120.45秒），原默认retry后321P/0F仍全量保留；先失败后通过不算首次通过。

原00dc收件器的多层percent跨边界、zstd内藏凭据等反例修复及36项模拟、退出链通过仍有效；原每文件60秒期限只做过静态审阅，没有声称执行了超时反例。新共享collector ee1b8287/36,352字节修正实际Fetch重复语义，并要求原test.log/test.xml输出物化；18个既有函数/类逐字节保持，原36+9新增控制和11项privacy检查通过。实际发布B21 head84cc7345/tree45858bc9/merge285d5727，parent ebd31；B23 head2ac89eaf/tree9a6fd02a/merge652ff4a8，parent e63。两支原10,582产品叶、目标、并发、断言、时间预算和retry不变；唯一新增Bazel参数是限定既有log/XML输出的remote_download_regex，不把下载物化描述成原argv逐字节不变。发布/静态接受没有补齐历史139份XML，也不证明新物化执行已通过。[共享收件修补](reviews/shared-bep-fetch-xml-repair-20261106/registry.actual.json)。

### 6.3 Linux信号：B23按原退出条件完成限定闭合

原退出要求真实baseline丢信号窗口、修后3个单信号父例及2个drain用例通过、配置关闭/stdio及平台语义不变，并最终原CI接受。旧baseline3fail/2pass和修复5pass保留为已接受历史；本轮没有声称重新取得旧raw。新fresh链是GNU诊断e63ed76c/mergeb3bc3dcf/treea6831e26：14pin和前后完整tree/clean均成立，剥唯一workflow后精确等于3982。8个真实remote/noncache测试分片在Linux/amd64执行，307P/0F/1I；3个first_sigterm/sighup/sigint父例和2个原drain全部PASS。唯一ignored retained_signal_child是由父例调用的owned child入口，未把它当成独立跳过的验收。

独立的最终原CI链来自main67原GNU job127679861926：完整605目标CI成功，其AppServer unit 8分片是cached，不能给这次main job新鲜执行资格。逐分片核对两链的argv、env、平台、规范化输入与工具图全部相同，457,661,280字节测试程序SHA256一致；16份日志分别与各自compact的输入digest绑定。两链8组log/hash与action-cache digest实际不同，且main先完成，明确不称main缓存来自此次fresh诊断。原stdio/disabled和非Unix语义逐字节保持。

诊断原Bazel exit0，但job仍因2次合法Fetch重复和8份未物化XML而failure；这两个收件问题如实保留。原退出条件没有要求XML上传、cache=false或后来新增的collector全绿，因此不将这些新门追加入原产品验收。独审2dd76784与根原样重放的108,070/13,052字节stdout均相等；只把B23改为CLOSED_SCOPED，B02/B15及其它平台全资格保持OPEN。[原范围独审](reviews/b23-original-scope-closure-independent-20261106/REVIEW.json)、[三份诊断原ZIP完整包](current-head-ci/b21-b23-original-terminal-20261106T0410/registry.actual.json)、[主GNU与完整92job包](current-head-ci/main67-20261106T0410/registry.actual.json)。

### 6.4 主CI：最新93 job切点保留七个执行失败及两个汇总失败

05:20:01–05:21:49 UTC为最新完整主67观察窗：19runs=11success/6failure/2skipped；93个不同job=68success/9failure/10cancelled/6skipped，无排队或执行中。逐run的jobs实取数与total_count相等。Rust required127704207208现已success；新增失败仅总汇CI required127712699481。9个failed job是原7个执行失败加Windows汇总与总CI汇总，不是9个独立根因；原失败和历史切点均不改写，也不按68/93计算项目完成度。[最新七head切点与原件](reviews/root-followup-publication-native-20261106/registry.actual.json)。

以下为历史04:10–04:13的完整92job与六份官方ZIP原件，原值保留：

04:10:12–04:13:40 UTC为此前主67完整观察窗：19runs=11success/5failure/2skipped/1queued；92个不同job=67success/8failure/10cancelled/6skipped/1queued，0running。每个run的jobs实取数与total_count相等。唯一queued是Rust required127704207208；blocking run-list仍queued但36个子job已有失败，两个层级及非原子窗口各保原值。8个failed job含Windows汇总127691446306，不等于8个独立根因，更不能按67/92计算项目完成度。

| 原job | 完整原件所证事实 | 处理边界 |
|---|---|---|
| Intel127679861660 | PTY30P/1F；Core首次startup timeout后默认retry通过 | 保原失败、partial drain字节及各attempt，不放宽预算 |
| Windows Core shard4 127679861687 | 原16shard/21次tw.exe=15成功6失败；第7shard三次各70P/3F/5I | 保两个deny-read和允许路径readback失败；三个受保护目录断言未到达，不能宣称逃逸 |
| Windows shard3 127679861699 | Queue35P/1F；caller_abort_after_core_started_keeps_exact_authority_until_persistence等queue_blocking_prompt_hook.entered到deadline | hook启动/调度根因尚未确定，不把超时等同权限绕过 |
| Windows shard2 127679861775 | 原sandbox两段89P/3F和50P/10F/2I，总139P/13F/2I | SetSecurityInfo/ReOpenFile error5、两个token边界、legacy错误链和6项poison后续错误分别保留；source67不同于native13 daa的147/7/2 |
| GNU clippy127679861740 | 两个expect_used源码位置导致3个远程非缓存Clippy action exit1 | 是编译lint，不是3次Rust测试失败；最小原合同修补已发PR4923 |
| MacARM127679861749 | holdout114P/1F：Some(Busy)≠Some(Rollback)；HTTP84P/1F：服务端WouldBlock35后客户端ConnectionReset54 | 两个实际target失败保留，未从错误串补造深层原因 |
| cargo-deny127679861307 | 原Run失败，whole-job日志三次Transport closed；原6artifact无报告 | 原job具体原因/退出码/checkout仍UNKNOWN；新PR4922独立日志不能回填 |

main92新增包完整保留六个官方ZIP与所有377原成员、五个新失败job和原成功GNU完整日志、全部19run/jobs API及17固定源。155归档成员恢复后共532文件，5个离线重放stdout精确相同，全部199payload及registry实际GET相等；临时签名下载URL响应不进入Git。新增选定失败目标共有14实际测试启动和14辅助XML动作，和旧Windows Core21+21的分母分开；不声称收齐全部605目标的所有case原件。

历史03:19的85job/两失败切点、01:59–02:01的58job/零failed-job切点、02:44仅四run23job增量都不改写。旧Windows Core五个后续XML复用早期compact digest的限制仍在；本次Intel Core retry后XML另有一处同类不匹配，官方ZIP保留真实字节，没有伪称每个后续XML都匹配compact。早期三项失败run只有取消job的事实仅属于当时选定范围，不能覆盖后来的真实执行失败。

### 6.5 Objective与UI：新增原生接受有明确边界

原Objective run42123581408/job127581904963已成功。官方artifact13471885720原ZIP共52成员，官方摘要、CRC、完整清单及实际67cc/tree3982的10582叶/1571目录均核实。Memory库327P/8skip，Agentd库242P/1skip，desktop feature Agentd库247P/1skip；没有失败或重试节点。后两组重复原242例，不能写成816个独立用例；JUnit没有输出skip名字，也不能据此改成0skip。源码、17锁、12命令的前后守卫、scoped fix/fmt和末尾空drift均绑定；根完整读取verifier后异目录重放116203字节完全相等。

这批GitHub任务使用CARGO_BUILD_JOBS=1、单test thread和dev-small；不等于原私有主机32GiB/jobs4默认full。generic append正负例仍是测试所有者/三ACK夹具；没有签发独立Root、Current或正常FinalUse。实际普通产品入口和provider/target效果继续归B16。

Rust UI source-head与base-merge的两份完整日志各有nextest88P、gateway四组9/5/12/2P，分别保留31/35/28/38过滤或跳过；另有libtest5P、browser四组6/7/9/1P和Node TAP各组13/5/159/12/7/32/1/4/31/41P。不同组和两个source形态不合并为独立总数。八份完整gateway JSON固定source67/base636及source或实际synthetic merge c0f9b518/tree3982、clean前后、exit0，无timeout或output-limit；预期畸形JS的SyntaxError为负控后ok25，不是产品失败。该范围仍不替代普通权限来源或真实外部效果。

### 6.6 已实施修补及三分支新切面

Windows原因链行为修补的执行源是340fbc06、parent67、mergeff2b873c、tree78b817fe，仅改变setup_error.rs与setup_main/win.rs两个文件，其余10580叶不变。未分类错误仍为HelperUnknownError，但从只输出顶层context改为完整anyhow原因链；有类型SetupFailure的原code/message保持。新增两项测试用真实临时目录写入/读回JSON，分别验证OS错误原因链与类型分类。原三个sanitizer测试、ACL执行、测试断言和预算不变。独立完整源码读取、正反patch与全树重算通过；本机just fmt和just test两次实际exit127（缺just，cargo/rustfmt亦不可用），不声称格式或Rust执行通过。

历史03:55:37首切尚未出现Windows编译/测试job，原件保持。04:41:40–04:43:11后续完整切面已观察到Windows clippy127703396775与release build127703396771成功；不能仍称没有编译观察。两个新cause用例在340源原log/XML各一次PASS，tw.exe实际local/noncache、300000ms；库整体141P/13F/2I。完整43+93成员官方ZIP与两原日志已实际登记，20个测试/20个XML动作中17份首次或单次digest匹配，3份重试compact复用旧digest，限制明确；Core19次中4次失败。EOF只在一attempt被打印为日志与返回错误两行，不扩成两个原因；SetSecurityInfo error5另列。该结果不转授后续18格式源。[固定340原生包](ci-audit/windows-setup-causes-native-20261106/registry.actual.json)。当前PR4913另已发布18bbef4f/tree d611fe96/merge eefd4467，parent340，仅将实际repo-checks job127703396530给出的setup_error.rs两hunk格式差异原样落实，10581其它叶不变。旧340的两例PASS及clippy/release成功不转授18源，后者原生资格独立等待。此修补使下一次原失败能区分状态读/解析/写、实际ACL调用等原因；它没有修复已证明的strict外部删除，也没有在根因未知时改ACL语义。内层Debug日志原有原因链；此次改变caller错误报告内容，不新增网络或特权路径。

Draft PR4922已实际发布head476653f8/tree06c4e2f8/merge825779c5，保持原cargo-deny0.19.0、Rust1.95.0、原命令和30分钟预算，只增加原日志、退出码及source/clean留存。其自动run42162085830/job127715564317再次失败，但11成员artifact及完整12,397,460字节日志已实得：唯一error[unmaintained]为pin-utils0.1.1的RUSTSEC-2026-0441，advisories FAILED，其余bans/licenses/sources OK；原命令exit1、tee/capture0，实际merge825779/tree06c4前后clean。此新job给出了可修依赖问题，不能反填旧job127679861307仍不可取得原日志的UNKNOWN。依赖更新正在按固定上游与锁文件核对，未加ignore或放宽规则；尚未宣称依赖修复或B15闭合。

GNU clippy原两处expect_used的最小修补已发布Draft PR4923：head3c9e2bba、treee60df9b5、merge65e1ec71、parent67。原成功/错误分支与断言合同保持；最新原GNU Clippy job127717742578已success，完整863,099字节日志绑定该merge，报告26,119 actions成功且check-clean通过，repo-checks127717742170亦success。该原门已接受修补；没有据此声称所有动作新鲜非缓存或整库通过，其余平台失败仍保留。[源码独审与实际出版](ci-audit/arg0-clippy-independent-20261106/registry.actual.json)、[原Clippy日志与最新切点](reviews/root-followup-publication-native-20261106/registry.actual.json)。

05:20:01–05:21:49七个head共46个run各自完整jobs原件已登记。除主93外，cargo为41jobs=27S/6F/6skip/2Q；arg0为43jobs=29S/4F/6skip/3Q/1running；B21 collector为9jobs=3S/2skip/2Q/2running，B23 collector为9jobs=4S/2skip/1Q/2running；Windows格式18源为7jobs=3S/2skip/1Q/1running；PTY新修补8075源为12jobs=2S/2skip/4Q/4running。这些是按head分开的非原子API观察，不相加为独立产品用例或替代原生资格。

历史04:41:40–04:43:11的三个完整分支切面分母分别为：cargo 3runs/34jobs=5S/1F/5skip/20Q/3running；arg0 5runs/10jobs=2S/2skip/6Q；Windows原因链5runs/42jobs=25S/6F/6skip/4Q/1running。它们不是main67的92job更新，也未整合成新的产品候选。Windows六个失败包含cargo/repo-checks/Intel/Win4/GNUclippy/Win2，各自原件仍需按固定源接受。新collector两支的后续原生结果单列，不借静态结果替换。

针对实际drain失败，独立产品修补Draft PR4927已发布head8075eb36/treec1249a17/mergeb88f625a，parent/base67；原期限、断言与失败历史保持。05:20–05:21其12jobs仍有4queued/4running，尚无新源终态资格，B21继续OPEN。实际发布原件已收入[root补充包](reviews/root-followup-publication-native-20261106/registry.actual.json)。

## 7. 工作队列与可验收交付物

| 优先级 | 当前可执行工作 | 交付物 | 停止等待/升级的具体条件 |
|---|---|---|---|
| P0.1 | 收口cargo pin-utils真实advisory，整合原门已通过的arg0及Windows原因链限定改进，再逐路径验收 | 原规则不放宽的依赖/锁更新；精确source/base/merge、原命令终态和原失败保留 | 新依赖/平台结果未取得不闭合；旧cargo UNKNOWN与新失败原因分开 |
| P0.2 | 定位Intel两个完整上下文partial drain、Queue hook等待与MacARM两个实际失败 | 原2/5秒、完整目标/原默认retry下的原因果修复和完整attempt；无放宽断言 | 超时/错误串只支持观察到的边界，未得原因果时维持OPEN |
| P0.3 | B11最小可审产品边界实现及原native资格 | 四类outside拒绝、ambient read/inside I/O、句柄/复制token/impersonation/后代寿命 | 当前token参数缺对象/操作输入；没有合格机制实现与部署依据时保OPEN |
| P0.4 | 维护已闭合B23原范围，验新collector物化并收齐最终required | 既有baseline/5例/fresh与原CI接受保留；新收件结果和最终整合候选独立核验 | 不把XML/新collector门追加入B23；整库与其它平台仍由B02/B15接受 |
| P0.5 | Linux原默认full按已准备入口续接 | 原19506eligible/57ignored、资源guard与完整结果 | 必须出现新的64GB磁盘/32GiB RAM/jobs4合格容量依据；不重复查询或降门 |
| P1.1 | B16 R1–R6按依赖逐段整合，恢复旧driver确定身份 | 正常UI→Root/Current/FinalUse→provider/target的任务/取消/丢ACK/重启物理回执 | authority材料/普通caller/外部效果未实得时维持开放 |
| P1.2 | B19固定Hepta/Chain配对原生和Bao/HIA各consumer验收 | 锁定版本、可信binary来源、完整失败与两个backend原接受 | paired测试源码、作者通过数字或development fixture不转授production |
| P2 | 明确逻辑Cells与实测并发/资源；先有可靠持久化和受控基线 | 64/256/1024/4096逻辑规模的CPU/RSS、尾延迟、队列年龄、质量/token/完整成本 | 不以instance数量或导航模块数替代吞吐/质量 |
| P3+ | 独立新科学实验与shadow/可回退采用 | 预注册2×2/D−B、独立数据、精度和全部成本失败 | 未通过保持强普通默认，B18不为追求清零而关闭 |

整合顺序由实际依赖与原结果驱动，不按排队时长承诺日期。每次报告固定head/tree、原target/name、selected/ignored/early-return、attempt/cache、有效负控、精确恢复和最终守卫；compile/link-only、测试执行与真实业务效果分别描述。同名跨source/merge/feature多次执行不累计成多个独立定义。

全部blocker闭合要求原23项分别满足原退出条件，且新整合树通过required gates。当前未达到；不能通过删项、改名、松断言、缩窄原产品合同或将科学HOLD写成工程完成实现清零。

## 8. 固定来源与证据入口

- [原全库审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)、[本轮进度V9](CONTINUATION_PROGRESS_V9.zh-CN.md)、[23项ledger V8](continuation-blocker-progress-v8.json)、[本轮完整登记索引](evidence-index-v10-registered.json)
- [canonical五文件同源桥接](reviews/canonical-product-direction-bridge-v1.json)、[原退出选择](reviews/original-exit-selection-5b/selection-checklist.json)
- [最新七head CI、四次实际发布、cargo完整失败与arg0原Clippy成功](reviews/root-followup-publication-native-20261106/registry.actual.json)、[B23根最终限定接受](reviews/root-followup-publication-native-20261106/ROOT_B23_ACCEPTANCE.json)、[Windows两个cause原生限定包](ci-audit/windows-setup-causes-native-20261106/registry.actual.json)、[arg0源码独审与实际出版](ci-audit/arg0-clippy-independent-20261106/registry.actual.json)。
- [历史完整92job与六原ZIP](current-head-ci/main67-20261106T0410/registry.actual.json)、[历史85job与Windows失败包](current-head-ci/main67-20261106T0319/registry.actual.json)、[历史完整58job包](current-head-ci/main67-20261106T0201/registry.actual.json)、[02:44四run增量](current-head-ci/main67-20261106T0244/registry.actual.json)
- [早期三失败run原日志分析](reviews/main67-three-run-triage-20261106T0203Z/registry.actual.json)、[早期两包及Chain文档的独审](reviews/main67-0201-triage-chain-independent-20261106/REVIEW.json)、[Objective完整原件与重放](ci-audit/objective-owner-main67-terminal-20261106/registry.actual.json)
- [native13根审](generated-evidence/b11-pr4884-ci/terminal/probe-127639593751/ROOT_VERIFICATION.json)、[Intel单target根审](reviews/b21-original-intel-terminal-20261106/ROOT_VERIFICATION.json)
- [新Intel作者与独审完整便携包](reviews/b21-full-intel-v2-rebuilt-20261106/registry.actual.json)、[新GNU完整候选包](ci-audit/b23-linux-full-appserver-candidate-20261106/registry.actual.json)、[两诊断实际发布根审](reviews/diagnostic-root-publication-20261106/ROOT_VERIFICATION.json)
- [B23原退出独审](reviews/b23-original-scope-closure-independent-20261106/REVIEW.json)、[B21/B23三个终态原ZIP](current-head-ci/b21-b23-original-terminal-20261106T0410/registry.actual.json)、[共享Fetch/XML修补](reviews/shared-bep-fetch-xml-repair-20261106/registry.actual.json)
- [Intel历史第二API切点](reviews/b21-full-intel-native2-secondcut-20261106T0344/registry.actual.json)、[GNU第一API切点](ci-audit/b23-linux-appserver-pr4910-initial-20261106T0327/registry.actual.json)
- [Windows原因链完整独审](ci-audit/windows-setup-error-causes-independent-20261106/registry.actual.json)、[PR4913实际发布](ci-audit/windows-setup-error-causes-pr4913-publication-20261106/registry.actual.json)、[PR4913第一CI切点](ci-audit/windows-setup-error-causes-pr4913-ci-initial-20261106T0355/registry.actual.json)
- [旧目录丢失时已冻结377路径恢复投影](recovery/post46fd-remote-inventory-20261106.json)、[B23恢复检查点](generated-evidence/b23-linux-original-gate/RESUME_CHECKPOINT.json)
- [主产品Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)、[Windows权限诊断Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)、[Intel诊断Draft #4902](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4902)、[GNU AppServer Draft #4910](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4910)、[Windows原因链Draft #4913](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4913)
