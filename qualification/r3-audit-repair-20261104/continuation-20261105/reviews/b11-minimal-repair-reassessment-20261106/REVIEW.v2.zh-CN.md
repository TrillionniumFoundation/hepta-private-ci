# B11 最小修复切口复核 V2：现成 helper 与历史 MIC 物理反证

**最终判定：B11 继续 OPEN。现成文件 helper 能处理显式请求，但固定调用链没有把原 raw-token / 任意 native child 的文件操作强制接入该授权入口；单独降为 Low 也已有同级外部删除的历史物理反证。没有找到保持原合同、已足以交付的最小产品修复。这个判断不等于所有 Windows token/API 手段不可能。**

本 V2 原字节保留 V1 的调用链分析，另在末尾并入 MIC 补充审查。补充是对已有 native10/11 原件的完整恢复与重读，**不是新增 native**。V1 原文、旧便携包及旧 stdout 不改；本版额外明确 Low→Medium 与 Low→另一个 Low cohort 的差别，以及尚未验证的未重标允许根、正常管道/desktop、继承句柄和后代兼容性。

注释候选继续独立保留，不加入正在运行的 ac18。普通可逆注释纠正不要求额外用户审批。只有具体机制需更改原执行/权限边界时，才适用原 B11 literal exit 的“需要超出已允许边界时明确升级审批”；本次没有安排或批准重标外部 SACL、新驱动、受限 API 替代任意 native 执行等扩展。

## V1 固定调用链分析（保留）

**结论：没有发现能在原严格 token、ambient read、合法根内 I/O、四类根外变更拒绝与原后代寿命合同内，直接接入的最小产品修复。B11 保持 OPEN。此次新增了一个具体区分：仓库确有请求级文件 helper、Windows 句柄传递和 no-follow 文件 API；缺少的是让原线程 impersonation 与任意原生子程序必须经过该授权路径的强制连接。不能把“有文件 helper”或“已路由 elevated”升级成这层连接已经存在。**

本结论只覆盖固定源码中已追踪的调用链，不是所有 Windows API 的不可能性证明。本次没有运行 Rust、formatter、Cargo、Bazel、产品测试、Windows native，未查 CI 或私有容量，未改 ref、PR、生产源或原 23 条退出条件。另附一个独立的注释 postimage，供以后审阅；它没有进入正在执行的整合源，也不修复 B11。

## 1. 固定来源与资格边界

本次把保留的完整源文件绑定到冻结的 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359`，再与已发布整合 head `2d1137b1ba39fab0e6a28bac8decc114dfa0138c` / tree `99a9c0cefa627290c9fc72a9ba90d0485020fe11` 对照。两份完整树均重新计算全部目录对象与根。Windows package 的 74 个叶中只有 `setup_error.rs` 与 `bin/setup_main/win.rs` 改变；其余 72 叶保持。新增取回的 8 份 exec-server/sandboxing/Job 固定源也逐字节符合这两个树。`SOURCE_BINDINGS.json` 共列 83 个来源文件，包含支持文件，不表示人工逐行审读了 83 个文件的全部功能。[S1]

源包里的 Cargo.lock 和两个 setup 文件明确保留为 **67 的前像**，不是声称它们是当前整合后的版本。本文的 token、ACL、runner、IPC、handle 与文件 helper 推理均绑定实际未变的对应叶。setup 原因链改进不是 token/ACL 修复，不能转授删除隔离资格。[S1]

历史原生事实仍取自已实际登记的 native13：source `daa21e7a6a9b19e74b61c6bbdc2c813f9fd35a42`，checkout `f8e97e161c7ad87bd1e242363901a0852170483c`，tree `fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae`，run `42140578464` / job `127639593751`，whole **147 通过、7 失败、2 忽略**。本次完整 GET 既有机制 registry、review、facts、source bindings 与两份官方材料，逐字节核对实际 Git 身份；没有重新宣称执行该原生目标，也没有把 whole 结果写成 #4936 的测试结果。[S2]

在 native13 与 67/99a 的对照中，19 份选中完整文件相同；`token.rs` 的差异仅为 native13 追加一个 `cfg(test)` 诊断模块，原生产文件是它的逐字节前缀。原 Rust strict 后半部、legacy strict 后半部及完整 `matrix_script` 也逐字节相同。宿主 ACL 控制的差异单列保留；不能把 native13 的测试前提修正视作已合入 99a。[S1][S2]

原 B11 退出条件保持原文：

> 在获准的修复范围内提供原生 helper 与原严格 token 契约，原攻击/权限/文件系统用例全部通过；需要超出已允许边界时明确升级审批。

固定台账仍为 **16 CLOSED_SCOPED / 6 OPEN / 1 SCIENTIFIC_HOLD**。本次无关闭项。[S3]

## 2. 现成能力逐项追到实际执行端

| 现成入口 | 实际调用链与能力 | 为什么尚不能接成原 B11 修复 |
|---|---|---|
| strict token | `create_workspace_write_token_with_caps_from → create_token_with_caps_from → CreateRestrictedToken`，参数为 base token 与 SID 集，返回 token HANDLE | 没有每个对象、操作或根句柄的授权回调。原测试拿到 HANDLE 后在宿主线程 impersonate，直接调用 `std::fs`；不经过 launcher 或 exec-server helper。 |
| legacy 进程 | `prepare_legacy_session_security → apply_legacy_session_acl_rules → spawn_legacy_process → spawn_process_with_pipes/CreateProcessAsUserW` | ACL 准备只处理许可根和明确 carveout；CMD 的 `del/rmdir` 直接在子进程内执行。原测试调用公开 legacy 入口，不能靠高层选择器绕过它。 |
| elevated runner | `select_windows_sandbox_backend → prepare_elevated_spawn_context_for_permissions → spawn_runner_transport → command_runner::spawn_ipc_process → create_workspace_write_token_with_caps_and_user_from → spawn_process_with_pipes/ConPTY` | 有专用账户、setup/refresh、token 与 ACL 运行边界；没有每次文件操作的强制代理。所用 token 仍进入同一家族工厂。 |
| runner IPC | 完整 `Message` enum 为 SpawnRequest、SpawnReady、Output、Stdin、CloseStdin、Resize、Exit、Error、Terminate | 这是启动与 I/O 控制通道；没有 filesystem operation 请求。增加一个 IPC variant 也不会自动拦截已有原生调用。 |
| exec-server 文件 API | `SandboxedFileSystem::remove → FileSystemSandboxRunner::run → FsHelperRequest::Remove → run_direct_request → DirectFileSystem::remove` | **这是实际存在的请求级文件服务**。调用者显式选择该 API，helper 在准备的 sandbox 内执行；不是任意 child 的 Win32/NT 文件调用必须经过的代理。 |
| 受控读取句柄 | `sandboxed_file_open::open_platform` 等待 helper 返回 `process_id/file_handle`，`DuplicateHandle(...DUPLICATE_SAME_ACCESS)` 取得其已打开句柄，再释放 helper | 可复用作显式 API 的资源交接。本次不扩大审计该 PID/handle handoff 的全部安全性；它没有替换 strict HANDLE，也不阻止原生进程自行打开新文件。不能据此构造猜测 PID 的新策略。 |
| no-follow 文件 API | `no_follow/windows.rs::open_handle` 调用 `NtCreateFile`，设置 `OBJ_DONT_REPARSE`；删除路径打开 DELETE handle 后调用 `SetFileInformationByHandle(FileDispositionInfo)` | 这是有效的对象访问部件。该函数接收绝对路径，`root_directory: 0`，自身不提供原 B11 的允许根策略/有效主体授权绑定；它仅作用于主动调用它的操作。换一组 API 名字并不能强制覆盖原 `std::fs` 与 CMD。 |
| Job 与启动句柄列表 | `ProcThreadAttributeList` 原子设置 Job、限定初始继承 stdio；`JobObject` 处理进程归属、终止和 `preserve_descendants` | 其实现没有文件路径/操作权限输入。正常 root exit 后原 legacy 与 runner 调用 `preserve_descendants`；不能用“root 退出就撤销所有后代”代替原寿命合同。 |

这些判断来自完整固定文件及其正向调用点，不是单靠全文搜索未命中。文件列表、blob 身份和可重放锚点见 `SOURCE_BINDINGS.json` 与 `verification-01.stdout.json`。[S1][S4]

现有 WFP 源的 filter layer 为 ALE connect/resource-assignment，条件为网络主体、协议、端口。它不是这条文件授权链里已经可用的文件操作过滤接口。没有据此提出新驱动或扩大部署。[S1]

## 3. 必须纠正的一处源码解释

`unified_exec/mod.rs`（固定 blob `c98f3e5d217ada48732e1686129806d0dd52169e`）把 elevated 描述为持有 “authoritative filesystem mediation boundary”，并说选择唯一能执行该文件系统策略的 backend。源码能证明的事实是：选择器把 write-capable/path-restricted 请求交给 elevated setup 与专用账户 runner，错误不会降级到 legacy；它不能证明逐对象删除授权已经闭合。[S1]

问题不是没有执行隔离或没有文件 API，而是该注释把 backend 选择与尚未资格的完整文件操作中介混在一起。它尤其不能推翻原 direct-token/legacy 入口的物理反例。

已提供 `comment-only.patch`、`comment-only-plan.json` 与 `comment-candidate-not-published/` 完整 postimage：仅替换这一段 doc comment，所有其它字节不变；computed postimage 为 `389258c039f38c40dc2f0cfd9c3722a4381206c6`，8,754 B。它明确描述 setup/runner 的实际职责以及路由本身不证明删除边界。没有改分支、参数、公开 API、错误处理、断言或调用顺序。**这只是可执行的源码解释纠正，不是 B11 产品修复，也没有自动加入当前整合 PR。**

## 4. 为什么已有小部件仍不能完成原合同

既有 native13 四格物理记录中，strict Rust 与 strict legacy 都是：Neither/TargetOnly 不删除；ParentOnly/Both 实际删除。对照的“删”是 retained handle 释放后的名字/对象后态，不以 CMD exit code 代替。两个普通 ACL 前提先通过，但 strict 工厂原本就使用 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`。再过滤宿主最大特权，不能解释成一次新的 strict 修复；亦不能把集合干预写成 SeRestore 单因果。[S2]

微软公开删除合同有目标 DELETE 与父 DELETE_CHILD 两条授权路线。公开 `CreateRestrictedToken` 合同说明完整 restricting 检查与普通 SID 检查必须都许可，WRITE_RESTRICTED 只用于写访问评价，restricting SID 的 Attributes 必须为零。这些公开参数没有给现有工厂提供“同一 broad SID 只恢复读、不恢复父删除”的逐权利掩码。本文不据 `FILE_GENERIC_WRITE` 映射推断内核私有算法，也不把一个 Windows build 的观察扩大到所有文件系统。[M1][M2]

| 可能的小改动 | 保留原合同所遇到的准确缺口 |
|---|---|
| 只移除 WRITE_RESTRICTED | 完整 restricting 检查也作用于读取。现有工厂没有为原 ambient read、加载器、IPC 与全部已有对象建立统一的独立 read capability 授权；有限 read-SID 夹具不构成全合同接受。 |
| 加回 Everyone、Logon 或用户 SID 来恢复读取 | 同一 SID 的已有 ACE 可能同时包含 DELETE/DELETE_CHILD；SID 集不能表达该 SID 仅限读。不能把匹配 broad ACE 当作读权限专用恢复。 |
| 调整现有 root allow mask/default DACL | `acl.rs` 已有去掉显式 FILE_DELETE_CHILD、改给子项 DELETE 的 WRITE_ALLOW_MASK 维护，能处理本模块写过的 root ACE。失败矩阵的外部父目录仍可由其它身份 ACE 授权；default DACL 只作用于后续新对象，不能改写任意既有外部父对象。 |
| 给已知外部父目录加 deny 或持有禁止删除的 handle | 只能覆盖明确列出的对象。需要所有既有/未来父目录、别名、重解析和后代寿命上的持续权限，不是当前有限 ACL 准备的参数集合；广泛改外部/受保护 ACL 又超出本轮允许边界。 |
| 用 elevated 或现有文件 helper 替代 direct legacy | 能改请求路径，不能修复原 raw-token HANDLE 的授权行为。把原 native commands 改成只能调用受控 API，也改变了原执行合同。 |
| 只用 Job、私有 desktop 或启动检查 | 这些现成实现控制进程和 UI/句柄生命周期，不会对未来每一次文件变更作允许根判断；原 desktop 零 restricting SID 拒绝仍应保持。 |

以上指出的是未满足接受门的机制差距，不声称每个替代设计都不可实现。特别是 no-follow、typed request 与 owned handle 可以作为将来实现的构件；缺的不是再包装一次调用，而是把它们接成无法由原生调用绕过、并覆盖有效线程身份与后代寿命的边界。[S1][S4]

## 5. 下一步能做什么，哪些决定不能冒充已完成

**本轮可交付的最小候选只有上述注释纠正。** 没有提交一个已证明保持原合同的 token/ACL 产品 postimage，不应为了让 B11 消失而制造 flag 变化、有限 fixture deny、blanket error、测试 skip 或改断言。

若实现方认为已有获准的强制机制可以复用，下一份候选至少必须给出：实际 API/组件及固定版本；在对象解析后、变更前的授权位置；目标 DELETE 和父 DELETE_CHILD 两条路线；对 effective thread token、复制/派生 token 与已开句柄的主体绑定；对正常 root exit 后仍存活的合法后代的策略寿命；保留 ambient read/loader/IPC 与允许根内 I/O 的依据。现成 helper 可用于 typed request/对象句柄操作，但不能省略“任意原生调用为何无法绕过”的说明。拿到这组真实输入后，才有依据限定源码 patch 与原生验收。

如果实际方案需要改成显式 read-root/受控文件 API 执行合同，或部署一个当前树没有的强制执行层、重写广泛外部 ACL，那是执行边界与权限决策，不是本轮已授权的小修。应先明确与原 B11 条件的关系及需决策的范围；本文没有批准/安排该变化，更没有把条件改窄后登记为关闭。

这里的限制来自根本轮明确的只读/原权限边界要求、原 B11 退出条件及固定源码缺口。`AGENTS.md` 仍允许正常 owner-authorized 实施/PR；没有从旧助手未恢复的“审批拒绝”叙述推导永久禁令。本文也没有在没有具体可实施方案时向用户重复索要抽象许可。[S3][S5]

继续保留原 4 正控、物理负控、精确恢复、21 helper/11 pins、native13 的 3 strict 失败与 4 后续 poison；一个注释修正或独立 setup 原因链改善都不重写这些结果。本文不额外触发 token 诊断轮次。

## 6. 未知项与复验范围

未知项仍包括：其它尚未提供的、已获准部署的 Windows 强制组件；其有效主体与对象标识契约；全部 ambient read/加载器对象的独立读授权；所有实际 Windows build/文件系统组合；新整合 head 的完整原生结果。没有把静态调用链缺少某个钩子写成全平台不可能，也没有把 native13 单次观察转授给新 head。

`python verify_scope.py <解包目录>` 只读复算两份完整 Merkle 树、83 个来源文件的字节身份、完整 GET 回执、native13/base/current 的严格后半部关系、两个枚举与正向调用点、原退出条件/台账和单段注释候选。它不执行产品，不构成新的测试或安全资格。初次结果为 exit 0、空 stderr；完整 stdout 保留。

### 固定依据

- [S1] `SOURCE_BINDINGS.json`、`authority/base67-full-tree.json`、`authority/integration99a-full-tree.json`、`source/`。原 token blob `8945d75fe172679479b738e6266cac99a6f7ed16`；native13 token blob `b22acb5556f6af3b4c250a2441f161ee448ea1c1`。
- [S2] 既有 registry `d02d479eb67476953e9c22a82382f25748fb0b99`，review `600e48022d5a915f259b44f3b63b01c2e2679c1b`，facts `829eb0b9faefa431b107209d548b07827031d88f`，bindings `6fd1ae9b799540965da63864b6248b98629320e6`。完整 fresh GET 保存在 `recovered/`；原 native13 registry 为 `6cd5476632a6e90d930a5f1c8a245c10150ea840`，root acceptance `93e23f06979ae5879ff07d1be8c45574f98bb262`，本次没有重新下载其整套大原件。
- [S3] `authority/ledger-fixed.json`，冻结 23 项及原 B11 条件，只读未改。
- [S4] 固定 `fs_sandbox.rs` `ca715ef44ed7c30e4da11149dcc2cf8248c67ab3`；`fs_helper.rs` `ad6eacf93cfda03b223c197f7c79c2dac1ec0fe4`；`sandboxed_file_system.rs` `61c3c061267bb79b8fc2eef490501190dece8d0a`；`sandboxed_file_open.rs` `93c78706a472d882908e124117cc0a9e94057ca3`；`no_follow/windows.rs` `14a3db30a9feb76cb0fe22ea7e07951d999957c9`；Job `b06035f72d227b4069da677e8104617ae5616283`。完整 GET 与源字节均在包内。
- [S5] `source/AGENTS.md`，blob `a22ff3bee70261f6061d598c31f0016e785a7a3c`。相关路径没有更深的 AGENTS 叶。
- [M1] [Microsoft CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)，固定原返回 `ee76e348897b7612fa88c13102f7ec0a144e7a6d`。
- [M2] [Microsoft DeleteFile](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-deletefile)，固定原返回 `3ea1191f92b502b8efff5ab116b7ccdebf4733d2`。两份原返回也含相邻权利/MIC/Job 官方页面；它们是已有工具返回全文，不是新抓取或 HTTP wire capture。


---

## B11 MIC 补充审查：单独降低完整性级别是否遗漏了最小修复

**限定结论：生产 token 工厂没有显式降低完整性级别；已有 test-only Low 干预确实执行过，并在原线程 impersonation / fresh-path I/O 下留下了物理反例。Low token 能拒绝 Medium 外部对象的四类变更，却仍删除另一个 Low capability cohort 的外部文件和目录。因此，只把现有 token 降为 Low，不能闭合原 B11 的全部外部变更合同。这个结论不依赖“没找到 broker”的推断，也不是所有 token/API 组合不可行的证明。B11 保持 OPEN。**

本补充只读恢复已实际登记的历史原件，未启动 native、CI、私有容量、产品测试或工具链，未更改 token、权限、allowlist、测试、ref、PR、台账或已冻结报告。它与 V1 文件 helper 调用链审查一同构成最终 V2 审查；V1 原文和第一次便携恢复原件保持不变。99a 是本次固定的整合源码比较锚，不是对后续 ac18 格式化源的最新运行声明。

### 1. 生产工厂与历史干预分别做了什么

固定生产 `token.rs` 为 blob `8945d75fe172679479b738e6266cac99a6f7ed16`。工厂实际调用 `CreateRestrictedToken`，flags 为 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`；另设置 default DACL 并启用 `SeChangeNotifyPrivilege`。该文件唯一真正的 `SetTokenInformation` 调用设置的是 `TokenDefaultDacl`，没有 `TokenIntegrityLevel` 或 `TokenMandatoryPolicy` setter；已纳入来源清单的固定 Windows Rust 文件也没有其它这样的 setter。这只说明本仓库工厂的显式行为，不据此推断任意输入 token 的输出 IL。[S1]

历史探针 `token_integrity_probe_tests.rs`（实际 blob `fc9faa6d47ac5fdefa216affceb51a586f8e6b81`）先用同一个生产工厂和 cap_a 构造 token，再在 test-only 路径调用 `SetTokenInformation(TokenIntegrityLevel)`，设置 SID `S-1-16-4096`。它没有替换生产 flags。随后通过 `ImpersonateLoggedOnUser` 进入原线程，在执行文件操作前打开实际 thread token 查询状态，最后用原路径进行读、覆盖、新建、删除文件、删除目录。[S2]

native11 的完整原 token 行分别记录 host/current_strict 的 RID 为 12288，current_strict_low 为 4096；三者记录的 integrity attributes 为 96，mandatory policy 为 3。本补充保留数值，不擅自扩展其语义。Low 两行的 expected 与 effective 状态相等，仅覆盖 **RID、integrity attributes、mandatory policy 三字段**；它不是 user/groups/privileges 等完整 token 身份一致的证明。[N1]

### 2. 已执行的四操作及物理后态

主证据使用 native11 job `127606676952`。固定来源 authority 为 head `2980fa274c599bd07437a2f5915b86d858f89bcc`、checkout `53766cb836b198e2f928b949f148d7a2a10c0d21`、tree `9cb7302777ce018dd022086041c2225d1dd5c8dd`。这条来源关系来自既有登记包的固定 authority/source-map；本次重新计算完整树、核对其 14 份完整来源和探针/support 的实际 blob，没有重新读取 CI 或执行 Windows。[S2]

| 原件位置 | Low → Medium 外部对象 | Low → 另一个 Low cohort 外部对象 |
|---|---|---|
| 完整 row JSON 行 | native11 原 log 第 408 行 | native11 原 log 第 434 行 |
| 实际线程查询 | RID4096、attrs96、policy3 | RID4096、attrs96、policy3 |
| 覆盖 / 新建 | 均 PermissionDenied / Win32 5 | 均 PermissionDenied / Win32 5 |
| 删除文件 / 删除目录 | 均 PermissionDenied / Win32 5 | 两项返回成功 |
| 完整 finalized JSON 行 | 第 412 行 | 第 438 行 |
| 关闭观察句柄后的外部名称 | 文件、目录仍存在 | 文件、目录均不存在，NotFound / Win32 2 |
| retained 对象状态 | 外部五对象 pending0、links1 | 被删文件与目录 pending1、links0，其余外部对象仍在 |
| 外部对象实际 label | `S:(ML;;NW;;;ME)` | `S:(ML;;NW;;;LW)` |

两行中的外部读取均成功且内容为 original；覆盖失败后的内容仍为 original，新文件仍不存在。两行的 inside 控制也都完成了四项操作，但 **inside 父目录和四个对象都被探针显式标为 Low**。outside 使用不同的 cap_b；父级原有 broad logon/Everyone 许可并没有替换成人工 deny 来制造通过。[N1][S2]

这不只是 API 返回值或 AccessCheck 预测。support 的观察 handle 只持 READ_CONTROL、WRITE_OWNER、FILE_READ_ATTRIBUTES，不持 DELETE；它验证 handle 不可继承，并开启 FILE_SHARE_DELETE。实际变更使用 fresh path opens。完成时核对同一个对象 identity 与安全描述符，记录 DeletePending/NumberOfLinks，恢复幸存对象的原 label，然后关闭观察句柄，再按名称打开/检查对象。因此，Low→Low 的 pending1/links0 与最终名称消失共同构成物理删除反例。[S2][N1]

native10 job `127584591851` 的既有完整 log/XML 也恢复并核对：Low→Medium 的 row408/finalized433，与 Low→Low 的 row456/finalized460，呈现相同结果。本补充把它保留为另一轮原始观察，不把 native11 的完整 source authority 擅自赋给 native10。[N2]

### 3. 可以排除什么，仍不能排除什么

**可以排除“在其它机制不变的前提下，只降低现有 token 到 Low 即足以满足原合同”这一方案。** 原合同要求所有根外四类变更拒绝，不能只覆盖较高 IL 的对象。已有同级 Low、不同 cap cohort 的外部删除反例已经违反这一要求；无需新增一轮测试来重复发现它。

微软现有 MIC 官方原件说明，MIC 在 DACL 前评估，较低 IL 对较高 IL 的写入受限；未显式标记的对象按 Medium 处理。由此推断，若把 token 降到 Low，却保持普通 Medium/未标记允许根不变，就存在合法根内写入被拒绝的具体兼容性风险。**这是由官方合同与当前候选结构作出的推论，本次没有把它登记成新的生产失败。** 历史探针为了研究机制，主动把 inside 标 Low，所以它的 inside PASS 无法消除这一风险。[M1][S2]

| 备选 / 兼容性事项 | 当前证据状态与必要边界 |
|---|---|
| Low token 的 raw-thread 文件操作 | 已实际观察；只含上表固定夹具和三字段 TokenState 查询。 |
| 不重标现有允许根的正常 I/O | **UNKNOWN**。本 probe inside 人为标 Low；未接受原始 Medium/未标记根的完整正控。 |
| loader、正常管道、desktop、ConPTY | **UNKNOWN**。没有用上述两条 Low row 证明这些路径可用。 |
| 继承句柄、复制/派生 token、已开句柄、任意 child 与正常后代寿命 | **UNKNOWN**。原八行 phase 明确 descendants_spawned=0，观察 handle 本身不可继承。后续 Neither 模块是另一阶段，不能用它替代 Low 进程/后代资格。 |
| 更低的 Untrusted、改 mandatory policy、多个机制组合 | **UNKNOWN**。未提出或执行这样的完整候选；没有全平台不可能性结论。 |
| 重标所有允许根 / 修改外部 SACL | 这是新增对象权限操作，不能由这次只读审查授权；即使允许根标 Low，也没有解决已观察到的 Low 外部 cohort 删除。 |
| 现成 FsHelper、no-follow 与 handle handoff | 确实存在，但仍是显式请求入口；没有据此证明原 raw-token / 任意 native child 的操作必经它。详见 V1/V2 调用链审查。 |

若未来出现保留原合同的具体组合候选，应明确 token 的实际 IL/policy、已开与继承对象、允许根及所有目标对象的授权规则，并在原断言、预算、后代合同不变的条件下取得对应原生证据。此处只是说明尚缺哪些证据，没有安排新的诊断轮次，更没有将未经执行的候选视为已通过。

### 4. 恢复、不可解析记录与资格限制

完整历史包来自 actual registry `37c1d61dd84102158caaa2d5801345639334c8bc`。本次完整 GET 两个原 base64 blob `6d2e9ffd69f0b3b23605cb532f379c5fb467811c` 和 `026913ec2128ee45ae7c914226b79dae4891cb15`，恢复 gzip 599,347 B、SHA256 `a90cb14087ee364f8f6c0fec1ad40fa442e4434b5598acee52b973a5079e2d21`。41 个归档成员共 3,882,455 B，逐一与实际 manifest `bb8b6b10a9f325396e35a336ac592b4cc1485669` 的字节数、Git blob、SHA256 和 mode 相等。原 native10/11 log/XML 都包含在其中。[C1]

解析器只接受从行首开始、整行能作为一个 JSON 解码的 row/restoration/finalized 记录；没有拼接被其它测试输出打断的行。按这个明确规则，native10 完整计数为 7/5/6，另有 6 条不可用 marker 行；native11 为 7/8/8，另有 1 条不可用 marker 行。这是 **该解析规则的记录数**，不是新增用例分母或全阶段通过率。实际选中的 native11 两条 Low row、对应 restoration 和 finalized 全部完整，restoration 对象与 finalized 对象逐项相同。完整 raw 及不可用行身份均保留。[C1]

此前尝试将 native13 的一个归档成员计算 hash 当成 standalone Git blob GET，得到 404；失败原件保存在 `fetches-01.original.json`。该失败未被重写成成功，也不作为本补充原 log 证据。最终使用的是已注册历史包完整恢复的 native10/11 原件。原 native13 机制结论仍由 V1 固定来源单列保留。[C1]

最终离线入口为：

```text
python mic-addendum/verify_mic.py <解包根目录>
```

它恢复/验证旧归档全部 41 成员、重算 9cb 全树、核 14 份固定来源、生产和 test-only token 差异、两次完整原 log/XML，以及选中物理记录。最终 `verification-02.stdout.json` 对应 exit0、空 stderr；此前第一次成功输出也保留，第二次仅增补观察 handle 锚点、restoration 对象对等检查和三字段边界。它不运行产品或原生代码。独立同事窄读上述四条原 JSON 和 probe/support 实现后确认这个限定结论，意见全文单独保留；不把该意见扩展成新的产品资格。[C2]

#### 固定来源

- [S1] `../SOURCE_BINDINGS.json`、`../source/codex-rs/windows-sandbox-rs/src/token.rs`、两份完整固定树。当前源比较锚为 67 与 99a；不声称新 head native 结果。
- [S2] `probe-tests.rs`、`probe-support.rs` 及 `probe-source-fetches.original.json`；旧包的 `v3/source-map.json` 与完整 9cb tree。生产文件在 native token blob `b22acb5556f6af3b4c250a2441f161ee448ea1c1` 中是完整前缀，差异只为 cfg(test) 模块追加。
- [N1] `native11.test.log.original`、`native11.test.xml.original`，完整身份和逐行身份在 `verification-02.stdout.json`。
- [N2] `native10.test.log.original`、`native10.test.xml.original`，仅保留其实际历史观测范围。
- [C1] `prior-strict-registry.original.json`、两份 `archive-part-*.GET.original.json`、`archive-member-manifest.GET.original.json`、完整失败/成功 GET 原返回。工具返回不是 HTTP wire capture。
- [C2] `verify_mic.py`、两次 stdout/stderr、`peer-review-message.json`。
- [M1] [Microsoft Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)，已固定于 `../recovered/microsoft_primary_1.original.txt`，实际 blob `ee76e348897b7612fa88c13102f7ec0a144e7a6d`。本次使用既有完整原返回，没有另查新页。

