# Hepta content001：完整结果与归因边界

本报告依据冻结协议完成的 **108/108 个 jobs、0 失败**。共享因果内容寻址使 Copy/MQAR 在长度32的测试中达到全部三seed、全部模型与训练模式的100% query accuracy和100%整序列exact recall；解析动态没有在该能力上建立增量贡献。AV情绪的三个共同encoder checkpoint均被验证选择回step0，AV binding的全部analytic主条件仍为50%。解析适配器在所有48个ID配对中消耗更多完整worker CPU，且prepared-feature单请求p50均更慢。**本轮没有得到“质量非劣且实际相关执行成本更低”的联合优势证据。** [逐seed原始重算](results/content_analysis001/metrics.json) · [配对成本与质量](results/content_analysis001/paired_seeds.json)

实现本身完成了共同容量、冻结/联合训练、反向传播、checkpoint、因果数据准备与完整执行账本的闭合；强自然内容encoder、长序列稳定泛化、全模态基础模型和Transformer替代优势仍未闭合。局部长128条件存在analytic增益，也存在同组其他seed的明显退化，下文保留全部结果。

## 1. 协议、证据与统计单位

预注册提交：[1a5434f361d2df8a0505b6069fe6d48736f9ff30](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/1a5434f361d2df8a0505b6069fe6d48736f9ff30)。[完整content协议](protocols/content001/plan.json) 的SHA-256为 `b7403897a666c2c4bd9a7b77587fd79de5e03d06143a45734f0bc78580f35a89`；正式data seed为2026110103，训练seeds固定81031、81032、81033。以下所有三元组均按此顺序。

四任务 × 三seed ×（一个共同内容预训练 + 两个core × 两种内容训练模式 × 两个预算）=108 jobs。Copy/MQAR共同预训练1024 updates；两个AV任务512 updates。适配阶段的256 optimizer updates和20 CPU秒是两套独立实验。选点规则始终是验证CE最小、首次tie，包括step0；test及干预均在选点后打开。冻结模式固定共同encoder/SDPA/readout，只训练adapter；joint模式从完全相同的共同checkpoint继续训练全部参数。

合成训练/验证/每个测试长度分别512/128/256 sequences，每条有4个query，长度32训练、64/128外推。exact recall要求同一sequence的4个query全部正确。AV情绪是既往已见的48条CREMA-D DFA片段、4/2/2 actor划分、24/12/12 clips；binding把每clip配为一个正例和一个同actor deranged负例，train/val/test为48/24/24 pairs。AV只有两个test actors，重复clips/pairs不会增加独立actor数。

分析器从717份raw logits重算accuracy、CE和episode exact，检查paired sample/position/label/group/input SHA以及共同初始化；形成324个逐seed配对、108个bootstrap strata。bootstrap固定2000次，联合重采样seed和共有episode/actor，区间仅描述当前有限样本，不构成总体显著性或已证明的非劣结论。数据集均衡使当前AV的actor-macro与micro结果相同。 [分析清单](results/content_analysis001/manifest.json) · [全部bootstrap](results/content_analysis001/paired_bootstrap.json)

预定合成ID要求为99% exact recall；accuracy非劣margin为1个百分点、CE margin为0.02。以下同时保留逐seed值，不以三seed均值掩盖失败，也不把这些ID要求改成OOD已通过。

## 2. 共同内容能力与step0 donor

下表每行是一个实际共同预训练job。shared SDPA没有动态core，已经能够独立提供合成ID能力。Copy输入增加的selected/query前缀计数及四槽顺序地址完全由过去输入标记计算，并提供给所有family；MQAR与Copy的共同两层causal SDPA保留其attention内容寻址和随长度增长的成本。这些改进应归于共享内容结构。

| 任务 | seed | selected step | 选中encoder已训练 | val Q% | test Q% | test exact% | 完整worker CPU秒 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Selective Copy | 81031 | 1024 | 是 | 100.000 | 100.000 | 100.000 | 9.434 |
| Selective Copy | 81032 | 1024 | 是 | 100.000 | 100.000 | 100.000 | 10.813 |
| Selective Copy | 81033 | 1024 | 是 | 100.000 | 100.000 | 100.000 | 9.876 |
| MQAR | 81031 | 1024 | 是 | 100.000 | 100.000 | 100.000 | 9.724 |
| MQAR | 81032 | 1024 | 是 | 100.000 | 100.000 | 100.000 | 9.866 |
| MQAR | 81033 | 1024 | 是 | 100.000 | 100.000 | 100.000 | 9.630 |
| AV 情绪 | 81031 | 0 | **否：step0** | 25.000 | 25.000 | 25.000 | 5.990 |
| AV 情绪 | 81032 | 0 | **否：step0** | 8.333 | 0.000 | 0.000 | 5.678 |
| AV 情绪 | 81033 | 0 | **否：step0** | 0.000 | 16.667 | 16.667 | 6.213 |
| AV recording binding | 81031 | 64 | 是 | 50.000 | 50.000 | 50.000 | 5.366 |
| AV recording binding | 81032 | 224 | 是 | 50.000 | 50.000 | 50.000 | 4.804 |
| AV recording binding | 81033 | 480 | 是 | 50.000 | 50.000 | 50.000 | 4.772 |

AV前端是既有log-mel/DCT特征，在其上训练宽度32、深度2的共同encoder，不是预训练foundation encoder。AV情绪三个donor都选step0，因此该任务的frozen组是冻结随机共同网络，而不是冻结一个成功预训练的强encoder；joint组同样从该随机donor出发。binding虽选了非零step，三seed test均50%，仍未建立可用的泛化能力。 [checkpoint状态与参数](results/content_analysis001/jobs.json)

## 3. 全部ID候选：frozen/joint × updates/CPU

Q与exact的单位均为%；每格依次列81031/81032/81033，CE列三seed均值。AV每pair/clip只有一个监督读出，因此其exact在本任务定义下等于Q，不代表多步语言序列精确生成。

### Selective Copy

| core | 模式/预算 | Q% 三seed | exact% 三seed | CE均值 | selected step 三seed |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000196814 | 246 / 232 / 232 |
| analytic | frozen / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000196496 | 256 / 256 / 256 |
| analytic | joint / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 7.08732e-06 | 239 / 226 / 243 |
| analytic | joint / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 6.57826e-06 | 256 / 256 / 256 |
| two_gate | frozen / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000190352 | 1180 / 1216 / 1161 |
| two_gate | frozen / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000196216 | 256 / 256 / 256 |
| two_gate | joint / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 1.25695e-06 | 1032 / 977 / 904 |
| two_gate | joint / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 6.51682e-06 | 256 / 256 / 256 |

### MQAR

| core | 模式/预算 | Q% 三seed | exact% 三seed | CE均值 | selected step 三seed |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000230118 | 246 / 225 / 239 |
| analytic | frozen / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000228502 | 256 / 256 / 256 |
| analytic | joint / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000149571 | 192 / 0 / 160 |
| analytic | joint / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000121578 | 256 / 0 / 256 |
| two_gate | frozen / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000205759 | 1120 / 1312 / 1190 |
| two_gate | frozen / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000223883 | 256 / 256 / 256 |
| two_gate | joint / CPU20.0 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 9.0855e-06 | 938 / 1032 / 1025 |
| two_gate | joint / U256 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000112504 | 256 / 0 / 256 |

### AV 情绪

| core | 模式/预算 | Q% 三seed | exact% 三seed | CE均值 | selected step 三seed |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | 25.000 / 8.333 / 16.667 | 25.000 / 8.333 / 16.667 | 1.86673 | 64 / 32 / 32 |
| analytic | frozen / U256 | 25.000 / 8.333 / 16.667 | 25.000 / 8.333 / 16.667 | 1.86673 | 64 / 32 / 32 |
| analytic | joint / CPU20.0 | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90544 | 0 / 0 / 0 |
| analytic | joint / U256 | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90544 | 0 / 0 / 0 |
| two_gate | frozen / CPU20.0 | 25.000 / 8.333 / 8.333 | 25.000 / 8.333 / 8.333 | 1.87331 | 64 / 128 / 64 |
| two_gate | frozen / U256 | 25.000 / 8.333 / 8.333 | 25.000 / 8.333 / 8.333 | 1.87331 | 64 / 128 / 64 |
| two_gate | joint / CPU20.0 | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.9056 | 0 / 0 / 0 |
| two_gate | joint / U256 | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.9056 | 0 / 0 / 0 |

### AV recording binding

| core | 模式/预算 | Q% 三seed | exact% 三seed | CE均值 | selected step 三seed |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693267 | 325 / 128 / 224 |
| analytic | frozen / U256 | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693251 | 192 / 128 / 224 |
| analytic | joint / CPU20.0 | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693446 | 0 / 0 / 288 |
| analytic | joint / U256 | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693463 | 0 / 0 / 0 |
| two_gate | frozen / CPU20.0 | 50.000 / 58.333 / 45.833 | 50.000 / 58.333 / 45.833 | 0.693226 | 1575 / 832 / 480 |
| two_gate | frozen / U256 | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693362 | 256 / 224 / 224 |
| two_gate | joint / CPU20.0 | 50.000 / 50.000 / 41.667 | 50.000 / 50.000 / 41.667 | 0.715056 | 768 / 832 / 768 |
| two_gate | joint / U256 | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693439 | 0 / 0 / 0 |

全部54个合成ID jobs（包括6个shared基线与48个适配jobs）均达到100% exact，超过观测样本上的99% floor；并不由此证明总体准确率或超长序列泛化。AV情绪主要结果在0%–25%间，binding analytic始终50%。这些AV负结果使当前内容前端成为继续讨论真实全模态优势的明确阻碍。 [全部ID及条件聚合](results/content_analysis001/aggregates.json)

## 4. ID配对差与真实执行成本

差值方向统一为analytic减two_gate；accuracy/exact的正值有利于analytic，CE和CPU的负值有利。方括号是描述性paired bootstrap 95%区间；Q/exact以百分点计，CE保持原尺度。p50倍率是三seed配对倍率的均值，来自验证集batch1 whole-sequence prepared-input profile。

| 任务 | 模式/预算 | ΔQ pp [CI] | Δexact pp [CI] | ΔCE [CI] | Δ完整worker CPU秒 | p50倍率 |
| --- | --- | --- | --- | --- | --- | --- |
| AV 情绪 | frozen / CPU20.0 | +2.778 [+0, +11.11] | +2.778 [+0, +11.11] | -0.006577 [-0.03571, +0.02519] | +0.965 | 7.659× |
| AV 情绪 | frozen / U256 | +2.778 [+0, +11.11] | +2.778 [+0, +11.11] | -0.006577 [-0.03571, +0.02519] | +25.463 | 7.201× |
| AV 情绪 | joint / CPU20.0 | +0 [+0, +0] | +0 [+0, +0] | -0.0001587 [-0.002986, +0.004532] | +0.901 | 5.711× |
| AV 情绪 | joint / U256 | +0 [+0, +0] | +0 [+0, +0] | -0.0001587 [-0.002986, +0.004532] | +24.074 | 7.238× |
| AV recording binding | frozen / CPU20.0 | -1.389 [-11.11, +5.556] | -1.389 [-11.11, +5.556] | +4.111e-05 [-6.714e-05, +0.0001859] | +1.047 | 7.561× |
| AV recording binding | frozen / U256 | +0 [+0, +0] | +0 [+0, +0] | -0.0001112 [-0.0002596, -4.477e-05] | +15.302 | 7.326× |
| AV recording binding | joint / CPU20.0 | +2.778 [+0, +8.333] | +2.778 [+0, +8.333] | -0.02161 [-0.07235, -0.0004946] | +0.915 | 7.368× |
| AV recording binding | joint / U256 | +0 [+0, +0] | +0 [+0, +0] | +2.445e-05 [-1.873e-05, +9.022e-05] | +14.711 | 7.511× |
| MQAR | frozen / CPU20.0 | +0 [+0, +0] | +0 [+0, +0] | +2.436e-05 [+2.011e-05, +3.079e-05] | +6.310 | 7.262× |
| MQAR | frozen / U256 | +0 [+0, +0] | +0 [+0, +0] | +4.619e-06 [+2.532e-06, +7.342e-06] | +23.319 | 7.742× |
| MQAR | joint / CPU20.0 | +0 [+0, +0] | +0 [+0, +0] | +0.0001405 [+3.697e-05, +0.0002669] | +6.946 | 7.402× |
| MQAR | joint / U256 | +0 [+0, +0] | +0 [+0, +0] | +9.074e-06 [-1.058e-05, +2.669e-05] | +23.994 | 6.818× |
| Selective Copy | frozen / CPU20.0 | +0 [+0, +0] | +0 [+0, +0] | +6.462e-06 [+4.996e-06, +8.714e-06] | +6.125 | 7.449× |
| Selective Copy | frozen / U256 | +0 [+0, +0] | +0 [+0, +0] | +2.797e-07 [-5.231e-08, +7.723e-07] | +23.187 | 7.404× |
| Selective Copy | joint / CPU20.0 | +0 [+0, +0] | +0 [+0, +0] | +5.83e-06 [+2.545e-07, +1.172e-05] | +6.156 | 7.296× |
| Selective Copy | joint / U256 | +0 [+0, +0] | +0 [+0, +0] | +6.144e-08 [-7.685e-06, +4.188e-06] | +22.891 | 7.631× |

48个逐seed ID配对的完整worker CPU差全部为正；p50倍率逐seed范围为3.906–8.377×。相同共同预训练成本加到两边后不会改变这个配对成本方向。20秒训练预算接近，并不意味着完整worker成本或推理成本接近。当前实现中analytic的循环、状态推进及评估成本更高；本结论限定于冻结的软件实现与CPU执行，不外推到未实现的融合kernel或专用硬件。 [逐seed配对](results/content_analysis001/paired_seeds.json)

## 5. 长度64/128：逐seed外推结果

这些是预定的长度外推测试，不是新的训练条件。共同模型的长128本身就明显退化，不能把长128局部最优seed当作稳定机制优势。所有长128 paired query-accuracy描述性区间均跨0。

### Selective Copy OOD

| family | 模式/预算 | 长度 | Q% 三seed | exact% 三seed | CE均值 |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | 128 | 41.699 / 51.270 / 65.039 | 1.172 / 5.859 / 7.812 | 2.93801 |
| analytic | frozen / CPU20.0 | 64 | 99.707 / 99.805 / 98.730 | 98.828 / 99.219 / 95.312 | 0.020269 |
| analytic | frozen / U256 | 128 | 40.820 / 51.660 / 65.723 | 1.172 / 6.250 / 8.984 | 2.9358 |
| analytic | frozen / U256 | 64 | 99.707 / 99.902 / 98.535 | 98.828 / 99.609 / 94.531 | 0.0210652 |
| analytic | joint / CPU20.0 | 128 | 44.922 / 52.441 / 78.613 | 0.781 / 10.547 / 37.891 | 3.45761 |
| analytic | joint / CPU20.0 | 64 | 98.926 / 100.000 / 100.000 | 95.703 / 100.000 / 100.000 | 0.018063 |
| analytic | joint / U256 | 128 | 44.824 / 52.539 / 78.613 | 0.781 / 10.547 / 37.891 | 3.46876 |
| analytic | joint / U256 | 64 | 98.926 / 100.000 / 100.000 | 95.703 / 100.000 / 100.000 | 0.0176003 |
| shared SDPA | joint / U1024 | 128 | 39.551 / 49.023 / 62.012 | 1.172 / 3.906 / 7.031 | 3.16827 |
| shared SDPA | joint / U1024 | 64 | 99.805 / 99.805 / 98.438 | 99.219 / 99.219 / 94.922 | 0.0230605 |
| two_gate | frozen / CPU20.0 | 128 | 58.301 / 57.520 / 62.402 | 9.766 / 6.641 / 7.031 | 2.44832 |
| two_gate | frozen / CPU20.0 | 64 | 100.000 / 99.023 / 98.926 | 100.000 / 96.094 / 95.703 | 0.0235716 |
| two_gate | frozen / U256 | 128 | 45.020 / 49.512 / 65.625 | 3.125 / 5.469 / 7.812 | 2.90666 |
| two_gate | frozen / U256 | 64 | 100.000 / 99.805 / 98.340 | 100.000 / 99.219 / 94.141 | 0.0229379 |
| two_gate | joint / CPU20.0 | 128 | 57.227 / 62.695 / 63.086 | 9.375 / 8.203 / 8.594 | 3.82048 |
| two_gate | joint / CPU20.0 | 64 | 100.000 / 98.926 / 98.535 | 100.000 / 95.703 / 94.531 | 0.0447092 |
| two_gate | joint / U256 | 128 | 57.129 / 63.281 / 61.426 | 10.156 / 8.594 / 7.812 | 3.49178 |
| two_gate | joint / U256 | 64 | 100.000 / 98.926 / 97.852 | 100.000 / 95.703 / 92.188 | 0.0551394 |

### MQAR OOD

| family | 模式/预算 | 长度 | Q% 三seed | exact% 三seed | CE均值 |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | 128 | 68.066 / 96.191 / 90.527 | 16.406 / 85.938 / 66.016 | 0.649014 |
| analytic | frozen / CPU20.0 | 64 | 99.805 / 100.000 / 100.000 | 99.219 / 100.000 / 100.000 | 0.00143197 |
| analytic | frozen / U256 | 128 | 67.383 / 96.582 / 90.137 | 16.016 / 87.109 / 64.453 | 0.659964 |
| analytic | frozen / U256 | 64 | 99.805 / 100.000 / 100.000 | 99.219 / 100.000 / 100.000 | 0.00136535 |
| analytic | joint / CPU20.0 | 128 | 76.660 / 93.652 / 96.973 | 30.859 / 76.953 / 87.891 | 0.608692 |
| analytic | joint / CPU20.0 | 64 | 99.023 / 99.902 / 100.000 | 96.094 / 99.609 / 100.000 | 0.0134945 |
| analytic | joint / U256 | 128 | 78.516 / 93.652 / 82.520 | 34.766 / 76.953 / 42.188 | 0.909095 |
| analytic | joint / U256 | 64 | 99.316 / 99.902 / 99.609 | 97.266 / 99.609 / 98.438 | 0.0115501 |
| shared SDPA | joint / U1024 | 128 | 63.770 / 93.848 / 90.137 | 13.281 / 76.953 / 63.281 | 0.71508 |
| shared SDPA | joint / U1024 | 64 | 99.805 / 100.000 / 100.000 | 99.219 / 100.000 / 100.000 | 0.00207633 |
| two_gate | frozen / CPU20.0 | 128 | 72.266 / 97.070 / 78.223 | 25.391 / 89.453 / 33.594 | 0.692299 |
| two_gate | frozen / CPU20.0 | 64 | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.00070482 |
| two_gate | frozen / U256 | 128 | 66.699 / 96.680 / 91.113 | 16.016 / 87.891 / 67.578 | 0.643266 |
| two_gate | frozen / U256 | 64 | 99.902 / 100.000 / 100.000 | 99.609 / 100.000 / 100.000 | 0.00122252 |
| two_gate | joint / CPU20.0 | 128 | 79.102 / 88.184 / 85.645 | 40.234 / 59.766 / 51.562 | 1.07759 |
| two_gate | joint / CPU20.0 | 64 | 99.902 / 99.414 / 99.805 | 99.609 / 98.047 / 99.219 | 0.0110672 |
| two_gate | joint / U256 | 128 | 76.465 / 93.555 / 81.543 | 36.328 / 75.781 / 41.797 | 0.99962 |
| two_gate | joint / U256 | 64 | 99.707 / 99.902 / 99.805 | 98.828 / 99.609 / 99.219 | 0.00875689 |

例如Copy analytic的长128 exact跨全部预定候选/seed为0.781%–37.891%，two_gate为3.125%–10.156%；存在一个seed的较大改善，也存在同模式其他seed退化。MQAR长128 analytic exact为16.016%–87.891%，two_gate为16.016%–89.453%。这些范围描述全部结果，不能按不同设置的最大值作公平优劣比较，公平比较以同seed/模式/预算的paired文件为准。

## 6. 所有预定干预与adapter关闭

content_shuffle保留原gold而破坏输入内容关系；MQAR query_permute同时变换query与正确gold，检验查询敏感性。missing_audio/video测试移除相应有效payload与元数据；binding metadata_only清零payload、保留age/availability/固定时钟，以检查PTS或录制指纹；modality_mismatch仅用于情绪任务，不能被解释成binding准确率。adapter_disabled在同一选中checkpoint上跳过动态适配器，不重新训练。

核心诊断结果是：Copy/MQAR关闭任一种adapter之后，ID仍在全部三seed/设置达到100% query与exact；说明当前ID正确性不需要解析适配器。内容打乱使Copy exact降至0%，MQAR exact降至8.984%，而MQAR正确同步置换query/gold仍100%；这支持共同内容寻址确实利用了值/查询关系。MQAR打乱仅重排已有四个值，可能保留原位置和重复值，不能把该诊断的准确率与无条件8类随机猜测直接比较。

AV binding所有analytic的normal、单模态、metadata_only、adapter_disabled均50%；内容打乱少数设置可到54.167%，但没有从normal的50%建立可靠绑定能力。训练数据的单模态完整输入字节边缘平衡测试通过，构造按source固定缓存并平衡正负重复，因此单独任一模态的输入分布不能提供配对标签信息；机会水平表现本身也不证明模型学会了双模态关系。该旧cohort每actor的固定DFA句只有六种情绪各一条，within-actor derangement同时改变情绪，仍不能分离一般语义对应、情绪一致性和录制指纹。

### Selective Copy：全部诊断

| family | 模式/预算 | 干预 | Q% 三seed | exact% 三seed | CE均值 |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 8.97831 |
| analytic | frozen / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000205322 |
| analytic | frozen / U256 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 8.97947 |
| analytic | frozen / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000205322 |
| analytic | joint / CPU20.0 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 12.1709 |
| analytic | joint / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 7.02844e-06 |
| analytic | joint / U256 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 12.2545 |
| analytic | joint / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 6.52736e-06 |
| shared SDPA | joint / U1024 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 8.95021 |
| two_gate | frozen / CPU20.0 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 8.99693 |
| two_gate | frozen / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000205322 |
| two_gate | frozen / U256 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 8.97562 |
| two_gate | frozen / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000205322 |
| two_gate | joint / CPU20.0 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 13.6755 |
| two_gate | joint / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 1.25362e-06 |
| two_gate | joint / U256 | content_shuffle | 16.113 / 16.113 / 16.113 | 0.000 / 0.000 / 0.000 | 12.342 |
| two_gate | joint / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 6.45548e-06 |

### MQAR：全部诊断

| family | 模式/预算 | 干预 | Q% 三seed | exact% 三seed | CE均值 |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 6.92549 |
| analytic | frozen / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000254947 |
| analytic | frozen / CPU20.0 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000229725 |
| analytic | frozen / U256 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 6.92857 |
| analytic | frozen / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000254947 |
| analytic | frozen / U256 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000228139 |
| analytic | joint / CPU20.0 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 7.96287 |
| analytic | joint / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000142035 |
| analytic | joint / CPU20.0 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000145637 |
| analytic | joint / U256 | content_shuffle | 33.203 / 33.203 / 33.301 | 8.984 / 8.984 / 8.984 | 8.14026 |
| analytic | joint / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000115405 |
| analytic | joint / U256 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000122666 |
| shared SDPA | joint / U1024 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 6.86337 |
| shared SDPA | joint / U1024 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000255152 |
| two_gate | frozen / CPU20.0 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 6.98831 |
| two_gate | frozen / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000254947 |
| two_gate | frozen / CPU20.0 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000205674 |
| two_gate | frozen / U256 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 6.93887 |
| two_gate | frozen / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000254947 |
| two_gate | frozen / U256 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000223717 |
| two_gate | joint / CPU20.0 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 9.65659 |
| two_gate | joint / CPU20.0 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 8.83178e-06 |
| two_gate | joint / CPU20.0 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 8.66402e-06 |
| two_gate | joint / U256 | content_shuffle | 33.203 / 33.203 / 33.203 | 8.984 / 8.984 / 8.984 | 8.23395 |
| two_gate | joint / U256 | normal_adapter_disabled | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000111469 |
| two_gate | joint / U256 | query_permute | 100.000 / 100.000 / 100.000 | 100.000 / 100.000 / 100.000 | 0.000113243 |

### AV 情绪：全部诊断

| family | 模式/预算 | 干预 | Q% 三seed | exact% 三seed | CE均值 |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | content_shuffle | 8.333 / 8.333 / 8.333 | 8.333 / 8.333 / 8.333 | 1.89479 |
| analytic | frozen / CPU20.0 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.85875 |
| analytic | frozen / CPU20.0 | missing_video | 25.000 / 8.333 / 16.667 | 25.000 / 8.333 / 16.667 | 1.84155 |
| analytic | frozen / CPU20.0 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.8833 |
| analytic | frozen / CPU20.0 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| analytic | frozen / U256 | content_shuffle | 8.333 / 8.333 / 8.333 | 8.333 / 8.333 / 8.333 | 1.89479 |
| analytic | frozen / U256 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.85875 |
| analytic | frozen / U256 | missing_video | 25.000 / 8.333 / 16.667 | 25.000 / 8.333 / 16.667 | 1.84155 |
| analytic | frozen / U256 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.8833 |
| analytic | frozen / U256 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| analytic | joint / CPU20.0 | content_shuffle | 8.333 / 16.667 / 8.333 | 8.333 / 16.667 / 8.333 | 1.91858 |
| analytic | joint / CPU20.0 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.91074 |
| analytic | joint / CPU20.0 | missing_video | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.886 |
| analytic | joint / CPU20.0 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.92556 |
| analytic | joint / CPU20.0 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| analytic | joint / U256 | content_shuffle | 8.333 / 16.667 / 8.333 | 8.333 / 16.667 / 8.333 | 1.91858 |
| analytic | joint / U256 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.91074 |
| analytic | joint / U256 | missing_video | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.886 |
| analytic | joint / U256 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.92556 |
| analytic | joint / U256 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| shared SDPA | joint / U512 | content_shuffle | 8.333 / 16.667 / 8.333 | 8.333 / 16.667 / 8.333 | 1.91724 |
| shared SDPA | joint / U512 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.90929 |
| shared SDPA | joint / U512 | missing_video | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.89978 |
| shared SDPA | joint / U512 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.92456 |
| two_gate | frozen / CPU20.0 | content_shuffle | 8.333 / 0.000 / 8.333 | 8.333 / 0.000 / 8.333 | 1.87748 |
| two_gate | frozen / CPU20.0 | missing_audio | 25.000 / 16.667 / 16.667 | 25.000 / 16.667 / 16.667 | 1.85684 |
| two_gate | frozen / CPU20.0 | missing_video | 25.000 / 8.333 / 16.667 | 25.000 / 8.333 / 16.667 | 1.86033 |
| two_gate | frozen / CPU20.0 | modality_mismatch | 25.000 / 16.667 / 16.667 | 25.000 / 16.667 / 16.667 | 1.8866 |
| two_gate | frozen / CPU20.0 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| two_gate | frozen / U256 | content_shuffle | 8.333 / 0.000 / 8.333 | 8.333 / 0.000 / 8.333 | 1.87748 |
| two_gate | frozen / U256 | missing_audio | 25.000 / 16.667 / 16.667 | 25.000 / 16.667 / 16.667 | 1.85684 |
| two_gate | frozen / U256 | missing_video | 25.000 / 8.333 / 16.667 | 25.000 / 8.333 / 16.667 | 1.86033 |
| two_gate | frozen / U256 | modality_mismatch | 25.000 / 16.667 / 16.667 | 25.000 / 16.667 / 16.667 | 1.8866 |
| two_gate | frozen / U256 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| two_gate | joint / CPU20.0 | content_shuffle | 8.333 / 16.667 / 8.333 | 8.333 / 16.667 / 8.333 | 1.91811 |
| two_gate | joint / CPU20.0 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.90928 |
| two_gate | joint / CPU20.0 | missing_video | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90076 |
| two_gate | joint / CPU20.0 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.92533 |
| two_gate | joint / CPU20.0 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |
| two_gate | joint / U256 | content_shuffle | 8.333 / 16.667 / 8.333 | 8.333 / 16.667 / 8.333 | 1.91811 |
| two_gate | joint / U256 | missing_audio | 16.667 / 16.667 / 8.333 | 16.667 / 16.667 / 8.333 | 1.90928 |
| two_gate | joint / U256 | missing_video | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90076 |
| two_gate | joint / U256 | modality_mismatch | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.92533 |
| two_gate | joint / U256 | normal_adapter_disabled | 25.000 / 0.000 / 16.667 | 25.000 / 0.000 / 16.667 | 1.90501 |

### AV recording binding：全部诊断

| family | 模式/预算 | 干预 | Q% 三seed | exact% 三seed | CE均值 |
| --- | --- | --- | --- | --- | --- |
| analytic | frozen / CPU20.0 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693259 |
| analytic | frozen / CPU20.0 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693173 |
| analytic | frozen / CPU20.0 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693291 |
| analytic | frozen / CPU20.0 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694221 |
| analytic | frozen / CPU20.0 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693447 |
| analytic | frozen / U256 | content_shuffle | 54.167 / 50.000 / 50.000 | 54.167 / 50.000 / 50.000 | 0.693243 |
| analytic | frozen / U256 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693168 |
| analytic | frozen / U256 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.69326 |
| analytic | frozen / U256 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694218 |
| analytic | frozen / U256 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693447 |
| analytic | joint / CPU20.0 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693451 |
| analytic | joint / CPU20.0 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693312 |
| analytic | joint / CPU20.0 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693462 |
| analytic | joint / CPU20.0 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694759 |
| analytic | joint / CPU20.0 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693432 |
| analytic | joint / U256 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693466 |
| analytic | joint / U256 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693286 |
| analytic | joint / U256 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693469 |
| analytic | joint / U256 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694764 |
| analytic | joint / U256 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693447 |
| shared SDPA | joint / U512 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693448 |
| shared SDPA | joint / U512 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693273 |
| shared SDPA | joint / U512 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693481 |
| shared SDPA | joint / U512 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.695016 |
| two_gate | frozen / CPU20.0 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693203 |
| two_gate | frozen / CPU20.0 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693155 |
| two_gate | frozen / CPU20.0 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693225 |
| two_gate | frozen / CPU20.0 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694429 |
| two_gate | frozen / CPU20.0 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693447 |
| two_gate | frozen / U256 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693359 |
| two_gate | frozen / U256 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693213 |
| two_gate | frozen / U256 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693397 |
| two_gate | frozen / U256 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694784 |
| two_gate | frozen / U256 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693447 |
| two_gate | joint / CPU20.0 | content_shuffle | 50.000 / 50.000 / 45.833 | 50.000 / 50.000 / 45.833 | 0.703659 |
| two_gate | joint / CPU20.0 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693539 |
| two_gate | joint / CPU20.0 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.704781 |
| two_gate | joint / CPU20.0 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694892 |
| two_gate | joint / CPU20.0 | normal_adapter_disabled | 50.000 / 50.000 / 41.667 | 50.000 / 50.000 / 41.667 | 0.71289 |
| two_gate | joint / U256 | content_shuffle | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.69344 |
| two_gate | joint / U256 | metadata_only | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693266 |
| two_gate | joint / U256 | missing_audio | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693474 |
| two_gate | joint / U256 | missing_video | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.694982 |
| two_gate | joint / U256 | normal_adapter_disabled | 50.000 / 50.000 / 50.000 | 50.000 / 50.000 / 50.000 | 0.693447 |

以上覆盖每个预定干预，不挑选有利子组。逐job相对于normal的差在[diagnostics.json](results/content_analysis001/diagnostics.json)，其余actor重采样和paired区间在[paired_bootstrap.json](results/content_analysis001/paired_bootstrap.json)。

## 7. 参数公平性、更新与冻结证据

| 任务 | shared参数 | two_gate总参数 | analytic总参数 | analytic多参数 | 相对two_gate |
| --- | --- | --- | --- | --- | --- |
| Selective Copy | 20712 | 28008 | 29487 | 1479 | 5.281% |
| MQAR | 20712 | 28008 | 29487 | 1479 | 5.281% |
| AV 情绪 | 22022 | 29318 | 30797 | 1479 | 5.045% |
| AV recording binding | 21890 | 29186 | 30665 | 1479 | 5.067% |

所有core使用相同共同encoder/attention/readout初始化；frozen模式共同参数严格冻结。两个adapter并非总参数完全匹配：two_gate为7296参数，analytic为8775，多1479（adapter自身多20.271%）。因此结果不能被描述为严格等总参数。

48个analytic worker最终checkpoint的content、dynamics、boundary、reset、refractory五组都实际更新，且训练梯度有限；选中checkpoint有35/48保留了五组更新，另外13个选择了初始adapter。梯度存在证明训练路径可用，不证明选中模型靠该动力学提高了任务成绩。冻结encoder的逐字节证据、initial_parameters、selected/final checkpoint及各组变化都保留于每个job。 [汇总](results/content_analysis001/jobs.json)

| 任务 | 24适配jobs中selected step0 | 其中analytic step0 | 继承未训练donor的jobs |
| --- | --- | --- | --- |
| Selective Copy | 0 | 0 | 0 |
| MQAR | 3 | 2 | 0 |
| AV 情绪 | 12 | 6 | 24 |
| AV recording binding | 8 | 5 | 0 |

## 8. 完整执行成本、训练预算与推理profile

content研究实际唯一worker CPU为 **2180.01233秒**，其中共同预训练12个worker共92.16745秒，只计一次。两worker并发的研究wall为1102.70416秒；supervisor自身CPU3.08337秒另列。最大单worker峰值RSS为331.305 MiB，不能当作并发进程总内存。后处理分析CPU为7.712542秒，归档成本将另外记录。 [完整进程账本](overview/content_meter.json) · [全部receipt](results/content001/meter/receipts)

成本有包含关系：optimizer更新与训练内验证属于training budget；training、数据准备、选中后推理/诊断、序列化属于worker body；完整子进程还包括import/startup。不能把这些嵌套分项相加。固定20 CPU秒按循环计费，可能超出一个batch/验证；表中报告实际训练CPU。任何独立部署若需从头获得共同encoder，可为单条pipeline计一个完整shared预训练worker加一个适配worker；共享同一donor的研究总账不能按八条适配路径重复收费。

| 任务 | family | 模式/预算 | 实际updates三seed | 实际training CPU均秒 | 完整worker CPU均秒 | 含一次预训练pipeline CPU均秒 | 峰值单worker MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Selective Copy | shared SDPA | joint/updates_1024 | 1024 / 1024 / 1024 | 7.404 | 10.041 | 10.041 | 312.2 |
| Selective Copy | two_gate | frozen/cpu_20.0 | 1180 / 1216 / 1161 | 20.031 | 23.282 | 33.323 | 315.3 |
| Selective Copy | two_gate | frozen/updates_256 | 256 / 256 / 256 | 4.210 | 7.500 | 17.541 | 315.3 |
| Selective Copy | two_gate | joint/cpu_20.0 | 1032 / 977 / 904 | 20.059 | 23.425 | 33.466 | 309.7 |
| Selective Copy | two_gate | joint/updates_256 | 256 / 256 / 256 | 5.217 | 8.417 | 18.458 | 317.5 |
| Selective Copy | analytic | frozen/cpu_20.0 | 246 / 232 / 232 | 20.274 | 29.407 | 39.448 | 328.8 |
| Selective Copy | analytic | frozen/updates_256 | 256 / 256 / 256 | 21.480 | 30.687 | 40.728 | 327.4 |
| Selective Copy | analytic | joint/cpu_20.0 | 239 / 226 / 243 | 20.275 | 29.582 | 39.623 | 331.3 |
| Selective Copy | analytic | joint/updates_256 | 256 / 256 / 256 | 22.265 | 31.309 | 41.350 | 330.6 |
| MQAR | shared SDPA | joint/updates_1024 | 1024 / 1024 / 1024 | 7.159 | 9.740 | 9.740 | 306.3 |
| MQAR | two_gate | frozen/cpu_20.0 | 1144 / 1318 / 1190 | 20.049 | 23.558 | 33.298 | 309.4 |
| MQAR | two_gate | frozen/updates_256 | 256 / 256 / 256 | 4.412 | 8.070 | 17.810 | 309.2 |
| MQAR | two_gate | joint/cpu_20.0 | 938 / 1032 / 1025 | 20.047 | 23.585 | 33.325 | 311.6 |
| MQAR | two_gate | joint/updates_256 | 256 / 256 / 256 | 4.991 | 8.415 | 18.155 | 311.0 |
| MQAR | analytic | frozen/cpu_20.0 | 246 / 225 / 239 | 20.266 | 29.869 | 39.609 | 327.9 |
| MQAR | analytic | frozen/updates_256 | 256 / 256 / 256 | 21.499 | 31.389 | 41.129 | 329.4 |
| MQAR | analytic | joint/cpu_20.0 | 211 / 226 / 233 | 20.259 | 30.530 | 40.270 | 329.6 |
| MQAR | analytic | joint/updates_256 | 256 / 256 / 256 | 22.722 | 32.409 | 42.149 | 330.8 |
| AV 情绪 | shared SDPA | joint/updates_512 | 512 / 512 / 512 | 3.523 | 5.961 | 5.961 | 277.6 |
| AV 情绪 | two_gate | frozen/cpu_20.0 | 866 / 908 / 890 | 20.026 | 22.518 | 28.479 | 281.5 |
| AV 情绪 | two_gate | frozen/updates_256 | 256 / 256 / 256 | 5.973 | 8.518 | 14.479 | 281.3 |
| AV 情绪 | two_gate | joint/cpu_20.0 | 691 / 745 / 718 | 20.034 | 22.561 | 28.522 | 283.5 |
| AV 情绪 | two_gate | joint/updates_256 | 256 / 256 / 256 | 7.218 | 9.821 | 15.782 | 283.5 |
| AV 情绪 | analytic | frozen/cpu_20.0 | 164 / 173 / 177 | 20.126 | 23.483 | 29.444 | 301.5 |
| AV 情绪 | analytic | frozen/updates_256 | 256 / 256 / 256 | 30.599 | 33.982 | 39.942 | 301.1 |
| AV 情绪 | analytic | joint/cpu_20.0 | 166 / 169 / 169 | 20.121 | 23.462 | 29.423 | 301.8 |
| AV 情绪 | analytic | joint/updates_256 | 256 / 256 / 256 | 30.550 | 33.895 | 39.855 | 302.3 |
| AV recording binding | shared SDPA | joint/updates_512 | 512 / 512 / 512 | 2.700 | 4.981 | 4.981 | 275.6 |
| AV recording binding | two_gate | frozen/cpu_20.0 | 1575 / 1633 / 1668 | 20.018 | 22.474 | 27.455 | 277.8 |
| AV recording binding | two_gate | frozen/updates_256 | 256 / 256 / 256 | 3.290 | 5.717 | 10.698 | 277.7 |
| AV recording binding | two_gate | joint/cpu_20.0 | 1251 / 1284 / 1262 | 20.022 | 22.486 | 27.467 | 279.5 |
| AV recording binding | two_gate | joint/updates_256 | 256 / 256 / 256 | 4.170 | 6.471 | 11.452 | 278.5 |
| AV recording binding | analytic | frozen/cpu_20.0 | 325 / 299 / 303 | 20.137 | 23.521 | 28.502 | 287.0 |
| AV recording binding | analytic | frozen/updates_256 | 256 / 256 / 256 | 17.530 | 21.019 | 26.000 | 286.8 |
| AV recording binding | analytic | joint/cpu_20.0 | 292 / 300 / 288 | 20.114 | 23.401 | 28.382 | 287.9 |
| AV recording binding | analytic | joint/updates_256 | 256 / 256 / 256 | 17.750 | 21.183 | 26.164 | 288.1 |

### Prepared-feature推理：实际单请求延迟与吞吐

以下是每个selected checkpoint在验证集上batch1完整序列推理的一次profile，包含tensor_batch、whole-sequence forward、监督读出和ID提取；显示三seed统计的算术均值，p50/p95为各seed内部request分位数再取均值，不是合并后的分位数。准备原始NPZ/窗口压缩另计。该测试没有增量KV cache，也不包括codec、传感器、网络或设备能耗；并发实验环境可影响wall-time，应结合CPU与raw profile解释。

| 任务 | family | 模式/预算 | 平均request ms | p50 ms | p95 ms | sequences/s | queries/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Selective Copy | shared SDPA | joint/updates_1024 | 0.831 | 0.860 | 1.052 | 1220.3 | 4881.4 |
| Selective Copy | two_gate | frozen/cpu_20.0 | 2.912 | 2.849 | 3.311 | 342.7 | 1370.8 |
| Selective Copy | two_gate | frozen/updates_256 | 2.960 | 2.866 | 3.480 | 337.1 | 1348.5 |
| Selective Copy | two_gate | joint/cpu_20.0 | 3.088 | 3.008 | 3.755 | 323.2 | 1293.0 |
| Selective Copy | two_gate | joint/updates_256 | 2.935 | 2.825 | 3.405 | 340.2 | 1360.7 |
| Selective Copy | analytic | frozen/cpu_20.0 | 21.890 | 21.220 | 25.225 | 45.7 | 182.7 |
| Selective Copy | analytic | frozen/updates_256 | 21.989 | 21.199 | 25.682 | 45.5 | 182.0 |
| Selective Copy | analytic | joint/cpu_20.0 | 22.735 | 21.891 | 26.426 | 44.0 | 175.9 |
| Selective Copy | analytic | joint/updates_256 | 22.090 | 21.549 | 25.522 | 45.3 | 181.0 |
| MQAR | shared SDPA | joint/updates_1024 | 0.764 | 0.728 | 0.966 | 1309.3 | 5237.2 |
| MQAR | two_gate | frozen/cpu_20.0 | 3.208 | 2.935 | 4.895 | 311.3 | 1245.0 |
| MQAR | two_gate | frozen/updates_256 | 3.110 | 2.844 | 4.254 | 323.8 | 1295.3 |
| MQAR | two_gate | joint/cpu_20.0 | 3.183 | 2.926 | 4.118 | 316.9 | 1267.8 |
| MQAR | two_gate | joint/updates_256 | 3.211 | 3.164 | 3.863 | 314.4 | 1257.7 |
| MQAR | analytic | frozen/cpu_20.0 | 22.100 | 21.272 | 25.740 | 45.3 | 181.0 |
| MQAR | analytic | frozen/updates_256 | 23.109 | 22.019 | 30.678 | 43.3 | 173.3 |
| MQAR | analytic | joint/cpu_20.0 | 23.058 | 21.659 | 30.275 | 43.4 | 173.6 |
| MQAR | analytic | joint/updates_256 | 22.099 | 21.282 | 26.171 | 45.3 | 181.0 |
| AV 情绪 | shared SDPA | joint/updates_512 | 1.172 | 1.157 | 1.484 | 867.5 | 867.5 |
| AV 情绪 | two_gate | frozen/cpu_20.0 | 4.322 | 4.028 | 5.814 | 230.8 | 230.8 |
| AV 情绪 | two_gate | frozen/updates_256 | 4.220 | 4.105 | 5.257 | 236.2 | 236.2 |
| AV 情绪 | two_gate | joint/cpu_20.0 | 5.527 | 5.483 | 7.672 | 189.8 | 189.8 |
| AV 情绪 | two_gate | joint/updates_256 | 4.345 | 4.123 | 5.545 | 229.4 | 229.4 |
| AV 情绪 | analytic | frozen/cpu_20.0 | 30.422 | 30.796 | 35.105 | 32.9 | 32.9 |
| AV 情绪 | analytic | frozen/updates_256 | 29.756 | 29.366 | 36.698 | 33.7 | 33.7 |
| AV 情绪 | analytic | joint/cpu_20.0 | 31.218 | 29.312 | 41.082 | 32.3 | 32.3 |
| AV 情绪 | analytic | joint/updates_256 | 31.407 | 29.768 | 40.237 | 32.0 | 32.0 |
| AV recording binding | shared SDPA | joint/updates_512 | 0.896 | 0.837 | 1.092 | 1108.1 | 1108.1 |
| AV recording binding | two_gate | frozen/cpu_20.0 | 3.071 | 2.890 | 4.312 | 324.6 | 324.6 |
| AV recording binding | two_gate | frozen/updates_256 | 3.030 | 2.904 | 3.809 | 329.7 | 329.7 |
| AV recording binding | two_gate | joint/cpu_20.0 | 2.905 | 2.865 | 3.137 | 343.3 | 343.3 |
| AV recording binding | two_gate | joint/updates_256 | 2.930 | 2.839 | 3.379 | 340.2 | 340.2 |
| AV recording binding | analytic | frozen/cpu_20.0 | 23.274 | 21.797 | 29.866 | 43.4 | 43.4 |
| AV recording binding | analytic | frozen/updates_256 | 23.064 | 21.229 | 31.458 | 43.5 | 43.5 |
| AV recording binding | analytic | joint/cpu_20.0 | 21.254 | 21.070 | 22.983 | 47.0 | 47.0 |
| AV recording binding | analytic | joint/updates_256 | 21.355 | 21.320 | 22.993 | 46.8 | 46.8 |

每个test条件还单独保存实际batch推理CPU/wall、逐batch样本/queries数与吞吐，包含长度64/128的成本；均在[metrics.json](results/content_analysis001/metrics.json)和各job原始summary中。平均训练步时长或20秒预算没有被用作推理速度替代指标。直接energy_joules为null，不能换算为已测得的节能优势。

## 9. 本轮能够支持与尚不能支持的结论

1. **可训练实现得到支持。** 解析适配器通过共同内容路径参与任务loss，五组参数最终确实更新，冻结/联合实验与raw checkpoint可复核。这里使用有限网格再生推进器，不是全局连续He–Xiong金融模型的原封闭式神经实现。
2. **合成ID内容瓶颈由共享结构解决。** 显式因果计数/顺序地址及共同SDPA已使无动态core基线100%；关掉adapter仍100%。不能把这些能力归到call/put算子。
3. **局部OOD变化保留为后续线索。** 存在analytic长128改善的seed，但同设置其他seed也会退化，exact远未稳定99%，paired区间跨0。它不构成可靠的长上下文优势。
4. **自然AV能力仍受内容前端阻碍。** 情绪共享encoder三seed全部回到step0；binding为机会水平。旧两actor测试以及固定DFA/情绪结构不能支撑foundation或全模态encoder结论。
5. **当前实现没有实际成本优势。** 所有ID配对完整worker CPU和prepared-input p50都更高；固定CPU预算与相同步数都保留负结果。优化未来kernel可能改变成本，但本轮没有测量该系统。

因此，本轮完整执行了预定内容机制和预算对照，并给出可复核的正负证据；继续扩大模型之前，应先以更强且确实学到内容的共同encoder、更新且多actor的真实多模态任务，以及明确的增量流式执行模型解决尚未闭合的部分。当前共同attention仍在承担内容寻址和长序列成本，不能据此主张已经替代Transformer或证明相对传统SNN/全模态大模型的优势。

## 10. 复核入口

- [raw worker目录](results/content001/jobs)：108份job、selection、初始/selected/final checkpoint、trace、raw predictions、source identity、数据及推理成本。
- [analysis manifest](results/content_analysis001/manifest.json)：所有输入文件SHA、分析器SHA、问题列表和完整成本。
- [metrics](results/content_analysis001/metrics.json)、[aggregates](results/content_analysis001/aggregates.json)、[paired seeds](results/content_analysis001/paired_seeds.json)、[paired bootstrap](results/content_analysis001/paired_bootstrap.json)、[diagnostics](results/content_analysis001/diagnostics.json)、[cost aggregates](results/content_analysis001/cost_aggregates.json)。
- [完整开发证据索引](development/content_evidence/CONTENT_INDEX.json)：保留无地址Copy失败、AV随机donor、binding机会水平等开发负结果。早期dev缺少历史源码blob快照的限制已明确，不以其替代正式冻结源码证据。

## 11. 不可覆盖归档与成本

原始`results/content001`和`results/content_analysis001`均保持不变。分别使用既有`archive.pack/restore`生成连续XZ流、262144-byte分片，恢复到全新目录，再逐文件对照原件与manifest的大小和SHA-256。全部成员集与校验值一致。

| 包 | 成员 | 原始bytes | 压缩bytes | 分片 | 打包/恢复/核验完整子进程CPU秒 |
| --- | --- | --- | --- | --- | --- |
| content001 | 2448（含324个checkpoint和717个raw预测表） | 149121856 | 47716564 | 183 | 35.658287 |
| content_analysis001 | 8 | 5208677 | 442420 | 2 | 1.076759 |

`content001` archive SHA-256：`a58534aec1c9bcad5c7cda65659c4d6f03bfb372c7b442767ee0a0fe0d90bd7f`。

`content_analysis001` archive SHA-256：`6a28afaa0ae16459e313c9b4d9b6079e48780996ecd8fb93fa111b7e14ac6cba`。

这些归档成本独立于模型worker的2180.01233 CPU秒，不混入训练预算。分析清单的7.712542秒是分析器内部CPU计时，不声称包含该分析进程的全部import/startup。归档的完整子进程成本由Linux wait4测量；具体分项、峰值内存和恢复收据见[raw包VERIFICATION](artifacts/content001/VERIFICATION.json)、[raw包WHOLE_PROCESS](artifacts/content001/WHOLE_PROCESS.json)、[analysis包VERIFICATION](artifacts/content_analysis001/VERIFICATION.json)和[analysis包WHOLE_PROCESS](artifacts/content_analysis001/WHOLE_PROCESS.json)。
