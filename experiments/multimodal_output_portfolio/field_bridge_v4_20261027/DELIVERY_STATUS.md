# V4 最终交付与归档状态

本文件是完整归档构建、校验和 literal restore 复算完成后的交付补充，**不在它所描述的归档内部**。科学协议、原始训练/端点结果、唯一资格判定和其冻结来源均未改变。

## 实际结论

本轮单次前瞻资格实验完成，正式状态为 `QUALIFICATION_FAILED`。六项检查通过四项：普通训练相对冻结模型的净效用增益，以及 ordinary、origin_field、origin_richer 的三项 qualification clean 非劣效。两项参数场增量都没有通过原校正区间下界和逐模型严格正向条件。

| 比较 | reward 均值 [99.1667% 区间] | audit 均值 [99.1667% 区间] |
|---|---:|---:|
| ordinary−frozen | +0.021425 [+0.014677, +0.029479] | +0.022656 [+0.015530, +0.030905] |
| origin_field−ordinary | +0.000160 [−0.003410, +0.004172] | +0.001286 [−0.001775, +0.004138] |
| origin_field−origin_richer | +0.000095 [−0.002693, +0.003111] | −0.000409 [−0.003482, +0.003094] |

以上是净效用单位，不是准确率百分点。固定 4,000 次层次配对 bootstrap、种子 271042；每观察者六比较校正，两观察者联合要求通过。三个模型是固定历史模型，四条日程是模型内训练变化。模型 29 的 field 与 ordinary 四条最终参数及优化器身份全部相同，增量为 0；这个平局不满足严格正向要求。

原 B03–B07 最终科学验收仍未建立或部分开放；新 qualification clean NI 不替代原 final retention。没有新 runtime 或 final 执行，没有为了通过门槛改策略、扩大样本或重试。全部依据见 [原始结果](evidence/QUALIFICATION.json)、[原条件 blocker 账本](../field_bridge_v4_20261027_review/BLOCKERS.json) 和 [独立解释审阅](../field_bridge_v4_20261027_review/INDEPENDENT_V4_RESULT_INTERPRETATION.md)。

## 完整原始证据已在本地闭环

| 项目 | 实际完成 |
|---|---|
| 研究执行 | 108 条完整训练路径、108 条端点路径、3 个冻结原模型端点；0 次科学重试 |
| 训练独立审计 | 108 路、360 次头预测、111 次 checkpoint 加载；策略、guard、零动作与完整 SGD 回滚全部通过 |
| 媒体独立评分 | 222 个媒体文件、340,992 个输出、681,984 个观察者效用值，最大重算误差 0 |
| 完整归档 | 945 个 payload 成员，487,105,575 字节原始载荷；包含全部 108 个 checkpoint、108 条轨迹和 222 个媒体文件 |
| 压缩包 | `hepta_field_bridge_v4_20261027_evidence.tar.gz`，415,960,474 字节 |
| 完整性 | 所有成员 SHA/字节、外层 gzip CRC 至物理 EOF、119 个内部 gzip 流均通过 |
| 字面恢复 | 280 个文件，15,622,988 字节，恢复到独立新目录 |
| 原算术重放 | 从恢复目录调用原冻结分析器，全部统计字段、原六项比较、抽样 SHA 和失败结论精确一致；模型、观察者、native、优化器、网络调用均为 0 |

归档 SHA-256：`716b1291ee2fe1271f50589222fec9793b87a5bcae156c7af8e498c6c80f9df7`。

Manifest SHA-256：`fd05cac4184a7c468b4da057ea0f84e7ffe0e8978dd25287840f6117fb215cd0`。

完整性回执 SHA-256：`4c6908684d98c7fa0b521b38be80a42ec72e25060a5bf91e27753e908887328e`。

恢复复算回执 SHA-256：`9e14fd53c756759060224d9690d6e4ceb798ef1af878b879626f29f18890e15f`。

见 [复合归档与恢复回执](evidence/ARCHIVE_AND_RESTORE_VERIFICATION.json) 和 [归档身份](evidence/EVIDENCE_ARCHIVE.json)。复算是同一结果的完整性验证，不是第二次推断性观察或新的方法选择。

## 历史资产缺口已经按原身份修复

首次 collector 正确拒绝了历史资产清单中的 19 个零字节占位文件；本轮实际使用的 9 个模型、观察者、数据文件一直完整且哈希正确。V3 的旧归档也含这些历史占位，不能虚称已经保存那 19 个有效载荷。

随后从已保存的原始 `ndu_v6_full002_evidence.tar.gz` 只读恢复。原包 SHA 为 `ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e`，原 manifest SHA 为 `c452c96798d45618d6509695e52b8587a080ac26e721b2a566e6d3746e425205`。恢复 19 个文件共 62,146,791 字节，全部按原尺寸与 SHA 校验；原 9 个科学输入未重写，前后身份相同，原 RESTORATION 清单未改。28 个文件现已完整进入 V4 包。

首次拒绝、官方只读下载的初次网络失败与成功读取、精确恢复脚本及前后身份、第二次 collector 和首次实际 build/integrity/reanalysis 的记录全部保留。没有重新训练、修改科学源码、放松资产校验或丢弃失败记录。

## 论文对应的补充界限

再次核对固定 R45 原文后，需要明确：论文已经区分优化器完整状态、信息、执行动作空间和估计系数误差，也明确不宣称普遍二维充分统计量。其预训练模型实验与这里的 Hepta 桥接实验是不同证据；本轮未建立 Hepta 的 LLM 规模效力，不能据此抹去论文自身的预训练模块实验，也不能借用那些实验替 Hepta 建立效力。

本桥接中的 H12 加冻结 Q_ref 头不是论文两场递归 Riccati 控制器的逐公式复现。它检验了受论文启发的训练状态和决策方案；Hepta 运行状态控制则是另一层候选。应把论文的误差记账标准用于约束两层各自的实证主张，再检验组合，而不能把共同使用“状态/控制”术语当成理论等价或最优性证明。

来源：[R45 main 固定快照](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)、[递归控制细节](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_recursive_detail.tex)、[完整 comments](PAPER_HEPTA_COMMENTS.md)。

## 剩余交付限制

源码、正式结果、审计和归档回执通过研究分支交付。完整 V2/V3/V4 原始包及其验证文件尚未完成新的持久保存；自动审批拒绝了先前上传请求，理由为需要明确命名文件和 ChatGPT Library 目的地的用户授权。原资产包的只读下载不改变此状态；没有重试被拒绝的写入，也没有换原始数据出口。具体六个最终文件见 [PERSISTENCE_REQUEST.json](evidence/PERSISTENCE_REQUEST.json)。

当前工作区是部分研究镜像；整仓格式化/CI 未执行，不声称该门槛通过。实验验证范围是实际研究契约、原始输出审计和归档恢复。PR 保持 draft，`DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false` 保持不变。
