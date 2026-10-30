# Hosted comparison 独立复算审计

**结论：70项完整有效；同一HCSN的忠实加速门槛通过；外部控制的质量条件速度门槛0/18通过。**

证据固定于 commit `a0de582931981b3742433475ecf5565409854a5c`。本审计直接读取原始发布的计量数组与执行回执，依据COMPLETE中的登记顺序恢复seed配对，并用逐项wait4 CPU和RSS交叉锚定顺序；未调用原analyze.py、未改参数或门槛。[协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/HOSTED_PROTOCOL.json) · [终态](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/comparison002_hosted/COMPLETE.json) · [原分析](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/comparison002_hosted_analysis/ANALYSIS.json)。

本次是此前本地7个任务已完成heldout评估之后的工程复跑。70项全部在hosted环境重新运行，旧7项未补入、未混合。原分析器完成完整logit/checkpoint/梯度/批次审计；本独立审计的范围是配对、原始计量数组、阈值计算和成本，不宣称重复加载全部NPZ或重放训练。

## 六个主配对：固定32次更新

|任务|Seed|Reference训练CPU秒|Accelerated训练CPU秒|训练CPU速度比|整个worker速度比|
|---|---:|---:|---:|---:|---:|
|selective_copy|98031|16.612549|8.433636|1.9698×|1.7379×|
|selective_copy|98032|16.468047|8.361939|1.9694×|1.7251×|
|selective_copy|98033|16.246507|8.359102|1.9436×|1.7068×|
|mqar|98031|16.231551|8.427147|1.9261×|1.6923×|
|mqar|98032|16.788685|8.247006|2.0357×|1.7654×|
|mqar|98033|17.124103|8.212308|2.0852×|1.8344×|

训练CPU的配对几何平均速度比为 **1.987543×**，对应计算时间减少 **49.69%**；整个worker的配对几何平均为 **1.743032×**。六个比值均大于1，几何平均高于预定1.10。六个主配对选定accuracy完全一致。原始误差回执中的最大loss差为2.38e-07、最大参数差2.96e-06，低于预定绝对容差；这项独立审计检查回执数值，不重新声称张量重算。

## 相同30 CPU秒：质量与全部控制

|模型|Copy准确率（均值±样本SD）|MQAR准确率（均值±样本SD）|Copy更新数均值|MQAR更新数均值|
|---|---:|---:|---:|---:|
|hcsn_reference|21.55% ± 2.15pp|16.60% ± 3.41pp|59.0|58.7|
|hcsn_accelerated|35.29% ± 0.88pp|33.50% ± 1.45pp|112.0|112.0|
|two_gates|99.06% ± 0.79pp|19.73% ± 11.16pp|2016.0|2043.0|
|transformer|44.73% ± 1.22pp|100.00% ± 0.00pp|3368.0|3373.3|
|lif_snn|13.57% ± 0.70pp|12.89% ± 1.67pp|1812.0|1795.3|

selective_copy：加速版相对reference的配对accuracy均值提高 **13.74pp**，3seed描述性t95%区间为[9.42,18.05]pp；更新数比均值1.8983。该改善是在同CPU下完成更多更新的工程效果，不是新增模型参数或任务价值最优边界的证据。

mqar：加速版相对reference的配对accuracy均值提高 **16.89pp**，3seed描述性t95%区间为[9.59,24.20]pp；更新数比均值1.9093。该改善是在同CPU下完成更多更新的工程效果，不是新增模型参数或任务价值最优边界的证据。

**18个外部质量条件比较全部不合格。** 预定规则要求三个paired seeds中双方准确率都达到50%/75%/90%的目标，并且每对相差不超过2pp。HCSN加速版在两任务的所有seed上均未达到50%，因此不能报告相同质量下比two_gates、Transformer或LIF更快。Copy最佳控制为two_gates99.06%，MQAR最佳为Transformer100%；这些差距必须与约2倍内部加速同时报告。

## 描述性补充与解释边界

固定16次更新、各1seed：irregular的HCSN两个backend均80.47%，two_gates89.84%、Transformer69.92%、LIF84.77%；CREMA-D两个HCSN均17.50%，Transformer20.83%、two_gates和LIF均16.67%。这些结果不支持全模态大模型质量优势。当前AV仍是共享线性头的算术late fusion，且复用已有actor split。

## 成本：采用单一非重叠计量层级

|计量项|CPU秒|解释|
|---|---:|---|
|70项纯训练时钟合计|1089.402744|是worker成本的内部组成，不能再相加|
|70个完整worker wait4合计|1408.708157|含导入、设置、验证、检查点和heldout|
|原study coordinator自身|6.861836|也已包含在外层HOSTED_TRAIN wait4中|
|hosted prepare完整阶段|19.477374|直接child wait4加此层coordinator自身|
|hosted train完整阶段|1416.040972|直接child wait4加此层coordinator自身|
|hosted finalize完整阶段|15.111433|直接child wait4加此层coordinator自身|
|hosted三阶段合计|1450.629780|此行与以上阶段择一使用，不能重复相加|
|证据打包函数|33.374690|另列函数体成本|
|三阶段加打包的测得合计|1484.004470|不含未知安装、publisher网络、开发等开销|
|此前本地失败cohort的9worker|128.032042|其中失败2worker为38.397553秒，不能丢弃|
|此前本地coordinator|1.544929|与其worker成本独立|
|此前只读内存备份|0.350074|单列，非训练成本|

完整70任务调度的wall time为718.643秒；最大worker峰值RSS为795.93MiB；CPU族最大完整更新过冲0.383314秒。wall time与CPU秒含义不同，不能跨机器把速度比混合。

[prepare完整回执](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/hosted_prepare001/RUNNER_PREPARE_RESULT.json) · [train完整回执](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/comparison002_hosted/RUNNER_TRAIN_RESULT.json) · [finalize完整回执](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/hosted_finalize001/RUNNER_FINALIZE_RESULT.json) · [证据打包回执](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/artifacts/hosted002/PUBLICATION.json)。未知开发、安装和网络CPU仍为null；不能把以上测得子集描述为整个研究项目的完整总成本。

12份登记输入NPZ的SHA与旧cohort全部一致，124项数学/模型/训练源码身份全部一致；本报告只新增审计材料，不修改源码或实验。
