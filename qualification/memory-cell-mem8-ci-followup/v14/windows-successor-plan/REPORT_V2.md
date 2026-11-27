# Windows native 后继验证方案（只读审阅稿）

**状态：仅方案，未实现新 harness，未准入或触发任何新运行。** root 已报告 V5 lock 审计通过、source PR 于 12:36:36Z 前进到 9bd2，并准入新原生 CI；应先观察这一次运行，再根据真实终态决定是否需要拆分。不能将下面的分区安排或原 189 的通过记录当作新源码通过。

## 1. 固定源码和既有入口

本方案只绑定：

- 源码：`9bd2f589debdba4a93baa363817c3669cb103721`。
- 原根树：`c77785ecb368c44ea699769001a47402c9f50591`，由 root 已发布的 source-gate 身份给出；本次独立逐文件读取并复算下列 11 个 Git blob，未重新下载整树。
- 原 scope：`.github/fixtures/windows-current-ci-scope.json`，blob `72f75127e9f92236def02a67a099fd90bb2a9b09`。
- 原 driver：`.github/scripts/windows_current_ci.py`，blob `161ed1149c8ffb5f2bb2a8272f555f8b91d729fe`。
- 原 workflow：`.github/workflows/hepta-windows-current-ci.yml`，blob `d9dc4986a86a6d29e51203e34b7cc3e4f08c536b`。

这三份 scope／driver／workflow 与原 189 的对应对象相同。scope 中的 `originalHead` 和 `scopeBase` 是既有历史字段，必须保留，不能把它们当作此次待执行的 head。后续 Cargo/Bazel lock 或源码若产生新提交，需要重新冻结确切 source head/tree；本方案不跟随移动分支。[原 scope](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/.github/fixtures/windows-current-ci-scope.json)；[原 driver](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/.github/scripts/windows_current_ci.py)；[原 workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/.github/workflows/hepta-windows-current-ci.yml)。

## 2. 原运行实际留下了什么

原 head `189711e3563ea13a5328d52e99a286f082045b98` 的 run `43002359812` / job `130461336393` 原配置的 job timeout 为 65 分钟；运行完成了前 15 组、139 个不同 case。原结果为 **137 PASS、1 LEAK、1 FAIL**；严格按原 driver 评估，13 组通过、2 组不通过。第 16 组 `exec-server-observation-wire` 在编译时中断，后 3 组未开始，共 28 个原定 case 没有完成。原 API 终态为 cancelled，原日志出现 KeyboardInterrupt；观察时间与 65 分钟配置相符。将取消归因于作业预算只是时间一致性推断，scheduler 的具体取消原因没有独立观测。这些未完成 case 不能列为已失败或已通过。

两项原非通过结果必须原样保留：

| 原 group | 实际 case | 原终态 |
|---|---|---|
| sandbox-original-failures | `unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit` | LEAK，group 进程 exit 0，但原严格评估仍失败 |
| sandbox-native-delete-routes | `unified_exec::tests::delete_permission_tests::legacy_refuses_before_elevated_four_cell_delete_boundary` | FAIL，group exit 1；末尾重印不是第二次执行 |

本次逐字核了原 `groups.json`（32,374 B，SHA256 `796b3b2c917991e5d2bde74b0e27b7c4b1388d1e4dd0299db80fc99c921e1bba`）、helper preparation 和两个终态日志。它们来自已保留的原 v2 档案（235,016 B，SHA256 `266fd121e2aca469e4ba9343a7db5594d58afffaae6f0c20af54f35ec6781c1d`），没有新增 host 查询。

原 helper build 用时 818.656 秒，原 core group 用时 1081.531 秒。完整 15 组时长在 `original/ORIGINAL_DURATIONS.json`。这些数值同时包含编译和测试，且共用逐渐变热的 target；它们不能作为新独立冷作业的完成时间预测。

## 3. 能否完全不改 source／driver 而分组

**静态上可行，但原 CLI 本身不支持。** 原 `main()` 只有 `--expected-head`、`--output`，并从自身文件位置计算源码根目录。把它复制到独立 harness 目录后直接执行，会有资格化错误树的风险。

可复用的是真正既有的函数：

| 原 driver 函数 | 已有接口 | 后继 harness 必须遵守 |
|---|---|---|
| `source(root)` | 显式源码根目录 | 固定 9bd2、树 c777、tracked clean 和 Cargo.lock 前后身份 |
| `valid_source(expected, before, after)` | 显式 head 与两次观察 | 不用旧源码观察替代新 source |
| `prepare_sandbox_helpers(root, output)` | 显式源码与输出目录 | 保留原 helper build、native PE 识别及编译产物逐字发布检查 |
| `execute_groups(root, output, groups, invoke=None)` | 显式原 group 对象列表 | native 必须使用原默认 `invoke=None`，不能替换执行回调 |
| `assess(group, exitCode, raw)` | 原日志／case 集合评估 | 保留全部非 PASS 终态和选择失败 |

独立 harness 可以在确认完整 driver 字节后，用非 `__main__` 模块名 import 该未修改文件，先完整核原 scope 的 19 行，再按冻结 ID 从原对象中取出分区内的 group，按原顺序调用以上函数。这样无需 monkeypatch、无需临时修改 scope，也不必改任何待资格化源码。必须保留 `PYTHONDONTWRITEBYTECODE=1`。

新 harness 仍需显式保留原 `main()` 的实际 Windows 检查、工具版本、canonical TEMP、真实 helper、源码前后观察和终态记录。它还需要自己的完整集合 fan-in 与适当回归。**本报告没有实现、运行或资格化这个新 harness。** 如不接受函数复用，才另提把原 main orchestration 抽成显式 root 接口的最小源码改动；当前没有为此改变 driver。

## 4. 条件性分区和完整集合

本次纯数据核对确认：原 19 组共有 **167 个不同 package+case 身份**，每组的 requiredTests 长度等于 expectedTestCount，组间无重复。保留原每个 group 的完整 filter、package、case 数及 requiredTests，不拆散 group。

| 待审分区 | 原 group 序号 | 原 case 数 | 新增 case 数 | 合计 |
|---|---|---:|---:|---:|
| storage-owner | 1、4、5、6、9、10 | 93 | 0 | 93 |
| core-session | 2、3、14 | 14 | 0 | 14 |
| sandbox-runner | 7、8、11、12、15、19 | 41 | 0 | 41 |
| exec-wire | 13、16、17、18 | 19 | 3 | 22 |
| **完整集合** | **1—19 各一次** | **167** | **3** | **170** |

条件性后继方案新增独立 group `restricted-write-preexisting-hardlinks`，package 为 `codex-exec-server`，只选择这三个已经存在于 9bd2 的 lib 单测：

- `windows_restricted_write::tests::restricted_helper_rejects_existing_hard_links_without_modification`
- `windows_restricted_write::tests::restricted_helper_creates_and_rewrites_single_link_files`
- `windows_restricted_write::tests::unrestricted_filesystem_keeps_existing_hard_link_behavior`

当前未修改的 Windows-current run `43021840561`（root 提供的 attempt 1 身份，创建于 12:36:45Z）仍仅选择原 **167 例**，不会自动选到这三例。本文的 **170 例**仅是待审后继 scope。

完整 170 身份在 `EXPECTED_CASES.json`，20 个确切 argv 在 `EXACT_COMMANDS.json`。新三例是独立补组，原 source scope 文件不改。[新单测原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/codex-rs/exec-server/src/windows_restricted_write_tests.rs)。

## 5. 保留所有执行与验收条件

每组仍用原命令形态：

```text
just test --locked -p <原 package> --lib --cargo-profile dev-small
  -E <原 filter> --test-threads 1 --no-tests fail --retries 0
```

原 justfile 设置 `NEXTEST_PROFILE=local` 和 `RUST_MIN_STACK=8388608`；原 run-nextest 加 `--no-fail-fast`。原 nextest 配置和 test 内部的原时限保持不变，不改重试、拒绝条件或安全断言。工具仍为 Rust 1.96.0、just 1.51.0、nextest 0.9.103，Cargo build jobs=1，原 dev-small 和环境约定不变。[justfile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/justfile)；[run-nextest](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/scripts/run-nextest.py)；[nextest 配置](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9bd2f589debdba4a93baa363817c3669cb103721/codex-rs/.config/nextest.toml)。

如后续决定准入分区方案，每个 job 必须有独立 runner、target 和 canonical TEMP，不能并发抢同一个 Cargo target。每个 job 都保留原真实 `codex-windows-sandbox-setup` 与 `codex-command-runner` 编译和 sibling publication 前置，不借旧 binary。helper 失败不使其后组静默跳过，也不消除最终失败。

65 分钟可作为每个独立 job 原样保留的作业预算；四 job 最多 260 job-minutes 是新的调度拓扑，不能描述为原运行的续时。组内 test threads 仍为 1，分区内保留原 group 顺序。若采用 matrix，需 `fail-fast:false`，一组失败不能取消其他分区。没有冷编译完成保证，也没有据此启动四份作业。

最终 fan-in 必须满足：

1. 全部分区绑定同一新 campaign、确切 source head/tree、harness 与 scope 身份。
2. 原 19 group 加 1 supplemental group 各出现一次；原每行的完整对象与已固定 scope 一致。
3. 全部 170 个 package+case 身份与 EXPECTED_CASES 完全相等。原 count／package／missing／non-PASS 检查全部保留，package-wide filter 选出额外 case 也必须拒绝。
4. 每个分区都有 source before/after、Cargo.lock、tracked clean、真实工具／helper 身份及该次原始日志。
5. LEAK 即使进程 exit 0 也不通过。FAIL、TIMEOUT、EXECFAIL、意外 SKIP、缺项、源变动和被中断作业均不得变成 PASS；缺结果不能借原 189／F2／G 的结果填充。
6. 原 driver 没有自行保留逐组 JUnit；若后续加采集，只能在下一组覆盖前复制实际新 report 并绑定当次命令／source／新 run UUID。不能把旧 JUnit 当新结果，也不能宣称原已经执行了未有的 JUnit gate。
7. 原 raw／group 进度／helper 信息在失败或中断时也保留。archive upload 成功不等于测试通过。

## 6. 原 enabled hardlink 回归必须另验

`suite::apply_patch_cli::apply_patch_cli_preserves_existing_hard_link_outside_workspace` 是原 core integration/Bazel 路径，**不属于这 170 例**。上述原 group 全为 `--lib`；三个 helper 单测不能证明实际 enabled apply_patch 路径已经安全拒绝 outside alias。

应继续在原 blocking core/Bazel exact-source 验证中保留此 case 的拒绝、原 bytes 和 link 不变断言。若以后单独运行，需要显式原 integration target 和真实 Codex CLI／依赖身份；不能悄悄把它作为第 171 个 lib case。

新增 hardlink guard 也只处理 restricted typed fs write 已存在的多链接目标。检查后并发新增 alias、shell／exec／copy 等其他写入路径仍不在已证明边界内。Windows elevated outside-delete 产品缺口亦没有由分组或新 helper 测试修复：现有 refusal assertion 必须继续作为真实门槛。

完整 elevated 源链／12 ACL／原 outcomes 的独立包已由 root 远端全读回：[ORIGINAL_SOURCE_REVIEW.tar.xz](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d9b5987a67bb110d2c013a5e1a379fb976c2db22/qualification/memory-cell-mem8-ci-followup/v14/windows-elevated/ORIGINAL_SOURCE_REVIEW.tar.xz)。其中明确：没有实际 child token trace，且没有提交未经读权限、WinSta0、route/WFP 闭包资格化的局部 token 修补。

## 7. 后续诊断的独立界限

如果新的原生执行仍出现 elevated outside-delete，下一步可单独审阅一个 test-only、严格限量的实际 child token 诊断，记录与该 child／原 owner 绑定的限制 SID 类别、权限和原 native route，而非仅打印父 runner 的静态构造输入。此项当前没有实现或准入；任何新子进程、case 或 instrumentation 都需要新的 source 身份和独立 scope，不能伪装成 9bd2 原 170 例，也不能算权限已修复。

`verify_plan.py` 只离线核文件哈希、原组／case 完整集合、命令和分区，不 import 原执行 driver、不调用 Cargo／host／模型。它通过只说明本报告可复算，不能关闭原生 CI 或 MEM 能力门槛。
