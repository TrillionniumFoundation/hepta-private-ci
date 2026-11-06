# Windows 权限边界：修复与验收设计

状态：只读审查完成；三个原失败仍开放。本文不是生产补丁，也不是权限实验的授权。此前对 token、ACL、loader、DLL 边界修改的自动审批拒绝继续有效；本次仅创建供独立审查的 qualification 文档对象。

## 1. 固定来源与证据限域

审查 head 为 `ff72d462d74f9eb856aa9edbc368caad9c466708`。Windows 原 job 实际 checkout 是合成 merge `8e20cb5ec8261053ea472f06f79a0def072f3dce`，其 tree 与 head 完全一致，均为 `f780fe13946102a33b329898af48810be9c7bf0c`。commit 父关系、tree 和八个来源文件 blob 均独立校核；完整清单在配套 JSON。

原证据：[run 41875454075 / Windows shard 2 job 126733764659](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454075/job/126733764659)。完整日志为 559,323 字节，SHA256 `9366f22f8137626203debc8be5448a8156b4d75b8fac7569bc55967ddcc4cda8`。目标为 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests`；原执行结果为 52 passed、3 failed、2 ignored、92 filtered out，4.39 秒。17:39 的尾段由 wrapper 再次打印相同 test.log，不能算第二次复现。

| 原 exact case | 已观察事实 | 当前判断 |
| --- | --- | --- |
| token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes | 重复 repair 实际为 (true, true, true)，原期望 (false, true, false)；目录 ACE 数 11→13，直接文件 8→9 | 幂等性根因已证；生产修复未获边界授权 |
| token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces | overwrite/create 返回 PermissionDenied / OS 5；remove_file/remove_dir 返回成功；结束 impersonation 后两个对象均 NotFound / OS 2 | 删除越界已证；具体授权路线未分离 |
| unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots | 真实 cmd 子进程退出 0，三个允许文件被删除；outside 文件和受保护 .git 也实际消失 | 真实子进程合同失败已证；删除根因仍需区分 |

不得把到达较后失败断言之前的局部成功描述为整个 case 通过。尤其前两例的最终内容/物理状态断言在先前 assertion panic 后未继续执行；修复后必须全部执行。

## 2. 已证幂等性缺陷与最小修复语义

来源：[acl.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/codex-rs/windows-sandbox-rs/src/acl.rs)，blob `755083dd97ef25065692028405412326e4e2ac49`。

`dacl_has_complete_deny_for_sid` 已将 generic mask 映射为 filesystem 的具体权限，但只把 leading、explicit、无条件 deny 中 flags 恰好为 0x03 的单条 ACE 视作完整。原 setter 后，Windows 实存以下表示：

| 对象/ACE | flags | mask | 语义 |
| --- | --- | --- | --- |
| 目录 effective deny | 0x00 | 0x00130156 | 对当前目录生效 |
| 同目录 inherit-only deny | 0x0b | 0x40130156 | OBJECT + CONTAINER + INHERIT_ONLY，向后代传播 |
| 直接文件 effective deny | 0x00 | 0x00130156 | 对当前文件生效 |

这三类都不等于 0x03，现有 query 跳过它们，再次调用 setter 增加 deny。源谓词、真实存储形态、返回值和 ACE 增长共同建立了原因；不是仅凭失败名称猜测。[M3–M5] 解释了 effective/inherit-only 分离、generic mapping 和自动传播机制。

后续可审的最小方案是修改“已有完整 deny 的识别语义”，保持安装权限、排序和 token 策略不变：

1. 在具备路径/对象身份的调用处明确区分文件与目录，并保证类型判定对应同一个被查询 DACL 的对象；不能让一个无对象类型的谓词把文件错误地要求为递归目录。
2. 文件只需要本体的完整 explicit effective deny。已有 inherited deny 不能冒充此次 explicit repair 已完成，原第一次直接文件 repair 仍须返回 true。
3. 目录同时要求本体完整生效和完整的 object/container 递归继承。完整 0x03 可同时证明两者；相同 SID 的完整 0x00 与 0x0b 组合也是有效表示。
4. 继续只信任 allow 之前的 leading explicit、无条件 deny。unknown/conditional/object-specific ACE、inherited entry、错误 SID、partial mask、NO_PROPAGATE 或缺失一种 child scope 均不能提前证明完成。不得任意合并不同 SID 或多个不完整 mask 来获得“完整”。
5. 不通过重排、删除重复 ACE、放宽 required mask 或改为返回 false 来隐藏原错误。完整已安装时直接不写，第二次 DACL 字节、ACE 顺序和数量应与第一次安装后的记录相同。

验收保留原 `(repaired, denied)`、`(false, true, false)` 和内容/文件不存在断言。新测试必须使用 native setter 实际规范化后的 DACL，并有 pair 的正控及缺任一半的负控。绝对 ACE 数随 runner 原 ACL 可变；检查重复 repair 前后不增长，不把本次 11/8 写成跨环境常量。

已有 `complete_denies_require_effective_recursive_scope_and_precede_allows` 必须继续以目录作用域要求 flags 0 单独失败；已有 mapped-mask、read-deny 和 setter-error 原例均保留。此识别函数被 read/write deny 共用，不能只验证 write 路径。[acl_tests.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/codex-rs/windows-sandbox-rs/src/acl_tests.rs) blob `a27ce6bde8a5a8ec68b005d6fc10cc4abf261d59`。

这项修复只解决幂等性，不能自动关闭两个删除失败。

## 3. 删除事实与尚待验证的原因

[token.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/codex-rs/windows-sandbox-rs/src/token.rs) blob `8945d75fe172679479b738e6266cac99a6f7ed16` 的 legacy workspace factory 使用 capability-only restricting entries，以及 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`。原五个 membership 观测确认 allowed a/b 存在，other-cap、logon、Everyone 不存在；这不是完整 active child token/handle 审计。

当前 fixture 同时给普通身份提供了对象 DELETE 和父目录 FILE_DELETE_CHILD。原日志没有只保留其中一路的受控实验。因此：

| 假说 | 证据支持到哪里 | 还缺什么 |
| --- | --- | --- |
| WRITE_RESTRICTED 的 write 分类没有覆盖这次删除检查 | 官方定义仅说明 restricting SIDs 用于 write access；overwrite/create 已拒绝而删除成功 | 同一精确对象/父 ACL、同一操作下的受控 token 策略对照 |
| 父目录 DELETE_CHILD 路线绕过对象侧拒绝 | Windows 文档明确删除可由对象 DELETE 或父 delete-child 授权；fixture 两路都有 | 将两种 grant 分离并实际删除的四格矩阵 |
| active token/handle/privilege 或 API 路径影响结果 | 当前 factory、五个 SID probes 和物理结果已知 | 实际 impersonation/子进程 token、fresh handles、组属性/特权及具体请求权限记录 |

[M1] 和 [M2] 不能证明哪条路线是这次的唯一根因。不得把删除说成夹具误报：真实父进程 metadata/readback 已证明对象消失。

**目前没有足够证据选择一个安全的最小生产删除补丁。** 不能先删除 WRITE_RESTRICTED 再让 loader/IPC 崩溃“挡住”业务；不能把 Everyone、logon 或用户身份重新加入 capability 限制集合；不能修改宿主全局父目录 ACL。GENERIC_READ/WRITE 的映射还共享 SYNCHRONIZE，改变 restriction 模型必须同时验证原读取行为。[M6]

## 4. 获批后可执行的因果判别设计

以下是后续审查设计，当前没有创建或执行权限实验。

仅在独占 disposable fixture 内设置并读回 effective ACL；消除隐藏的 inherited/其他 enabled identity grants，避免它们重新引入本应被去掉的一路。保留 unrelated capability 的原负控，并对文件、空目录分别覆盖：

| 对象 identity DELETE | 父 identity DELETE_CHILD | 目的 |
| --- | --- | --- |
| 无 | 无 | 没有身份删除路线，必须拒绝 |
| 有 | 无 | 分离对象 DELETE |
| 无 | 有 | 分离父 DELETE_CHILD |
| 有 | 有 | 复现原 broad-identity 条件 |

产品 baseline 始终使用现有精确 factory。正常 identity token 可证明这个 fixture 的 ACL 设置有效；如安全审查允许，可以另建 full-restriction diagnostic token 来检验 flag 假说，但这种对照不等于可发布修复，更不能替代真实 loader/IPC 验收。

保留原 Rust filesystem 操作与真实 legacy cmd 子进程。精确 desired-access handle 或 AccessCheck 的观察只作补充，不替代实际 native 操作和退出后的物理读回。每个 case 不复用此前获得的特权句柄；记录实际 token 类型/完整 restricting roster、enabled 与 deny-only groups、特权和 integrity，以及对象/父 DACL 的 role、mask、flags 和完整性。

只有矩阵确定哪一个检查失效后，才选择生产 enforcement 方案。候选必须同时覆盖对象 DELETE 和父 DELETE_CHILD 两条授权路线，并继续允许声明的 workspace/TEMP/TMP 行为。任何 broader restriction 方案均需单独证明合法 read、loader、desktop、IPC 不受损；没有从文档推导出的“只补 delete”隐藏 flag。

## 5. 入口范围与闭合门槛

[正常 selector](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/codex-rs/windows-sandbox-rs/src/unified_exec/mod.rs) blob `c98f3e5d217ada48732e1686129806d0dd52169e` 将 workspace write / overrides 导向 elevated backend，相应原 backend-selection cases 在该 job 通过。这限制了结论范围：没有证明每个正常入口都有相同删除结果。但 [lib.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/codex-rs/windows-sandbox-rs/src/lib.rs) 仍公开 re-export 直接 legacy spawn 和 capability-only token factory；不能用路由选择关闭它们已失败的原合同。

发布前至少满足：

- 三个原 exact cases 全部实际执行并通过，原 assertion、真实 child、5,000 ms child budget 与 10 秒收集 budget 保持。不得新增 skip、放宽错误、过滤掉失败或调整重试。
- 原 repeat tuple 严格为 `(false, true, false)`；有效内容和 ACE 不发生额外变化。
- outside 四种操作严格拒绝，父进程确认 outside 文件内容、目录和 .git 保留；允许根目录仍有创建/删除的真实物理效果。
- 原非 TTY cmd 输出/退出、TTY PowerShell 双向输入输出、elevated env/退出、stdin open/close、private/default desktop 及 exact capability、network proxy identity 正控通过。
- 如修改 token/default DACL，新增真实 restricted child 的加载与 child-created IPC object 正控；仅 channel 单元测试不足以证明 ACL/loader 兼容。
- 原两个 legacy TTY cmd 的 STATUS_DLL_INIT_FAILED ignored 仍明确未验收，不能记成通过，也不能扩大 ignore 集合。
- 在准确获批 source commit/tree 上运行原 Windows x86_64-pc-windows-msvc Bazel target/工作流，收集全部原 test.log/XML，验证 roster、无 retries、source 前后不变。Linux 或 Wine 结果不关闭这个平台门。

配套 JSON 包含计划命令、精确 case 集合、完整来源 hash 和条件门。当前状态依旧为三个原 case OPEN；本次没有生产补丁、ref 更新或权限实验。

## 官方依据

- [M1 — CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [M2 — DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
- [M3 — ACE inheritance rules](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)
- [M4 — ACE_HEADER flags](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-ace_header)
- [M5 — Automatic propagation of inheritable ACEs](https://learn.microsoft.com/en-us/windows/win32/secauthz/automatic-propagation-of-inheritable-aces)
- [M6 — File security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [M7 — Order of ACEs in a DACL](https://learn.microsoft.com/en-us/windows/win32/secauthz/order-of-aces-in-a-dacl)
