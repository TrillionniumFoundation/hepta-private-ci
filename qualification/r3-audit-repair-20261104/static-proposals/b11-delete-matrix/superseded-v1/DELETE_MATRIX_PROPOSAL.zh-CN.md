# B11：Windows 删除权限四格控制（静态、未执行）

本候选只增加真实文件系统控制，帮助区分普通身份的目标 `DELETE` 和父目录 `FILE_DELETE_CHILD` 两条删除路径。它不改变 `CreateRestrictedToken` 的 flags、capability 集合构造规则、生产 ACL、legacy loader 或 DLL 行为，也不宣称修复了两条物理删除失败。

固定原源为提交 `7bc267096f23159605c0b6563374e697f8a0bd1f`、树 `f8251e1d14fa8524ab469281296cd4cf708f173c`。三个已有修改文件已从该提交完整读回，Git blob 与此前 `cabc` 原审计源相同。新增两个文件在该固定提交中的不存在状态也已 GET 核实。本次只有云端候选和不可达 Git 对象，没有 native、编译、格式化、Windows 执行或 ref 变化。

## 实际控制及冻结断言

每条执行路径各有两套新建的临时对象：普通宿主对照和受限执行。每格包含独立父目录、一个有固定内容的文件、一个空目录。所有对象在配置前即取得同一对象的句柄；其访问权没有 `DELETE`，句柄不可继承，允许共享删除。

通过原生 `SetEntriesInAclW` 和 `SetSecurityInfo` 设置 protected DACL，只有 Everyone 的显式 allow/deny ACE，且 ACE 不向下继承。目标对象和父目录分别设置，消除继承、其他身份及混合路径的干扰。宿主和受限两套对象的实际 DACL 必须逐字相同。

| 格 | 目标 DELETE | 父目录 DELETE_CHILD | 宿主文件与空目录 | 无对应 capability 的受限执行 |
|---|---|---|---|---|
| Neither | 显式 deny | 显式 deny | 必须拒绝，原对象仍在 | 必须拒绝，原对象仍在 |
| TargetOnly | allow | 显式 deny | 必须真实删除 | 必须拒绝，原对象仍在 |
| ParentOnly | 显式 deny | allow | 必须真实删除 | 必须拒绝，原对象仍在 |
| Both | allow | allow | 必须真实删除 | 必须拒绝，原对象仍在 |

宿主四格不符即测试失败，不允许忽略、不允许将其解释为产品隔离正确。原生 Rust 控制还要求宿主第一格的两项错误均为 `PermissionDenied / OS 5`，后三格均成功；受限四格则要求每项均为该真实拒绝错误。legacy cmd 记录真实输出和每个命令的原 ERRORLEVEL，但不会把 cmd 的 ERRORLEVEL 冒充 Win32 errno；最终判据是实际对象状态。

## 两个新增用例

1. `token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells`：调用未修改的 `create_workspace_write_token_with_caps_from`；两 active capability 为 restricting SID，logon/Everyone 不得成为 restricting SID。进入原 `Impersonation` 后，先完成真实允许根的文件/空目录删除，并确认 outside 文件仍可读，再执行四格。退出原 RAII impersonation、完成 `RevertToSelf` 后才输出结果和读回对象。
2. `unified_exec::tests::delete_permission_tests::legacy_delete_routes_require_workspace_capability_in_all_four_cells`：普通宿主先用真实 `cmd.exe /d /c` 执行同形矩阵，子进程五秒等待失败会 kill/wait 并失败。随后通过原 `spawn_windows_sandbox_session_legacy` 执行 workspace-write 场景；仍是 `Some(5_000)` 和原 `collect_stdout_and_exit` 的十秒参数。真实允许根必须删除成功，全部四个操作标记和最终完成标记必须按序出现，四格 outside 对象必须保留。

这两个新用例的冻结 expected 是产品隔离合同；在未修复的当前产品上可能真实失败。没有先把未知受限结果设成“应该成功”的诊断假阳性，也没有改原三条失败来求通过。

## 物理身份、删除后观测与清理

原生句柄始终指向同一文件系统对象。操作后先通过这些句柄核验 volume/file-index 身份、DACL 未变以及文件内容未变，同时记录 `DeletePending` 和 link count。不能仅凭待删除时路径返回 OS 5 就宣称权限拒绝；Windows 删除可能等最后句柄关闭，POSIX unlink 又可能提前移除名称。因此释放观察句柄后另行打开原路径：真实 `NotFound` 才记为删除，其他错误直接失败；仍存在的对象必须具有原 identity。

正常清理通过原句柄恢复原 DACL/保护标志并传播错误；已待删除或零 link 对象不作恢复。异常退栈有同一对象的尽力清理，它不构成通过判据。所有操作限于本测试新建的 TempDir 对象；不扫描宿主目录或读取共享 sandbox 日志，不把持有观察句柄交给子进程。

这里的四格只证明通用 outside 文件/空目录的两条删除路径。原 legacy `.git` 特殊根涉及生产 startup 的专门 ACL 设置，本候选不模拟、更不绕过该过程；原 `.git` 严格断言继续保留，不能由这两个新控制宣布闭合。

## 原用例和 CI 接线

原 `token_tests.rs` 的全部 18,059 字节作为完整前缀保留；原 `unified_exec/tests.rs` 的 43,037 字节仅增加一个测试子模块声明。三条原失败定义、所有原 host/写入/读取/拒绝断言、原五秒 child 与十秒收集参数均未改。

现有 `codex-rs/windows-sandbox-rs/BUILD.bazel` 调用 `codex_rust_crate`；固定 `defs.bzl` 以 `src/**/*.rs` 收集源码并构建 `windows-sandbox-rs-unit-tests-bin`，通过既有 wrapper 暴露 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests`。根模块仅在 `all(test, target_os = "windows")` 注册公共测试夹具，legacy 测试文件的 `#[path]` 注册新增用例。因此没有未编入的孤立 `.rs` 文件，无需新增 Cargo/BUILD 目标或锁。

固定 `.github/workflows/bazel.yml` 原 Windows 路径查询非 manual test target，该 label 加换行的 POSIX cksum 为 `1544371041`，按原四分片表达式落在第 2 分片。原 Windows launcher 实际 `--list --format terse`，保留原 skip 条件，并用 `--exact` 分批执行；两个新增名称都不匹配当前两个 skip 字串。这里核实的是源码接线，最终新 head 必须在真实 Windows 原日志中出现两个完整名称及终态，不能拿 Linux 或另一个 head 的结果代替。

验收应同时保存实际 source/merge tree、原编译与 libtest 名单、完整 test.log/XML 和每次尝试。若目标最终成功而现有上传只保失败日志，需要明确保留该成功目标原件；目标级绿色本身不足以恢复两项控制的逐例证据。本候选没有修改上传、命令、重试、skip 或预算。

## 限制

当前仅做静态 patch 重建和源码/WinAPI 检查。两组补丁的原文增量分别为 375 行与 109 行，删除 0 行；尚未运行 formatter，后续排版的实际行数应重新记录。没有可用的 Windows 原生主机；新 Windows CI、原三失败、原全部 host 负控及窄幂等性候选的真实验收仍是 gate。宿主基线失败、setup/编译失败、读取不全、超时或选中零项均不得记为任何删除策略的因果证据。

官方行为依据：Microsoft 的 [DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew) 说明目标删除权与父目录删除子项权、共享删除及最后句柄释放的关系；[文件安全与访问权](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights) 说明目标 ACL、继承与标准权利。实际四格仍须由宿主物理控制验证，不以文档替代运行结果。
