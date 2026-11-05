# B11：删除权限边界与可实现修复范围

## 结论

**B11 仍然开放。本次没有生成声称能修复隔离的产品补丁。** 当前公开的 `create_workspace_write_token_with_caps_from(base_token, capability_sids)` 只接收 token 和 SID，不接收可读对象、可写对象或独立文件访问执行边界。已实测的 `WRITE_RESTRICTED` 模式在原攻击夹具上没有阻止父目录 `FILE_DELETE_CHILD` 授权；单独移除这个 flag 又不满足原 outside-read 条件。当前代码没有可供一行修复调用的第二个、已证明安全的文件访问边界。

这不等于证明所有 Windows 隔离技术都不可行。它限定的是：**保持当前 token-only API、原 flags、任意环境读取、原宽泛 ACL 攻击和原正向操作同时不变时，没有从现有源码及公开 API 契约中找到正确的局部修复。** 不能用拒绝全部请求、改为另一个同类 token 后端、扩大能力 SID，或删掉原读取条件代替这一缺口。

## 固定源码与原始运行

- 当前产品固定为 `5b6331250ff459033bd44d1a95daec70131277cc`。
- 原 Windows 运行：run `41966043093` / job `127043294552`，实际合并提交 `9459cf8a4e5e43d6645e2b619b86455132c7df67`。完整日志 600,398 字节，SHA-256 `a30a35effe2fe56d997ef570b27f3c81b358b33fb13401e3977ed6277bec0bb1`。
- 原 token 文件 `3e732021a5e52fef8dfc60f1fdf338b55868ea7a` 精确等于当前产品文件 `8945d75fe172679479b738e6266cac99a6f7ed16` 加一个末尾 `cfg(test)` 诊断模块声明；本次重新计算并比较了完整字节。
- 本次另取并完整读了原运行的诊断模块 `e8bf47c8a07ad827b322ffe689240efe42fbba95` 与其实际 AccessCheck 实现 `349bb50a38929fadbf038daf0c5c0c6913a3803b`，不只依赖日志中的自述字段。
- 全部 15 个固定源码原件、字节数、SHA-256 和 Git blob 列于 `source-manifest.json`。较大的 setup 文件按相关调用段审查；完整原件被保存不等于所有无关分支都审查完成。

## 实际证据的层次

| 证据 | 已证明内容 | 不扩展为 |
|---|---|---|
| 原 strict token case 的真实 `std::fs` 操作和 panic | 允许根内创建、删除先成功；outside 文件读取先成功；outside 覆写、创建返回 PermissionDenied；outside 文件与目录删除却成功 | 当前 5b 整个 Windows CI 已执行同例；所有 Windows 版本均同样 |
| production token 对现存对象的真实打开 | outside read / DELETE / 父 DELETE_CHILD 打开成功，outside write 打开失败 | 这些打开自身已执行删除 |
| 同一 retained descriptor 的 AccessCheck | production token 上 outside `DELETE=0x10000` 拒绝，父 `FILE_DELETE_CHILD=0x40` 准许；原始 descriptor 副本调用前后相等 | Windows 内核具体私有实现、每一次物理删除的内部调用栈已被跟踪 |
| full-restricting 对照 | 复制原 token 的实际两个 restricting SIDs、default DACL 和单一保留 privilege；仅省略 WRITE_RESTRICTED。AccessCheck 同时拒绝 outside read / DELETE / DELETE_CHILD | full-restricting token 已被 impersonate 后执行物理读取或删除；诊断实现明确没有这样做 |
| legacy 子进程原 case | 原 cmd 子进程完成后，workspace/TEMP/TMP 文件消失，outside 文件与受保护 `.git` 也消失，违反原 tuple | 下游 elevated 后端已运行相同攻击 |

原目标结果是 78 PASS / 2 FAIL / 2 ignored / 86 filtered。日志后半段 wrapper 重印不算第二次 attempt。两个失败分别是 `token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces` 和 `unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots`。

## 当前 API 为什么没有足够的表达能力

原 strict case 故意授予宽泛 Logon/Everyone `FILE_ALL_ACCESS`，并要求环境读取仍然成功。当前工厂在正常身份上没有禁用 SID，只把工作区 capabilities 放入 restricting list，保留 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`。改变 restricting list 不能被当作已覆盖原运行中独立的 parent DELETE_CHILD 授权；添加 Everyone 或 Logon 反而会扩大第二次检查的可用授权。

把这些正常身份改为 deny-only 也没有为它们保留“只读”的公开 API 参数。Microsoft 的定义是关闭相应 SID 的 enabled 属性；这会影响该 SID 的全部 allow 匹配。更关键的是，工作区 capabilities 只在 restricting list 中，不能凭这份列表补回正常身份检查所缺的写授权。对当前 raw-HANDLE 接口做这种改动，既没有路径信息可以补足读取，也不能证明根内正向操作不退化。

Microsoft 文档规定，删除可以通过目标 DELETE 或父目录 DELETE_CHILD 两种权限获得；`WRITE_RESTRICTED` 只在写访问评估中使用 restricting SIDs。公开文档没有把该 flag 扩展为可由应用传入的任意文件操作访问掩码。本次具体 0x40 行为来自真实 Windows 运行，不把文档的一般描述当作所有 build 的位级实现规范。

## 现有 elevated 路径不能直接充当证明

当前 `unified_exec/mod.rs` 的 selector 已把写能力请求和路径限制请求送到 elevated backend，但公开 direct legacy 入口仍直接执行 legacy。将其改为转调 elevated 可以消除一个入口绕行，**却不是本次原攻击的隔离修复证明**：

1. `command_runner/win.rs` 的实际构造调用 `*_with_caps_and_user_from`。它仍进入同一 token 工厂、使用 WRITE_RESTRICTED，并把 dedicated user / Logon / Everyone 纳入其现有模式。
2. `setup_main/win.rs::apply_read_acls` 在已有 builtin RX 时跳过补充；工作区 write refresh 只针对指定 sandbox group 与 root capability。代码没有逐个约束任意外部父目录上的 Everyone DELETE_CHILD。
3. 这条链启动的是一个能直接执行文件系统调用的进程，当前读取的 IPC 协议承载 spawn/stdin/terminate/exit，不是对每个删除操作的文件访问 broker。

因此，在原夹具故意提供 broad Everyone 权限的前提下，单纯换到现有 dedicated-account runner 没有消除已知授权来源。此处是固定源码的未闭合风险分析，不虚构该后端已经发生一次新的物理 FAIL。

## 最小可实现的下一切片

### 可使用现有 Win32 原语实现的有限读取模式

可另建一个**显式读取根的完整限制 token 模式**，输入须包含可信的当前 read-root / write-root 集合，以及只授予读取的独立 capability。只有实际完成同一对象的 ACL 处理后，才允许构造完整限制 token；工作区 write capabilities 与独立 read capability 不得以 Everyone、Logon 或宽泛 user SID 替代。正常身份检查继续限制宿主原本无权访问的对象。加载器、IPC 和所有辅助进程必须走同一真实模式。

最小生产依赖切片是：token 构造的新具名模式与合同、spawn preparation 的实际 root/capability 输入、setup 对这些 read grants 的同步成功门、runner 对同一权限模式的消费。已存在的 `add_allow_ace` 会授予写权限，不能误作 read-only grant；必须使用真实 read/execute mask。保护路径、符号链接/重解析点、并发 ACL 变化和独立运行的会话还需要明确对象及生命周期责任。

这条路可以保留**显式授权**的外部读取，不能悄悄替代当前“任意 ambient read”或维持原 flags 的旧 token-only 合同。因此现在不把它包装成三行修复，也不修改原 strict case 来接受更窄语义。必须先决定该新接口的真实调用方和许可策略，再制作连续的小补丁。

### 必须保留全部 ambient-read 语义时

需要在实际文件操作发生处提供独立、不可由 child 绕过的执行边界；例如真正约束每个原生文件操作的已部署隔离层，而不是 launch 前一次 AccessCheck 或 spawn-only broker。现有读取链中尚未找到这样的可复用组件。仅添加启动前检查存在对象/ACL/路径随后变化的问题，也无法约束未枚举的外部目录。该部分保持 OPEN，不声称仓库中完全不存在尚未审查的其他隔离实现。

### MIC 低完整性不是当前接口的一行替换

MIC 是另一项可能的独立机制：Microsoft 明确说明低完整性主体受到较高完整性对象的 no-write-up 限制，未带标签的对象按 medium 处理。这一机制原则上可以把“读取 medium 对象”和“写入 medium 对象”分开，不能据此声称 Windows 全局不可能实现所需隔离。

但当前已读的 token / spawn / ACL / setup / command-runner 主链没有设置 TokenIntegrityLevel 或安装 mandatory label 的步骤；原诊断请求的是 OWNER/GROUP/DACL，**没有读取 SACL 或对象完整性标签**。因此原根目录的实际标签仍是未观测输入。若降低 token 完整性，允许根也必须具备兼容标签及权限，当前只含 base+capSID 的 constructor 无法选择和验证这些对象。直接在所有 `ensure_allow_write_aces` 调用中降低标签也错误：原夹具的 outside 还特意授予了另一个、不属于本 token 的 capability，同样的 label 不能表达这两组 capability 的区别；其他既有 low-integrity 外部目录仍需独立边界保护。MIC 路径需要新的可信 root/label 输入、错误与恢复合同及真实删除验证，不能广改系统 SACL 或把原测试改成低标签布置来宣称旧合同已修复。

## 原 Windows 验收必须保留

沿用原 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests` 选择和预算，保留完整 stdout / test.log / XML / 所有 attempt 的 source、cache、retry 身份。至少必须实际到达并通过：

- 原三个失败控制：`partial_delete_deny_is_repaired_before_native_workspace_writes`、`workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`、`legacy_workspace_write_delete_is_limited_to_writable_roots`。
- 两个实际四格控制：token 和 legacy child 的 `DELETE` × parent `DELETE_CHILD`，包括 ordinary-host 正负控制及真实同一对象、ACL、内容和最终物理存在性。
- 原 public ACL query、幂等性返回值、外部读取、工作区/TEMP/TMP 写入及删除、受保护 `.git`、加载器与 IPC 正向控制。

raw token 工厂的原严格测试不能因为上层改路由就删除、ignored 或改为接受 Err。任何不同权限模式须单列自己实际资格；旧模式未修复仍保持失败事实。所有新增实现都要重新取得原平台证据，不能借 Linux、不同 donor 或元数据成功替代。

## 官方依据

- [Microsoft：CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)：Flags、deny-only SID 和两个访问检查的公开合同。
- [Microsoft：DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)：目标 DELETE 与父 DELETE_CHILD 的独立授权路线。
- [Microsoft：File Security and Access Rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)：文件 generic masks、对象 ACL 和继承范围。
- [Microsoft：Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)：独立 MIC 检查、对象/token 标签、无标签对象的默认处理和 no-write-up 范围。

本次仅固定源码与原件审查，没有运行 Windows 权限实验，没有修改 native source、测试、产品 refs 或 Windows 宿主设置。
