# 外部接受闭合计划与原 23 项台账更新建议

时间基准：2026-11-04 19:01 UTC。选中产品为 #4797 的 `ff72d462d74f9eb856aa9edbc368caad9c466708`，执行 merge `8e20cb5ec8261053ea472f06f79a0def072f3dce`，同树 `f780fe13946102a33b329898af48810be9c7bf0c`。后续 9 文件候选树 `a69b20c4c3cfee9cf483496742d6bea1469d847a` 属独立原生验收阶段。

**当前不能宣称全部 blocker 或生产资格闭合。** 能继续完成的仓库内整合、必须使用真实权威输入的接受，以及科学采用判断，应分别留档。本计划复用已完成审计，未执行生产迁移、外部任务或新实验；未重算 architecture agent 负责的原 48 名 × 平台资格表。

## 1. B16：先补正常接线，再做真实接受

既有审计固定于 e729/r3、donor [#4749](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4749) 的 `14e2d89b3367232ec5dbe6187f09feed0f2b68d3`。该 donor 相对 e729 为 478 ahead / 328 behind、89 个变动文件，不能当作一个薄 launcher 移植。旧配对 Desktop `c2c369836e87e9cf27b4dc9aa8b7446e85efdf90` 的正常 Root 仍选 Notes-only profile/seed/factory；donor joint consumer 与 Session 显式 joint 模式不补齐这个 normal producer。

这属于**固定旧 cohort 的审计结论**，不是对所有最新分支的缺失断言。补充文件的独立原 blob 本次未找回，相关源码审计事实明确引用已审 HTML version 1 二级记录，不补造文件哈希。

| 步骤 | 现在可以做的具体工作 | 必需输入与完成证据 |
|---|---|---|
| B16-R0：冻结迁移范围 | 独审现有 donor 增量，按六组合同列字段/类型/返回值/owner 来源及真实调用图；先判断最新 normal producer 是否已存在。 | 一个产品源和一个配套 Desktop 源的完整 head/tree/pin；每组原资格命令、负控名单；实际正常 launch 入口文档。 |
| B16-R1：仓库内完整接线 | 独立产品 PR 与配套 Desktop PR 同源迁移必需组件，正常入口实际调用既有 installer/provider；保留 #4797 修复。 | 六组合同一起兼容、生成锁完整、实际 normal caller 可达、原构建/拒绝控制通过。未使用的 helper 不算完成。 |
| B16-R2：真实 Root fixture 与镜像资格 | 在获准的原环境执行真实 UID/peer/listener 控制，再跑原 image builder 与原场景。 | 同源实际二进制、原资源/尺寸/时限门、各层 exit 和完整日志；外层 measurement exit 0 不能覆盖 builder 失败。 |
| B16-A1：真实正常任务 | 经正常 Root→Agentd→原 Core 和 Session joint 路径完成 Notes+Calculator 的成功、取消、丢 ACK、重启矩阵。 | 原信任链提供 attachment、signed objective、draft/session/purpose/expiry、Current/clock/frontier/issuer；独立核物理效果次数、authority、evidence 和 Memory。 |

六组必须成套核对的合同是：**Root handoff/pidfd 生命周期；Registry/arg0/启动凭据转换；protected checkpoint/verifier；独立 issuer/FinalUse；listener custody；实际 normal UI caller 与 joint producer。** 不能以打开 feature、文件存在、环境变量、自报 PID 或测试身份建立第二个权威来源。此子任务只完成计划，尚未实施跨仓迁移；不存在由本报告创设的一般 Root 代码禁令。

原已读 retained profile 的 300,000 ms 上限、固定 issuer end，以及 joint typed schema 不消费 legacy Notes `previous_recovery`，必须按其固定来源理解。handbook 对续租/epoch continuation/joint restart 的未验声明，不等于所有底层恢复原语都不存在。

### 新 donor 增量的实际限域

本次只读了三份指定 PR 的 API 元数据与正文；正文中的原生收据未在本计划重新下载验证。

- [#4800](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4800) 当前 head `1b390853e50aa2fdae2e6c68793f94742d2d667c`、base `a39a0871d9601ffccb5e0d95d8f39d54b3a63360`，10 文件。作者报告的 matched GNU 测量属于此前 `6b715d2c…`：Cargo/packaging 为 0，原 builder 为 **1**；F/L/S 为 20,179,992 / 20,209,664 / 15,351,808 字节，仍超原门。当前 inline hint 没有新 ELF/guest 资格，六个 Root fixture 尚未执行。
- [Desktop #293](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/293) API 确认 head `c42eccaf8b9b5a163d0c52b1a3c42466fe0f425b`。作者报告旧 A39 owner 的三项拒绝 PASS、两项正向 FAIL；一个是早期 connect EACCES，另一个是无 EACCES 的 initial activation Unavailable。不能合并成已解决的同一原因。
- [#4803](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4803) head `83ad164ff05cb34d444d51e23ee286fa0241c783` 的本地 V8 入口可以作为独立组件审查；正文报告 10 个 Python 测试通过，但原 Rust continuation 仍 pending。它不关闭 B16。

## 2. B19：三个外部接受面分开推进

### HeptaBao

固定产品 pin 为 `eac9c608bfda77a8972e1e8a1343dfc21985d62b`，兼容目标 OpenBao 2.6.2。旧矩阵是 **13 个 blocking capability：11 partial、2 gap、0 closed**；外仓 13/60 scoped surfaces 是另一分母。

仓库内先把 **`BaoFinalUseHost::consume_kv_v2` 接到具名正常产品 consumer**，保受限 registry、独立 signed approval、撤销/epoch/replay 校验，再逐行补原兼容契约。真实接受需要所选服务版本、endpoint/CA pin、用途限定授权和独立观察。KV v2 窄范围接受可以单独完成，但不能被写成完整 OpenBao 替代。

JSON 保留全部 13 行退出条件：KV v2 消费、HTTP/CLI、KV 引擎、auth/token/policy、租约动态 secret、Transit、audit、seal/KMS、Raft/HA、备份复制、plugin/agent/proxy/UI、迁移升级及生产运维。最后两项原来没有证据条目，应先实现并演练。

### Chain 与 HIA

**Chain：**先从既有 qualification 恢复准确 candidate、原命令、失败确认指标与阈值，完成同源仓库内契约修复，再做真实部署/业务接受。本次仅持有已审 checkpoint 摘要，不补造指标数值。若宣称 WAN 或物理双节点，必须提供实际相应网络/节点证据；单 host 多进程不替代。签名输入沿用原协议，不能新增自签接受来源。

**HIA：**独立构建、bridge 协议及拒绝测试可先做；advisory 的 `DENY_ALL` / `safety_certificate=false` 保持。要取得 effects 权限，必须先满足现有威胁模型、证书来源/验证、独立 issuer 与正常 caller 的接受合同。构建绿色、普通 operator 同意或改标志都不能替代这一证明；科学收益和 AOT 资格仍单独验。

## 3. B17/B18：报告交付闭合，科学采用保留 HOLD

[77b244 终稿](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/77b24407b9898aa44769502fbb22c24fb7193a58/tools/hcsn/digital_feedback_20261101/REPORT_ZH.md) 已补齐：32/32 fits、四个主收益门 **0/4**、256 个必需组合的八项整体质量 **0/256**。四个 feedback 比较不是全局解析核 D−B；区间跨零也不是等效证明。#4798 的报告完成不签发其研究祖先的工程 CI 资格。

可以立即完成的工作是证据保管和缺口登记。历史 CPU 已知下界为 8,326.229650133 秒；`development_001`、`development_002`、`training_001` 的 controller CPU 只能从原可信历史收据补回，找不到就永久 unknown，不能重跑后补造历史成本。

若继续研究，先在 TRAIN/开发集修质量，再事前冻结新 2×2、强普通对照、D−B、实用差门、multiplicity、精度/样本/停止规则、全部失败与完整成本。已经读过的确认集永久属于已知历史，不能再作新 holdout。新的确认数据应独立于训练选择过程保管。未达到原门就继续 HOLD；科学不采用是有效决策，不应制造正结果。

AOT/Rust 数值与端到端成本、Safe Core 拒绝、强前端信息对等、开放域真实任务、Memory 权威记录应分别验收。原复算命令在[COMPLETION_REPRODUCE.md](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/77b24407b9898aa44769502fbb22c24fb7193a58/tools/hcsn/digital_feedback_20261101/audit/COMPLETION_REPRODUCE.md)，本计划未重新执行训练、下载全部归档或展开新实验。

## 4. 原 23 项台账的状态建议

下表是对 17:02 原台账的分范围建议。详细原状态、原退出条件、最新证据范围和下一门均在配套 `external-closure-plan.json`。没有把原生、fixture 或另一 head 的通过升级为本候选全平台通过。

| 原项 | 建议状态 | 下一步及范围 |
|---|---|---|
| B01 仓库与证据清单 | 固定快照盘点已完成；发布前刷新增量 | 保留固定时间清单；最终发布刷新增量。 |
| B02 单一整合候选 | 单一候选取舍完成；最终产品资格未闭合 | 单一#4797候选，最终head/base/merge及原CI。 |
| B03 cwd 展示语义 | cwd原始7例范围闭合 | 保原7例语义；不扩大为Core/main绿色。 |
| B04 认知投影 oracle | 认知投影oracle原目标范围闭合 | 保原revision/Current及来源/删除/重启断言。 |
| B05 supervisord 子进程定位 | supervisord绝对可执行路径范围闭合 | 新daemon RPC诊断另列，不重开已证路径修复。 |
| B06 正向私有路径夹具 | 首批正向路径原目标闭合；TUI另列 | 原target级、Unix N/A、ignore保留；TUI独立验。 |
| B07 Hook 元数据与工具可见性 | Hook修复已提交；原native22例通过 | 原Hook/MCP及权限/环境/陈旧目录负控同源验。 |
| B08 私有 attempted tool 元数据 | 内部attempted metadata范围已验；额外replay oracle仍需同源验收 | namespaced replay当前失败不能被原22例遮盖。 |
| B09 终态清理与恢复 | 终态清理已提交；Windows生命周期指定范围通过 | Windows指定8例/unit与全平台资格分开。 |
| B10 WebSocket / prewarm / compact | WS生产修复已提交；turn_state夹具原平台门仍开 | turn_state原例及身份负控；不放宽请求数。 |
| B11 Windows 原生 sandbox 与 helper | Windows三严格边界仍失败；helper与CodeMode分项 | 严格三失败、CodeMode未知、helper目标分开。 |
| B12 Windows 私有目录冻结对照 | Windows两攻击正例及两冻结负控范围闭合 | 两正例及两反事实scope保闭合，不泛化权限。 |
| B13 Lease / Queue 时序夹具 | Lease/Queue原native5例通过；平台总资格待核 | 原平台结果接独立48表，异源PASS不迁移。 |
| B14 Windows exec 恢复清理开销 | Windows原source与merge各13恢复例已闭合 | 保source/merge13例闭合；缺helper另修。 |
| B15 最终 CI 与 main 资格 | 最终required CI/main资格未闭合 | 最终原required CI；保skip/retry/cache/unknown。 |
| B16 可信产品入口及外部效果 | 正常入口接线与真实接受两门均未闭合 | 先真实normal caller整合，再真实权威/效果接受。 |
| B17 #4578 缺失确认终稿 | 32-fit终稿缺失已复算并提交#4798 | 报告完成；0/4与0/256、成本unknown保留。 |
| B18 解析核心 / 参数记忆科学采用 | 科学采用HOLD；结论记录完成 | 独立新协议/数据；不得事后修改采用门。 |
| B19 HeptaBao / Chain / HIA 外部接受 | Bao/Chain/HIA外部接受未闭合 | Bao/Chain/HIA各自同源与外部接受。 |
| B20 远程控制握手夹具 | 远程握手确定性负控及19例原生通过；最终平台门待核 | 最终原平台真实握手/EOF及原19例。 |
| B21 macOS Intel PTY退出和输出 | Intel PTY原门仍开；Linux局部通过保留 | 原Intel30例与drain因果；Linux不能替代。 |
| B22 TUI 中断与退出顺序 | TUI已复现并本地修复；原Windows门按证据更新 | 原Windows interrupt/shutdown同源收据。 |
| B23 App Server Unix关闭信号生命周期 | Unix信号丢订阅因果与5例通过已证；最终CI门待核 | 最终Unix原门；不计入原48失败名。 |

B06 已有[原平台 target 级记录](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/B06_ORIGINAL_PLATFORM_TARGETS.json)，不应因第二批 TUI pending 把首批已闭合范围重新写成未核。B12 原攻击/反事实和 B14 Windows source/merge 恢复各有独立真实收据，也应保留窄范围闭合。B15 仍保持开放，且两个 Linux GNU/musl 标签不能当作两种 libc 的独立 runtime 资格。

## 5. Windows 审批证据与执行前清单

**原始自动审批 receipt 尚未找到。** 当前只有历史 assistant/已审 HTML 的二级记录称 Windows token/loader/DLL 生产修改曾被拒绝；具体 decision ID、时间、原文与理由未核实，全部保留 unknown。本任务继续暂不触碰生产 token/ACL/loader/DLL 边界，不重试历史受拒动作，也不把它扩大为 Root 或其他源码的一般禁令。测试诊断、正确 helper 构建准备和可审设计另按已有范围推进。

每次真实接受前都要填齐：精确 product/paired/external source 与二进制；实际正常 argv/profile；原受保护 attachment/issuer/Current 来源；signed objective/session/expiry；目标 workspace/provider/CA；原预算/阈值；独立观察方；完整原始日志、结果、skip/retry/cache 和 source 前后哈希。缺失项写 MISSING，不用 fixture、空字段或自报标志代替。

### 来源范围

- [已审 HTML version 1，17:02:40 UTC](https://chatgpt.com/library?file_id=libfile_80ac18769b7c8191b7bd5878ba6924c3&account_id=personal)：B16/B19 原完成审计的二级载体。
- 原 23 项完整 ledger blob：`295e4d892b53e3dab44c1181e5c152955d508bea`。
- [第二批固定资格](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/second-batch-qualification.json)：保留各原生树、原错误与适用范围。
- Windows 终态 review blob：`2a73377bdc7787db8c5e49423269d08b39428e5d`；root 后续 merge 工件独验的 review SHA256：`9afc1c8a4376176855d5a9cbfb1027485adaccce659a9a010c9856cabefa5831`。
- musl 独审 JSON blob：`29c4057e04593d314dcf95a9ebf7fec1aaf4bdf0`。实际 V8 musl 构建与跳过的 smoke 均单列，不推为产品 musl runtime。
