# 最终后继候选的 40 模块源码事实报告重建

本目录固定描述 canonical commit `797116d61cf422c26274ffef31297dce84a53a80`、tree `67ce024db1679aa6cd301856ba3a694ea18bc4b6` 的源码事实。其代码父提交是 `c4863123b65f895be0eb14e0958d5cfe6c9c78bd`。源码报告不包含该候选的原生执行或平台 CI 通过声明；执行结果必须由对应候选的独立回执提供。

## 输入链和保留范围

完整来源链是初始 40 张 Map → f581 的 9 张导航替换 → bb55 的 11 张导航替换 → 本次 `inference.worker` 的 1 张导航替换。后继以已验证的 bb55 完整 40 张 Map 为底，`prior-facts` 使用 bb55 完整 facts。三份 source-navigation history 文档全部保留：原 history、history-final 和新增 history-spelling；前两份的原始字节不变。

本次 Map 替换的 Git blob 为 `8ad25b2f06c9d48dab97eb89cb0ccc244e0f75d3`，新增 history 的 Git blob 为 `6d39404b76052381138d6c4db4c3a24d3ddaedbb`。所有 40 模块的原始 roots、owner、caller/writer、sourceBase、claimBoundary、371 条操作及 108 条 repository gate、140 条 external gate 都保持原值。后继产物写入本目录；旧 `final-report-prep` 的 60 个文件逐字节保留，详见 `bb55-preservation-manifest.json` 和 `BB55-PRESERVATION-VALIDATION.json`。

## 阶段一：组合后继输入

在 `/workspace/scratch/da8578abae00` 运行：

```bash
python successor-report-prep/stage_successor_source.py \
  --prior-facts final-report-prep/MODULES40-SOURCE-FACTS.json \
  --prior-snapshot final-report-prep/final-source-snapshot \
  --prior-verified-blobs final-report-prep/final-source-verified-blobs.json \
  --navigation-export integration/spelling-navigation-export.json \
  --postimages integration/spelling-navigation-postimages \
  --canonical-objects integration/canonical-spelling-final-object.json \
  --source-commit 797116d61cf422c26274ffef31297dce84a53a80 \
  --source-tree 67ce024db1679aa6cd301856ba3a694ea18bc4b6 \
  --output-dir successor-report-prep
```

该步骤验证 bb55 原 Map 与原 facts、清单三者一致，校验新增导出的 Git blob/SHA256 及独立 postimage 字节，并验证原生导航 commit 与 canonical commit 各自的原始对象、tree 和父提交。它只写本目录的 `source-snapshot` 与 `source-verified-blobs.json`，不修改旧资料。

## 阶段二：生成完整报告

```bash
python successor-report-prep/build_source_report.py \
  --source-commit 797116d61cf422c26274ffef31297dce84a53a80 \
  --source-tree 67ce024db1679aa6cd301856ba3a694ea18bc4b6 \
  --map-dir successor-report-prep/source-snapshot/docs/modules \
  --verified-blobs successor-report-prep/source-verified-blobs.json \
  --registry-file successor-report-prep/source-snapshot/docs/modules/MODULES.json \
  --canonical-objects integration/canonical-spelling-final-object.json \
  --prior-facts final-report-prep/MODULES40-SOURCE-FACTS.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history.json=successor-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-final.json=successor-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-final.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-spelling.json=successor-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-spelling.json \
  --output-dir successor-report-prep
```

加上 `--validate-only` 可只校验输入和语义，不写报告。该生成器支持显式 commit/tree、任意绝对或相对输入路径和重复的 source-history 参数，不通过全局字符串替换历史身份。

## 输出和校验

- `MODULES40-DEVELOPMENT-BODY.zh.md`：40 行能力、组合层级和下一门槛。
- `MODULES40-SOURCE-FACTS.json`：所有 Map 原字段、登记表、三份 history 全文和来源元数据。
- `MODULES40-OWNER-AND-MAPPING.zh.md`：源码根、owner、caller/writer 原状态与操作数。
- `MODULES40-OPERATIONS-AND-GATES.zh.md`：371 行导航，以及全部 operations 与 repository/external gate 原文。
- `MODULES40-CRITICAL-PATH.zh.md`：8 条跨模块关键路径及完成判据。
- `SOURCE-REPORT-VALIDATION.json`：所有输入 hash、模块校验和最终文件 hash。

JSON 往返后逐值核对全部原 Map 字段。附录的 120 个 JSON 区块再次解析核对，确保操作与 gate 原值完整保留。40 个 productionImplementation 仍为 false，371 是导航映射数。原始执行、平台失败、范围内通过和后继运行都按独立身份记录；`BB55-EXECUTION-HISTORY.zh.md` 只记录已经封存的 bb55 及更早候选。
