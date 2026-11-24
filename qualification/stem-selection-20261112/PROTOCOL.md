# Hepta 干细胞选型：共同源码上的四包研究协议

状态：**预先冻结的研究协议；RESEARCH_ONLY / HOLD / NoUpdate**。
本文件规定输入、比较、成本和资格边界，不填写尚未执行的研究结果。
所有实际执行必须记录最终共同源码、数据和配置身份；旧分支的通过记录不自动继承。

## 1. 起点与决策范围

[#6146](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6146) 的前置研究是两个互不交叠参数布局的等价对照。
它提供了相同任务信息、输入和训练顺序的控制基础，尚不检验共享可塑权重中的任务干扰。
[#6204](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6204) 是该谱系的格式修复，不能扩展原实验的科学资格。
本轮加入真实共享参数、显式时间接口、CfC 和可恢复的定向读出信用实验。

维持两类祖细胞的研究选择：语义表征型、有状态时序型。
现有语义头与 GRU 是主线；CfC 是专项挑战者，不按名称获得默认采用资格。
七条既有谱系保持不变；本轮没有自动分裂、合并、退役或 Population/native daemon 采用。

## 2. 冻结输入与统计单位

输入由 [cord_replay.py](../../scripts/hepta_cells/cord_replay.py) 与 [cord_evidence.py](../../scripts/hepta_cells/cord_evidence.py) 校验并冻结。

- `DATASET.json` SHA256：`b331d33f3aad24cff4088488c47afe3f67461e98dc15d61c5abdceea0494763f`。
- 来源为保留的 CORD pilot 原件：32 个文档，每文档 upper/middle/lower 三条 ROI 记录，共 96 行。
- 原划分为 24 个训练文档、8 个开发文档；共享初始捕获与三次 ROI 捕获共对应 128 条唯一 owner receipts。
- 记录绑定文档、初始及后续 receipt、特征 profile、实际 latent、原结果标签和捕获时间。
- 同一文档 SHA 不能通过不同来源名称进入多个划分；同一来源的初始信息必须在三条路由中一致。
- 所有来源均已被历史工作暴露；`fresh_confirmation=0`，`source_independence_verified=false`。
- `source_group`/文档是统计分组单位。三个 ROI、训练 pass、种子和重复恢复不能累加为独立真实任务。
- 候选失败、缺少原件或 UNKNOWN 不得通过删除分母、替换标签、填零或静默回退处理。

捕获时间只提供离线重放间隔。它不证明历史特征、反馈或授权在某个时刻已真实可用。
后续两个原件文件与依赖清单必须一起保留：`DATASET.json`、`ORIGINALS.json.gz`。
实际捕获依赖仍由原 pilot 档案及 `source_inventory` 中的 hash 绑定。

## 3. 研究包一：时间、状态与学习接口

实现：[stem_contract.py](../../scripts/hepta_cells/stem_contract.py)、[temporal.py](../../scripts/hepta_cells/temporal.py)、[lifecycle.py](../../scripts/hepta_cells/lifecycle.py)。

| 对象 | 冻结语义 |
| --- | --- |
| 时钟 | 整数微秒；绑定 owner、clock domain、boot identity |
| 推理事件 | `available_us` 表示观测暴露时间；不复用为 action/outcome 时间 |
| 模型输入 | 零填充观测值、显式 observed mask、实际间隔秒数；时间在最后一维 |
| 状态更新 | 消耗一个明确 cursor，更新时钟与隐藏状态，不更新模型或 optimizer |
| 参数学习 | 消费已经冻结的训练批次，产生独立候选，不修改父模型 |
| 重复与乱序 | 同 request 返回原 receipt；新 request 重复 cursor、时间回退或异源时钟拒绝 |
| 缺测与空闲 | 缺测必须显式标记；范围内保留真实间隔；超过声明范围拒绝，不能静默截断 |
| 原任务恢复 | 恢复同版本状态、时钟、cursor，继续遵守既有 owner epoch 约束 |
| 原训练恢复 | 恢复参数、Adam moments/step；绑定原编码数据与剩余完整 batch 更新计划 |
| 跨版本迁移 | 当前不支持通用状态/optimizer 迁移；不能把新初始化或 qualified adoption 冒充恢复 |

来源认证、反馈可见性 admission 和 native owner 授权仍属于各自原 owner。
文件 hash 与本地一致性校验只证明被绑定的字节，不自行授予这些权限。

## 4. 研究包二：相同信息下的语义与时序比较

实现：[stem_temporal_study.py](../../scripts/hepta_cells/stem_temporal_study.py)、[stem_study_support.py](../../scripts/hepta_cells/stem_study_support.py)、[cfc.py](../../scripts/hepta_cells/cfc.py)。

问题限定为：取得初始观测和指定 ROI 后，预测该条保留结果是否正确。
所有组获得同一初始 latent、ROI latent、三维路由 one-hot 和相同重放时间信息。
训练来源拟合唯一 normalization；开发来源不能参与其均值和尺度估计。

| 组 | 参数化与预定预算 |
| --- | --- |
| Constant zero | 固定零类预测；经过相同语义 provider/owner 服务路径 |
| Train prevalence | 仅从训练标签估计先验；开发标签不参与 |
| Semantic linear | 现有 LocalHead；两次完整事件展平为 270 维；SGD，32 updates，lr 0.03 |
| GRU | 两次相同的 135 维事件；hidden width 2/4/8；Adam，32 updates，lr 0.003 |
| CfC | 同一输入和预算宽度；真实 CfC 核及其梯度；Adam，32 updates，lr 0.003 |

全部模型 seed 固定为 0。计划为九组：七次候选拟合各 32 updates、合计 224 updates，另有两个固定基线；不进行额外调参搜索。
CfC 与 GRU 均获得实际 dt；CfC 在 dt=0 时不被假定具有恒等流或半群性质。
相同信息、标签和更新次数，不意味着参数量、状态容量、optimizer 或实际计算完全匹配。
各预算点分别报告参数数、实测成本、保存大小和评价；不建立跨任务总分榜。

8 个开发来源在训练前按 source ID 排序分成 B/C 各 4 个来源，每部分 12 行。
B 的来源组平均 Brier 只选择下一步研究使用的候选；C 在选择完成后才执行。
即使固定基线更好，也可对被选候选做受限研究使用，但发布结论仍为 `NoUpdate`。
C 不再用于换模型、选择宽度或调参；不把这组历史 C 重命名为独立确认集。

B/C 推理分别经过 SemanticComponent 或 TimedTemporalComponent 和真实 SQLite CellOwner。
冷恢复必须使用新 Python 进程、相同 Bundle、原 owner 状态与新的推理 request ID。
旧 request 的 receipt 重放与恢复后的实际模型计算分别记录，不互相替代。

## 5. 研究包三：真实共享参数中的分化与干扰

实现：[plastic_bank.py](../../scripts/hepta_cells/plastic_bank.py)、[stem_plastic_study.py](../../scripts/hepta_cells/stem_plastic_study.py)。

仅使用行动前 initial64；所有模型得到同一个命名 ROI task ID。
后续 ROI latent 不进入该包。三条任务为 upper、middle、lower，目标是各自保留结果的正确性。

| 组 | 可塑参数归属 |
| --- | --- |
| `shared_plastic` | 三任务真正更新同一个 first factor，各有命名读出 |
| `frozen_backbone` | 同一冻结 first factor，各任务只更新私有读出 |
| `independent` | 各任务拥有独立 first factor 与读出 |
| `frozen` | 保留同类结构，禁止参数学习 |

固定 seeds 为 1101/1102/1103；独立模型 rank 为 2/4。
共享结构按最接近的总部署参数量选择 rank，分别为 6/12。
计划总参数为 independent 393/783、共享结构 405/807；差额必须保留。
该匹配不同时匹配 active rank、可塑参数数和 MAC；同 seed 不意味着不同形状模型函数完全相同。

固定 curriculum 为 upper→middle→lower，重复两遍，共六阶段。
每阶段 40 次 SGD 更新，lr 0.03，每 10 次更新记录三个任务的开发表现。
计划为 3 seeds×2 预算点×4 arms，共 24 个运行，其中 18 个训练运行计划合计 4,320 次更新；种子是重复计算条件。
强基线包括 constant zero、训练 prevalence 与训练记录上的精确最近邻距离检索。

报告学习曲线、旧任务保持、其他任务预测的变化、实际参数更新数、MAC、时间和恢复成本。
共享参数中的数值变化本身不是负迁移；必须结合旧任务结果变化解释。
固定分化是否有价值由这些对照决定，不以细胞数量或提交数量代替证据。

该六阶段重复同一任务集合，不构成连续新任务、开放分布或终身可塑性验收。
每组保存真实 bank 状态，并区分冷启动后的旧 receipt 重放与新 request 推理。

## 6. 研究包四：固定状态核上的读出信用

实现：[readout_credit.py](../../scripts/hepta_cells/readout_credit.py)、[stem_credit_study.py](../../scripts/hepta_cells/stem_credit_study.py)、[stem_credit_support.py](../../scripts/hepta_cells/stem_credit_support.py)。

每个 seed 固定一个 hidden width 4 的 GRU，不训练其 recurrent body。
每文档重置状态，只输入 initial64、present mask64、dt=0。
读出输入为 L2 有界的 direct initial64 与 hidden4，共 68 维；三个输出对应三个命名 Cell 读出。

| 组 | 更新与控制含义 |
| --- | --- |
| `frozen` | 记录同样的决策与反馈，但不更新 |
| `replay_sgd` | 在同一保留特征上，用候选当前预测计算普通 SGD 梯度 |
| `scalar` | 对共同教学向量取标量平均；属于信息减少的消融 |
| `routed` | 使用正确归属的共同向量与衰减读出敏感性痕迹 |
| `shuffled` | 同一向量、mask 和延迟，按无固定点 permutation 打乱归属 |

所有 arms 在标签前固定相同 zero reference。routed/shuffled 不利用各自已变化的预测重新定义教学向量。
这是冻结 reference 的读出教学实验，不是每个演化候选的精确梯度，也不是一般脑反传或全核 eligibility。
普通 replay SGD 保留为强学习规则基线；scalar 不被解释为同信息控制。

固定 seeds 为 1101/1102/1103，tau 为 10 秒与 100 秒，lr 0.01。
按训练 source ID 固定顺序重复三遍；每组计划 72 次反馈，完整面板为 30 个运行，其中 24 个为可学习组，6 个为冻结组。
三个 ROI 的保留标签在最长捕获间隔后一起暴露，属于明确构造的离线反馈时钟。
各 pass 记录全部 8 个历史开发来源；没有开发训练、胜者选择或晋级。

最后一个训练决策在 feedback 前保存 pending checkpoint。
新进程恢复参数、SGD 更新计数、RNG、clock、pending/settled ledger，再执行同一个下一步 feedback。
随后重算 GRU 特征和开发预测；动态 wall/CPU 字段不参与数值状态等价判断，仍各自保留。
该验证不计为新的训练来源或独立反馈事件。

## 7. 共同成本与失败处理

- 每个尝试保留开始身份；没有终态的尝试保持 unresolved，不能记为成功或零成本。
- 成功训练的收据须先持久写入，再构造/发布候选与 checkpoint；失败训练也保留成本。
- 报告训练、被拒候选、provider copies、路由、SQLite、序列化、存储大小及真实子进程恢复。
- MAC 的范围明确列出；bias、分配、hash 和 IO 不被伪装成已经由 MAC 覆盖。
- `DATASET.historical_costs` 单独报告原捕获成本，共享初始捕获只能按唯一 receipt 计一次。
- 当前重放没有重新编码图像；不能把缓存输入的运行时间称为完整在线感知时间。
- 原历史失败训练、部分服务费用、能耗和峰值内存存在缺口时，保留 unknown 和明确排除项。

## 8. 执行与最终资格

实际执行前冻结同一提交上的接口、三条 study driver、importer、参数与数据原件。
三个 driver 分别产生自己的 PLAN/PROTOCOL/DESIGN、训练收据、预测、checkpoint、冷进程记录和总结。
源码、Python/NumPy 环境与输入 hash 必须可复核；结果和后续证据提交不得改写原执行身份。
所有输出目录 create-only；中断或失败原件保留，不通过相同路径覆盖后宣布闭合。

下列结论在本轮仍须明确分开：

1. 接口和恢复行为通过有意义的测试。
2. 同一冻结源码确实执行了保留真实经验上的候选学习和研究使用。
3. 独立新来源上的效用改善与完整成本净收益。
4. 普通 native daemon 使用同一候选、授权采用、恢复后继续真实任务。
5. 连续新任务上的长期适应，以及学习机制本身变得更有效的递归改进。

本协议最多支持前两项的局部证据；第三至第五项不能由局部通过或重放数推导。
本轮实现的 CfC 仍需新来源与完整成本资格；HCSN、真正的关联状态模型和 Mamba-3 未在本面板执行。
后者仍需各自实现、任务、硬件与成本资格；不能把当前读出试验、GRU 或简单对角递推重新命名为它们。
