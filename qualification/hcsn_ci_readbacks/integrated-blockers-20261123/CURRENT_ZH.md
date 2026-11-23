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

## #7016 的仓库终局与后续源码

#7016 已完成原仓库级 CI。e3277e96 的 46 个作业中 33 项成功，6 项因条件跳过，7 项失败。失败项包含 Windows 汇总、learning.operator 汇总和 CI 总门。Linux GNU、macOS 两个平台、repo-checks / build-test 和 NDU v6 实际运行成功。两个 Rust 严格作业失败，Windows shard 4 和 Linux musl 作业失败。[46 项及失败步骤](e327-blocking.json) · [原终局](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598)

- Windows 第五次原生运行的最终日志中，四个隔离正例仍失败。此前超时的分离会话这次成功，原目标 1.7 秒；另一次定位作业在三个完整原目标和三个只增上下文的完整目标上实际通过 36/36。[原生四项完整历史](windows-capability/NATIVE.md) · [会话复核](windows-detached-session/DETACHED.md)
- 两个严格作业在 e327 源和 prospective merge 各报 124 项。后续固定资格源码 43e5 将九项修复合到同一处，实测从 124 降到 115，新增零项。它在新 ELF 上通过原普通 62/62 和真实 UID0 30/30。基线普通 62/62、UID0 29/30，唯一红是取消后过早读取队列。用原条件观察十个独立 UID0 进程，五次实际返回队列仍满，五次返回原断言要求的不可用。归档保留两臂真实失败状态。[组合原 ZIP 及剩余 115 项](combined-43e5/) · [首次直接观测](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45134423798)
- Linux musl 的滚动升级夹具有一次未在原时限收到 drain ACK；原生 core 的最终失败涉及子代理通知写入父 rollout。已分开检查最终失败与各自中间重试。[原 musl 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598/job/137546561415)

默认分支冻结点的全部 8,665 个 blob 已在第二台托管机重新从 Git 原对象散列，97,364,825 字节全部相符。[审计原报告、清单和第二次回执](../repository-inventory-732e934/)

在冻结的媒体价格和前端下，允许每题自由选择六个时点和免费或付费答案后，32 道 TEST 查询中只有 3 道值得等；它们来自 3 个来源。预知上界的平均等待增益 0.008722，低于原定 0.015，DEV 的 24 题等待增益全部为零。逐来源预知上界延伸到全部 12³² 种终止动作分配后，所能得到的相对立即免费最小单侧 p 为 1/16。首时点的两项 Holm 采用判据在这个延伸分析中仍不可能同时通过。[三个分区的效用与计算](../purchase-attainability-20261123/README.md)

e327 的仓库 build-test 原输出中另提取了 770,005 字节的权限调用回执。与 c6a 已归档回执逐字节一致，SHA-256 为 2de991230d84e60c8d440278ceb189e0f4111ce8b7c200a934ffc7a31257d6c3。实测相同的 9,141 个 Rust 文件数、1,652 个清单边界、826 个受保护文件与 authorityGranted=false。[e327 仓库原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598/job/137546560666)

e327 自身从冷检出重新编译的原始启动工作流也已成功。新 Agentd 二进制长 597,708,816 字节，对应 SHA-256 以 b0a412d13359 开头。不同于 c6a 的旧 ELF。新二进制在原正式套件中运行 265.528 秒，源与恢复名册 1,723 项完全相同，可执行项 1,552/1,552 逐名通过，原忽略 171 项。此前六项失败均有自己的通过行，另四个控制组分别 6/6、3/3、6/6、2/2。[两阶段冷构建和原生执行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787247) · [原始归档与逐项复核](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/57263947fb62efda78071af3c85709c7af202200/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/memory-startup/E327.md)
