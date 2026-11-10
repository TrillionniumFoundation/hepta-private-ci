# Text/image NDU：研究与使用契约

本目录提供 Linux CPU 上可训练、可推理、可保存及回滚的双模态研究原型。有限控制实验和真实 v4 数值生成适配器分别保留证据：前者能够计算明确模型内的精确 DP，并训练续行 advantage；后者实际更新 v4 参数、调用 Rust 推理、执行付费 READ 重编码与重放、交付文本和图片。目前原生动态策略的准入结论是 **`no-update`**。`--policy dynamic` 明确执行 `static-quota` 回退，不代表有限策略已经部署到真实生成器。

当前实现基于 [PR #5440](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5440) 的提交 [`d13761500aba28634238ec23fb1d62eae5cf81ec`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/d13761500aba28634238ec23fb1d62eae5cf81ec)。这不是声称该提交已进入 `main`。同期 [PR #5445](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5445) 的条件残差与采集器工作没有合入本原型；其记录、校准结论及测试结果不能直接归入本目录。

## 1. 模块与证据范围

| 模块 | 可执行职责 | 证据边界 |
| --- | --- | --- |
| `finite.py` | 有限状态、合法动作、资源收费、已知终止结算、嵌套风险 DP | 数值等级是已验证的夹具；没有从自然语言或图片推断语义质量 |
| `learning.py` | Torch advantage 拟合、支持集检查、残差校准、可校验 JSON checkpoint | 拟合精确 DP 教师；没有训练终止收益或真实语义正确率 |
| `evaluation.py` | 固定/轻量/动态/DP/oracle 对照、来源配对、冻结及两层消融 | 程序化有限模型实验；真实部署收益不由此获准 |
| `generator_training.py` | 实际 v4 编码器、核心及内容头的小规模训练 | 16×16 色卡数值任务；没有完整 Hepta/NDU 联合训练 |
| `native.py` / `cli.py` | 严格输入编码、真实 Rust 调用、Torch 对照、READ 重放及本地交付 | 内容变化及数值一致性不等于语义质量改善 |
| `lifecycle.py` | Packet 时序、资源账本、checkpoint 安装/激活/回滚 | 准入检查验证声明；外部证据真实性仍由独立评估层负责 |
| `run.py` | 源码身份固定、构建/测试、有限实验、训练/冷加载及原生演示收据 | 当前标记为辅助执行器，不能作为项目专属 Codex 云环境认证 |

原型显式限定 **Linux CPU**，使用 `resource` 记录父/子进程 CPU。已执行的云端会话使用 Python 3.12.14、Torch 2.8.0 CPU、NumPy 2.3.5、Pillow 13.0 和 Rust 1.96；先前辅助 desktop 测试使用 Python 3.12.3、NumPy 1.26.4、Pillow 10.2。两者均没有项目专属环境身份认证。`run.py` 检查 Rust 1.96 工具链并记录实际版本；没有声明 macOS、Windows 或 GPU 已通过验证。

## 2. 有限状态、收益与信息价值

状态是

```text
State(text_grade, image_grade, budget, time, steps,
      signal, requested, ready_at)
```

两种 `grade` 取 0、1、2；`budget`、`time`、`steps` 分别是模拟 credit、tick 和动作次数。`signal=-1` 表示未 READ 的信号；`requested` 与 `ready_at` 表示已声明的未来观测。默认实验根覆盖预算 18/24/30 和两模态等级 0/1 的组合。状态足够性的依据是显式转移模型；没有证明真实生成器可以用这些量构成 Markov 状态。

动作是 `STOP`、`SUBMIT`、`READ`、`WAIT` 和 `REPAIR:text/image/both`。模态份额分别为 `(1,0)`、`(0,1)`、`(0.5,0.5)`，属于离散菜单。没有求解任意连续份额、任意输出组合或全模态全局最优。

`STOP` 返回当前已验证草稿；`SUBMIT` 要求两模态等级至少为 1，并满足剩余时间、预算及调用限制。已知终止收益为：

```text
G_STOP(s)   = 0.2 * (text_grade + image_grade)
              + 0.06 * min(text_grade, image_grade)
G_SUBMIT(s) = G_STOP(s) + 0.08 - utility_per_credit * cost(s, SUBMIT)
```

`STOP` 在此有限模型中免费；原生 v4 的终止 flush 仍产生真实计算和调用成本。历史费用已经发生，不能在终止收益中再次扣除。每个续行动作都为最坏情况 `SUBMIT` 预留 5 credits、1 tick 和 1 次调用；预留只有实际花费才入账。

Bellman 目标使用嵌套的指数确定性等价：

```text
CE_rho(X) = -log(E[exp(-rho * X)]) / rho     # rho > 0
CE_0(X)   = E[X]
Q(s, a)   = CE_rho(V(s_next) - kappa * edge_cost)
V(s)      = max(known terminal settlements, continuation Q values)
A(s, a)   = Q(s, a) - G_STOP(s)
```

`risk` 是该有限模型的风险厌恶参数；credit/tick 不是美元、焦耳或实测秒。逐轨迹报告的 `net_utility` 是终止收益减全部模拟费用，其样本均值不是上述嵌套风险值，不能混为同一指标。

未来信息只有在合法 READ 后进入状态。READ 前修复成功率与未读信号独立；READ 后信号改变两种模态修复配方的成功率。WAIT 只推进至声明的到达时刻，但其下游价值可能随机。因此不确定性掩码递归检查续行子树，不会因 WAIT 的一步转移确定就把它错误当作已知价值。信息价值体现在付费 READ/WAIT 后的 Bellman 差值，没有免费预看观测。

## 3. 仅学习不确定续行与校准

训练枚举注册根的全部可达支持集，只拟合 `uncertain(state, action, model)` 为真的合法续行动作。`STOP`、`SUBMIT` 和完全确定的续行子树使用显式 `terminal_value` / `known_score` 结算；终止训练目标数量必须为零。保守掩码可能包含被支配的随机动作，但不会把确定终止收益交给网络拟合。

网络为相同的 16→24→1 float64 骨干，使用 tanh。`fixed_hidden` 冻结初始化隐层并训练输出层；`trainable_hidden` 同时训练隐层和输出层。这是有限控制表示学习及 DP 蒸馏。实际 v4 色卡内容训练是另一项实验，不能借此宣称端到端 NDU 联合优化已完成。

校准按程序化来源分组，使用每组最大的绝对 DP advantage 残差及 `ceil((n+1)*(1-alpha))` 次序统计量，保留经验残差 CDF。样本不足时不伪造有限置信半径。动态执行比较扣除残差半径和实用改进余量后的续行预测与已知结算。

这是 **DP 逼近误差的残差校准**。模型没有输出正确概率，报告中的 `probability_prediction=False`，Brier/ECE 为 `null`。残差 CDF 不能解释为任务正确概率；没有条件覆盖、语义 OOD 覆盖或真实分布校准保证。

支持集/模型身份不匹配、缺少可用校准半径等情况触发已知策略回退。输入编码器拒绝超范围字节、未知格式/尺寸；checkpoint 验证结构、形状、数值与外部 SHA256。这些是协议及有限支持拒绝机制，尚不是开放世界语义未知输入识别器。

## 4. 对照、两层消融与 future 协议

| 对照 | 有限实验中的行为 |
| --- | --- |
| `encoder-only` | 不续行，选择当前合法的已知终止结算 |
| `static-quota` | 按步骤交替 text/image，无法执行预定动作时终止 |
| `fixed-steps` | 最多两次 `REPAIR:both`，受共同合法动作限制 |
| `light` | 使用公开转移模型进行一步续行后立即终止的比较 |
| `tuned-fixed` | 在校准来源上选择长度 0..3 的 text/image/both 序列，共 40 个预注册候选 |
| `exact-DP` | 对共同可见状态和已知转移模型求精确有限 DP |
| `dynamic` | 在支持范围内使用校准后的续行 advantage，否则回退 |
| `privileged-oracle` | 预看 counter RNG 的未来结果并搜索，作为特权上界 |

所有有限策略使用相同动作收费及资源约束。REPAIR 的共同随机数由 `(source_seed, state.time, action.name)` 决定；READ 则按来源及不可变观测包标识绑定，延迟读取同一包不会重新抽取其内容。oracle 的上界只相对于这个耦合、有限动作空间和给定费用成立；其额外未来信息及搜索成本必须披露，不能用于同信息公平晋级。DP 也只在声明的模型与风险目标内最优，不是现实生成任务的全局最优证明。

`tuned-fixed` 的网格在拟合前注册，只用校准来源选择一次，记录全部试次、模拟费用、CPU 和 wall time。所有候选及其选择结果冻结后才展开 future；不得看 future 结果重新选择固定策略。动态候选须与该强固定对照以及其余注册的固定/轻量对照比较。

真正的训练×执行 2×2 为：

| 训练因素 | `fixed_execution` | `dynamic_execution` |
| --- | --- | --- |
| `fixed_hidden` | A：`static-quota` | B：对应 fixed-hidden 候选 |
| `trainable_hidden` | C：同一 `static-quota` | D：对应 trainable-hidden 候选 |

A/C 与拟合无关，复用同一批实际静态执行记录，不能重复计为新实验或新成本。报告保留 B−A、D−C、C−A、D−B 和交互项 D−C−B+A。`trained_hidden` / `reset_hidden` 另列表示消融；重置隐层不是“固定执行”。此矩阵的范围是有限控制表示，不是完整 Hepta 训练×部署闭环。

默认至少三个独立初始化 seed：11、29、47。训练、校准、future seed 名单互斥；训练来源明确标为“声明有限模型的全部 DP 支持”。校准来源从 100000 起，future 来源从 200000 起，权重、残差、固定策略及其 SHA256 在生成 future 结果之前冻结。注册字段分别为 `future_seeds_registered_before_fit` 和 `future_outcomes_materialized_after_freeze`。

future 测试是已知有限支持上的新程序化随机轨迹。训练已见过该模型的全部支持；来源 ID 分离不能证明未见语义任务或真实未来分布泛化。报告保存每个 seed 的原始轨迹、动作/份额、成本类别、净效用和来源配对差，并提供初始化×来源的配对 bootstrap 区间；固定/轻量主比较采用多重比较调整。区间仍是该实验域的描述性证据。

## 5. 实际 v4 训练、原生推理与 READ

内容训练实际实例化 `JointGeneratorV4(width=32, depth=1)`，编码 UTF-8 文本和 16×16 RGB 色卡，经过 shared/image/text 动作，以文本 NLL 和图片 MSE 更新内容参数。`critic.*`、`delivery_critic.*`、`actor.*` 保持冻结；训练报告列出变动参数组、来源摘要和逐步损失。产生可冷加载的 baseline/candidate `.heptapk` 数值包，不加载可执行 pickle。

当前输入契约为 1..4096 UTF-8 字节文本及不超过 1 MiB 的 16×16 PNG/PPM；其余格式直接拒绝。音频、视频张量及 mask 为零。原生程序使用仓库既有 `hepta-joint-propose.rs`，逐步比较 Torch/Rust 状态，并在终止时比较实际输出字节。REPAIR 报告连续候选变化；没有把“非零变化”“合法 UTF-8”或“可解码图片”当作语义提升。

`PacketInbox` 只在到达且未过期、资源允许时调用载荷 loader；提前 READ 不会触发 loader。WAIT 受剩余时间与终止预留约束。重复 READ 仍收费，复用必须由适配器显式实现。

v4 状态绑定整个公开输入包，所以 `NativeSession.read()` 对新输入重新编码，并逐项重放已发生的修复历史。它先检查调用预留；失败时恢复旧候选、公开输入及 owner 身份，但不恢复已花费的时间、调用次数或账本。已终止/提交的会话不能再 READ。该事务语义不能被解释为外部副作用可撤销。

原生 CLI 的 `static-quota` 固定执行 text、image；`fixed-steps` 固定执行 both、text、image；`encoder-only` 直接进行终止 flush。这与有限实验的同名调度具有不同具体步骤，不能把两个 profile 的成绩混为一张收益表。原生 `--policy dynamic` 输出：

```text
requested_policy = dynamic
effective_policy = static-quota
dynamic_admitted = false
production_update = no-update
```

原因是尚缺真实 native 状态到有限控制状态的已验证映射、语义校准及真实 future 净收益证据。`SUBMIT` 只在新的本地目录写出文本、PPM 和交付收据，不代表上线或向外部服务提交。

本地交付以 `delivery.json` 的独占原子链接为完成标记；目录或 `delivery.intent.json` 存在都不能视为成功。这是原子完成标记，并非原子目录改名。先写入并同步原始 intent 和各模态字节，再发布完成标记。中途失败可用同一内存会话保留的 terminal bytes、同一目标和同一预算继续提交；不得重跑生成或延长截止时间。提交确认丢失后，只按原来独立保存的 `delivery.identity` 读取并核对全部字节。损坏、陌生文件、不同身份和软链接均拒绝。

`python -m scripts.ndu_bimodal.cli read-delivery --output <原目录> --identity <原identity>` 可在新 Python 进程冷读已提交结果，不加载 Torch 或执行原生模型。该读回返回历史生成收据；额外恢复读取的成本由调用方单独记录，不能当成历史生成费用为零。CLI 的完整执行/成本记录在同级 `<目录名>.execution.json`，不修改已经绑定的交付目录。这里只验证本地交付与读取机制，尚未建立真实 `StageOwnerPorts`、CURRENT/NextUse、daemon/Root 冷恢复或完整机器断电持久性。

## 6. 成本账本与 no-update

有限 tariff 按 observation、residency、recompute、reuse、coordination、generate、control 七类扣费，包含终止自身费用。真实账本独立记录观测、生成、控制、驻留 byte-seconds、重算、复用、协调和提交；失败、超时及拒绝也保留收据。CLI 从读取权重/图片起计观测成本，跟踪已命名输入、公开张量、候选状态及 checkpoint 载荷的驻留；READ 重放不能免费。

控制器实际 wall time、训练/调参成本、整个运行 wall/父进程 CPU/子进程 CPU 分别报告。整段计时与内部事件可能重叠，不能相加；Rust 子进程 CPU 与 Python 父进程 CPU 分开。有限算法测时含暖缓存效应，不构成严格匹配物理资源的在线服务对比。

目前驻留统计只覆盖显式命名载荷，没有完整 Python/Torch/native heap、RSS、能耗及供应商账单。未知正用量单价产生 `monetary=null`，不能当成零。`provider_money`、`energy_joules` 的缺失必须保留。有限 credit 预算一致，不等于完整真实资源预算已经一致。

若任一注册强对照未被稳健净收益下界超过，保留固定策略或 `no-update`。即使有限实验下界为正，报告仍保持 `production_adoption=False`；程序化证据及不完整真实成本/保留能力证据不能自动授权生产更新。未来晋级需另行冻结阈值，在同信息机会、同真实预算及独立真实未来样本上核验净收益、约束、保留能力、数值一致性与未知输入拒绝。

## 7. Checkpoint 与安全回滚

`CheckpointStore` 使用有界、带 SHA256 清单的不可变 bundle，验证冷加载，并以文件锁及原子替换维护 active pointer。初次 `initialize()` 只能接受显式 baseline；`stage()` 不修改 active。有限 JSON controller checkpoint 同样要求外部可信 SHA256，且绑定有限模型 profile/支持集，不能作为原生 v4 部署凭证。

`activate(evidence, expected_pointer_sha256)` 要求候选 provenance 为 `measured`、证据绑定候选/证据摘要、非 fixture/非 synthetic 的前瞻性实测声明、净收益及保留能力下界、约束/parity/future/未知拒绝通过。它检查声明格式和门槛，不能自行证明外部声明真实。任何缺失均保留 baseline。不要为使门槛通过而把夹具重新标为实测证据。

`rollback(identity, expected_pointer_sha256)` 只接受当前 pointer 的 `previous`，要求目标完整性验证通过且 compare-and-swap 摘要仍匹配；发生并发冲突必须重新读取 pointer，不能覆盖其他更新。尚未激活候选时 `previous` 可为空，此时没有“新生产候选已回滚”的事实。

`run.py` 验证 fixture 候选被拒绝、active 未变及冷加载 baseline 字节相同；公开 API 回滚测试通过人工构造测试证据检验机制。机制测试不能作为科学准入或生产版本回滚的证据，正式收据保留 `HOLD_NOT_ADMITTED`。

## 8. 音视频扩展接口

`Packet` 预留 `modality=text/image/audio/video`、`event_ns`、`arrival_ns`、`deadline_ns`、`sequence`、`media_clock`、`media_time_ns`、`sync_group`、载荷 SHA256 和字节数。要求事件/到达/截止顺序，音视频必须带成对的媒体时钟及媒体时间；未知字段拒绝进入公开描述符。

这些字段为未来同步音视频的可用性、媒体时间对齐、分组协调及费用记账提供边界。当前没有训练音视频策略、同步生成器、AV drift 指标或全模态校准，字段存在不能作为这些能力已经完成的证据。

## 9. 复现命令与收据

从包含本目录实现的 checkout 根运行。将解释器与 `rustc` 路径替换为已配置的实际路径；正式运行前固定源码。`--source-commit` 必须等于当前完整 HEAD，已跟踪源码不得有未提交修改；runner 另存 Python/Rust 文件摘要并比较运行前后身份。输出必须在 checkout 外且为空/不存在。

```bash
PYTHON=/path/to/python3.12
RUSTC=/path/to/rustc
RUN_ROOT="$(mktemp -d /tmp/hepta-bimodal.XXXXXX)"
SOURCE_COMMIT="$(git rev-parse HEAD)"

"$PYTHON" -m scripts.ndu_bimodal.run \
  --source-commit "$SOURCE_COMMIT" \
  --rustc "$RUSTC" \
  --output "$RUN_ROOT/qualification" \
  --execution-label auxiliary-desktop \
  --epochs 240 \
  --future-sources 48
```

runner 构建原生程序及既有 Rust 测试，执行四个 Python 测试模块并拒绝空测试/skip，运行有限研究、内容训练、checkpoint 冷加载和 READ/WAIT 原生演示。成功或失败均写 `qualification.json`；失败时保留已有日志和产物。`passed_auxiliary_checks` 只表示该执行器上的检查完成，`project_cloud_environment_verified=False`、`scientific_acceptance=HOLD_NO_GO` 和 `production_update=no-update` 仍保留；改变 `--execution-label` 不能提供环境认证。

成功后可独立复现内容训练与 CLI 推理：

```bash
"$PYTHON" -m scripts.ndu_bimodal.cli train \
  --seed 41 --steps 12 --output "$RUN_ROOT/content-cli"

WEIGHTS="$RUN_ROOT/content-cli/candidate.heptapk"
BINARY="$RUN_ROOT/qualification/hepta-joint-propose"
WEIGHTS_SHA256="$(sha256sum "$WEIGHTS" | cut -d ' ' -f 1)"
BINARY_SHA256="$(sha256sum "$BINARY" | cut -d ' ' -f 1)"

"$PYTHON" -m scripts.ndu_bimodal.cli infer \
  --weights "$WEIGHTS" --weights-sha256 "$WEIGHTS_SHA256" \
  --binary "$BINARY" --binary-sha256 "$BINARY_SHA256" \
  --text "Describe the colour in the image." \
  --image "$RUN_ROOT/qualification/native-demo/initial.ppm" \
  --output "$RUN_ROOT/cli-delivery" \
  --policy dynamic --wall-seconds 30
```

这里从刚产出的可信本地文件计算摘要用于复现；部署时摘要应来自独立可信记录，不能把任意收到的文件及其自报摘要视为认证。CLI 输出目录必须不存在。

有限研究亦可通过 `evaluation.run_study(output, seeds=(11,29,47), epochs=240, calibration_sources=24, future_sources=48)` 调用。核心收据为 `finite-study/registration.json`、`candidate-freeze.json`、六个 controller checkpoint 及 `report.json`；原生证据为 `content-training.json`、`native-demo/report.json`、交付文件和 `qualification.json` 的摘要清单。保留原始配对轨迹及失败记录；不要只保留聚合均值。

正式结果表应由对应源码/产物摘要的实际运行收据填入。本契约不预填尚未完成的训练收益、测试数量、校准覆盖率或性能数字。

## 10. 研究依据

| 来源 | 本原型采用的研究约束 |
| --- | --- |
| [Merton, *Optimum consumption and portfolio rules in a continuous-time model*, MIT 存档](https://dspace.mit.edu/entities/publication/45b93de3-551e-475d-9d42-4724ecd84484) | 用资源状态、效用和风险组织配置问题；本原型不是连续时间金融模型或其闭式解 |
| [Ruszczyński, *Risk-Averse Dynamic Programming for Markov Decision Processes*](https://optimization-online.org/2009/12/2497/) | 明确逐步风险聚合及 DP 的模型条件；不能把单次均值评分称为风险一致的动态最优 |
| [Laroche et al., 2019, *Safe Policy Improvement with Baseline Bootstrapping*](https://proceedings.mlr.press/v97/laroche19a.html) | 支持不足时保留 baseline 的方法论参考；本目录 no-update 门槛不是该论文定理的实现证明 |
| [Guo et al., 2017, *On Calibration of Modern Neural Networks*](https://proceedings.mlr.press/v70/guo17a.html) | 区分置信概率与经验正确率；残差区间不能冒充概率校准 |
| [Callaway et al., UAI 2018, *Learning to Select Computations*](https://www.auai.org/uai2018/proceedings/papers/269.pdf) | 计算选择需要比较续行信息价值和计算代价，并保留轻量元推理对照 |
| [*When Does Learning to Stop Help?*, arXiv:2606.30852v2](https://arxiv.org/abs/2606.30852v2) | 冻结校准选点、比较强固定/标量规则、计算探测与重算成本，并接受没有可认证收益的结果 |

