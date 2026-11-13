# 共同候选：精确源码的本地 native 门已通过，完整 P0 与科学收益仍待建立

本轮已形成包含 M6、干细胞路线、representation、ordinary consumer、学习 scope 和原 Root 启动链的共同候选。**精确 f070 源码的四项本地 native 门均已通过：helper 构建、八库 1486 项测试、Matrix SDK 30 项测试、agentd binaries 检查。** 70 + 2 个跳过项单独记录。完整“普通任务→学习/NoUpdate→不同普通任务→恢复”链仍未建立，真实模型与 actual Root 组件也已单独执行；它们保留各自的研究/fixture边界。 四臂完整开发对照已经实际执行，结果平局，未建立学习收益。

本报告按实际执行源码、后续代码维护和证据提交分别记录结果。机读状态见 [CURRENT.json](CURRENT.json)，固定范围与材料边界见 [INPUTS.json](INPUTS.json)。报告及后续证据提交可以晚于被测源码，以下 commit/tree 始终指实际运行时输入。

## 1. 固定的共同候选

| 项目 | 精确身份 |
| --- | --- |
| 已验运行时 commit | `f070113bb61cda492d2668b3afbbcda13e11fa52` |
| 已验运行时 tree | `068b6a7749e94d7335c826d6c43c19198e02cc24` |
| 后续代码维护 commit/tree | `dde0c36ef2b90af37f5cdafe7dca0c7572585b09` / `19e7619d7b4df0f1ba645151ffb5844a53ad97d3` |
| 工作分支 | `engineering/cell-common-20261109-e1c98` |
| 当前 native 状态 | f070 上四项配置门均 exit 0：八库1486 PASS / 70 skip、Matrix30 PASS / 2 skip，helper 与 binaries 检查通过；975 durable job succeeded |

f070 是 native、真实模型和实际 Root 测试共同绑定的源码。随后 dde 仅完成已发现的 lint 修复与格式化：22 个文件（16 Rust、6 Python；Python AST 不变），`just fix`、`just fmt` 和七 crate strict Clippy 均 exit 0；维护后未重跑测试。[维护证据](maintenance/README.md)及[逐文件绑定](maintenance/APPLICATION.json)保存确切 patch 与源码哈希。后续证据提交与维护代码不能继承成“新 tree 已跑过 f070 测试”。

五个固定上游输入如下。本轮停止追逐后续移动 head，Root 的后续纯证据提交未作为新的运行时输入合入。

| 输入 | 固定 commit |
| --- | --- |
| M6 | `885dae0f3285267e9e9c49d8b43b0d009779f9e8` |
| 干细胞路线 | `4cc753af511bf7c406608caa9da0795d7691bd23` |
| representation 与 ordinary consumer | `5530f84e1305c4c86b8be19c4c8765c4340e51db` |
| 维护后的 scoped learning | `342fb02346fb1a2f97d684fb1a3ef9042737401b` |
| 原 Root learning bootstrap | `b443fe0cd7642316d016d78d6d3fbaa3e9dfc341` |

候选范围仍是固定图和每次请求中明确声明的一个学习对象；没有开放共享基础模型更新、组织搜索或改进器继承。普通产品运行所需的 CURRENT、被授权 source frontier、原 Root writer 和真实 stage-owner 材料在输入清单中明确为缺失。实际研究模型另有冻结模型、CURRENT、数据和配置，其资格边界在第 6 节单独记录；不能用该研究身份代替产品 owner 材料。

## 2. 已补上的运行机制

| 修复 | 现在的行为 |
| --- | --- |
| readback 与 delivery 的冻结边界 | 普通 delivery 登记前检查原请求/owner binding；恢复后重新检查每一个 Training observation。最终 NoUpdate 不会使此前越界的 candidate 合法。 |
| registered checkpoint 与 Root transport 的 V2 | stage adapter 保留冻结 binding；显式 schema 2、`runtime.learning.checkpoint.v2` 和原 scope digest 一致。V1/V2、Cell/Organ、请求或规则替换均拒绝。 |
| 原 Root 普通启动 | 固定 Root stack 提供原 writer 注册、open-only 恢复、独立 sealed FD、同一个 Root pidfd、retained listener 与 ordinary startup 消费。 |
| Root scope 全链保存 | `new_scoped_v2` 明确冻结 Cell/Organ、update rule 和 binding；schema-2 protected CAS、`runtime.learning.bootstrap.v2`、原 Root client 与 scoped runtime 连续绑定。缺 scope、错误 schema/operation 或变更 binding 均失败，不迁移旧记录来使其匹配。 |
| 编译与兼容修复 | 84b native 编译发现 gated-store 测试漏填 `scope`；`f1548649c9` 补为明确 legacy `None`，并保持 legacy registration JSON 不多输出空 binding。`47959b409c` 消除新增测试的 5 个 join unwrap。随后 47959b native 暴露结果 JSON 宏递归上限，`ca584b236a` 将两个字段移到宏后插入，未扩大递归限制。8857 native 又发现 Root synthetic fixture 漏填 evaluation profile，`f070113bb6` 使用同一共享 fixture 明确冻结的 digest 补齐，并核查全部七个请求 literal。 |

原 writer、lease、pidfd、revocation、同服务生命周期及独立 actor 验证均保留。收到 checkpoint capability 仍不等于拥有实际 stage owners；未组装这些 owner 时普通启动继续拒绝。实现边界见 [Scoped V2 说明](../../codex-rs/hepta-agentd/SCOPED_LEARNING_V2.md)。

**claim 后而 backend checkpoint 尚未出现的窗口没有被改成自动重放。** 对已经 claim 的操作只允许原 owner readback；缺失或部分 checkpoint 不能证明没有执行过。仅把 prepare 移到 claim 前会移动不确定窗口。安全恢复还需要原 owner 的 durable admission、execution generation/fence 与阶段效果 reconciliation，或可验证的 not-started 证明。

## 3. 已执行的验证及其边界

| 验证 | 绑定源码与结果 | 解释范围 |
| --- | --- | --- |
| 全仓 source caller closure | A9 `a9c05cf352dac5a96f8f72248c25f34f80f7a5b3` / tree `136e9e44969734521270857708a9de211c7eae03`；6166 Rust files、181 boundaries、164 protected files；PASS，`authorityGranted=false` | 源码 caller 闭集与保护标记；不证明 Rust 编译、native 行为、实际模型或授权。 |
| targeted source-guard mutation tests | f154 上 Root bootstrap 10 项、checkpoint 6 项，均 PASS | 源码守卫拒绝回归。 |
| 较早 84b native 编译 | `84b2a97c2ab3d727e27a2f5d3bc72ecfd56ae36d` / tree `eb01896296d28bfa86f6d30236e5b0d08f2942fd`；观察到 E0063 | 已有针对修复；不能把“已修改”当成新源重编通过。 |
| 47959b native 编译 | `47959b409c` / tree `f0788360`，ai395 source-fresh；helper build 成功，测试编译在 `neuron_generation_real_learning_tests.rs:1209` 的 json! macro recursion 失败 | 测试没有执行；不能计通过或算法失败。 |
| 8857 native | `8857d0f0b149a1aec7546c71803453c93a4aabb5` / tree `965c462e0b31f04d54d0905c43456eacbd74186b`；helper 通过，Matrix 30 PASS / 2 skip；八库编译失败，binary 命令在编译前失败 | [全部原件与分项解释](native-validation/README.md)；Matrix component 结果不转移到失败或尚未执行的门。 |
| 修复后共同候选 native | f070113bb6 / tree 068b6a77；四项门均 exit 0，八库1486 PASS / 70 skip，Matrix30 PASS / 2 skip；helper 与 agentd binaries 检查通过 | [同源全部原件](native-validation/README.md)。A/B六项scope回归、Root两项schema/binding回归和两个owner-drop回归均已从JUnit核对。它不是全workspace或全平台CI结论。 |
| 综合 Python 控制 | `8c1cf773d2e96c7f98ac3e09b544c5dbedb11a7e` / tree `93eda171c94d6d6cc738cffb70acb26137206461`；128 项 PASS，测试 7.529 秒 | runtime/qa/scripts 前后未改；[执行记录](python-validation/RESULT.json)。不是 Rust native、真实模型或科学样本。 |
| 实际 Root CAS / sealed FD / scope 冷恢复 | f070 同源 archive，真实euid=0，两个原ignored用例均PASS，Nextest0.042秒；archive另852项与7个binary被过滤 | [完整Root原件](actual-root-handoff/README.md)。原检查和私有`/var/lib`目录，scope用例覆盖Cell/Organ；同一Root测试进程、synthetic metadata，不证明独立owner或daemon OS restart。 |
| 不同实际输入的真实模型研究运行 | f070 同源 archive；一个选定测试 PASS，45.388 秒；另 1555 项被过滤。source 与 next 各一次真实 forward，训练 10 optimizer steps，评价后 NoUpdate，冷恢复保留原结果 | [完整模型证据](actual-model-no-update/README.md)。source 答错、next 答对；candidate 1/4 低于 parent 3/4。真实训练和恢复已发生，普通 P0、独立评价、学习收益仍未建立。 |
| 测试后维护 | dde `19e7619d` tree；`just fix`、`just fmt`、七 crate strict Clippy 均 exit 0 | [维护证据](maintenance/README.md)。22 个文件、Python AST 不变；维护后未重跑测试，不能把 f070 的 JUnit 改署为 dde。 |

全仓扫描的原始 stdout 和空 stderr 已逐字保存于 [source-closure](source-closure/MANIFEST.json)。[receipt.json](source-closure/receipt.json) 为 84,384 bytes，SHA-256：

`23830ab35f24ceef5a1bb2bf5895a125b80a20b0ba80b302a0f04e704b97151f`

该扫描在合成工作树执行，结束后核对 `git diff a9c05cf352 -- CALLERS.toml codex-rs` 为空；它绑定 A9 的 manifest/Rust 源码，不声称当时整个目录是干净 checkout，也不是后续共同候选的 native 运行凭据。

## 4. 原 M6 CI：部分已通过，整体没有通过

原 M6 的 source/tree 是 `885dae0f3285267e9e9c49d8b43b0d009779f9e8` / `293ece7ffdffa2332ccfdec4fbbc4b7dcb3363cb`。以下均为原 CI 或其一次定点重试的观察，不能转移为共同候选资格。完整分类、14 份原始日志和四次 Matrix 诊断原件见 [CI 取证](ci-forensics/README.md)、[SHA 清单](ci-forensics/MANIFEST.json)。

| 门 | 已保留的事实 |
| --- | --- |
| [Cell native attempt 2](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42565757710) | 已结束，failure。composition job 的 scoped suite 为 7879 passed / 104 skipped；全 workspace 为 20498 passed / 1 failed / 134 skipped。失败项是 Matrix encrypted restart 的 `Initialization`。另外两个 Cell mechanism/recovery job 成功。 |
| [原 Architecture job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42565769715/job/128991823205) | 获取 V8 时 urllib HTTP 504；architecture native 测试尚未执行。这不能解释为架构理论失败。 |
| Architecture 一次定点重试 | source-head job `129124162512` 与 `Architecture required` job `129139973803` 最终 success；base-merge job `129124164629` success，但其 native 按原配置跳过。原 M6 Architecture 门已由这一次重试完成，不能转移为共同候选通过；原整体 CI 与 Cell workspace 仍未通过。 |
| [整体 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42565769736) | run 结论是 cancelled；`CI required` 失败，reported needs 为 bazel=failure、repo-checks=cancelled。 |

失败已按原因分开处理：DotSlash、hermetic dependency、bazel-lib 的 HTTP 504 是获取环境问题；GNU job 在获取失败后的通用 lock 提示不足以证明真实 lock drift。MUSL `StateLocked`、macOS 非 canonical TempDir fixture、Matrix 初始化失败则是具体的源码/fixture/runtime 问题。其他 Windows sandbox、app-server/core/TUI 等失败没有在本轮冒称修完。

窄修复包括：prompt owner-drop 显式解锁及 retained-descriptor 回归（`2cd2c890ca`）；六处 automation fixture 路径 canonicalization，保留生产检查（`cfae11bba5`）；V8 对 HTTP 502/503/504 最多三次 GET、1/2 秒退避（`d301b2a387`）。V8 的 15 项 Python 测试已通过；SHA-256、其他错误、导出检查没有放宽。前两项回归已在 f070 的八库同源 suite 中通过。Matrix 的同 CPU 配额 A/B 已支持“本地加密构建成本耗尽原 deadline”的解释：仅优化 store-encryption 开发编译后，诊断运行通过；这仍是 84b 基底上的诊断 overlay，不是最终共同源资格。生产超时、加密参数和测试断言没有放宽，正式 `8857d0f0b1` 随后实际运行 Matrix SDK 全 suite，30 项通过 / 2 项跳过，原 encrypted restart 为 4.906 秒；这次同源组件结果已保存于 [native 证据](native-validation/README.md)。后续 f070 的 Matrix suite 仍为30 PASS / 2 skip，八库、helper及binary检查也全部通过；[native原件](native-validation/README.md) 保留新旧尝试的不同终局。

### 共同候选 f070 的新远端 CI

这里的 f070 指 PR #5509 的 head。build-test 和两个 Windows Bazel job 实际 checkout 为 GitHub synthetic merge `9498ada2adfa88f5562d9e91acab3dad480fcb3d`（把 f070 合入 M6）；原 commit 对象确认其 tree 与 f070 的 `068b6a77…` 完全相同。Windows private job 则明确 checkout f070。完整源码身份、四份原日志、无法取得的日志说明和观察快照见 [后续 CI 证据](ci-observation-f070-20261109/README.md)。该追加记录保存于 2026-11-09 12:59:43 UTC；未因追加取证重跑任何测试或 CI。

| 门 | 保留结果与原因 | 已有维护覆盖及剩余状态 |
| --- | --- | --- |
| [Cell run 42615233826](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615233826) | mechanisms `129153342070`：`clippy::type_complexity`；composition `129153342282`：`clippy::duplicate_mod`。均在相关 native suite 执行前失败；actor recovery `129153342283` 成功。 | dde 中 type alias 和单一 private test-support module 修复已通过本地七 crate strict Clippy。[原日志与维护](maintenance/README.md)保留；不改写 f070 的原失败。 |
| blocking build-test `129159652068`；独立 Windows private `129153808326` | formatting 失败；Windows private 尚未运行该 workflow 的 Windows native suite。 | 两份日志同一组 72 个 Rust hunks、11 个文件，逐字匹配 f070 前像与 dde 后像；6 个 Python 格式路径也被维护覆盖。这是 [静态差异核验](ci-observation-f070-20261109/FORMATTING_HUNK_REVIEW.json)，不是远端重跑通过。 |
| blocking cargo-deny `129159652206` | `Run cargo-deny` 明确失败，原因尚未观察。 | 原日志正文未取得；取证接口失败和有界 GET 超时不能推断 CI 失败是由网络、依赖策略或 V8 导致。 |
| Windows Bazel shard 3/4 `129159652631` | 实际 native tests 已运行，hepta-agentd、hepta-neuron、tui 三个 target 失败；Windows 锁 code 33、Circuit fixture Invalid/PermissionDenied、perception fixture 多出 CR 字节、TUI 路径前缀断言。 | 27 个不同失败 case 中，25 个已在原 M6 同 shard 失败；另两个新 credit case 在未修改的服务 fixture 构造处遇到同样 code 33。没有据此建立新 runtime 回归，也没有宣称这些 Windows 问题已修完。 |
| Windows Bazel shard 1/4 `129159652726` | exec-server target 失败：legacy sandbox 因 ambient parent `FILE_DELETE_CHILD` 拒绝删除边界；原 M6 已出现同样错误。 | core resume-context cleanup 另有超时，Bazel 最终记为 FLAKY，不能额外计成失败 target。不是 V8 获取失败。 |
| [Architecture run 42615372442](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372442) | source-head `129153810392` 在保留快照中仍处于 compiled service lifecycle / actual process restart；base-merge `129153810121` 已 success。 | 完整 gate 终局尚未建立。 |

[blocking run 42615372714](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372714) 因已有失败而不是全绿，不能统称为仍在等待；独立 [Windows private run 42615372441](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42615372441) 也为 failure。Windows 的 Bazel target、执行/缓存与 skipped 计数在原件中分开保存，不能与 Linux Rust testcase 数相加。本地 native 通过、后续 lint/格式化通过和远端 CI 终局分别成立；本报告没有共同候选远端 CI 全绿结论。

## 5. 完整四臂开发对照已经运行：平局

详见 [完整开发比较](development-comparison/README.zh-CN.md)、[机读结果](development-comparison/CURRENT.json) 和 [原始封包清单](development-comparison/MANIFEST.json)。

| 臂 | 真实消费状态 | 所选文档 | 历史 S 的 native 终局 |
| --- | --- | --- | --- |
| no_update | 原父状态 | native-clippy-borrow | 33 passed / 0 skipped，proved |
| bm25 | 同语料 exact + BM25 | native-clippy-borrow | 33 passed / 0 skipped，proved |
| fixed_expert | 事前固定文档，未声称调优充分 | native-clippy-borrow | 33 passed / 0 skipped，proved |
| candidate | M6 的真实候选私有状态 | native-clippy-borrow | 33 passed / 0 skipped，proved |

四个臂各在独立 Git clone 中执行完整修复/验证流程。候选确实读取了候选状态，但排名、所选文档和终局均未改变；这项四臂比较新增训练为 0。第 6 节的真实模型运行另有一次训练、10 个 optimizer steps，最终 NoUpdate。这里是一项已曝光历史任务的四次策略运行，独立确认任务为 **0**，不能把 132 个断言当作独立科学样本。

Python 驱动只物化 84b 提交的 8 个精确文件；实际 native 任务源是历史 S `693a013b254d07779f6f2b2a78d0ee31481f4ea9` / tree `f06389aa4f5caf0af5fec419da6473e198796b24`，不是最终共同候选。rog job `1a1c000e937-5e21-85c` 实际 succeeded / exit 0。

比较函数 wall 为 52.627891 秒、回收子进程 CPU 为 88.077974 秒。固定顺序为 no_update→bm25→fixed_expert→candidate，第一臂冷 target 编译、后续复用缓存；各臂约 40.60/4.05/3.76/4.14 秒不能解释为学习加速。峰值内存、能耗和金额仍未知，完整端到端成本未建立。原始封包 107,032 bytes，180 个 manifest 成员已核对；完整 SHA 与成本窗口见上述结果。

## 6. 真实模型与完整 P0 的边界

此前 SmolLM research runner 的 source/next request 都使用 `next_prompt`，只改 task/run ID；它不能证明内容不同的两个任务。`7155006473` 同时修改 Rust 请求、Python probe 和冻结 task→prompt 映射；新 `distinct-source-next-v2` 配置明确要求前后输入实际不同。本轮唯一实际模型运行已绑定这个新 profile；旧 `shared-next-prompt-v1` 仍可用于其原研究配置，但不取得“不同输入”资格。旧历史结果没有被追认为满足新合同。

### f070 上实际发生了什么

实际模型使用与 native 门相同的 f070 源码和冻结 nextest archive；job `1a1c0435e71-5e21-994` 已 succeeded / exit 0，没有重试或超时。准备 001 曾因缺少预先创建的 extract 目录而停止，模型没有启动；外部准备器补齐目录后，新准备 002 成功，随后只执行了一次实际模型回归。[完整原件与材料清单](actual-model-no-update/README.md)保留这两个准备过程和唯一执行的区别。

这次研究运行的输入也已冻结，原件见 [INPUT_BINDINGS.json](actual-model-no-update/INPUT_BINDINGS.json)：

| 输入 | 实际绑定 |
| --- | --- |
| 基础模型 | `HuggingFaceTB/SmolLM2-135M-Instruct`，revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`；base 文件 SHA-256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`。 |
| 数据 | 已曝光的 4 行训练数据、每个版本 4 个评价题；source prompt 来自曝光训练行。训练输入 SHA-256 `37941edc1981a90fa95039fdbb9e01fff0017708c0bd88f21dc4d432f5e06c21`，没有独立隐藏确认集。 |
| 配置 | `distinct-source-next-v2`；config SHA-256 `5538ff90dd712a270a59635f3e97b0fa155d5f9c46fc98a1ca7e736c238b4080`；frozen plan SHA-256 `be8cae248750cc7e1fcab83e371d09c154354b0c87bfaf24144a88acf3d0f5e0`。 |
| 状态协议 | Cell scoped V2、原 `HEPLCP02` checkpoint codec、明确 scope/update-rule binding；NoUpdate 保留 generation 1 的原 selected adapter。详细初始/完成 learning head、CURRENT 与 artifact pins 保存在输入清单。 |

此运行的 `prediction_mode=conditional_binary`：真实模型 forward 后比较固定 yes/no 候选的条件 logits，并保留所选标签；以下“回答”不表示已验证自由文本生成。前后仍是同一已曝光算术任务族中的不同输入，不建立跨任务族迁移。

| 阶段 | 已观察结果 |
| --- | --- |
| 真实源任务 | 输入比较 `135 > 134`；一次实际 forward，回答 `no`，**答案错误**。该输出仍是确实产生并保留的任务结果，不能写成源任务成功答对。 |
| 局部训练与评价 | journal 记录一次 train，实际 training receipt 记录 10 optimizer steps；对同一组 4 个研究题，parent 正确 3/4、candidate 正确 1/4，共 8 次评价 forward。没有独立隐藏科学任务。 |
| 原选择与后继 | 协议选择 **NoUpdate**，保留父版本；另一个内容不同的任务 `8517 > 8516` 通过一次实际 forward 回答 `yes`，答案正确。输入 profile 为 `distinct-source-next-v2`，前后输入 SHA 不同。 |
| 恢复与只读确认 | 重新打开 Learning/Generation owner、重建 native fleet 生命周期并重启模型 worker 后，仍读回 `yes` 和同一个 retained artifact；worker forward 计数为 1→1，增量 0。没有 agentd daemon 的 OS 级重启。 |

保留的 selected/retained artifact SHA-256 相同：`a946c2cd7073092e607fb5ee3fd9b2dc78053ba5dc3d357a0a27c273ebbf95e2`。原 native result SHA-256 为 `a93e720cceb5ee0a90d33c458627c7e7eb69b880262f4647caaf6c674e0e8a6b`。完整 journal 只有一次 train，实际 training receipt 记录 10 steps；没有独立的 training-invocations 前后计数器，不能把这一点写成额外计数器已经证明。冷恢复的 forward 计数和原 readback 则直接支持本次没有重复 forward 的结论。

[成本记录](actual-model-no-update/COSTS.json)中，唯一模型执行的外层命令 wall 为 46.179697 秒、回收子进程 CPU 为 53.625113 秒、child peak RSS 为 3,018,300 KiB。Nextest 的 45.388 秒和各训练阶段都包含在该外层窗口内，不能再相加。两次准备分别为 10.683565 秒（失败）和 11.121716 秒（成功），另行保存。历史基座训练、下载、缓存准备、全部操作/传输开销、同时全进程树峰值、能耗和金额未全部建立；本轮没有成本收益结论。

### 实际训练范围与基座冻结

实际训练是 **60 个 q/v 模块、120 个 LoRA A/B tensors、rank 4，共 230,400 个可训练参数**。固定的 inherited runtime child 对 candidate 执行 `insert_lora` 后训练；`requires_grad` 只选择 LoRA，AdamW 只接收可训练参数。训练后内存 backbone descriptor root 必须等于原 `index_root`，并且执行前后的 67 个已观察源码/模型/配置材料 pin 不变。这些检查支持本次基座保持不变；磁盘 pin 本身不能代替内存 backbone 检查。

配置中两个 `allowed_patch_targets` 属于另一条 `training=false` 的 direct weight-edit worker 接口，其 export 要求 gradient/optimizer steps 为 0。它们不是本次 LoRA trainer 的“两 tensor 训练 mask”。NativeCellV2 检查组件和 update-rule 摘要，没有 tensor mask；因此既不能据此认定本次越权修改了两个目标之外的 tensor，也不能声称已经证明“两 tensor 学习”或 parameter-V3 资格。`RetainedOnly.external_owner=None`，原 parameter-V3 qualification 仍未建立。精确区分和四份原实现快照见 [scope review](actual-model-no-update/SCOPE_REVIEW.json)。

该 runner 仍处于明确研究 custody。它实现 Generation V2；普通 Circuit 使用 Feature V1 的原 inference receipt/readback，不能直接交换接口。ResearchTrust 的四把角色 key 仍由同一 operator 控制，不能因 controller 标签不同就变成真实独立评价。普通协议的 Evaluation、Selection、NextUse actor separation 保持原样。

### 普通 P0 的代码交接表

普通产品路径尚未完成组装。`main.rs` 收到 Root learning inputs 后继续调用 `launch.run`，而该函数及 `run_with_shutdown` 会调用 `require_root_learning_assembled` 拒绝未组装的 stage owners；补充证书文件不会自动产生缺失的实现。下表对应仓内实际符号，已有产品实现与测试 fixture 分开列出。

| 环节和已有产品代码 | 当前接入事实 | 仍需完成的产品代码 |
| --- | --- | --- |
| [state_circuit_task.rs](../../codex-rs/hepta-agentd/src/state_circuit_task.rs)：`AgentdCircuitTaskInvocationProviderV1::{build,publish_result}`、`execute_circuit_task_record`；[config_circuit_task.rs](../../codex-rs/hepta-agentd/src/config_circuit_task.rs)：`with_circuit_task_bootstrap` | 唯一具体 invocation provider 是 [ingress_tests 的 Invocation](../../codex-rs/hepta-agentd/src/circuit_task_ingress_tests.rs)；配置入口没有产品 caller | 实现真实普通任务→稳定request映射、原结果幂等持久化，并在正常启动安装原owner/bootstrap。 |
| [circuit_task.rs](../../codex-rs/hepta-agentd/src/circuit_task.rs)：`CircuitTaskInputProviderV1::resolve`；[circuit_task_runtime.rs](../../codex-rs/hepta-agentd/src/circuit_task_runtime.rs)：`circuit_task_channel_v1` | 具体Inputs在测试文件；生产representation encoder已存在，但普通channel仍要求真实Feature V1 control+readback。研究`ProcessControl`是另一Generation V2接口；[fixture Model/Encoder](../../codex-rs/hepta-agentd/src/circuit_cell_test_support.rs)给固定Q24输出 | 保留真实task/source/clock/masks，恢复读取原输入；组装实际模型的Feature V1执行与durable readback。不能把固定fixture输出当真实推理或直接替换接口。 |
| [learning_iteration_ports.rs](../../codex-rs/hepta-agentd/src/learning_iteration_ports.rs)：`LearningIterationStageOwnerPortsV1`；[checkpoint_ports](../../codex-rs/hepta-agentd/src/learning_iteration_checkpoint_ports.rs)：`CheckpointedIterationPorts` | checkpoint adapter是产品代码；唯一具体StageOwnerPorts是 [测试 StageOwners](../../codex-rs/hepta-agentd/src/learning_iteration_checkpoint_ports_tests.rs)。真实模型`ResearchPorts`位于cfg(test)，实现另一full-port trait | 实现原experience/dataset/trainer/evaluator/proposal/selector/observer的实际执行、attestation与read-only恢复，接入Root checkpoint和固定trust；不是新建测试签名器。 |
| [neuron_generation_update.rs](../../codex-rs/hepta-agentd/src/neuron_generation_update.rs)：`prepare_agentd_generation_same_model_task_v1`、`publish`；[update_learning](../../codex-rs/hepta-agentd/src/neuron_generation_update_learning.rs)：`read_learning_selection/next_use` | 非test的原CURRENT publication/readback API已经存在；把它们用于本轮真实模型的组装仍是research tests | 补产品caller，把实际decision/签名selection绑定原CURRENT，提交内容不同的普通后继任务，返回原committed NextUse；公开API本身没有完成普通入口组装。 |
| [main.rs](../../codex-rs/hepta-agentd/src/main.rs)、[production_launcher.rs](../../codex-rs/hepta-agentd/src/production_launcher.rs)、[config_root_learning.rs](../../codex-rs/hepta-agentd/src/config_root_learning.rs) | `with_root_learning_stage_owners`只有定义，没有产品caller；当前收到capability但缺owners时实际拒绝启动 | 在`launch.run`之前增加明确的原host composition/factory，同时供给Circuit bootstrap、真实stage owners、verifier和已要求的governed plasticity owner。保留拒绝分支。 |

[CURRENT.json](CURRENT.json) 的 `full_P0.code_handoff` 保存精确文件、symbol、existing/test-only分类与每项缺失工作。现有 [objective_learning_outbox.rs](../../codex-rs/hepta-agentd/src/objective_learning_outbox.rs) 和 [circuit_learning_delivery.rs](../../codex-rs/hepta-agentd/src/circuit_learning_delivery.rs) 已实现正常outbox补建、delivery与只读reconciliation，不需要另建一条平行研究闭环。

### 代码之外的真实 owner 材料

除上表的实际组装代码外，还需要原 Root writer/capability 及有效生命周期、普通 AuthBus trust/replay checkpoint/objective profile、被授权 source frontier、固定产品模型和 selected CURRENT，以及真实 generator/evaluator/selector/observer 的 signer/readback 和 controller 映射。已观察的模型研究配置没有提供这些产品材料；没有通过创建 fixture 私钥来补齐。实际 Root 的两个通过用例也使用新建 fixture store 和 synthetic metadata，不能替代部署中的原 writer 或真实独立 owner。

存在合法的后续时序：先让普通源任务真实完成，再由原 owner 绑定事后真实 `completed_task_receipt`、冻结并注册 exact learning profile；恢复启动时从原 Objective journal 与 AutomationStore 已 commit trace 补出 outbox。现有 reconcile 路径支持这一顺序，不必预测未来结果 hash，也不必重跑源任务。但这一能力尚未与上述真实 owner 和模型材料形成一次完整执行证据。

因此目前可以分别报告组件机制、原 Root 传递、开发终局比较，以及已经完成的真实模型研究运行；**不能报告“普通任务→学习/NoUpdate→不同普通任务消费→进程恢复”的完整 P0 已通过**。协议 NoUpdate 仍要求真实训练、评价、选择和 NextUse，不能改成零步骤、固定签名或一个“无更新”布尔值。

## 7. P1–P4 的科学状态

详细历史来源、计数和对照义务见 [P1–P4 review](development-comparison/P1_P4_REVIEW.json)。本轮没有重跑已曝光确认数据，没有调整验收门槛。

| 阶段 | 当前结论与继续要求 |
| --- | --- |
| P1 有用学习 | **HOLD**。PRED 后续确认 16 seeds、114 fits，净增量 `+0.01093896 < 0.02`，单侧 `p=0.08126831 > 0.05`。新四臂开发结果平局；真实模型训练后 candidate 1/4 对 parent 3/4，NoUpdate；两者的独立确认任务均为 0。还需隐藏任务、预注册收益/错误/保持率界限、充分基线和完整成本。 |
| P2 机制归因 | **HOLD**。分别做单体/固定专家/分化、fixed/greedy/MPC/充分训练 router/NDU、GRU/CfC/SSM/attention/HCSN 比较；匹配数据暴露、训练充分性、搜索、推理成本和资源包络。现有延迟 cue fixtures 的 GRU、SSM 和规则均满分，不产生科学赢家。 |
| P3 组织优势 | **HOLD**。[ORG 原结果](../cell-organization-20261108/RESULTS.json) 中 split/merge/rewire 的固定与动态臂每项均 33/33，training steps=0。迁移/AdamW 状态连续性不等于组织搜索收益。组织搜索、迁移、drain、冷启动、缓存、重训、故障和回滚成本仍需计入。 |
| P4 改进器变强 | **HOLD**。[EVOLVE 原结果](../evolve-1-20261108/CURRENT.json) 为 3 lineage、12 runs、72 attempts，qualified=0、unresolved=12。它不是十二次已证明的算法失败，也不是十二次成功进化。还需旧/新/冻结/同历史不继承更新对照及多代后继优势。 |

生产 adoption、独立确认、组织进化和改进器进化均未建立相应资格。工程机制验证与科学收益分别记账。
