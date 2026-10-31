# 追加实验：完整 cell 与策略联合学习

全部 20 个模型已完成完整 cell／策略联合学习，600 次训练更新均提升 nominal
精确 soft-policy 效用；在预先固定的四个新 heldout 配置上，四个 family
的平均效用均下降。FPT 没有表现出相对普通 direct 策略的稳定净收益。
全部 2,560 条预注册配对部署轨迹已执行并保留。本追加结果完成了联合
学习阶段，但不支持由此部署新的 Brownian 核。

## 状态与实验边界

本文件记录一个独立的 post-primary 实验。团队已检查主要确认结果，因此
追加设计不宣称盲于旧结果。固定 30 步预算沿用 R7；四个新 heldout 配置和
world 均在候选冻结后才评价，没有用于调参。协议与源码已在远端 commit
`385a9621410e4d6dea4214510db804ae6bcba2b3` 注册后开始正式训练。
全部 20 个 fit 均已完成恰好 30 次更新，40 份 initial/final 权重全部
冻结，且在 commit `f53e4891b0a66f831c32b6b989367c73f715a62a` 远端发布
后才开始新 heldout 评价。原 Round8 `FREEZE.json`、60 个候选和主要确认
终点保持原样。

本追加注册清单 SHA256 为
`606530930a5033a84e1af7c7cd0cf22b3d6d92f7ac35a6a51d66812dd2fddb7e`；
候选清单 SHA256 为
`b7d55711a1c5bcfb025bafbe8379b7a90515eb6bedf6528ab541de018abb91c1`。

这次补齐“固定共同内容编码器／读出之后，再开放联合学习”的后一阶段。
使用 4 个 family × 5 个原始 fit seeds，共 20 个初态，来源均为各 family
自身的 R7 baseline checkpoint；不使用先前校准模型作有利初始化。

三个含 cell 的 family 共同使用新 Brownian 过程：leak=0、dt=1、N=15、
12 个正负 image terms。与此前 R7 OU 的比较属于不同过程；这里的
initial/final 对照始终使用相同的新过程。Direct family 没有内部事件。

## 训练目标与完整后继

只优化 softmax 温度 0.12 的完整期望效用，固定 30 次 Adam 更新、学习率
0.003、clip norm 5。计算覆盖原八个 nominal 配置的全部公开 DAG，按配置
等权。没有 critic/myopic 回归、旧 Q* 监督、straight-through estimator，
也不把非线性函数在平均状态处的值当作抽样过程的期望。

每一步先传播并观察内部状态，再选择外部动作。费用计入该步实际新事件
与 compute；STOP 的当前费用照常计入，其未来价值为零。所有 surviving
bins、事件分支、reset、recovery 和后续动作均进入反向传播。
训练递推对每个转移行执行与 `hard_soft` 部署一致的非负归一，并从归一后
的 active-to-refractory 质量计算事件费。

开放参数为内容 encoder、drive、有效物理 core 和 readout。所有 leak
冻结；direct core/drive 冻结；continuous 的 reset/recovery 不可达，
同样冻结。行为使用 head 1，因此 head 0 末层坐标没有梯度。共同 hidden
readout 仍被训练。纯 return 训练后的输出称为策略分数，不宣称校准 Q*。

## 数据和评估隔离

先完成全部 20 个正式训练，再冻结所有 initial/final checkpoint hash，
随后才评价四个新 heldout 配置。具体参数直接列于新协议，由本实现代理
在未读取旧确认或 heldout 结果的情况下指定；团队层面的实验动机已知
旧结果。每个模型都保留末次更新，不择优 epoch 或 seed。

Exact DP 分别报告 soft 和 greedy 的初态期望效用、决策数与事件数。
Greedy 转换单列，因为它与被训练的 soft-policy 目标不同。

实际 Python `hard_soft` 部署另运行 2,560 条小规模配对轨迹：20 fits ×
initial/final × nominal/heldout × 32 episodes。新 world 与 latent seed
空间独立，四配置和八配置都得到平衡覆盖。每条轨迹和每个失败均保留。
样本均值、标准误及与 exact soft 值的差用于部署诊断；不由这 32 条轨迹
宣称显著、不劣或精确相等。

## 数学开发验证

`posthoc/full_joint_audit.py` 使用独立、未保存为候选的 N=15 开发对象：
H=2 枚举 16 个外部世界和全部内部状态／动作路径，H=4 检查完整 reset／
recovery 梯度，并对费用导数作独立计数。最多两次 tiny-graph Adam 更新
只记录梯度有限性和资源预算，不作为训练或选点依据。

四种模式的独立枚举均通过。完整终端路径数分别为 48、7,440、9,456、
9,456；完整效用／决策／事件期望的最大差为 `5.78e-15`，费用导数与
独立计数最大差为 `3.16e-12`，完整目标的自动微分与中心有限差分最大差
为 `7.33e-12`。Clock 与 FPT 的 reset 和 recovery 梯度均非零且有限。
这些检查验证有限矩阵模型的后继与训练梯度，不把它提升为无网格、连续
恢复的再生过程。

## 固定预算训练结果

以下为原八个 nominal 配置等权、五个 fit 等权的 exact soft-policy
训练目标。全部 600 次更新的效用均提升，没有训练失败或 seed 替换。
最大梯度范数为 0.117209，预注册的 clip norm 5 没有触发。

| Family | Initial | Final（第 30 步） | Final − initial |
|---|---:|---:|---:|
| Direct | 0.617528288 | 0.632006480 | +0.014478192 |
| Continuous | 0.618070815 | 0.632353275 | +0.014282461 |
| Clocked | 0.618296913 | 0.632104914 | +0.013808001 |
| First passage | 0.618085678 | 0.632118034 | +0.014032356 |

这说明完整 cell／策略目标在固定预算下可训练。各 family 从自身原始 R7
权重出发，初态并非跨 family 完全相同；这些细小终点差异不能单独归因于
事件机制。所有逐 seed 初末值、31 条曲线、30 个完整更新前梯度向量和
逐参数变化均保留在 `evidence/full_joint_v1/cases/`。

独立训练产物审查核对了 600 个完整梯度向量、490,650 个有限标量、所有
输入身份和逐步日志。使用保存梯度独立代入 Adam 更新公式，重建最终参数
的最大差为 `3.33e-16`；inactive 参数、buffers 和 head 0 末层参数逐值
保持不变，head 0 对应梯度全零。共享 hidden 层已更新，因此这不表示
head 0 的整体函数不变。

有效 core 参数均连入完整梯度，但有两个 reset 分支的信号近乎为零：
`clocked_13/raw_reset_minus` 的 30 步最大梯度 `9.83e-21`、初末变化
`2.83e-15`；`clocked_15/raw_reset_plus` 分别为 `1.38e-17` 和
`1.36e-11`。本结果支持梯度路径和更新规则正确，不能证明每个 core
分支都获得实质学习或独立任务价值。最终训练审查证据为
`evidence/full_joint_v1/INDEPENDENT_TRAINING_AUDIT.json`，已绑定
`posthoc/full_joint_training_audit.py` 的最终源码 hash；早期审查输出保留
但不作为最终源码绑定证据。

## 新 heldout 的完整精确评价

下表对四个新配置、五个 fit 等权。Soft 是训练与 `hard_soft` 部署的目标；
greedy 是冻结权重之后的另一种策略，不能与训练目标混用。所有数字均为
有限矩阵过程的精确期望，仍包含网格投影、tick 末 reset／recovery 合同。

| Family | Soft initial | Soft final | Soft Δ | Greedy initial | Greedy final | Greedy Δ |
|---|---:|---:|---:|---:|---:|---:|
| Direct | 0.707792366 | 0.706464049 | -0.001328317 | 0.709003706 | 0.706717022 | -0.002286684 |
| Continuous | 0.708251118 | 0.706273159 | -0.001977959 | 0.708908344 | 0.706516113 | -0.002392230 |
| Clocked | 0.707083481 | 0.705988724 | -0.001094757 | 0.708599443 | 0.706155065 | -0.002444377 |
| First passage | 0.707662588 | 0.706184214 | -0.001478374 | 0.709113884 | 0.705746003 | -0.003367881 |

每个 family 的 heldout soft 效用都是四个 seed 下降、seed 14 上升，
平均降幅约 0.0011–0.0020。固定 nominal 目标上的优化没有转化为这四个
新配置的泛化收益。下列全部逐 fit 变化保留了正向和负向结果；没有选取
有利 epoch、seed 或配置。

### 全部逐 fit 的 initial → final 效用变化

| Policy／regime | Family | Seed 11 | Seed 12 | Seed 13 | Seed 14 | Seed 15 |
|---|---|---:|---:|---:|---:|---:|
| soft／nominal | Direct | +0.014467822 | +0.014072813 | +0.012456128 | +0.015799901 | +0.015594295 |
| soft／nominal | Continuous | +0.013768217 | +0.014261530 | +0.013981325 | +0.015131127 | +0.014270103 |
| soft／nominal | Clocked | +0.014167958 | +0.012408958 | +0.012652058 | +0.015273755 | +0.014537278 |
| soft／nominal | First passage | +0.015621282 | +0.013334124 | +0.012036443 | +0.015090295 | +0.014079634 |
| soft／heldout | Direct | -0.004323625 | -0.001260342 | -0.001495818 | +0.000511359 | -0.000073159 |
| soft／heldout | Continuous | -0.002449755 | -0.004708522 | -0.001491906 | +0.000110578 | -0.001350191 |
| soft／heldout | Clocked | -0.002998811 | -0.000639165 | -0.002109783 | +0.000813120 | -0.000539148 |
| soft／heldout | First passage | -0.004301714 | -0.000910826 | -0.002353162 | +0.001400109 | -0.001226279 |
| greedy／nominal | Direct | +0.000000000 | +0.000000000 | +0.000000000 | +0.000000000 | +0.000000000 |
| greedy／nominal | Continuous | +0.000869117 | +0.013664976 | -0.000952567 | +0.000000002 | +0.003431618 |
| greedy／nominal | Clocked | +0.000074111 | +0.000332912 | -0.000979064 | +0.000494454 | +0.000380216 |
| greedy／nominal | First passage | +0.015772880 | +0.000535445 | -0.000577108 | +0.000678788 | +0.000613763 |
| greedy／heldout | Direct | -0.017224620 | +0.001682560 | +0.000750000 | +0.002608640 | +0.000750000 |
| greedy／heldout | Continuous | +0.000000533 | -0.013550059 | -0.000314994 | +0.002608640 | -0.000705271 |
| greedy／heldout | Clocked | -0.008104571 | -0.000599985 | -0.000129355 | -0.001392494 | -0.001995482 |
| greedy／heldout | First passage | -0.013003598 | -0.002726122 | -0.000923525 | -0.000408432 | +0.000222271 |

Greedy 的 nominal direct 初末值在五个 fit 上都没有变化，但 soft
效用增加：训练改变了动作概率，并不必然改变最优分数的动作。Greedy
变化的正负也与 soft 不完全一致，不能把后者的可训练性自动推广到前者。

### 预先指定的 FPT 对照

下表为各自 final 模型的效用差。跨 family 同一 seed 的初始化来自各自
R7 fit，因而属于预先指定的配对描述，不是只改一个核的因果干预。

| 对照／policy／regime | Seed 11 | Seed 12 | Seed 13 | Seed 14 | Seed 15 | 平均 |
|---|---:|---:|---:|---:|---:|---:|
| FPT − clocked／soft／nominal | +0.000122824 | -0.000307308 | +0.000222774 | +0.000117373 | -0.000090065 | +0.000013120 |
| FPT − clocked／soft／heldout | +0.000797498 | -0.000584109 | +0.000638029 | -0.000312652 | +0.000438683 | +0.000195490 |
| FPT − clocked／greedy／nominal | +0.000228810 | -0.000021854 | +0.000427357 | +0.000006540 | -0.000007036 | +0.000126763 |
| FPT − clocked／greedy／heldout | +0.000017525 | -0.003216520 | +0.000159930 | +0.000305495 | +0.000688259 | -0.000409062 |
| FPT − direct／soft／nominal | +0.000265957 | -0.000417072 | +0.000148611 | +0.000455397 | +0.000104878 | +0.000111554 |
| FPT − direct／soft／heldout | -0.000234912 | +0.000071070 | +0.000308059 | -0.000986389 | -0.000557003 | -0.000279835 |
| FPT − direct／greedy／nominal | +0.000054555 | -0.000181589 | -0.000762799 | -0.000162155 | -0.000181403 | -0.000246678 |
| FPT − direct／greedy／heldout | -0.000221408 | -0.001602645 | -0.000046144 | -0.002725771 | -0.000259128 | -0.000971019 |

Heldout soft 的 FPT − clocked 为 `+0.000195490`，但五个 seed 正负
混合；FPT − direct 为 `−0.000279835`。Heldout greedy 的 FPT − direct
为 `−0.000971019`，五个 seed 全部为负。当前结果不支持 FPT 的稳定额外
净收益，也不构成新的显著性、优效或不劣结论。

训练后的 heldout soft 期望事件数为 clocked `0.972023489`、FPT
`0.825650923`，FPT 比 clocked 少 `0.146372567` 次事件；两者决策数
都约为 3.289。较少事件并未使 FPT 超过无内部事件的 direct。

## 实际 hard_soft 配对部署诊断

20 fits × 2 stages × 2 regimes × 32 episodes，共 **2,560 条轨迹**，
没有运行失败；每个 fit／regime 的 32 个 world 在配置间平衡。Initial、
final 与四个 family 使用完全一致的 world、latent/action seed 和配置
索引，全部配对键已核验。路径经原 `task.step` 执行，不把 DP 的值当作
实际轨迹，也不将此 Python 执行称为新核的 native 部署。

| Family | Nominal sample initial | Nominal sample final | Sample Δ | Heldout sample initial | Heldout sample final | Sample Δ |
|---|---:|---:|---:|---:|---:|---:|
| Direct | 0.677993750 | 0.688818750 | +0.010825000 | 0.749506250 | 0.743418750 | -0.006087500 |
| Continuous | 0.675975000 | 0.688868750 | +0.012893750 | 0.750237500 | 0.756356250 | +0.006118750 |
| Clocked | 0.679202500 | 0.688436875 | +0.009234375 | 0.737921875 | 0.756110625 | +0.018188750 |
| First passage | 0.678086250 | 0.688773750 | +0.010687500 | 0.736544375 | 0.743098125 | +0.006553750 |

这里不能用样本均值给精确期望作通过／失败判定。每个 32-world 分组的
效用标准误为 `0.061712–0.149630`；80 个 fit／regime／stage 分组中，
最大的绝对 sample-minus-exact 为 `0.209175`，最大的标准误倍数为
`2.848744`。四个 family 共用 world，因此这些偏差也高度相关。特别是
FPT 的 heldout sample change 为 `+0.006553750`，而 exact change 为
`−0.001478374`：小规模样本甚至不足以稳定判断这一细小变化的方向。
本节只保留预注册部署诊断；完整后继／梯度的数学验证与独立路径重放
承担实现一致性证据，不以增加样本或调参来修饰这个差异。

全部逐 fit 的 exact utility／decision／event、逐配置值、样本值和
标准误在 `evidence/full_joint_v1/SUMMARY.json` 与各 fit 的
`EVALUATION.json` 中，原始路径在 `paired_rollouts.jsonl.gz` 中。

## 实测资源与一次测量纠正

四个 family 在独立单线程 Torch 2.8.0 CPU／NumPy 2.3.5 进程中并行
运行，每个进程顺序完成五个 fit。下面的完整进程 CPU／wall 包含启动和
五次训练；并行 job-seconds 之和不代表用户等待的 makespan。

| Family | 完整进程 CPU（s） | 完整进程 wall（s） | 进程 peak RSS（KiB） |
|---|---:|---:|---:|
| Direct | 6.206727 | 6.249772 | 303,204 |
| Continuous | 13.164430 | 13.195556 | 336,688 |
| Clocked | 15.842647 | 15.875927 | 341,972 |
| First passage | 132.700566 | 132.821526 | 1,867,540 |

正式 738-state、N=15 FPT 的第一步 wall 为 1.747865 秒。最初的外层
监控把 namespace PID 用于 host-mounted `/proc`，取得了错误进程的
VmRSS／VmHWM；`launch_*.json` 保留原始观察，但这两项内存数值作废。
SELF 和 CHILDREN `getrusage` 的进程 high-water／CPU 记录有效。

为获得可靠的首步内存，另从冻结 initial 模型在独立、随后丢弃的对象上
重放恰好一步。重放 wall 1.050728 秒、CPU 1.050695 秒，进程 peak RSS
1,215,816 KiB；其下一步效用与原始 curve 的 update 1 差严格为零。
原候选没有收到第 31 次更新，所有冻结 hash 未变。重放结果仅作资源诊断，
不替代正式首步 wall。Peak RSS 包含解释器和启动分配，不是该步新增字节。

完整注册评价（exact soft／greedy 加全部配对 rollout）的单进程资源为：

| Family | CPU（s） | Wall（s） | Peak RSS（KiB） |
|---|---:|---:|---:|
| Direct | 3.982943 | 3.991980 | 234,644 |
| Continuous | 6.335857 | 6.358635 | 239,140 |
| Clocked | 6.932055 | 6.954029 | 239,620 |
| First passage | 26.406082 | 26.421898 | 255,852 |

四个正式训练进程共 167.914370 CPU 秒，四个完整评价进程共 43.656937
CPU 秒；未把开发验证、独立审查和资源重放隐藏在这两个正式预算数中。
本实现的 FPT 全图训练 CPU 约为 clocked 的 8.38 倍，进程 peak RSS
约为 5.46 倍。该测量针对本次 Torch N=15 完整反传，不等同于原 R7
native 单步延迟，也不是对所有首达实现的性能下界。

## 版本与部署

新的 checkpoint schema 为 `hepta.full-joint-policy.v1`，三个 cell 使用
`r8-brownian-images-v1`，direct 使用 `r8-full-joint-direct-v1`。
它们会被当前 R7 native loader 拒绝。此前已通过的 R7 native 资格不会
自动覆盖这些新权重和新核。本追加实验不改变生产 activation。

本追加的所有权重、NPZ 梯度、gzip 轨迹、摘要和审查结果直接保存在
`evidence/full_joint_v1/` 并独立发布到 Git；它们不属于此前 99 个 parts
的主要确认原始证据包。主要确认冻结与统计终点不受影响。

## 从全新输出目录重跑

在仓库根目录运行，使用已安装 Torch 2.8.0 CPU、NumPy 2.3.5 和 SciPy
1.17.0 的 Python。下列流程固定 N=15、20 fits、每 fit 30 次更新和
2,560 条配对轨迹，不改变源码、协议或原 evidence。所有写操作使用新
目录；已有输出不可覆盖。

`register` 会创建新的时间戳与注册清单。若这是一个新的预注册实验，须
先发布该清单并设置真实的 `JOINT_REGISTRATION_COMMIT`；全部模型训练
完成后，再发布新的 `CANDIDATES.json` 与权重并设置真实的
`JOINT_CANDIDATE_COMMIT`，然后才运行评价。纯本地数值复验应如实标注为
local replay，不冒用本次两个历史 commit 作为新注册证明。

```bash
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
JOINT_PYTHON=python
JOINT_MODULE=experiments.analytic_event_neuron.round8_contract_closure_20261031.posthoc.full_joint
JOINT_OUTPUT=/tmp/hepta-full-joint-replay

"$JOINT_PYTHON" -B -m "$JOINT_MODULE" register --output "$JOINT_OUTPUT"

# 发布新 REGISTRATION.json 后，设置其真实的 40 位 commit。
: "${JOINT_REGISTRATION_COMMIT:?Set the newly published registration commit}"
```

下面的辅助函数仅为 CLI 包装器，保存每个进程的 wall、CPU 和 peak RSS。
它使用 `RUSAGE_CHILDREN`，不查询 namespace PID 的 `/proc`。汇总器读取
这两类 resource receipts，因此完整重跑请保留该包装器。

```bash
run_joint() {
  "$JOINT_PYTHON" -B - "$1" "$2" "$JOINT_OUTPUT" \
    "$JOINT_REGISTRATION_COMMIT" "${JOINT_CANDIDATE_COMMIT:-}" <<'PY'
import hashlib, json, resource, subprocess, sys, time
from pathlib import Path

stage, mode, destination, registration_commit, candidate_commit = sys.argv[1:]
output = Path(destination)
module = "experiments.analytic_event_neuron.round8_contract_closure_20261031.posthoc.full_joint"
command = [sys.executable, "-B", "-m", module, stage, "--mode", mode,
           "--output", str(output)]
if stage == "train":
    command += ["--registered-commit", registration_commit]
before = resource.getrusage(resource.RUSAGE_CHILDREN)
started = time.perf_counter()
result = subprocess.run(command, check=False)
after = resource.getrusage(resource.RUSAGE_CHILDREN)
receipt = {
    "mode": mode, "command": command, "returncode": result.returncode,
    "registered_commit": registration_commit,
    "candidate_freeze_commit": candidate_commit,
    "full_wall_seconds": time.perf_counter() - started,
    "child_user_cpu_seconds": after.ru_utime - before.ru_utime,
    "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
    "child_peak_rss_kib": after.ru_maxrss,
    "registration_sha256": hashlib.sha256((output / "REGISTRATION.json").read_bytes()).hexdigest()
}
name = f"launch_{mode}.json" if stage == "train" else f"evaluate_launch_{mode}.json"
with (output / name).open("x") as stream:
    json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
sys.exit(result.returncode)
PY
}

for mode in direct continuous clocked first_passage; do
  run_joint train "$mode" || exit
done

"$JOINT_PYTHON" -B -m "$JOINT_MODULE" freeze-candidates --output "$JOINT_OUTPUT"

# 发布新的 CANDIDATES.json 与所有 40 份权重后，再进行评价。
: "${JOINT_CANDIDATE_COMMIT:?Set the newly published candidate freeze commit}"

for mode in direct continuous clocked first_passage; do
  run_joint evaluate "$mode" || exit
done

"$JOINT_PYTHON" -B -m "${JOINT_MODULE}_summary" --evidence "$JOINT_OUTPUT"
"$JOINT_PYTHON" -B -m "${JOINT_MODULE}_training_audit" \
  --evidence "$JOINT_OUTPUT" --output "$JOINT_OUTPUT/INDEPENDENT_TRAINING_AUDIT.json"
```

完整分支／梯度开发核验可以独立复现。它使用单独的 tiny-graph 对象，
不修改候选，也不读取 heldout：

```bash
"$JOINT_PYTHON" -B -m "${JOINT_MODULE}_audit" \
  --updates 2 --output "$JOINT_OUTPUT/development_audit_replay.json"
```

`full_joint_summary.py` 是训练和评价之后的纯读取汇总器；
`full_joint_training_audit.py` 独立检查保存的梯度、Adam 代数、inactive
参数、head 0 和身份 hash。上述辅助文件不是新的目标、选点器或训练阶段。
