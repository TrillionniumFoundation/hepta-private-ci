# HCSN 独立群体小网络：研究实现与复现协议

本目录研究 **8、32、64 个独立物理群体**如何经连续边界/事件通量组成可训练网络，以及同一冻结表示上的五种 readout 适配方法。它接续上游 `hcsn_adaptive`、`hcsn_network` 的有限群体研究，不重跑原 PenDigits、169 配置、N256 或 HPCA 的封存实验。

**正式配置已确定，本文尚未填入正式训练或适配结果。** 使用原始特征 `feature_normalization=none`，N=8/32 采用 dense，N=64 采用 uniformized，每个 fit 最多512次更新、180优化 CPU 秒；不再以前测选优。源文件、参数、运行环境和选模证据均须绑定到冻结 manifest，不能把可编辑的 `protocol.json` 当成已完成实验。

## 1. N 的含义、拓扑与完整状态

`SmallHCSN` 输入为 `[time,batch,6]`。每个样本的每个神经元有自己的概率分布、signed mark、边界、漂移、成本与消息；N 不是内容通道数，也不是空间网格数。

| 对象 | 默认结构与语义 |
| --- | --- |
| 前 N/2 个 sender | 接收原始输入；可读取 sender 的上一拍消息 |
| 后 N/2 个 receiver | 不直接读取原始输入；可读取全部神经元的上一拍消息 |
| 连接约束 | 屏蔽 receiver→sender；保留组内递归与 sender→receiver |
| 每个群体 | 6 个 active 格、3 个 Erlang phase、1 个保留的 upper account |
| density | `[B,N,2,10]`；两个通道分别是概率质量与有符号内容质量 |
| 消息 | `[B,3,N]`：边界、区间 event count/dt、signed event mass/dt |
| readout | 只读 receiver 的五个特征，总维度 `5*N/2`，输出二分类 logits |

每个群体各自守恒为 1；消息不是把一个群体的概率复制给另一个群体。所有耦合都读 **OLD message**，本拍的 sender 输入至少下一拍才影响 receiver。屏蔽的 recurrent 参数槽仍存在，不能把参数张量总数自动当成有效自由参数数。

`PopulationState` 保存 density、boundary、drift、cost、message、绝对 step 和配置。配置、形状、dtype/device、控制域及概率/mark 界限在续算前检查。forward 状态不保存过去的 autograd tape；恢复训练还需要模型、优化器、RNG、数据游标和源身份。

## 2. 一步实际推进与输入语义

每步先由输入与旧消息计算 drive/mark。默认仅在 `step % slow_every == 0`（`slow_every=2`）时更新漂移、成本和边界；其余步骤沿用完整状态中的旧 law。law 在本区间内冻结。

新旧边界不同时，按 piecewise-uniform active density 的重叠保守重映射：落到新下界以下的质量进入 phase 0，超出有限上界的质量并回最后一个 active 格。这里采用有限格反射上边界，不是无限半直线的精确实现。

随后仅对 active signed content 写入：

```text
m_new = (1-write_fraction) * m_old + write_fraction * tanh(raw_mark) * p_active
```

默认 `write_fraction=.5`。phase 内的内容在该写入动作中不变；内容随概率一起传播、触界、等待和释放。当前是**每个声明采样点触发一次写入**，不是连续输入率，也尚未采用 cue-arrival mask。重复样本并缩小 dt 会改变模型。

空间核复用 upwind finite-volume generator。触界质量进入 Erlang 链，最后一个 phase 释放到同一绝对 reset 坐标 `a_i`，在当前网格上的距离为 `a_i-b_i`。释放采用线性点沉积；矩阵传播包含区间内所有可能的重复事件，不把分布压成均值再重置成一个点。

有限 R 个 phase 的等待时间均值为 d、方差为 `d²/R`；它没有严格正的最短等待时间。固定 phase 数能使 streaming 状态有界，不能据此宣称等价于确定性等待或长期任务记忆已解决。

## 3. 局部 QVI、value 与 risk 的准确关系

QVI 分支先解冻结的标量 Brownian 再生控制问题：active reward 为 `gain*y-maintenance`，触界即付 K，等待结束后回到固定绝对位置 a；discount 为 rho。Erlang 等待的折现因子为：

```text
eta = (1 + rho*d/R)^(-R)
k = (mu + sqrt(mu² + 2*rho*sigma²)) / sigma²
p(y) = gain*y/rho + gain*mu/rho² - maintenance/rho
A = gain/(rho*k)
F(b) = p(b) + A + K - eta*(p(a) + A*exp(-k*(a-b))) = 0
```

实现对 k 的负漂移分支采用避免抵消的等价式。根在声明区间 `a-b ∈ (1e-4,8)` 内二分，backward 使用 `db/dtheta=-F_theta/F_b`。目前只支持一阶导数，不承诺 Hessian。reset 点还必须位于有限格中心的严格内部。

该 QVI 给出**局部、冻结 law 的控制参数化**。实际执行有有限反射上界、粗空间网格、输入控制及其他群体的反馈；这些改变不自动继承原半直线问题的最优性。分类内容的全网络 Bellman/QVI 没有被解出。

| receiver 特征 | 实际计算 |
| --- | --- |
| value | 同一有限生成元上的 continuation value：`(rho*I-G)U=running_reward-K*event_rate`，再由当前概率加权 |
| risk | 从完整区间初态出发，该区间至少一次触界的概率；包含初始 phase 释放后再触界 |
| signed event rate | 区间 signed event mass/dt |
| event rate | 包含重复事件的 expected event count/dt |
| margin | 无条件 active mean margin/extent |

edge-crossing 已触发的群体在 risk 中只计一次；实现检查 `0<=risk<=min(1,event_count)`。risk 不是重复事件数、当前 active probability 或 hazard。value 可为负，不等于原 He–Xiong equity call；risk 也不是原金融 put 价格。

`fixed/learned/qvi`、三种消息选择、tanh/value-only/risk-only 特征在协议中分列。替换或屏蔽 value/risk 的 arm 仍支付实际核计算费用，不能把这种功能消融计作免去求解的内核加速。

## 4. 分段可微性与实际修复

边界网格接触、upwind 和点沉积存在 kink。BP 在光滑片段使用通常导数，在精确 knot 使用明确的选定斜率；没有全局 smooth-pasting 定理。

本轮修复了两个具体缺陷：

- 旧零位移 remap 的独立 min/max/clamp 组合可能产生不守恒、落在单侧导数区间外的 AD。新实现从同一个 cell CDF 做差分，lower、全部格差分和 upper 在值与导数上同时望远镜相消。
- 三角点沉积的默认 ReLU/abs knot 规则会使精确格中心的一阶矩 AD 为 0，而其前向一阶矩恒等于输入位置、真导数为 1。新实现使用同一 symmetric clip，专门检查该恒等关系的导数。

unit ramp 在精确 0/1 处取左右斜率平均 0.5。这是广义导数选择，不是把真实 kink 消除。有限差分和数值参考必须区分非 knot 与精确 knot。

## 5. 精度、归一化与内核费用

`float64` 的参数和物理状态均为 FP64；`mixed` 的可训练层/输出为 FP32，网格、概率、phase、QVI 与线性代数仍为 FP64；`native32` 才是原生 FP32。mixed 通过不能写成 native32 通过。原生 FP32 仍须保留已观察到的长期守恒失败，不能靠概率重归一化或放宽门槛改成成功。

dense 路径每步计算带累计量的传播、killed first-event 传播和 continuation 线性求解。uniformized 路径用 Poisson 截断替代指数动作，但当前是 **dense batched action**，不是上游 banded kernel；生成元构造和 value solve 仍存在。

设 S 为每群体状态数：动态状态约为 O(BNS)，recurrent coupling 为 O(BN²)，dense 线性代数约为 O(BNS³)；uniformized action 的有限和仍有阶数和矩阵乘法费用。BPTT tape 随序列长度增长，不能用固定 streaming tensor bytes 代替训练内存。

Poisson tail bound 只约束精确算术中的截断，不涵盖 roundoff、长时累积或梯度误差。benchmark 比较一个声明组合 loss 对全部可训练参数和输入的 VJP，不能称作完整 Jacobian。512-step forward profile 也不是 512-step BPTT 训练证明。

保留的 `feature_normalization=population` 选项对**同一样本、同一时刻、每个特征通道的 receiver 组**去均值并除以 `sqrt(mean(square)+1e-12)`；不混合 batch，不改物理状态或守恒质量。它会丢去组内公共分量，小方差可能放大数值误差。population 的64更新 smoke 与 raw 的128更新 smoke 均停留在多数类水平；更新预算不同，这只是阴性前测，不是两者等效或归一化无效的证明。正式比较使用 `none`，保留该选项和前测原件，不据此改变默认。

## 6. 合成任务的信息与局限

任务标签为独立均匀 A、B 的 `sign(A+B)`。A 在 t=0 给出，B 在后续一步脉冲中给出；输入另含各自 arrival 标记、时间坐标及相关噪声。原始输入不含标签或未来 B。已知 A、尚未知 B 的理想 Bayes accuracy 为 3/4，看到 A+B 后为 1；这只是任务构造的性质，不是网络结果。

train/dev/test、adapt-train/dev/test 使用不同生成 source ID。source 改变正增益、噪声和 cue 时刻；适配域有更强噪声及较晚 cue。这些是**模拟参数组**，不是独立真实人体或传感器数据。各方法共享同一固定数据字节、初始 margin 与目标约定。

两项限制必须保留：

1. B 是单拍脉冲，可能落在奇数 tick；默认 law 只在偶数 tick 更新。`boundary-only` 同时切断内容和 event-rate 消息，因此可能漏读奇数 tick 的 cue，而其他 arm 仍可走内容路径。这是当前采样/通信合同的 alias，不能外推成边界通信本质无效。
2. 每拍 .5 active content 擦写会衰减早期证据；持续留在 active、未获补充的那部分内容每步乘 .5。phase 储存、回流与递归路径另有演化，不能把这个局部衰减率当成全网络遗忘定理。

`early_accuracy` 是 t=0 时 receiver 尚未收到消息的分数；评估等待信息收益使用每个样本 `late_step-1` 的 `pre_late_accuracy`。停止策略是预声明 confidence≥.8，最后一步强制决策，并收等待费用；它不是由本地物理 QVI 证明最优的分类策略。

## 7. 两个不同的学习问题

第一阶段训练整个小网络：3 个 N × 8 个 arm × 3 个初始化，共72个正式槽位。每 fit 上限为180优化 CPU 秒、最多512次 Adam 更新；实际完成数、原子操作越界、开发选择、失败和全 worker 费用分别保留。最大资源与最终参数以冻结 manifest 为准，不假设已充分收敛或参数/FLOPs完全匹配。N8/32 的 dense 与 N64 的 uniformized 是预声明成本选择；跨 N 时间差同时包含宽度与 backend 的影响，不能单独归因于规模。

第二阶段只适配9个 `qvi_full` selected parent 的同一 readout。五臂均用同一冻结表示、同一 signed one-hot 目标和参数 mask `readout.weight/readout.bias`：

| 方法 | 定义 |
| --- | --- |
| KEEP | 原 parent 不变 |
| BP | FP64 工作矩阵上的 L-BFGS；无 line search，至多96次 closure，显式停止与候选预算 |
| ANALYTIC | 同一 MSE+ridge 目标的条件解析线性求解，bias 不惩罚 |
| STRICT_WSP | 没有可识别、无标签拟合的新能力构造时 ABSTAIN |
| HYBRID | 独立 ridge 求解后，在预声明 parent-to-ridge blends 中按开发指标选择；不是 edit-then-BP |

目标为 `mean_examples_and_classes((XTheta-Y)²)+lambda*sum(W²)`，解析正规矩阵为 `X'X/(n*C)+lambda*diag(1,...,1,0)`，与 BP 尺度一致。工作参数回到 parent dtype 后才评价/保存。旧域 accuracy 与 Brier 保持门及新域选择只读 dev；worst-source 另报，不能把聚合保持写成每个来源都保持。

共享特征提取、cache IO、各方法构造/选择/失败/写盘/重载和继承的 parent 训练成本分列。解析 readout 优势不是 HCSN 独有优势，也不是整网 BP 被替代。程序发现成本未测，不能当作0。

迁移正控制另列：已知 affine 输入接口用 `W'=W*A^-1,b'=b-W'*offset`；输出标签 schema 可按已知规则置换；角色内 neuron 置换必须同时变换物理 buffer、recurrent、readout 和完整状态。readout sign view 是显式坐标 wrapper，不是物理神经元符号对称。重跑程序与复制一份固定 delta 分开比较；同 checkpoint 的多个 view 不算更多独立样本。

## 8. 复现顺序与命令

在完整仓库根，或同时含本目录和 `upstream/qualification` 的源胶囊根执行。使用可用的 CPU Python/Torch/NumPy 环境；freeze 将记录并要求之后精确匹配版本。下例输出目录必须是新目录，旧 attempt、claim、seal 和成本账本不覆盖。

```bash
export PYTHONPATH="$PWD:$PWD/upstream"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export HCSN_RUN_ROOT=/absolute/new/hcsn-run
mkdir -p "$HCSN_RUN_ROOT"
python -m unittest qualification.hcsn_smallnet_20261124.kernel_tests qualification.hcsn_smallnet_20261124.data_tests qualification.hcsn_smallnet_20261124.editing_tests qualification.hcsn_smallnet_20261124.protocol_tests qualification.hcsn_smallnet_20261124.adaptation_tests
python -m qualification.hcsn_smallnet_20261124.benchmark --output "$HCSN_RUN_ROOT/numerical.json"
```

benchmark 写出诊断并退出，不等于每个 native32/长时 case 都合格；逐项查看失败、censor、finite、梯度覆盖与误差。protocol tests 仅使用明确标记的 smoke 数据替身，不开正式 holdout。

按已确定配置冻结源码后：

```bash
python -m qualification.hcsn_smallnet_20261124.train freeze --manifest "$HCSN_RUN_ROOT/train-manifest.json"
for n in 8 32 64; do
  python -m qualification.hcsn_smallnet_20261124.campaign launch --manifest "$HCSN_RUN_ROOT/train-manifest.json" --output "$HCSN_RUN_ROOT/training" --neurons "$n" --workers 4
done
python -m qualification.hcsn_smallnet_20261124.train seal --manifest "$HCSN_RUN_ROOT/train-manifest.json" --output "$HCSN_RUN_ROOT/training"
python -m qualification.hcsn_smallnet_20261124.adaptation_suite freeze --manifest "$HCSN_RUN_ROOT/train-manifest.json" --adaptation-manifest "$HCSN_RUN_ROOT/adaptation-manifest.json"
for n in 8 32 64; do
  for s in 1101 2202 3303; do
    python -m qualification.hcsn_smallnet_20261124.adaptation_suite fit --manifest "$HCSN_RUN_ROOT/train-manifest.json" --adaptation-manifest "$HCSN_RUN_ROOT/adaptation-manifest.json" --checkpoint "$HCSN_RUN_ROOT/training/n$n-qvi_full-s$s/checkpoint.pt" --output "$HCSN_RUN_ROOT/adaptation/n$n-qvi_full-s$s"
  done
done
python -m qualification.hcsn_smallnet_20261124.adaptation_suite seal --manifest "$HCSN_RUN_ROOT/train-manifest.json" --adaptation-manifest "$HCSN_RUN_ROOT/adaptation-manifest.json" --output "$HCSN_RUN_ROOT/adaptation"
```

每 worker 一线程；`--workers` 与外部 CPU/内存配额配套。三分片可由外层资源调度并行，但并行 wall 不等于 child wall 之和。示例没有把 logical affinity 当成独占物理核。

**联合研究必须先封存全部72训练槽和全部9 parent×5适配臂，再打开任一正式 holdout。** 训练单独的 test API 不替调用者强制适配封存顺序；联合流程按这里的顺序执行：

```bash
python -m qualification.hcsn_smallnet_20261124.train test --manifest "$HCSN_RUN_ROOT/train-manifest.json" --output "$HCSN_RUN_ROOT/training"
for n in 8 32 64; do
  for s in 1101 2202 3303; do
    python -m qualification.hcsn_smallnet_20261124.adaptation_suite test --manifest "$HCSN_RUN_ROOT/train-manifest.json" --adaptation-manifest "$HCSN_RUN_ROOT/adaptation-manifest.json" --output "$HCSN_RUN_ROOT/adaptation/n$n-qvi_full-s$s" --training-seal "$HCSN_RUN_ROOT/training/SEAL.json" --adaptation-seal "$HCSN_RUN_ROOT/adaptation/GLOBAL_ADAPTATION_SEAL.json"
  done
done
```

test 前共同预检完整 roster、参数/源/协议身份、checkpoint/hash、选模历史及适配的非head保护域，然后创建一次性 claim。初始化/训练失败有原件；失败 parent 不能伪装成可适配的成功模型。test 后不得用结果改源码、重选参数或替换已选 checkpoint。

无标签迁移控制使用函数 API，例如对已选 parent 和独立人工 probe：

```bash
python - "$HCSN_RUN_ROOT/training/n8-qvi_full-s1101/checkpoint.pt" "$HCSN_RUN_ROOT/transfer-n8-s1101.json" <<'PY'
import sys, torch
from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN
from qualification.hcsn_smallnet_20261124.transfer_suite import run_transfers
torch.set_num_threads(1)
saved = torch.load(sys.argv[1], map_location="cpu", weights_only=True)
model = SmallHCSN(ModelConfig(**saved["config"]))
model.load_state_dict(saved["selected_model"])
torch.manual_seed(2401124)
x = torch.zeros(12, 2, 6, dtype=model.input_drive.weight.dtype)
x[0, :, 0] = torch.rand(2)*2-1
x[0, :, 2] = 1
x[6, :, 1] = torch.rand(2)*2-1
x[6, :, 3] = 1
x[:, :, 4] = torch.linspace(0, 1, 12)[:, None]
x[:, :, 5] = .1*torch.randn(12, 2)
run_transfers(model, x, output_path=sys.argv[2])
PY
```

这条命令不生成任务标签；保存完整规则、输入/初态身份、每个控制的结果及费用。正式多 parent 迁移应对每个独立 checkpoint 重跑同一程序，不能只迁移一份已拟合 delta。

## 9. 如何读取迭代结果

训练目录保留 started/history、initial/selected/last model、优化器与 RNG、result、worker 成本及日志；最终预测原件包含 selected/initial 全 prefix logits。适配保留公共特征、全部候选记录、KEEP/ABSTAIN、独立源冻结、父权重身份和全局 seal。body、import-inclusive worker、launch-to-exit、共享费用与能耗可用性是不同口径。

正式结论须同时检查数值/梯度域、信息是否真实到达、学习是否超过初始/早期基线、独立来源表现和实际费用；缺一项就保留相应限制。如果72槽实验未通过预声明学习门槛，不能声称该网络已经具备有效学习能力或规模优势；仍可报告所测域内的数值、费用与方法比较，但解析 readout 成功不替整网补过关。当前没有全模态大模型、Transformer/SNN 主干替换、GPU吞吐、能耗或整网免 BP 的通过声明。源码或调参改变需要新的实验身份与 holdout family；旧失败和原件保持不变。

