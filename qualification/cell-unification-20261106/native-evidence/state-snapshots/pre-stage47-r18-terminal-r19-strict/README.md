# Cell 统一候选：角色、历史后端与原生执行证据

**本轮已完成两个原生实现的组合，并补上有实际回归的注册与特征输入桥，仍有 blocker 未闭合。** 七类功能职责已有多种真实历史后端，不能归结为“只有 enum”；本轮新桥和 registry 的通过范围仍是明确的原生机制与 fixture，不是七类语义模型的完整采用。完整成熟度与不可转移的历史资格见 [MATURITY.zh-CN.md](MATURITY.zh-CN.md) 和 [HISTORICAL_ASSETS.json](HISTORICAL_ASSETS.json)。

这是 **DRAFT** 证据索引，尚无发布分支或PR。最新stage46 / r17 的Core＋codex-mcp＋core_test_support 原门已闭合：**严格 lint PASS；完整测试4,063/4,063 PASS，另9个原配置skipped**。其中Core3,830、MCP196、core_test_support37项通过；r14的24项、r15的3项和r16的2项原失败均逐ID通过，重叠用例不相加。默认193成员全工作区门r18已启动，终态仍待完成。此前失败与通过均分别绑定其原源码、命令和回执。

原 r8c 的 **206 fail＋10 timeout** 已全部按唯一测试 ID、错误签名与日志行完成分类和归档；分类完成不表示根因全部解决。r9、r11、r12 的 Agentd 组合严格门均以 **101** 退出，分别保留其原始源码和失败证据，三次测试均未启动。r11 为 stage 36 的两项 infer-worker-host 测试 lint；r12 为 stage 40 的 12 项 Agentd 测试层 lint，已封存原日志与独立源码重建证明。

r13 的 **stage 41** 树 `6be3dbb1420c0ac7e0590c6e3c17191a073af9a9` 已完成原始严格门和原测试命令，154 源文件的 Git tree 重建与逐测试 ID 读回均已闭合。r14 在 **stage 43** 树 `d3d2313b838422818bf9448ce5a1b86d89abdf69` 完成全部 3,830 项测试，命令退出 **100**。六项新增终止确认回归、原真实 shell 持久用例及五项非登录 shell fixture 均逐项 **PASS**；完整 Core 门仍有 **24 项 FAIL**。179 份闭合归档原件、163 源文件、24 个原失败块与独立 Git tree 重建均已核验。后续修复须绑定新源码重验；完整工作区、最终 fix/fmt、发布及远端 CI 仍未闭合。stage 39 冷恢复上下文仍只是诊断，科学收益继续 **HOLD**。

r15 在 **stage 44** 树 `1646e1656cf6365e74accae19a1225fd2ce6d964`、同树 commit `638997499470f0b7dd33ad18226feacf0198ef3d` 上完成。严格门耗时 **45.162 秒**；完整测试连同构建耗时 **594.945 秒**，测试执行 **479.725 秒**，退出 **100**。190 个归档原件、177 个变更源码的 bytes／mode／Git blob、完整日志及回执均已核验，并从原 framework base 独立重建为同一 Git tree。三项剩余失败是恢复 epoch、Zsh parent approval 保留拒绝读取，以及 managed network proxy unit；原三个失败块完整保留。详见[闭合读回](native-evidence/r15-core-mcp-checkpoint/ROOT-RESULT-READBACK.json)与[原24失败到本轮修复的映射](native-evidence/r15-stage44-input/R14-REPAIR-COVERAGE-MAP.json)。该历史阶段未启动完整工作区，也未执行最终fix/fmt。

r16使用的 **stage45**：commit `96dc9232535fedf735e3099ef1391b69477270d4`、实际原生 tree `3ebd193f213d640e5330a1be4b983bcc4b06617a`。r16 三包严格门 **PASS，36.351 秒**；完整测试 **4,061 passed、2 failed、0 timeout、9 skipped**，连同构建562.390秒、执行452.452秒，退出100。195个归档原件、180个变更源文件及完整日志已核验，并从原framework base重建为同一Git tree。proxy 与 denied-read 原失败已通过；恢复用例推进到设置契约拒绝，冷恢复再次出现尚未定位的 ThreadNotFound。两项均保留为失败，详见[闭合读回](native-evidence/r16-core-mcp-support-checkpoint/ROOT-RESULT-READBACK.json)。默认全工作区尚未启动，最终fix/fmt尚未执行。

当前 **stage46**：commit `2d7ad1d60019f35fc13d84138ceb2755d914f434`、tree `ffa0a37f4616c5563169c7f0a9305bf6c982d58b`。两个Core fixture修正后，r17严格门14.149秒退出0，完整测试连构建478.688秒、执行462.084秒，4,063项全部通过；冷恢复7.387秒、Plan恢复0.268秒。196个归档原件、180个变更源码及完整日志已核验，原framework base的GitData重建精确一致。[闭合读回](native-evidence/r17-core-mcp-support-checkpoint/ROOT-RESULT-READBACK.json)不代替正在运行的默认193成员工作区门或最终fix/fmt、发布与CI。

## 组合身份

| 层次 | 固定身份 | 已证明范围 |
| --- | --- | --- |
| 原生 Cell / Circuit / owner 来源 | #4887：`bef6fa7645df9df12b69fda499e97eed25de6c75` | 提供既有 prepare/infer/decide/commit、journal、Circuit 与学习协调实现。 |
| 七职责、群体计数与分化来源 | #4890：`caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b` | 提供 capability、人口计数、分化提案与冻结 Python 研究。 |
| 首次组合测试树 | `50ae18757324959cf8fc7c41389ede13bbc80d44` | Pocket4 原生 neuron＋plasticity **200/200**；0 skipped。 |
| 加入输入桥与 registry 的测试树 | `73bc5da08b54612ff662542c20124e96d3d51908` | 同两包 **214/214**；新增 14 项包含在总数内；0 skipped。 |
| 七包联合门测试树 | `e634d4d2f7ce4a9bc78d3d1756e3242c5d3eb211` | **623 passed、1 skipped**，自然退出 0；回执与完整日志已归档。该树随后的严格 lint 失败，后续修复需要新的源码身份。 |
| 九包修复后测试树 | `40da496d1e1c163f67ed83dcdb23d61bf16836aa` | 原始严格 `-D warnings` 通过；753 passed、1 个既有 worker ignored，退出 0。58 文件与原始附件已完整传回；后补 commit `5778f6b` 的 tree 与实际测试 tree 完全相同。 |
| r10 继承七包测试树 | `6ec19f0bae87ffc2dc3c5343c3e5ac390c22a6f0` | 原始严格门与测试通过：1,355 passed、17 个既有 skipped；包含修复后的真实 paired-process fixture。该包范围不包含 Agentd / infer-worker-host，也未运行 Core 自身测试。 |
| r11 实际失败树 | `f20c3860c90853e90ab9d5c4d1b772787e0379a7` | stage 36；任务 `1a1af8171a0-fc05-6932` 的三包严格门退出 101，测试未启动。后续 stage 37、38 及冷恢复诊断不属于这次执行树。 |
| r12 实际失败树 | `a0d24a6cca704bb1bb43c4090a275a38832f7b19` | stage 40；三包严格门退出 101，12 项实际源码诊断；测试未启动。145 个相对基线的源文件已独立重建为相同 Git tree。 |
| r13 已闭合测试树 | `6be3dbb1420c0ac7e0590c6e3c17191a073af9a9` | stage 41，同树 commit `d313ba51180a838269677d28b2d91e1777b7b463`；原严格门与测试通过：696 passed、66 个既有 skipped。154 源文件、原始附件、逐 ID 读回及独立 Git tree 重建已闭合。 |
| stage 42 Core 行为修复 | `ccb50851347a0c27e5cbe621790daa78b9c98794` | commit `05fc1158eee025e1a76d45cef27b4caddc69d22b`；7 文件、6 项新回归；随后合入 r14 的 stage 43 树，未单独测试，也不属于 r13 执行树。 |
| stage 43 / r14 已闭合 Core 执行树 | `d3d2313b838422818bf9448ce5a1b86d89abdf69` | 同树 commit `b44d4ca4aa0ef9f894eff29e9975938e066a82f5`；原严格门通过，完整测试 3,806 passed、24 failed、0 timeout，另 9 skipped。179 个归档原件与 163 个变更源文件已读回；GitData 与独立离线重建均得到同一 tree。 |
| stage 44 / r15 已闭合执行树 | `1646e1656cf6365e74accae19a1225fd2ce6d964` | 同树 commit `638997499470f0b7dd33ad18226feacf0198ef3d`；177 源码独立重建一致。严格门通过；完整测试 4,023 passed、3 failed、0 timeout、9 skipped；其中 MCP 196/196 passed，Core 3,827 passed／3 failed。后续源码和工作区资格仍待验证。 |
| stage 45 / r16 已闭合执行树 | `3ebd193f213d640e5330a1be4b983bcc4b06617a` | 同树 commit `96dc9232535fedf735e3099ef1391b69477270d4`；180源码重建一致、195归档原件已验证。三包严格门通过；完整测试4,061 passed、2 failed、0 timeout、9 skipped；MCP196/196、测试支持包37/37通过。 |
| stage46 / r17 已闭合三包执行树 | `ffa0a37f4616c5563169c7f0a9305bf6c982d58b` | 同树commit `2d7ad1d60019f35fc13d84138ceb2755d914f434`；严格门通过，4,063/4,063测试通过，另9原skip。196归档原件、180源码重建精确一致；r18工作区资格仍待终态。 |
| 最终发布源码 / PR | **PENDING_FINAL_SOURCE / PENDING_PUBLICATION** | 不以以上 staged tree 冒充最终 commit。 |

两次原生运行均使用 Rust 1.96.0、原始 `just test -p codex-hepta-neuron -p codex-hepta-plasticity --locked --retries 0`、任务专用 target。Cargo.lock SHA256 为 `4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c`。这是两个阶段的独立运行，不能相加成 414 项独立测试。source manifest、command、日志 SHA 和自然退出码分别保留。

## 新增的原生能力

1. **导入既有 global Q24 receipt。** `CellGlobalFeatureProjectionV1` 读取历史 `FeatureBundleV1.q24_global()` 的既有语法，要求独立的 conversion、bundle、source-record、row、encoder、scope 与当前 frontier pins。严格拒绝重复/未知 JSON 字段、bool/float 冒充整数、超范围、替换向量后自行重封条及超限输入。输入保持原坐标顺序，width 为 1..512；EG2 的 768 维输出直接拒绝，需要独立合格的投影方案。
2. **把注册绑定到实际执行身份。** `CellBackendRegistryV1` 绑定 backend family、角色 capability、expert、状态/输入/输出 schema 与完整 Cell definition；三种家族独立于七种功能职责和 HNMF engram 分类。注册 digest 进入 operation 语义，变更角色、家族或版本后不能重新解释原 pending/committed 请求。
3. **沿既有 owner 完成状态和恢复。** 注册入口调用原 native owner 路径；当前来源失效后拒绝读回，未知结果保持 pending，恢复仅查询原请求；晚到结果保留已发生成本并 abstain。注册前缀也计入已有输入预算。输出仍是 `CellDecisionReceiptV1`，authority 保持 `DENY_ALL`。

对应代码：[projection](../../codex-rs/hepta-neuron/src/cell_feature_projection.rs)、[registry](../../codex-rs/hepta-neuron/src/cell_registry.rs)。14 项新回归使用独立 Python canonical JSON 样例和显式控制端 fixture。它们没有加载 Granite、EG2 或 V13 权重，没有真实 Encoder receipt 的端到端导入证明，也没有生成文本/媒体、完整 token/region/time/missing-mask 导入或原始非线性 Head parity。schema/hash 绑定不能代替来源认证及真实行为验收。

## 本轮实际验证

| 验证项 | 已观察结果 | 固定证据与边界 |
| --- | --- | --- |
| 两包组合基线 | **PASS_SCOPED：200/200，0 skipped** | `native-evidence/baseline/native-first-{source,receipt}.json` 与日志；测试树 50ae187。 |
| 新桥与注册回归 | **PASS_SCOPED：214/214，0 skipped** | `native-evidence/registry-a/native-registry-a-{source,receipt}.json` 与日志；测试树 73bc5da。 |
| 原冻结 Python 行为测试 | **24/24 normal；24/24 -O** | [原日志与 source binding](study-evidence/README.md)；两次运行同一组 24 个案例。 |
| 完整冻结 Python 研究 | **10 trials、60 arms、11,520/11,520 测试预测；0 failed arms** | [完整报告](study-evidence/study.json.gz)；两个场景均 **HOLD**。 |
| 独立数值读回 | **30,720 predictions；最大绝对差 1.4432899320127035e-15** | [独立回执](study-evidence/independent-replay.json)；独立标量求值，不导入原研究模块，仍共享 NumPy RNG。 |
| 七包联合门 | **PASS_SCOPED：623 passed、1 skipped** | [完整回执](native-evidence/combined/native-combined-a-receipt.json)与[日志](native-evidence/combined/native-combined-a.log.gz)绑定树 e634d4d；构建＋测试 279.195 秒，测试阶段 4.817 秒。解压日志 SHA 与计数已独立读回。 |
| worker 父流程 | **PASS，原 skip 已解释** | [worker 证据](native-evidence/combined/ignored-worker-evidence.txt)：`owner_host_process_kill_reopen_matrix` 通过，并明确以 `--ignored --exact` 启动 `owner_host_process_fault_worker`。保留原来的 1 skipped，不额外加算测试数；未新增排除。 |
| 首次严格 lint | **FAIL：退出 101** | [严格门回执](native-evidence/strict-a/native-strict-a-receipt.json)和[日志](native-evidence/strict-a/native-strict-a.log.gz)记录 Context compiler 的文档空行与 8 参数问题；后续窄门还发现 Cell 与 automation 的 API 问题，见下节。 |
| 九包修复后门 | **PASS_SCOPED：753 passed、1 skipped；原始严格 lint PASS** | 树 40da496；加入 context-compiler 与 intelligence 自身测试。构建＋测试 27.123 秒，测试阶段 8.345 秒；[测试回执](native-evidence/nine-r2/native-nine-r2-tests-receipt.json)、[严格回执](native-evidence/nine-r2/native-nine-r2-strict-receipt.json)与[独立读回](native-evidence/nine-r2/evidence-readback.json)已归档。 |
| 协议严格 lint 与测试 | **PASS_SCOPED：14/14，0 skipped** | 实际 tree `634b3a5`，九包源码与已通过 checkpoint 逐字节一致；[原始回执与独立读回](native-evidence/r3/VERIFICATION.json)已归档。 |
| Agentd 组合严格门 r9 | **FAIL：退出 101；测试未启动** | tree `64ab951`；[原回执](native-evidence/r9-agentd-composition-diagnostic/native-agentd-composition-r9-strict-receipt.json)和[日志](native-evidence/r9-agentd-composition-diagnostic/native-agentd-composition-r9-strict.log.gz)保留 infer-worker-host 的 `collapsible_if` 与 14 参数问题；两项源错误不加算编译器汇总行。 |
| 继承七包原门 r8b | **严格检查 PASS；1,349 passed、4 failed、2 timeout、17 skipped** | tree `6d88ca9`。四项新 Supervisor 恢复回归和两项 exec 锁回归通过；proxy、snapshot 与物理进程夹具问题分别处理，不把整套写成通过。 |
| Core 原门 r8c | **严格检查 PASS；3,608 passed、206 failed、10 timeout、9 skipped；分类已闭合** | 同一原 tree。[完整 216 项分类](native-evidence/r8c-core-failed/core-r8c-failure-classification.json)按唯一 ID 去掉结尾重复摘要；108 项有明确 helper 元数据缺失，另 1 项有 host fallback `ENOENT`，余下 107 项保持独立签名分类，不推定同因。 |
| 原 paired target 串行诊断 r8d | **0 passed、1 failed、1 timeout、1 skipped** | 原 tree、debug limited 和 60 秒门槛保持不变；two-pair 到达错误 Drain 响应，five-pair 仍超时。进程采样器未捕获测试 PID，空采样不充当 CPU/IO 归因。 |
| 继承七包修复后原门 r10 | **PASS_SCOPED：严格门退出 0；1,355 passed、17 skipped** | tree `6ec19f0`；[严格回执](native-evidence/r10-closed-checkpoint/native-inherited-seven-r10-strict-receipt.json)、[测试回执](native-evidence/r10-closed-checkpoint/native-inherited-seven-r10-tests-receipt.json)与原日志已闭合。构建＋测试 510.079 秒，测试阶段 124.813 秒；原 60 秒看门狗下 two/five paired 分别 9.939 / 29.067 秒通过。 |
| nextest runner 回归 r10 | **PASS_SCOPED：31 passed、0 skipped** | [独立 runner 回执](native-evidence/r10-closed-checkpoint/native-runner-r10-tests-receipt.json)；原 10 项与新增 21 项全部运行，包含真实跨包 helper 的缺失失败与正确接线场景。该隔离运行没有改动 native checkout，不能充当 Core 门。 |
| Agentd / protocol / infer-worker-host 原门 r11 | **FAIL：严格门退出 101；测试未启动** | stage 36 的 `f20c386`；37.917 秒，两个既有 `expect_used` 阻塞。[原严格回执](native-evidence/r11-agentd-composition-diagnostic/native-agentd-composition-r11-strict-receipt.json)、[日志](native-evidence/r11-agentd-composition-diagnostic/native-agentd-composition-r11-strict.log.gz)及 [142 源文件独立 tree 重建](native-evidence/r11-agentd-composition-diagnostic/root-source-roundtrip.json)已归档。 |
| Agentd / protocol / infer-worker-host 原门 r12 | **FAIL：严格门退出 101；测试未启动** | stage 40 的 `a0d24a6`；26.055 秒，12 项实际源码诊断，排除两条编译汇总及一条 recipe 汇总。[原回执](native-evidence/r12-agentd-composition-diagnostic/native-agentd-composition-r12-strict-receipt.json)、[独立读回](native-evidence/r12-agentd-composition-diagnostic/INDEPENDENT-READBACK.json)及 [145 源文件 tree 重建](native-evidence/r12-agentd-composition-diagnostic/root-source-roundtrip.json)已闭合。 |
| Agentd / protocol / infer-worker-host 原门 r13 | **PASS_SCOPED：严格门退出 0；696 passed、66 skipped** | stage 41 的 `6be3dbb`；[严格回执](native-evidence/r13-agentd-composition-checkpoint/native-agentd-composition-r13-strict-receipt.json)为 27.514 秒，[测试回执](native-evidence/r13-agentd-composition-checkpoint/native-agentd-composition-r13-tests-receipt.json)为构建＋测试 503.426 秒，测试阶段 95.082 秒。原 `--locked`、`--retries 0` 和既有 ignored 保留；[逐 ID 读回](native-evidence/r13-agentd-composition-checkpoint/ROOT-RESULT-READBACK.json)与 [154 源文件 tree 重建](native-evidence/r13-agentd-composition-checkpoint/root-source-roundtrip.json)已闭合。 |
| Core 原门 r14 | **严格门 PASS；完整测试 FAIL：3,806 passed、24 failed、0 timeout；9 skipped** | stage 43 的 `d3d2313`；[严格回执](native-evidence/r14-core-checkpoint/native-core-r14-strict-receipt.json)为 190.008 秒、退出 0；[测试回执](native-evidence/r14-core-checkpoint/native-core-r14-tests-receipt.json)为构建＋测试 1,305.349 秒、退出 100，测试阶段 570.123 秒。原 `--locked --retries 0` 保留；[独立读回](native-evidence/r14-core-checkpoint/INDEPENDENT-READBACK.json)核对 3,830 个唯一结果，排除日志末尾 24 个重复失败摘要。 |
| Core＋codex-mcp 原门 r15 | **严格门 PASS；完整测试 FAIL：4,023 passed／3 failed／0 timeout，9 skipped** | stage 44 `1646e16`；[严格回执](native-evidence/r15-core-mcp-checkpoint/native-core-mcp-r15-strict-receipt.json)、[完整测试回执](native-evidence/r15-core-mcp-checkpoint/native-core-mcp-r15-tests-receipt.json)及[原始日志](native-evidence/r15-core-mcp-checkpoint/native-core-mcp-r15-tests.log.gz)。Core 3,827 passed／3 failed，MCP 196/196 passed；旧24失败逐 ID 读回为22通过／2失败。原预算、默认配置与零重试保留。 |
| Core＋MCP＋core_test_support 原门 r16 | **严格门 PASS；完整测试4,061 PASS、2 FAIL、0 TIMEOUT、9原SKIP** | stage45 `3ebd193`；[闭合读回](native-evidence/r16-core-mcp-support-checkpoint/ROOT-RESULT-READBACK.json)绑定原命令、终态回执、全日志和180源码重建。两项Core失败仍需修复与新源码重验。 |
| Core＋MCP＋core_test_support 原门r17 | **严格门PASS；完整4,063 PASS、0 FAIL、0 TIMEOUT、9原SKIP** | stage46 `ffa0a37`；[全源码与结果闭合读回](native-evidence/r17-core-mcp-support-checkpoint/ROOT-RESULT-READBACK.json)。旧失败逐ID全部通过，工作区r18另行执行。 |
| 最终 fix/fmt、源码封存与 GitHub CI | **PENDING** | 首次基线的 fix/fmt 不覆盖最终源码；stage46 的180个变更路径已映射为21个实际 Rust package owner（167个Rust文件）和13个非Rust路径。最终[范围与参数](native-evidence/final-fix-scope/FINAL-FIX-PACKAGES.json)只已准备，尚未执行；必须在完整项目门和默认工作区门结束后运行最终 fix/fmt，再绑定最终源码与远端CI。 |

各阶段的回执、source manifest 和完整日志分别索引，见 [native-evidence/INDEX.json](native-evidence/INDEX.json)、[r8–r8d 闭合附件](native-evidence/r8-r8d-closed-checkpoint/README.md)、[r10 checkpoint](native-evidence/r10-closed-checkpoint/INDEX.json)、[r11 闭合附件](native-evidence/r11-agentd-composition-diagnostic/INDEX.json)、[r12 闭合附件](native-evidence/r12-agentd-composition-diagnostic/INDEX.json)、[r13 闭合附件](native-evidence/r13-agentd-composition-checkpoint/INDEX.json)与 [r14 闭合附件](native-evidence/r14-core-checkpoint/INDEX.json)。原日志与各自回执 SHA256、原失败和原 skip 均保留。r14 的 [24 个完整失败块](native-evidence/r14-core-checkpoint/native-core-r14-result-review.json)逐一对应闭合日志原字节区间；先前严格阶段和活动前缀保留为历史快照，不代替完整门的 FAIL 结论。不同树、不同包范围及 runner 的计数不累加成独立测试总数，也不转移为最终源码资格。

r13 的同源码 nextest 清单列出 762 项，逐 ID 对应 **696 个非 ignored 项全部 PASS**，分包为 protocol 14、Agentd 632、infer-worker-host 50；66 项保留原 ignored 标记，清单本身不执行测试。外层 ignored 可能含由父测试单独启动的 helper，不能把外层计数改写成全部子流程运行次数，也不能据此授予真实 GUI、特权服务或外部模型资格。原始清单、完整日志与两个独立读回均已归档。

### 严格门发现与有边界的候选修复

这些是原生构建门发现的具体问题，不能用测试通过或选择性 lint 覆盖。当前候选保持 `-D warnings`，未添加 `#[allow]` 或减少原门的检查范围。

| 问题 | 候选源码改动 | 兼容性与验证边界 |
| --- | --- | --- |
| Cell 大 enum payload | `CellStepEntryV1::Ready`、`Replayed` 分别装箱 `PreparedCellStepV1`、`CellDecisionReceiptV1`；`CellUpdateOutcomeV1::Candidate` 装箱更新候选。 | producer 显式 `Box::new`；真实 `hepta-agentd/src/circuit_cell.rs` 在 `infer_cell` 与 `finish` 前解包，相关 fixture 和 replay 断言同步调整。Agentd 原三包范围已在 r13 通过；最终源码资格仍待最终门。 |
| Context compiler 文档空行、`observe_delivery` 8 参数 | 移除注释空行；新增 `ContextDeliveryObservationMetadataV2 { delivery_id, observed_unix_ms }`，函数改为 7 参数。 | 完整 checkout 只有 7 个测试调用，均已更新；解包后原验证与摘要函数体逐字节一致，实参和断言已核对。 |
| `NeuralCircuitCandidateV1::new` 10 参数 | 新增 `NeuralCircuitRevisionV1`，合并版本、前驱及路由/参数/资源 digest；构造函数改为 6 参数。 | 5 个 inline、1 个 runtime、1 个 store 调用均已更新。排序、验证、摘要方法和候选/receipt 字段保持原样，现有断言保留。 |
| 授权 effect 的同步/异步 10 参数与大 `Observed` payload | 新增借用输入 `AuthorizedEffectExecution<'a>`，命名绑定 intent、wire payload、fence、grant、期望 binding、command ID 与时间；`Observed` 装箱原 `TaskFlowStepReceipt`。 | authority 与 driver 保持显式；19 个测试调用和 1 个实际 Agentd host 调用已改写。原三包组合已在 r13 通过；后续源码与最终工作区资格仍待完成。 |
| 学习迭代与 canonical 结果的大 payload | `Training.candidate` 与 `CanonicalRunOutcomeV1::Ready` 装箱，更新 owning 构造与 Agentd 消费者。 | 显式签名/checkpoint/envelope/dispatch 编码不变；借用访问继续自动解引用。九包范围与 r13 Agentd 组合均已通过，各自绑定实际执行树。 |
| 私有 lifecycle event 与遗漏恢复分支 | 私有 `Observed` 载荷装箱；恢复矩阵纳入原有 `NegativeObservation` 分支；移除 intelligence 测试末次冗余 clone。 | lifecycle Serde 标签/字段与认证顺序保持原样；恢复 integration target 4/4，覆盖 Disabled 与 Cancelled，原断言保留。 |
| Agentd 协议大 payload | `AgentdMethod::AutomationExecuteEffect.signed_grant` 装箱，原便捷构造器内部装箱。 | 公共构造器与 wire JSON 不变；直接构造/按值解构枚举的 Rust 调用方需要适配。协议严格门与原测试 14/14 通过。 |
| 锁定 Tokio / Landlock 兼容接口 | PTY 与 socket 将稳定持有的 fd 显式交给 `AsyncFd::register`；Landlock 使用 `no_new_privs(true)`。 | 核对锁定 crate SHA 与官方源码：原 Landlock 弃用函数只是新方法的直接转发。fd 所有权、注册失败与注销先于关闭的约束逐处审计；不改变隔离或权限。 |
| memory 内部 helper 8 参数 | `MemoryCorrectionTarget` 组合 ID/预期版本；`OutcomeTransitionPolicy` 组合允许状态/结果状态/精确重放策略。 | 3 文件、4 调用点；公开 API、原事务、SQL、租约及断言不变。仅 crate-private/private helper 改签名。 |
| mock endpoint 布尔表达式 | 将 `!is_some_and(port != 0)` 写作 `is_none_or(port == 0)`。 | 缺少端口、零端口和凭证拒绝条件保持原样；独立包测试纳入新增四包门。 |

这里存在明确的 **Rust 源码调用兼容性变化**：调用方要构造命名输入，enum 的生产者与消费方要处理 `Box`。仓库内已搜索并更新实际调用点；不能声称未知外部 Rust 调用方无需修改。这些输入分组和堆分配调整不新增序列化 schema，不改变已有 receipt、候选或 wire 字段，也不重定义 digest 域；原有 owner、持久提交、授权检查和 unknown 恢复路径继续由原实现承担。Context 与 Circuit 的逐字节保真检查是源码证据，最终行为和构建资格仍需要新源码上的测试与严格门。

### 后续原门发现的实际问题

Supervisor 的 Matrix companion 恢复遗漏属于生产行为问题：原生产源码上的同四项回归实际断言失败，修复后四项通过，之后在原继承七包门中再次通过。恢复会先读取持久预算，再进行可能覆盖持久状态的恢复写入；发布身份未解析时保留预算并暂停重试，foreign owner 继续拒绝。真实 paired-process fixture 的 Drain 响应也已修复：只有真实持久 Draining 状态及匹配代际时返回 Drain acknowledgement；原 Health 路径、生产 driver、全部断言和 60 秒看门狗保持不变。r10 的 two/five paired 均已实际通过，但不据此把原 five-pair 超时唯一归因于 debug profile 或镜像大小。

Agentd 的 31 项严格诊断按四组提交：移除实际未读的私有字段和仅供测试的生产 wrapper；命名组合相邻的借用上下文；大 payload 装箱并同步真实 producer/owning consumer；保留 Notes receipt 的必需 `idempotent` 布尔字段、原 wire 名和未知字段拒绝。未增加 lint allow、虚构字段使用或修改原断言。Notes 的新 schema 回归明确覆盖 true/false、缺失、错误类型、额外字段与私有 Rust 字段名。公共 Rust 源码 API 的变化需要调用方适配，不能因 wire JSON 未变而省略兼容性说明。

继承七包的 proxy fixture 原先让外部 DNS 与 HTTP 读取共享同样的两秒时间尺度；修复使用仓库已有的公网字面量测试地址，保持原 NotAllowed、403 与 token 断言。原失败中的 DNS 时间没有被测量，不写成已观察原因。snapshot fixture 的三条额外 stderr 与宿主登录 profile 中的 `systemd-cat` 调用吻合；修复用受控 Bash launcher 隔离该宿主 profile，仍显式捕获测试 `.bashrc` 并保持原 retry/capture 次数断言。这些 fixture 与原继承七包已在 r10 一起通过，原失败日志继续保留。

r9 发现的 infer-worker-host 两项问题已提交窄候选：合并等价取消条件，按请求身份与 authority 分组私有校验输入，入口立即解构，原持久 binding 校验体与实参顺序不变。[源码审计](native-evidence/infer-worker-host-r9-repair/repair-audit.json)记录这组边界。r11 的两处测试 hook 错误传播随后修复，但 r12 又暴露 12 项 Agentd 测试层诊断，不能把先前诊断消失等同于整个门通过。

stage 41 的 11 文件测试修复分别保留原断言：[五文件 clone／条件分支审计](native-evidence/agentd-r12-simple-test-repair/independent-review.json)与[三文件 fixture 输入审计](native-evidence/agentd-fixture-r12-repair/root-independent-review.json)确认，六处冗余 clone 改为最后使用的移动或 Copy 字段继承，单模式 match 改为等价 if-let；请求记录使用同一具体类型的 alias，release helper 将两个相邻的独立读回 oracle 组合为命名输入，并更新唯一实际调用方。[两处并发收集](native-evidence/agentd-r12-concurrency-repair/root-independent-review.json)保留先启动全部任务、再等待／join 的顺序，不能采用会破坏 barrier 的惰性迭代建议。这些是测试 fixture 的源码改写；r13 已完成当前三包原严格门与原测试，696 个外层测试通过、66 个原 skipped 保留。未选中的 vendored `i18n-config` 仍输出原有两条 lifetime warning，不据此声称整个仓库无 warning。

后续编译采用现有 CI 已设置的 `CARGO_PROFILE_TEST_DEBUG=0`、`CARGO_PROFILE_DEV_DEBUG=0`；原 debug-limited 结果完整保留，不与 debug=0 结果混写。锁文件、features、优化级别、测试断言、原 timeout 和 retries 均保持原门约束。全部剩余门与源码身份见 [STATUS.json](STATUS.json)。

### Core 完整分类、修复与 r14 结果

r8c 的 216 项不通过结果已逐项封存，其中 109 项有明确的 helper 元数据缺失或 executable `ENOENT` 证据；其余 107 项包括结果结构、JSON、请求数、事件期限和 watchdog 等独立签名。原日志结尾重复的 216 项摘要不重复计数，日志内的 “skipping test” 文本也不改记为 nextest skip。以下修复不能代替完整 Core 重验：

| 实际问题与候选 | 改动及资格边界 |
| --- | --- |
| [跨包 runtime helper 接线](native-evidence/nextest-runtime-helper-repair/REVIEW.zh-CN.md) | 按声明的消费包与真实 helper owner 构建，核对 Cargo artifact 的 package、target、来源与实际 executable 路径，再传入测试子进程；不伪造路径、不扩大原 test selection。runner 的 31 项已在隔离目录全通过；r14 Core 完整重验已经闭合，仍有 24 项失败，不授予整套资格。 |
| [custom provider / Bedrock fixture](native-evidence/core-provider-r8c-fixture/repair-audit.json) | 仅在 7 个相关 fixture 中清除通用 builder 为 mock 开启的私有 metadata 能力，保留原 wire、历史和请求断言；不修改生产 provider gate。 |
| [SQLite retained-owner fixture](native-evidence/core-sqlite-preview-r8c-fixture/repair.patch) | 为原测试记录补充明确的 preview，使其符合既有列表选择条件；保留原 retained-owner 与 title 断言。 |
| [两项 compaction 完成屏障](native-evidence/core-compact-finish-r8c-fixture/repair-audit.json) | 在观察原正常 TurnComplete 后等待其既有 finish owner；保留原事件和预算，不增加重试，也不授予新的输入权限。 |
| [WebSocket compaction fixture](native-evidence/core-compact-websocket-r8c-fixture/repair-audit.json) | 原五个响应批次分为 `[2,1,2]` 三段连接，适配当前相位身份；保留全部请求与 sticky turn-state 断言。fixture 的关闭行为也会促成重连，分组断言本身不单独证明生产身份绑定。 |
| [executor hook metadata](native-evidence/core-hook-metadata-r8c-repair/independent-review.json) | 修复生产 adapter 丢弃已有 hook metadata 的路径，保留原 metadata 并由 owner 写入 canonical `threadId`；原输入、timeout 与权限保持不变；r14 的 model-hidden hook 原用例仍失败，不能把 metadata 保留等同于完整 hook 路径已通过。 |
| [原 owner 的终止确认](native-evidence/core-unified-termination-r8c-repair/repair-audit.json) | stage 42 的 7 文件修复新增共享一次请求与同 owner 退出观察的一秒合作预算；仅真实 native exit 确认后移除 owner，ACK、关闭或超时不冒充退出。保留既有 failure 优先级和身份检查；合入 stage 43 后通过 r14 Core 严格门，6 项新边界回归均通过，未改的真实 shell 持久用例也通过；111 条原断言保持。完整 Core 门仍失败，见[逐项回归读回](native-evidence/r14-core-checkpoint/REGRESSION-CASE-READBACK.json)。预算不抢占同步 Local 系统调用，也不覆盖 manager 锁获取与后续清理。 |
| [五项非登录 shell fixture](native-evidence/core-eperm-r8c-fixture/repair-audit.json) | stage 43 只在两份测试源的五个既有 config closure 中设置 `allow_login_shell=false`，保留原命令、权限合并、approval、精确输出与全部断言；不修改生产默认值或过滤 stderr。原额外输出和已固定的宿主 profile 源码支持初始化链推断，但没有逐 case 的 syscall／进程 trace。r14 原五项行为用例均逐 ID 通过，见[逐项读回](native-evidence/r14-core-checkpoint/REGRESSION-CASE-READBACK.json)；完整 Core 门仍有其他失败。 |
| [cold root resume 阶段诊断](native-evidence/core-cold-resume-r8c-diagnostic/read-only-audit.json) | 只给两个原 `get_thread` 和一个 `restart` 错误增加阶段与目标 ID；stage 39 为 `e267843…` / tree `076d8a5…`。旧 ThreadNotFound 根因仍未确定，不称修复。 |

原八项 zsh watchdog 超时在 r14 中逐 ID 对应为 **7 PASS、1 FAIL、0 TIMEOUT**；剩余 skill-approval 用例在原事件等待器 10 秒内失败，不能改记为通过。当前原 DotSlash fetch 与原 zsh 截获 preflight 均满足 fixture 的既有判定，但这是缓存已存在时的观测，不证明旧超时发生在下载步骤。新增 [CI 资源准备](native-evidence/ci-test-prerequisite-repair/static-review.json)沿用原 descriptor 与校验规则，并运行原 runner 回归；不修改测试 deadline、过滤器或断言。stage 37、38 与 stage 39 诊断均未包含在 r11 的 stage 36 执行树中。stage 42、43 晚于 r13 的 stage 41 执行树；r13 已闭合的三包通过不能替代 r14 的完整 Core FAIL 结论，也不能替代后续修复与完整工作区重验。

### 分阶段评审与封存计划

提交按以下阶段组织；当前已创建的不可变 Git 对象及对应实际测试 tree 见 [SOURCE_IDENTITY.json](SOURCE_IDENTITY.json)。分支和 Draft PR 在最终源码与证据齐备后创建，当前不宣称已发布或合并：

| 阶段 | 连同改动一起评审的范围 |
| --- | --- |
| 既有源码组合 | #4887 与 #4890 的导出/模块组合，以及原 CI migration fixture、PTY 接口问题的有据修复；保留原失败日志。 |
| 严格门 API 修复 | 按 Cell boxing、Context metadata、Circuit revision、授权 effect 输入/恢复分别组织；每个源码调用变更与其真实消费者及现有测试原子提交。 |
| Global Q24 输入桥 | importer、独立绑定与 7 项 fixture 回归一起提交；不混入真实 Encoder 或 Head parity 声明。 |
| Backend registry | 注册身份校验、原 owner 入口/恢复和 7 项回归一起审阅，依赖前一输入桥阶段；最终 diff 过大时继续拆成可编译、可验证的阶段。 |
| 最终格式与证据 | 最终 fix/fmt 的差异单独核对；源码定型后归档 source manifest、所有成功/失败命令回执和完整日志，再提交成熟度、研究与状态索引。 |

当前新增 projection 与测试合计 368 行，registry 与测试合计 502 行，尚未计少量导出或最终格式化；二者共 870 行，应分开评审。精确提交尺寸以最终 diff 为准。文档/证据提交需要明确映射到实际测试的源码树，不能把后补说明的提交号直接写成曾执行的测试身份。

### 冻结研究的实际含义

冲突任务中，按需求分化的平均测试 MSE 为 **0.002552108**，原父模型为 **6.044695446**，固定专家为 **0.002614898**。分化确实解决了这一构造任务的冲突，却未满足“每个种子相对每个强对照至少改善 0.0005”的原条件：相对固定专家平均仅改善 **0.00006279064223624**，五个种子全部失败该项。冗余任务没有持续需求或负迁移，候选保留原父模型、预测相同而诊断成本增加，正确保持 HOLD。

原协议是每个被拟合模型 128 步与候选 FP 操作量上限，**不是六臂严格同总计算预算**。655 个捕获成本事件计一次，共 49,090,740 估算 FP 操作、37,120 路由决策。它们不是物理能耗计数。序列化后预测复核不是跨节点完整状态迁移，完整成本净收益和真实长期采用仍未通过。完整六臂表、进程计时、来源与限制见 [研究说明](study-evidence/README.md)。

## 历史资产如何进入统一合约

| 历史资产 | 可复用的已存在部分 | 仍不能转移给本轮的资格 |
| --- | --- | --- |
| 共享 Encoder＋私有 Head（#3650） | Granite、EG2、FeatureBundle、selected-only worker、私有状态与 snapshot。 | 新来源视频/联合 AV、真实 Q24 桥接、768→≤512 的合格投影、生产 owner 接入。 |
| V13 MiniLM＋Residual Adapter（#4532） | 官方固定 ONNX、实际训练、完整参数/Adam/RNG/sampler 续训与特定 profile 的三 VM 证据。 | 稳定保留、强检索对照净收益、任意硬件或别的模型状态恢复。 |
| V14 内部 encoder LoRA（#4541） | Attention query/value 适配与八分类头、结构 gate。 | 它不是冻结表示或 causal LM；21 个结构候选均未采用；完整 Transformer 续训未通过。 |
| V15 持久评价/authority（#4892） | 类型敏感评分、comparison/look ledger、unknown 结果与路由 trace 诊断。 | 整体恢复旧 authority DB＋keys 的反例、独立 freshness、缺失 trace 与长期净收益。 |
| 真实生成与小型 Rust 内容网（#4442） | SmolLM2＋训练前缀、另一个小网络的原生数值差分与媒体读回。 | 自然语义与流式联合质量、统一产品 owner；历史开放文本事实检查为三臂各 0/4。 |
| Digital feedback/readout（#4578） | 有实际训练和预算的 belief、continuation-Q、readout 与控制研究。 | 该记录固定物理 dynamics；48 个 DEV 质量条目均未合格，不能宣称通用 World Model 优势。 |

每项精确 commit、blob、模型修订与历史结果见机器清单；本轮未重新训练这些历史模型。功能职责与 HNMF 记忆组织保持两套独立分类，不按序号互转，不要求恰好七个模型。

## 已复核的原上游 CI 失败

上游已不再仅处于“排队”状态。保存的原始日志表明：

| 原 job | 原结果 | 具体未通过项 |
| --- | --- | --- |
| [#4890 native：127369396829](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42062983444/job/127369396829) | 165 tests 通过；job 仍失败 | formatter 检查产生差异并退出 1。 |
| [#4887 mechanisms：127392153697](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42069233246/job/127392153697) | 502 run：501 pass、1 fail；另 1 skipped | `v1_store_migrates_atomically_to_dispatch_outcome_schema` 返回 `Unavailable`，两次原尝试均失败。 |
| [#4887 Agentd：127392153944](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42069233246/job/127392153944) | 631 pass；66 skipped；job 仍失败 | 严格 Clippy 因 `AsyncFd::new` 弃用/安全接口变更在 `codex-utils-pty` 失败。 |

完整原日志和哈希在 [upstream-ci](upstream-ci/summary.json)。这些结果属于各自原提交；本轮两包通过不能代替 automation、Agentd、整工作区或原 GitHub 门的闭合。最终联合门必须保留失败、跳过和修复后的源码对应关系。

## 剩余采用 blocker

| 工作面 | 必须补齐的具体证据 |
| --- | --- |
| 当前统一源码资格 | stage46的r17三包严格门和完整4,063项测试通过；默认193成员工作区r18正在运行。须完成其终态、最终fix/fmt、最终源码与依赖身份及远端CI。全部原失败记录、既有skip和实际执行树继续保留，不能把重叠阶段的计数相加。 |
| 真实后端与特征接线 | 原 Encoder 的真实 FeatureBundle＋conversion receipt→独立 source/owner pins→Rust importer→同一现行 Head/模型→读回；原始输入与完整生成/状态 schema 保持正确。 |
| 真实生命周期与恢复 | 由既有 owner 完成 drain/fence/transfer/install/readback/rollback；所有适用参数、optimizer、RNG、sampler、decoder/transition 状态和运行时 profile 一并恢复；unknown 不重复分派。 |
| 独立来源与最终使用 | 解决旧 authority 整库回滚反例，建立独立 freshness/撤销信任；真实目标端在最终使用点核验当前身份，不能以同库签名替代。 |
| 保留、校准和完整净收益 | 固定强检索/KV、linear/ridge、强固定策略、父模型继续训练及 no-change 对照；冻结独立任务与足够多代窗口，比较同输入和明确预算下全部训练/推理/存储/迁移成本。 |
| 多模态与预测/生成质量 | 新来源视频及联合 AV、动作条件预测、自然语义评分、学得的流式一致性；自 critic 不独立签发最终质量结论。 |

当前总体状态为 **DRAFT / 部分机制有原生通过证据 / 科学收益 HOLD / 生产采用未合格**。历史研究、注册、计数、有限机制测试和真实部署收益分别记录，不能互相代替。
