# 扩展评估：独立完整汇总

本报告独立重算全部 225 个 query prediction NPZ，并核对 45 个冻结 fit、原始预测、数据身份、目标交换、内容诊断与成本记录。没有重新训练、筛选种子或改动主分析。

## 完整性与范围

- 225/225 条件记录、45/45 fits、225/225 NPZ 独立重算通过；无失败。
- 扩展协议 SHA-256：`5bcbf25bd6c611ffe80f7536862565c7a85e073814c55e2d51b728ddfd73100f`。
- 扩展源码 SHA-256：`9c6f9633225625e9696871c4396e5b52f872ac117b8a4d47cba6f125cf53f84d`。
- 扩展协议冻结时间：2026-11-01T04:53:11.116246+00:00；早于主评估进程开始：True。
- 以下百分数取三个种子的算术均值；完整逐种子值、样本 SD 与条件分母保存在 JSON。

## 主实验与扩展的关系

原主分析中 `query_swap_implemented=false` 保持不变；query swap 是本独立扩展新增的已执行诊断。主实验的 acc / all-query 基线如下；Dynamics 为 all-8，三个内容任务为 all-4，AVT 的 all-query 为未加权单 query accuracy。

| 任务 | Flow | Diagonal | GRU | SNN | Transformer |
|---|---:|---:|---:|---:|---:|
| dynamics | 87.915 / 38.802 | 87.769 / 39.062 | 88.843 / 43.034 | 89.893 / 45.182 | 90.088 / 48.633 |
| mqar | 24.870 / 0.000 | 25.098 / 0.000 | 24.756 / 0.000 | 25.358 / 0.000 | 100.000 / 100.000 |
| selective | 23.893 / 0.000 | 24.821 / 0.000 | 24.251 / 0.000 | 23.470 / 0.000 | 40.186 / 11.784 |
| binding | 24.935 / 0.000 | 24.788 / 0.000 | 25.146 / 0.000 | 24.577 / 0.000 | 25.228 / 0.000 |
| avt | 49.942 / 67.274 | 49.769 / 70.833 | 49.942 / 59.809 | 50.116 / 73.090 | 50.000 / 58.333 |

## 长序列与等时静默

每格为 accuracy / all-4，单位 %。`long_tokens_64/128` 为总长度 64/128 的含观察 distractor 序列；`matched_silence_64/128` 仅匹配该插入对应的物理时间，保留原始 token 数。

| 任务 | 条件 | Flow | Diagonal | GRU | SNN | Transformer |
|---|---|---:|---:|---:|---:|---:|
| mqar | long_tokens_64 | 20.622 / 0.000 | 22.493 / 0.000 | 20.345 / 0.000 | 13.770 / 0.000 | 64.893 / 17.253 |
| mqar | long_tokens_128 | 16.260 / 0.000 | 13.997 / 0.000 | 17.725 / 0.000 | 12.939 / 0.000 | 31.641 / 0.000 |
| mqar | matched_silence_64 | 24.837 / 0.000 | 24.740 / 0.000 | 25.081 / 0.000 | 24.984 / 0.065 | 99.870 / 99.479 |
| mqar | matched_silence_128 | 24.333 / 0.000 | 24.170 / 0.000 | 24.740 / 0.000 | 22.965 / 0.000 | 98.535 / 94.141 |
| selective | long_tokens_64 | 17.660 / 0.000 | 16.781 / 0.000 | 19.564 / 0.000 | 12.288 / 0.000 | 28.467 / 1.888 |
| selective | long_tokens_128 | 13.558 / 0.000 | 15.316 / 0.000 | 15.316 / 0.000 | 12.158 / 0.000 | 21.956 / 0.260 |
| selective | matched_silence_64 | 24.089 / 0.000 | 23.844 / 0.000 | 24.072 / 0.000 | 13.704 / 0.000 | 39.876 / 11.133 |
| selective | matched_silence_128 | 24.007 / 0.000 | 22.852 / 0.000 | 22.347 / 0.000 | 12.240 / 0.000 | 39.242 / 9.961 |
| binding | long_tokens_64 | 19.727 / 0.000 | 20.524 / 0.000 | 20.947 / 0.000 | 12.744 / 0.000 | 24.886 / 0.000 |
| binding | long_tokens_128 | 16.618 / 0.000 | 12.419 / 0.000 | 18.669 / 0.000 | 12.988 / 0.000 | 23.779 / 0.000 |
| binding | matched_silence_64 | 24.951 / 0.000 | 24.837 / 0.000 | 25.407 / 0.000 | 24.170 / 0.065 | 24.414 / 0.000 |
| binding | matched_silence_128 | 24.756 / 0.000 | 25.098 / 0.000 | 25.391 / 0.000 | 23.079 / 0.000 | 24.854 / 0.000 |

## Query swap

交换前两个 query 的身份与标签，保留每个位置的时间和 prelude。正确切换必须让两个新输出都等于交换后的真实目标。条件正确切换仅考察原先前两题全对的 episodes；原先全对为零时保留 NA。

| 任务 | 模型 | Accuracy / all-4 (%) | 正确切换 (%) | 原始双题全对数：17/29/43 | 条件切换种子均值 (%) | 条件切换有效种子 | 条件切换 pooled (%) | 原始和交换后均全对 (%) |
|---|---|---:|---:|---|---:|---:|---:|---:|
| mqar | flow | 24.821 / 0.000 | 0.586 | 4/5/3 | 41.111 | 3 | 41.667 | 0.326 |
| mqar | diagonal | 24.935 / 0.000 | 0.586 | 5/3/2 | 43.333 | 3 | 50.000 | 0.326 |
| mqar | gru | 24.723 / 0.000 | 2.279 | 14/6/11 | 10.823 | 3 | 12.903 | 0.260 |
| mqar | snn | 25.228 / 0.000 | 2.018 | 13/12/13 | 0.000 | 3 | 0.000 | 0.000 |
| mqar | transformer | 100.000 / 100.000 | 100.000 | 512/512/512 | 100.000 | 3 | 100.000 | 100.000 |
| selective | flow | 23.942 / 0.000 | 0.781 | 5/2/4 | 55.000 | 3 | 54.545 | 0.391 |
| selective | diagonal | 24.886 / 0.000 | 0.716 | 2/6/3 | 44.444 | 3 | 63.636 | 0.456 |
| selective | gru | 24.479 / 0.000 | 0.456 | 1/3/0 | 16.667 | 2 | 25.000 | 0.065 |
| selective | snn | 23.714 / 0.000 | 1.042 | 5/7/8 | 0.000 | 3 | 0.000 | 0.000 |
| selective | transformer | 40.137 / 11.719 | 19.466 | 2/0/295 | 72.966 | 2 | 95.623 | 18.490 |
| binding | flow | 24.788 / 0.000 | 1.367 | 3/15/7 | 66.032 | 3 | 64.000 | 1.042 |
| binding | diagonal | 25.000 / 0.000 | 0.911 | 2/1/5 | 60.000 | 3 | 62.500 | 0.326 |
| binding | gru | 24.756 / 0.000 | 1.758 | 12/14/14 | 19.444 | 3 | 20.000 | 0.521 |
| binding | snn | 24.951 / 0.000 | 2.604 | 11/11/12 | 0.000 | 3 | 0.000 | 0.000 |
| binding | transformer | 25.456 / 0.000 | 2.214 | 8/11/18 | 44.571 | 3 | 51.351 | 1.237 |

## 内容诊断：集合成员信息与按 key 检索

以下对全部 45 个主实验内容预测档案独立重算。集合命中以所有 query 预测为分母；四题同答以 episode 为分母。两者不能互换。

| 任务 | 模型 | 四题同答 episodes (%) | 预测属于最终四值集合 (%) | 每 episode 平均不同答案数 |
|---|---|---:|---:|---:|
| mqar | flow | 85.612 | 98.844 | 1.145833 |
| mqar | diagonal | 84.570 | 99.967 | 1.157552 |
| mqar | gru | 43.685 | 100.000 | 1.645833 |
| mqar | snn | 52.799 | 100.000 | 1.543620 |
| mqar | transformer | 0.000 | 100.000 | 4.000000 |
| selective | flow | 85.742 | 95.410 | 1.144531 |
| selective | diagonal | 86.979 | 98.828 | 1.130859 |
| selective | gru | 84.505 | 97.103 | 1.158854 |
| selective | snn | 63.672 | 94.596 | 1.386068 |
| selective | transformer | 56.836 | 84.001 | 2.044271 |
| binding | flow | 78.320 | 99.300 | 1.223307 |
| binding | diagonal | 81.771 | 100.000 | 1.190104 |
| binding | gru | 50.195 | 100.000 | 1.574219 |
| binding | snn | 47.917 | 99.984 | 1.602865 |
| binding | transformer | 49.674 | 100.000 | 1.591797 |

Flow 的 MQAR 在 85.611979% 的 episodes 对四个不同 key 返回同一答案；98.844401% 的 query 预测落在最终四个目标值集合内。结合主实验 accuracy 24.869792%、all-4 为零，这支持保留了内容/集合成员信息，但未形成可靠的按 key 完整检索。集合命中本身不能证明完整记住四个值；反复输出一个已见目标也可产生高集合命中。

## 成本与解释边界

- 扩展整个子进程：CPU 56.749625 s；wall 67.632337 s。
- 内层执行体：CPU 55.126636 s；wall 65.998495 s。
- 225 条条件内层 CPU 合计 54.565933 s；45 次 fit setup CPU 合计 0.417680 s。这些已被外层和内层执行体包含，不重复相加。
- 能耗未测，为 null。

- Post-hoc descriptive aggregation of all 225 conditions from a separately frozen extension; no retraining, checkpoint selection, or new confidence intervals.
- The main 75-fit analysis remains unchanged, including its query_swap_implemented=false field. Query swap is implemented and reported only in this separate extension.
- Every condition uses the same 512 original episodes for a task and all three training seeds. Seed-episode counts are descriptive, not additional independent experimental units.
- Long-token conditions insert observed distractors to total sequence lengths 64/128. Matched-silence conditions keep the original token count and add the identical elapsed time; they do not themselves have 64/128 tokens.
- Correct switch requires both swapped first-two predictions to match their exchanged targets. Changed outputs alone are not counted. Conditional switch is undefined when the original pair was never both correct; null is preserved.
- Conditional-switch macro means omit undefined seeds and report their valid n. Pooled conditional ratios retain eligible counts and are descriptive only.
- Accuracy and all-four are different criteria. Near 25% accuracy with repeated same-answer responses does not establish keyed retrieval.
- Membership in the final four-value set supports retained content or set-membership information, but does not prove that all four values were stored. A repeatedly returned single remembered target can satisfy membership without binding keys to values.
- Only three training seeds and small symbolic tasks are represented. No foundation-model, natural multimodal, energy-efficiency, or architecture-impossibility conclusion follows.
- Setup and condition clocks are components inside the extension enclosing execution clock; the whole-child receipt also contains those clocks and must not be added to them. Energy is unmeasured.
