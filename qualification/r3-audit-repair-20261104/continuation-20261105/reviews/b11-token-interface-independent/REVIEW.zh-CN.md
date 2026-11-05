# B11：当前 token 接口的独立机制复核

## 结论与范围

**未找到能在当前 `base_token + capability_sids` 接口内、同时保持原外部读取、能力根内写删和阻断外部父目录删除权限的已证最小修复。** 这是对固定 `5b6331250ff459033bd44d1a95daec70131277cc`、原严格用例和已读取 Win32 契约的结论，不是“Windows 无法实现这种隔离”的结论。没有生成或应用 token、ACL、loader、DLL 生产补丁，没有执行 Windows 实验，也没有更改原用例、预算或退出条件。

本复核接受 architecture 的限定结论；另补充一个权限精度：只查询 mandatory label 并不等于读取整个 SACL。Microsoft 的 `SECURITY_INFORMATION` 表明确规定，`LABEL_SECURITY_INFORMATION` 查询需要 `READ_CONTROL`、设置需要 `WRITE_OWNER`；不能笼统称所有标签观察都需要管理员或 `ACCESS_SYSTEM_SECURITY`。[官方权限表](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information)

## 已核实的证据

当前 token 源 `8945d75fe172679479b738e6266cac99a6f7ed16` 的工厂只接收 base token、capability SID 列表及内部 identity 选择；实际调用 `CreateRestrictedToken` 时不禁用普通身份 SID，使用 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`。workspace-write 只把 capabilities 放入 restricting list。它不接收文件句柄、读根、写根或 label 生命周期责任。`spawn_prep.rs` 上层持有写根，但该信息在此处被转换为 SID 后传入工厂，不能把上层信息视为已存在于这个公开接口的可信新输入。

原运行是 run `41966043093` / job `127043294552` / 实际 merge `9459cf8a4e5e43d6645e2b619b86455132c7df67`。600,398 字节完整日志的 SHA-256 为 `a30a35effe2fe56d997ef570b27f3c81b358b33fb13401e3977ed6277bec0bb1`。其 token 源比当前 token 全文仅多 test-only 诊断 module，生产文本相等；不能据此把这次旧 donor 运行升级成当前 head 的完整 Windows 资格。

| 证据层 | 实际已经发生 | 不能外推 |
|---|---|---|
| 原 strict token 物理用例 | 能力根内创建、删除成功；outside 读取成功；outside 覆写/创建被拒，文件/目录删除却成功 | 尚未执行的新 head 原平台用例已经通过或失败 |
| 原 legacy 子进程 | child 完成、exit 0，workspace/TEMP/TMP 文件删除；outside 文件和受保护 `.git` 也消失，原 tuple 失败 | dedicated elevated 后端已经在相同攻击上实测失败或成功 |
| 同一 descriptor 的 AccessCheck | production 的 outside `DELETE` 被拒而父 `FILE_DELETE_CHILD` 获准；原 descriptor 字节在比较前后相等 | 已跟踪内核内部每次物理删除的具体调用路线 |
| full-restricting 对照 | 复制原实际两个 restricting SID、default DACL、保留 privilege，仅去掉 WRITE_RESTRICTED；outside read/DELETE/DELETE_CHILD 均被 AccessCheck 拒绝 | 已 impersonate 该对照并做物理读取或删除；源码明确没有这些操作 |

官方 [DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew) 允许通过目标 DELETE 或父目录 DELETE_CHILD 获得删除权限。原 AccessCheck 与物理结果和这条规则一致，构成有依据的父权限路线解释；仍不声称已对私有内核实现做 syscall trace。

## 为什么候选快捷改法还不足

| 机制 | 当前证据或接口问题 | 判定 |
|---|---|---|
| 只去掉 WRITE_RESTRICTED | 第二次 SID 检查扩展到读取；原对照 already 拒绝 outside read。缺少独立只读 grant | 不满足原正向合同；不是完整修复 |
| 把 Everyone / Logon 加回 restricting list | 宽泛 allow ACE 同时授予读、写、删除，SID 本身不是 read-only capability | 不能补读而不重新放大写删 |
| 将普通 SID 设为 deny-only | 该 SID 的所有 allow ACE 都不再参与，不是按访问掩码只撤写权限；cap SID 仅在 restricting list，不能自动补普通身份检查 | 原读取及根内正向行为均缺证 |
| 改 token default DACL | 当前函数只改变新对象的默认 ACL；不能重写已经存在的 outside 父目录授权 | 不覆盖已证删除路线 |
| 给父目录加全局 deny，或启动前 AccessCheck | 前者会影响同 SID 的宿主正向；后者不约束 child 后续任意原生路径、ACL 变化和重解析对象 | 不是原宿主负控和对象边界的替代 |
| 直接改用现有 elevated 路由 | 固定当前 runner 仍调用同工厂族，含普通 identity；没有原攻击下的完整物理通过证明 | 入口收敛与隔离证明必须分开 |
| 低完整性 token / mandatory label | 原物件 IL/label 未观测；工厂无 selected root 对象输入。合法根能否写入、outside 已是低完整性时怎么办、label 何时恢复均未定义 | 可研究的另一层机制，尚非可应用的修复 |

[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken) 给出的 restricting SID 属性不提供逐访问掩码配置。[SID attributes](https://learn.microsoft.com/en-us/windows/win32/secauthz/sid-attributes-in-an-access-token) 定义 deny-only 的影响对象为该 SID 的 allow 匹配。[File access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights) 也说明 generic read/write 映射共用 SYNCHRONIZE；不能简单用 generic-write deny 当作不影响 read 的方案。以上是公开接口约束，不把 generic 映射自行当作 Windows WRITE_RESTRICTED 的私有实现规范。

## 可以继续实现前必须补齐什么

**有限、显式读取模式**可以用完整限制 token 加独立 read capability 设计，但必须由真实调用方提供可信的 read-root / write-root 对象集合、只读 grants 与 capability 的对应关系，以及成功安装 ACL 后才启动的门。不能用 Everyone / Logon 代替 read capability。当前仅有写能力的 SID 工厂不具备这些输入；更不能暗中把任意 ambient read 改成有限 roots，并用修改原断言掩盖语义变化。DACL 查询/设置权限分别是 READ_CONTROL / WRITE_DAC，还需定义共享权限、重解析、并发变化、继承及撤销责任。

**若保持全部 ambient-read 语义**，则还需真实不可绕过的逐操作边界，或能够证明覆盖所有允许读取对象及外部写删路线的 OS 隔离合同。现有 spawn-only broker 和一次启动检查不是这样的文件操作边界；本次未发现可直接复用的已验证组件，不声称未审代码或 Windows 的全部其他机制不存在。

**MIC 方案**首先要实际观察原 token 的 IntegrityLevel/MandatoryPolicy 及同一 retained 文件/父目录的 LABEL_SECURITY_INFORMATION。官方 [MIC 文档](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control) 规定低完整性主体不能写较高完整性对象、无标签对象按 medium 处理；这些规则不能替代本次缺少的对象观察。后续若改标签，必须绑定真实 selected roots 和对象身份，证明合法根写删仍成立、其他 capability 的 outside 及既存低完整性外部目录仍被限制。没有理由把所有 `ensure_allow_write_aces` 的对象一律降级：原夹具特意给 outside 安装了另一个不属于此 token 的 capability。新模式还必须说明标签设置所需 WRITE_OWNER 权限、继承、并发会话及恢复机制，不假定已有权限或已标记路径。

## 原验收门保持

原 strict token 和 legacy child 用例仍必须成功执行，而非返回统一 Err。保持 outside read、能力根内写删、outside 内容和目录保存、`.git`、child done 与宿主正负控制。原两组四格控制需要实际区分目标 DELETE 与父 DELETE_CHILD；单边拒绝不等于两条路线都被封住。原一般文件/目录矩阵也不能替代 `.git` 特殊保护条件。保留当前原预算、所有 attempt、cache 和来源，不能借 Linux 或另一个 donor 的总目标成功。

截至本复核没有新增 Windows 执行证据。B11 保持 OPEN；没有改变原 23 项 ID、退出条件或闭合数字。
