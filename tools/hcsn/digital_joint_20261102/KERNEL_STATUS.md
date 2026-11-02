# Kernel 数学状态与发表清单

本轮已获得**完整33状态有限CTMC的可微传播资格**，并给出一个登记子域内的连续模型近似与参数敏感性收敛证据。它支持首达、未发放后继、指数恢复、复位后继续消耗剩余时间及区间内多次事件。这个结论不等于连续自由边界、数学精确路径模拟或一般任务优势已经成立。本文只整理核数学线，不修改、选择或追认20个正式候选及其任务结果。

核心源码 SHA256 固定为
`0439cf12f4519c29b1b079adb2ebc66eb86a252c59a2754770acc58ed5cff0e9`。

| 层次 | 本轮对象及实际成立的范围 | 必须保留的边界 |
| --- | --- | --- |
| 正式候选可使用的有限核 | 31个内部电压代表点、下/上两个refractory状态，保存完整33维概率质量；`p·exp(dt Q)`保留所有有限过程后继、恢复与再事件分支 | “时间连续”指有限generator的矩阵指数；空间仍离散。它没有保存一次实际连续路径的全部hit/release时刻 |
| 连续模型参照 | Brownian首达像和/数值反演、真实区间内命中时间、指数恢复及连续截断高斯复位；另有独立FV-PDE240/480求解作局部收敛参照 | 路径反演有容差和有限像和，PDE也有空间离散；均不是已证明误差为零的连续“精确路径”实现。其路径时间资格不能直接迁移到正式候选 |

完整33维质量是所声明Markov状态的末态分布，不是全路径分布；当前附加事件计数是期望，不是任意事件数的完整计数分布。若下游需要按已发生事件序列更新内容或费用，还必须声明相应的路径／计数状态。

有限核默认使用32个空间区间形成31个内部点；文中`grid31/63/127`表示内部点数，对应总状态数33/65/129。`PDE240/480`表示参考空间区间数，分别有239/479个活动点，另加两个refractory状态与事件计数积分量，不能把这些记号混为同一状态规模。

活动态的左右跃迁率为

\[
q_\pm=\frac{\sigma^2}{2\Delta x^2}\pm\frac{\mu}{2\Delta x},
\qquad \Delta x=\frac{2b}{n+1}.
\]

边缘向外的跃迁进入对应refractory状态；该状态以恢复率`gamma`跳入连续截断高斯在各代表点Voronoi区间上的概率质量。矩阵指数包含任意次数的有限过程恢复/复位循环。旧的“每个外部区间最多一次新事件、只在区间末释放”限制未用于此核。

在登记参数域`b∈[.8,1.2]`、`sigma∈[.35,.8]`、`|mu|≤1.1`、`gamma∈[.25,2]`和`n≥31`内，左右活动跃迁率至少为`3.55555556`，无需通过截断负率或重归一化传播结果修补合法性。恢复为指数分布，因此未揭示的恢复时钟可由mode概率描述；若已知某次抽样的确定剩余恢复时长，或恢复依赖年龄，就需要更丰富的状态，不能直接压成refractory one-hot沿用本接口。

本轮有8个raw坐标：boundary、diffusion、gain、drift bias、两个reset center、recovery rate、reset SD。它们均进入完整概率质量、未来bank与事件计数的计算图。固定boundary使用独立buffer，已经检查梯度与AdamW weight decay均不会移动它。驱动恒为零等特殊任务条件会使gain进一步不活跃，必须另计有效参数。

**8个raw的偏导均被激发，不代表8个物理方向可独立识别。** 同时缩放`b、sigma、gain、drift bias、两个reset center、reset SD`而保持`gamma`不变，会保留归一化generator。因而在允许变化驱动、观察完整转移的最好条件下，该参数化局部至多有7个可识别方向；部分观察或退化上下文还可能更少。全局可学习boundary仍有尺度gauge，不是时间移动边界，也不是由任务价值求解出的自由边界。

bank为该有限CTMC的reset-aware未来阈值概率：3个期限`.25/.75/1.5`，3个相对阈值`−.5/0/.5`，call采用严格`X_h/b>k`，put取补概率，并包含未来refractory/释放/复位。其期限内保持所传入context不变。若未来公开驱动切换，真实schedule预测需要相应转移矩阵的乘积；不能把当前bank直接叫作实际deadline成功概率。旧自由端点bank单独保留为`free_features`，两者语义不混用。

| 已登记数值核验 | 实际结果 |
| --- | --- |
| 47项有限核检查 | 47/47通过 |
| 8 raw、完整33质量＋9 bank＋count的43输出Jacobian，两个长前缀、两个FD步长 | 最大绝对误差`3.9018e−9`；每个raw列均非零 |
| 7个独立physical坐标完整状态Jacobian | 最大绝对误差`2.5982e−10` |
| 同context整段/切分的完整质量与raw Jacobian | 误差分别`3.1364e−15`、`3.6360e−15` |
| 事件计数切分梯度 | 最大误差`4.4686e−15` |
| 零时间、固定boundary、批量context/dt、正率/质量、SciPy expm | 登记检查通过 |
| 独立代码的长前缀非线性loss、reset数值积分、半群/梯度与gauge审计 | 通过；不据此外推连续梯度 |

FD针对确定性的有限law与矩阵指数，不是对罕见Monte Carlo事件路径扰动后冒称精确梯度。上述检查也不替代内容likelihood条件化、神经头损失、策略训练或原生owner的独立验收。

局部连续敏感性登记在单个物理点
`(b,sigma,mu,reset_plus,reset_minus,gamma,reset SD)=(.84,.78,.2,.15,−.12,1.9,.08)`，初态为中心活动点、时长2，相对阈值固定。grid31的单区间预期事件数为`1.2586411`，确实超出一次事件的范围。独立NumPy FV代码与SciPy完成30次PDE240/480中心FD积分；另以已独立发表的协议完成14次PDE480半步长积分。该参照是独立实现的同一FV离散族，不是另一套闭式连续解。

| 对PDE480、FD步长`5e−5`的最大参数敏感性差 | grid31 | grid63 | grid127 |
| --- | --- | --- | --- |
| 投影CDF、两个refractory质量、重复事件count | `9.25332e−4` | `2.28196e−4` | `5.39491e−5` |
| 正式有限节点严格阈值CDF相对连续密度CDF | `.0169764` | `.00841079` | `.00418665` |

投影CDF把活动质量均匀分配到其Voronoi区间，用于比较连续密度；严格节点CDF保留有限网格原子。不能用第一行较小的误差替代实际严格bank的梯度精度。PDE240与480的Jacobian差为`1.23898e−5`；PDE480的FD步长从`1e−4`减为`5e−5`后，全Jacobian最大变化为`7.11431e−8`。这支持该登记点的空间收敛诊断，同时显示严格bank原子偏差仍显著高于FD步长差。

此前独立killed-Brownian压力案例的概率误差必须同时保留：**grid31最大`.0097422242`，grid127仍为`.0005807781`**。局部收敛不是全域误差界，不能把有限CTMC的数值梯度正确升级成连续Brownian、任意移动边界或全部参数域的精确梯度。

连续路径参照原有2,000条`truncated_reset`记录已保存在旧CSV中。本轮按同一旧源码、law与seed`0xBE23`记录重放，2,000/2,000条终态列、事件数与first-hit逐项精确匹配；新增完整保存2,854个事件、剩余恢复时钟及各路径前后PCG64状态。它是同seed补录，**不增加独立样本、fit或确认世界数**。

| 本数学线保留的失败 | 处置与严格状态 |
| --- | --- |
| 47-check attempt001：旧PDE脚本以package导入时找不到顶层`continuous_renewal` | 数值检查未执行；失败JSON与当时源快照保留。只修新validator导入路径，attempt002通过，未修改旧源码或核 |
| sensitivity attempt001：写源快照时`ENOSPC` | PDE尚未执行；失败JSON、零字节部分快照、补回的源快照均保留。attempt002按同一已发表源重跑，没有改门槛 |

| 成功运行段的程序内部计时，秒 | Wall | Process CPU |
| --- | --- | --- |
| 47-check attempt002 | 11.719633434 | 14.136636817 |
| 30次PDE／AD局部敏感性 | 154.429720827 | 146.620862276 |
| 14次PDE半步长补充 | 146.014655692 | 107.707490642 |
| 2,000路径同seed完整记录重放 | 2.694413539 | 2.666225536 |

以上实测CPU合计`271.131215271`秒。各段Wall可能与其他工作重叠，不能当作整个项目串行总耗时。该台账不含解释器导入、两次计算前故障未采集的开销、独立审计、正式候选fit/确认、封存和文档成本；不把缺失计时填成零，也不据此宣称完整采用成本、加速或能耗优势。

完整原始证据包为
[`joint_kernel_EVIDENCE.tar.gz`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8977e83d89fc0b2e7e74c2ed6f025adb096f5dfc/tools/hcsn/digital_joint_20261102/joint_kernel_EVIDENCE.tar.gz)：**492,844 bytes，18成员**，SHA256
`ffa4c2c1c7d05c2c1e2d457bcb39252c9807c0dd60b9bc15fd6afa61a5edc5d5`。
固定commit的远端Git blob为`c2252e4ab5b15fb6715753b98380e089409d1c21`，与本地原始字节重算的blob一致；同commit的[支持索引](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8977e83d89fc0b2e7e74c2ed6f025adb096f5dfc/tools/hcsn/digital_joint_20261102/evidence/JOINT_SUPPORT_ARCHIVES.json)记录相同大小与SHA256。清单只取其中kernel条目，不把其他工作线混入本数学结论。

| 本线发表／复核对象 | 固定身份与保存方式 |
| --- | --- |
| 核初始工程pilot源码 | `73fa3394d34674af7178b5bf0271917a992fee05`；已只读核对`joint_kernel.py`全文与当前冻结核一致 |
| 47-check与局部敏感性源／协议 | `29b2246c4bfb53d2bb5c3ca3ce83dcf142af0f2a`；测试源与协议先发表，再运行登记积分 |
| 半步长与同seed recorder源／协议 | `97edbc1b5f20eae2a3e064d4ab93557c9eacba9b`；先发表，再运行14积分及记录重放 |
| 原始证据包及可复用源码／README／47-check JSON | `8977e83d89fc0b2e7e74c2ed6f025adb096f5dfc`；包内保留44次PDE的完整mass/count、2,000完整路径、所有attempt与源快照 |
| 包内逐文件内容身份 | `joint_kernel_EVIDENCE_MANIFEST.json`；所有18成员已逐字节读回验hash。零字节失败快照被显式列为expected incomplete，不隐瞒或冒充有效gzip |
| 独立已保存PDE记录审计 | `joint_independent_audit_sensitivity.json`；44次全部重建，observable误差`4.44e−16`、中心FD重建差`2.22e−12`，未再次运行昂贵PDE |
| 本次中文状态与机器可读发表清单 | `KERNEL_STATUS.md`、`KERNEL_PUBLICATION_MANIFEST.json`由root后续发表；本文不提前声称这两份新文档已有远端commit |

完整文件级路径、bytes、SHA256、Git blob及“直接发表／包内保存／待root发表”的区别见`KERNEL_PUBLICATION_MANIFEST.json`。包内采用仓库根目录相对路径，可在相应源码checkout恢复原始文件；不以摘要替代科学raw。

| 仍未由本数学包闭合的科学命题 | 下一项必要证据 |
| --- | --- |
| 连续、任务价值驱动的自由边界 | 明确边界方程、时间／状态依赖和正则性，给出适用范围内的解／数值收敛及相应参数导数；全局raw boundary与尺度gauge不构成这项证明 |
| 连续模型全参数／全域梯度与误差资格 | 更广参数、初态与时间域的误差界；区分严格阈值原子偏差、FV投影误差、FD误差和求解误差。一个登记点的refinement不能覆盖全部合法输入 |
| 逐事件hit/release时间真正进入正式训练／策略 | 本轮采用本核的正式接口保存完整分布，未把实际连续逐事件时间接入formal损失、后续动作价值和相同原生执行；旧路径adapter的时间记录不能跨profile借用 |
| 一般恢复分布或已知剩余时钟条件化 | 增加age／residual状态并验证正确后继；指数memoryless模式的资格不能覆盖这些条件 |
| 核相对强普通方法的一般任务优势 | 在同信息、强full-distribution／GRU／Bayes参考、独立fit、冻结确认和完整成本下检验实际贡献；数学核正确不推出收益为正。开放域、未知生成器、长距离跨模态仍需独立任务证据 |
| 一般生产／低精度／GPU资格 | 同一最终源码与模型profile的部署、恢复、数值稳定性及质量／时延／吞吐／能耗账；本数学包没有建立这些结论 |

本次收尾只进行了文件／JSON读取、固定Git commit只读回查和新文档整理；没有改核、20个正式候选源码或模型，没有重跑PDE、梯度或轨迹验证，没有调用GitHub写入操作。
