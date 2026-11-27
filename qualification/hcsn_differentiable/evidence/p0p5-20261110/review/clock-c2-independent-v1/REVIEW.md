# 独立审查：续训时钟与 C2 结构边界

本记录审查三个相互独立的工件。**未来 producer 的单次时钟修复没有发现作用域问题；C1 历史双采样适配器没有发现新的静态阻断；未部署的 C2 v1 结构守卫有三项已复现的加严需求。** 本审查未执行原生训练、checkpoint forward、反向传播或 optimizer step，也不授予训练充分性、数值资格、科学收益或整体 CI 信用。

## 1. 未来 producer 修复

审查提交 `7d7fa1dff8ea8259b1bae0a9e1889183325693bf`，仅有 `continuation.py` 和 `test_continuation.py` 两个文件变动。

新代码在 epoch 的 development evaluation 完成后取一次 `elapsed()`，用同一值设置 `phase_process_wall_seconds`，并加父任务完整 outer wall 得到 `cumulative_process_wall_seconds`。该 row 直接进入 report 与 journal，因此两者共享同一次观测。修改未触及参数更新、best 选择、plateau、父预算扣减或历史 capsule。

新增回归使用每次递增 1ms 的假时钟，检查每个 epoch 严格满足 `cumulative == parent_outer + phase`，并核对 journal 的 phase 值。独立读取了 owner 保存的原源 red、修复源 green 和格式化回执，并核对其字节身份；原源的目标测试失败、修复后 12 项通过是这些回执报告的结果，本审查没有重复执行它们。修复只适用于采用该新源码的未来执行，不能据此替换历史 C1 的 source SHA。

## 2. 历史 C1 双采样补充审查程序

静态审查冻结的 `baseline36-c1-independent-reviewer-program-v2.zip`。历史 source 的 epoch 字典先计算 early phase，随后计算 `parent_outer + elapsed()`；适配器通过 AST 和被绑定的完整源码核对这一顺序。

每条原记录必须满足有限数值和严格区间：

`0 <= raw_phase_early <= raw_cumulative - complete_parent_outer <= complete_child_outer`。

适配器保留原 report、events 和两次采样区间，只在深拷贝中将供既有逻辑 helper 使用的 phase 值设为较晚采样。既有 helper 的容差未扩大；质量截点、首次越过预声明 0.30 阈值和费用轴均使用未改动的原始较晚 cumulative。负差、超过 outer 终点和非有限值均有拒绝用例。

程序会重新绑定 v1 全部 source/input SHA、36 个已通过的 baseline 子记录和六个原 fresh-forward 文件；v1 整体失败及其完整 22.93758828798309 秒 wall / 21.723336 秒 waited child CPU 保留。新程序仅对七条 C1 链进行实际 checkpoint 审查；本记录只确认代码方法和 owner 的 preparation 回执，不宣称该原生执行已完成。

费用表从每个 core 的全部六个原候选 outer 加所有相应 C1 outer 计费，不以审查是否通过为筛选条件。七条 C1 任一失败时，完整 core 比较表不输出。共同 LR 由同一 D 数据的三个预声明 seed 均值选择；保留两种 LR 的全部候选，不把最好 seed 当预期结果，也不把 D 选择结果当独立确认。HCSN 终态不在此次 subset 审查范围。原阶段终态 CPU 未被追造为精确 per-fit exit rusage。

## 3. C2 v1 已复现的结构缺口

被审源码 SHA 为 `9b6bd43ebde5317d62c55fbc37b5fb2309f89178d195c529598529caf1e99f4f`。它正确地保持 `execution_authorized: false`，并要求另行绑定 source/data/runtime/checkpoint 原字节；它不是 C2 runner。原 owner 的 18 项测试、首次失败和修复回执均保留。

| ID | 独立制造的反例 | v1 结果 | 需要的修订 |
|---|---|---|---|
| C2-01 | min30、patience10；epoch1–39 的 F1=.5，epoch40=.6。按既定规则 epoch30 已应停止，但最终 stale=0。 | terminal guard 接受最后状态。 | 逐前缀保存首次 plateau epoch；只要曾达到停止条件就拒绝新增训练。|
| C2-02 | 单 epoch 的完整 batch journal，首个累计 wall/CPU 都为 -.5。 | 初始下界是 -1，负值通过单调性检查。 | 两种累计时钟均须有限且非负，再检查不减。|
| C2-03 | 未执行任何 step 的合成 Linear 状态，所有 AdamW `exp_avg_sq=-1`，其他字段结构有效。 | checkpoint guard 接受。 | 除 shape/dtype/finite/step 外，验证二阶矩非负；若未来支持复数，分别验证实/虚通道。|

C2-01 只调用 terminal guard，边界状态由测试制造，不冒充通过全套 native checkpoint 验证；C2-02 只调用 journal guard；C2-03 仅构造和加载张量，不调用 forward/backward/step。这三项不是实际原生训练损坏或既有结果无效的证据。源码保持冻结，后续应在独立 v2 中修复并保留 v1 原件。

该次反例执行的完整 waited 子进程 wall 为 **3.3642368869986967 秒**，waited child CPU 为 **2.976492 秒**；源前后 hash 相同。它是独立审查开销，不是训练成本，不与 owner 的 18-test 成本或 C1 原审查成本相加冒称一次执行。

## 边界与后续

C2 是否准入仍需原六个候选全部终态、实际 dispatch wall ceiling、完整父 outer 扣减、所有候选/拒绝/失败费用、latest complete last 与 prefix strict-best 一致性，以及 source/data/runtime 的独立字节绑定。原 4 小时名义上限及各实际较小 ceiling、300/900/1800 秒截点保留；12 小时/200 epoch 只是另列的自适应后续阶段提案。

所有原始归档和 canonical 源码在本审查中只读。结果的 `scientific_admission` 保持 `HOLD`；C1 的实际补充审查和 C2 未来修订需各自独立回执。
