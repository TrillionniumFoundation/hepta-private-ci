# B11 v2：修复两个 host Neither 测试的非特权前提

## 状态与固定来源

**这是四路径、test-only 的候选，尚未 compile、fmt 或原生执行，不是 strict sandbox 修复，也不关闭 B11。** 固定 source `87b8603f21e52063ed54ce89cba26756a3efaab7`、实际 tree `9a804c7b6e0dd554cdb435f41e06c5c689fffaaf`、实际 merge `09960fe697c9c181e4a7d624e29b49360877b687`。四个相关旧源码均重新 full GET，完整字节与实际树 leaf 相等。根 AGENTS 原件 `a22ff3bee70261f6061d598c31f0016e785a7a3c` 也完整保留；本代理没有执行 just test / just fix / just fmt 或完整 suite，原生验证由根与既定 native owner 负责。

完整候选 tree **computed** `fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae`；10,590 leaves、1,571 directories。`full.patch` 与 `reverse.patch` 各为 4 路径 / 4 hunks，全部 pre/postimage 正反重放精确相等。这里的 tree 是计算值，actual blob 登记与 publication 另记；不把计算值写成已发布。

## 为什么要修复 host 控制前提

native12 的完整原 test.log 165,186 字节、SHA-256 `36c31fd6f11301673685d00f5e6c63d0a797650148d215cd01b4db5f168f397d`。本候选只借用该运行中已经执行完成的 observation 机制，原 whole 仍为 147 PASS / 7 FAIL / 2 ignored。完整原件 actual registry 是 `391236ff6394987e52eebab3b73fd0aaa58d4f9c`。

同一身份、无 restricting SIDs 的普通高权限主体在 Neither 格真实删除了文件和目录；只应用 DISABLE_MAX_PRIVILEGE 的 owned 派生 token 在 Neither 格真实拒绝两种删除，其他三格仍删除。Rust 的 direct/impersonated 控制和两个实际 primary child 已完整记录。两个 child 在释放门闩前的完整现有 token record 与其预期 identity/privileges 一致，exit 0、cleanup wait 0、active process 0。

**CMD 在 denied 两次删除时仍打印 FILE_RC/DIR_RC 为 0，且有两条 Access is denied。** 因此不能用命令返回码代替真实文件后态，原四格物理断言完整保留。结果证明权限集合干预影响普通 ACL 控制；不把效果归因于单一 SeRestore 或其他单一 privilege。

## 四路径变更

| 路径 | 候选变更 | 明确保留 |
|---|---|---|
| `src/token_tests.rs` | host 四格操作进入 nonprivileged ACL token 的同步 impersonation scope，操作前验证 actual effective token，退出后验证宿主恢复 | 原所有 host 错误/物理断言；原严格 half 全字节；测试名和 roster |
| `src/unified_exec/delete_permission_tests.rs` | host `Command` 改为指定 primary token 的 owned launcher | 原 matrix_script 全字节、同一 script 的原始字节后缀、host status/roster/物理断言、完整 strict half、原 mutex guard |
| `src/acl_control_test_support.rs` | 新 433 行私有测试 helper，封装 token / impersonation / gated primary child | v3 native helper 的机械来源与失败清理；不增加 production API |
| `src/lib.rs` | 只增加 `cfg(all(test, target_os = "windows"))` 的私有模块登记 | 其余完整字节 |

`token_neither_privilege_observation.rs` 的实际 `8c16416c185f17871c25139bc16c6fd112b5fd41`、原八行 probe `fc9faa6d47ac5fdefa216affceb51a586f8e6b81`、生产 token、desktop、process、ProcThreadAttributeList 与 Job 均没有修改。

## v2 的唯一静态修正

v1 原源码、四个 actual postimages、正反补丁、报告与 freeze manifest 完整保留。根静态审查发现，私有 gate 原先依赖 ambient CMD extensions/delayed expansion；继承环境中也可能有私有 B11_RELEASE 的大小写别名。这是审阅发现的前置风险，未发生新的原生运行或原生失败。

v2 仅改 helper：在 gate 开始时 setlocal EnableExtensions DisableDelayedExpansion，成功 gate echo 后 endlocal，再接原 matrix_script 完整字节；override 合并后清除全部 eq_ignore_ascii_case(B11_RELEASE) 项。原 /d /c 保留，没有把 /e: 或 /v: 施加到矩阵；endlocal 恢复其原模式。其他三个候选 postimages 仍逐字节为 208e17f、ba51c9e、14a9cae。v1→v2 恰一 helper / 两 hunks，正反完整字节重放相等。

Microsoft 的 [setlocal 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/setlocal) 明确支持在 batch 局部控制两种模式，并在 endlocal 恢复之前设置；[cmd 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd) 说明这些默认设置可来自注册表且变量名不区分大小写。本次未编辑注册表或宿主环境。

## 非特权 token 与 Rust scope

`AclControl::new` 读取普通进程 token，确认当前线程没有别的 effective token；派生时只传 DISABLE_MAX_PRIVILEGE，SID disable / delete list / restricting list 均为空。不设置 LUA_TOKEN、WRITE_RESTRICTED，不写 token IL/default DACL，不调整宿主权限。

现有完整 record 检查的是 user SID+attributes、groups+attributes、restricting SIDs、integrity RID+attributes、mandatory policy、session、AppContainer 状态、token type，以及全部 privilege LUID/name/attributes/enabled。派生前后的 identity record 必须完全相等、restricting SIDs 必须为空、不得有 SeChangeNotifyPrivilege 以外的 enabled privilege。不是声称枚举了 Windows 的每个 TOKEN_INFORMATION_CLASS。

Rust 操作前 actual thread token 必须匹配派生 token 的 identity/privileges，类型为 SecurityImpersonation。返回的 RAII guard 借用 token，任何查询失败、原操作错误或 panic 都先恢复线程；RevertToSelf 失败直接 abort，避免污染复用测试线程。正常返回后再次比较原 ordinary effective record，才允许原矩阵恢复/物理检查。随后原 strict token 构造与完整原断言原样执行。

## CMD gate、继承与清理

线程 impersonation 不能替代真正的 primary child 创建。本候选直接使用已经在 native12 执行的 test-only CreateProcessAsUserW 组装：创建时指定 Job 和 stdio handle list；只继承私有 stdin reader 与输出文件，不继承 release writer；保留原环境组装、命令行转换和三个 creation flags。生产 LaunchDesktop 对 zero restricting SIDs 的有意拒绝完全不变。

原 `matrix_script` 的返回字符串照旧写入原文件，新 owned 文件在其完整字节前加 fail-closed gate。门闩先清空变量；EOF 或非固定串均 exit 87，不能进入原删除脚本。父进程先打开实际 child primary token，完整核对原有 identity/privilege record 后才写固定 release。对 helper 的新内容核对，与脚本真实开始执行的日志 marker 分开检查。

原 host `/d /c` 参数和 inherited cwd 保留；原 overrides 按 Windows key 不区分大小写的规则覆盖 inherited environment。未更改全局环境。原矩阵脚本里的 del/rmdir、每格顺序和 MATRIX marker 不变。退出后转回 ExitStatus，继续执行原 `status.code()==Some(0)` 与原物理断言。

成功 CreateProcessAsUserW 后立即以 owned process/thread handles + Job 接管，中间无 fallible gap。work closure 的任何错误都会先关闭 release writer、终止 owned Job、等待并查询 active count；只有 cleanup wait 为 WAIT_OBJECT_0 且 active=0，才能标记 cleaned、返回给原物理 oracle。panic/提前返回还保留原 v3 Drop 的终止/等待后备。create 之前的任何错误只释放本函数已持有的对象，没有 child 句柄悬空窗口。

## 预算事实与校正

根最初引用了更早 `.status()` 无局部 deadline 的版本。重新完整读取实际 d851 preimage 后，确认当前已有 `.spawn()`、`WaitForSingleObject(..., 5_000)` 和 timeout 下 `child.kill()/child.wait()`；根已接受以实际原件校正。这个历史校正原样记录，不继续传播“原来没有 deadline”。

候选保留 **5,000 ms work wait**，采用 v3 的 **5,000 ms Job cleanup wait**，异常 Drop 也沿用其 5,000 ms 后备。新 gate/Job 是新的准备和清理控制，不把它冒充原 host 已有设施；也不声称 Win32 API 本身新增了完整壁钟 deadline。原 strict 部分的 5,000 ms spawn budget 和 10 s collector budget 全字节不变。没有扩大原测试的选择、重试或 CI timeout。

## 验证与仍需观察的风险

`verify_candidate.py` 离线 exit 0、stderr 0；完整 stdout 106,616 字节、SHA-256 `154869e18a72187e3e93acdd5fc15fe8e9fdab9ceefecdedcfeb7c53ad3881a4`。它独立重算原树与候选树，检查实际 published parent/merge，原 host 断言、两个 strict halves、matrix_script、case roster、模块 cfg、所有机械复制块、gate 顺序和原 native12 样本。

机械来源：8c 的 TokenBuffer/token_record/effective_record 整块，以及 OwnedChild/Drop/spawn_observation_child 整块，逐字节复制；fc9 的 TokenState/token_state 整块也相等。support Handle 只收窄可见性，其 Drop body 不变。这里有意不抽改刚取得原生证据的 8c/fc9，避免扩大此切片；复制依据、精确 SHA 和范围均在 mechanical-origin 与 static stdout 中。

这不等于 compiler 或 native 证明。新 helper 在当前测试宿主是否编译并通过 gate，仍需原 Windows 运行证明；API 调用若改变 actual child privilege record，会在 gate 处失败，不会放宽比较。两个原测试先前可能在 host 前提处结束，这次可能首次到达更深 strict 断言，因此不能预报 FAIL 数下降，也不能将更深失败改为接受或 skip。生产 strict outside-delete 的机制缺口继续单列 OPEN。
