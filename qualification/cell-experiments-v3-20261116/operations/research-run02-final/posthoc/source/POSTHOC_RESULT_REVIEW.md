# Run02 诊断顺序修复后的只读结果复核

复核日期：2026-11-17（UTC）。复核对象是已完成的 posthoc 读回，不是新一轮训练或能力实验。
本文所有相对路径均相对于 `/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a`。

## 结论

原诊断的顺序兼容错误已由独立版本的最小修复解除；三项固定候选、两项基线及独立列示的 shadow 均可按原有诊断门槛读回。
这不改变科学结论：六臂在旧曝光 B 上均为 **0/3**，固定三槽在旧 A 的 first-attempt 成功并集为 **5**，最佳单槽亦为 **5**。
未观察到这组三槽可增加的任务覆盖，未执行路由，所有科学确认、Circuit、原生 Cell 采用和 PoUW 资格保持 false。
**原 DIAGNOSTIC 仍原样记录全部 UNAVAILABLE；它与明确标记 posthoc 的新结果必须并列保存和解释，不能用新文件覆盖历史结果。**

## 1. 实际执行与输出身份

独立重读同一已结束 Mac PTY `dpty-248f77b275fa92cd5b9d431cb96abc15252718785b99f4c68eb9775fcd99149e`。
观察到 `state=exited`、`exit_code=0`、`output_complete=true`、无 capture_error、无截断。
其保留输出记载 `CLOSED_AND_COPIED`、实际 SSH wait return code 0，以及下列三个精确输出身份。
此处只读已有终端存档，没有再次启动 controller、diagnose、测试、模型或 verifier。

| 文件（均在 research-posthoc-evidence-02/） | 字节数 | 本次完整字节 SHA-256 |
|---|---:|---|
| DIAGNOSTIC.json | 79,539 | `5aed01965e9d1cb6575bc97b8e760e13ffcd656ab15b8c4a88dd33674a5929b7` |
| INPUT_BINDINGS.json | 272,959 | `ce31ded2b375d1666f550c34772d56da0fafb90ee434765c126591822e31d51d` |
| POSTHOC_RECEIPT.json | 1,319 | `47682bc26218d9c47d3d9a1fcd2379eeaf036717474aa204ea2fe07c44166b9b` |

全部分块以首块返回的版本固定后读取；各分块 SHA 和拼接后全文件 SHA 相符。
POSTHOC_RECEIPT 中 `diagnostic_sha256`、`input_bindings_sha256` 与上述实读值相符。
新诊断为 `RESEARCH_DIAGNOSTIC_COMPLETE_UNQUALIFIED`；外层回执为 `POSTHOC_READOUT_COMPLETE_UNQUALIFIED`。
冻结的准备 manifest 继续保留 `PREPARED_NOT_EXECUTED`，实际完成身份由新的回执和终端结果表达，不回写准备历史。

## 2. 输入、规则及原件保全

已核对 `operations/research02-diagnostic-order-fix-01/POSTHOC_RUN_MANIFEST.json`：
完整 SHA 为 `147d90e993733c3c998210c55548c15d339a87d661a72bc49b1968bda3936e1c`。
其十项 pin 的相对路径、字节数及 SHA 均出现在新 INPUT_BINDINGS，逐项一致：
candidate_source、fix_manifest、operation_freeze、original_diagnostic、original_rules、
original_source、patch、recorded_inputs、regression、runner。

INPUT_BINDINGS 声明和实际成员数均为 **1,624**，每项为合法 SHA-256 与非负整数长度。
独立重算其规范 JSON digest 为
`c5def6f16b77844be4f9793870de5dc24c890a8e5000e1a5c75aa1fb1692a5f7`，
与新诊断 `input_bindings_digest` 一致。该数量是选定读取清单，不是整个归档成员数或逐行代码审计量。
清单路径中未出现独立 C/confirmation/sealed 目录；本次复核没有读取任何新 C。

下列原件在 `research-final-evidence-02/` 下被本次重新完整读取并重哈，全部与先前冻结身份一致：

| 原件相对路径 | 字节数 | 原值与当前实读 SHA-256 |
|---|---:|---|
| research-diagnostic-02/DIAGNOSTIC.json | 64,006 | `662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b` |
| research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py | 46,995 | `28d82e170ab0720fb6b453275a80b4bf1eebc1e987ed1ae3bd935bb00a77a071` |
| research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json | 3,861 | `f50ced9146611fc07c4638a35f204e94f1ebf0b5e6c4ab70ac9667095135c1bc` |
| research-sft-02/FREEZE.json | 55,576 | `50a6ad4c3e8088100cc84a047f0556b92294eb3e44dc644e62e2976137c2770a` |

原 INPUTS 的 `691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3` 在 manifest 与新读取清单中完全一致；
本次没有额外重读该 495,218 字节原件，也没有逐一重哈清单内全部 1,624 文件。
已完成 runner 的 `Reader.recheck` 是选定文件前后 hash 一致性检查，不能称为原子文件系统快照。
新诊断也明确 `atomic_snapshot_claimed=false`、`writer_stop_authentication_performed=false`。

派生源 SHA 为 `ce0b68cd98673bf15f170d1da7c42670f65320ba5c9d3cacc2f1c28696273821`；
patch SHA 为 `29c614601ac0e63d2c2d64bd0c99d817d41bdda065ae3982a1052d28dec819ad`。
原规则仍绑定原源 SHA，派生源不冒充预训练冻结原源；新回执明确 `original_rules_modified=false`、`original_output_overwritten=false`。
根审查文件 `operations/POSTHOC_ROOT_REVIEW_02.json` 实读 SHA 为
`ec909a13fda91535cd03775875f6aa769a1b2f4660fd4dae48bc5d79eac87efc`，授权一次只读读回。

## 3. 固定槽、基线与 cold 结果

下表从新诊断每条 `primary_outcomes` 布尔 map 重新计数；分母逐条核对为 A=6、B=3。
所有臂的 first 与 last 分数相同，cold 的完整 A/B outcome maps 与 primary 完全相同。

| 臂 | 新诊断状态 | A first / last | B first / last | cold identity / 不同 PID / 业务与原答案-token 一致 |
|---|---|---|---|---|
| parent | AVAILABLE | 0/6 · 0/6 | 0/3 · 0/3 | 全部 true |
| retrieval | AVAILABLE | 0/6 · 0/6 | 0/3 · 0/3 | 全部 true |
| final_answer（固定槽） | AVAILABLE | 5/6 · 5/6 | 0/3 · 0/3 | 全部 true |
| trajectory（固定槽） | AVAILABLE | 4/6 · 4/6 | 0/3 · 0/3 | 全部 true |
| controlled_correction（固定槽） | AVAILABLE | 1/6 · 1/6 | 0/3 · 0/3 | 全部 true |
| shadow_correction（单列） | AVAILABLE | 0/6 · 0/6 | 0/3 · 0/3 | 全部 true |

AVAILABLE 表示这些既有材料通过修订读回中的原有绑定与可读性门槛，不表示泛化或采用合格。
cold 对每臂均明确 `independent_sample_increment=0`，是同一任务、候选的跨进程重复观察。
parent A 先前成功数为零，retention 的分母为空；不能据此声称“已证明无遗忘”。

独立按固定三槽 A-first 成功集合取并集，得到 clipped-metrics、counter、mse、pair-map、readout-score 共五项。
该集合等于 final_answer 成功集合，准确复现 `union_successes=5` 和 `best_single_successes=5`。
`union_exceeds_best=false`、`routing_executions=0`、`slot_replacement=false`，
`full_system_cost_matched=false`、`circuit_experiment_qualified=false`，
停止原因为 `union <= best single slot`。不能把三臂成功数相加称为额外能力或 Circuit 收益。

## 4. 成本与资格边界

新诊断 cost_ledger 在其明示的 Run02 新保留 worker 文件范围内读回：
model_calls=202、student_verifier_calls=196、reference_calls=36、training_steps=256，
input_tokens=92,217、output_tokens=30,896；其 measurement_errors、measurement_gaps、budget_violations 均为空。
这些是已发生研究工作的读回计数，posthoc 自身新增 model/verifier/reference calls 为零。
该 ledger 排除此前 readiness 成本并单独关联，不能拿它替代 Run01+Run02 的累计成本。
`global_totals_unknown=false` 仅适用于此限定账本；energy、GPU active time、full_system_cost 仍为 null，
全系统成本未匹配，coordinator 成本另列且明确不能与嵌套范围直接相加。

新结果保留 `binding_errors=[]`、`candidate_selected=null`；
scientific_confirmation_qualified、circuit_qualified、native_cell_adoption、proof_of_useful_work_eligible 全部 false。
new_C=false；新增用户、外部教师、独立样本及独立观察均为零，任务仍是旧曝光 A/B。
本次核验未独立重新执行任何任务语义 verifier、加载权重或验证全部张量；不得将读取成功扩大为这些工作已复测。

## 5. 历史解释与发布方式

刚实读的原诊断中，三 fixed slots、parent、retrieval、shadow 全部仍为 UNAVAILABLE，
同一原因均为 `ValueError('evaluation task order or coverage differs')`，原 available_slots 仍为空。
根因及最小修复详见 `operations/research02-diagnostic-interface-review-01/REVIEW.md`
与本目录 `ORDER_FIX.diff`、`README_POSTHOC.md`；本次不扩大修复范围或降低顺序、覆盖、候选、cold 门槛。

发布应同时保留原诊断、事后派生源及 patch、冻结规则、输入清单、运行回执和本复核。
新报告支持“原输出存在且可以按相同规则正确读回”的解释，并呈现上述有限开发任务成绩；
它不增加独立确认，不产生采用资格，也未证明多来源互补、有效路由或净业务收益。
