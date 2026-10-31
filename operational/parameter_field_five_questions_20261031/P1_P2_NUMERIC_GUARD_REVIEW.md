# P1/P2 只读审计与数值防护候选

状态：**准备完成，尚未登记为新运行，也未安装到任何实际科学实验。**
基础版本为 `c27e1b2c291dc213b4a34bb41360235013c909e0`。本目录只新增 operational 文件；没有编辑旧科学代码、阈值、动作、样本或标签。

## 1. 已核对的科学接口

| 问题 | 固定源中实际实现 | 证据位置 |
| --- | --- | --- |
| 四动作是否来自同一合法 parent | 每个动作执行前恢复同一 sealed bytes；完成首个动作后执行同一 seed 的普通 baseline 到 clock 288 | `experiments/parameter_field_fullstudy_20261029/bank.py` 的 `build_bank`，尤其 68–85 行 |
| 标签是否对齐 baseline、时钟、预算、guard | `advantages = action_values - action_values[baseline]`；baseline 是 seed 17→2、29→3、43→3；相同 `guarded_block`、剩余 tape、48 步决策粒度 | `bank.py`、`branching.py`、V3 `learning.py::guarded_block` |
| 拒绝动作是否被当成免费重试 | guard 拒绝后恢复优化器/参数等，外层 `clock += 48`；已消耗梯度工作不回滚 | `branching.py::transition`、V3 `learning.py` |
| 是否有完整恢复 | checkpoint 包含参数、buffer、梯度的 None 状态、优化器、RNG、immutable context、cursor、remaining schedule、history；恢复后重新序列化须与原 bytes 完全相等 | `branching.py::capture/validate/restore` |
| 是否把 hash 不同当成有用控制 | report 已分别列 complete hash、parameter/optimizer、仅其他分量变化；注明 incoming-gradient 差异可能在下一次清梯度后消失 | `report_results.py::bank_diagnostics` |
| 全成本是否含失败/零动作 | 零 multiplier 仍计算梯度并收费，拒绝事务仍收费；分支子账从 restore 之后开始，整个 context 账包含恢复；二者不能混当同一总计 | `bank.py`、V3 `learning.py`、`branching.py::timed/restore` |

上述是源码审计，不是完整 A/B/C/W/R 科学运行成功的声明。特别是原始 raw evidence、逐 parent clock/tape 和 R 的完整 replay 仍须通过既有门槛，不能从 aggregate 摘要推断已完成。

## 2. 已有 supplement 覆盖标签复核，不再重复实现

初看原 `report_results.py::bank_diagnostics`，它本身只检查 baseline advantage 为零和 prefix replay 标志。但是后续既有 `supplements/parameter_field_fullstudy_20261030/postseal_supplement.py` 已补齐：

- `bank_analysis` 检查每个 seed 的 48 个 parent 及其预定顺序、baseline、prefix replay。
- 逐条重算四动作 `advantage = value - baseline_value`。
- 读取绑定 NPZ 的 `values_reward`，检查有限性，重新取均值并与 `action_values` 比较。
- `equal_dynamics_checks` 比较 branch.value 与 action_values；同一 first dynamics 下还比较 components、terminal dynamics、标签、输出 hash 向量、source/condition 行身份。
- `calibration_analysis` 核对 head 数组、metadata、36/12 分割、维度、ridge、threshold、head bank 的 features/advantages/fit mask，并使用原始 chooser 计算 gated calibration 指标。

因此不新增一个重复 label 核对器。剩余区别应保留：以上核对不等同于重新运行完整恢复/训练 replay，也不能证明新未完成任务的真实效应。

## 3. 确认的数值边界缺陷

原始 `heads.py::predict` 只校验输入 feature 有限，未对标准化后的 z、scores、norm 或加载 head 的数值契约逐一 fail closed。`choose` 对唯一最大值执行 `margin > threshold`。有限数相乘仍可上溢。

使用**原始源码字节**与原 pinned Python/NumPy 的合成实测：mean=0、scale=1、feature=[2]、action 0 的 coefficient=1e308、其他 coefficient/intercept=0、baseline=2、threshold=0。输入及 head 数组全部有限，原 chooser 返回 action 0、override=true、predicted_margin=+Inf。

原 `run.py` 随后调用 `adapter.transition(action)`，在整个路径结束后才写含 choice 的 JSON。`allow_nan=False` 会拒绝 Infinity，因此不能据此声称该缺陷能形成有效的最终 COMPLETE 或已造成历史正结果误报；实际缺口是非有限决策可先触发学习事务及额外成本，再在序列化时失败，违反即时停止的数值完整性要求。

**没有证据表明历史科学运行触发过此情况。** 本例是有区分力的工程边界测试，不是历史 checkpoint、真实模型输出或新的科学胜出证据。

## 4. 最小 operational overlay

`finite_head_guard.py` 提供：

- `validate_head`：检查形状、finite arrays、正 scale、结构性零 baseline、有限且非负 threshold/fit norm bound。
- `guarded_choose`：校验 feature；在局部 NumPy 错误策略中只调用原 chooser 一次；返回前检查所有预测优势、margin、norm、threshold 有限。BLAS 未抛 arithmetic warning 时也由 receipt 检查捕获。
- `installed_choose_guard`：**显式 context manager**。先核对原 `heads.py` SHA256；从验证过的原 bytes 受控编译 reference，核对已加载 choose/predict 的代码、defaults、closure、所属 globals 与 NumPy binding，拒绝预先内存替换。run 与 heads 必须是不同模块。仅在 context 中替换传入 run 模块的 `choose`；退出时先恢复原对象，包括异常退出；若 context 内最终绑定被另改则抛 integrity failure。导入本模块不会自动启用。

调用方式由一个未来单独登记的 operational launcher 明确执行：

```python
with installed_choose_guard(run_module, frozen_heads_module) as guard_receipt:
    registered_scientific_entrypoint()
```

这只是接口示意；当前没有修改 launcher、ProducerAdapter、C2 或其他科学路径。使用前还要验证该 entrypoint 实际引用的就是传入 run 模块，以及新的 source closure 接受已登记的 overlay。

在满足既有契约且所有预测中间量/receipt 均有限的域上，原 chooser 只执行一次，原 action 和 receipt 原样返回。阈值边界、并列时回到 baseline 的规则、校准数据和标签全部保持。数值检查不消耗 RNG、不修改输入数组或训练状态；NumPy 错误策略在成功和失败时都恢复。全流程会多消耗验证 CPU/墙钟，因此**成本和元数据不是逐字节不变**。

任何 guard 命中须作为 integrity failure 停止阶段、保存既有失败与成本证据。不能把该异常转换成 baseline fallback 再统计成成功路径。

## 5. 新 operational freeze 策略

1. 保留原科学 freeze 与其中全部 167 项原字节/哈希。不得把 overlay 写进旧文件后更新旧哈希，也不得覆盖旧运行身份。
2. 新候选 freeze 明确绑定旧科学 freeze 身份、基础 commit、overlay/test/launcher/integration 的完整新 SHA256、依赖环境、目标模块和绑定位置。状态应保持 prepared，直到既有资源、来源与发布门槛真实满足。
3. 启用前再次校验旧 167 项字节未变；验证新的额外 source closure。明确这是新 operational admission guard，不把“旧源字节未变”说成“执行流程完全未变”。
4. 在 entrypoint 启动前做 head admission 只能检查已有输入；不能代替每个新 feature 的动态检查。必须在原 choose 返回到调用方、执行 transition 之前放置 wrapper。
5. 对本接口的适用范围，当前是原 A/B `run.py` 的三个 adaptive head，而不是普通 baseline，也不是未经验证的 C2、其他架构或所有 producer。一次完整 A seed 应有 72 次 adaptive chooser 调用，B seed 为 288 次；未来 integration 需记录/核对实际覆盖。
6. wrapper 内工作自然计入原 `head_decision` 计时；安装和文件校验成本另进入 operational 总账。原梯度、资源与停止上限保持，额外开销可能使运行更早触及原资源门。
7. 科学输出和 endpoint 开放仍遵守原完整 population/barrier。当前 credential upload 审批和资源阻塞均未因这个补丁解除。

## 6. 精确源码身份与验证

原文件：`experiments/parameter_field_fullstudy_20261029/heads.py`。

- 固定 Git blob：`27c9e98d1039fbc06b1c68d88161ee8bc3bc4998`。
- 字节数：5571。
- SHA256：`19254959a30e3719024841dc91376d1ecdfa018c30427b962a265e3b3d4647f7`。
- 旧完整 checkout 中该文件精确匹配。`review_cache/heads.py` 只多一个末尾换行，5572 字节；没有用这个缓存充当 exact 源，也没有修改它。

`test_finite_head_guard.py` 仅加载核验过 SHA256 的原 `heads.py`，不导入 torch、不读科学资产、不训练。当前 13 项测试全部通过，覆盖：原始有限乘积溢出复现；transition 前停止；标准化和范数溢出；错误 head 提前停止；无 arithmetic warning 的非有限 receipt；严格阈值/并列结果保持；原 chooser 只调用一次且结果对象不替换；输入/RNG/错误策略不变；context 成功与失败均恢复绑定；拒绝已加载 choose/predict 替换、相同代码但不同 globals、run/heads alias，并在 context 绑定篡改时恢复后报错。

第一次测试执行有一项合成 fixture 的序列化错误：`np.nextafter` 留下的 NumPy scalar threshold 与实际 fit/load 返回的 Python float 类型不同。仅将 fixture threshold 按原 fit/load 的真实类型转为 float 后，第二次 9/9 通过。随后按独立审查加入代码身份/context 绑定检查及对应测试，当前 13/13 通过。原科学源码和候选 wrapper 均未为消除该 fixture 错误而更改科学算法。

验证命令（只读旧源码，在当前工作副本中执行）：

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python \
  operational/parameter_field_five_questions_20261031/test_finite_head_guard.py \
  --frozen-heads /workspace/scratch/178ced6a501f/fullstudy_recovery06_git/experiments/parameter_field_fullstudy_20261029/heads.py -v
```

13/13 仅是该补丁的工程验证；并非 P1/P2 真实科学结果，也不是实际运行已受该 guard 保护的证据。
