# 新执行 004：独立算术核验

对象仅为新执行 `PRED1-CROSSED-REEXEC-004-20261110-4456`，注册提交 `260922ba18438a24b2941c306606ec853f4a7348`。它不恢复缺失的原 189-fit 执行，也不增加独立确认样本。

189 个完整身份全部准确对齐；每 fit 30 epochs、960 个 optimizer calls，总计 181,440 calls、23,224,320 次训练样本呈现。所选 epoch 是逐 fit 曲线的首次最小 dev observed-label NLL，保存的 checkpoint step 与所选 epoch 一致。九份冻结源码与隔离副本、训练保存副本及当前源码相同。初始化摘要在同 model/init 下跨 data/order 一致；batch-order 摘要只随三个 order 水平变化。

独立实现使用 Python 条件均值与容斥公式，没有调用训练程序的 decompose。44 项模型／对比分解的 1,276 个数值叶子与 RESULT.summary 一致，最大绝对差 2.4647e-14。另从逐 episode 数组重新核了 5,670 个均值。未重训模型、未打开 checkpoint 数组、未读取旧确认集。NLL 核验是所选曲线及跨 fit 聚合一致性，不是重新计算模型 likelihood。

## 27 个共享 factor cell 的均值

| 模型 | 所选 dev observed NLL | 扩展资源廉价 Fixed1 预期净效用 | 旧整套 panel adaptive 预期净效用 |
|---|---:|---:|---:|
| single_step | 1.776183640 | 0.632556705 | 0.629589604 |
| gru | 1.770581394 | 0.635655795 | 0.633090548 |
| diag_ssm | 1.767134738 | 0.632837244 | 0.630462625 |
| dual_timescale | 1.750290928 | 0.644605561 | 0.642320138 |
| gru_reset | 1.768907957 | 0.632529442 | 0.630672861 |
| gru_no_action | 2.253104797 | 0.353488382 | 0.347591006 |
| gru_no_time | 1.743348310 | 0.646876069 | 0.644386919 |

效用单位来自有限模拟器；budget 16/deadline 20 是已声明的资源干预。原资源 panel 全部五个 arm 均为 STOP（跨 fits/arm 共 483,840 条记录）。旧 adaptive 与廉价 Fixed1 的编码／费用不同；严格缓存公平的 horizon 比较见另行核验的 replay 报告。

## 有限网格差异与不稳定性边界

GRU 原始 observed-label NLL 的平方差分解：data 82.0451%、init 6.5316%、order 0.04556%、data×init 10.9441%。这些仅是该有限网格的描述分量。Data 水平也改变任务难度、缺失与标签粗化的熵，不能将 82% 直接称为优化失稳的因果来源。

| data seed（配置顺序） | dev exact / interval / verified censor | missing / cancel unknown | GRU NLL 边际均值 |
|---|---|---|---:|
| 1075468529 | 280 / 110 / 50 | 32 / 40 | 1.792190065 |
| 2756881551 | 270 / 106 / 47 | 43 / 46 | 1.728707705 |
| 1237426659 | 272 / 106 / 47 | 47 / 40 | 1.790846414 |

同 cell 的 GRU−single-step 配对 NLL 均值为 −0.005602246；该差值的平方差分解变为 data 34.3021%、init 23.8245%、data×init 39.8341%、order 0.07684%，其余交互约 1.96%。同对比的扩展廉价 Fixed1 效用均值仅 +0.003099090：data 34.4448%、init 10.7373%、data×init 43.1077%、order 1.7839%，其余交互约 9.93%。配对增益仍受 data×initialization 交互影响，不能用一个随机源解释全部差异。

## 已注册消融的描述结果

扩展廉价 Fixed1 下：GRU−无 action = +0.282167412；GRU−reset = +0.003126352；GRU−无显式 clock/lag = −0.011220274。无 action 同时删除历史与候选 action；reset 同时删除历史与累积状态；无 clock/lag 仍保留顺序与 missingness。这些消融不能单独充分证明一个纯机制的作用。

无 clock/lag 在此 grid 同时改善 NLL 与效用，完整 GRU 的显式 timing 编码优势未成立。Dual-timescale 与无显式 clock/lag 的开发均值较好，但不能据此选确认赢家。此处的 27 cell 复用了因素水平，189 fits 也不等于 189 独立确认样本。未计算新 p 值、总体方差分量或改变历史 HOLD；真实历史训练、完整物理成本和独立决策收益仍未闭合。
