# Future OOD 合同采集与依赖修复：发布说明

更新日期：2026-11-26。

**本地合同执行已获得实证：原登记的 113 个测试实例／方法节点全部通过，另有 27 个成功的 subTest 调用报告；原测试内实际执行 20 次 AdamW 更新。两次驱动器的原始失败回执完整保留，独立离线复核结论为 `PASS_RETAINED_CONTRACT_EVIDENCE`。新 workflow 的 hosted CI 尚未执行，全仓仍为 HOLD。**

## 修复内容和冻结来源

源码固定为 `ce6b9fe9dcb7d6bb8e78978c8b81a001ac7e2ea2`。准备阶段逐一核对的 33 个原文件与 Git blob 一致；实际执行回执还确认原源码字节没有变化。来源与完整清单原件保存在归档的 `registered/SOURCE_IDENTITY.json`、`registered/SOURCE_MANIFEST.tsv`。

[原 contract 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45725442426/job/139594026612) 因缺少 pytest 出现两个导入错误。其 `Ran 82 tests` 包含 80 个 unittest 方法和两个导入错误占位项。只补装依赖仍不足以执行顶层 pytest 函数，因此本修复同时修正依赖与采集入口。

候选仅修改 `.github/workflows/hepta-future-ood-harness-contract.yml` 的 contract job，补丁为 **增加 10 行、删除 1 行**：

- 建立隔离 CPU venv，固定直接依赖 Torch 2.10.0 CPU 和 pytest 9.0.2。
- 在 `qualification/neuron-shared-encoder` 目录执行 `python3 -m pytest -q tests/`，覆盖原 unittest 方法及顶层 pytest 案例。

原测试名单、测试源码和判据均未修改。trigger、permissions、concurrency、checkout、15 分钟 contract 超时、编译步骤，以及整个 90 分钟 `laya-reader-intake` job 保持不变。原 Laya job 块逐字保留，没有增加 skip 或条件绕行。

| 对象 | SHA256 |
|---|---|
| 原 workflow | `af672c6438070693771221b2b0adeba2842077a344973a0142c9f727de97f65c` |
| 候选 workflow | `9204137f5518ea96b83e4ad5bf79f66c9dd9aac698cc4fae04dfa3fa5262a2b7` |
| 原登记 113 项名单 | `148bfb7d28ee4278abe40067a2e41ad4fe18393af4e095f73c68052a6112890b` |

候选完整文件位于本分支的 [.github/workflows/hepta-future-ood-harness-contract.yml](../../../../.github/workflows/hepta-future-ood-harness-contract.yml)；归档的 `workflow/original.yml` 和 `workflow/candidate.yml` 保留原／新完整文件，可直接核对最小差异。

## 两次原执行及后续离线复核

实际本地环境为 **Python 3.14.4、Torch 2.10.0+cpu、pytest 9.0.2**，Torch threads 和 interop_threads 均为 1。完整实际包版本保存在原执行回执与离线审核记录中。这里记录的是已经观察到的本地环境，不把它当成尚未执行的 Ubuntu 24.04 hosted job 环境；候选 workflow 继续使用该宿主的现有 `python3`，没有新增 Python 版本选择或全量传递依赖锁。

| 阶段 | 原始观察 | 结果的准确解释 |
|---|---|---|
| driver 01 | 缺少测试根目录的 `sys.path`；收集阶段出现 `neuron_shared_encoder` 导入错误；AdamW 更新为 0 | 收集／名单门失败，保留原 `FAILED`；没有发生成功后再次拟合 |
| driver 02 | 实际采集 113 项；pytest exit code 为 0；原 stdout 为 `113 passed, 27 subtests passed`；AdamW 更新为 20 | 原测试实际通过，但外层包装器把额外 subTest call 报告错计为顶层测试，原 `RESULT.json` 因而仍为 `FAILED` |
| 纯 stdlib 离线审核 | 对原名单、采集记录、JUnit、全部 phase 报告和摘要交叉核对 | 新增独立 `PASS_RETAINED_CONTRACT_EVIDENCE` 回执；模型加载、测试执行、训练更新均为 0 |

没有把 driver 02 的原 `status=FAILED` 或 `executed_nodeids_match=false` 改写为成功。新的审核记录明确保留 `original_driver_status=FAILED`、`original_driver_receipt_unchanged=true`，并说明计数错误的原因。它依据已经保存的成功 pytest 执行解释证据，不通过重跑测试获得更好结果，也不修改原测试的通过条件。

原 driver 02 结果 SHA256 为 `49990286864fb5af7b06cf3a156e1dcd7a62ce0b8445d38bff9abef99bbde4e8`。独立离线审核回执 SHA256 为 `4e2c8288555ca7373b640c2e478621c37739a1961e48c6ec3ea2f4c8e3fcf314`；审核脚本 SHA256 为 `3135e45c4e385d0e9ca643495fd05918c24086e8cdb4267e7155bf0b9a341cb2`。

## 113 项、27 个 subTest 与 366 条报告如何对应

113 个登记节点由 **80 个 unittest 方法、8 个 bundle pytest 实例、25 个 qualification pytest 实例**组成。独立审核确认，原名单与实际 collection、JUnit 的方法节点以及 phase 报告的节点集合一致。

| 原始记录 | 数量与含义 |
|---|---|
| 收集的方法／实例节点 | 113 |
| JUnit `<testcase>` 元素 | 113 |
| JUnit `tests` 属性 | 140，包含 subTest 计数 |
| setup 报告 | 113，全部 passed |
| call 报告 | 140，全部 passed，包含 27 个额外 subTest 报告 |
| teardown 报告 | 113，全部 passed |
| 全部 phase 报告 | 366，全部 passed，均无 xfail 标记 |

额外 call 报告集中在 `HarnessFlagTypeTests` 的两个原方法：

- `test_forbidden_flags_reject_non_boolean_values`：22 次 call 报告，即父方法一次及 21 次 subTest。
- `test_literal_false_none_and_missing_flags_preserve_receipt`：7 次 call 报告，即父方法一次及 6 次 subTest。

这不是新增 27 个顶层测试，也不能把 140 当作 140 个独立登记实例。**原记录没有保留每个 subTest 的参数标签。**当前证据能够支持原源码循环次数、准确的父节点归属、22／7 的报告重数及原成功摘要；不能声称已经取得 27 组逐参数标签的独立执行证据。

## 实际优化器与模型范围

20 次 AdamW 更新来自原合同中的 `test_synthetic_head_smoke_and_no_change_distinguisher`：40 行合成数据、两档参数预算和六种 head；两个超预算候选在拟合前拒绝，其余十个候选各执行两步。没有改变原参数预算、步数或拒绝条件。

同一原合同还包含不使用优化器的 tensor stress、head 参数量和前向检查。它们仍按原名单执行，没有为使合同通过而排除相关测试。该合成执行不加载真实 Laya checkpoint，不新增 E1–E6 试验，也不构成 HCSN／Laya 的任务效果或生产采用证据。

本次离线复核、归档和发布说明编写没有增加拟合、模型调用或测试执行。原 driver 01 为 0 次更新，driver 02 为上述 20 次更新；没有为修正包装器计数再跑一轮合成拟合。

## 原件保全

完整归档为 **`OOD_CONTRACT_01_02.tar.xz`，21,200 bytes，SHA256 `d6a5f1b0d0a5a3904a3adafa920f7fa3766a70298d333b4b7f03baa8c85da033`**。`OOD_CONTRACT_01_02.index.json` 逐项登记 20 个成员的原始大小与 SHA256。

归档包含两次原失败回执和原 stdout/stderr、driver 02 的实际采集与 JUnit、两个原驱动器、纯 stdlib 离线审核器及其结果、原登记名单与来源材料，以及原／新 workflow。主要目录为：

- `attempt_01/`：收集失败的原件。
- `attempt_02/`：成功 pytest 执行及仍标为 FAILED 的原包装器回执。
- `drivers/`：两个原驱动器与离线审核脚本。
- `registered/`：执行前登记的名单、范围、计划和源身份。
- `verification/OFFLINE_AUDIT.json`：新增独立审核结果。
- `workflow/`：原 workflow 与最小修复候选。

`registered/` 中的静态准备文档保持当时原字节，部分字段仍写“未执行”。它们是执行前快照；后续实际结果由原执行记录和独立审核回执补充，不能通过覆盖这些历史文件来制造一份从未失败过的记录。源码身份和全部原件以归档索引为准。

## 发布状态与剩余范围

本候选以独立、可审阅的源码分支发布。当前不创建会再次启动原 90 分钟 Laya intake 的 PR，不调用原 workflow 的手动／复用入口；同时完整保留原触发器和 job，不改 trigger 来回避既有门。

本地结果已经证明该固定源码、所记录本地环境中的完整合同采集与执行。**新 workflow 的依赖安装、hosted contract job、编译及整套工作流尚无新 head 的实际终局。**原始 Laya 成功继续归属于其原源码和原运行，不转移到这个新候选头，也不把原 Laya 成功与本地 contract 通过拼接为新整套 workflow 成功。

因此当前结论为：本地 contract 的依赖／采集问题有完整原始执行及离线审核支持；新 workflow 待其自身 hosted 证据；全仓和生产采用仍为 **HOLD**。root 继续推进其他独立 blocker，本说明不引入新的训练或重复 intake。
