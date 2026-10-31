# V4：参数场训练原点校准资格实验

**完整执行与独立审计完成；参数场候选资格失败。** 单次前瞻资格检查通过 4/6 项：普通训练增益，以及 ordinary、origin_field、origin_richer 的三项 clean 非劣效。参数场相对普通训练及 richer 参照的两项增量均未通过。遵守已登记的失败策略，未开放 final 或新的 runtime holdout。

本研究编号为 `hepta.field-bridge.v4.panel-origin-qualification.20261027.1`。它延续最初六类实验问题，但不是又一轮完整六臂最终试验，也不覆盖原 B03–B07 的最终联合验收条件。

## 阅读入口

- [完整六项结果](RESULTS.md)：两观察者的点估计、校正区间与判断。
- [论文与 Hepta comments](PAPER_HEPTA_COMMENTS.md)：参数学习、运行控制、轻量参照和理论主张的关系。
- [原始资格结果](evidence/QUALIFICATION.json)、[终态处置](evidence/STUDY_DISPOSITION.json)、[完整执行账本](evidence/V4_EXECUTION_LEDGER.json)。
- [原条件保留的 blocker 账本](../field_bridge_v4_20261027_review/BLOCKERS.json)。
- [108 路训练独立审计](evidence/INDEPENDENT_V4_TRAINING_AUDIT.json)、[逐媒体硬评分核验](evidence/INDEPENDENT_V4_ENDPOINT_HARD_SCORE_AUDIT.json)。
- [实际训练机制](evidence/mechanism/MECHANISM.md)、[详细机制证据](evidence/mechanism/MECHANISM.json)。
- [归档与恢复说明](../field_bridge_v4_20261027_review/ARCHIVE_RESTORE_GUIDE.md)。最终归档 SHA、全部成员校验、literal restore 和原统计精确复算由事后外部 [归档验证回执](evidence/ARCHIVE_AND_RESTORE_VERIFICATION.json) 绑定；该回执有意不嵌入其验证的同一个包。

## 为什么增加这一轮

V3 在完整训练路径上没有建立 H12 相对强 ordinary 的增量。对已公开旧数据的诊断发现：冻结训练 readout 的若干损失/效用坐标随新来源面板发生原点偏移。V4 只增加预登记的 14 坐标初始平移，复用既有初次 probe/guard 测量；冻结旧 heads、normalizers、ridge、训练动作、288 步预算、48 步事务块、raw guard、完整 SGD 回滚和部署动作。没有新增 head 拟合或终点调参。

`mapped[I] = raw[I] - (observed_initial[I] - frozen_fit_initial[I])`，其余 16 个原始坐标不变。I 固定为 `[0,1,2,3,12,13,14,15,24,25,26,27,28,29]`。校准上下文在首次更新前固定，回滚后不重新定原点。所有 adaptive 参照获得相同的初始信息。

## 前瞻冻结与完整运行

| 阶段 | 实际边界 |
|---|---|
| 协议、策略与源码 | [d40343f](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/d40343fc8c08828461463664cba9a594422ccd9f)，任何 V4 新模型调用之前发布 |
| 外部训练冻结 | [28cb77a](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/28cb77a30f713e4efde91edf550b9bbe15fffcd4)，58 个源码/证据身份、25 个固定旧输入 |
| 训练后开放屏障 | 全部 108 路完成并通过独立审计，seal 与 endpoint freeze 在 [46b21d7](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/46b21d7e5af9a485c27a232e3ef1a4b9237b18d7) 发布，随后才开始端点执行 |
| 资格算术绑定 | endpoint 与独立媒体核验之后、唯一统计调用之前在本地固定；不声称这个含终点身份的后续文件早于终点公开 |
| 决策 | `QUALIFICATION_FAILED`；没有重试、重选方法、增加样本或开放新的 runtime/final |

固定模型 17/29/43，每个模型四条新更新日程 14000–14003，九种方法：ordinary_0/1/2/3、raw_field、origin_field、origin_generic、origin_richer、origin_h7。总计 108 条完整路径，各 288 步。强 ordinary 的倍率索引在终点前固定为 17→2、29→3、43→3；这些索引是训练倍率，不能与部署动作混淆。

本轮 6,352 张来源图像全部来自此前未分配的官方 train，排除 V2 的 29,000 和 V3 的全部 28,048 个像素身份，包含 V3 未开放角色中的 12,496 张。六个新角色分别为 gradient 2,000、rehearsal 512、probe 256、guard 512、task 1,024、clean 2,048。没有根据类别或结果挑选配对；不声称新作者或未知预训练数据独立。

固定 4,000 次层次配对 bootstrap，种子 271042，六项比较下每观察者双侧区间覆盖率 99.1666667%。三个增益还要求每个固定模型均值严格为正；两个观察者须同时满足各自条件。四条日程是模型内训练变化，不是四个独立模型。三项 clean NI 的界限为 -0.01，不附加增益的逐模型正号要求。完整规则见 [PROTOCOL.json](PROTOCOL.json)。

## 验证与费用

独立训练审计检查全部 108 路、360 次 head 预测和 111 次安全 checkpoint 加载，确认实际选择、初始校准、guard、零动作、完整优化器回滚、来源访问及费用。媒体核验从 222 个输出文件重建所有 340,992 个输出的两观察者效用，681,984 个数值精确相等，最大差值 0。验证缓存仅复用相同完整有序图像批次，所有目标、文本和代价仍重算；不能把缓存逻辑工作计作新的独立样本。

研究训练执行 31,104 个梯度微步、2,985,984 个梯度样本，另有 648 次方向测量；被拒绝和零动作计算均计费。训练 reward observer 工作为 1,660,416 个 digit examples；训练中 audit observer 和资格端点访问均为零。端点的两观察者合计为 1,363,968 个 digit examples。独立媒体核验额外实际执行 724,992 个 observer digit examples。没有新控制器拟合或 native tick。

逐阶段 CPU/wall、来源绑定、全部原始输出身份和验证费用见账本。并行进程 wall time 不相加解释为延迟；112 字节仅是每路径 14 个 float64 的活跃校准数组，不是整个状态、head、日志或进程内存。临时公共 Torch 环境在全部神经计算结束后按完整 SHA 清单校验回收；模型、数据、原始输出和恢复配方保留。

## 当前边界

普通训练在本轮新资格范围内的收益及 clean NI 有正证据；参数场增量、Hepta 超越相同信息历史的增量、两层联合最终收益、原独立 final retention、LLM 规模结论仍未建立。此前的科学失败和未开放角色均保留。

完整原始归档的持久保存仍受自动审批拦截：需要用户明确点名 V2/V3/V4 归档及各自验证文件，并指定 ChatGPT Library。Git 中的源码与结果不替代完整原始归档持久保存；没有改走其他原始数据出口。见 [审批回执](../field_bridge_v4_20261027_review/PERSISTENCE_APPROVAL_STATUS.json)。

`authority=DENY_ALL`，`requires_calibration=true`，`native_owner_integration=false`。PR 保持 draft；这不等于生产接入、理论证明或整仓 CI 通过。
