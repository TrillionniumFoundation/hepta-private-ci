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

补修完整源码与验证输入为 `74eda6dbe9a63c043c60e7c468fa353b64bb3854`，tree `2d2015f0c02ab6a2362ae5860a67ec0d34331ad7`。
当前 source map 绑定该观察；首次修复源码、本地具名执行和 7c CI 的身份均保留。
