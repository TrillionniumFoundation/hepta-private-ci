# 最终 source/native 资格链：最小后继绑定清单

**结论：原门禁代码与预算可继续复用；最终身份与 admission 消费实际证据的接缝尚未绑定，保持 HOLD。** 本文是离线审查清单，不是批准配置、门禁执行结果或真实任务闭环。当前 d256/a489 是已冻结的维护输入；最终 fix/fmt 后像、最终 canonical tree/commit、完整 clean 库存与 native compact 库存均为 **Unknown**。

## 1. 已复用的原合同与本次唯一新增核对

| 原件 | 固定 Git blob | 本次结论 |
|---|---|---|
| source gates | 51181866cbbb6e0176aab04117efffa8b6792b31 | 保留完整 main：独立 shared/no-hardlinks clone、冻结、全物理库存、600/300/4800 三门禁 |
| 总计划 | 3aefbc71d69d8014eed9e5a18269bbcc866a7583 | 14 个原 phase ID、原命令与预算；历史计数不是最终门槛 |
| native wrapper | de3e9dc5e7eb30f47929f9e1ba9f460035a94fae | 完整 eval lib → B92 focused → B92 all；不再 fix/fmt |
| B92 native driver | b92ddded4fce78aeb076d022471c62bf81ce2e4f | 从最终 workflow AST 读取 packages/parents；原 helper、JUnit、Root setup/cleanup |
| source handoff wrapper | 8607fa4bf00fc8cf535849de04d1eb6ff29429b3 | 原 5118 main 原样调用；rc0 与 payload passed 必须同时满足 |
| d256 workflow | c0012652889b0cca409b27f87bfdc74b234c0fbe | **48 个唯一 Root FQN = 原39 + 新9**；原33仍是该清单前缀 |

既有完整准备合同位于 hepta-complete-new-source-handoff-hold-v1；本次不重写编排。纯 AST/字节提取把全部48名称、精确 Root filter、四个 eval 回归名称、全部原命令和14阶段预算保存在 **STATIC_TEMPLATE_BINDINGS.json**。这里只摘要绑定差异。

### 保留的运行范围与预算

| 阶段 | 原范围 | 秒 |
|---|---|---:|
| source-closure | 完整 discover：qa/b4-no-bypass，*source_closure.py | 600 |
| caller-self-test / caller-verify | 原 verifier self-test / 全 source verify | 300 / 4800 |
| eval-lib | codex-hepta-intelligence-eval 完整、无过滤 --lib，threads2 | 3600 |
| native-toolchain / helper-build | 原工具版本观察 / 原 helper 构建 | 120 / 3600 |
| helper-verify-before / after | 各次 B92 调用的原 helper 验证 | 120 / 120 |
| focused | 原7项 filter，agentd+eval --lib，threads2 | 7200；driver 外层12000 |
| ordinary | 原5包全部 --lib，threads2 | 7200 |
| root-setup / root / root-cleanup | 原 sudo Root fixture；48完整名称；finally清理 | 60 / 7200 / 60 |
| all-native-driver | ordinary → Root；保留自身 toolchain/helper，不重复 focused | 外层21000 |

14是原计划的 phase 条目数；toolchain/helper 会按原 B92 调用重复，all-native-driver 是包含 ordinary/Root 的原外层，不应改写成14个独立测试命令。source 外层 **7200**、native 外层 **45000** 原样保留。source7200还核了历史实际 request eae8d46956ac3afd89bf18b30d69997cbe925788，未用三个内层预算相加推测。

ordinary 五包按原序为：codex-hepta-agentd、codex-hepta-learning-ledger、codex-hepta-learning-artifacts、codex-hepta-intelligence-eval、codex-hepta-neuron。ledger 已包含在内，不另造重复 phase。

Root 保留 --run-ignored only、--test-threads 1、--retries 0，filter 为每个完整 FQN 的 test(=name)。原 collector 成功后，B92 要求 **sorted(实际非skipped JUnit names) == sorted(最终 workflow parents)**；缺项、重复或多余非skipped项不能替换为“达到48”。实际 fresh JUnit 尚未产生。

justfile/run-nextest/nextest.toml 在 a489 图中仍是原字节：8MiB 栈、local profile、--no-fail-fast、各原命令显式 --retries 0。配置默认 retries=1 本身未改，显式命令0须保留。30s×2默认及 ledger 180s/600s既有 overrides均不动。不能声称所有 ordinary case 都是60s。

## 2. 后继只应绑定这些面

| 面 | 必须接收的实际内容 | 本次状态 |
|---|---|---|
| 维护终态与后像 | 本次原 normal、RESULT、fix/fmt terminal、完整原log、所有实际 source-before/after、raw Git/index、inputs/环境审计与 postimages | 最终结果 Unknown；不能从 stage成功或物化 normal0 推定 |
| 最终非Rust保护 | 根据实际fmt字节逐项核 CALLERS、完整 protected bodies/额外约束、QA mutation定位、allowlist；保留旧断言与原计数口径 | 仅预留633/442基线，未刷新为最终 |
| 最后格式化及canonical | 最后非Rust整合后原 fmt900 实际原件；所有后像复核；最终 commit/tree/parents、clean物理与正常index/stat、原证明链 | Unknown；不把d256/a489预填为最终 |
| admission consumer | 对最终fmt/alignment/materialization/维护 proof 的真实 schema/pins/path/完整raw Git映射做窄后继；历史runtime与当前repo实例分离 | 需后继代码同行，不能仅换cfg |
| source cfg/launch | source_sha/tree、object_repository、独立fresh source_checkout/records/run_identity、原5118/recorder pins、600/300/4800；原7200/noenv typed request | 未生成批准配置或请求 |
| native cfg/launch | 同最终source/tree/parents、实际 compact count/hash、完整物理pin、target/runtime/lock、fresh records与 /run 直接子目录；原4回归名；原45000/noenv typed request | 待 source 完整成功证据后再精确冻结 |

原23d412 admission 是明确的旧实例：它硬绑 cc57/B7/15188/16449、旧 CURRENT_REPO、旧 materializer/config/packet，以及旧 final-format/alignment producer 谓词。**不能以“5118/de3可不改”推导 admission 也只需替换配置。** 应保留既有双实例设计、完整稳定元数据、真实 lease/process/resource/原runtime守卫，在最终真实 producer 输出后仅修改具体身份/schema接缝；不能把历史archive inode或原source路径偷换成当前观察。

stage/main 的许可与实际 terminal 是不同事实。后继 exact request、全部控制文件全文读回、具体 Root 批准应独立保留；unknown admission只核对原身份，不重发新key。本文没有填 state=ready、批准布尔值或任何可执行后继。

## 3. 必须按顺序接收的 actual outputs

1. **完整最终 source**：维护和最后fmt的原 normal/RESULT/logs/postimages；非Rust后像及 review；最后 clean canonical 对齐/物化原件、全physical/index/Git metadata和真实源输入审计。完整证明收齐前不进入资格链。
2. **source阶段**：原5118新clone与checkout记录、source-freeze/baseline；三gate原dispatch/start/terminal/raw log/original recorder/gate-final与retained manifests；run-result、wrapper RESULT和原supervisor正常终态；origin before/after及完整物理审计。只看汇总“passed”不够。
3. **native前提**：Root已独立核source完整通过；同source的当前build/process/target/lock/runtime观察；真实工具与helper Cargo输出/manifest/env；新exact请求。source clone和全部source原件先完成，随后才让native写source-local ignored JUnit。
4. **native结果**：完整eval fresh JUnit与原4回归；focused fresh JUnit及原 mixed-evidence case恰一次；ordinary真实5包和原owner coverage；Root实际UID0、48精确FQN、setup/cleanup；所有原execution/driver terminals、logs及source snapshots。163、旧28失败、旧source PASS均是历史，不转移成新结果。

原5118即使source-closure失败，只要source未变仍可能运行独立self-test；verify仅在self-test通过后运行。任一已知失败仍导致整次failed，未运行不算通过，归档失败可使原passed降为unknown。source wrapper还要求原main rc0与payload passed一致。native一阶段失败停止后续suite，原finally证据/清理继续保留；无法取到before/after时如实Unknown。

## 4. 两种库存和最终保护审查预留

- **5118 full physical inventory**：包含ignored文件、所有index条目、实际权限/稳定性/working blob；新clone只对自有非hardlink文件去写权限。因此clone库存与origin库存不是同一字节串。
- **native compact snapshot**：git ls-files 加非ignored untracked，path/mode/bytes/SHA256/blob（或missing），独立HEAD/tree/status；不含source-local ignored JUnit。它的count/hash必须从最终实际snapshot验证，不能用full库存hash代替。
- admission最终完整观察会看到测试生成的ignored artifacts；必须按原范围保留和审核，不能从compact相等推导所有物理文件相等。

本次预留7个非Rust路径，其完整前像pins见提取证明：

- .github/blob-size-allowlist.txt
- .github/workflows/hepta-daemon-learning-native.yml
- CALLERS.toml
- qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json
- qa/b4-no-bypass/test_evaluated_published_read_source_closure.py
- qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py
- qa/b4-no-bypass/test_resident_root_source_closure.py

复用既有独立静审 b90584055478ffe6d9c20f585349753b361784c7 / 原字节证明 b84c6853a31996e21df55d2f9239e4e29387e0fd：633 boundaries；442 protected（原437完整forbidden等附加约束不删）；provider45路径/288 scopes，ordinary34 scopes/17 literals；64 QA文件原604方法602原文相同、2明确迁移、增3，准备态共607；Root39+9=48。它们是**维护前静态基线**，不是完整collector或最终QA通过。后续新增/移位只按实际后像逐项核，不扩ignore，不按保护path去重。

## 边界

本次只实际运行了独立stdlib AST/JSON/TOML/哈希提取，没有import/执行原runner、main/preflight、QA、Rust、formatter或H；没有修改source/ref。局部准备中一次JS模板插值错误和一次本地多LF复制错误已单独保留，后者从完整原Git响应精确恢复990字节后验证，均不属于项目或门禁失败。实际工程门禁通过也不会自行证明生产host装配、独立B、授权任务A/B/C或真实utility闭环。
