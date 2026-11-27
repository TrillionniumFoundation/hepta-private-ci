# 冻结生成器条件残差与 STOP：本轮实际结果

**日期：2026-11-09。科学状态：HOLD。** 本轮完成源码、真实采集、冻结模型预测诊断及证据回读；没有完成策略净收益或架构优势的确认实验。有效诊断来自 HeptaRuntime 原生 CPU 回退；Colab/Kaggle 的原始尝试均单独保留。

## 1. 已完成的范围

实现以 M6 `885dae0f3285267e9e9c49d8b43b0d009779f9e8` 为基线，最终科学源码 head 为 `6f6d76b78349448015655de7fbba9ac89c0b94fb`。当前研究控制器使用既有 40 维公共状态与动作，按来源组等权抽取联合状态、质量及 log-duration 残差；比较真实 `STOP` 与一个合法动作后实际 `STOP` 的终止宏。它返回执行要求，尚未接入生产 actor 的策略执行循环。

- 冻结源码包 81 个文件，包 SHA-256 `73bd281f8728191aab9865f700455f3f65bc324a03c3e1cedf5ff1aeec986ae4`；发布回读和实际运行前后均匹配。
- 新增范围的 44 项本地测试全部通过，零跳过；原始 8,447-byte 日志已恢复并核对断连前 SHA，见 [原始日志](local/all-source-tests.log)。`just fmt` 成功且源码未改变。
- 60/60 个实际 episode 完成，生成 120 条原生 V2 记录。真实宏提取为 calibration 54、diagnostic 54；所有 54 个诊断观测宏获得经验支持。
- 生成器与辅助预测头均未在本轮训练；独立训练重复为 0；正式 confirmation 未访问。

## 2. 数据资格

旧 pilot 的 741 条 transition 与生成器拟合使用同一批 40 个来源，不能重标为独立校准；更早 200 条 bootstrap 记录还属于另一份行为权重。本轮从该 pilot 已登记 fit40/tuning8 之外的 49 个 train 来源中，按事先规定的 SHA 排序选 12 个，前 6 校准、后 6 诊断，每个来源覆盖五种预定 family。这个分离只针对已核验的历史范围，不证明全项目或基础模型从未接触这些材料。

两个原始 JSONL 各 60 行，按校准整块、诊断整块的顺序无损拼接为 6,333,026 bytes。拼接 SHA 为 `5db098eef1d5bd935d5d58919cd5295e06c317cee3cebfd5363367825da0fd13`。原行、V2 链和 action-only 耗时语义均未改写。

在新采集前锁定的参数为：ordinary core、reset memory、seed 19、6 个邻近来源组、8 粒子、风险参数 `[0, 0.25, 1, 4]`、40 维单位尺度、距离阈值 2、延迟权重 0.01、每秒折扣 1、实用 margin 0.02。注册 SHA 为 `561f29a64c47995e45d5934202fad7be10645354df40ca2f6330d768c4257836`。margin 是预定规则，尚无误差界使其成为收益证书。

## 3. 预测分数：有改善，但对照是弱 critic

下表先在各来源组内平均，再对 6 个来源组等权；CRPS 越低越好。分数针对已观测宏的终端质量、记录耗时和 `U - 0.01 D`，不等于实际内容改善或完整成本收益。

| 指标 | 冻结中心点预测 | 条件联合残差分布 | 中心点减联合分布 |
| --- | ---: | ---: | ---: |
| 终端质量 CRPS | 0.4056396772 | 0.1103362665 | 0.2953034107 |
| 耗时 CRPS（秒） | 0.8877561978 | 0.0621522699 | 0.8256039279 |
| 延迟价值 CRPS | 0.3997678362 | 0.1103779838 | 0.2893898524 |

**原 checkpoint 仅完成 content-stage 预训练。** 精确匹配原 receipt pin 的训练代码表明，utility、transition、duration、light heads 不在该阶段优化。因而这里比较的是尚未专门拟合的辅助中心点预测。没有完成与充分训练 critic 或无条件残差基线的比较，不能把改善归因于语义条件化本身。完整依据见 [独立审查](local/READ_ONLY_CROSS_REVIEW.json)。

## 4. 风险改变了预测选择，尚无替代动作的真实结果

| 风险参数 ρ | STOP | PREPARE_ROI | WRITE_TEXT | 相对 ρ=0 改变的状态 |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 19 | 32 | 3 | 0/54 |
| 0.25 | 14 | 40 | 0 | 8/54 |
| 1 | 12 | 42 | 0 | 10/54 |
| 4 | 0 | 54 | 0 | 22/54 |

每档风险共做 198 次候选预测，没有候选被判为 unsupported；这仅表示通过本方法的有限邻域规则。替代动作没有执行，`actual_outcome_for_choice` 为 null。高风险下全部选择 PREPARE_ROI 不是已验证的合理行为。

131/432 个观测宏的效用粒子被裁剪到 `[0,1]`，占 **30.324%**；46/54 个宏包含裁剪。所有 54 个终值分布均非恒定，但这不提供条件覆盖、尾部覆盖或未来 deadline 保证。动作与 task family 按固定计划绑定，替代动作的观测重叠不足；这是需要检查的偏差风险，尚未确认其对上述选择的因果影响。

## 5. 实际内容结果必须与预测改善同时报告

以下是固定行为真实执行的终端 rubric 质量；不同动作来自不同上下文，不能据此排序其因果效果。

| 已观测宏动作 | 数量 | 均值 | 最小值 | 最大值 |
| --- | ---: | ---: | ---: | ---: |
| PREPARE_ROI | 6 | 0.5 | 0.5 | 0.5 |
| READ_ROI | 6 | 0 | 0 | 0 |
| RENDER_IMAGE | 6 | 0.0060276956 | 0 | 0.0204833246 |
| STOP | 30 | 0.3012055391 | 0 | 1 |
| WRITE_TEXT | 6 | 0 | 0 | 0 |

补充的事后描述性检查发现：6 条 WRITE_TEXT 记录的 before/after score 均为 0，而 6/6 候选列表都包含按现有 evaluator normalizer 可精确匹配 reference 的候选。这提示应核查内容选择与交付链，但不确定具体成因；没有为此修改模型、注册或记录。见 [描述性检查](runtime/POSTHOC_CONTENT_DIAGNOSTIC.json)。READ_ROI 后直接 STOP 没有文字交付，其零分也不能自动解释成读取失败。

## 6. 资源、失败和时间

| 路径 | 实际观察 | 可作出的结论 |
| --- | --- | --- |
| Colab T4 | 一次 allocation 未确认；同 key 对账为未观察到分配且不重提；没有 owned runtime/kernel | 未建立 GPU 执行 |
| Kaggle GPU 预检 | kernel 143579470 v1；provider COMPLETE，但 Torch 2.11.0+cpu、CUDA device 0；worker 4.722 秒 | `GPU_FAILED / CUDA_UNAVAILABLE` |
| Kaggle CPU 诊断提交 | 一次 submit HTTP 400 `INVALID_ARGUMENT`；原请求对账 HTTP 403 `PERMISSION_DENIED`；无 kernel/version | 远端效果 UNKNOWN，没有新 request 重提 |
| HeptaRuntime 实际采集 | 60/60 completed，外层墙钟 24.801615 秒 | 真实固定行为采集完成 |
| HeptaRuntime 原生诊断 | rog，Python 3.14.4、Torch 2.13.0+rocm10.0.0，实际 model device CPU；成功外层 2.972172 秒 | 预测诊断完成，`gpu_used=false`、`cloud_run=false` |

原生首次启动因 PYTHONPATH 缺仓库根目录而失败，耗时 2.603634 秒，原件保留；第二次只修正启动路径。两次 native attempt 合计 5.575805 秒。成功 driver 区间为 2.412149 秒，包含加载、重放、经验 bank 拟合与诊断，但不包含解释器初始导入和最终 receipt 序列化；外层回执补充该范围。

原始宏之间可能共享 STOP，不能累加宏耗时冒充系统总成本。所列执行上限保守合计 `600 + 90 + 600 + 480 = 1770` 秒；它不含全部控制面、上传、编译及传输开销。货币、能耗、未知云请求的完整成本仍未确定，原生所有权认证仍标为 separate_required，因此没有完整生命周期净收益声明。

## 7. 工程准入与研究准入

本地新增范围 44 tests 通过，与全仓库 CI 是两件事。最终科学源码 head 的 44 个 CI checks 为 **18 success / 15 failure / 10 skipped / 1 cancelled**。已核查六个代表性失败，观测到工具／依赖下载或 action 准备问题；未执行的套件不算通过，也未把六例解释外推为全部原因。见 [完整 CI 快照](local/GITHUB_CHECK_SNAPSHOT.json) 与 [补充审查](local/FINAL_CI_ADDENDUM.json)。

本轮方法层面的交付为可执行的有限问题、身份约束和明确误差条件；架构优越性尚无 matched-resource 实验；系统审计已覆盖本次采集和诊断，但生产控制、学习更新、加载恢复与全成本收益的闭环仍未完成。所有阶段保持 draft/HOLD。

## 8. 代码与证据入口

| 阶段 | PR | 内容 |
| --- | --- | --- |
| 1 | [#5441](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5441) | 条件联合残差 bank |
| 2 | [#5442](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5442) | STOP 同口径的 horizon-one 选择器 |
| 3 | [#5443](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5443) | 冻结 checkpoint 与真实宏绑定 |
| 4–5 | [#5444](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5444)、[#5445](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5445) | 分区注册、proper scores 和诊断 runner |
| 6–7 | [#5446](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5446)、[#5447](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5447) | 真实采集契约与有界执行 |
| 8–9 | [#5448](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5448)、[#5449](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5449) | 方法边界、原始测试与完整 CI 证据 |

- [方法与近似条件](METHOD.zh-CN.md)：CE 的 sup-norm 稳定性、有界 TV 条件、贪心误差、实用 margin 和多步假设边界；已有研究的准确定位。
- [源码资格与 pins](SOURCE_QUALIFICATION.json)、[环境恢复记录](runtime/RECOVERY.json)。
- [实际诊断完整脱敏摘要](runtime/NATIVE_DIAGNOSTIC.json)、[云端尝试完整脱敏摘要](runtime/CLOUD_EXECUTION.json)。原始标签、私人路径及完整训练行未发布到此公开仓库。

直接启动 driver 时，使用包含 Torch/NumPy 的解释器，同时设置 `PYTHONPATH=<source-root>/scripts:<source-root>`，传入原 records、weights、registration、behavior receipt 与全部 expected SHA；指定新的 output 目录和受外层监督的时间上限。精确参数形状及实际 launcher hashes 见 NATIVE_DIAGNOSTIC 的 launch 字段。仅启动成功或返回 exit 0 不足以判定研究通过。

## 9. 下一道实验准入

先核查六个 WRITE_TEXT 零分观测的内容选择／提交链，并确认冻结内容基线的资格；在独立 fit 分区训练充分的价值、动态与耗时预测头，保持内容权重冻结。之后补足动作跨任务类型的探索覆盖，加入条件／无条件残差和期望／风险控制的预登记对照，再在未访问的 confirmation 上执行真实 STOP/继续 A/B。完整计划分母、失败／恢复成本、独立训练重复，以及收益下界超过实用门槛是准入条件。满足这些条件之后，才讨论开放 Hepta 状态更新与局部 adapter 的联合学习。
