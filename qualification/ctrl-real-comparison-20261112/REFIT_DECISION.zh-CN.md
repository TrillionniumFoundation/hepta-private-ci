# 数值修正后的重新运行决定

## 决定及原始分母

本轮不新增跨版本复用 collection 的 admission 协议。数值修正后的精确源码使用新的、只允许创建一次的 `run-v2` 输出目录，保持原 study identity、来源 roster、train/calibration/evaluation 划分、动作、预算、价格与分析方案，重新执行完整流程。最终源码与运行参数以新启动记录和冻结文件为准。

前一轮 `run-v1` 的原生 collection 为 **126/126 pairs、0 UNKNOWN**；export 已完成，fit 在 checkpoint 归一化与观测包络检查处报错 `Invalid normalization or observed envelope`。这批真实执行数据及其原始 source pins、freeze、export、时间成本、失败记录全部保留。该轮仍是 **collection 完整、fit 失败**，不会被改写成完成的六策略实验。它与 `prior-attempt/` 中更早的 **125/126** 尝试是两次不同运行。

选择新运行是为了在既有、已经实现的冻结与验收路径内完成研究，不是因为 126/126 原 collection 的内容或终态评分不合要求。不得按这次 fitting 结果重新选择来源、丢弃 outcome，或只重做有利的分支。新一轮实际观测自己的执行成本，不把旧时延改记到新源码下；两轮相同来源不能合并成两份独立样本。

## 为什么不能直接改写旧 pin

[`CriticContext`](../../scripts/ndu_real_runtime/critic_context.py) 固定内容编码、答案模型、OCR 生成器、公共状态、宏动作、终结、效用、价格和评分器的九项语义依赖；它没有把 fitter 或 observer 的实现哈希混入这些语义字段。仅修正 fitter 的数值计算，未必改变原 collection 的语义。

但语义一致不能取代原件的实现身份。当前代码另有严格的实现绑定：

| 绑定 | 数值修正的影响 |
| --- | --- |
| [`macro_policy.source_sha256()`](../../scripts/ndu_real_runtime/macro_policy.py) | 包含 `macro_policy.py`；修改 fitter 后必须得到新的 fitter pin。 |
| [`macro_training_pairs.source_manifest()` / `fit_rows()`](../../scripts/ndu_real_runtime/macro_training_pairs.py) | converter 清单也包含 `macro_policy.py`，所以新代码不会直接接收带旧 converter pin 的 export。 |
| [`ctrl_macro_study.thaw()`](../../scripts/ctrl_macro_study.py) | 检查 driver、repository、converter、fitter、observer、analysis，以及原 producer source pins；不是只检查数值形状。 |
| [`ctrl_macro_factorial.inputs()` / `freeze()`](../../scripts/ctrl_macro_factorial.py) | 每个内容版本仍须通过 study thaw、checkpoint cold load，且 adaptation receipt 必须指向真实的 frozen study。 |

因此，把旧 `FROZEN.json` 或 `EXPORT.json` 中的 hash 替换成新源码 hash，会错误地声称旧原件由新实现产生，也会破坏 content adaptation 与 factorial registration 的真实来源链。不能用复制目录、改 context、跳过 `fit_rows()`、调整 loader 容差或进程内 monkeypatch 来隐藏这种差异。

## 本轮保持的验收边界

数值修正应在 fitter 中产生满足既有不变量的 checkpoint；checkpoint 对有限值、正尺度和 `minimum ≤ center ≤ maximum` 的严格校验保留。观测包络不能为通过检查而扩大，计划分母与 train/calibration 分离也不能放宽。

从研究方法上，未来可以显式注册“原 collection admission → 新 fitter”的派生协议：由原 checkout 校验原 freeze/export 与完整分母，再将有独立 pin 的行、分区和完全相同的语义 context 交给新 fitter，记录新的 cold load 和后续 evaluation registration。那需要独立实现、审阅与验证；不能由替换哈希隐式完成。本轮选择重新执行，避免在当前实验中引入这项尚未验收的协议。

学得内容的 encoder/answer 身份会改变，仍需其真实执行数据和对应 critic；任何情况下，都不能把 frozen 内容的公共特征或 critic 当作 learned 内容的真实 2×2 单元。

本说明是代码契约审计和运行决定，不是新运行已完成或策略已经产生净效益的声明。完成与否由新的原始 stage、冷加载、执行、终态评分与分母记录判定。
