# Group 推理闭环 V2 三种子实验交接（2026-10-15）

已执行固定真实 Granite97 Encoder、轻量 Group 核心训练、冻结 critic、现有 System2 回调和独立程序标签复核；V2 三个种子均完整训练，独立复核均通过。V1 的失败及不完整训练记录在证据包 failed-v1 中保留，不进入 V2 汇总。

三种子合并测试结果：static 31/288；wide 28/288；fixed 26/288；adaptive 26/288；ndu 26/288；no_verifier 26/288；reset_state 26/288；split 31/288。分类正确率接近八分类随机基准，未观察到递归或 NDU 的推理准确率优势，不能据此认定学习到的推理已经涌现。NDU 实际测试步数 288，固定深度 1152；但 NDU 在线 CPU 合计 2.710874 秒，高于静态 Head 的 0.918265 秒。这些时间仅覆盖在线路径，排除共享 Encoder 摊销、模型训练和 critic 拟合；不能解释为全生命周期效率优势。三个 split 候选均被独立选择门槛拒绝，继续保留父模型。

| Seed | Arm | Test 正确率 | 实际步数 | 在线 CPU 秒 |
|---:|---|---:|---:|---:|
| 41 | static | 13/96 (13.54%) | 96 | 0.3398 |
| 41 | wide | 10/96 (10.42%) | 96 | 0.2936 |
| 41 | fixed | 9/96 (9.38%) | 384 | 1.7654 |
| 41 | adaptive | 9/96 (9.38%) | 270 | 1.9450 |
| 41 | ndu | 9/96 (9.38%) | 96 | 0.9912 |
| 41 | no_verifier | 9/96 (9.38%) | 384 | 1.7865 |
| 41 | reset_state | 9/96 (9.38%) | 384 | 1.8887 |
| 41 | split | 10/96 (10.42%) | 384 | 2.3117 |
| 47 | static | 10/96 (10.42%) | 96 | 0.2939 |
| 47 | wide | 9/96 (9.38%) | 96 | 0.2940 |
| 47 | fixed | 9/96 (9.38%) | 384 | 1.6539 |
| 47 | adaptive | 9/96 (9.38%) | 96 | 0.8739 |
| 47 | ndu | 9/96 (9.38%) | 96 | 0.8449 |
| 47 | no_verifier | 9/96 (9.38%) | 384 | 1.5050 |
| 47 | reset_state | 9/96 (9.38%) | 384 | 1.6318 |
| 47 | split | 13/96 (13.54%) | 384 | 1.9903 |
| 53 | static | 8/96 (8.33%) | 96 | 0.2845 |
| 53 | wide | 9/96 (9.38%) | 96 | 0.3008 |
| 53 | fixed | 8/96 (8.33%) | 384 | 1.5941 |
| 53 | adaptive | 8/96 (8.33%) | 272 | 1.8972 |
| 53 | ndu | 8/96 (8.33%) | 96 | 0.8748 |
| 53 | no_verifier | 8/96 (8.33%) | 384 | 1.4544 |
| 53 | reset_state | 8/96 (8.33%) | 384 | 1.5083 |
| 53 | split | 8/96 (8.33%) | 384 | 1.9079 |

- Seed 41：四种模型均完成 120 个真实 SGD 更新；参数数 core=19112, split=22474, static=3152, wide=19265，critic=14。Encoder 实际 forward 754 次，逻辑请求 832，缓存规范字节数 199312492；该字节数不等于 Python 进程峰值内存。Split 决策 reject_candidate，保留模型 core。
- Seed 47：四种模型均完成 120 个真实 SGD 更新；参数数 core=19112, split=22474, static=3152, wide=19265，critic=14。Encoder 实际 forward 756 次，逻辑请求 832，缓存规范字节数 199794066；该字节数不等于 Python 进程峰值内存。Split 决策 reject_candidate，保留模型 core。
- Seed 53：四种模型均完成 120 个真实 SGD 更新；参数数 core=19112, split=22474, static=3152, wide=19265，critic=14。Encoder 实际 forward 757 次，逻辑请求 832，缓存规范字节数 200484666；该字节数不等于 Python 进程峰值内存。Split 决策 reject_candidate，保留模型 core。

NDU 的 continuation 区间来自独立 calibration 样本的最大残差，是经验包络，不能当作未来支持或置信保证。固定深度、普通 gate、NDU 和 split 消耗不同，未建立等计算量比较；相同步数上限也不代表实际成本相同。结果包括状态重置、删除证据、长链和未训练组合的程序任务消融，尚未证明自然任务的未来收益、通用推理涌现或多模态生成能力。多模态目前只完善了带位置、时间和模态标记的接口。

真实 Encoder 的 aten.silu.default 仍未被当前算术 profile 完整覆盖，因此完整 Encoder FLOPs 保持 null；已知部分、CPU/墙钟和进程峰值内存原始记录均保留。原生 Q32 三次 replay 与独立精确参考一致，但范围仅为已完成轨迹的离线重放；未接通生产 NDU owner、未完成全工作区 Rust 资格验证，也不是一般 FBSDE 求解器。证据分别绑定实验实际使用的二进制，以及独立重建脚本验证得到的二进制；构建产物 SHA 不同，未声称两个二进制相同。

最终修正后 Python 测试为 332 passed；完整日志随包保留。云端 CI 最近记录为 queued，本报告未将其计为通过。实现 PR 为 [#2263–#2269](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2263)，统一入口 [#2271](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2271)。

证据包：`hepta_group_reasoning_pretrained_v2_evidence_20261015.zip`；SHA256：`692283c5bd54793348c701fbb115e6dc33e2625109ad0da0bee7fa9576641d96`。包内 RAW_FILE_HASH_MANIFEST.json 逐项绑定原始文件；不包含源码副本、权重或特征张量。
