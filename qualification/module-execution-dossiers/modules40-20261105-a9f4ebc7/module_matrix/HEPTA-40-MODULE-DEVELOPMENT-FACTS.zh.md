# Hepta 全量 40 模块发展报告

**状态：本轮已完成全部 40 模块的源码导航与严格一致性检查，C58 原四包套件 Run2 的 697 项执行全部通过，59 项必要用例已独立核对；40 模块生产资格仍全部为 false。** 原套件另有 66 项 skipped；Run1 的真实失败和缺少 JUnit 的事实完整保留。导航已检查 40 张 Map、刷新 26 张，发布 C1 后原 qualification、状态、registry/docs、no-op 与全仓输入等价检查均实际通过。Rust 测试执行身份保留在 C58，没有改写为 C1 执行。本报告逐项区分固定基线能力、本轮实际改动和仍未关闭的执行/生产门槛。

## 一、固定身份与统计口径

| 对象 | 固定身份或事实 | 可支持的结论 |
| --- | --- | --- |
| 基线提交 B0 | `f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55` | 40 份 Map、注册表与本轮差异审计的共同起点 |
| 基线真实 Git tree | `1f3d38ee52320bba1f345da2f2c54b23a36832ee` | 来自 commit 对象的 `tree.sha`，没有把 commit SHA 当作 tree |
| Map 数量 | **40** | 逐个覆盖所有登记模块 |
| 操作记录总数 | **369** | Map 的操作映射条目数量；不表示 369 项已运行或验收 |
| 已解析源码根 | **40/40 模块均存在** | 固定 tree 中可定位；填有 sourcePath 的操作未发现缺失路径 |
| 下载文件身份 | **47/47 Git blob 一致** | 40 份 Map 和 7 份注册/状态文件的下载内容与固定源对象一致 |
| Map 的 productionImplementation | **0 true / 40 false** | 全部模块仍保持非生产资格；源码存在与生产资格分开 |
| 注册投影不一致 | **2 模块 × 3 文件 = 6 个布尔值** | objective.compiler、cognitive.store 的三份投影错误地保留 true |
| sourceObjects 漂移 | **18 张 Map、70 个对象** | 基线导航 tree/blob 与基线当前源码对象不一致，须在最终候选重新观测 |
| Map gap 条目 | 仓内 101 条、外部 140 条 | 数组条目汇总，含跨模块重复依赖，不能当作 241 个独立缺陷 |
| 实际机制测试提交 N0 | `910a5373c786c3e180f5b4d743ad794d88df5cec` / tree `4d9de9f9d5eef537e5cee1c07b3d1875d30af56e` | ai395 实际执行 159 项机制 tests 的身份 |
| 已发布 canonical C0 | `e9b84f242326e5280ee2b2de937f03f78bc1e907` / 同 tree `4d9de9f9d5eef537e5cee1c07b3d1875d30af56e` | 17 阶段 tree 逐项一致；commit 身份与 N0 不同 |
| 最新原生 merge M0 | `f29a30f5f9ba42d139659b80ec332e75ee0ccfb9` / tree `57809be09ef01c02389ef37a817f1447d13d167b` | 真实三方融合 C0 与 e65；格式化和 lint 阶段独立记录 |
| 当前发布源码 C58 | `58c81ccdd25002ae0f481d434af067a56fa7ddb8` / 同 tree `57809be09ef01c02389ef37a817f1447d13d167b` | PR #4869；Run1 与 Run2 都在此 commit 实际运行，分别保留结果 |
| 已发布导航提交 C1 | `5e917b9f5fb3e841dbcaefcd5bbbf59b32f20411` / tree `5f02eb87cce34d40d6ddf21722305192b4fa00d7`；sole parent C58 | 26 张 Map 与新账本；strict 绑定独立 C1，不转写 C58 执行身份 |

统计证据：[完整 40 模块固定源码审计](40-module-source-audit.json)、[初始漂移审计](initial-audit.json)、[47 文件 blob 校验](source-blob-verification.json)。Map 的 caller/writer 状态是登记的源码组合事实；其运行有效性必须由相同候选的执行证据确认。真实 tree 的身份更正已记录在初始审计中，没有影响逐文件 blob 比对。

### 已发布源码与实际执行身份

源码通过 GitHub connector 分 **17 个阶段**发布到 `integration/modules40-source-recovery-20261105-a9f4ebc7`，固定 canonical C0 为 [e9b84f242326e5280ee2b2de937f03f78bc1e907](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e9b84f242326e5280ee2b2de937f03f78bc1e907)。阶段包括 Desktop 与 ConPTY 两个 donor、资格投影纠偏、11 个产品恢复 cohort、原 formatter 与受审查的 lint 清理，以及最后的原 pin 守卫。

逐项核对结果：17 个 published commit 的 tree 全部等于各自 native stage，canonical parent 顺序连续且从 B0 接续。最终 C0 与 ai395 实测的 N0 共享 tree `4d9de9f9d5eef537e5cee1c07b3d1875d30af56e`，但 commit SHA 不同。17 个阶段的发布不等于 17 次产品执行，tree 一致不会把 N0 的测试记录转写为 C0 执行记录。见[源码发布原始映射](../publication/canonical-source.json)和[逐阶段身份核对](canonical-source-publication-check.json)。

ai395 已在 N0 上实际运行 159 项原 verifier 机制 tests，全部通过。实际日志为 31.780 秒，外层 wrapper 为 32.039 秒；执行前后 commit/tree 相同，结束时工作树为空。该 suite 验证源码身份与迁移机制，尚不提供四包 Rust 产品测试或 40 张真实 Map 的 strict 结果。见[ai395 原始运行回执](../publication/native-evidence/source-pin-mechanism-suite.json)、[与回执摘要匹配的完整日志](ai395-source-pin-mechanism-suite.raw.log)与[格式化身份对照](../publication/native-evidence/source-pin-format-equivalence.json)。原本地文本传输副本多了一个末尾 LF；日志副本仅移除该字节后精确匹配回执 SHA-256 `be67c74515ea46cf6086a16deef207d5b5792b636a2dec900dd55a7c2ec20ad8`，保留[字节恢复说明](ai395-mechanism-log-byte-recovery.json)，未改变运行结果。

### 当前统一源码 C58

在 17 阶段 C0 之上，继续执行了与 `e65a53ddfc872ef66edc63dff8f28d4414817c60` 的真实三方 merge。原生 merge M0 为 `f29a30f5f9ba42d139659b80ec332e75ee0ccfb9`，完整有序 parents 为 `[e9b84f242326e5280ee2b2de937f03f78bc1e907, e65a53ddfc872ef66edc63dff8f28d4414817c60]`；其 tree 为 `57809be09ef01c02389ef37a817f1447d13d167b`。初次 Git merge 的真实冲突及逐文件解决记录保留，未把冲突返回码改写为自动成功。

最终发布为 [C58：58c81ccdd25002ae0f481d434af067a56fa7ddb8](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/58c81ccdd25002ae0f481d434af067a56fa7ddb8)，tree 与 M0 相同，见 [PR #4869](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4869)。e65 是实际 parent，不能只用新 commit 描述代替真正的源码融合。见[canonical merge 身份](../publication/canonical-e65-merge.json)、[原生 merge/格式化记录](../publication/native-evidence/e65-merge-source.json)与[逐文件融合审查](../product_recovery/base_refresh/patch-review.json)。

此次补充将 `turn/completed` 携带的完整消息按 item ID 并入既有累加器，在精确 terminal witness 验证及有界文本检查成功后才写终态。只带最后一条消息的 summary 保留此前已经观察的其他消息；超大 terminal snapshot 不能授权完成。1,024 项边界保留，metadata 计入结构和 ID 总字节；原新增 10 个测试名及 30 个断言保留。Desktop joint boundary 同时验证注册并核对回调内实际 issuer/writer lease 与原租约完全相等，保持原 CAS、撤销和时间边界。行为细节与兼容性见[源码影响说明](../product_recovery/source-impact-compatibility.zh.md)。

完整四包原 `just test` 的 Run1 于 2026-11-05 10:57:01 UTC 在 **C58** 启动，没有用子集 filter 替代。实际结果为 **697 tests run：696 passed、1 failed、66 skipped，原入口 exit 100**。唯一失败是 `native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`，首次及一次原 retry 共两次失败尝试，都在探测 Agentd control socket 时遇到 `path must be shorter than SUN_LEN`；原工作区 temp root 使 socket 路径达到 140 字节。保留[完整 Run1 日志](../publication/native-evidence/four-package-original-test.log)及[环境路径诊断](../product_recovery/socket-path-environment-review.json)，没有删掉失败或更改测试断言。

Run1 还暴露报告配置问题：实际 nextest 0.9.103 的 `local` profile 未继承 `default.junit.path`，所以没有生成原生 JUnit，也没有 Run1 的正式 59 项 XML 审计。先前关于该字段继承的推断已经纠正，见[版本源码与实际配置更正](../product_recovery/nextest-0.9.103-junit-correction.json)。不从 stdout 合成 XML。

**Run2 仍在同一 C58/tree 上完成 697/697 passed（1 slow）、66 skipped，原入口 exit 0，外层实际耗时 39.174 秒**；执行前后源码身份相同且 clean。Run2 使用短 temp root `/tmp/a9f4ebc7` 并启用明确的原生 JUnit 输出；原 package/profile、筛选范围、timeout/retry、测试线程和断言不变。[实际运行回执](../publication/native-evidence/four-package-run2.json)、[完整原日志](../publication/native-evidence/four-package-run2.log)和[原生 JUnit](../publication/native-evidence/four-package-run2.junit.xml)已取回；日志与 XML 的字节数及 SHA-256 均精确匹配原回执。

原 scoped Cargo metadata 保留为 [gzip 原件](../publication/native-evidence/run2-original-scoped-metadata.json.gz)，解压得到 942,439 字节，SHA-256 为 `46c44dc18560eee9f3ecc3ab72a4b7389b61a637b4c9b924210c377f61e3f988`，与实际 Run2 收据和[metadata 原始命令回执](../publication/native-evidence/run2-original-scoped-metadata.json.receipt)一致。[仅启用报告的 TOML](../publication/native-evidence/report-only.nextest.toml)只设置原 `local` profile 的 JUnit 输出路径。发布保留原 gzip，避免再复制同一份 942 KB 明文。

[原生覆盖审计](../publication/native-evidence/required-tests.run2.report.json)记录 XML 697 cases、必要用例 **59/59 clean、0 flaky**。[独立原始运行审计](../product_recovery/native_audit/independent-native-run-audit.json)的 59 项身份、命令、字节与集合一致性检查全部通过（含原始 scoped metadata 补核）：21 个测试 binary 中的 697 个唯一测试全部 PASS，stdout 与原生 XML 的执行集合完全一致，无失败、重试或 flaky；两轮选择的 697 个测试集合也相同。必要覆盖为 **59 = 原 49 + e65 原 10**，见[扩展清单](../product_recovery/required-tests.with-e65.md)。XML 只包含实际运行的 697 个 case；**66 skipped 由原 runner 日志保留，不能因 XML 中没有 skipped case 就写成全套零跳过**。C1 的输入等价和 strict 单独记录，测试执行身份仍为 C58。

### 本轮已经完成的事实更正

`MODULES.json`、`SOURCE_BINDINGS.json`、`MODULE_DOCS.json` 中，objective.compiler 和 cognitive.store 的 `production_implementation` 统一改为 `false`，与两份 Map 原来就存在的否定资格一致。`PLAN_AUDIT.json` 的 `moduleStatusFacts.production_implementation` 从 2 改为 0。该修复没有撤销一个已经证明的生产资格，也没有将任何 false 改成 true。

原状态测试只比较三份投影，未识别它们共同偏离 Map。修复把 Map 纳入既有一致性测试：加强后的测试在更正前失败，更正后通过；独立复核也确认 Map 原字节保持不变。`PLAN_AUDIT.json` 的历史 V8 子集 `implementedModuleCount=14` 有自己的明确范围，保持 14，不能因全量审计覆盖 40 模块而改成 40。见[状态更正补丁](module-status-consistency.patch)与[实际 RED/GREEN 回执](validation.json)。

### 本轮源码改动的实际范围

| 改动 | 已确认的源码事实 | 尚不代表 |
| --- | --- | --- |
| Desktop issuer donor `facba0d32c1cd0e8163a6186d7ba91fa311f2e2e` | Agentd Desktop policy CAS 在同一边界持有原 issuer 与确切 writer 的 live token，CAS 前后检查原租约 epoch/期限 | 真实目标主机 authority/custody 或 Windows hostile ACL 验收 |
| ConPTY donor `345dd470a64783b54f45c522ac8675435d204738` | handle clone 失败明确转换为 `io::Error` 并保留错误上下文 | ConPTY 新生命周期机制、原生 UI 完成或 Windows 平台资格 |
| 产品恢复补丁，来源 `78668ea2837a16811b922dfcfbc438f3d8a98f5e` | 33 文件、11 个集成 cohort；完整 RunSnapshot、canonical admission、bound mutation、durable terminal ACK、无重复 dispatch 恢复、完整消息与真实 host 测试路径 | Agentd 自身进程重启全恢复、真实外部 provider 或默认七 owner 生产组合 |
| 原 Map 校验器修复 | 9 类旧 claim 别名、所有原显式源码 pin 和嵌套 manifest 写回均受检；旧 true 不能因导航重绑获续期 | 给任何产品模块新授予执行或生产资格 |
| 安全导航 helper | 保存历史 sourceBase/候选记录，实际检查 40 张 Map、刷新 26 张，追加前像账本；提交后另跑原 strict | 给任何模块新增产品执行、生产或 release 资格 |

源码与独立审查证据：[Desktop/ConPTY 应用审查](../lifecycle_review/independent-patch-application.json)、[产品恢复补丁清单](../product_recovery/PARENT-UPDATE.json)、[产品恢复独立审查](../lifecycle_review/recovery-review.json)、[最终 pin 守卫审查](FINAL-PIN-GUARD-REVIEW.json)。产品补丁保留原有溢出、取消、owner-loss、request/dispatch/turn 绑定和恢复断言；新增进程测试复用原进程隔离机制。

产品恢复集成选择了相关的 33 文件增量，保留统一基线已有的严格校验；它不表示全量合入 #4846 的 19 个提交。新增恢复用例使用实际 Agentd/App Server/worker 进程路径和受控 provider fixture；真实外部 provider、硬件、quota 与默认 owner 组合仍需对应证据。

兼容边界必须保留：`run.lifecycle` 能力版本由 1.1 升到 1.2，`AGENTD_CONTROL_SCHEMA_VERSION` 保持 2；durable fingerprint 从 V2 到 V3 包含完整 snapshot，旧 V2 journal 不会自动迁移为已认证 V3；CLI 由 run-id 输入改为完整 snapshot JSON，不能通过当前 owner 查询伪造旧 admission。新进程恢复测试覆盖新 worker 与原 Agentd 之间的恢复及 lifecycle 变化；它们不能证明 Agentd 自身进程重启后的全部 durable coordinator 恢复。

## 二、全量分组索引

| 模块组 | 模块数 | 操作映射数 | 本轮推进重点 |
| --- | ---: | ---: | --- |
| 契约与内核 | 5 | 41 | 固定根/契约核对；authority 的 Agentd 使用边界；旧证据守卫 |
| 执行运行时 | 4 | 28 | Agentd 完整身份与恢复；保留 supervisor/fleet/Codex 的真实部署门槛 |
| 身份、密钥与推理 | 4 | 14 | worker 物理调用恢复和 terminal；真实经济 quota、模型/device 仍待闭合 |
| 目标与决策 | 8 | 85 | canonical 调用与上下文边界；纠正 Objective 资格投影 |
| 认知与记忆 | 7 | 52 | 纠正 Store 资格投影；保留当前性、删除、旧代及 provider 门槛 |
| 学习与演化 | 5 | 101 | 保留原始 provenance；默认学习环与自迭代触发仍待闭合 |
| 外部器官与交互 | 5 | 17 | 核对真实产品边与外部依赖；无新增外部效果验收 |
| 全局控制与工程 | 2 | 31 | 完整 Control lifecycle 仍未闭合；工程证据与资格一致性推进 |

以下每项都附固定基线 Map 链接、实际解析根、owner、操作数及 caller/writer 原字段。所述“本轮变化”限于源码/元数据层；执行结果另见末尾回执表。所有模块共同保持 `productionImplementation=false`，独立语义/安全审查、目标主机、运行接受及发布门槛不会被本报告替代。

原 Map 中关于“当前精确候选”的门槛包含不同层次：**源码导航部分已在 C1 通过**；对应模块完整产品组合、独立接受和平台条件，只有本报告明确列出的执行证据才能支持相应范围。helper 没有改写历史 gap 数组，因此逐项保留的产品/候选门槛不表示本轮 40-map strict 尚未执行，也不能仅凭四包 suite 就把所有模块的完整验收写成通过。

## 契约与内核

### 01. platform.types

**固定根：** `codex-rs/hepta-types`。**Owner：** `kernel-contracts`。**操作：** 11 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/platform.types/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 通用有界值、标识符、规范摘要、定点数、数值配置与注册契约。11 项操作有源码映射；产品 caller 尚未组合，writer 未建立。契约注册存在不等于所有消费者已经迁移。
- **本轮真实变化：** 完成固定源码根、操作入口及资格字段核对；本轮没有修改 hepta-types 的运行时代码。Agent 协议新增绑定字段属于 Agentd/worker 组合改动，不能直接算作本模块全部契约闭合。
- **仍需闭合：** 补 RandomStreamManifestV1、ExternalSystemManifestV1、SensorCalibrationManifestV1 的原生源码；执行完整消费者编译矩阵、认证产品组合及该候选的 Lane A/合并候选验证。

登记状态：caller=`not_composed`；writer=`not_established`。

### 02. platform.wire

**固定根：** `codex-rs/hepta-wire`。**Owner：** `kernel-contracts`。**操作：** 5 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/platform.wire/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 版本化 wire 编解码、协商、schema admission 与流式解码。只读 caller 和已注册端口适配器已在源码中组合；production writer 未建立。
- **本轮真实变化：** 核对 5 项操作；发现 1 个旧 sourceObjects 对象，纳入最终导航刷新清单；本轮未改变 hepta-wire 的协议运行时代码。
- **仍需闭合：** 将 HPTN 协商与 HPTA 帧绑定到选定的认证生产 transport/session；新增领域 codec 必须逐个注册并验收；补当前精确候选与确定性合并验证。

登记状态：caller=`source_composed_read_only_and_registered_port_adapters`；writer=`not_established`。

### 03. kernel.authority

**固定根：** `codex-rs/hepta-contracts`。**Owner：** `security-authority`。**操作：** 9 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/kernel.authority/IMPLEMENTATION_MAP.json)。

- **职责与基线：** FinalUseAuthority、授权租约、撤销前沿、最终使用验证和授权见证。Fleet、注册 Bao host 和 Agentd browser 的源码 caller 已组合；authority owner 有实现，仍未激活。
- **本轮真实变化：** 核对 9 项操作与 5 个旧对象。本轮在 Agentd 的使用边界加强 Desktop issuer 与 writer 的联合 fence：持有原 issuer 租约和确切 writer，CAS 前后重验 epoch/期限；没有改动 hepta-contracts owner 的生产资格。
- **仍需闭合：** 剩余 ModulePort 必须落在真实单一 authority owner；Bao final-use host 仍需命名产品 caller；还需生产前沿存储、可信时钟、HSM/KMS custody/轮换、Fleet 撤销传播及目标端收敛测量。

登记状态：caller=`source_composed_runtime_fleet_registered_bao_host_and_agentd_browser_not_product_activated`；writer=`authority_owner_source_implemented_not_activated`。

### 04. kernel.operations

**固定根：** `codex-rs/hepta-operations`。**Owner：** `durability-kernel`。**操作：** 10 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/kernel.operations/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 持久 operation intent、prepare、outbox claim、授权 dispatch 与 terminal 对账。Agentd 生命周期 caller 已在源码组合，持久 cognitive-store owner 有实现，外部 authority 激活待定。
- **本轮真实变化：** 核对 10 项操作；记录 9 个 sourceObjects 漂移。本轮没有改 operation owner；新的导航守卫保证旧执行证明不能随 blob 刷新转为当前候选资格。
- **仍需闭合：** 每个 effect destination 都要有目的端去重、实际 apply 及可信 terminal observation；补崩溃/掉电/存储验收，设计有界 segment/checkpoint compaction，并重新取得当前候选执行回执。

登记状态：caller=`agentd_runtime_lifecycle_source_composed_external_authority_activation_pending`；writer=`durable_cognitive_store_owner_implemented_not_activated`。

### 05. kernel.evidence

**固定根：** `codex-rs/hepta-evidence`。**Owner：** `qualification-plane`。**操作：** 6 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 追加 receipt、查询 claim、验证链、恢复快照和 provider effect intent/lookup 对账。Agentd caller 和认证 writer 已存在，但受配置门控；历史 source proof 不能覆盖已变源码。
- **本轮真实变化：** 核对 6 项操作，发现 1 个旧对象；本轮未修改 evidence owner，增加了防止历史资格随导航迁移的校验。
- **仍需闭合：** 补当前精确候选验收；部署外部单调 CAS/latest-frontier backend 和备份发布仪式；再取得独立接受、canary、promotion/release 证据。

登记状态：caller=`agentd_composed_config_gated`；writer=`agentd_authenticated_writer_established_config_gated`。

## 执行运行时

### 06. runtime.supervisor

**固定根：** `codex-rs/hepta-supervisor`。**Owner：** `runtime-control`。**操作：** 11 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 实例启动、健康监测、drain/stop/kill/restart，以及签名升级、回滚和恢复。11 项操作有源码映射；Map 的产品 caller/writer 均未建立。repositoryControlledGaps 为空仅表示该数组没有列项。
- **本轮真实变化：** 完成固定源码与映射核对；本轮未新增 supervisor 运行时代码。
- **仍需闭合：** 绑定实际部署的 supervisord 二进制、主机身份和外部 grant/H7 verifier 配置；实测启动、watchdog、typed Agentd drain、受限重启与签名恢复；验证外部发布策略分发及运行接受。

登记状态：caller=`not_composed`；writer=`not_established`。

### 07. runtime.fleet

**固定根：** `codex-rs/hepta-fleet`。**Owner：** `fleet-runtime`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 主机 admission、容量 allocation 和租约 renew/revoke。3 项操作有实现入口；生产 caller/writer 未建立。
- **本轮真实变化：** 完成固定根和操作核对；本轮没有修改 Fleet owner，也没有把内存 lease 当作真实容量证明。
- **仍需闭合：** 把内存 lease 组件接到 supervisor 所有的持久 FleetRegistry grant/fence 和真实 capacity observer；验证已登记主机的容量、非测试 grant 强制执行、分区及租约过期。

登记状态：caller=`not_composed`；writer=`not_established`。

### 08. runtime.agentd

**固定根：** `codex-rs/hepta-agentd`。**Owner：** `agent-runtime`。**操作：** 10 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json)。

- **职责与基线：** daemon 运行协调、RunStart admission、取消/上下文、运行生命周期与 Neuron owner 接口。基线已有 daemon lifecycle 与持久 RunStart projection 的源码组合；Map 仍标注 physical Codex caller 待闭合，writer 未建立。
- **本轮真实变化：** 本轮源码集成的重点之一：加入完整 RunSnapshot 的 bound API、同锁 snapshot/receipt 校验、run-id 复用 ABA 拒绝、canonical RunStart 当前信任与期限绑定；Desktop issuer/writer 联合 fence 保留原 issuer 身份，C58 进一步核对联合边界内实际返回的两份 lease 与原始登记完全相同。原有溢出原子性和关闭运行记账断言保留。
- **仍需闭合：** 统一候选必须执行真实 Agentd/App Server 开始、取消、终态及 lost-ACK 恢复回归；部署 socket/process/generation 身份、backpressure/drain/restart 需目标主机证据。新 worker 恢复源码不等于 Agentd 自身重启后的持久协调已完成；Neuron 默认 daemon 组合仍是独立依赖。

登记状态：caller=`daemon_lifecycle_and_durable_run_start_projection_composed_physical_codex_pending`；writer=`not_established`。

### 09. runtime.codex

**固定根：** `codex-rs/app-server`、`codex-rs/hepta-codex-adapter`。**Owner：** `codex-integration`。**操作：** 4 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/runtime.codex/IMPLEMENTATION_MAP.json)。

- **职责与基线：** App Server thread/turn、tool dispatch 和 delivery observation 的适配边界。已有组合候选与 App Server owner；当前精确候选资格待补。
- **本轮真实变化：** 核对 4 项操作和 4 个旧对象；保留原有严格 request/dispatch/turn、重复 turn 及 owner-loss 恢复边界。worker 侧新增恢复与完整输出处理，并以显式同构建 Arg0DispatchPaths 启动真实测试 host；共享 ConPTY 改动仅为 handle clone 错误转换。
- **仍需闭合：** 补真实 provider terminal stream、认证 Agentd/App Server process/socket/generation、外部 tool terminal/lost-ACK；App Server 历史丢失时须有独立 unknown 对账或 quarantine。Final-use endpoint、custody、时间/撤销及反回滚恢复均须真实部署证据。

登记状态：caller=`composed_candidate_exact_head_qualification_pending`；writer=`existing_app_server_owner`。

## 身份、密钥与推理

### 10. auth.authbus

**固定根：** `codex-rs/hepta-authbus`、`codex-rs/hepta-authbus-p1-3-qualification`。**Owner：** `identity-access`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/auth.authbus/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 认证、AuthBus message admission 与 enqueue。3 项操作有映射；认证产品 caller 与 owner writer 尚未建立。
- **本轮真实变化：** 完成固定根和映射核对；Agentd RunStart consumer 的当前信任重验有所加强，但本轮没有修改 AuthBus owner 或闭合所有消费者。
- **仍需闭合：** 每项操作绑定真实认证 consumer callsite 和 owner store；取得当前精确候选/合并候选验证、独立语义审查和目标端产品执行证据。

登记状态：caller=`not_composed`；writer=`not_established`。

### 11. secrets.heptabao

**固定根：** `external/HeptaBao`、`codex-rs/hepta-bao-adapter`。**Owner：** `secrets-platform`。**操作：** 4 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json)。

- **职责与基线：** HeptaBao/OpenBao KV v2 消费、binding，以及租约 prepare/reconcile。4 项操作有入口；产品 caller 和持久 host owner 未建立，provider-native 动态租约兼容仍为阻断的 partial。
- **本轮真实变化：** 完成 external/HeptaBao 与 adapter 的固定根核对；本轮没有更改真实密钥服务、租约发放或生产配置。
- **仍需闭合：** 先确认精确 endpoint 合同，再实现/验收动态 issue/renew/revoke；把 lease owner 接入认证产品 caller 和持久 host；完成崩溃/故障及候选资格。

登记状态：caller=`not_composed`；writer=`not_established`。

### 12. inference.control

**固定根：** `codex-rs/hepta-infer-core`、`codex-rs/hepta-inferd`。**Owner：** `inference-platform`。**操作：** 4 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/inference.control/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 请求资源预留、调度、取消和结算。4 项操作有映射；当前原生策略只保留本地 in-flight run slot，尚不代表真实经济配额或硬件容量。
- **本轮真实变化：** 完成固定源码核对；worker/Agentd 侧终态发布和期限保持得到加强，但本轮未新增 inference.control 的经济配额 authority。
- **仍需闭合：** 接入真实 quota/hardware-capacity authority；进程丢失后认证恢复 provider terminal 与 usage；64 MiB journal 还需同 owner 下有界归档/保留，不能截断已确认历史。

登记状态：caller=`not_composed`；writer=`not_established`。

### 13. inference.worker

**固定根：** `codex-rs/hepta-infer-worker-host`。**Owner：** `inference-platform`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/inference.worker/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 模型 load/run/unload、原生 worker host 与受控物理调用。3 项顶层操作有映射；基线仍未建立生产 caller/writer。
- **本轮真实变化：** 本轮加入 durable native settlement 后的 Agentd terminal 发布、旧 snapshot/revision 拒绝、非 redispatch 恢复、严格完整消息聚合、完整 CLI snapshot 输入及进程隔离回归；C58 进一步合并 turn/completed 携带的消息，按 item ID 保留既有多条输出并在有界检查之后授予 terminal 状态。已持久化或已 dispatch 状态不得重启物理请求；文字输出不能充当 terminal 或 usage。
- **仍需闭合：** 最终候选需跑完整原生套件及真实进程回归。另需实际 weights/tokenizer/runtime/device 和 memory grant、隔离控制通道、OOM/device reset/load-kill；provider unknown 或缺 token usage 仍需可信对账，不能推定零消耗或安全重放。

登记状态：caller=`not_composed`；writer=`not_established`。

## 目标与决策

### 14. objective.compiler

**固定根：** `codex-rs/hepta-objective`。**Owner：** `intelligence-platform`。**操作：** 10 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/objective.compiler/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Objective envelope 解码、规范 intent digest、结构/可行性验证、admission 与编译。无状态 owner；认证 Agentd caller 已在源码组合，但未激活，Map 的 productionImplementation 本来就是 false。
- **本轮真实变化：** 将三个 registry projection 中错误的 production_implementation=true 更正为 false；核对 10 项操作和 3 个旧对象。Agentd canonical RunStart consumer 的真实绑定加强，Objective owner 源码未改。
- **仍需闭合：** 取得同一最终候选的 exact-head 与确定性合并成功回执；运行命名主机 Objective 测量及 Agentd crash/restart/backpressure；独立产品/目标主机资格未获替代。

登记状态：caller=`source_composed_authenticated_agentd_not_activated`；writer=`not_applicable_stateless`。

### 15. utility.ndu

**固定根：** `codex-rs/hepta-ndu`。**Owner：** `intelligence-platform`。**操作：** 12 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/utility.ndu/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 候选效用评估、偏好目标和回归求解、系数 admission、持久投影及认证 owner。request-local 只读使用已建立；认证 owner 和 durable writer 为未选择、未激活的源码候选。
- **本轮真实变化：** 核对 12 项操作、2 个旧对象；本轮没有修改效用算法、选择生产随机系数或宣称净收益改善。
- **仍需闭合：** 命名 bootstrap 选择 NduProjectionStoreV1 并接当前 fence/revocation；实际独立 producer/evaluator 的收敛与适定性证据、生产系数选择及 withdrawal frontier；补 durable reopen、容量和命名主机延迟/CPU/RSS/文件系统测量。

登记状态：caller=`request_local_read_only_established_authenticated_owner_source_candidate_not_product_composed`；writer=`durable_writer_source_candidate_not_selected_or_activated`。

### 16. neuron.runtime

**固定根：** `codex-rs/hepta-neuron`。**Owner：** `learning-platform`。**操作：** 9 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Neuron tick、模型特征端口、稀疏日志、anchor witness、plasticity 统计与删除重建。AgentdNeuronOwner 已编译的源码边界存在，但未接 daemon 生命周期；durable V1 owner/witness 未激活。
- **本轮真实变化：** 核对 9 项操作；本轮没有把新的 Agentd recovery API 视作 Neuron 默认生命周期完成，也未迁移 V1 journal 为 V2。
- **仍需闭合：** 构造真实 current inference.control feature port、selected artifact 和 witness 生命周期；V2 promotion 要独立版本化持久迁移；验证 rollover/anchor、lost-witness ACK、校准/OOD、资源、删除不复活与未来窗口消融。

登记状态：caller=`agentd_owner_source_compiled_not_daemon_lifecycle_composed`；writer=`durable_v1_owner_external_witness_source_implemented_not_activated`。

### 17. intuition.policy

**固定根：** `codex-rs/hepta-intuition`。**Owner：** `intelligence-platform`。**操作：** 2 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/intuition.policy/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 有校准约束的 intuition policy 决策 V1/V2。2 项操作有源码入口；认证 consumer 与 owner store 未建立。
- **本轮真实变化：** 完成固定根、操作及 false 资格边界核对；本轮未更改 policy 运行时代码。
- **仍需闭合：** 接入认证消费者与 owner store；验证当前候选和确定性合并；补独立语义审查、真实产品/主机及运行接受。

登记状态：caller=`not_composed`；writer=`not_established`。

### 18. prompt.registry

**固定根：** `codex-rs/hepta-prompt-registry`。**Owner：** `intelligence-platform`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/prompt.registry/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Prompt realization 注册、版本兼容读取和 registry owner。3 项操作有入口；产品 caller/writer 未建立。
- **本轮真实变化：** 完成固定源码核对；未将 knowledge.graph 的 prompt-factor 源码组合借作本模块的 durability/activation 资格。
- **仍需闭合：** 绑定认证 consumer、持久 owner、版本兼容与撤销生命周期；当前候选执行和目标端资格未闭合。

登记状态：caller=`not_composed`；writer=`not_established`。

### 19. prompt.optimizer

**固定根：** `codex-rs/hepta-prompt-optimizer`。**Owner：** `intelligence-platform`。**操作：** 2 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/prompt.optimizer/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Prompt 优化及本地 shadow 计算。2 项操作有入口；产品 caller 和 writer 未建立。
- **本轮真实变化：** 完成映射核对；本轮没有修改优化算法、选择生产 prompt 或宣称实测效用提升。
- **仍需闭合：** 接入认证调用与 owner store；验证知识图投影、registry 版本和真实 delivery/outcome 的组合边界；补精确候选、独立接受及目标端证据。

登记状态：caller=`not_composed`；writer=`not_established`。

### 20. context.compiler

**固定根：** `codex-rs/hepta-context-compiler`。**Owner：** `intelligence-platform`。**操作：** 12 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/context.compiler/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 上下文编译、admission、精确 serialization/attachment、delivery preparation 与 observation。legacy V1 只读路径已组合；verified V2 尚未接入一个完整认证产品 caller，writer 未建立。
- **本轮真实变化：** 核对 12 项操作和 1 个旧对象；本轮 canonical RunStart/worker 绑定更严格，但没有把它等同于 V2 payload 最终使用授权的真实 provider 闭合。
- **仍需闭合：** 绑定精确 tokenizer/serializer/template/tool schema、authoritative verifier 与 provider owner；physical send 前同一 effect 仪式消费 current final-use authority，并绑定 payload 和 ProviderRequestBinding；持久化 attempt/terminal 并验证撤销、adapter/进程死亡、unknown 与 retry 对账。

登记状态：caller=`legacy_v1_read_only_source_composed_verified_v2_not_composed`；writer=`not_established`。

### 21. intelligence.control

**固定根：** `codex-rs/hepta-intelligence`。**Owner：** `intelligence-platform`。**操作：** 35 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/intelligence.control/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Objective 到 candidate、决策、上下文和学习反馈的组合门面，不自建 writer。35 项操作有映射；已有命名 Agentd runner，默认 daemon route 仍未形成全闭合；Decision/Outcome 仍有进程丢失边界。
- **本轮真实变化：** 在 Agentd/worker 的实际 caller 文件中强化 canonical ObjectiveStart→RunStart 的完整身份与当前 authority、同锁 bound snapshot、持久结算后 ACK 及恢复链；本模块 owner crate 没有新增默认七 owner 全量启动。
- **仍需闭合：** Decision/Outcome append 与 ambiguous append recovery 须跨 Agentd 进程丢失；PendingIntelligenceLedgerAppendV1 仍是内存 replay。补真实 lost-ACK、依赖故障、重启/撤销竞态 E2E，以及硬资源终止；spawn_blocking 的迟到结果丢弃不等于停止物理计算。

登记状态：caller=`named_agentd_runner_present_daemon_route_not_composed`；writer=`none_by_design_composition_facade`。

## 认知与记忆

### 22. cognitive.types

**固定根：** `codex-rs/hepta-cognitive-types`。**Owner：** `cognitive-platform`。**操作：** 15 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/cognitive.types/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 认知快照、MemoryEvent、binding、engram/synapse、cue/recall、outcome、plasticity 和忘记传播的规范 V1 类型。15 项操作有入口；认证产品 consumer/writer 未建立，注册投影不代表所有 native consumer 已迁移。
- **本轮真实变化：** 完成固定根与 canonical 类型映射核对；本轮未改变认知 schema 或消费者的版本承诺。
- **仍需闭合：** 消费者通过显式 canonical V1 adapter 迁移并绑定精确 wire schema；完成 package/all-target/strict lint 及确定性合并验证，随后才谈产品资格。

登记状态：caller=`not_composed`；writer=`not_established`。

### 23. cognitive.store

**固定根：** `codex-rs/hepta-cognitive-store`。**Owner：** `cognitive-platform`。**操作：** 12 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/cognitive.store/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 认知语义 revision、持久 owner、快照/恢复、sealed mutation capability 及 shared-experience grant/read/revoke。正常 Agentd runtime capability 的源码组合存在；同事务 provenance writer 已绑定但未取得当前资格，外部 bootstrap 待补。
- **本轮真实变化：** 将三个 registry projection 的错误 production_implementation=true 改为 false；核对 12 项操作、9 个旧对象。保留原有 live-authority、duplicate/restart 和语义失败测试边界，没有给 Store 增发生产资格。
- **仍需闭合：** 最终候选需 child-process crash/reopen、同事务语义失败、response-loss/restart 去重、撤销和 256/16384 PERF-DURABLE；host 必须独立提供 current-cut witness 与 live authority。还需 ancestry-safe 长期 retention；逻辑 tombstone 不等于物理/备份删除或 model unlearning。

登记状态：caller=`normal_agentd_runtime_capability_composed_external_bootstrap_pending`；writer=`sealed_same_transaction_provenance_writer_source_bound_qualification_pending`。

### 24. cognitive.read

**固定根：** `codex-rs/hepta-cognitive-read`。**Owner：** `cognitive-platform`。**操作：** 6 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/cognitive.read/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 权威读取、持久快照、final-use 重验和 legacy→canonical shadow 适配。本地 host caller 已组合，模块只读；durable SQLite kind capability 当前限定 Fact。
- **本轮真实变化：** 核对 6 项操作、5 个旧对象；真实 native worker 的原有 fresh-context、tombstone/correction 和 owner-generation 测试断言保留，测试 host 改为显式同构建 helper 路径。
- **仍需闭合：** 这些源码用例仍需最终候选实际执行；补 expiry/rollback/stale generation 与 p50/p95/p99、CPU/RSS/SQLite；canonical source-revision 归属未完全等价，physical attachment 前仍要当前 final-use snapshot 重验。

登记状态：caller=`composed_local_host`；writer=`not_applicable_read_only`。

### 25. memory.retrieval

**固定根：** `codex-rs/hepta-memory-retrieval`。**Owner：** `cognitive-platform`。**操作：** 9 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json)。

- **职责与基线：** cue 编译、候选并集、engram settlement、召回与 assignment observation。显式 profile 已在源码组合；hnmf-required 缺真实 context provider 时启动拒绝；未获产品资格。
- **本轮真实变化：** 核对 9 项操作；本轮没有制造替代 provider、开放 Vector 通道或把词法/graph/ranker 分数改名为向量证据。
- **仍需闭合：** 独立认证的 CurrentMemoryRetrievalContext 必须进入实际 Agentd profile；真实 encoder/vector-index owner 才能开放 Vector；在批准主机复跑 SQLite/currentness 和 512 candidate/4096 node/32768 synapse/four-step 测量。因果效用还需独立 propensity/outcome。

登记状态：caller=`source_composed_explicit_profile_not_product_qualified`；writer=`not_established`。

### 26. memory.federation

**固定根：** `codex-rs/hepta-memory-federation`。**Owner：** `cognitive-platform`。**操作：** 2 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/memory.federation/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 跨 memory owner 的一次性只读 federation 和取消观察。组合候选待执行，只读、不设 writer。
- **本轮真实变化：** 核对 2 项操作、2 个旧对象；本轮未扩大为已部署的跨主机 federation。
- **仍需闭合：** 完整 focused/package/product/all-target/lint 与确定性合并；如需规范取消观测，补目前 future-drop 之外的明确 attribution/receipt；跨 process/host 时验证认证 transport。

登记状态：caller=`composed_candidate_pending_execution`；writer=`not_applicable_read_only`。

### 27. knowledge.graph

**固定根：** `codex-rs/hepta-kg`。**Owner：** `knowledge-graph`。**操作：** 5 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 完整 generation 构建、增量 delta、发布/查询及 prompt-factor 投影。Cognitive read 与默认 Agentd writer/Prompt optimizer 的候选组合已有源码，精确候选资格待补。
- **本轮真实变化：** 核对 5 项操作、1 个旧对象；本轮未改 durable writer 的 generation 选择或替 Prompt registry 签发资格。
- **仍需闭合：** 当前默认 writer 按每次逻辑 mutation 做有界完整重建；是否改用已存在的增量算法要由 PERF-LIBRARY/目标主机结果决定；Prompt registry durability/activation 独立关闭。

登记状态：caller=`composed_cognitive_read_default_agentd_write_and_prompt_optimizer_pending_exact_head`；writer=`candidate_agentd_default_fail_closed_pending_exact_head`。

### 28. compact.engine

**固定根：** `codex-rs/hepta-compact-engine`。**Owner：** `cognitive-platform`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/compact.engine/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 压缩、构建 qualified compaction candidate 与压缩证明。3 项操作有源码入口；认证 caller/writer 未建立。
- **本轮真实变化：** 完成固定根和映射核对；本轮未把旧摘要或逻辑删除提升为可执行的压缩/遗忘资格。
- **仍需闭合：** 绑定认证消费者和 owner store；候选与确定性合并验证、独立语义与真实产品/主机资格待补。

登记状态：caller=`not_composed`；writer=`not_established`。

## 学习与演化

### 29. learning.ledger

**固定根：** `codex-rs/hepta-learning-ledger`。**Owner：** `learning-platform`。**操作：** 17 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/learning.ledger/IMPLEMENTATION_MAP.json)。

- **职责与基线：** RunStart、Decision/Outcome/Credit、dataset freeze、unlearning、witness/trust 与 journal owner。qualification consumer 已组合；真实 live product caller、物理独占 writer/host 尚未建立。
- **本轮真实变化：** 核对 17 项操作、2 个旧对象；Agentd canonical consumer 加入原始 admission snapshot 与当前 trust 的绑定，dispatch 后 recovery 保持不可重新派发。ledger crate 本身未修改，旧记录不因投影而变为当前认证证据。
- **仍需闭合：** 命名物理 writer/目录 owner、独立 trust/root custody/witness、掉电/文件系统与长期增长；真实独立 outcome 和未来窗口、dataset withdrawal 后代撤销与 rebuild handoff；Agentd 进程丢失的 durable 协调仍待闭合。

登记状态：caller=`qualification_consumer_composed_live_product_not_established`；writer=`source_implemented_host_not_established`。

### 30. learning.operator

**固定根：** `codex-rs/hepta-bellman-operator`。**Owner：** `learning-platform`。**操作：** 20 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/learning.operator/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Bellman target/参考求值、verified tabular/world-model 训练、预测和 shared terminal-cell 训练。显式只读 consumer 已组合，默认完整学习环缺失，writer 未建立。
- **本轮真实变化：** 核对 20 项操作、1 个旧对象；本轮未改变训练数学、默认学习触发或宣称 D-B/净效用改善。
- **仍需闭合：** 组合 dataset freeze→verified training→independent evaluation→selection→新进程 load shadow 的默认闭环；在统一候选执行训练与独立证据回归，补目标主机训练/推理、未来窗口实效和科学审查。

登记状态：caller=`explicit_read_consumer_composed_default_learning_loop_absent`；writer=`not_established`。

### 31. learning.eval

**固定根：** `codex-rs/hepta-intelligence-eval`。**Owner：** `learning-platform`。**操作：** 12 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/learning.eval/IMPLEMENTATION_MAP.json)。

- **职责与基线：** OPE、聚类区间、序贯/时间 holdout、product qualification receipt 与带签名接受决策。evaluated shadow 已消费 product qualification receipt；sink 的目标主机持久绑定仍未证明。
- **本轮真实变化：** 核对 12 项操作、4 个旧对象；保留历史 sourceBase/evaluation provenance，导航迁移不生成新的独立评估或接受结论。
- **仍需闭合：** 最终候选与 ordered-parent synthetic merge 回执；sink 与 final-holdout namespace 的真实认证/custody，真正未来日历窗口、独立 snapshot、retention/change-point/privacy/power/unlearning；shared filesystem 场景另做跨主机存储资格。

登记状态：caller=`product_qualification_receipt_consumed_by_evaluated_shadow`；writer=`qualification_evidence_sink_contract_composed_target_host_binding_unproved`。

### 32. learning.artifacts

**固定根：** `codex-rs/hepta-learning-artifacts`。**Owner：** `learning-platform`。**操作：** 25 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 候选 payload/manifest、registry/withdrawal、publication、fence、owner recovery 与独立 selection/load。显式 read 与命名 writer service 已源码组合，owner 源码资格和真实部署待补。
- **本轮真实变化：** 核对 25 项操作；本轮未实际选择或激活新学习产物。
- **仍需闭合：** 在统一候选执行 source binding/build、owner recovery、current-head anchor 与撤销/恢复；补生产 owner/selector trust、掉电/目标主机和独立运行接受。

登记状态：caller=`explicit_read_and_writer_service_composed`；writer=`named_owner_service_composed_source_qualification_pending`。

### 33. learning.plasticity

**固定根：** `codex-rs/hepta-plasticity`。**Owner：** `learning-platform`。**操作：** 27 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 参数/拓扑候选、独立 admission、持久 proposal registry、anchor/fence 和 structural canary/rollback。Agentd process bootstrap、命名 learning producer 和 owner 有源码；真实 self-iteration trigger 未组合，拓扑 journal/执行器未获目标主机资格。
- **本轮真实变化：** 核对 27 项操作、6 个旧对象；本轮未提交真实自迭代请求、变更 live topology 或开放公共 apply/recover。
- **仍需闭合：** control.engineering 的非测试协调器必须真实提交 frozen/independently evaluated 下一代请求；IterationEnvelopeV1 仍缺生产 caller。需独立回滚域中的 anchor/fence、descriptor/proposal lifetime 恢复、live telemetry 和强制故障 canary/rollback。

登记状态：caller=`agentd_process_bootstrap_and_named_learning_producer_source_composed_self_iteration_trigger_not_product_composed_or_target_host_qualified`；writer=`agentd_append_only_parameter_and_topology_anchor_fence_journal_plus_final_use_runtime_topology_executor_source_implemented_target_host_unproved`。

## 外部器官与交互

### 34. automation.taskflow

**固定根：** `codex-rs/hepta-automation`。**Owner：** `automation-platform`。**操作：** 4 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 持久 schedule、occurrence 物化/claim 与 TaskFlow step 执行。Agentd/App Server 与能力协商 Calendar V2 control 已组合；AutomationStore owner 建立，外部 effect caller 仍待补。
- **本轮真实变化：** 核对 4 项操作；本轮没有把空 repositoryControlledGaps 数组解释为真实外部效果完成。
- **仍需闭合：** 选定主机上的持久因果路径执行回执；独立 FinalUseAuthority signer/key/revocation 与每个已激活 effect 的真实 attested provider、terminal/reconciliation；IANA/tzdb provenance、DST 与多 scheduler 验收。

登记状态：caller=`agentd_app_server_and_capability_negotiated_calendar_v2_control_composed_external_effect_product_caller_pending`；writer=`automation_store_durable_schedule_occurrence_taskflow_owner_established`。

### 35. channel.matrix

**固定根：** `codex-rs/hepta-matrix-sdk`、`codex-rs/hepta-matrixd`。**Owner：** `channels-platform`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/channel.matrix/IMPLEMENTATION_MAP.json)。

- **职责与基线：** Matrix event admission、send prepare 和 send observation。3 项入口有映射，真实产品 caller/writer 未建立。
- **本轮真实变化：** 完成固定根和映射核对；本轮未连接实际 homeserver、用户/device 或发送消息。
- **仍需闭合：** 新 send-observer 必须并入既有 MatrixDurableStore transaction identity，不能另建 sender owner；真实 homeserver/encryption identity、sync/send callsites 和 rate limit/reconnect/redaction/restore 需验收。

登记状态：caller=`not_composed`；writer=`not_established`。

### 36. browser.servo

**固定根：** `apps/hepta-browser`、`third_party/servo-patches`。**Owner：** `browser-platform`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/browser.servo/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 浏览器 profile、页面 observation 和 navigate/action。3 项入口有映射，产品 caller/writer 未建立；无列出的仓内 gap 不代表实际 browser binary 已验收。
- **本轮真实变化：** 完成 apps/hepta-browser 与 servo-patches 固定根核对；本轮没有构建或签收可复现 Servo 产品二进制。
- **仍需闭合：** 可复现 Servo binary/patch digest、OS sandbox/profile/credential/network 强制执行，以及真实 navigation/download/business terminal observation。

登记状态：caller=`not_composed`；writer=`not_established`。

### 37. ui.control

**固定根：** `apps/hepta-control-ui`。**Owner：** `ui-platform`。**操作：** 3 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/ui.control/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 控制界面的 view 读取、请求提交和 stop 请求。3 项入口有映射，产品 caller/writer 未建立。
- **本轮真实变化：** 完成固定根核对；本轮没有新建已部署 Web UI 或授予控制权限。
- **仍需闭合：** 选择真实 Web framework/build artifact 和浏览器支持矩阵；认证/CSP/CSRF/WebSocket 部署拓扑；端到端 accessibility 与 backend 部署验收。

登记状态：caller=`not_composed`；writer=`not_established`。

### 38. ui.native

**固定根：** `apps/hepta-native`。**Owner：** `ui-platform`。**操作：** 4 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/ui.native/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 原生 shell 的 runtime 连接/展示、平台能力请求和 shell 更新。4 项入口有映射，产品 caller/writer 未建立。
- **本轮真实变化：** 完成固定根核对；共享 ConPTY 的错误适配修复不等于 native shell 平台托管、签名或 updater 验收。
- **仍需闭合：** 实际 native framework/platform matrix、代码签名/notarization/keychain/updater trust roots；打包进程的 crash/restart/accessibility/update rollback 需实测。

登记状态：caller=`not_composed`；writer=`not_established`。

## 全局控制与工程

### 39. control.runtime

**固定根：** `codex-rs/hepta-control-plane`。**Owner：** `runtime-control`。**操作：** 6 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/control.runtime/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 采集 control snapshot、prepare/finalize plan、绑定 NDU、请求 execution grant 与 PlannerJournal。6 项入口有映射，产品 caller 和 writer 都未组合；完整 Control lifecycle 没有闭合。
- **本轮真实变化：** 本轮保留公共 topology apply/recover 的拒绝边界与原测试；没有为计划/导航刷新放行 DENY_ALL，也没有合成 current lifecycle owner。
- **仍需闭合：** 每个操作落到认证 caller 与唯一 owner store；完整生命周期、当前授权与路由 CAS、独立 custody/批准链和执行/恢复语义必须先闭合，再谈目标端产品或生产资格。

登记状态：caller=`not_composed`；writer=`not_composed`。

### 40. control.engineering

**固定根：** `tools/hepta-engineering-control`。**Owner：** `developer-productivity`。**操作：** 25 项。[固定基线 Map](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55/docs/modules/control.engineering/IMPLEMENTATION_MAP.json)。

- **职责与基线：** 工程工作 envelope、候选生成、sandbox/mutation、integration decision、worker/queue/fence 和产品 receipt。仓内产品 caller 双 lane 与命名 owner 已有定义/组合；执行回执仍待当前候选验证，外部审查不能由 fixture 替代。
- **本轮真实变化：** 本轮形成可复核的 donor+recovery 源码集成、独立补丁审查、资格字段纠偏及原 pin 校验器修复；原 49 个必要原生用例已扩展为 59 个，JUnit 审计器用于检查完整套件覆盖。没有修改工程 owner 或代行外部批准。
- **仍需闭合：** 同源 exact-head/确定性合并、强 Linux/Bubblewrap、mutation/sandbox controller 回执；独立 custody、distributed lease/fence、immutable audit anchor、授权部署/回滚演练。CI reference fixture 不得被声明为真实外部完成或接受。

登记状态：caller=`repository_product_caller_dual_lane_defined_execution_pending`；writer=`named_product_owner_composed_execution_pending`。

## 三、sourceObjects 刷新与历史证据保留

下表是 **B0 上已经确定的导航漂移**，不是最终 C58/C1 的刷新结果。最终源码继续变化时，新候选的精确数量可能变化，必须以 helper 的实际计划/账本和 strict verifier 为准。

| 模块 | B0 旧对象数 | 模块 | B0 旧对象数 |
| --- | ---: | --- | ---: |
| `platform.wire` | 1 | `kernel.authority` | 5 |
| `kernel.operations` | 9 | `kernel.evidence` | 1 |
| `runtime.agentd` | 7 | `runtime.codex` | 4 |
| `objective.compiler` | 3 | `utility.ndu` | 2 |
| `context.compiler` | 1 | `intelligence.control` | 7 |
| `cognitive.store` | 9 | `cognitive.read` | 5 |
| `memory.federation` | 2 | `knowledge.graph` | 1 |
| `learning.ledger` | 2 | `learning.operator` | 1 |
| `learning.eval` | 4 | `learning.plasticity` | 6 |

合计 **18 张 / 70 个**。本轮采用独立导航观测，不重写历史执行的 `sourceBase`、`exactSourceCandidate` 或 `productCompositionSourceCandidate`。允许改变的当前导航字段限于 `sourceObjects`、operation `sourceBlob`、exact manifest/caller 的 blob、`observedAtHead`、`observedSourcePaths` 和已有的 `mappingSourceIdentityMode`。完整旧 Map 的 Git blob、SHA-256、字节数、commit/tree 与旧 observation 将记录到新账本，已有 claim/completion、owner、caller/writer 状态、操作语义和门槛保持不变。

旧 `true` claim 在任何重写之前必须用原 pin 证明源码仍匹配。此检查覆盖 sourceObjects 独有 witness、exactSourceEvidence 独有 witness、operation sourceBlob 和 caller blobSha；既有 source-root tree 和普通 file blob 都允许。空/缺失的必需 manifest 或 pin 不能通过自动补当前值获得资格。若原观测过期或原显式 pin 不符，保持拒绝；只在没有过期执行资格时刷新导航。

### 首轮导航预检拒绝与历史图谱恢复

首次 C0 preview 在原 `checked_identity(sourceBase, candidate)` 的祖先检查处拒绝：`de47d561266c97d8350de71ae710b650a3b61447` 到 C0 的本地 `merge-base --is-ancestor` 返回 1；helper 尚未进入写入阶段。这个检查不是 helper 单独添加的可选限制：原 qualification verifier 也先检查 sourceBase 的 commit/tree 和 ancestry；`exact_blob` 仅改为独立证明当前源码内容，不豁免历史身份的祖先关系。

随后的只读 GitHub 对照确认，40 张 Map 使用的 5 个历史 sourceBase **都是真正的 C0 祖先**，各自 tree 也完全匹配。de47→B0 为 ahead 236 / behind 0，de47→C0 为 ahead 253 / behind 0，merge base 都是 de47；其余四个 sourceBase 的 behind 同样为 0。本地仓库随后确认为浅历史，最初仅能看见 C0 链上的 18 个提交；问题不是基线引用了真实非祖先旁支。恢复应保留原始 Git 对象和父边，再用原规则重跑；不改 sourceBase、不删除 ancestry 检查、不清 true、不增造 parents。见[初次双重对照](source-base-ancestry-remote-check.json)与[全部 5 个 sourceBase 对照](all-source-base-ancestry-check.json)。

最老一段 3659→331b 已通过 5 次 API 读取找到 34 个真实提交、33 条原始 parent 边，完整路径与原元数据保存在[旧段路径记录](history-older/path-3659-to-331b.json)。组合后的历史包含 181 个证明路径提交、37 个真实侧父提交及 5 个 anchor root tree；原始提交 SHA、完整有序 parents 与 path edge 均经独立复算。新的浅边界只截断证明路径之外的侧支，旧边界的展开恢复原本存在的边，不创造父关系。

在新的独立 bare repo 中，223 个对象的原生 hash/readback 及 5 组 ancestry/tree 查询均已通过。安装器又在独立测试 checkout 完成实际 default/apply 验证，HEAD/ref/index 保持不变；对象根、fanout 和 leaf 的符号链接都提前拒绝。原安装器沿共享对象符号链接写入的反例及修复已保留。见[独立历史包审查](independent-history-frontier-review.json)、[安装器实际行为](independent-installer-normal-review.json)与[写边界 RED/GREEN](independent-installer-boundary-review.json)。

同一 223 对象包已在 ai395 独立 C58 checkout 实际安装，5 组 ancestor/root-tree 查询均通过，shared checkout 原浅边界未变；source checkout/index/refs 没有由安装器修改。见[实际对象与 5 查询回执](../publication/native-evidence/history-install-receipt.json)及[实际安装命令/退出码](../publication/native-evidence/history-qualification-ancestry-install.json)。只恢复本次所需的真实父链及 anchor root，不声明完整 reachable history 或历史 subtree/blob 已全部补齐；原对象 hash 核对也不等于 Git 签名的密码学信任验证。该结果不替代最终 Map strict。

### 已审查的单一历史观测归档

`runtime.supervisor` 的旧 `observedAtHead` 除 commit/tree 外，还带有一段明确排除产品激活、部署 trust root、目标主机和独立接受的历史源码收敛说明。当前观测 scope 包含本轮已修改的 Agentd/agent-protocol，因此不能把旧说明原样挂到新 SHA。协调审查已认可将该旧记录完整保留在 ledger，再写纯 commit/tree 的当前导航身份。

helper 的扩展仅由 `--archive-reviewed-supervisor-observation` 显式启用，且严格同时匹配 `runtime.supervisor`、原 Git blob、原 Map SHA-256 `362f4f5c…` 与完整旧观测 SHA-256 `68b7b582…`，并核对载入 row 等于原 Map 字节解析结果。其他模块、任何字节/字段变化、任何其他额外观测字段仍拒绝。完整旧文、原 Map 身份和 review 理由进入新 ledger；所有 sourceBase、claim 与历史 candidate 不变，旧 true 的原 pin 检查仍先执行。该扩展不改原产品 verifier。见[确切旧观测](runtime-supervisor-observation-review.json)、[限定 helper 补丁](reviewed-supervisor-observation.patch)和[8 项实际测试回执](reviewed-supervisor-helper-tests.json)。 独立审查也对同一 helper SHA-256 `790d124c…` 复跑全部 8 项并通过，见[独立 Supervisor 归档审查](../lifecycle_review/navigation_independent/independent-supervisor-archival-review.json)。

### 第二轮预检：只有 operation pin 过期的真实 Map

实际预检又定位 `learning.artifacts`：`mappingSourceIdentityMode` 缺省为 `path_only`；两个操作 `load_pinned_candidate`、`revalidate_pinned_candidate` 的 `sourceBlob` 仍为 `3ff1450b5111706d737643351fb5692ee657726c`，而同 Map 的 sourceObjects 和实际 pinned.rs 均为 `3a097702ef7294467e2a16b5ae8624b716372c41`。sourceBase 指向的文件内容已是后者，所以原 source-identity 检查没有发现新漂移；原迁移器只在 `exact_blob` 模式刷新 operation pin，旧 helper 因而在最后的显式 pin 检查正确拒绝，未写文件。

修订只增加一行：把 **迁移后** 的显式 pin 校验同时放进现有 SourceDrift 捕获范围，沿原 exact_blob 路径刷新无执行资格的当前导航。**原 row 的 true claim 校验仍在任何 try/迁移之前，最后的 pin guard 也保留**；坏格式/结构错误不被 SourceDrift 捕获。C58 的真实源码字节和原 Map 两条操作已在独立 Git fixture 复现旧 helper 的拒绝，新 helper 的导航刷新后原 qualification 通过；标准/别名 true 两类仍拒绝且零写，坏格式同样拒绝。

当前 helper SHA-256 为 `940f0fe0d5fccf53dc8d00dacbd4f572cf9b02419704dba0cde35d495f9e7e3b`，原 8 项加真实 pin 场景 3 项共 **11/11 PASS**；独立同形反例也完成 RED/GREEN。见[单行修复](explicit-pin-fallback.patch)、[真实数据及 11 项回执](explicit-pin-fallback-helper-tests.json)与[独立复测](../lifecycle_review/navigation_independent/explicit-pin-only-corrected-GREEN.json)。这只是 helper 的触发条件修复，未改产品 verifier 或资格规则。

### C58 上的实际导航刷新

Run2 结束后，940f helper 在同一 C58/tree 先 preview、再 apply，两次均 exit 0：**40 张 Map 检查，26 张 Map 刷新，新增一份导航账本**。preview 结束保持 clean；apply 只产生这 26 张 Map 和固定账本的变动。原 formatter 随后 exit 0，未额外更改文件。见[preview 回执](../publication/native-evidence/navigation-940f-preview.json)、[apply 回执](../publication/native-evidence/navigation-940f-apply.json)及[formatter 回执](../publication/native-evidence/navigation-940f-format.json)。

[实际导航差异独立审查](../lifecycle_review/navigation_independent/actual-navigation-940f-review.json)已通过：重新从 C58 绑定旧 Map 字节，将实际 diff 在独立 Git 重放后，与实际后像逐字节一致。26 张改动 Map 中的 **410 个 sourceObjects、284 个 operation pins、6 个 caller pins、23 个 manifest pins**均与新鲜读取的真实 C58 对象相符；历史 sourceBase、claims、候选和未放行门槛均保持不变，Supervisor 旧说明完整归档。该审查仍不代替提交后的全仓输入等价和原 strict。

导航原生提交 N1 为 `ae37963acc4dc5b6a297cdcb6143e57f810176f4`；发布的 canonical **C1 为 [5e917b9f5fb3e841dbcaefcd5bbbf59b32f20411](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/5e917b9f5fb3e841dbcaefcd5bbbf59b32f20411)**，两者 tree 均为 `5f02eb87cce34d40d6ddf21722305192b4fa00d7`，唯一 parent 都是 C58。见[导航发布身份](../publication/canonical-navigation.json)。原始四包测试仍只记为 C58 的执行。

在 canonical C1 上，原 qualification verifier 已实际 **40/40 PASS**，其中 **27 张为 provenance-anchored exact-blob、13 张使用 exact observed fallback**；并非把全部 40 张都重绑为 C58，本轮实际修改仍为 26 张。原状态测试 **2/2 PASS**，registry strict 对齐，module docs qualification 验证 **40 份技术文档与 40 份绑定 PASS**；每条命令都 exit 0，执行后 C1/tree 不变且 clean。Map verifier 明示 `validationScope=source_navigation_and_declared_evidence_not_build_or_execution`、`productionImplementationProved=false`；文档 verifier 明示 `productExecutionProved=false`、`authorityGranted=false`。注册表对应 40 模块、51 个绑定 crate；browser.servo、ui.control、ui.native 的登记根没有 Cargo package，这些根不能据此算作已编译产品。见[完整命令与身份回执](../publication/native-evidence/qualification-c1-summary.json)、[Map 原输出](../publication/native-evidence/maps-qualification-c1.log)、[registry 原输出](../publication/native-evidence/module-registry-strict-c1.log)与[docs 原输出](../publication/native-evidence/module-docs-qualification-c1.log)。

提交后的 [no-op 原输出](../publication/native-evidence/navigation-noop-c1.log)记录再次检查 40 张 Map、`changedMaps=0`、`written=false`、`ledger=null`。[全仓输入等价实际回执](../publication/native-evidence/navigation-execution-input-equivalence.result.json)比较 C58 与 C1：除精确 40 个 Map 路径和唯一新增导航账本之外，**10,795 个 tracked path/mode/type/object 条目完全相同**，投影摘要前后均为 `4a9d64833cbb736ddec26d120f08cc8b472b3f980960c93f0c3a27827c248964`；源码、测试、runner、构建清单和其余跟踪输入未变。该回执明确 `tests_reexecuted_on_C1=false`、`execution_identity_transferred=false`，只证明跟踪输入等价，不冒充 C1 上的另一次原生测试。[最终 C1 回执独立审查](../lifecycle_review/navigation_independent/final-c1-receipt-independent-review.json)又核对了全部 6 项实际退出码/身份/日志及导航后像，结果一致。

这里的 **26 张实际刷新**与前述 **B0 的 18 张 / 70 个 sourceObjects**口径不同：前者基于最终 C58，包含当前导航身份和 operation/manifest/caller pin；后者只统计固定 B0 的旧 sourceObjects。不能把两者相减解释为新增 8 个缺陷，也不能把 pin 刷新数量当作新产品实现数量。

详细操作见[安全刷新步骤](NAVIGATION-REFRESH-RUNBOOK.md)。helper 的选择性刷新不能取代既有 strict verifier；不运行会顺带改 bootstrap/interpretation 的历史 source-registry normalizer。SOURCE_BINDINGS 的 source root/owner 没有因为导航刷新而变动，PLAN_AUDIT 的 14 模块历史子集和 0 个 production 计数均不随 pin 刷新改写。

## 四、实际验证证据与仍保留的门槛

### 已执行、且范围确定的验证

| 检查 | 实际结果及身份 | 证明范围 |
| --- | --- | --- |
| 固定源内容 | 47/47 blob 一致；40 根存在；369 个操作条目已核对 | 源码与文档定位，非执行 |
| 状态一致性 | 加强测试在更正前失败，更正后通过；5 文件补丁实际应用字节一致 | 6 个 flag 与统计纠偏 |
| 原 claim alias 反例 | 9 类 × 3 位置 = 27 个旧工具反例 | 旧资格可被错误续期的真实 Git 失败证据被保留 |
| 原显式 pin 反例 | 4 类 × 2 claim = 8 个独立旧工具反例；修复后全部拒绝 | sourceObjects、manifest、operation、caller 的旧证据保护 |
| 独立开发环境的原 verifier 机制 suite | **159 tests PASS**，verifier SHA-256 `a72b1aca62257154488ed2da6fa2378d7a4d65e0e6366fa1be9841db4c74fce3` | 本地 disposable Git 的机制回归 |
| ai395 原生候选上的同一机制 suite | **159/159 PASS**，31.780 秒，wrapper 32.039 秒；N0=`910a5373c786c3e180f5b4d743ad794d88df5cec` | 实际退出码 0；commit/tree 前后一致，结束时工作树 clean；仍是 Map 机制 tests，不是四包 Rust suite |
| 初版导航 helper | **4 tests PASS**；helper SHA-256 `ab97182df14d727e7b38c4332ccb73fb7570ea9959a1dfe9b4e144ff578f0633` | 历史保留、前像账本、no-op、dirty/错误身份及旧 verifier 拒绝 |
| 精确 Supervisor 观测归档扩展 | **8 tests PASS**；helper SHA-256 `790d124c85dc299f6254fcd0427461881023bf60fcc4943713867eacd3dba438` | 仅已审旧 Map/blob/观测 hash 的显式 opt-in；默认拒绝不变，完整旧文归档、当前观测纯身份，旧 true 仍拒绝 |
| operation pin 单独漂移的 helper 修复 | **11/11 tests PASS**；helper SHA-256 `940f0fe0d5fccf53dc8d00dacbd4f572cf9b02419704dba0cde35d495f9e7e3b` | 既有 8 项加 C58 真实源码/原 Map 操作的 3 项隔离 Git 回归；独立 RED/GREEN 同时确认 false 导航可刷新、两种 true 仍拒绝且零写 |
| 独立审查 | 8 个拒绝子例、不变 true 的 tree/blob 正例、4 个 helper 场景通过；两条 patch 应用结果同字节 | 防止错误续期，也防止把合法不变证据误降级 |
| Formatter 后实际 verifier / 新 pin test | verifier=`7a66ce3c8a73b29771d16ccfc71b69f84b5c0cf01c991badad8dd8703d017832`；test=`b4c2e63ace85ef0f32c5ded9b4014eb35e0de66dd1923f4a6664a859fcb778c2`；两者相对原审版本 AST 相同 | 实际格式化输入已在 N0 完成 159 项重跑；原审日志保留原 hash |
| C58 原四包 Run2 | **697 passed / 66 skipped，exit 0；59/59 必要用例 clean，0 flaky**；59 项独立证据一致性检查通过（含原始 metadata 补核） | 21 个测试 binary 的实际运行及必要覆盖；Run1 失败与缺少 XML 保留，不扩张至真实外部服务或生产资格 |
| C1 原有严格检查与 no-op | **40 Map、2 状态 tests、registry、40 docs/40 bindings 全 PASS；no-op changedMaps=0** | C1 的源码导航、声明证据、注册/文档一致性；所有命令实际 exit 0、结束 clean |
| C58→C1 跟踪输入等价 | **10,795 个非 Map/账本条目逐项相同**，原始 C58 Run2 receipt/log/XML 摘要匹配 | C1 没有改变已执行源码的跟踪输入；没有在 C1 重跑 Rust，不转移执行身份 |

机制证据：[159 项输入与命令](refresh_review/final-source-provenance-receipt.json)、[159 项日志](refresh_review/final-source-provenance-suite.log)、[helper 日志](navigation-helper-tests.log)、[独立最终补丁应用](../lifecycle_review/navigation_independent/independent-final-patch-application.json)、[formatter 字节差异审计](remote-guard-format-audit.json)。嵌套 manifest 的原地修改/丢失写回反例也已保留并修复。测试通过仅覆盖各自记录的输入。ai395 新回执绑定实际格式化输入和 N0；C0 与 N0 的 tree 相同，但不能把回执改写成“已在 C0 commit 执行”，也不能推导任何 C1 或原生产品资格。

### 最终统一候选回执与未关闭范围

| 门槛 | 当前报告状态 | 实际边界与证据要求 |
| --- | --- | --- |
| 当前冻结源码 C58 | **已发布** `58c81ccdd25002ae0f481d434af067a56fa7ddb8` / tree `57809be09ef01c02389ef37a817f1447d13d167b` | 已真实融合 C0 与 e65；C0 的 17 阶段与 N0 的 159 机制回执继续保留各自身份 |
| 原生候选上的 159 机制 tests | **已执行 PASS，N0=`910a5373…`** | 命令、formatter 输入身份、退出码 0、实际日志已归档；保留与 C0 的不同 commit 身份 |
| helper preview/apply | **已实际 exit 0；40 maps checked / 26 maps updated，新账本已写入；实际差异独立审查通过** | 精确 C58/tree、940f helper；前两次拒绝保留；formatter exit 0 且无额外文件改动 |
| 导航提交 C1 | **已发布 `5e917b9…` / tree `5f02eb8…`，sole parent C58** | 原始父序与完整 tree 已绑定；10,795 个非导航跟踪条目与 C58 相同，C1 未重跑 Rust |
| 原 40-map qualification verifier | **C1 实际 40/40 PASS，exit 0** | 原 `qualification` profile、expected-sha/tree、JSON 结果与 clean 状态已归档；不授予执行/生产资格 |
| 状态、registry、module docs checks | **C1 实际全部 PASS** | 状态 2 tests；40 模块/51 crates 对齐；40 docs/40 bindings；原命令与条件不降级 |
| 原生四包完整测试套件 | **Run1：696 passed / 1 failed / 66 skipped，exit 100；Run2：697 passed / 66 skipped，exit 0** | 两次同 C58/tree；两轮原始回执与日志、Run2 XML 已归档；独立审查确认字节、身份和选择集合一致 |
| 59 个必须用例覆盖审计 | **Run1 无 XML；Run2 59/59 clean、0 flaky，独立审查通过** | 原 49 + e65 原 10 全部确实执行；不缺失、不 skip、不失败、不重复冒充；其他 66 skipped 不算执行通过 |
| GitHub 合并与平台 CI | **未关闭**：PR 为 draft；API `mergeable=false/dirty`，0 check runs，commit status pending/0 statuses | e65 已是 C1 祖先、ahead 19/behind 0 不能替代 GitHub 平台合并状态或 CI 回执 |
| 独立合并候选与目标平台资格 | **仍需各自回执** | 当前真实三方 merge 和祖先关系已经证明；独立 Lane A、Windows/其他目标 host 与批准链仍需对应执行证据 |
| 产品执行、独立接受、activation/release | **仍未授予** | 对应 owner、独立证据与批准链；导航通过不会改为 true |

原生四包为 `codex-hepta-agent-protocol`、`codex-hepta-agentd`、`codex-hepta-runtime`、`codex-hepta-infer-worker-host`。[原 49 个必要用例](../product_recovery/required-tests.md)与[扩展后的 59 个清单](../product_recovery/required-tests.with-e65.md)都是完整套件的覆盖审计子集，绝不是 runner filter。它覆盖 wire 绑定、bound snapshot/ABA、溢出、canonical 身份/期限、Desktop issuer、公共 Control 拒绝、真实进程恢复、terminal/usage/currentness 和完整输出等原有边界。

### GitHub 当前合并与 CI 状态

2026-11-05 **11:21:10 UTC** 读取的 [GitHub 门槛快照](../publication/github-final-gates.json)显示，[PR #4869](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4869) 为 open/draft，head 为 C1、base 为 `e65a53ddfc872ef66edc63dff8f28d4414817c60`。compare 确认 ahead 19、behind 0、merge base 等于 e65；同一次快照的 PR API 仍返回 `mergeable=false`、`mergeable_state=dirty`。本报告保留这两组实际返回值，不猜测 dirty 的原因。

当前 C1 有 **0 个 check runs**，commit status 为 **pending、0 个 statuses**。本轮 ai395 原生和源码严格验证已经通过，GitHub 平台合并/CI 门槛仍未关闭；PR 尚未合并，不能写成“全平台 CI 通过”或“可生产发布”。

### 原有严格验证命令

以下原命令已在实际 clean canonical C1 执行并记录 exit 0。回执中的 `C1` 为 `5e917b9f5fb3e841dbcaefcd5bbbf59b32f20411`，`T1` 为 `5f02eb87cce34d40d6ddf21722305192b4fa00d7`；复现时仍必须核对实际身份，不能用基线 SHA 或猜测值。

```bash
python scripts/hepta-implementation-maps.py verify \
  --profile qualification \
  --expected-sha "$C1" \
  --expected-tree "$T1"
python scripts/test_hepta_module_status_facts.py
python scripts/hepta_module_registry.py --strict --pretty
python scripts/hepta-module-docs.py verify --profile qualification
```

原 verifier 机制 suite 在 `scripts` 目录执行：

```bash
python -m unittest \
  test_hepta_implementation_maps \
  test_hepta_implementation_source_identity \
  test_hepta_implementation_identity \
  test_hepta_implementation_git_environment \
  test_hepta_source_observation \
  test_hepta_implementation_claim_pins
```

## 五、继续推进时必须保留的依赖顺序

1. **固定统一源码与真实身份。** C58 已真实融合 C0 与 e65，Run1/Run2 原生完整 suite 均绑定 C58，失败和后续通过分开留存。原 N0/C0 同 tree 的机制回执保留旧身份；C58/C1 也分别记录，不转写执行身份。
2. **维持已验证的导航一致性。** 原始父链已在隔离候选恢复；940f helper 保留历史 evidence 后刷新 26 张 Map，clean C1 的原 40 模块 strict 和 no-op 已通过。后续源码变化仍要重新观测并验证，旧执行声明不能因重绑获得续期。
3. **扩展同源物理执行与恢复。** 本轮实际 App Server/Agentd/worker 进程与受控 provider 路径已经取得完整原生 suite 和 59 项覆盖回执；Agentd 自身全进程重启、跨 owner 接管和真实 provider 的能力仍需独立条件证据，不能由 worker 重开测试推导。
4. **按 owner 补实际服务与资源。** AuthBus、Bao、Fleet capacity、经济 quota、model/device、CurrentMemoryRetrievalContext、Matrix/Servo/UI 都有各自真实外部依赖；不以 fixture 自证。
5. **闭合决策、学习和全局控制。** durable Decision/Outcome、默认 dataset→训练→独立评估→选择→新进程加载、非测试自迭代触发，以及完整 Control lifecycle/路由 CAS/custody/批准链分别验收。公共 topology 继续 DENY_ALL，生产资格继续 false。

本报告的 40 项职责、固定根、owner、原 caller/writer 状态和操作数可由对应固定基线 Map 与注册表复核；本轮新增代码按固定补丁与实际执行身份绑定。C58 原生测试、C1 导航 strict 和独立审查分别留有回执；本轮没有执行的外部接受、目标平台或生产资格继续保持未授予。
