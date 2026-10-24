# 本地阶段关闭记录

## 结论与范围

本轮冻结协议定义的 **真实 770D 运行、私有训练、队列恢复和完整证据恢复工程验收全部通过**。没有访问或等待远端 CI。任务质量没有重新评估，所有新产物仍为 `SHADOW_ONLY / DENY_ALL`；原生生产执行未接入。

“本轮关闭”对应 [CELL_RUNTIME_770_PROTOCOL.md](../../CELL_RUNTIME_770_PROTOCOL.md) 在真实测量前声明的范围。前轮已观察到的高置信正向动作覆盖不足、没有稳定门控增益、任务多样性不足等质量问题继续保留，不能被参数校验或系统吞吐结果自动关闭。

## 已完成的本地验收

| 验收 | 状态 | 具体证据 |
|---|---|---|
| Bounded 校准与批量运行接口 | PASS | 直接复用原校准公式；feature、实际 predictor、外部 context、完整校准和 task 共同绑定 |
| 快照、输入边界与缓存 | PASS | 相关 44 个独立测试通过；NPZ 在分配前核验 header/shape/size；拒绝过期身份和不一致来源 |
| 真实服务矩阵 | PASS | 3 结构×3 scales×3 batches=27 条件；physical/logical 逐位相同，scalar 容差和决定一致 |
| 独立私有训练 | PASS | 9 条件、161280 updates；同初值、固定容差；全部最终批量参数保存 |
| 真实 job 接管 | PASS | Linear attempt 1 在优化前退出，fresh attempt 2 完成唯一一次 20-step 训练并发布 |
| Token/generation 隔离 | PASS | 真实旧 token 在 replacement 发布后被拒；运行中隔离由独立 logical-clock metadata 对照验证 |
| 参数更新后的校准失效 | PASS | 队列三份新 Head 都为 uncalibrated；旧 predictor 校准不重新绑定 |
| 完整异路径归档恢复 | PASS | 234 文件、230 内容对象；恢复前后文件大小/SHA/ordinary-file/link count 完全一致，无额外文件 |
| Fresh-process 对照原结果 | PASS | 13 子进程：restore 1、serving 1、checkpoint 9、queue 1、facts 1 |
| 全参数与固定预测恢复 | PASS | 4032 参数状态槽位全部摘要核验；每条件首尾固定预测与原报告相同，三份 queue publication 相同 |
| 固定事实和成本绑定恢复 | PASS | facts 输出逐字节相同；45 个成本账输入文件映射到恢复路径逐一核验 |
| 成本可审计 | PASS | 主账与 closing 分开；内外层不重复相加，失败工作和未知项保留 |

数值主运行代码已固定在 `bb0d5c67ab5457e551b97fbda9a57390e3a69425`；包含恢复/绘图工具的已保存提交为 `201cccfcee22ad787fc491f484268beaa4cfdb56`。每个真实 probe 在运行前后检查其数值代码 SHA，异路径 replay 再次与主报告代码 pin 比较。

## 完整恢复实测

归档：`hepta-cell-runtime-770-evidence-v1.tar.gz`，147,909,524 B。

```text
Archive SHA256 f2fa364efa81ffb96bfc27bc5517c43a4d3b1dcd3374d9eee7660d6c250cc498
Index SHA256   afcb12d61f1e62e86951886733f537e5a48909f5c9e2aa74b76de26cf1c2ccad
Facts SHA256   aa3641e69da7c4202b4b49ef62ddb7b355330aa157e9211802e578c8c6fb4be6
```

恢复目标与原始实验分离：`/tmp/hepta-cell-runtime-restore-20261024/runtime`。全部 154,374,750 个逻辑字节在 replay 前后保持一致，SQLite 重新打开后也没有改变封存文件。参数槽位中的跨 scale 重复没有被当作新能力；不同最终批量参数摘要数仍是 3072，任务仍只有一个。

| 完整外层工作 | Wall 秒 | Parent+child CPU 秒 |
|---|---:|---:|
| 归档构建、压缩、index 与最终校验 | 5.672705846 | 5.647472764 |
| 异路径 restore、13 子进程、前后 inventory 和对照 | 4.874638412 | 4.847588893 |

这些计时包含其内部工作。Serving replay、checkpoint verification 和 archive restore 的子计时是诊断分解，不能再加到同一外层小计上。13 个子进程共包含 11 个数值验证命令，没有优化器更新、Encoder 调用、校准拟合或质量评分。

完整关闭收据及原始 stdout/stderr、来源 SHA 见 [closing-evidence.json](closing-evidence.json)。数据包在 build 前冻结，因此 build/recovery 产生的收据留在此 Git 交付中，没有递归重打包原始数据。复现命令见 [REPRODUCE.md](REPRODUCE.md)，文件定位见 [delivery-index.json](delivery-index.json)。

## 仍不能授予的资格

| 问题 | 当前结果 | 下一份有效证据需要什么 |
|---|---|---|
| Head 是否更会解决真实诊断任务 | 本轮没有新质量实验；旧高阈值正向动作覆盖仍不足 | 未被选择过程暴露的新任务和 outcome，固定校准/决策规则 |
| 门控是否优于 linear | 前轮没有稳定优势，本轮只测执行与训练成本 | 匹配预算、独立数据、完整基线和区间估计 |
| 1024 Cells 是否等于 1024 技能 | 否；1 个任务，分别测副本分发和独立参数更新 | 数十个真实定义任务和跨任务学习曲线 |
| n128 是否补齐 | 否；224 条新候选仍只是 metadata，未准备 outcome/features | 有效训练组数、隔离划分和完整执行来源 |
| 某个 Encoder 是否普遍最优 | 没有证明；Granite 仍是条件性文本/代码成本基线 | 对具体工作负载比较表示质量、增量成本和模态缺口 |
| 多模态是否从文本 Head 自动长出 | 不能由本轮结果推出 | 实际模态前端、对齐、局部特征和来源/时间契约 |
| 原生生产 Cell 是否已经接入 | 没有 | 沿现有 owner/head 边界实现并通过原生、任务质量和权限验收 |
| 中间优化状态是否可续训 | 没有保存 Adam moments | 单独定义并验证优化器 checkpoint/恢复协议 |

## 收尾约定

所有数值实验和 fresh-process 恢复均在最终格式化之前完成。按根 `AGENTS.md` 执行 `codex-rs` 下的 `just fmt` 后不再运行测试。实际 formatter 输出、最终源码提交/树对齐及后续 terminal 成本保存为独立收据；它们不回写主账和本页引用的 closing cutoff。没有 Rust 源码变更，不把 formatter 成功说成全 Rust 编译或生产集成通过。
