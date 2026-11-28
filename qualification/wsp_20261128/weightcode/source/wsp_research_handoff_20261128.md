# Weight-Space Programming：原始文献核验与 Hepta 实验边界

研究日期：2026-11-28。本文是研究协作中间记录；实际 Hepta checkpoint 与 Rust 运行时结论由对应实验记录负责。这里没有把外部模型成绩当成 HeptaTrader 端到端收益，也没有把元数据检查当成神经电路理解。

## 已独立完成的外部重执行

固定源代码为 [Gen-Verse/WeightCode](https://github.com/Gen-Verse/WeightCode)，commit `297c24db4b63c09a78d3552ac5f90865eaf95c9a`。官方 SCAN 示例的源数据与模型均由上游下载器核验 SHA。

- 模型：`ncc5c260f`，4 层、宽 128 的小型 Transformer，共 803,975 参数。
- 原始模型 canonical 参数 SHA：`9cee872c639d5d419cf759c9cff80ec86462b5533fdb64252220efd0a93126bc`。
- 程序：`s9be29c2c302e4daa/centroid_meanrow_floor.py`，SHA `b003c6b9e7a03a3d367633b600cb2ca8cac11cde428ea12b55bdc60362fc5320`。
- 重建 child SHA：`6c9bc3bdaf347dfb6c868a71f17506bea58ab51f82707f236692604dc34198a0`，与作者发布结果逐位相同。
- 公开的 sealed reading：新命令 2,568 行，0/2,568 → 2,563/2,568（99.8053%）；旧命令 1,000 行，996/1,000 → 996/1,000。
- 改动为 jump embedding 128 个值、I_JUMP head row 128 个值、head bias 1 个值，共 257 个值。
- 本轮官方重执行与最终评估墙钟 144.679 秒；其中程序 `update` 报告 84.377566 秒。只重新应用已算好的补丁约 0.0124 秒；三种成本不能混为一谈。
- 作者记录的 discovery：session result `wall_s=1860.065`；从 created 到 finalized 的完整间隔 1905.575976 秒；使用 3 次外部 checks（预算 8 次）。editor 是 Claude Opus 5.5、max effort，本轮重执行没有调用 LLM。
- 作者 token 记录：cache creation input 190,394、cache read input 5,059,217、input 116、output 128,903、thinking 100,858。保留上游字段口径，不把 thinking 再与 output 相加；当前记录未见该 session 确切美元账单。

重要信息边界：从程序静态计算，它用了 15,195 个 sample-forward rows。包括 64 个已标注旧经验行，964 个 jump 输入及其 964 个替代原语参考输入，以及所有 13,203 个 jump-free grammar 输入。其无标签探查涵盖公开 final 新命令中的 299/2,568 行和旧命令中的 1,000/1,000 行。未向程序提供 final 标签，但不能称为输入从未见过的全新独立 holdout。

记录位置：

- `WeightCode/reproduction_scan/runs/20261128T103750.741015Z/result.json`
- `scan_extension_protocol.json`：先固定全部 arms、种子与选择规则，再执行扩展。
- `run_scan_extension.py`：独立编排，上游数学/forward/Adam/LoRA 实现不改。
- `scan_extension/manifest.json`：协议与脚本 SHA、源 commit、环境版本。
- `scan_extension/arms/`：每个消融与所选模型的配对结果。
- `scan_extension/summary.json`：完整矩阵结束后才产生；缺少该文件表示矩阵未完成。

固定扩展包含 8 个三组件组合消融、3 个同支持/同分张量范数随机编辑，以及 head Adam、full Adam、rank-4 LoRA 各 3 个种子。每个 BP 方法/种子固定 2 个学习率 × 4 个步数（10/30/100/300），只按 V_check 与 old_check 选 checkpoint，旧集合最多净损失 5/1,000；最终只读所选模型。重复参数 SHA 的预测可复用，但区分逻辑 check 预算和实际执行的样本 forward 数。

BP 使用原始 65 个标签。WSP 额外拥有 grammar 和无标签探查，因此这是“相同原始标签经验”的对照，不是完全相同知识或总算力的对照。head/full 的全批确定性算法可能跨种子给出相同结果；不能据此宣称跨训练数据或基础 checkpoint 的稳定性。

### 固定 20-arm 矩阵完成记录

矩阵于 UTC 11:10:10 完成，墙钟 1,591.693 秒，峰值 RSS 1,027,676 KiB。8 个组件组合、3 个随机编辑、9 个 BP 方法/种子臂均完成，没有中途删除失败臂或看 final 改方法。所有回滚均恢复原始完整 canonical SHA。

| 固定编辑 | 新命令 EM | 旧命令 EM | 最终变化参数 |
|---|---:|---:|---:|
| base | 0% | 99.6% | 0 |
| embedding | 0% | 99.6% | 128 |
| head weight | 0% | 99.6% | 128 |
| bias | 23.3645% | 99.6% | 1 |
| embedding + head weight | 0% | 99.6% | 256 |
| embedding + bias | 79.5950% | 99.6% | 129 |
| head weight + bias | 26.5966% | 99.6% | 129 |
| 完整原程序 | 99.8053% | 99.6% | 257 |
| 同支持/范数随机 seed 0 | 17.6012% | 36.5% | 257 |
| 同支持/范数随机 seed 1 | 0.7009% | 99.6% | 257 |
| 同支持/范数随机 seed 2 | 0% | 99.6% | 257 |
| head/full/LoRA 各 3 seeds，按 check 选择 | 均 0% | 均 99.6% | 均选择 base |

训练确实改变过候选权重；“最终选择 base”不等于训练没有运行。9 个 BP 臂共执行 5,400 个 optimizer steps、351,000 个有梯度 sample-forward rows；额外 Torch forward 合计后为 356,850 rows，NumPy 实际 forward 为 186,227 rows。总 fit 墙钟 657.585 秒、check 墙钟 744.187 秒。缓存复用按完整模型 SHA 计，不能把跨种子的 cache 命中误报为每次重新测量。

基础模型在原始 65 条训练行的 token CE 仅约 5.2345e-9，几乎没有剩余监督信号。因此上述结果支持组件机制与信息预算诊断，不支持“训练本质上不如直接编辑”。完整程序相对 base 的按命令配对 bootstrap 95% 区间为 +99.6106 到 +99.9611 百分点；该区间只重采样这份公开命令集合，不覆盖 editor 搜索或独立 checkpoint 的不确定性。

为补齐规则知识公平性，已冻结作者预选的 rule-generated sparse q3（300步）与 full q2（100步）配置，正在 HeptaRuntime 实际 T4 上执行。它们使用 4,065 行相同 grammar 导出的数据；在正式完成文件出现前不将该项写作完成。云原生每 job 600 秒、内部软预算 480 秒、总最多 8 个 job；保留 optimizer 连续性并立即续固定任务，没有创建定时任务。

## 最新原始来源与可复现性

### 1. Sparks of Weight-Space Programming，2026-11-02

Rikiya Takehi、Jayden Teoh、Alex Zhang、Omar Khattab，MIT CSAIL 的研究博客，不是提出一个统一优化器的论文。原始作者把 WSP 定义为读写权重的概念；它可以包括梯度，博客实验为了隔离推理能力而禁用梯度。

GPT-6 Astra 的小网络任务有直接读取原始数值且不运行 forward 的实验；Qwen3.5-0.8B 编辑任务则有 Python、权重统计、激活和 50 次批量 forward 请求。每次请求可包含大量样本和长生成，50 次请求不等于 50 个样本。Qwen 的干预抑制循环，不能据此外推任意模型的新知识获取或替代所有训练。Gemma 小模型没有获得同等收益。

- [原始博客](https://rikiyat.github.io/blog/weight-space-programming/)
- [完整日志与程序](https://github.com/RikiyaT/lm_understand-logs)
- [公开 Qwen 编辑 checkpoint](https://huggingface.co/RikiyaT/Qwen3.5-0.8B-weight-space-programming)

公开 checkpoint 的独立重建评估与博客数字不是同一次运行。其模型卡报告 2,000 个 MATH 生成、约 4,340 万生成 token、H200 约 51 分钟；不能把它当成本轮复现。

### 2. WeightCode，2026-11-19

Bo Li 等，`arXiv:2611.25476`。核心对象是可复用程序 `W' = p(W, I)`，程序会重新测量当前权重和证据，而不是跨 checkpoint 复制固定 delta。固定架构中的 grammar/action 安装、图像偏移修复以及顺序编辑是其主要证据。

严格主实验允许统计与解析矩阵运算，禁止基于输出目标的梯度、有限差分优化和迭代标签拟合；部分探索性轨迹单独列出。对照匹配示例、外部 checks 和 retention 门槛，不能解读为总算力完全相同。程序发现耗时与 API 成本、程序重执行成本必须分别报告。

- [论文](https://arxiv.org/html/2611.25476v1)
- [官方代码](https://github.com/Gen-Verse/WeightCode)
- [官方数据与记录](https://huggingface.co/datasets/Boom5426/WeightCode)

本轮精确复现来自此源，身份与边界见上节。

不能省略同规则知识的训练结果：论文 Table 2 的 grammar-generated FT 在 add-primitive 达 99.6%、旧任务不变，改变 152,718 参数；WSP 为 99.8%、257 参数。around-right 上，FT 达 100.0%、旧任务 −0.1pp，WSP 为 89.6%、旧任务 −0.3pp。因此“65 行微调失败”不能概括为“训练无法达到 WSP 的质量”。这类 rule-to-data 训练会生成部分公开 test 命令，作者也明确没有称其为普通的 unseen-input supervised holdout。双方都拥有 grammar，应比较规则编译、改动规模、总成本及质量，而不是隐藏该训练对照。

### 3. Forward Weight-Space Programming / FWSP，2026-11-25

Lin Yao，`arXiv:2611.34612v1`；截至本次 11-28 搜索，最新核实的直接相关 primary preprint。不能把搜索未发现更晚论文解释为穷尽全部互联网。

四阶段为探查、定位、分层算子、配对验证/回滚。O1 是异常裁剪/行尺度，O2 是子空间投影，O3 是统计与时钟校准，O4 是 readout/ridge。O4 是用数据拟合参数，虽然不反向传播，仍有统计估计与优化成本。Protected FisherGate 用协方差白化并投影掉受保护子空间。保护只对测得子空间成立。

重要贡献是两类可修复性边界：失败与正常行为在同一可编辑子空间纠缠，以及目标超出冻结表示的线性 span。论文允许由定位结果转向局部 LoRA；这应明确记成需要梯度的升级路径。当前未在论文中核实到可直接复跑的官方完整代码仓库，报告的大模型成绩不能当作已独立证实。

- [论文](https://arxiv.org/html/2611.34612v1)
- [版本与提交时间](https://arxiv.org/abs/2611.34612)

### 4. Self-WSP，2026-11-21

Guoming Ling、Shanshan Zhong、Kaixuan Zhang、Zhongzhan Huang，`arXiv:2611.28833`。同一小模型执行任务并生成下一轮参数编辑，接口以张量目录与少量摘要为主。存在 tensor catalog 顺序偏置、机制解释不可靠、短校准批次改善在独立数据上退化等问题；随机搜索在部分任务可匹配效果。报告只选择最好轮次会隐藏停滞与失败。

- [论文](https://arxiv.org/html/2611.28833v1)

启发：Hepta Agent 必须有相同预算的随机/坐标/标量对照，记录每次拒绝候选与总成本；张量名称被打乱后是否仍能定位也是有效控制。

### 5. Just sort it!，2026-11-16

Matteo Fischetti，`arXiv:2611.21432`。分析已有线性规划 WSP 编辑，发现许多作用近似常量偏置；按统计量排序选少数神经元可接近 LP。不能把输出改善本身当成复杂电路已被理解的证据。

- [论文](https://arxiv.org/html/2611.21432v1)
- [代码、方向向量与协议](https://doi.org/10.5281/zenodo.24286137)
- [AHA 官方代码](https://github.com/Eppy-EpHard/AHA)
- [相关 LP 代码](https://github.com/nathanrs/weight-space-lp)

Hepta 应包含 bias-only、gain-only、temperature-only、head-only 对照；NDU 改善若只需固定偏移，就不应声称发现复杂状态电路。

### 6. WeightLoop，2026-11-05，修订 11-14

`arXiv:2611.07319v2`。LLM 制定有限参数编辑程序，数值执行器拟合残差并将结果写回原生权重，涵盖科学预测/估计任务。它把 LLM 规划与数值求解分开，适合具有解析结构的 Hepta。但“无全模型反传”不等于“不拟合数据”。

- [论文](https://arxiv.org/html/2611.07319v2)
- [官方代码](https://github.com/limengran98/WeightLoop)

### 7. HypoLoop，2026-11-18

`arXiv:2611.23718`。Agent 调整可编辑参数、目标、正则与约束，原生数值执行器使用原始非线性模型验证；并非一概无梯度。对 NDU 的适用点是目标与约束的显式规划，不是让语言模型直接猜数百万标量。

- [论文](https://arxiv.org/abs/2611.23718)
- [官方代码](https://github.com/limengran98/HypoLoop)

### 8. Exploring WSP: Capabilities, Generalization, and Limitations，2026-11-06

Junru Hu 等，`arXiv:2611.09382`。16 条编辑轨迹、两种规模、七类任务；六条轨迹最终保留原始权重。50 次 forward request 可各自包含多个问题、样本、原模型与编辑模型；不是等额 FLOPs。小模型与大模型的剩余提升空间很不同。

- [论文](https://arxiv.org/html/2611.09382v1)
- [项目仓库](https://github.com/WSP-Scope/WSP-Scope-Project)

本次浏览仓库只看到论文 PDF，不应宣称完整编辑代码与 checkpoint 已开放。

### 9. WSP Doesn't Need Transformers，2026-11-17

Hyunjong Ok、Jaeho Lee，`arXiv:2611.22055`。允许 LLM 设计被写入的模型后，它们倾向于用具有明确语义和局部影响的关联表，而不是密集 Transformer。不能从这种从头构造结果推出任意预训练网络可被同样轻易解释。代码发布了文本模型及构建器；部分测量/作图代码和大型编辑 checkpoint 未发布。

- [论文](https://arxiv.org/html/2611.22055v1)
- [官方代码](https://github.com/effl-lab/Weight-Space-Programming)

Hepta 的解析算子可提供语义明确的参数槽位，降低可写结构的歧义。连线改变与参数改变必须分别归因，即使参数数量不变。

### 10. 与边界有关的其他 primary sources

- [Replicating and Extending Weight-Space Programming: Frontier LLMs Compile Programs into Weights and Read Input Layers，Goworek 等，11-16，arXiv:2611.21449](https://arxiv.org/abs/2611.21449)：新游戏控制揭示先验/输入几何与完整规则理解之间的差别。
- [Same Fix, Different Weights: Replicating Weight-Space Programming with Claude，Kundu，11-16，arXiv:2611.20953](https://arxiv.org/abs/2611.20953)：输出行为调节可能经不同通路达到相似效果，改善不唯一标识原始机制。
- [Weight-Space Programming of Policies and Their Verification via Model Checking，Gross，11-08，arXiv:2611.11604](https://arxiv.org/abs/2611.11604)：神经策略编辑后的模型检查，可把形式化状态模型的性质与一般准确率分开。
- [PAW 作者方法说明](https://programasweights.com/research/weight-space-programming/)：由训练过的 compiler 一次生成 adapter 与通用 LLM 推理编辑不同；compiler 预训练成本不能省略。
- [WSP 写入 ICL 的论文，11-19，arXiv:2611.26841](https://arxiv.org/abs/2611.26841)：写入任务向量或稀疏门控并不自动产生鲁棒语言理解，提示改写和跨任务保护仍需评估。

### 11. 11-20 至 11-25 的补充原始研究

- [机器人 foundation model 的定向修复，Coelho 与 Solowjow，11-24](https://arxiv.org/abs/2611.31715)：将可识别失败状态映射为纠正动作，quiet-neuron 写入配合反向/随机控制；五项故障并非全部成功。实际 editor 为 Claude Opus 5.5。解析结构有助于构造纠正方向，但不保证任意闭环任务可修复。
- [粒子物理中的 WSP 与机械解释，Bonnet-Guerrini 等，11-20](https://arxiv.org/html/2611.27079v1)：已知物理不变量帮助定位非物理捷径。SAE 与 WSP 是不同路径；前者另外训练 SAE，不能将整条 SAE 管线称零训练。
- [Kolpona，Farazi 等，11-25](https://arxiv.org/html/2611.33973v1)：单神经元的 trigger/read/write 闭式编程与配对接受。4B 是替换已有低激活单元，27B 会追加零单元；后续部分评估被作者明确标记为 test-informed。weight-only 与多 agent 推理收益须分开。
- [IR-ODWSP，Wang，11-23](https://arxiv.org/abs/2611.29882)：以保持函数的展开/折叠构造可编辑坐标。这里只核实摘要与作者声明的代码链接 [ODWSP](https://github.com/WongKinYiu/ODWSP)，未完成官方代码执行，不把声明的成绩计入独立复现。

## REA 是什么，以及不能据其声称什么

[morluto/rea](https://github.com/morluto/rea) 是 Reverse Engineer Anything。其 [model-artifacts 文档](https://github.com/morluto/rea/blob/main/docs/model-artifacts.md) 明确说明，模型检查读取 GGUF/safetensors 的声明、尺寸和身份，不加载模型、不解释学习到的权重、不做 inference。默认 header hash 不是权重内容的承诺，完整权重身份须 full hash。不同量化类型版本可能有相同声明却不具备唯一存储解释，未知必须保留为未知。

HeptaRuntime 可以借鉴其证据模型与生命周期，但神经图解释、激活探查、优化算子、数值验证和事务回滚需要自己的实现。这些不是“接入 REA”即可自动获得。

## Hepta 的可修复性分层：独立推导与实验建议

以下是据方法与结构给出的推导，不是文献已替 Hepta 证明的事实。

### A. 先判定信息是否到达可编辑位置

如果存在两条历史 h、h'，冻结表示 φ(h)=φ(h')，但正确动作或价值目标不同，任何只接收 φ 的确定性 readout 都无法区分。平衡交换配对的二分类任务上，它至多答对一半。这比“head fit 不收敛”更强。

如果计算图从当前报价/Reset flag/历史事件到目标 score 根本没有路径，任何原图权重都不能修复该信息缺失。添加 tied bridge 可能不增加注册参数数目，却改变了函数族，必须单列结构修复臂。比较应包括：原图、bridge-only、同 bridge 上解析编辑、同 bridge 上预算匹配随机搜索、同 bridge 上 Adam。

### B. 然后判定冻结表示的线性可达性

设 Φ 为 n×d 冻结特征矩阵、Z=[Φ,1]，Y* 为目标矩阵。任意 affine head 的最小平方误差为：

`min_B || ZB - Y* ||_F² = || (I - P_Z)Y* ||_F²`。

这个量证明特定样本上的不可达部分，但训练残差为零不证明泛化。如果 n≤d+1 且 Z 满行秩，任意标签都可插值。必须报告 n/d、SVD 阈值、有效秩、条件数，并在按轨迹/市场 regime 分组的独立集合上 cross-fit 验证。不要把随机打散高度相关 ticks 当作独立样本。

### C. 六个模块各自需要的证据

| 模块 | 先排除的失败 | 可能的解析/稀疏权重编辑 | 必要保护 |
|---|---|---|---|
| 状态表示 | 缺失输入路径、历史别名、单位或尺度错误 | 有语义槽位的 affine 校准、受保护子空间投影、已知映射写入 | 新旧信息可达性、重载 parity、跨 regime 状态探查 |
| First-Passage/Reset | 首次事件与重复越界混淆、存活质量遗漏、reset 时钟错误 | 已证明参数化允许时的门阈值/尺度/时钟修复 | first-hit 顺序、概率质量、reset 前后状态一致 |
| Call/Put 双通道 | 通道交换、方向符号、合并导致反向证据抵消 | 具备适用数学假设时的对称/反对称投影 | 逐通道、镜像输入、censoring 与“未命中”质量；不无条件强加 Call+Put=1 |
| Belief | 先验与后验时点混用、遗忘/归一化错误、不可观测历史 | 受 simplex/正性约束的校准或有标签 closed-form fit | 概率校准、序列更新、尾部事件与变化 regime |
| Continuation Q | 一步代理损失改善但真实递归误差放大 | 解析 Bellman teacher 的低秩/读出修正 | 真正递归 rollout、horizon、reset 后续值、动作 margin |
| NDU 价值控制 | proxy MSE 与全局目标错位、占用分布变化、风险预算未入 state | 对决策关键残差加权的约束求解 | 原始 NDU 全局目标、相同轨迹随机数、尾部/成本/旧行为门槛 |

### D. Continuation Q 的数学保护必须有适用条件

若原 Bellman 算子在 sup norm 下是 γ<1 的压缩，可用 `||Qhat-Q*||∞ ≤ ||Qhat-TQhat||∞/(1−γ)` 约束残差与价值误差。若目标非加性、风险预算未进状态、reset 映射不一致或 continuation 用错时点，这个界不能直接应用。先确定真实算子与部署递归，再定位残差，避免修好代理模型却恶化最终闭环。

局部拟合应给决策边界和真实占用分布足够权重；平均 MSE 下降可能没有改变任何动作，或者改变少数最昂贵的动作。最终接受条件必须是原始 NDU 目标和 retention，而不是中间 head loss。

## 原生 Rust 子系统的研究接口建议

无需把整套 Python 编辑脚本直接带进可信运行时。Agent 提供可验证的 plan；Rust 执行固定、有限、可追溯的算子。

1. **Artifact identity**：完整 checkpoint hash、架构/配置/输入 schema/归一化/backend/量化身份。缓存激活必须绑定这些身份。
2. **Graph semantics**：参数路径、矩阵朝向、共享/tied 参数、值域/单位、依赖图和无路径证明；“tensor 名看起来像”不能代替数据路径。
3. **Evidence**：数值观察、因果消融、数学推导、待验证假说分别记录。给每个结论实际 probe 样本 hash 和测量范围。
4. **Plan**：编辑范围、预算、数学假设、预期变化、保护集合、验证协议及失败条件；有限算子如 row replacement、low-rank add、projection、affine recalibration、constrained ridge。
5. **Transactional edit**：copy-on-write candidate，有限性/形状/范数/支持/tie 约束；从原始字节恢复，不能依靠浮点减 delta 实现逐位回滚。事务还必须绑定并恢复 graph、route 与 evaluator phase；仅恢复权重不能撤销已变化的信息路径。
6. **Validation**：重新加载后的真实 forward、Python/Rust/CUDA/Metal 后端 parity、解析不变量、配对 validation、原始全局目标与独立最终评估。
7. **Search accounting**：完整记录所有候选，包括被拒绝、超时、无改善和回滚。计划预算、实际 sample-forward、生成 token、梯度步数、矩阵求解和 wall time 分开记。

闭环能自主规划和回滚，不代表能证明“最优权重修改”。最优性必须相对于明确定义的可编辑集合、目标、约束和求解器证书；一般非线性网络全局最优性不能由 Agent 的自然语言声称建立。

## 什么算闭合、什么仍然不能宣称

- 官方小模型的冻结程序重执行可以闭合“程序与权重确实能产生所报行为”的复现项。
- 相同 child SHA 和公开 heldout 分数不能闭合“独立 GPT 已从头发现方法”“真正未见数据泛化”或“交易收益改善”。
- 图无路径与状态别名可闭合“原图纯权重编辑是否可能”的诊断，结论可能是不可达；这时应修复信息路径，而不是继续扫同一参数空间。
- 验证门、回滚与构建测试通过可以闭合运行时工程项；真实 checkpoint 的端到端收益仍需真实输入、完整前向和匹配预算对照。
- 解析正确是约束和诊断优势，不是全局收益证明。只有在相同轨迹、相同成本、独立最终数据上改善原始 NDU 目标，才闭合业务质量项。
