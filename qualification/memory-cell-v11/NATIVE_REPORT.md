# V11 原生 Cell 生命周期验证报告

本报告记录 V11 原生生命周期实现的实际验证结果。精确受测提交为 **`1bc02cb33a380cf53bb58333b2ee8b3d1a70f175`**：GitHub Actions 实际执行 **517 个测试，517 个通过，0 个失败**；nextest 另报 **24 个 skipped**。其中八个 V11 专门用例全部执行并通过，包括向两个 owner 广播同一 withdrawal frontier、未受影响 cell 对相同参数版本重新 admission/install，以及重建计划后的真实读取。随后 scoped `just fix` 和 `just fmt` 均成功，且未改变受测源码树。[实际 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41062425475)、[独立核验记录](evidence/native-ci/41062425475/VERIFICATION.json)。

该结果覆盖 `codex-hepta-memory` 与 `codex-hepta-agentd` 的 scoped library 回归，并未运行整个 workspace 测试套件。生命周期夹具使用明确标注的解析构造参数，结果不构成学习质量、整体存储压缩或生产通用记忆服务的验收。

## 1. 精确源码与证据身份

| 项目 | 实际值 |
| --- | --- |
| 受测 source commit | `1bc02cb33a380cf53bb58333b2ee8b3d1a70f175` |
| 受测 source tree | `73de4b2ac95f7be92261dd7df07b8e70ddb5ddb3` |
| GitHub run / attempt | `41062425475` / `1` |
| GitHub job | `124085223772` |
| GitHub artifact | `12981851880` |
| Provider 最终结论 | run、job 均为 `success` |
| 原始 artifact ZIP | 454,165 bytes |
| 原始 ZIP SHA-256 | `059eb9563458675dabddbcb0e3c12ec198bf5d2acf06836511afd544d570a585` |
| 完整 source inventory SHA-256 | `135ebab68797bc86870ce1390ec0fa32097c6fe2caf08d2d57c65786fed09720` |
| 原生/build input 条目数 | 8,080 |
| 规范 input entries SHA-256 | `a20f51039d9608605e19196be33730217c317e38251c468817e923b4783f7d2d` |
| `NATIVE_BUILD_INPUTS.json` 文件 SHA-256 | `7e18e949550eb5dceba94a13546c168cfdcb864f573345f51fbf0130c750b7e7` |
| `VERIFICATION.json` 文件 SHA-256 | `d92180c99bfa0949fb16456912adc1b27a6244a5a056c4d6d0b7229ebe022974` |

下载的原始 ZIP 已与 GitHub 返回的 artifact digest 核对。artifact 中的完整 `source-tree.txt` 与本地对该精确 commit 执行 `git ls-tree -r --full-tree` 的结果逐字节一致。独立核验同时检查了 JUnit、各命令退出码、执行顺序、同源 executable 身份及各阶段空 patch/status，不能仅以 workflow 的绿色图标代替这些证据。[Provider 状态](evidence/native-ci/41062425475/PROVIDER_STATUS.json)、[raw receipt](evidence/archives/native-success-v11/README.md)（包内 `artifact/receipt.json`）、[source inventory](evidence/archives/native-success-v11/README.md)（包内 `artifact/source-tree.txt`）。

原始证据树位于 `evidence/native-ci/41062425475/`，包括 `artifact.zip`、完整解包内容、`PROVIDER_STATUS.json`、`VERIFICATION.json` 与 `NATIVE_BUILD_INPUTS.json`。原始日志的 Markdown 链接指向可在 GitHub 打开的持久证据包入口，并在括注给出包内成员路径；小型 verification/provider/correction 记录保留直接链接。成功 run 的完整解包成员可从 [native-success-v11](evidence/archives/native-success-v11/README.md) 恢复，失败 run 从 [native-attempts-v11-early](evidence/archives/native-attempts-v11-early/README.md) 恢复；总入口见 [evidence/README.md](evidence/README.md)。下载 ZIP 的身份与持久归档的身份分别记录，不要求重新打包能复现 GitHub ZIP 的封装字节。GitHub artifact 本身存在保留期限，不作为唯一长期副本。

## 2. 实际执行顺序与同源 App Server

CI 使用 Ubuntu 24.04 runner、Rust `1.95.0`、cargo-nextest `0.9.131` 和 just `1.51.0`。资源配置为 `CARGO_PROFILE_DEV_DEBUG=0`、`CARGO_PROFILE_TEST_DEBUG=0`、`CARGO_INCREMENTAL=0`、`CARGO_BUILD_JOBS=2`。这些版本和资源设置均来自本轮 raw receipt/version logs。[版本与命令证据](evidence/archives/native-success-v11/README.md)（包内 `artifact/receipt.json`）。

以下命令在 `codex-rs` 工作目录执行，顺序和耗时来自实际 receipt：

| 阶段 | 命令 | wall time | 退出码 |
| --- | --- | ---: | ---: |
| 同源 App Server 构建 | `cargo build --locked -p codex-app-server --bin codex-app-server` | 362.38 s | 0 |
| Scoped 测试 | `just test --locked --lib --retries 0 -p codex-hepta-memory -p codex-hepta-agentd` | 223.57 s | 0 |
| Scoped fix | `just fix --locked -p codex-hepta-memory -p codex-hepta-agentd` | 184.36 s | 0 |
| 最终格式化 | `just fmt --base 740dbff4e00b8b74a19c6b7ec487937c1f4c96ab` | 0.44 s | 0 |

验证 step 总耗时为 **772.19 s**；nextest 输出中的实际测试执行阶段为 **35.664 s**。223.57 s 的 scoped 测试命令时间包含构建，二者不能混为同一耗时口径。[测试日志](evidence/archives/native-success-v11/README.md)（包内 `artifact/scoped-native-tests.log`）。

同源构建产物 `codex-app-server` 大小为 **444,006,728 bytes**，SHA-256 为 `6cbef25bf4dfa66573643cc97d0b435d8f76d2173a6907e6faf7cf9ce15d47c5`，receipt 将其 source commit 绑定到上述受测提交。workflow 设置 `HEPTA_TEST_CODEX_EXECUTABLE` 指向这个构建产物。原有 `memory_cell_context_tests::memory_prediction_reaches_real_untrusted_context_and_final_use_races_stop_before_effect` 因此实际运行并通过，没有被跳过，也没有改成虚构 executable。[构建日志](evidence/archives/native-success-v11/README.md)（包内 `artifact/same-source-app-server.log`）、[JUnit](evidence/archives/native-success-v11/README.md)（包内 `artifact/native-junit.xml`）。

初始 checkout、测试后、fix 后、fmt 后、最终状态均记录 tracked tree 未改变；对应 `.patch` 与 `.status.txt` 全部为空。fix/fmt 后没有再次执行测试。若 fix 或 formatter 曾修改受测源码，本 workflow 会留下 patch 并拒绝通过，需要以新源码提交重新完成验证；本次没有发生该情况。[核验记录](evidence/native-ci/41062425475/VERIFICATION.json)。

JUnit 包含 517 个实际执行的 testcase，全部通过；24 个 skipped 来自 nextest 的独立 summary，未被写成这 517 个成功 testcase。报告不把 skipped 当作通过，也不称全部仓库测试均已执行。本轮 cache restore 实际 **miss**，cache save 成功；原始证据先上传，再保存 cache，缓存没有替代任何测试。[Provider/cache 记录](evidence/native-ci/41062425475/PROVIDER_STATUS.json)。

## 3. 已实现的原生生命周期

V11 增加了独立模块，复用现有 artifact owner 与有界数值执行链。原生训练 selector 当前明确接受 **Semantic 和 Procedure** 两类；Python 实验中的其他 cell 类型不能据此视为已经获得原生 decoder、控制 wire 或生产 admission。[投影实现](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-memory/src/memory_training_projection_v11.rs)。

| 层次 | 实现与实际保证 |
| --- | --- |
| Owner training projection | 真实 SQLite owner 的完整授权 snapshot 解析声明的 type/key 分区；完整当前记录、owner、scope、selector 进入 projection identity。最新有效版本、缺失与 tombstone 由 owner 决定。 |
| 历史获取证据 | 历史 acquisition cut 保留在 cell envelope 中；它与局部 training projection digest 分开，不能由训练者提供任意 hash 冒充 owner snapshot。 |
| 独立版本槽 | 每个 cell 有自己的 artifact registry/CURRENT 和 signed selection；替换一个 cell 不要求同时增加 sibling 参数版本。 |
| 不可变 ServingPlan | 计划固定 cell ID、generation、artifact digest、training projection digest、registry binding；拒绝重复 cell、共享 CURRENT registry 和有歧义的训练地址归属。 |
| 查询新鲜度 | 每次读取取得当前完整 owner snapshot；执行前、返回前验证选中 artifact、全部固定 cell 的训练依赖和本次完整查询 cut。 |
| 恢复 | checkpoint 仅保存 pins。恢复重新依赖真实 owner、live CURRENT、signed selection 和 withdrawal frontier，不能把反序列化 metadata 当成 authority。 |

对应源码为 [cell release](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-agentd/src/memory_independent_cell_v11.rs) 与 [ServingPlan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-agentd/src/memory_serving_plan_v11.rs)。

来源分区以外的普通写入，可以改变完整 acquisition/query cut，同时保持该 cell 的训练 projection 和参数版本不变。相应 cell 可在下一次新鲜查询中继续复用参数。正在执行的一次查询仍受完整 cut 检查保护，无关写入也可能使该次查询保守拒绝；这里没有通过删除完整 cut 检查换取“独立性”。

声明分区内任何当前来源更正、撤销或新版本生效都会使旧训练依赖失效，即使本次查询没有直接使用那个训练来源。一个不可变 plan 固定的任意 cell 失效，会使整个旧 plan 拒绝。可复用 sibling 参数的方式是构造包含有效 cell 的新计划，不能声称旧 joint plan 会自动把失效 cell 排除后继续服务。[执行与竞争测试](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-agentd/src/memory_serving_plan_v11_tests.rs)。

### 八个专门用例

以下名称均在本轮实际 JUnit 中出现并通过。前两个属于 `memory_training_projection_v11::tests`，其余属于 `memory_serving_plan_v11::tests`。[实际 testcase 记录](evidence/native-ci/41062425475/VERIFICATION.json)。

| 用例名 | 验证重点 |
| --- | --- |
| `memory_v11_owner_projection_is_local_complete_and_recoverable` | 无关写入保持 projection、相关但未查询来源更正使其失效、SQLite 恢复、错误 owner 拒绝、撤销与 sibling 局部性。 |
| `memory_v11_new_effective_version_and_tombstone_cannot_hide_behind_old_source_ids` | 未来版本生效和最新版本 tombstone 不能被旧 source ID 掩盖。 |
| `memory_v11_candidate_binds_the_complete_owner_partition_and_acquisition_cut` | 候选绑定完整声明分区、来源支持与历史获取 cut。 |
| `memory_v11_independent_cells_reuse_weights_with_fresh_queries_and_replace_one_version` | 新鲜查询复用不变参数、独立版本替换和计划重建。 |
| `memory_v11_query_fences_reject_source_and_selected_version_races` | 查询两端拒绝来源与 selected-version 竞争。 |
| `memory_v11_return_fence_rechecks_timed_dependencies_outside_query_support` | 返回端拒绝未被本次查询直接使用、但已新生效的训练依赖。 |
| `memory_v11_recovery_requires_live_signed_selection_and_withdrawal_frontier` | 真实恢复、篡改 pins 拒绝、共享撤销 frontier fanout、same-version re-admission 与新计划恢复。 |
| `memory_v11_plan_rejects_duplicate_and_ambiguous_ownership` | 重复 cell 与有歧义的 ownership 被拒绝。 |

## 4. 共享 withdrawal frontier 与相同参数版本恢复

既有 V3 artifact admission 绑定整个 withdrawal scope 的 frontier。V11 没有改变这个全局认证范围：同一 scope 的新 frontier 送到两个独立 artifact owner 后，即使只命中其中一个 cell 的训练来源，两个 owner 上旧 admission 都需要重新验证。测试明确向 semantic 和 procedure 两个 owner 安装了**完全相同的新 frontier**，没有通过不给 sibling 送达通知来证明隔离。[真实测试及恢复编排](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-agentd/src/memory_serving_plan_v11_test_support.rs)。

这条可用恢复路径已在本轮 CI 走通：

1. 同 scope 的 semantic 来源撤销通知送达两个 owner；原 joint plan 与原 procedure-only plan 均拒绝。
2. semantic 的 fresh admission 仍被拒绝，不能借更新 metadata 复活已撤销的训练依赖。
3. procedure 从其**实际 owner 的 `withdrawal_registry()` 与当前 head** 调用 `admit_manifest_at_withdrawal_head_v3`，manifest 保持不变。
4. 使用现有 `ArtifactSelectionVerifierV1` 验证独立 signed CURRENT selection，再调用 `MemoryCellReleaseV11::install_selected`；仍执行 owner、scope、CURRENT、manifest、签名和代际规则检查。
5. 新 selected 对象的 generation、artifact digest、payload digest 与旧参数一致；selected Arc 已更新。持有旧 selected Arc 的旧 plan 以 `superseded selection` 拒绝。
6. 构造新 plan，cell version tuple 保持相同，真实 Procedure 读取成功。

因此，准确能力是：**未受影响 sibling 无需重训，可在新 frontier 下完成 metadata re-admission/install 并重建计划后复用同一参数版本**。它并不保证“所有共享撤销前沿变化都无需重新认证”。这一路径复用现有公开 API；没有新增绕过 V3 权限含义的 bridge，也没有放宽 release core 的验证。[未放宽的 release core](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-agentd/src/memory_cell_release_core.rs)。

## 5. 运行保证的其他边界

`read()` 使用五秒 `tokio::time::timeout`，并在结果返回前检查实际 elapsed time：超过预算时不返回成功结果。但 Tokio timeout 无法抢占同步 JSON decode、签名检查或数值 inference；长同步片段可能占用超过五秒后才到达拒绝点。因此这是带最终返回检查的协作式 deadline，不是严格 CPU 抢占或“所有调用必在五秒内结束”的保证。该说明来自实现，不另行声称已经执行极端耗时压力实验。[deadline 与返回检查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-agentd/src/memory_serving_plan_v11.rs)。

当前 sleep 路径可以释放已解码数值缓存，但一次 plan read 会校验所有选中 cell，并可能唤醒全部 cell；按查询仅唤醒实际消费 cell 的稀疏机制尚未实现。来源与发布验证是按顺序进行的边界检查，本报告不把它描述为跨进程或跨节点原子事务。

Owner-created projection 没有公开字段构造或 `Deserialize` authority 入口，release 会核对声明来源和完整参数 admission。与此同时，来源 hash 与 lineage 不能证明训练过程实际只使用了声明数据，也不能单凭 metadata 证明已完成 machine unlearning。该原生 profile 采用当前来源的 clean-fit 声明，训练生产者仍需遵守真实因果来源记录；从 parent 继承参数的 Python split children 保留 parent 依赖，不能直接冒充独立 clean-fit projection。[投影源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/codex-rs/hepta-memory/src/memory_training_projection_v11.rs)、[结构实验报告](TASK_STRUCTURE_REPORT.md)。

原生 lifecycle、Python learned runtime、结构演化和迁移实验分别有自己的执行路径与证据。当前原生数值执行仍复用已有有界 profile；Python 的 MLP、attention-internal LoRA、其他 learned cell 类型尚未完整接入 native 发布/推理/control-wire 链。解析构造的 lifecycle 参数并非微调模型；本报告也不把已有 App Server 上下文回归通过，解释为新 Python 模型已端到端部署。[内容实验](CONTENT_REPORT.md)、[维护实验](MAINTENANCE_REPORT.md)、[迁移实验](MIGRATION_REPORT.md)。本轮 receipt 明确保留 `production_activation_allowed=false`、`trained_quality_claimed=false`。

## 6. 失败与更正历史

| Run | Source commit | 实际结果 | 后续处理 |
| --- | --- | --- | --- |
| [41057002479](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41057002479) | `7677c8a7424f0f888f53aefb1ea97ce38a1978a2` | Workflow schema 校验失败，0 个 job、没有测试。 | job-level env 不接受 `runner.temp` context；改为使用允许的 `github.run_id` / `github.run_attempt` 构造临时路径。 |
| [41057484405](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41057484405) | `767909f710cc969e82e357e1726231cebf2e2b8c` | E0603 编译失败，没有测试执行。 | sibling V11 模块不能访问 release core 的 `pub(super) now`；改用既有可访问 host clock 与 checked `u64` 转换，没有扩大 core 可见性。 |
| [41059465673](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41059465673) | `a2daab680ee1ec88a0e295ade3204ecb4158a27f` | 517 个实际执行测试中 515 通过、2 失败；另报 24 skipped；V11 为 7/8 通过。没有进入 fix/fmt。 | 补同源 App Server 构建；更正错误的 full-cut 不变断言；补双方共享 frontier 恢复覆盖；修 reporter 的失败路径统计。 |
| [41062425475](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41062425475) | `1bc02cb33a380cf53bb58333b2ee8b3d1a70f175` | 517/517 通过、另报 24 skipped、8/8 V11；fix/fmt 成功且零改树。 | 本报告所采用的实际通过记录。 |

第三轮两个失败的原因需要分开看。原有上下文回归要求真实 `HEPTA_TEST_CODEX_EXECUTABLE`，旧 workflow 未构建/绑定它；修复保留并实际运行该回归。另一个失败来自 V11 测试的错误前提：“没有新增数据库写入，完整 Lane-C cut 就不会变”。未来有效记录进入当前可见集时，即使没有新增写入，完整 cut 也可变化。修订后的测试确认直接查询的 semantic 来源未变、procedure 的新有效版本已出现，并验证返回端以 `training projection changed` 拒绝；不再声称已证明一个原 full-cut 检查无法发现的漏洞。[编译失败更正](evidence/native-ci/41057484405/CORRECTION.json)、[测试失败更正](evidence/native-ci/41059465673/CORRECTION.json)、[workflow 校验错误](evidence/local-native-resource/WORKFLOW_VALIDATION_41057002479.json)。

`41059465673` 原始 receipt 的 `tests_executed=false` 是 reporter 缺陷：失败的测试进程抛错后，旧的仅在成功路径运行的 JUnit 解析没有执行。**原始 receipt 保持不变**；保存的 JUnit 和 nextest 日志证明实际执行了 517 个用例，`CORRECTION.json` 单独记录该字段更正。后续 workflow 在 `finally` 解析 JUnit，并分别保留 JUnit testcase 数和 nextest skipped summary。更正记录中的“尚待下一轮验证”属于当时的历史状态，不回写成成功；本轮成功由新的独立 artifact 证明。[原始失败 receipt](evidence/archives/native-attempts-v11-early/README.md)（包内 `runs/41059465673/artifact/receipt.json`）、[原始失败 JUnit](evidence/archives/native-attempts-v11-early/README.md)（包内 `runs/41059465673/artifact/native-junit.xml`）。

### 本地磁盘预算中断

在 remote CI 之前，本地有三次 scoped Rust 构建被资源预算中断，均通过所属会话 Ctrl-C 正常退出，exit 130，均发生在测试执行之前。它们既不是测试通过，也不是逻辑测试失败。[资源中断记录](evidence/local-native-resource/memory-v11-build-resource-interruption.json)。

| 尝试 | 当时资源状况 | 证据范围 |
| --- | --- | --- |
| 第一次 | 初次构建未设置 debug/incremental 限制；共享磁盘只余约 1 GiB。 | 保留中断 receipt；首次完整 stdout 文件被第二次尝试替换，**不声称该完整日志仍然存在**。 |
| 第二次 | 已设置 debug=0、incremental=0、jobs=2，但共享 root overlay 达到 0 可用空间；本轮 target 约 1.9 GiB。 | 保留 receipt 与 bounded build 中断日志。 |
| 第三次 | 同样的资源限制；剩余空间降至约 1.8 GiB，低于预留 2 GiB。 | 保留 receipt 与第三次 bounded build 中断日志。 |

每次退出后只清理本任务自己的可复现 target，没有删除其他任务目录。最终通过结论来自上述真实 GitHub CI，而非这些本地中断尝试。

## 7. 后续 publication head 的原生输入绑定

Native workflow 的 push path filter 覆盖 `codex-rs/**`、本 workflow、setup-ci、脚本、工具、patches、Bazel、Cargo/工具链和根构建配置等输入。`qualification/memory-cell-v11/` 的 research/report/evidence-only 提交不再次触发 native CI。结果始终属于受测 commit；后续 publication head 只有在原生/build inputs 与它零差异时，才可继承**该限定范围**的验证结果。[受测 workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bc02cb33a380cf53bb58333b2ee8b3d1a70f175/.github/workflows/memory-cell-v11-native.yml)、[输入身份清单](evidence/native-ci/41062425475/NATIVE_BUILD_INPUTS.json)。

最终 publication 绑定由发布者另行执行，并在 PR 保留精确结果；本报告撰写时不预填一个尚未核验的最终 head。使用仓库统一校验工具，在仓库根目录运行：

```bash
python qualification/memory-cell-v11/evidence/verify_native_inputs.py --revision HEAD
```

发布完成后，应将 `HEAD` 换成最终发布的完整 commit SHA 再运行，并把确切 commit、tree、输入 digest 和限定 scope 的相等结论记录在 PR 中。该工具与输入清单属于证据发布内容；本次原生 CI 没有执行尚后续加入的验证工具。[输入复核工具](evidence/verify_native_inputs.py)。

比较应以受测 workflow 定义的同一 scope 重新枚举受测提交与最终提交的全部 Git 对象，包含 path、Git mode、object type 和 object ID，检查范围内新增、删除、重命名及内容变更，并核对受测 workflow SHA 与保存的 8,080 条清单。不能仅比较已有几个 Rust 文件，或以改写过滤范围获得相等结果。成功输出只建立限定输入范围的一致性；它不替代新的测试，也不证明未运行的 Python 实验或整个新 head 均已通过 CI。若范围内输入改变，应为新源码重新运行原生验证。
