# 四次 B/C 开发连通检查：只读可行性审查

## 结论

**原开发 API 可以承载一个事前冻结、最多四个新 macro 调用的独立执行实例；当前尚未 freeze，也未授权或派发这些调用。** 本次只读审查没有远端 job、actor、collection、fit 或 export。完整候选输入在 REGISTRATION_CANDIDATE.json，执行前条件及一次性对账方案在 PREFLIGHT_AND_ONCE_ONLY.json；二者是待审候选，不是已完成登记。

原路径允许 development 角色，要求普通非 root 账户、原 Landlock/seccomp 隔离和原外部评分。它没有以 Rust StageOwner receipt 为这个开发入口的必要输入，也没有产生该 receipt。生产 owner、持久 cadence/CAS、原生跨重启 exactly-once 仍未认证，研究结局仍为 HOLD_NOT_EVALUATED，owner_decision=null。

## 精确输入与执行范围

| 项目 | 固定内容 |
|---|---|
| 原 native source | 3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd |
| 原 wrapper blob / SHA256 | 94e819d579232597de08a5c239a78e9d40768416 / e0800f6e1187a1b2bab532dbd8b1618d200a9cce786f0337d7c13da228beb82a |
| 原训练 FROZEN SHA256 | 7679b083343d6de9d7b3e1f1acc4f3252b044de36deafadb289ff532c7de7497 |
| 原 CHECKPOINT SHA256 | c4ee4a0219117edeec6381b0bb01b896f9a182862298eba22d3c69a828c17096 |
| 候选 registration SHA256 | e8c386af635518c9ee8d73c62f8e217bd9f8bcbf78b1bbe36fb2477f9ba634c4 |
| B 来源 / case / seed | merchant-8be0cc526665e1b3713e88d9 / case-6132a3f806804b12f08cb095 / 130363 |
| C 来源 / case / seed | merchant-ac7dff025170a6ee898d500b / case-fdc68cd739dea87c3c21bb51 / 130366 |
| 方法 / 分母 | 每阶段 tuned-fixed 与 conditional；每阶段 1 context、1 source、2 rows；总 4 rows、2 个既有来源 |
| 开发运行环境 | 原配置 Python 3.12.16 路径及原 python-deps；不是 #6240 的 Python 3.12.14 合同测试环境 |
| 新输出候选 | /home/qq/neuro-rv-bc-development-862531d11598-v1（尚未检查存在性或创建） |

候选完整 case、packet、reference、source SHA 与 seed 来自保留的原 FROZEN.evaluation_cases：按原顺序取前两个不同来源各第一行，没有依据效益挑选。只读资产核验已通过实际 wrapper load_native、原 modules/thaw/model.load、原 collection validator、原留存 execution plan 的 validate_plan/check_inputs，以及这两个来源的 validate_partitions；job 1a1cf673fde-2564-1a15，0 actor。它没有执行新 plan 的 freeze/check_inputs，也没有重读两份 reference 正文；只对 B reference 做过 stat。未来每次 EpisodeHost 构造继续核 public packet/reference 字节，评分继续核独立 role-index/rubric。不存在以静态检查取代该原门的许可。

minimum_observed_gain 候选为 0，仅定义 B 结果中描述性参考标签的正负；未改变 alpha=0.1、校准门、支持域或科学验收标准。C 仍执行两个固定方法，无论 B 的描述性标签是什么。该标签不产生采用决定。

## 为什么它与旧运行是新 effect，又不是新独立样本

完整旧 REPORT 原 SHA256 为 968b1d462dcc6afc3c51ecf34f17c05c59762c2d9cda889054d10cb87c48e41a，3,108,442 B；本次重核全原文 hash。两个候选各已有 12 个 COMPLETED 原行，合计 24 个旧 operation。SOURCE_AND_OLD_EFFECT_AUDIT.json 保留这些精确旧 ID、同模型两臂和 8 个实际调用源码的 hash/链接。

原 macro_execution._roster 的公式是 `"macro-" + digest([plan_pin, context, arm_id])`。wrapper 新部署的绝对路径写入新 plan，所以新 output、实际新 plan pin 与新 effect ID 绑定；不是只改文件夹名再沿用旧执行对象。必须在真实 freeze 后、actor 前，按原 digest 计算四个 ID，验证四者互异且与旧 576 ID 全集无交集，保存检查原件。本次没有臆造尚未生成的 FROZEN/plan/operation digest。

原 profile 的 study_id、fit_run_id、fit_id、weights、receipt 等训练谱系仍原样保留。execute_steps 会用新 roster ID 覆盖 profile.original_operation_id，再传给 EpisodeHost 和实际 actor CLI；这才是新调用的 effect 身份。不能声称每一个 metadata 标识均已改名，也不能用继承的原 study_id 将四次新调用混入旧 576 分母。

这些来源已在原 development evaluation 中暴露。B/C 与 fit/cal 及彼此的声明来源、图像字节不重叠，可以用于开发连接性检查；它们不是新的独立确认来源，不能把复用 seed 或新 output 增记为新 source。

## 此模型决定了检查能覆盖到哪里

原 checkpoint 的 tuned_fixed=STOP，calibration.complete=false。原 choose 在 conditional 支持域内仍因 incomplete calibration 返回 STOP，域外更早返回 STOP；其他合法性/预算拒绝也不会放行 READ。保留现有模型与门槛时，两臂都不会选择 READ。四次实际完成可以覆盖两个阶段的新真实调用、终端保留、B→C 屏障和只读对账；不能覆盖 READ 动作效力、校准通过、独立确认或科学效益。

read30s、finalizer reserve5s、action40s、actor episode60s 均沿原值；每行另有原外部 scorer timeout30s。最多四个 actor 的超时额度合计240s，评分额度合计120s，初始化/源码核验/准入仍另行真实计费。候选外层每阶段600s仅是新控制进程上限，不是完整成本证明。full_cost_observed=false，energy/provider/一次性训练校准调优成本不因本轮变成0。

## 事前冻结与一次性执行顺序

1. Root 审定原 wrapper 字节、完整 registration、新输入/输出路径与用途。只用新目录 create-only 物化候选；所有原 run-v2、源码、模型及标签对象不改。输出必须在全部 actor runtime/profile read roots 外，且不能别名到旧输出。
2. 仅调用原 wrapper freeze，保存实际 request、wrapper、四份 deployment、B_PLAN/C_PLAN 和最终 FROZEN 的原字节 hash。freeze 中途失败留下的目录是失败准备证据，不能覆盖或声称完成。
3. 真实 freeze 后，在两个新 plan 上跑原 validate_plan/check_inputs，并核四个新 operation ID 不与旧 576 相交。这个 actor 前检查不执行 actor；它尚未发生。
4. B 使用一个独立固定 key 与精确请求启动一次；原 wrapper START 和 native START 都在 actor 前落盘。C 使用另一个固定 key；仅在 B 的原只读 reconcile 验出 RECORDED、digest 不变、两行 COMPLETED 后启动。
5. C 仍保留两臂，不按 B 结果删掉一臂。若 B 不完整，保留总计划四行，C 两行记 NOT_STARTED；不为了补足分母补跑、换 seed 或重启。
6. 请求确认不明只对原 key/原参数对账，不换 key 重派。同一 START 无 TERMINAL 永远保持 UNKNOWN。若 native PLAN/RUN 尚未完整写出导致原 reconcile 无法读取，也保留该原错误及 wrapper MAY_HAVE_DISPATCHED/UNKNOWN，不能推断零 effect。
7. 后续只用原 reconcile-B/reconcile-C 读取保留对象。保存全部原 stdout/stderr、START/TERMINAL/REALIZATION、原 launch/evaluator/content 证据与失败信息。普通进程独占文件和 fsync 不认证断电恢复、持久 owner CAS 或跨 boot exactly-once。

## 验收与未闭合项

机械验收要求新 freeze 早于全部 START、实际四行均为 native_macro、B/C 各两行 COMPLETED、原准入证据可读且 hash 一致，独立只读对账重现两阶段 report digest/summary。执行失败仍是有效保留结果，不能等价于机械门通过。原3c94 native cohort 中的旧 NoUpdate 字段仍是原源输出，不能冒充 owner 决定；wrapper 显式 HOLD/null 保持不变。

仍未闭合：真实新 freeze/B/C 四次调用、任何未实测的新路径状态，以及 production owner、真实冷恢复/重启权限链、长期可塑性与效益、READ 价值、完整成本、功效和独立 B/C 确认。本审查不以这些边界阻止原本允许的普通开发 API，也不把该 API 执行当成上述资格。

实际源码依据：[macro_execution](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ndu_real_runtime/macro_execution.py)、[macro_execution_plan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ndu_real_runtime/macro_execution_plan.py)、[EpisodeHost](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ndu_real_runtime/episode.py)、[evaluator](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ndu_real_materials/evaluator.py)、[isolate](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ndu_real_materials/isolate.py)、[macro_policy](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ndu_real_runtime/macro_policy.py)、[原 wrapper](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/52f936df6e7d3f55e65c133dd7d9c9d16ca699a2/qualification/neuroscience-20261110/replay_perception_native.py)。
