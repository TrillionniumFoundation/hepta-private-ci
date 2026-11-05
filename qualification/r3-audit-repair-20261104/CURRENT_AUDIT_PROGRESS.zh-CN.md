# Hepta 全量审计、发展方向与阻塞项闭合进度

## 结论与范围

项目已有大量源码、真实原生控制与平台执行证据，但尚未达到全阻塞项闭合、完整产品入口或 main 合入资格。本轮以 [PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797) 为唯一整合候选，持续实际修复和验收。原23项阻塞项为 **8项范围内闭合、14项开放、1项科学HOLD**；第四批局部通过没有换算为整项完成。[当前机器账本](current-blockers.json)

近期发展方向依次是：**可重复验证的整合候选 → 普通启动可用的可信任务闭环 → 同信息、等总成本的共享计算与学习验证 → 独立外部接受**。源码存在、局部通过、科学采用和生产发布需要各自的退出证据。

本报告完整库存覆盖2026-11-05 03:16–03:24 UTC；旧2026-11-04 22:27:38 UTC快照保留，各增量和原生执行另有source tree与时间。发布前分支观察为cabcb40d36e116beaa65750e1f674c52035da785；本批22个源提交最终收敛到代码树4a3374e22e16ce5c764288ad018cd9affadf94ea。旧f825原25审批控制、owning7和完整workspace的原结果保持。后续Skills、Migration、V8各自在固定源取得原9、166、76例PASS；App父存活控制和Windows/Python源码继续整合到fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff。fb9现已实际执行未过滤的原完整工作区命令：19,506项中19,490 JUnit PASS、16 FAIL，另有57项原ignored和25项已绑定早退，零重试。14项与旧失败逐名重合，新增恢复线程不存在和代理响应超时两项，原因待查。完整新42件原件已独立重建，最终原fix/fmt及两项差异检查均已实际exit0，自动改动和完整54路径源映射已独立核准；原16FAIL仍保留，候选未全绿。[本轮非通过逐项根审](fourth-full-fb9-nonpass-root-review.json) / [新42件完整原件根审](fourth-full-fb9-complete-root-review.json)

全局架构权威仍为 [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md)。本目录记录特定候选资格；[前一版完整报告](THIRD_AUDIT_PROGRESS.zh-CN.md)、旧失败和原退出条件都保留。

## 1. 全量盘点与实际开发阶段

最新完整分页快照覆盖 **1,103个open PR、5,193个分支、0个open非PR issue、0个release**。其中1,079个Draft、24个非Draft；155个直接以main为base、948个为其他base；最长依赖链211层。PR13页到终态空页，branch53页到首个空页并另核两个空页guard；issues13页全部为PR，未以open_issues_count替代计数。没有重复、依赖环或head/branch不一致；185个metadata base SHA不同于当前分支tip，不自动证明冲突。首/尾/空页及latest100终锚一致，但多次API读取不是原子快照。相比旧1088 PR/5163分支，新增15个Draft（#4809–#4823）和30个分支；仅旧#4729的head改变。[新完整库存](fourth-repository-inventory-20261105.json) / [逐字归档](repository-inventory-20261105/archive-manifest.json) / [旧1088历史快照](fourth-complete-inventory.json)

规范登记为40模块、205契约、58协议、67持久数据域、91工作包。工作包状态为43 planned、25 source_implemented、20 source_implemented_execution_pending、2 source_implemented_semantic_review_pending、1 blocked_external。源码映射为46根、1,408源文件、938 Rust文件、474名称含测试特征的文件。这些分别是登记与源码规模，不是测试执行数或产品完成百分比。[阶段计划与规范映射](PROJECT_DIRECTION_AND_PLAN.zh-CN.md)

40份implementation map的production_implementation均为false；38份已有native-mapping，platform.types和runtime.codex是例外。apps/hepta-native当时23文件、0 Rust，实际Rust UI位于apps/hepta-control-ui/rust；browser.servo为33 JS/1 Rust、control.engineering为77 Python。命名和目录存在不能代替实现与接受。[原源码审计](THIRD_AUDIT_PROGRESS.zh-CN.md)

## 2. 分支整合方向

#4797保持Draft，base为integration/ui-objective-20261103-product。已核main为732e934ba496d90fbe042b8d41d479ef901643e5、base为63652be658ebed8d3052eb789b951793384fd5e4。r3与#4776在2,110路径并集中有2,089差异：2,023 donor-only、39 r3-only、21相同、27双方不同；最后27项并非27个已证实的merge conflict。[原逐路径决定](THIRD_AUDIT_PROGRESS.zh-CN.md)

保留cwd展示、V8初始化互斥、首个ArrayBuffer生命周期、ZIP mode掩码、SQLite drive/UNC、Fleet rename-before-seal、Guardian截止后取消和runtime Git缓存。Rust/Bazel/Matrix/SQLite/AWS/keyring/YAML升级按共同验证的依赖批次处理，保持源码、manifest、vendor与锁一致。

| 新活动 | 实际观察 | 整合决定 |
|---|---|---|
| #4806 / fbf7868 | blocking37 jobs为22成功/11失败/4跳过；closed-caller proof发现deployment_calculator.rs额外调用authority_lease_put | 核对真实caller合同，不能只补白名单 |
| #4808 / 2496308 | 相对当前#4806 diverged，ahead1/behind5；不是线性包含关系 | 不借base分支名称继承后续修复 |
| #4808 private-state | 6脚本selftest通过，随后production source与冻结控制不符；攻击控制未执行 | 不建立攻击资格 |
| #4808 native UI | 链接缺-lpulse，原native cases未运行 | 先修实际构建输入 |
| #4808 Windows | 7真实scope共91 selected、47非通过；两个fake owner-package selftest行已排除 | 逐真实范围处理，不报93产品用例或整体通过 |

#4808 legacy-delete的新形状是允许目录内文件仍存在、外部文件也存在，不能沿用旧“外部被删”的具体原因。[完整原日志与DAG](fourth-pr-current-delta.json) / [独立根审](fourth-pr-delta-root-review.json)

本次新增donor独立核对了固定源、完整changed-files分页和当前CI。#4810（c2243df）为20路径，当前9个工作流中3成功/4失败/2跳过；#4812（3a8e50）为43路径、当前Actions为0，原native收据绑定更早1993db，交付代码仍HOLD；#4817（379c21）为33个Python/文档/收据及工作流路径，实际386f7a专用job的53个ok/0skip已逐名核对，当前头另有blocking失败。三者均未纳入本候选，不能替代B11原Windows门或B16实际custody/Current/正常caller。后继#4821的277例仅为另一固定源的作者报告，尚未独核原日志。[三donor主源与资格表](FOURTH_DONOR_PROGRESS_20261105.zh-CN.md) / [原23项增量索引](fourth-blocker-external-progress-20261105.json)

## 3. 第四批实际完成的修复

下表结果绑定各自源码，不能相加为一次全仓通过；相互重叠的控制不计作新增独立能力。

| 范围 | 原始问题与实际结果 | 未完成的边界 |
|---|---|---|
| arg0 preflight | 提前到Tokio/dotenv/PATH前，保留helper dispatch；原10控制和54 Python均PASS | 不等于正常Root/UI接受 |
| authority clock | 原3FAIL保留；owner mutex后读时间，原18PASS | 最终同源平台 |
| inherited Unix listener | 原real-exec FD泄漏FAIL；修后15PASS，真实FD在exec后消失 | 保留AF_UNIX/listening/path/uid/0600/nlink/CLOEXEC及Tokio约束；不是整个Root custody |
| Fleet no-ACK | 原ENOTCONN失败；仅NotConnected归入原有无ACK路径，5 unit+2 Fleet PASS | Darwin os57及原ARM验收仍待 |
| Core response/WS/subagent | 5d8选中6PASS（含新增真实重连控制）：并发消费与真实EOF、配置先于启动、身份重连、真实提示匹配 | 有意修正prewarm/request oracle；保留turn-state、turn-id、工具结果、原预算与生产身份隔离；最终CI |
| PTY/forward/Supervisor | 1c2原31PASS：PTY29、原13MiB/30秒转发、真实监督；另Doctor3PASS | Intel与Windows原门仍开放 |
| ApplyPatch错误语义 | 原I/O错误缺underlying cause；保留cause后原同例PASS | 保留真实文件系统/Error断言，不替代strict token |
| Cargo/Bazel锁 | 原just update/check完成，两个锁均由真实流程生成并逐字绑定 | 最终源码仍需完整门禁 |
| musl/lifecycle CI | 两个平台映射改为真实musl链，保留ELF/smoke；Windows8 shard去重复--nocapture | 当前仅2 YAML、7内嵌Python解析；原hosted待运行 |
| 成功目标日志保留 | 10个明确原目标，只收当前无歧义PASSED/FLAKY的原日志/XML；原Python discover57PASS/0skip | 新CI需实际产逐case正文；不推Bazel/Windows产品通过 |

完整源树、原日志、负控、实际程序身份和根审收据见 [第四批技术资格](FOURTH_BATCH_QUALIFICATION.md) 与 [证据索引](fourth-evidence-index.json)。

### 所属七包原验收揭示的新问题

e84c2f12e39022701c8a942343b3913faa62cf31上，原owning-seven选择5,416测试、另19原ignore。实际 **5,404 JUnit PASS / 12 FAIL，just100、controller1，retry0**。其中24个JUnit PASS是原requires-remote早退，不能描述为该行为执行通过。69个选中测试程序与12 helper前后身份稳定。完整JUnit、catalog、selection和review已按原字节分片重建。[完整原件](fourth-owning7-complete-index.json) / [根审](fourth-owning7-root-review.json)

12FAIL中的8项含真实主机启动噪声“Failed to create stream fd: Operation not permitted”。已读/etc/profile、im-config调用链及对应systemd源码，三次logger调用与输出相符；没有syscall trace来确定socket/connect/shutdown/write哪步返回EPERM。未修改主机profile、sandbox、环境或过滤输出消除失败。[归因与限制](fourth-host-startup-root-review.json)

另四项沿原断言继续修复：

- Hook第二次又输出上下文，超出原两条SSE并产生第三个请求。夹具仅首次真实完成后停止重复输出；原请求数、warning/context、150ms/5s保持。
- Skill的None分支已消费TurnComplete，测试又等待同一事件。去掉重复等待；原权限/输出断言和另一分支保持。
- literal-deny将真实字面路径错建为GlobPattern。改为PathUri后进入真实执行，又暴露父批准后的子进程重复审批；随后最小生产修复在f825的原25控制中通过，后续完整工作区仍有18项失败，最终平台资格仍待。
- readonly snapshot原夹具在只读沙箱写counter，且两请求不是同一cache key。修正后仍提前读.bashrc，继而定位并修复Bash恢复路径。

### snapshot：有效反例和原矩阵已有实际结果

恢复argv仅增加--norc，保留原-pc、set +o privileged、环境过滤与sandbox。原捕获/fallback的-lc及非Bash行为未改。实际诊断证明.bashrc函数先于snapshot恢复执行；GNU启动规则支持该修复方向。getpeername/EPERM的精确因果仍是条件推断，没有冒称已trace。[主源与限制](FOURTH_BASH_STARTUP_SOURCE.zh-CN.md)

c270有效负控先通过第一个原完整tuple，再实际覆盖profile，只改变第二次scope，原第二tuple在267行FAIL且profile_helper缺失。实际exit0，不预设42。其后controller变量遮蔽TypeError发生在restore首guard、写源之前；续跑完整重验同一树/原件/程序身份，只恢复正向夹具，没有重跑有效负控。[原负控](fourth-bash-no-rc-valid-negative.json)

da60原13例 **12PASS/1FAIL，0retry、0选中skip、0早退**：8 snapshot Linux分支、2 Hook、2 Skill通过。literal-deny在原893行仍收到意外/usr/bin/cat审批，denial/no-secret终点尚未到达。该旧失败完整保留，未重复baseline。随后最小修复让父批准后子评估使用实际生效权限；显式拒绝、危险命令与原sandbox继续保留。[完整13例](fourth-four-fixtures-13-native.json) / [根审](fourth-bash-no-rc-native-root-review.json)

### 父批准后的子评估：原25控制已真实通过

f8251e1d14fa8524ab469281296cd4cf708f173c仅改生产unix_escalation.rs的7增1删。通过现有denied-read权限保留函数，让子审批fallback与实际生效sandbox一致；原父级拒绝、显式Prompt/Forbidden、Guardian、granular和执行sandbox不变，未改原25测试源码。

原5 integration＋20 unit **25PASS、0FAIL、0retry、0选中skip、0早退**；原denied-read用例0.452秒通过，真实原拒绝/非零/无secret/不重复审批断言到达。另19原ignore与5,391未选择例单列。5个normal helper构建成功且均为fresh=true缓存命中；73个catalog binary中实际选中2个，2测试程序及12 helper前后身份一致。完整22嵌入文件、784,623字节helper stdout、原日志逐名PASS与新JUnit均经独立核验。[完整原件](fourth-literal-approval-original25-native.json) / [根审](fourth-literal-approval-native-root-review.json)

同一f825的原owning7终态为 **5,416 selected＝5,408 JUnit PASS＋8FAIL**，另19原ignore、0unmatched，原just100/54.872秒，controller1。8项精确同于旧的5 Core＋3 snapshot fallback主机输出失败，每例仍有原三行stream-fd EPERM；四个已修复用例不再在失败集合中。原完整review的skip消息包含24个requires-remote，JUnit成功正文缺失时不能把派生空表当成零早退，完整raw已逐case关联全部24项，并与新JUnit、目录、选择集和review逐名核验。[八项原失败](fourth-f825-owning8-failures.json) / [逐名根审](fourth-f825-owning8-root-review.json)

完整workspace已在同一f825上实际终态：**19,503 selected＝19,485 JUnit PASS＋17FAIL＋1TIMEOUT**，另56原ignore、0unmatched、0retry；原just exit100/228.919秒。193个workspace成员中173个有选中用例，20个无用例；321个实际选中测试程序与33 helper前后身份稳定。其前置同源6 helper（原5个加codex-exec）实际构建成功，6个均为fresh=false，未沿用上一feature组合的旧程序hash。

18项非通过（17FAIL、1TIMEOUT）包含旧8项、额外6个App command/exec输出用例，以及连接断开未回收进程、外部迁移60.004秒超时、无project marker时skills多读父目录、V8 sandbox声明与链接状态不等4项。13个失败正文直接包含三行stream-fd EPERM；输出上限用例实际stderr为Faile，其具体前缀因果仍单列待核。24个requires-remote早退已从原raw按字节块逐名绑定到JUnit；原解析器对其已知prefix没有未绑定通知。后续从完整34,360,967字节原raw额外确认1项retained-capability早退（0.116秒JUnit PASS），因此已知25项省略行为，不能把旧24项表当全部早退。原JUnit、退出码及原件均不变。[18项完整正文与24项早退](fourth-full-f825-failures-and-early-returns.json)

完整raw为34,360,967字节，SHA256为75cd2cd5c89ce70781781c3b8c3e1bb168720b83bf6961c206720b3c08efe15c。完整workspace与所属包的18件原始日志、catalog、selection、metadata、review及新JUnit共74,867,442字节，已通过33个Git压缩分片保存；独立解码后逐件重新打开验证长度/hash，并逐名核对原日志、JUnit和选择集。所属包24个早退也全部精确绑定。一个冗余cloud副本曾短写，原件和压缩分片不受影响；该差异与重新解码的结果均保留，不把短副本充当完整证据。[完整原件与解码器](fourth-f825-full-owning-compressed-index.json) / [完整独立根审](fourth-f825-full-owning-complete-root-review.json) / [副本差异记录](fourth-f825-export-companion-copy-addendum.json)

三项新增修复已完成各自原范围验收。Skills正负夹具都改用Table.insert设置非空project marker，实际负控在原446行完整roots断言得到outer＋cwd两项，恢复后原9例PASS；此前425行的index panic仍记为无效准备失败。Migration负控实际到达子进程原588行，得到[]而非["claude-plugins-official"]；精确恢复后原166例PASS，正例原日志1613–1627行同时保留父、子两层同名测试成功。V8仅将既有sandbox feature加入默认，原6例及runtime68＋jit1＋parallel_initialization1共76例PASS，包含两个原integration。三组范围均为零重试，原输出、JUnit、冻结名单和程序身份已核；各自精确源树见[三修复完整根审](fourth-three-repairs-v3-root-review.json)。

最终7d703源上实际执行原just bazel-lock-update和check，分别exit0/111.734秒与exit0/0.493秒，真实生成流程没有锁差异；原Cargo.lock与MODULE.bazel.lock的字节身份保持。现有缓存如实保留，未称fresh-cache资格。这些局部结果没有重写f825的完整工作区失败，也没有关闭新的原阻塞项。

App首次断连诊断在helper前置检查停止，未启动metadata、catalog或测试。只读复查发现原target/dev-small及33个helper不存在，原因未定；初始f825/index/锁/测试源码检查通过，异常后的最终guard未执行。其后独立只读检查重新确认f825、普通index、双锁及无未审untracked路径，随后在全新目录完成epoch2冷构建（job 1a1a967b3ab-fc05-34f6）。本次绑定自己的程序身份、原193成员依赖图和33 helper名单，原5秒断言及零重试不变；原1例终态为FAIL，耗时5.491秒。该次观测为外层bwrap已消失、内层 sandbox helper与Python仍存活，未确定信号原因。首次前置停止与原完整运行失败继续分别保留。[首次停止](fourth-app-disconnect-preflight-stopped.json) / [epoch2原终态](fourth-app-epoch2-terminal-diagnostic.json) / [独立根审](fourth-app-epoch2-root-terminal-review.json) / [系统 bwrap 身份](fourth-app-bwrap-exact-readonly.json)

随后仅增加观测的临时树1e936b1ca6df807d8928a4cc6c527f40f92808aa再次运行同一原App例，终态为FAIL/5.575秒，原5秒预算不变。inner_entry与inner_after_restrictions的PR_GET_PDEATHSIG均实际返回rc0、signal0，原killpg返回Ok(())；这没有定位信号在哪一步被清除。50件完整原件已独立核验，诊断结束后精确恢复f825源码及原source map。新的父存活候选首个native反事实已执行，但在5.005秒以INVALID_FIXTURE_BEFORE_CAUSAL_STAGE停止：nested libtest banner与首marker同一行，未到kill/reparent/arm，不能认作有效因果负控。finally精确恢复d8a5e94af06b9555fc8256af1337e9f28f7c7fa8；仅增加一行println!的夹具修正后，后续V2以同一原5秒预算继续执行；该最初无效负控及其47件完整原件继续单列保留。[完整50件根审及恢复](fourth-app-parent-probe-complete-root-review.json) / [首反事实无效与精确恢复](fourth-app-parent-liveness-invalid-negative-root-review.json)

V2实际job 1a1a9cf9300-fc05-3823在c6fbcfa0d1ba3b1556f601dc4ca3a7734328b9f7完成三项有效因果反例：去掉退出拒绝时，实际重归属子进程在259行错误接受原父已退出的Ok(())；去掉重新武装时，原111行断言观察到reaper存活；泄漏FD时，原269行在用户fork前观察到(1,Some(0))而非EBADF。三次分别0.018、5.022、0.010秒实际失败，均在finally精确恢复c6；父级传播错误没有当独立因果oracle。[三项原件与根审](fourth-app-parent-liveness-three-negatives-root-review.json)

恢复后的八项选择是**5项原例＋3项新控制**。原just exit0/4.059秒、JUnit 8 PASS；原App断连0.606秒、3项原namespace reaper和3项新父存活控制实际通过。原retained-capability例明确输出“skipping capability test: unprivileged user namespaces are unavailable”而早退，因此只有7项行为实际执行；严格wrapper的selection_valid=false/controller1原样保留。程序、33 helper、完整依赖图与源树身份稳定，补充只读观测169事件无错误且末次已拥有进程表为空；该观测不替代原测试断言。此结果支持继续独立工程WIP，原权限行为门仍开放。[最终八项实际范围](fourth-app-parent-liveness-final-eight-root-review.json)

Windows窄ACL、两组DELETE矩阵和原日志保留共四个精确cohort已整合到fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff。原Python discover真实57/57通过、零skip；首次job随后因普通index字节身份变化停止，原controller1保留。只读复核证明当前9,575条path/mode/OID/stage与cabc完全一致、无特殊位或额外项；已接受实测c41b4d7索引快照，但旧索引二进制不可用，具体变化字段及原因仍未知。续跑未重执行Python或重施源码，正常helper构建、完整193成员/1501节点metadata及19,506 eligible/57 ignored目录比较通过，原未过滤full返回just100。16项失败的完整XML正文已逐项审读：14项旧输出异常、2项新问题；25项早退不计作省略行为通过。最终原fix/fmt及两项差异检查已完成；固定新提交的原平台CI仍待完成。[Python与索引根审](fourth-windows-python-index-root-review.json) / [续跑约束](source-assembly/windows-full-after-index-root-execution-guard.json) / [新full逐项根审](fourth-full-fb9-nonpass-root-review.json)

所属包与完整workspace失败均未豁免。最终fix/fmt已完成；新head的原hosted CI仍待验收。

## 4. 已发布候选的原平台终态

cabc的19workflow为14成功/3失败/2跳过；blocking37jobs为22成功/11失败/4跳过。失败是blocking、独立musl、Windows lifecycle。普通实际merge为28af7f705fa1024b9a6d2ef751fec116002260eb，tree与cabc同为b2d7f038d6d88156bc6a4cb29c8703f69b808f29；新源码不得借其结果。[原CI全终态](fourth-cabc-ci-terminal.json)

GNU与标名musl的blocking lane实际共用GNU/RBE，441PASS/3FAIL/160skip，不是独立libc验收。真正musl在GNU std/musl linker的open64/fstat64阶段失败，没有合格ELF/smoke。ARM为435PASS/2FAIL/167skip；Intel仍有turn_state、forward超时和两PTY失败。Windows各shard的失败、flaky attempt与cache单列。[原平台失败全集](fourth-original-platform-failures.json)

Windows限域结果保留：source/merge各13 resume、121 rollout、254 exec通过；retained532PASS、另7原skip；两私有目录正向与两个冻结负控分别满足原范围。strict ACL flags03对0b、restricted SID删除和legacy外部删除三项未闭合。write/create DENY不自动建立DELETE DENY；DELETE与父目录DELETE_CHILD仍需因果区分。

历史助手记录提到生产Windows token/ACL/loader/DLL修改曾受审批限制；本轮检索没有恢复原decision/action/reason回执，也没有找到用户设定的永久Windows禁令，因此不把未恢复的叙述当作新的审批事实。保持原public query和原负控的窄范围ACL幂等识别候选，以及restricted-token删除边界的四格物理控制V2，均已精确应用到fb9组合源，尚未在Windows原生编译或执行，含原token与legacy两条入口和普通host对照，原三例定义及时间预算保留。当前未改token旗标，未据静态推理闭合。[四格候选](static-proposals/b11-delete-matrix/repair-manifest.json)[原修复设计](WINDOWS_BOUNDARY_REPAIR_DESIGN.md)

UI六ZIP共358成员已核。各lane HTTP96、Gateway7PW与后端2+5+12+9、Robrix6/9/1按真实源记录；像素JSON60 captures/138 checks和78/438通过，不是新人工视觉验收。实际UI merge为7ccc78d…、tree仍b2，与普通workflow metadata的28af分开。CJK48、IME7组28、SDK appQualified=false及总qualification=false保留；正常Root caller接受仍未建立。[UI原件核验](fourth-ui-original-root-review.json)

当前可用环境也已实际核查：7个配置别名中，6个非ROG别名的硬件快照均完整取得；mac/main均为Darwin/arm64/Apple M5且返回同一主机名，另外4个为Linux/x86_64。没有配置Windows，也没有实测Intel macOS。ARM Mac与Linux Intel不能替代这两类原生平台门，仍以最终head的对应原CI为验收依据。[主机原文与范围](fourth-host-platform-discovery.json)

## 5. 七组原名证据与待补平台

对B07/B08/B09/B13/B20/B22/B23的97原名及8上下文名，已投影7份原归档：243成员、406观察，其中331账本行/75上下文行；去重为64账本名/8上下文名。39份XML只有wrapper而无原名，不能填逐case PASS。GNU/musl标签54对应成员逐字相同，不增加独立平台资格。[完整投影](fourth-seven-rows-original-projection.json) / [根审](fourth-seven-rows-root-review.json)

已有正文足够的24原名不为凑数另行重跑。73原名在至少一个要求平台缺证据，已整理为10原CI查询、7原target、33 target/platform对；需要最终同源原CI正文，不能新造更弱替代控制。final_head_binding暂为null，待实际发布/checkout绑定。[范围说明](FOURTH_SEVEN_ROWS_SCOPE.zh-CN.md) / [机器缺口](fourth-seven-rows-missing-evidence.json)

## 6. B16可信入口：基础已有结果，正常闭环仍是关键路径

正常入口需串联Root handoff、Registry/arg0身份、protected checkpoint/verifier、FinalUse issuer、listener custody与真实UI caller。随后用同源Root/Session、原signed objective和provider/target执行任务/取消/丢ACK/重启/回滚，核对物理效果、authority、evidence、Memory。

R0已形成102路径决策：63 donor-only、27双方不同、8相同、4 current-only，9 crates、6 cohort；不是可任意抽取的launcher。固定c42 normal Root producer仍Notes-only，UI又缺旧c2 joint consumer；两源非包含关系。当前Agentd attachment返回真实UI original_sender，普通current-user peer gate和owner-local边界必须保留。joint grant30秒与Root300秒也需合同级处理，不能自授authority。[R0迁移计划](B16_R0_SOURCE_AND_MIGRATION.zh-CN.md)

| 批次 | 进展 | 开放边界 |
|---|---|---|
| R1/R2a/R2b | arg0、inherited listener、authority clock已有原生结果 | 不构成普通Root/UI接受 |
| R2c | SQLite连接级COMMIT veto、growth/reuse/cancel控制已独审 | 未编译/执行，不宣称531已验 |
| R2d | readonly observer与query_only/BEGIN IMMEDIATE barrier、close-on-drop反例已独审 | 原实际控制未执行 |
| R2e1 | store monotonic gate与checkpoint取消veto接线已独审 | 最后live检查到COMMIT窗口仍在；逐提交Current/expiry/revoke未接 |
| R2e2a/b | 32KiB wire、ASCII/UTF8、digest、whole-head CAS/序列/转换已独审 | 7控制未执行；ReadHead观察/公共DTO不等于认证Current |
| R2e3 | 已注册物理连接的真实锁custody与4 File/SQL控制已独审 | 注册前open/PRAGMA、growth/replacement取消、raw替换、独立opener开放 |

SQLx会先销毁commit hook再sqlite3_close，所以hook capture不足以覆盖WAL/SHM清理。R2e3利用原安全collation API保留同一真实锁capture，commit hook仍决定提交准许。xDestroy晚于该连接Btree/Pager/WAL清理，**不代表晚于sqlite3_close返回**。该候选明确不关闭注册前取消或Current最终使用链。[完整manifest](fourth-b16-r2e3-manifest.json) / [逐主源根审](fourth-b16-r2e3-root-review.json)

注册前缺口现已进一步核到固定SQLx 0.9.0主源：worker只接收EstablishParams，原生open与初始PRAGMA早于options collation和pool after_connect；pool自己的acquire timeout也能取消connect。现有正常公共API没有在open前交接真实custody的入口。前阶段“不fork依赖”是研究范围约束，并非用户永久禁令或自动审批拒绝；最小依赖层lifetime-token补丁及独立静态审查已完成：在spawn/open前交接真实owner，成功native close后释放；BUSY/关闭失败保留owner并维持原错误。原生采用和实际四项物理控制尚未执行。它只管理生命周期，不替代Current或授权。[固定主源与可执行后续方向](FOURTH_B16_PRE_REGISTRATION_CUSTODY.zh-CN.md)

六批提案已完成独立串行源对齐：51对象、19次隔离patch应用、16最终路径两条重建路线逐字相等。R2d/R2e1的旧R2c元数据引用不会覆盖V3测试；原六manifest不改，以增量对齐收据说明。计划包含24个新精确用例和10个实际因果阶段，下一步进入原生编译/执行；这些静态结果没有计为测试通过。[串行方案](FOURTH_B16_SERIAL_PLAN.zh-CN.md)

完整workspace的正常Cargo metadata给出了实际SQLx缓存身份：两个0.9.0 crate的VCS为003b698e，发布标签为75bc048。17个原包文件逐字核验，11个关键SQLite/Core源与此前主源完全相同；两个原.crate的SHA256与Cargo.lock checksum相等。根tree并非整个相同，规范化Cargo.toml与原Cargo.toml.orig分开保存，实际不存在.cargo-checksum.json也如实记录；B16继续以这些实际包字节为基线。[实际依赖增补](FOURTH_SQLX_ACTUAL_CRATE.zh-CN.md) / [根审](fourth-sqlx-actual-crate-root-review.json)

两个state pool入口已准备四行实际owner接线，并有独立静态重建和三项父控制设计；同一原File及Windows目录句柄经CognitiveCommitGate捕获进入native token，未创造新授权。两个state控制包含临时Tokio runtime退出与opening future取消，不单独证明runtime存活时取消；Memory控制仅在移除旧hook/collation后读取真实SQL，再验证native close释放锁。独审同时发现private recovery checkpoint在validation pool关闭后另开普通连接，未绑定同一owner。针对这个实际入口，已另备2个生产路径15增/3删、3个控制路径324增的静态候选；这些是源码行数，不是通过用例数。该候选尚未应用、编译或执行，不改变checkpoint、ACK、发布或Current授权。B16整体保持开放。[caller独审与明确缺口](fourth-b16-native-caller-independent-review.json) / [checkpoint静态候选](static-proposals/b16-checkpoint/repair-manifest.json)

B16五阶段执行器V3已通过独立静态审查，112个源对象、24个转换和17次负控选择的源码锚点已经核对；这些均不是原生执行次数。V3修复了JUnit终态属性丢失的问题，超时、句柄泄漏和未知失败类型会在物理判据之前停止。各阶段复用A的真实target并各自重建程序；最终A源与最后实际测试源分别绑定，磁盘容量仍待实测。A当前修复的Draft发布优先，B保持未启动。[执行器与原版本](static-proposals/b16-native-runner/README.md) / [独立静态审查](static-proposals/b16-native-runner/independent-static-review-v3.json) / [根审](fourth-b16-runner-v3-root-static-review.json)

## 7. 科学采用与外部接受

#4798固定77b244终稿补齐了报告缺失。32/32 fits，4收益CI均跨0，0/4过预设收益线，0/256同时满足全部八质量门。四个均值与区间如下：

| 比较 | 均值 | 区间 |
|---|---:|---|
| 1 | −0.011212158 | [−0.0777352, 0.0553109] |
| 2 | −0.022689209 | [−0.1089372, 0.0635588] |
| 3 | +0.003876953 | [−0.0525625, 0.0603164] |
| 4 | +0.009311523 | [−0.0451946, 0.0638177] |

这是同模型家族多轮反馈相对单轮，不是解析核D−B；不能推出零效应、普遍伤害或等价。旧23:49–23:51 UTC刷新及本次完整终锚/固定head工作流读回均无#4798源码或新原始实验增量；当前头3个工作流为2成功/1blocking失败，与4个科学比较不是同一计数。[研究增量](fourth-research-current-delta.json)

37归档/30,735成员/25,506,732记录比较未见违规，最大残差4.44e−16；没有重放完整teacher/RNG/decoder/optimizer。CPU下界8,326.229650133秒含55.0725秒中止worker，另3controller成本unknown。[原研究范围](THIRD_AUDIT_PROGRESS.zh-CN.md)

下一轮采用需事前冻结2×2：A强普通、B同任务价值控制、C解析、D解析+价值控制；主量D−B，另报B−A/D−C/C−A/交互。固定同信息、独立数据/评估者、等总CPU、初始化/驻留/失败成本与充分精度，保留全部尝试。未过时继续强普通默认，不能挑seed、改阈值把HOLD“修绿”。

内部HeptaBao13关键能力为11partial/2gap/0closed；外部固定eac9/OpenBao2.6.2的60surface中13限域实现/47定义是另一分母，不证明完整替代任意后续版本。真实consumer、独立签名、epoch/revoke/freshness需与本产品caller验收。Chain历史27round的6confirmed/9unconfirmed/12unobserved来自旧17:02记录，本轮未恢复原逐round receipt或重跑；经典Ed25519不构成后量子资格。HIA DENY_ALL与safety_certificate=false保留。[外部闭合计划](EXTERNAL_CLOSURE_PLAN_ZH.md)

#4823的独立复核已完成：固定9f2d00f科学源的452件原文件（39,426,104字节）逐件核Git/bytes/SHA，并重算5个既有拟合检查点上的4项Bonferroni校正区间。有限Bellman J−C在冻结IID/OOD任务分别为0.10528、0.20216，区间下界0.04777、0.12036，均超过0.005门槛。15个D/G/R权重候选均未过VAL门并恢复C，D_gated−C的两组0是回退结果，不能解释为原D无效果或等效证明。J改变了规划算法与计算量；OOD分布已在VAL暴露，320个TEST世界不是320次独立拟合。TRAIN证书、77组保存回放和native/Qwen记录得到有限的一致性复核，但本次没有重运行模型或取得完整总成本，不能替代B18原D−B采用门。原B18继续HOLD。[科学独审](scientific-pr4823/INDEPENDENT_REVIEW.zh-CN.md) / [根审与独立重算](fourth-pr4823-root-review.json)

Chain固定continuation README中的不同范围控制与结构核查仍保HOLD_NO_GO，runtime endpoint/真实WAN接受未建立。[Chain与此前donor历史范围](FOURTH_DONOR_PROGRESS_20261105.zh-CN.md)

## 8. 后续执行计划

| 顺序 | 实际工作与交付 | 退出条件 |
|---|---|---|
| P0当前 | 保留原25、所属7包与两轮full的已完成原结果；原fix/fmt已完成，统一源码/锁/证据提交现有Draft并验原平台CI，16项失败继续开放 | 原断言/预算/负控不弱化，完整raw/JUnit、程序身份一致，剩余失败如实保留 |
| P0原平台 | 最终head与merge原CI；成功正文；真实musl ELF/smoke；Intel/Windows逐因果处理 | 原required均满足；cache/skip/retry/早退分列，审批限制不绕过 |
| P1可信普通入口 | 执行R2c/d/e与native token/caller/checkpoint控制；独立审4812/4821净迁移，保Current、Root/joint/FinalUse/listener合同 | 普通启动同源authority/sender，任务/拒绝/取消/丢ACK/重启/回滚有独立物理证据 |
| P2共享计算/Memory | 一套Encoder/Cell/worker、单写者域、有界队列、可重建投影 | 64/256/1024/4096 logical Cell与实际并发分别测质量、CPU、RSS、p50/p95/p99、总成本及恢复 |
| P3–P4 shadow/C1 | 等预算只读排序因子/消融，proposer/scorer/acceptor分开 | exact-source/freshness/contradiction/cite-before-use/abstain-on-stale，zero Memory/KG/tool/provider effect和独立收益 |
| P5未来验证 | 下一snapshot签名加载/回滚、遗忘不复活、未来日历holdout | 实际未来窗口完成，Current/来源/forget frontier一致 |
| P6–P8后续 | 结构塑性、源码候选、simulator/HIL、授权外部fixture | 各自前驱、硬件、真实owner输入与独立接受满足 |

[完整40模块/91工作包/owner及三类前驱计划](PROJECT_DIRECTION_AND_PLAN.zh-CN.md)继续作为分解依据，不以没有资源和验收依据的日期承诺替代完成。

## 9. 23项原账本

| ID | 工作包 | 当前状态 | 下一验收门 |
|---|---|---|---|
| B01 | 仓库与证据清单 | 固定全量快照完成；新1103 PR / 5193分支，旧1088快照保留 | 后续发布与新CI继续绑定各自观察时间；不把增量观察冒充全量当前总数。 |
| B02 | 单一整合候选 | 单一候选确定；最终源码/CI资格开放 | 保r3 Guardian取消/截止及runtime-scoped Git缓存；最终同一次提交完整源码/锁/证据，验原required CI和合成merge树。 |
| B03 | cwd 展示语义 | cwd原始7例范围闭合 | 新整合树保留原语义，若改该代码才触发相应重验。 |
| B04 | 认知投影 oracle | 认知投影oracle原目标范围闭合 | 保不可变revision/当前指针、来源/更正/删除/重启等原断言；最终产品资格另归B15。 |
| B05 | supervisord 子进程定位 | supervisord绝对可执行路径范围闭合 | 新RPC失败由独立诊断记录处理，保原daemon预算和控制fence。 |
| B06 | 正向私有路径夹具 | 首批正向路径原目标闭合；TUI另列 | 不得写逐case7/7或零skip/retry；TUI第二批仅按其真实原平台收据更新，不混B22。 |
| B07 | Hook 元数据与工具可见性 | 原元数据控制有证据；新Hook两例通过，最终平台开放 | 最终候选原Hook/MCP/Executor/TokenBudget及allow/deny、环境错配、陈旧目录控制同源终态通过。 |
| B08 | 私有 attempted tool 元数据 | 原retained/wire与Linux replay已有局部证据 | 在新固定head及merge的原平台执行新增namespaced原例与保留的wire/retained边界；不借B09/B10通过计数。 |
| B09 | 终态清理与恢复 | 原恢复与Windows指定范围有证据；最终CI开放 | 保busy/lineage/exact实例/fence与恢复原负控；最终范围依独立原48映射和本候选原CI。 |
| B10 | WebSocket / prewarm / compact | 新Core六例通过；最终原平台开放 | 用同源原turn_state与身份负控验收；不修改production身份或通过放宽请求数获取绿色。 |
| B11 | Windows 原生 sandbox 与 helper | Windows helper原范围通过；三个严格权限失败仍开放 | 已审窄ACL与四格控制已应用到组合源，最终fix/fmt已完成，待新head原WindowsCI验收。保留原严格token/legacy断言和预算；历史审批原receipt未恢复，不虚构新拒绝或永久禁令。 |
| B12 | Windows 私有目录冻结对照 | 原Windows两正向与两冻结负控范围闭合 | 保留该scope闭合；不外推一般Windows权限或原strict delete三例。 |
| B13 | Lease / Queue 时序夹具 | Lease/Queue局部通过；成功正文缺口仍开放 | 原平台同源结果以独立48映射为准；不在此重算或将异源native通过升级全矩阵。 |
| B14 | Windows exec 恢复清理开销 | 原Windows source/merge各13恢复例闭合 | 保留已完成的原Windows helper前置、source/merge各13恢复例及原业务/清理断言；新最终head的整体平台资格归B15，不重复旧scope以凑通过数。 |
| B15 | 最终 CI 与 main 资格 | 原full16FAIL；最终hygiene完成，原平台CI开放 | 最终精确head、base和merge tree、所有required门、原失败与有效负控齐全；保全部skip/retry/cache/unknown，原48映射独立维护。 |
| B16 | 可信产品入口及外部效果 | 入口基础已实测；Current、正常接线和真实接受开放 | 按独立R1–R6批次实现：arg0基础→trust/Current与inherited合同→Agentd装配→joint consumer→normal producer与paired pin→原真实接受。R0的102决策/474净差不等于编译最小闭包。 |
| B17 | #4578 缺失确认终稿 | 32-fit缺失终稿已补；报告范围闭合 | 保77b244终稿与冻结903946源、全部失败与成本unknown；不为使结论变绿重训同一确认集。 |
| B18 | 解析核心 / 参数记忆科学采用 | 科学HOLD | 保留原D−B采用门与HOLD。J有限规划作为独立有证据的组件继续评估，权重编辑保强普通默认与验证回退；新实验先冻结独立数据、拟合单位、计算成本和全部失败保留，禁止以J−C、原记录重放或移植一致性换名关闭D−B。 |
| B19 | HeptaBao / Chain / HIA 外部接受 | 外部兼容及本产品独立接受开放 | 按B19-Bao/B19-Chain/B19-HIA分开取得同源实现与真实目标接受；advisory DENY_ALL/safety_certificate=false保持。 |
| B20 | 远程控制握手夹具 | 旧原19例正文已核；新最终同源CI开放 | 最新候选原19例及原平台CI以精确收据关闭；不得跳过正常HTTP或替代真实握手。 |
| B21 | macOS Intel PTY退出和输出 | ROG PTY29/转发/监督31例通过；Intel原门开放 | 原Intel30例、完整drain/child/FD原断言和2/5秒预算不变；同源因果与原平台结果齐全。 |
| B22 | TUI 中断与退出顺序 | Windows目标级通过；逐case正文仍缺 | 原Windows interrupt/shutdown case与真实stdout就绪、canonical cwd和原5秒预算；结果交独立48映射。 |
| B23 | App Server Unix关闭信号生命周期 | Unix原因果负控及5例通过；最终原平台开放 | 同最终source原Unix平台验收；原stdio/disabled语义和drain规则保持；首signal注册失败提前报错属已审兼容差异。 |

八项范围内闭合为B01/B03/B04/B05/B06/B12/B14/B17，科学HOLD为B18，其余14项开放。新失败作为对应包子项记录，原23项退出条件不因拆分或改名改变。

候选保持Draft。可执行修复和验收继续推进；Windows严格权限契约、真实外部权威输入与科学HOLD分别保留边界。没有以自签authority、删失败、跳控制、降低断言或增加原预算取得完成判定。

## 证据导航

- [第四批技术资格与执行树](FOURTH_BATCH_QUALIFICATION.md)
- [当前23项机器账本](current-blockers.json)
- [新完整库存](fourth-repository-inventory-20261105.json) / [旧1088历史快照](fourth-complete-inventory.json)
- [新donor固定源与资格](FOURTH_DONOR_PROGRESS_20261105.zh-CN.md) / [机器索引](fourth-donor-progress-20261105.json)
- [第四批证据索引](fourth-evidence-index.json)
- [原平台失败全集](fourth-original-platform-failures.json)
- [七组原名的平台缺口](FOURTH_SEVEN_ROWS_SCOPE.zh-CN.md)
- [13原例与有效负控根审](fourth-bash-no-rc-native-root-review.json)
- [R2e3物理持锁候选](fourth-b16-r2e3-manifest.json)
- [前一版完整报告](THIRD_AUDIT_PROGRESS.zh-CN.md)
- [整合PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)

## 最终代码与下一道门禁

第四批共22个连续源提交，终点为 `20fd174ded4e5ce01bda34e4f6d1d74803301f49`，最终原生代码树为 `4a3374e22e16ce5c764288ad018cd9affadf94ea`。原 `just fix` 实际exit0（220.947秒），只删除当前Linux64范围两处同类型转换；原 `just fmt` 实际exit0（42.684秒），17文件的完整改动已经双重审查。随后两项原/完整候选差异检查均exit0（0.287/0.294秒），完整54路径映射重算得到同一个Git树。两次自动改动后的controller3是保留的审查停点，最终controller为0；这些成功不覆盖完整测试的16FAIL与25项早退，也不提供Windows或Intel原生资格。[最终收口根审](fourth-final-A-complete-hygiene-root-review.json) / [完整索引原件复核](fourth-windows-index-complete-root-review.json)。

下一步按现有Draft提交本批源码及证据，绑定新head、base、真实merge tree和原工作流。Core新增失败的裸线程缺失错误更符合rollout flush传播路径，但尚未定位哪一次flush；Proxy存在原2秒DNS与原2秒读取预算的静态竞争可能，原日志尚不能证明实际进入DNS。两项继续OPEN，观测候选尚未执行。[Core诊断](diagnostics/core-cold-root-fb9/CORE_COLD_ROOT_DIAGNOSIS.zh-CN.md) / [Proxy诊断](diagnostics/proxy-connect-fb9/STATIC_DIAGNOSIS_ZH.md)。

B16最后实测剩余空间为23,893,377,024字节，旧40,122,997,968字节foundation预算不满足。仅foundation复用既有构建产物路径的条件方案正在独立复核，执行前仍须重新量取容量并满足完整资源门；本批没有执行B或关闭其正常入口/真实接受门。容量变化未归因于本任务或其他具体进程。
