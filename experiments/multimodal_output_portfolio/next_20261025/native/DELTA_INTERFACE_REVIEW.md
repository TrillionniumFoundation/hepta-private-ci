# 新 signed action-value critic 的原生接口静态方案

这是对 `next_20261025/action_value/model.py` 的接口评估，未修改当前冻结 native 源、未导出尚未资格的模型、未执行新来源。是否进一步部署取决于新 critic 的独立评价。

## 可直接保留的函数

新 head 是 `763 public → normalization → Linear(H) → tanh → Linear(4)`，H 由冻结选择确定为 32 或 128。四个输出是 action-minus-stop 的 signed exponential moment difference；stop 恒为零。H1 排除 semantic，H2 保留其作用。原标签及 H2 cross-fitted backup 已包含约定的 continuation cost，因此 native 不应重复加成本。

可以像现有 teacher 一样做精确函数拆分：实际 public encoder 执行归一化和第一层；native 模型 port 加载、执行最后的 `4×H` 线性层，并拼接 stop=0。这不需要再训练。它是显式分布式模型计算，encoder 成本必须计入；不能把所有模型都在 native 内执行作为声明。

新输出允许有限负值，**不能套用现有 moment 的 softplus 或 value>0 检查**。选择应在原 native admission 允许的集合内，对 `[0, delta_semantic, delta_image, delta_text, delta_couple]` 求最小值。固定 tie 顺序和 H1 semantic mask 应与 Python policy 一致。日志应明确命名 `signed_action_differences`，仍使用可往返十进制字符串，避免旧 f64 JSON hash 问题。

## 最小清楚的 ABI 增量

现有 511 维输入没有空间追加 32/128 个新 hidden，原生输入上限仍为 512。不过目前新 correctness admission 实际只使用四个 absence 坐标、action 编码和原 teacher hidden32；没有使用其余公共前缀。因此可以增加独立版本的 compact ABI，而不改变产品 owner：

| 新输入坐标 | 内容 | 保持条件 |
| --- | --- | --- |
| 0:4 | 原公共坐标 448、449、460、471 | Q24 值逐项保留，用原 complete-absence 判定 |
| 4:6 | 原 action flags | 保持五动作编码及顺序 |
| 6 | horizon | 当前已资格范围只允许 H1 |
| 7:39 | 原 teacher 的 32 个 hidden | 保持原第一层、归一化、Q24 quantization |
| 39:39+H | 新 critic 的 H 个 hidden | 冻结 normalization/第一层、Q24 quantization |

总宽度为 **71 或 167**，都低于原 512 上限。版本应由新 preprocessor/encoder/model identity 和 descriptor 明确区分；不能把这个新布局冒称为旧 511 维布局。所有候选除了 action flags 必须具有相同公共编码，request public-prefix digest 继续绑定同一原始动作前 state。

需增量修改的研究适配器为：公共 encoder/export、native `ValueHead` 输入解析和 signed final layer、`Control` 宽度/receipt、controller 字段/选择、descriptor/config 的新输入维度与身份。原 `AgentdNeuronOwner`、33 维 probability carrier、原准入/资源门、持久决策、真实生成、观察绑定、NDU projection 和恢复不需要改变。旧冻结版本应完整保留，另建新版本。

当前 pooled correctness predictor/calibrator 的数值函数可以逐项保持：原 hidden32 与四个原始 absence 坐标完全相同，新表示只是搬运它们。仍应在旧 development 上量化 probability/Q24/admission、signed delta、选中动作的 parity，并重做必要的实际执行/恢复验证；该验证不增加新来源 N。新 delta 经过 Q24 hidden 后的输出误差可按最终层权重 L1 范数计算上界，但靠近 stop=0 或两个 action 的小间隔可能翻转选择，不能事先保证动作完全一致。

## 资格不能自动迁移的两处边界

1. 现有 correctness admission 只在固定 `initialize → refine_image` 后的 H1 状态获得独立资格。H2 根状态，以及 H2 选出 semantic/text/couple 后到达的其他 H1 child，都不在此资格范围。原先的 pooled 结果不能授予这些新状态或 selected-action 的同等校准保证。
2. 新 action-value 研究若在完整 H2、无 native admission 的策略上通过独立评价，不等于新的 admission-masked H1/H2 策略也获得了相同收益。引入 gate 会改变实际策略与访问分布，需要独立定义对应的效用评价，不能转移原全动作策略结论。

若新 critic 的独立效用评价不通过，不应为把接口做完而重复打开新的 native 确认来源。若通过，可先在旧 development 上完成真实 owner 的数值与生命周期接入；之后只对明确的新状态资格或实际受门控制的策略，按预先冻结的范围取得所缺证据。这里没有提出放宽门、复用正式来源调参，或以研究身份代替生产授权。
