# 已知关系规则的权重程序：前瞻协议

本研究检验一个有限且明确的新能力：给定两条独立的延迟信息序列，以及可观察的 query，回答原任务 A、两个原任务的 AND、OR 或 XOR。目标来自两条序列各自真实的 `sign(early + late)` 标签，不能用模型预测替代真值。

这关闭的是“在结构和规则已知时，能否生成可执行的新组合能力”的实验缺口。它不检验未知规律发现、端到端表示学习、多模态预训练，或一般性的 BP 替代。新增字典和查询路由是所有方法共有的结构先验。

## 模型与新能力

父模型为本轮新训练的纯 signed-flow、QVI、value/risk HCSN；N=8/32/64，独立训练种子 17011/27011/37011，共九个，全部保留。父模型选取只使用其原训练与开发集，不能看父 test 或本实验 pair test 选择父模型。父模型选择为初始状态、训练失败或 CPU 截断的情形必须按原记录披露，不能改称成功学得表示。

两条序列分别经过同一个冻结父网络。令当前 checkpoint 的两类线性读出得到差值 dA、dB。共有特征字典为：

`z = [dA, dB, abs(dA-dB), abs(dA+dB)]`。

三个新增关系 head 共 15 个可编辑标量：3×4 权重和三个偏置。父网络所有参数、物理状态定义及从父读出复制的投影均受保护。query=0 直接返回原 A 的 logits；query=1/2/3 选择 AND/OR/XOR。这使新旧任务在输入上可辨识，不要求同一个无条件输出同时满足矛盾标签。

| 方法 | 初始化与更新 | 使用关系样本真标签 |
|---|---|---:|
| KEEP | 每个关系仍预测 A，权重 `[1,0,0,0]`，零偏置 | 否 |
| BP | 从 KEEP 开始，最多 96 次实际 closure 的 L-BFGS | 是 |
| ANALYTIC | 同一目标的正则化闭式线性解 | 是 |
| STRICT_WSP | 从当前权重和给定规则直接生成关系程序 | 否 |
| HYBRID | STRICT_WSP 初始化，再执行与 BP 同上限的监督优化 | 是 |

所有方法都获知任务规则、父 checkpoint 和相同字典/参数域。严格程序函数只接收父读出的权重字典与规则名称，不接收标签、激活、模型 forward 或候选选择结果。监督方法的标签访问、求解和梯度调用另记。已知规则包含直接可编译的答案结构，因此这不是无结构知识条件下五种通用学习算法的竞争。

严格程序写入的三行分别为：

`AND = [1/2, 1/2, -1/2, 0]`；`OR = [1/2, 1/2, 1/2, 0]`；`XOR = [0, 0, 1, -1]`。

AND/OR 对应 min/max。XOR 的连续分数等于 `abs(dA-dB)-abs(dA+dB)`。在非零分量 margin 和精确算术下，它们的符号实现父分类结果的逻辑组合。真实任务准确率仍取决于父模型错误；当父模型预测错误时，正确安装规则也可能回答错误。零 margin 与有限精度消减必须单列，不能由逻辑恒等式推导所有真实标签都正确。绝对值字典连续、分段可微，在零点采用框架子梯度；不宣称全局光滑。

## 数据、冻结与验收

父任务使用 10000–10011 / 11000–11003 / 12000–12015；本任务的 pair train/dev/test 分别为 20000–20011 / 21000–21003 / 22000–22015。每个 source 16 对、每序列 12 ticks。每条序列使用独立 `SeedSequence([20261125, source, lane])`，cue、噪声、增益和初态都单独生成。source 是合成生成器身份，并非真实外部数据集。

`prepare` 只构造 pair train/dev。协议、运行时、父源码闭包、程序源码、父 tensor 身份、全部五候选、训练/开发特征和真实标签先封存。没有基于开发效果选优：每个方法保留最后有限候选；更新失败显式记录并回到 KEEP。开发指标只用于报告。

`seal_all` 要求九个预声明父模型的完整候选名单。`final_test` 在构造 test 前核对全体候选字节、schema、method/parent/protocol 元数据、受保护投影和本父模型身份，再创建不可重入的测试 claim。测试后不重新选择模型或调阈值。失败记录和成本必须保留。

预声明主要观察量为 XOR 真标签准确率相对 KEEP 的差值，AND/OR、Brier、交叉熵、source 分组及父 A/B 准确率同时报告。三种宽度各只有三个独立训练种子；坐标视图和 query 不能扩大独立样本数。正的描述性均值不自动成为统计显著或全能力优势。

## 程序重新生成与迁移

每个独立父模型都重新读取当前读出权重生成完整程序。另在固定前 16 对开发输入上执行真实物理 forward：

1. sender/receiver 各自内部进行合法神经元置换，连同异质物理参数、recurrent 三个列块、读出列、mask 和完整初态一起变换。
2. 在读出接口显式加入符号坐标适配，同时变换读出列。它不是物理 population 的符号对称。
3. 从每个视图的当前权重重新生成程序，比较实际关系分数、决策和原父 logits；另保存错误地沿用原数值投影的负控。

视图属于同一父模型的等价控制，不是新增训练种子。真实模型分数容差预先固定为 atol=rtol=3e-5，决策分歧独立计数；不能把容差内分数误差掩盖为零决策变化。

## 优化目标与成本

监督目标统一为 `mean((zW^T+b - (2y-1))^2) + 1e-4 * sum(W^2)`，mean 覆盖样本和三个关系；偏置不正则化。闭式 Hessian 为 `X^T X/(N*3)+lambda*diag(1,1,1,1,0)`，记录条件数。BP/HYBRID 使用 max_iter=max_eval=1、无 line search 的 L-BFGS；每次 closure 计数，最多96次，更新部分最多10 CPU秒，梯度无穷范数≤1e-8早停。优化器建立时间在其阶段成本中。

完整报告区分：父模型加载/继承训练，数据生成，两个父 forward，投影/字典构造，程序生成，监督更新，开发验证，候选保存/重开校验，迁移的真实 forward，全体预检，test 特征/评估，以及证据写入。共有特征成本同时报告一次总账、五方法等额分摊及单方法承担全部共有成本三个口径；不得把分摊账重复相加或只用矩阵求解时间声称端到端提速。

函数体 CPU/wall 包含已列阶段；最终结果文件写入、解释器导入和退出由外层完整 worker 记录。父加载与原训练费用由父实物/外层回执绑定。缺少的能源、完整机器成本或人工/agent 规则发现成本保持 unknown，不能记为零。程序编译计时不等于自动发现程序的全部时间。

## 运行接口与测试范围

- `default_protocol()`：在单线程真实运行时冻结规则、数据、预算和源身份。
- `prepare(parent, parent_identity, output, protocol)`：独立输出目录，产生五候选与 `SEAL.json`。
- `seal_all(all_nine_directories, global_seal_path, protocol)`：全局封存。
- `final_test(parent, output, protocol, global_seal_path)`：只执行一次的新 pair test。

父加载使用 `models.make_model(checkpoint['slot'])` 后装入 `checkpoint['selected_model']`。传入身份应含父 checkpoint SHA256、selected_step、独立 seed、slot、父原始 result 和完整 worker 成本摘要。调用器必须先核对原父训练 result/checkpoint/worker 身份。

`program_tests.py` 的十个合成控制使用71–75来源和明确测试父身份，不读取正式pair来源或正式checkpoint。包含一个真实 SignedHCSN 物理 forward 控制；其随机初始化只用于函数等价测试，不算独立训练或新能力证据。正式执行结果须待原始回执写入后报告，本说明不预先宣称通过。

## 常规网络比较与长延迟补充

`baselines.py` 提供 GRU、surrogate LIF 和单 block 因果 Transformer。三容量分别为 GRU hidden=4/16/32，LIF hidden=9/30/58，Transformer d=3/11/21、head=1、FF=2d、dropout=0、固定正弦位置编码。实际参数为 GRU 154/1186/3906、LIF 155/1142/3830、Transformer 134/1190/3950；对应 HCSN 结构活动参数目标154/1186/3906。参数量接近不意味着功能容量、精度、初始化、算子成本或训练轨迹相同。

LIF 输入/递归线性层无 bias，固定 leak=.9、threshold/reset=1、spike trace=.8，读出 trace。前向为真实0/1脉冲；反向采用 `1/(1+5*abs(gap))^2` surrogate，reset 的 spike detach。此反向不是硬阶跃的真实导数。GRU 保存一个 hidden；LIF 保存 membrane/spike/trace；Transformer 保存随长度线性增长的 K/V，无截断。各模型均验证整段与逐步因果前向一致及未来输入不能改变过去输出。零初态不使用 HCSN 的物理 initial_margin，这个差异保留。

27 fits 使用与主63完全相同的训练/开发生成器、source、样本数和长度12。在独立进程中显式绑定 baseline factory/accounting/evaluate，再调用同一个原 `runner.fit`；不修改其源文件。沿用 Adam、batch RNG、.8 final+.2 prefix CE、512实际更新、900训练CPU秒安全截断、开发集最低CE选择及180训练CPU秒前缀。失败、初始/selected/last/optimizer/RNG、完整worker和launch成本均保存。

baseline27封存与主63封存共同构成短test准入；源码、slot、checkpoint、cost和原数据摘要均在构造test前核验。完整worker时钟包含导入/父加载/校验，launch回执包括子进程退出；阶段CPU是其子集，不能重复相加。

预声明额外纯评估：sources30000–30007，length76/delay64；sources31000–31007，length140/delay128；每source16条。主63和baseline27均封存且所有短test有终态后，固定 selected weights 对27 baseline与9QVI signed父执行，不训练或重选。报告final/prelate准确率、相对短test差异、完整CPU/wall与state/KV bytes；工程门为final≥.8且final−prelate≥.1。它是训练T12后改变延迟和clock分布的外推压力，不能当作长任务训练或全模态基础模型证据。

统一薄调用器为 `python -m qualification.hcsn_closure_20261124.baselines_run`。`freeze --suite baselines|programs --root <独立输出> --parent-root <主实验>` 先绑定全部源；`campaign --root <独立输出>` 逐个启动有界worker。程序campaign等待九个指定父训练终态；baselinecampaign优先完成27训练并封存，再等待联合test门。调度等待算入campaign wall，规则发现成本保持unknown。

在原十项程序控制之外，另有五项实际参数/streaming/surrogate/BP/原训练循环smoke控制，以及两个超时成本/长延迟未封存拒绝控制。未执行的控制不能计为通过；原缺依赖导致的首轮import失败单独保留。
