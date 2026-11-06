# B11 native13：宿主 ACL 前提通过，严格删除边界仍失败

**B11 OPEN。原完整目标仍为 147 通过 / 7 失败 / 2 忽略，整个 job 仍 failure。** 两个宿主前提已通过并让原测试走到了真正的受限主体四格断言；不能给这两个仍失败的原测试追加 PASS 数。原子门、失败、超时与源码恢复规则全部保留。本包只读取原自动工作流，没有 dispatch、rerun、cancel、源码或 timeout 变更。

## 实际来源

| 项目 | 固定值 |
|---|---|
| Run / attempt | `42140578464` / `1` |
| Job / runner | `127639593751` / `1000006705` |
| Job 时间 | 2026-11-06 `00:58:23Z`—`01:05:37Z` |
| Head | `daa21e7a6a9b19e74b61c6bbdc2c813f9fd35a42` |
| 原实际 checkout | `f8e97e161c7ad87bd1e242363901a0852170483c` |
| 实际 tree | `fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae` |
| Head parent | `87b8603f21e52063ed54ce89cba26756a3efaab7` |
| Merge parents | `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`、上述 head |
| 新 test-only helper | `47baf88cf0a30521c3b2eb033dc3ee65056ed2f6`，23,135 B |
| Artifact | `13468391745`，2,313,119 B |
| ZIP SHA-256 | `19f458b8bfcb54afa14d306ae308343118ac37007896f76c74fb01cf28889309` |
| 完整 job 原件 | 519,728 B；519,726 字符；3,371 个 CR 全保留 |
| Job log SHA-256 | `970bc500ab8b44912f06757eb9df84f148e1684b0b2d0ade3ecc86d6d0a3936f` |

第一次实际 API 观察在 01:08:26 UTC，已经是终态，没有虚构运行中的初始快照。source-filtered run discovery、run/jobs/artifacts API、head 与 merge GET、完整 MCP log 返回对象和解码原字节均保存。MCP 返回对象序列化不等于 HTTP wire capture。下载授权 URL 不进入登记包。

84 个 ZIP 成员的 CRC、长度、SHA-256 全核；未压缩总字节 3,058,949。18 个 base64 分片无损保留整个原 ZIP，包含所有 raw logs、XML、7 份 compact、原正反例全源码与 guard 记录；不声称每个 ZIP 成员分别登记成 Git 对象。原 source-leaves 实际为 **80**；加 helper 原 11 pins 后 **84** 条去重路径，用 18 个完整祖先 tree 节点的 Merkle 证明绑定 actual tree。不是沿用 native12 的 79/83 常数。

## 原门核验

| 范围 | 本轮实际结果 | 资格范围 |
|---|---|---|
| 原完整库 | 两批 92/0/0 + 55/7/2；Bazel 3，XML/actual TestRunner 1 | 整体不通过 |
| 原四个 exact 正例 | 每例 1 passed / 0 failed / 0 ignored / 155 filtered | 四个原子门 |
| 原物理 identity negative | 0/1/0/155；XML 101、Bazel 3，`acl_tests.rs:597:9` | replacement 改变、原对象未改变的预期反例 |
| 源码恢复 | positive/negative 全字节、原单一替换、finally 精确还原全部核对 | 正常恢复；不证明强制取消恢复 |
| 原 unfiltered setup helper | 21/0/0/0；原 11 pins 与实际 checkout 相等 | helper 子门，非完整 read/loader/后代合同 |
| 7 compact | 全部解析到 EOF；每份实际 TestRunner local / 非 cache / 300,000 ms；7 XML wrapper 分开记 | 原 whole/helper argv 不加过滤，exact 名称与次数保留 |

9 个 collector manifest 的文件 hash、source commit/tree 及唯一受控 dirty 区间全部核对。完整原 index/lock 字节没有另存，保留的是原流程稳定指纹；不能把它们称为全字节归档。

## 两个宿主前提与四格真实后态

每个矩阵有四个 route。表格单元同时表示 file 与 directory 的释放句柄后物理存在性；“已删”依据保留对象与释放后路径/身份检查，**不是 cmd 的 ERRORLEVEL**。

| 实际主体 / 原日志标签 | Neither | TargetOnly | ParentOnly | Both |
|---|---|---|---|---|
| Rust 非特权宿主控制 `nonprivileged-acl-control` | 未删 | 已删 | 已删 | 已删 |
| 原 restricted Rust `after-revert` | 未删 | 未删 | 已删 | 已删 |
| CMD 非特权宿主控制 `nonprivileged-acl-control-cmd-done` | 未删 | 已删 | 已删 | 已删 |
| 原 legacy restricted CMD `legacy-child-done` | 未删 | 未删 | 已删 | 已删 |

48 条原 retained-object dump 均可完整解析：每矩阵 12 个对象（四 route × file/directory/parent），实际 identity、DACL、pending、links 与释放后物理记录全保留。四套矩阵按 route/kind 的实际 DACL 字节相等；ACL header 和每个 World SID ACE 的 type/mask 均核对。目标缺 DELETE 的格有真实 deny `0x10000`；父目录缺 FILE_DELETE_CHILD 的格有真实 deny `0x40`。已删目标的 pending=1/links=0，未删目标和父目录 pending=0/links=1。不是把“未配置 deny”误当成机制解释。

Rust 宿主原 native errors 为 Neither 双 `PermissionDenied / OS5`，其余三格全部成功；原 host errors、physical assertions 和线程恢复均已越过。原 restricted token 的 `[cap_a,cap_b,logon,everyone]` membership 是 `[true,true,false,false]`，最终在 **token_tests.rs:573** 的四格全部拒绝断言失败。原 inside 合法删除和 ambient file read 内容断言排在该位置之前且已执行通过，这是固定源码与后续失败位置支持的窄推断，不虚构额外 raw read receipt。

CMD 控制的实际 primary child token 与单独完整观测的 expected record 全相等，stdin 放行前完成该 gate。实际 `work_error=null`、`exit=0`、`terminate_error=null`、`cleanup_wait=0`、`accounted=1`、`active_processes=0`；`ACL_CONTROL_INPUT_RELEASED` 恰一次，四次原操作及 MATRIX_DONE 全在。原控制脚本字节作为 gate 后的完整后缀执行，私有 setlocal 在原脚本前 endlocal；仍是原 `/d /c`、cwd/env 语义和 5 秒工作预算，正常 owned-Job 清理另按原 5 秒完成。

该 child gate 只阻止 owned fixture 删除动作，不能称为“进程启动前挂起”。控制输出打印两次 Access is denied，但全部 FILE_RC/DIR_RC 仍为 0；物理断言才是本包采用的成功/拒绝 oracle。原 legacy 路径在 **delete_permission_tests.rs:100** 的 outside 全未删断言失败，之前的原 allowed-file/allowed-directory NotFound 与原 exit/markers 检查已完成。

## 并发原输出的证据边界

新增 `ACL_CONTROL` 共 5 个 marker：两个 subjects、child_before_release、child_finished 共 **4 条完整 JSON**；Rust `rust_before` 的第 298 原物理行被其它 test 输出插入，标为 **UNPARSED**，不拼接或删除插入文本。两条 subjects 完整显示 identity/groups/restricted SIDs/IL/policy/session/app-container 相同，控制 token 只保留启用的 SeChangeNotifyPrivilege。

Rust effective token gate 的资格来自另一种明确证据：固定 47baf helper 实际调用 OpenThreadToken，检查实际 identity/privileges/type/impersonation level 后才返回 guard；原测试随后完成 host OS5、物理和恢复断言，并继续到 restricted 573 断言。因此可以确认该固定 guard 执行成功，但**不能说完整 Rust before token 原 JSON 已独立解析**。

旧 v3 neither-privilege probe 仍实际 `ok`、complete。其初始 subjects prefix/JSON 在本轮也被交错，完整可解析的是 **13 JSON + 1 plain-text complete**，而非 native12 的 14 JSON。三份 Rust actual-before 与两份 child-before 都完整；本包直接用这些实际上下文的 token 比较 identity/privileges/type，而不重构损坏的初始 expected record，也不搬用 native12 的完整行信用。旧八行 row/restoration/finalized 同样逐行记完整或未解析，保留原字节。

旧 v3 的三 Rust、两 owned cmd 物理观测继续符合全特权集合干预：普通 Neither 真删除，DISABLE_MAX_PRIVILEGE 后 Neither 未删，另外三格删除。仍不能单独归因于 SeRestore。通过的 probe 没有输出新五组的 60 条逐对象 ACL dump；不要与这里两个原失败测试保留的 48 条 dump 混为一谈。

## 剩余失败与范围

7 个原失败全部保存，当前分类是 **3 个独立 strict 断言 + 4 个原共享锁 poison 后果**：broad identity outside-delete 在 token_tests.rs:434，restricted Rust 在 573，legacy CMD 在 100；其余 4 个仍在 unified_exec/tests.rs:62 报原 poison。原断言没有放宽，production token/flags 未改，正常 native source roster 未减。

当前工作把不合适的 elevated-host ACL 前提修正为保 identity 的非特权控制，使严格机制缺口可直接观察。它不修复 ParentOnly/Both 的真实 outside 删除，不关闭完整 ambient read、loader、任意后代/breakaway、取消、生命周期或产品隔离。正常 owned-child cleanup 不能外推任意后代安全。B11 必须保持 OPEN。

## 离线重放

Python 3 与 zstandard 已安装后，完整登记目录内执行：

```sh
python verify-native13.py.source.txt --output new-result.json
```

本地对应文件为 `verify-native13.py`，仓库对象用 `.py.source.txt`。脚本只重建原 ZIP、验证原件与固定门；不访问网络、不写 ref、不运行产品或 native。已有结果不会覆盖。`native12-to-native13-verifier.patch` 保留全部 verifier 变化，`VERIFICATION.json` 为本轮实际 exit0 的确定性结果。
