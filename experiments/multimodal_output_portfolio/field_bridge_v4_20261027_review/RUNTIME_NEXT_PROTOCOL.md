# Runtime 诊断、负向 pilot 与下一步边界

状态：**EXPLORATORY_COMPLETE；本轮 runtime 候选不推进新 holdout。** 本文基于已公开的 V3 runtime_fit、runtime_select 与 runtime_audit；不是新预注册，不改变 V3 的失败判定。权限仍为 `DENY_ALL`，`requires_calibration=true`，`native_owner_integration=false`。

## 1. 结论与证据范围

这次已经排除两个具体解释：native 状态没有参与计算，以及只需把共同 baseline 从各动作 target 中减掉就能改善策略。实际 native 状态持续改变特征和动作；它在 V3 selection 的三个模型上均落后同信息 history。现有证据支持“这组表示、拟合与任务上的增量价值未成立”，不支持“所有 Hepta 状态控制无效”。

现有选定策略在审计 reward observer 上的收益明显高于 audit observer；差值来自两套图像评估输出，不是 text/relation/pixel 项或修订成本。这个分解定位了观测差异，不能单凭它判定 reward hacking、评估器缺陷或某个因果机制。

本轮实际执行一个有明确假设的小型修复：按 source pair 将三阶段拟合分开，冻结后续头，再生成前一步的 own-policy continuation target；不在生成标签后全量 refit。6 个模型×表示组合在原 selection 上全部退化。因此该候选本轮停止推进；不继续换 split、盐、λ 或候选族来挽救结果。额外执行的 3 个 raw-history 线性参照也没有稳定胜出。

全部数字来自 [RUNTIME_DIAGNOSIS.json](RUNTIME_DIAGNOSIS.json)，可执行实现为 [runtime_diagnosis.py](runtime_diagnosis.py)，9 个候选的完整参数保存在 [RUNTIME_PILOT_CONTROLLERS.json.gz](RUNTIME_PILOT_CONTROLLERS.json.gz)。JSON 的 `input_files` 记录全部 16 个实际输入文件的 SHA256 与字节数，`source_sha256` 绑定脚本；`pilot_parameters` 绑定候选参数。旧实现见 [runtime_controller.py](../field_bridge_v3_20261027/runtime_controller.py) 与 [native_stream.py](../field_bridge_v3_20261027/native_stream.py)。

V3 的已公开 runtime_audit 此后属于开发证据；不能在调参后再次充当新的确认数据。本轮没有访问或执行 primary、retention、未开学习 audit，也没有运行新模型、observer、native 内核或网络任务。

## 2. Selection 本来就没有支持 native 的增量价值

每个模型的 selection 为 64 个 source pair ×4 个条件，共 256 棵完整树。下表值是原先已选控制器的 reward 净效用，越高越好。

| 模型 seed | 固定策略 | History | Native | Native − History | 事后树 oracle − 固定 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 17 | 0.7719673321 | 0.7777227326 | 0.7751234841 | −0.0025992485 | 0.0582104592 |
| 29 | 0.8090493610 | 0.8101052208 | 0.8073954057 | −0.0027098151 | 0.0240977803 |
| 43 | 0.7456283311 | 0.7544081867 | 0.7499085791 | −0.0044996076 | 0.0400563115 |

因此，“只要增加 audit 样本就会成功”没有现有开发证据支持。全部源对平均的小正点差也不能消除逐模型方向不一致。

这里的 oracle 是每棵已生成树的 85 个节点输出中，事后选取最高净效用。它接触实际部署控制器不可见的未来结果，只给出已生成树上的 hindsight 上界；它不证明这些机会能从允许的信息中识别、学习或泛化。未选 runtime_audit 分支不存在于数据中，本轮没有估计或补造这些反事实。证据：JSON `banks[*].banks` 与 `banks[*].selected_comparisons`。

## 3. 状态是活跃的，但活跃不等于有益

Native 的输入为 48 维因果历史加 40 维 activation/eligibility 状态，共 88 维；history 同样为 88 维，由 48 维历史与固定 Fourier 特征组成。在相同 transform 下，native 与 reset-native 的 stage 0 特征完全相同；stage 1 的 2,048 行与 stage 2 的 8,192 行中，三模型的额外状态特征均发生变化。其 RMS 差异分别为 seed 17 的 0.2540/0.3906、seed 29 的 0.2014/0.2483、seed 43 的 0.4012/0.4375。

Native 额外 40 维的标准化协方差有效秩，按 stage 0/1/2 排列，为 seed 17 的 13/24/27、seed 29 的 27/31/33、seed 43 的 23/31/32；participation ratio 约为 5.95–13.55。History 额外维度的协方差秩均为 40，但 participation ratio 也只有约 4.55–15.55。有效秩描述不同，不构成两类表示统计容量相等或 native 容量不足的证明。

在冻结头上，仅把 native 额外特征替换成训练均值，就会改变 selection 已有状态中约 51.5%–79.1% 的动作。这是后验敏感度分析，不是重拟合后的公平 ablation，不能把它计入增益或因果证据。真正审计中 native/history 只有 1,356/6,144 个完整动作路径一致。证据：JSON `selected_features`、`matched_native_reset_extra` 与 `audit.comparisons.native-history.same_action_paths`。

## 4. Audit 差异集中在哪些观测

每个源对先在固定的 3 个模型×4 个条件内平均，再计算下表 SD；独立抽样单位为 source pair，不能把 6,144 条配对 episode 当成独立样本。数值只是对已公开审计的诊断，不是新的显著性裁决。

| 比较 | Reward 平均差 | Audit 平均差 | Reward 源对 SD | Audit 源对 SD |
| --- | ---: | ---: | ---: | ---: |
| Native − Fixed | +0.0068946332 | +0.0008399457 | 0.0333210119 | 0.0320296396 |
| Native − History | +0.0009548572 | +0.0001980213 | 0.0281478738 | 0.0283895395 |
| Native − Reset | +0.0003865527 | −0.0012736036 | 见 JSON | 见 JSON |

Native − History 的逐模型差值，在 reward observer 上为 `[+0.00357914, −0.00311059, +0.00239602]`，在 audit observer 上为 `[−0.00081539, +0.00167457, −0.00026511]`。Native − Reset 在 audit observer 的三个模型上均为负：`[−0.00099141, −0.00112428, −0.00170513]`。后者是额外的描述性对照，不增加一项事后注册检验。

净效用由 `1 − 2 × joint_loss − 0.002 × (1 + revisions)` 构成；`joint_loss` 权重依次为 image_fact 0.35、text_fact 0.30、relation 0.15、crossmodal_disagreement 0.10、pixel_mse 0.10。这里 `image_fact` 等记录的是 loss，不是 accuracy。

Native − Fixed 的 reward 与 audit 差值相差 0.0060546875，其中 image_fact 贡献 0.0038736979，crossmodal_disagreement 贡献 0.0021809896。Native − History 的对应差值为 0.0007568359，其中 image_fact 贡献 0.0007405599，crossmodal_disagreement 贡献 0.0000162760。两套 observer 的 text/relation/pixel 项相同，成本也相同。分解是净效用公式的代数恒等式；不能由此辨认是哪一 observer 更接近真实世界事实。证据：JSON `audit.comparisons`。

## 5. 真实执行的 source-disjoint stage pilot

假设是：同一源对反复用于后续头拟合及前一步 target 生成，可能产生对训练 continuation 的过度适配。V3 已经按最终选定的后续策略形成 own-policy target，没有发现“用了 max oracle 冒充自己的策略”的 Bellman 实现错误。因此这里是统计设计探索，不是已证实 bug 的修复。

每个模型原有 128 个 training source pair。用固定 SHA 盐与 source identity 分组，整对不拆分：stage 2 使用 43 对，stage 1 使用另 43 对，stage 0 使用剩余 42 对，分别形成 2,752、688、168 行拟合数据。后续头完成后冻结；前一阶段标签沿该候选的冻结尾部策略求得。最终部署也使用同一组冻结头，不进行全量 refit。脚本断言反向 continuation 值与最终前向 rollout 完全一致。

每个 native/history 表示只保留 V3 已选 transform 与 λ=1；每个模型仅一个 stage 分割。两类表示各 88 维、1,335 个 head 系数。该划分减少了单阶段训练源数，不能把结果解释成同等每头样本量的比较。它使用了此前已经被选过的 transform 与已公开 selection，所有结果都是 exploratory。

| Seed | Honest History − 原 History | Honest Native − 原 Native | Honest Native − Fixed | Raw History − Fixed |
| --- | ---: | ---: | ---: | ---: |
| 17 | −0.0179714029 | −0.0089906874 | −0.0058345354 | −0.0123151225 |
| 29 | −0.0033615947 | −0.0056963146 | −0.0073502699 | −0.0034845473 |
| 43 | −0.0051597299 | −0.0124910181 | −0.0082107702 | +0.0064209281 |

Raw-history 参照仅使用 48 维原始历史、735 个 head 系数、固定 λ=1，各模型一个候选；不搜索宽度或正则。全部 9 个参数与结果均已保存。6 个 stage 分割候选全部劣于对应 V3 策略，且 native 全部劣于固定策略。判定为 **pilot 未支持；不推进本候选至新 holdout**。不能从这个低样本量负向 pilot 推导所有 source-disjoint 方法无效，也不能因为有这个可能性就持续加候选。

原 history/native 的 18 个 ridge head 已从保留特征精确重建，系数最大误差为 0，选定 terminal node 一致。其余旧策略的冻结 rollout 也与原记录一致。本轮没有发现可归因于旧 rollout 未执行或参数未读取的错误。证据：JSON `banks[*].offline_pilots`。

## 6. 共同 baseline 中心化不会产生新策略

固定特征、normalizer 与 λ 时，共用 ridge 算子 `L=(ZᵀZ+λP)⁻¹Zᵀ`。原系数为 `B=LY`；若每个动作 target 都减去同一 source-wise baseline `b`，新系数为 `B′=B−(Lb)1ᵀ`。每个动作预测减去同一个数，argmax 不变，除浮点数 tie 外行动和完整 rollout 不变。

因此，单纯把 reward target 改名为相对 stop 的 advantage，既不扩大当前候选策略集合，也不能构成控制改进。如果未来使用动作相关加权、非线性约束或不同 penalty，则已经改变了假设与算法，必须单独注册，不能援引这个不变性结论。

## 7. 下一步设计与不推进规则

### 本轮明确执行到的边界

Runtime 诊断与最小候选探索已完成。原 V3 两项 runtime gain 未通过的事实继续有效；本轮没有新 runtime gate 通过记录。候选不推进，原 primary/retention 与学习 audit 的执行权不由本文授予。学习层可由独立新协议推进；不能把学习层 qualification 成功写成 runtime 成功。

必须保留当前六个负向 stage 结果和三个 raw-history 结果。不从 audit 中挑有利 observer、模型、条件；不把后来有利的条件改成主 endpoint；不因接近阈值而顺延样本数。审计条件下未选动作的结果不可识别，不能把 fit/select 树的反事实当成新观察。

### 条件方案：仅用于研究单阶段样本损失，尚未注册、未启动

若未来仍有独立科学理由专门检验 source 分割的数据量混杂，一个有界设计为：新 development fit 384 个独立 source pair，固定分成 3×128 对；新 select 128 对；4 个原条件、3 个固定模型、每树 85 个节点。总计 6,144 棵树、**522,240 次逻辑输出**。两 observer 均对全部输出评分时，为 **1,044,480 次 output-observer 评估**。这些是节点工作量，不能替代实际 batching、encoder、native tick、内存、时长及失败尝试成本账本。

固定的比较为 original all-source native/history 与 source-disjoint native/history，各模型各 4 个控制器，共 12 个；所有 λ、transform、分组盐、ties、停止规则在新标签前锁定。每个阶段仍冻结后续头，部署不全量 refit。强 all-source history 必须获得相同的全部 384 个 fit pair；不能只给它 128 对来人为制造公平。分割 native 与分割 history 使用同一源对、信息与模型预算。原固定策略与原 current/reset 策略作为冻结描述性参照保留，不从结果中重新选择较弱对手。

一个严格的 development 推进条件是：source-disjoint native 相对 all-source history、source-disjoint history、all-source native 的差值，在两个 observer 上均为正，且三个模型逐一同向；clean 相对固定策略不劣。除此之外必须证明成本、源身份、动作集与 own-policy 一致性。这个条件不等于确认显著性。若任何一项不满足，就结束这一个固定设计，记录全部结果，不自动增加源数或候选。**现有 pilot 没有满足这些条件，当前不启动该方案。**

任何真正的 confirmation 还需先独立冻结新目标人群、未使用 source role、observer、所有比较与校正、最低有用增益、clean 非劣界、bootstrap 单位、固定样本数和失败规则；随后一次执行。本文没有指定一个已经获准运行的 confirmation，也不替代原门槛。若未来更换模型 checkpoint，其 readout 必须独立重拟合并完整记账，不能把旧 readout 中介效果混入学习参数的因果效应。

### 固定样本量只提供规划尺度

以下按源对 SD 估算固定模型/条件、单个 comparison 的 normal approximation，使用 V3 的每 observer 四比较校正：`N=ceil(((z_(1−0.05/(2×4))+z_power)×SD/δ)²)`。没有用 selection 后点差承诺真实效应；δ 是规划的最低效应假设。

| 比较与 δ | 80% power：Reward / Audit 源对数 | 90% power：Reward / Audit 源对数 |
| --- | ---: | ---: |
| Native − History；0.001 | 8,836 / 8,988 | 11,317 / 11,512 |
| Native − History；0.002 | 2,209 / 2,247 | 2,830 / 2,878 |
| Native − Fixed；0.001 | 12,381 / 11,440 | 15,859 / 14,653 |
| Native − Fixed；0.002 | 3,096 / 2,860 | 3,965 / 3,664 |

90% 每 observer 至多给一个 comparison 的双 observer 联合成功率约 80% 的粗略 union-bound 规划，不保证两项 gain、逐模型同向、clean 非劣与全部门槛的联合功效。4,096 对也不能被称作整套协议 80% power。更多源数无法把真实负向的模型效应变成正向。证据：JSON `audit.comparisons.*.fixed_n_normal_approximation_per_observer`。

## 8. 复现、成本与冻结

脚本只依赖 Python stdlib 与 NumPy；不导入模型框架，不调用原 native 库。所有输出文件以 exclusive create 写入。恢复原 16 个输入文件至绑定路径后，可使用新的输出文件名重新执行：

```bash
OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 python runtime_diagnosis.py --run /tmp/hepta-field-v3-run --output /tmp/RUNTIME_DIAGNOSIS-reproduction.json --controllers /tmp/RUNTIME_PILOT_CONTROLLERS-reproduction.json.gz
```

本轮实际脚本运行：45 次 ridge 求解（18 次重建、18 次分割 pilot、9 次 raw-history pilot），144 次协方差特征值分解，读取 2,304 棵既有树与 30,720 条既有 audit 记录。wall 5.741947810 秒，CPU 5.727913510 秒；新增 generator/observer/native/network 调用全部为 0。此前 schema 与概要读取没有计时，不能将这些读盘工作包含在这一个 wall 数字中。一次正常 sandbox 启动曾因磁盘空间不足在进程启动前失败，未发生科学计算；文件版实际运行首次完成。

冻结文件 SHA256：

| 文件 | SHA256 |
| --- | --- |
| runtime_diagnosis.py | c69a0368d55c0a28dcdc0e1b175d786b0dd067a7d6530ba101813c91bdfbc462 |
| RUNTIME_DIAGNOSIS.json | 638ce04cd3c8baf2442fd15d292fea3814ddbd596a16ce757c36c15ee44d9a34 |
| RUNTIME_PILOT_CONTROLLERS.json.gz | 20556b183c80cd6f8af0e9bf06ab12ed83411563fe4cb6e4cec5fcc81b3cfebe |

旧源、门槛、冻结结果与内核权限没有改写。诊断和负向 pilot 的可复现性闭合了“为什么没有推进凭据”的调查事项；科学效应本身仍未成立。
