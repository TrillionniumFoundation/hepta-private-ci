# Hepta 全量审计、整合方向与阻塞项闭合记录

## 结论与报告范围

当前项目尚未达到全阻塞项闭合、完整平台通过或 main 合入资格。已选定 PR #4797 作为本轮唯一整合候选，并实际完成多轮修复、原始失败复现、负控和平台 CI 核对。当前关键路径依次为：固定候选的工程资格、正常可信产品入口、真实外部任务闭环、独立学习与外部系统接受。

本报告跟随候选源码保存，属于特定候选的审计记录；全局架构与交付权威仍是 [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md)。原 23 项 blocker 的退出条件完整保留在 [historical-blockers-at-1702.json](historical-blockers-at-1702.json)。范围内闭合、单个平台通过、待原平台复验、证据不足、外部阻塞和科学 HOLD 分别记录。

**固定范围。** 完整库存快照截至 2026-11-04 16:58:59 UTC；原 ff72 CI 终态核对截至 18:28:14 UTC；main/候选/base 与新增活动的最后增量核对为 19:38:08 UTC。第三批原生用例按各自执行树记录；原 scoped lint 与格式化恢复已完成。代码和 CI 文件组合树为 `aa1b76d8591358be2f591c8e411b9e0364a818fd`，其中格式化后原生树为 `7aa959b44ed8d2bdad2ab83fb103c40a3333cf0b`。此组合树尚未包含本稿等新审计文档；最终发布 commit/tree 及新 CI checkout 由 PR 单独绑定，不能把本地通过挪成最终平台通过。

## 1. 全量盘点揭示的实际进度

2026-11-04 16:57:12–16:58:59 UTC 的完整分页快照覆盖 1,081 个 open PR、5,146 个分支、0 个 open issue、0 个 release。PR 中有 1,057 个 Draft、24 个非 Draft；154 个以 main 为 base，927 个属于堆叠分支；最长 PR 依赖链为 211 层。12 页 PR 和 53 页分支均读到终止空页，保留重复、循环和首尾漂移检查。这是一个固定时刻的工程库存，不能据此推算完成百分比。

其后增量核对发现 #4802、#4803、#4804 新增，以及 #4800 等已有工作更新。19:38 核对的 main 仍为 732e934ba496d90fbe042b8d41d479ef901643e5；增量结果不冒充重新全量盘点的当前分支总数。原 HTML/ZIP 报告保留 17:02 的历史版本；本目录的记录承接此后的修复与实际 CI。

规范注册表包含 40 个模块、205 个契约、58 个关键协议、67 个持久数据域和 91 个工作包。91 个工作包的登记状态为 43 planned、25 source_implemented、20 source_implemented_execution_pending、2 source_implemented_semantic_review_pending、1 blocked_external。这些状态描述不同的验收阶段，不能把 25/91 或已建目录数当作产品完成率。

源码映射覆盖 46 个根、1,408 个源文件，其中 938 个 Rust 文件、474 个名称含测试特征的文件。原审计中 40 份 implementation map 的 production_implementation 均为 false，38 份已有 native-mapping 标记；platform.types 与 runtime.codex 是例外。映射登记与实际运行资格需要逐候选对齐，目录存在本身不建立产品接受。

特别需要保持命名与事实一致：apps/hepta-native 当时有 23 个文件、没有 Rust 文件；实际 Rust UI 位于 apps/hepta-control-ui/rust。browser.servo 与 control.engineering 也不能仅凭模块名称推定浏览器或原生控制面已经完整落地。

## 2. 整合策略与分支取舍

本轮保留 [PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797) 为唯一修复候选，目标 base 为 integration/ui-objective-20261103-product。它不是已合入 main 的发布版本，PR 保持 Draft。原 r3 与 complete 分支已经做过逐路径比较：2,110 个路径并集内有 2,089 个差异；6 份规范文档一致；13 个组件的 27 个双方不同变化路径已有保留、迁移或延期决定。

保留 complete 分支 #4776 作为有选择的供给来源。已完成逐路径取舍的修复覆盖 cwd 展示语义、V8 初始化互斥、首个 ArrayBuffer 生命周期、ZIP mode 掩码、SQLite drive/UNC、Fleet release 密封顺序、Guardian 截止时间与取消、运行时 Git 缓存。依赖升级应作为一个经过共同验证的整组处理，Rust/Bazel/Matrix/SQLite/AWS/keyring/YAML 的组合不拆成互不验证的零散升级。

新活动的处理决定：

| 工作 | 本轮核对状态 | 处理 |
|---|---|---|
| #4800 原生 G2 socket 发布与启动诊断 | 当前 head 1b390853e50aa2fdae2e6c68793f94742d2d667c；作者报告的匹配 GNU 环境构建仍在旧 6b715 候选上被原 ELF 大小门拒绝；当前 inline hint 尚无新 ELF/guest 资格 | 保留为独立供给组件；先关闭其原尺寸与 Root/guest 验收门，再讨论完整 cohort 迁移 |
| #4801 turn-recover 变体 | 不同基线与审批范围 | 不转借它的资格到本候选 |
| #4802 Windows HEAD-timeout fixture | 两项等待预算改变，保留 405 检查，但尚无本候选的原预算资格 | HOLD；不用于消除本轮原始时间约束 |
| #4803 V8 本地 resolver --run | 三文件、base 14e2；作者报告 10 个 Python 测试通过，Rust 原 continuation 待执行 | 作为构建入口改进独立评审；不合并成正常产品入口或 Rust 运行通过的证据 |
| #4804 rama-dns bindgen 输入 | head 04a42923aaf8c562ad161a17a4bbf35fe883a1b5，parent 14e2；实际仅 Linux GNU 两平台的 build-script 输入修复；该分支 Rama 0.3.0，而本候选明确锁定 0.3.0-alpha.4 | 当前候选依赖版本不同，不把 donor 的新失败直接继承，也不先叠入 MODULE 修改；双方 MODULE 的实际 Cargo.lock 入口已独立核对；保留 [独审记录](third-pr4804-independent-review.json) |

## 3. 上一轮固定候选的完整 CI 结果

固定源码头 ff72d462d74f9eb856aa9edbc368caad9c466708 的完整 CI 已终态。普通 GitHub 合成 merge 为 8e20cb5ec8261053ea472f06f79a0def072f3dce，二者产品树为 f780fe13946102a33b329898af48810be9c7bf0c。UI 工作流自行构造的 merge 身份另记，不能替换为普通 GitHub merge。

| 层级 | 成功 | 失败 | 取消 | 跳过 | 总数 |
|---|---:|---:|---:|---:|---:|
| Workflow runs | 13 | 2 | 1 | 2 | 18 |
| Checks | 72 | 11 | 1 | 7 | 91 |
| blocking 工作流内 jobs | 24 | 9 | 0 | 4 | 37 |

上述计数的分母分别是 run、check 和 job，不能相加当作缺陷数。失败汇总 job 也不能重复计成独立根因。完整终态数据见 [third-original-ci-terminal.json](third-original-ci-terminal.json)，原执行见 [blocking CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454075)。

GNU 与 musl 标签的两条 blocking job 都使用相同 GNU/glibc RBE 平台。它们没有建立两种独立 libc 的运行资格。四条 V8 musl 构建确实选择了对应 musl 平台并产出了目标，但执行记录明确跳过非原生 Cargo smoke，且大量使用远端缓存；这只能按实际构建范围报告。完整证据与真实产品 musl 后续门槛见 [MUSL_QUALIFICATION_SCOPE.md](MUSL_QUALIFICATION_SCOPE.md)。

本批另加独立的 `.github/workflows/hepta-musl-product-smoke.yml`：对原显式 x64 musl 产品目标构建，核对真实 executable、配置平台与静态 ELF，再对同一份文件执行一次 `--version` 和一次 `--help`。原平台检查不变。YAML 与四段内嵌 Python 已通过语法检查；这尚不是 hosted 构建或运行 PASS，也不建立完整 musl、ARM、Alpine、sandbox 或正常产品入口资格。具体范围见 [MUSL_PRODUCT_SMOKE_SCOPE_ZH.md](MUSL_PRODUCT_SMOKE_SCOPE_ZH.md)。

Mac ARM 最终有 3 个失败 target，Intel 有 7 个。Intel 新观察到的 forward、Fleet、Supervisord 和 worker 失败需要阶段证据才能定位。106.69 秒与 37.71 秒分别是 Fleet 和 worker 整个 target 的耗时，不能当成失败用例的耗时。

### 原 48 个失败用例的逐项核对

| 当前最强可见证据 | 原用例数 | 验收含义 |
|---|---:|---|
| exact case FAIL | 8 | 失败仍明确存在 |
| 至少一个执行范围有 exact case PASS | 13 | 该范围有通过证据，其余平台分别判定 |
| 只有原平台非缓存 target PASS | 11 | 真实目标通过，缺少逐例成功正文或 JUnit |
| 没有可见 case 正文 | 16 | 保留 unknown |

48 个名字及 121 个原平台关联均已列出，当前全矩阵闭合数仍为 0。此前 35 个名字的 Linux 原生通过记录保留，不覆盖原平台失败。另有 18 个原 48 之外的新可见失败名字：8 个来自最终失败目标、final-log 或完整 JUnit，10 个仅见于重试阶段。后者不被升级为持续终态失败，也不凭后续没有打印而补造逐例 PASS。

详见 [ORIGINAL_FAILURE_RECONCILIATION.md](ORIGINAL_FAILURE_RECONCILIATION.md) 与 [完整逐项数据](third-original-failure-reconciliation.json)。旧 Core shard 10/11 超过 1 MiB 的输出被省略，下载完整 job log 仍不能恢复被 runner 丢弃的 case 输出。新的收集器会保存所选失败 target 下所有现存 shard/attempt 的 test.log 与 test.xml，并显式记录缺失或采集错误；原 Bazel 退出码、重试、跳过、断言和时间限制保持。其真实 CI 产物仍待下一轮验证。

## 4. 已实施修复与实际验证

前两批已发布修复覆盖 cwd、真实认知投影 oracle、正向私有路径、Hook 元数据、私有 attempted-call 观察、终态 admission、请求级 WebSocket 身份、顺序 realtime handoff、Lease/Queue 夹具、Windows helper 布局、PTY 真实执行就绪、TUI 中断顺序与 Unix 信号订阅。原失败、负控与 25 个实际原生阶段均保留在第二批资格文件中。

第三批的主要变化如下：

| 组件 | 变化及依据 | 当前验收范围 |
|---|---|---|
| namespaced custom tool | 按实际持久历史与内部 bounded retained-call 观察检查 namespace，保留三轮交互、截断、反斜杠与 replay oracle | 旧源实际 FAIL；修后原用例 Linux PASS |
| turn_state | 使用现有 thread-settings helper 的默认 override，避免夹具意外改变模型与权限 | 旧源原 60 秒 TIMEOUT；修后原三请求/一握手断言 PASS |
| suspension/resume | 以原 environment manager 和完整 rollout history 保留真实环境身份，包含 Wine 的 Windows path identity | Linux 原 baseline 与修后均 PASS；Wine 原 CI 仍待通过 |
| Queue | 同一个原 25 秒尾部预算内等实际数据库确认；通知先注册再观察状态；不以 CoreTurnComplete 代替持久 ack | 真实 owned DB gate 负控 FAIL 命中；修后 4/4 PASS；Mac ARM 待原 CI |
| executor Skills | 让临时工作区与自动环境使用同一个 canonical cwd，保留全部允许/拒绝/符号链接检查 | 原组 5/5 Linux PASS；两个 macOS 平台待原 CI |
| PTY readiness | 首次仅发一个执行探针；首次观察真实提示符后最多补发一次；echo 不算执行成功 | 原 5 秒 readiness、2 秒 PID、5 秒 exit 预算保留；现批次见下表 |
| PTY drain | 在原 4 MiB 写入及 2 秒退出预算内增加 owned 进度记录 | 诊断变化；Intel 根因仍开放 |
| Fleet | 直接健康检查后执行一次普通 tick 并核对六个进程身份完全不变，随后保留全部原断言 | 可验证最终快照一致性；没有把 tick 保证成新的网络探测响应 |
| forward / Supervisord / worker | 给原 timeout/RPC 增加固定阶段、耗时或同一 owned stream 尾日志 | 诊断变化；不能单独关闭原 Intel 失败 |
| Windows authorized-read workflow | 在同一隔离目标目录先构建原 setup 与 command-runner 两个 helper | 等原 Windows source 与 merge 实际运行 |
| UI CI | 仅取两个固定 commit 的完整祖先；保持准确 source/base 合并；原 13 个 build 命令按同样顺序拆分计时 | 原 60 分钟预算不变；需 GitHub source/merge 真正完成 |
| 历史证据与失败日志 | 历史 JSON 改为指向原不可变字节的显式索引；失败分片收集器保存全量 test.log/XML | 原 docs verify 与收集器 13 个测试已通过；下一轮 CI 验实际产物 |

针对性 Rust 结果分属三棵明确的源码树：Core 三例在 eb5a 上通过；Queue 四例与 Skills 五例在 8699 上通过；本批 PTY/Fleet/forward/Supervisord/worker 八例在 a69b 上通过。共 20 个所选用例均实际 PASS，重试为 0；这不是一次全仓测试，也不覆盖原 macOS、Windows 或 Wine 资格。

| a69b 所选原用例组 | 实际结果与用时 |
|---|---|
| PTY inherited FD / drain / echo-tcflush | 3/3 PASS；0.075 / 0.136 / 0.367 秒 |
| Fleet 五进程升级 / 六 Agent 生命周期 | 2/2 PASS；11.856 / 12.176 秒 |
| forward 命令与大文件转发 | 1/1 PASS；20.094 秒 |
| Supervisord 五 Agent / daemon restart | 1/1 PASS；31.033 秒 |
| worker fresh context / tombstone | 1/1 PASS；1.869 秒 |

这八个所选用例全部执行。原 nextest 摘要同时保留筛选外的 62 个 skipped（PTY 25、Supervisord 1、worker 36）；它们没有被计作通过。UI 原完整 Python discover 为 13/13 PASS，47.297 秒。六个原 Gateway graph 检查仍查询本地 HEAD907d4f5，实际 GitHub 新提交图与 source/merge UI 运行仍由后续 CI 验收。

原生验证控制器的实际 exit 为 1，原 success=false 保留：Fleet 的 package-scoped Cargo 编译把当前源码的 Agentd 从最初联合构建的 9b0a… 重编译为 d24b…。源码树和五个实际测试程序哈希前后稳定，编译日志、解析路径和实际 JUnit 支持当前源码的执行链。catalog 之后、just 之前没有独立采集三个外部程序的哈希，因此没有把“匹配最初构建”的失败字段改成 true；它与八个业务用例的 PASS 分别呈现。forward 使用自己的集成程序，worker 的外部 codex/Linux sandbox 哈希保持最初构建值。

完整记录见 [third-intel-ui-complete-native.json](third-intel-ui-complete-native.json) 和 [独立 Fleet 来源核验](third-fleet-and-report-independent-review.json)。成功用例的捕获 stdout 未被原 nextest 配置输出，因此不推断未见的健康状态翻转或 daemon 阶段日志。

### Windows 已有的范围内闭合

B12 的原两个正向私有目录用例通过；unchecked-create 与 path-check-open 两个真实负控各精准命中一个 FAIL、另一个 PASS；文件系统观察、finally 源码恢复和工作树清洁均符合原契约。此项按原退出条件闭合。

B14 的原 13 个 Windows exec resume 用例在 source-head 与 base-merge 各 13/13 通过，均 0 retry；两边 rollout 各 121/121 通过。已独立解包两份 GitHub artifact、核尺寸、摘要、CRC 与全部 JUnit。两边 server 各 253 PASS/1 FAIL 是另一项 helper 缺失，不能把整个 workflow 标为通过。见 [两份原始 artifact 独立核验](third-windows-independent-artifacts.json)。

Retained Windows lane 实际执行 532 个测试全部通过，另有 7 个原跳过项；20 个要求的原控制各执行一次。Core lifecycle 的 8 个指定案例和 Core unit target 也分别有真实通过范围。这些范围不替代严格 token/DELETE 或 CodeMode 集成验收。

### Windows 三项严格失败

三个原始严格权限断言仍失败。ACL 修复的幂等问题已有直接 DACL 证据：Windows 规范化后的 effective / inherit-only 拆分未被原精确 flags 判断识别。另两项真实观察到不允许的删除，分别涉及 broad-identity fixture 与公开 legacy workspace-write 路径；write/create 被拒绝不代表删除同样被拒绝。具体 DELETE 与父目录 DELETE_CHILD 路径仍需因果区分。

已准备 [具体修复设计](WINDOWS_BOUNDARY_REPAIR_DESIGN.md)，包含 normalized ACE pair 的严格匹配、真实 token/handle/文件系统的区分实验和原 loader/IPC 正控。生产权限边界在本轮尚未改动。会话历史与旧审计报告记载过自动审批拒绝 token/loader/DLL 生产边界修改；当前未恢复原始审批工具回执，因此无法提供其 decision id、原文或具体理由。该历史限制继续保留，不通过换执行方式绕过。

### 提交前的原格式与静态核验

七个受影响 crate 的原 `just fix --locked --offline -p …` 实际 exit 0，442.883 秒，没有自动源码改动。首次 `just fmt` 在 Python 阶段因 PATH 缺少 `uv` 退出 1，保留该失败及六个 Rust 文件的完整格式差异。随后复用环境中真实 UV 0.11.3，按原冻结配方使用 Ruff 0.15.13；原 `just fmt` exit 0，5.895 秒。新增 Python 文件确实被枚举，四份 Python AST 前后等价，整个 Rust 子树未变。根审独立应用完整 diff，重建树与原生快照完全一致。格式化后未重跑 Rust 或单元测试；原最终文档核验与整树一致性检查在提交前另作记录。

[首次完整记录](third-hygiene-first-attempt.json) 与 [格式化恢复及 musl 语法记录](third-fmt-recovery-native.json) 分开保存。原 docs checker、单文件大小门、原等待预算、重试和跳过规则均保留。

## 5. 项目的发展方向

全局规划的 P0–P8 顺序仍适用。近期应集中资源完成 P0 和 P1 的真实交付链，再开展具有可比较预算的 P2/P3。源码、执行、安全、学习效益、独立接受、晋级和发布分别需要相应的证据。

### 第一优先级：一个能重复验证的整合候选

把每个 blocker 绑定到固定源码、原始失败、最小修复、真实负控及原平台复验。对依赖、Bazel/Cargo lock、vendored 源和生成物作整组验证。保留旧失败与原 retry/skip 事实。平台问题先定位触发阶段和资源归属；时间限制、权限断言或测试集合不能为了变绿而放宽。

### 第二优先级：一个普通启动就能完成的真实任务

正常入口需要完整连接 Root handoff、Registry/arg0 身份、受保护 checkpoint/verifier、FinalUse issuer、listener custody 和真实 UI caller，并与实际 Root/Session producer 同源验收。旧 14e2 donor 的 89 个文件属于有依赖的六个 cohort，不能只移一个 launcher。

先完成一个带真实签名输入、真实 provider/target 的任务，验证该任务约定的真实输入输出；任务包含外部作用时，核对对应物理效果。随后覆盖取消、丢 ACK、进程重启、撤销及回滚，每次都核对 authority、evidence、Memory 与应有外部效果一致。本轮直接读取固定源码后确认：Desktop c42 与旧 c2 的 services 整棵树相同，正常 Root producer 仍只准备 Notes；c42 的 UI 则缺少旧 c2 已有的 joint Desktop 启动 consumer。这两条分支并非包含关系，不能直接配对验收。Hepta 当前 attachment 返回实际 UI 所用的 original_sender；旧 donor 同名接口只返回 Notes identity。普通连接已有的 current-user peer gate 和 owner-local 跨平台边界也必须保留。因此下一步是逐接口迁移、补齐正常 joint producer/caller，再做同源接受。详见 [B16 当前入口主源证明](third-b16-current-entry-source-proof.json)、[六组合同与 R1–R6 迁移清单](B16_R0_SOURCE_AND_MIGRATION.zh-CN.md) 和 [独立核验增补](B16_R0_INDEPENDENT_ADDENDUM.zh-CN.md)。

### 第三优先级：可测的共享计算与只读学习闭环

沿现有 Neuron、inference 与 organ owner 合并一个共享 Encoder/Cell/worker 实现，使用有界队列、稀疏 microbatch 和固定代际输入。分别测 64/256/1024/4096 个逻辑 Cell 与实际活跃并发，记录质量、CPU、RSS、p50/p95/p99 和总成本。Memory Cell 保持可由源事实重建的投影，遗忘、纠错和引用前重验有独立 oracle。

第一个学习闭环按 C1-PROMPTED-MEMORY-RETRIEVAL-RANK 落在只读检索排序领域，比较 exact-source、freshness、contradiction、cite-before-use、abstain-on-stale 因子及组合与时机；保持规范要求的 zero Memory/KG/tool/provider effect 边界。之后才考虑长期效益、下一 snapshot 签名加载、回滚、遗忘不复活，以及结构塑性、代码候选和具身能力。

## 6. 研究与外部依赖的真实门槛

#4798 已补齐缺失确认终稿并对三个 JSON 重新计算，关闭的是缺失报告与结果表述问题。实际结果为 32/32 fits；4 个收益置信区间全部跨 0；0/4 通过预先收益线；256 个评估条目中没有一个同时通过全部八项质量门。

四个效果均值与区间分别为 -0.011212158 [-0.0777352, 0.0553109]、-0.022689209 [-0.1089372, 0.0635588]、+0.003876953 [-0.0525625, 0.0603164]、+0.009311523 [-0.0451946, 0.0638177]。这些结果支持继续 HOLD；不能据此宣称零效应、普遍伤害或等价。现有比较是同一模型家族内多轮反馈与单轮之差，不是独立解析核心的 D−B 增量。

审计复核了 37 个归档、30,735 个成员，完成 25,506,732 次记录一致性比较，其中 15,595,691 次为数值比较、9,911,041 次为相等性比较。该范围未发现违规，最大残差约 4.44e−16；没有重放完整模型、teacher、RNG、decoder 与 optimizer。已记录 CPU 成本下界 8,326.229650133 秒，含 55.0725 秒中止 worker；另有三项 controller 成本未知。完整成本与失败尝试继续保留。

后续科学采用必须使用新的事前冻结 2×2 比较，重点为 D−B，独立数据和评估者、足够精度、等总预算、所有失败尝试与成本。不能通过事后挑种子、删失败或挪动门槛获得采用资格。强普通默认继续保留。

Hepta 内部 Bao 适配器的 13 项关键兼容能力为 11 partial、2 gap、0 closed。另一个分母来自外部 Bao 固定采用源 eac9c608bfda77a8972e1e8a1343dfc21985d62b：60 个 surface 中 13 个限域实现、47 个仍为定义。两张表的来源与验收对象分别保留。需要把 restricted consumer、独立签名接受、epoch/撤销/freshness 与本产品真实 caller 一起验收。

原固定审计对独立 Chain 候选记载：六类确认尚未建立接受，27 个回合中 6 confirmed、9 observed-unconfirmed、12 unobserved。该数字沿用 17:02 历史报告的审计记录，本轮未重新执行该 Chain 候选，也未恢复其原始逐回合 receipt；不能把它提升为当前 Hepta 的独立运行资格，或重新表述为原方案要求的对抗规模。现有经典 Ed25519 也不建立后量子资格。HIA 当前 DENY_ALL 与 safety_certificate=false 应继续反映实际接受结果。

具体的真实权威输入、六组入口合同、Bao 兼容出口、Chain/HIA 独立接受及研究冻结规则见 [EXTERNAL_CLOSURE_PLAN_ZH.md](EXTERNAL_CLOSURE_PLAN_ZH.md) 与 [external-closure-plan.json](external-closure-plan.json)。可自主完成的仓库内代码工作继续推进；外部输入缺失的接受步骤保留其精确 owner、输入和退出条件。

## 7. 后续执行计划与退出条件

| 顺序 | 实际交付 | 退出条件 |
|---|---|---|
| 当前 P0 | 发布本批固定源码、完整失败采集、UI/Windows helper 修复；独立 musl 构建与进程 smoke | 原 required CI 在真实 head/merge 满足；缺失 shard 日志补齐；严格 Windows/Intel/Wine 问题逐项有结果 |
| P1 / B16-R0、R1 | 固定两仓源，完成六组合同净差和普通 caller 接线；同一 cohort 的锁与程序 | 正常调用链实际可达，原正向与拒绝控制通过；随后消费原权威输入做真实接受 |
| P2 | 一个共享 Encoder/Cell/worker 与单写者 Memory/episode/artifact 链 | 真实 64–4096 logical Cell、实际活跃并发和质量/延迟/CPU/RSS/总成本记录；故障可恢复 |
| P3–P4 | 等预算 shadow 与 C1 只读因果闭环 | 冻结完整总体、强普通对照和消融；独立收益、质量与 zero-effect 合同均成立 |
| P5 | 下一快照加载/回滚、未来日历 holdout、遗忘不复活 | 实际未来窗口和独立评估完成，Current/来源/forget frontier 一致 |
| P6–P8 | 可塑性与源码候选、simulator/HIL、受授权外部 fixture | 各自前驱、目标主机/硬件、独立接受和实际 owner consent 满足 |

完整 [中文阶段计划](PROJECT_DIRECTION_AND_PLAN.zh-CN.md) 与 [机器可读计划](project-direction-and-plan.json) 保留全部 40 模块、91 个工作包、owner/deputy、7 条实现线，以及 Development/Activation/Evidence 三组前驱。计划以可验收产物和前驱排序，没有用未经验证的日期承诺替代实际完成。

## 8. 完成判定与未关闭事项

每项修复都保留其原退出条件。实际 PASS 可以关闭相应的原始范围；诊断增强、源码存在、编译成功、目标级结果、被跳过的测试和外部作者报告分别按各自范围记录。科学 HOLD 与外部 BLOCKED 不被计作全任务完成。

| 项目 | 当前状态 | 下一验收门 |
|---|---|---|
| B01 仓库与证据清单 | 固定全量快照已完成；19:38 增量核对完成 | 后续发布与新CI继续绑定各自观察时间；不把增量观察冒充全量当前总数。 |
| B02 单一整合候选 | 单一候选取舍完成；最终产品资格未闭合 | 保r3 Guardian取消/截止及runtime-scoped Git缓存；最终同一次提交完整源码/锁/证据，验原required CI和合成merge树。 |
| B03 cwd 展示语义 | cwd原始7例范围闭合 | 新整合树保留原语义，若改该代码才触发相应重验。 |
| B04 认知投影 oracle | 认知投影oracle原目标范围闭合 | 保不可变revision/当前指针、来源/更正/删除/重启等原断言；最终产品资格另归B15。 |
| B05 supervisord 子进程定位 | supervisord绝对可执行路径范围闭合 | 新RPC失败由独立诊断记录处理，保原daemon预算和控制fence。 |
| B06 正向私有路径夹具 | 首批正向路径原目标闭合；TUI另列 | 不得写逐case7/7或零skip/retry；TUI第二批仅按其真实原平台收据更新，不混B22。 |
| B07 Hook 元数据与工具可见性 | Hook修复已提交；原native22例通过 | 最终候选原Hook/MCP/Executor/TokenBudget及allow/deny、环境错配、陈旧目录控制同源终态通过。 |
| B08 私有 attempted tool 元数据 | 新增 namespaced 原例 Linux 通过；原平台仍待验 | 在新固定head及merge的原平台执行新增namespaced原例与保留的wire/retained边界；不借B09/B10通过计数。 |
| B09 终态清理与恢复 | 终态修复及 Windows 指定范围已有通过；Wine 门仍开 | 保busy/lineage/exact实例/fence与恢复原负控；最终范围依独立原48映射和本候选原CI。 |
| B10 WebSocket / prewarm / compact | 生产修复已提交；turn_state 新夹具 Linux 通过 | 用同源原turn_state与身份负控验收；不修改production身份或通过放宽请求数获取绿色。 |
| B11 Windows 原生 sandbox 与 helper | 三项严格权限失败；helper 新准备待 Windows | 先保留原始诊断和四格权限/删除判别设计；本任务暂不改production token/ACL/loader/DLL。原审批receipt缺失须补证，不能虚构拒绝理由或扩大成一般Root禁令。 |
| B12 Windows 私有目录冻结对照 | Windows两攻击正例及两冻结负控范围闭合 | 保留该scope闭合；不外推一般Windows权限或原strict delete三例。 |
| B13 Lease / Queue 时序夹具 | Lease/Queue 已有局部通过；Mac 新回归待原平台 | 原平台同源结果以独立48映射为准；不在此重算或将异源native通过升级全矩阵。 |
| B14 Windows exec 恢复清理开销 | Windows原source与merge各13恢复例已闭合 | 保持原清理/业务断言；同target helper前置作为独立普通构建准备项提交并原Windows重验。 |
| B15 最终 CI 与 main 资格 | 最终required CI/main资格未闭合 | 最终精确head、base和merge tree、所有required门、原失败与有效负控齐全；保全部skip/retry/cache/unknown，原48映射独立维护。 |
| B16 可信产品入口及外部效果 | R0 源码准备完成；正常接线与真实接受未闭合 | 按独立R1–R6批次实现：arg0基础→trust/Current与inherited合同→Agentd装配→joint consumer→normal producer与paired pin→原真实接受。R0的102决策/474净差不等于编译最小闭包。 |
| B17 #4578 缺失确认终稿 | 32-fit终稿缺失已复算并提交#4798 | 保77b244终稿与冻结903946源、全部失败与成本unknown；不为使结论变绿重训同一确认集。 |
| B18 解析核心 / 参数记忆科学采用 | 科学采用HOLD；结论记录完成 | 若继续研究，执行R0/R1/R2的新冻结协议与独立数据；不继续也可保留明确不采用决策，不追求事后正结果。 |
| B19 HeptaBao / Chain / HIA 外部接受 | Bao/Chain/HIA外部接受未闭合 | 按B19-Bao/B19-Chain/B19-HIA分开取得同源实现与真实目标接受；advisory DENY_ALL/safety_certificate=false保持。 |
| B20 远程控制握手夹具 | 远程握手确定性负控及19例原生通过；最终平台门待核 | 最新候选原19例及原平台CI以精确收据关闭；不得跳过正常HTTP或替代真实握手。 |
| B21 macOS Intel PTY退出和输出 | 新 PTY 三例 Linux 通过；Intel 仍开放 | 原Intel30例、完整drain/child/FD原断言和2/5秒预算不变；同源因果与原平台结果齐全。 |
| B22 TUI 中断与退出顺序 | 本地修复及 Windows 目标通过；逐例资格按原记录 | 原Windows interrupt/shutdown case与真实stdout就绪、canonical cwd和原5秒预算；结果交独立48映射。 |
| B23 App Server Unix关闭信号生命周期 | Unix 因果修复已有五例通过；原 CI 仍需复验 | 同最终source原Unix平台验收；原stdio/disabled语义和drain规则保持；首signal注册失败提前报错属已审兼容差异。 |

本候选保持 Draft，直到原必需 CI 通过且目标基线与合成合并树重新验证。正常产品入口、独立接受与研究采用的后续门槛仍各自成立；没有以临时签名、自授 capability、忽略严格断言、增加原等待预算或删除负控关闭它们。

## 证据导航

- [第三批技术资格与验证范围](THIRD_BATCH_QUALIFICATION.md)
- [原 CI 全终态](third-original-ci-terminal.json)
- [原 48 用例与 121 平台关联](third-original-failure-reconciliation.json)
- [Core 原失败与超时](third-core-baseline-native.json) / [修后原生记录](third-core-fixed-native.json)
- [Queue/Skills 原始 JUnit 与真实负控](third-queue-skills-native.json)
- [Windows 原 CI](third-windows-original-ci.json) / [source 与 merge 独立 artifact 核验](third-windows-independent-artifacts.json)
- [八个 Rust 用例及完整 UI 原生记录](third-intel-ui-complete-native.json)
- [UI 完整 13 例与真实日志长度证明](third-ui-and-log-bound-native.json)
- [原 Windows 权限边界修复设计](WINDOWS_BOUNDARY_REPAIR_DESIGN.md)
- [musl 构建与运行的实际范围](MUSL_QUALIFICATION_SCOPE.md)
- [当前 23 项机器可读账本](current-blockers.json)
- [全部证据索引](third-evidence-index.json)
- [本轮 PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)
