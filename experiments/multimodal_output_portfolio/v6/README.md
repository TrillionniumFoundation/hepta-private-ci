# NDU v6：真实手写源图像上的联合生成与动态控制原型

这是**有界领域的研究实现**：输入真实 MNIST 手写图像及公开文字提示，生成实际自回归文字和神经像素图像，并比较训练目标与推理控制。配对、遮挡和任务说明是人为构造的 benchmark；它不代表自然场景的通用全模态能力。本页说明实现、重现方法与证据范围，尚不记录正式实验的优劣结论。

## 1. 模块与实际输出

| 模块 | 责任 |
| --- | --- |
| [data.py](data.py) | 原始源文件校验、像素身份去重、独立 split、输入与真值分离 |
| [neural.py](neural.py) | 共享 encoder、可训练状态更新、像素 decoder、自回归文字 decoder、冻结快照 |
| [plan_training.py](plan_training.py) | 对真实输出评分后训练内部内容计划 gate，推理时执行选定计划 |
| [forecast.py](forecast.py) | 独立分区拟合效用预测、残差校准、路由及固定序列基线 |
| [control.py](control.py) | 有限前瞻、条件 entropic 估值、停止与实际搜索工作记账 |
| [observer.py](observer.py) | 冻结 OCR、严格 caption 解析、PNG/UTF-8 原始输出回读 |
| [run.py](run.py)、[reporting.py](reporting.py) | 冻结协议、完整样本清单、配对统计、原生 receipt 接口 |

encoder 的共享 context 保留输入条件；初始 latent 噪声有显式 seed。四个控制动作是 `refine_semantic`、`refine_image`、`refine_text`、`couple`。前者和最后者可改变共享语义状态；纯 image/text 动作只推进相应生成状态。输出为 56×28 灰度 PNG 和 UTF-8 caption，例如 `left 3 right 5 relation less`。坏语法和错误数字原样进入评分，不进行模板修复。

模态传输 schema 保留 `text=1`、`image=2`、`audio=4`、`video=8`。当前必需 mask 为 `3`，只有 text 与 image 两种神经 decoder。音频/视频的 schema 位不代表相应能力已经实现。

## 2. 数据来源、公开信息与两个 observer

MNIST gzip 来自 [PyTorch 的 MNIST 镜像](https://ossci-datasets.s3.amazonaws.com/mnist/)，按 torchvision 使用的已发表 MD5 校验；运行 manifest 另存原 URL、SHA256、字节数和 split 身份哈希。split 先按完整源像素 SHA256 去重，排除相同像素的标签冲突，并从训练派生池排除官方 test 中出现的像素身份。

当前协议的源池如下；数字为源图像数，不是独立训练重复数。

| 源池 | 数量 | 用途 |
| --- | ---: | --- |
| `train` | 10,000 | 基础生成器及内容计划 gate 训练 |
| `validation` | 2,000 | forecast fit/calibration/dev 三个源不交叠的子分区 |
| `evaluator` | 10,000 | 等分为 reward 与 audit 两个源不交叠池 |
| `retention` | 1,000 | 保留的干净域评估源，未用于训练或调参 |
| `test` | 2,000 | 官方 MNIST test 的保留源；运行记录称为 `future` |

`Observation` 只包含公开像素、缺失 mask 与文字 token。`Target` 的完整像素和标签仅用于训练或执行后的评分。源图像完全缺失的一侧可获得明确的公开类别提示；该提示不包含原始笔迹。错误提示与移除提示有单独测试分层。

reward observer 使用自己源池的前 80% 训练、后 20% 校准，seed 为 `314159`。audit observer 在另一个源池独立训练和校准，seed 为 `161803`。两者参数、训练源、校准源及权重文件身份分离；只有 reward observer 给 plan/forecast 产生训练标签，最终报告由 audit observer 对实际落盘字节评分。audit 参数不进入训练或控制路径。

两者仍是同一领域、同类架构、同一主机上的有限 OCR 模型。源与参数分离不构成人类真值、外部机构独立性或可信硬件证明。各自的保留源准确率必须随报告读取。

`future` 只是保留源 split 名称，没有真实时间外推含义。`retention` 是干净域保留性能评估；此处没有连续学习后的参数漂移流程，因此其分数不能直接解释为灾难性遗忘实验。

## 3. 两阶段训练及其准确数学范围

### 基础生成器预训练

两种 profile 使用相同初始化、批次、latent 噪声场景、控制序列和优化步数。基础 terminal surrogate 为：

\[
L=\mathrm{pixel\ BCE}+0.5\,\mathrm{teacher\ forced\ text\ CE}
+0.15\,\mathrm{digit\ CE}.
\]

`supervised` 对同一输入的场景取均值；`terminal_entropic_ndu` 对损失使用 `logmeanexp(γL)/γ`。这是实际梯度训练，但文字部分仍是 teacher-forced surrogate。报告明确标记该阶段没有直接优化独立的实际离散输出评分。

### 真实输出上的内容计划训练

冻结基础生成器后，每个训练输入枚举四个两步计划和两个共同 latent-noise 场景。每条路径执行真实神经控制、实际自回归 caption 生成、PNG 编码/解码与 UTF-8 回读，再由固定 reward observer 对训练真值评分。效用为固定 joint metric 下的 `R=1−2×joint_loss`。

gate 只读未加 latent 噪声的共享 encoder context，因此同一观察的各场景共用一个条件计划分布。对已观察且 detach 的 `R[i,p,k]`，NDU 阶段最小化：

\[
\ell_i(\omega)=\frac1\gamma\log\left[
\frac1K\sum_{p,k}\pi_\omega(p\mid C_i)e^{-\gamma R_{i,p,k}}\right].
\]

这是对声明的有限 plan/scenario 分布求精确梯度；reward、observer 与评分尺度均不被优化。监督对照以经验平均效用最好的计划为标签训练 gate。两者枚举量、gate 初始化和更新序列一致。报告保留实际效用表、参数哈希、梯度、目标历史及所有候选评分成本。

部署选择 gate 的确定性 `argmax`；报告分别列出随机混合策略目标与部署选择的效用。两个 latent 噪声场景是有限经验风险 profile，不能据此声称真实世界条件风险已校准。

当前训练轴同时改变基础 surrogate 的风险聚合与计划 gate 的训练目标；2×2 对照不单独识别这两项训练贡献。一般内生偏好 `P`、非线性 `f(U,Z)` 的完整 FBSDE 仍遵循仓库的[控制规范](../../../docs/learning/NDU_FBSDE_SPEC.md)，本原型没有实现或证明该一般系统。

## 4. 推理对照、真正的 allocation 消融与协议

每次推理冻结模型、gate、forecast、metric 身份。控制器只接收公开状态及经过分区拟合的预测；执行后的 audit 真值不回流到同一推理的动作选择。候选前瞻调用真实神经 transition，并记录这些未被最终选中的计算。

| Policy | 作用 |
| --- | --- |
| `fixed` | 预设动作序列 |
| `fixed_dev_tuned` | 在独立 dev 源上选择固定序列，包括空序列及提前停止的前缀 |
| `learned_router` | 以离线动作收益监督训练的 hard top-1 路由基线 |
| `greedy` | 单步、风险中性的估值选择 |
| `risk_neutral_mpc` | 多步前瞻，`γ=0` |
| `risk_aware_recursive` | 多步条件 entropic 前瞻与停止 |
| `allocation_only` | 禁用全部共享语义控制，仅推进固定的 image/text 生成过程 |

前六种 policy 的 encoder 后都会执行学得的两步内容计划。`allocation_only` 从初始化就绕过 gate，固定执行 image→text，记为 `plan_index=-1`；后续也只允许这两种动作。共享 `h` 在整个路径保持原初值，直接调用 semantic/couple 会被拒绝。forecast 的拟合与校准覆盖两种初始化 profile。

`learned_router` 是四个独立 latent-update experts 上的有界 hard top-1 MoE，共享 encoder 与输出 heads。其 gate 使用离线动作收益监督；这里没有独立的 token-level MoE 大模型或通用 MoE 优势结论。

forecast 的效用预测有两个公开效用分层的源平衡残差 profile，支持不足时回退全局 profile。保留数据上的覆盖率是经验诊断，不是条件覆盖保证。`search_complete=false`、预算停止和有限候选集合必须保留，不能解释为无限动作空间的全局最优解。

主 2×2 对照定义：

| | 固定 dev 调优推理 S | NDU 动态推理 N |
| --- | --- | --- |
| 监督训练 S | S/S | S/N |
| NDU 训练 N | N/S | N/N |

这里 S 推理轴指初始化后的固定控制序列；其初始化仍使用同一冻结模型的内容 gate。因此推理对照识别的是后续动态控制的增量。

[protocol.json](protocol.json) 当前登记 seeds `17,29,43`；两种训练；七种 policy；预算 `64,128`。基础训练为 400 steps、batch 64、hidden 96；计划训练 128 对输入、120 steps；forecast fit/calibration/dev 为 128/64/64 对；每个 observer 300 steps。最终推理最多追加三步，搜索 horizon 为二，`γ=2`，动作效用成本为 `0.002`。

搜索上限为 32 工作单位，`search_fraction=0.5`。64 单位预算的初始完整深度二四动作树需要 25.25 搜索单位，能够纳入初次搜索配额；后续仍可能预算截断，须按每次 decision 的完成标志解释。

每个 seed/profile/policy/budget 重放同样的 60 个 `future` 与 30 个 clean `retention` case；不同 case 的原始源不复用。future 按 `clean`、`occlusion`、`missing`、`heavy_noise`、`wrong_hint`、`missing_no_hint` 六层循环登记。完整协议预期 **7,560 条**结果；这是清单大小，不是已经完成的结果声明。

统计先计算每个训练 seed 的均值与经验最坏 10% loss，再跨 seed 汇总。2×2 interaction、强基线配对差、corruption 分层、实际延迟和工作量均保留。只有三个训练 seed；同一 case 的重复 policy 行不能当作独立训练重复。条件 Hoeffding 区间依赖原始 case 独立抽样假设，也不覆盖训练 seed 的不确定性。当前汇总器不发布确认性优势判定。

## 5. 预算、延迟与原生 V2 receipt

声明的工作单位：encoder 为 1、初始两步计划为 2、启用 gate 为 1、每次 neural transition 为 1、forecast 为 0.25、最终联合 decode 为 2、执行后图像观察为 2。allocation-only 的初始成本为 3，其余为 4；最终 decode 与观察预留 4。搜索、路由和未被选中的前瞻工作也收费。

这些单位是实验记账尺度，不能转换成 FLOPs、纳焦耳或硬件时间。两档预算比较的是相同上限，各 policy 的实际消耗可以不同。报告另存真实 wall/CPU 时间及 encode/controller/execute/decode/observer 分项；最终 wall 包含输出落盘、回读和评分。训练枚举、observer 训练、gate/forecast 训练及 native adapter 的时间另列。能耗当前没有测量，记录为 unavailable。

原生接口位于 [generation_rollout.rs](../../../codex-rs/hepta-ndu/src/generation_rollout.rs) 与 [ndu-generation-rollout](../../../codex-rs/hepta-ndu/src/bin/ndu-generation-rollout.rs)。传输为 `hepta.ndu.generation-rollout.v1`，实际调用 `evaluate_candidates_with_policy`，内部产生 `NduEvaluationReceiptV2`，并保留 `evaluation_digest_v2`。

它对**已经完成并评分**的同一 episode/snapshot 下各 policy 做事后可行性与 advisory 比较。它没有参与在线神经动作选择，也不执行 encoder/decoder。一个 joint rollout 只贡献一次完整成本，文字与图像不会各自重复记总延迟。native risk 字段采用已知 normalized-loss 上界 1；它不是失败概率、协方差估计或把未知风险填为 0。

传输绑定 objective、source bundle、model snapshot、episode、metric、预算及逐候选支持摘要。必须具有 literal `abstain` 零效果候选；选择 abstain 不能算完成必需的双模态输出。返回值明确为 `observation_attestation_verified=false`、`production_authority=false`、`DENY_ALL`。本地哈希与真实 Rust 调用不构成外部真值认证或生产 owner 生命周期闭环。

## 6. 重现

在仓库根目录使用独立环境。当前依赖由 [requirements.txt](requirements.txt) 固定；实现使用 Python 3.12 与 CPU PyTorch，不需要 GPU。

```bash
python3.12 -m venv /tmp/ndu-v6-env
/tmp/ndu-v6-env/bin/python -m pip install -r experiments/multimodal_output_portfolio/v6/requirements.txt
/tmp/ndu-v6-env/bin/python -m unittest \
  experiments.multimodal_output_portfolio.v6.data_tests \
  experiments.multimodal_output_portfolio.v6.neural_tests \
  experiments.multimodal_output_portfolio.v6.plan_training_tests \
  experiments.multimodal_output_portfolio.v6.test_control \
  experiments.multimodal_output_portfolio.v6.test_forecast \
  experiments.multimodal_output_portfolio.v6.test_reporting \
  experiments.multimodal_output_portfolio.v6.run_tests -v
```

首次运行会下载校验后的 MNIST 文件到独立 cache；数据、模型权重及原始输出不应提交为代码。

```bash
/tmp/ndu-v6-env/bin/python -m experiments.multimodal_output_portfolio.v6.run \
  --cache /tmp/ndu-v6-data --output /tmp/ndu-v6-smoke-001 --smoke
```

smoke 会缩减训练、源 case 和预算，mode 为 `mechanism_smoke_only`，只能检验执行机制。正式实验使用新的输出目录，不传 `--smoke`：

```bash
CARGO_TARGET_DIR=/tmp/ndu-v6-target cargo build --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-ndu --bin ndu-generation-rollout
just test -p codex-hepta-ndu
/tmp/ndu-v6-env/bin/python -m experiments.multimodal_output_portfolio.v6.run \
  --protocol experiments/multimodal_output_portfolio/v6/protocol.json \
  --cache /tmp/ndu-v6-data --output /tmp/ndu-v6-full-001 \
  --native-binary /tmp/ndu-v6-target/debug/ndu-generation-rollout
```

输出目录必须不存在；失败或部分完成目录保留原状。省略 `--native-binary` 不会产生原生 receipt，不能声称完成了这部分核验。修改协议后应使用新目录，并以运行时冻结的协议判断适用范围。

## 7. 证据身份与完成标准

| 文件 | 内容与核验范围 |
| --- | --- |
| `protocol.json` | 运行前冻结的配置、完整 case/source 清单、metric、数据 manifest、源码哈希、native binary 哈希 |
| `status.json` | `running`、`failed` 或 `completed`；失败保留行数和 traceback |
| `observer.json`、两个 observer `.pt` | 独立源池、校准结果及权重文件身份 |
| `training.json`、各模型 `.pt` | 基础 surrogate 与真实输出 plan 训练分开记录；冻结 base+gate |
| `forecast.json`、各 forecast `.pt` | 拟合/校准/dev 分区、成本、残差支持和预测身份 |
| `outputs/*/caption.txt`、`image.png` | 未修复的实际输出字节 |
| `rows.jsonl` | case、snapshot、forecast、observer 身份，动作、成本、raw-output SHA256 与行 receipt |
| `native-receipts.jsonl/json` | 可选的原生事后 advisory；含二进制身份和 adapter 时间 |
| `summary.json` | 完整清单核验、配对结果、分 seed 统计、运行环境与科学范围 |

源码身份包含 `git_commit`、`dirty`、逐文件 SHA256 和 bundle SHA256。存在未提交改动时，commit 不能单独代表本次执行源。运行结束会重新核对源码文件；更改源码不能悄悄归入既有结果。

汇总器要求全部登记组合、唯一原始源 case、相同配对 snapshot/observer、完整成本，以及能够回读且哈希匹配的原始输出。缺行、改分、替换字节、变更身份或超预算都会拒绝。SHA256 是完整性绑定，不是签名或外部认证；`completed` 说明该协议执行和清单完成，并不表示研究假设、性能优势或所有科学 blocker 已闭合。

## 8. 历史负面证据与未完成范围

历史资料保留在固定提交，v6 不覆盖或重解释它们：

- [v5 有限模型的预算/数值修复 `df2b8165`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/df2b8165dd7e7ac8488d1eec73ecaede148dae20/experiments/multimodal_output_portfolio/v5)，原分支 `fix/ndu-v5-fresh-root-budget-custody-20261023`。
- [v5 learned factorial `d98229a0`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d98229a03150fb598082c32b206bc22aeb6695ce/experiments/multimodal_output_portfolio/v5)。
- [独立事后 credit/tail audit `92e1b091`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/92e1b0913226d46be0f39abda5d52c5c80224c2d/experiments/multimodal_output_portfolio/v5/FACTORIAL_CREDIT_AUDIT.md)：N/N−S/S 的平均 loss 为 −0.2408854167，但 CVaR90 为 +0.0520833333，seed 29 的均值恶化 +0.203125；所有 N/N `refine_rate=0`，差异主要来自付费 QUERY，实际 modeled cost 也不相等。该 audit 明确维持 `HOLD_NO_GO`。

这些数值使用 v5 合成任务的自身 loss 量纲，不能与 v6 分数直接横比。历史测试和重放入口仍以对应冻结提交为准，v6 测试不替代其负面证据合同。

v6 用真实源、实际神经输出、真实内容控制、两套 observer、完整成本与更强对照回应这些缺口。是否改进均值、尾部、clean-retention 或成本，只能由新的完整运行报告判断。

以下仍未完成：神经音频/视频 decoder、自然全模态大模型、一般 NDU FBSDE、无限策略空间全局最优证明、真实用户或外部认证终端效用、生产 Hepta neuron owner 执行与持久化/权限生命周期、能耗测量，以及足以支持总体训练 seed 推断的大规模实验。四模态 schema、通过接口测试或获得 V2 receipt 均不自动关闭这些项目。
