# Windows state EOF：固定源码可行性审阅

## 决定：REJECT_PUBLICATION

本包保留被拒草稿及其依据，**不构成修复资格，不关闭 blocker**。草稿用同目录文件锁覆盖 load → apply/revoke → store，保持原 JSON/schema、ACL 操作及错误传播。但 `.sandbox` 对 sandbox group 开放读、写、执行及 DELETE，而 `File::lock()` 可无限等待。有权打开锁文件的主体可以先占锁，新增无限阻塞 setup 的路径。已有 state 文件可被非合作写者干扰，不能成为引入这个新等待风险的理由。

根审明确拒绝发布该草稿。代码、两个 parent 回归和一个明确 ignored 的 owned-child helper 都**未编译、未执行、未格式化**。静态验证成功只证明文件身份及证据可重放。

## 原事件与源码身份

原 EOF 属于 PR #4913 head `340fbc0629d27e3a2bda7c6971be25c60b3bf2bc`，实际 checkout merge `ff2b873c8b907e1e86b1a728c2c18552edfbd0ed` / tree `78b817fec87e593e0a0f6357d84f895b8574bde5`；run `42158689226`、Windows job `127703396792`、Core shard 7 attempt 2。

完整原 attempt 日志（恢复包路径 `evidence/core-shard7-attempt2.original.log`） 为 178,284 字节，Git blob `b64d1e1e5d258084967dadb890210b9907b0c98c`。它与官方 artifact `13477083714` 的原 ZIP 成员逐字节一致；整个 ZIP SHA-256 为 `70569eff66484a837e89fbe012553bbda2244c11a432d33cdc41308f4b624707`。完整官方 ZIP、其他 attempts、compact 与原 API 由包内引用的既有原生 registry 保留。

`deny_read_acl_state.json` 的 EOF 被日志和 returned error 各呈现一次，代表**一次原事件**，不是两次。`SetSecurityInfo …: 5` 是另一个失败，不能由 EOF 解释。原行号、两类错误、成员与 source 身份在 native-eof-provenance.json（恢复包路径 `evidence/native-eof-provenance.json`）。没有实际 writer/PID/并发时序，因此原 EOF 的唯一根因仍未知。

该 native tree 相对固定 main67 仅更改 `setup_error.rs` 和 `bin/setup_main/win.rs` 的错误链报告；包内保存这两个实际 postimage 的全文 GET、commit/merge 原件，并复算完整树。state 原叶仍为 `fd073a4d45c781f0441839708f92e32d0831556c`。所有调查源码均与 base `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359` 的对应叶相等。

## 可以确认的机制

`load_state` 仅将 NotFound 视为空状态；空文件和损坏 JSON 均保留解析错误。`store_state` 完整序列化后直接 `std::fs::write`，存在打开并截断到完整写入之间的窗口。并发读取可能观察空/不完整内容，两个未串行化的读改写也可能丢失 SID 项。这是源码支持的机制，不能等同于已经解释原 EOF。写入中进程崩溃也能留下不完整文件，互斥锁本身不解决崩溃一致性。

对实际原 source archive 的全部 **4,832 份 Rust 文件**执行了两个精确字面搜索，结果完整保存于 full-archive-state-reference-search.json（恢复包路径 `full-archive-state-reference-search.json`）。已知 state 生产调用为 setup helper 一处、legacy ACL helper 两处，均进入同一函数；load/store 私有且只被该函数使用。Legacy 公开入口拒绝非空 deny-read overrides，preflight 则传空数组，不能据潜在调用点假定私有目录前提已成立。字面扫描不证明仓库外或旧二进制没有写者。

`ReadAclMutex` 只保护背景 read-grant helper。setup 在同步 state 之后才查询它并决定是否启动背景 helper；它不包围 state 事务。其 ERROR_ALREADY_EXISTS 路径直接跳过工作，也不能移植为“并发 state 更新成功”。

## 被拒草稿的限定内容

只有 `deny_read_state.rs` 和新增 `deny_read_state_tests.rs` 两路径变化。原 load/store、schema、apply/revoke 顺序及原测试字节全部保持。锁用非截断读写打开，禁 FILE_SHARE_DELETE，通过 OPEN_REPARSE_POINT 和句柄 metadata 拒绝重解析点/非普通文件，RAII 持有至函数退出。这可以说明合作调用者的串行化设计，并限制已打开锁叶的替换；它不证明锁对象可信，也不排除先占导致的无限等待。

未执行的回归草稿设计为：子进程的原生 try_lock 必须先报告 WouldBlock；父进程保持受锁的空状态窗口，写回完整 JSON 后才解锁；子进程随后读到完整状态并保留两个主体的更新。另验证解析错误释放、锁叶不可替换和目录负例。未执行的测试不能降低已确认的设计风险。

## 已核对的替代前提

| 机制 | 固定源码事实与限制 |
|---|---|
| `.sandbox-secrets` | 首次 provisioning 仅 create_dir_all、写 DPAPI 内容；完整 setup 到 state 同步之后才设置目录保护 ACL。不能在 state 入口先假定它已是稳定私有锁目录；refresh 入口也未验证一个锁对象的 owner/DACL。 |
| protected `setup_marker.json` | setup 开始前创建保护 DACL 的 marker，但 full setup 先删除再重建它，成功后新句柄原地写入。它不是永久锁身份，不能直接兼作 state 锁。 |
| setup singleflight | 进程内 Mutex/Condvar，按完整 payload 分组；不跨进程、不统一不同 payload，也没有生产 deadline。 |
| helper 等待 | refresh 和非提权 setup 用 Command.status；提权 setup 用 WaitForSingleObject(INFINITE)。不存在可直接传给 try_lock 的既有 setup 剩余预算。 |
| command timeout_ms | 在实际 child 的等待阶段才使用；setup Request/Payload 未携带 setup deadline。将其改为端到端预算会改变 None、UAC、首次 provisioning 等合同。 |
| 既有私有状态提交 | sandbox_users.json 和 setup_marker.json 均是序列化后 fs::write，不提供事务锁或崩溃原子提交。 |
| helper materialization | 固定67在 .sandbox-bin 暂存、继承目的目录 ACL，旧目标存在时先删除再 rename；它面向 helper 文件，不能作为保持 state 原 DACL 的严格原子替换。 |

这些结论限于包内固定调用链及初始化顺序，不宣称整个项目没有私有存储。已有私有目录和 marker 各有用途，但当前证据没有建立一个可直接覆盖首次/刷新 state 调用的稳定私有锁对象。

固定 tempfile 3.27 的 Windows persist 使用 MoveFileExW，并不自动合并被替换文件的原 DACL。ReplaceFileW 有属性/DACL 合并行为，但失败状态可能已改变文件名或移除原目标，且 WRITE_THROUGH 标志不受支持。因此直接替换成这些 API 也不能在本次受限范围内被视为合格修复。

## 下一阶段二选一的设计义务

1. **建立可信稳定锁对象。** 明确 owner 身份、首次建立、已有对象校验、不同进程/payload 共用、refresh/迁移及重解析边界。在任何 state mutation 之前成立，并证明 sandbox 主体无法先占。不能只给新对象传安全描述符，却信任已有对象；不能删除可能正在使用的锁文件。复用私有目录必须先解决初始化顺序和实际保护验证，不能扩大 ACL 授权。
2. **定义有界 setup deadline/cancellation。** 明确预算来源、覆盖阶段、None 的语义、UAC/首次 provisioning/refresh 兼容性，再把剩余预算与取消信号传到所有调用。try_lock 只能在该预算内等待；到期/取消必须保留错误，不能跳过 ACL 同步或将 WouldBlock 视为成功。验证正常并发成功、先占者不释放时有界失败、owned helper 清理与错误传播。不能凭空套用测试 5 秒或 CI 120 分钟。

两条路径都要保留原 EOF 负控、独立 ACL error 5、完整原平台断言。若随后修 crash consistency，应另行设计 DACL/属性保留、失败后的有效副本和持久化保证；本包没有混入该问题。

## Primary 与重放

固定全文 GET 在 primary/（恢复包路径 `primary/`）： [Rust 1.95 File](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/fs.rs)、[Windows 实现](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/sys/fs/windows.rs)、[Windows metadata](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/os/windows/fs.rs)、[windows-sys 0.52](https://github.com/microsoft/windows-rs/blob/0.52.0/crates/libs/sys/src/Windows/Win32/Storage/FileSystem/mod.rs)、[tempfile 3.27](https://github.com/Stebalien/tempfile/blob/v3.27.0/src/file/imp/windows.rs)。Microsoft 原页回执同时保留：[LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)、[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)、[ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew)。

`python verify_assessment.py --root <本目录>` 仅验证固定证据与被拒草稿身份、原函数保留、完整树、native 来源投影及正反补丁。成功结果仍明确输出 **REJECT_PUBLICATION**。

本文为冻结 README 的交付阅读版，仅把恢复包内相对链接改为路径说明；实际完整原 README 保留在 ZIP。
