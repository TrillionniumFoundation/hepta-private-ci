# B11：当前 Windows 失败与可审静态候选

## 结论与范围

当前 cabc 的三条严格失败均有完整原始输出；其中幂等性识别错误已有具体静态候选，两个删除权限失败的安全生产改法尚不能选定。这不是三个夹具误报，也没有已闭合的 Windows 修复资格。

本次只在隔离目录生成候选和审查材料，没有应用产品源码、修改 ref、运行 Windows/Cargo/Bazel 或更改 token/loader。历史自动审批拒绝的原 receipt、动作和理由仍未找到，不能替其补造理由或视作用户禁止 Windows 工作；旧版本文档的相应表述只保留为历史二级记录。

## 当前证据，不借旧 head

已独立读完整 [Windows shard 2 原 job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41902318286/job/126827931463)。实际 merge 为 `28af7f705fa1024b9a6d2ef751fec116002260eb`，父为 `63652be658ebed8d3052eb789b951793384fd5e4` 和 `cabcb40d36e116beaa65750e1f674c52035da785`；tree 与 cabc 完全相同，为 `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`。完整 job log 是 585,442 字节，Git blob `2d10d7f1381c43a0d6e9d1c9da0bab3b44ef7c85`，SHA256 `49981a617c75a7224dc3985ecdde4fcd6c6dfccb36b209d04d15d85ec0f02eba`。

目标 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests` 的完整输出为 **52 passed / 3 failed / 2 ignored / 92 filtered out，6.22 秒**。后续 wrapper 重印同一 test.log 尾段，不是第二次执行。ZIP 成员身份来自此前已校验索引，本次没有重新下载 ZIP；当前三条失败正文及 DACL/物理观测则从完整 job 原件重新独立读到。

| 原 case | 当前实际结果 | 结论 |
| --- | --- | --- |
| `partial_delete_deny_is_repaired_before_native_workspace_writes` | repeated tuple 为 `(true,true,true)`，原期望 `(false,true,false)`；目录 ACE 数 11→13，文件 8→9 | native 规范化后的 deny 被旧识别器漏认，重复安装，原因已证 |
| `workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces` | overwrite/create 为 OS5；remove_file/remove_dir 成功，退出 impersonation 后文件/目录均 OS2 | outside 对象确实被删；还没分离对象 DELETE 与父 DELETE_CHILD |
| `legacy_workspace_write_delete_is_limited_to_writable_roots` | 真实 cmd 子进程退出 0，parent 读到 outside 与受保护 .git 不存在；原 tuple 保留要求失败 | 真实 legacy 执行合同失败；不是只看 exit0 的误判 |

发生 panic 后的后续断言没有执行，不能将其记成成功。f825 所存 cohort 中 Windows sandbox 源码没有改动，但这只证明相关 source 连续，不把 cabc 结果扩大为 f825 全树资格。

## 三路径最小幂等性候选

`idempotency-candidate.patch` 改动 `acl.rs`、新增私有 `acl_deny.rs`、追加 `acl_tests.rs`。公共目录 query、其严格 mask/scope/order 语义和四个原 ACL 测试定义逐字不变；token/legacy 三个原失败源码也不改。

1. 以 `READ_CONTROL` 打开一个真实对象，通过同一 handle 读取 `FileStandardInfo` 和 DACL。没有 `path.is_dir` 或分离的路径类型推断。
2. 已完整时返回 false，完全不索要 `WRITE_DAC`。文件接受完整 explicit effective deny；目录仍需本体和两类后代完整覆盖，除原 0x03 外只增加同 SID、各自完整的 0x00 + 0x0b native 表示。
3. 仍只信任 leading explicit 无条件 deny。不同 SID、partial mask、inherited、unknown/allow 之前不完整、no-propagate 和缺 child scope 均不组成完整目录 deny。
4. 确需 repair 才 `ReOpenFile` 原对象请求 `WRITE_DAC`，使用原 mask、`SetEntriesInAclW`、OI/CI 继承设置，再对该 reopened handle 调 `SetSecurityInfo`；不按原 pathname 重选目标。

这比单纯改谓词多了明确的 handle API 替换：新错误标签报告实际 CreateFile/GetFileInformation/ReOpenFile/SetSecurityInfo 操作；文件系统支持、共享模式和访问规则需要 Windows 原例验收。没有启用额外 privilege。对象身份一致也不等于 DACL 并发写串行化、路径/父目录 custody 或整个权限系统已安全。

三个新增控制分别验证：完整/缺半/不同 SID/错误 scope 的 native ACL 查询；真实 file/directory、read/write 安装后重复调用的完整 DACL 字节不变；真实 OWNER_RIGHTS deny 使与生产 repair 相同的 ReOpenFile(WRITE_DAC) 返回 OS5 后，已有 read/write deny 仍能仅查询并返回 `(false,false)`。最后这个控制必须先真实证明宿主缺少 WRITE_DAC，不能以错误原因或未进入测试冒充 no-op 资格。

候选只做静态重建与源码/接口核对，尚未格式化、编译或执行。windows-sys 当前 lock 为 0.52.0；相应官方源已核这几个接口存在。原 partial-repair case 继续要求 `(false,true,false)`、原内容和拒绝断言。三个原失败仍全部 OPEN。

## 删除策略必须先通过的四格实验

当前 fixture 同时给普通身份两条删除路线；官方 DeleteFileW 合同允许对象 DELETE 或父目录 DELETE_CHILD，因此现有结果不足以在两者中唯一归因。`WRITE_RESTRICTED` 文档也不能代替真实删除 access-check 证据。当前不直接删除该 flag，不重新加入 broad identity SID，不修改宿主全局 ACL。

| 普通身份对象 DELETE | 普通身份父 DELETE_CHILD | 同布局宿主物理控制 | 当前产品 capability-only token 的 outside 合同 |
| --- | --- | --- | --- |
| 无 | 无 | 删除必须拒绝，对象保留 | 拒绝且对象/内容保留 |
| 有 | 无 | 删除必须成功 | 拒绝且对象/内容保留 |
| 无 | 有 | 删除必须成功 | 拒绝且对象/内容保留 |
| 有 | 有 | 删除必须成功，覆盖原 broad 条件 | 拒绝且对象/内容保留 |

每格分别覆盖新鲜文件、空目录、原 Rust 操作和单独对象上的真实 legacy cmd；仅改独占 disposable fixture。实际读回完整 DACL 和 token 信息，剔除隐藏的 inherited/enabled SID grant；操作前关闭旧 DELETE/data 句柄，防共享冲突、只读属性、对象预先不存在伪装权限结果。宿主控制若不符合表格，整格不可用于推导产品 token 原因。matching-capability 的允许根正控单独沿现有产品 setup 建立，不要求宿主本就无删除权的 00 格凭空成功。

矩阵可以区分问题，但不是发布修复。任何后来受审的 full-restriction diagnostic token 都不能凭 outside 拒绝称产品可用，还须通过真实读取、加载、desktop、child IPC、workspace/TEMP/TMP 正控。Oct31 的“prototype 宿主控制异常”只有历史 assistant 陈述，不是 cabc 的运行证据。

## 保留原验收门

先验证幂等性候选的三新增控制、四原 ACL 控制和三个原失败，完整保存原错误、物理效果、来源与过滤/忽略/重试信息。原 legacy child 5,000 ms、collection 10 秒及全部断言保持。随后仍需原 Windows Bazel 目标/工作流；不能用 Linux、Wine、静态审查或旧源通过代替。

当前 cabc 原 job 已有 private/default desktop、exact capability、network proxy SID、backend selection、ACL setup error、stdin 两状态、非 TTY cmd、TTY PowerShell、elevated env/exit 等正控实际通过；JSON 逐一列出名字。两个旧 legacy TTY cmd `STATUS_DLL_INIT_FAILED` ignored 仍未验收，不能计 PASS。配置中没有原生 Windows host，故下一实际平台门必须由对应 Windows CI 提供。

当前 normal selector 把 workspace-write/overrides 导向 elevated backend，直接 legacy 与 capability-only factory 仍是公开入口；前者通过不抹掉后者原失败。已核调用链为 `legacy::... → prepare_legacy_session_security → create_workspace_write_token_with_caps_from → CreateRestrictedToken → actual CreateProcessAsUserW`，没有假设所有正常入口都有相同删除结果。

## 原件与 API 来源

- 当前固定源：[acl.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/codex-rs/windows-sandbox-rs/src/acl.rs)、[token.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/codex-rs/windows-sandbox-rs/src/token.rs)、[spawn_prep.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/codex-rs/windows-sandbox-rs/src/spawn_prep.rs)。全部来源 Git/bytes/SHA 清单在 JSON。
- [ReOpenFile](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-reopenfile)、[SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)、[FileStandardInfo](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info)、[NtQueryInformationFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntqueryinformationfile)：同对象句柄、目录识别、standard information 无额外 desired-access 要求；不把原生 API 文档当已执行结果。
- [DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)、[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)、[OWNER_RIGHTS](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/81d92bba-d22b-4a8c-908a-554ab29148ab)：分别支持矩阵设计、flag 限域和 no-op 宿主控制；不证明具体当前删除检查路线。
