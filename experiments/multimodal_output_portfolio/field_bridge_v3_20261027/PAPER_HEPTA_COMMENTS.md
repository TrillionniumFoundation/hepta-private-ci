# Parameter field theory 与 Hepta neuron：V3 理论对应和 comments

**两者可以组成两个控制层，但现有论文与 Hepta 实现并不互相提供效果或充分性证明。** 参数场这一层决定怎样继续改变模型；Hepta 这一层处理交付输出与后续反馈，并决定下一次运行动作。连接两层的是实际更新后的生成器及它交付的输出。V3 将这条连接写成可以失败、可以复核的实验；实际结果与停止决定见 [研究报告](README.md)。

论文固定为 [R45 主文](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)和 [递归控制细节](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_recursive_detail.tex)。这里不把固定修订称为所有后续版本的最新稿，也不作投稿或录用状态判断。Hepta 内核固定于 `63f198ad85cfa2aa579032256355f446cfe793a0`，V3 包装没有改变原始 `sparse_tick` 算法。[构建与原始内核身份](evidence/NATIVE_BUILD_RECEIPT.json)。

## 1. 应当如何对应两个系统

| 对象 | 论文中的问题 | V3 的实际实现 | 可以检验的主张 |
| --- | --- | --- | --- |
| 完整学习状态 | 参数与全部优化器变量，时间和外生随机规则明确 | 局部适配参数、完整 SGD 动量、确定日程、guard 事务 | 同一状态和动作能否精确重放 |
| 参数场 | 预先固定的可观测映射及被省略的动态 | 固定 H12；并保留 H7、generic12、richer30 对照 | 对指定终点值的预测和学习决策是否有增量价值 |
| 未来价值 | 未来成本定义的 Bellman 值，不等同于当前损失 | 候选 48 步后，按冻结 reference 续训到第 288 步的 Qref | 完整闭环是否兑现参考续训预测的价值 |
| 运行状态 | 依赖实际信息集的控制 | 最多三次决策，公开输出、部分反馈、真实 Hepta 递归状态 | 在同信息历史参照之外是否改善实际交付 |
| 执行器 | 允许的干预空间及其代价 | 训练倍率四选一；运行 stop/image/text/semantic/couple | 收益是否只对这个受限动作集合成立 |
| 误差与成本 | 动态省略、信息限制、执行器限制、系数估计分账 | 源身份分离、完整分支与实际输出、同机会对照、独立成本账 | 能否把效果与更大搜索、更多信息或漏计成本区分开 |

表中论文对应来自 R45 的 `sec:r45-framework`、`sec:r45-accounts`；实现依据为 [训练状态和事务](learning.py)、[场测量](training_features.py)、[训练目标与控制器](training_policy.py)、[运行任务](feedback_task.py)和 [运行控制器](runtime_controller.py)。这是操作层面的对应，没有把本实验称为论文控制方程的数值解。

## 2. 终点目标修正了八步贪心，但 Qref 仍有明确边界

V2 已得到的区分是：短期局部预测和决策门槛通过，完整十一臂的六项联合验收仍为 0/6。V3 因此改为完整 288 步续训目标，用四条完整开发日程检验闭环；原定独立审计日程因开发门槛失败而未开启。局部预测误差与完整训练收益分别报告。[V2 报告](../field_bridge_v2_20261027/README.md)、[V3 冻结协议](PROTOCOL.json)。

V3 实际拟合的是

\[
\widehat Q_{\mathrm{ref}}(H(X_t),a)
\approx U\bigl(X_{288}\mid a\text{ 先执行 48 步，随后固定 reference}\bigr).
\]

部署时每 48 步重新选动作，后续策略已经改变。因此 Qref 与部署策略自身的 Q 值不同；低 CV MSE 不保证低动作遗憾，也不保证闭环终点改善。训练 bank 的 24 个状态来自每个模型的四条轨迹，存在明显相关性。跨轨迹 CV 检查的是这些已规定轨迹中的拟合稳定性，新的 source roles 和完整 rollout 才能检验转移。[完整分支生成](training_bank.py)、[完整路径与开发选择](training_stages.py)。

这与论文强调在被评估策略实际到达的状态分布下衡量误差相一致。V3 没有估计论文完整的可达动态误差预算，因此无权把一次实验的收益或失败提升为一般控制误差定理。尤其不能用 reference 轨迹上的准确性替代实际 field policy 的轨迹表现。

## 3. H12 的方向信息是合理假设，名称不提供充分性

H12 在原 H7 上增加下一次加权裁剪梯度的尺度、梯度与动量夹角，以及三项损失的方向测量。代码按正方向 \(v=\beta m+\operatorname{clip}(g)\) 计算 \(\nabla L\cdot v\)，实际 SGD 位移为 \(-\eta a v\)。测量使用与实际更新相同的 rehearsal、teacher anchor 和裁剪规则，保持参数、优化器与随机状态不变，并恢复原有梯度。[特征定义](training_features.py)、[训练契约](../field_bridge_v3_20261027_review/TRAINING_IMPLEMENTATION_CONTRACT.json)。

这些信息针对 V2 暴露的方向缺失提出了可检验的修正，但有限个标量仍可能丢失更新方向、曲率和 guard 边界信息。参数场有用与参数场是全局 Markov 充分状态，是不同强度的命题。论文也区分严格全纤维闭合与指定可达分布上的近似控制；不能仅凭一个构造反例否定所有分布相关结论，也不能凭几条成功轨迹证明全局闭合。[R45 主文的投影与 forcing 定义](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)。

本轮全部 12 个 head 的 ridge 选择都是 1，H7 在三个模型上的 Qref CV MSE 都低于 H12。这个结果保留为拟合诊断；H12 treatment 没有因观察到该结果而被替换。[完整 CV 网格与解释边界](../field_bridge_v3_20261027_review/TRAINING_FIT_REVIEW.md)。

## 4. Hepta 的价值应体现为同信息下的表示和决策收益

Hepta 状态是公开历史的确定性变换。在本任务中，历史控制也获得同样的三轮公开事件、反馈和已执行动作。因此 native 若胜出，合理解释是这个受限读出族中的表示或拟合优势；不能解释成它凭空获取了历史控制看不到的信息。

V3 为此使用 48 维完整原始历史，加 40 维 native 状态或 40 维固定 Fourier 特征。两者均为 88 维读出输入，每个策略 1,335 个拟合系数、12 个候选机会，并使用同一批实际输出和各候选自身的未来策略目标。当前事件参照与重新独立拟合的 reset-native 保留为诊断。[控制器定义](runtime_controller.py)、[全部候选及独立重建](evidence/INDEPENDENT_RUNTIME_FIT_AUDIT-frozen.json)。

相同 head 宽度和系数数目并不证明两个函数类的所有统计容量完全相等。它们提供的是具体、可审查的预算匹配。V2 的复用 head 后重置状态可能引入读出分布失配；V3 的 reset-native 重新拟合，减少了这项诊断混淆。即使 native 与 reset 的动作明显不同，也只证明状态影响行为，仍须由 native−history 的实际收益比较判定其增量价值。

## 5. 两层组合收益与超加性交互需要区分

用户提出的六类实验问题被具体化为冻结的十一臂：既检查普通训练和 field 训练，也检查 frozen/ordinary/field 模型上的运行控制，并保留历史、当前状态和重置对照。[实验臂与六项主要比较](PROTOCOL.json)。

其中 C−B 检查同一固定部署策略下的训练增量；E−C 检查 field 模型上的 native 控制增量；E−G 检查 native 部署算法下 field 相对 ordinary 的差异；E−F 检查 field 模型上的 native 相对 history。各检查点的运行 head 独立拟合，因此 E−G 包含训练后 head 适配的中介作用，不能被表述为严格固定全部下游权重后的纯参数场效应。

即使这些比较通过，“两层均有增量”也不自动等于超加性协同。更强的交互问题对应 \((E-C)-(D-A)\)。它不是 V3 六项注册主要比较之一，本研究不会把事后交互计算升级成确认性结论。

## 6. 训练、审计和最终任务之间没有自动等价关系

学习资格检验使用历史固定单动作输出任务；运行与最终确认使用新构造的三次决策反馈任务。即使学习 gate 通过，也只能允许继续检验转移，不能直接宣称反馈任务上的 C−B 已经成立。反馈来自预先定义的模拟外部 verifier，控制器只收到局部反馈；这也不等同于真实用户、长期跨任务反馈或生产环境。[反馈任务和访问边界](feedback_task.py)、[协议独立评审](../field_bridge_v3_20261027_review/PROTOCOL_REVIEW.md)。

23 个互斥 source roles 将拟合、开发、审计和最终评估分开，并排除全部已登记的 V2 图像身份。源角色的身份分离和已执行阶段的访问边界均通过核验；独立学习审计与最终评估仍未开启。该核验没有证明新的书写者独立性、未知预训练数据独立性或 LLM 总体泛化。[最终源身份核验](../field_bridge_v3_20261027_review/FINAL_SOURCE_ROLE_AUDIT.json)。两套 observer 都参与开发资格判断，因而第二套是不同测量模型，不应称为开发阶段完全盲的结果模型。

## 7. 成本需要覆盖找出策略的代价

完整 Qref bank 本身需要 51,840 个梯度微步；reference、development、方向探针、teacher、guard、回滚丢弃的计算和独立验证另记。普通方法在实验中接受同样的完整 30 维测量，以统一实验记账和审计；普通固定倍率训练本身不需要这些测量。因此不能把共同探索总成本当成 ordinary 的最小实现成本，也不能把已经共享的 bank 重复收费。[协议成本约束](../field_bridge_v3_20261027_review/PROTOCOL_REVIEW.md)、[训练调用计数](training_common.py)。

运行的 0.002 是注册效用中的逻辑动作费用，不是测得的毫秒、能量或货币成本。native 的原生执行、Python 特征与 head、媒体序列化、observer 和 verifier 开销需要分别报告；同一共享主机上的并发 wall 时间只能作描述性数据。拟合时完整树的 85 个节点属于同一个 episode 的反事实输出，不能冒充 85 个独立样本。

## 8. 对论文与系统工程的具体建议

论文最适合为 Hepta 提供的是“先写明完整状态、信息集、执行器、未来价值，再分别核算误差”的研究纪律。系统接口可以保留完整优化器／运行状态的可恢复记录，而把紧凑摘要作为可替换的决策表示；何时允许该表示控制，交由独立资格检验决定。V3 的 frozen source、真实交付、完整状态回放和 gate 就是这个接口的有限实例。

本实验没有求解或验证论文的 Riccati、HJB、FBSDE、标量系数识别或 switching 假设。论文的预训练模块实验与这里的构造 MNIST 多模态任务也不同，不能互相替代。[R45 的模块范围和未执行识别检验](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)。

最终应分别报告：可执行与可复现是否成立；资格门槛是否通过；在通过资格后，主要比较和独立保留能力是否成立。若某个 gate 失败，保留完整失败结果并停止它控制的后续阶段。继续调整特征、目标或样本直到通过，会破坏这条证据链。所有研究运行始终为 `DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false`；研究 readout 拟合不授予生产 owner 权限。[原生构建回执](evidence/NATIVE_BUILD_RECEIPT.json)。
