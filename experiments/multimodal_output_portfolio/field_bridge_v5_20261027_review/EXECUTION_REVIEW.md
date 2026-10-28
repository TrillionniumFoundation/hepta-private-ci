# V5 执行与 blocker 独立审阅

**封包前结论：72 条路径执行完成；V5 候选 REJECTED；原冻结审计仍为 FAIL。**

本文件与 [BLOCKERS.json](BLOCKERS.json) 是独立于冻结实验源的后续审阅。
当前 run 的独立诊断通过内部一致性检查，150 个媒体文件的双 observer
数值全部精确复算。四个 field 对匹配 ordinary/richer 的增量比较均为零，
固定进入标准不通过。历史 ordinary48 精确回归失败没有被改写或豁免。
本文件是封包前快照；本地归档/恢复和原始数据持久保存尚未完成。

## 1. 四种结项语义

| 状态 | 允许表达的结论 | 不能表达的结论 |
| --- | --- | --- |
| `closed_pass` | 该具体子项在所列范围内满足标准 | 其他科学主张、全项目或生产资格自动通过 |
| `closed_reject_candidate` | 固定规则的有效数值判断否决该候选，决策工作完成 | B04 参数场增益已建立，或所有参数场方法无效 |
| `open_insufficient_evidence` | 所需证据缺失、待完成或不足 | 正效应、负效应或等价已经得到确认 |
| `approval_blocked` | 有具体审批记录阻止指定动作 | 科学试验失败，或可以换通道绕过审批 |

候选失败可以形成完整、可复核的研究结论，但不能满足“证明候选有增益”的
原始标准。本轮候选决策子项 `V5-D01` 与历史科学项 `B04` 分开记录。

## 2. 原始 B01–B10 的保存

来源为 Hepta commit `0acfd9b27db910c180b0d8911f39aea469b7f864` 的
[V4 台账](../field_bridge_v4_20261027_review/BLOCKERS.json)，文件 SHA-256：
`80f2169c0bd099b167684cf0dad197b05c34f5d3015832c73e1578a0e82d9f65`。

新台账对每个旧项逐字段复制，保留 `closure_criteria`、`status`、
`resolution`、历史证据与 `v3_update/v4_update`。额外字段只绑定原 commit、
文件 SHA-256、Git blob、JSON pointer、原项规范 JSON hash，并记录独立的
`v5_update`。旧文件未修改，L01/L02 的原始文字和非完成门槛性质也未修改。

| 项目 | 原始 status 原样保留 | 本轮可补充的范围 |
| --- | --- | --- |
| B01 硬输出响应 | `closed_for_registered_development` | 沿用已注册 actuator，不宣称通用可控性 |
| B02 局部预测与决策技能 | `closed_for_registered_local_trajectory_skill` | 保留旧八步结果；38 项测试不是新神经预测技能 |
| B03 普通学习收益 | `not_established` | 旧 development 不能替代 fresh gain 与独立 retention 联合条件 |
| B04 参数场训练增量 | `not_established` | 四个 field 增量比较为零；候选否决不转写为增益通过 |
| B05 runtime 控制收益 | `not_established` | 本轮没有新 native runtime 比较 |
| B06 Hepta 特有价值 | `not_established` | 本轮没有新 Hepta 对 matched-history 资格比较 |
| B07 独立保留性 | `partially_closed` | 旧 clean development 不充当独立最终 retention |
| B08 bridge 开销 | `closed_for_transport_overhead` | 保留旧工程范围；事务测试不扩大为部署收益 |
| B09 新数据与访问边界 | `partially_closed` | 本轮是已暴露 development；V2 shared-panel 历史条款仍未满足 |
| B10 完整证据与保存 | `partially_closed_pending_persistence_authorization` | 当前内部一致性/媒体精确复算通过；历史回归仍失败，归档与授权分别核验 |

上表是旧 `status` 字段，具体 V3/V4 的更细范围继续保留在 JSON 中。
`all_original_substantive_blockers_closed=false` 保持不变。

## 3. 已有实际证据

[SOURCE_AND_TEST_VERIFICATION.json](SOURCE_AND_TEST_VERIFICATION.json)
保存本次独立核验的完整回执、测试输出和文件身份。

### 科学源冻结与测试

- 已注册 source commit：`f49810e422892a76c1d37c19c5b4d5112cba6d9e`。
- 已注册 tree：`4abf70bbfe359f78cf4d42b550d6493e172a0764`。
- 对冻结清单中的 **64 个文件**逐项复算 SHA-256，并把本地字节的 Git blob
  hash 与已提交 tree 对比；全部一致。Partial clone 无需先物化新 blob
  才能完成这个字节身份比较。
- 三个训练 START 都绑定相同 source freeze，且登记时间先于训练开始。
  这只验证开始身份，不预先证明全部训练完成或 endpoint barrier 通过。
- 在固定 Python/NumPy/Torch 环境执行下列 **38 项测试，全部通过、无跳过**。
  未调用新的科学模型，也未读取 V5 endpoint artifact。

| 测试模块 | 数量 | 实际覆盖 |
| --- | ---: | --- |
| `calibration_tests` | 8 | 旧 saved-head/OOF 重放、共同阈值、seed17 baseline mismatch、输入与泄漏拒绝 |
| `policy_improvement_tests` | 8 | 有限 MDP 改进命题、误差界，以及 guard、hidden state、tail 与 baseline 反例 |
| `transactions_tests` | 6 | accepted prefix、当前 slice rollback、零动作、异常成本、原 48 步委托 |
| `records_tests` | 3 | hash chain、失败阶段拒绝、跨 study 和不完整封印拒绝 |
| `audit_tests` | 13 | 合成媒体与配对、记录篡改、事务成本、固定 admission 规则 |

这些结果使 `V5-E01` 在有限工程范围内成为 `closed_pass`，不能作为 rollout
质量、泛化或统一误差 certificate。实际神经轨迹仍须逐项独立审计。

### R45 文档绑定

核验的 `LEARNING_SYSTEM.fieldSourceRevision` 指向
`ICLR-2027/paper-llm-theory@f8df0a6075f58f3ab9431a889b773cdf8d6e771d`。
`ALGORITHM_SPECS` 中的文档 blob 与当时的 `NDU_FBSDE_SPEC.md` 字节一致，
并保持 `implementationState=not_implied`、`fieldIsCanonicalTruth=false`。

`V5-E02` 只结项这组已记录文档字节的绑定。后续
[ENGINEERING_REPOSITORY_VERIFICATION.json](ENGINEERING_REPOSITORY_VERIFICATION.json)
核验工程 commit `4cea2e109446115b12246952a0fdacb3a43e1281`、tree
`4d4030ea7a8578268a16b5f2ec9f462eedef327d`：40 个模块/来源观察、177 个
entrypoint、97 个 runtime 文档、165 个测试文件引用，
`repositoryBindingsChecked=true`。故 `V5-E03` 在提交后源/文档一致性范围
内通过；`nativeProductTestsExecuted`、`independentReview`、`allGapsClosed`
仍为 false，不宣称全仓库远端 CI 通过。R45 来源更新不证明 Hepta 满足论文
定理假设，也不替代实际 owner/product execution。

## 4. 冻结的科学问题与解释边界

本轮为三模型种子 × 四既定 schedule × 六方法，共 **72 路径**；每条 288
scheduled gradient microsteps，每 48 步选一次动作。六方法是 ordinary、
field gate、richer gate 分别配 guard48 和 guard8。各方法 gradient 数相同，
ordinary 不承担不用的特征测量；总 compute 并不相同。

所有实际 gate 保持 `certificate=false`。旧 OOF 最大 residual 不是部署统一
误差上界，旧 labels 是一条 realized reference tail，不是精确 expected Q。
seed17 的 label reference 为 action 1，ordinary fallback 为 action 2。
guard8 改变转移核，旧 guard48 head 在这里是经验 surrogate。相同 origin
preprocessing 的复用既不重新拟合 head，也不改变 V4 的科学负结果。

`Q_ref` 在足状态、精确或满足有效误差条件、相同 guarded transition 下可以
支持 policy improvement；它不同于部署策略价值不是自动的算法错误。但本轮
上述条件未获证明，因此只能用实际完整 rollout 评价经验候选。

## 5. 已执行结果与被保留的失败

三个原始回执的精确字节副本保存在本目录的 `evidence/`：

| 回执 | 结论与 SHA-256 |
| --- | --- |
| [AUDIT.json](evidence/AUDIT.json) | **FAIL**；`35af3341f3fc283c41beda469e5c9ff2531f7bf01d537cb4dcc9c4a7fd6b42df` |
| [WITHIN_RUN_AUDIT.json](evidence/WITHIN_RUN_AUDIT.json) | 当前 run 内部一致性 PASS，整体 FAIL；`0105da40023843b7551308c51e86fa945f9d213f21af29d53fb43a5fdfa6814f` |
| [MEDIA_AUDIT.json](evidence/MEDIA_AUDIT.json) | 媒体算术精确复算 PASS；`45240283c980e1558e4e8374a1e74088b126764f5d301d06d4b2c42a8048d7fe` |

原冻结 audit 在完成当前 path/endpoint 检查后，由历史 ordinary48 逐元素
精确回归检查抛错。另行登记的诊断 commit
`f0897403189e866ffaa16c186fdb4ded2d3b5341` 绑定该 FAIL 与六份阶段封印，
复用冻结检查函数复核 **72 路径、20,736 scheduled gradient microsteps、
1,512 个事务**，并验证全部训练封印先于 endpoint。诊断既不覆盖原回执，
也不产生原冻结 audit PASS：`overall_status=FAIL`、
`historical_regression_status=FAIL`、`admission=false` 始终保留。

独立媒体审计重新构造目标面板并执行冻结 observer，核验 **150 文件、
192,000 个媒体输出、384,000 个 observer 数值**；全部逐项精确相同，最大
数值误差为零、generator calls 为零。媒体 PASS 只说明本轮记录的分数算术
正确，不能消除跨历史执行的回归差异。

### 全部七个预定描述性比较

下表是当前旧 development 的三 seed 等权均值差，不是新的置信检验。

| 比较 | task/reward | task/audit | clean/reward | clean/audit |
| --- | ---: | ---: | ---: | ---: |
| field48 − ordinary48 | 0 | 0 | 0 | 0 |
| field48 − richer48 | 0 | 0 | 0 | 0 |
| field8 − ordinary8 | 0 | 0 | 0 | 0 |
| field8 − richer8 | 0 | 0 | 0 | 0 |
| ordinary8 − ordinary48 | −0.0129956001 | −0.0089652453 | −0.0024359677 | −0.0010280901 |
| field8 − field48 | −0.0129956001 | −0.0089652453 | −0.0024359677 | −0.0010280901 |
| richer8 − richer48 | −0.0129956001 | −0.0089652453 | −0.0024359677 | −0.0010280901 |

前四个比较的每 seed、两个 endpoint、两个 observer 的报告均值差也均为零。
guard8 相对 guard48 的 task 差在每个 seed、两个 observer 下都为负，
不能把更细的 rollback 粒度解释为本轮有益机制。field/richer 仍承担其
特征、方向梯度和探针测量工作；相同 gradient budget 不等于相同总计算。

field8 对 frozen 的 pooled task 增益为 reward `+0.0118164504`、audit
`+0.0147502070`，各 seed 为非负；clean 检查也满足本轮 development 的
数值 margin。它仍未超过匹配 ordinary/richer：两个 observer 各有两个
pooled superiority 检查失败，14 项数值检查中四项失败。因此
`numeric_passed=false`，`V5-D01=closed_reject_candidate`，候选 **REJECTED**。
这没有建立 field 的独立增量，也没有证明不同表示普遍等价。

### 动作机制已独立核实

[V5_NUMERIC_DIAGNOSIS.json](V5_NUMERIC_DIAGNOSIS.json)（SHA-256
`7c7d74b07dfdaabd0457d491bcf4b69523cc2a4d5461748968008073b597da7e`）及
[解释报告](V5_NUMERIC_DIAGNOSIS.md) 独立核验了 72 条 trace：**288 个自适应
决策中 override 为零**，所有预测 margin 都低于固定阈值，最大 margin/τ
为 `0.7182597844`。若不加 gate，greedy 有 121 次会选择非 baseline 动作
（field 53 次、richer 68 次）；实际执行全部回到 ordinary baseline。

48 个同 guard 的 field/richer 对 ordinary 路径，terminal parameter 和
complete optimizer hash 全部相同；对应 96 对 task/clean 原始 NPZ 文件
也具有完全相同的 SHA-256。因此零增量不只是报告均值相等。两个头的预测
并不相同：144 个配对决策的输入相同，greedy 有 26 次不同；本轮 gate
阻止这些差异进入实际动作。事后降低 τ 会构成新候选，不能修复本轮结论。

按每种方法的 12 条路径汇总，guard48 保留非零更新微步 `1728/3456`，
guard8 为 `912/3456`；不能把已接受事务数量 `36→114` 解读为实际学习
增加，因为事务长度改变。guard8 的额外检查与丢弃工作均已计费。

### 历史精确回归仍未闭合

旧/新 frozen 原模型的 utility 最大差为 `8.1434845922e-7`，ordinary48
最大差为 `3.3698976041e-6`。原门槛要求逐元素精确相等；大小很小也不满足
该门槛。本轮没有引入 tolerance pass。差异原因仍为 `UNDETERMINED`，不能
只因差异较小就宣布是硬件、库或浮点环境造成。旧 checkpoint/media 缺失
会限制进一步定位；重新执行不能替代原字节。

`V5-X02` 保持未闭合；另列的 `V5-X03` 和 `V5-M01` 分别记录当前 run 内部
一致性与当前媒体算术通过，不改变原冻结结论。

## 6. 保存与历史审批

[ARCHIVE_PLAN.md](../field_bridge_v5_20261027/ARCHIVE_PLAN.md) 已完成，故
`V5-A01=closed_pass`；它只表示方案可审查。此封包前快照中实际
archive/restore 的 `V5-A02` 保持 pending。封包后的 build/integrity/literal
restore 回执将单独追加，不回写已入包的本台账，以免出现自指 hash。

历史 Library 上传三次 automatic-review 拒绝由独立项 `H-P01=approval_blocked`
保存。它要求用户本人明确授权具体私有 archive/report 与 Library 目的地，
普通 continuation、分卷成 Git 小 blob、换通道或换为新 V5 文件名都不提供
该授权。**这一边界也约束本轮新的 V5 原始包**；`V5-A03=approval_blocked`，
当前尚无新原始包及具体目的地的明确授权，且本轮 upload attempts 为零。
这不是声称 V5 收到了新的自动审核拒绝。先完成新包和验证，再提供其精确
文件、大小、hash、内容与目的地供最终授权；不重试旧上传或绕开原限制。

历史 V2/V3 当时的本地完整验证回执也不证明今日仍有可检索的完整 raw bytes。
`H-A01` 要求找回与旧 hash 一致的原始字节；新执行不能代替旧证据。当前
已检查位置未发现完整副本，也不等于证明所有外部存储中的原件永久丢失。

## 7. 保持的系统边界

`DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false`
保持。L01/L02 保持原声明边界，不新增为本轮小任务必须证明的定理门槛。
完成执行、拒绝一个候选、通过归档完整性，与证明科学收益各有独立标准。

**本版 prearchive review 已定稿并停止修改。** 后续本地归档、literal restore、
授权或持久保存的实际结果由独立 postpackage 回执补充；不修改已封包台账。
