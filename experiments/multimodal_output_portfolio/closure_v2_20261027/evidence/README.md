# 联合证据：事件身份、真实预测结果和部署选择

本轮把可修复的证据语义和模型晋级问题落实为代码，同时保留新来源上的失败。
**不同事件共享 speaker 的 likelihood 优势仍未通过；同事件 rank 联合模型虽然
改善 conditional NLL，却降低真实识别准确率，不能据此晋级。** 新的部署选择器
已经在历史 fit/validation 上验证，但没有把已看过的测试结果重新认证。

## 1. 同一事件只有一个联合因子

`blocks.py` 提供规范化 `JointLaw`、显式 `Capture` 和 `EvidenceState`。
采集身份与内容哈希分开：新的 qualification capture 使用模型特征计算前随机
分配并封存的 UUID。含数字标签的 WAV 文件名只存在于私有来源映射，不进入
预测器。两个真实采集可以具有相同字节；同一采集的别名必须保留相同身份及
原始内容承诺。

对于属于同一物理事件的多个观察视图，状态使用一个联合因子：

\[
p(y\mid v_{1:k})\propto q(y)
\sum_{v_{k+1:m}}L(v_1,\ldots,v_m\mid y).
\]

后到的视图更新这个因子的边际，不额外乘一个独立 likelihood。实现支持部分
到达、反向到达、别名重试和 checkpoint 恢复；一个物理采集不能同时放进两个
声明为条件独立的 block。未知 target 的 likelihood 列保持未知；正 prior
覆盖未知支持时拒绝推断。target-prior 拟合 API 只接受 cue 与训练 target，
拒绝 WAV、event、观察值等字段。

13 个行为／集成测试通过，包括一个明确的概率反例：更好的 generative
conditional NLL 可以伴随更坏的 posterior log score 与风险决策。因此
conditional NLL 不能单独作为部署晋级标准。另有 240 个真实新 WAV 的
alias／恢复／逆序／冲突检查，完整 checkpoint 均保留。

这些约束依赖可信采集注册器维护身份；它们不是任意新 ID 下重复物理事件的
自动识别器，也不是分布式 exactly-once、恶意全量 checkpoint 伪造防护或
生产权限机制。

## 2. 新来源、冻结与原始证据

来源固定为 [AudioMNIST](https://github.com/soerenab/AudioMNIST/tree/630d7dab4c040882834de6fa21baf9a60372accd)。
本轮下载 speakers 21–32、每个数字 20 条，共 **2,400 个实际 WAV**；与上一轮
4,000 个 WAV 没有字节哈希重叠。模型仍是原冻结 FSDD observer，参数 SHA-256
为 `6c5391e2ea0ee6102977992cb14ebcee857e393a7c9c66b8b534c78951356e86`。
没有重新训练识别器。4 个历史 WAV 的特征及模型输出与原实现逐位一致。

所有 fitting 和超参数选择只用旧 speakers 01–08 / 09–12。两个开发诊断、
完整候选、独立审计代码、模型和协议均在计算新测试特征前封存。模型封条：

`c5fa30f6ecbfec3f59138d4a2be2a563239240ff73f08b05668145a2c95f8341`

本轮实际交付并重新读回 **115,200 个 UTF-8 预测记录**。统计单位是 12 个
speaker；重复使用录音构造的 pair 不增加独立样本数。报告固定来源的配对
bootstrap 97.5% 区间，不认证说话人总体，也不把多项区间当成同时覆盖保证。

## 3. 不同事件的共享 speaker 依赖

旧实验明确限定“相等目标使用同一 WAV”，因此 alias 身份本身带有相等信息。
本轮所有 100 个目标对都使用两个不同录音，包括相等数字。左索引为 `k`，
右索引为 `(7*k+11)%20`；模型再也不能通过 event equality 取得目标关系。

所有模型共享同一平滑边际。paired 和 speaker mixture 都通过 information
projection 匹配该边际，并在 validation 候选中包含明确的 independence。

| 模型 | conditional NLL | posterior NLL | 实际 pair 准确率 |
| --- | ---: | ---: | ---: |
| Independence | 1.750381 | 1.872870 | 52.775% |
| Paired | 1.749885 | 1.875054 | 52.775% |
| Speaker mixture | 1.743495 | 1.868899 | 52.775% |

Paired 的 conditional NLL 差为 −0.000496，区间
[−0.009422, +0.007870]；speaker mixture 为 −0.006885，区间
[−0.014718, +0.000210]。两个模型的实际 MAP 输出均与 independence 相同。
**原先 likelihood／实际输出优势门槛均未通过。**

## 4. 同一 WAV 的联合 rank 视图

使用原 CNN 的 top1 与 runner-up 标签作为同一事件的两个派生视图。
它们不是两个独立录音，也不是新增的第二个模态。强对照是共享边际、相同
合法支持上的 maximum-entropy 表；它也排除 top1 等于 runner-up 的不可能
对角，联合模型无法仅靠这个结构零取得优势。

| 模型 | conditional NLL | posterior NLL | 实际数字准确率 |
| --- | ---: | ---: | ---: |
| 相同支持的 maximum entropy | 2.039494 | 0.707767 | 76.7083% |
| Measured joint，按 conditional NLL 选择 | 1.999172 | 0.745306 | 74.8333% |

联合模型的 conditional NLL 差 −0.040322，区间
[−0.059334, −0.019775]，但 posterior NLL **恶化** +0.037538，区间
[+0.014828, +0.057516]；准确率差 −1.875 个百分点，区间
[−3.1667, −0.75]。改善 `p(observation|target)` 的平均拟合分数不自动保证
`p(target|observation)` 或最终决策更好。冻结结果没有被替换或重选。

## 5. prior 与 likelihood 继续分别检验

任务 cue 的真实目标联合分布是公开声明的构造机制：`plus1/3/7` 有 70%
质量在指定模 10 关系、30% 均匀分布。两边 marginal 均匀；训练 prior 只读
目标计数。joint 和 factorized prior 使用相同冻结 observation likelihood。

去掉 alias 信息后，joint-prior 的实际准确率增益仍为：

| Cue | 准确率增益，百分点 | 97.5% speaker 区间 |
| --- | ---: | --- |
| plus1 | +17.6944 | [+13.1667, +21.8333] |
| plus3 | +14.1667 | [+10.8056, +17.1667] |
| plus7 | +15.8889 | [+11.5833, +19.9167] |
| uniform | −0.3889 | [−0.9722, +0.1944] |

这是构造目标分布上的 prior 机制结果，不能当成自然语音目标共现规律。
原 JSON 为复用统计结构，在 `prior_comparisons` 中仍使用 `conditional_nll`
字段名；该部分实际指 **prior-only target NLL**，原记录及
`results/INTERPRETATION.json` 已明确说明，不能读作 observation likelihood。

## 6. 预先冻结的风险决策诊断

在新测试前另行固定实际文本动作：输出一个数字或 `uncertain`。
净任务收益分别为正确 +0.99、错误 −0.51、拒答 −0.003。这些是任务定义的
收益和交付费，不是美元、能耗或实际 CPU 价格。均值策略的 posterior
门槛为 0.338；γ=2 的指数风险门槛为约 0.670623，由相同收益代数导出，
没有在新测试上搜索阈值。

强 maximum-entropy 对照从 γ=0 切换到 γ=2，654 个实际输出改变，错误率
从 23.25% 降至 10.625%，拒答率从 0.0417% 升至 27.2917%。实际 CE 从
0.143110 升至 0.211614，均值从 0.640836 降至 0.559619，体现真实的风险
权衡。联合模型有 758 个动作改变，但相对强对照的 γ=2 CE 差为 −0.011519，
区间 [−0.041656, +0.026592]，未通过优势门槛。这个诊断没有替代 MAP 门槛。

## 7. 新的部署准入选择器已修复

`deployment_selection.py` 要求在相同验证面板上保护四件事：proper posterior
log score、MAP 准确率、实际均值决策收益、实际风险 CE。使用配对 source
bootstrap 检查相对基线的保护；independence／maximum-entropy 基线总是候选。
只有通过保护的模型才能按风险 CE 和 posterior score 排序。conditional
likelihood 仍独立报告，不能单独触发晋级。

`decision-development-001` 只重新使用历史 speakers 01–08 / 09–12，未读取
21–32 的测试观察／目标做选择，也没有产生新的 qualification 声明。
23 个模型候选实际写出 126,400 个包含 MAP／均值／风险文本的验证记录，
共 379,200 个文本决策。rank 任务保留 maximum-entropy 基线，拒绝上一轮
仅因 conditional NLL 好而晋级的 strength50 联合模型；不同事件任务选择
speaker-mixture strength50。后者只是历史验证选择，**尚无新来源收益证明**。

## 8. 独立验证、成本与复现

独立审计没有调用实验 scorer：重新哈希全部 2,400 WAV，用 NumPy 窗函数、
rFFT 和双线性 resize 重建特征，再用重建的同权重 CNN 评分。概率最大差
1.2517×10⁻⁶，top1／runner-up 无差异。5 张选定联合表由独立计数公式重建；
全量交付、source bootstrap 和 alias checkpoint 重新核验。最大统计差
7.22×10⁻¹³，最大 posterior 差 4.09×10⁻¹²。

整个 qualification 批次测得 32.68 CPU 秒／66.39 wall 秒，包含冻结输入
校验、预处理、共享 CNN、controller、真实文本写入／读回／评分和 alias
检查；独立审计另为 6.52 CPU 秒／6.96 wall 秒。运行时存在并发作业，
这些值不被包装成生产交互延迟或不同 estimator 的等计算训练优势。

本目录还包含对 direct-gradient 分支的独立 peer review 和 probe 工具。
18 个保存状态的训练 probe 实际重建并读回 4,608 个 PNG／UTF-8 bundles，
成本最大差 3.06×10⁻⁸，Gaussian coefficient-gradient 最大差 1.89×10⁻⁷。
这些都是 clean-condition checkpoint 后的步骤，不证明所有未保存的原训练
媒体身份；完整记录在 `results/JOINT_GRADIENT_PROBES.json`。

最终原始包保留新 WAV、原 observer、全部 fitted laws、两个开发诊断、冻结
源码、原失败 qualification、验证 selector 的实际输出和独立审计。历史
fitting observer 输出已复制入包；若要从历史 WAV 重建这些旧观察，另依赖
上一轮已保存的完整来源包，身份在本轮归档说明中列明。

建议审阅顺序：`blocks.py` 与测试；`models.py` 与输入接口；冻结、交付与
审计；独立部署选择器；最后对照原始 JSON。各代码模块保持约 300 行以内，
大型 JSON 是机械证据记录。所有测试在最终仓库格式化之前完成。
