# PR #4798 科研增量核验

**本次没有发现该 PR 的新源码或原始实验结果，原科学 HOLD 不变。** 观察窗口为 2026-11-04 23:49:13–23:51:49 UTC；此结论仅覆盖 #4798 当前分支、最新 head 的工作流及 PR 文件/评论元数据，没有重新遍历旧 37 个实验归档。

## 固定身份

PR 仍为 open / Draft，head 为 `77b24407b9898aa44769502fbb22c24fb7193a58`，tree 为 `0f431f6a7c5f31a19f21563cae8e5221f5d03582`；base 仍为 `903946f15dd79bc53a39a479230e366df04a371f`。最后更新时间仍为13:58:49 UTC；2提交、9文件、0条普通评论与0条review comment均未变。收尾再次读取PR，head/base/更新时间/文件数/评论数全部一致。

九文件仍仅为README、报告、复现说明和脚本、派生分析与审计记录。报告 `7261cae919c01871977214136df50c0400948c53`、README `02396619f8031158a092f0b9ddaaca1904eb9b49`、统计收尾检查 `7506202102981c81be2cccfc58647c747689b832` 已重新完整读取并核验Git blob/SHA256。没有把旧派生分析当作新实验。

## 最新工作流实际结论

完整head查询共3工作流，均为原13:58:55 UTC发起、attempt 1；第2页为空。各工作流jobs同样分页至空页，共43个job，无重复ID。四个统计置信区间与GitHub CI是不同概念。

| 工作流 | Run | 结论 | 实际范围 |
|---|---:|---|---|
| Hepta architecture convergence | 41843067463 | success | 3 success，最后更新14:32:33 UTC |
| blocking-ci | 41843067204 | failure | 37jobs：11 success、14 failure、4 cancelled、8 skipped，最后更新15:03:57 UTC |
| v8-canary | 41843067199 | success | metadata 1 success；两个build均skipped，不能写成V8构建通过 |

此处head身份是Actions API元数据；本轮未重新读取每个job的checkout日志，因此不冒称实际source/合成merge身份。也未仅凭报告九文件差异，把各失败原因全部归为继承失败。逐job原文与状态保存在证据包。

## HOLD及下一步边界

原32/32注册拟合已完成。四个预注册主比较的家族校正置信区间仍全部跨零，0/4达到收益门槛；256个必需candidate × fit × domain项中，0项同时通过全部八个质量条件。后者是联合通过数，并非每个单项指标都0/256。无新输入改变这些结论。

`fpt_feedback`与`ordinary_feedback`是各自模型家族内多轮对单轮反馈，不能改称解析核替换的D−B主检验。未校正次级`analytic_increment`也不能升级为严格D−B或开放域优势。未达收益门槛不证明零效应、等效或普遍伤害。

已完成的是缺失报告/分析的交付缺口；质量、收益、完整成本和外推门槛继续保留。历史已核CPU仍为下界8,326.229650133秒；开发001、开发002、被中止正式训练001的控制器自身CPU仍缺，没有新收据补回。未来若继续，应先在TRAIN/开发数据改进质量，再冻结新协议与完整成本口径，使用新确认身份；已读确认集不能调参后再冒称未见。

## 可复核证据

- API原文包：`24e7a368a0614410aa3618f5dcbc7afbfac89710`，288,339 B，SHA256 `03ea0c46a985f45ccdbb7e944bd48f117ee9df32ad91dede7d0cbb46517dbfd5`。13个返回体含终止空页；哈希为connector解码UTF-8 JSON，不是HTTP压缩字节。
- `fourth-research-current-delta.json`保存固定身份、3工作流/43job、9文件、分页检查、原件哈希和完整限域。
- 并行R2e3范围独审：`2cc31c4e2e812294ef1523ebd8d96edfe63ca8ed`。仅接受成功注册后连接custody的静态说明；注册前取消、Current/final-use、其他opens与raw-handle替换仍OPEN，控制未执行，不构成科研证据或B16闭合。

没有搜索其他研究分支或本地未发布实验，不能声称全局不存在新研究。没有修改源码/ref/PR状态或原生工作区，没有新实验和native构建。
