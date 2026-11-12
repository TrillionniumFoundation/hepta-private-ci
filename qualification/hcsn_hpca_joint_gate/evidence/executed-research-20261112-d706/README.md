# HCSN / HPCA 本轮实际执行与证据边界

本页索引本轮各自固定源码的实际执行结果。整体科研准入继续为 **HOLD_NO_GO**。
数值共同源、uniform Torch 梯度、旧 C2 checkpoint 恢复、HPCA 内容头有各自的源码身份；
本页保留这些边界，不赋予跨分支的联合模型资格。

## 已改变的证据状态

| 工作 | 本轮已观察到的结果 | 结论范围 |
|---|---|---|
| 原访问域迁移与续值 | 同一新共同源，原 14,336 个位置在 256 / 512 网格都为 0 失败 | 原 1% scaled continuation 工程门槛通过 |
| DDE 历史与恢复 | 28 项无 skip 测试、真实新进程恢复、30 次直接 DDE 积分 | 声明的数值状态与固定 fixtures |
| 原生 Torch 梯度 | native 与 hosted 分别完成 6 项无 skip 检查 | 小型 uniform CTMC / delay / reset 流 |
| 六 checkpoint 恢复 | 本 attempt 实际 26 次 optimizer 调用，六组完整声明状态逐位一致，两个负对照通过 | 每组两步的旧 C2 恢复诊断 |
| HPCA 内容训练与生成 | 64 次训练 prefill、4,096 次手工 SGD 槽位、1,632 次主生成 | 冻结 SmolLM2 上的两个输出头开发实验 |
| HPCA 冷恢复 | 204/204 实际新进程生成，tokens / text / features / head delta 逐条一致 | 固定 12 题 × 17 条件 |

## HCSN：原域后继通过结果已经存在

执行源为 `9f6c7c4dc24510472ca012647ebd1d96c1405c69`，先发布并读回源码，再实际执行。
证据提交为 `672184fa5f51c5d658167a01b1c9be9668e383bb`。
这次把 canonical migration 绑定、persistent DDE state 与原域审计放在同一源上重新运行；
此前分支的 PASS 没有计入新执行。

原门槛保持：`abs(candidate - original_continuum) / max(1, abs(original_continuum)) <= 0.01`。

| 网格区间数 | 原位置数 | 失败数 | 最大 scaled error | 最大非抵消 scaled error |
|---:|---:|---:|---:|---:|
| 256 | 14,336 | 0 | 1.5874878671907167e-5 | 1.5874908044083096e-5 |
| 512 | 14,336 | 0 | 4.009563388424706e-6 | 4.009592859123869e-6 |

每个位置的 prior / posterior 都保留。全部位置使用同一离散生成器的线性 first-excursion
核评估；有限时 M/H/A 的 gaps 为 0.001–0.16，均小于 delay 0.2。
另有预定的 30 次 `JointModel.solve` 直接积分、210 条 query records，
与谱核的最大差异为 `2.091088413536113e-11`。

共同源的 28 项测试无 skip；真实冷恢复从绝对 clock 0.417 继续到 1.0，
最大通道差异 `7.671177582047051e-11`。这是容差内的数值恢复。
两条执行 lane 合计 wall 275.368 秒，source / protocol 的 18 项 guard 前后一致。

新网格是在已暴露域上做的工程修复。原 14,336 个位置没有逐一跑长时多次 reset DDE，
冷恢复也没有逐一覆盖全部 posterior；递归观测更新、完整新核训练与域外尾部资格仍未建立。

[共同源原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/672184fa5f51c5d658167a01b1c9be9668e383bb/qualification/hcsn_joint_dde/evidence/common-source-20261112-d706/attempt001/RESULT.json)
· [冻结协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/672184fa5f51c5d658167a01b1c9be9668e383bb/qualification/hcsn_joint_dde/GRADED_PROTOCOL.json)
· [PR #6174](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6174)

## 梯度：六个物理参数与初始 law 已有真实检查

另一路 native Torch finite renewal cascade 保留边界、drift、sigma、绝对 reset、delay、discount，
以及初始概率、signed content、phase mass / content / support 的计算图。
六个物理参数在一个内部 fixture 上做全输出 Jacobian gradcheck；初始 law / phase 做投影检查。
七个输出字段与独立 SciPy DDE 对照，最大差异 `1.6504300530406635e-11`。

执行源为 `19b7a99f6d63596dd77c34a1ed8e529e1c744750`；native 6/6、无 skip。
hosted run `43169226255` 精确 checkout `f8bf0070a96975bd8c636f4ef72926b131bce372`，也完成 6/6。
原四文件 ZIP 已完整下载并核对 GitHub SHA256，六项执行源 hash 与 native 相同；
原件保存在证据提交 `28196265803a81d69041ad6a106e581456f3e360`。

它仍是小型 uniform 网格 oracle。上述梯度结果不为另一条 graded 原域源码赋予端到端 AD 资格。
这两条新核数值路线实际神经网络 optimizer 调用仍为 0。

[梯度原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/28196265803a81d69041ad6a106e581456f3e360/qualification/hcsn_joint_dde/CASCADE_AUTOGRAD.md)
· [PR #6150](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6150)

## C2：26 次现在是已执行的窄恢复实验

固定执行源 `5cb83d9c76beedf4c1c917e4bf561f5f26261ce7` 使用六份真实原 C2 状态，
epoch 为 116 / 76 / 126 / 50 / 127 / 72。
每组比较：新进程连续两步 reference，与一步 producer 发布后由另一个新进程恢复再走一步。
模型、Adam、Torch RNG、order RNG 与 cursor 的完整声明状态六组全部逐位一致；
六对最终 Torch 文件连 SHA256 也相同。

本 attempt 调用计数为 `6 × (2 + 1 + 1) + 1 + 1 = 26`。
两个额外调用分别用于省略 Adam 状态、真实 Torch-save / fsync 后但 canonical 发布前崩溃。
独立审计脚本实际解码 26 份状态文件、核对 Adam counter 与 554 个绑定输入；
26 份文件包含六份 origin，文件数量本身不是 optimizer 调用数的依据。
这份审计额外模型 forward / optimizer 调用均为 0。

本 attempt 外层 wall 为 905.761 秒；CPU user 1,474.17 秒、system 157.19 秒。
GNU time 的最大 RSS 3,655,716 KiB 是所报告的单进程高水位，不是并发内存总和。
128-member / 10,976,581-byte 原 ZIP 已归档，SHA256 为
`d17e71b766631f3789dcb43bdd312dacfbc4ea0ce7e4fc14074587584900a2fe`。
包内含本 attempt 输出与六份 origin；554 个外部训练 / 源输入通过原 PREEXECUTION hash 绑定，
不把它称为完整可移植训练数据包。

**新增完整独立 C2 训练重放仍为 0。** 旧 C2 完成状态没有被改写。
另一路 c06d v1 / v2 已取消尝试的调用数继续为 UNKNOWN；本次 26 不是所有历史尝试的总成本。
[此前取消尝试原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a832b028abdf1a1c9ab66534332457c6d76a91ca/qualification/hcsn_differentiable/evidence/real-checkpoint-replay-native-20261112/ATTEMPTS.json)

[恢复诊断原件](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/afa7415d5a740a59bb436cdb90bb157be6f450bf/qualification/hcsn_differentiable/replay_v1/evidence/native-desktop-20261112-d706/INDEPENDENT_AUDIT.json) · [完整 attempt ZIP](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/afa7415d5a740a59bb436cdb90bb157be6f450bf/qualification/hcsn_differentiable/replay_v1/evidence/native-desktop-20261112-d706/NATIVE_ORIGINALS.zip) · [PR #6199](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6199)

## HPCA：真实输出已改变，本配置未建立稳定内容改善

固定源 `b0ea141de2d5218869823b2d9e075db6d7b215dd` 在模型执行前冻结并逐文件读回。
独立静态审查发现的 template / answer 混淆在首次模型执行前修正；未执行的旧准备源保留在历史中。
这轮使用冻结 SmolLM2-135M body / LM head，加两个可训练线性输出头来改变首 token 的 Yes/No logits；
整个词表仍参与贪心选择。它验证输出头学习，不涉及全 LM 或 LoRA 重训。

64 个训练 prompt 只需 64 次实际模型 prefill；四个 seed × 四臂共 16 个候选。
4,096 次手工 SGD 槽位中 3,072 次非零，1,024 次为 no-eligibility 零更新对照；Torch optimizer 调用为 0。
主评估为 17 条件 × 96 题 = 1,632 次实际生成，全部执行完成，执行失败为 0。
答案有效性和正确性另计，invalid 仍留在固定分母。

每个 seed 都评估相同的 64 个 content 开发题：

| 训练顺序 seed | 正确路由 | 打乱路由 | 无 eligibility | scalar 投影 |
|---:|---:|---:|---:|---:|
| 11 | 27/64 | 29/64 | 32/64 | 24/64 |
| 17 | 32/64 | 32/64 | 32/64 | 32/64 |
| 23 | 24/64 | 24/64 | 32/64 | 24/64 |
| 29 | 37/64 | 33/64 | 32/64 | 32/64 |
| 四次评估合计 | 120/256 | 118/256 | 128/256 | 112/256 |

Base 为 32/64。正确路由相对打乱的逐 seed 正确数差为 −2 / 0 / 0 / +4；
合计仅多 2 个正确答案，且均值低于 base。
正确路由的 content valid 为 233/256，打乱为 236/256，base 为 64/64。
四个 seed 是训练顺序重复，不能把 256 次评估称为 256 个独立未来任务。
四个 no-eligibility 条件的全部 96 条 tokens / text / feature hash / delta 都与 base 相同。

正确路由与打乱路由使用相同的完整二坐标反馈向量。Scalar 对该向量取均值，改变了信息量，
单独作为信息消融，不作为纯路由对照。

Retention base 只有 8/32 correct、14/32 valid；冻结门槛为 correct≥24/32 且 valid≥28/32，已失败。
因此这轮不能支持旧能力保持。所有题和标签为研究者可见的 development 资产，
`independent_future_B=false`；本轮 1,632 + 204 也不代替另一条旧 adapter 的 624-generation 协议。

真实冷恢复逐条重新生成了 204/204 条，执行失败为 0；独立比较 tokens、text、feature hash 与首 token delta 全部一致。
原报告的 `all_exact=true` 已用原始行重算核实，没有用 exit 0 代替这一判断。
独立纯 Python 审计还复算 4,096 个已记录更新，最终 head 最大绝对差为 5.55e-16；这次复核没有新增模型调用。

主运行 wall 279.655604 秒、CPU 1,015.173847 秒、最大 RSS 1,138,232 KiB。
冷进程 wall 27.281654 秒、CPU 90.378344 秒，最大 RSS 1,136,512 KiB。
这些进程数据不含源码准备、排队、旧模型训练、能耗或完整 Owner 生命周期成本。

[完整结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65d688af66f3797a4d6a61a8f4adf6a5a06b7689/qualification/hpca_routed_content_v1/evidence/native-20261112-v1/RESULTS.md) · [独立算术与冷恢复审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65d688af66f3797a4d6a61a8f4adf6a5a06b7689/qualification/hpca_routed_content_v1/evidence/native-20261112-v1/INDEPENDENT_ARITHMETIC_AUDIT.json) · [71 份原件归档](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65d688af66f3797a4d6a61a8f4adf6a5a06b7689/qualification/hpca_routed_content_v1/evidence/native-20261112-v1/native-originals.tar.xz) · [PR #6172](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6172)

## 内容核 × NDU 2×2 的具体未完成项

固定主线 `732e934ba496d90fbe042b8d41d479ef901643e5` 的
`evaluate_candidates_with_policy` 是真实 Rust NDU 评估器，要求带完整 objective / organ / generation、
utility / risk / resource / uncertainty 的候选贡献；控制平面 adapter 再核 owner coverage。
当前 SmolLM2 runner 没有生产或调用该契约。
已有有限 AdvantageNet 检查点也不接受 SmolLM2 hidden / logits / cache 状态。
另一 native CLI 的普通 `dynamic` 请求实际执行 `static-quota`；严格匹配模式会在加载模型前拒绝。

因此当前 2×2 完成数为 0。下一道实质工作是把所选真实 NDU 实现接到因果可见的候选 / 状态 / 行动上，
固定策略与成本记录，再执行内容 off/on × NDU off/on。评估标签不能拿来制造 utility 或控制状态。
详细只读入口审查和 13 份源码 blob 身份见 `NDU_INTERFACE_REVIEW.json` / `NDU_SOURCE_READBACK.json`。

## 保持未通过的门槛

- HCSN：递归 posterior / observation likelihood、同一 graded 核的完整 AD、真实新核重训、长时与域外尾部资格。
- C2：独立完整训练重放；历史未知调用数和原始完成状态仍照原件保留。
- HPCA：稳定内容收益、合格 retention 基线、独立未来任务、真实内容核 × NDU 2×2。
- 整体：无默认 Cell、Owner 生产准入或能耗收益结论。

本页不修改旧原件。`LEDGER.json` 绑定最终各路 source / evidence refs 与计数；
`HPCA_MAIN_READBACK.json` 是对既有主结果的零模型调用重评分。
`hosted-state-43171816183/` 保存完整下载并核 SHA256 的 28-test state CI 原 artifact；
该 hosted run 没有执行全 14,336 原域 lane。
