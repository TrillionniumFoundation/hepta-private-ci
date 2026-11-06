# B11 hostNeither v3 独立审阅

**结论：STATIC_ACCEPT_EXACT_CANDIDATE_NOT_COMPILE_OR_NATIVE_QUALIFICATION。** 对固定候选 `8c16416c185f17871c25139bc16c6fd112b5fd41` 未发现阻止此次仅供测试使用的启动修正发布的源码问题。候选为 26,205 字节，SHA-256 `c48d7a3917ca0bd8dda236d3773c0351a39272bbc277b8186bde7467035580ff`。这不是 Rust 类型检查、格式化或原生执行结果，**B11 仍为 OPEN**。

## 原失败与本次修正

native11 暴露了 v2 候选及先前静态审阅遗漏的生产前提：普通主令牌与仅禁用特权的派生令牌都没有 restricting SID，而 v2 调用了生产 `LaunchDesktop::prepare` 路径。该路径先执行 `private_desktop_restricting_sids`；原日志出现 `GetTokenInformation(TokenRestrictedSids) size query failed: 122`，因此未到达实际 `CreateProcessAsUserW`。原件只有三组 Rust 前后观测，没有两组 cmd 或五矩阵完成资格。日志没有记录 needed 的实际数值，不能补造该数值。

v3 只改变 `token_neither_privilege_observation.rs` 一条源码路径、五个 hunk。生产 `desktop.rs`、`token.rs`、`process.rs` 和入口约束保持原字节。原 `token_integrity_probe_tests.rs` 保持 `fc9faa6d47ac5fdefa216affceb51a586f8e6b81`，原八行观测、断言和清理均未改动。

## 创建与清理审阅

| 阶段 | 独立核对 |
|---|---|
| 两个 cmd subject | 都经过同一个局部 `spawn_observation_child`；复用原 `make_env_block`、`argv_to_command_line`、`to_wide`、`ProcThreadAttributeList` 和 `JobObject`，使用同一组三个 creation flags、同一个默认 desktop 字符串 |
| 创建之前 | Job 和属性列表均有作用域所有者；设置 JOB_LIST 与仅含私有 stdin reader、输出文件的 HANDLE_LIST。任一步失败都在实际创建之前返回，已有所有者负责关闭资源 |
| FFI 缓冲区 | 可写 UTF-16 command line、环境、cwd、desktop、startup record、属性列表及其向量均活到调用结束；参数指针类型与归档的 windows-sys 0.52 声明一致 |
| 创建返回 | 失败时立即保存原 Win32 错误；成功到构造 `OwnedChild` 之间没有可失败工作。Job、hProcess、hThread 直接进入所有者，没有数字 PID 重新查找或无 Job fallback |
| 实际子令牌门闩 | 私有 writer 不在继承列表中且不可继承。父进程先查询实际 hProcess 的主令牌，完整身份和特权与该 subject 一致、类型为 Primary 后才写入释放串；EOF 和错误字符串不能触发删除 |
| 正常与错误退出 | work closure 中的错误仍执行关闭 writer、Job terminate、等待和 accounting 查询。stdout 读取或日志写入失败会落入未 cleaned 的 Drop。成功资格要求正常清理 wait 为 WAIT_OBJECT_0、查询成功且 ActiveProcesses 为 0 |
| 等待与最终物理结果 | 原 work、正常清理、异常 Drop 三处 5,000ms 原样保留；只有成功清理后才进入矩阵物理 finish。异常 Drop 为有界尽力清理，清理失败不会被标为成功 |

整个 `run` 函数逐字节相同，包含原三个 Rust 上下文、两个 cmd subject、五个独立四格矩阵、身份/特权核对、Both 合法 I/O 控制和末尾有效令牌恢复核对。cmd 中除启动调用与 Job 字段访问外，其余门闩、命令、结果解析及物理断言亦逐字节相同。没有增加 test/ignore 属性，没有改断言或把 Neither 改为必须成功。

原 Job 的 breakaway 设置未改变，固定脚本只用 cmd 内建命令；本观察不能扩张为恶意后代逃逸或整个产品生命周期资格。创建 API 本身也没有新增总墙钟超时。Windows 的运行时权限、desktop 可达性和子令牌实际属性仍须由下一次真实执行给出结果，不能预先宣称成功。

Microsoft 的 [CreateProcessAsUserW 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)说明，调用可能需要特权并可在调用期间启用所需特权。因此保留完整 actual-child privilege 比较，不在不匹配时放宽门闩。[UpdateProcThreadAttribute 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)要求属性值的存储活到属性列表销毁；现有封装拥有对应向量，局部启动器保持其生命周期。

## 独立证据与验证范围

本审阅独立完整 GET 并逐字节比较了全部 14 份原始 blob 和实际候选 blob；另取两份不可变 authority commit 原件，确认源 tree 为 `9cb7302777ce018dd022086041c2225d1dd5c8dd`。独立验证器从完整叶子映射重建全部 1,571 个目录、10,589 个叶子，与实际 source root 相等；仅替换这一叶子得到 `9a804c7b6e0dd554cdb435f41e06c5c689fffaaf`，其余 10,588 个叶子不变。

`verify_independent.py` 使用自己的逐 hunk 字节应用与逆变换，完整恢复前后两个文件；还验证上述保留块、实际 GET 回执、来源树与 native11 缺失的 cmd 观测。执行退出 0，原始 stdout 是 `verification.stdout.json`，stderr 为空。验证器只读文件，不联网、不运行 Git、不编译或执行产品代码。重放时把完整 v3 源码证据目录作为唯一参数。

审阅原件由 v3 证据所有者统一实际物化与 full GET 后登记；仅凭本文件的计算哈希不冒充实际登记结果。后续出版或自动 CI 启动也不改变此处“静态通过、原生待证、B11 OPEN”的结论。
