# hepta-private-ci 全量审计：原 CI 续批与阻塞推进

本报告是 [第四批项目审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md) 和 [方向与工作计划](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md) 的增量。完整 CI 证据归档截止 **2026-11-05 07:49:25 UTC**；07:59:56 的后续只读查询又观察到两个 Windows 原作业开始执行，结果另行追加。各 API 查询发生于不同时间，不视为原子快照。

**结论：已经落地并验证的修复取得了实际进展，但项目尚未达到整体验收。原 23 项台账仍是 8 项限定范围闭合、14 项开放、1 项科学采用 HOLD。** 本批四项 CI 修复和一项 PTY 测试诊断已形成固定提交，正在准备独立原生验证。B16 的新主机已完成固定源码及工具准备，正在补齐项目原有的 V8 供应。不能将候选提交、构建准备、单个平台的通过或失败后的取消计作 blocker 闭合。

## 1. 固定版本与审计范围

| 对象 | 固定身份与用途 |
| --- | --- |
| 正在审查的产品 | [Draft PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)，头 `0e139b599f0fe451f80fb7db4b2913bb9c679dce`，树 `091e659e0da6602299fd14cfa93889191405edd8` |
| 产品基线 | `63652be658ebed8d3052eb789b951793384fd5e4`；普通合成提交 `e93aefbbb33438f6ec67e995adcfe88657158487` 的树与上述发布树一致 |
| 新修复候选 | `814dbd8a4b16be1b63303ab1455a8d9b43aa4e0a`，树 `64918386b5de73209da15250dbb3f378b97f43f8`；相对产品头 5 个提交、9 个文件 |
| 独立原生代码快照 | `1ddadae2c1bcb3c48047d2692565606833e87909`，树 `73f4b30499524d6137bb8f4b40c3977de286d1a5`；相同 9 个源码/CI 后像应用于原生代码基线 `20fd174…` / `4a3374…` |
| 审计续批分支 | `audit/r3-evidence-20261105`；桥接提交 `2ca528f…` 同时使产品候选和原生代码快照可读取。后续证据提交不改变产品 PR 头 |
| 最后完整原生 A | 测试树 `fb9e131…`；后续原 `just fix`、`just fmt` 后代码树为 `4a3374…`。不得把格式化后的整树重新命名为已完整测试树 |

上述原生代码快照和产品候选只在此前 996 个发布证据条目上有差别；这些条目均位于 `qualification/r3-audit-repair-20261104/`，与本批 9 个源码/CI 路径不相交。这是可核对的源码组合关系，**不是两个整树测试资格等价的声明**。详细路径、父提交和审查对象见 [源码与发布状态](reviews/source-and-publication-state.json)。

审计覆盖仓库清单、规范合同和工作包、集成候选的源码与锁文件、原测试及负控、实际 CI 日志和工件、研究报告及外部接受缺口。清单快照为 03:16–03:24 UTC：1,103 个开放 PR，其中 1,079 个 Draft；5,193 个分支，最长祖先链 211。它说明整合成本与未收敛工作量，不表示逐个 PR 均已获得行为验收。规范口径为 40 个模块、205 个合同、58 个协议、67 个领域、91 个工作包；43 planned、25 source implemented、20 execution pending、2 semantic pending、1 external。源码已存在与生产可用必须分别判定。原始清单与逐项依据保留在上面的第四批审计中。

## 2. 本批已完成的具体工作

| 原失败 | 已完成的修复候选 | 保留的验收边界 |
| --- | --- | --- |
| musl product smoke 的 `cquery` 输出两行相同 canonical label，按行数检查唯一性误报 | `15bc63c…`：解析后只增加 `sorted(set(platform_rows))` | 空标签、冲突标签及后续 target/linker/rustlib、构建、静态 ELF 和 CLI smoke 均保持；原失败尚未进入产品构建 |
| Supervisor 与 Objective 的 Rust 1.95.0 格式检查失败 | `c70bedd…`：按原 rustfmt 输出，仅折行 Windows 删除权限矩阵中的一个表达式 | 错误返回、上下文、闭包尾表达式与权限断言均保持；等待原工作流重新验收 |
| Codespell 对冻结原证据产生 572 条结果 | `f1484b3…`：精确列出 153 个已核验的不可改写证据路径 | 没有新增通配目录或忽略单词；其他 836 个原注册证据不被新规则命中，31 个 Markdown/README 仍检查。7 个混合 JSON 回执的排除粒度是整个具名文件，应明确披露 |
| V8 Mac release smoke：native sandbox=false、Cargo 默认 feature=true | `26a651d…`：staged smoke 基础参数增加 `--no-default-features`，sandbox 行仍显式启用原 feature | 产品默认特性、真实运行断言、6 项 smoke、构建和预算均保持。两个平台原结果各为 5 PASS / 1 FAIL，不能先称修复已通过 |
| Intel PTY dropped-output drain 失败信息不足 | `814dbd8…`：增加仅测试构建使用的读取计数、丢弃计数、错误、任务状态与 FD 状态观察 | 是诊断候选；原 2 秒/5 秒预算、4 MiB 输出、Python alarm、backend 顺序及退出断言不改。观察发生在原超时判断之后，不构成根因证明 |

各修复的完整差异、原件身份和审查结论分别见 [musl](repairs/musl/repair-manifest.json)、[格式](repairs/format/repair-manifest.json)、[Codespell](repairs/codespell/repair-manifest.json)、[V8](repairs/v8/repair-manifest.json)、[PTY](repairs/pty/observation-manifest.json)。最终源码和运行结果仍应按固定提交复核。

原 Intel PTY 31 项实际为 **30 PASS / 1 FAIL**；其中原 30 项为 29 PASS / 1 FAIL，新增 collector 控制为 1 PASS。唯一失败 `pty_dropped_output_receiver_keeps_draining_child` 在 portable backend 等待 2.023 秒后仍未取得退出通知，最后阶段为 `python_started`。该阶段同时包含写入和随后侧通道操作，不能据此断言已证明阻塞在写操作；`has_exited=false` 是等待任务公布的状态，也不是独立 OS 进程存活证明。失败早于原作业取消。现有读取循环本就会在输出接收者关闭后继续排空，不能把已经存在的行为再当作新修复。完整因果边界见 [PTY 复核](repairs/pty/causal-review.json)。

## 3. 原 CI 已取得的行为证据

三批归档含 480 个原件或只读派生记录，原长度合计 **68,011,372 字节**；121 个 Base64 分片重建 23,635,036 字节压缩传输。每批均实际创建 Git blob 并逐字回读；三个归档校验器又逐件核对成员集合、长度、SHA-256 和 Git 对象身份。这里的 480 是归档成员数，不是独立行为测试数。

| 原执行范围 | 原件直接支持的结论 | 尚未证明的部分 |
| --- | --- | --- |
| Windows Core lifecycle | 8 个分片、2,343 个不同测试名：2,340 PASS、3 原忽略 | Core 集成 cold-root、先前环境早返及完整产品资格 |
| Windows retained / State / Memory / Path | XML 532 PASS，另有 7 个原命令跳过；两个原 private-dir 拒绝控制通过 | 未合入的 B16 实现及实际正常产品入口 |
| Linux / Mac ARM Exec | 原 resume 各 13 PASS；rollout 125；server 379 / 383；原非 Windows proxy 包含 CONNECT 行为并通过 | Windows resume 的本次完整结果；此前 full proxy 偶发失败的因果解释 |
| Windows Exec source / merge | 取消前各完成 rollout 121、server 254 PASS，包含真实 authorized-read 权限用例 | resume 只有编译记录、无 XML；整体作业和 retained 最终回执未成功 |
| Windows Queue source / merge | 各 36 个 Queue 用例通过；B13 原 8 个 Queue 名称每个一次通过 | B13 第 9 个 Agentd qualification 目标及其他原平台 |
| Operator 多平台 | Intel 33、Windows 40、ARM 33/33 个原签名夹具控制通过 | 真实 operator、目标系统及正常 Root caller 接受 |
| Objective owning libraries | Memory 327、Agentd 242、desktop feature 247 条 PASS 记录，分别另有 8/1/1 跳过 | 两种 Agentd 配置有重叠，不能相加成 816 个独立用例。格式失败使 `owning_packages_qualified=false`；原 API 最终取消 |
| UI source | 实际完成 88 个 nextest 和 5 个 libtest Rust 控制，均通过 | 浏览器安装阶段取消，渲染、像素、网关等未执行；三个 SDK 探针均 `appQualified=false`；原生 source 没有测试工件 |
| Supervisor | 原 3 + 14 项控制通过 | 同一源的格式检查失败，不能将整个 workflow 判成功 |
| Intel PTY、Mac V8 | 保存真实失败的完整日志与原名字 | 待诊断和修复后的原平台验收 |

详见 [第一批](CI_BATCH01.zh-CN.md)、[第二批](CI_BATCH02.zh-CN.md)、[第三批](CI_BATCH03.zh-CN.md)。07:49:25 的 run 级快照为 19 个运行：6 成功、2 失败、6 取消、3 排队、2 跳过；这并不替代稍后 job 级状态。07:59:56 查询已观察到 Windows Clippy 和一个原 Windows Core 分片正在执行。取消者和取消原因没有原证据，保持未知；本轮没有主动取消或重跑这些原作业。

## 4. B16 的实际推进与下一道门

此前 ROG 上的 B foundation 尝试在 `just test` 参数解析阶段退出：包装器已注入 `--no-fail-fast`，runner 又传了一次。该次是 harness 错误，**0 个用例执行，没有新 JUnit**，不能当作产品失败或有效因果负控。已修正多余参数，并精确恢复该次自有两条源码变更，完整树重新回到 `4a3374…`，普通 index 和两个锁文件保持。完整失败及恢复见 [原失败索引](native/b16-v4/durable-index-v1.json)。

后续 V5 在原 22 GB 门前退出，未安装、编译、修改源码或执行用例。容量调查显示，即使删除调查范围内全部旧私有 index 仍不足门限；因此没有删除缓存或降低门限。新选 ai395 有约 0.97 TB 可用空间，固定 checkout 已完成，Rust 1.95.0、just 1.51.0、nextest 0.9.103、Bazel 9.3.0 已验证。一次 Bazel 版本探测使用了不支持的启动参数组合；原失败完整保留，改为固定二进制的单参数 `--version` 后实际成功。

新主机的 V8 P3 首次查询找错官方发布仓库而按条件退出，没有以近似变体继续。原项目安装回执证明 sandbox 资产来自 `openai/codex` 的 `rusty-v8-v150.4.0` 发布，匹配固定 archive、bindings 和 checksum。正在按该来源核对和继续准备。P4 的全依赖 metadata、全部普通 helper 和完整 nextest catalog 尚未产生；这里不预填将来的哈希，也不将 BUILD_ONLY 准备标记为 A 测试通过。

随后顺序为：实际 P4 完整输入与 396 个既定角色核对 → 新主机 BUILD_ONLY 来源约束绑定 → foundation 的原正控和因果负控 → driver / pool / checkpoint / owning 批次 → 实际 Root / Session / signed objective / provider / target / 正常 UI caller 接受。原 112 个源码对象、5 个 epoch、负控、原 22 GB/8 GB 门与精确恢复要求保持。即使组件全通过，仍必须取得任务、取消、丢 ACK、重启和外部效果的一致性回执后才能关闭 B16。

## 5. 原 blocker 的续批状态

所有原状态类别和原退出条件保持，机器可读版本见 [续批台账](continuation-blocker-progress.json)，冻结原台账见 [current-blockers.json](../current-blockers.json)。

| 阻塞 | 当前可用进展 | 下一项实际闭合条件 |
| --- | --- | --- |
| B02 / B15 整合候选与最终资格 | 固定产品头、base、merge tree；原件和新候选已分开登记 | 新候选自己的原 required CI 成功，复核目标 main 和真实产品接受 |
| B07 Hook / 工具可见性 | 已有同源窄范围实现和原生通过 | 原 Hook、MCP、Executor、TokenBudget 及 allow/deny、错配、陈旧目录负控的最终平台结果 |
| B08 私有工具元数据 | 当前 Windows 已读到原 4 个名字中的 3 个通过 | 剩余 namespaced replay 原例及 wire / retained 边界同源验收 |
| B09 终态与恢复 | 当前 Windows 19 个具名要求中的 9 个通过 | turn_recover、特性门负控、取消、panic、watchdog 与 lineage / fence 的完整原范围 |
| B10 WebSocket / prewarm / compact | 原 turn-state 修复及身份约束保留 | 原连接数、请求数、身份变化拒绝与重连边界；不放宽断言 |
| B11 Windows sandbox / helper | 已审权限修复在产品候选，原严格 token 与攻击控制保留 | 原 Windows 实际 helper、权限、文件系统与负控完整终态 |
| B13 Lease / Queue | Windows 两个检出中的原 8 个 Queue 名字通过 | 第 9 个 Agentd qualification 原目标和原平台同源结果 |
| B16 可信入口和效果 | 新主机源码/工具已准备；foundation runner 的已知 CLI 问题修复 | 上述分批实现、原负控以及真实正常调用链和外部效果接受 |
| B18 科学采用 | 原分析与新增研究证据完整保留 | 新的事前冻结 D−B 采用实验、独立数据、完整成本和失败尝试；当前仍 HOLD |
| B19 Bao / Chain / HIA | 已分开清点接口、已实现项和接受缺口 | 固定外部版本与真实调用者兼容、故障、安全、效果回执；HIA 原 DENY_ALL 保持 |
| B20 远程握手 / 断连 | 原生确定性旧源负控与修后原例已有证据 | 最终候选原 AppServer / HTTP 关闭和断连平台资格 |
| B21 Intel PTY | 已取得实际失败；仅测试观察候选已审 | 原 Intel 30 项和完整 drain / child / FD 约束通过，并解释实际失败原因 |
| B22 Windows TUI | 原 interrupt / shutdown 约束保留 | 同源原 Windows 5 秒预算、stdout 就绪和 canonical cwd 的真实结果 |
| B23 Unix shutdown | 已有有效因果负控与 5 个原生通过 | 最终同源原 Unix CI，保原 stdio / disabled 语义 |

B01、B03、B04、B05、B06、B12、B14、B17 仍只按各自原范围闭合。任何现有成功总数都不能替代上述未完成的具体名字或外部接受。

## 6. 项目发展方向与执行计划

近期主线仍应集中在 **P0.8D 的可用纵向切片和 INT-2 的 Agentd / Codex 装配**。Codex AppServer 保持 session、thread、turn、model、tool 的执行主干；Agentd 负责装配与生命周期；优化器只能在已授权约束下提供建议。当前瓶颈是固定版本的跨平台资格、真实产品入口和可证明的权限/取消/恢复语义。继续堆叠独立 Draft 会增加对齐和验收工作，不能替代这一主线。

| 顺序 | 工作 | 可审查的完成产物 |
| --- | --- | --- |
| P0，立即 | 独立 PTY 包原测试 → `just fix` → `just fmt --base 20fd174…`；复核实际差异后更新现有 Draft；观察新原平台 CI | 固定 source、完整 raw/JUnit、零重试、原用例映射、格式前后变化；fmt 后不再做手工复测 |
| P0，并行 | 新主机原供应与全 catalog 准备，逐批推进 B16 foundation 及后续依赖 | 新主机真实 BUILD_ONLY 基线、完整角色身份、正负控和精确恢复；最终正常 caller 接受 |
| P1 | 收敛 B07–B13、B20–B23 的原平台具名缺口，以及 UI 浏览器/原生接受 | 一个固定整合候选的 required CI；任务、取消、重启、丢 ACK、撤权回执可追踪 |
| P2 | 在已通过执行主干上整合共享计算与可靠 Memory | authority、evidence、Memory 和物理效果一致；故障、恢复及回滚可复核 |
| P3 | 只读因果观察和学习，随后独立 holdout / rollback / unlearning | 冻结数据和估计单位、包含全部失败与完整成本的科学证据；无证据时保持强普通默认 |
| 后续 | 高阶自适应、具身和 Bao / Chain / HIA 外部吸收 | 按实际依赖 DAG 和各外部目标接受推进，不能依赖组件名称或定义文件声明生产完成 |

科学 HOLD 有明确理由：#4823 的已有拟合支持特定有限规划 J 相对 C 的结果，但没有完成原 D−B 采用比较；部分收益同时改变计算量，OOD 已在验证阶段暴露，五次 solver 都未达到 success，完整成本与目标生产运行形态仍欠证。验证门拒绝 D 并恢复 C 是回退机制工作，不能改写成 D 已与 C 等价或 D−B 已通过。科学问题应通过新的可证伪实验处理，不能通过修改台账关闭。

本续批没有合并 main、改变目标基线、发布生产服务或启用外部执行权。下一次状态更新以实际原生回执和原 CI 新终态为依据。

### 08:04 UTC 的后续实际失败

原 macOS Bazel 包装器控制 `127089468398` 执行 57 项 Python 控制，其中 3 项失败。完整原 stderr 指向 `run-bazel-ci.sh` 第 98 行的 `failed_targets[@]: unbound variable`；另两个失败是成功日志清单未生成。原 Windows 同一套 57 项已经通过。正在按 macOS 的 Bash 空数组与严格变量检查行为修复，保留原成功日志留存断言。这一项尚未进入上述五个候选提交，后续以独立差异和原平台结果追加。

两个 GNU V8 release 作业又各实际得到同一 sandbox feature 断言的 5 PASS / 1 FAIL，与本批已审 smoke 参数修复范围一致。两个 musl V8 canary 虽在 API 中成功，原日志明确跳过 non-native Cargo smoke；它们只证明各自构建、stage 和上传，不能代替真实 musl CLI 执行门。
