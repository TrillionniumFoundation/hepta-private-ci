# 新 action-value 实验的独立静态审查

本审查覆盖 `next_20261025/action_value/{model,develop,evaluate,analyze,audit_fit,register,process}.py` 与 METHOD，并跟读真实调用的旧数据收集、公共特征、generation transition、媒体持久化、来源分配和模型加载代码。没有启动 Torch/ASR、训练或正式生成，也没有读取新来源像素与质量结果。结论是：**审查后版本没有发现阻断执行的目标方向、交叉拟合或统计单位错误；是否获得有效动作收益和质量/成本资格仍须由预注册的实际结果决定。**

## 版本与本次发现的修复

| 文件 | 审查后 SHA256 |
| --- | --- |
| model.py | `9c578bdb9721da06b50de50bc8a06262a77d3cd17ea49593cfc01c27d71cce03` |
| develop.py | `3dcbe3f3af9ce10f3c19df80be179b0410a060f4010faf1e637f6bed69099230` |
| evaluate.py | `353d6a306a35ac09dd871c8c9b22f73756d3fee6b16d7526596cfef852d0d2f6` |
| analyze.py | `5647a15def80f980f8ddcb5c547febe542983d187e06438a92eba480c420ad29` |
| audit_fit.py | `3f43f600ce0b0427ecc3a8e72eb3dae2dec77301da8fa0ad895e5763553f3d38` |
| register.py | `74da8d3d3802eb0cc726462c3e4e6c7acb99b5f3c786e274499daa2167b2b351` |

初审发现两处身份绑定缺口，已直接通知 control agent 与 root；control agent 在该实验任何 development/正式执行前完成修改，复核如下：

1. `evaluate.run` 先核对冻结文件，再对**实际传入的** `asset.resolve()` 调用原 `asset_pins`，逐路径和 SHA 与 protocol 比较，之后才开放新来源。这堵住了“protocol 校验登记目录、运行却从另一个参数目录加载同 schema sensor/controller”的缺口。原 `load_controller` 自身不校验外部预期 SHA，不能仅靠它代替此绑定。
2. `analyze` 读取来源分配前校验 allocation SHA，明确要求 1024 条 source records、512 对、256 个 writer、每 writer 两对、两个组成样本的 writer 与 pair mapping 一致；每个实际 request 的 source IDs 也与对应 case 的已分配 source records 比较。统计 cluster 不再只依赖一个未核对的外部 mapping 文件。

另将真实计时边界补入 METHOD 与未来 protocol：root 媒体打包和候选独有的 H1 公共向量 clone 在 request timer 内；根节点诊断档案的 fsync 在 timer 外。没有要求为这些修复重跑旧实验或扩大正式样本。

## 1. Δ 标签、符号和停止基准

H1 标签为同一公共状态下的实际配对结果：

`Δ(a) = exp[-2 × (U(a) − 0.002)] − exp[-2 × U(stop)]`。

因此负值表示继续动作减少 exponential risk，选择最小值的方向正确。stop 在网络外固定为 0，网络只输出四个 signed difference，未施加错误的 positivity/softplus 约束。H1 semantic 保留实际输出但付动作费，所以被 stop 严格支配；代码屏蔽它，仍保留它作为 H2 的合法首动作。

`examples` 对原五个公共节点构造五动作结果表：root 对应原前五个 plan；每个首动作 child 的 stop 对应该首动作结果，其他四个终端动作按原 plan 顺序索引。root 被当作一个可查询的一步状态时，其 horizon 特征显式改为 0.5；其实际一次动作结果仍与这些标签一致。最终 H2 网络使用原 root horizon=1 的特征，未把这个辅助 H1 处理误用于 H2 输入。

固定 0.002 是动作代理成本，不是实测毫秒费用。经济曲线另外计算 `CE(U − price × measured_ms)`，没有把平均时间在 CE 之后简单相减。

## 2. 两折 OOF 与 H2 backup

旧数据的 `cases` 在原 collect 中由 `start + source_pair_index` 产生；同一 pair 的八个 view、两个 scenario 以及五个节点都绑定同一个 case。`cases % 2` 因而把这些重复测量完整留在一折。每折 H1 的 mean/scale 只由 fit 折计算，held 折没有参与网络拟合或归一化统计。

这是**source-pair 分组**的交叉拟合，不是声明旧 MNIST 数据已经按 writer 分折。新正式来源另外采用全新 writer，不能把两种独立性表述混为一谈。

对 held pair 的每个 H2 首动作，代码先让另一折 H1 网络只读当前 child 的公共特征并选动作，再索引该动作的已生成实际结果。标签等价于：

`exp[-2 × (U(first, selected_second) − 0.002 − 0.002 × 1(second≠stop))] − exp[-2 × U(root_stop)]`。

代码中的 `exp(2×0.002) × selected_child_moment` 正确加入了首动作成本；child moment 已包含第二个非 stop 动作成本。这里没有按私有已实现终值选最大收益或最小 moment。

`audit_fit.py` 使用保存的实际 fold 权重和 normalizer 重算 held 公共状态上的选择，校验 fit/held case 交集为空，并从实际终端 plan 与总动作费直接复算 H2 标签。它另外计算与私有 hindsight 最优的不同次数，但不把该私有最优送入训练或部署选择。

最终 H1 使用全部旧 fit 数据重拟合，确实不同于产生 H2 标签的 fold heads。METHOD 已如实将此称为一次近似策略 backup，未宣称 exact policy evaluation、Bellman fixed point 或全局最优。teacher 本身曾使用旧 fit 来源，因此它只作选型和比较，不用作伪装成 held-independent 的 backup baseline；这一区分正确。

## 3. 候选选择只使用旧数据

每个 seed 仅比较预先固定的 32、128 两个宽度。拟合文件要求旧 `forecast_fit[480,736)`，选择文件要求另一个旧角色 `forecast_calibration[448,576)`，并对照已冻结历史文件 SHA。角色名和索引范围共同决定来源，不能仅比较两个数字区间判断重叠。

选型先筛选相对旧 teacher 没有 raw CE 或 exact-success 点损失的候选，再按 action-cost CE 最大选择，固定 tie 规则。若没有候选满足开发门，明确保留一个 `development_admitted=false` 的研究候选，未把失败改称已获开发准入。正式统计结果仍须独立通过后续 family gates；静态审查不能将研究候选授予替代资格。

## 4. 实际执行与私有反事实分离

部署函数只接受 `Observation` 和当前 763 维公共特征。它不接收 Target、source label 或未来 RNG。两个策略从相同实际初态开始，每个配对请求内随机执行顺序，各自支付真实初始化、公共 CNN/sensor、head、generation、commit 和媒体保存/回读的成本。

每个动作在创建其未来 innovation RNG 前写入 commitment 并 flush/fsync。H1 诊断状态只由 owner 保留；候选的动作完成、两个策略的请求结束后，才在该保留状态上实际执行另外四个 action branch。选中动作直接复用已完成的实际媒体。所有目标评分发生在请求输出与反事实生成关闭之后，原始像素/token 由 lossless 204-byte record 解码和 SHA 核对。

分析核对每个实际 decision 与 commitment、一致的初态 SHA、同路径输出媒体一致、反事实 action census、公共父状态和预测身份，以及选中分支确实对应原实际输出。未发生 H1 的 root-stop 请求不会伪造 H1 反事实节点；若实际请求失败或诊断缺失，分析拒绝质量推断，而非删除失败样本。

私有 `hindsight regret` 使用同状态各动作各自实际 noise outcome 的最小值，包含未来噪声偶然性。它不是在线可达到的 oracle，也不是 conditional optimal regret。当前代码和 METHOD 对此限定清楚。H1 诊断只覆盖候选实际到达的状态分布，不能据此证明所有 H2 分支的价值校准或最优性。

## 5. 512 对、256 writer 与统计量

只读实际 allocation 元数据确认：512 对对应 256 个 writer，每个 writer 恰好两对。writer 与 native 资格的 1000 writer、当前所有 QMNIST 角色的 writer 交集均为零。实际已登记的 1024 个 pixel SHA 与 native 资格 2000 个 pixel SHA、当前 QMNIST 各角色的已选 pixel SHA 也无交集。这些核对不读取新样本像素或质量。

分析按 writer multinomial bootstrap 重采样，将一个 writer 的两对来源、八个 view、两个 future draw 和固定三个训练 seed 一起保留。若按协议完成，主请求数量为 `512 × 8 × 2 × 3 × 2 = 49,152`；该数量不能当成独立 N，独立 source cluster 仍为 256。训练 seed 是固定面板，区间不能解释为对任意训练随机 seed 的总体保证。

风险指标在每个 bootstrap 样本里对 exponential moment 汇总后取 log，计算顺序正确。selected-H1 事件用同一 writer bootstrap 权重及事件分母，能够保留不同 writer 到达 H1/选择非 stop 次数不同的结构。若某些重采样中无对应事件，代码返回不可计算区间并阻止相关 gate，不给出虚假确定结果。

动作价值 family 要求同状态可行非 stop 动作 MSE 优于零差预测，且选择后的非 stop 实际 action-minus-stop moment 有负的上界。all-selected 与 nonstop-only 分别报告，stop 的恒零误差不会单独令增益门通过。teacher 同状态 MSE 比较是预先说明的 secondary diagnostic；没有按结果把它另选成通过标准。

替代 family 保持 raw CE 与 exact success 的 −0.005 非劣效边界，并要求平均实际 request wall time 的差值上界小于零；这与“证明 raw quality 显著提升”是不同命题。各指标使用预注册 nominal 97.5% writer-cluster percentile 区间；四个价格的 bands 另按每种 clock 分别作 nominal 95% 同时带，不能扩展为所有诊断、所有 clock 的联合保证。

## 6. 成本与最后的声明范围

在线请求成本包含真实 public encoder、head、所选 generation、durable decision、terminal persistence/readback，也包含报告已明确说明的小量诊断准备。反事实枚举、根档案 fsync、私有 observer 评分、resident 模型载入在主请求 timer 外分别记录，但全部包括在整个 child 的 wall/CPU/RSS receipt 中。反事实生成不是免费的，也不能当成部署推理成本；同样不能把主请求毫秒数当成整个研究成本。

共享主机、随机配对顺序和 writer-cluster 区间提供本次执行的比较证据，不构成生产负载下的 latency 保证。该实验仍使用固定有限动作、H2、数字图像/文本与少量已训练 seed。即使预注册 gates 最终通过，支持的也是这个明确范围内的动作差预测与质量/成本替代结论，不是一般 NDU 全局最优，更不能自动继承到带 native admission 的新策略或生产授权。

本审查没有读取该实验的拟合或确认结果，因此没有预判通过。当前审查结论可以作为正式执行前的独立代码与科学方法检查记录。
