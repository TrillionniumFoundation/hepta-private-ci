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
