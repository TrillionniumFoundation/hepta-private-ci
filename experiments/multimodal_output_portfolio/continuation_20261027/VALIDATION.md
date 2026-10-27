# 本轮验证记录

审计通过意味着结果可以按声明的协议重建，不代表科学优势门槛自动通过。
各门槛的正负结果见 [ACCEPTANCE.json](ACCEPTANCE.json)。

## 行为测试和实际实验

| 工作线 | 已完成的验证 | 记录 |
| --- | --- | --- |
| 联合证据 | 5 项行为测试；4,000 WAV hash；3 个联合表独立公式重建；240 alias receipt；67,200 实际输出重读 | `evidence/TESTS.json`、`evidence/INDEPENDENT_AUDIT.json` |
| 原生执行 | 未修改 owner/runtime/journal/witness 的实际编译与运行；两版 240 episode 完整网格；全部 owner API 独立回放 | `control/evidence/BUILD_V1_RECEIPT.json`、`BUILD_V2_RECEIPT.json`、`RUN001_AUDIT.json`、`RUN002_AUDIT.json` |
| 持久化事件 | live / cold / fork 重试无新 transition；冲突 payload 与 5 类恢复篡改拒绝；拒绝前后持久化字节不变 | `control/evidence/DURABLE_GUARD_RESULT.json` |
| 联合训练 | 3 项行为目标测试，包含数值梯度；历史 validation 上部署 bitwise/实际输出与 oracle 一致 | `joint/evidence/TESTS.json`、`INTEGRATION_VERIFICATION.json` |
| 新源生成资格 | 23,040 实际 bundle 与 98,304 oracle candidate bundle 全部重读；独立 CE、bootstrap 与 gate 重建 | `joint/evidence/INDEPENDENT_AUDIT.json` |
| 自然任务 | 7 项行为测试：私有目标隔离、真实 cache/费用、缺失标签、跨样本目标隔离、完整安全恢复、模型冲突保留 | `natural/evidence/TESTS.json` |
| 自然实际输出 | 132 FLAC 全解码、60 原票据重读、1,680 final record 独立重评分、270 canonical 帧重建、48 batch 全成本对账 | `natural/evidence/INDEPENDENT_OUTPUT_AUDIT.json` |
| 独立交叉复核 | 30 项发现/处置，正式 owner、训练、文档、语音与视频实际输出另行核验 | `evidence/PEER_REVIEW.json` 和附属 `PEER_*.json` |

未运行全仓库 `cargo test`，也没有修改生产 Rust crate。原生实验使用孤立
build manifest 和与仓库 lock 一致的依赖，编译原三个 crate 及确切 owner
源码，随后以真实 JSON host 调用、实际文件和独立 native replay 验证行为。
它不声称完整 daemon 构建或 production integration suite 已通过。

## 原始证据恢复与保存

上一轮五个精确证据包从已保存版本恢复，原模型、数据、observer 和恢复
manifest 的字节身份重新核对。恢复得到的原代码基线未被替代成另一个实现。

本轮每个原始包均有完整成员身份清单并实际重读校验。自然包用内容寻址去除
相同文件内容的存储重复，仍保留每个逻辑路径，并通过逐路径写出/重读校验。
该包明确不内嵌两份公开 Whisper weights；官方 immutable revision、URL、大小、
SHA-256 与拒绝覆盖不匹配文件的恢复程序一并提供。

联合证据包保存成功且全波形成员重新验证后，才删除 4,000 份相同的展开 WAV
副本以回收工作空间；原始 archive 与全部科学记录保留。相关记录在
[RESOURCE_CUSTODY.json](RESOURCE_CUSTODY.json)。原生工具链也只清理了已核验
且重复的安装源，编译器/formatter 安装体不变。

所有失败尝试、测试前修订、执行源码 snapshot 与负结果都保留。科学运行
开始后新加的报告、审计和打包 helper，不被冒充为旧运行的预注册源码。

## 最终格式化与仓库检查

仓库 `AGENTS.md` 要求所有代码修改完成后，在 `codex-rs` 执行 `just fmt`，
并禁止其后重跑测试。已安装官方 `just 1.43.0`，按 GitHub 官方 release
metadata 的 SHA-256 校验；原生 `rustfmt 1.95.0` 来自已核验官方工具链。
`just fmt` 已执行成功，退出码 0。首次处理本轮四个独立 Rust 文件，
stdout/stderr 均为空。随后 staged Git whitespace check 找到 `control/training.py`
末尾一个多余空行；仅删除该换行后再次执行 `just fmt`，退出码仍为 0，
提示已无需要格式化的变化。没有运行无关全仓库格式化。完整命令、工具链
版本、前后 hash 与纯空白修正记录见 [FORMAT_RECEIPT.json](FORMAT_RECEIPT.json)。

格式化前，49 个 Python 源文件通过编译与禁止 `__future__` import 的静态
检查，100 个当时存在的 JSON 记录通过标准数值语法解析，记录在
[PREFORMAT_CHECKS.json](PREFORMAT_CHECKS.json)。这一步没有重新执行科学实验。

历史运行的准确执行源码和 binary 继续留在原始包中。最终仓库排版不改写这些
执行身份。格式化之后只做 Git 差异、文件身份和远端发布身份核对，不重新
训练、推断、改变统计门槛或运行测试。

## 发布后的拼写检查修订

首次 CI 在 13 条原始 source/receipt 行上报告拼写错误，其中包括官方语料的
原文、商户/地名、拉丁语引文和旧不可变回执。修订保留全部科学原文与 hash，
仅启用 Codespell 官方的 exact-full-line `exclude-file` 机制；其他行继续检查，
不增加全局词汇白名单，不跳过文件/目录，不修改 workflow。

[CI_AMENDMENT.json](CI_AMENDMENT.json) 保存失败 job、13 条原行的来源与 hash、
四份原文件的身份及该机制的范围。使用 CI 相同的 Codespell 2.4.3 和命令，
本地已检出的仓库内容检查通过；随后再次执行 `just fmt`。科学实验和行为测试
未重跑，原始归档未重写。完整远端 CI 状态以 PR 当前 head 的检查为准。

远端 Codespell 与 blob-size gate 随后通过。全仓格式化检查另外指出基线
`scripts/format.py` 和 `scripts/test_hepta_format_scope.py` 的排版问题。两文件
在修订前与原基线 Git blob 完全相同；仅对这两文件应用仓库 lock 中的 Ruff，
前后 AST 完全相同，并再次成功执行 `just fmt`。详情见
[CI_FORMAT_AMENDMENT.json](CI_FORMAT_AMENDMENT.json)。没有改变研究实现、
实验结果、依赖或权限逻辑，也未重跑行为测试。
