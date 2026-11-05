# Foundation 完整资格、driver 接续与当前阻塞

本报告接续已经发布的第四次续审快照 `be6eddc503d909181ea195612c293f115d0447ea`。**原 23 项仍为 8 项限定范围闭合、14 项开放、1 项科学 HOLD。Foundation 的原定范围已经取得实际原生资格；driver 已形成具体、已授权的执行请求，但启动结果尚未知。不能宣布 B16、最终候选或全部 blocker 闭合。**

产品仍是 [Draft PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)，固定 head `5b6331250ff459033bd44d1a95daec70131277cc`、tree `b26598d0d97d8d51e723bb5582137315f2174d35`、base `63652be658ebed8d3052eb789b951793384fd5e4`，已观测的合成 merge 为 `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff`。本证据提交不修改产品源文件、产品 ref、base 或 main。

## 1. Foundation 取得了什么资格

实际 ai395 任务 `1a1ab493f2b-fc05-4bfe` 于 **2026-11-05 11:26:45 UTC** 完成。原运行器和原启动器均退出 0；完整 epoch 终态为 `QUALIFIED`、`error=null`、`final_guard=true`；启动器的外部 SDK 守卫也没有错误。最终源码树为 `e510f685d2aa7b9a7121a78f96af3569919e6f88`。

根审从完整原日志、新生成的 JUnit、选择清单、程序身份、源码守卫与 finally 回执独立复核了全部十个阶段：

| 原阶段 | 正向执行 | 有效负控执行 | 实际观察与恢复 |
|---|---:|---:|---|
| R2c V3 | 4 PASS | — | 原 SQLite 提交边界控制 |
| R2d 反事实与修复 | 5 PASS | 1 FAIL | 反事实进入真实 SQLite callback 后看到 `query_only=0`、`busy_timeout=7`；修复后恢复为 `1`、`5000`；finally 精确恢复 |
| R2e1 提交联锁 | 4 PASS | 4 FAIL | 基线实际提交成功，触发原断言；修复后实际 `commit_succeeded=false`、SQLite 码 `531`；finally 精确恢复 |
| R2e2a codec | 3 PASS | — | 有界帧、原 opaque token、完整 head 与错误绑定拒绝 |
| R2e2b codec 扩展 | 7 PASS | — | 其中 3 例是规定重复执行；不能算 10 个不同 codec 用例 |
| R2e3 custody 基线 | — | 4 FAIL | 实际原生连接仍有物理行，但竞争进程取得排他锁；原物理断言失败，随后精确恢复 |
| R2e3 anchor 反事实 | — | 1 FAIL | 实际移除 commit hook、native close 尚未开始后，竞争进程错误取得排他锁；原断言失败，随后精确恢复 |
| R2e3 最终实现 | 4 PASS | — | 连接仍活着时排他锁持续被保留；取消关闭的路径真实进入 checkpoint 与 SQLite 提交否决 |

合计为 **24 个不同正向用例、27 次规定正向执行；9 个不同负控用例、10 次规定负控执行；4 次精确 finally 恢复**。两类名字可能重合，不能相加成 33 个独立产品用例。全部规定执行为 0 重试。负控的真实失败是因果证据，不是产品正向 PASS。

完整终态记录了 43 条原命令：39 条退出 0，4 条负控测试命令退出 100。每个负控失败都已核对原物理观察先于原断言，且不是 setup、超时或无用例所造成。原运行器正是在这些负控和恢复全部有效后才给出整体 `QUALIFIED`。

最后四例尤其覆盖了容易遗漏的生命周期：Rust 上层对象结束、pool 关闭或 commit hook 被移除时，SQLite 原生连接仍可能存在。锁和 custody 必须跟随原生连接保留到实际关闭。最终原始记录显示，在 `commit_hook_removed=true`、`native_close_started=false` 时，竞争排他锁仍为 `false`。这项结果建立在真实 SQLite 连接和文件锁观察上。

原始阶段 ID 中的 B01–B10 是 **B16 内部执行阶段**，不是原 23 项 blocker 的编号。

### 源码、依赖与执行环境

普通 HEAD 仍为 `20fd174ded4e5ce01bda34e4f6d1d74803301f49`；普通 Git index 为原 1,224,180 字节、SHA-256 `6b39b6b27d164001c9b130487d0d7879be5f80e22a4579d06fd472c2bb8d7ac0`。两份原锁文件保持不变。阶段源码变化由原私有 index 守卫和原 payload 逐项约束，不能把普通 HEAD 不变误读为 B 阶段没有源码变化。

最终完整、无 `-p` 的 `cargo metadata --format-version=1 --locked` 原输出为 **8,296,096 字节**，SHA-256 `b4090db792babde64575b11e7ae04df8245074b96a154048c4de08691e4a23e0`。它来自实际最终树，保留 193 个 workspace 成员和 1,501 个解析节点。根审与独立审查分别重建完整原字节，并比较完整依赖图。原 metadata 前、后两份整树守卫及最终守卫均匹配 `e510f685…`、原 HEAD/index/双锁。

OpenSSL、libcap、V8 和全部 8 项工具的原始前后记录逐字身份一致；四份末态原件已实际回收。最后记录的剩余空间为 **656,695,242,752 字节**，这是 Foundation 完成时的观测，不能代替下一次启动时的新测量。

**范围说明：Foundation 每阶段 catalog 保留原 `-E` 选择表达式、没有 `-p`，因此保持完整 workspace 特性解析与原程序布局；它不是重新执行或重新列出全部 19,563 个原用例的无过滤资格。** P4 的无过滤完整 catalog 属于之前的构建前置证据，且该前置没有执行测试。此前文案中“原全目录准备”应按这一明确范围理解。

可复核材料：[全部阶段根审](reviews/foundation-phase-review-through-10.json)、[阶段复核程序](reviews/verify_foundation_phases.py)、[完整终态原件包](native/b16-ai395-foundation-v7-v2/terminal-priority-bundle.json)、[最终 metadata 无损原件](native/b16-ai395-foundation-v7-v2/final-metadata-original/manifest.json)。B01 的完整原件在前次快照已登记，B02–B10 在本次分别登记。

随后全部原件已完整回收：**352 个原路径、110,290,778 字节**，其中相同内容仅在传输中去重为 328 个不同内容、26,803,647 字节。加上完整外层任务 stdout/stderr、状态和复核材料，共 341 个内容对象，分装为 8 个小于连接器单对象上限的无损归档。根审从所有分片独立做严格 base64 解码、gzip CRC、完整 SHA-256/Git 身份和逐原路径覆盖核验；341 对象、352 原路径及全部 116 份整树守卫通过。归档没有删改任何原命令或原始文件，也不增加测试执行次数。见 [完整归档](native/b16-ai395-foundation-v7-v2/complete-archive/archive-manifest.json) 与 [根审重建记录](reviews/foundation-complete-archive-root-review.json)。

## 2. Driver 接续已经具体化，启动状态仍未知

下一阶段继续使用原冻结 V7 的 29 个安装对象、25 项 integrity 清单及全部原 scope、oracle、finally、预算和 ignored/support 语义。它会真实采用已审查的 SQLx driver 源码，由原 Cargo 与 Bazel 命令生成并校验锁文件，而不是手写锁文件或预填未来源码树。

已固定的原范围包括 12 个正向父用例、3 个负控父用例执行、2 个负控恢复阶段，以及原 Bazel 注册目标。`owned_scenario` 是单独的原支持 helper，不混入 12 个父用例，也不把原 ignored 状态改成通过。

具体 binding 已绑定 Foundation 实际终态、原 enabled binding、原 launcher 终态、最终 metadata 原字节及原前后两份守卫。根审和第二位审查者均已通过。启用只改变 5 个授权/状态字段；原 launcher、安装包、源码 payload、测试名和断言全部未变。

启动仍须现场验证 **48,517,479,536 字节**的容量门槛，逐原命令保留 8 GB 最低余量。该数来自实际 P4 程序族大小，加上 Cargo、Bazel、证据增长和余量预算；它是计划门槛，不是编译峰值保证。Foundation 的 22 GB 特例没有延用到 driver。

原唯一操作键为 `hepta-ai395-b16-driver-v7-20261105-v1`，原请求为 938,052 字节，SHA-256 `5f2fe280d8e4fb6aa54d751cc6475060d238b18638b4b6efe4be9a5d7e7152d2`，原超时配置 21,600 秒。

第一次 `process_start` 和随后同一操作键、同一 host/argv/cwd/stdin/timeout 的协调调用均返回 MCP request timeout，未取得任务编号。两次响应完整保留。11:48:42 UTC 后验只读检查仍未找到该 owned installation；完整 durable inventory 不提供 key/fingerprint，不能凭几个时间相近的 ID 推断归属，也没有读取那些无法归属任务的 stdout。

一次限定的 host health 返回 SSH 已认证、可达、healthy，往返约 514 ms。随后通过文档支持的后台只读接口取得已知 Foundation 任务的完整权威 `process_status` 原响应，确认该旧任务 succeeded/0、output_complete=true。在这一新证据下，又使用完全相同 key 和请求协调一次，第三次调用仍返回 MCP request timeout、无 driver 任务编号。三次原响应及每次后验都保留；随后停止启动协调。**SSH 与旧任务只读 API 可用，不证明 driver 的 process_start 已启动、未启动或失败。driver 当前必须记为 `START_OUTCOME_UNKNOWN`，不能记为原生 FAIL、0 用例、PASS 或已完成。** 没有创建新操作键，也没有通过不同入口重复启动相同编译。

具体材料：[driver 输入审查](reviews/b16-driver-exact-inputs/REVIEW.zh-CN.md)、[根审接续记录](reviews/driver-actual-foundation-root-review.json)、[独立接续审查](reviews/driver-actual-foundation-independent-review.json)、[精确执行记录](native/b16-ai395-driver-v7-v1/root-execution-guard.json)、[请求完整原字节](native/b16-ai395-driver-v7-v1/launch-request-originals/manifest.json)、[前两次不确定响应原件](native/b16-ai395-driver-v7-v1/provider-indeterminate-start-bundle-v1.json)、[三次调用与新只读证据](native/b16-ai395-driver-v7-v1/provider-indeterminate-start-bundle-v2.json)。本任务执行记录不授予产品 Root、Current 或 FinalUse 权限。

Pool 的 disabled 模板也已完成：原范围实际为 1 个负控源码变体、2 个 package scope、3 次负控执行、1 次 finally 恢复，再运行 3 个正向控制。模板的 driver 后树、两锁、metadata 和终态引用全部保持 null；它不把工具超时冒认为 driver 已完成，也不错误要求 driver 的初态等于旧 A 树或生成前后两锁相等。模板只准备接续条件，没有启动 pool。

## 3. 正常 Root checkpoint 接线的下一份具体代码

R2f1 已形成 3 路源码候选，共 386 行新增、0 行删除：生产 transport、4 项真实 UDS/pidfd 控制、lib 的 8 行注册与导出。完整 patch 在隔离的真实 Git 目录执行 apply check、实际 apply、逆向 check，三个后像逐字匹配；第二位审查者又独立完成重建和回读。

生产入口消费继承的原 socket 与 pidfd，恢复 CLOEXEC，检查固定 UID 0、PID、boot ID、启动 tick 和 pidfd 活性；进入正常 I/O-enabled Tokio 后才注册原连接。交换函数在首个 await 前取走连接，取消、超时或不确定回复会关闭该 lane，不能自动重连后把先前的未知结果当作成功。编解码沿用已经验证的冻结 codec，并保留 ACK 原字节。

这份候选目前是 **STATIC PASS，尚未 Rust 编译或原生执行**。它返回经过请求绑定的线级响应，不含 `Receipt → Current` 构造捷径。四项 UDS/pidfd 控制也没有借用 Foundation 的通过数。

必须保留的设计边界包括：SO_PEERCRED 是建立连接时的凭据，不能证明 FD 后来从未被转交；UID/PID 受调用方 namespace 解释，原 host namespace 与 Root 来源必须由可信启动链另外证明。ACK 中的 `peer_lifetime` 还须由未来 binder 按 writer/lease owner 语义核验，不能机械当作 Root server PID。真正的 live authority、合法 Current、exact cut、三池协调以及独立 Root/issuer 接受仍然开放。

完整候选与说明见 [R2f1](candidate-next/r2f1-root-checkpoint-transport/README.zh-CN.md)。它作为明确未取得原生资格的候选保存在审计目录，没有作为生产源文件并入产品分支。

## 4. Windows 删除隔离缺口没有被掩盖

第二次独立机制审查核对了 15 份源材料、完整原 Windows 日志及官方接口说明。原实际运行的 token 允许外部 read，拒绝外部 overwrite/create，却实际删除了外部文件和目录。同一个 descriptor 上，目标的 DELETE 被拒绝，而父目录的 DELETE_CHILD 被允许。这是实际文件系统边界缺口。

该历史运行使用的生产 token 字节与当前候选对应实现一致；运行树、测试文件和时间则明确不同。因此可以说它揭示当前实现仍需解决的机制问题，不能冒称它是当前 `5b633…` 新 CI 的原生结果。

去掉 WRITE_RESTRICTED 的控制在 AccessCheck 层也拒绝了外部 read；没有该替代 token 的物理 I/O 对照，不能宣称替代方案满足原读写合同。返回 blanket Err、把相同 token 换一条 elevated 路由、仅改变默认 DACL 或补诊断，都不构成原严格功能合同的修复。

现有 token-only 构造接口没有读写路径、对象权限及其生命周期输入，尚未证明存在可同时保留原功能和删除隔离的最小补丁。这里没有断言 Windows 所有机制都不可能实现，也没有把 MIC 或其他机制未经验证就排除。下一方案须明确读/写能力、可信 grant 完成状态和实际 runner 消费，并重新执行原严格三例、原物理矩阵、合法读写和 host 负控；不能改小功能合同换取绿色。

见 [独立 Windows 机制审查](reviews/b11-token-interface-independent/REVIEW.zh-CN.md)。B11 继续开放。

## 5. 当前 CI、原失败目录与 Windows 锁文件

11:44:50 UTC 的完整逐 job 快照包含原 19 个 workflow、44 个内部 job：**38 queued、4 success、2 skipped、0 running**。20 个空末页在 11:46:22–24 UTC 另行回收，保留非原子观察时间。12:03:03 的快照记录了 Core 已启动，之后的终态另列，不回写历史快照。**本次登记冻结截点 12:40:31 UTC 为 19 个 workflow、44 个 job：16 queued、16 running、9 success、1 failure、2 skipped。** 前驱成功后可以继续展开更多任务，44 不是最终固定总数。顶层 workflow 的 queued 不代表内部从未执行；仅诊断或业务阶段全部 skip 的 success 也不代表业务通过。

已取得的四个成功范围分别是：Intel operator 33 个原用例、Windows operator 40 个原用例、Windows 普通业务库 118 个具名用例、Windows retained 532 个具名用例。业务库在实际 base-merge 上执行，retained 在产品 head 上执行；源码身份分别保留。retained 另有 7 个原 nextest 跳过，名字与原因未由现有日志给出，不写成零跳过。

118+532 这些名字与冻结的 142 个原 blocker 退出用例交集为 0。因此，这些通过结果没有减少 B07/B08/B09/B10/B13/B20/B21/B22/B23 的待验范围。两项 Windows 私有目录拒绝控制另有同 head 实际通过，可补强 B12 的限定证据，不外推到 B11。

### 新增的 source-head 业务库成功

普通业务库 source-head job `127149582480` 在 **12:09:56 UTC** 取得实际 success，原 118 个名字分别为 Intelligence 78、Bao 19、Adapter 21，0 ignored、0 filtered。此次完整原日志、3 个 XML wrapper、3.6 MB 原 ZIP、源码与命令 receipt 均独立读取，绑定 `5b633…`/`b26598…`；不是借用前一次 base-merge 的通过。测试缓存禁用、原 attempt 为 1；2,045 个远程 build cache hit 明确属于构建缓存。两次执行的同一 118 个名字不合计成 236 个不同测试，与原 142 项的名字交集仍为 0，也不构成 Bao/Chain/HIA 外部接受。

### 新增的 Core 实际失败与最小修复候选

Core lifecycle run `41999104379` / job `127149546323` 于 11:59:54 开始、**12:12:02 失败**，source head 为 `5b633…`、tree 为 `b26598…`、attempt 为 1。完整原 job 日志为 702,243 字节，SHA-256 `95e2beb757a2984141f5ca26a91ee44a949947e261a8643b611e97dc31141a3f`；两份 ZIP 与所有成员完整校验，原 ZIP 没有 XML，不把 libtest 文本冒称 JUnit。

原正常分片的 8 份日志包含 33 次 libtest 子调用，恰好 **2,343 个不同测试：2,339 PASS、1 FAIL、3 ignored**。唯一失败是 `environment_selection::tests::blocking_snapshot_waits_for_starting_environment`，在原 `environment_selection.rs:1284` 的父子日志链断言处失败。真实 snapshot 已完成、选择结果检查已通过；捕获日志有未挂在父级下的 `environments.wait_until_ready`，却缺少 `environments.snapshot` 父 span，另一个 `environment.info` span 也缺失。包装器末尾重复打印同一 thread/time 的失败，不是第二次 attempt。

同一个 job 较早的原隔离 lifecycle 四例全部通过，并且该例的 snapshot 父子链完整。较早隔离成功不能替代后续正常并行范围。较早的 ownership 三例与 resume 控制也分别记录，不混进正常分片的 2,343 个名字。

冻结的 142 个 blocker 退出用例与本次原正常分片实际交集为 **12 个 PASS：B08 三个、B09 九个**。其余 130 个名字未在该范围内取得新结果，B08/B09 的剩余门槛和其他 blocker 原条件均不变。完整逐名索引、所有原件与失败切片见 [Core 终态独审](generated-evidence/ci-5b633-windows-core-lifecycle-v5/original-terminal-review.json)。

源码复核发现 pinned `tracing-core 0.1.36` 的单 Dispatch 快速路径会向首次触达 callsite 的当前线程询问 interest；其他测试在线程没有 scoped subscriber 时首次触达共享 callsite，可能将 never 缓存给后来的捕获线程。这一可达机制符合当前日志形态；真实 CI 未记录线程调度，具体交错仍为推断。原六行候选在测试内保留第二个从未设为 default 的 `NoSubscriber` Dispatch，但独立审查发现旧线程可能先捕获不持读锁的 `JustOne`，在新 Dispatch 完成重建后再写回 never；缓存写入没有版本检查。该方案已按 `REJECTED_AS_INCOMPLETE_REPAIR` 保留，不晋升为产品修复。

下一方案准备将原用例隔离到同一 test binary 的 exact 单例 owned child；原父用例继续留在原正常分片，子进程执行原业务 body、三条 parent-chain 断言及原 5 秒等待。必须验证精确一个原例确已执行、原失败/输出能够透传、无 0 用例或 skip 假绿并完成子进程清理。它属于测试 fixture 隔离，不能说成修复了 tracing-core 上游同步机制，目前也尚未取得原生资格。

Windows source receipt 的 Cargo/MODULE 锁文件哈希与 Git LF blob 不同，现已精确解释：Git 中完整 LF 原件按 LF→CRLF 转换后，其字节数和 SHA-256 恰好匹配两个 Windows receipt。它没有暴露依赖语义差异。该结论是“完整 Git 原件转换与原 receipt 哈希精确匹配”，不能说已经下载了 Windows 工作树两份完整锁文件。也不能把 Git tree 相同误写成工作树字节相同。见 [锁文件换行核验](generated-evidence/5b633-windows-lock-eol/lock-eol-review.json)。

11:28 的 GitHub 官方状态只读观察显示 Actions operational、无未解决 incident；状态服务自身更新时间为 08:19:24 UTC。它不能解释本仓库当前排队原因；队列原因仍是 UNKNOWN，没有推断账单、组织权限或 runner 配置问题，也没有为试运气重新触发工作流。

Windows owner-local job `127149582441` 在 **12:31:09 UTC** 实际 success，完整原日志和 ZIP 分别核验 UDS 14、Matrixd 31、Agentd 172 个 library 用例，合计 217，三组均 0 skip。原命令使用 `just test --locked -p PACKAGE --lib --test-threads 1 --no-tests fail --retries 0`，scope 与执行方式完整保留。其 217 个名字与原 142 个退出用例交集为 0；B13 的第九个 Agentd 控制属于独立 qualification 目标，没有进入该 library。实际传输/library 回归通过，不外推到外部接受或未选中的目标。见 [完整原件和逐名独审](generated-evidence/ci-5b633-owner-local-and-snapshot0040-v5/original-case-review.json)。

见 [冻结 12:40 CI 快照](generated-evidence/ci-5b633-owner-local-and-snapshot0040-v5/snapshot-summary.json) 及 [保留的 11:44 原快照](generated-evidence/ci-5b633-snapshot0030-v5/snapshot-summary.json)。本次没有覆盖或重标旧成功日志。

## 6. 新发现的 Memory 拒绝提交后连接复用风险

对 #4855 的固定提交与冻结 B16 vendor 逐字复核后，确认一条尚未由 Foundation 原控制覆盖的源码路径：SQLite commit hook 否决 COMMIT 后已经自动回滚，但 SQLx 的 `Transaction::commit` 因错误提前返回，内部 tracked transaction depth 仍可能非零；Drop 排队的 ROLLBACK 又因 SQLite 已经结束事务而失败。ping 只完成排队往返，不重置 depth。下一次 pool 复用该连接，再开自定义读事务时可能得到 `InvalidSavePointStatement`。

Foundation 的四个 Memory 提交否决控制直接使用 raw SQL BEGIN/COMMIT，没有走 SQLx Transaction bookkeeping；它们的真实 PASS 不受推翻，但不能覆盖这里的新读可用性风险。Donor 的相关生产修复实际早于上次观察，属于本轮新识别的风险，不能说它是刚新增代码。Donor 正文报告的 1,288 PASS 和红绿结果尚无对应完整 native raw，因此未借作资格。

已经写成独立 **2 路径、160 行新增/1 行删除**候选，其中生产变化只有 **11 行新增/1 行删除**：两个显式 guarded pool 入口在复用前拒绝 tracked transaction 非零的连接；coordinated 入口通过检查后继续原 owner callback，replacement 继续安装同一 hook、custody 和 lifetime token。默认 pool、只读入口、权限规则、锁文件和 SQLx driver 没有改变，没有重试 COMMIT 或手工伪造 depth。

两个新物理控制占住其余四个连接，在第五个槽创建 TEMP marker；真正触发 531 提交否决、比较 SQLite autocommit 与 tracked state，验证下一次读事务得到新连接，同时原 owner gate 仍拒绝隐式写入。负控须先显示真实 stale depth 与旧 marker，再命中原 read-availability expect，普通退出 101；超时、setup 错误或没走到物理前提都不算有效负控。候选已完成真实 Git apply/反向恢复的静态重建，**尚未编译和原生执行**，也没有修改未知 driver 所绑定的冻结 V7。见 [候选及完整审查](candidate-next/b16-refused-commit-pool/README.zh-CN.md)。

## 7. 后续执行顺序和实际闭合条件

1. **修复新出现的 Core 实际失败，并恢复原执行的可观测性。** Core 先验证 pinned tracing 的因果机制和原并行范围，不弱化原日志合同。Driver 已做三次完全相同请求的协调，现停止重复启动；只有后续出现可归属的真实任务身份或新的权威状态证据，才接续原输出，不另建 key、猜任务归属或重复编译。
2. **完成原 driver → pool → checkpoint → owning。** 每一段依赖上一段实际成功终态、源码树、两份实际生成锁、完整 metadata 与原前后守卫。后继模板可以先准备，未来值保持空缺。保留原负控恢复与原测试/fix/fmt 顺序，最终 hygiene 以后不追加测试凑资格。
3. **完成正常入口的真实接线与连接复用修复。** Memory 新候选在独立实际绑定的后续源批次做两个物理红绿控制，保持冻结原阶段不变。R2f1 先取得原编译/测试结果；随后实现并验证合法 Current、Dirty↔Current 协调、三池 binder、签名 objective/lease/revocation 与实际正常 caller。独立 Root/issuer/provider/target/UI 的成功与拒绝路径必须真实完成，wire DTO 或 operator SSH 不充当产品权限。
4. **逐名收齐原平台门。** 等待当前源的实际 CI，按冻结的 142 个退出用例、原平台、实际 source/merge 身份核对。失败有原正文才作因果修复；Intel PTY、Windows TUI 和 Unix App shutdown 均保原预算与真实输出要求。
5. **处理原严格 Windows 删除合同。** 以真实 parent DELETE_CHILD 原因设计带明确能力与对象生命周期的修复；必须兼顾合法 read/write 与外部删除拒绝，不能用 blanket denial、弱化断言或继承异源绿色代替。
6. **保持科学与外部接受的边界。** B18 的原 D−B 采用结论仍为科学 HOLD；B19 的 Bao/Chain/HIA 外部接受、WAN 与证书不能靠本地 build/test 关闭。需要原独立证据和实际接受材料。
7. **最后统一候选。** 只有上述实际源码和原必要平台门齐备，才能核准最新 main、合成 merge 与发布树的一致性。当前仍保持 Draft，不把证据提交或构建成功当成 main 合并资格。

完整项目发展方向与逐项执行门槛见 [当前发展方向和执行计划](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V2.zh-CN.md)：先完成 Agentd/Codex 的正常可用垂直流程和持久状态生命周期，再接 Memory 与共享计算，再做只读学习和独立 holdout/回滚/unlearning。原全量库存仍绑定 03:16–03:24 UTC；10:14/10:26 的 45 个新 Draft 增量，以及 12:04 的 13 项更新/4 个新 PR，均不被重新包装成一次新的全量库存。后者的两页原 API 及固定比较原件已 [单独冻结](generated-evidence/pr-increment-20261105T1204/api-freeze-manifest.json)。

本次新增结果直接推进了 B16 的 Foundation 子范围和后续具体代码。**原关闭条件、原状态分类、旧失败、取消、跳过、早退和未知项都保留。** 机器可读逐项状态见 [原 23 项本轮进度](continuation-blocker-progress-v3.json)。
