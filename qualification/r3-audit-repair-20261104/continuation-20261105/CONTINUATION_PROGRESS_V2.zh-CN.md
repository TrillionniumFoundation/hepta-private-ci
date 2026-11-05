# hepta-private-ci：续批进展、剩余阻塞与执行顺序

本报告续接[完整项目审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)、[发展方向与计划](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md)和[首份续批报告](CONTINUATION_PROGRESS.zh-CN.md)。本地状态观察截至 **2026-11-05 09:12 UTC**；原 CI 的第五批完整归档截止 08:25:35，旧主阻塞工作流另有 08:33:29 的 job 状态观察。各读取不是原子快照。

**项目目前仍处于“整合现有实现、补齐跨平台和正常产品入口验收”的阶段。原 23 项台账保持 8 项限定范围闭合、14 项开放、1 项科学采用 HOLD。** 七个新修复提交已实际发布到现有 Draft，Linux PTY 原范围完成验证；新头已触发 19 条原工作流，Mac 本地原测试对照及新主机冷构建继续执行。这里不把工作流启动、构建准备、诊断代码或取消前的部分成功记为完整验收。

## 1. 当前主线与完成标准

近期交付应围绕 **P0.8D 可用纵向切片、INT-2 Agentd / Codex 装配** 收敛。Codex AppServer 继续承载 session、thread、turn、model、tool 执行主干；Agentd 负责装配和生命周期。Memory、共享计算和优化能力按这条主干的权限、取消、恢复与证据接口接入。

上一轮全量清单的规范口径为 40 模块、205 合同、58 协议、67 领域、91 工作包；其中 43 planned、25 source implemented、20 execution pending、2 semantic pending、1 external。03:16–03:24 的仓库快照有 1,103 个开放 PR、5,193 个分支。源码、接口、研究报告和局部通过已经很多，当前推进应以同一候选的实际行为闭环为准。该清单不代表全部 PR 已获得行为验收，也不能由文件存在推导生产完成。

一个可用交付至少要同时具备：固定源码和依赖、原平台验证、正常用户入口、正确的权限与效果归属、取消和重启后的恢复，以及可核对的结果回执。科学采用另受独立实验约束，外部 Bao / Chain / HIA 接受另受真实目标和调用者约束。

## 2. 固定修复候选

| 对象 | 当前身份 |
| --- | --- |
| 现有产品 PR | [Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)；基线 `63652be658ebed8d3052eb789b951793384fd5e4` |
| 09:02:33 实际发布产品头 | `5b6331250ff459033bd44d1a95daec70131277cc`；树 `b26598d0d97d8d51e723bb5582137315f2174d35` |
| 前一产品头 | `0e139b599f0fe451f80fb7db4b2913bb9c679dce`；树 `091e659e0da6602299fd14cfa93889191405edd8`；本次增加 7 个提交、10 个路径 |
| 实际新合成 merge | `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff`；树同为 `b26598d0…`；实际父提交依次为原基线和新产品头 |
| 已发布的续批证据 | `audit/r3-evidence-20261105` 的 `5801001c488dcb3ea4c3e1a2e5f7cba7b9eef84b`；树 `d530d05338d3d1eb293c394ae01d112f10366f9b` |
| Linux PTY 测试源码 | `1ddadae2c1bcb3c48047d2692565606833e87909`；测试树 `73f4b30499524d6137bb8f4b40c3977de286d1a5`；原格式化后树 `ae8ce55dc264cdca2dd4a125d473fbca030f45e2` |
| B 冷构建固定源码 | `20fd174ded4e5ce01bda34e4f6d1d74803301f49`；树 `4a3374e22e16ce5c764288ad018cd9affadf94ea` |

新候选的具体变化如下。完整源码与提交链见[候选记录](reviews/final-code-candidate.json)，实际 lease 更新、回读、合成 merge 与验证限域见[发布回执](reviews/product-publication-receipt-v1.json)。Mac 取源仍未结束时，已将可逆的 Draft 更新与本地验证并行，未把尚无结果的原 57 项预记为通过。

| 变化 | 原因和保持的边界 |
| --- | --- |
| musl 平台标签去重 | 原 `cquery` 返回两个相同 canonical label。只对解析结果去重，空值、冲突、真实 target/linker/rustlib、静态 ELF 和同文件 CLI 验证保持。 |
| Windows 删除权限夹具格式 | 按实际 Rust 1.95.0 rustfmt 输出折行，不改变权限或删除断言。 |
| Codespell 精确证据路径 | 对已逐件核验的 153 个冻结证据文件列出准确路径；不增加词级忽略或目录通配。其余 836 个旧注册证据不被这批排除命中。七个混合 JSON 的排除粒度是整个具名文件。 |
| V8 staged smoke 特性 | 增加 `--no-default-features`，原 sandbox=true 行继续显式启用 sandbox；产品默认特性和六个原 smoke 断言保持。 |
| Intel PTY 测试观察 | 记录读/丢弃字节、任务和 FD 状态。原 2 秒 / 5 秒预算、4 MiB 输出、alarm、backend 顺序和退出断言不变。这仍是诊断变化，尚未构成 Intel 根因修复。 |
| Mac Bash 空数组处理 | 对空 `failed_targets` 增加长度判断，并对另一处可选参数数组作同类保护；成功日志留存仍在失败循环之外。原 57 个测试、collector、退出状态和参数语义保持。 |
| PTY 原生格式化结果 | 只接纳原 `just fmt` 实际产生的两个文件机械变化：链式表达式折行、原子类型导入顺序和调用折行。 |

## 3. 本次已完成的原生验证

### Linux PTY：原范围完成

在 ai395 的独立源码和 target 上，原命令 `just test --locked --cargo-profile dev-small --no-tests fail --retries 0 --success-output immediate -p codex-utils-pty` 实际执行 **29 PASS / 0 FAIL / 0 SKIP**。完整 catalog、选择记录、JUnit 和原输出的测试名字逐项一致，两个测试二进制身份保持，没有以提前返回代替行为通过。

随后按仓库要求运行原 `just fix`，退出 0、没有源码变化；原 `just fmt --base 20fd174…` 退出 0，产生上述两个机械变化。控制器按约定保留了格式变化审查停止的 exit 1，没有把它改写为全程 exit 0。独立复核实际后像后，只执行剩余两条 `git diff --check`，均退出 0；六次整树守卫、普通 HEAD、index、锁文件及九个源文件保持。**fix/fmt 后没有重跑测试。**

完整原件见 [测试及修整优先包](native/pty-v2/priority/priority-bundle.json)、[最终只读检查完整包](native/pty-diagnostic-ai395/readonly-completion-bundle.json)、[根审结论](reviews/pty-completion-root-review.json)。初次执行器的 `os.X` 拼写错误发生在建目录和测试之前，原 0 用例失败也已保留。

Linux dropped-output 两个 backend 都实际读完并丢弃 4,194,304 字节、得到 child exit 0，输出阶段到达 `output_write_returned`。这支持 Linux 本范围通过，**不解释原 Intel 的 `python_started` 超时，也不关闭 B21**。Intel 的原失败仍是 31 个结果中 30 PASS / 1 FAIL，失败早于取消。

### Mac 原 57 项：取源失败后按精确闭包继续

原 hosted Mac wrapper 曾得到 57 项中的 3 个失败；Windows、Linux 和 repo-build 的同一范围分别已有原通过。现已固定一个只有 wrapper 后像变化的 Mac 原生对照：旧树 `4a3374…` 到新树 `890362b5…`，保留十个关键源码及 57 个完整测试身份。

实际 Mac 使用 `/bin/bash 3.2.57` 和已安装的 Python 3.14.3，父进程和 wrapper/collector 子进程使用相同 PATH。系统 Python 3.9.6 不支持原代码直接求值的 union 注解，已在执行前识别，没有用不兼容解释器运行基线。

第一次完整取源在 1,169.393 秒后实际退出 128，尚未 checkout、执行零测试；完整 144 B stderr 是 HTTP/2 stream CANCEL、early EOF 和 invalid index-pack output。控制器退出 1，原目录和原失败保持。这里的 CANCEL 是该 Git 传输报错，不能用它解释 GitHub Actions 的历史作业取消。

实际依赖闭包审查发现，原 57 项需要 13 个固定源文件、共 146,000 B：此前十项之外，还需要原 query wrapper、根 `BUILD.bazel` 和 `MODULE.bazel`。Collector 和两个原例还会调用并比较真实 `git rev-parse HEAD/HEAD^{tree}`。因此替代方案使用新的独立源码投影和真实 Git commit/tree，保留原目录布局、测试、collector、参数及现有 Python/Bash。来源仍可逐文件追到固定 `20fd/4a`，实际执行身份必须是投影自身，不能标为完整 `4a` checkout。预测投影树为 `69f329ac…`，仅 wrapper 修后为 `93fe0fed…`；它们需要实际安装后核对。见[精确来源映射](native/mac57-projection/source-map.json)和[投影方案](native/mac57-projection/contingency-plan.json)。此刻原 57 项仍未取得结果。

## 4. 原 CI 最后结果与取消边界

五批原件归档累计 574 个成员，原长度 86,256,266 字节，132 个分片重建 25,452,260 字节压缩传输。成员包含不同快照和派生记录，不能当作不重复测试数。前三批已在上面的固定审计提交中注册，第四、第五批随本报告继续登记。每批完整长度与内容哈希可从其 registry、manifest 和复核回执重建。

| 新取得的原证据 | 实际结论 |
| --- | --- |
| Mac ARM Clippy | 原作业成功，20,515 个 actions；完整 raw 已保留。 |
| Mac wrapper | 原 57 项中 3 FAIL，明确出现 `failed_targets[@]: unbound variable`，对应当前修复。 |
| 两个 GNU V8 release | 各自 5 PASS / 1 FAIL，同一 sandbox 特性错配；等待新候选自己的结果。 |
| 两个 musl V8 release | API 成功，但日志明确跳过 non-native Cargo smoke，只支持构建 / stage / 上传成功。 |
| Windows 主测试分片、GNU 与 musl 标签作业 | 已读完整原日志，终态取消；只存在不同程度的中间进度，没有完整测试终态或主 collector ZIP。 |
| 主 blocking run | 08:33:29 可见 34 jobs：8 成功、16 取消、2 失败、4 跳过、4 排队，0 running。排队项不能解释为仍在编译。 |

取消原因仍未知。完整检查固定头的 93 个工作流，没有发现可证明的调用图自取消；分支 API 的完整可见结果为 74/74 次运行、四个源码头、全部 attempt 1，当天 19/19 仍是原先那组，没有可见的较晚运行解释 08:00–08:23 的取消。这个检查只覆盖当前连接能看见的该分支记录，不能推断所有外部事件、操作者或服务内部原因。原触发 actor 也不能当作取消者。详见[有界查询复核](reviews/ci-concurrency-branch-visible/bounded-runtime-review.json)。

新头的首次完整读取发生在 09:03:09–09:04:29：19 runs 为 16 queued、blocking pending、2 条件 skipped；41 jobs 为 39 queued、2 skipped，尚无实际 runner。09:11:54 的后续读取仍无实际执行。即使 queued job 已有 `started_at`，runner 空值也不能当作已开跑。实际 head/tree/merge 父链、分页和原 API 见[新头初始投影](new-head-ci/snapshot-0001/projection.json)与[完整原 API 归档](new-head-ci/snapshot-0001/complete-api-archive.json)；没有因排队修改并发策略或归因具体操作者。

## 5. B16 新主机冷构建与原验收

ai395 已完成固定源码、Rust 1.95.0、just 1.51.0、nextest 0.9.103、Bazel 9.3.0 和 V8 原供应准备。正确的 V8 archive、bindings 与 checksum 来自原项目使用的 `openai/codex` 固定发布，实际下载的两项资产与既有回执哈希一致，gzip 校验完成。首次查询错误供应仓库的失败原件仍保留。

P4 第一次执行六个普通 helper 的原 Cargo 构建，在 123.945 秒后退出 **101**。完整 stdout 218,488 B、stderr 44,310 B 证明 `openssl-sys 0.9.117` 找不到 OpenSSL 开发信息：系统缺少 `openssl.pc` 和开发头文件。该次没有执行后续 metadata/catalog，更没有执行 A/B 测试。

主机已有 Ubuntu 26.04 的 OpenSSL 3.5.5-1ubuntu3.7 运行库。任务私有依赖准备已实际成功：官方 dev/runtime 包完整 SHA 核对，142 个未改写头文件及相对链接映射、两份私有与现有运行库字节身份均记录，原 pkg-config 版本及私有编译参数查询成功。完整成功回执为 114,477 B，终态为 48,831 B；根审重新核对了两段固定版本传输和五份完整原件。见[SDK 根审](reviews/openssl-sdk-root-review.json)及[完整 SDK 回执](native/ai395/openssl-prerequisite/openssl-sdk.json)。没有系统安装、特性或锁文件修改。

新的 P4 continuation 在同一 source/target 上执行，仅向实际 Cargo 环境加入两个 OpenSSL 路径，起止重新检查 SDK 物理输入。原三条构建 / metadata / catalog 命令及 13 个原函数保持，独立静态审查已核对。该次明确复用首次失败留下的任务内构建缓存，不称为空缓存首次构建。

本次六个普通 helper 构建实际退出 0、165.247 秒；完整 metadata 实际退出 0、11.489 秒。随后无过滤完整 catalog 的编译在 146.063 秒后退出 101。完整 40,456 B stderr 明确 `codex-bwrap` 的原构建脚本找不到 `libcap.pc`，OpenSSL 错误已经跨过；仍为零测试执行。固定源码、六个源码守卫、普通 index/锁和 SDK 首尾身份保持，后续补齐真实匹配的 libcap 开发依赖，不设置跳过 bubblewrap 的环境变量。完整失败见[catalog 原 terminal](native/ai395/p4-openssl-catalog-failure/terminal.json)和[原 stderr](native/ai395/p4-openssl-catalog-failure/03-full-unfiltered-catalog.stderr.original)。本次没有产生成功 BUILD_ONLY 基线。

后续仍按原顺序：六个普通 helper → 完整 metadata → 无过滤完整 catalog → BUILD_ONLY 基线 → 原 foundation 正负控 → driver / pool / checkpoint / owning。冻结 V6 可绑定新主机的真实 BUILD_ONLY 回执，不会把历史 ROG 测试身份改成 ai395 测试身份。原 112 个源码对象、五个 epoch、正负控、22 GB / 8 GB 门、零测试重试和精确源码恢复要求保持。缺少的三项 recipe 身份会作为单独只读补充登记，不重写失败记录，也不为补哈希重跑构建。

SDK 的实际文件身份由独立回执及启动 / 结束只读校验覆盖；V6 现有源码守卫本身不会自动覆盖外部头文件和库。所有阶段都应如实记录实际生效的环境，准备期 pkg-config 查询环境不能冒充后续 Cargo 的环境。

## 6. 剩余工作顺序和闭合条件

| 优先级 | 当前工作 | 闭合依据 |
| --- | --- | --- |
| P0 | 已发布七提交候选并触发原工作流；继续 Mac 原 57 对照和新头平台验收 | 新产品头、base、实际 merge tree；新头自己的原平台日志和工件。 |
| P0 | 完成 ai395 冷构建，执行 B16 逐批原正负控 | 同源真实 BUILD_ONLY、普通 helper 与完整 catalog；每批效果、拒绝和恢复回执。 |
| P0 | 根据新 CI 解决 Intel PTY、Windows strict sandbox / TUI、Core 集成及其他具名缺口 | 保留原断言和预算，完整原名字与实际行为相符；取消、过滤和早返分开。 |
| P1 | 验收正常 Root / Session / signed objective / provider / target / UI caller | 真实任务、取消、丢 ACK、重启、撤权和物理效果接受，不能用组件夹具替代。 |
| P1 | 完成同一候选的 main 整合资格和 UI 浏览器 / 原生产品验收 | 新候选 required CI、实际浏览器和原生入口的完整接受，复核 main 的真实差异。 |
| P2 | 整合共享计算和可靠 Memory | authority、evidence、Memory 与物理效果一致，故障和回滚可复核。 |
| P3 | 因果观察、学习和科学采用 | 事前冻结独立数据、估计单位、完整成本、失败尝试、holdout / rollback / unlearning。 |
| 外部依赖 | Bao / Chain / HIA 接受 | 真实固定外部版本、调用者、目标、故障、安全和效果回执。 |

原 B02/B15 仍等待最终整合资格；B07–B11、B13、B20–B23 等待各自原平台具名范围；B16 等待正常入口和效果接受。B01/B03/B04/B05/B06/B12/B14/B17 的闭合继续限于原范围，原台账与退出条件不变。

B18 科学采用继续 HOLD：已有 J−C 规划收益不能替代原 D−B 采用比较，部分收益改变计算量，OOD 已在验证中暴露，五次 solver 均未达到 success，完整成本和目标生产运行形态仍未满足。验证拒绝 D 后恢复 C 证明了回退机制工作，不能证明 D 已通过采用门。B19 的 Chain HOLD、Bao 能力缺口及 HIA DENY_ALL 同样需要真实外部接受。关闭这些项目必须获得新的证据，不能靠重命名或放松条件。
