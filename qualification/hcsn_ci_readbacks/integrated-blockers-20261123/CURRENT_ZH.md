# Hepta 研究与集成核验

## 已回答的研究问题

| 问题 | 原始条件和结果 |
| --- | --- |
| 固定连续阈值能否作为可微算子 | #7015 已实现一维常系数、单吸收边界、点初态、最多一次不应期释放的算子。概率、重置后的存活质量、第二次触及、有符号跨层标记及梯度均有独立数值参照。两套 CPU Torch 环境各通过原 12 例，458 个输出逐项相同。[源码](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7015) · [两机原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7906cc6b4a89ce1bca41d4ccf402a692390400b9/qualification/hcsn_ci_readbacks/halfline-67b04d5) |
| 什么查询值得花价钱 | 22 个新录制来源上的分区和价格均已冻结。实测梯度策略的测试效用为 0.765625，免费为 0.6875，最差来源损失 0.075 超过容许的 0.05。以往 22 个主策略均未达到采用条件。新复算表明即使知道每一题的两种答案，九个可救错误也只落在三个测试来源。全部 2³² 个首时点动作组合中满足原统计准则的有零个。训练、开发分组给出了音频头与图库分歧时的净购买收益，也重算了真实传感器上等待 0.48 秒的十二组结果。[效用与分组](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f88428b64033ff417a7f4af9ea985bc0d4ea92/qualification/hcsn_ci_readbacks/purchase-attainability-20261123/README.md) |
| 能否靠编辑取代 BP | 当前证据支持冻结非线性部分时直接求解条件线性读出。实际干预的来源保持门槛和双对照检验仍未达标。在同等新来源效用、检索质量和最坏保持下限下，尚无胜过 BP、传统 SNN 或 Transformer 的训练墙钟结果。[五种适配方法](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0307d62f4d4226a979692cb4420746e8c84af0d4/qualification/hcsn_flow_integration_v1/RESULTS.md) |

## 已终结的仓库级运行

#7013 的源 c6a3ed9c 和 prospective merge 14272605 具有相同 Git 树。原 blocking-ci 的 46 个作业包括 34 项成功、6 项按工作流条件跳过和 6 项失败。Linux GNU、musl、macOS ARM、Intel 的原 Bazel 测试，Linux、macOS、Windows 的原 Bazel Clippy，以及仓库 build-test 均成功。完整权限调用检查涵盖 9,141 个 Rust 源文件、1,652 个边界、826 个受保护文件，权限授予标志为 false。[46 个作业逐项状态](c6a-blocking.json) · [原运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165932) · [完整权限回执](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7c0e392f4f9348d587c366d145f94325c69fc002/docs/learning/evidence/agentd-private-migration-20261123)

六个红色作业中包括汇总门。底层失败有两个来源。

- 两个原始 Rust 严格构建在 source 和 prospective 各报 128 项。后续修复四项，在不同的两个 musl ELF 上各通过 51 个原测试，严格命令仍以 124 项诊断退出。这 124 项包含 71 个参数过多、40 个变体过大和 13 个未使用代码诊断。[四项修复及原件](strict-four/) · [双源严格作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45127907565)
- Windows shard 4 的最终 test.log 共有五个失败。其中四个原隔离正例在连续四次同源系的原生运行均失败。第五个是分离会话等候 WebSocket 事件超时，此前同名测试三次通过。另外两条在中间尝试中失败但最终通过。Windows 私有状态专项独立成功。[四次逐用例原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/8e7de7cc4b195df4bb588067ea1ea684c11b3ead/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/windows-capability) · [私有状态专项](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165764)

## MemoryCell 启动

原先缺两个测试子进程，随后一次运行又因冷编译用完 30 分钟而中止。将同源编译与正式执行分开后，原 c6a 全部 1,552 项得以运行，1,547 项通过，五项仍找不到同一个带连字符的子程序。增加 Rust 定位器原已支持的下划线环境变量后，独立托管机在同一套三个 ELF 上逐项通过全部 1,552 项。171 个原始忽略项及四个原控制组均核对通过。[未通过和通过的原 ZIP、独立复算](memory-startup/FULL.md)

#7016 已把四项 Rust 修复和便携子程序绑定放入同一源码。该 PR 的完整原 run 与上述同二进制实验分别记录。[新集成 PR](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7016) · [原启动作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787247)
