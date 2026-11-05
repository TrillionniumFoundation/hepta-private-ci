# Hepta 全量审计、发展方向与阻塞项闭合进度

## 结论与范围

项目已有大量源码、真实原生控制与平台执行证据，但尚未达到全阻塞项闭合、完整产品入口或 main 合入资格。本轮以 [PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797) 为唯一整合候选，持续实际修复和验收。原23项工作包为 **8项范围内闭合、14项开放、1项科学HOLD**；第四批局部通过没有换算为整项完成。[当前机器账本](current-blockers.json)

近期发展方向依次是：**可重复验证的整合候选 → 普通启动可用的可信任务闭环 → 同信息、等总成本的共享计算与学习验证 → 独立外部接受**。源码存在、局部通过、科学采用和生产发布需要各自的退出证据。

报告更新于2026-11-04美国东部时间；机器收据保留UTC。完整库存终锚为2026-11-04 22:27:38 UTC，各增量和原生执行另有source tree与时间。已发布候选为cabcb40d36e116beaa65750e1f674c52035da785；最近审读原生树为da60f29b6789434c394edeff3c79f59191ad932c，仍在修复。最终commit、base和实际merge checkout由PR与新CI另行绑定，不能继承旧源绿色。

全局架构权威仍为 [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md)。本目录记录特定候选资格；[前一版完整报告](THIRD_AUDIT_PROGRESS.zh-CN.md)、旧失败和原退出条件都保留。

## 1. 全量盘点与实际开发阶段

完整分页快照覆盖 **1,088个open PR、5,163个分支、0个open issue、0个已发布release**。其中1,064个Draft、24个非Draft；154个直接以main为base、934个为其他base；最长依赖链211层。12页PR与53页分支完整收集。首次收集后出现#4808，已重新执行全部PR分页并核对终锚；没有重复、依赖环或head/branch不一致。185个PR的metadata base SHA不同于当前分支tip，不自动证明冲突。[完整库存及逐字分片](fourth-complete-inventory.json)

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
- literal-deny将真实字面路径错建为GlobPattern。改为PathUri后进入真实执行，又暴露父批准后的子进程重复审批；第二阶段仍开放。
- readonly snapshot原夹具在只读沙箱写counter，且两请求不是同一cache key。修正后仍提前读.bashrc，继而定位并修复Bash恢复路径。

### snapshot：有效反例和原矩阵已有实际结果

恢复argv仅增加--norc，保留原-pc、set +o privileged、环境过滤与sandbox。原捕获/fallback的-lc及非Bash行为未改。实际诊断证明.bashrc函数先于snapshot恢复执行；GNU启动规则支持该修复方向。getpeername/EPERM的精确因果仍是条件推断，没有冒称已trace。[主源与限制](FOURTH_BASH_STARTUP_SOURCE.zh-CN.md)

c270有效负控先通过第一个原完整tuple，再实际覆盖profile，只改变第二次scope，原第二tuple在267行FAIL且profile_helper缺失。实际exit0，不预设42。其后controller变量遮蔽TypeError发生在restore首guard、写源之前；续跑完整重验同一树/原件/程序身份，只恢复正向夹具，没有重跑有效负控。[原负控](fourth-bash-no-rc-valid-negative.json)

da60原13例 **12PASS/1FAIL，0retry、0选中skip、0早退**：8 snapshot Linux分支、2 Hook、2 Skill通过。literal-deny在原893行仍收到意外/usr/bin/cat审批，denial/no-secret终点尚未到达。当前最小修复方向是让父批准后子评估使用实际生效权限，显式拒绝、危险命令与原sandbox继续保留。随后仍需原owning7、完整workspace、最终fix/fmt和新CI。[完整13例](fourth-four-fixtures-13-native.json) / [根审](fourth-bash-no-rc-native-root-review.json)

## 4. 已发布候选的原平台终态

cabc的19workflow为14成功/3失败/2跳过；blocking37jobs为22成功/11失败/4跳过。失败是blocking、独立musl、Windows lifecycle。普通实际merge为28af7f705fa1024b9a6d2ef751fec116002260eb，tree与cabc同为b2d7f038d6d88156bc6a4cb29c8703f69b808f29；新源码不得借其结果。[原CI全终态](fourth-cabc-ci-terminal.json)

GNU与标名musl的blocking lane实际共用GNU/RBE，441PASS/3FAIL/160skip，不是独立libc验收。真正musl在GNU std/musl linker的open64/fstat64阶段失败，没有合格ELF/smoke。ARM为435PASS/2FAIL/167skip；Intel仍有turn_state、forward超时和两PTY失败。Windows各shard的失败、flaky attempt与cache单列。[原平台失败全集](fourth-original-platform-failures.json)

Windows限域结果保留：source/merge各13 resume、121 rollout、254 exec通过；retained532PASS、另7原skip；两私有目录正向与两个冻结负控分别满足原范围。strict ACL flags03对0b、restricted SID删除和legacy外部删除三项未闭合。write/create DENY不自动建立DELETE DENY；DELETE与父目录DELETE_CHILD仍需因果区分。

历史自动审批曾拒绝生产Windows token/ACL/loader/DLL边界修改；原decision回执本轮未恢复，因此不编造拒绝原因或扩大成一般Root禁令，具体限制继续保留。[已准备修复设计](WINDOWS_BOUNDARY_REPAIR_DESIGN.md)。其他获准构建、只读诊断和原测试继续执行。

UI六ZIP共358成员已核。各lane HTTP96、Gateway7PW与后端2+5+12+9、Robrix6/9/1按真实源记录；像素JSON60 captures/138 checks和78/438通过，不是新人工视觉验收。实际UI merge为7ccc78d…、tree仍b2，与普通workflow metadata的28af分开。CJK48、IME7组28、SDK appQualified=false及总qualification=false保留；正常Root caller接受仍未建立。[UI原件核验](fourth-ui-original-root-review.json)

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

## 7. 科学采用与外部接受

#4798固定77b244终稿补齐了报告缺失。32/32 fits，4收益CI均跨0，0/4过预设收益线，0/256同时满足全部八质量门。四个均值与区间如下：

| 比较 | 均值 | 区间 |
|---|---:|---|
| 1 | −0.011212158 | [−0.0777352, 0.0553109] |
| 2 | −0.022689209 | [−0.1089372, 0.0635588] |
| 3 | +0.003876953 | [−0.0525625, 0.0603164] |
| 4 | +0.009311523 | [−0.0451946, 0.0638177] |

这是同模型家族多轮反馈相对单轮，不是解析核D−B；不能推出零效应、普遍伤害或等价。23:49–23:51 UTC刷新无源码/实验/rerun增量，研究blocking仍失败。[研究增量](fourth-research-current-delta.json)

37归档/30,735成员/25,506,732记录比较未见违规，最大残差4.44e−16；没有重放完整teacher/RNG/decoder/optimizer。CPU下界8,326.229650133秒含55.0725秒中止worker，另3controller成本unknown。[原研究范围](THIRD_AUDIT_PROGRESS.zh-CN.md)

下一轮采用需事前冻结2×2：A强普通、B同任务价值控制、C解析、D解析+价值控制；主量D−B，另报B−A/D−C/C−A/交互。固定同信息、独立数据/评估者、等总CPU、初始化/驻留/失败成本与充分精度，保留全部尝试。未过时继续强普通默认，不能挑seed、改阈值把HOLD“修绿”。

内部HeptaBao13关键能力为11partial/2gap/0closed；外部固定eac9/OpenBao2.6.2的60surface中13限域实现/47定义是另一分母，不证明完整替代任意后续版本。真实consumer、独立签名、epoch/revoke/freshness需与本产品caller验收。Chain历史27round的6confirmed/9unconfirmed/12unobserved来自旧17:02记录，本轮未恢复原逐round receipt或重跑；经典Ed25519不构成后量子资格。HIA DENY_ALL与safety_certificate=false保留。[外部闭合计划](EXTERNAL_CLOSURE_PLAN_ZH.md)

## 8. 后续执行计划

| 顺序 | 实际工作与交付 | 退出条件 |
|---|---|---|
| P0当前 | literal-deny父/子审批修复；原所属7包和完整workspace；原fix/fmt；统一源码/锁/证据发布 | 原断言/预算/负控不弱化，完整raw/JUnit、程序身份一致，剩余失败如实保留 |
| P0原平台 | 最终head与merge原CI；成功正文；真实musl ELF/smoke；Intel/Windows逐因果处理 | 原required均满足；cache/skip/retry/早退分列，审批限制不绕过 |
| P1可信普通入口 | 执行R2c/d/e控制，解决注册前取消与逐提交Current，接Root/joint/FinalUse/listener | 普通启动同源authority/sender，任务/拒绝/取消/丢ACK/重启/回滚有独立物理证据 |
| P2共享计算/Memory | 一套Encoder/Cell/worker、单写者域、有界队列、可重建投影 | 64/256/1024/4096 logical Cell与实际并发分别测质量、CPU、RSS、p50/p95/p99、总成本及恢复 |
| P3–P4 shadow/C1 | 等预算只读排序因子/消融，proposer/scorer/acceptor分开 | exact-source/freshness/contradiction/cite-before-use/abstain-on-stale，zero Memory/KG/tool/provider effect和独立收益 |
| P5未来验证 | 下一snapshot签名加载/回滚、遗忘不复活、未来日历holdout | 实际未来窗口完成，Current/来源/forget frontier一致 |
| P6–P8后续 | 结构塑性、源码候选、simulator/HIL、授权外部fixture | 各自前驱、硬件、真实owner输入与独立接受满足 |

[完整40模块/91工作包/owner及三类前驱计划](PROJECT_DIRECTION_AND_PLAN.zh-CN.md)继续作为分解依据，不以没有资源和验收依据的日期承诺替代完成。

## 9. 23项原账本

| ID | 工作包 | 当前状态 | 下一验收门 |
|---|---|---|---|
| B01 | 仓库与证据清单 | 固定全量快照完成；1088 PR / 5163 分支 | 后续发布与新CI继续绑定各自观察时间；不把增量观察冒充全量当前总数。 |
| B02 | 单一整合候选 | 单一候选确定；最终源码/CI资格开放 | 保r3 Guardian取消/截止及runtime-scoped Git缓存；最终同一次提交完整源码/锁/证据，验原required CI和合成merge树。 |
| B03 | cwd 展示语义 | cwd原始7例范围闭合 | 新整合树保留原语义，若改该代码才触发相应重验。 |
| B04 | 认知投影 oracle | 认知投影oracle原目标范围闭合 | 保不可变revision/当前指针、来源/更正/删除/重启等原断言；最终产品资格另归B15。 |
| B05 | supervisord 子进程定位 | supervisord绝对可执行路径范围闭合 | 新RPC失败由独立诊断记录处理，保原daemon预算和控制fence。 |
| B06 | 正向私有路径夹具 | 首批正向路径原目标闭合；TUI另列 | 不得写逐case7/7或零skip/retry；TUI第二批仅按其真实原平台收据更新，不混B22。 |
| B07 | Hook 元数据与工具可见性 | 原元数据控制有证据；新Hook两例通过，最终平台开放 | 最终候选原Hook/MCP/Executor/TokenBudget及allow/deny、环境错配、陈旧目录控制同源终态通过。 |
| B08 | 私有 attempted tool 元数据 | 原retained/wire与Linux replay已有局部证据 | 在新固定head及merge的原平台执行新增namespaced原例与保留的wire/retained边界；不借B09/B10通过计数。 |
| B09 | 终态清理与恢复 | 原恢复与Windows指定范围有证据；最终CI开放 | 保busy/lineage/exact实例/fence与恢复原负控；最终范围依独立原48映射和本候选原CI。 |
| B10 | WebSocket / prewarm / compact | 新Core六例通过；最终原平台开放 | 用同源原turn_state与身份负控验收；不修改production身份或通过放宽请求数获取绿色。 |
| B11 | Windows 原生 sandbox 与 helper | Windows helper原范围通过；三个严格权限失败仍开放 | 先保留原始诊断和四格权限/删除判别设计；本任务暂不改production token/ACL/loader/DLL。原审批receipt缺失须补证，不能虚构拒绝理由或扩大成一般Root禁令。 |
| B12 | Windows 私有目录冻结对照 | 原Windows两正向与两冻结负控范围闭合 | 保留该scope闭合；不外推一般Windows权限或原strict delete三例。 |
| B13 | Lease / Queue 时序夹具 | Lease/Queue局部通过；成功正文缺口仍开放 | 原平台同源结果以独立48映射为准；不在此重算或将异源native通过升级全矩阵。 |
| B14 | Windows exec 恢复清理开销 | 原Windows source/merge各13恢复例闭合 | 保留已完成的原Windows helper前置、source/merge各13恢复例及原业务/清理断言；新最终head的整体平台资格归B15，不重复旧scope以凑通过数。 |
| B15 | 最终 CI 与 main 资格 | cabc完整CI失败；新组合原全门禁待验 | 最终精确head、base和merge tree、所有required门、原失败与有效负控齐全；保全部skip/retry/cache/unknown，原48映射独立维护。 |
| B16 | 可信产品入口及外部效果 | 入口基础已实测；Current、正常接线和真实接受开放 | 按独立R1–R6批次实现：arg0基础→trust/Current与inherited合同→Agentd装配→joint consumer→normal producer与paired pin→原真实接受。R0的102决策/474净差不等于编译最小闭包。 |
| B17 | #4578 缺失确认终稿 | 32-fit缺失终稿已补；报告范围闭合 | 保77b244终稿与冻结903946源、全部失败与成本unknown；不为使结论变绿重训同一确认集。 |
| B18 | 解析核心 / 参数记忆科学采用 | 科学HOLD | 若继续研究，执行R0/R1/R2的新冻结协议与独立数据；不继续也可保留明确不采用决策，不追求事后正结果。 |
| B19 | HeptaBao / Chain / HIA 外部接受 | 外部兼容及本产品独立接受开放 | 按B19-Bao/B19-Chain/B19-HIA分开取得同源实现与真实目标接受；advisory DENY_ALL/safety_certificate=false保持。 |
| B20 | 远程控制握手夹具 | 旧原19例正文已核；新最终同源CI开放 | 最新候选原19例及原平台CI以精确收据关闭；不得跳过正常HTTP或替代真实握手。 |
| B21 | macOS Intel PTY退出和输出 | ROG PTY29/转发/监督31例通过；Intel原门开放 | 原Intel30例、完整drain/child/FD原断言和2/5秒预算不变；同源因果与原平台结果齐全。 |
| B22 | TUI 中断与退出顺序 | Windows目标级通过；逐case正文仍缺 | 原Windows interrupt/shutdown case与真实stdout就绪、canonical cwd和原5秒预算；结果交独立48映射。 |
| B23 | App Server Unix关闭信号生命周期 | Unix原因果负控及5例通过；最终原平台开放 | 同最终source原Unix平台验收；原stdio/disabled语义和drain规则保持；首signal注册失败提前报错属已审兼容差异。 |

八项范围内闭合为B01/B03/B04/B05/B06/B12/B14/B17，科学HOLD为B18，其余14项开放。新失败作为对应包子项记录，原23项退出条件不因拆分或改名改变。

候选保持Draft。可执行修复和验收继续推进；具体Windows审批限制、真实外部权威输入与科学HOLD分别保留边界。没有以自签authority、删失败、跳控制、降低断言或增加原预算取得完成判定。

## 证据导航

- [第四批技术资格与执行树](FOURTH_BATCH_QUALIFICATION.md)
- [当前23项机器账本](current-blockers.json)
- [完整库存](fourth-complete-inventory.json)
- [第四批证据索引](fourth-evidence-index.json)
- [原平台失败全集](fourth-original-platform-failures.json)
- [七组原名的平台缺口](FOURTH_SEVEN_ROWS_SCOPE.zh-CN.md)
- [13原例与有效负控根审](fourth-bash-no-rc-native-root-review.json)
- [R2e3物理持锁候选](fourth-b16-r2e3-manifest.json)
- [前一版完整报告](THIRD_AUDIT_PROGRESS.zh-CN.md)
- [整合PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)
