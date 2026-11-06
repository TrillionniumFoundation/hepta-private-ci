# 最终报告升级准备

本目录只准备一次最终候选生成器；旧 `r30-closed-candidate-v2`、checkpoint6 canonical 三报告、INDEX、ledger 及所有已冻结正式组均保持原字节。

`FUTURE-BINDINGS.json` 是不可执行的空值示例。只有实际 finalization 新正式组已闭合，root 已登记格式化后代码 commit/tree，并提供实际 commit API、独立 readback 与固定 ledger 原文后，才写新的 `ACTUAL-BINDINGS.json`；不能把示例中的 null 当结果。

```sh
python source53-final-report-preparation/build_final_reports.py \
  --bindings source53-final-report-preparation/ACTUAL-BINDINGS.json
```

这个命令仅本地读文件和生成候选，不调用网络、Git、native、测试、metadata 或 formatter。所有内容与保护断言先在内存完成，最后才 create-only 写新 final-candidate。生成三报告、PR 短正文/完整 body/审阅 guide/197 路径表、精确差异、JSON pointer 变更、输入 pins 和交接清单；canonical 是否采纳由 root 单独处理。

实测 source53 f74/440 的 R30 1,345 PASS 与 R31 20,228 PASS 分别保存，不相加。fix→默认 fmt 的原回执、3 个诊断 warning 与 3 条汇总、最终格式化树/commit 另列；格式化后没有本地测试，最终 SHA CI 待真实结果。科学 HOLD、DENY_ALL、两套七分类、Q24 与 Encoder/FeatureBundle 边界、历史失败及 source53 diagnostic-only 限定保留。

最终候选可以是 `READY_FOR_STACKED_DRAFT_PR`；它只说明具体材料可供 root 执行后续步骤，不宣称 branch、PR、CI 或发布已经发生。新代码登记的固定 ledger 与此前 53 source / 235 binary / 6 artifact 历史快照并列保存，不反复追写旧快照。
