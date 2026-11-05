# B11：让 Full setup 等待本次 read ACL 阶段

## 当前结论

这是基于产品 `eed4d6bb61b789b19f60facc79f9e031765fa4c9`、树 `ca1c4671ef6b2773280d01b5d76c6166252f5856` 的独立静态候选。三个文件共 **96 行新增、92 行删除**；没有应用到产品、诊断分支或任何 native 工作树，没有编译或运行 Windows 测试。

本片使 Full setup 的成功返回包括**本次请求原有 read ACL 阶段的正常返回**，并把已存在但没有完成凭据的命名 mutex、阶段中记录的 ACL 错误变成失败。现有 read roots、权限掩码、SID、token flags、write/deny 规则都不变。这只是正常产品接线的一项前置修复，B11 整项仍为 OPEN。

补丁为 [read-readiness.patch](read-readiness.patch)，逐路径身份为 [source-map.json](source-map.json)，实际四次 Git check/apply/逆 check/逆 apply 收据为 [static-verification.json](static-verification.json)。完整范围与原门见 [manifest.json](manifest.json)。

## 已确认的实际调用链

`prepare_elevated_spawn_context_for_permissions` 与普通 elevated capture 路径调用 `require_logon_sandbox_creds`。该函数在必要时执行初次 setup，并且在返回凭据前总会执行当前 roots 的 Full refresh。外层 setup 确实等待 helper 退出。

缺口在 helper 内部：旧 `run_setup_full` 只查询全 session 的 `Local\CodexSandboxReadAcl` 是否存在；存在就跳过，不存在则启动 detached `ReadAclsOnly` 子进程后立即返回。`ReadAclsOnly` 自身在 mutex 已存在时也返回成功。因此，原 Full helper 退出 0、原 setup marker 存在，都不能证明本次 roots 的 read ACL 工作已经完成。它们也没有携带 read-root 集合哈希或每请求完成记录。

新 Full 在原 read 分支位置直接调用同一 `run_read_acl_only`。原 deny-read 阶段仍在其前，runtime/write/deny-write 阶段仍在其后；初次 marker 只有所有阶段正常返回后才提交。ReadAclsOnly 的 wire 枚举与独立入口保留。

| 路径 | 原行为 | 候选行为 |
|---|---|---|
| Full，read roots 非空 | detached child 启动或同名 mutex 存在即可继续 | 同步完成本次原 read 阶段，否则返回错误 |
| Full，read roots 为空 | 跳过 read child | 跳过 read 阶段 |
| 已存在的命名 mutex | 当前请求可能直接成功 | 关闭新打开的非 owner handle，带实际 OS 183 原因明确失败 |
| read 阶段累计错误 | child 的 refresh 模式失败，但 Full 不等待；显式非 refresh 模式还可能成功 | 原完整错误日志保留，初次与 refresh 均失败 |
| 同进程、完全相同 payload | 原 singleflight 共享同一结果 | 原实现不变，共享的结果现在包含同步 read 阶段 |

## 权限和操作范围

`apply_read_acls` 与 `read_mask_allows_or_log` 全文保持。仍只遍历原 payload roots；仍保留缺失路径跳过、Users/Authenticated Users/Everyone RX 快捷判断、sandbox group RX 判断；仍用原 sandbox group SID、`FILE_GENERIC_READ | FILE_GENERIC_EXECUTE`、`OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE` 执行原 ACL 调用。没有增加路径递归、root 扩张或读 SID。

初次 Full 的原 detached helper 由当前 setup executable 通过普通 `Command` 启动，没有指定新账号、token、工作目录或环境覆盖。现在在父 helper 中执行同一段工作；此源码依据支持保留该路径的执行账号与操作参数，但本轮没有动态 token 对照。refresh 仍使用原非提权 helper，初次提权规则也不变。

这些既有快捷判断并不证明新 full-restricting token 的 read SID 已获授权。缺失路径、并发路径替换、ACL 继承后的全树有效性、protected children、真实 loader 依赖与后代生命周期也未由本片解决。操作不是事务；发生错误时，先前 provisioning 或 ACL 变更可能已发生，候选不会伪称已回滚。

## 原等待与并发兼容性

没有增加任何 timeout、retry 或等待循环。原初次非提权路径与 refresh 都使用没有本地 timeout 的 `Command::status()`；原提权路径使用 `WaitForSingleObject(INFINITE)`；原 singleflight Condvar 也没有独立时限。同步 read 阶段会增加父 helper 的实际耗时，并继承这些**原本无界的外层等待限制**，不能称为有界就绪。

mutex 名称、session namespace、默认安全描述符和 guard 的 ReleaseMutex/CloseHandle 保持。存在对象不一定仍有 owner，更不代表本次请求完成；因此即使原 owner 已释放而另一个 handle 仍持有对象，候选也拒绝成功。不同 roots、不同进程的合法并发请求可能出现新的显式失败；本片没有可靠的跨进程完成记录来安全复用另一请求，不会将“曾存在”解释成 ready，也没有新增重试。现有同进程相同请求合并仅保持原覆盖范围。

## 控制与验收

唯一新增控制 `win::read_acl_mutex::tests::existing_read_acl_mutex_is_not_a_completion_receipt` 使用任务独占的临时目录名产生独立 Local mutex。它先实际持有 mutex，确认竞争 acquisition 返回带 OS 183 的错误；随后另开一个实际 handle，释放 owner，确认仍不能把保留的无 owner 对象当成完成凭据；最后关闭该 handle，确认可以重新创建并取得 owner。所有 handle 由原 guard 或 `OwnedHandle` 管理，全过程不触碰生产固定 mutex，不新增子进程或改环境。

该新测试通过现有 Windows-only setup binary 模块自动注册到：

`//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests`

原库目标 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests` **不会执行它**。专用 B11 probe 的原库 target 结果不能替代 setup binary 的资格。Cargo 原入口为 Windows 上的 `just test -p codex-windows-sandbox`，不能加 `--lib` 来声称覆盖 helper；Bazel 应沿原 Windows runner、配置、预算执行上述 helper 与原库 target，实际 catalog/日志再证明选择范围。

应保留原 setup completion、同 payload singleflight、错误报告、root selection 与 write-root refresh 控制，完整列表在 manifest。原 singleflight 的 5 秒 waiter 检查不变。新 mutex 控制只能证明其物理错误/释放合同，不能代替实际初次 Full、refresh、权限失败与并发调用验收。本轮不声称新控制、旧控制或端到端 read/loader 已通过。

## 固定依据

当前 helper `win.rs` preimage 为 `1d9340c6db26d6d10c1b3edecb1c9fecc908ef1d`，mutex preimage 为 `a96b6a502474a8bab3baa7842f36dfa814c9cc37`；已通过固定 eed 目录 API 与完整本地字节核对。新测试路径在该完整目录列表中不存在。Cargo、BUILD、defs 与 Windows main 入口亦绑定固定 eed。

Windows-sys 0.52 的原 `CreateMutexW`、`OpenMutexW`、`ReleaseMutex` 签名已逐字核对。Microsoft 的 [CreateMutexW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw) 文档明确区分新建 owner 与打开已存在对象、既有对象返回 ERROR_ALREADY_EXISTS、最后一个 handle 关闭才销毁；[ReleaseMutex](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-releasemutex) 文档要求调用线程实际持有 owner。这些 API 契约支持本控制的设计，仍不等于 Windows 实际执行结果。
