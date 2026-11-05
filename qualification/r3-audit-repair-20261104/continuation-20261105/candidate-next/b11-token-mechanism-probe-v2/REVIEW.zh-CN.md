# B11：四主体 × 两 outside cohort 的 Windows 物理诊断候选 V2

本候选已经形成完整源码和一个独立 Windows job 草案，**尚未编译、格式化、运行或发布**。它不是 sandbox 修复。新增测试只判断观察条件、合法 inside I/O、outside 读取和清理是否有效；全部 outside 写入、创建、删除结果按实际发生情况记录。原三项严格测试及两项四格测试不改名、不改正文、不改断言或预算。原 B11 状态仍为 OPEN。

## 固定输入与可审切片

代码基线是 `5b6331250ff459033bd44d1a95daec70131277cc` / tree `b26598d0d97d8d51e723bb5582137315f2174d35`。它与 e78 Core/musl 候选分离。`source-map.json` 给三条源码的精确前后像；`fixed-source-identities.json` 对照实际 5b 全叶清单固定现有依赖及原测试。只新增 `token.rs` 的 `cfg(test)` 模块挂接、两个私有测试文件；没有 Cargo、BUILD、锁、生产函数或生产权限变化。

源码按两片审查：`01-label-custody-support.patch` 只有未挂接的测试支持文件，单独不具测试或生产效果；`02-probe-consumer.patch` 挂接测试并增加消费代码。第三片 `03-independent-windows-workflow.patch` 单独提供运行入口。`full.patch` 是前三条 Rust 路径的完整组合，`diagnostic-pr-full.patch` 则组合三条测试源码与新增 workflow。

V1 原件保存在 `v1-frozen/`。V2 的唯一行为变化是诊断输出改走 `std::io::Write` 写入锁定的 stderr，并带前导换行，避免成功测试的 libtest 宏输出捕获和 banner 同行污染。正常输出错误会让诊断无资格；Drop 中的错误报告仍是 best effort。没有改物理操作顺序或断言。Rust 1.95 原 `stdio.rs` 将 `_eprint` 经 `print_to_buffer_if_capture_used` 捕获，`StderrLock` 的 `Write` 则直接转发底层流，见 `primary/rust-1.95-stdio-api.json`。这不是运行证据。

## 需要观察的真实差异

| 主体 | token 构造 | outside Medium | outside Low / 另一 cap cohort |
| --- | --- | --- | --- |
| host | 实际进程 token | 原样记录操作，要求 host 正控有效 | 同左 |
| current_strict | 现有生产 strict constructor，flags 不变 | 观察读、覆盖、创建、文件/目录删除 | 同左 |
| current_strict_low | 同一生产 constructor，仅降低此新建测试 token IL | 独立观察 MIC 效果 | 区分 Low 与 cohort 授权边界 |
| full_restricting_explicit_read | 仅测试内无 WRITE_RESTRICTED 的 token；有限 owned 对象增加 read SID | 观察明确 read grant 与写 cap 分离 | 同左 |

每行都先查询实际 token IL/attributes/mandatory policy，并在真实 impersonation 期间查询当前线程 token。返回后校验其状态和计划主体一致。每个 outside parent 的 `FILE_DELETE_CHILD = 0x40`、outside 文件和目录的 `DELETE` 都对同一个保留对象的完整 security descriptor 执行四主体 AccessCheck。AccessCheck 只作为机制观察，不能替代随后真实文件 I/O，也不能据此假定 MIC 在所有路径生效。

实际 I/O 包括 outside 和 inside 的读取、覆盖、新文件创建、文件删除和目录删除；所有错误包含种类、原 OS code 和消息。RevertToSelf 后再检查真实内容、名字存在性与恢复状态。新探针的八个阳性条件只要求 fixture/read/inside I/O/host 正控和正确恢复；它不会因为 strict outside 删除成功而将结果改成拒绝，也不会因为 probe PASS 宣称隔离闭合。

显式 read SID 仅授予有限的 owned fixture 路径 `FILE_GENERIC_READ | FILE_GENERIC_EXECUTE`，没有增加 WRITE/DELETE，亦没有把该 SID 加入新建 IPC 的 GENERIC_ALL default DACL。此结果不代表生产 loader/IPC/任意 ambient read 已解决。

## 对象、label 和生命周期

所有变化都位于新建 TempDir。对象创建时带显式 Medium mandatory label，因此恢复不依赖未证实的 LABEL + NULL 清除语义。每个观察对象由不可继承、无 DELETE 权限且允许 FILE_SHARE_DELETE 的句柄保留；读身份、保存 SD、设 label、回读和 survivor 恢复均使用该句柄。验证原 owner/group/DACL 不变，拒绝 reparse point 与多链接普通文件。

删除操作使用新的路径打开，不使用观察句柄。成功删除处先记录 same-handle SD/identity/DeletePending，再关闭 share-delete 句柄，实际确认名字消失；survivor 则恢复原 Medium label 并精确回读 complete SD。每行尝试完成所有十个观察对象，即使其中一个恢复失败也继续处理其余；任何恢复/readback 错误令 fixture 无资格。异常 Drop 只 best-effort，不冒充已恢复。

这个同步 token probe **不创建任何子进程**，`descendants_spawned=0` 明确输出；因此不存在新增 Job 后代清理链，也不能将它计为 process backend、loader 或 Job 隔离资格。原 legacy/backend 测试仍在同一 outer target 中原样执行。若不能创建显式 Medium 对象、降低测试 token、查询标签或准确恢复，结果是 fixture 无资格，不能以早退或 skipped 当通过。

## 独立 Windows 执行入口与解释

草案文件是 `execution-candidate/.github/workflows/hepta-windows-token-mechanism-probe.yml`，目标仍为：

```text
//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests
```

它使用原 `prepare-bazel-ci`、native MSVC host/platform 包装、`windows-latest` 和 120 分钟 job 预算；不增加 test filter、test arguments、重试、timeout、权限或 secrets。原分片标签被准确的 observation-only build metadata 取代；新增 `--test_output=all` 只用于保留输出，不使用 `--nocapture` 绕过原 launcher 路径。完整 target 都被选择，六个必须出现的名字是记录/复核清单，不是缩小 target 的过滤器。

1. `token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes`
2. `token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`
3. `unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots`
4. `token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells`
5. `unified_exec::tests::delete_permission_tests::legacy_delete_routes_require_workspace_capability_in_all_four_cells`
6. `token::integrity_probe::integrity_mechanism_probe_observation_only`

原 wrapper 的退出码由 PIPESTATUS[0] 写入独立文件并原样退出，原严格失败仍会使 job 失败。完整 console、原 code、source HEAD/tree/leaves、原 collector 保存的 test.log/XML 和 Bazel execution logs 会一并上传。固定 5b collector 的 RETAINED_TARGETS 已含这个 Windows outer target；使用原 wrapper 的失败归档和按真实 console 报告选择的成功归档，不新增无条件 collector 调用。实际原始名字、六例是否执行、八行观察是否完整、cache/attempt/skip 情况需要读取新 job 原件；缓存日志、target PASS、配置源码或新 probe PASS 都不能单独作为新鲜实际隔离资格。

该 workflow 自身只有一个 job。独立 Draft PR 仍可能触发仓库其余现有工作流；不声称整个 PR 只有一个 job，也不解决当前主矩阵调度未知原因。

## 建议的 Draft 交付形态（尚未执行）

建议从上述固定 5b 创建独立诊断 head，例如 `diag/b11-token-mechanisms-20261105`，PR base 使用当前产品分支 `fix/r3-original-product-contracts-20261104`，发布前必须确认其仍指向审查所用基线，或重新说明 base 关系。三个小 commit 分别承载支持文件、测试挂接、单 job workflow。不要包含 e78、B16 payload、Windows production 权限变化或其它修复。

标题可用：`test(windows-sandbox): observe token integrity and delete routes`。PR 应明确是诊断 Draft：为什么原 strict outside 删除仍需解释、将记录哪些真实机制差异、原严格测试如何保持失败资格，以及原生运行和修复仍 pending。当前没有创建 branch、commit、PR、dispatch 或 Windows ACL 操作。

## 已做与未做

隔离 cloud Git 的 25 条命令已验证完整四路径 patch、三个分片、逆向以及 V1→V2 的字节等价；YAML 解析和 Bash `-n` 静态语法通过。原 V1 验证器把 `git diff --no-index --check` 的正常差异 exit 1 错当失败，原记录保留；V2 要求 stdout/stderr 无 whitespace diagnostic 并正确区分该退出码。一次本地 workflow selector 的可选 name KeyError 也保留，未修改产品或 workflow 行为。

Windows Rust fmt/compile、完整原 target、原五控制和新探针均未执行，未新增依赖或运行 Linux 替代实验。原始 Windows 删除失败、B11 OPEN、两候选机制的适用范围都保持不变。
