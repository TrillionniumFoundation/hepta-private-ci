# B11 native13 后产品修复的窄范围可执行性审阅

**结论：B11 仍 OPEN；在当前生产接口与完整原合同内，没有找到可立即实施并接受的局部产品修补。native13 消除了宿主 ACL 对照的特权干扰，随后原严格测试实际走到 ParentOnly/Both 的物理删除失败；它没有引入新的文件 I/O 强制执行能力。停止扩展 token 诊断轮次。**

这是一份固定来源的可执行性判断，不是对所有 Windows API 的不可能性证明。没有改生产代码、原测试、参数、超时、过滤器或 ref；没有触发、重跑、取消 native，也没有新驱动、新平台或新权限部署计划。

## 1. 本次固定来源及已有独立核验

当前源码是 `daa21e7a6a9b19e74b61c6bbdc2c813f9fd35a42`，实际 checkout `f8e97e161c7ad87bd1e242363901a0852170483c`，tree `fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae`；原自动 run `42140578464`、job `127639593751`。全目标为 **147 通过、7 失败、2 忽略**，job 为 failure。正式 53 项证据 registry 是 `6cd5476632a6e90d930a5f1c8a245c10150ea840`，完整验证结果是 `af10ff6664344d3d8825dbdfc6ef3c6646a59a61`。

根审计独立读完整 verifier 并回放，269,320 B 结果逐字节相同；53 项本地原件、Git/SHA 摘要和实际登记回执均核对。新增根独立回执已单项 create + full GET，实际 blob `93e23f06979ae5879ff07d1be8c45574f98bb262`，36,347 B，SHA-256 `67402974b9c64cf057ffe0e24e8273feba7f2ba065956e971ab01e86f190155d`。本次没有改写该 53 项 registry。

既有机制独审 `research-audit/b11-strict-boundary-independent-20261106/REVIEW.zh-CN.md` 固定于 native11；实际 custody registry `37c1d61dd84102158caaa2d5801345639334c8bc`。本增量将相关完整源字节重新绑定当前实际 tree，并单独使用 native13 原件，未把旧独审冒充 native13 独审。

## 2. native13 增加了什么事实

下表中“删”均指原 retained-object 句柄释放之后的真实名字消失，文件和目录结果一致；不以 CMD 的 ERRORLEVEL 或“命令 exit 0”替代物理检查。

| 原矩阵路由 | 非特权普通 Rust / CMD 对照 | 原 strict Rust | 原 strict legacy CMD |
|---|---|---|---|
| Neither：目标拒绝 DELETE，父拒绝 DELETE_CHILD | 两者均拒绝，物理仍在 | 拒绝，物理仍在 | 拒绝，物理仍在 |
| TargetOnly：目标许可，父拒绝 DELETE_CHILD | 删 | 拒绝，物理仍在 | 拒绝，物理仍在 |
| ParentOnly：目标拒绝 DELETE，父许可 DELETE_CHILD | 删 | **删** | **删** |
| Both：两条路由均许可 | 删 | **删** | **删** |

四个矩阵 48 份原 retained-object 记录完整；每条路由、每类对象的实际 DACL 字节在四矩阵间相等。World SID 的目标 DENY DELETE 为 `0x10000`；父 DENY FILE_DELETE_CHILD 为 `0x40`。实际删除对象为 pending=1、links=0；未删目标和父目录为 pending=0、links=1。故不能用“Neither 未真正装 deny”解释该结果。

两个宿主前提已先通过，原 strict 构造器及参数保持不变，strict restricting membership 实际为 `[cap_a,cap_b,logon,everyone]=[true,true,false,false]`。Rust 原四份读取内容和允许根内删文件/目录断言在 `token_tests.rs:573` 的真实失败前已执行；legacy 允许删除断言在 `delete_permission_tests.rs:100` 的真实失败前已执行。这是绑定原控制流的推断，未虚构额外 raw read 收据。strict Rust 在 Neither/TargetOnly 得到双 OS error 5，在 ParentOnly/Both 返回成功并真实删除。

7 个失败现为 3 个真实 strict 断言和 4 个后续共享测试锁 poison。3 个 strict 失败分别是 broad-identity 原测试（434）、Rust 四格（573）、legacy 四格（100）。不能因宿主前提通过而为仍失败的原测试另加 PASS，也不能把 poison 的四例当作独立业务执行完成。

新 ACL_CONTROL 的 Rust token JSON 一行存在 stdout 交错，完整字节原样保存；actual token gate 的完成依据来自源码检查及其后的原断言位置。旧八行诊断也有交错记录，未拼接为完整 JSON。两项有限 CMD 对照的 actual primary token、输入 gate 和 owned Job 正常清理通过，均不授予任意加载器、后代或产品隔离资格。

## 3. 能够成立的机制判断与不能扩大之处

公开 Windows 文件删除合同允许目标 DELETE 或父 DELETE_CHILD 的授权路线。[M2] 当前实际矩阵把这两条路线分离：仅目标许可时 strict 拒绝；父许可时 strict 真删除。既有原八行完整 AccessCheck 对应同一 descriptor 的记录还显示 strict 的目标 DELETE 拒绝、父 `0x40` 许可。结合当前矩阵，可把产品故障准确定位为**允许根外父目录的删除子项路线没有被现有 capability 限制有效覆盖**。

生产 `token.rs` 的所有相关入口最终进入 `create_token_with_caps_from`。严格 legacy 工厂排除宽泛 Logon/Everyone restricting SID，但仍使用 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`。公开参数说明 WRITE_RESTRICTED 只在写访问评价中使用 restricting SID，而完整限制需要两次访问检查都许可；restricting SID 的 Attributes 必须为零。[M1] 该工厂实际只接收 token 和 SID 集，没有对象、根路径、操作类别或父子删除路线参数。

`FILE_GENERIC_WRITE` 官方映射没有列出 FILE_DELETE_CHILD，`0x40` 是单独的目录权限。[M3][M4] 这是解释边界的辅助材料，**不能仅凭这张映射表宣称已证明某 Windows 内核 build 对 WRITE_RESTRICTED 的私有位级算法**。没有内核调用栈，也不推断所有 Windows 文件系统和 build 行为相同。

普通宿主最大权限集合干预与 strict 故障是不同层次：前者修正了 Neither 对照，后者工厂原本就已禁用最大权限。旧实测没有单独隔离 SeRestore；本次不写成 SeRestore 单因果。

## 4. 为什么候选“小修”不能完成当前合同

| 候选改动 | 当前来源能支持的范围 | 不满足当前闭合门的原因 |
|---|---|---|
| 再禁用宿主权限 | native13 已用于普通 ACL 前提 | strict 工厂已禁用最大权限；新 strict 仍真实删 ParentOnly/Both |
| 仅去掉 WRITE_RESTRICTED | 旧 finite fixture 的独立 RX SID 对照能读并拒绝四变更 | 完整限制也检查读取；任意现有 ambient 文件、加载器与 IPC 没有该 read SID ACE，原 full-disk-read 合同不能据有限夹具推过 |
| 给完整限制加入 Everyone、Logon 或现有用户 SID | 可以重新匹配它们已有的 ACE | token 的 restricting SID 参数没有“只允许读”的权限掩码；同一宽泛 ACE 的父删除权限也会参与匹配，不能证明只有读取被恢复 |
| 把普通 SID 改为 deny-only | 可以取消其允许 ACE 的匹配 | 这是身份级变更，不是按对象根及操作权利裁切；依赖同 SID 的 ambient 读取亦会受影响；需全面 read 授权重建才可能讨论另一合同 |
| 仅降低完整性 | 旧实际 Low→Medium 对照能挡写删 | 同 Low、不同 capability 的外部对象仍被删；MIC 的完整性层级不等于允许根边界。[M5] |
| 调整 default DACL 或局部父 deny ACE | 可以影响新对象或明确拥有的已知对象 | default DACL 不会重写现有外部对象；当前接口没有完整 outside 对象集，不能把有限启动前 ACL 枚举当成之后所有对象的持续约束 |
| 改走 elevated runner、加启动检查或 Job | 源码已有启动、stdio、exit、取消和进程归属管理 | elevated 仍调用同一家族 token 工厂；IPC schema 没有逐次文件操作。Job 管理进程集合与生命周期，不能从现有实现推得按根的文件授权。[M6] |

以上拒绝的是把有限证据直接升级成当前产品闭合；没有否定显式 read-root 的完整限制模式作为不同合同的价值，也没有把该模式加入本任务或替换原 strict 断言。测试 skip、放宽错误类型、只查 AccessCheck、只查 exit 0、只做启动前检查或全面改变外部 ACL，均不能修复已证实的物理副作用。

## 5. 当前实现具体缺少哪一层

真实调用链是 `prepare_legacy_session_security → create_workspace_write_token_with_caps_from → create_token_with_caps_from → CreateProcessAsUser/线程 impersonation`，随后任意原生子程序直接操作文件系统。ACL 准备只处理许可根及显式保护路径。capture 与 unified legacy 都要求 full-disk read。elevated runner 的消息是 SpawnRequest/SpawnReady、Output/Stdin/CloseStdin、Resize、Exit/Error、Terminate；它不是强制的每次文件操作代理。

若保持当前 ambient read 和外部 ACL 不被广泛改写的合同，缺口位于**实际文件对象访问的授权执行层**：必须能在对象解析后、变更发生前，按真实主体与允许根判断所有原四种变更，覆盖目标 DELETE 和父 DELETE_CHILD 两条路径，并保持读取、加载器、IPC、允许根内 I/O。将这样的能力接入当前工厂需要一个实际存在、可部署且不能被原生调用绕过的执行边界；本次固定源码和已取得外部材料没有提供可直接复用并接受的实现。

身份和寿命也是原合同的一部分。raw-token 用例在宿主线程 impersonate，不能只绑 root PID。原 capture/legacy 在 root 正常退出后调用 `preserve_descendants`，原测试要求此后真实后代仍能合法写入完成标记；因此策略不能随 root exit 一并撤销。超时/取消仍须遵守原清理门。未来任何合格外部能力必须明确绑定有效线程身份、派生/复制 token、合法后代与打开的句柄，并处理真实对象身份和再解析竞态；这是一组准入要求，不是本次已经实现的技术方案。

**实际下一步**：保留 B11 OPEN 与全部原失败；由负责当前生产执行边界的实现方提供上述已有能力及固定版本接受材料后，再形成源码候选。当前可执行工作是收口准确证据和继续独立的原平台门，不再追加 token flag 试验。没有把“需要外部能力”登记成已解决，也没有申请/安排新驱动、新平台或擅自改变 ambient-read 合同。

## 6. 依据与可回放材料

`SOURCE_BINDINGS.json` 记录本次选中完整文件、当前 tree leaf、字节数与 SHA-256；`MECHANISM_FACTS.json` 仅从已冻结 native13 原验证结果和原日志投影。`verify_scope.py` 校验这些字节和事实，不运行产品、Rust 或 native。`official-primary-01.original.json`、`official-primary-02.original.json` 保存本次公开官方文档工具返回全文；不是 HTTP wire capture。

- [M1 CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [M2 DeleteFile](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-deletefile)
- [M3 File access rights constants](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)
- [M4 File security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [M5 Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
- [M6 Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
