# Windows 错误链修复：固定 340/ff2 原生资格与失败原件

## 结论

`SetupErrorReport` 新增的两个用例，已经在真实 Windows、非缓存的 `//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests` 执行中各通过一次。新增错误链也实际暴露了底层 `SetSecurityInfo` 错误 5 和状态文件解析 EOF。整套 Windows library 与 Core 目标仍失败；本包没有给予它们整体通过或 blocker 闭合资格。

这项资格只属于 PR #4913 的旧 head `340fbc0629d27e3a2bda7c6971be25c60b3bf2bc`，实际 checkout 为 merge `ff2b873c8b907e1e86b1a728c2c18552edfbd0ed`，tree `78b817fec87e593e0a0f6357d84f895b8574bde5`。实际 merge parents 是固定 base67 与该 head。后续格式提交 18bb 的原生资格另行取得。

## 原件和来源

| 原件 | 精确来源与范围 |
|---|---|
| Windows shard4 | run `42158689226` / job `127703396792`，终态 failure；完整 decoded console 1,550,020 B 与完整 MCP 返回对象均保留，包括 4,671 个 CR |
| Windows shard2 | 同 run / job `127703396875`，终态 failure；完整 decoded console 521,525 B 与完整 MCP 返回对象均保留，包括 4,331 个 CR |
| shard4 官方 artifact | `13477083714`，5,531,760 B，43 成员，官方 SHA-256 `70569eff66484a837e89fbe012553bbda2244c11a432d33cdc41308f4b624707` |
| shard2 官方 artifact | `13477309997`，5,084,766 B，93 成员，官方 SHA-256 `aa4588b3a4a8417f52b13846bb320ddba86aba69f5b060577ca6d017ede7d9f4` |
| API 切点 | 从根保存的 1,393,234 B 原包 `c10b5e771f406cc987b8589f3d8cc5ed07aa4c48` 提取全部六个 Windows records，完整保留每个嵌套 MCP 原返回与 parsed 对象；未重新查 CI |
| 源码 | 实际发布 API 与 head/merge 原件；两生产叶 `37aa38d`、`505be92` 的原字节；固定 `lib.rs` 明确 `setup_error` 模块受 `target_os = windows` 限定 |

两份官方 ZIP 全字节保留；每个成员均核 CRC、长度、Git blob 计算值和 SHA-256。四个 retention manifests 的全部 listed files 与原件相等，source 均为 ff2/78 且 tracked worktree clean。ZIP 内其他目标和全部尝试一并保留，但本包仅对本节明确的 Windows library/Core 目标作执行关联。

“完整 MCP 返回对象”是工具返回对象的 JSON 序列化，不是 HTTP wire。临时下载签名 URL 不进入本包。完整日志和 ZIP 原件没有经过摘要替代或行尾规范化。

## 新增用例的限定原生接受

原 Windows library `tw.exe` spawn 序号 `83657`，runner `local`、`cache_hit=false`、实际预算 `300000 ms`、目标整体 exit `1`。后续 `xml.exe` 序号 `83983` 是生成 XML 的辅助进程，不能多算一次测试。

- `setup_error::tests::typed_setup_report_preserves_code_and_message_through_context`：原 raw log 与 XML transcript 各恰一条 `ok`。
- `setup_error::tests::untyped_setup_report_preserves_context_chain_and_os_error`：同样各恰一条 `ok`。

该单次目标的完整 raw log 为 38,780 B / SHA-256 `10e0859a9beb93bbb75d153e27fe466cc7f7981855597f64333164a5f8c5e54c`；完整 XML 为 39,205 B / SHA-256 `47cc530b61df587131535ca004a831ae8d041456e6d093f83afc7743a26bffe8`。二者分别与 XML 生成进程的输入、输出 digest 和 size 全等；原测试 exit 与 XML 的原 exit 参数相等。

整个 library 分两个 libtest 批次执行：89 通过 / 3 失败 / 0 忽略，以及 52 通过 / 10 失败 / 2 忽略，合计 **141 通过、13 失败、2 忽略**。原 13 个 failure headers 全部保留。其中六条是前置测试锁被 panic 毒化后的 `PoisonError`，不能解释为六个独立产品根因。另有 ACL 错误、外部删除及原 host 前提失败；本包没有更改那些断言，也不把另一 #4884 诊断分支的资格移到此 source。

## Core 全部尝试与新错误链

Core 的 16 个 shard 共执行 19 次真实 `tw.exe`，全部 local / noncached / 原 `900000 ms` 预算。十九个 `xml.exe` 只作 XML 生成。保留的四次失败分别为 shard1 的首尝试，以及 shard7 的三次尝试。

| Core 原尝试 | 原 libtest 结果 | 限定事实 |
|---|---:|---|
| shard1 attempt1 | 61 P / 1 F / 3 I | `v2_residency_reload…owner_preserves_stricter_child` 报 `agent thread limit reached`；后续原默认重试通过，首败仍保留 |
| shard7 attempt1 | 69 P / 4 F / 5 I | 直接与 managed deny-read、metadata 和 outside-writes 用例失败 |
| shard7 attempt2 | 70 P / 3 F / 5 I | 原 state 文件 `deny_read_acl_state.json` 报 `EOF while parsing a value at line 1 column 0`；outside-writes 此次通过 |
| shard7 final | 69 P / 4 F / 5 I | 原失败保留，整个 Core 目标失败 |

新格式化错误链明确显示 `apply deny-read ACLs → apply deny-read ACE → SetSecurityInfo …: 5`。状态 EOF 出现在一次 attempt2 用例中，日志与 returned error 各记录一次，并非两次独立故障。底层 ACL error 5 和 JSON EOF 分别列入核验结果；不能用后者解释前者。

既有 `deny_read_state` 的直接 `fs::write` 和缺少完整事务锁，为截断窗口及 lost update 提供源码层面的修复方向；当前原件没有实际 writer/PID/时序，尚不能证明本次 EOF 的唯一来源。修复候选由另一路独立处理，不能在这里把推断写成已经确认的并发事件。

## compact 重试边界与已更正的取证假设

两个 compact 全流分别解析 89,912、87,267 个记录。固定 Bazel 9.3.0 的 `CompactSpawnLogContext` 原源码表明：普通文件按 `execPath` 缓存 entry ID，后续同路径直接复用旧 ID。原 Core 的三个重试记录确实复用了首尝试 log/XML 的摘要。

因此，正式关联文件是 `actual-test-runner-bindings.v2.json`：**17 个首次或唯一尝试的摘要相等；三个 Core 重试不能宣称取得了新鲜的逐次 compact 文件摘要。** 重试关联依赖原 retention 文件名和顺序、同 target/output path 的唯一前序 tw/XML 配对、原 exit 与 duration，以及完整原 log 与 XML transcript 相等。XML 对非法控制字符的实际问号替换被显式核验；原 log 没有被修改。

初版把旧摘要错误映射为后续尝试的脚本和结果作为 superseded 历史保留。随后检查原 libtest 结果发现该假设与后续 exit 不符，已经纠正；它不是新的 native 失败，也没有被用来赋予资格。正式 v2 核验要求 20 份关联日志互不重复，三次重试的旧摘要必须明确不相等。

## 复验与交付边界

运行 `python3 verify_native.py --root <恢复目录>` 仅解压原 ZIP、核对全字节、解析固定 proto compact，并复验 API、实际 commit、每个 manifest、20 个执行关联和上述结果。需要已有 Python 与 zstd；不会启动任何产品、Rust、cargo、Bazel 或 CI。

正式结果 `verification-01.stdout.json` 为 64,403 B / Git `306fadbb0b568a8826ede8edc91ddfb12f72cef7`，首次重放 exit 0、stderr 0。异地恢复后再重放及其实际登记结果另附回执。生成投影可以从 ZIP 重建；计算身份不被冒充为单独创建的 Git 对象。

附带的 formatter 小包只接受 37aa→7918 两处原 native rustfmt 布局差异，独审实际对象 `7131b1ffbabdc8a0d0c5090350e61135c6b89fd4`。它没有把新 source 当作原生通过。整个包没有修改源码、权限断言、预算、重试策略或 required-check 结论。
