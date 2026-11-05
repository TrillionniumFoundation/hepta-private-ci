# 775 源码检查点的 40 模块报告

本目录固定描述 commit `775bf555b0a7faf6eed17627acb0d0433294b737`、tree `e6f4644152d11a06457fdd92d8e5066675b26565`。该源码在父提交 `797116d61cf422c26274ffef31297dce84a53a80` 上修正两处 Windows 测试名称引用。它作为独立检查点保留；正在准备的后续有序合并候选不得继承它或其父提交的执行结果。

## 固定输入和零导航变化

`stage_unchanged_source.py` 校验 canonical commit 的原始 Git 对象、同 tree 的原生 source commit `587a37f7cb3196426962024a094dab8947596fef`、原生两文件 postimage、原生导航 preview，以及独立 GitHub 精确父子 compare 和登记表读取。

GitHub compare 确认当前候选是父提交的直接单父后继，仅修改以下两个路径：

- `codex-rs/utils/pty/src/win/native_observation_tests.rs`
- `codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs`

原生 formatter 输出与独立审阅 postimage 完全一致。原 helper 在固定 775 commit/tree 上返回 `changedMaps = 0`、`written = false`、`ledger = null`。全部 40 张 Map 的 SHA256 与 797 一致，原三份 source-navigation history 也逐字节一致。未创建新导航 history。

对应固定输入为：

- `integration/windows-source-evidence/windows-name-source-run1-export.json`
- `integration/windows-source-evidence/windows-canonical-run1-navigation-preview.json`
- `integration/canonical-windows-final-object.json`
- `windows-775-report-prep/github-797-to-775-compare.json`
- `windows-775-report-prep/github-775-registry-capture.json`
- `successor-report-prep/MODULES40-SOURCE-FACTS.json`、`source-verified-blobs.json` 和 `source-snapshot/`

以上来源的文件摘要、原始身份和核对结果保存在 `source-verified-blobs.json`。这里的源码绑定不产生 Windows 编译、原生七包、平台部署或生产资格声明。

## 重建

从 `/workspace/scratch/da8578abae00` 运行：

```bash
python3 windows-775-report-prep/stage_unchanged_source.py
python3 windows-775-report-prep/build_source_report.py \
  --source-commit 775bf555b0a7faf6eed17627acb0d0433294b737 \
  --source-tree e6f4644152d11a06457fdd92d8e5066675b26565 \
  --map-dir windows-775-report-prep/source-snapshot/docs/modules \
  --verified-blobs windows-775-report-prep/source-verified-blobs.json \
  --registry-file windows-775-report-prep/source-snapshot/docs/modules/MODULES.json \
  --canonical-objects integration/canonical-windows-final-object.json \
  --prior-facts successor-report-prep/MODULES40-SOURCE-FACTS.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history.json=windows-775-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-final.json=windows-775-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-final.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-spelling.json=windows-775-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-spelling.json \
  --output-dir windows-775-report-prep
```

生成器加 `--validate-only` 可仅验证输入而不写报告。它显式接收当前身份，历史 sourceBase、原 claimBoundary、source-history 文档与旧执行身份均按原值保留，不做全局字符串替换。

## 完整输出

| 文件 | 内容 |
| --- | --- |
| `MODULES40-DEVELOPMENT-BODY.zh.md` | 全部 40 模块逐项发展情况与下一门槛。 |
| `MODULES40-OWNER-AND-MAPPING.zh.md` | 源码根、owner、caller/writer 原状态和操作数。 |
| `MODULES40-OPERATIONS-AND-GATES.zh.md` | 全部 371 项操作及 108 repository gate、140 external gate 原文登记项。 |
| `MODULES40-CRITICAL-PATH.zh.md` | 8 条跨模块工程依赖和完成判据。 |
| `MODULES40-SOURCE-FACTS.json` | 40 张 Map 原字段、登记表、三份原 history 与来源元数据。 |
| `SOURCE-REPORT-VALIDATION.json` | 固定输入摘要、逐模块核对、完整原字段/操作/gate 保留检查及输出摘要。 |

40 个源码根存在标记均为 true；40 个 productionImplementation 保持 false。Gate 数字是原始登记项，含跨模块重叠，并不表示独立 bug 数或生产完成比例。只读/无状态 writer 的设计边界、未组合产品 caller 与源码存在之间的区别继续保留。
