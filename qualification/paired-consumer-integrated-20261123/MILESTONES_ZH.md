# Hepta 三个里程碑的验收记录

2026-11-23。下列分母依次表示参与人、候选模型对或题目。所有实验分支都保留失败、拒绝及原始回执。

| 验收目标 | 可复验结果 | 尚缺的原始证据 |
| --- | --- | --- |
| 第一次 A→B | A 的失败和纠正有受保护的单次训练许可入口。冻结后，B 的盲评、后续独立请求、冷加载指定权重、接受或拒绝都有可执行路径。工程样本两次真实生成和现场报告均已回读。四台登记主机上一轮合计 26 个条目，新增参与记录为 0。 | 前瞻性真人 A、冻结后独立 B 的未见任务、盲评改善和保持、B 真正再次使用同一候选。首例用于证明闭环，估计跨人收益仍需独立重复。 |
| 用户与算力增长 | 在 AMD EPYC 7763 的 4 vCPU 上，单、双 worker 各两个计时区组。训练至双臂冷恢复的 8 次作业包括 16 个冷进程、32 个答案、48 次模型调用。317.97 → 535.79 个相同历史模型对/小时，1.685 倍。另一 CPU 型号的首次重跑有 4/8 个权重逐字节合格，该轮没有合格的吞吐估计。 | 分别固定总预算、每人预算，登记 1、4、16、64 个独立来源。worker 数单列。正式指标是通过保持门槛、后来实际被采用的候选/小时。 |
| 教师断开后的能力 | 16 个新英语源句各生成德语和法语译文。使用压缩的开放专家并按语言路由，平均逐句 chrF++ 为 65.87，单专家为 38.93、42.45。双语均过 35 的源句为 14/16，对照均 0/16。学习路由和固定路由选中的专家完全相同。 | 从行为学习的独立编码器在 192 道八域问题上得到 124/192，冻结父模型 125/192。跨域配对全对 8/32 对 12/32。尚待用户经验带来稳定的增益与跨域组合，以及没有预设拓扑时的长期增长。 |
| 编辑与反向传播 | 同一 MiniLM 冻结表示、464 × 1,152 设计矩阵、相同正则和两个真实教师的相同标签，直接解 14.65 ms，PyTorch 自动微分 L-BFGS 138.33 ms。272 个历史输入逐项同答。计入加载和训练特征提取，4.952 s 降为 4.828 s，节省 2.50%。这份混合教师输出头主测 114/192，原父模型 125/192。 | 更深层参数、长序列编辑、遗忘、分布外任务，以及首次达到可用质量的端到端时间。缓存特征和每回合重新编码有不同的节时收益。 |
| HIA 和 Cell 连边 | 固定 HIA 镜像曾在真实 macOS 控制器和 ai395 worker 完成 MEM/PRED 原生计算与重启读回，两项维护决定均为 NoUpdate。在独立托管 VM 间传递 1 B 实际输出后，同一 reader 有边输出 1、去边输出 0，逐 token 与单机相同。原始绑定信封为 1,160 B。两端生成耗时约 5–6 ms，测试所用 CI 制品传输和平台调度约 14.22 s。 | 跨机数据表明逐 token 远程调用成本可能主导总时延。生产传输的收益需常驻模型、批处理和相同任务下的直连时延测量。HIA 自身带来的收益需等预算原生基线。新边带来的收益需要删边、断边、端到端成本与未见任务比较。 |
| 有用工作与付款 | Chain 的两笔旧开发评测各付 2,000 单位，未来题改善依次为 +1、0。原收费操作指向评测交付。研究内两次后续使用不匹配既有收费案例的 study、admission、freeze、candidate 和 paired request。 | 同一候选的独立实际效果凭证、使用方和付款方授权，以及绑定同一次操作的结算。新增学习奖励为 0。 |

### A 的反馈可以改变哪一部分

普通 MCP 客户端已能在用户选定的本地会话中，主动提交固定 JSON 文件的失败与纠正，用原字节、工具回执和生产者签名形成训练材料。该适配器只核验站点在计划中固定的公钥，申请训练仍需 A 在原有界面授权。此前在别处产生的效果、商业平台的身份和业务采用分别需要其原件。

#7044 只更新已有拓扑的路由。既有 amber 主测两图均失败，按冻结前规则返回 NoUpdate。两项此前已许可训练的机械对照中，输入 train 不改变权重。输入 1 改变路由、修复已见 A、保持旧题，未改变任何 Cell 权重。正常分发入口拒绝将这些工程身份送给真人 B。没有新拓扑产生。[固定主测](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b74362ea860b4bef21ce11e7f697b8ba7888c420/qualification/paired-router-source-20261123/READOUT.json) · [原始两项对照](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b74362ea860b4bef21ce11e7f697b8ba7888c420/qualification/paired-router-source-20261123/CONTROL.json)

### 把来源与路由接在一起的实测

在同一份 checkout 内，官方 MCP 客户端实际提交「列表 [2, 3] 有几项」这一任务的两份 JSON 文件。第一次结果 count=1，工具读回判错。第二次根据该反馈提交 count=2，原件读回判对。两个受保护真实用户句柄缺失时，实际训练入口拒绝。随后只在标记为工程试验的通道，把这两份原始记录直接送入冻结 Circuit 的路由拟合。相连图与断边图各调用两个 Cell，均未解决任务，返回 `no_update_no_distinct_graph_success`。没有新候选、B 任务或付款。[同一次运行读回](../optin-circuit-integration-20261123/RESULT.json) · [69 份原件 ZIP](../optin-circuit-integration-20261123/ORIGINALS.zip) · [独立托管运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45190772394/job/137748195711)

### 如何选边和更新器

跨机边可按一个完整子任务传递有界结果，并把任务、输入、权重、路由、输出和预算绑定到同一回执。每个节点单独计入冷加载、计算、传输与等待。在未来任务上与删边图和同预算固定图比较。对本次几毫秒的微型任务，使用研究 CI 制品传输，调度超过推理时间三个数量级。高频的紧耦合算子宜共同驻留，跨节点优先测试能摊薄传输成本的任务与批次。HIA 可表达执行与重放，路由是否改善质量要由实际删除或替换一条边来检验。

直接编辑适合作为可选择的局部更新器。既有缓存表示时可用直接解拟合小层。需要学习新表示时保留普通梯度更新作等预算对照。分开测首次达到质量门槛的总时长、旧能力、吞吐量与获得采用的成本。近期的 [RLSEdit](https://arxiv.org/abs/2601.15686) 对长序列知识编辑提出递归最小二乘，[BiSpace](https://arxiv.org/abs/2611.25861) 将外部检索与内部知识注入分开。两者的原实验主要针对知识维护，Hepta 上的对照使用冻结特征线性读出，不是这些方法的复现。

## 原始材料

- [两台托管 VM 的删边对照与原始计时](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8723639cbe68a5e23713fc0547cb17df814a7d5a/qualification/circuit-two-host-edge-20261123/README.md) · [主动选择外部会话的 MCP 工具](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f2663985e5e6552248cf3e40316c599ce53f0484/qualification/selected-session-mcp-20261123/README.md)

- [本人使用的私有操作说明](./PRIVATE_USE_ZH.md) · [真实 ROG 安装和标准 Cargo 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fb2ae8997538e1538fc79883cfcf6263b96bef23/qualification/paired-consent-process-20261123/SUBSEQUENT_DEPLOYMENT.json) · [独立 hosted 二进制重读原始使用回执](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45187759470/job/137737728663)
- [单 Cell 原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/60347d4d1687147ddf7c1e12350711583dac5918/qualification/paired-consumer-use-20261123) · [双 Cell 原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/751e3df8819ef975fea5eb8a7395aba543ee98f1/qualification/paired-consumer-circuit-20261123) · [264 项工程测试](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45187736384/job/137737653310)
- [训练到冷评的吞吐与硬件复现边界](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/434f948eb66edcc36a4ba9be6d8ea933ee4a900b/qualification/e5-worker-readback-20261123/HOSTED_READOUT_ZH.md) · [规模协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1df26bf88c32a7c61340f1c1a93ae88d7841509b/qualification/cell-cross-user-milestone-20261123/PROTOCOL.md)
- [教师断开的德法自由生成](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d95f9213a664f73bcc408e9eb136d6bc201488fc/qualification/cell-e3-encoder-transfer-20261123/translation/generation/READOUT.md) · [独立行为蒸馏](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f78c777d2bb7c030a2fe7b955e0886f987c1901f/qualification/cell-e3-encoder-transfer-20261123/READOUT.md)
- [预训练编码器的局部更新](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/347a9c57dfb23613735fb9e0c7fe8844472fa25c/qualification/cell-e3-encoder-transfer-20261123/matched-edit/READOUT_ZH.md) · [历史 OpenHands 程序轨迹、真实外部题与文件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1a454c0246ed743666fa31f8854420762d77aefa/qualification/trace-binding-controls-20261123/README.md) · [HIA 实机原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1df26bf88c32a7c61340f1c1a93ae88d7841509b/qualification/cell-hia-joint-20261116/ACTUAL_RUNTIME_REPORT.md)
- [Chain 已付开发评测](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/989) · [独立业务与付款读回](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/990)

另有一份历史压力 ZIP 待恢复。原上传日志记录 3,060,886 B，SHA-256 为 `07631d0d25d7367c97d7cb4061fad1f291b24229a59a24d7c8a2527ef02fb70a`。四台限定项目目录查过 4,567,560 个文件条目，本地 Git 对象库核对过 137,817 个对象，未发现相同大小的原件，有两处目录读取错误。[原始上传日志](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/37730166589/job/113157255304)
