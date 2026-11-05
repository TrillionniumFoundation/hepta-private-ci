# hepta-private-ci：构建基线收尾、Foundation 首组结果与新提交 CI

本记录汇总 2026-11-05 本轮已经核验的原件；各 API 快照的实际观察时间分别列明。此前完整项目审计、发展方向和原 23 项退出条件继续有效；本记录补充实际完成的工程工作、纠正新发现的证据解释问题，并列出下一批执行顺序。

## 当前结论

**项目尚未达到全部 blocker 闭合。原账本仍为 8 项限定范围闭合、14 项开放、1 项科学 HOLD。** 本轮已经完成 Mac wrapper 的原始 57 用例修复验证、Linux PTY 诊断的原范围验证，并真正解决了新 Linux 构建基线的 V8、OpenSSL、libcap 前置问题。完整测试目录与 396 个程序产物身份现已取得；这份构建收据仍是 BUILD_ONLY 基线。此后单独启动的原生 Foundation 首组 4 个控制已通过，后续反事实控制仍在执行，不能外推为整个 B16 或全量测试通过。

新代码已经发布到 [Draft PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)。审计与原始证据分支独立保存，不把尚未验证的可信入口候选代码直接并入产品分支。

| 对象 | 本次固定身份 | 资格边界 |
|---|---|---|
| 产品 head | `5b6331250ff459033bd44d1a95daec70131277cc` | 已发布，Draft |
| 产品 tree | `b26598d0d97d8d51e723bb5582137315f2174d35` | 七个新增提交、十个受影响文件 |
| 原 PR base | `63652be658ebed8d3052eb789b951793384fd5e4` | 本轮未改变 |
| 实际 PR merge | `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff` | tree 与产品 tree 同为 `b26598d…`；不等于全部 CI 已通过 |
| ai395 原生构建源码 | commit `20fd174ded4e5ce01bda34e4f6d1d74803301f49` / tree `4a3374e22e16ce5c764288ad018cd9affadf94ea` | 独立 BUILD_ONLY 基线，保留与历史 A 测试树的区别 |
| 新构建基线原收据 | blob `31053a6179c016a9b5569cc6fb301e19aeb5c633` | 265,463 字节；Git 工具身份补项形成独立的 `5401ad25c5da11a6f37dc1d93a755070f927a396`，不改写这份原件 |

## 已完成的工程工作

### 1. Mac wrapper 的真实故障已在原 57 用例范围内修复

原 macOS CI 因 Bash 空数组在 `set -u` 下触发 `failed_targets[@]: unbound variable`，57 个原用例中有 3 个失败。本轮只保护空数组展开，保留原退出码、失败目标收集和成功目标日志保留语义，并处理第二处同类可选数组展开。

原完整 checkout 的下载曾以 Git 128 失败；该记录包含原错误和 1,169.393 秒耗时，实际未执行测试。随后按已审查的原文件依赖闭包，使用 13 个精确 Git 文件组成真实 Git 投影，在实际 Bash 3.2.57、Python 3.14.3 上执行同一组 57 个原控制：

| 源码状态 | 原用例 | 结果 | 跳过 / 重试 |
|---|---:|---|---|
| 修复前 | 57 | 原 3 个失败重现 | 0 / 0 |
| 修复后 | 57 | 57 PASS | 0 / 0 |

两次命令、用例名单、13 个源文件模式和内容、9 次源码检查、普通索引、完整 stdout/stderr 均已核验。74 份原件共 452,930 字节已经保存；根审查独立重构两个投影树并逐名比较全部用例。详见 [Mac wrapper 资格说明](MAC_WRAPPER_QUALIFICATION.zh-CN.md)。

这闭合了 wrapper 本身的原失败范围。它不代替真实 Bazel 产品测试、Windows 原生测试、Intel PTY 或整个产品 CI。

### 2. Linux PTY 诊断保持原行为和预算

测试专用的输出丢弃、进程状态和阶段观察已进入产品提交。独立 ai395 原生验证中，原 29 个 PTY 用例全部通过，0 跳过、0 重试；随后原 `just fix`、`just fmt` 和两个差异检查均成功，fmt 产生的两份机械改动已经独立复核并提交。没有在 fix/fmt 后重复测试来混淆验证顺序。

Linux 两个后端都观察到完整 4 MiB 输出被读取/丢弃及正常退出。这只能证明该 Linux 范围。旧 Intel 失败仍保留原 2 秒/5 秒预算及真实阶段观察；目前不能据此宣称其根因已经解释或其原 30 用例已经通过。

### 3. Linux 构建前置问题已逐个解决

所有准备都位于任务所属目录，没有修改系统安全策略或清理其他任务缓存。

| 前置问题 | 实际处理 | 完成证据与保留的失败 |
|---|---|---|
| V8 供应地址 | 使用项目锁定的 `openai/codex` 官方 release 资产 | archive/bindings/checksum 全量校验；此前错误供应地址失败单独保留 |
| OpenSSL 开发文件缺失 | 私有解包与已安装 runtime 精确匹配的 Ubuntu 官方 dev/runtime 包 | 142 个原头文件、真实 `.so`、符号链接与 pkg-config 身份记录；原 `openssl-sys` build101 保留 |
| libcap 开发文件缺失 | 私有解包与已安装 runtime 精确匹配的官方包 | 真实 `-lcap` 链接；仅独立 `.pc` 中 prefix/libdir/includedir 三整行重定位；系统默认搜索路径保留 |
| libcap 下载记录顺序错误 | 已关闭的原下载流重新校验，并继续读取原包 | 初次脚本在文件流关闭前取 hash 的失败保留；不是供应包损坏，没有放宽 checksum |

OpenSSL 的 `OPENSSL_INCLUDE_DIR` / `OPENSSL_LIB_DIR` 与 libcap 的 `PKG_CONFIG_PATH` 明确写入本次构建环境；它们不是未说明的系统全局安装。两套 SDK 的物理文件与符号链接检查在入口、出口以及失败 finally 中执行。

### 4. 三条原构建与列举命令全部成功

第三次实际 P4 在同一环境下执行了原定的三个命令：六个正常 helper 的完整构建、无裁剪的 Cargo metadata、无 `-p` / `-E` 过滤的完整 nextest catalog。它们分别以 0 退出，耗时约 1.661 秒、0.612 秒、298.789 秒。前两个命令利用已存在缓存；本记录不把它们称为全冷构建。

目录和依赖图独立复核结果：

| 契约 | 实际结果 |
|---|---:|
| workspace 成员 | 193 |
| resolve 节点 | 1,501 |
| 测试程序角色 | 363 |
| 正常 helper 路径 | 33 |
| 非 ignored 的可执行用例 | 19,506 |
| 原有 ignored 用例 | 57 |
| 非原过滤形态 | 0 |

完整 `(binary_id, name, ignored)` Counter 与原基线逐项相同，未只比较总数。整个 resolve graph 在仅规范化源码目录 ID 前缀及数组顺序后也相同；registry/git 包身份、实际 features、typed dependency edges 都保留。

三条命令后，原 P4 解析器错误地要求每个 case 都为 `filter-match=matches`，因此 controller 以 1 停下。这是记录解析器的错误：原基线的 57 个 ignored 用例本来就是 `mismatch`，且 reason 精确为 `ignored`。原 controller 失败保留，三个成功命令没有重跑。

独立只读 completion 随后以 0 完成，读取已经成功的原输出，取得 363+33 个当前物理程序身份，并完成源码、普通索引、两锁、8 个构建规则文件、工具及两套 SDK 的检查。该过程执行测试数为 0。完整 14 原件共 730,542 字节；不同原件的直接转运或精确重建方法逐项公开，并与各自原 native 文件 hash 相符。

完整 workspace catalog 构建实际改变了 4 个正常 helper 的产物 hash；原构建前记录与构建后记录分别保存，`normal_helper_initial_hashes_preserved_after_catalog=false` 保持真实值。

### 5. V7 修正原目录语义，同时保持所有执行门

V6 消费者与 P4 生产者具有同一错误的 all-matches 条件。此前静态审查未捕获它与真实原件之间的矛盾；保留旧版本与旧审查，本次在 V7 明确更正。

V7 只接受两种精确字典：非 ignored 且 `{"status":"matches"}`；ignored 且 `{"status":"mismatch","reason":"ignored"}`。它同时绑定完整原 19,563 个具名 tuple，而不是允许任意 mismatch 或只比较计数。

云侧使用真实原 catalog 重现 V6 拒绝，再运行原 4 个控制和新增 2 个控制，共 6 PASS。新增控制含 6 种错误过滤形态和 3 种保持总数的改名/ignored 身份交换，全部被拒绝。原 4 个测试函数正文、22 个原输入文件、原 SourceGuard、负控 finally 恢复、5 个 epoch、全部源码 payload 与 22 GB / 8 GB 预算均未改变。

这 6 项是解析器控制，不是原生 B 组测试。Git 工具补项已实际完成：`/usr/bin/git` 版本 2.53.0、文件身份及前后源码/索引/两锁检查齐全。新收据 `5401ad25…` 只新增第 8 个工具和补项来源，原收据其余全部字段相同；明确记录它是当前观测，不假称 P4 构建前已捕获。原模板保持 disabled；具体 ai395 绑定经独立复核后，由单独根执行记录启用，实际结果见下一节。

### 6. Foundation 已实际开始，首组 4 个原用例通过

具体入口固定 V7 的 29 个文件、25 个完整性对象、原源码/普通索引/两锁、8 个工具身份和两套 SDK。历史 ROG 记录以原 5,364,870 字节转运，原内部路径与旧失败保持不变。启动器的一项 V8 收据类型误读在运行前修正：`variant_unchanged` 实际为锁定变体字符串，不是布尔值；只改该精确比较，旧版本保留。

第一次启动工具返回超时，不能推断 native 是否执行。读取完整任务库存、授权时间窗口及精确安装路径后，按控制器文档用完全相同的操作键和全部原请求实参对账，取得实际任务 `1a1ab493f2b-fc05-4bfe`。返回 `reused=false`、systemd running；原超时和本地错误响应解析记录分别保留，不改写为成功或产品失败。

实际安装收据确认 29 个文件、启用绑定和根执行记录相符，安装前空闲空间为 631,759,765,504 字节，冻结执行器仍再次检查原 22 GB 入口门。原始 `4a3374e…` 经规定的两文件迁移进入首个 B 树 `87e44120dc46e4751b74fb167269a6d85448ff4f`。普通索引与两锁未改变。首组辅助程序构建 0、完整元数据 0，随后原全目录准备和原 `just test` 成功。

首组真实测试的原 JUnit UUID 为 `e5d53c67-01d5-4858-861a-93e218c015c2`，四个原名字全部 PASS：初次/复用连接的 checkout callback、撤销后的显式事务拒绝、取消 checkout 后的连接控制、pool 增长与替换。原 `just` 退出 0，耗时 2.560 秒，0 重试、无早退观察，实际 SQLite 版本 3.51.3。1 个测试程序与 33 个辅助程序的前后 hash 相同，源码和完整依赖图检查成立。

该命令按原选择器执行 4 项，另有 216 个用例和 362 个二进制未被选中；不能把它写成全 workspace 通过。执行器内部名称 `B01_R2c_V3` 是 B16 的阶段名，不是原 23 项账本的 B01。后续已进入原反事实源码阶段；整个 Foundation、driver、pool、checkpoint、owning 及正常 Root/UI/provider 接受仍须各自原结果。

## 新提交的 CI：四个原生任务已成功，其余继续逐项核实

旧 blocking run `41975255726` 于 09:42:55 进入 completed/cancelled，新 blocking run `41999114842` 的单个串行等待解除。取消者仍未知；本助手没有执行取消、dispatch 或 rerun。旧 Rust / required 汇总的失败反映旧任务取消及旧门失败，保留在旧 head 记录中，不作为新 head 的产品失败。

**状态解释更正：工作流顶层 `queued` 不足以证明它的全部内部 job 尚未执行。** 10:00:55 的完整 job 列表显示新 head 已有一个成功 job，而相关 workflow 顶层仍是 queued。此前仅根据 run 级快照推断没有内部执行的表述收回；逐 job 的实际 runner、steps、checkout 与完整日志才是执行证据。

[Intel operator 原任务](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41999114742/job/127149584078) 的实际 head 为 `5b633125…`，实际 tree 为 `b26598d…`，运行于 macos-15-intel，09:42:55–09:45:38 成功。原命令使用 `--nocache_test_results`。完整 ZIP 1,269,035 字节、5 个成员的 CRC/hash 已核验；完整 test.log 逐名记录 33 PASS、0 FAIL、0 ignored、0 filtered，包含真实 `/usr/bin/ssh-keygen` 对照。

该任务有编译远程缓存命中，测试本身实际执行；不能称为全冷构建。test.xml 中是 1 个 Bazel wrapper testcase，33 个原 Rust 用例来自完整 test.log，不能写成 33 个 JUnit case。

随后 10:07:28 的完整分页复核中，新 19 个 workflow 的完整 job 列表仍为 44 个：41 queued、2 skipped、1 success，全部 attempt1。该成功仍是 operator fixture 范围，不能代替 Bao/Chain/HIA 的真实外部接受，也不能代替 Intel PTY。后续状态使用独立增量记录，不能把本快照当成后续终态。

10:41:39 的完整逐 job 快照及截至 10:45:00 的空末页复核，得到同一组 19 个 workflow / 44 个 job：38 queued、4 success、2 skipped。新增成功的原件分别核验如下：

| 原任务 | 实际源码 | 原用例结果 | 资格限制 |
|---|---|---|---|
| Windows operator `127149584053` | head `5b633125…` / tree `b26598d…` | 40 个具名 JUnit 与完整日志逐项一致，全部 PASS，0 跳过/重试 | operator / 原生 OpenSSH fixture 范围 |
| Windows ordinary business `127149582006` | 实际 base-merge `9063c52a…`，parents 为原 base 与当前 head，tree 同为 `b26598d…` | Intelligence 78、Bao adapter 19、Codex adapter 21，共 118 个原日志具名 PASS，0 ignored/filtered | 三个 XML 仅各有一个 Bazel wrapper testcase；不是 118 个 JUnit 节点 |
| Windows retained `127149547694` | 实际 head `5b633125…` / tree `b26598d…` | Memory 299、State 209、Path 24，共 532 个实际 JUnit 节点全部 PASS，与完整原日志名字 Counter 相同 | 原 nextest 另报 7 个 skip，原件未给名字和原因；XML/result 的零 skip 不能覆盖它们 |

普通业务库保留原 `--nocache_test_results --flaky_test_attempts=1`；构建有远程缓存命中，不能称为全冷。retained 保留原 `just test --locked` 三库、`--lib --no-capture --retries 0`。普通业务 ZIP 的 10 个成员和 retained ZIP 的 4 个成员分别通过 CRC 与逐项 hash 复核，包含完整实际日志、源码记录和原 Bazel 执行日志。

将新 118+532 个名字与冻结的 142 个原失败退出用例逐项对照，交集为 0，因此不减少 B07/B08/B09/B10/B13/B20/B21/B22/B23 的未验数量。补充目录中的两项 Windows 私有目录拒绝控制——祖先替换、junction——在当前 head 的实际 JUnit 与原日志中均通过，分别耗时 0.024 / 0.021 秒。这更新 B12 的同源运行范围，不替代 B11 的严格 token/legacy 合同。

## 正在开发的 PR 增量与真实修复边界

在原完整库存之后，10:14 与 10:26 的两组 updated-desc 前缀各读取完整两页、60 条且无重复，覆盖至 03:24 历史边界。发现 49 条近期更新，其中 45 个新编号为 #4824–#4868，全部 Draft；这不是新的完整 open PR / branch 总数，也不包含期间已关闭 PR 的全量历史。原 1,103 PR / 5,193 分支仍保留原观察时间。

与当前收敛方向最相关的候选有以下边界：

- Windows PTY #4854 → #4868 先有 E0034，移除 trait 导入后又出现 6 个 E0599，实际未执行测试。当前产品不含该 donor 的新增测试文件，不能将 donor 失败算成本产品回归，也不能采用为已验证修复。
- Windows 隔离 #4844 的原物理 I/O 证明两项严格用例发生越界删除；同 descriptor 的生产 token `DELETE` 拒绝而父目录 `DELETE_CHILD` 允许。full-restricting 对照的 outside-read 拒绝来自 **AccessCheck**，没有在该对照 token 下执行物理 read/delete。候选的 blanket rejection 不能恢复原读取及 root 范围写入合同；当前产品严格原用例仍需自身 Windows 结果。
- Memory #4847 的 native migration kernel 尚未接生产 Control，scoped CI 实际失败；Notes/G2 #4842 仍缺原 owning、socket、boot 和外部效果验收。不能拼接为 B16 的接线或恢复资格。
- #4867 的算法负面发现保持研究结论与科学 HOLD，不能代替独立 D−B 采用门。

61 份完整 PR/API/日志/固定源码原件已归档；#4812 / #4855 的两次实际 head 移动分别保留。详见 [PR 增量复核](PR_INCREMENT_20261105_1014.zh-CN.md) 与其 AccessCheck 限域补记。

## 项目方向与下一批计划

完整方向分析见 [项目发展方向与工作计划](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md)。本轮证据继续支持先打通可用的产品纵向链路：Codex AppServer 负责 session/thread/turn/model/tool 主流程，Agentd 负责组合与生命周期，优化器和研究组件不额外获得执行权限。

| 执行顺序 | 交付 | 闭合条件 |
|---|---|---|
| 1. 原 CI 收敛 | 固定新 head/base/merge 的逐 job 原结果 | 原失败用例、平台边界、skip/retry/早退均保留；required 门实际成功 |
| 2. Foundation | 原 24 个不同阳性控制、27 次规定执行及 10 个负控 | 实际 native 结果、精确失败原因、物理观察与恢复成立；预算与原 oracle 不变 |
| 3. Driver / Pool / Checkpoint | 原驱动控制、两个 state pool 的 owner 绑定、独立 checkpoint custody | 真正依赖采用及生成两锁；runtime 活着时的取消及跨进程物理观察通过 |
| 4. 所属包与正常入口 | owning epoch 的测试与 fix/fmt；Current/FinalUse/issuer/listener 与正常 caller 接线 | 同源结果及真实正常入口成立，不能用测试辅助入口替代 |
| 5. 产品接受 | 同源 Root/Session、原 signed objective、provider/target 的任务/取消/丢 ACK/重启 | 外部物理效果、权限、证据与 Memory 一致性回执齐全 |
| 6. 外部与科学门 | 分别推进 Bao、Chain、HIA；另行冻结独立 D−B 实验 | 真实外部消费者接受；科学门未过即保留 HOLD 与普通默认 |

原 23 项分类和退出条件没有因为子任务进展而改名或放宽。详见 [本次 blocker 进度](continuation-blocker-progress-v2.json)，以及原 [全量审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)。本记录不会宣称 main 合并资格、生产发布资格或全部 blocker 已闭合。
