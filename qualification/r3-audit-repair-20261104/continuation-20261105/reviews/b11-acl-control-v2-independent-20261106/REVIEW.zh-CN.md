# B11 host ACL 前提候选 v2：独立审阅

## 结论

**STATIC_ACCEPT_EXACT_V2，未发现阻断这一精确候选进入原 Windows 验证的源码问题。B11 继续 OPEN。** 这份结论只接受两个既有 host ACL 控制改用同一身份的非特权主体；没有把它认定为生产 strict sandbox 修复、编译通过、格式化通过或原生测试通过。

固定 parent source `87b8603f21e52063ed54ce89cba26756a3efaab7`，实际 tree `9a804c7b6e0dd554cdb435f41e06c5c689fffaaf`，既有实际 merge `09960fe697c9c181e4a7d624e29b49360877b687`。候选完整树独立计算为 `fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae`；本审没有创建提交或更新引用。

| 精确路径 | 独立实际 full GET 对象 | 字节 |
|---|---|---:|
| `codex-rs/windows-sandbox-rs/src/acl_control_test_support.rs` | `47baf88cf0a30521c3b2eb033dc3ee65056ed2f6` | 23135 |
| `codex-rs/windows-sandbox-rs/src/lib.rs` | `208e17fcedc894663b5eaa6dc2d2c5d1991967d7` | 30491 |
| `codex-rs/windows-sandbox-rs/src/token_tests.rs` | `ba51c9e5e30f0e614451c02c54b40a6ea40f9ada` | 23065 |
| `codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs` | `14a9cae9a7913ebc53a34ac3e1d3e038bc88d004` | 6152 |

四份对象都由本审独立读取完整正文，与候选文件逐字节比较；原始工具响应保存在 `full-GET-originals/`。没有复用候选作者的“GET 相等”布尔值作为独立证据。

## 实质审阅

已读完整 433 行 helper、两个实际调用点及后续原 strict 半部，并核对实际 `token.rs`、`desktop.rs`、`ProcThreadAttributeList`、环境/参数组装和此前 v3 donor 的真实实现。

`AclControl::new` 只在调用线程实际没有 impersonation token、其 effective record 等于当前进程 primary record 时开始。派生使用 `DISABLE_MAX_PRIVILEGE`，三个 SID/privilege 列表均为空；没有改变宿主 token、IL、DACL、capability 或生产构造 flags。派生 record 必须保持既有完整 identity 字段相同、restricting SID 列表为空、类型为 primary，且 enabled privilege 只能保留 ChangeNotify。此 record 的范围是源码明确查询的 user/groups/restricting SIDs/integrity/policy/session/AppContainer/type/全部 privilege 记录，不声称覆盖全部 Win32 token 信息类别。

Rust host 四格操作在同一同步 scope 中执行，没有 await、调度让出或子线程转交；进入后再次查询实际 thread token，核对 identity、全部 privilege record、TokenImpersonation 和 SecurityImpersonation。guard 在任何返回、错误或 panic 时 RevertToSelf；失败直接 abort，不能带着错误主体继续其他测试。正常路径在原 host 物理 readback 和 strict 构造之前再次验证普通 effective record 完整恢复。原 PermissionDenied/Win32 5、四格物理后态和 strict 后半部全部保留。

CMD 的真正 primary child 使用指定派生 token 创建。Job 和 stdio whitelist 在 CreateProcessAsUserW 创建参数中原子装配；成功后立即把 process/thread/Job 放进 OwnedChild，中间没有可失败操作。仅私有 stdin reader 与输出文件可继承，release writer 创建后立即 owned 并检查不可继承，且不在 handle list。调用失败先保存原 Win32 错误，生产 LaunchDesktop 对空 restricting SID 的拒绝没有被放宽。

child 在私有 stdin gate 等待时，父进程查询其真实 primary token；identity、完整 privilege record 和 TokenPrimary 均匹配后才写固定 release。EOF、未写入或不匹配输入使 gate 退出 87，不能进入原删除矩阵。局部 `setlocal EnableExtensions DisableDelayedExpansion` 约束 gate，随后 `endlocal` 恢复原矩阵的 ambient 模式；继承环境与 overrides 合并后清除所有 B11_RELEASE 大小写别名。原 `/d /c` 和整个 matrix_script 后缀保持，不向原矩阵附加 `/e:` 或 `/v:`。Microsoft 对 setlocal/endlocal 的局部模式与恢复语义、cmd 的 ambient 设置和 `/d` 含义提供直接依据：[setlocal](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/setlocal)、[cmd](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)。这两页本审已独立读取。

原 child work wait 仍为 5000 ms。每个 work Result 都关闭 release writer、终止 owned Job、等待至多 5000 ms 并查询 active process count，只有 WAIT_OBJECT_0、查询成功且 active=0 才能标记 cleaned 并返回原 oracle；未完成或中途失败仍走 Drop 后备。该后备失败不构成清理成功证据。新的准备/清理步骤不冒充原 host 已有控制，也不声称 Win32 调用本身具有整体壁钟上限。

## 独立机械证明

自己的 `verify_independent.py` 初次执行 exit 0，stderr 为空，完整结果在 `verification-01.stdout.json`。它不导入或调用候选作者的 verifier，不运行产品/native 程序。

- 对 parent 和候选所有 1571 个目录重新计算 Git Merkle hash；10589 个 parent leaves 变为 10590 个，只有新增 helper 和三个原叶变更。其余 10586 个 prior leaves 完全相同，无删除。
- 实际 published source/merge authority 均绑定 parent tree；12 份依赖源码字节各自与其原 tree leaf 相同。
- 在独立临时目录正向应用完整补丁，四个 postimage 完整相同；反向应用后只剩三个原文件，逐字节恢复，新增 helper 消失。
- 原 host 全部断言至文件末尾的 suffix、两 strict 半部、整个 matrix_script、函数/测试 roster 均逐字节不变。
- helper 的 TokenBuffer/token_record/effective_record、OwnedChild/Drop/spawn_observation_child 与实际 `8c16416` donor 相同；TokenState/token_state 与实际 `fc9faa6` donor 相同。
- 生产 `token.rs` / `desktop.rs`、原观察模块 `8c16416`、原 probe `fc9faa6` 在候选树中全部不变；没有改生产 privilege flags、原 strict 断言或原测试选择。

## 验收边界

原生 Windows 编译及实际 child gate、四格 host 物理后态、Job cleanup/active=0、两个后续 strict halves 仍必须由原测试验证。本次未执行 cargo、rustc、just test/fix/fmt、原生 driver、宿主资源查询、workflow dispatch/rerun/cancel 或 ref 更新。

候选可能让此前卡在 host Neither 的两个测试首次到达更深 strict 断言，不能预报 FAIL 数下降。既有 Job BREAKAWAY_OK 语义仍在；这里审查的是固定 owned matrix 脚本，不能外推为任意不可信后代隔离资格。CMD 输出 RC 与实际删除后态分开，原物理断言继续作为 oracle。没有把这份静态接受或此前 donor 的原生成功转移为新候选的运行成功。
