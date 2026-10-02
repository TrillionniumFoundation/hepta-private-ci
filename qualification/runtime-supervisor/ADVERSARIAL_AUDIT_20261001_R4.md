# runtime.supervisor 第四轮对抗审计 — 2026-10-01 UTC

## 结论与范围

候选分支有详细技术开发文档，当前实现仍是部分完成的原生生命周期执行模块。
本轮修复已发现的具体问题，完成独立交叉复审及本地验证，补上 Linux/macOS
source-head 与 prospective-merge 的独立原生 CI 入口。目标主机、独立验收、
激活和发布没有由这些源码或本地结果建立。

审计从 PR #1306 的 `e78095abf8df069d5dc9496f6e362f9ed27e3978` 开始，
PR base 为 `e8f8f2d0ca399b0a68abba4da90a3be5114d0735`。
首次修复源码为 `5489fb84cee5a51e4baa30ecfc665302e68742e7`，
tree 为 `b0813e63eddf49863fd49f38d9383ca4c60299f2`。
首次发布的后续提交只增加当前源码导航和未签名观察材料。
原 `sourceBase` AA68 是不可变集成来源，不是本轮执行身份。

本报告与 [本地观察](LOCAL_EXECUTION_OBSERVATION_20261001_R4.json)
均不是生产资格收据或独立安全验收。

## 最新文档是否足够详细

模块目录有 24 个文件：19 篇 Markdown、5 个 JSON。其中 7 篇明确列为历史记录，
另 12 篇是当前指南、状态和策略。本轮逐篇检查当前材料；历史修复记录保留原样。

| 需要开发者明确的契约 | 当前入口 |
| --- | --- |
| 模块职责、接口、失败语义、构建、完成度 | [TECHNICAL.md](../../docs/modules/runtime.supervisor/TECHNICAL.md) |
| 子进程所有权、信号与退出、进程身份 | [PROCESS_OWNERSHIP.md](../../docs/modules/runtime.supervisor/PROCESS_OWNERSHIP.md)、[PROCESS_LIFETIME.md](../../docs/modules/runtime.supervisor/PROCESS_LIFETIME.md) |
| daemon 锁、取消、串行写入与只读投影 | [OWNER_AND_READ_ISOLATION.md](../../docs/modules/runtime.supervisor/OWNER_AND_READ_ISOLATION.md) |
| 重启预算、恢复域、持久化与资格验证 | [RECOVERY_AND_QUALIFICATION.md](../../docs/modules/runtime.supervisor/RECOVERY_AND_QUALIFICATION.md)、[RESTART_CANCELLATION.md](../../docs/modules/runtime.supervisor/RESTART_CANCELLATION.md) |
| 生产权限、控制操作、凭据和恢复门槛 | [PRODUCTION_BOUNDARY.md](../../docs/modules/runtime.supervisor/PRODUCTION_BOUNDARY.md)、[PRODUCTION_CONTROL_RUNBOOK.md](../../docs/modules/runtime.supervisor/PRODUCTION_CONTROL_RUNBOOK.md) |
| 可机器核对的源码/执行/验收状态 | [CAPABILITY_STATUS.json](../../docs/modules/runtime.supervisor/CAPABILITY_STATUS.json)、[CURRENT_STATUS.md](../../docs/modules/runtime.supervisor/CURRENT_STATUS.md)、[IMPLEMENTATION_MAP.json](../../docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json) |

最新观察到的 main 为 `c6f90d48c40f7b5267db587bb3c3f4934f1414a8`。
main 的模块目录只有 TECHNICAL、RECOVERY_AND_QUALIFICATION 和 IMPLEMENTATION_MAP
三个文件；完整指南仍在候选分支。main 新增五个提交主要影响整体 CI/集成策略，
Supervisor 的少量变更没有提供新的完整模块执行证明。
本轮吸收了不窄化整数的恢复窗口比较；没有整文件覆盖候选已有的严格读取和原子发布。

main 已有详细技术开发文档：实际 TECHNICAL 为 401 行、17 个章节，
RECOVERY_AND_QUALIFICATION 为 174 行、八个章节，覆盖模块职责、生命周期、
持久状态、恢复和验证边界。候选新增专题指南，并修正文档与最新代码间的漂移；
文档详细程度和能力／执行完成度分别评估。

旧指南存在真实漂移：已删除的六字段 verifier 参数、错误的 main/Matrix 重启预算描述，
以及将历史“工具链缺失、源码未执行”写成当前状态。本轮按实际 CLI、源码和具名
观察材料修正，明确区分历史 v2 契约与当前 v3 qualification；未把旧失败或局部
通过改写成当前无过滤全绿。

## 对抗发现与修复

| 问题和影响 | 修复与保留的边界 |
| --- | --- |
| 健康 JSON 自报 PID 没有绑定 Socket 对端，伪造服务可冒充不相关活进程 | 所有 Agentd health/drain、Matrix health 请求在发送任何字节前核对 kernel peer PID。Linux 使用 SO_PEERCRED，macOS 使用 LOCAL_PEERPID；保留 lifetime handle、nonce、generation、root 和完整 wire 校验。 |
| 竞争 daemon 在拿到 owner lock 前打开 Fleet，可能先创建迁移目录或改权限再失败 | 只读检查既有物理目录，先持有 exact descriptor flock，再打开/迁移 registry。失败前不服务 Socket；可信祖先目录仍是部署前提。 |
| 紧急 Kill 先进入 Matrix driver，慢/失败 companion 可推迟主进程终止 | 主进程先准备并尝试信号，再独立尝试 Matrix；两侧错误继续报告，未观察到退出的所有权和租约继续保留。graceful Restart 的 Matrix-first 流程不变。 |
| macOS 禁止移动已取消写权限的目录，旧 installer 导致大量 EACCES | Fleet staging root 保持 0700；payload 先封闭并同步，rename 后封闭最终 root，再同步 root/catalog。中断留下的可写 orphan 不可解析、准入或覆盖，不隐式修复其身份。 |
| control-intent 写入/rename 失败累积本次暂存文件 | 复用 write_atomic，尽力清理本次唯一暂存；保留 create_new、0600、文件同步和同目录发布。目录同步失败仍返回错误，不将可见的新内容视为已确认完成。 |
| 没有任何恢复证据的 Agent 在 constructor 重复完整读取 Fleet | 初始完整 Fleet、全部安全 codec 和独立进程恢复保留；仅物理 run parent 下所有相关 witness 明确 NotFound 时省略两次恢复扫描。存在、symlink、FIFO、损坏或 I/O 错误均进入原校验路径；没有把单 Agent 读取变成准入权威。 |
| paired child 对 Drain 等方法总回复 Health，实际 Drain 校验失败 | 使用真实 typed method 分派，只有确切 Draining generation 才返回 Drain ack；过早、过期和不支持方法均拒绝。新增实际 child/Socket/driver 产品回归。 |
| deep 使用默认重试；五个真实 pair 的多阶段工作被普通 60 秒 watchdog 截断 | 所有 deep 原生命令明确 retries=0；仅命名 qualification profile 的精确 ten-child 叶使用有界 360 秒 watchdog。四个 60 秒阶段和清理预算保留；普通测试预算不变，fixture 完成不冒充产品延迟 SLO。 |
| 新 Fleet 发布回归没有进入 Supervisor 的双平台收据 | 增加独立 fleet-library 全库 record、两条精确 package/test mandatory identity；同计数缺失、前缀或错 binary 均拒绝。15 份 records 必须齐全；Fleet PASS 不能记作 Supervisor PASS。Supplemental PR 入口独立执行双平台 source/merge lanes。 |

本轮修复过程中发现并保留了失败：新终态 release fixture 使用 generation 0，
通过真实 Fleet CAS 推进至 generation 2 后纠正；旧 paired Kill 断言要求 Matrix-first，
与既定 emergency main-first 契约相反，现验证正确顺序并保留所有次数、退出、无替换和
peer 隔离检查。原共享 publish wrapper 的最后编译消费者迁移后产生 dead_code，
已去除 wrapper；三个未接线原型改为等价 publish_at 调用，未激活这些原型。

Darwin rename 依据为 [Apple 官方 rename 文档](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/rename.2.html)。
源码语义依据不代替新候选 macOS 的执行结果。

## 在项目中的位置与完成度

Fleet 拥有不可变 release catalog、allow/revoke 和 CAS 准入事实；Supervisor 是
generation-fenced 的生命周期执行侧，协调 release selection 与进程控制；Agentd
拥有 turn/RPC admission 与 drain acknowledgement。Kernel authority 和 Operations
保留各自权限与操作事实。readiness、缓存或进程退出不建立用户任务成功，也不授予
模型、工具或 secret 权限。

16 项源码能力仍为 **12 implemented、2 partial、2 not_implemented**。
这个分布不是生产完成率。优先阻塞项仍包括：

- 跨 daemon 的 exit-cleanup witness；
- launch-before-lease/rejected-adoption 区间内完整 predecessor/replacement lineage；
- owner 内一次生成、digest-bound 的原子 recovery-observation envelope。

per-Agent 投影仍是部分实现：相同完整输入可复用 status Arc，但每次刷新仍读取
完整 Fleet、全部 metadata 和 readiness。本轮 constructor 优化没有建立 dirty-Agent
传播、选择性 Fleet I/O 或 per-Agent mutation ownership，也没有改变全局完整性校验。
后续这些结构调整须依据混合负载和目标 SLO 证据，先定义失败、排序及准入边界。

## 实际验证与证据边界

| 最终本地阶段 | 结果 |
| --- | --- |
| Default library | 358/358；11 个精确 listener 环境项另记 |
| Qualification/offline-authority package | 387/387，15 binaries；16 个环境项、2 个既有 ignored helper 分开记录 |
| 显式 CLI | 6/6，无排除 |
| Fleet 全 package | 42/42，无排除 |
| Python hosted/evidence/integrity | 73 + 30 + 24 = 127，无 skip |
| Scoped fix、完整 just fmt | 均成功 |
| All-target strict Clippy | Supervisor/Fleet default、Supervisor qualification/offline 均成功 |

四场最终原生执行共享 169 个 native 文件、1034 个 external build inputs（47 个本地
Cargo 依赖的递归闭包），每场前后均无输入、清单或 HEAD 漂移，零重试。
两个 kernel socketpair 叶实际通过。新 paired protocol 真运行保留了子进程 exit101
和 stderr 的 EPERM；该失败没有按通过计算，没有新增源码 skip。

SIGKILL 父用例真实启动、等待子进程发布同步证据、发 SIGKILL 并检查绑定；ignored
child helper 不另算通过。HOL256 父用例实际 179.057 秒完成；这是本机 shadow harness
观测，不是目标主机性能验收。两个 profile 的 mutex 模块路径不同，不能仅用数量差
推断新增测试；具名 inventory 已分别保存。

fix/fmt 后没有重跑测试，遵循 AGENTS。160 个 Rust 文件的生产内容 canonical-format
等价；5 个 Python 文件 AST 等价。唯一 test-only 变化是旧 Fleet ledger helper 将错误
传播至原测试 caller，以消除 unwrap lint；严格编译通过。无关格式化改动已还原。
源码拆成 9 个可审阅阶段，每阶段少于 500 行；本地与 GitHub 创建的每阶段 tree 相同。

[上一个 head 的实际远端观察](REMOTE_CI_OBSERVATION_20261001_R4.json) 显示：
旧 e780 deep 两 lanes 通过，但没有执行完整 daemon/paired/authority-recovery/handoff
产品集合；旧 native 有 Linux 产品失败及 macOS Fleet installer 失败。旧 merge
`6690465` 对应旧 base e8，不能证明 main c6 的集成。
全仓库另有其它模块的非祖先 source observation 等继承失败，本轮没有替它们重绑定
源码或隐去失败。

首次发布后的真实 CI 又发现下面列出的具体缺陷，因此先前源码复审不能作为最终
闭环结果。目标主机、独立安全/代码/运维验收、activation 和 release 继续未建立。
补修后的执行须绑定实际新 head；限定范围的复审停止也不证明所有未来优化均不存在。

## 发布后的 CI 导航与前置补修

`7c4e0ab6acfbea85089a93a00f25bdeb1a2080af` 的 development-docs CI
实际发现两项文档验证问题：历史 README 将已删除的 authoring workflow 路径写成
当前文件引用；source-head 的 broad Python suite 调用真实 Justfile 回归，却没有安装
`just`。前者现直接链接保持原始字节、Git blob 与 SHA-256 的 `.txt` 归档，并明确
workflow 已退役；后者安装与原生资格验证一致的 pinned `just@1.51.0`。
检查器和真实 recipe 测试的强制断言均保留，没有增加 skip。

这两项补修没有改动 Rust、Python validator、原生命名测试或已有原始证据。
更新的 archive README blob 和当前观察绑定另行核对；旧源码执行仍绑定本报告上方
的 `5489fb8`，新 CI 结果须按各自实际 head/base 判读。完整 `just fmt` 再次成功，
46 个无关 formatter-only 路径已还原；遵循 AGENTS，没有重跑本地测试。

后续 blocking CI 还发现本模块两份有意保留的机器生成资产超过 512,000 字节限额：
Robrix canonical cross-parser corpus 与本轮原始归档。按既有政策给这两条精确路径
添加用途、大小和 SHA-256 注释的 allowlist，保留 generator/parity 与归档证据原字节；
全局限额、扫描范围和其它路径检查不变。`FileTests` 改为 `EvidenceFileTests` 以通过
拼写检查，全部方法和断言保持。该命名变化不回写旧具名执行 inventory。
历史收据和修复指南中真实出现的旧 identifier 则通过精确 `filetests` 词项保留；
没有删除这些材料或重写历史测试名称。

Fleet release 修复和 test-only authority helper 还使 `runtime.fleet` 与
`kernel.authority` 的旧 path-only 观察发生真实源码漂移。仅这两份相关 map
迁至 exact-blob/current-observation 模式，保留各自原 `sourceBase`、ownership roots、
全部操作语义和 false claims；Authority 的 16 条历史 witness 全保留，只有实际
变化的 helper blob 更新。没有重绑其它模块的非祖先来源，也没有借本轮 Fleet
测试建立 Kernel/Fleet 产品执行或生产资格。补修源码观察为 `da13c201fccfae2b16856b10ee71310138c329a9`。


## 首次发布的真实原生 CI 与第二次补修

首次发布 `7c4e0ab6` 的 supplemental recovery PR 四 lanes、push 两 lanes
全部完成且失败。六份官方 ZIP 和 90 条独立 record 的日志字节数及 SHA-256
均已核对。PR lanes 的 base 是 e8；push lanes 的 base 是 e780。两个 prospective
merge lane 测试 b9f，与 deep 的 51df 不同；二者都不能证明 main c6 的集成。
完整身份、官方 artifact ID 和 digest 见 [首次发布远端观察](REMOTE_CI_OBSERVATION_20261001_7C4E.json)。

| 实际范围 | Ubuntu 三 lanes | macOS 三 lanes |
| --- | --- | --- |
| 默认 / 生产 library | 369/369 | 365/369 |
| qualification library | 374/374 | 370/374 |
| Fleet library | 42/42 | 41/42 |
| 默认 products | 14/15 | 14/15 |
| 完整 products | 25/26 | 25/26 |

六 lanes 的五对真实进程和新增 typed Drain protocol 都通过，两个 Fleet
copy/seal 回归也全部通过。HOL256、实际 SIGKILL parent 和 authority-distribution
均通过。deep 两 Linux lanes 成功，但未执行全部 products，不能替代上述失败。

共同失败是实际 256 Agent daemon 在原 10 秒等待内未绑定 Socket。首次 absence
优化仍在纯空闲 constructor 执行 260 次完整 Fleet 读取，约 66,560 次 load_agent。
补修仅将重复、无副作用的空闲 hydration 记录为至多 256 项临时观察，在 constructor
结束时再做一次完整 Fleet 校验、比较完整 AgentRecord，并重新检查全部八类恢复
witness 及物理 parent。空 release CAS 即使只增加 generation、没有 run 文件，也会
触发原 fresh 路径；无关 Agent 的损坏仍导致拒绝。发现新的所有权或 pending/denial
状态时保留 exact owner 并拒绝，不二次 adopt；全局读取失败不以 Err 丢弃既有 owner。
纯空闲 256 路径的完整读取从 260 降至 5 是源码调用计数，不是已建立的目标启动 SLO。
混合 / 非空闲恢复仍保留原全局校验，不将局部缓存用于任何 admission 或 mutation。
产品等待也强化为 ready=true、精确注册数量及进程仍存活；保持原 10 秒和零重试。

macOS 的四个 Supervisor library 失败是 cached-catalog 测试移动只读目录出现
EACCES，以及三个真实 peer 负例绑定临时 Socket 路径出现 EINVAL。后者改短以消除
Darwin 路径长度风险，原日志尚不能独立证明该风险是唯一原因。前者只在测试
rename 前临时开放原 root，再恢复 exact permissions；后者使用短 /tmp parent 并在
bind 错误中保留具体路径。全部真实 peer/PID、零 request bytes、未 signal unrelated
child，以及未 spawn / 未 lease / 未修改 lifecycle 的断言保留。新执行才能确认补修。
Fleet 唯一失败是 /tmp symlink 导致 oracle fixture 的 workspace 输入非 canonical；
测试创建后先 canonicalize，保留全部 256 subsets、双身份排序与 oracle 比较。

全仓库 CI 另外发现 16 处 Supervisor anonymous literal 参数缺注释，以及 Fleet
Bazel compile_data 未包含 include_str 使用的 MODULES.json。前者只加匹配 callee 的
参数注释；后者声明单一 catalog filegroup、可见范围只限 Fleet，不引入依赖或宽 glob。
两个改动保留参数值、生产校验及 catalog 原字节。

新增 eight-witness / CAS / 全局损坏等回归与最终 settlement 的真实文件系统回归
均列入当前 v3 的精确 mandatory identities，拒绝同数量缺失、前缀和错 binary 的收据。
本地补修执行编译、scoped fix 和完整 fmt；没有在 fix/fmt 后重跑本地测试。
旧本地 inventory、manifest、归档和结果保持原绑定；补修测试交由新 head 的原生 CI。

补修完成后，default Supervisor/Fleet 与 qualification/offline Supervisor 的
all-target strict Clippy 均通过；完整 fmt 后 46 个无关 formatter-only 路径还原。
新增测试曾在编译中发现宏导入歧义，显式导入 pretty_assertions 后纠正，原失败日志保留。
两次独立源码复审未再发现具体实现缺陷；当前执行和验收状态保持 pending / false。

首次补修源码与验证输入为 `74eda6dbe9a63c043c60e7c468fa353b64bb3854`，tree `2d2015f0c02ab6a2362ae5860a67ec0d34331ad7`。
该次补修的源码身份保留；首次修复源码、本地具名执行和 7c CI 的身份均保留。

在 d74cde5bf1262172086a05f381034ceb64438dd1 的实际 recovery scope 中，
Fleet mandatory 已为三项，但 receipt validator 的有效样本仍只含两个 publication
测试，导致前置 suite 报错，六 native lanes 全部 skipped、零 Rust 执行。
现有效样本加入从 registry_tests 源码核对的 canonical sweep 精确身份，
并对全部三项执行既有 missing / prefix / wrong-binary 反例；生产门槛保持三项。
这次真实 scope 失败日志由 run 36930763804 和 36930754188 保留，不能算原生通过。

收据样本补修源码观察为 `462adb4973c14c958cb696fdf5789ca34fed0a6e`，tree `a9edf57af51a27064e1e631154501789934205af`。
独立复审确认三项正向样本、九种拒绝场景与现有计划一致，整个 codex-rs tree
和 v3 生产门槛保持 d74 原字节；新原生执行仍须按最终 head 核对。

## 整个控制交换的绝对截止时间

后续独立全模块复审发现新的实际阻塞路径：旧 UnixStream::connect 没有连接
超时，设置的 200 ms read timeout 也会被每次成功的部分读取重新开始。
即使对端 PID 正确，满 accept queue 或持续发送没有换行的字节仍可能长期
占用生命周期线程，推迟 Kill 升级；健康探针在查询返回后才更新标志，也可能
无限保留此前的 ready=true。64 KiB 帧界限不能代替经过时间界限。

Agentd health、typed Drain 和 Matrixd health 现在共用私有传输实现。一次交换
从连接、内核 peer PID 核验、写入、半关闭到读取和返回共用原有 200 ms 绝对
deadline；成功的部分读写和 Interrupted 不续期。Linux 满队列 EAGAIN 直接
拒绝，EINPROGRESS 必须在剩余预算内确认 SO_ERROR 和实际 connectedness。
PID 验证通过前不发送请求字节。macOS 设置非阻塞、close-on-exec 和 SIGPIPE
保护。原有首行、maximum+1、nonce、generation、schema、目录绑定和 Drain
确认检查保留；超时不构成 DrainAck、退出证明或释放所有权的依据。

新增四项 Linux/macOS 共同真实 socket 回归，覆盖完整帧、持续部分读取、错误
peer 的零请求字节，以及超限／不完整 EOF；另有 Linux 满队列回归，以外层
watchdog 和失败后的 listener 释放确保测试不残留阻塞线程。共同四项进入 v3
精确 mandatory identities；Linux 专有身份不会作为 macOS 的执行要求。
独立只读复核未找到新的具体反例。本地只编译、scoped fix 和完整 fmt；实际
执行须由新源码身份的原生 CI 建立，d016 及之前的结果不能替代本次修复验证。

这修复可防止协议进展无限续期和通常的 Socket 队列等待，不是可抢占的内核／
文件系统保证，也不是整个 Stop、adoption 或 256 Agent constructor 的 200 ms
SLO。两秒只读投影新鲜度、已经开始的 owner callback、跨 daemon 清理见证、
原子恢复观察和每 Agent 调度隔离缺口保持原状态。能力状态仍为 12 implemented、
2 partial、2 not implemented；目标主机和独立验收、激活、发布均未建立。

本次传输修复源码为 `9e27dab1e445ab04c0e7ea6b68a2dd89e5bc9ab0`，tree
`adb9bf639b274b8cbeed8db00c5488921fbb22be`。三个复杂修改 stage 分别为
452、170、83 changed lines，API tree 与本地 tree 逐阶段一致。默认
Supervisor/Fleet 与 qualification/offline Supervisor 的 all-target strict
Clippy 均通过，完整 fmt 后只还原 46 个无关 formatter-only 路径。

## Darwin 已断开连接的测试服务端竞态

d016 的真实 Linux 全部 native 范围通过，包括 381 项默认／生产 library、
386 项 qualification、42 项 Fleet 和 15／26 项产品测试。macOS 三库的剩余
失败仅涉及 forged Agentd、forged Matrix 和 foreign Drain 的三个 peer 负例，
日志为裸 Os EINVAL；cached catalog、12 项 constructor、Fleet 三项必测和
全部产品范围均通过。这些结果仍只覆盖 d016，不验证后续传输源码。

先前短路径处理没有解决该残留失败。三个负例在身份拒绝后关闭客户端，
服务端接收连接再设置 SO_RCVTIMEO／SO_SNDTIMEO。Apple XNU Darwin 24 家族
源码明确建立了这个竞态：Unix stream disconnect 在两端设置完全关闭标志，
而 sosetoptlock 对该状态的 setsockopt 返回 EINVAL。实际日志没有 syscall
上下文，故这是与日志一致的源码解释，不是已经取得逐 syscall trace。
新增的 common transport fixture 也有同样模式，必须同时纠正。

测试服务端改用显式非阻塞 fd 和经过时间有界的读写循环，避免关闭连接上的
timeout setsockopt；accepted socket 在 Darwin 继承 listener 的非阻塞状态，
也不再依赖它能立即完成 read_to_end。原 200 ms／1 s fixture IO 预算、有效
伪造 JSON 回包能力、精确连接计数、零请求字节、拒绝 adoption、子进程存活
及所有测试名字保留。不吞掉 EINVAL，不延长门槛、重试或跳过用例。
修改是否解决真实残留失败，必须由新 head 的 macOS 执行确认。

固定的 primary source 是 XNU `xnu-11215.81.4` 的
[socket option 校验](https://github.com/apple-oss-distributions/xnu/blob/xnu-11215.81.4/bsd/kern/uipc_socket.c)、
[Unix disconnect](https://github.com/apple-oss-distributions/xnu/blob/xnu-11215.81.4/bsd/kern/uipc_usrreq.c)
和 [关闭状态设置](https://github.com/apple-oss-distributions/xnu/blob/xnu-11215.81.4/bsd/kern/uipc_socket2.c)。
它建立 Darwin 24 家族语义，不冒充 runner 24G830 补丁内核的精确执行身份。

六 native lanes 和两条 deep lanes 的真实身份、具名失败、官方 ZIP digest、
90 条 native 原始日志的字节／SHA 校验、零重试与干净源码证明已冻结在
[d016 远端观察](REMOTE_CI_OBSERVATION_20261001_D016.json)。Linux 三 native
成功、macOS 三 native 失败；deep 两条成功仅证明其较窄范围。该历史材料不
为新源码、当前 main、生产激活或独立验收转移资格。

最终 fixture 补修源码与指南为 `4b6b5afbe80cc8e25963dcd18ef72a54a6496d8b`，
tree `f0eb8dd82c1eb058dc233e0b089144b798ae6880`。两个 reviewable stages
分别为 237 和 40 changed lines，API 与本地 tree 一致。再次完成 scoped fix、
完整 fmt 和默认／qualification-offline all-target strict Clippy，未在其后
重跑本地测试。新发布候选须取得自己的 Linux/macOS source 和 merge 执行。

## 已确认控制阶段的期限升级不得被观测错误饿死

最后一轮全模块对抗复审发现另一条真实路径：driver 成功接受 Drain 或 Stop
后，pending control 被清空，而阶段的原期限仍有效。随后持续的坏 Drain
回复让 poll 返回错误，旧 tick 在检查阶段期限前返回，因此 Stop／Kill
升级可以永久饥饿。即使 poll 有界，重复失败也不能保证已接受的期限执行。
同样，完整 Fleet 读取中的 unrelated Agent manifest 损坏会更早阻断升级。

现有 Draining／Stopping 阶段到期时，按当前已持有进程的 spawn generation
恢复控制意图，合并时保留更强的 Kill 和更早的期限。Drain 到期沿用原
Drain limit 加 stop grace；迟到超过两个期限可直接 Kill，不重新给预算。
这些已确认且到期的阶段及下述已准入的当前意图，在可失败的 Fleet 读取及
poll 前执行终止控制。
新准入、普通未到期 pending 控制和生命周期 CAS 继续原有完整 Fleet 校验；
已保存的真实 observed exit 保持最先处理，不再发送信号。

成功事件只发出一次；信号、Fleet、poll 错误在实际发生的路径分别保留，
不把错误改成 DrainAck、健康、退出证明或清理授权。generation 漂移仍执行
原 fencing 和精确句柄终止；已成功 Kill 不重复发送。失败不丢弃 owner 或
删除租约，只有真实进程退出观测及原有 durable finalization 才完成清理。

新增五项公共 Supervisor::tick 回归，使用真实 Fleet 文件和既有进程测试
driver，覆盖确认 Drain／Stop 后持续 poll 错误、信号与 poll 双错、原预算
和更强 Kill，以及确认 Stop 后全局 manifest 损坏。检查原租约字节、句柄
保留、真实 fault 和事件次数；修复观测后才允许真实退出清理。五个精确
叶身份加入 v3 mandatory requirements，缺失、前缀及错误 binary 收据仍
必须被拒绝。它们只能由后续自己的源码 head 执行，不能引用 1f 或旧 CI。

这项修复只关闭已有进程终止控制的观测错误饥饿路径，不填补跨 daemon
退出清理见证、完整 launch-before-lease lineage、原子恢复观察或逐 Agent
调度隔离缺口。16 项能力的 12／2／2 状态与全部验收边界保持不变。

同轮边界复核还确认，非零 Duration 不等于 Instant 上可表示的组合期限。
stop grace 为 Duration::MAX 时，旧配置检查可以通过，Drain 也可成功开始，
但原 Drain limit 加 stop grace 每次都溢出，永远不能升级。恢复入口在取得
任何 driver 所有权前检查给定 now 的完整 Drain／Stop 预算；每次 Drain 在
deferral、fencing、CAS、信号前按实际 now 再检查。不可表示的预算直接拒绝，
不把溢出解释为 Kill 权限。两项真实文件／进程 driver 回归验证恢复零取得
和现有运行进程的生命周期、租约字节、事件及调用次数不变。

Matrix 的直接 containment 路径也曾丢失诊断：首次 Kill 失败后，随后的
poll、Fleet 读取或租约清理失败可覆盖该信号错误；旧回归只覆盖较早的
generation fencing 控制路径。私有 companion tick 现在携带当前 TickReport，
在后续失败返回前保留控制错误一次，直接返回控制错误时不重复记录。
公共 tick 回归覆盖 main poll／Matrix Kill／Matrix poll 三错，以及真实
Matrix exit 后的租约清理失败；双进程所有权和租约保留，保存 terminal 后
仅重试清理，不重复发送信号。已完成的真实退出仍由原条件决定，不改成
虚构故障、Exit 或恢复授权。这些新增具名回归同样须取得新 head 的执行。

扩大同类复核后，首次 Drain／Stop 信号失败留下的已准入 pending control
也必须覆盖：此时 runtime 仍可为 Running，但同 incarnation 的原意图和期限
已经建立。坏 Fleet 记录不能阻断到期的 Stop／Kill；已有 current pending
Kill 也须立即重试。过期阶段和这些已建立的当前意图共用同一执行／事件／
错误复用路径。未到期 Drain／Stop、stale spawn 意图及新准入没有获得额外
权限。三项公共 API／真实损坏 manifest 回归分别覆盖首次 Drain、Stop、Kill
失败，并验证 stale incarnation 不发送信号。

Matrix 的统一 kill helper 同样须尊重已保存 terminal：真实 exit 已记录、
但 foreign lease 阻止清理时，随后主进程 generation CAS 曾再次调用伴随
进程 kill，制造 ESRCH 或虚假 KillRequested。统一 helper 现在只撤销健康和
服务权限，保留句柄、租约及原阶段；该 terminal 不再 signal。已有清理回归
增加真实 Fleet CAS 和必定失败的 probe／signal，证明只重试准确所有权清理。

## 签名变更的 durable effect boundary

有效签名的升级可能已发布 Prepared intent、release transaction、推进
lifecycle 并发送 Drain，却在第二次 Queued intent 发布确认时失败。旧入口
返回普通 Driver／Invalid，RPC 又按 mutation_started=false 给出安全拒绝，
错误暗示没有发生变更。签名 recovery 的两个 terminal 发布之间也有同类
durability ambiguity：rename 已发生但 directory sync 确认失败。

另确认一个既有协议缺口：Prepared intent 已发布但还没有 release transaction
时，现有签名 resolution 强制要求 transaction digest，无法解除该隔离。
离线 legacy abort 只写 digest-only directive，生产恢复不消费它；现有真实
integration test 明确验证仍 blocked。旧指南称退出后自动 Aborted／ready，
runbook 暗示离线可以 terminalize，均与实现不符，现已改为明确不支持。
本次错误分类只保证可信隔离和真实未知结果，不伪造缺失的 journal、物理
退出或签名授权。这条缺口须由带版本的授权终止协议补齐，不作已完成声明。

验签、catalog 和 preflight 的纯拒绝保留原分类。首次持久化发布尝试之后，
无法确认的失败使用已有 SignedMutationIndeterminate，由已有安全 RPC 映为
operation_indeterminate。保留可信 RecoveryRequired intent、原始 bounded
diagnostic 和精确进程所有权；恢复 marker 自己发布失败也不解除隔离。处理
terminal recovery 时保留磁盘中原决定的精确 replay witness，仍验证签名、
expiry、epoch、frontier 和状态；两个 durable 确认全部完成才推进 revision。
发布尝试和不确定性都不冒充已完成物理执行、退出或权威验收。

新增三个真实签名／Fleet／RPC 回归分别覆盖纯拒绝零效果、真实 Drain 后的
Queued 发布失败，以及 Prepared rename 后 sync 失败且零进程交付。既有
signed rollback recovery 回归保留所有实际 publication fault cuts 和精确
重试／revision 断言，并加强为明确的 Indeterminate 错误类别。编译曾发现
assert_eq 导入歧义及不存在的 measured try_lock；改用现有异步 lock，失败
日志保留，没有为测试扩大锁接口。

## 文件与目录的特殊文件替换窗口

另一个真实可避免阻塞是 lstat 校验与重新 pathname open 之间的 FIFO 替换。
无 O_NONBLOCK 的只读 FIFO open 会等待 writer，后面的 fd type／inode 校验
无法执行；[POSIX open](https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html)
定义了这一行为。这个问题在 owner 可修改的控制文件／安装输入中成立；
sealed catalog 的同 owner 替换还需要恢复目录写权限。它不是跨 UID 的授权
绕过，也不同于不能抢占的正规文件系统／内核调用。

authority bundle 保留 inode、euid、private mode、link 和 digest pin；Matrix
binding、signer request 文件、三个 private seed loader、public-key CLI 共用
非阻塞 fd 打开并在读取前核验普通文件／字节界限。读取使用 maximum+1，
文件在打开后增长也不能解除界限；seed 保留 Zeroizing storage 和原 32 字节
及权限约束，stdin／显式 key-fd 的流式协议不改变。public-key 文件建立
8 KiB 输入上限，仍接受原 32 字节原始值或 trim 后 64 位 hex 表示。

Fleet 的 Agent TOML／lifecycle、catalog／allow／revoke／release state 和
frontier 读取，以及源程序复制和 digest 读取，都绑定非阻塞 fd 的真实类型
与身份。原 32 KiB JSON 上限保留；没有固定上限的记录／程序以捕获的长度
界定此次操作，复制和 hash 要求长度一致。全部 canonical、closed-world、
catalog seal、全局校验和 CAS 继续执行。为使用命名 ABI flags，Fleet 仅添加
已有锁定 workspace libc 的 Unix 依赖边，Cargo.lock 仅增加该边，无新版本。

同类 directory→FIFO 替换也不能让 publication／lease cleanup 在 fsync 前
卡住：Unix 目录 fd 使用 O_DIRECTORY／NOFOLLOW／NONBLOCK／CLOEXEC，并核验
真实 directory，再执行原 fsync。原 durability fault hooks 与确认顺序保持。
Windows 目录同步契约不改变。它不证明可抢占所有祖先路径或正规 fsync。

真实 regular／directory metadata 后的 rename-cut 回归共用生产 helper，
外层 watchdog 只为旧阻塞实现提供退出清理，修复必须在释放 writer 前拒绝。
Fleet 回归通过公共 load／catalog／digest／install API 验证拒绝、原记录、
marker 与 staging cleanup；descriptor 增长回归验证实际打开后的字节界限。
新增 exact binary/test 身份和有效 Fleet 收据样本一起更新，missing、prefix、
wrong-binary 拒绝规则保持，不能只有生产必测项增加而样本仍缺失。

## 后续真实 CI 与本轮源码的边界

1f1113884a5af82a6153fc694f2d290224f1f07a 的六 native lanes 和两条 deep
lanes 已实际全部通过，官方八份 ZIP、90 条 native 原始日志的字节／SHA
与具名结果完成核对，冻结在
[1f 远端观察](REMOTE_CI_OBSERVATION_20261001_1F111388.json)。Linux 每 lane
default／production 386、qualification 391、Fleet 42 全通过；macOS 每 lane
为 385／385／390／42，差一项 Linux 专有满队列回归。各 native lane 的
default products 15、products 26、真实五对协议、typed Drain、256 Agent
roster、HOL、SIGKILL parent、authority smoke、两 lint 和 clean identity
均通过，既有 helper 的 ignored 状态单独记录。macOS 的三个旧 peer 失败
与四个共同传输回归，在三种 library 中全部按精确名字通过。

这些成功只验证 1f 的传输／fixture／constructor 等原字节，不验证本节
之后的阶段／pending 期限、signed effect 分类、文件／目录 fd 读取源码。
6958 补修新增 20 个 Supervisor 和两个 Fleet 测试叶；common repair mandatory
为 76 个，Fleet 为五个，其中一个既有 signed terminal 回归仅加强断言。
这是静态源码要求，须在自己的新 head 上真实执行，不能把数量预测或历史
通过填入新收据。验收、当前 main 合入、生产激活与发布仍未建立。

Cargo 的包集合、版本及 checksum 全部保持，仅增加 Fleet→libc 依赖边。
本地必需 Bazel lock 更新首次因工具缺失失败，官方二进制网络读取超时；
保留真实失败日志。现有只读 diagnostic workflow 增加本审计分支的 Cargo
路径 push 触发，只有 Bazel lock candidate job 自动运行，其余四项仍仅
workflow_dispatch。使用真实 Bazel 生成及后验 lock-check artifact；job green
不足以证明生成成功，必须核对 update／after exit、head 和文件身份。
这不减少既有检查、修改 required gate、增加 retry 或延长门槛。

发布前严格 all-target Clippy 已在最新源码通过：Supervisor／Fleet default，
以及 Supervisor qualification／offline-authority-tools，两组均使用
`--no-deps -- -D warnings`。required scoped fix 与全量 fmt 已完成；没有在
fix／fmt 后重新执行本地测试。静态逐名核验覆盖真实模块路径：76 个 repair
mandatory、Fleet 五个，Fleet 正向样本与五乘三类拒绝保护完整。额外补齐一个
既有 cached catalog admission mandatory 的防删除回归检查，repair 保护集
从 75 补齐至 76，实际测试结果仍须由新 head 的 CI 建立。

源码变更先拆为十个 reviewable stages，实际改动分别为
256／225／248／389／457／373／431／404／399／122 行，每阶段低于 500；
逐个 API blob 与本地 object 相同，逐阶段 tree 相同。随后一个小阶段补齐
上述防退化检查与只读诊断 receipt。6958 的诊断产物明确记录 exact source／tree／
parents、更新前后五个输入 SHA、candidate copy／hash 退出码；真实 lock
生成需要 update、after、copy 和 hash 全部成功，绿色 job 本身仍不是证明。

6958a901d1318f01fe836aa679f501d4b610637b 的真实 Linux Bazel 诊断中，
before／update／after／copy／hash 均为零退出；生成 candidate 与原锁文件
字节及 SHA256 相同，实际更新无需修改 MODULE.bazel.lock。不制造空锁差异，
也不借此声称新的 package 或生产资格。该历史 receipt 只记录五个选定输入，
没有单独记录工作区 Cargo.toml。后续候选的诊断补至六个选定输入，并记录
生成前完整 tracked-clean 与生成后除 lock 外的 tracked drift；这些增强
须由自己的 exact head CI 确认，不能补记为 6958 已执行。

## 6958 真实执行发现的时钟与健康回归

6958 的两个 deep lanes 实际 default library 均运行 406 叶：403 PASS、
三 FAIL、零 skip、零 retry；后续 qualification／products／lint 因失败未运行。
第一个 base lane 原始日志 SHA256 为
`7d35d2d86346035161b271d2e5c1ebacd4c0459786ba2307c002707335be45e1`。
三个失败为既有 prepared-release recovery 的健康断言，以及新增 acknowledged
Stop／failed-initial-Stop 原期限断言。额外 Agentd Ubuntu 执行确认同三个
失败，但该额外 workflow 使用默认 retry，独立记录，不能作零重试 qualification。
这些真实失败没有改为环境项、跳过、通过或提高预算。

两个独立诊断确认：fresh Stop 先记录 wall-clock deadline，发布后再扣去
fsync 等经过的 wall time，却把 remaining 加回更早 supplied Instant，因而
原 10 ms 单调期限可缩至 9 ms 或更早。修复对 fresh preparation 只建立一次
checked monotonic deadline，在 publication 前验证 representability，成功取消
durable restart 后才保存在同 incarnation 的 pending。Retained Stop／Kill
及 acknowledged phase 继续使用原强度／期限；仍读取并校验 journal 的 digest、
exact target 和 wall rollback，无 in-process continuation 才执行原恢复换算。
wire、schema、signed authority 与跨 daemon wall-clock 恢复格式不变。

另一个失败是前置控制成功后清 pending，再读取 retrying 丢失本 tick 的控制
事实，旧 healthy probe 回填了 readiness。现在保留该事实；后续 Stopping／
Killing 的 live probe 也不能重新宣告健康。原 Draining 语义保持。未到期且同
owner 的 Matrix-deferred Stop 继续遵守 companion-first，并允许原 Running
观察，不能因保存期限而提前主进程信号或 companion emergency Kill。

新增一个真实 Fleet／两份 lease 配合 deterministic process driver 的回归，
覆盖 Matrix Stop 成功与失败、Retained 重试不续期、9 ms 无提前信号、10 ms
一次 containment、11 ms 未退出不回填健康、明确 poll exit 后正确清理且无替换。
它不冒充真实 OS child 或目标机 SLO。最终补修源要求因此为 21 个新 Supervisor
叶、两个 Fleet 叶、77 个 repair mandatory 与五个 Fleet mandatory；6958 的
历史 20／76 要求与失败观察不重标。新源码仍需要自己的完整远端执行证明。

[6958 真实 Bazel 锁文件诊断](BAZEL_LOCK_DIAGNOSTIC_OBSERVATION_20261001_6958A901.json)
保留实际 run／job／官方 ZIP、17 成员 hash、五选定输入与 exact API bytes、
五退出码和不变 candidate 的原始结论；没有新增锁内容或未来执行信用。

上述时钟／健康修复交付后，scoped fix 的 default 与 qualification 配置、
完整 fmt、Supervisor／Fleet default strict all-target Clippy，以及 Supervisor
qualification／offline strict all-target Clippy 均通过。仅执行编译／静态
检查，fix／fmt 后没有重跑本地测试；独立源码复核未找到新的具体反例。
同 head 原生 CI 仍是新修复验收的必要条件。


## 最终源码绑定与开发文档核验

完整补修源码冻结于 `6c6c051e8f0fac8ce766fe1dc6eb7eda1c6cb58c`，
tree 为 `8c78d5c7faeeabfa24e75d0d2884a9d330a77f25`。前十三个源码／指南
阶段实际改动为 256／225／248／389／457／373／431／404／399／122／38／
368／191 行，每阶段均低于 500；各 API blob、tree 与本地阶段一致。
随后的 metadata 只将 Supervisor／Fleet／Kernel 三份实现映射绑定到该源码
祖先，保留各自 sourceBase、owner、原 claims／gaps 与 12／2／2 能力状态。
逐项原始对象证明和独立 Git 对象核对均确认 156 个 source objects
（154 blob、2 tree）及 23 个 operation bindings 精确一致；新增 34 个
explicit support／dependency 对象涵盖新 helper、测试及实际依赖／锁收据。
这证明具名绑定，不能替代最终候选的执行或全项目文档闭包。

main 快照 `c6f90d48c40f7b5267db587bb3c3f4934f1414a8` 已有三份模块文件：
IMPLEMENTATION_MAP、TECHNICAL、RECOVERY_AND_QUALIFICATION。TECHNICAL 为
401 行／27,742 字节，包含权属、架构、接口、持久化、并发、故障恢复、威胁、
性能、运维、验收与完成定义的 17 个二级章节；恢复／资格指南为 174 行／
12,043 字节。因此明确存在详细技术开发文档。候选模块目录现有 24 个文件
（19 Markdown、5 JSON），本轮补充精确源码语义和运行边界，但文档详细程度
与源码／执行／部署完成度分别判断，不能以页数或声明代替运行证据。

增强的最终 Bazel 诊断另经对抗静态复核修正：set+e 中 non-lock git status
必须记录自身退出码，combined drift 成功同时要求命令成功及输出为空，
避免命令失败产生空文件被误判 clean。after identity 与六输入 hash 也独立
记录退出码。Bash 语法检查通过；这些增强必须在最终 exact head 上实际
运行，尚未获得执行信用。该 diagnostic workflow 不在三份 map 的源码
对象或观察路径闭包内，因而 metadata 源码祖先仍精确绑定上述 6c 源码。


Canonical verifier 首次指出新增测试引用中的 signed_intent_recovery.rs 尚未
进入 sourceObjects；已补齐该既有源路径的精确对象并重新按 canonical inventory
逐项静态核对，156 对象与 23 operation 绑定一致。首次失败保留，不把原 155
对象的哈希一致误写为完整 inventory。全项目校验同时揭示本轮 Cargo.lock
依赖边变化造成七个其他模块的输入观察漂移，须逐项证明无其他源码变更后
最小重绑；七个不可访问历史 provenance pin 则单列，不提升任何完成声明。


## 6958 原生／深度观察完成封存

[6958 全部八条远端观察](REMOTE_CI_OBSERVATION_20261001_6958A901.json)
冻结六 native lanes 的 90 条原始日志与六份官方 artifact ZIP 的逐文件
byte／SHA 验证；每 lane 15 records、九条无过滤零重试命令和 clean identity
均具名核对。Linux 每 lane default／production 406 叶为 403 PASS、三 FAIL，
qualification 411 叶为 408 PASS、同三 FAIL；macOS 对应 405／405／410 为
402／402／407 PASS 加同三 FAIL。每平台只有那三个已列明的时钟／健康
断言失败，76 个历史 repair mandatory 中 74 PASS、两个 FAIL。

各 native lane Fleet 44／44、五个 required names，以及其余十二个 stage
实际均通过，包括 products 15／26、HOL、SIGKILL parent、authority smoke、
validator 73、两 strict lints、格式和 identity 检查。两 deep lanes 只实际
执行 default 406 叶（403 PASS、同三 FAIL），后续步骤跳过；不能写成 deep
完整通过。各 assembly／资格均为 false，不凭通过的步骤隐藏整体失败。
该 compact SHA256 为
`128ba6c979d13c15062a87cf8aa8b4ec607d3fc2da4c5a8fd6a02552f5fa2529`。

全项目文档 raw 也明确保留本轮共享 Cargo.lock 输入造成的七个其他 map
漂移，以及当时尚未重绑的 Kernel／Fleet／Supervisor 关联漂移。另一组
七个历史 pin 的真实远端失败是 nonancestor（merge-base exit 1），不能
等同为已证明 missing。模块源码、源码绑定、执行与资格分别判断。
本 compact 不验证之后新增的 Matrix 终态／延迟控制与 signed 恢复修复。


## 2026-10-02 组合审计的继续修复

扩大有界组合复核后新增的具体反例继续修复，不用历史 CI 成功替代新代码：

- 已观察 Matrix 真退出但 foreign-incarnation lease 阻挡清理时，public
  Drain／Stop 仍可能再次信号终态 owner。现保留 matching deferred marker
  与 owner，仅等待 exact cleanup，不再发信号、改 phase 或记控制事件。
- 主进程原期限已 acknowledged Kill 后，晚到的 Matrix cleanup 可能恢复
  deferred Stop，再次 Kill 主进程。现到真正 cleanup 后才丢弃同 spawn
  的终止 marker，不重放 control／CAS，也不把 Kill 视为实际进程退出。
- 同 spawn deferred Drain 尚未完成、主进程实际退出时，原 Running phase
  会错误准入 automatic restart。现在既有 deferred termination 会阻止
  新预算／lineage／replacement，stale spawn marker 不挡正常重启。
- signed release 原先先发布 unsigned Prepared，再单独绑定 authority；
  第二写失败留下可被 cold recovery 按 unsigned 重放的事务。现在第一次
  publication 即含完整已验证 authority。对旧 partial journal，constructor
  在任何控制／语义重放前纯读取并验证 typed intent，建立 trusted denial，
  继续独立取得 main／Matrix exact owner 并 containment。完整 signed
  CAS／terminal-witness 写入仍在 owner acquisition 后。真实无 signed
  denial 的 unsigned 自动恢复保留；旧 unsigned Prepared + signed denial
  不能自动 Drain、terminalize 或 spawn，也不伪造缺失 authority。
- trusted denial 原先可能在真实退出／Missing／Rejected 时准入 main 或
  Matrix 新重启 claim。现在保留诊断、真实退出、精确清理与旧持久化事实，
  禁止新自动 claim。失败 containment 各 owner 在 constructor 尝试一次，
  用 bounded main event／Matrix report 保留错误，后续 tick 再重试。

primer 对真实匹配的 Committed／RolledBack transaction + release state
证明导出纯内存终态，防止 Queued／RecoveryRequired 历史 intent 错杀合法
目标；后续仍 fresh-read／publish。codec/projection 中的 Aborted 没有生产
签名 decision producer，未把任意 raw Aborted 或 legacy digest directive
当授权终态。Prepared 无事务或缺 authority 的显式终止仍需版本化协议。

新增两个 Matrix 和五个 signed constructor 叶，使用真实 Fleet、leases、
签名验证和 journal publication，进程观测明确为 double；不冒充 OS child
或目标 SLO。既有 transient_release_recovery_fault_does_not_skip_signed_intent_recovery
保留名字及 ownership／quarantine 断言，oracle 加强为根本不调用被注入的
Drain；没有跳过、延长预算或把原 unsafe Drain 路径接受为成功。

当前静态要求为自 1f 新增 28 个 Supervisor、两个 Fleet 叶，84 个 common
repair mandatory 与五个 Fleet mandatory。逐项源码名字与 missing／prefix／
wrong-binary 拒绝保护集合一致；旧 6c 的 21／77 和 6958 的 20／76 不重标。
source 与组合复核由独立 reviewer 检查，限定范围内无新具体反例。

最新源码 scoped fix default／qualification 分别通过（41.92／17.19 秒），
完整 fmt 通过且从正确 repository root 恢复 46 个仅 formatter 产生的
无关文件，保留全部 20 个授权路径。严格 all-target default Supervisor／Fleet
Clippy 通过（35.10 秒），qualification／offline Clippy 通过（10.44 秒）；
均 --no-deps -- -D warnings。fix／fmt 后没有本地重跑测试。新 exact head 的
完整远端执行仍是交付必要条件，12／2／2 与所有生产资格限制不提升。

## 最新完整源码与共享输入绑定

此前 6c 源码、156 对象／23 entrypoint 绑定和 21／77 回归要求是历史
checkpoint。最新完整修复源码为
`90ef2d19255502306488ef9009eed916a6d004bb`，tree 为
`ac043ce60a390b7515989f11ed580b4e83f12bff`；二十个源码、指南与历史
证据阶段实际改动依次为 256／225／248／389／457／373／431／404／399／
122／38／368／191／427／16／153／196／468／484／306 行，各阶段低于
500，API blob 和 tree 均与本地 immutable Git 对象相同。当前 84 个
common repair identities、五个 Fleet identities 是源码要求；自 1f
新增 28 个 Supervisor、两个 Fleet 叶。它们尚未取得最终 head 执行信用。

三份关联 map 的 canonical inventory 现在包含 160 个对象（Supervisor
144、Kernel 16）及 23 个 operation entrypoint blobs。新增三份 signed
constructor 模块／测试和真实 6958 历史失败 receipt 均绑定实际源码对象。
七份共享 Cargo.lock map 的历史 evidence／root／observation 闭包到新
源码逐项证明只有 Cargo.lock 改变：1518 个 package 的版本、来源和
checksum 不变，仅既有 Fleet 增加 workspace libc 依赖边。它们保留
immutable sourceBase 和原 identity policy，增加 exact_blob 模式与
92 个真实 operation blobs，绑定 90ef current observation；其余
108 个 canonical 对象保持真实。合计 268 个对象（249 blob、19 tree）
和 115 个 entrypoint bindings，十份 map 的完整结构／源码规则静态核对
通过，不提升 owner、claims、gaps、capability 或激活状态。

另外七份历史 provenance map 未修改。6958 远端 raw 对它们的实际错误
是 nonancestor（merge-base exit 1）；本地对象未 fetch 的访问失败不等于
已证明远端缺失。共享锁漂移是本轮造成且已修正，不能归入无关历史问题。
历史结果交叉核验也纠正了 metadata 草稿误把 1f 的 deep PASS 带入 6958：
6958 六 native 和两 deep 全部失败，两 deep 实际只跑 default
406／403 PASS／三 FAIL，随后 qualification／product／lint 跳过。
冻结 raw 与 receipt 不改写；只修正解释，不把静态 schema PASS 当运行证明。

最终 metadata 候选将以 clean committed checkout 再执行完整 map verifier，
随后单独进行六 native、两 deep 和增强六输入 Bazel 诊断。上述对象与
源码检查不代替这一执行，也不建立 current-main merge、目标主机、独立
验收、生产激活或发布资格。

## 5b71 远端反例及继续修复

`5b71df96f682765b01357ccf4af62f7b4917d02a` 是完成静态复核后发布的
实际候选，不把它重标为成功。其 source／base deep 默认库各实际执行
414 叶，412 PASS、两 FAIL、零 skip、零 retry；后续五组跳过。原三个
时钟／健康失败及八个新增 mandatory 均在这两条默认库中逐名 PASS，
84 个 mandatory 中 83 PASS、一个 FAIL。新失败为：

- `new_corrupt_signed_witness_runs_fresh_validation_and_denies_recovery`：
  signed codec 被先后重复读取，错误数实际二而原断言为一。
- `process_recovery_fault_does_not_hide_signed_recovery_required`：
  提前 signed denial 令 adopted main 在纯 catalog 检查前短路，已撤销
  release 原应保留的 fault 被吞掉，实际零而原断言为一。

[完整 5b 历史执行观察](REMOTE_CI_OBSERVATION_20261002_5B71DF96.json)
已收齐六 native 的 90 份 record log、六官方 artifact ZIP 与完整官方 raw，
逐原字节 SHA、身份及 raw 行序核对通过。六条均失败：Linux default／
production 为 414／412 PASS／两 FAIL，qualification 为 419／417／两；
macOS 对应 413／411／两和 418／416／两。三库每条 mandatory 均为
84／83 PASS／一 FAIL；Fleet 44／44、五 mandatory 和其余 12 阶段实际
通过。两 deep 也失败；没有成功 qualification assembly，不借用任何
未来修复、88 identities 或原型归档的执行信用。

全仓 docs source 实际 803 执行、801 PASS、两 ERROR，两个 traceback
与 Lane B source／merge 同源：新增 Matrix 测试导航把 `file.rs::leaf`
写入 test.path，而严格 canonical path 不接受冒号，truth 校验也要求
实际文件。五个 operation 的十处 path 改为真实文件，kind 与命令中的
exact leaf 不变；既有 validators 不放宽。真实 canonical_path 已检查
全部 121 个 Supervisor 测试引用。之后暴露的 Agentd delegated-owner
索引不闭合来自与 base 相同的 map／truth／guard，不宣称 Lane B 全绿。

继续组合复核还确认，idle restore 会清空 expired Matrix 预算，或在墙钟
rollback 时 normalize future 窗口。它必须位于完整 typed validation 与
signed denial 之后；无 owner 时真实坏 persisted catalog 的纯诊断也必须
保留。修复保留原两失败叶名字、断言和预算，并新增这些组合的实质回归。

cargo-shear 的三份 Supervisor orphan 在 base 已缺声明链接；本轮机械
publish_at 适配改变其 blob，不能说与 base 字节相同。它们已按 5b 原
字节移入 history/unlinked-prototypes，显式 authoring CLI 仅在原事务中
stage 恢复，历史 raw／manifests 不改。此整理没有编译其内嵌测试或实现
跨 daemon witness／原子 recovery protocol，12／2／2 状态保持不变。

[5b 增强 Bazel 实际收据](BAZEL_LOCK_DIAGNOSTIC_OBSERVATION_20261002_5B71DF96.json)
核对官方 artifact 的 23 文件、六个 selected inputs、九个独立退出记录、
before／after head／tree／parent、前 clean 与后 non-lock drift，21 项
实际检查均通过；生成锁与已提交锁 byte-identical。该证据绑定 5b，
不赋予后续 head 或 Fleet Bazel target 编译信用。诊断 push scope 补充
Supervisor source 路径，使下一份修复候选取得自身精确执行收据。

本次继续修复复用单次 Agent-bound signed intent／release transaction 读取，
保持 main／Matrix／无 owner catalog 的独立纯诊断，并使 trusted denial
先于 idle hydration／budget normalization；每个精确 owner 的 constructor
containment 至多尝试一次。两个独立对抗审阅者在这一冻结范围未发现新
具体反例；归档事务、CI exact identity guards 和五份指南也经独立只读
复核。原两失败测试源码不改，新增三叶覆盖八种 signed 状态与 budget
窗口组合、三种 Matrix binding 错误、两种 ownerless catalog 损坏。
新源码共有 31 个 Supervisor／两个 Fleet 新增叶（相对 1f），88 个
common repair／五个 Fleet 强制 exact identities；这是静态库存，不是
新候选 PASS 收据。默认／qualification 的 scoped just fix、完整 just fmt
及两组 own-crate strict Clippy 均实际通过；格式器的 46 个原 clean
无关 Python 文件已从根目录精确恢复。遵循 AGENTS.md，没有在 fix／fmt
后本地重跑测试。新候选的六 native／两 deep 及增强锁诊断仍须独立执行。


## d1ed 组合复审：emergency Kill 的 RPC 准入与退出观察

`d1ed2a18120d8b8af7136ae9cd14208f0f9ad37a` 的完整源码为
`2a26991bdd15d81c5ec9cbd9bae483634ae59aa7`，发布 tree 为
`2b8fc2c0342afaae4e06472d2b6b5fc79881b290`。十份地图独立核对
273 个对象、115 个 operation blobs 和 139 个 Supervisor test paths；
没有把旧 CI 的执行信用转给这一候选。最新版源码与项目边界组合复审
发现共享 Stop/Kill preflight 仍把 serving 条件误当 emergency ownership：

- signed constructor denial 在首次 containment Kill 失败后保留精确
  main owner；后续 Fleet 转 Failed，runtime 的原 generation 未变。
  当前真实 Snapshot 的 Kill wire 合法、live fence 相等，但共享
  preflight 因 generation 漂移拒绝，尚未到达现有安全 containment。
- main 精确退出且清理完成后，Matrix 仍可能保留 live handle 或
  stored-exit cleanup owner。合法 fresh Kill 因 main 不存在被拒绝。

修复单独 Kill owned-handle admission：先完成 daemon 的完整 live
fence 比较，再要求已有 main 或 Matrix 句柄；准入后先推进
owner-local control revision 才 dispatch；该计数在内存，daemon epoch
隔离冷重启，不能误称其为 durable journal；不以 Serving/main presence/generation equality 代替 ownership。
Stop 保留原约束，无 owned handle 仍拒绝。已有 kill_slot 继续独立收集
主进程准备／存储错误并尝试精确 Matrix，不生成缺失 main 的虚假 journal，
不把 indeterminate 当成功、不通过 Kill 清除 signed quarantine。

进一步 observer-cut 对抗审阅确认另一个真实问题：主进程退出已经
保存、lease 或 lifecycle cleanup 尚未完成时，库 Kill 路径仍能重写
journal、CAS 至 Draining 或再次发信号。stored exact main exit 应像
既有 Matrix terminal guard 一样只保留清理重试；重复 Kill 不得再次
信号、改 phase 或伪造 KillRequested。独立 live Matrix 仍须 containment。
三条回归通过真实 Fleet、lease、public constructor 和 daemon
handle_mutation；前两使用 typed signed intent denial，第三同时覆盖
无 signed quarantine 的 ordinary cut 和 signed cut。进程行为明确
使用 double，不冒称真实 OS child。

文档同时明确：库接口保留 Stop/Kill containment，daemon signed
quarantine 下普通 mutation RPC 只开放 emergency Kill。此前 §7 的
Stop/Kill 同列说明有歧义，现已更正。12 implemented／2 partial／2 not
implemented、跨 daemon witness、完整 replacement lineage、原子 recovery
observation、per-Agent mutation/dirty Fleet I/O、target-host/独立验收及
生产激活状态不因这一准入修复提升。

该观察边界同时适用于普通控制：无 signed quarantine 的 Running owner
在退出／lease 清理失败后，Drain／Stop 也原可重新发信号或写 journal。
修复在 ordinary mutation、Stop preflight 与私有 signal entrypoint 的
任何新 effect 前拒绝 stored main exit；Kill 仍能处理 live Matrix。
Matrix stored exit 自身不封禁既有 deferred control cleanup；signed
recovery decision 所用 blocker-only 契约保留，避免无意扩大恢复协议。

三条新 RPC 测试及其 exact identity guards 已纳入源码库存，当前相对
1f 为 34 个新增 Supervisor／两个 Fleet 叶，91 个 common repair／
五个 Fleet mandatory。d1 的 31／2／88／5 是历史库存，它自己的实际
两 deep PASS 不改写，也不授予这三条新叶或更改源码任何执行信用。

新增 owner admission/observer 修复生产代码分阶段审阅，独立私有 helper
42 行；867 行新文件全部为 test fixture 与三个真实控制回归，未扩大
public crate API。源码／测试三个阶段实际改动为 89／470／400 行，
使用 immutable index prefix 分拆首个完整回归及其后两项，最终源码
字节与完整工作副本相同；没有通过少计 rename 或削弱断言规避行数。

最终 default scoped just fix（13.87 秒）、qualification/offline fix
（17.80 秒）、完整 just fmt、own-crate default strict Clippy
（36.58 秒）和 qualification strict Clippy（10.99 秒）均实际通过。
编译发现的新 fixture 括号错误已修正；锁 poison 在非 test helper／
trait 方法中传播为 ProcessDriverError，未用 lint suppression 放行。
完整 fmt 后从根目录恢复仅 46 个此前 clean 无关 Python 文件；
source-derived 91／5 identities 保留原 d1 88／5 的全部名字，仅增加
三条精确 RPC identity。原两项诊断失败测试整个文件字节未改。
遵守 AGENTS.md，fix／fmt 后未执行本地测试；最终候选还需要自己的
六 native／两 deep 收据，源码复核与 Clippy 均不能代替执行。


### d1 完整历史执行与继续修复的边界

历史候选为 `d1ed2a18120d8b8af7136ae9cd14208f0f9ad37a`，tree 为
`2b8fc2c0342afaae4e06472d2b6b5fc79881b290`，唯一父提交为完整源
`2a26991bdd15d81c5ec9cbd9bae483634ae59aa7`。PR 的固定 base 仍为
`e8f8f2d0ca399b0a68abba4da90a3be5114d0735`；没有据此声明当前 main 合并资格。

`REMOTE_CI_OBSERVATION_20261002_D1ED2A18.json` 实际记录六个 native lane
和两个 Linux deep lane 全部成功。六个 native 官方 ZIP、90 份 record 原始字节摘要
及日志原序与 official raw 已核对；每 lane 都有完整、干净的前后身份和九条
`retries=0` 测试命令，Supervisor/Fleet 库未过滤。

| 历史 native 平台 | default / production 实际执行并通过 | qualification-lib 实际执行并通过 | Fleet 实际执行并通过 |
| --- | --- | --- | --- |
| Linux，三 lane | 417 / 417 | 422 | 44 |
| macOS，三 lane | 416 / 416 | 421 | 44 |

每个 native 的三个 Supervisor 库组均观察并通过全部 88 个强制身份；Fleet 的五个
强制身份也全部通过，库组没有跳过。两个 deep lane 的六组实际计数分别为
417、422、4、5、1、1，全部执行的用例通过；两个库组的 88 个强制身份完整通过。
native 的具名 product/SIGKILL helper 保留原跳过记录；deep 的 SIGKILL
日志仅有 helper skip count=1，不能冒称另有具名 SKIP 行。它们不计为库用例执行。
deep 的范围较窄，不补充它没有运行的独立 Fleet/product 组。

上述成功只证明 d1 的既定测试计划。随后对真实 daemon mutation admission 的源码
对抗审阅发现 emergency Kill 与 Stop 共用 serving-generation preflight，使已拥有的
fenced main 或 Matrix-only 句柄可能无法经 RPC 重试终止；stored main exit 的普通
控制也需要在效果前拒绝。下一轮修复及三条新 RPC 回归源均没有在 d1 执行：

- `emergency_kill_rpc_reaches_fenced_main_after_signed_constructor_generation_drift`
- `emergency_kill_rpc_reaches_matrix_only_owner_and_preserves_terminal_cleanup`
- `emergency_kill_rpc_preserves_observed_main_exit_without_resignal_or_new_journal`

新源码的强制身份为原 88 个完整保留加这三个实际叶子，共 91 个，Fleet 仍为五个。
三个新叶子的存在、编译或旧测试成功均不授予新的 runtime PASS；最终候选须获得
自己的 exact-head/platform 执行记录。第三个叶子还明确覆盖 plain/signed stored-exit
下 Stop/Drain daemon 和 library 拒绝的无效果边界；这不扩展成其它 Stop deadline
或 Drain acknowledgement 场景的覆盖声明。

增强 Bazel 历史记录 `BAZEL_LOCK_DIAGNOSTIC_OBSERVATION_20261002_D1ED2A18.json`
实际捕获九个成功 exit、六个选定输入、21 个检查及 23 份 artifact 文件摘要。
before/after 身份、parent、tracked clean/non-lock drift 检查均通过，生成候选与已提交
`MODULE.bazel.lock` 字节完全相同：1,657,200 B，SHA-256
`c03b95ff14a8c813ea4cbb27498437293057540d2374b7f9b6903c1a0a4749d4`。
这不是完整 Cargo 输入闭包或 Fleet Bazel target 编译证明，也不转移到后来源码。

d1 的全仓观察在有界窗口关闭时仍为 FAILURE_AND_PENDING：最终 extra API 保存
上界为 **2026-10-02 02:17:43.504934Z**，窗口于 02:18:04.999Z 关闭。
114 个 checks 当时为 43 success、36 failure、13 skipped、22 in_progress。
该快照不是这些剩余 job 的未来终态；pending/skipped 没有执行通过信用。

全仓实际失败保留分类：docs 的 803 个测试全部通过，但七个原历史 map 的
`merge-base --is-ancestor` 返回 1，base/head 对应 map blob 相同；它们是历史
nonancestor，不是缺失对象。Lane B 的 runtime.agentd delegated-owner 故障也有
base/head 相同 blob 证据。没有观察到新增 Cargo.lock map drift。
Cargo-deny job 已终态失败，但 raw 获取返回 `Transport closed`，根因仍为 **UNKNOWN**；
不能改写为 pending，也不能推断继承自 base。其它外国模块的失败只能按其已有
直接证据归因；macOS Bazel 的 hepta-intuition clone lint 的 base inheritance 同为
UNKNOWN，Fleet target 没有完成信用。

Cargo-shear 在 d1 已不再发现本模块的三份未接线原型，但仍指出本模块
`[lib] doctest=true` 的空目标。源码静态检查覆盖 147 个 `.rs`、563 行 Rustdoc：
没有 fenced/indented 代码示例、doc attribute/include 文档、block Rustdoc 或 build.rs。
本轮只将 lib.doctest 改为 false，features、依赖及整个 manifest 其它字段保持相等；
已有 Supervisor crate tree 来源对象覆盖此 manifest，显式对象库存不因此扩大。
这是移除空包装目标，没有删除已有可执行测试或修改 gate。
Cargo-shear 的另外六个 unused 项已有 app-server/codex-adapter 同 base/head manifest
及零 changed-package-files 的静态归属证据；仍保留整个原 gate 的失败，新的 flag
不能被当成该 gate 已通过。

模块能力状态继续为 12 implemented / 2 partial / 2 not implemented；独立 acceptance、
deployment、activation 和 release 没有因此获得资格。源文档及历史记录完整保存原
作用；新完整源冻结与最终候选身份由后续映射及独立执行呈现。

冻结的 d1 CI 文件为 22,080 B／143 行，SHA-256
`ed637fcf5a367c214e4808a528234ef1dc59b80f6d4d82e7cdfee14331268bbf`。
独审纠正了四个 HOL 字段从 stage Summary 到具名 PASS 的小数秒差异；
它们分别为 428.187、366.693、311.990、410.421 秒，成功、预算及身份不变。
旧候选摘要另存，最终 receipt 不再修改。全仓快照为 22,959 B，SHA-256
`31ab59afdcede4a7377a21d3ab4758c7e987d137ca1dfa55ecfd40915877209a`。

仅 manifest 的再次检查实际通过：default/qualification scoped fix 分别
43.16／18.45 秒；完整 fmt；default/qualification strict all-target Clippy
分别 37.39／11.48 秒。46 个此前 clean 的无关 Python 格式改动精确恢复。
manifest parsed fields 全等（仅 lib.doctest 不同），源码 guard 91／5 未改变；
检查 receipt SHA-256 为
`721b2000bf0ab062a6ef6433b6ba9201ca4e3aa974291a89e1f05949f4d483ea`。
fix/fmt 后没有本地测试，仍不代替新 head 的原生或深度执行。

## 22beb 组合复审：Matrix 重试与启动的 Fleet 准入

后续发布观察为 `22bebc8ed8ea87d9f79d99c0ea1aae4f39e1832e`，tree
`348340f7fbcbaeb11796974dd712f4ec7f54a3a0`，唯一父提交、完整源为
`97240ae33ca7385bfd7eeaa3c70a9946e0bb89b1`。该提交的 91／5 是自己的
历史测试计划；其 actual CI 结果与本节之后的修复源码分别记录，不相互转移。

独立 source-only 对抗复审确认两个效果边界仍使用缓存 Matrix descriptor：
合法 Fleet revoke 后，健康 main 保留，但 companion 退出后仍可能新增一次
持久化 retry charge，并在到期时再次启动已经撤销的 Matrix 命令。
`load_binding` 只验证公共 Matrix binding，不能代替 Fleet allowance/revocation。
31 个不可变源码对象的反例证明 SHA-256 为
`a5c8f7445f942f2708107413c4e26faf9eab5cb906d353b40dc728ed9544e131`；
这是代码审查证明，没有把 fixture 当作已执行测试。

补修复用现有 `refresh_release_for_transition`，在新增 Matrix retry charge 前
和实际 companion spawn 前各自重新准入。Catalog provenance 继续防止删除条目
后降级为资格用 plant；最终启动使用新解析的 canonical Matrix command。
拒绝仅写入 bounded Matrix degraded 诊断，保留 main／其他 Agent、精确 lease
清理、旧 budget/window/retry deadline 和所有已取得的 process owner。

只在策略拒绝后再次直接启动仍会漏记新失败，因此新增私有、owner-local 的
uncharged retry marker，绑定 exact main spawn generation 与 active ReleaseId。
合法恢复 allowance 后先收费一次并等待完整 backoff；原本已收费的 retry 恢复
其原 claim，不能再收费。新 main incarnation 丢弃旧 transient marker，初次
companion setup 不收费。Fleet 的 append-only revoke 不通过删除 marker 或
重新 allow 来伪造撤销恢复。该标记没有新增 durable witness、协议或权限。

相邻独审又确认 main poll 后合法 Fleet CAS Running→Draining 的观察切点：
旧 cached healthy main 不再足以准入 Matrix。两道 gate 对 cached Running main
消费新 Fleet record，要求 current Running、exact generation、active bundle
和 unfenced owner。拒绝不执行 Kill/CAS，不扩展 nonRunning／ownerless constructor
旧预算语义；现有 tick containment 继续负责旧 owner。检查没有承诺消除读取之后
并发 CAS 的 TOCTOU，也没有实现跨 daemon 原子 spawn 协议。

三个真实新叶在真实 Fleet／lease 和明确标注的 process double 中覆盖：
初次 setup、已有健康 attempt、合法 allowance 恢复的一次收费／backoff、旧已收费
claim 零重收费、新 main generation、撤销／删除／损坏 catalog、晚到 canonical
catalog 命令，以及上述两个 Running→Draining continuation cut。当前相对 1f
为 37 个新增 Supervisor／两个 Fleet 叶；mandatory 完整保留原 91 个并仅追加
这三个实际身份，成为 94／5。原 `supervisor_tests.rs` 只增加三行 child wiring，
剔除这三行后全部旧测试字节与 22beb 相同，原 constructor diagnostic 文件不改。
这些是 source inventory，仍须新最终 head 的独立执行证明。

详细开发文档继续包含职责、接口、所有权、失败恢复、权限、构建和资格门槛。
Fleet 是 release catalog 与 lifecycle CAS 的事实来源，Supervisor 消费其准入
并执行 generation-fenced 生命周期；Agentd 与 Kernel 的 RPC／任务／权限事实
不能由 companion 健康或进程退出代替。当前 12／2／2 能力和独立验收、目标主机、
activation/release 状态保持原值；cross-daemon exit cleanup witness、atomic
recovery observation、完整 replacement lineage 和 per-Agent selective projection
继续是具体未完成项，不能用这次局部反例闭合声称全部完成。

本轮实际 default／qualification scoped fix 通过（1m06s／37.85s），完整 fmt
通过，default／qualification strict all-target Clippy 通过（41.48／12.46s）。
46 个此前 clean 的无关 Python 文件在 repo root 精确恢复，Rust 最终源保留。
私有 admission 模块为 148 行，Matrix 编排从 781 行缩至 769 行；新测试文件
545 行，按完整 fixtures／第一叶与余下两叶分阶段审查，不改变最终编译源码。
fix/fmt 后没有执行本地测试；这些检查不能代替新发布 head 的实际测试或资格收据。

22beb 自身的六个 native 和两个 deep lane 已全部实际 SUCCESS。Linux 三 lane
Supervisor default／production 为 420 PASS、qualification 为 425 PASS；macOS
三 lane 为 419／419／424 PASS，Fleet 六 lane 均 44 PASS。91 个 Supervisor
mandatory 在三库逐名通过，Fleet 五个逐名通过；每 native lane 的 15 records、
其原 log、官方完整 raw、ZIP 和 assembly 均核实，90 records 完整保存。
每份 assembly 的 7,643 个源码绑定与该 head 精确一致；六条 HOL 秒数均引用
具名 PASS 而非 Summary。两 deep lane 为 420／425 PASS，91 个 mandatory
在两库通过，原 crash/SIGKILL/authority/writer/HOL 范围保留。全部 retry0。
这一历史实际成功不覆盖本节三处后来确认的 Matrix 切点，也不转给新修复 head。

同 head 增强 lock 观察的 21 项检查、9 个 exit 和 23 个 ZIP members 均核实；
6 个 selected inputs 与 fresh API 字节相符，lock 候选与 committed 完整字节相同。
该诊断不是 Bazel Fleet 编译证明。全仓 30 分钟窗口于 03:13:57.454Z 关闭，
114 checks 为 42 success／35 failure／13 skipped／24 in progress，未宣称全仓绿。
803 项 docs 测试通过，但 gate 仍拒绝七个历史非祖先 sourceBase；Lane B 仍有
旧 delegated-owner closure，Cargo-shear 的六个 foreign-unused gate 仍失败，
其外部包与固定 base 整包 tree 相同；cargo-deny 终态失败根因仍 UNKNOWN。
Supervisor 空 doctest 和三个 orphan 警告已在完整 raw 中消失。311 份窗口材料的
bytes／SHA 独立复核通过，窗口不延长，也不把 pending／skipped 计为执行。

## e00b CI 复审：子进程退出观测的既有测试竞态

Matrix 修复最终发布为 `e00b7d2b6acccf6a35683a595cf88e1f23673642`，tree
`79a1810d36bc6217595c0f31129eb9812c729d1a`，唯一父、完整源为
`75886ae97f2deb6c1da6b921f80ffaa0696d9ea3`。该 head 的 docs source job
110694024239 实际运行 803 tests，802 成功、一个 ERROR，不能记录为 803 PASS。
Traceback 在 `test_exited_parent_cannot_leave_a_running_pipe_holder` 第 73 行：
读取 `/proc/<pid>/stat` 时子进程被回收，得到 ProcessLookupError（errno 3）。
前面的真实 timed_out／parent returncode=0 断言已经通过；这不是 Supervisor
或 Fleet Rust 测试叶失败。测试和 executor 文件在该 head、完整源及固定 base
e8 的 Git blob 完全相同，静态归为既有观测竞态；没有声称 base 实际同样失败。

原测试只捕获 FileNotFoundError；补修同时捕获明确表示进程不存在的
ProcessLookupError。仍存活的后代继续受原 100 轮观测、SIGKILL 和失败断言约束，
权限／其他 I/O 错误仍会报错。原超时、正常父退出、日志字节和 digest 检查保留。
此修改没有改变 executor、Supervisor Rust 或生产进程控制语义。原 ERROR 结果
保留；新的成功只能来自修正后 head 的实际执行，本地不运行测试。
现有只读 enhanced-lock push 入口同时加入这个真实 fixture 路径；其 branch、
permissions 和其余 dispatch-only jobs 保持原值，补修后的 head 自动取得独立观察。

## e00b 实际核心收据与有界全仓窗口闭合

该 head 的六个 native 和两个 deep lane 已全部实际 SUCCESS，attempt1、零重试。
Linux 三 lane 为 Supervisor default／production／qualification 423／423／428 PASS；
macOS 三 lane 为 422／422／427 PASS，Fleet 六 lane 均 44 PASS。94 个 common
在各 native 三库逐名一次 PASS，Fleet 五个逐名一次 PASS，三个新 Matrix admission
叶实际执行；每 lane 的 15 stage／原 logs、官方完整 raw／32 个 ZIP members、assembly
完整核实，共 90 records。每份 assembly 的 7,645 个源码绑定与 e00 精确 tree 相符。
两个 deep lane 实际为 423／428 与其余 4／5／1／1 PASS，SIGKILL helper 一项 ignored。
其第四组五个用例实际覆盖 restart_budget、restart_budget_recovery 与
robrix_control_projection。此前概述中的 writer 字样不作为 deep writer 执行信用；
原 22 compact 的真实 argv 与计数保持原值。native 的 writer handoff 产品另有实际记录。
本轮原两失败叶、emergency Kill 三叶和新 Matrix 三叶均按具名原日志核实。

这些 e00 成功覆盖 Matrix 补修，但不覆盖之后的 procfs fixture 补修。source docs
仍是 803＝802 ok＋1 ERROR／whole job FAIL，独立 ERROR receipt 保留原完整 traceback、
head／source／base blob、raw bytes／SHA；base 同 blob 只是静态继承，没有失败执行信用。
fixture 修正后的成功必须由新 head 自身取得，不转移历史结果，不运行本地测试。

全仓窗口 03:37:07.257Z 至 04:07:07.257Z 已关闭，25 runs／114 checks 实际为
42 success／38 failure／13 skipped／21 in progress。279 份材料 bytes／SHA 独立匹配，
pending／skipped 不作成功，初次跨 worker 24 秒采样例外如实保留。旧历史 ancestry、
delegated-owner 和 foreign unused 等 gate 仍失败，literal 三项未闭合；Fleet Bazel
只获得 compile STARTED，尚无 target completion／test 信用。核心后来完成的实际结果
单独记录，不回写已关闭窗口的 pending。生产资格、目标主机、验收、activation／release
和 current-main merge qualification 仍未建立；能力 12／2／2 与四个具体开放项不变。


### Fleet 依赖的参数注释检查继续闭合

ca7 的 Windows argument-comment 检查真实发现两个 Fleet-owned 错误：
`module_catalog.rs` 的 `canonical_ids` 调用缺少布尔参数 `dependencies`
的命名注释。完整原始日志 job `110705886186` 保留失败；head ca7、
完整源 52 和固定 base e8 的该文件同为 blob `78c61c6197ee9eaa2f46972b4137466c9896537e`。
这只证明原源码静态继承，不能推断 base 曾执行同样失败。Supervisor 无该检查错误。

补修仅给原有 `true`／`false` 添加正确的 `/*dependencies*/` 注释，保留私有
函数、全部实参、行为和错误分类。现有只读 enhanced-lock push 入口增加这个
真实源文件路径；分支、权限、命令、dispatch-only 作业和诊断范围均不扩大。
本轮不为固定值增加镜像测试，不改参数类型或模块权属。源码／格式／token
等价复核不能代替新候选自己的 native、deep、803 和锁诊断执行。

ca7 的 Mac Bazel release job `110705776189` 另保留内部 NPE／退出 37；
诱因、模块归属和 base 同失败继承仍未知，没有 Fleet 编译或测试完成证明。
不会通过注释修复或锁诊断把该门禁提升为通过，12／2／2 及四个功能缺口保持。
