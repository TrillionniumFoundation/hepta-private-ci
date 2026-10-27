# 六条工作流：实现、实测结果与未通过项

本轮从 `ab417dfc97aad4fd51e2ae77515936d6ef6464b7` 建立独立研究目录，
完成联合证据、执行合同、多值风险任务、交付后真实 neuron 状态反馈、原始
生成器联合训练，以及自然语音、视频、扫描图文任务的实跑和审计。
**这些工作没有证明全模态 NDU 模型已经取得可重复的最优输出收益；六项目标
不能全部验收。**所有失败、较强对照和适用范围均保留。

## 验收表

| 优先级与目标 | 实质结果 | 当前边界 |
| --- | --- | --- |
| P0 联合证据 | 同事件 receipt 幂等；alias-aware 110 事件联合 likelihood；100 类 joint prior 实际训练；原 V6 和真实 WAV 独立验证 | 单个 fit speaker 的 paired likelihood 跨 speaker 更差；未知 coupling 保持 unknown，不认证转移 |
| P0 未来备份与真实执行 | 顺序 owner ticks、准入/拒绝、剩余资源、联合随机成本、continuation 身份绑定；完整策略终局标签；64 模型/248 策略独立枚举一致 | 原 Oct25/26 native 完整资产未恢复，真实 owner 完整闭环尚未重跑；未来资源/owner law 未识别 |
| P0 风险可识别任务 | 多值收益、严重损失和不同成本实际导致 mean/risk 选择不同，真实交付与评分完成 | 合成有限任务；均值与尾部有真实取舍，不代表自然全模态收益 |
| P0 反馈后的可控制决策 | 原 Hepta sparse kernel 递归状态、两 tick、checkpoint reset、后续修复和外部收益的机制证据 | 同信息 history 完全持平；未接 Agentd owner，未识别 neuron 各子机制的独特优势 |
| P1 联合训练与保留 | 原 V6 encoder、转移、文字/图像 decoder、gate 均实际更新；独立审计 5760 份图文交付 | 收益和 retention 门槛均未通过；不是自然音视频生成器联合训练 |
| P1 自然任务与成本 | 真实朗读语音、真实跟踪视频、真实扫描文档均完成输出/读回/后置评分，包含强固定对照 | 未超过较强固定策略的质量/成本关系；是感知与计算控制，未完成自然全模态生成或复杂图文推理 |

## 1. 联合 prior 与 observation likelihood 分开检验

[证据模块](evidence/README.md)直接表示完整联合 target prior，不把两边 marginal
的外积当作联合模型。重复 receipt 由事件身份去重；发生真实 alias 后只计一次
似然，未来规划在到达前对可能的 alias 事件求和。没有测到的 distinct-event
coupling 不自动填成独立；正 prior 命中 unknown 即拒绝规划。

[原 V6 真实 encoder 试验](evidence/REAL_V6_REPORT.md)使用相同公开信息、近似
匹配参数量和 3 个固定训练 seed。2000 个 train 来源对、500 个不重叠图像
来源对开发 holdout 上，共同遮挡+公开关系任务的 joint NLL 为 `1.0145`，
factorized 为 `2.4582`；两者都解析条件化到公开关系后为 `0.9666 / 1.3579`。
但后者的准确率是 factorized `71.27%`、joint `68.53%`；clean 上原冻结模型
也更好。因此只支持声明任务中的某些联合概率预测改善，不宣布全面输出增益。
MNIST 在此没有 writer 身份，来源图像对不等于独立 writer。

[真实 WAV 试验](evidence/REAL_AUDIO_REPORT.md)使用固定 FSDD 数据。四位 speaker
训练一个新 CNN、一位 speaker 拟合 likelihood、一位 speaker 开发评价。
旧 naive Kronecker 模型对不可能的 same-WAV 异标签结果分配
`1.77%–64.28%` 概率；结构修复后为零，10 个真实重复事件后验幂等。
但在相同身份信息下，distinct-event 的 paired joint likelihood 跨 speaker
NLL 为 `4.0010`，明示独立假设基线为 `3.5694`；posterior NLL 和 ECE 也更差。
5000 pair rows 来自 500 条测试 WAV、一个 speaker，未夸大独立样本数。

审计发现 ECE 在 0.9 附近的浮点分箱差异。原源码/原结果原样保存，后评分
修正统一到 12 位边界舍入，仅 alias 分区的两个 ECE 从 `0.170397` 改为
`0.171004`。未重训，NLL、准确率与研究结论不变。

## 2. 备份针对完整可执行 continuation

[执行合同与校准](control/README.md)绑定 generator、owner、observation、
continuation、calibration、objective 和 cost 身份。候选扫描按实际顺序推进
owner 状态；每个未来分支显式携带资源、成本、拒绝及后续状态。随机成本保留
在指数期望内部，没有用平均成本代换。

复用旧 Bellman，64 个有限模型的 248 个完整确定性策略独立枚举，最大
moment 误差 `2.66e-15`。忽略未来拒绝、把相关随机成本换成均值，都会在
反例中改变根动作。acquire 之后被拒绝的样本，其完整策略成功标签必须为零。
这证明提供模型上的实现一致性；不证明提供的未来 law 已正确拟合真实 owner。

`native_adapter.py` 已提供原 episode 的 opt-in 调用、实际回执导入、扫描顺序、
mask、checkpoint、eligibility 和选择核对；原 owner 源码 SHA 完全一致。
不过原 Oct25/26 权重、完整 qualification、renderer、binary/dependency 与
运行回执包仍缺失。`real_native_episodes=0` 不能被有限枚举或纯 kernel 实验
替代。原 native 动态策略的完整终局校准与资源分支估计继续保持未验收。

## 3. 风险有了可观察的作用

[多值有限任务](risk_feedback/README.md)包含不同语义损害、部分正确收益、
不可撤销的首份交付损害、传输故障和不同动作成本。完成 256 cases × 7 臂、
1792 episodes，产生并读回 11248 个实际 text/PNG/WAV/AVI 文件。
声音是 tone、视频是移动标记，codec 没有接受神经训练。

mean 按四个 cue 选 `[0,1,2,3]`，risk 选 `[3,3,2,3]`。风险策略 CE 为
`0.1832`，均值策略 `-4.3358`，但平均净收益为 `0.2981 / 0.4480`，风险策略
牺牲了均值。该分布上严重损失从 `7/256` 到 `0/256`，不是所有分布上的保证。
保留原二值等成本任务的 mean/risk 等价负对照。

## 4. 真正 Hepta neuron 数值状态中介

[原 sparse kernel 实验](control/neuron_feedback_probe/README.md)从本仓库精确
复制三个 crate 的 83 个源文件离线编译；依赖身份与原 Cargo.lock 一致。
固定 kernel 和 codec，只训练一个 21 系数的状态读出头。

执行链是：真实交付并读回 → 公开一致性反馈 → 原 `sparse_tick` → checkpoint
→ 第二次零新 drive 的原 `sparse_tick` → activation/eligibility → 后续动作
→ 实际最终输出 → 私有评分。第二次 tick 与读出头都不再接收 scalar 或 target。

新 256 cases × 5 臂。numeric 平均净收益 `0.30203125`，zero/reset 为
`0.22515625`；两个预定主比较差 `+0.076875`，配对 97.5% 区间
`[0.0684375, 0.0846152]`。清掉中间 checkpoint 改变 164 个后续动作。
包含训练共 2752 个原 native ticks、9040 个真实媒体文件；独立审计重放
全部 2560 个评测 ticks、重读 8272 个评测媒体、重算 1280 个终局收益。

同信息 history 在 256 个 case 上与 numeric 动作和收益完全一致。reset 删除
整个 checkpoint，未单独识别 eligibility/homeostasis/inhibition 的优势。
所有原 receipt 保持 `DENY_ALL` 与 `requires_calibration=true`；没有因此
取得 owner 准入或生产执行权限，`native_owner_integration=false`。

## 5. 原模型联合训练真实发生，收益门槛失败

[联合生成训练](joint/README.md)恢复了原 full002 精确权重和数据划分，每个
原 seed 分别做 frozen、joint_mean、joint_entropic；更新臂同信息、同训练
计算预算，所有臂同推理逻辑预算。encoder、共享转移、文字/图像 decoder
及 gate 的参数均真实变化，6 个新 checkpoint 均通过保存/重载检查。

独立审计的 test CE 差：NDU − frozen `-0.0074714`，配对 97.5% 区间
`[-0.0306185, 0.0148835]`；NDU − mean `-0.0010231`，区间
`[-0.0037350, 0.0005958]`。retention 相对 frozen 的下界 `-0.0520`，
没有通过预定 `-0.01` 保留界限。5760 份真实交付全部重评分，误差为零。

训练采用明示的可微代理、量化 straight-through 与 soft plan；部署为离散
文字/argmax plan，训练与报告的 CE 聚合顺序也不同。这些限制不能用
“参数更新了”或代理 loss 下降来掩盖。P1 可重复实际收益仍未成立。

## 6. 自然任务没有超过强固定策略的效率

| 真实任务 | 较强固定对照 | 动态结果 | 结论 |
| --- | --- | --- | --- |
| [自然语音](natural/README.md)，8 个 test speaker / 24 段 | beam-5 WER `4.4944%`，24 次调用，13.703 s | 同 WER，32 次调用，15.820 s | 改善 greedy，但比 beam-5 更贵 |
| [真实视频](natural/README.md)，2 个 test 来源 / 各 160 帧 | local IoU `0.85075 / 0.84124` | 动态等于 local；global 轨迹也相同 | 额外全局搜索无质量增益；帧不当独立来源 |
| [扫描图文](natural/document/README.md)，12 个 test 商家字符串 | base 字段 EM `22/48`，11.117 s | 同 EM、同 base 策略，10.910 s；enhanced 同 EM、23.932 s | 时间小差不作速度提升；增强计算无总体字段收益 |

自然语音只拟合继续计算阈值，视频为模板跟踪，图文为 OCR+规则抽取。
扫描图与标注真实配对；不同任务之间没有伪造音视频同步配对。三个任务都
没有进行自然语音/视频神经生成器联合训练，也未证明一般复杂图文推理。
计时为一次共享主机实测，非跨环境性能保证。

## 证据与复现

各目录 README 给出独立运行入口；`VALIDATION.json` 汇总验证，
`EVIDENCE_INDEX.json` 列明原始包身份。原始参数、实际文件、逐步状态、失败与
修正前结果均保留。较大的四份完整包作为本轮交付附件提供；附件访问不改变
仓库权限。原模型恢复入口为 `python -m ...repair_20261026.restore`。

后续优先需要：恢复原 native 完整资产并重新收集实际完整策略回执；用更多
独立 speaker 估计/验证 observation coupling；让部署分布、可微训练代理与
评价 NDU 的目标关系更明确；在真实对齐的自然多模态生成任务上取得强对照
之外的增益。当前证据不支持宣布全局 portfolio 最优、全模态模型完成或
将本研究分支自动提升为生产模型。
