# B11 v3 实际源码发布：完整恢复包

本包绑定实际源码提交 `87b8603f21e52063ed54ce89cba26756a3efaab7`、父提交 `2980fa274c599bd07437a2f5915b86d858f89bcc`、树 `9a804c7b6e0dd554cdb435f41e06c5c689fffaaf`，以及实际 PR merge `09960fe697c9c181e4a7d624e29b49360877b687`。merge 的两个父提交依次为 main `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` 与该 v3 源码提交。它只证明源码发布身份、静态审查和证据完整性；**B11 仍 OPEN，不包含后续 CI 的成功资格**。

## 完整输入与恢复验证

`root/` 保存 89 个原始输入：全部 11 份根发布原件，原发布 verifier 及两份依赖脚本、父 9cb 完整树，已经实际登记的 v3 候选包全部 71 个成员，以及该候选的 actual registry、registry 原始 full GET 与实际登记回执。候选实际 registry 为 `24dfb6b7f3cd9b9374221390c3337a3d5acb420a`。原件逐字节复制，不修改原根文件，也不改先前候选包。

已在另一个独立临时目录恢复完整输入，以 `--root` 调用原根 verifier，退出 0、stderr 为空。生成的完整树与根 proof 均逐字节等于原始记录。候选静态重放结果只在 `git apply` 命令的恢复目录参数上不同，该唯一差异经过限定归一；其余字段完全一致。随后运行候选的独立 verifier，stdout 与原独审冻结结果逐字节一致。具体命令、输出身份与范围位于 `ROOT_REPLAY.json`，所有运行只执行离线树、源码和本地补丁验证。

解包后可在临时恢复目录运行：

```text
python root/hepta-audit-fifth/verify_b11_observation_launcher_v3_publication.py --root root
python root/architecture-audit/b11-host-neither-observation-candidate-20261105/v3/independent-review/verify_independent.py root/architecture-audit/b11-host-neither-observation-candidate-20261105/v3
```

原根 verifier 会在恢复副本内重写它的三个派生结果文件，因此应在临时恢复目录执行。脚本不会编译产品、启动 Windows 程序或调用 GitHub。归档清单给出每个原始成员的完整字节数、SHA256 与 Git blob 身份；base64 分片均小于 480 kB，拼接去除换行后解码得到完整 gzip tar。

## 发布的精确范围

10,589 个源码叶子中仅 `codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs` 改变：`b40b49ce772c402c51ddb16bb98ff73dc78cdb41` → 实际 `8c16416c185f17871c25139bc16c6fd112b5fd41`。其余 10,588 个叶子、所有生产桌面/令牌入口、原 probe、严格断言、预算与 helper pins 不变。1,571 个目录节点按完整叶子重新计算，并绑定实际非递归 root GET。

v3 修复的是新诊断对 sandbox-only `LaunchDesktop` 的错误复用。普通及仅禁用 privilege 的主体继续保持零 restricting SID，新的 test-only helper 使用同一套 `CreateProcessAsUserW`、原 Job 配置和显式 stdio 列表。实际 child primary token 门闩、五矩阵、三个 5 秒等待与 ActiveProcesses=0 清理资格保持。生产入口对零 restricting SID 的拒绝规则完全保留。

初次 native11 的 146 PASS / 8 FAIL / 2 IGNORE、122 错误、三组 Rust 观察和两组 cmd 缺失都原样保留。多 privilege 干预不能单独归因于 SeRestorePrivilege。未将静态接受、发布成功或自动 CI 启动转写为原生通过。实际提交、ref 读回、完整 PR body 与此前历史全文的保留均由冻结原件和 verifier 核对。

实际登记完成后，`delivery/registry.actual.json` 及其独立 receipt 给出所有对象与清单自身的 materialization/full GET 结果。此目录的原始 GET 是工具返回的完整结构化 payload，未伪造 HTTP headers 或状态。该 evidence 包不会更改任何产品或审计 ref。
