# 原始 V6 冻结生成器：有限真实输出空间与强基线

本补充实验直接恢复并冻结 **full-002 的原 seed 17、terminal_entropic_ndu 生成器及其内容 gate**。没有重训，也没有将 ABC/V7 模型改称 V6。64 对此前未打开的来源上，真实枚举显示仍存在有限动作空间的质量余量；原动态控制器相对新选强固定策略的收益，区间仍包含零。事后 oracle 使用私有真值，其结果不能当作已实现的可行策略收益。

## 1. 原模型身份与恢复链

原完整证据包 `ndu_v6_full002_evidence.tar.gz` 为 62,166,608 bytes，SHA256 为 `ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e`。从中读取模型、forecast、两个 observer、training/forecast/observer/protocol 记录，分别核对历史文件摘要。

| 对象 | SHA256 |
|---|---|
| 原生成器文件（含 base + gate） | `8fa76a13cdeee48e41b84e29211659a065d9573e2fdfecc4281f882248b508b6` |
| 原 base 参数 | `3bdb3955667243563b8d3ffeb767b58c6d74b858933a349fa1befe18db7cfaff` |
| 原 gate 参数 | `b5b49221fa930df8f3999f0a432d92efe084645ebfb1eb0485eb27bfde100167` |
| 原组合 fingerprint | `e3a4a72e61925b95a5eee3c7db8a25fbef6450051dc84f736fcd33d6240ae022` |
| 原 forecast 文件 | `6c058399c0f66a21af873a80a554fd78b1017db97bd74344705fb5bd3cab1cae` |
| 原 reward observer 文件 | `a9cfe78a08b9192ba9d8fe9c144de29ef5d3b1e9cd6ed236d01d170d32034210` |
| 原 audit observer 文件 | `cd560d4ec2f45cef6a0f4db9809b902ea68833c8693798f7597135a83a6e3589` |

`ControlledSnapshot.load` 进一步核对 base、gate、配置与组合摘要；它们与原 `training.json` 的内部记录相等。关键生成、控制、forecast、observer 源文件与原提交逐字节相同。现行 `v6/run.py` 增加过来源收集范围；从原提交 `b98961ceb71414490e1c6ae397cf635bca3093f4` 读取的 `run.py` 经原摘要验证后，确认本次调用的 `rollout` 函数源码逐字节相同。完整身份见 [ORIGINAL_IDENTITY.json](ORIGINAL_IDENTITY.json)。

本次推理使用一个 CPU 线程。原训练曾用两个线程，但本次没有重跑训练，参数身份不依赖重新训练的数值复现。只有 **一个历史训练 seed**，不能解释成三个或五个独立生成器实验。

## 2. 三个清晰分开的动作空间

保留原 gate 的两步初始计划，再允许最多三步继续动作。提前停止对应每个前缀的实际终端输出。

| 空间 | 初态 | 允许继续动作 | 实际端点数 |
|---|---|---|---:|
| full | 原内容 gate 执行两步后的状态 | semantic、image、text、couple | 1 + 4 + 16 + 64 = 85 |
| common-initial allocation | 与 full **同一个** gate 后状态 | image、text | full 的 15 个端点子集 |
| historical allocation | 原 `content_control=False`：固定 image、text 两步初始计划 | image、text | 独立 15 个端点 |

common-initial allocation 直接复用 full 树的对应端点，不额外生成、不新增样本数。historical allocation 改变初始计划，不能单独用来识别继续动作空间的效应。full 与 common-initial allocation 的 oracle 比较才严格控制了初态。

每组使用同一个实际 encoder 初始噪声，所有动作共享该初态。V6 的后续状态转移是确定性的，图像为 decoder 输出的灰度 PNG，文字为原始自回归 greedy 输出。这里没有新增未来随机转移，也没有把该实验称为一般随机 FBSDE 求解。

## 3. 先选策略、后开新来源

强固定策略在旧 V6 validation 的独立补充 dev 范围 `[256,320)` 选择；原 forecast 的 fit/calibration/dev 合计使用 `[0,256)`。本次 dev 为 64 对、每对两个初始噪声，只用原 reward observer。候选包含 full 全部 85 序列、common-initial allocation 15 序列、historical allocation 15 序列。每个空间分别最大化经验均值与 gamma = 2 的 entropic CE，目标均为实际输出效用减 `0.002 × 继续步数`。选中的全部路径和候选分数保存在 [DEVELOPMENT_SELECTION.json](DEVELOPMENT_SELECTION.json)。

同时直接复用原已冻结的 `fixed_dev_tuned`、`risk_neutral_mpc`、`risk_aware_recursive`、`allocation_only`。原 fixed 路径为 `semantic → image → text`；动态控制保留原 horizon 2 的滚动规划、最大实际继续 horizon 3、work budget 64 与 search limit 32。

新来源通过补充 allocator 独占登记，为原 `unallocated_train` 的对索引 `[736,800)`；最终协议先冻结 56 个源码、模型和 selection 文件摘要，再由 loader 放行。协议 SHA256 为 `348a20f4aac75979d3a49e7592e8ac6babdefed3b85cae13009dbd04867110ad`。没有根据新来源的结果重新选策略。

64 对来源共 128 张不同原图。每对只分配一种 corruption，两个独立初始噪声；clean、occlusion、missing、heavy_noise 各 11 对，wrong_hint、missing_no_hint 各 10 对。**不是把六种视图重复算成 384 对独立来源。** 新评估只用原 audit observer；其分数仍是此构造域的代理评价，不是人工认证语义。

## 4. 实际执行和检验

新评估完成 12,800 个终端输出，即 `64 × 2 × (85 + 15)`；10 个可行策略各执行 128 次，共 1,280 次独立策略请求。每个输出都写入 PNG 和 UTF-8 文本、回读后评分，未修正文案或图像。每个可行策略的媒体摘要、评分和最终状态，均与其枚举端点精确相同；全部 **1,280 / 1,280** 通过。分析再次核验全部 **28,160** 个新媒体文件摘要，并核对数值表与逐行实际评分一致。

在打开新来源前，还用一个旧 dev case 将 100 个树端点分别从根重新执行，媒体与状态均精确相同。私有 Target 不能进入公共生成接口，historical allocation 不能执行共享语义动作，篡改 gate 参数会被完整性检查拒绝。见 [CHECKS.json](CHECKS.json)。这些旧 dev 检查不计入新来源 N。

整个新收集阶段 wall 为 67.958 秒，CPU 为 67.897 秒，进程峰值 RSS 为 431,325,184 bytes。它包括枚举和 1,280 次可行策略运行，不是单次在线延迟。轮换策略执行顺序后，实测包含序列化和 observer 的平均请求耗时：strong fixed CE 14.094 ms、原 fixed 27.242 ms、risk-neutral 50.099 ms、risk-aware 51.768 ms。这些是本机本次描述性测量；oracle 的枚举耗时没有伪装成可行策略成本。

## 5. 结果

原效用为 `U = 1 − 2 × joint_loss`，数值越大越好。下表 CE 为 `−log E[exp(−2U)] / 2`，对新 64 对来源与各两个噪声的经验分布计算。所有策略在同一来源与噪声上配对。

| 已冻结可行策略 | 原始效用 CE | 扣继续步数惩罚的 CE |
|---|---:|---:|
| 强 fixed，dev CE 选择 | 0.365756 | 0.359756 |
| 强 fixed，dev 均值选择 | 0.376891 | 0.372891 |
| 同初态 allocation，dev CE 选择 | 0.371795 | 0.365795 |
| 同初态 allocation，dev 均值选择 | 0.376891 | 0.372891 |
| 原 allocation 初态，dev CE 选择 | 0.390846 | 0.384846 |
| 原 allocation 初态，dev 均值选择 | 0.376561 | 0.372561 |
| 原 fixed_dev_tuned | 0.374977 | 0.368977 |
| 原 risk-neutral MPC | 0.383562 | 0.379508 |
| 原 risk-aware recursive | 0.383558 | 0.379031 |
| 原 allocation_only 动态策略 | 0.381411 | 0.378346 |

强固定策略的“强”指 dev 上遍历完整候选空间，不保证跨来源泛化后仍最好。不能在看到上表后改选测试集最优行并声称是事先冻结的策略。

| 有限私有真值上界 | 原始效用 oracle CE |
|---|---:|
| full，85 个端点 | 0.434379 |
| 同初态 allocation，15 个端点 | 0.406692 |
| 原 allocation 初态，15 个端点 | 0.399584 |

每个 oracle 在事后读取该组所有真实输出的 audit 分数，再选择最好端点。它允许窥见私有真值，且未计枚举、搜索、observer 成本，只是这棵有限树的上界。另行按 `U − 0.002 × 继续步数` 选择的 full oracle，其该目标 CE 为 0.433946，平均继续深度 0.21875；这同样不能称为可部署决策。

以来源对为 bootstrap cluster，两个噪声及所有策略保持配对，做 2,000 次重采样。以下为未作多重比较校正的描述性 95% 区间，条件于这一历史生成器：

| 原始 CE 对比 | 差值 | 95% 区间 |
|---|---:|---|
| risk-aware − 强 fixed CE | +0.017803 | [−0.031643, +0.063450] |
| 强 fixed CE − 同初态 allocation CE | −0.006039 | [−0.058990, +0.051734] |
| full oracle − 强 fixed CE | +0.068624 | [+0.036295, +0.107791] |
| full oracle − risk-aware | +0.050821 | [+0.021408, +0.089882] |
| full oracle − 同初态 allocation oracle | +0.027687 | [+0.007505, +0.056300] |

因此，该历史模型的真实有限输出树中还有可选择的质量余量，且共享语义动作在相同初态下扩展了事后可达到的集合。**现有公开信息控制器仍未证明把这部分上界转化为可靠的动态收益**：risk-aware 相对强 fixed 的区间包含零，risk-aware 与 risk-neutral 的点估计也近乎相等。下一步应检验可观测状态对这些高价值动作的可预测性；不能从 oracle 差距直接推出存在可实现的最优策略。

## 6. 证据与复现边界

[RESULTS.json](RESULTS.json) 保存完整数值、路径计数、成本和区间；[PROTOCOL.json](PROTOCOL.json) 保存打开新来源前的冻结登记。`RAW_EVIDENCE.tar.gz` 包含原模型/observer/forecast 与原记录、旧 dev 全端点、一次新收集全部媒体与逐行评分、独立重放、执行源码快照。摘要与成员核验见 `RAW_MANIFEST.json`。

历史登记保留原绝对路径。其他环境复制文件时应建立新的复现登记并核对原始 SHA，不得原地改写本次已执行的协议。MNIST 缓存按原协议的四个公开归档 SHA 读取；本补充没有改变数据、动作成本或原 owner 资格门槛。它不证明音频/视频能力、跨训练 seed 稳定性、一般 NDU/FBSDE 全局最优或生产准入。
