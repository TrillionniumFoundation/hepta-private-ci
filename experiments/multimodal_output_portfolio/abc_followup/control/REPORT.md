# Control follow-up：同来源质量、真实成本与精确缓存

本轮研究原有 NDU 图文生成器上的控制成本，并检验去除额外 CNN 的紧凑条件价值方案。本控制实验未重新训练生成器；新的训练由独立 training 目录报告。

## 0. 主要结论

完整81,920次真实请求完成，失败0、必需模态完成率100%。预选 exact cache 与旧反馈的20,480个实际配对输出、动作和运行时ledger逐值相同，平均wall减少 **0.637170 ms**。相对开发阶段选出的强非反馈对照，raw CE提高 **0.01210811**，成功率提高 **0.932617个百分点**，两项名义97.5%区间下端均为正；两个注册主要家族均满足既定规则。

相对强非反馈，cached仍增加 **1.085912 ms** 平均wall。预先声明的价格网格同时bands均未排除零，因此本轮支持在所评估census中保持原输出的缓存加速及限定任务上的公开反馈收益，尚未证明统一置信的真实资源成本补偿。紧凑头的成功率下降仍然存在，不能用其低延迟替代成功率要求。

## 1. 开发结果与冻结选择

仅复用已经读取的历史 forecast_fit[480,736) 和 forecast_calibration[448,576) 作为开发数据。它们没有被重新命名为未见验证。每个 seed 的21条实际候选路径重新生成、保存、回读并由 primary observer 评分。

紧凑头以384维当前生成器状态、192维实际 caption one-hot 和1维剩余预算为输入，共享64宽 trunk 预测5个正值条件风险矩和5个成功概率，共37,642参数，无额外 CNN。来源两折的 H1 预测产生 H2 目标，未以事后最佳未来作为在线信息或 Bellman 标签。预测成功率限制要求所选动作距预测最优成功率不超过.02；这一学习约束不等于真实成功率保证。

开发选择预先要求 compact 相对 old feedback 的代理净 CE 不低于−.002，成功率不低于−.005。五个 seed 均未同时满足门槛，因此全部选择 exact cached feedback。没有根据开发失败放宽门槛，也没有丢弃紧凑方案；它继续作为正式描述性对照执行。

| Seed | Compact − old，代理 CE | 成功率差／百分点 | 冻结 candidate | 冻结强非反馈 |
| --- | ---: | ---: | --- | --- |
| 17 | +0.00098209 | -0.781250 | cached | fixed |
| 29 | -0.00851215 | -1.416016 | cached | one_shot |
| 43 | +0.00420773 | -0.585938 | cached | static |
| 59 | +0.00565492 | -0.537109 | cached | static |
| 71 | -0.00774849 | -1.611328 | cached | one_shot |

Exact cache 保持原有反馈权重和763维公开特征。只有当前实际 draft 像素逐值相等时，才复用 generator draft encoder 与 public reader 的视觉结果；latent、caption 和预算每步重算。共享语义或文字动作不改变图像时可避免重复 CNN。One-shot 对照获得相同缓存能力；所有对照均保留相同的共享内容动作权限。

开发入口计时：wall **439.898012482 s**，process CPU **439.731953182 s**。这包含来源构造、实际开发树、拟合和选择，不包含 interpreter startup/import 或最终 result JSON 写出；不是纯梯度训练时长。成功或失败候选的开发成本均保留。[DEVELOPMENT.json](DEVELOPMENT.json)

## 2. 正式来源、比较与测量边界

正式评价固定 test[512,768)：256个来源对、512张不同原图、8个视图、2个生成场景和5个已有 NDU 模型 seed。四策略各实际执行20,480次请求，共81,920次。Selected feedback 只引用事前选定 candidate 的实际行，不增加物理请求或独立 N。Root 的新生成器实验使用同一256来源组，双方不能算成512个独立来源组。

SOURCE_ALLOCATION 对所有历史角色与新 native 角色检查 individual ID 和像素 SHA 的交集，并包括16个大型历史 metadata 文件的完整结构化扫描。旧 test[0,512) 已用于历史评价；新 native calibration[768,1568) 和 verification[1568,3000) 与本组分离。原始 writer cluster 不可得，因此不声称 writer 级独立性。

每次 resident 请求包含 owner RNG、真实初始化/选定动作/发射、公开特征与策略、无损 NPZ 序列化、append+fsync、同一仍打开文件描述符上的回读与 hash 核查。请求之后关闭整个媒体文件，再回读并由两个冻结 observer 离线评分。单请求端点是 durable local output；不包含网络交付或设备显示。原运行时的动作提交在进程内先于 future draws，不是 crash-durable action journal。

模型装载、来源准备、离线评分、分析及开发训练分账；完整 child 进程另由 exact-PID wait4 测量。同组策略执行顺序循环轮换。共享主机不等于隔离硬件，所有 outlier 保留。

两个主要比较家族使用4,000次配对来源×seed bootstrap、名义双侧97.5%区间：

- Candidate 对强非反馈：raw CE 下端>0，且 success 下端≥0，零成功率 margin。
- Candidate 对 old feedback：raw CE 与 success 下端分别≥−.005，且平均 wall 差上端<0。

后一项是事前规定的有界替代问题，不能改写成全局无损保证。精确 cache 另做逐请求 output/path/ledger 身份核对。有限五 seed 的 percentile 覆盖没有总体保证。

CE 先在每个已训练模型的4,096个来源/视图/场景输出上计算，再对五个模型做算术平均。训练 seed 没有被当成额外生成样本混入一次指数风险聚合。等权来源内预聚合与直接在该模型全部输出上计算CE等价。每来源/视图只有两个生成场景，这是有限样本 plug-in 估计；来源bootstrap不使条件尾部突然精确，也不提供无偏总体CE。

## 3. 正式实际执行

完成状态：**complete**。Census：**81,920** 请求。

请求失败 0；old/cache 匹配对 **20,480**；output/path/ledger 身份差异 **0**。

### 3.1 Primary 主要对比

| 比较 | Raw CE 差 | 名义97.5%区间 | 成功率差／百分点 | 同等级区间／百分点 |
| --- | ---: | --- | ---: | --- |
| selected_feedback_minus_reference | +0.01210811 | [+0.00087617, +0.02357147] | +0.932617 | [+0.258789, +1.625977] |
| selected_feedback_minus_old_feedback | +0.00000000 | [+0.00000000, +0.00000000] | +0.000000 | [+0.000000, +0.000000] |

| 注册家族 | 条件逐项 | 全部满足 |
| --- | --- | --- |
| new_feedback_quality_over_strong_nonfeedback | raw_CE_lower_positive=True; success_zero_margin_lower_nonnegative=True | True |
| efficient_replacement_of_old_feedback | mean_wall_cost_upper_negative=True; raw_CE_loss_within_.005=True; success_loss_within_.005=True | True |

### 3.2 策略质量与实际延迟

| 策略 | Raw CE | Exact success／% | 完成率／% | Wall mean ms | P50 ms | P95 ms | CPU mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| reference | 0.17301085 | 54.643555 | 100.000 | 8.909821 | 8.254817 | 12.477119 | 8.404294 |
| old_feedback | 0.18511895 | 55.576172 | 100.000 | 10.632903 | 10.737279 | 15.278023 | 10.075346 |
| cached_feedback | 0.18511895 | 55.576172 | 100.000 | 9.995733 | 9.870590 | 14.484232 | 9.464791 |
| compact_feedback | 0.18445292 | 54.755859 | 100.000 | 7.333039 | 7.408769 | 10.555640 | 6.831119 |

所有 seed 的 selected 都是 cached；上表 cached 即主要 candidate。这项选择在新来源之前冻结。紧凑策略的正式结果只作描述性分析，未被用于重新选择。

| 成本比较，candidate − reference | Mean wall ms | 名义97.5%区间 | P95 差 ms | 同等级区间 |
| --- | ---: | --- | ---: | --- |
| selected_feedback_minus_reference | +1.085912 | [+0.216322, +1.827584] | +2.007113 | [+0.761877, +3.820889] |
| selected_feedback_minus_old_feedback | -0.637170 | [-0.764726, -0.502532] | -0.793791 | [-1.079711, -0.519892] |

未被开发阶段选中的 compact 仍完整执行。其 primary observer 相对 old feedback 的描述性结果为：raw CE差 **-0.00066603**，95%区间 [-0.01056015, +0.00897186]；成功率差 **-0.820312个百分点**，95%区间 [-1.455078, -0.244141]；平均wall差 **-3.299864 ms**，95%区间 [-3.518819, -3.090540]。这不是替换冻结 candidate 的依据，也不能由单个改善指标宣称总体优越。

### 3.3 独立 Secondary observer

| 比较 | Raw CE 差 | 描述性95%区间 | 成功率差／百分点 | 描述性95%区间／百分点 |
| --- | ---: | --- | ---: | --- |
| selected_feedback_minus_reference | +0.01105534 | [+0.00064441, +0.02164054] | +1.079102 | [+0.517578, +1.635742] |
| selected_feedback_minus_old_feedback | +0.00000000 | [+0.00000000, +0.00000000] | +0.000000 | [+0.000000, +0.000000] |
| compact_feedback_minus_old_feedback | -0.00166860 | [-0.01107371, +0.00729957] | -0.742188 | [-1.416016, -0.102539] |

### 3.4 缺失信息、错误提示与尾部

| 视图 | Selected raw CE | Selected success／% | Reference raw CE | Reference success／% |
| --- | ---: | ---: | ---: | ---: |
| clean | 0.86819916 | 89.570312 | 0.85934278 | 88.359375 |
| noise | 0.84371859 | 89.140625 | 0.83844429 | 87.617188 |
| occlusion | 0.68740561 | 75.507812 | 0.67594435 | 74.843750 |
| missing_trusted | 0.88802272 | 89.609375 | 0.88577863 | 89.218750 |
| conflict_untrusted | 0.87287073 | 89.765625 | 0.85610052 | 88.203125 |
| missing_untrusted | 0.17721438 | 7.109375 | 0.16666251 | 5.898438 |
| missing_unknown | 0.12475745 | 3.906250 | 0.10919857 | 2.968750 |
| both_missing | -0.56326641 | 0.000000 | -0.57580282 | 0.039062 |

| 策略 | Mean loss | Output CVaR90 | Source-mean CVaR90 |
| --- | ---: | ---: | ---: |
| reference | 0.22410011 | 0.81554830 | 0.35889078 |
| old_feedback | 0.21976262 | 0.80896053 | 0.35476656 |
| cached_feedback | 0.21976262 | 0.80896053 | 0.35476656 |
| compact_feedback | 0.22218123 | 0.80644909 | 0.35677894 |

尾部是完整样本上的描述性经验值；先平均来源再取尾部改变了估计对象。没有统一条件尾部保证。完成率与事实正确率分开报告。

## 4. 实际价格敏感性

每个价格计算 **CE₂(U − λ·实际请求成本ms)**。质量和成本的同一行相关性保留；未使用 CE(U)−λE[C] 替代。预先指定8个价格分别作用于 wall 和 CPU，采用共同来源×seed 重采样产生有限网格上的名义95% max-deviation band。

### wall_ms

| λ，utility/ms | Candidate − reference CE | 描述性逐点95%区间 | 网格同时95%区间 | 同时下端>0 |
| --- | ---: | --- | --- | --- |
| 0.0000 | +0.01210811 | [+0.00213973, +0.02185113] | [-2.39233049, +2.41654670] | False |
| 0.0005 | +0.01159962 | [+0.00160582, +0.02124559] | [-2.39283898, +2.41603821] | False |
| 0.0010 | +0.01107678 | [+0.00103803, +0.02071712] | [-2.39336182, +2.41551537] | False |
| 0.0020 | +0.00997723 | [-0.00005703, +0.01974572] | [-2.39446136, +2.41441582] | False |
| 0.0050 | +0.00592228 | [-0.00478541, +0.01659089] | [-2.39851632, +2.41036087] | False |
| 0.0100 | -0.00939624 | [-0.04673547, +0.01115821] | [-2.41383483, +2.39504235] | False |
| 0.0200 | -0.24756630 | [-0.69297187, +0.00259277] | [-2.65200489, +2.15687229] | False |
| 0.0500 | -2.29123523 | [-4.60740336, +0.12410994] | [-4.69567382, +0.11320336] | False |

### cpu_ms

| λ，utility/ms | Candidate − reference CE | 描述性逐点95%区间 | 网格同时95%区间 | 同时下端>0 |
| --- | ---: | --- | --- | --- |
| 0.0000 | +0.01210811 | [+0.00213973, +0.02185113] | [-1.73934615, +1.76356236] | False |
| 0.0005 | +0.01161794 | [+0.00162916, +0.02126951] | [-1.73983632, +1.76307220] | False |
| 0.0010 | +0.01111726 | [+0.00108018, +0.02075048] | [-1.74033699, +1.76257152] | False |
| 0.0020 | +0.01007621 | [+0.00000953, +0.01993838] | [-1.74137805, +1.76153046] | False |
| 0.0050 | +0.00637905 | [-0.00456110, +0.01710456] | [-1.74507520, +1.75783331] | False |
| 0.0100 | -0.00677705 | [-0.04429638, +0.01343246] | [-1.75823130, +1.74467721] | False |
| 0.0200 | -0.20603448 | [-0.64286678, +0.00694819] | [-1.95748874, +1.54541978] | False |
| 0.0500 | -1.56946444 | [-4.40446839, +0.07376474] | [-3.32091870, +0.18198982] | False |

本次两个成本网格的同时band全部跨零，**未建立统一置信意义的实际成本补偿结论**。低价格的正点估计或逐点描述性区间不能替换这一结果。按已冻结网格，wall和CPU的净CE差均在λ=.005时为正、λ=.01时为负；这是点估计符号所在的网格区间，没有计算连续价格的置信break-even。高价格将尾部慢请求赋予很大的指数风险权重，统一max-deviation半径随之变宽；这与仅检验raw质量的主要比较使用不同的推断问题。所有慢请求保留，未为通过门槛删除或缩尾。

这些 λ 是敏感性参数，未声称它们是用户的实际经济价值。wall 与 CPU 的 bands 分别解释，不是合并双价格家族保证，也不能扩展为连续价格区间。请求曲线不包含模型预训练、历史 generator/controller 训练或新增开发的摊销成本，因此不能作为完整生命周期经济收益证书。新增开发成本已在 §1 全部保留。

## 5. 完整进程与阶段成本

Runner entry wall **940.794090262 s**，CPU **897.530601103 s**。

| 阶段 | Wall s | CPU s |
| --- | ---: | ---: |
| analysis | 28.173410061 | 28.171725574 |
| closed_media_readback_and_scoring | 143.470594377 | 143.447887024 |
| source_and_reader_setup | 0.861655520 | 0.861208790 |

Exact-PID child 正常退出码 **0**，完整 wall **942.655170974 s**，child CPU **899.386962000 s**，Linux peak RSS **928,628,736 B**。包含启动/import、请求、离线评分、分析、结果写出及退出；wrapper 自身CPU另列。它与 runner、单请求和阶段计时有包含关系，不能重复相加。

## 6. 验证、身份与可支持范围

7项 synthetic-only 验证覆盖：完整公开特征缓存的精确相等、真实动作改变像素后的失效、紧凑特征一致性、私有 RunState 拒绝、成功概率约束/支配动作、实际生成+持久回读的旧/缓存路径身份、完整 census、source错绑、失败/outlier保留和随机质量/成本的联合CE计算。[VALIDATION.json](VALIDATION.json) 记录实际退出0与源码hash；不声称完整仓库测试。

正式来源开放前，依赖预检发现旧 runner 将 Snapshot 的语义 fingerprint 误作 checkpoint 文件字节 SHA，这会在模型装载时拒绝执行。原 PROTOCOL.json 保留；PROTOCOL-v2.json 分别冻结文件 SHA 与参数/配置语义摘要，并在预检及 resident 装载时检查两者。没有重跑开发选择、改变策略、来源或统计。新增历史 forecast_calibration[448,449) 的真实 smoke 覆盖五模型×四策略共20次生成，并分别检查错误文件 SHA 和错误语义摘要被拒绝；全部通过，未读取新 test。[MODEL_IDENTITY_AMENDMENT.json](MODEL_IDENTITY_AMENDMENT.json) 与 [MODEL_IDENTITY_VALIDATION.json](MODEL_IDENTITY_VALIDATION.json) 保留修订和实际验证。

Control 冻结协议首次发布于 GitHub commit `ad6462e98ba131880d68ba49465afff166af9347`，完整源码/开发/验证发布到 `46102fb5c0504e3a691bd012b11087a4693592df`。模型身份 v2 修订发布于 `78f4ed0d8d35147a0de81b1ff40580590a8e29ab`；共享最终来源等待新的15模型与5个 warm 参考全部冻结并发布于 `a2d9942da8a8a1080bf85522a9995101a11ee19e` 后开放。正式 launch 的实际时序另由 process registration 与 root 总发布记录核对。

本轮只回答所列固定生成器、任务、来源和动作空间中的控制实现与成本问题。紧凑方案失败不证明所有无 CNN 状态不可行；新成功率监督与模型容量同时变化，其作用未被单因素分离。精确缓存没有新增生成器训练，也不改变旧风险训练成功率下降的事实。全模态端到端训练、长时域控制、真正生产接纳和全局 portfolio 最优另需相应证据。

| 文件 | SHA-256 |
| --- | --- |
| [SOURCE_ALLOCATION.json](SOURCE_ALLOCATION.json) | `85ba9a409a31a6ff6c6b4df5f6f06867d14be9442d3434c0c143e0cdb9a4e76d` |
| [DEVELOPMENT.json](DEVELOPMENT.json) | `37a336a0d40a146f26875490b314edf22943cba51d86bd912d352275760516d5` |
| [PROTOCOL.json](PROTOCOL.json) | `b3d5c8e1483b37514fe64176678d26e8c37a3085a5cb0a027eef5186e62551c9` |
| [PROTOCOL-v2.json](PROTOCOL-v2.json) | `35601464db2dce9a31e79dc28443f689e4a91c29b706e3e41a45cd865e52c9ef` |
| [VALIDATION.json](VALIDATION.json) | `b9da6561c75e24ff059157ef85ddc262ed9a48487b50446fa1fe66cfe11535b0` |
| [MODEL_IDENTITY_AMENDMENT.json](MODEL_IDENTITY_AMENDMENT.json) | `d23a0b5c62d93fc72904a9772de85342bfea4487ad9605f50d5a11508c401294` |
| [MODEL_IDENTITY_VALIDATION.json](MODEL_IDENTITY_VALIDATION.json) | `80103e9de141d6ea701a3822f971799bb31511a3c21ff70b1ddab7e6431a2d84` |
| [SUMMARY.json](SUMMARY.json) | `39a495eba8af4183af3dbd17dad52de8e4cb57d605e2d02fe6f36308edb7ea38` |
| [PROCESS_RECEIPT.json](PROCESS_RECEIPT.json) | `5105b26a74acef2d6f023ff02e5d448407d7364eba0fef859b4a5b53d3bda8dc` |

只发布源码、主要详细报告、冻结协议与聚合证据。原始媒体、权重和逐行记录不归档到Git；这是用户指定的交付范围，不是未闭合 blocker。
