# NDU 持续状态与真实生成桥：v4 实现及资格记录

本候选把用户提出的六个实现方向连接到可执行入口，并以独立源码清单记录每次验证。研究状态仍是 **数值与集成资格候选**；合成诊断不构成真实任务收益、语义生成质量或生产采用的证据。具体执行结果、失败尝试及其源码范围见本目录的 JSON 回执和测试日志。

## CI 追加修复及源码身份

原始数值与云端资格对应候选 `e2802a53a82529b9a206f77fcdfa98dd65918bfc`。首次 PR CI 暴露了一个方法名碰撞：根写入器的词法规则没有限定接收者类型，因此也匹配了交付合同的 `validate_successor`。追加修复仅将其声明及调用改为 `validate_delivery_successor`，并应用原有 rustfmt；三个文件做逆向改名后，再以同一格式规则规范化，均与原文逐字节一致。验证器和特权调用清单没有修改。

改名后的 19 项现有原生测试、格式检查、scoped Clippy `-D warnings` 和实际原生编译通过。使用同一官方调用规则及精确的规范调用文件，修复前重现原 CI 错误，修复后通过。另将合法包名 `inout` 加入现有拼写词表，原始基线编译日志保留。完整记录见 [POST_CI_QUALIFICATION.json](POST_CI_QUALIFICATION.json)。

新编译的 ELF 与原云端 ELF 的 SHA 不同；本次命名修复没有重新进行云端训练或数值回放，原始云端结果仍绑定原执行文件，不移记为新 ELF 的运行证据。所有 NDU 数值逻辑、训练参数和原测量值均保持不变。首轮 CI 的 cargo-deny 还报告了既有 `pin-utils` / `vodozemac` 依赖通告；本候选没有修改依赖图或屏蔽这些通告，不能据此宣称完整工作区 CI 通过。

## 已执行的资格结果

| 范围 | 结果 |
| --- | --- |
| `hepta-neuron` 完整 lib，精确三 crate 依赖闭包 | 179 passed，0 skipped；scoped `just fix` / `just fmt` 通过 |
| 实际原生生成核 / 有限 entropic 模块 | 19 + 6 passed；scoped Clippy `-D warnings` 通过 |
| 最终 Kaggle runtime 契约 / v4-NDU 单测 | 27 + 8 passed；原生进程测试真实执行，无 native skip |
| 同 v4 权重的三项独立优化、导出、载入、Auto 与媒体解码 | 完整通过；6 项 FP64 中心差分最大误差 2.65e−10 |
| Python / Rust 原生规划与状态 | 根评分最大误差 1.11e−16，状态最大误差 4.03e−16；提交字节逐字相同 |

最终训练与原生载入的 checkpoint 均为 `fd5a17c0a5a706175130a88104aee00f762d0c923a2a090197f7e02e85be3fb5`。递归项与策略项分别造成核心参数的非零梯度及实际更新；详细分组见 [QUALIFICATION.json](QUALIFICATION.json)。这轮 Auto 序列是 audio → audio → shared → audio → stop；最后一步由模型现有 step=6 的合法动作边界强制 STOP，不能据此声称学会了最佳提前停止。

首个冻结 runtime 的 6 项方向差分最大误差为 5.37e−12，训练/推理规划值差异不超过 3.89e−16。它的原始回执保存在 `cloud-v1/`；后续 receipt 元数据修订与旧快照的完整差异保存在 `POST_V1_RUNTIME_DIFF.patch`，数值核心源码逐文件确认未变。最终 width32 原生闭环的独立回执保存在 `cloud-v4/`。

所有中间失败保留在 [attempts.json](attempts.json)：包括提交前 Kaggle scope 拒绝、width8 诊断被 width32 原生 profile 拒绝、首次 lint 与临时测试脚手架失败。完整工作区 Cargo/Bazel 和真实任务收益未由上述结果代替。

## 源码身份与提交范围

- 原生基线：`1e6bc8517d61fd42496bc0ed5082e34204b065dd`。
- 票据任务 runtime 的机械导入来源：`7ca2f6657529a538ccd17e056dfaf0269b1a14aa`，原始 30 个文件均按保留清单逐一验证。
- 这是独立组合候选。两个来源各自已有的测试、采用状态和历史实验结论不会自动成为本候选的证明。
- `SOURCE_BASES.json` 保存来源；`FINAL_CODE_MANIFEST.json` 保存本次交付代码的 SHA256 与 Git blob 身份。提交按数学算子、观察/codec、规划、原生接线、宿主预算、Python 状态/训练、同权重闭环和资格证据拆分。

## 六项改动落点

| 方向 | 实际入口 | 新行为 |
| --- | --- | --- |
| 权威交付观察 | `joint_generation/observation.rs`、`observed_model.rs`、宿主 `cell_joint_observed.rs` | actor 与两个 critic 都接收真实提交前缀的特征、游标、已用/剩余预算、required/optional 义务 |
| 持续核心和生成 codec | `state.rs`、`model.rs`、`decoder.rs`、`text_codec.rs`、`media_codec.rs` | 四状态 Hepta 核心跨动作保存；有序字节输入、UTF-8 自回归输出；PPM、WAV、Y4M 实际容器 |
| 有限 NDU 规划 | `planner.rs`、`proposal.rs` | 明示 profile、预算和合法动作筛选、真实模型滚动、有限递归、可读规划回执 |
| runtime 状态对照 | `scripts/ndu_real_runtime/neural.py`、`actor.py` | episode 内传递核心 memory，保留显式 reset；完整轨迹按 episode 展开训练 |
| 目标梯度 | `recursive_objective.py`、`fit_loop.py`、`training.py` | 冻结参考模型的递归目标和有限动作策略项进入实际 backward/optimizer；各项梯度独立核对 |
| 同权重训练到原生生成 | `joint_generation_v4_{model,ndu,gradients,diagnostic}.py` | v4 生成器经独立 NDU/策略/文本训练步骤后导出；同一 packet 由原生 Auto 读取并逐步比较 |

## 观察及宿主预算契约

新增权重格式是 `joint-generator-weights-v4`。v3 权重、HJREQV01 请求与 HGC1 输出保留原有含义，观察版使用 HJREQV02、HGC2 及独立 manifest schema。

宿主公开 `JointGenerationDeliveryContractV2`、`JointGenerationCommandV2` 和 `JointGenerationInputV2`。required/optional 两个四位 mask 按 image、audio、video、text 排列，二者不得重叠，总选择必须非空。契约绑定任务摘要、总预算、截止时间和义务。每个 v2 请求必须使用相同任务截止时间；更短的请求截止时间也会被拒绝，以保证观察预算与实际可执行时间一致。

预算单位固定为 `wall-microseconds-v1`。剩余预算由任务截止时间减去宿主当前单调时钟读数得到，调用方不能在 Auto 命令中另填剩余比例。桥验证前驱契约相同、剩余预算不增加、提交游标及前缀一致。已截止但尚未启动的请求产生 `DeadlineExceeded` 和相应 Cancelled 成本结果，保留已发生的校验计时。

actor、continuation critic、delivery critic 的输入都增加 68 个观察特征。它们包括各模态游标、完成度、义务、提交字节数量、均值/方差、有序校验摘要及尾部字节，还有总预算量级与剩余义务。前缀由真实已提交帧解析得到，调用方不能用预测前缀替换它。**68 维特征是有损字节摘要，不声称具备完整语义理解。**

显式 Advance 与 Auto 都执行同一合法动作检查。STOP 在预测副本上或实际提交阶段仅补齐 required 模态和已经开始的 optional 模态。未开始的 optional 模态不会自动成为交付义务；停止状态缺少 required 内容会被拒绝。

## 内容表示、核心状态及输出边界

v4 将输入文本编码为有序 UTF-8 字节序列，使用 256 个字节嵌入与递归编码。生成器保留四状态 Hepta 核心、共享状态、各模态状态、文本隐藏状态、游标和解码计数。序列化恢复继续使用这些状态。`persistent-v1` 与 `reset-each-action-v1` 是显式不同的实验配置；v3 原本已有持续核心，本次并未把它误记为新发现。

输出有下列明确上限：

| 模态 | 容器与上限 |
| --- | --- |
| 图像 | P6 PPM，16 × 16 RGB |
| 音频 | 单声道 PCM16 WAV，16 kHz，共 1,024 个采样点 |
| 视频 | Y4M C444，16 × 16，共 4 帧，4 fps |
| 文本 | 受 UTF-8 合法性约束的字节自回归，最多 128 个 Unicode scalar |

这些是可由独立程序读取的真实内容容器。开放字节词表消除了固定词表枚举限制，仍需真实数据训练和独立质量评价才能讨论可用语义能力。图像/视频尺寸和音频时长均为当前数值研究配置。

## 数学与推理 profile

新增连续数值算子身份是 `hepta.ndu.finite-entropic.v1`。它与仓库已有 Q32/FBSDE 等配置并列，未重新解释旧 profile。

对有限概率分布，使用：

\[
\operatorname{CE}_{\eta}(X)=-\eta^{-1}\log\mathbb{E}\exp(-\eta X),
\qquad \operatorname{CE}_0(X)=\mathbb{E}X.
\]

每条边只收取一次预测时间成本，时间以秒为单位：

\[
Q(s,a)=\operatorname{CE}_{\eta}\left[-\lambda\Delta t+
\gamma^{\Delta t}V(s')\right],\qquad V(s)=\max_a Q(s,a).
\]

默认参数为 risk 0.25、discount per second 1.0、latency weight 0.01。极小正 risk 使用均值中心化的 `expm1/log1p`，其他区间使用移位指数计算；零概率极值不参与稳定性基准。共享黄金向量与 risk 0、1e−300、1e−20 等检查防止风险中性极限出现数值消减。

原生 `ndu-finite-deterministic-v1` 使用真实生成核作状态转移、单粒子、固定已准入发射种子。单粒子下 risk 在数学上不改变价值，不能用这条 profile 声称观察到了风险敏感性收益。默认 horizon=2、max_forecasts=32，各动作预测耗时为权重包声明的微秒数。所有可负担合法根动作先各获得一次预测，再分配更深展开的调用额度；截断使用 continuation critic，STOP 使用交付后的 delivery critic。critic 输出经 sigmoid 表示质量预测。时长是配置/模型预测，实际规划 wall time 由宿主另外测量和记账。

`actor-greedy-observed-v1` 仍可作为控制器对照，其回执明确标注 `actor-probability-argmax-v1`。它不被记为运行了递归 NDU。所有规划回执记录 profile、噪声、所选动作、根评分及评分 mask、horizon、预测调用数/上限、耗尽状态和所选动作预测耗时。

票据 runtime 的默认规划为 horizon=3、particles=4、max_forecasts=96。噪声是按 `[seed, step, action]` 固定抽样的经验残差对角 Gaussian，不声明 Brownian 或 `dt` 扩散缩放。有限差分复用同一噪声。部署契约分别绑定完整 `ControlPlan` 的规范 SHA、utility profile SHA、weights SHA、core、memory mode 与独立 rubric revision。`ControlPlan` 摘要包含 horizon、particles、预测上限、memory mode 和效用参数；rubric 与权重使用各自的绑定字段。persistent/ndu_policy 要求该契约，旧 reset/v1 兼容入口允许缺失。

## 训练及同权重验证的含义

票据 runtime 的 v2 轨迹记录真实 step、前驱 SHA、合法动作、剩余预算、采集 memory mode、行为 control profile、rubric 与相邻状态/分数。persistent 训练要求完整链，按 episode 初始化并进行跨动作反向传播。v1 旧数据继续支持 reset 辅助训练。

参考 critic/world model 在总 epoch 预算内先完成一次观测目标 warmup，随后冻结。参考参数不更新，关于输入状态的导数保留。递归损失为 `-V0`，策略项为 `-sum(pi * stop_gradient(Q_reference))`。该策略项是有限动作、模型依赖的策略改进梯度；不是无偏环境回报估计。真实工具和外部 rubric 不被假定为可微。

v2 数据允许明确的离线重放：例如 reset 采集的完整观测链用 persistent 模型重新编码。训练 receipt 单列采集 memory modes、训练 mode、是否发生改变及行为动作/分数的来源，不把这种重放称为同策略采样或反事实环境收益。

新 v4 闭环分别执行递归、策略和 teacher forcing 三次独立优化步骤，记录各项对核心、字节嵌入、共享文本递归层、actor 和 decoder 参数的梯度及实际更新。递归/策略目标可以经有序输入编码与连续状态改变同一生成模型。硬字节选择与量化没有重参数梯度；decoder 专用发射参数通过文本监督更新，该贡献与 NDU 贡献分开。

闭环将训练后的 packet 保存并重新载入，随后交给真实 `hepta-joint-propose` 的 Init/Advance/Auto。比较根评分、评分 mask、动作、预测调用数、核心/文本状态、输出字节，并用 Pillow、WAV reader、ffprobe 独立读取媒体。参考 critic 是未校准合成权重，这项检查证明接线和数值一致性。

## 外部终局指标及后续真实数据评价

外部指标身份固定为 `ndu.real.observed-quality-minus-wall-cost.v1`：独立 rubric 质量减去 `latency_weight × deployment_wall_seconds`。这里的 wall time 来自实际部署运行，规划、模型和工具成本不能漏出计量区间。当前默认 duration discount 为 1；单个 episode 不被当作一个观测到的 certainty equivalent，递归 critic 值始终标注为模型预测。

真实数据上的 reset/persistent 对照必须使用同一数据划分、权重初始化、预算、动作支持、参考模型、rubric 和种子配对。除显式 `memory_mode` 外，其余 `ControlPlan` 字段保持一致；两组分别绑定各自完整的训练/部署 profile。训练数据收益、预测 critic 上升和外部终局收益分开报告；失败、拒绝、截止和未完成交付均保留。当前合成诊断不替代此评价。

## 复现入口

以下命令从完整候选仓库根目录执行。Rust 测试遵循仓库 `just` 入口；本次临时闭包和 standalone 构建的具体命令以各运行 receipt 为准，不冒充完整工作区验证。

```sh
PYTHONPATH=scripts:. python -m unittest \
  ndu_real_runtime.test_recursive_contract \
  ndu_real_runtime.test_span_meter \
  ndu_real_runtime.test_interval_costs

PYTHONPATH=scripts:. python -m ndu_real_runtime.gradient_check \
  --output /absolute/new-receipt-runtime-check

JOINT_V4_NATIVE_BINARY=/absolute/hepta-joint-propose \
  python -m unittest -v scripts.test_joint_generation_v4 scripts.test_joint_generation_v4_ndu

JOINT_V4_NATIVE_BINARY=/absolute/hepta-joint-propose \
  python -m scripts.joint_generation_v4_diagnostic \
  --output /absolute/new-same-checkpoint-check
```

缺少原生二进制时，旧 v4 单元入口会明确 skip 原生比较；新的同权重 diagnostic 强制要求原生二进制。检查通过数不得把 skip 计入。验证记录区分首个冻结快照、后续源码修订和每次执行身份。
