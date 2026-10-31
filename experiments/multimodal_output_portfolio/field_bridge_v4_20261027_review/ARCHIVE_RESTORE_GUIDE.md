# V4 完整原始证据打包与 literal restore

本工具链只保存和验证已完成的 V4 执行。调用前必须由研究负责人确认全部训练、端点、独立审计、唯一资格统计及机制报告已完成，并写好 `run/V4_EXECUTION_LEDGER.json`、`run/STUDY_DISPOSITION.json`。未获得该终态许可时，模板的 `terminal_access_authorized` 必须保持 `false`。目前文档不代表归档已经完成。

## 保存范围

完整保存 terminal V4 run，包括全部 108 checkpoint、108 完整轨迹、222 媒体文件、三个 ENDPOINTS、所有成功或失败记录、阶段费用、日志、资格结果和机制/独立审计证据。保存 V4 science/review 源码与报告、所有外部 freezes、58 个冻结源码/证据文件、25 个固定旧输入、完整 V2/V3 来源身份登记、全部 `bridge_assets/full002` 原始文件及 RESTORATION。

明确排除 Python bytecode/cache、归档本身、事后归档回执及可再生临时 Torch 环境。V2/V3 大型历史 tar 通过原已验证回执中的 SHA、字节数和 manifest SHA 引用，不嵌套入本包。旧实验全部生成历史不属于这个 V4 包；本工具也不声称重新训练了所有历史模型。

`MANIFEST.json` 是首个 regular tar member，列出所有其他成员的字节数和 SHA。tar 使用固定权限、零时间、零 uid/gid 和无用户名；gzip 使用 level 6、零时间和空文件名。完整验证重新读取整个包至物理 EOF，校验所有成员 SHA、外层 gzip CRC、每个内层 `.gz` 的 CRC/EOF，以及 tar 结束块。没有异常白名单。

## 工具与环境

| 文件 | 职责 | Python |
|---|---|---|
| `archive_plan_v4.py` | 只读枚举并固定终态输入、来源和恢复清单；不复制 raw | 默认 `python`，NumPy 可用 |
| `archive_build_v4.py` | 重查全部身份，先检查最坏空间上界，再流式打包 | 本机 `/usr/bin/python3` |
| `archive_integrity_v4.py` | 完整流 SHA/CRC/EOF 验证及排他性选择恢复 | 标准库 Python |
| `archive_reanalysis_bindings_v4.py` | 仅依据已验证归档绑定阶段、来源、策略、checkpoint 和原资产 | 恢复目录中的默认 `python` |
| `archive_reanalysis_v4.py` | 从 literal restored 冻结 analyzer 精确重算原六比较 | 恢复目录中的默认 `python`，NumPy 2.3.5 |

本机默认 Python 的 zlib 为 1.3.2，可调用的系统 libz 为 1.3；`/usr/bin/python3` 与 libz 同为 1.3。builder 使用与实际压缩器相同版本和配置的 `deflateBound` 给出压缩大小的数学上界，因此正式 build 使用 `/usr/bin/python3`。这一要求不涉及研究代码或统计方法变更。

## 顺序

1. 将 `ARCHIVE_COLLECTION_TEMPLATE.json` 复制到外部 `bridge_v4_archive/ARCHIVE_COLLECTION_CONFIG.json`，在终态获准后设置 `terminal_access_authorized:true`；按实际记录补齐位于 run/freezes/repo 之外的 `operation_files` 或 `operation_trees`。禁止把归档输出目录自身列为输入。
2. 调用 collector，生成 `ARCHIVE_INPUTS.json`、`ARCHIVE_SELECTIVE_RESTORE.json` 和 `ARCHIVE_PLAN_RECEIPT.json`，均放在外部 `bridge_v4_archive/`。此阶段只写小型清单，raw copy 数为零。
3. 使用 `/usr/bin/python3 archive_build_v4.py --index ... --output /tmp/hepta-v4-final-20261027/hepta_field_bridge_v4_20261027_evidence.tar.gz --receipt .../ARCHIVE_BUILD_RECEIPT.json`。builder 会独立重算完整清单身份，并在创建目录、归档或 `.partial` 前检查空间。
4. 从 build receipt 精确读取 `archive_sha256` 和 `manifest_sha256`，调用 verifier：`archive_integrity_v4.py --archive ... --expected-sha256 VALUE --expected-manifest-sha256 VALUE --restore-plan .../ARCHIVE_SELECTIVE_RESTORE.json --restore-dir .../literal-restore --output .../ARCHIVE_INTEGRITY.json`。恢复目录必须不存在；默认 100 MiB 恢复上限必须覆盖计划中的精确字节数。
5. 计算 `ARCHIVE_INTEGRITY.json` 的 SHA。启动新进程，执行 **literal restore 目录内部** 的 `repository/experiments/multimodal_output_portfolio/field_bridge_v4_20261027_review/archive_reanalysis_v4.py`，传 `--restore .../literal-restore --integrity .../ARCHIVE_INTEGRITY.json --expected-integrity-sha256 VALUE --output .../ARCHIVE_REANALYSIS.json`。不能从工作区主本启动统计重算。
6. 归档验证与 literal reanalysis 成功后，再将所有归档回执复制进 repo evidence，标记为 archive-self-excluded postpackage receipts。这些回执绑定最终 tar；不能再次把它们加入同一个包并试图维持旧 SHA。

所有调用使用 `PYTHONDONTWRITEBYTECODE=1`；NumPy 重算使用 `OPENBLAS_NUM_THREADS=1`。不需要临时 Torch，不调用模型、observer、native solver、网络或上传。

## 空间和失败处理

builder 按完整 tar header/padding、同版本 libz 的 gzip 上界、所选 literal restore 精确载荷、manifest、验证回执和 build receipt 预算，另保留默认 32 MiB。verifier 在写恢复目录前再次检查空间。默认使用 `f_bavail`；只有明确启用 `--use-root-reserved-blocks` 且当前 uid 为 0 时才使用 `f_bfree`，并在回执记录该选择。预算是可用空间快照，不是文件系统预留。

空间不足会明确拒绝，不能删减媒体、身份文件或独有证据。所有输出排他性创建；失败的 `.partial` 保留，不能覆盖为成功。继续操作必须先解释失败原因，并使用新路径或经负责人确认处理可再生失败副本。绝不在此流程中删除独有证据或重试 Library 上传。

## 恢复验证的边界

完整当前 V4 媒体/checkpoint 由整包逐 SHA 与 CRC 校验覆盖。literal restore 选择全部必要元数据、三个 ENDPOINTS、冻结 analyzer、协议、来源登记、输入绑定和原 QUALIFICATION。统计重复只调用冻结 analyzer 的 `validate_protocol`、`panel_from_flat`、`analyze_panels`，精确核对原比较、观察器、描述量、bootstrap draw SHA 及原结论。它不调用 `qualify()`，不产生新 outcome look，也不选择新方法。

选择恢复不重跑模型或重新计算 observer；已完成的独立模型/媒体审计通过原报告和完整原始数据保存。归档完整性、统计精确重复与科学通过是三个不同判断。若原 QUALIFICATION_FAILED，正确恢复应精确重复该失败结果。
