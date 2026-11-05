# 最终固定合并候选的 40 模块报告重建

本目录的源码事实固定于 commit `8658210499706130788c216ff14fd342809b45a4`、tree `6bc86196d10cf83b010f9917e5e9cb471b5f6b68`。真实有序父提交是：

1. `775bf555b0a7faf6eed17627acb0d0433294b737`
2. `3a39c799a3f776b0aeedfce350341d865d3cc1c4`

同 tree 的原生合并 commit 是 `c2834dcade885fb9ff5da41b3947773067ec652d`。两种 commit 原始对象分别校验，执行结果只归属于实际运行的 canonical 865。报告不会把原生合并、PR head、平台自动合并对象或证据发布提交的身份混用。

## 合并和导航核对

`stage_final_source.py` 对固定 raw commit、GitHub commit 元数据、原生 merge export、GitHub 精确父子比较及真实导航 preview 作联合校验。相对 775，最终 tree 仅变化 5 个路径：4 份 Windows CI 脚本/workflow 和 `codex-rs/hepta-operator-acceptance/src/openssh_windows.rs`。

4 份 CI 文件的 Git blob 与固定并发分支 3a39 一致。OpenSSH 文件相对 3a39 只增加原生 rustfmt 的 4 处换行布局和 2 处尾逗号，逐项重建后与最终 postimage 字节完全一致。合并只有一处 PTY 文件冲突，保留了 775 已审阅的显式 trait 选择及原生格式；精确 GitHub compare 证明该文件相对 775 没有变化。

真实 helper 在 canonical 865 上返回 `changedMaps=0`、`written=false`、`ledger=null`。40 张 Map 的 SHA256 与 775 一致，3 份既有 source-navigation history 也逐字节一致。5 个变化路径不属于这 40 张 Map 的 `resolvedRoots` 或 `observedSourcePaths`，因此未新增导航 ledger。历史 sourceBase、owner、caller/writer、claimBoundary、371 条 operation 及原 gate 保持原值。

## 主要固定输入

- `integration/canonical-complete-object.json`、`canonical-complete-metadata.json`
- `integration/upstream-3a39-native-export.json`
- `integration/complete-navigation-preview.json`
- `integration/live-base-073-to-3a39-compare.json`
- `integration/upstream-3a39-openssh-preformat.rs`
- `final-windows-report-prep/github-775-to-865-compare.json`
- `final-windows-report-prep/github-865-registry-capture.json`
- `windows-775-report-prep/MODULES40-SOURCE-FACTS.json`、`source-verified-blobs.json` 和 `source-snapshot/`

完整输入 SHA256、原生/规范身份、有序父提交和核对结果见 `source-verified-blobs.json`。原生或平台的执行状态不写入 source facts；它们在 `EXECUTION-OVERVIEW.zh.md`、相应历史执行总览及原始回执中分别记录。

## 重建命令

从重建材料解包后的根目录运行：

```bash
python3 final-windows-report-prep/stage_final_source.py
python3 final-windows-report-prep/build_source_report.py \
  --source-commit 8658210499706130788c216ff14fd342809b45a4 \
  --source-tree 6bc86196d10cf83b010f9917e5e9cb471b5f6b68 \
  --map-dir final-windows-report-prep/source-snapshot/docs/modules \
  --verified-blobs final-windows-report-prep/source-verified-blobs.json \
  --registry-file final-windows-report-prep/source-snapshot/docs/modules/MODULES.json \
  --canonical-objects integration/canonical-complete-object.json \
  --prior-facts windows-775-report-prep/MODULES40-SOURCE-FACTS.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history.json=final-windows-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-final.json=final-windows-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-final.json \
  --source-history qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-spelling.json=final-windows-report-prep/source-snapshot/qualification/module-execution-dossiers/modules40-20261105-da8578/source-navigation-history-spelling.json \
  --output-dir final-windows-report-prep
```

第二条命令加 `--validate-only` 可仅核对输入和原值，不写报告。固定源码通过显式参数绑定；历史身份没有被全局字符串替换。

## 输出与完整性

| 输出 | 完整范围 |
| --- | --- |
| `MODULES40-DEVELOPMENT-BODY.zh.md` | 40 个模块逐项能力、源码组合状态和下一门槛。 |
| `MODULES40-OWNER-AND-MAPPING.zh.md` | 全部固定源码根、owner、caller/writer 原状态、操作条目数。 |
| `MODULES40-OPERATIONS-AND-GATES.zh.md` | 371 项操作导航，以及每个模块的 operations、repository/external gate 完整 JSON 原文。 |
| `MODULES40-CRITICAL-PATH.zh.md` | 8 条跨模块工程依赖和完成判据。 |
| `MODULES40-SOURCE-FACTS.json` | 40 张 Map 的全部原字段、登记表、3 份 history 原文及来源元数据。 |
| `SOURCE-REPORT-VALIDATION.json` | 逐模块原字段/owner/gate/claim 深比较、输入 hash、原 commit 对象与输出文件 hash。 |
| `FINAL-PREDECESSOR-PRESERVATION-VALIDATION.json` | bb55 的 60 文件、797 的 58 文件、775 的 57 文件，共 175 个历史文件逐字节保留。 |

生成器在 JSON 往返后检查全部原 Map 字段，并解析操作/gate 附录的 120 个 JSON 区块，保证 371 项操作、108 条 repository gate 和 140 条 external gate 原值完整保留。40 个 sourceRootPresent 为 true，40 个 productionImplementation 为 false；scope/owner 状态保持各自原义，不以报告数量推导产品激活或生产完成比例。
