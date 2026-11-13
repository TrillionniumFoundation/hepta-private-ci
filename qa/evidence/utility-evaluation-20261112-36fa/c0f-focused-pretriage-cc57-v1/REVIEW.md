# c0f focused 失败与 cc57 源码对照：独立离线预诊断

## 结论与范围

历史 c0f 的 28 个失败并非同一类问题：24 个有明确栈溢出输出，2 个达到单用例 60 秒终止条件，另 2 个分别返回 `InvalidBinding` 与 `OwnerUnavailable("original learning evidence owner")`。当前 cc57 包含有实际代码依据的内层 future 装箱、provider 场景分区和 unsorted route 对齐；deep 与 NextUse 的相关改动主要增加诊断。**本审查不将任何历史失败改判为通过，不给 cc57 原生行为下结论。**

固定历史源为 `c0f78493f815780f68b9bf5e390a21314d79311f` / tree `313ee34febc8ccc54c611ab56286e289518c63cb`；固定对照源为 `cc57c7198db6293ccca562253c42fffbe2a04633` / tree `b7b357c07b5539769a068c6b9b009629f5612d1e`。本次核了 30 条明确相关路径的 59 份版本字节、42 个独立 Git blob；另按固定全量 inventory 比对了 24 条相邻 production 路径。它不是整个仓库的行为证明。

### 原件

- 完整 JUnit：`96d5b747e0579ff70730a89f70eb7ae3b70dd479`，49,808 B，SHA256 `e1e7901986fef0bb4a682156d87eef31b93a54f7e8759e564966dac136e198e7`。
- 完整 focused raw：`d833e7724371e4626ac5860c356c5ac2f07e9934`，135,424 B，SHA256 `0a66330b21fee14ed42d276eac31fc2be6214de378ce42ff192f382cbeac27c5`。
- 原命令/终态：`465232e636f286344d9a4941960decee4d97c4e5`；原 Root 分类复核：`9f876775e386e4f9ca51e8c9ca5f429fd0d72331`。
- 单 case 原 GDB：`e0c0d9d82475980089e921ec2332c907469b02a6`；4 caller 原序言：`f919c40fff919bf7395a87e492bcc34be0f4c624`；当时的源码/算术审查：`a0af9f060bdcf61b42d3073f8869d3655f1a80b3`。

这些原 blob 此前已在证据树中，本次完整读取后按原 Git SHA 校验，未重新运行它们。新 `OFFLINE_ANALYSIS.json` 包含 28 个完整 FQN、原输出、时间、对应源码和逐版本身份。

## 1. 历史运行到底证明了什么

原 focused 命令是完整的原七 filter 联集、两个 crate、`--lib --test-threads 2 --retries 0`，原 `just test --locked --offline` 入口。执行记录为 2026-11-12 14:21:06.133352 至 14:37:06.751728 UTC，返回 100，非命令 timeout，未触输出限额。960.6167 秒包含构建；JUnit 用例执行段为 409.228 秒。109 个用例中 81 通过、28 失败；不是 28 次测试进程启动失败，也不能把整个命令的墙钟时间当单用例时间。

原始 source before/after 均固定 c0f、tree 一致且 clean。后续 all/Root 不能借此 focused 结果取得资格。cc57 新增了默认用例和分区用例，最终运行集合应由当前源和原 filters 决定，不能以旧 109 的计数限制新运行。

## 2. 24 个栈溢出用例的具体共同路径

下表所有叶测试函数在 c0f 与 cc57 **逐字相同**；完整 FQN 均在 `OFFLINE_ANALYSIS.json`。共同入口为 `model_selection_owner::original::evaluation_provider::panel_members`，实际模块 `#[path]` 已逐条读核。

| 原失败组 | 数量 | 实际叶源码（均在 `codex-rs/hepta-agentd/src/`） | 共用装配链 |
|---|---:|---|---|
| panel 直接读、签名续期拒绝、撤回/恢复字节永久拒绝 | 3 | `circuit_original_evaluation_panel_tests.rs` | `PanelFixture::completed` |
| Evaluation host | 3 | `circuit_original_evaluation_host_tests.rs` | `HostFixture::new` → Panel |
| Model material | 3 | `circuit_original_evaluation_model_material_tests.rs` | `HostFixture::new` → Panel |
| Evaluated retention context | 2 | `circuit_evaluated_retention_context_tests.rs` | `HostFixture::new` → Panel |
| Evaluated publication | 6 | `circuit_evaluated_retention_publication_tests.rs` | `PublicationFixture::ready` → `HostFixture::before_adoption` → Panel |
| Evaluated Selector receipts | 3 | `circuit_evaluated_retention_receipt_tests.rs` | 同一 Publication fixture |
| Evaluated C receipts | 4 | `circuit_evaluated_next_use_receipt_tests.rs` | 同一 Publication fixture |

共用 Panel 先 `preregistered_for_publication` → `PositiveFixture::ready_for_publication`，随后实际 retention member 完成，再实际 primary member 完成；每个 member 经 `PanelMemberFixture::complete` → `qualification_owner.qualify_or_readback`。这是真实装配依赖，不是仅从文件名归类。

cc57 相对 c0f 的两处相关新增装箱为：

1. `circuit_original_evaluation_panel_tests.rs` 的 `completed_member`：将完整 `PanelMemberFixture::complete(...)` future 用 `Box::pin` 包住。c0f blob `c968ff41de9cca02f5321cb2fa813ef5f8eeef6b` → cc57 `89e82d4b77f7cd76ac8df20e4ad88790e66a7158`。
2. `circuit_original_evaluation_panel_member_support_tests.rs` 的 `complete`：将完整 `qualification_owner.qualify_or_readback(...)` future 用 `Box::pin` 包住。`0e7f3c909fcc97742e228eb4ad189bd074727604` → `2bdf58f807f79da78a0d1e8ee66ebf735fb7cb7b`。

两处均保留原参数、同一 owner、`.await`、错误传播、retention-first 顺序与断言。c0f 已经有 Panel 顶层 boxed async body、对子 `preregistered`/member 的 Box，以及 PositiveFixture 的相关外层 Box；不能把这些旧 Box 当成新增修复。当前 `circuit_model_selection_owner_support_tests.rs`（27 kB 的 PositiveFixture 文件）仍完全等于 `127e9731d146a8a30b2f6cfa8b563f97afe694a8`。

相邻 24 条 production host/command/service、panel/member、qualification、model-material 路径在两个完整 inventory 中均为同一个 Git blob，包括两条已有 retention guards。详情在 `STACK_ADJACENT_PRODUCTION_INVENTORY_COMPARISON.json`；此项为完整字节身份对照，不是重新执行这些生产函数。

### 只对一个原 case 有首信号实测

`original_panel_reads_actual_b_and_retention_with_full_original_signatures` 的原 c0f GDB 首停在 `PositiveFixture::ready_for_publication` poll 的序言栈探测。原 8 MiB 测试线程 writable stack 为 `0x71d6fe800000..0x71d6ff000000`；fault 处 SP/地址在其下方 4 KiB guard 内。原 caller SP 为 `0x71d6fe915b60`，上方已占 7,251,104 B，仅余 1,137,504 B。

| 原 ELF 实际函数 | 序言局部 reservation |
|---|---:|
| `PositiveFixture::ready_for_publication` poll | 2,284,152 B，另 16 B pushes |
| `preregistered_for_publication` poll | 1,186,072 B |
| `PanelFixture::completed_for_publication` poll | 1,861,448 B |
| panel test poll | 2,608,216 B |
| panel test entry | 1,586,536 B |

四个 caller 的局部 reservation 合计 7,242,272 B；其余 8,832 B 未逐帧归属。ready 原指令计划需求超过剩余空间约 1,146,672 B；它在 page probe 中途已 fault，并未成功完成整个 reservation。原 CFI 有界提取未取得，不补造。

这解释该原 case 的首次碰撞，不能推为全部 24 个的共同根因。Box 将 future 状态放到堆上不等于消除 poll 栈帧或构造临时量；更深 member future 即使尚未 poll，也可能影响父 future 的静态布局。新两处 Box 有合理的源码作用点，但其实际降幅和是否充分只能由新二进制观察证明。本次不添加猜测性 boxing patch，不延长 8 MiB/60 秒合同。

## 3. 两个 timeout 的改动不同

### Provider 的六场景已有完整分区

历史 `original_evaluation_provider_current_withdrawal_and_corruption_never_release_cached_rows` 在 60.017 秒 timeout。旧用例依次构造四种 mutation（withdraw/source-bytes/ledger-bytes/rollback）和两种 mode（unreleased/cold-readonly）的真实 B cohort。

cc57 将原 body 搬到 `current_refusal_cases`，分为三个默认测试：原名字执行 withdraw/source-bytes；`original_evaluation_provider_ledger_corruption_and_clock_rollback_never_release_cached_rows` 执行 ledger-bytes/rollback；`original_evaluation_provider_unreleased_and_cold_readonly_never_release_cached_rows` 执行 unreleased/cold-readonly。将新 helper 的两个 loop header 投影回旧常量后，**其余完整 body 与旧 body 逐字相等**。六场景联合完整，每组重新取得真实原 owner；所有实际读、恢复字节后的永久拒绝、只消费一次及 bytes assertions 保留。

这是减少单个用例工作量的实际改动，未增加每用例期限。它可能增加整套总装配工作，不能以旧 case 名仍存在就遗漏另外两个，也不能称已证明新的三个各自能在期限内完成。该文件另外四处新 `Box::pin(preregistered())` 属于 missing/wrong outcome、renewal、expiry、zero-support 兄弟测试，不属于上述 24 个栈例的唯一新增装箱清单。

### Deep 用例只增加诊断

历史 `q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources` 在 60.014 秒 timeout。当前 `circuit_deep_training_readback_tests.rs` 新增一个 logger 和 32 个 stage 调用；精确删除这两类新增文本后，旧完整测试函数逐字恢复。`circuit_deep_training_readback_support_tests.rs` 的 21,868 B 完全不变（`5752c7e3c43931277c84bcec952450bc49415af9`）。

原测试仍顺序执行真实 A/Material/T、S、不同任务 C、C 签名、hot/cold 读回、只读拒绝、所有物理 bytes 比较和各原线程 join。历史 timeout 输出没有定位某个 join 或 owner；单次旧栈采样也不能证明死锁或热点。最小下一步是使用已存在 stage 输出定位新运行的最后完成阶段，并与同次原始线程/owner 终态对应。本次没有足以证明安全的新增优化，不省略 fresh owner 读、不缓存签名结果、不改 deadline。

## 4. 两个功能错误

### Unsorted source：已有确定性 fixture 对齐修复

旧 `original_evaluation_accepts_unsorted_source_policy_without_reordering_its_bytes` 在 12.044 秒返回 `InvalidBinding`。原 source helper 已把候选 definition 按实际 input 的降序排列，而 `configuration()` 保留 routes `[a,b,abstain]`。`circuit_cell_binding.rs::CircuitCellRegistryV1::new` 在第 102–107 行对 routes/candidates 逐位置 zip 比较，身份不符直接 `InvalidBinding`。配置来源 `circuit_cell_tests.rs::configuration` 及 `cell_q24_dataset_source_test_support.rs` 的导入链已读核。

当前 helper `bc7be5dd406bb4da8afda7a9fd9df06cda2cece0` 按 candidate ID 移动完整原 route 对象，使 outcome/edges 与原候选保持配对，并保留数量、重复、缺项和剩余项检查，再计算原 route policy digest。原 input 顺序、activation 映射、selected ID 不重写；生产 registry 的 zip 拒绝未变。这是可证明的旧 fixture 前提错误修正。原修复 manifest `dfd30e0e1471c5bd8f4dd74fca42dedee99e36bd` 的完整后像与当前 cc57 字节相同。

历史 raw 未提供抛错行/回溯，所以这里只证明独立可达的确定性拒绝，不把推导说成原运行回溯，也不宣称新用例通过。无需基于旧日志再做相同修复。

### NextUse withdrawal：保留 Unknown 根因

旧 `q24_next_use_command_readback_refuses_actual_publication_withdrawal` 在 8.949 秒返回 `OwnerUnavailable("original learning evidence owner")`。原始输出只有错误类别，没有精确调用点；不能直接断言它发生在撤回后的拒绝步骤，或者把 8.949 秒整例时长等同某次 500 ms 超时。

实际测试先取得原 S、执行不同 C、取得 C completion，再对当前 C evidence 作一次应该成功的 readback，随后才 withdraw 原 publication。cc57 在这次 pre-withdrawal 读上增加了 elapsed 和原 evidence-server join 结果的错误留存；无第二请求、重连、deadline 延长或替代签名。它是诊断改进，尚无恢复该历史失败的行为修复证明。

`LearningIterationEvidenceClientV1::readback` 及测试用 evidence channel helpers 字节不变。evidence exchange 仍 500 ms / session 300 s；一般 command channel 仍 30 s。client 会把通道竞争/已消费、transport/read failure、部分回应关联检查和 lifetime failure 汇成同一个 OwnerUnavailable。因此该字符串不能单独区分超时、EOF、原 owner 拒绝或错误回应。

当前 C evidence service 委托到新增 `observe_original`；其 Legacy arm 仍使用同一 context snapshot/live/T/S，并由同 runtime `block_on(readback_remote(...))`。原 owner 的 typed trainer 调用改为同实际类型 UFCS，另有 profile guard；均不能自动视为解决旧 OwnerUnavailable。应先用新同次错误/elapsed/server result 判断具体失败层，再考虑最小修正，保留原单次通道消费和 Unknown/拒绝语义。

## 5. 后续边界

没有执行 H、Cargo、Rust case、原 verifier 或完整门禁；没有修改生产/测试源码、控制预算、stack、test filters、refs 或 PR。仅运行纯本地 XML/JSON/hash/字符串对照脚本。源码在此作为原 Git 对象读取，完整内容身份与固定 inventory 相符；并未把远端源重新 materialize 或进行第二次原生观察。

本报告的四类结论分别是“单个旧 case 的实际栈证据”“已存在的源码修正”“保留的诊断改进”和“根因仍未知”。新的流程若在前置检查失败、尚未进测试，也不属于这 28 个行为失败的再现。

这些 fixture 使用真实原 owner 和实际文件机制，但密钥、admission、角色及 Outcome/时钟仍为显式测试输入。本报告不把源码门禁、工程 fixture、原件恢复或多个 agent 的审查写成真实独立 B 或真实净效用。
