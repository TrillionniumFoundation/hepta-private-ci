# 原 0e139 CI：第四次不可变证据增量

本增量的 API 截止时刻为 **2026-11-05 08:17:06 UTC**。所有产品作业仍绑定 PR #4797 的 `0e139b599f0fe451f80fb7db4b2913bb9c679dce`、原 `run_attempt=1`；普通合成 checkout 为 `e93aefbbb33438f6ec67e995adcfe88657158487`，树为 `091e659e0da6602299fd14cfa93889191405edd8`。没有重跑、取消、dispatch 或产品 ref 更新。独立证据分支不作为这些作业的源。

完整原件通过 [原件清单](generated-evidence/batch-04/original-files-manifest.json)、[传输清单](generated-evidence/batch-04/transport-manifest.json) 和 [逐字校验程序](generated-evidence/batch-04/verify_archive.py) 关联。共 80 个文件、16,117,438 原始字节；9 个严格 Base64 分片重建 1,596,696 字节 gzip，SHA256 为 `e71463a3a38059822b4d32600cc57a8e7c317f5aa8c017f375845f00b357355b`。已实际复核全部原件长度、SHA256、Git 内容哈希、gzip/TAR 成员集合与无漏尾。文件中的计算 Git 哈希不表示每个原件分别上传；分片提供可恢复原文。

## 实际增量结果

| 原范围 | 已取得原文 | 限域 |
|---|---|---|
| Windows 主矩阵 4 个 test 分片 | 4 个完整 job log 均以取消结束；第 4 片只到 34/149 目标进度 | 无 Core integration、CodeMode、严格 token 或 TUI 的完整最终案例正文，不能补记通过 |
| Windows/Linux native wrapper | 原命令各报告 57 tests、OK，分别 15.430 秒与 5.088 秒 | 输出非逐例 verbose，不能补造 57 个名称；不代表 Mac 修后结果 |
| Mac ARM native wrapper | 原 57 tests 中 3 FAIL，5.184 秒；实际 stderr 为 `failed_targets[@]: unbound variable` | 固定原源码和失败块完整保留；未记录精确 Bash 版本 |
| GNU V8 staged release smoke（ARM、amd64） | 两者均 5 PASS、1 FAIL；原 `sandbox_feature_matches_linked_v8` 不等 | 与已审默认 feature 修复相关，但候选未因这些旧作业获得通过资格 |
| V8 musl release / ptrcomp-sandbox | 原作业构建与上传完成，日志明确跳过 non-native Cargo smoke | 不证明 musl CLI 实际执行，也不把 V8 产物等同产品业务验收 |
| Mac ARM Clippy | 完整原 log 明确构建成功、20,515 actions | 本次未下载 8.9 MB 执行日志工件，不声称其内容校验 |
| GNU release/Clippy、Mac ARM test/release、repo build-test | 完整原 log 中取消及清理保留；repo build-test 取消前原 57 tests 已 OK | 不推测取消 actor 或因果；部分成功步骤不等于整个 job 成功 |

观察截止时，GNU 主测试仍 queued，标记 musl 的主矩阵作业刚开始 `bazel test //...`。该标签仍使用已核的 GNU/RBE 配置，不能代替独立真实 musl 产品门。

## 静态审查与开放门

本批包含两个独立静态回执。Mac 包装脚本候选只保护两处可能为空的数组展开，保留原执行命令、返回码、日志范围和 57 项断言；第二处是同型静态风险，不写成第二个实际错误。修后原平台测试尚未由该回执证明。

B16 V6 新模式严格标记 `BUILD_ONLY_CURRENT_HOST`、`tests_executed=false`、`test_qualification=false`，历史 fb9 测试证据与新宿主构建来源分别固定。原负控、恢复和预算未改；实际 P3/P4 完整原件、绑定输入与 native 门仍待满足。这一审查不授予 A 全平台或 B16 正常入口资格。

此前 23 项原退出条件与状态没有因本增量改变。取消窗口只证明作业被取消；没有操作人或足够机制证据时，原因继续记为未知。
