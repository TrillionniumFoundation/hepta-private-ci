# B11：普通主机 Neither 删除结果的受限诊断候选 v2

**状态：v2 已获独立静态接受并发布到诊断分支；本包没有新增编译、格式化或原生通过资格。B11 仍为 OPEN。**

v1 源码和实际登记 `ebe01d3d8dbbacbe2240ce4690fe38bc80fd02a4` 原样保留在上级目录。v2 只按独立审阅意见修正新观测模块的 cmd 环境与启动开关；原 probe 两处插入及其完整 postimage `fc9faa6d47ac5fdefa216affceb51a586f8e6b81` 不变。

## 原始问题与本候选的范围

native10 的原始运行是 `42124355402`，job `127584591851`，head `021a59ff05ccd963bc087918db823aa86af31bb8`，实际 checkout `5ce73498a9e8ee843d156c43593b1bc2fede416f`，tree `36ca349de7f4c7c5a2914cf1960a81d8621350fa`。完整原件已单独登记为 `6930d8ab9054f099c7e08dc6c791c1a670733dfc`，不能把它的执行结论移用于本候选。

原始整组仍是 147 通过、7 失败、2 忽略。严格边界用例在 `token_tests.rs:434:5` 记录了越界写入被拒绝而文件、目录删除成功。两个四格删除矩阵分别在 `token_tests.rs:479:5` 和 `unified_exec/delete_permission_tests.rs:69:9` 的普通主机 Neither 前置条件失败：应拒绝的文件和目录实际已删除。另四个失败在共享进程测试锁已污染时退出，没有到达各自隔离断言。原始 DACL、对象身份、删除后物理状态及错误码全部保留。

现有原件没有完整实际特权列表、操作线程的完整有效令牌、子进程实际主令牌和同一夹具卷的文件系统资料。因此不能断定 SeRestorePrivilege、保留句柄或某个文件系统机制就是原因。候选只补这些缺失事实，以及经过配对控制的特权干预；它不修复产品令牌、ACL 策略或严格边界断言。

## 两条源码路径

| 路径 | 变更 |
|---|---|
| `codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs` | 在原有模块内声明诊断子模块；原八行观测、所有断言、原完成标记和清理完成后，再调用新诊断。移除两个精确插入块后，整个文件恢复到实际原 blob `2a384792e8ba88518c26943716e8c3a39a523f9b`。 |
| `codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs` | 新建普通主机 Neither 因果观测模块，没有 `#[test]` 或 `#[ignore]`。 |

没有增加测试入口，原 `token::integrity_probe::integrity_mechanism_probe_observation_only` 名称保持不变。因此静态上保持 156 个库用例及四个 exact 正例各自 155 个 filtered out 的预期；这些不是候选原生实测计数。四个正例、物理反例、精确源码恢复、辅助目标、wrapper 参数、原生资源门槛和工作流预算均不改动。辅助目标原有 11 个源码 pin 不包含本次两条路径，因此不需要放宽或重写任何 pin。

## 五组配对观测

| 引擎与组别 | 实际操作令牌 | 用途 |
|---|---|---|
| Rust ordinary-direct | 当前进程令牌，确认线程未在模拟 | 保留直接普通主机基线。 |
| Rust ordinary-impersonated | 对普通主令牌调用现有 `ImpersonateLoggedOnUser`，在作用域内查询 `OpenThreadToken` | 与下一组使用相同模拟路径。 |
| Rust disabled-impersonated | 对仅设置 `DISABLE_MAX_PRIVILEGE` 得到的派生令牌进行相同模拟，并在作用域内查询 `OpenThreadToken` | 与前组比较实际特权差异；不把模拟方式差异误算为特权效果。 |
| cmd ordinary | 同一现有 `CreateProcessAsUserW` backend，普通主令牌 | 私有 stdin 门闩放行前查询实际子进程主令牌。 |
| cmd disabled | 同一 backend，派生主令牌 | 与前组保持启动方式和门闩一致。 |

每组使用独立、仅由测试创建的四格矩阵：Neither、TargetOnly、ParentOnly、Both。所有矩阵使用现有 `DeleteMatrix`，五组完整 DACL 字节须相同。它保留不带 DELETE 权限、不可继承的夹具句柄，检查对象身份、READONLY/reparse 状态、删除挂起/链接数、内容和原始 DACL 恢复。Rust 还核对每个文件可读，Rust/cmd 均以 Both 的实际文件与目录删除作为合法 I/O 正控制。Neither 结果只记录，不新增“必须拒绝”的诊断成功断言，也不改变原有产品与主机前置条件断言。

令牌记录包含用户 SID 和属性、完整组及属性、完整限制 SID、完整特权 LUID/名称/属性/启用位、完整性 RID/属性、mandatory policy、session、app-container 位、TokenType，以及模拟令牌的 ImpersonationLevel。两个 Rust 模拟组均须为实际线程令牌、`TokenImpersonation` 和 `SecurityImpersonation`；用户/组/限制 SID/完整性/策略等身份字段与各自主令牌须一致。普通主机进入和结束时都要求没有线程模拟，最终记录必须回到原始进程令牌。既有模拟 guard 在 `RevertToSelf` 失败时中止进程，不允许带残留模拟状态复用测试线程。

派生令牌只调用 `CreateRestrictedToken(..., DISABLE_MAX_PRIVILEGE, 0, NULL, 0, NULL, 0, NULL, ...)`。不对宿主令牌调用 `AdjustTokenPrivileges`，不增加 capability/restricting SID，不设置 LUA_TOKEN/WRITE_RESTRICTED，不改变标签或宿主 ACL。原令牌与派生令牌身份字段须相同，原限制 SID 列表须为空；派生令牌不得保留 SeChangeNotifyPrivilege 以外的已启用特权。输出保留完整实际差异；若普通令牌本就没有其他启用特权，这组数据不能支持“禁用特权导致变化”的因果结论。

## 实际子进程、卷与清理

两组 cmd 都使用当前 `process.rs`、`proc_thread_attr.rs` 和 `JobObject` 实现。原 backend 通过创建属性把新进程原子加入自己的 Job，继承列表仅含声明的 stdin/stdout/stderr。诊断保留父进程的私有写端并确认它不可继承；脚本必须从 stdin 读到精确释放串才执行任何 `del`/`rmdir`。父进程在放行前通过实际进程句柄查询主令牌，完整身份、特权和 TokenPrimary 与预期不一致时不放行。EOF 或错误字符串会退出，不能越过门闩。

v2 在新 cmd 的环境副本中，按 ASCII 大小写无关比较移除 `ERRORLEVEL`、`B11_RELEASE` 与将写入的八个 `MATRIX_FILE_i`/`MATRIX_DIR_i` 名称，再加入本次夹具值；其余继承环境和父进程环境不改动。cmd 明确使用 `/d /e:on /v:off /c`。这使动态错误级别不会被同名环境项遮蔽，`set /p` 的命令扩展开启，延迟展开关闭，避免注册表或默认值改变本次输入门闩和错误码观测。依据为 Microsoft 官方 [if](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/if)、[cmd](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd) 与 [set](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/set_1) 文档；这里只解释候选的控制条件，不是原生行为实测。

成功路径保留两个 cmd 的全部合并输出原始字节、每项退出码及实际物理后态。每次正常进程等待与清理等待分别为 5000ms；异常 Drop 还有一次 5000ms 的尽力清理。只有自身创建的进程和 Job 句柄会被等待/终止，不查找数字 PID、不枚举或终止其他宿主进程。成功完成必须看到 Job accounting 的 ActiveProcesses 为零，随后才能读取删除矩阵的物理后态。创建 API 本身没有新增总墙钟超时；原有 Bazel/工作流预算不变，异常清理失败不会获得成功资格。

`use_private_desktop=false` 保持现有 backend 的默认桌面路径；当前源码在此路径只读取限制 SID，并在非空时拒绝，不创建或改写桌面 ACL。现有 Job 的 breakaway 配置也保持不变；本候选执行的私有 cmd 脚本只有内建命令，不是针对恶意后代逃逸的验证，不能据此闭合产品的后代生命周期要求。

通过同一个保持打开的测试根目录句柄调用 `GetVolumeInformationByHandleW` 和 `GetFileInformationByHandleEx(FileIdInfo)`，输出实际文件系统名、flags、卷序列号和 128 位根对象身份。不会猜测 D: 的文件系统或把未观察到的卷特性当作原因。

原 `descendants_spawned=0` 完成标记只属于之前的八行观测；源码添加了明确说明。新阶段另有包含 `owned_child_processes=2` 的完成标记，不能把旧标记扩张到整个新增诊断。并行输出仍可能与其他用例交错，必须保存原始日志，不能修复或猜补破损 JSON 后宣称完整因果证据。

## 已完成验证与下一道门槛

`source-map.json` 绑定 12 份当前源文件的完整实际 Git blob GET；原件都与 native10 的实际合并 tree 对应。`full.patch` 仅含上述两条路径。`freeze-candidate.py` 在独立临时目录中完成 Git apply-check、apply、reverse-check 和 reverse，并逐字节比较前后完整源码；没有执行产品代码。相关 Windows API 名称及声明已与 Microsoft `windows-rs` 0.52.0 的四份完整模块源文件核对；当前 Cargo feature 配置和 Bazel `src/**/*.rs` 收集规则也已核对。

本地没有 Rust/Cargo/rustfmt/just，因此未声称完成 Rust 类型检查、格式化或原生执行。独立审阅已核对模拟配对、实际子令牌门闩、失败路径清理、原始 `DeleteMatrix` 物理后态及完整原源码保留，原始决定见 `independent-review/review.json`（实际 Git blob `a53e8141b1a62532a483f91cc2b7a6d84486f5fb`）。根随后发布诊断 head `2980fa274c599bd07437a2f5915b86d858f89bcc`；实际合并 commit `53766cb836b198e2f928b949f148d7a2a10c0d21` 与 head 共用 tree `9cb7302777ce018dd022086041c2225d1dd5c8dd`，原自动 workflow 为 native11 run `42130823627` / job `127606676952`。原生终态证据单独接续；初快照不能充当测试通过资格。当前 `native10` 的四正例、一物理反例和 21 用例辅助目标资格仍保持原范围，严格越界删除与主机 Neither 原因仍未闭合。

本包保留静态核对及首次 postimage GET 时的原始 PENDING 字段，二者早于独立审阅；后续接受状态以独立原始 review 与本包 manifest 为准。v1 原件和实际 registry 未被改写。
