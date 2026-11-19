# 共同候选 native：保留失败历史与同源组件结果

本目录保存 ai395 上已经结束的原始执行记录。**最新精确源码 f070 的四项本地 native 门均已通过：helper 构建、八库 1486 项测试、Matrix SDK 30 项测试、agentd binaries 编译检查。** 70 + 2 个跳过项单独保留，原有失败尝试仍按真实终局归档；这些结果不等于整个 CI 或完整普通 P0 通过。

机读解释见 [SUMMARY.json](SUMMARY.json)，逐文件远端版本、SHA-256 和压缩前摘要见 [MANIFEST.json](MANIFEST.json)。所有 command record 均有非空 completed/exit，并记录相等且干净的 before/after source。每个原始文件小于 500 KiB。八库 JUnit 的 341,353 bytes 经六个 chunk 取回，后五个显式绑定第一个返回的 version，逐 chunk 摘要和整体摘要均核对；其余文件采用一次完整 versioned read。没有将运行中的日志作为终局保留。

## f070 的精确源码终局

运行时 commit 为 `f070113bb61cda492d2668b3afbbcda13e11fa52`，tree 为 `068b6a7749e94d7335c826d6c43c19198e02cc24`。四条命令各自的 before/after source 均为该身份且干净。durable job `1a1c03ab679-5e21-975` [终局状态](native-f070-process-status.json) 为 succeeded / exit 0；[controller](native-f070-controller.json) 的原始 state 是 completed，四个 step 均 exit 0。

| 项目 | 实际结果 | 原件 |
| --- | --- | --- |
| helper build | exit 0，wall 0.755346 秒；没有执行测试 | [command](helper-build-f070-v1.json) |
| 八库 lib suite | 1486 passed / 70 skipped，1 slow；Nextest 120.036 秒，整条命令 wall 156.846918 秒 | [command](native-libraries-f070-v1.json)、[JUnit](native-libraries-f070-v1.junit.xml) |
| Matrix SDK suite | 30 passed / 2 skipped；Nextest 6.071 秒，整条命令 wall 11.733130 秒；原 encrypted restart 用例 5.123 秒 | [command](matrix-sdk-f070-v1.json)、[JUnit](matrix-sdk-f070-v1.junit.xml) |
| agentd binaries | `cargo check --bins` exit 0，wall 78.022706 秒；没有执行模型或启动 daemon | [command](agentd-binaries-f070-v1.json) |

八库实际执行分布为 agentd 787、automation 77、infer-core 41、intelligence 90、learning-artifacts 116、learning-ledger 120、neuron 204、prompt-registry 51。A/B 两 cut 的六项 readback/delivery/checkpoint/transport 回归、两项 Root schema/binding 回归，以及两个 owner-drop 回归的确切 testcase 名都已从 JUnit 核对并列在 SUMMARY 中。实际 Root privileged ignored 测试与真实模型运行另行取证，不能从这 70 个 skipped 中计入通过。

Matrix 的用例总耗时包括准备与恢复；5 秒生产 deadline 限定内部 startup，不是整个 testcase 的时限。本轮没有改变该 deadline、KDF 参数或断言。

## 早先的实际运行历史

| 源码 | 命令记录 | 实际结果及边界 |
| --- | --- | --- |
| `84b2a97c2ab3d727e27a2f5d3bc72ecfd56ae36d` / tree `eb01896296d28bfa86f6d30236e5b0d08f2942fd` | [helper-build-84b-v1](helper-build-84b-v1.json) | exit 101；离线缓存缺 `aws-smithy-async v1.3.1`，尚未开始编译或测试。 |
| 同上 | [helper-build-84b-online-v2](helper-build-84b-online-v2.json) | exit 0；允许获取依赖后，指定 helper 构建成功。没有执行测试。 |
| 同上 | [native-compile-84b-v1](native-compile-84b-v1.json) | exit 2；`nextest --no-fail-fast` 与 `--no-run` 参数冲突，命令在编译前拒绝。 |
| 同上 | [scoped-controls-84b-v2](scoped-controls-84b-v2.json) | exit 101；E0063，测试构造器遗漏 `LearningIterationCheckpointOwnerV1.scope`。修复提交 `f1548649c9`，此次没有执行测试。 |
| `47959b409c7d672fa0be1a17afb7c034bc87bed0` / tree `f07883603839fcabdc20f114c4ee0800e266fcb6` | [helper-build-4795-v1](helper-build-4795-v1.json)、[native-libraries-4795-v1](native-libraries-4795-v1.json) | helper exit 0；八库命令 exit 101，结果 `json!` 宏达到递归限制，测试没有执行。修复提交 `ca584b236a`。 |
| `8857d0f0b149a1aec7546c71803453c93a4aabb5` / tree `965c462e0b31f04d54d0905c43456eacbd74186b` | [helper-build-8857-v1](helper-build-8857-v1.json) | exit 0；指定 helper 构建成功。 |
| 同上 | [native-libraries-8857-v1](native-libraries-8857-v1.json) | exit 101；E0063，Root synthetic fixture 的 `LearningIterationRequestV1` 漏填 `evaluation_profile`，测试没有执行。修复提交 `f070113bb6` 使用同一共享 fixture 明确冻结的 evaluation digest，没有使用默认值或降低验证。 |
| 同上 | [matrix-sdk-8857-v1](matrix-sdk-8857-v1.json)、[JUnit](matrix-sdk-8857-v1.junit.xml) | exit 0；30 passed / 2 skipped。Nextest 测试时间 5.865 秒，原 encrypted-state restart 测试 4.906 秒。JUnit 记录实际执行的 30 项，跳过数来自原日志。 |
| 同上 | [agentd-binaries-8857-v1](agentd-binaries-8857-v1.json) | exit 101；V8 wrapper 已进入 `codex-rs`，命令仍传 `--manifest-path codex-rs/Cargo.toml`，路径不存在。没有进行 agentd binaries 编译或模型执行。 |

8857 的 durable controller job 是 `1a1c024c77f-5e21-925`，[终局状态](native-8857-process-status.json) 为 failed / exit 1，`output_complete=true`、`terminal_publication_confirmed=true`。四个子命令的终局也在 [controller record](native-8857-controller.json) 中保存。原 4795 的 [controller record](native-4795-controller.json) 同样保存，不用新的命令结果覆盖历史。

## 证据与成本边界

原始 JSON 与 JUnit 按字节保存；`.log.gz` 是远端已结束时生成的原封 gzip。逐个解压后得到的长度与 SHA-256 已与各 command JSON 的 `raw_log_bytes`、`raw_log_sha256` 一致。清单中的远端 version 是读取时文件身份，不是源码版本；源码 commit/tree 另列并绑定对应 command record。

各命令的 wall、child CPU、peak RSS 均保留原记录，统计窗口包括编译及子进程；不把 helper、controller、重复 source attempt 或嵌套窗口相加为一次系统成本，也不把 Nextest 测试秒数当整个命令耗时。能耗和提供商金额没有观察值。

8857 的 Matrix 通过只证明当次该组件；当次八库和 binary 的失败保持不变。f070 的四项新结果有独立 source/tree 与原件绑定，不能追写进旧尝试。真实模型、actual Root ignored tests、完整普通 P0、全 workspace / 全平台 CI 以及科学收益也不由这四项本地门推出。
