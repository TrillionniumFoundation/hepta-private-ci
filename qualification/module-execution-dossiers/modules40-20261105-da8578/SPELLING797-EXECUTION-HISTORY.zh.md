# 797 拼写修复候选的执行检查点

`797116d61cf422c26274ffef31297dce84a53a80` / tree `67ce024db1679aa6cd301856ba3a694ea18bc4b6` 已完成自身的 Linux 原七包、Codespell、格式/Clippy 及指定库/进程回归。它的代码父提交是 `c4863123b65f895be0eb14e0958d5cfe6c9c78bd`，导航阶段仅重绑 `inference.worker` 的观察身份并追加第三份 history。原两份 history 与全部产品声明边界保持。[固定源码](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/797116d61cf422c26274ffef31297dce84a53a80)；[797 源码检查点](checkpoints/797/BUILD-SOURCE-REPORT.md)

## 本候选原始执行

Native job `1a1ac84ead1-fc05-54ef` 的权威终态为 `succeeded / exit 0`，输出完整且持久化，无取消、外层超时或自动重试。17 份命令回执均在干净、身份一致的 797 commit/tree 上执行，所有日志字节数和 SHA256 已独立核对。[运行服务终态](runtime/spelling-canonical-797-runtime-status.json)；[原总回执](native/spelling-canonical-run1-summary.json)；[报告核对结果](SPELLING797-EXECUTION-HISTORY-VALIDATION.json)

| 范围 | 原始结果 | 证据 |
| --- | --- | --- |
| 七个完整包 | **1,219 passed（2 slow）、78 skipped；0 failed、0 timed out**；nextest 阶段 66.007 秒 | [日志](native/seven-package-run3-original-test.log)、[JUnit](native/seven-package-run3.junit.xml)、[命令](native/seven-package-run3-original-test.json) |
| 必需清单与完整套件审计 | **69/69 clean；整体 CLEAN；exit 0** | [audit](native/seven-package-run3-required-tests.69.native-audit.json)、[绑定清单](native/seven-package-run3-required-tests.69.source-bound.json) |
| 七项严格仓库检查 | **7/7 exit 0** | [七包汇总](native/seven-package-run3-summary.json) |
| Codespell 2.4.3 原命令 | **exit 0**，日志为空 | [回执](native/spelling-canonical-run1-original-codespell.json) |
| 原全工作区格式、原四包格式、原三策略 Clippy | **全部 exit 0** | [总回执](native/spelling-canonical-run1-summary.json) |
| 两个完整 library target | **319 passed（1 slow）、0 skipped**；45.061 秒 | [原日志](native/spelling-canonical-run1-two-library-regression.log)、[回执](native/spelling-canonical-run1-two-library-regression.json) |
| AppServer `process_exec` 选择范围 | **5 passed、1,016 skipped**；1.337 秒 | [原日志](native/spelling-canonical-run1-app-server-process-regression.log)、[回执](native/spelling-canonical-run1-app-server-process-regression.json) |

原七包选择、`local` profile、断言、超时与重试配置保持；69 项用于审计完整执行，并非测试过滤器。78 项 suite skipped 和 AppServer 选择之外的 1,016 项保持跳过记账。稳定版 rustfmt 忽略 nightly-only `imports_granularity=Item` 的告警完整保留；Clippy 只称原 `correctness`、`await_holding_lock`、`await_holding_invalid_type` 三条 deny policy 通过。[命令与日志核对](SPELLING797-EXECUTION-HISTORY-VALIDATION.json)

## Codespell 的等价源码修复

bb55 平台实际失败的流式前缀 `"hel"` 改写为 `"he\x6c"`，运行时仍是同一个 `&str` 和 `68 65 6c` 三字节。原通知顺序、测试断言、Codespell 2.4.3、`.codespellignore` 和 `.codespellrc` 保持。匹配的原命令在 bb55 上重现 exit 65，在 c486 代码候选上得到 exit 0；797 又在自己的固定源码上重新运行通过。[固定测试源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/codex-rs/hepta-infer-worker-host/src/native_output_tests.rs)；[RED 回执](native/spelling-navigation-run1-codespell-red.json)；[代码 GREEN 回执](native/spelling-navigation-run1-codespell-code-green.json)

## 独立读取归档与不确定打包请求

原生测试终态与后来一次打包请求的状态分开记录。归档 shell 请求 `1a1ac8ebea3-fc05-5545` 保持 `launch_unknown`；同 key 查询没有证明归档成功，不能据此改写已经成功的原生执行结果，也没有用新 key 重放该不确定打包动作。

随后通过只读 file API 收集 **72 个远端文件**，每个文件各自绑定版本、字节数和 SHA256；大文件逐块读入并核对整体摘要。写入方已完成且对应输出为 create-only，但该过程仍明确标为 **atomic_snapshot=false**，不声称跨文件原子快照或采集时远端当前 checkout 的证明。[采集与归档范围核对](SPELLING797-EXECUTION-HISTORY-VALIDATION.json)

只读采集归档 [native-797-file-read-checkpoint.tar.gz](native/native-797-file-read-checkpoint.tar.gz) 大小 **313,492 字节**，SHA256 `6e95dfc4723db20a4bfa158bedae04e8fc537622bbd0a20abf59783552c7571a`，共 **123 个文件 / 122 个 MANIFEST 条目**，包括原始数据与读取 custody。它明确链接 bb55 基础归档，保留过往失败及原始身份。[归档核对](SPELLING797-EXECUTION-HISTORY-VALIDATION.json)

本次 JUnit 为 **280,620 字节、34 个 suite、1,219 个 testcase**，SHA256 `9c08b92ba417f2a99ed449bad0373b5359f535572546138ff735f2e2d9b66510`。原始 JUnit 与全部 69 个关键案例独立交叉核对，没有 failure、error、flaky 或 rerun 记录；78 项选择跳过由原日志保持。[JUnit](native/seven-package-run3.junit.xml)；[报告核对](SPELLING797-EXECUTION-HISTORY-VALIDATION.json)

797 之后的 775 和最终 865 各有新的运行身份与证据。这里的 Linux 成功不升级为 Windows、Darwin、provider、部署或独立接收方通过，40 个 productionImplementation 继续为 false。
