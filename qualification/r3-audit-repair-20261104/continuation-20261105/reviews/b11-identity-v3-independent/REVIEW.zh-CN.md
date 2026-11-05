# B11 ACL V3 同对象修复独立静审

**结论：静态接受，等待原 Windows 编译、具名用例和物理负控；B11 仍为 OPEN。** 未发现必须先修正的 FFI、资源所有权或负控构造问题。本审没有修改产品源、运行 Rust/Windows 或移动引用。

## 源码与权限边界

审查固定在专用 Draft 的 `7e0b2303ed0242d83bf56202e8ffb17f5c856186`。两后像分别为 `da5346c220c41cf0c83f62b596132c74c02284d8`（acl_deny）与 `ec0264a7615097bec1b554cb60918b4f4662eec2`（acl_tests）。完整补丁为 `a0784b109767396ddb452ca6d5798491b8ffeabe`。

原 READ_CONTROL 查询和完整 deny 的提前返回保持原字节。只有实际修复会新开 READ_CONTROL、WRITE_DAC、READ_ATTRIBUTES 句柄，拒绝最终重解析点，并比较两个仍存活句柄的卷号与全部 128 位 ID；通过后才执行原 ACL 写入尾部，setter 使用这个已核验句柄。

这确实收窄了修复兼容范围：属性读取不获准、文件系统不支持非零 128 位 ID、最终路径是重解析点时均拒绝。它不证明祖先路径保管权，也不与其它 DACL 写入者串行化。两处原目录 ReOpenFile error 5 的具体内核原因仍未由现有日志唯一说明，不能把本候选写成已实证根治。

## FFI、线程恢复与控制有效性

已亲读 windows-sys 0.52 的结构和函数声明，核对当前原 Cargo 的五个所需 Win32 feature。所有新字段、指针、HANDLE、BOOL、u32 参数一致。当前 token helper 返回 owned process primary token，所持 QUERY 与 DUPLICATE 权限符合该 primary-token 的 impersonation API 要求。这是源码接口核验，不是编译结果。

no-WRITE_DAC 控制只限制新建 token 的特权，不改变进程 token 或原生产 SID 策略。必须先证当前测试线程未 impersonate，随后实际 READ_CONTROL 与 RC|READ_ATTRIBUTES 打开成功；拒绝必须是生产 acquisition 的 CreateFileW 精确 error 5。原六条断言保留。同步普通 test 的错误或 panic 路径先析构 Revert guard，再析构更早创建的 RestoreDacl；正常路径也显式遵守此顺序，Revert 失败直接终止，不让受污染线程继续。原 RestoreDacl 是 retained handle 设置原 DACL 后检查 API 成功，未新增整个 security descriptor 的恢复相等证明。

新增控制真实保留原句柄、改名原文件/目录、在原路径创建替换对象。正例要求两对象 DACL 不变，随后可通过原对象新名字修复。负例仅移除 ID 相等拒绝，必须在第一文件行实际输出 `returned_ok=true replacement_changed=true original_changed=false`，并在第 597 行替换对象 DACL 断言普通失败。准备失败、超时、其它 panic 均无效。目录行由正例覆盖，不能把先终止的文件负控算作目录物理结果。

## 已做与待做

独立执行 8 条隔离 Git apply/check，逐字核完 positive → negative → restore → inverse 四阶段两路径。作者 13 个已上传回读对象均重新核本地长度、SHA256 和 Git SHA；原其它六测试及辅助实现、no-op 原六断言、四段生产逻辑保持确认。

下一门仍是既有 Windows MSVC 原目标 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests`。其它输入不变时预期 156 名；原严格删除失败、host control 和全部旧断言均须显式保留。负控和正例目前均未执行，不从静审、artifact 总数或后续缓存 PASS 提升资格。

完整逐项依据、官方原文身份、源与补丁哈希见同目录 `independent-review.json`；实际重建命令见 `static-reconstruction.json`。
