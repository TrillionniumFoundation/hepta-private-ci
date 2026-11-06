# B11 v3：普通令牌观测的测试专用启动入口

本候选只修正新观测模块对 sandbox-only 启动入口的错误复用。它没有修改生产令牌、桌面、进程、Job 策略，也没有放宽任何既有严格断言。B11 继续为 **OPEN**。本包未编译、未运行 Rust 或 Windows 产品代码、未执行 rustfmt，未更新任何 ref。

## 首次失败及其边界

依据 `evidence/native11-full-job.original.log` 的完整原始字节，native11 使用实际 merge `53766cb836b198e2f928b949f148d7a2a10c0d21`、树 `9cb7302777ce018dd022086041c2225d1dd5c8dd`。整套原始结果是 146 passed / 8 failed / 2 ignored；日志中的 54/8/2 失败子集在归档输出中再次出现，只计一次。

新观测已记录 NTFS、两主体完整令牌，以及三组 Rust 同路径矩阵。普通主体和仅禁用 privilege 的主体均没有 restricting SID，除 privilege 外比较的身份字段相同。普通直接调用、普通 impersonation 的 Neither 文件与目录删除成功；disabled impersonation 的 Neither 两项拒绝，其他三个路由成功。该结果仅支持这次多 privilege 反事实观察，不能单独归因于 SeRestorePrivilege，也不能替代 B11 的沙箱闭合要求。

随后在第一个新 cmd 子进程创建前，原测试失败于 `GetTokenInformation(TokenRestrictedSids) size query failed: 122`。没有 `child_before_release`、`cmd_physical` 或新五矩阵完成标记。原始日志及其 SHA256 `29c7b0343a5f8865bd2bf8088e3108e2c3db3b3f89f93c0aaa72b89834d685bc` 保存在本包，不以新候选覆盖。

精确源码位置是 `desktop.rs::private_desktop_restricting_sids`，不是当前 `token.rs` 中一个名为 `get_restricted_sids` 的函数。`LaunchDesktop::prepare` 在 `use_private_desktop=false` 时仍先调用该 helper。helper 用包含占位数组成员的 `sizeof(TOKEN_GROUPS)` 作为长度下界；零组变长结果可能小于这个固定结构大小。初始零长度查询的 122 本身是缓冲区不足响应；日志未记录实际 `needed` 数值，本包不声称测到了 4 或 8 字节。随后源码又明确对 `GroupCount == 0` 拒绝并报 `sandbox token has no restricting SIDs`。

因此，即使另行修正变长头解析，也必须保留生产入口的零 restricting SID 拒绝。本候选完全不改该生产入口，避免把诊断普通令牌的需要转化为生产策略放宽。相关 Win32 契约见 [GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation) 和 [TOKEN_GROUPS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_groups)。

## 唯一源码差异

唯一替换路径为 `codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs`：实际已发布的 v2 preimage `b40b49ce772c402c51ddb16bb98ff73dc78cdb41` → computed v3 postimage `8c16416c185f17871c25139bc16c6fd112b5fd41`，26,205 字节。`v2-to-v3.patch` 与 `full.patch` 完全相同，只有该路径的 5 个 hunk。

`OwnedChild` 改为直接持有现有 `JobObject` 与成功创建返回的原始进程、线程句柄。新私有 `spawn_observation_child` 对 ordinary / disabled 两主体使用同一个实现，复用实际生产依赖中的 `argv_to_command_line`、`to_wide`、`make_env_block`、`ProcThreadAttributeList` 和 `JobObject::create`，直接调用 `CreateProcessAsUserW`。`token.rs` 的 `#[cfg(test)]` 探针模块链保持原样，新 helper 只在这个测试模块可用。

| 约束 | 候选中的具体处理 |
| --- | --- |
| 同一路径与身份 | 两主体调用同一 helper，继续比较完整实际 child primary token 的身份、全部 privilege 属性及 primary 类型。没有新增全局 privilege 调整、身份替换或 fallback。 |
| 参数、环境、桌面 | 使用现有参数与环境构造；显式 `Winsta0\Default`；原 `/d /e:on /v:off /c` 和保留名大小写无关清理不变。没有桌面 ACL 修改。 |
| 创建 flags | 精确保留 `CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW`。 |
| 创建时 Job 绑定 | `ProcThreadAttributeList::new(2)`，先 `set_job`，同时传入显式 stdio handle list。属性失败即返回，没有创建后追补 Job 或未受控 fallback。 |
| 继承白名单 | 仅私有 stdin reader 与同一 stdout/stderr 文件两个句柄；父进程 release writer 的非继承断言保留且不在列表内。 |
| 句柄所有权 | Job 与 stdio 在调用前已经有 owner；成功返回与 `OwnedChild` 接管两个新句柄之间没有任何可失败操作。后续错误触发既有 Drop 清理。 |
| 失败保留 | `CreateProcessAsUserW` 返回零后立即捕获原始 OS error，再添加上下文；不重试、不改 token、不改 flags。 |
| 删除门闩 | child primary token 在释放私有 stdin 前核对；EOF 或非预期值退出，只有精确 release 字符串进入删除操作。门闩只约束夹具删除阶段，不声称阻止 loader 或子进程初始化。 |
| 完成与清理 | 工作等待、正常清理等待、unwind 等待均保持 5,000 ms；成功必须满足原进程结束、Job accounting 成功且 `ActiveProcesses == 0`，之后才接受物理结果。 |

`CreateProcessAsUserW` 与属性所需的明确接口签名已对照包内 windows-sys 0.52.0 原始声明；公开契约见 [CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw) 与 [UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)。Windows 可能因权限、桌面访问、属性或启动失败而拒绝本候选；这些都仍是实际失败，不能转写成观测成功。API 自身可能临时启用调用所需权限，因此实际 child token 核对保留全部 privilege 属性，不为得到结果而删减比较字段。

现有 `JobObject::create` 的 `KILL_ON_JOB_CLOSE | BREAKAWAY_OK` 配置原样复用；本诊断脚本只执行四组内置删除操作，本包不增加对任意 descendant 或 breakaway 的资格声明。Drop 的回收失败日志不能作为成功证据。

## 原断言与回归门槛

`verify_v3_candidate.py` 证明整个 `run` 函数后缀逐字节不变，包括三 Rust context、两 cmd subject、五个相互独立的同 ACL 矩阵、最终主线程令牌回读和 fixture 关闭。完整 token 查询和 effective token 查询段不变；cmd 函数仅替换启动调用及 Job 字段访问，释放门闩、全部操作、退出码、原输出、清理、物理断言均完整保留。既有 `token_integrity_probe_tests.rs` 仍为实际 blob `fc9faa6d47ac5fdefa216affceb51a586f8e6b81`，原八行探针及其所有断言未改。没有新增测试或 ignore 属性，156 whole / 155 exact 仅是 roster 保留预期，不能当作本候选的 native 计数。

后续实际验证继续使用原测试 `token::integrity_probe::integrity_mechanism_probe_observation_only` 与原 workflow / 参数 / 预算。必须同时取得三组 `rust_before` / `rust_physical`、两组 `child_before_release` / `child_finished` / `cmd_physical`、完整五矩阵完成标记及原测试结果，才能接受新增观察阶段。所有正控制、原严格断言、原 whole 失败和 B11 退出条件继续有效。缺失任何行、启动失败、token 不同、超时或清理失败都不能计为通过。

## 本包已经验证的内容

14 个源码依赖逐字节匹配实际已发布 9cb 树；其中新增读取的 winutil 原件由完整 Git blob GET 取得，Git SHA 为 `45378b4bb527ce2b202913ab3b21aad9ef4b1828`。全部原树目录节点与根 Merkle hash 已离线重算，替换范围严格只有一个 leaf。补丁在独立临时目录正向、反向 `git apply` 完整字节相等。静态接口名称检查仅证明声明存在，不等同于 Rust 类型检查或 native 执行。

`source-map.json` 给出源码前后 SHA、依赖、实际发布身份和范围；`static-verification.json` 是离线 verifier 的完整结果。审查者可从包根运行 `python verify_v3_candidate.py`，只检查保存字节与本地临时补丁应用，不执行产品命令。本候选完成独审和根审之前不发布；历史 v2 和首次失败记录始终保留。
