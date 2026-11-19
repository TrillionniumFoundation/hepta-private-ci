# HCSN P0–P5 本轮研发门禁台账

本轮核验时间：2026-10-30 America/New_York（UTC 已为 2026-10-31）。这是一次有明确范围的 P0 数值修复准备，不是六阶段生产验收。所有来源 PR 在检查时均为 Draft，不得改称 Accepted。

- GitHub 主干冻结：`TrillionniumFoundation/hepta-private-ci` main `732e934ba496d90fbe042b8d41d479ef901643e5`。
- 本轮针对已存在的 P0 研究栈 PR #4455 HEAD `8a216c3d084680d79f2c491031e83271e1db62c5`。目标研究文件 `experiments/hcsn_hx_unified_v3/hx.py` 的 Git blob `b6afc3c957297ed9b37b4f0177e0343ee6607f83`。
- 已通过连接器创建空的候选分支 `dot/hcsn-p0-hx-first-passage-envelope-20261031-gpt6`，对应上述父 SHA；GitHub 实际源文件和测试写入被平台安全拦截。**没有产生源码提交，没有 PR，没有合并，也没有部署。** 本地补丁需后续在正确源仓路径实际应用并独立测试。

| 阶段 | 本轮与既有真实证据 | 尚未达到的关闭证据 | 判定 |
|---|---|---|---|
| P0 数学 | 复现 HX F/G 逆序的双精度反例，制作 fail-closed 小补丁和独立测试；已有 #4380、#4453、#4455 的障碍/标量 QVI/精度研究 | 全域耦合 HX 障碍和自洽边界、可证明的首达积分舍入/尾部界、FP32/BF16 真机、整仓回归 | OPEN |
| P1 机制 | #4438 为局部斜率对照添加数值诊断；既有对照 0/4 机制门未通过 | 未见数据先注册，Call/Risk/Margin 单项/两项/三项对照、同信息与局部斜率、同有效参数和完整成本 | OPEN |
| P2 记忆 | #4447 真重复事件 CTMC 参考、#4450 checkpoint 因果拒绝；已有有限状态恢复 | 真实长时 Copy、MQAR、覆盖写入、连续事件与多次再生结果在未见长度上达到质量门 | OPEN |
| P3 多模态 | #4362 研究中有音视频真实演员任务，GitHub run `41158089224` 核验当时 job 为 in_progress | 独立文本/图像/音频/视频 encoder，实体/时序配对、跨模态检索、缺失模态 OOD，外部基线 | OPEN |
| P4 原生与硬件 | #4362 有 CPU 加速与训练状态→Rust owner 的有限执行链，非 Rust 神经算子 | GPU/Rust 内核、64/256/1024/4096 Cell 端到端吞吐/p99、真实焦耳、断电/重启 | OPEN |
| P5 扩模 | #4362 研究 run `41156755829` 核验当时 job 为 in_progress；历史负结果保留 | 公平的共享 Encoder+HCSN Head 对 Transformer/SSM 强基线在等质量、数据、预算下净收益 | OPEN |

研究准入：`DENY_ALL`、`all_blockers_closed=false`、`production_activation_allowed=false`。任何定量收益必须绑定具体数据分割、源码、环境及完成的工作流。`queued/skipped/cancelled/in_progress` 不视为 PASS。
