# 精确 v8 原训练 trace 的记录范围

**4096 条记录 / 32MiB 的 cap 不可能覆盖一个完整 ABC epoch，更不能覆盖至少 30 epoch 的训练。** 这个结论只用冻结源码、预声明计划和精确数据 manifest 推出，没有读取仍运行的六个原生 HCSN fit。

八个相关源码文件已与 `training-source-v8.zip` 逐字节相等；源码包 SHA256 为 `288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102`。原计划 SHA256 为 `e13f97aafdaf66548f016f2dcc3a38dd7e641a2ea83d52b8bea89f4c7e0cf114`；数据 manifest SHA256 为 `0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb`。完整文件路径、大小和 hash 见 RESULT.json。

## 记录发生在哪里

Recorder 在 memorization 结束、原初始化和 optimizer 恢复以后创建。诊断过程、初始 D 评估、各 epoch 的 D 评估和最终 best 的 D 评估都不在这个 recorder 的访问范围。

在 main update 中，trainer 为每个 microbatch 设置按顺序连接的 episode IDs 和 `update_index`；后者是此次有效 batch 开始前已经完成的 main optimizer 更新数，第一批为 0。同一有效 batch 的各 microbatch 共用该编号。

`HCSNCore.forward` 先从新的 initial state 完整计算该 microbatch 的序列，再调用 capture，然后才把预测返回给 loss/backward。每个 microbatch 都在该有效 batch 的唯一 optimizer.step 之前。因此这些是当前参数版本下、更新前的完整 forward 状态，首批仍对应主训练初始化。之前 microbatch 的 backward 可以已发生，但参数尚未更新。

只完成了 forward 不等于该次 update 已完成。若之后 backward 或 optimizer 失败，捕获状态仍可能存在；若 forward 在 capture 前中断，已经访问的部分内部状态不会进入这个 trace。完整覆盖还需要更新 journal，不能仅凭 footer 的 seen 计数。

## 一条 record 的单位

一条 visit 对应一个 `(capture, time position, layer)`，含该时点所有有效 microbatch 样本的向量。这里 microbatch=8、layer_count=1，所以每条最多含 8 个样本时点；它不是一个样本、一整个 batch 或一次 optimizer 更新。

- `prior` 是间隔起点的上一 conditioned probability（position0 是 initial state）。
- `posterior` 是本间隔 flow 和当前 observation conditioning 完成后的 probability。
- `expected_events` 是当前 observation conditioning 之前的 flow 给出的条件期望间隔计数。
- `model_sha256` 是内部 ContinuousSpikingNetwork 的 tensor digest，不是完整 CoreStudyModel、optimizer 或 checkpoint 文件 SHA。

每条含完整 273 维概率向量以及物理参数、GridSpec、operator 配置。Recorder 本身不保存 content_mass、全部模型权重或梯度。数据与 fit plan 由 header 绑定；完整 trainer/runtime 来源仍要连接 fit 的 source ledger。

## Padding 与限额

batch builder 在每个窗口真长度之后填 `x=0, dt=0, y=-1`；microbatch 保留有效 batch 的 padded time length。HCSN 用原输入的观测 mask 同时设置 `observed` 和 `valid_mask`，内部 network 的 predictions 在 padding 位置必须为零；随后公共 head 的 bias 可以令最终分类 logits 非零，这些位置由 `y=-1` 排除出 loss。每条 `batch_indices` 是 microbatch 局部的有效行索引；全 padding 的时间位置不会新增 seen/retained record，但仍计入 `padded_states_excluded` 的样本时点层计数。

记录按实际调用顺序保留前缀，既不是随机抽样，也不是分层覆盖。首次碰到 record 或 byte 限额后停止全部后续 retention；32MiB 检查额外预留 16384 bytes 给 footer。此后仍统计 captures、seen、ranges 和 padding，不能据这些汇总恢复未保存的 posterior。footer 缺失时 `read_trace` 拒绝完整性；`truncated=true` 必须保留。

## 不足一个 epoch 的严格计数界

精确 manifest 有 356 个 ABC 窗口、89,216 个事件。batch32 / micro8 对每个完整 epoch 对应 12 次 optimizer update、45 次完整 microbatch capture。

每条 record 至多含 8 个有效样本时点，所以一个完整 epoch 至少需要 `89216/8 = 11152` 条 visit。4096-record cap 最多保留 `4096×8 = 32768` 个样本时点，已经少于一个 epoch。至少 30 epoch 时共有 `30×89216 = 2676480` 个主训练样本时点；即使忽略 byte cap，最多保留 **1.2242945958871354%**。32MiB 限额只可能进一步降低覆盖。实际 retained 数和首次 drop 的 update/position 必须等原 trace 原件与 footer 到手后确定，本记录没有推造这些结果。

最终 best checkpoint 上重新导出的固定窗口 posterior 应明确为 **supplemental final-model evaluation**，独立绑定最终 checkpoint 文件、tensor/config、窗口、数据和导出源码。它能回答最终模型在这些窗口上的状态问题，不能补称原训练全过程访问轨迹。整体数值资格继续 HOLD。
