# E6 终态原件包：2026-11-21

本包恢复 61503 源码上的资格关口、65 个原生组件与 NoUpdate17，以及 a3acdf 源码上的独立 CI 原件。完整 NoUpdate17 仍失败，Adopt、cold/restart 和下一任务增益尚未成立。

## 包结构

七个原容器保持原始压缩字节。第八个容器是本次新建 sidecar，保存 70 个小原件、完整 CI job logs、保留的 H receipt、恢复观察和逐成员哈希复核。57 构建归档的 170061834 B 展开原件只保存在原 gzip 内，没有再次放进 sidecar。

- CONTAINERS.jsonl：八个容器的大小、SHA-256、分片数和成员数。
- CHUNKS.jsonl：每个真实二进制分片的顺序、偏移、大小、SHA-256 和 Git blob SHA-1。
- CONTAINERS.sha256：重组后的校验清单。
- SUMMARY.md：按源码版本区分的结论、失败、成本与证据缺口。
- sidecar 中 reviews/RECONSTRUCTED_REVIEW_FROM_RETAINED_ORIGINALS.json：本次重建复核。
- sidecar 中 reviews/*.members.jsonl：七个原容器内全部 537 个成员的哈希。
- sidecar 中 SIDECAR_MEMBERS_SHA256.jsonl：sidecar 内其他成员的哈希；清单自身由容器 SHA-256 保护。

## 恢复

在本目录中按分片名称顺序拼接，然后校验：

```sh
mkdir -p restored
cat payloads/54-source-gates/part-*.bin > restored/54_source_gate_originals.tar.gz
cat payloads/57-build/part-*.bin > restored/57_build_originals.tar.gz
cat payloads/59-lint-diagnostics/part-*.bin > restored/59_lint_diagnostics_originals.tar.gz
cat payloads/61-original-65/part-*.bin > restored/61_components_originals.tar.xz
cat payloads/64-noupdate17/part-*.bin > restored/64_noupdate17_originals.tar.gz
cat payloads/ci-61503/part-*.bin > restored/61503-daemon-native-original.zip
cat payloads/ci-a3acdf/part-*.bin > restored/a3acdf-daemon-native-original.zip
cat payloads/sidecar-reconstructed/part-*.bin > restored/e6-terminal-sidecar-reconstructed-20261121.tar.gz
sha256sum -c CONTAINERS.sha256
```

校验后按需解开 gzip、xz 或 ZIP，审阅原始日志和输入脚本。此目录没有新增可执行 verifier；原保存脚本均作为证据数据保留。

## 本次恢复边界

复核标签为 **RECONSTRUCTED_REVIEW_FROM_RETAINED_ORIGINALS**。重置前丢失的本地复核报告没有被重新冒充为原件。ROG 读取绑定首块版本，每块独立核 SHA-256，再核整容器和归档内成员；CI ZIP 和完整 job log 与既有精确 SHA-256 一致。

本次只恢复与复核原件：新增原生测试、训练、collector 执行和源码修改均为 0。恢复过程发生的传输错误及补取记录完整保留。H 当前终态读取属于新恢复观察；从 62 原输入中解出的组件 H receipt 保持其原字节和来源说明。

发布预期父提交为 fb766447ee882b5945c492d67724c73d21a2369a。本目录使用全新前缀，既有 #6859 的 63 个路径保留。此包不包含 NoUpdate18 的候选或执行结果。PR 维持 Draft；commit/ref 由主审查方处理。
