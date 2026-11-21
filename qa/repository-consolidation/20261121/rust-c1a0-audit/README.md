# Rust 分支整合审计：2026-11-21

本记录推进 `TrillionniumFoundation/hepta-private-ci` 的普通 Rust 分支整合。目标仍是普通分支最终只保留 `main`；用户排除的新 HIA 分支及已识别的历史别名保持保护。本记录不是全仓库源代码已经逐行审完、全部 CI 通过或可以批量删除分支的证明。

## 本次追加的五组普通历史

在 `87b141833f2a43e0e87fdb3d4a168e1dacde7a0f` 后，本批准备五个顺序双亲合并，最后一个远端合并对象为 `4fe76f0a3dd3dd4bbff68bbf8d11584573c1feb9`，再以一个仅 QA 的子提交承载证据。各组均实际计算默认合并并复核冲突，组合时核对实际第一亲、三方对象和完整冲突内容，完整 59,426 个叶条目保持不变。后续发布 ref 的确切 head 以 PR 的新鲜读回为准。

| 原历史 tip | 新纳入原祖先 | 对应普通 ref 数 | 实际冲突文件 / 块 |
| --- | ---: | ---: | ---: |
| `1bc77df729081280a17284be3ff52f612f0bbd94` | 1 | 4 | 0 / 0 |
| `047468e6edd6d7166ed639123d701a26a2568cfd` | 7 | 1 | 13 / 36 |
| `438a2de93f5fd3bc06f61a0575422dbc4915019d` | 24 | 1 | 16 / 49 |
| `a5a5958c3797d281a96fc613827c28404bd404a5` | 41 | 1 | 38 / 74 |
| `c6e58e1cf5cbd26f660b2f852884ba2b76dffc7a` | 46 | 1 | 48 / 106 |

合计新纳入 **119 个原历史提交、8 个普通 refs**，另有五个实际合并对象。已审解决保留当前严格 Clippy、依赖审计规则、后续运行时约束与原测试，明确消除旧历史重复重放；源码和门禁字节不变。每组原路径、mode/OID、实际冲突与解决记录已核对；这不等于二十四、四十一和四十六个中间补丁均已逐行审完。完整证据见 [五组历史证据索引](history-batch/INDEX.md)。

最新固定快照采集于 **2026-11-21 10:00:15–10:00:21（America/New_York，UTC−5）**：**7,831 refs、79,118 个当前远端可达提交**；unknown tips 和缺失 parents 均为零。已知保护为 **540 refs / 1,472 个节点**，其中 414 个名称不含 `hia`，新发现的 HIA tip `c03eb6e20a8a2554306244d91b780c083cfd81e1` 已加入保护。五组合并候选的 45,038 个祖先与当前已知 HIA/STOP 集合交集为空。原第 551 个历史保护 pin 仍未恢复。

这次快照共有 **7,290 个非 main 普通 refs**；五组合并候选包含 **2,866 个**，仍缺 **4,424 个 refs / 4,207 个不同 tips**。当前 `main` 仍为 `732e934ba496d90fbe042b8d41d479ef901643e5`，其包含的可退役普通 tips 为零。本批没有移动 `main`、integration 或 HIA，也未删除任何分支。快照无法冻结随后新增或漂移的 refs，发布仍使用新鲜 expected SHA。

原 head `87b141…` 在 **2026-11-21 09:59:52（America/New_York，UTC−5）** 开始采集的 103 项 CI 快照为：**68 success、7 failure、17 skipped、1 cancelled、10 in progress**。GNU、musl、两种 macOS 的 Bazel 测试、原 Codespell、Blob size policy，以及 learning.operator 的确定性合并任务均已通过；这次 musl 成功与此前 500 毫秒失败分别保留。Windows 三个分片和 AppContainer 仍失败。

learning.operator 原分支任务的编译、原测试、严格 Clippy 和格式步骤通过，随后原 **85% 行覆盖率门槛**失败。覆盖测量中的 32 + 5 项断言通过，报告写出后命令 exit 1；日志没有实际覆盖百分比，上传步骤也因前序失败被跳过，不能编造数值或继承后续门禁通过。其 mutants、performance、map 和 receipt 步骤尚未执行。原日志与 103 项快照保存在上述证据索引中，**不升级为新 head 的 CI 资格**。

下面继续保留初次源码修复、执行输入、原失败、工具恢复和前两次 QA 修订的完整记录；其中较早快照与旧 head 结果保持其原时间绑定。

最终已准备源码对象为 `77aae54a30eb37ef7930d01224e5ef312a5014a1`，唯一 parent 为 `6e97ba31efe03adaf798e46ef7c26fe96cd85b05`，tree 为 `ebf0778517def0426a43e7ae24c46927c82a870d`；本地提交对象的 parent/tree 已核对。该提交只接纳真实 native formatter 对 AuthBus 夹具的一处换行输出；测试执行源与格式后源码的区别见下文。承载审计材料的后续提交与最终 PR head 以发布后的精确 readback 为准；发布前仍核实 head/lease。源码对象创建本身不代表远端 ref 已更新。

## 初次发布时的分支与提交图

初次发布固定快照采集于 **2026-11-21 08:09:57–08:10:02（America/New_York，UTC−5）**，包含 **7,812 个 refs、79,074 个当前 refs 可达提交**。相对先前 7,803 refs，新增 9 个、移动 5 个、删除 0 个；14 个 exact current tips 的只读元数据补取增加 20 个提交图节点，unknown tips 与缺失 parents 均为 0。本轮这些图查询未改变远端 refs。原清单、完整父图与逐 ref 分型见下方证据导航。

| 项目 | 固定快照结果 |
| --- | ---: |
| 当前已知受保护 refs | 538 |
| 其中名称不含 `hia` 的历史别名 | 414 |
| 已知保护闭包中的提交 | 1,470 |
| 普通 refs，不含 `main` | 7,273 |
| 最终 `77aae54…` 在固定快照中已包含的普通 tips | 2,858 |
| 快照中候选仍未包含的普通 tips | 4,415 |
| 上述未包含 tips 的不同 OID 数 | 4,195 |
| 已包含于当前 `main` 的普通 tips | 0 |

初次覆盖与保护交集计算绑定 `6e97ba31efe03adaf798e46ef7c26fe96cd85b05`；最终 `77aae54…` 的独立复核在同一固定快照图上只补入其单 parent 节点，完整 44,911 个祖先与已知 HIA 保护闭包、STOP 及元数据中已知的 STOP 后代没有交集，普通覆盖数保持不变。完整 59,349 个 leaf 的 Merkle 重建也匹配最终 tree。这些静态证明不替代发布时的新鲜 ref/lease 检查。此前识别的保护 tips `bc8d0117befcf44c140fbb6b82db17d2f3afb42e`、`44864f0f2937b86d4696deaf5fb0835067d33a13` 继续保留；最新补入历史保护别名 `research/e2-own-state-correction-20261121-ac5459` 的 tip `6cba59d70e697f926e423aaee878c2ca3daa2652`，形成上述 1,470 节点已知闭包。完整提交图元数据不等于所有源码和行为都已审完。

**原始第 551 个历史保护 pin 的身份仍未恢复。** 已知保护集合只增不减，不能由总数、时间顺序或名称猜测补齐。该缺口明确保留，不能声称完整历史保护清单已恢复。正在增加或更新的远端 refs 也不会由这一固定快照自动获得删除资格。

`main` 在此快照为 `732e934ba496d90fbe042b8d41d479ef901643e5`；integration 为 `0cee57ca617e0324e2df8e9447a2c075a6c76952`。本轮未修改这两个 ref，也未删除任何普通或 HIA 分支。需要先让最终候选通过原 required gates、真实进入 `main`，再以新鲜 exact-tip ancestry 和保护清单决定普通分支退役。

## 已准备的实际源码与历史变化

| 提交 | 内容与审查边界 |
| --- | --- |
| `8016166226cd6206ba09c83fa64acc91eca368ba` | 四个仅测试相关 Rust 文件：删除零调用的测试构造器，复用原私有 checkpoint codec，保留 18 个原断言，并删除末次冗余 clone。生产持久化实现未改。 |
| `394e28812368f5174b890cea51ff13e882231756` | AuthBus Unix 测试夹具在创建时设置 0700，并先 canonicalize 自己的临时目录，再组成数据库/检查点路径；六个原测试体和断言保持。针对 macOS `/var` 与 `/private/var` 路径别名的实际失败。 |
| `5a42644ff02a511e12ce2f95f1c11f85b709835f` | 用原锁定 Ruff 0.15.13 格式化四个 procedural-memory Python 文件。完整 AST、注释、11 个测试名和 38 个断言 AST 保持；标点和换行发生合法格式变化，不声称 token 完全相同。 |
| `0847396844638608708608072ec94961bb20458b` | 真实合入 `4a120a0bba8b493407930924822eb6cf38279976` 的原历史。默认 merge 的两文件四处冲突逐项审查，完整 Python AST 等价，保留当前格式。 |
| `132b3227ae1978b5ae2eba5b64efef53158a92f6` | 真实合入 `dbed60c6372a148a934e48e9a08ba88aa2a536e2` 的原格式历史。审查原 29 文件变化及默认 merge 的十文件十八处冲突，保留较新的实际代码。 |
| `55e81c7e12deb14e30b177fb7474dd3b1aa97b6d` | 只将 Architecture qualification job 总预算从 60 分钟调为 120 分钟；所有原命令、runner、资源参数、单命令 3,600 秒上限、产品期限与 required 汇总门保持。 |
| `6e97ba31efe03adaf798e46ef7c26fe96cd85b05` | 在 `55e81c7…` 后应用 formatter v3：登记 34 份有原文约束的精确历史 Rust 记录，沿用原逐路径/大小/SHA-256 校验；扩展两个原范围测试，不修改任何历史 Rust 原文、manifest 或生产 Rust。 |
| `77aae54a30eb37ef7930d01224e5ef312a5014a1` | 原 native Rust formatter 在测试通过后把 AuthBus `owner_tests.rs` 的一条路径表达式换行；完整后像与真实输出一致，其他字节及断言不变。该格式后像没有重跑测试。 |

两次历史合并均实际运行默认合并并审查冲突，不使用 `ours` 策略或仅挂父节点冒充代码合入。合并后全部 59,349 个 leaf 的 path、mode 和 OID 与 `5a42644…` 一致，tree 均为 `cf4965757cc8ef01109c06b40ade160f3a6f57bb`。局部对象库的 `write-tree --missing-ok` 只用于核对已经完整比较的 Merkle tree，不作为全部 blob 已物化的证明。

Architecture 旧任务在约 60 分钟取消前已有 33 条命令成功，最后 runtime-tasks 步骤尚在编译，未达到单命令上限。时间线符合总预算耗尽，但日志没有明确取消原因，因此这里只记录这一推断。新的两小时预算仍需真实 CI 证明足够。

### Formatter v3 的精确档案修复

旧 native 的范围解析首先碰到 AUDIT 内的历史 Cargo manifest：它属于 PR #2909 的四文件原始快照，继承 edition 的原 workspace 与 crate 入口本来就没有复制。该 manifest 的原 blob、大小和 SHA-256 均与既有 projection/packaging 记录一致，因此保留原文，不补造 workspace 或猜测 edition。

v3 为 **32 份 AUDIT Rust 副本**逐份核对原 packaging manifest、大小和 SHA-256；31 份另核对原 Git blob，UI 上游副本核对冻结证据 hash 与固定 Makepad commit 路径。再补齐 **2 份**原有档案遗漏：封存 continuation 内的 reader `recursive.rs`，以及明确区分旧已测 preimage 与后续格式化版本的 `bootstrap_runtime_preformat.rs`。前者三份 manifest 与完整封存 subtree 一致，后者精确匹配原 supersession 记录的 preformat SHA。其余十个无 manifest 的 executable/probe/fixture 输入由现有脚本实际编译或装配，全部保留在 formatter 范围。

原五份历史证据和五份 vendor 语法输入不变，合计 **44 份精确保留记录**。新增的固定前缀仅约束允许登记的路径；实际保留集合仍是逐文件固定字节清单，没有目录通配排除。原大小/hash、缺失文件、符号链接、路径别名与越界拒绝规则保持，`rust_file_command` 和 `rust_configuration_scope` 逐字不变。

原 `b8e8c6e82abc1479c573f61a5e17d28d581e6cad` 范围的 **4,247 个 Rust 路径**已在 `55e81c7…` 加 v3 精确脚本上完成静态命令规划：44 项逐字保留、4,203 项其余输入，scope errors 为零。完整计划为 2,032,681 字节，SHA-256 `280b77eb840e52999dc76b825592da39e615539240e44d2a4b45096dacadd8ab`。**全 b8e8 范围 formatter 没有执行；规划成功不是 4,203 个文件的格式化通过，也不是完整 native maintenance 通过。**

## 本轮实际验证与来源绑定

| 验证 | 实际输入与结果 |
| --- | --- |
| 原三包 strict Clippy、all targets、`-D warnings` | 在 `5a42644…` / tree `cf496575…` 上 exit 0，源码前后 clean。原七项诊断在本轮候选的这条真实命令中已消失。 |
| 原 B4 no-bypass suite | 同一 `5a42644…`，1,350 项，exit 0，源码前后 clean。 |
| 原完整脚本 Ruff 范围 | 同一 `5a42644…`，`scripts .github` 共 1,145 文件均已格式化，exit 0。 |
| 原 CI scope suite | `132b…` 加唯一 YAML 预算修改，完整树等于 `55e81c7…`；25 项，exit 0。 |
| Formatter v3 原 scope suite | root 在 `55e81c7…` 加 v3 两文件的精确输入上运行 `python3 -m unittest -v scripts.test_hepta_format_scope`：**41 项通过，exit 0**；原命令日志为 `Ran 41 tests in 3.191s; OK`。两文件执行前后 SHA-256 完全相同。该 suite 内的临时 fixture formatter probes 实际执行；它没有运行仓库完整 formatter，后续两文件格式命令另列。 |
| Formatter v3 两文件真实格式/检查 | 原 `just fmt --base 55e81c7…` 与同范围 `--check` 均 exit 0，format diff 为 0 字节，两个 Python 文件 AST 和 SHA-256 不变；此范围仅包含这两份新修改，不是原 b8e8 Rust 全范围。测试后未再次跑 suite，因为 formatter 没有改变其已测字节。 |
| Formatter v3 完整脚本 Ruff 范围 | 在上述最终精确脚本输入上重新执行原 frozen/offline `ruff format --check scripts .github`，**1,145 文件通过，exit 0**。 |
| 原 `.github/scripts` suite | 同一 `5a42644…` 的完整精确输入和真实 Cargo 上执行 314 条测试记录，原 unittest 命令 exit 0；实际为 304 个唯一 ID，原 loader 重复发现十项 V8 测试。额外审计 wrapper 的唯一性假设失败仍原样保留，不隐藏 wrapper exit 1。 |
| 同源真实辅助程序 | `codex`、`hepta-infer-worker`、`hepta-joint-propose` 实际构建成功，保存 Cargo compiler-artifact、ELF 与 SHA-256 绑定。 |
| Agentd / AuthBus 原 `just test` 首次尝试 | 两条命令在构建/链接阶段 exit 101，均未执行测试断言；完整日志包含磁盘配额耗尽及 SIGBUS，不能记作通过。源码仍为干净 `5a42644…`。 |
| Agentd 原 `just test --locked` 恢复执行 | 在 clean `5a42644…` / tree `cf496575…` 上 **1,605 passed、0 failed、181 原 profile skipped，exit 0**；1,605 个通过测试的 ID 多重集合与原记录完全一致。原断言、选择范围、单命令及产品期限保持。 |
| AuthBus 原 `just test --locked` 恢复执行 | 同一 clean `5a42644…`，**51 passed、0 failed、0 skipped，exit 0**。两条测试执行期间源码不变；恢复是独立新 attempt，不改写首次失败与其绝对 deadline。 |
| 恢复 attempt 的第一次原格式/检查 | 测试通过后，Rust formatter 生成上述 AuthBus 换行；Python 组因缺少 `uv` 使原格式和检查均 exit 1，attempt 总状态 failed。该真实失败保留。 |
| 仅缺失工具恢复后的原格式/检查 | 在独立工具目录使用官方 uv 0.13.9 发行物并核对 SHA-256；原 `just fmt --base 6cbad406…` 及同范围 `--check` **均 exit 0**。原 formatter/lockfile/scope 不变，执行前后同为 native postimage tree `f80cd064b5237c75b0703df376344edd17e3a745`，没有再改源码，也没有再跑测试。 |
| macOS 本地尝试 | Git clone 在 300 秒截止时 early EOF，tests_started=false；未取得本轮 macOS 测试资格。 |

早期容器 `.github/scripts` 尝试因无 Cargo 出现六个错误；第一次 native 尝试缺少 sparse 范围外的原 `third_party/v8/BUILD.bazel`。这两份失败记录保留。随后在独立 checkout 补全同一提交的实际输入才得到上述原命令通过；没有修改测试或增加 skip。

这些 native 执行来自本轮新 session 的 Linux x86_64、Rust 1.96.0、nextest 0.9.152；没有冒充 CI 固定的 nextest 0.9.103 环境或 macOS 资格。原 `/tmp` target 配额/链接失败、经内容及 hardlink 拓扑核验后的 target 迁移、测试恢复及工具恢复分别留有独立记录。

实际测试源为 `5a42644ff02a511e12ce2f95f1c11f85b709835f` / tree `cf4965757cc8ef01109c06b40ade160f3a6f57bb`。到 `55e81c7…`，两个历史合并的完整树不变，只另有单独验证的一项 CI 编排字段；到 `6e97…`，v3 formatter 与原测试改动另绑定 41 项实测；到 `77aae54…`，仅接纳 `owner_tests.rs` 的原 rustfmt 换行。该文件 blob 从 `8045757f7ea65d48534409f07541f5400712b116` 变为 `23ff40605963c8ea795fb2613053fbc117db63a0`，后像 SHA-256 为 `14fa4f1826c6f9b1365dc90849438cc556138a964705c17fcc2a95fa2274c93d`，其余字节完全一致。**5a 的测试通过与最终 77 的静态格式绑定分别记账；没有对 f80 格式后树或最终 77 重新运行测试。** v3 执行前后 `format.py` SHA-256 为 `374839d73d51cddde230f514888cd05532f791534bdd35c1842df19b8b2e2be9`，测试文件为 `a11eb6fa3d5d4f8fc5edfcec680e20f11dd9f8a4a977005b625dea3db743377c`；完整测试日志 SHA-256 为 `71502284a4f4852b4469a91785697baea4f00d9c940df0528e180dc2271fc6fb`。这些绑定**不能替代最终 PR head 的全部 required CI**。

## 仍然阻止进入 main 的实际事项

本轮没有把旧 head 的成功结果继承成新 head 的完整资格。原 `6cbad406a4a203201edc0e103c1377d3664e3fbe` / tree `08f5d464bedff1c1acbb3abe1d7f28e43827854f` 在 2026-11-21 07:43:39（America/New_York，UTC−5） 的全部 **102 个 checks 已终态：70 success、17 failure、13 skipped、2 cancelled、0 pending**。计数包含 required 汇总与 source/merge 重复范围，不是独立测试数量。GitHub synthetic merge `7714fcc496317e0d09c8673e172f7749d6147608` 与 operator deterministic merge `53995eb8862380d508ac50e5220d47811da05958` 均与原 source 同树，但执行身份分别保留。这些旧结果不升级为 `77aae54a30eb37ef7930d01224e5ef312a5014a1` 或后续审计提交的 CI 结果。

旧 `6cb` 的完整诊断用于指出待修复问题：

1. Windows AuthBus 的非 Unix 私有父目录校验当前直接返回 `UnsafeCheckpoint`，导致两个原正例失败，入口在数据库/检查点建立之前。该问题不能通过修改 Unix 临时目录夹具解决。
2. Windows elevated sandbox 的零参数 admission 当前直接拒绝，四个原正例在权限解析、ACL 和进程启动之前失败。恢复正例需要合格的隔离实现与真实 Windows 验证；不能把拒绝改成无条件成功，或删减原删除边界矩阵。
3. musl 的原 next-use 诊断超过 500 毫秒期限并返回 `OwnerUnavailable` / `DeadlineElapsed`；原期限保留。AppContainer/LPAC 的原机制探针也仍未获得合格结果。
4. 旧 Architecture job 未完成所有原步骤。新的总预算只解决编排容量问题，不预先证明后续断言通过。
5. 旧最后 native job 的 2,831 项普通库测试和 68 项 Root 测试通过，但其维护格式阶段因历史 AUDIT 副本缺失 owning workspace 信息失败，最终 bins check 未执行，维护完成状态为 false。本轮 v3 已修复范围登记并通过原 scope tests；完整 b8e8 格式执行、维护后的验证与最终 required CI 仍未完成，不能据此关闭整个 native gate。
6. 最新固定快照中候选仍缺少 4,415 个普通 tip（4,195 个不同 OID）的真实合入与相应逐项代码审查，当前 main 没有任何可据此删除的普通 tip。

既存自动审批已因 **cybersecurity risk** 拒绝 `d783273c25b3164f5f632482cb7b017fdcb9d756` 的生产持久化补丁。本轮未读取其实现、应用、编译、after-test、改写/委派重试，亦未使用其后代或等价 workaround 绕过该拒绝；该 exact STOP 持续生效。当前已观察的 Windows 两类入口失败与历史记录的 stale-history 问题是不同的直接触发点；没有建立它们依赖该被拒绝改动的因果关系。

## 继续执行的边界

用户当前指令已授权普通 Rust 分支的全量审计、合并和安全退役。继续工作需完成上述功能/平台阻碍和其余普通历史的审查，保留 `CI required`、`Architecture required` 及现有 review/protection。每次 ref 更新使用新鲜 expected SHA 且不 force。普通分支只有在其**当前 tip** 已由最终 `main` 包含、且不在当前或历史 HIA 保护闭包中时才具备删除前提。历史助手的泛化 HOLD 或 owner 措辞不另设永久发布权限，也不要求用户重复授权。

具体并发边界仍保留：private `9455785c23e0c8d2407f39283dfe4f80840c0ee5` / tree `e290e07140c1743e31f92f50773541f6ac8760fa` 的旧通过只绑定其原输入，不覆盖该并发 checkout 或接用其未验证成果；冻结 native jobs `19a6`、`19a5`、`19b8`、`19ce` 不查询、重放或恢复；未知 key `hepta-rust-c2d514464ab5-exact-source-copy-01` 及并发 native/helper/private-copy jobs 不触碰。本轮另建的 `5a` 恢复 session 有独立输入和日志，不改变上述具体任务边界。

完整此前 PR 说明保存在 `qa/repository-consolidation/20261121/rust-c1a0-audit/earlier-pr6799-body.md.gz`，保留原 handoff、owner 措辞、STOP 和失败记录作为历史事实。解压后的文件与先前发布版本逐字一致，仍保留初次归档时补入的一个 Markdown 文件末尾换行；不会用新的通过记录抹去旧的失败或未完成状态。当前执行授权按上文用户指令和具体边界处理。各项发布证据的来源、字节数、SHA-256 及公开副本处理见下方索引。

## 发布材料的大小与术语修订

首次发布到 `b9fb18785fb74e968b5e0bf304679515bfa93a2b` 后，原 CI 在两项审计材料规则中报告失败。Blob size policy 的 512,000 字节限制准确指出两个完整归档超限；现将相同原始字节保存为最多 491,520 字节的有序片段，不改检查器、阈值或 allowlist。原归档的完整大小、SHA-256、Git blob，以及每块的大小、偏移、顺序和摘要见 [ARCHIVE-PARTS.json](ARCHIVE-PARTS.json)。重组后全部原始记录及其摘要保持有效，使用方法见 [ARCHIVE-PARTS-README.md](ARCHIVE-PARTS-README.md)。

Codespell 2.4.3 唯一命中来自 `lint-source-review.md` 的 Rust 术语表达；该解释性叙述现使用 `mutable static items`。此次只作一处术语展开，不修改任何原日志、测试结果、断言或源代码审查结论。原叙述仍可在 b9 的不可变 Git 对象中核对；对应 manifest 条目区分原来源摘要与修订后的发布摘要。原 `.codespellrc`、忽略词、custody 清单与规则保持。

原失败来源：[Blob size policy](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44909716197/job/136862721519)、[Codespell](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44909716197/job/136862721594)。这一材料修订没有修复 Windows、AppContainer、musl 或其他仍未关闭的平台问题，也不代替最终 head 的完整 CI。

## 原始文本记录的无损压缩

`bb2ca75092084d22dff2d7a1d6245df75f5cca60` 的原远端 Codespell 与 Blob size policy 均已通过。随后 learning.operator deterministic merge 在成功构造真实合并后，被原 `git diff --cached --check` 拦下；Rust Clippy 和测试尚未开始。原失败见 [job 136870143637](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44911977664/job/136870143637)。本地按完整 PR base `69ec34ac53176ff1e46a1689048817c91adb5be2` 复现相同的三文件、十三条空白诊断。

三份原始文本现以 gzip 保存：历史 PR 正文的 Markdown 行尾空格、原补丁合法的单空格 context 行，以及原 musl 日志的时间戳行尾空格均逐字保留。没有清理、重写或截断原记录；每份压缩文件与解压后原文的大小、SHA-256 和原 Git blob 都登记在 `EVIDENCE-MANIFEST.json`。可用 `gzip -dc 文件名.gz` 读取原文。

| 原始记录 | 当前入口 |
| --- | --- |
| 早前完整 PR 正文 | [earlier-pr6799-body.md.gz](earlier-pr6799-body.md.gz) |
| Formatter v3 原始补丁 | [formatter-v3-source.patch.gz](formatter-v3-source.patch.gz) |
| musl 原始失败摘录 | [musl-original-failure.txt.gz](musl-original-failure.txt.gz) |

本修订仅改变三份证据的存储表示及导航和摘要。Git 空白规则、属性、CI 检查器、跳过清单、大小限制与 Rust 源码保持；新 head 的完整 CI 仍需实际执行，不能从前一 head 继承资格。

## 证据导航

下列名称对应本审计目录中的发布文件；`EVIDENCE-MANIFEST.json` 记录来源与发布路径映射和摘要。native 公开副本的处理边界由单独 publication review 记录，原失败与执行身份不被覆盖。

| 要核查的结论 | 入口 |
| --- | --- |
| 最终源码、发布 head 与整体范围 | [STATUS.json](STATUS.json)、[final-source-77-review.json](final-source-77-review.json)、[EVIDENCE-MANIFEST.json](EVIDENCE-MANIFEST.json) |
| 7,812 refs 的固定快照与逐项分型 | [branch-snapshot-7812.json](branch-snapshot-7812.json)、[current-refs.tsv.gz](current-refs.tsv.gz)、[all-current-ref-classifications.json.gz](all-current-ref-classifications.json.gz) |
| 完整已知父图及 HIA 保护集 | [完整父图的片段清单](ARCHIVE-PARTS.json)、[protected-current-refs.json](protected-current-refs.json) |
| 34 份新增原文保留证据与 41 项实际测试 | [formatter-v3-provenance-34.json](formatter-v3-provenance-34.json)、[formatter-v3-tests.json](formatter-v3-tests.json)、[formatter-v3-tests.log](formatter-v3-tests.log) |
| 44/4,203 静态规划及已执行的有限格式检查 | [formatter-v3-full-scope-summary.json](formatter-v3-full-scope-summary.json)、[formatter-v3-full-scope-plan.json.gz](formatter-v3-full-scope-plan.json.gz)、[formatter-v3-format.json](formatter-v3-format.json)、[formatter-v3-format-check.json](formatter-v3-format-check.json)、[formatter-v3-full-ruff.json](formatter-v3-full-ruff.json) |
| 本轮 5a native 原命令、所有失败/恢复与格式后无重测边界 | [native-validation-index.json](native-validation-index.json)、[native 归档的重组说明](ARCHIVE-PARTS-README.md)、[native-publication-review.json](native-publication-review.json) |
| 原 6cb 的 102 checks 终态 | [ci-original-6cb-final-summary.json](ci-original-6cb-final-summary.json)、[ci-original-6cb-final-facts.md](ci-original-6cb-final-facts.md) |
| 早前 PR 全文及历史约束记录 | [earlier-pr6799-body.md.gz](earlier-pr6799-body.md.gz) |
