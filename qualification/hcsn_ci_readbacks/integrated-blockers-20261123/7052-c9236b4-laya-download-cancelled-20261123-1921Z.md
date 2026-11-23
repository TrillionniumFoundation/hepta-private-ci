# #7052 c923 MemoryCell Laya 原生外部下载与取消（2026-11-23 19:21 UTC）

原 [MemoryCell workflow 45240608027](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45240608027) 精确源码 `c9236b4ee6d73a8de3bf4ccb7887a41715738d3c`，现在为 **completed/cancelled**，不应继续作为“还在运行”。

[原 Laya job 137934297752](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45240608027/job/137934297752) 中，`Install and stage the pinned Laya checkpoint` 阶段最终 **cancelled**；之后训练 `Train actual Laya scorer tensors and retain held-out outputs` **skipped**。原日志逐行证实：

- 模型源固定为 Hugging Face `convaiinnovations/laya`、revision `7b928d828b7b0e022f929d9bd2e44165aa270148`，目标文件 `model.safetensors`；
- 18:59:44 开始抓取五个文件，模型权重后端 `us.aws.cdn.hf.co` 至少在 **19:03:24、19:08:32 UTC** 发生 HTTP read timeout 并尝试续传；
- **19:21:13 UTC** 原 job 报 `The operation was canceled`。临时上传目录 `/tmp/laya-evidence` 没有文件，上传步骤明确 `No files were found`，因此没有 Laya 独立训练/held-out 资格工件。

其他 6 个 MemoryCell job 包括 [source-format 137924066774](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45240608027/job/137924066774) 全部各自 success，不受已取消 Laya 作业的伪装影响。原 [Learning artifacts workflow 45240608033](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45240608033) 独立 success。

此为外部模型交付/输入依赖阻塞，不是 Laya 模型通过，也不能直接断定取消是 CDN 超时引发（工作流取消的上游触发者未在此日志证实）。应先验证原固定 revision 的可获取性、权重实际大小、完整 SHA/内容签名与供应链来源，再考虑在不改变预定数据、模型、测试与来源的情况下使用可验证缓存/镜像作单次原生运行。不得凭取消自动重试、改变来源或以其他模型冒充。此轮不触发任何重复 CI。

全仓仍 HOLD，#7052 仍 Draft。此处仅归档真实后续终态与此前 19:20 的在途快照的差异。
