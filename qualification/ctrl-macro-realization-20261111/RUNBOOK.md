# CTRL 宏动作执行交接

当前状态：代码锚点 `e5ed7174` 的 CPU CI 已通过 149 个方法；原生 CI 已实际通过 OCR 3/3 与宏动作 2/2，包含 READ 后重新选择、交付和独立评分。原生 tested merge 与 source 的 tree 相同，Landlock ABI 8；详见 [CI_FINAL_VERIFICATION.json](CI_FINAL_VERIFICATION.json)。本地 Mandatory Landlock 失败原件（`abi=-1, errno=38`）仍保留；不得绕过隔离或改成 skip。上述结果限于 fixture，真实六策略和 2×2 尚未执行，保持 **HOLD / NoUpdate**。
以下命令从仓库根目录运行；`python` 必须是具备该仓库原生依赖与内核条件的解释器。所有大写路径/pin 变量均由审核后的真实材料提供，本文不提供虚构数据、模型 pin 或 fixture 替代品。

## 1. 先冻结来源、case 与完整分母

在任何采集前冻结 source ID 与原始 source 字节 SHA256 的双向一一映射、case、READ 条件、seed、内容训练开关、策略臂及 fit/calibration/evaluation 来源分区；分区互斥，别名不得把同一来源变成独立样本。
`macro_cohort` 的 `ndu.real.macro-cohort.v1` 必需字段为 `contexts, arms, partitions, shared, one_off_costs, factorial`，另有 `schema`；contexts 每项是 `{source_id, case_id, seed}`，实际分母固定为 contexts × arms。
arms 每项为 `{arm_id, content_mode, control_mode, policy, content_sha256, critic_context_sha256}`；partitions 使用 `fit/calibration/evaluation`；shared 绑定 action、legal_actions、settlement、evaluator、utility、tariff 六个 `*_sha256`。
保留独立冻结的 canonical `digest(cohort)`；调用 `macro_cohort.validate_plan(cohort, expected_plan_sha256=cohort_pin)`。哈希和 mode 声明是完整性检查，不是材料授权或来源认证。
将封存 confirmation/future 与已暴露来源排除在可执行评估材料之外；当前 runner 只接受 train/development/retention_validation，不能据此解封 future。

## 2. 取得 matched STOP / READ 的完整轨迹

已有采集入口 `metacontrol_native_pairs.collect(plan, output)`，使用 `ndu.real.native-macro-pair-plan.v1`；plan 包含 config、profile、source_pins、source_splits、excluded_sources、pairs、action_budget_seconds、latency_tariff。
这里 source_splits 的键是 `train/calibration/future`，与 cohort 的 fit 名称不同；每个 pair 为 `{pair_id, split, case, seed, read_condition}`，pair_id 唯一且仅字母数字，case.role 必须为 train；future 执行目前明确拒绝。
冻结真实 weights/control-plan/source 字节，profile 使用 ordinary/reset，采集 profile 不加载 macro_policy。两分支同 case/源/内容/控制随机种子/公开初态/预算，独立 reset；READ 条件仅 original/repeat/noise。
STOP 必须实际完成 `WRITE_TEXT → STOP`；READ 必须实际完成 `PREPARE_ROI → READ_ROI → 重新选择 → WRITE_TEXT → STOP`。保留原始 launch、host 回复、trajectory、候选选择、delivery、score、source/reference 绑定及失败状态。
```sh
PYTHONPATH=scripts:. python -m ndu_real_runtime.metacontrol_native_pairs --plan "$PAIR_PLAN" --expected-plan-sha256 "$PAIR_FILE_SHA256" --output "$NEW_PAIR_OUTPUT"
```
此 collector 的 CLI pin 是 **plan 文件原始字节 SHA256**。output 必须新建；强制采集只产生训练/校准动作证据，不是学到的策略评估。
转换入口已实现：`macro_training_pairs.export(collection_root, expected_plan_sha256=plan_file_sha, context=context, expected_source_sha256=frozen_converter_sha)`；这里 plan_file_sha 是保留 PLAN 原始字节摘要，frozen_converter_sha 是事前冻结的 `macro_training_pairs.source_sha256()`。仅接纳重新验收的 original READ 完整配对；repeat/noise、失败或缺件保留 UNKNOWN，不补造。
将完整返回值单独保存并冻结 canonical `digest(report)`，再调用 `macro_training_pairs.fit_rows(report, split, expected_export_sha256=frozen_export_sha, context=context)`，split 分别取 train/calibration。任一计划项 UNKNOWN 都会拒绝取行；不可直接把 report["rows"] 送入拟合。
每个新 fit row 必须含 `source_id, source_sha256, decision_id, context_sha256, state, branches, labels, label_receipts`；STOP/READ branches 各有 status、quality、cost、full_cost_observed、evidence_sha256、initial_public_state_sha256、public_state_sha256、actions。
同对两分支初态摘要相同，public_state_sha256 必须绑定原始公开投影与 `digest(state)`；每个物理分支使用独立证据。acquired/selected_used/effect_occurred 标签各需原始 witness，无法证明则 null。不得向 actor 暴露 reference 或未来来源标签。

## 3. fit / calibration 后冷加载，再冻结部署

`CriticContext` 的 encoder/answer 取真实内容权重 SHA，generator 取实际 ocr.py 字节 SHA，public_state 取 `macro_actor.codec_sha256()`，action 取 `macro_policy.ACTION_SHA256`；其余四项由 `macro_actor.host_context(config, digest(utility_profile(control)))` 取得。
输入 fit_rows/cal_rows 必须经过上一步真实证据审查并属于互斥来源；`source_sha256`（row 的来源字节）和 `macro_policy.source_sha256()`（拟合实现清单）含义不同，后者也须事前冻结。
```python
from ndu_real_runtime import macro_policy
model = macro_policy.fit(fit_rows, cal_rows, context=context,
                         expected_source_sha256=frozen_fit_source_sha)
with checkpoint_path.open("xb") as stream: stream.write(model.to_bytes())
cold = macro_policy.load(checkpoint_path.read_bytes(), model.sha256, context=context)
```
在新进程以独立保存的 checkpoint SHA 再次 load；上例变量来自已登记材料。模型、codec、动作、结算、评分、价格或公开特征语义变化时重新取证/拟合/校准；不沿用旧 critic 的效力声明。
每臂部署 JSON schema 为 `ndu.real.macro-deployment.v1`，字段是 policy、context（值为 context.to_wire()）、weights_sha256、control_sha256、checkpoint_utf8、checkpoint_sha256、read_seconds_bound、finalizer_seconds_reserve。
其中 control_sha256 是 `digest(asdict(control))`，control 为实际 ControlPlan 实例，不是 control-plan 文件 SHA；checkpoint_utf8 为完整 checkpoint UTF-8 文本。冻结部署文件字节并在 profile.macro_policy 填 `{path, sha256}`，host 将交叉核对实际 scorer/tariff/finalizer。
拟合数量门槛和预测改善均不构成独立来源效益结论；manufactured labels 与 fixture checkpoint 仅可用于软件回归。

## 4. 固定内容，实际执行六策略

预登记六臂 `STOP, light, tuned-fixed, point, unconditional, conditional`；light 是本轮宏动作经验 cell baseline，并非旧 utility=0.47125 实验的复现。同一 content_mode 共用内容与 critic context，所有臂共用原始 control-plan 文件、合法动作、结算、评分、utility/tariff、case 和 seed 集合。
`macro_execution_plan.source_inventory(config)` 取得实际 runtime/material/core 清单；`shared_context(config, control)` 取得 shared。weights 旁如有 deployment-profile.json/receipt.json，另加真实 source pin。
执行计划 schema 为 `ndu.real.macro-execution-plan.v1`，字段为 cohort、cohort_sha256、config、registered_cases、profiles、action_budget_seconds、source_pins、observer_sha256；observer pin 为事前冻结的 `digest(macro_realization.source_manifest())`。
registered_cases 每项是 `{source_id, case_id, seed, case, read_condition}`，完整对应 contexts；profiles 按 arm_id 提供 ordinary/reset、weights/model_sha256、control_plan/control_plan_sha256、macro_policy。输出必须在所有 actor 可读 runtime roots 之外。
先执行 `macro_execution_plan.validate_plan(plan, execution_pin)` 与 `check_inputs(plan, new_output)`；execution_pin 是事先冻结的 canonical `digest(plan)`，不是文件字节 SHA。
```sh
PYTHONPATH=scripts:. python -m ndu_real_runtime.macro_execution execute --plan "$EXECUTION_PLAN" --output "$NEW_EXECUTION_OUTPUT" --expected-plan-sha256 "$EXECUTION_CANONICAL_SHA256"
```
Python API 为 `macro_execution.execute(plan, output, expected_plan_sha256=pin)`。真实运行不传 host_class、不启用 allow_fixtures；host 使用 training=False，不接受 forced override/resume。
按原始 operation 保留 START/TERMINAL/REALIZATION/native artifacts；观察器分别检查信息取得、当前候选覆盖、选中并使用、实际执行与终态评分。历史匹配候选与 named policy 都不能替代当前执行。

## 5. 2×2、完整成本与源等权

另行事前登记四臂，factorial 映射 `off_off/off_on/on_off/on_on → arm_id`，顺序为 content/control；四臂使用相同完整 context/seed 集合及独立执行身份。
control-off 选择冻结 baseline，control-on 选择确已 fit/cal 的 critic；跨内容模式保持各自同一 policy，mode 声明不能自行证明学习发生。内容 on/off 来自真实内容学习协议，不将旧 static/dynamic 或算法名称当作已执行因子。合法 NoUpdate 可使两内容权重相同，仍如实记录。
每个内容 context 使用相应真实 fit/cal 证据和冷加载 critic。checkpoint 的 source_bindings 保存来源 ID↔字节 SHA 映射，runner 拒绝 evaluation 与 fit/cal 的 ID 或字节重用；仍须审计原始来源清单，声明不替代认证。
每臂 `one_off_costs={fit, calibration, tuning}` 用同一 utility/tariff 单位登记；共用工作须事前声明分摊。每臂一次成本总额除以 **该臂计划 contexts 数**，不是完成数或来源数。
每状态净值为 quality − task_cost − one_off_total/planned_contexts；先在同来源内平均，再对来源等权平均。paired contrast 逐同 context 相减；交互为 on_on − on_off − off_on + off_off，然后源等权。
调用 `macro_cohort.evaluate(cohort, rows, expected_plan_sha256=cohort_pin)`；同时报告 planned、各状态、admitted_completed、fully_costed 和 planned/paired sources。删整源、缺臂或换 case/seed 不可缩减分母。
只有对应计划所有状态都有合格终态才产生 primary_quality；完整成本净值、配对和交互还须全部 task/full-cost/一次成本已知。observed_subset 仅是带缺失的描述，质量实测 0 与未测 null 严格不同。
当前 runner task_cost 仅为初始化、选择、执行、评分及取证耗时 × latency_weight；provider/energy/一次成本尚未知，full_cost_observed=false，**完整成本效益、配对和交互保持 null，未知项不得填 0**。

## 6. 按原 operation 只读 reconcile

```sh
PYTHONPATH=scripts:. python -m ndu_real_runtime.macro_execution reconcile --output "$ORIGINAL_EXECUTION_OUTPUT" --expected-plan-sha256 "$ORIGINAL_EXECUTION_CANONICAL_SHA256"
```
等价 API：`macro_execution.reconcile(output, expected_plan_sha256=original_pin)`。仅读取原 PLAN/RUN/START/TERMINAL/REALIZATION/native 字节，不写文件、不启动 actor、不重新执行；可将 stdout 保存到 output 目录之外。
未开始的计划项为 NOT_STARTED；START 无 terminal 为 UNKNOWN；一般 cohort 缺记录为 UNKNOWN。FAILED/CANCELLED/RUNNING/UNKNOWN 不补零、不删行；已有 output 禁止 execute 恢复或换 key 重跑。
旧 V4/FIT40 原 operation 的 UNKNOWN 须按其原始服务 request/job/receipt 身份只读核对；本 runner 不把旧格式变成新证据，不重建请求、不补终态、不重用动作。CI 通过也仅说明软件/原生 fixture 契约，真实效益和生产准入仍需独立完成。
