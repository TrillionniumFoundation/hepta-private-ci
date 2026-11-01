# R13：R12 原始记录的独立质量与成本重算

**这是已公开结果后的历史重分析，未重训、未选择新候选，也不是新的留出确认。**
720 份原始预测独立重算；96 个模型的质量、102 个训练任务和 294 份模型流程成本按身份配对；另计1份原始审计收据。本报告只分析固定期望 renewal 门的内容模型；数值 HX 核和真实动作价值线不因此合为一个模型。

## 输入身份与核验范围

INPUT_MANIFEST.json 列出本轮实际读取的每个文件、字节数和 SHA-256。SOURCE_MANIFEST.json 冻结本次分析代码及协议。原 R12 已记录的源码冻结与本地副本字节匹配；这不证明全部原始结果此前已经上传远端。候选只核对清单、训练摘要和评估摘要中的 SHA 链，不读取或重新执行权重。本程序不导入 R12 的模型、数据生成器或 audit_results.py。

## 进程总账

| 阶段 | 收据数 | CPU 秒 | 失败 | 峰值 RSS MiB |
|---|---:|---:|---:|---:|
| worker | 102 | 361.400232 | 0 | 281.520 |
| evaluate | 96 | 176.235522 | 0 | 218.484 |
| profile | 96 | 152.375027 | 0 | 215.785 |
| audit | 1 | 4.604500 | 0 | 236.195 |

训练总账包含6个共同 donor，各计一次。独立部署单个候选的训练成本包含该 donor 全额与该候选 fit/选择。allocated_research_training_cpu_s 将 donor 按16个使用者均摊，只用于核对研究总账。内层训练/验证 CPU 已包含在完整进程 CPU 中，不能再相加。并行 worker wall 不能相加解释为研究耗时。

## IID 质量与实际 profile 成本

每个 latency 先取该 fit 的12次 CPU 计时中位数，再对3个 fit 求均值；batch32 按32个样本摊分。这些是缓存原始张量经完整 encoder/core/readout 到输出拷贝的 warm CPU 测量。不是请求网络时延，也没有把启动、训练和 profile 内的重复调用再次计入单次请求。

| 任务 | 模式 | 模型 | IID 准确率 | batch1 ms | batch32 ms/样本 | fit CPU s | donor+fit CPU s | batch1 Pareto |
|---|---|---|---:|---:|---:|---:|---:|---|
| recall | frozen_frontend | ordinary_dual | 0.516927 | 0.579468 | 0.022432 | 3.204742 | 6.026747 | 是 |
| recall | frozen_frontend | probit | 0.516927 | 0.840053 | 0.040038 | 3.630197 | 6.452202 | 否 |
| recall | frozen_frontend | analytic | 0.519531 | 1.911536 | 0.153790 | 4.788198 | 7.610203 | 是 |
| recall | frozen_frontend | lif_snn | 0.335938 | 0.926582 | 0.036217 | 3.703333 | 6.525338 | 否 |
| recall | frozen_frontend | continuous_rnn | 0.464844 | 0.546705 | 0.020228 | 3.302138 | 6.124143 | 是 |
| recall | frozen_frontend | cfc | 0.507812 | 0.989005 | 0.037466 | 3.527950 | 6.349955 | 否 |
| recall | frozen_frontend | mamba1 | 0.335938 | 1.026191 | 0.046282 | 3.668714 | 6.490719 | 否 |
| recall | frozen_frontend | transformer | 0.451823 | 0.381212 | 0.026601 | 3.267116 | 6.089121 | 是 |
| recall | joint | ordinary_dual | 0.505208 | 0.599238 | 0.024542 | 3.531896 | 6.353901 | 否 |
| recall | joint | probit | 0.505208 | 0.970003 | 0.040831 | 3.859272 | 6.681277 | 否 |
| recall | joint | analytic | 0.507812 | 2.047759 | 0.166696 | 5.216159 | 8.038164 | 否 |
| recall | joint | lif_snn | 0.335938 | 1.242498 | 0.044481 | 3.399944 | 6.221949 | 否 |
| recall | joint | continuous_rnn | 0.490885 | 0.538695 | 0.023908 | 3.407513 | 6.229518 | 否 |
| recall | joint | cfc | 0.475260 | 1.294441 | 0.045585 | 3.861639 | 6.683644 | 否 |
| recall | joint | mamba1 | 0.480469 | 0.895850 | 0.045264 | 3.766633 | 6.588638 | 否 |
| recall | joint | transformer | 0.617188 | 0.317815 | 0.019592 | 3.258083 | 6.080088 | 是 |
| binding | frozen_frontend | ordinary_dual | 0.522135 | 0.616413 | 0.024835 | 3.285232 | 6.321494 | 否 |
| binding | frozen_frontend | probit | 0.522135 | 0.503778 | 0.022716 | 3.098530 | 6.134791 | 是 |
| binding | frozen_frontend | analytic | 0.518229 | 1.359700 | 0.121836 | 4.251968 | 7.288230 | 否 |
| binding | frozen_frontend | lif_snn | 0.498698 | 0.774141 | 0.027590 | 3.201908 | 6.238170 | 否 |
| binding | frozen_frontend | continuous_rnn | 0.498698 | 0.585806 | 0.024115 | 3.168693 | 6.204954 | 否 |
| binding | frozen_frontend | cfc | 0.501302 | 0.998969 | 0.042956 | 3.188347 | 6.224609 | 否 |
| binding | frozen_frontend | mamba1 | 0.500000 | 0.686754 | 0.031682 | 3.381663 | 6.417924 | 否 |
| binding | frozen_frontend | transformer | 0.502604 | 0.442343 | 0.024879 | 3.133550 | 6.169811 | 是 |
| binding | joint | ordinary_dual | 0.526042 | 0.752069 | 0.028893 | 3.276405 | 6.312667 | 否 |
| binding | joint | probit | 0.527344 | 0.631526 | 0.027973 | 3.263552 | 6.299813 | 是 |
| binding | joint | analytic | 0.523438 | 2.163582 | 0.146999 | 4.334027 | 7.370289 | 否 |
| binding | joint | lif_snn | 0.501302 | 1.003027 | 0.035583 | 3.583667 | 6.619928 | 否 |
| binding | joint | continuous_rnn | 0.503906 | 0.623657 | 0.023702 | 3.364422 | 6.400683 | 否 |
| binding | joint | cfc | 0.509115 | 0.933727 | 0.036937 | 3.633740 | 6.670002 | 否 |
| binding | joint | mamba1 | 0.500000 | 0.723976 | 0.030847 | 3.716860 | 6.753122 | 否 |
| binding | joint | transformer | 0.518229 | 0.383134 | 0.022355 | 3.332388 | 6.368649 | 是 |

逐 seed 及全部 stress 域在 per_seed_quality_cost.csv；三个 seed 的质量和计时均保留，Pareto 是种子均值的描述性前沿，不是显著性结论。96个完整模型在 IID 与验证集具有同一输入形状；stress 域缺少对应 profile，因此 domain_cpu_s_per_request 留空，不用 IID 计时冒充长度外推或 clock4x 成本。

## 训练摊销

对单个候选复用 N 次，绘制 CPU/request = (T_donor + T_fit)/N + t_warm_request。
N 从1到1,000,000，原始逐 seed 情景在 training_amortization.csv。该数值是测得训练成本与 warm 请求成本的会计组合；未测生产服务加载/编译、部署基础设施、外部数据获取，不能冒称完整生产成本。不赋予 CPU 价格，不把质量换成货币，不把 CPU 秒乘假定功率生成 Joule。

## 八族基线及调参预算

普通双头、匹配中心斜率 probit 与 renewal 三者均为1,584个动态核心参数，初始化严格配对。真实 LIF+替代梯度、continuous RNN、官方 ncps CfC、Mamba-1 CPU serial scan、SDPA Transformer使用最近实际宽度匹配，误差分别为3.03%、3.09%、2.02%、0%、5.81%。每 fit 固定128步、batch32、lr=0.003，允许step zero；并未逐族调参。LIF/Mamba有chance附近或step-zero结果，当前范围是固定预算对照，不能称最强充分优化基线已被击败。Mamba未使用融合GPU scan，Transformer调用真实SDPA；这些CPU结果不推断GPU排名。

frozen_frontend 仅冻结共同的当前/前一帧编码器，动态核心与任务readout仍训练。joint训练三者。内容 analytic 是固定漂移、噪声、reset和不应期的有限完整 E[N] 门，加普通write头；它不持有完整存活条件密度，也没有求解任务最优自由边界。特殊函数成本已包含在模型profile内；完整分布存储和自由边界求解没有在这个模型里发生，不能借数值线的验证补齐。

## 能耗与成本缺口

本轮只读探测到可见遥测：False。详情在 ENERGY_VISIBILITY.json。这是当前容器可见性，既不声称物理宿主没有传感器，也不替代原运行的能耗记录。即使存在共享host计数器，也不能自动归因到本任务。R12历史能耗维持null；原meter的energy_sensor_available字段是固定值，不将其当作实际探测结果。

进程RSS含解释器/库/模型，不是分布状态专项内存。当前还未测在线外部查询、流式cache、stress域推理时延、优化GPU实现、物理能耗与生产服务初始化。在这些缺口关闭前，不能用局部核速度或抽象任务tariff声称完整计算净优势。

## 文件

- process_ledger.csv：294份模型流程与1份原审计进程收据及hash。
- per_seed_iid.csv：96候选逐seed的IID质量、CPU、训练、RSS、身份。
- per_seed_quality_cost.csv：720个逐seed×域记录；未测域时延为空。
- aggregate_iid.json：均值及batch1/batch32描述性Pareto。
- training_amortization.csv：1,248个逐seed×请求数情景。
- quality_cpu.png / .svg：IID质量与CPU。
- training_amortization.png / .svg：训练复用成本。
- ANALYSIS_PROCESS_RECEIPT.json：本次重分析自身成本，与R12总账分开。
- INPUT_MANIFEST.json / SOURCE_MANIFEST.json：复跑所需字节身份。
