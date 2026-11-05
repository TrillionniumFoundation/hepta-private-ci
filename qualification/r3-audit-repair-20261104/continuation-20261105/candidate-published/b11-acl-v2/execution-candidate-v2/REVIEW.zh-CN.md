# B11 ACL 更新与失败契约：最小待验候选

候选基于诊断 Draft #4884 的实际 `3a407dde2727de2176b02d3cb2c3883fbb771f60`，没有发布、没有 Windows 执行。本次共四条路径、15 行新增与 8 行删除。三个 Rust 原像与主产品 5b、native4 工件中的 source-leaves 全部相同；专用 workflow 原像为 `757e0eb43b2583604569fd51fac3aee4828899a5`。

## 原 13 个失败应分开解释

| 数量 | 原失败性质 | 可以下的结论 |
|---:|---|---|
| 4 | 三个 ACL 测试和一个 partial-delete 测试返回 native API error 5 | 两案在 `SetSecurityInfo`，两目录案在 `ReOpenFile`；后续物理断言尚未到达，不能预设同因 |
| 1 | 当前 strict token 的 broad-ACE outside file/directory 删除成功 | 已有原物理越界，写入与创建被拒绝不能补足删除隔离 |
| 1 | 四格 fixture 的普通宿主 Neither 路线仍删除成功 | 在 current token 构造之前失败，属于宿主前提失败，不能计为第二个 strict token 结果 |
| 1 | legacy capture 原断言期待旧 `SetNamedSecurityInfoW` 文案 | 实际路径 context 正确、spawn marker 为 false、底层为 `io::Error` 的 OS 5；名称断言过时 |
| 6 | 后继 legacy case 获取已中毒的共享测试锁 | 本次没有独立执行到其业务检查，不得当作六个新的隔离缺陷或通过证据 |

完整分类保存每个原失败 block 与行号。native4 总数仍为 140 PASS、13 FAIL、2 ignored；8 行机制 probe 的 PASS 只证明其 fixture/物理观察完成，B11 仍开放。

## 两个独立修改及其资格

**ACL 更新句柄。** 保留最初只申请 `READ_CONTROL` 的对象查询和完整 deny/no-op 早返。只有确需更新时，仍在同一 retained object 上调用 `ReOpenFile`，将请求从 `WRITE_DAC` 改为 `READ_CONTROL | WRITE_DAC`。这样更新句柄同时保留此前查询已需要的读取权限。共享方式、backup semantics、DACL 构造、SID/mask/继承范围、`SetSecurityInfo` 及错误传播均不动。原 `existing_native_deny_does_not_require_write_dac` 的真实拒绝控制仅使用相同的新组合，仍必须得到 access denied；其后两次 no-op 和 DACL 字节相等断言原样。

这是一条权限组合修复候选。Microsoft 文档明确 `GetSecurityInfo` 查询需要 `READ_CONTROL`，DACL setter 的基本访问权为 `WRITE_DAC`，并说明 `SetSecurityInfo` 会传播可继承 ACE。文档没有证明本次两个目录 `ReOpenFile` 的 error 5 必由缺少 `READ_CONTROL` 引起。因此不能把静态合理性称为四案已修，也不虚构 `ReOpenFile` 不支持目录：官方文档明确支持 `FILE_FLAG_BACKUP_SEMANTICS` 的目录句柄。

**Legacy 失败契约。** 保留精确的外层路径 context 和 `process-started` marker 必须不存在，将底层错误检查改为真实类型 `io::Error` 且同时要求 `PermissionDenied` 与 `raw_os_error == 5`。这不接受任意错误，也不允许子进程启动。实际原 failure 已证明只有旧 API 名称字符串不同；原 fixture 对 named setter 拒绝及新开 `WRITE_DAC` 句柄被拒绝的两个物理前提均保留。该小片纠正可观察错误契约，不能修复 strict token 删除隔离。

**专用执行入口。** 只在原 `pull_request.paths` 增加上述三个源路径。原 Windows MSVC outer unit target、完整测试范围、所有 args、120 分钟 job 预算、runner、secret 引用、原错误退出码和完整工件保存逻辑逐字不变。没有新的 test、skip、retry 或诊断 mode。

## 必须保留的原生判据

在该 Draft 的新真实 head 运行同一个 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests`。四个 ACL 控制应实际进入并通过原 read/write/no-op/DACL/实际拒绝断言；尤其 owner-rights 的写权限拒绝必须真实成立，不能把 no-op 转成 silent repair。两个 legacy setup-failure case 应验证 typed OS 5、原精确路径 context 与 marker=false；解除锁中毒后，其余 case 的真实结果另行判定。目录 `ReOpenFile` 若仍 error 5，必须原样保留，并据该端点继续处理，不能以另外两个 setter case 的通过代替。

原 strict broad-ACE、原四格与 legacy strict 断言以及完整 8-row probe 均未改。此 ACL 候选本身不解决 token 删除模型，也不改变宿主四格 Neither 前提；不得要求整个 target 在尚未修复这些问题时显示虚假的通过。

## 静态核验与资料

两套云端隔离 Git 往返分别精确重建三源和四路径执行包；原生产除访问掩码及注释外逐字相同。三个 V1 后像在 V2 未再修改，workflow 仅新增三条 path。没有运行 Rust 编译、formatter、Cargo、Bazel、Windows API 或修改任何宿主 ACL。

原始证据：native4 job `127352234293`、完整 test.log `af35e023f86c2a9216f0bb2ce787dc9e8226a405`、source-leaves 与无损 ZIP 均已另行冻结。

官方依据：

- [ReOpenFile](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-reopenfile)
- [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
- [SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)
- [SECURITY_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information)
