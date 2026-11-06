# B11 MIC 补充审查：单独降低完整性级别是否遗漏了最小修复

**限定结论：生产 token 工厂没有显式降低完整性级别；已有 test-only Low 干预确实执行过，并在原线程 impersonation / fresh-path I/O 下留下了物理反例。Low token 能拒绝 Medium 外部对象的四类变更，却仍删除另一个 Low capability cohort 的外部文件和目录。因此，只把现有 token 降为 Low，不能闭合原 B11 的全部外部变更合同。这个结论不依赖“没找到 broker”的推断，也不是所有 token/API 组合不可行的证明。B11 保持 OPEN。**

本补充只读恢复已实际登记的历史原件，未启动 native、CI、私有容量、产品测试或工具链，未更改 token、权限、allowlist、测试、ref、PR、台账或已冻结报告。它与 V1 文件 helper 调用链审查一同构成最终 V2 审查；V1 原文和第一次便携恢复原件保持不变。99a 是本次固定的整合源码比较锚，不是对后续 ac18 格式化源的最新运行声明。

## 1. 生产工厂与历史干预分别做了什么

固定生产 `token.rs` 为 blob `8945d75fe172679479b738e6266cac99a6f7ed16`。工厂实际调用 `CreateRestrictedToken`，flags 为 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`；另设置 default DACL 并启用 `SeChangeNotifyPrivilege`。该文件唯一真正的 `SetTokenInformation` 调用设置的是 `TokenDefaultDacl`，没有 `TokenIntegrityLevel` 或 `TokenMandatoryPolicy` setter；已纳入来源清单的固定 Windows Rust 文件也没有其它这样的 setter。这只说明本仓库工厂的显式行为，不据此推断任意输入 token 的输出 IL。[S1]

历史探针 `token_integrity_probe_tests.rs`（实际 blob `fc9faa6d47ac5fdefa216affceb51a586f8e6b81`）先用同一个生产工厂和 cap_a 构造 token，再在 test-only 路径调用 `SetTokenInformation(TokenIntegrityLevel)`，设置 SID `S-1-16-4096`。它没有替换生产 flags。随后通过 `ImpersonateLoggedOnUser` 进入原线程，在执行文件操作前打开实际 thread token 查询状态，最后用原路径进行读、覆盖、新建、删除文件、删除目录。[S2]

native11 的完整原 token 行分别记录 host/current_strict 的 RID 为 12288，current_strict_low 为 4096；三者记录的 integrity attributes 为 96，mandatory policy 为 3。本补充保留数值，不擅自扩展其语义。Low 两行的 expected 与 effective 状态相等，仅覆盖 **RID、integrity attributes、mandatory policy 三字段**；它不是 user/groups/privileges 等完整 token 身份一致的证明。[N1]

## 2. 已执行的四操作及物理后态

主证据使用 native11 job `127606676952`。固定来源 authority 为 head `2980fa274c599bd07437a2f5915b86d858f89bcc`、checkout `53766cb836b198e2f928b949f148d7a2a10c0d21`、tree `9cb7302777ce018dd022086041c2225d1dd5c8dd`。这条来源关系来自既有登记包的固定 authority/source-map；本次重新计算完整树、核对其 14 份完整来源和探针/support 的实际 blob，没有重新读取 CI 或执行 Windows。[S2]

| 原件位置 | Low → Medium 外部对象 | Low → 另一个 Low cohort 外部对象 |
|---|---|---|
| 完整 row JSON 行 | native11 原 log 第 408 行 | native11 原 log 第 434 行 |
| 实际线程查询 | RID4096、attrs96、policy3 | RID4096、attrs96、policy3 |
| 覆盖 / 新建 | 均 PermissionDenied / Win32 5 | 均 PermissionDenied / Win32 5 |
| 删除文件 / 删除目录 | 均 PermissionDenied / Win32 5 | 两项返回成功 |
| 完整 finalized JSON 行 | 第 412 行 | 第 438 行 |
| 关闭观察句柄后的外部名称 | 文件、目录仍存在 | 文件、目录均不存在，NotFound / Win32 2 |
| retained 对象状态 | 外部五对象 pending0、links1 | 被删文件与目录 pending1、links0，其余外部对象仍在 |
| 外部对象实际 label | `S:(ML;;NW;;;ME)` | `S:(ML;;NW;;;LW)` |

两行中的外部读取均成功且内容为 original；覆盖失败后的内容仍为 original，新文件仍不存在。两行的 inside 控制也都完成了四项操作，但 **inside 父目录和四个对象都被探针显式标为 Low**。outside 使用不同的 cap_b；父级原有 broad logon/Everyone 许可并没有替换成人工 deny 来制造通过。[N1][S2]

这不只是 API 返回值或 AccessCheck 预测。support 的观察 handle 只持 READ_CONTROL、WRITE_OWNER、FILE_READ_ATTRIBUTES，不持 DELETE；它验证 handle 不可继承，并开启 FILE_SHARE_DELETE。实际变更使用 fresh path opens。完成时核对同一个对象 identity 与安全描述符，记录 DeletePending/NumberOfLinks，恢复幸存对象的原 label，然后关闭观察句柄，再按名称打开/检查对象。因此，Low→Low 的 pending1/links0 与最终名称消失共同构成物理删除反例。[S2][N1]

native10 job `127584591851` 的既有完整 log/XML 也恢复并核对：Low→Medium 的 row408/finalized433，与 Low→Low 的 row456/finalized460，呈现相同结果。本补充把它保留为另一轮原始观察，不把 native11 的完整 source authority 擅自赋给 native10。[N2]

## 3. 可以排除什么，仍不能排除什么

**可以排除“在其它机制不变的前提下，只降低现有 token 到 Low 即足以满足原合同”这一方案。** 原合同要求所有根外四类变更拒绝，不能只覆盖较高 IL 的对象。已有同级 Low、不同 cap cohort 的外部删除反例已经违反这一要求；无需新增一轮测试来重复发现它。

微软现有 MIC 官方原件说明，MIC 在 DACL 前评估，较低 IL 对较高 IL 的写入受限；未显式标记的对象按 Medium 处理。由此推断，若把 token 降到 Low，却保持普通 Medium/未标记允许根不变，就存在合法根内写入被拒绝的具体兼容性风险。**这是由官方合同与当前候选结构作出的推论，本次没有把它登记成新的生产失败。** 历史探针为了研究机制，主动把 inside 标 Low，所以它的 inside PASS 无法消除这一风险。[M1][S2]

| 备选 / 兼容性事项 | 当前证据状态与必要边界 |
|---|---|
| Low token 的 raw-thread 文件操作 | 已实际观察；只含上表固定夹具和三字段 TokenState 查询。 |
| 不重标现有允许根的正常 I/O | **UNKNOWN**。本 probe inside 人为标 Low；未接受原始 Medium/未标记根的完整正控。 |
| loader、正常管道、desktop、ConPTY | **UNKNOWN**。没有用上述两条 Low row 证明这些路径可用。 |
| 继承句柄、复制/派生 token、已开句柄、任意 child 与正常后代寿命 | **UNKNOWN**。原八行 phase 明确 descendants_spawned=0，观察 handle 本身不可继承。后续 Neither 模块是另一阶段，不能用它替代 Low 进程/后代资格。 |
| 更低的 Untrusted、改 mandatory policy、多个机制组合 | **UNKNOWN**。未提出或执行这样的完整候选；没有全平台不可能性结论。 |
| 重标所有允许根 / 修改外部 SACL | 这是新增对象权限操作，不能由这次只读审查授权；即使允许根标 Low，也没有解决已观察到的 Low 外部 cohort 删除。 |
| 现成 FsHelper、no-follow 与 handle handoff | 确实存在，但仍是显式请求入口；没有据此证明原 raw-token / 任意 native child 的操作必经它。详见 V1/V2 调用链审查。 |

若未来出现保留原合同的具体组合候选，应明确 token 的实际 IL/policy、已开与继承对象、允许根及所有目标对象的授权规则，并在原断言、预算、后代合同不变的条件下取得对应原生证据。此处只是说明尚缺哪些证据，没有安排新的诊断轮次，更没有将未经执行的候选视为已通过。

## 4. 恢复、不可解析记录与资格限制

完整历史包来自 actual registry `37c1d61dd84102158caaa2d5801345639334c8bc`。本次完整 GET 两个原 base64 blob `6d2e9ffd69f0b3b23605cb532f379c5fb467811c` 和 `026913ec2128ee45ae7c914226b79dae4891cb15`，恢复 gzip 599,347 B、SHA256 `a90cb14087ee364f8f6c0fec1ad40fa442e4434b5598acee52b973a5079e2d21`。41 个归档成员共 3,882,455 B，逐一与实际 manifest `bb8b6b10a9f325396e35a336ac592b4cc1485669` 的字节数、Git blob、SHA256 和 mode 相等。原 native10/11 log/XML 都包含在其中。[C1]

解析器只接受从行首开始、整行能作为一个 JSON 解码的 row/restoration/finalized 记录；没有拼接被其它测试输出打断的行。按这个明确规则，native10 完整计数为 7/5/6，另有 6 条不可用 marker 行；native11 为 7/8/8，另有 1 条不可用 marker 行。这是 **该解析规则的记录数**，不是新增用例分母或全阶段通过率。实际选中的 native11 两条 Low row、对应 restoration 和 finalized 全部完整，restoration 对象与 finalized 对象逐项相同。完整 raw 及不可用行身份均保留。[C1]

此前尝试将 native13 的一个归档成员计算 hash 当成 standalone Git blob GET，得到 404；失败原件保存在 `fetches-01.original.json`。该失败未被重写成成功，也不作为本补充原 log 证据。最终使用的是已注册历史包完整恢复的 native10/11 原件。原 native13 机制结论仍由 V1 固定来源单列保留。[C1]

最终离线入口为：

```text
python mic-addendum/verify_mic.py <解包根目录>
```

它恢复/验证旧归档全部 41 成员、重算 9cb 全树、核 14 份固定来源、生产和 test-only token 差异、两次完整原 log/XML，以及选中物理记录。最终 `verification-02.stdout.json` 对应 exit0、空 stderr；此前第一次成功输出也保留，第二次仅增补观察 handle 锚点、restoration 对象对等检查和三字段边界。它不运行产品或原生代码。独立同事窄读上述四条原 JSON 和 probe/support 实现后确认这个限定结论，意见全文单独保留；不把该意见扩展成新的产品资格。[C2]

### 固定来源

- [S1] `../SOURCE_BINDINGS.json`、`../source/codex-rs/windows-sandbox-rs/src/token.rs`、两份完整固定树。当前源比较锚为 67 与 99a；不声称新 head native 结果。
- [S2] `probe-tests.rs`、`probe-support.rs` 及 `probe-source-fetches.original.json`；旧包的 `v3/source-map.json` 与完整 9cb tree。生产文件在 native token blob `b22acb5556f6af3b4c250a2441f161ee448ea1c1` 中是完整前缀，差异只为 cfg(test) 模块追加。
- [N1] `native11.test.log.original`、`native11.test.xml.original`，完整身份和逐行身份在 `verification-02.stdout.json`。
- [N2] `native10.test.log.original`、`native10.test.xml.original`，仅保留其实际历史观测范围。
- [C1] `prior-strict-registry.original.json`、两份 `archive-part-*.GET.original.json`、`archive-member-manifest.GET.original.json`、完整失败/成功 GET 原返回。工具返回不是 HTTP wire capture。
- [C2] `verify_mic.py`、两次 stdout/stderr、`peer-review-message.json`。
- [M1] [Microsoft Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)，已固定于 `../recovered/microsoft_primary_1.original.txt`，实际 blob `ee76e348897b7612fa88c13102f7ec0a144e7a6d`。本次使用既有完整原返回，没有另查新页。

