# 参数场 × Hepta neuron：V3 完整执行、独立核验与停止结论

**V3 已完成注册范围内的执行与独立核验，并按原定失败门槛停止。H12 没有在完整训练开发路径上超过强普通训练；冻结模型上的 Hepta 没有通过双 observer 的运行增益门槛。最终十一臂确认没有启动。** 这些是两道资格门槛的结果，不是又一次完整主测试的“0/6”。V2 已执行的十一臂、0/6 联合验收及其保留能力限制保持原样。

本轮完成 21 个注册任务；其余 42 个任务按资格失败规则跳过。实际实验没有重试，冻结科学代码、样本量、表示族和门槛均保持不变。独立复核覆盖完整训练终点、实际 PNG/UTF-8、反馈、原生状态、拟合选择、统计和成本。执行正确与科学假设成立分别记账。[终态处置](evidence/STUDY_DISPOSITION.json)、[独立结果评审](../field_bridge_v3_20261027_review/V3_RESULTS_REVIEW.md)、[成本账](evidence/V3_EXECUTION_LEDGER.json)。

## 1. 这一步具体推进了什么

V2 的主要未解问题是短期局部预测没有转化成终点增量、运行控制没有显示稳定的历史参照优势，以及训练保留能力的联合验收不完整。V3 实际落实了以下修改：[冻结协议](PROTOCOL.json)、[训练设计](../field_bridge_v3_20261027_review/TRAINING_DESIGN_PROPOSAL.md)。

| 方面 | V3 实际方案 | 检查目的 |
| --- | --- | --- |
| 学习目标 | 候选 48 步后继续到第 288 步的 Qref，随后做完整闭环 rollout | 检验短期目标与训练终点不一致的问题 |
| 学习状态 | 前瞻固定 H12，包含梯度／动量方向测量；保留 H7、generic12、richer30 | 检验新增方向信息的增量 |
| 普通训练 | 全部四种固定倍率、每个模型四条完整日程；按开发规则选择 | 提供有实际学习能力的常规参照 |
| 保留措施 | rehearsal、teacher anchor、训练专用 clean guard、完整优化器回滚 | 检验守住训练面板后是否还能获得新面板收益 |
| 连续运行控制 | 初始共同输出后最多三次决策，真实交付反馈后继续选动作 | 执行真正的多轮因果控制 |
| 历史参照 | 完整公开历史＋固定 Fourier 特征，与 native 同为 88 维输入、1,335 个拟合系数、12 个候选 | 限定相同信息与相同读出预算下的比较 |
| 状态诊断 | current-only 与重新独立拟合的 reset-native | 避免仅用训练后强制重置造成的读出失配解释结果 |
| 数据边界 | 23 个互斥角色，排除全部登记的 V2 像素身份 | 分离拟合、开发、资格审计与最终确认 |

训练资格仍使用历史固定单动作输出任务；运行与原定最终确认使用新的模拟反馈任务。两种目标的转移必须实际检验，不能默认成立。这里的模型是三个固定历史 MNIST 多模态模型；本轮没有执行新的 LLM 主干训练或生产部署。[协议评审](../field_bridge_v3_20261027_review/PROTOCOL_REVIEW.md)。

## 2. 学习侧：完整路径的开发门槛失败

三种模型各完成 8 种方法 × 4 条日程，共 **96 条 288 步完整路径**。普通方法的已选倍率分别为 seed 17 的 1、seed 29 和 43 的 2；已选自适应参照为 richer30。所有比较使用匹配的源图像、条件和完整日程。[开发选择](evidence/DEVELOPMENT_SELECTION.json)、[完整终点数组](evidence/development/ARRAY_EXPORTS.json)。

| 开发阶段比较 | Reward observer 平均差 | Audit observer 平均差 | 注册条件 |
| --- | ---: | ---: | --- |
| 普通训练 − 冻结模型 | +0.02481205 | +0.02371545 | pooled ≥0.005、每个模型非负：通过 |
| H12 − 普通训练 | **−0.00981172** | **−0.00764090** | pooled 严格大于 0：失败 |
| H12 − 已选 richer30 | +0.00295071 | +0.00241157 | pooled ≥0：通过 |

这里的差值是注册净效用单位，不是准确率百分点。六项开发条件中五项通过；H12−ordinary 在三个固定模型的点差都为负。所有普通候选和表示候选仍保留，没有换用 CV 表现最好的 H7 或扩大 ridge 搜索。[完整检查项和逐模型数值](evidence/DEVELOPMENT_SELECTION.json)。

这些数字来自用于选择 ordinary/richer 的开发面板，包含选择作用，不能称为无偏的独立确认效果，也没有据此作显著性或一般劣效结论。开发条件失败后，独立学习 audit、最终训练以及 ordinary/field 检查点上的 runtime 阶段均未开启；普通训练的新联合确认也因此没有运行。[学习资格处置](evidence/TRAINING_QUALIFICATION.json)。

独立终点审计核查 498 个文件、96 条路径、253,440 个硬输出；另一份独立 verifier 从实际像素、UTF-8、重建目标和原有有序批次重新计算两套 observer，共 **506,880 个评分，误差全部为 0**。两份审计按 COMPLETE、ENDPOINTS、协议、freeze 和源身份精确连接；开发选择重建误差也为 0。[终点审计](evidence/INDEPENDENT_DEVELOPMENT_ENDPOINT_AUDIT.json)、[实际评分重算](evidence/INDEPENDENT_TRAINING_HARD_SCORE_AUDIT-development.json)、[审计连接](evidence/DEVELOPMENT_AUDIT_JOIN.json)。

### Qref 拟合诊断不替代完整路径收益

每个模型的 24 个拟合状态来自四条完整探索轨迹。全部 180 次拟合求解已由增广最小二乘独立重建；全部 12 个控制器选择 ridge=1。H7 的 CV MSE 在三个模型上均低于 H12，但 treatment 仍按预注册固定为 H12。[完整 CV 网格](../field_bridge_v3_20261027_review/TRAINING_FIT_REVIEW.md)。

完整 bank 包含 72 个分支起始状态、288 条 Qref 终点续训分支和 184,320 个硬输出记录。单次预注册回放复现 seed 17、轨迹 0、起点 0 的四条完整 288 步分支和已选 48 步前缀；参数、完整优化器、guard 事务、硬输出和效用均精确一致。回放单独计费，没有增加样本或重新选择策略。[bank 证据](evidence/training_bank/17/BANK.json)、[唯一预注册回放](evidence/prespecified-bank-replay/REPLAY.json)。

## 3. 运行侧：收益门槛失败，局部 clean 非劣通过

冻结模型路线按独立注册规则继续，完成 **512 个源对 × 4 条件 × 3 固定模型 × 5 策略 = 30,720 个 episode**。五种策略为固定计划、current、完整历史、native、reset-native。固定参照在拟合／选择阶段的全部 85 个开环终止计划中选择；实际审计只执行每个策略选中的动作，没有执行未选续步。[运行拟合与选择](evidence/runtime_fit/READOUT_ARCHIVES.json)、[运行审计完整清单](evidence/runtime_audit/17-frozen/COMPLETE.json)。

预注册统计使用 4,000 次配对源对 bootstrap、四比较族校正和每个 observer 的 **98.75% 双侧区间**。模型种子与条件等权固定；clean 比较复用同一源对抽样，只选 clean 条件。两个 observer 是同时满足的条件。[独立统计](evidence/INDEPENDENT_RUNTIME_RESULTS-frozen.json)。

| 比较 | Reward 平均差 [98.75% 区间] | Audit 平均差 [98.75% 区间] | 双 observer 结果 |
| --- | --- | --- | --- |
| Native − Fixed | +0.006895 [+.003254, +.010619] | +0.000840 [−.002660, +.004219] | 增益未通过 |
| Native − History | +0.000955 [−.002194, +.004082] | +0.000198 [−.002881, +.003234] | 增益未通过 |
| Native − Fixed，clean | +0.007569 [+.001457, +.013518] | +0.001938 [−.003441, +.007322] | −0.01 非劣通过 |
| History − Fixed，clean | +0.004821 [−.000745, +.010501] | −0.004033 [−.009570, +.001316] | −0.01 非劣通过 |

**两项增益比较为 0/2 通过，两项本任务 clean 非劣比较为 2/2 通过。** Native−Fixed 的 reward 差为正、区间下界为正且三个模型同向；audit 区间跨零，seed 29 为负。Native−History 的两套区间均跨零，模型符号混合。没有建立 native 的双 observer 优越性，也没有证明等效或普遍无效。[运行资格处置](evidence/RUNTIME_QUALIFICATION-frozen.json)。

以上 clean 检查是同一 runtime audit 面板的 clean 条件，不是最终独立 retention 结果。区间与结论只针对固定三个历史模型、所登记的源对总体和动作／读出族；不主张跨整个模型总体或两个完整 observer 族的同时覆盖。

## 4. 连续状态已经执行；增量效用仍需单独成立

全部拟合／选择树共 2,304 棵、195,840 个实际终点奖励、48,384 个公开事件和 46,080 份反馈，都从实际 H3M 内的 PNG、UTF-8、保留公开 logits 及公开 mask 独立重算。另行精确重建 96 份特征矩阵、432 个自身后续策略目标和预测器，以及 2,322,432 个训练／选择节点动作；误差为 0。[媒体标签真值](evidence/INDEPENDENT_RUNTIME_BANK_MEDIA-frozen.json)、[完整拟合核验](evidence/INDEPENDENT_RUNTIME_FIT_AUDIT-frozen.json)。

实际选中路径包含 80,870 次逻辑输出、70,398 个公开事件／决策、39,678 份反馈和 61,440 份双 observer 终点评分。独立核验复算全部固定选择及 26,849 次 current/history 动作，并与 12,288 个 native/reset 会话、54,330 次原始内核回放精确连接。[媒体和因果时序审计](evidence/INDEPENDENT_RUNTIME_MEDIA-frozen.json)、[原始内核回放](evidence/NATIVE_SESSION_AUDIT-frozen.json)。

其中 14,877 次 native/reset 后续决策使用已经交付输出对应的反馈，recurrent native 臂占 7,361 次。V3 因而补上了 V2 仅有一次自适应延续的执行范围限制；它仍是最多三次决策的模拟反馈任务。实际递归、状态敏感性或精确回放不能替代 native−history 的收益门槛。保留 logits 与其媒体字节绑定，公开 softmax 被重算；审计没有重新运行生成器以认证 decoder logits 的来源，生成过程由冻结源、模型身份和执行记录约束。

## 5. 数据与停止边界

最终源清单使用 26,000 张新的官方 train 图像与 2,048 张新的官方 test 图像，共 28,048 张，分为 23 个角色；排除全部已登记的 29,000 张 V2 图像身份。独立核验全部 253 个角色交集及先前身份交集，均无重叠。[分配清单](SOURCE_ALLOCATION.json)、[最终源审计](../field_bridge_v3_20261027_review/FINAL_SOURCE_ROLE_AUDIT.json)。

本轮两个资格路径都失败，所以原定最终十一臂、六项主要对比和十项最终保留非劣比较全部未启动。没有冻结模型 fallback 资格。学习 audit 的六个角色及 primary/retention 两个角色，共 **12,496 张**，没有进入模型任务；其中最终 primary/retention 合计 **6,144 张**。这不表示原始 corpus 字节从未被读取：分配阶段已读取像素哈希，并仅为冲突重复排除使用原始标签。[最终资格决定](evidence/CONFIRMATION_QUALIFICATION.json)、[角色使用与跳过任务](evidence/STUDY_DISPOSITION.json)。

V2 的同面板 H7 轨迹审计限制仍留在原 ledger；V3 的新数据边界不能追溯改写它。新像素身份也不等于新书写者、未知预训练独立性或真实用户总体。

## 6. 实际工作量与独立验证开销

成本账绑定 **1,181 个文件、63 个注册任务和 18 份实际验证回执**，终态为 21 完成、42 因资格失败跳过，未出现成本未知的实际失败尝试。各阶段只汇总顶层资源；重复的父子 COMPLETE、报告副本和逻辑缓存覆盖不重复收费。[完整机器账本](evidence/V3_EXECUTION_LEDGER.json)、[独立账本说明](../field_bridge_v3_20261027_review/EXECUTION_LEDGER.md)。

| 工作 | 实际研究计算 | 额外独立验证 |
| --- | ---: | ---: |
| 梯度微步 | 82,944 | 1,200 |
| 梯度样本 | 7,962,624 | 115,200 |
| 方向梯度测量 | 648 | 1 |
| 训练 head 求解／重建 | 180 | 180 |
| 运行 head 拟合／重建 | 432 | 432 |
| Native tick | 828,474 | 828,474 |
| Observer 数字样本 | 4,315,644 | 773,416 |

研究梯度微步包括 reference 的 3,456、完整 Qref bank 的 51,840、development 的 27,648；零倍率和被 guard 回滚的实际计算也计入，其中 23,040 个微步被 guard 回滚。teacher、特征逆向、guard、observer、序列化等独立计数保留在完整账本，不把微步数冒充 FLOPs。普通固定策略本身可以省去共同实验仪器，所以共同测量成本也不能冒充 ordinary 的最小实现成本。

独立开发评分实际调用每个 observer 1,520 个批次、194,560 个数字样本；逻辑覆盖是每个 observer 506,880 个数字样本，缓存命中单列。bank 媒体验证另有 258,048 次 reward digit forward，选中媒体验证另有 64,682 次 reward 和 42,110 次 audit digit forward。各项 observer 成本按其原有单位记录，不能把逐数字调用与批调用直接相加。合成测试、环境安装、构建和归档验证在研究计算账本之外另有回执。

各 worker 的 wall 时间会因并发而重叠，只报告累计已记录工作时长；没有通过相加伪造实际总 elapsed。0.002 的动作价格是逻辑净效用费用，不是毫秒、能耗或货币。

## 7. 与论文的关系和 comments

完整的理论对应与评论见 [PAPER_HEPTA_COMMENTS.md](PAPER_HEPTA_COMMENTS.md)。核心判断有四项：

1. 论文提供了完整优化器状态、未来价值、信息与执行器预算的分析框架；V3 的经验 H12 与 Hepta 运行状态处于两个不同控制层。
2. Qref 是冻结 reference 的终点续训值，部署策略会重新选动作；拟合准确不能替代完整闭环收益。本轮 H7 的拟合优势和 H12 的开发失败使这种区分更加具体。
3. Hepta 的状态来自同一公开历史。若其受限读出族有额外价值，需要实际击败同信息历史参照；本轮尚未建立这一点。
4. 两层各有增量也不自动证明超加性协同；本轮连继续到最终组合确认的资格都未获得。不能把执行完整性扩写成参数场充分性、Riccati/HJB/FBSDE 识别、LLM 规模或生产能力证明。

原始内核始终保持 **DENY_ALL、requires_calibration=true、native_owner_integration=false**。研究 readout 校准没有清除生产校准或 owner 契约要求。[原生构建](evidence/NATIVE_BUILD_RECEIPT.json)。

## 8. Blocker 的真实状态

原 B01–B10 的闭合标准逐字保留，并单独追加 V3 证据；没有把失败门槛重新定义为成功。[逐项 ledger](../field_bridge_v3_20261027_review/BLOCKERS.json)。

| 范围 | 本轮状态 | 解释 |
| --- | --- | --- |
| 完整续训、回滚、拟合与实际输出可复核 | 已闭合到注册执行范围 | 完整记录、唯一预注册重放和独立评分均通过 |
| 三轮运行状态与已交付反馈的因果执行 | 已闭合到注册执行范围 | 原始内核、历史、动作和实际媒体精确连接 |
| B03 普通学习联合确认 | 仍未确立 | 新开发收益通过；新的独立学习／最终确认未启动，V2 的 retention 限制保留 |
| B04 参数场训练增量 | 仍未确立 | H12−ordinary 开发门槛失败 |
| B05/B06 运行收益与 Hepta 超过历史 | 仍未确立 | 两项 runtime 增益未通过双 observer 条件 |
| B07 独立保留能力 | 部分证据 | 本任务两项 clean NI 通过；最终独立 retention 未执行 |
| B09 源身份／访问 | V3 已执行阶段核验通过，原 V2 限制保留 | 不外推为全局数据秘密性或跨书写者独立性 |
| B10 完整持久证据 | 归档与恢复回执单独记录；上传权限未闭合 | 自动审批要求对 V2 具体归档和报告、以及 Library 目标明确授权 |
| 理论、LLM 与生产范围 | 尚未建立 | 属于主张边界，不被小任务的工程通过替代 |

代码、冻结协议、完整拟合候选、开发终点数组、独立审计与停止决定均已进入研究分支。原始媒体、全部检查点及逐步证据的归档使用逐成员哈希清单；归档身份和从归档恢复的复算回执独立于归档保存，以避免自指哈希。[恢复说明](../field_bridge_v3_20261027_review/RESTORE_V3.txt)、[归档校验与恢复复算](evidence/ARCHIVE_AND_RESTORE_VERIFICATION.json)。

**不能将全部 substantive blocker 标为 closed。** 科学门槛失败作为完整结果保留；V2 的归档上传也曾被自动审批两次拒绝，要求明确文件和保存目标。没有通过改用其他外部目标来绕过这一拦截。V3 的新归档将提供同样可审查的文件身份，等待具体保存授权；仓库内代码和结果的提交不等于原始归档已长期保存。[原始授权 blocker](../field_bridge_v2_20261027/evidence/PERSISTENCE_AUTHORIZATION_BLOCKER.json)。
