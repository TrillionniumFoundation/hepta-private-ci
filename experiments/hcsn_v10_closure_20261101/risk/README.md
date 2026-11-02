# v10：输出截止余量与风险目标分离

本轮在登记的有界合成执行范围内修复 v9 的 flush 缺口。新执行器把服务等待截止设为 **2.0 秒**，硬输出截止保留 **2.4 秒**；0.4 秒余量明确分给 head 0.08、序列化 0.04、sink 0.08、调度 guard 0.20 秒。实际最终输出写文件、`flush`、`fsync` 后才判定是否满足硬截止；迟到 worker 在输出完成后排空并丢弃。

`execution.py` 是从 v8 隔离复制的新文件，旧 v8/v9 源码没有修改。`results/closure001/PLAN.json` 固定基线 `8cc469fcb0e6527fac56e26b65baa3ae1c09c86b`、七个依赖源码 SHA256、预算和完整条件；`EXECUTOR_DIFF.patch` 保存相对 v8 的准确差异。

服务 timeout 与最终输出违约现在有两个不同的目标。公开快慢服务 law 的 timeout 概率为 0.5；内容预测已经包含“成功取得 video”与“timeout 后沿用当前内容”各半的回退。新 reserve 合同在登记 finalization 预算内，输出违约概率为 0。这个额外违约罚项不能再次扣掉已经在内容预测中反映的 timeout 损失。旧无 reserve 合同仍保留输出违约概率 0.5，以复现实验差异。

先冻结新合成传感 law（audio 正确率 0.72、video 0.96）、16 个完整因子逻辑世界和八个预先指定的实际半分数世界，再执行六臂。实际世界不是 iid 录制或自然 AV，新名字也不构成独立真实 AV 资格。六臂包括旧 full/zero、新 reserve full/zero，以及两个跨合同固定动作回放。

| 结果 | 逻辑（16 世界 × 6 臂） | 真实单调时钟（8 世界 × 6 臂） |
| --- | ---: | ---: |
| 新 reserve full − zero 净效用 | 0 | +0.0000137720 |
| 固定旧 zero 动作：reserve − old 净效用 | +0.5010375 | +0.5008797010 |
| 新 reserve full − 旧 full 净效用 | +0.0973875 | **−0.0226892848** |
| 新 reserve 固定动作/内容/请求费一致 | 全部一致 | 全部一致 |

新 reserve full 与 zero 的动作和内容相同。真实时钟微小差值来自重复执行的时长差，不是独立风险机制收益。固定旧动作的修复对比保持每世界的内容概率、实际请求数和 observation fee 完全相同，其收益来自消除原输出违约和缩短等待；不能把它改称解析核心或风险内容表示的优势。实际子集的 reserve full 相对旧 full 仍为负，原始结果完整保留。

登记正常范围内的 **24/24 次实际 reserve 运行**全部满足硬输出截止及四项 finalization 预算。这些运行包含 **12 次服务 timeout、0 次输出截止违约**。旧 zero 及其旧合同固定回放共有八次实际服务 timeout，也产生八次输出违约。迟到 video 均未进入输出；跨合同固定回放的实际请求费全部相等。

另有两个预先登记的实际超约探针：head 延迟 0.45 秒、sink 延迟 0.45 秒。两者均被记录为预算不满足且输出违约，仍在 flush 后排空 worker。**本轮不保证任意 head、sink 或操作系统停顿下的硬实时输出**；成功范围限于本次声明、执行并核对的有界 profile。

七项行为检查通过，标准库原始记录审核通过 2,413 项检查，覆盖 144 次正常运行和两个实际超约探针。`AUDIT_SUMMARY.json` 是本线可复算审核，不冒称外部独立审稿。

四个阶段分别由经济性 wrapper 唯一执行，全部成功；外层 CPU 秒依次为 prepare **0.188767**、validation **0.222090**、execute **15.762415**、audit **0.111349**，合计 **16.284621** 秒。执行阶段壁钟 **111.91345708** 秒。外层包含测量器，内层 task CPU **7.857925** 秒、monitor CPU **7.848146** 秒只是已包含的诊断，不能重复相加。完整收据位于 `../economics/results/risk_*001/`。历史准备成本、设备能量和连续精确进程族内存峰值仍未知。

复现应为每次 prepare 使用新的输出目录，并由同一经济性工作流依序计量：

```bash
python -m experiments.hcsn_v10_closure_20261101.risk.study prepare --output /tmp/risk-v10-new
python -m unittest experiments.hcsn_v10_closure_20261101.risk.test_study -v
python -m experiments.hcsn_v10_closure_20261101.risk.study execute --output /tmp/risk-v10-new
python -m experiments.hcsn_v10_closure_20261101.risk.audit /tmp/risk-v10-new
```

原始入口依次为 `PLAN.json`、`runs.jsonl`、`stress.jsonl`、`EXECUTION_COMPLETE.json`、`AUDIT_SUMMARY.json`。真实 AV 准入、强头、解析核心增量和全面经济优势均不由本轮证据闭合。
