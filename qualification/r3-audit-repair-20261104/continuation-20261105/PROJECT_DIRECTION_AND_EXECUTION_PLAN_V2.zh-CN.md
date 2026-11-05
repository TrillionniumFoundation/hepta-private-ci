# 项目发展方向与执行计划 V2

**V5 固定事实截点：2026-11-05 12:40:31 UTC，CI 对应 snapshot0040。** 本文接续原 [项目方向与分阶段执行计划](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md) 和 [23 项原始 blocker 账本](continuation-blocker-progress-v3.json)，更新执行顺序和剩余工作，不修改 canonical 注册表、原退出条件或状态分类。12:46 的后续观察在下文单列，不改写该固定截点。

当前主线继续是：**完成跨平台运行基线，交付一条真实正常业务调用链，再以可靠 Memory 和共享计算支撑有因果对照的学习闭环，最后进入真实未来窗口、具身与外部系统接受。** 当前最需要完成的两项工程工作是新 Windows Core 失败的原范围验证，以及 B16 已有 Foundation 资格之后的 driver、pool、checkpoint 接续。源码审查、编译、物理控制、正式平台 CI、独立权威接受和科学采用分别记录。

原 23 项仍为 **8 项 `CLOSED_SCOPED`、14 项 `OPEN`、B18 为 `SCIENTIFIC_HOLD`**。Foundation 的实际 `QUALIFIED` 提高了 B16 内部基础范围的证据强度；它没有关闭 B16，也没有使整个候选取得发布或 main 合并资格。

## 1. 当前事实与优先级

### 1.1 固定产品与实际执行状态

当前产品是 [Draft PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)，head 为 `5b6331250ff459033bd44d1a95daec70131277cc`，产品树为 `b26598d0d97d8d51e723bb5582137315f2174d35`，base 为 `63652be658ebed8d3052eb789b951793384fd5e4`。已观测的合成 merge `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff` 与该产品树相同。B16 在隔离 native 工作树上的后续修改尚不属于这个已发布产品树。[当前完整进度](CONTINUATION_PROGRESS_V4.zh-CN.md)

| 范围 | 当前可成立的结论 | 下一项具体动作与不能越过的边界 |
|---|---|---|
| B16 / Foundation | ai395 任务 `1a1ab493f2b-fc05-4bfe` 实际完成；24 个不同正向用例共 27 次 PASS，9 个不同负控用例共 10 次有效失败，4 次精确 finally 恢复；runner、launcher 均为 0，终态 `QUALIFIED` | 保留全部原件；后继只消费实际终态、源码、metadata 和守卫。不能把次数相加成独立用例数，不能借此宣称 driver 或正常 Root 接受通过 |
| B16 / driver | 已有具体、获准的请求；三次完全相同操作键的启动／协调调用均返回 provider 工具超时，没有可归属的 job ID，状态 `START_OUTCOME_UNKNOWN` | 保留原 key、完整请求与三次响应；仅凭新的权威任务身份或状态证据接续输出。停止猜测归属和另建 key 重复启动；不记为原生 FAIL、零用例或 PASS |
| B16 / pool | 完整模板、原 scope、oracle、恢复逻辑已静态审查；`execute=false`，driver 后树、生成锁、metadata 与终态引用仍为空 | driver 实际合格后再绑定；不能预填后树或把启动超时当作前驱已完成 |
| B16 / R2f1 | 三路径、386 行新增的 Root checkpoint transport 已双重静态审查；4 项 UDS/pidfd 控制未编译、未执行 | 在正式前驱完成后的独立源码批次编译和执行；线级响应不能直接构造 Current，测试 peer 不能充当独立 UID 0 Root |
| Memory 拒绝 COMMIT 后复用 | 已准备两路径、160 行新增／1 行删除的独立候选，生产变化为 11 行新增／1 行删除；独审 `STATIC PASS/PENDING_NATIVE`，尚未原生执行 | 验证两个显式 guarded pool 的物理红绿控制，再做所属范围回归；不修改未知 driver 请求已绑定的冻结 V7 payload |
| 新 Windows Core 失败 | job `127149546323` 的正常分片为 **2339 PASS、1 FAIL、3 ignored**；唯一失败为 `blocking_snapshot_waits_for_starting_environment`。同 job 更早隔离四例通过 | 六行 `NoSubscriber` Dispatch 方案已因未封闭竞态窗口而否决。`owned-child-v2` 已写成新增 80 行的 fixture，原分片 parent 启动同一 test binary 的 exact 单例 owned child；保原业务、三条父子 span 断言和 5 秒预算，目前静审中、未运行 |
| 截点原平台 CI | **12:40:31 UTC：19 个 workflow／44 个 job = 16 queued、16 running、9 success、1 failure、2 skipped** | 按原 attempt 收取原任务全部真实终态、完整输出、source/merge 与缓存／跳过层次。job 总数会随 workflow 展开，此时点的 44 不是最终固定分母，也不表示全部 CI 终态 |

snapshot0039 与 snapshot0040 的完整原 API 和逐项汇总已冻结。Windows owner-local job `127149582441` 于 **12:31:09 UTC** success，原日志 UDS 14、Matrixd 31、Agentd 172 合计 **217 个具名 PASS、三组均为 0 skip**；与冻结 142 个原 blocker 退出用例逐名比较，**交集为 0**。B13 的第 9 个 Agentd 原退出用例属于独立 qualification target，不在本次 `--lib` 范围，不能由 Agentd 172 例总数补成通过。诊断／业务 skip 范围的 job success 也不计为相应业务执行资格；零 skipped 汇总本身不能排除平台早退。此前 12:27:46 与 12:35:45–46 的计数保留为历史观察。[固定快照](generated-evidence/ci-5b633-owner-local-and-snapshot0040-v5/snapshot-summary.json)／[owner-local 217 例与原退出名单映射](generated-evidence/ci-5b633-owner-local-and-snapshot0040-v5/original-case-review.json)

**截点后的观察：** 12:46 的 snapshot0041 中，V8 metadata 成功后展开 14 个 build job，原任务计数增至 **58：27 queued、14 running、14 success、1 failure、2 skipped**。这是后续观察，不重标 snapshot0040 的 44-job 分母或 V5 固定截点；B15 始终要求原任务全部真实终态，并核对动态展开后的完整集合。

Foundation 最终工作树是 `e510f685d2aa7b9a7121a78f96af3569919e6f88`；普通 HEAD 仍为 `20fd174ded4e5ce01bda34e4f6d1d74803301f49`，原普通 index 和双锁保持。最后完整 metadata 来自实际 e510 工作树，193 个 workspace 成员、1501 个解析节点。P4 的 `BUILD_ONLY_CURRENT_HOST` 基线保存了构建与完整 catalog，明确没有执行测试；它不能改名为旧 A 的测试资格。Foundation 各阶段的选中 catalog 保留原 `-E` 且没有 `-p`，维持完整 workspace 解析，却不等于重新执行完整工作区。[Foundation 终态与来源层次](CONTINUATION_PROGRESS_V4.zh-CN.md#1-foundation-取得了什么资格)

此前完整工作区结果继续保留：f825 的 19503 项为 19485 JUnit PASS、17 FAIL、1 TIMEOUT；后续 fb9 的 19506 项为 19490 JUnit PASS、16 FAIL，并有 57 ignored 和 25 项已识别的行为早退。最后 fix/fmt 形成的 4a 树与最后完整测试的 fb9 树分开标识；hygiene 成功没有覆盖这些失败。后来的同名成功按其实际源与范围补证，不回写历史。[第四批原计划与完整结果](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md)

### 1.2 现在按什么顺序推进

| 优先工作 | 可以立即完成的工程动作 | 必须取得的实际验收 |
|---|---|---|
| Windows Core 日志链 | 保留已否决的六行机制探索：旧 `JustOne` reader 可在 rebuild 后写回 `never`，新增 Dispatch 未封闭该窗口；审查已写成的 `owned-child-v2`，明确同一 test binary 的 exact 单例、parent／child 生命周期与原输出关联 | 新 fixture 尚未运行；静审完成后在原生 Windows 原范围验证，保原业务和三条 parent-chain 断言、5 秒预算与原分片入口。子进程必须实际运行该例，不能以零测试成功或隔离四例的旧 PASS 抵销正常分片失败 |
| driver 启动不确定性 | 维护同一请求的可归属状态与原件；准备后继输入模板；处理有明确身份的 provider 回执 | 必须先得到该请求的真实任务身份和原输出。SSH 可达、旧 Foundation 查询成功、owned 目录未发现，均不足以判定 driver 是否启动 |
| driver → pool → checkpoint | 已冻结源码、锁门、原物理 oracle 和 finally；仅在前驱实际结束后具体化下一 binding | 每段实际终态成功、源码／两锁／metadata／工具／SDK 一致；各负控先达到物理前提再命中原断言，恢复精确成立 |
| Memory 连接复用修复 | 完成独立语义审查，保两个入口、原 owner 校验与完整物理控制；不混入当前未知执行 | 两项真实负控与正向控制、原 state/Memory 回归；不能仅靠 SQLx depth 快照代替 SQLite 物理连接与读取可用性 |
| Intel PTY | 等待 5b 原 Intel 目标的会话诊断；按 read/bytes/discard/EOF/errno、wait 状态辨别剩余阻塞 | 原 Intel 的 2 秒／5 秒预算与退出、FD、完整 drain 断言通过。Linux 和 ARM Mac 不替代 Intel |
| Windows 严格删除隔离 | 将 token、路径授权、对象生命周期与 runner 消费的合同写成最小接口设计；保留实际 parent `DELETE_CHILD` 证据 | 原严格权限／攻击／合法读写／物理四格控制在 Windows 通过；不能返回全部 Err 或删除合法 read 断言获得绿色 |

这些动作可以在源码准备与只读审查层面并行；共享 native 工作树仍由单一执行者串行修改。当前没有必要等待所有研究方向完成后才交付可用垂直流程，也不能把尚待真实 authority、目标硬件或未来时间的接受材料伪装为仓库内测试。

## 2. Canonical 方向：七条实现线、40 模块、91 工作包

本计划沿用固定 `ff72d462d74f9eb856aa9edbc368caad9c466708` 的 [DEVELOPMENT](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/DEVELOPMENT.md)、[MODULES](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/modules/MODULES.json)、[WORK_PACKAGES](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/delivery/WORK_PACKAGES.json)、[READINESS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/READINESS.json) 和 [GAPS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/GAPS.json)。这是已有规范的固定来源，不宣称本次重新扫描 5b 全部模块或重新计算生产 readiness。

Hepta 的产品方向是本地优先、可恢复的多 Agent 系统：执行与权威内核提供稳定权限和事实所有权，Memory 与学习账本提供可追溯经验，Objective／NDU 和学习组件提出可比较的候选。**Codex App Server 继续拥有 session、thread、turn、model、tool 执行主干；Agentd 负责组合和生命周期；优化器不能自行授予执行权。** 源码候选、选择、activation、外部 effect 和 release 有各自消费的证据。

### 2.1 工作包状态的准确含义

| Canonical registry state | 数量 | 本轮应转化成的工作 |
|---|---:|---|
| `source_implemented` | 25 | 查明实际 caller、测试及接受证据；有源码声明不等于生产可用 |
| `source_implemented_execution_pending` | 20 | 将原执行义务绑定到精确源码、原平台和依赖前驱，不用单元目标摘要替代 |
| `source_implemented_semantic_review_pending` | 2 | 完成独立语义审查和明确的拒绝／取消／恢复合同，再进入运行 |
| `planned` | 43 | 沿 Development、Activation、Evidence 三组 DAG，准备有 owner 和最小闭包的源码批次 |
| `blocked_external` | 1 | 对 `P0.9-EXTERNAL-GATES` 列出具体凭据、目标、消费者、科学或运行输入与接受出口 |
| **合计** | **91** | **不转换成生产完成百分比** |

40 个模块在固定注册表中均为 `existing_bound`、`source_root_present=true`，而 `production_implementation=false`。这些字段说明源码绑定和声明边界；既不表示没有实现，也不表示已经投产。当前 Foundation 的实际结果应记录在相应执行证据中，不能直接批量改写 91 个包的注册状态。

### 2.2 七条线的工程动作和接受门

| 实现线 | 模块／包 | 当前可以做的具体工作 | 必须另行证明的接受 |
|---|---:|---|---|
| A Foundation | 7／14 | 固定 types、wire、authority、operations、evidence、AuthBus、HeptaBao 合同；完成真实 token／lease／revocation／错误分类和取消所有权；保存有界 wire 与否定控制 | 独立 issuer、真实 credential／scope／epoch／撤销消费，以及服务故障下的实际拒绝；协议 DTO 不授予 authority |
| B Runtime | 11／19 | 收敛 supervisor、fleet、Agentd、Codex、inference control/worker、automation、Matrix、browser、两类 UI 的正常调用者；保 single owner、取消、重启和进程清理 | 精确平台原 CI；真实 Root→Agentd→Core/Session→UI 任务、取消、丢 ACK 与外部效果一致性 |
| C Memory | 9／13 | 完成 SQLite native custody、pool／checkpoint owner 绑定和拒绝 COMMIT 后读可用性；接上 read/retrieval/federation、KG、compact、Prompt registry、context compiler 的一致快照 | 合法 Current 与 exact cut 驱动的三池协调；真实 correction／forget／rollback 跨消费者传播，不能靠离线 receipt verifier 替代 |
| D Objective／Value | 3／7 | 固定 Objective、NDU、runtime control 的确定性基线、候选预算、episode 归因与 effect 前置校验 | 真实 signed objective／FinalUse，任务结果与实际 target effect 关联，错误和未知效果可恢复 |
| E Learning | 4／14 | 形成不可变 episode、operator、eval、artifact 的数据／模型／成本账本；预注册独立比较和所有失败保留 | 独立 holdout、完整成本、未来窗口与实际消费者 reload／rollback；不得把同 fit 多次重放当新拟合 |
| F Adaptive Policy | 5／12 | 对 neuron、intuition、Prompt optimizer、plasticity、intelligence facade 做 bounded shadow；分开 proposer／scorer／selector，保 abstention | 固定总体、预算和强基线下的因果收益；promotion 必须消费独立证据，B18 的 D−B 门仍有效 |
| G Engineering | 1／12 | 按逐路径净 diff 组织源码候选、依赖锁、原测试与可恢复集成；保一个主候选和 donor 来源 | 适用原 CI、完整 main/merge 身份与正式 release／外部 activation 条件；代码生成或静态审查不等于发布接受 |

模块 owner/deputy 和三组依赖以 canonical registry 为准。表中工程工作可并行准备，真实 activation 仍逐个消费前驱，不能把某条线局部通过扩展到整条线。[固定实现线与依赖](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/readiness/READINESS.json)

## 3. B16 的可执行接续：从物理持锁到正常调用者

### 3.1 Foundation 已解决的范围和仍未解决的范围

已执行的基础控制覆盖实际 SQLite 提交否决、连接复用 barrier 的取消、checkpoint exchange 的单调提交联锁、有界 codec，以及注册后的物理连接 custody。最终控制在 commit hook 被移除、native close 尚未开始而连接仍有物理行时，实际竞争排他锁仍被拒绝；相应负控能真实取得该锁并命中原断言。

这不能覆盖注册前 open／初始 PRAGMA 的取消；该缺口属于下一 driver。单调 commit interlock 也不等于每次 COMMIT 重新验证 deadline、authority 或 Current；final live check 与实际提交之间的时间变化、独立 shared-open 实例、跨进程访问和 FinalUse 仍有各自合同。真实 cold-image 的 provided-pool 路径依靠 `query_only`、`SQLITE_DESERIALIZE_READONLY` 与 max-one 物理只读保护，不能被计入没有安装 hook 的 commit-gate 覆盖。[Foundation 与接续范围](CONTINUATION_PROGRESS_V4.zh-CN.md)

### 3.2 冻结原阶段的执行顺序

**内部阶段 ID `B01…B21` 属于 B16 的执行器，不是原 23 项 blocker 编号；`internal_stage_ids_are_not_original_blocker_ids=true`。** 本文统一按 `B16/foundation`、`B16/driver`、`B16/pool`、`B16/checkpoint` 和 `B16/owning` 表述，避免把内部阶段通过误写为原 B15 等 blocker 闭合。

| 阶段 | 当前状态与实际输入 | 下一步原执行 | 合格出口及接续条件 |
|---|---|---|---|
| B16/foundation | **QUALIFIED**；最终 e510；24 个不同阳性／27 次 PASS，9 个不同负控／10 次有效失败，4 恢复 | 不为凑数重跑。保留 352 个原路径、完整日志／JUnit／源守卫和最终 metadata | 仅把其真实终态、最后 metadata 两份守卫和原 HEAD/index/双锁交给 driver；不冒充全工作区或产品 Root 接受 |
| B16/driver | 三次同 key 超时，**UNKNOWN**；原启用请求及完整源码已冻结 | 找到可归属任务后读取原执行；按原包采用 SQLx native lifetime token，真实 Cargo/Bazel 锁生成与校验；12 个正向父用例、3 个负控父用例执行、2 个恢复阶段、原 Bazel 注册目标 | open 前持有真实 token；取消、初始化错误、BUSY close 均按原物理锁 oracle 验证。正常 close 成功后释放；close 失败不能因 panic 展开提前解锁。原 8 个 SQLx 用例和 4 个新控制都实际执行，support child 不另计 PASS |
| B16/pool | **DISABLED**；4 路源码已审；driver 依赖值为空 | 同一负控变体在 state／Memory 两个 package scope 运行 3 次负控，1 次精确恢复，再运行 3 个正向控制 | 两个 pool 构造把实际 owner 的 `Arc` 传入 native token；真实 File／Windows directory custody 连续。保原 owner callback、commit hook 和 collation；运行前绑定 driver 真正生成的后树与双锁 |
| B16/checkpoint | 静态候选；尚未具体运行绑定 | 为独立 `checkpoint_private_recovery_database` 连接传入同一实际 custody；执行 1 项物理负控、恢复后 1 项新控制及原 14 项 recovery；Memory 新 dev-edge 触发第二次真实 Cargo/Bazel 锁门 | 在实际 checkpoint PRAGMA callback 已进入、runtime 保持运行时取消，竞争锁仍被拒绝；释放后观察真正 close 与最终锁释放。原 checkpoint／发布／错误优先／bootstrap ACK 不变 |
| B16/owning | 等前四段实际合格 | 在实际最终源码、锁、metadata、程序身份上跑原 state／Memory 所属完整范围，再按原 recipe 进行 fix/fmt 与差异核查 | 保留全部失败、ignored、早退与重试计数；自动改动逐路径审语义。依原 AGENTS 在最后 hygiene 后不追加测试并重标之前的源 |

driver 使用的原新容量门为 **48,517,479,536 字节**，命令前后保留 8,000,000,000 字节最低余量，开始前重新读取实际空间。它是基于现有程序族和 Cargo/Bazel／证据增长的计划门，不是实测峰值保证。不能沿用旧 Foundation 22 GB 例外，也不能删除已有 cache 或临时降低预算来通过门槛。pool 与后继继续使用各自冻结容量计算、真实 source/metadata/tool/SDK 条件，不凭 Foundation 完成时的剩余空间预报可执行。

原 V7 的 29 个安装对象、25 项 integrity、源码 payload、scope、零重试、物理 oracle 和 finally 保持冻结。负控必须出现规定的真实物理状态和精确原断言，并以普通 `test failure with exit code 101` 结束；timeout、leaked handles、setup 错误、没有用例或未知 XML 终态均不能当有效负控。普通 ignore/support 保留原语义，不改成成功。每次恢复核对所属路径和整树，后继不能使用上个阶段残留的错误变体。[冻结 pool 输入与恢复审查](native/b16-ai395-pool-v7-disabled-v1/README.zh-CN.md)

### 3.3 新 Memory reuse 候选的独立接受

已识别一条 Foundation 原控制未覆盖的源码链：SQLite commit hook 否决 COMMIT 后自动回滚，但 SQLx `Transaction::commit` 提前返回错误，内部 tracked transaction depth 可能仍非零；随后 Drop 排队的 ROLLBACK 因 SQLite 已无事务而失败。ping 完成队列往返，却没有修正这个 depth；复用连接再执行自定义读 BEGIN 可能得到 `InvalidSavePointStatement`。已有 Foundation 提交否决控制使用 raw SQL BEGIN/COMMIT，不经过该 SQLx bookkeeping，原 PASS 仍成立。

候选只修改 `codex-rs/state/src/sqlite.rs` 的两个显式 guarded pool 复用入口，并增加独立测试文件。遇到非零 tracked depth 时丢弃旧连接；coordinated 入口对干净连接继续执行原 owner callback，新连接继续安装原 hook、custody 和 native token。默认 pool、只读入口、SQLx driver、权限规则、Cargo/Bazel 锁均未改。深度检查保护读可用性，不能代替 owner／Current 校验。

接受时必须分别执行两个入口：占住其余四个连接，在第五个物理连接设置 TEMP marker，触发真实 SQLite `531` 提交否决，证明 SQLite autocommit 与 SQLx tracked 状态分离；负控再出现旧 marker 和 `InvalidSavePointStatement`，才允许计入原读取断言失败。修复后须看到旧 marker 消失、读事务可用、未提交数据不可见，同时新连接写入仍以 `531` 被原 gate 拒绝。先完成这两组原生红绿，再做原 state/Memory 回归，作为独立后续批次绑定，不暗改正在处理的冻结 B 请求。[完整候选与范围](candidate-next/b16-refused-commit-pool/README.zh-CN.md)

Donor #4855 的相关修复早于上一观察窗口；本轮新识别的是它与当前冻结源码的具体关系。正文所述 1288 PASS 和红绿结果尚未取得对应完整 native raw，状态 `RAW_NOT_RETRIEVED`。本产品候选的资格必须来自自己的实际执行，不能借 donor 正文计数。

### 3.4 从 R2f1 到 Current、FinalUse 和正常 UI 的最小链

当前 `P0.8D-VERTICAL-SLICE` 与 `INT-2-AGENTD-CODEX-COMPOSITION` 继续作为正常入口主线，agent-runtime 为包 owner，runtime-control 为 deputy。目标是一条真实 UI/API → Objective → bounded Memory/Context → Agentd → 现有 Codex execution → 可观察终态的有限流程。[工作包合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/docs/delivery/WORK_PACKAGES.json)

| 具体接线 | 可立即准备的源码与接口工作 | 必须由真实系统完成的接受 |
|---|---|---|
| 继承 lane → Root checkpoint transport | 先对 R2f1 的 `hepta-agentd/src/lib.rs`、`root_checkpoint_transport.rs` 与测试后像取得原编译／4 控制结果；同步 `from_inherited` 验证和 CLOEXEC custody，进入 I/O-enabled Tokio 后 `into_runtime` 注册；取消／未知 ACK 消耗并关闭 lane | 独立可信 launcher 建立实际 Root 来源、host namespace、UID 0、boot+birth 与 pidfd 身份；真实父死亡／FD 移交／错误 lane 必须拒绝。UDS unit fixture 不是该接受 |
| checkpoint 响应 → 私有合法 Current | 基于已有 codec 实现私有 binder，逐项校验合法 phase、完整 head CAS／继任、lease owner、epoch／generation、期限、撤销、独立 floor 与 exact cut；不提供任意 Receipt→Current 公有捷径 | 独立 authority 提供可验证的当前状态与时间／撤销材料。`decode_against` 的 identity／monotonicity 和 wire/request-ID 相等不构成 authority |
| Current → recovery → 三池 writer | 在实际 state／Memory 两个 pool 和 private recovery checkpoint custody 通过后，绑定同一真实 Current／cut／writer owner，明确共享／排他持锁与取消、关闭、替换顺序；保路径恢复拒绝、Windows retained directory 与 secure sync | 实际 SQLite 的所有受管写路径、已借出事务、替换连接与恢复发布均消费有效 Current；跨独立 shared-open／跨进程不被现有池内门默认为已覆盖 |
| writer → `original_sender` → ACK | 保原 `AgentdProductionHostAttachment<C>`、bootstrap ACK、普通 peer/current-user gate、exact duplicate 的字节比较与独立 ACK；将新协调放在真实 caller，不整体覆盖 donor 文件 | 任务、重复提交、取消、丢 ACK、重启后实际效果与 authority／evidence／Memory 对齐；Queue ACK、工具 ACK 和 terminal effect 分别核验 |
| Objective／FinalUse issuer → effect entry | 接入真实独立 issuer、签名 objective、scope／session／期限／撤销与单次进入；将 runtime frontier 和 generation 漂移拒绝放在实际 effect entry | 由合法外部签发材料和实际 target/provider 验证；本地自行生成一个可解析签名、SSH 权限或 shadow admission 均不授予 FinalUse |
| listener custody → normal UI caller | 明确父目录 UID/GID/mode、原子发布、inode/FD 持有、peer 与匹配 inode cleanup；补真正正常启动 producer、Registry/arg0/helper 查找和 paired Desktop pin；同步 preflight 不创建线程／Tokio，runtime 注册另行执行 | 同源正常 Root→Agentd→Core/Session→UI 路径完成原任务与拒绝、取消、重启、丢 ACK；原独立 UID 0／pidfd lane、真实 effect 和 UI owner 接受不能由临时 socket 或 mock 替代 |

R2f1 的 `SO_PEERCRED` 是建立连接时的凭据，不能证明 FD 后来未被转交；UID/PID 按 namespace 解释，不能只看数值 0 就认定 host Root。ACK 的 `peer_lifetime` 要按原 writer／lease owner 语义验证，不能机械等于 Root server PID。现有可调用 `execution_shadow_admit` 只做 shadow，不启动进程、不授予 FinalUse、不确认 effect；它不是这条正常调用链缺失的 issuer。[R2f1 独立候选](candidate-next/r2f1-root-checkpoint-transport/README.zh-CN.md)

每一小批先给完整依赖与实际 caller，再给可审 diff、原控制和接续守卫；复杂修改拆成可独立验证的连续批次。只把需要真实 Root／独立签发者／provider／目标主机的接受输入列为外部门槛，源码与控制仍继续推进。

## 4. 原 23 项 blocker 的逐项行动与原退出门

以下分类与原 ledger 一致。表中“立即动作”是本轮工程工作；“原退出门／实际接受”保持原范围。已闭合项没有增加新的普遍重跑义务，相关代码变更时才针对受影响合同重新验证。

### 4.1 八项限定范围闭合：维护原合同

| ID／范围 | 分类 | 立即动作 | 原退出门与范围限制 |
|---|---|---|---|
| B01 仓库与证据清单 | `CLOSED_SCOPED` | 保留原完整分页、固定 refs、时间和每次增量；新 donor 只按净变化和相关门评估 | 固定时间、固定 refs、无分页缺口、完整机器可读清单。03:16–03:24 的全量与 12:04 的增量分开，后者不改写全库总数 |
| B03 cwd 展示语义 | `CLOSED_SCOPED` | 在整合时保原 cwd 展示和 canonical 路径语义；仅受影响变更触发原 7 例 | 已满足该原始回归范围；不自动代表整个 Core 或 main 资格通过 |
| B04 认知投影 oracle | `CLOSED_SCOPED` | 保不可变 revision／当前指针、来源、更正、删除与重启断言；新 Memory 候选不改投影协议 | 已满足修复后的原产品目标；生产投影协议保持不变。新的 Current／事务复用资格另行验收 |
| B05 supervisord 子进程定位 | `CLOSED_SCOPED` | 保绝对可执行路径与真实 helper/runfile 解析；后续 RPC 超时按自己的阶段诊断处理 | 已满足原目标的子进程执行断言；不以脚本存在代替真实启动。RPC 或平台失败不能继承本项闭合 |
| B06 正向私有路径夹具 | `CLOSED_SCOPED` | 保实际权限前置与原负控，按适用平台记录；TUI 修复继续归 B22 | 原 macOS／Windows 对应正向用例通过，原负控维持通过；不改称逐 case 7/7 或零 skip/retry，Unix-only 在 Windows 仍为不适用 |
| B12 Windows 私有目录冻结对照 | `CLOSED_SCOPED` | 保存原两正向、两反事实和干净恢复；补充 5b 同 head 的祖先替换／junction 两个具名成功 | 不改生产代码和攻击断言；正向 2/2、两负控各精确 1 fail + 1 pass、真实文件系统观察和干净恢复成立。不能外推 B11 删除隔离 |
| B14 Windows exec 恢复清理开销 | `CLOSED_SCOPED` | 保真实 helper 与原业务／清理断言；最新整体平台资格交 B15 | 保持原 90 秒限制，解决真实临时 runtime 开销；原 source 与 merge 的 13 例全部通过。既有 121 rollout／254 exec 另按原范围记录 |
| B17 #4578 缺失确认终稿 | `CLOSED_SCOPED` | 保固定终稿、冻结源、全部失败与成本未知；后续研究使用新的预注册输入 | 缺失报告与结果失真问题已完成；原研究分支全部工程 CI、科学采用门槛不因此闭合。不得重训已暴露确认集来追求绿色 |

### 4.2 十二项开放的平台与运行合同

| ID／范围 | 分类 | 立即工程动作 | 原退出门／真正系统验收 |
|---|---|---|---|
| B02 单一整合候选 | `OPEN` | 保 PR #4797 为主候选；逐路径决定保留／合入／延期，保 Guardian 取消／截止和 runtime-scoped Git cache；候选和证据分清 | manifest、vendor、Cargo/Bazel 锁同步；固定 head、目标 base、实际 merge tree；原必需 CI 全部通过。不得从多分支局部绿拼成当前产品绿 |
| B07 Hook 元数据与工具可见性 | `OPEN` | 在 5b 原结果中逐名核 binding、Hook executor、MCP、TokenBudget；保 active／idle fixture 的请求数、顺序及真实工具输出 | 原正常用例通过；未配置 server、allow/deny list、环境错配、陈旧目录负控都拒绝。源码／局部 native 成功不能代替原平台范围 |
| B08 私有 attempted tool 元数据 | `OPEN` | 对齐实际 prompt 的 retained calls、真实 output 和 exact calls；核 namespaced replay、非官方 wire 无私有字段，保生产持久化 | 原 exact calls 与 wire／retained 合同同源通过。新 Windows Core 分片已见的 3 个 PASS 只是子范围，仍需其余原名字和平台，不借 B09/B10 数量 |
| B09 终态清理与恢复 | `OPEN` | 保 busy／lineage／exact instance／fence；核注入、idle-steer、suspension、8 个 turn_recover 和特性负控；归档新 Windows 9 个具名 PASS | 原 panic/cancel/watchdog 与恢复负控实际通过。新 Core 日志链失败按 B15 处理，隔离通过或同一测试多份 wrapper 输出不能扩张本项 |
| B10 WebSocket／prewarm／compact | `OPEN` | 以真实并发握手、EOF、身份变化和工具结果核新 fixture；按已审含义记录 stable 的 1 次无工具 prewarm＋3 次 turn | 原连接／请求／工具／模型／工作区合同及身份拒绝、重连边界通过。已审请求 oracle 修正逐项说明，不声称全部原计数／断言字节不变，更不放宽生产身份 |
| B11 Windows 原生 sandbox/helper | `OPEN` | 围绕实际父 `DELETE_CHILD` 缺口设计最小能力／对象生命周期接口，核原 broad ACE 与 `WRITE_RESTRICTED`；保 public query、strict token、合法 read/write 和物理四格 | 原生 helper 与原严格 token 契约，原攻击／权限／文件系统用例全部通过。若方案需要新的路径授权或 label 生命周期，要把具体变更交审；不存在恢复出的永久禁令，也不能擅改系统 ACL 来代替产品实现 |
| B13 Lease／Queue 时序夹具 | `OPEN` | 利用已修复的成功日志保留链，取得本 head 原名字正文；保已有因果负控，不延长时间以掩盖错误 | 原过期、quarantine、guardian、release=0、单发送及重启不重放断言在原平台通过。Mac Bash3.2 下 57 控制通过证明日志链修复，不能替代 Queue/Lease |
| B15 最终 CI 与 main | `OPEN` | 先处理新 Windows Core 原失败并收齐**原任务全部真实终态**；随 workflow 展开核完整 job 集合，不固定为 44；逐项维护 142 个原退出名字和平台来源，保历史失败与 25 早退 | 最新候选所有必需 workflow 终态成功；重新核实目标 main；实际合成 merge 与发布树一致。main 曾为祖先不等于 main 目标 CI 通过，当前排队／取消原因仍需权威证据 |
| B20 远程控制握手夹具 | `OPEN` | 保真实 HTTP／WebSocket 握手、EOF 与连接关闭；取得同源原 19 例完整结果；保确定性旧源反例 | 旧源实际同握手错误、新源对照及原 AppServer 关闭／断连断言都通过。c6 原 App 断连成功、三父存活反例仅是局部，capability 早退不计行为执行 |
| B21 macOS Intel PTY | `OPEN` | 分析 5b 会话内只读诊断，先区分 reader／channel／子进程等待与 EOF；按原 portable 路径定位剩余 4 MiB 输出阻塞 | 原 Intel 30 例及相关 CI 通过，保持完整 drain、child 退出、FD、原 2 秒／5 秒预算，并解释实际 drain 原因。新 collector 第 31 例成功不替代原失败；不加 sleep／retry 或仅吞掉退出码 |
| B22 TUI 中断与退出顺序 | `OPEN` | 对真实 turn／interrupt／shutdown、stdout-ready 和 canonical cwd 逐例取证；使用当前成功日志 collector 保存正文 | 原用例、有效负控和原 Windows CI；原 5 秒与关闭顺序断言不变。非缓存 target PASS 仍不能补造内部未展示的成功名字 |
| B23 App Server Unix 信号生命周期 | `OPEN` | 保原丢信号窗口、首信号注册、stdio／disabled 行为与 drain 清理；收同最终 source 原 Unix 结果 | 真实 baseline 丢信号成立；修后 3 个单信号父例和 2 个原 drain 通过，配置／平台语义与最终原 CI 验收齐全；其余 App 成功不混入该计数 |

新 Windows Core 的正常分片与冻结 142 个原退出名字实际交集为 12 个 PASS：B08 三个、B09 九个。它们应补入对应精确范围，其余 130 个名字没有因此取得本任务资格。业务库 118、retained 532 等通过也必须按自己的名字、head/base-merge、原 skip 分开记录。[新 Core 原结果与逐名交集](CONTINUATION_PROGRESS_V4.zh-CN.md#新增的-core-实际失败与最小修复候选)

### 4.3 正常产品、科学采用与外部接受

| ID／范围 | 分类 | 立即工程动作 | 原退出门／必须真实取得的输入 |
|---|---|---|---|
| B16 可信产品入口及外部效果 | `OPEN` | 按第 3 节完成 driver／pool／checkpoint／owning，再验证独立 reuse 和 R2f1，继续 Current、issuer、listener 与 normal UI caller 的小闭包 | 先完整迁移并验收 Root handoff、Registry/arg0、protected checkpoint/verifier、FinalUse/issuer、listener custody 和一个真实正常 UI caller；再由同源实际 Root/Session、原 signed objective、provider/target 完成任务／取消／丢 ACK／重启，并保物理效果、authority、evidence、Memory 一致性 |
| B18 解析核心／参数记忆采用 | `SCIENTIFIC_HOLD` | 冻结新的 2×2 比较、独立数据和拟合单位，明确 D−B 主比较、成本和全失败记录；可继续验证有限 J 规划组件 | 独立数据、充分精度、全部失败尝试与完整成本；原 D−B 采用门通过才提升声明，未过则保强普通默认。工程构建或 J−C 收益不能换名关闭 D−B |
| B19 Bao／Chain／HIA | `OPEN` | 分别固定版本／接口／权限／故障合同，写可执行的独立 consumer 接受包；继续补仓库内 adapter 和拒绝控制 | 外部固定版本、兼容／故障／安全回执，以及本产品真实调用者的独立接受。签名、epoch、撤销、实际服务／网络／目标与证书不能由本地 fixture 生成自证 |

本节 23 行分类合计恰为 8／14／1。B11 目前的证据证明现有 token-only 接口尚无已经验证的最小合格修复，不能推出 Windows 全局不可能实现。MIC 或其他机制可能要求显式根路径、对象 label／权限与生命周期；必须先给实际合同和最小改动，再验合法读写与外部删除拒绝。label-only 查询／设置权限也应按真实 API 区分，不能笼统归为管理员或整个 SACL 权限。[Windows 机制独审](reviews/b11-token-interface-independent/REVIEW.zh-CN.md)

## 5. P0–P8 路线的具体交付与接受

### P0：可复现的跨平台产品基线

**近期交付：** 固定当前候选及后续必要修复，完成新 Windows Core `owned-child-v2` 的静态审查，再取得原生验证；已否决的六行 Dispatch 方案不作为修复推进。取得原 Windows、macOS Intel、ARM、Linux 适用目标的完整输出，将原失败、有效负控、skip／早退、缓存、额外 attempt 与未知逐项对齐。已完成的 Bash 空数组兼容、musl canonical label 去重、V8 staged `--no-default-features`、格式与证据扫描边界修复按实际源和原门验收，不能把 CI 配置修复说成其产品目标已执行通过。

**接受：** 原 B02/B15 的固定 head/base/merge、required workflow 终态、源码和锁文件一致性成立。已有 main 祖先关系不是 main 集成结果；在相应实际门通过前继续保持 Draft。对于 CI 排队与取消，只读调查的可见窗口、workflow group 和运行元数据可限定排除，不能据静态配置推断取消者或全局原因。

### P1：一条正常可用的垂直流程

**近期交付：** 以第 3.4 节为顺序，先让 transport、Current/recovery/writer、issuer/FinalUse 与 listener 的输入输出和 owner 可编译、可审，再接一个实际正常 UI caller；固定对应 Desktop／服务 pin。选择有限业务流程，明确 request、turn、result、approval、cancel、reconciliation 和 terminal effect 的关联，不依赖测试专用入口。

**接受：** 真实独立 Root/Session、signed objective、provider/target 与 UI owner 执行成功和拒绝；覆盖取消、丢 ACK、撤销、进程重启、重复提交和 rollback。独立权威材料未到时可继续源码和控制，但任何本地 receipt、shadow tool 或操作系统管理员权限都不能自行补成 Current/FinalUse。

### P2：共享计算与可靠数据

**近期交付：** 沿 `INFER-V4-T1…T5` 和 Memory store/read/retrieval，交付共享 Encoder/Cell/worker、有限队列、sparse microbatch、单一事实所有者及一致的 snapshot/source/forget frontier。实现实际 caller 的 intent/outbox/dedupe/ACK/reconciliation，测量资源，保出错后的恢复路径。B16 的连接与锁所有权是这一步的运行基础，不能用协议文档取代。

**接受：** 实际运行 64／256／1024／4096 logical Cells，同时报告 active concurrency、CPU/RSS、p50/p95/p99、queue age、token、质量和完整成本；配置数量不当作实际容量。每个 durable domain 的 authoritative writer 明确；更正／删除／遗忘传播到 reader、KG/index、compact/federation 与 artifacts。#4817、#4847 的离线 verifier 或未连接 production Control 的 kernel 只能作为组件资料，不能替代这些 native 与消费者接受。

### P3：固定预算的 shadow 比较

**近期交付：** 预先固定候选总体、输入、预算、deterministic／strong-retrieval baseline；将真实 local model、Neuron、Intuition、Prompt 和 Bellman/NDU 候选分开记录。保 proposer／scorer／selector 边界；不可用、拒答、OOD 和负例留在原总体，不事后删样本。

**接受：** 分别报告生成质量、Reader 容量、retrieval utility、citation entailment、参数学习收益和成本。相同模型拟合下的多个世界／多个重放不当成独立拟合；候选输出不能直接写入当前 authority 或授予 effect。

### P4：首个只读因果学习闭环

**近期交付：** 完成 `C1-PROMPTED-MEMORY-RETRIEVAL-RANK` 的正常调用链：request/Objective receipt、bounded retrieval、NDU/Prompt portfolio/timing、Context receipt、outcome/correction/attribution、下一 snapshot shadow candidate。保当前 run 的 Objective/artifact 不可变，以及原 C1 的 zero Memory/KG/tool/provider-effect 合同。事前列 no prompt、单 factor、pairs、full portfolio、fixed timing、learned timing 消融。

**接受：** 固定总体和预算下的任务／检索收益、引用准确、陈旧与冲突拒绝、abstention、calibration/OOD、延迟和总成本可复核。#4823 的已有独立原件支持有限 J−C 规划收益，15 个权重编辑候选被 VAL 拒绝并恢复 C；这不证明权重编辑等效或原 D−B 通过。CPU 完整成本、未暴露分布和独立 future window 仍需补齐，B18 保持 HOLD。[科学采用原条件](continuation-blocker-progress-v3.json)

### P5：长期学习、回滚与不可复活

**近期交付：** 沿 `ART-2`、`LONG-1…3` 设计 next-snapshot reload、predecessor rollback、delayed outcome、retention/forgetting 和 unlearning non-resurrection；固定时间来源、签名输入、模型／规则／状态版本。列出未来日历窗口、采集 owner 和下一次采集动作，让真正等待时间的部分可跟踪。

**接受：** 真实未来窗口到达后取得独立评价；Memory、KG/index、Prompt、compact、federation、缓存和 signed artifacts 的实际消费者都验证删除／撤销不可复活。离线重放和已有确认集的反复调参不能替代未来窗口或独立数据。

### P6：可塑性与工程自迭代

**近期交付：** 分别实现 eligibility/homeostasis、replay、world-model、PromptFactor evolution、参数可塑性和受限源码候选的 shadow 接口；把训练、候选选择、promotion、release 的输入和撤回条件写清。结构 Cell Split、topology canary 先做可回滚的小闭包。

**接受：** 每次结构或源码 promotion 消费独立性能／安全／成本证据和明确授权；不让同一优化器既提出候选又自批生产。原强普通默认在科学门未过时保持，失败和回滚按原 ledger 留存。

### P7：具身与物理目标

**近期交付：** 完成 sensor/body/reflex/actuation 类型、确定性控制与终态 reconciliation，在 simulator/HIL 明确动作界限、故障与 emergency stop。先修仓库内接口和故障处理，再交可执行的目标接受包。

**接受：** 实际 target-host 的时序、物理安全范围、紧急停止、失联、重启和恢复由真实硬件/操作者验证；simulator/HIL 通过不代表实际物理系统已具备安全资格。实际动作须沿已有 activation 与目标 owner 合同。

### P8：外部系统吸收与兼容

**近期交付：** 在 owner 授权的非特权 Debian/POSIX fixture 完成只读 discovery、manifest／contract、无凭据 sandbox 和可回滚迁移；分别制作 Bao、Chain、HIA 的版本与消费者测试包。记录实际网络、证书、目标和故障恢复所需输入。

**接受：** 显式 host enrollment、真实 owner consent、本产品独立 consumer 和必要服务／网络／证书验收齐全。Bao 要覆盖 policy/auth/lease/revoke/rotation/deny；Chain 要按原合同取得实际网络／指标／消费者结果；HIA 要区分独立构建、运行契约与签发方、scope、epoch、撤销、实际消费者。`advisory DENY_ALL` 与 `safety_certificate=false` 在真实接受前保持，operator／adapter fixture 通过不能替代 B19。

## 6. 哪些工作现在能推进，哪些确实需要外部输入

| 边界 | 仓库内应先完成的工程工作 | 真正待取得的材料或运行 | 未取得时的准确状态 |
|---|---|---|---|
| provider 启动 | 保存精确请求、same-key 协调和可归属原件；后继保持 disabled | 当前 driver 请求的权威 job 身份／状态／完整输出 | `START_OUTCOME_UNKNOWN`；不是测试失败，也不虚报零用例 |
| 原平台 | 修具体源问题、冻结原测试与诊断、准备完整 source/merge 绑定 | 原生 Windows／macOS Intel 等适用执行；没有 Intel 时等待原 hosted 目标 | 平台资格 OPEN；Linux/ARM 成功分别保留 |
| Current／issuer | 实现真实 caller、私有构造和拒绝控制，保 custody、cancel、revocation 语义 | 可信独立 Root／issuer、实际 signed objective、scope/generation/floor、当前 authority 材料 | 源码或有限执行可成立，正式 Current/FinalUse 接受 OPEN |
| 外部 effect／UI | 完成 normal producer、Registry、listener 与 paired UI 接线 | 同源真实 provider/target、UI owner、任务／取消／丢 ACK／重启回执 | B16 OPEN；不以 mock／shadow effect 代替 |
| 科学采用 | 事前冻结设计、数据分割、成本和全部失败，保强普通基线 | 新独立数据、真实未来窗口、充分精度的 D−B 与完整成本 | B18 `SCIENTIFIC_HOLD`；不是待通过的 lint 缺陷 |
| Bao／Chain／HIA／具身 | 固定接口、版本、安全／故障合同和接受脚本 | 实际服务、网络、签发材料、硬件和独立 consumer 接受 | B19 及相应 activation 门 OPEN，不批量称外部全部完成 |

系统性前提不能凭文字补齐，能做的工程也不因最终接受未到而停止。每个开放项都应留下一个可审源码或明确的下一执行输入，而不是只写“待外部”。

## 7. 集成、donor 与证据维护规则

**同一主候选持续收敛。** donor 的 head/base、完整净 diff、caller 和依赖闭包先固定；只迁入可审的小批次，保持当前 `original_sender`、普通 peer/current-user、Windows 权限与原身份隔离。#4812 的 FinalUse/frontier、#4869 的 Current 接线、#4871 的编译修补等有各自源和资格，不能直接拼接为当前 B16、B11 或 Intel 的接受结果。新增 Memory 风险已转成自己的两入口候选，其 donor raw 缺口仍明确保留。

**库存有明确观察窗口。** 原完整库存是 03:16–03:24 UTC 的 1103 open PR、5193 branches；分页及非原子观察限制保持。10:14／10:26 的 45 个新 Draft 增量和 12:04:06–12:04:43 的两页 60 条 API、13 项更新／4 个新 PR 分别冻结。它们都不是新的全库总数。只对能缩小当前开放门的变更继续读真实源码与运行证据，不以分支数量衡量进度。[本轮增量原件清单](generated-evidence/pr-increment-20261105T1204/api-freeze-manifest.json)

**每个批次交付一个可复核结果。** 内容包括前后源码与锁、真实 caller 和 owner、依赖前驱、原用例／负控／平台、实际程序和 helper 身份、原输出、恢复或 reconciliation、剩余接受材料。source、build-only、exact testcase、target、cache、retry、ignored、early return、unknown 分层记录；同名 wrapper 重印不计第二次执行。Windows 工作树 CRLF 与 Git LF 的精确换行对应另列，不将树相同写成工作树字节相同。

**新发现不静默改冻结批次。** 新 Core 候选、Memory reuse 与 R2f1 分别有自己的前后像和运行门。若原 owning gate 暴露新问题，保留原 FAIL，再做必要修复、重新具体绑定和接受；不在原运行器中改变选中名单、timeout、skip 或负控谓词。driver/pool/checkpoint 的实际源码和生成锁未到齐时，未来字段保持空缺。

## 8. 固定来源与审查入口

下表列出本计划关键结论的固定依据。Git blob 是已实际保存并回读的审计对象；对象存在不表示其中候选已经执行。完整原始失败、旧版本和当前快照均继续保留。

| 来源／用途 | 固定 Git blob 或仓库内审查入口 |
|---|---|
| Canonical DEVELOPMENT | `9ff53000ff301289d87c364eb45a938755a0f11e` |
| Canonical MODULES | `2571766d45a0a6b0db0ec83e675c70609d3bc39d` |
| Canonical WORK_PACKAGES | `77568a3965c4c68357b2e16f6af10309209b35dd` |
| Canonical READINESS | `2b56ff94aad7e6a0e19b0c2a600a2c3cd3616729` |
| Canonical GAPS | `aa01454cf24a60b8f0c61a8440d5177dced8d7a0` |
| 原 23 项状态和原退出条件 | [continuation-blocker-progress-v3.json](continuation-blocker-progress-v3.json)；[第四批原 ledger](../current-blockers.json) |
| 当前产品／Foundation／driver 的完整进度 | [CONTINUATION_PROGRESS_V4.zh-CN.md](CONTINUATION_PROGRESS_V4.zh-CN.md)；本计划 CI 固定截点为 12:40:31，后续观察另列 |
| snapshot0039／0040 与 owner-local 原件 | [固定快照汇总](generated-evidence/ci-5b633-owner-local-and-snapshot0040-v5/snapshot-summary.json)／[217 例原退出映射](generated-evidence/ci-5b633-owner-local-and-snapshot0040-v5/original-case-review.json)；0040 是 19 workflow／44 job 的时点集合，不能作为最终 job 总数 |
| Foundation 全阶段根审 | `c9da4defd63c6c63b22fdf731c37fa91a201f4c4`；最终原 metadata SHA-256 `b4090db792babde64575b11e7ae04df8245074b96a154048c4de08691e4a23e0` |
| 实际 Foundation → driver 接续根审／独审 | `819bdbcfd1fc1494b3718eea891f4bb490dbdd72`／`765e0e5194c72c9b44f1de052082cef2ff36b644` |
| 冻结 V7 runtime integrity／源码 payload | `18f27fbb488777d621b4f37aa0cf70956cdbe7d9`／`64db580beabe2642eb8611184dac4fc686fe34e1` |
| Pool disabled 模板 manifest／独审 | `14d8f092ec7aa9b59ed8f2e887cea178d4670fba`／`e242867a7961b597c292ecbc563b051d2bb64268` |
| R2f1 manifest V2／完整 patch／独审 | `16e4c8e5ad178afe7e3351dbf7c3f5f99abd50c1`／`00e997f3ab4c1f5858121041ed1088adfd1f7a2c`／`e406fcf2eb7dc21491d98bab08c00fd28809bb7c` |
| Memory reuse manifest／完整 patch／源码因果审查 | `28a0ccb97b740c6d18561c9bf2d63616db881189`／`6e0a36957f6f2976a06f3c91a968a33213a31b2d`／`d8dee4156ecedcc2a652dfd3e0e9ff292f74a1e7`；独审 `f40037c9d91a6d5625b83750294db2d000823697`，仍待原生执行 |
| Windows 删除机制作者审查／独审 | `2f7ad7fb25f5deb09a4ddb52de3937da4020ceb2`／`846d2358f4f32b3291f0286809fd052414df1fd2` |
| 新 Windows Core 原件／fixture 状态 | [原 job 独审](generated-evidence/ci-5b633-windows-core-lifecycle-v5/original-terminal-review.json)；六行方案已否决，`owned-child-v2` 已写成新增 80 行，静审中、未运行；当前进度正文保留两者区别 |
| 12:04 有界 PR 增量 | manifest `9d1155c873a31c28e0c6faa654c9e3a9d441b8d7`；原件 map `c4cca93e1f038510aa762dd43d2ba020148dee10` |

本计划的下一次更新应由实际 driver 身份／终态、新 Core 原生结果、原平台 CI 或独立接受材料驱动。没有新证据时保持当前分类和不确定性；有新结果时只提高被真实覆盖的范围。
