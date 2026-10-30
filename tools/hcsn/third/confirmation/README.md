# 有条件的独立序列确认

这是与48次机制开发分开的30次固定确认矩阵：FullHX mass ridge、同图C1 mass ridge、纯memory mass ridge，两个任务、五个全新种子。继承 `third/memory` 已冻结模型、FP32状态/FP64求解、600 updates、batch32、Adam .003，不修改架构或搜索超参数。

**开发完整门未通过时，不生成任何确认数据、不初始化确认模型、不训练。** `contract.require_development()` 同时核验开发源码身份、完整结果和 `development_gate.passed`。`data.py`、`worker.py`、driver都受该条件保护。开发最终失败时，driver保留 `not_executed_development_failed` 回执与 `no_confirmation_data_constructed=true`；没有“先跑几个看看”的路径。

## 运行与证据

从 `tools/hcsn` 运行 `python third/confirmation/contract.py`，仅执行静态源/已存JSON种子审计并冻结，不创建数据。

种子扫描只检查现有JSON明确声明的整数seed字段，不能穷举所有派生随机流。开发门之后的逐样本精确输入审计负责检查实际cohort交叠，两项检查的范围分别保存。

在依赖环境已就绪时，`python third/confirmation/driver.py --wait` 可等待当前开发完成。门通过后，先生成并核对全部新输入，再启动最多两个seed worker；每个worker绑定两个CPU。驱动与worker沿用公开的保守工作集余量计算，每个新worker预留至少1.5GB，余量不足时暂停。调度器对尚在启动的worker额外保守预留，不以失败重试替代余量检查。该Linux cgroup策略不是不发生OOM的证明。

源码可按三个审查阶段交付：前置合同/数据协议；可恢复执行与资源驱动；只读预测重算与预定汇总。每个模块独立，所有修改仅在本目录。

成功执行后保留：

- `freeze.json`：确认源码和开发科学冻结身份；没有确认数据的时点。
- `prerequisite.json`：实际打开确认门的开发结果SHA。
- `data_manifest.json` 与 `data/*.npz`：新输入、标签、全部变换、split指纹、历史与新cohort重合检查。
- `shards/seed*.json`：每次尝试、选定checkpoint、训练历史、全部预测指标、数值求解条件/残差、资源与成本；五个seed shard可独立恢复。
- `checkpoints/*`：每次已选权重及原始logits，失败后以不同attempt编号保存，不覆盖已完成run。
- `execution.json`：准备过程、各worker、未执行/失败/完成状态。
- `analysis.json`：全部90个主能力单元（3模型×2任务×5种子×3长度）、六项FullHX-C1配对差异、所有挑战、保存预测独立重算。

没有选择失败后的额外训练预算。恢复时仍使用同一源码、种子、输入、初始化和训练预算，并保留中断尝试；不能选择性替换差种子。

## 固定验收

主能力门仅看FullHX每个seed在32/64/128长度上的观测准确率：memory至少95%，retrieval至少90%，并要求本矩阵数值检查全部有效。纯memory和C1使用相同门槛分别报告。任何失败seed/长度都保留，不用总体均值掩盖。六个FullHX-C1差异另报配对t区间及六项Bonferroni区间，能力通过不等于金融形状优越，也不授权backbone扩模。

512长度单独挑战。三项扰动只在128长度、共享同一个干净潜在任务上做：正的随机dt、原始16维数值输入加Gaussian噪声、固定删除25%的非信息filler。删除仅由评估生成器识别任务标记；模型没有新标记分支。记忆任务保留首信息/末查询，检索保留四关联/末查询。删去时间累加到下一保留token，保留原总时长；每样本同样删31或30个filler，因此输出长度固定97或98且所有dt正。它不能代表缺失关键信息仍可恢复的能力。

async128改变时间分布而保留原标签，因此只检验这类时间扰动的鲁棒性，不证明模型完成了必须正确积分时间才能求解的任务。

新训练长度为8/16/32，每种2048例；新validation32、各确认/挑战条件均512例。旧有限词汇的短训练序列可以重复，不能假称整个输入空间无重复；要求新的validation/干净确认在匹配长度上与已知历史、当前训练和其他新确认精确不重合。扰动条件与clean128共享潜在任务是有意配对。

FullHX/C1参数、状态、初值和minibatch序列相同；纯memory用单独宽度匹配约6200参数，实际状态和成本另报，不把它称完全等资源。所测是合成四分类任务，金融参数仍固定，不能外推成语言模型、连续感知或全模态能力。
