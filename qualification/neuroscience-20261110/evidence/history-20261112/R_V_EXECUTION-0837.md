# R/V 实际执行入口与资产缺口（2026-11-12）

`replay_perception_native.py` 将既有真实 CTRL macro 执行器接到事前冻结的 B/C 开发面板；不复制 OCR、模型、隔离器或最终评分器。当前资格是 **DEVELOPMENT_ONLY / HOLD_NOT_EVALUATED**；`adoption=NOT_REQUESTED`、`owner_decision=null`，不冒充原 owner 的 NoUpdate 或采用决定。本文不是完成实验的结果。

## 已核实可复用资产

| 精确来源 | 实现／资产 | 可执行范围与限制 |
| --- | --- | --- |
| [#6159，397632651912513e24030476d98a5b101a0a0e0e](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6159) | `scripts/ctrl_macro_{prepare,study,analysis,content,factorial}.py`；`scripts/ndu_real_runtime/macro_{execution,execution_plan,policy}.py` | 原始 train/calibration pairs、实际 fit、独立 cold-load、真实 OCR／效果、完整计划分母；现有 campaign 使用已暴露 development。复用已拟合结果，禁止重复启动另一线程的同源 campaign。 |
| [#6072，a5583f0f4a12d9618a3a5bc5ed0e7062a7463f39](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6072) | `scripts/perc1/{source_capture,active_capture,source_qualification}.py`；`qualification/perc-real-observation-20261112/PRIVATE_ARCHIVE.json` | 原始 FUNSD→Tesseract/MobileNet→native 诊断 owner 已有工程链；64/16/32 来源全部复用，active 视觉系数为零。 |
| [#6136，ea5d3f77e275906f6623f7f4b64be1678d640f8d](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6136) | `scripts/ndu_real_runtime/episodic_provider_handoff.py` 与原 Rust episodic owner | 120 个组合软件控制不是记忆效益；真实模型尝试 ACK 超时且结果 UNKNOWN，不能新 key 重派发。 |
| [#6113，8c11ca58559f0fc05678387e09588bf2368d4d84](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6113) | `scripts/act2_learning/{qualify_operational,skill_lifecycle,durable_lifecycle,durable_async_owner}.py` | 真文件／进程恢复控制，仍是受控 probe；不是独立真实任务，缺原 Root/AuthBus/FinalUse 与通用技能回放效果链。 |

已公开路径只确认旧云工作区 `/workspace/scratch/e11c579132dc/hepta-perc`、`/workspace/scratch/e11c579132dc/perc-real-source-native-001`，不代表本机或 ai395 仍有这些文件。
PERC 私有包名 `perc-real-observation-20261112-evidence.zip`，39,224,877 bytes，SHA256 `8038206cf0219ab9ea1b7547ddc74aa6041c552c2843ecd1509c26215e0744b5`；仓库未给当前 host 路径。
旧 CTRL `runtime/NATIVE_DIAGNOSTIC.json` 的 `host_alias=rog` 是历史记录。后续只读探针已在 ai395 从真实 `FROZEN.json` 派生并校验资源：原运行 `/home/qq/ctrl-real-study-20261112-1333/run-v1/frozen`，freeze SHA256 `5ec574f35366cbffb12555832dc611a722e92d72ea3c709feaa838f6d619cf27`；weights 为 `/home/qq/ndu-real-runtime-20261107-bc2efaf10cd0/pilot-run-v1/models/common-collector-content/weights.pt`，SHA256 `db6e3d05270163368d10176299a7d5be3ccee2d8e773fcfbb32454ff1c0f9f54`。
旧原件的 83 项 source pins、driver/analysis、weights/control/exposure 与 collection plan 均通过对应 hash 校验；82 项是源码，另 1 项是 receipt。原 Python 路径存在且可执行，但 FROZEN 未提供其 binary expected pin，不能把观测 hash 称为原始认证。全部路径、清单与读回见 [部署前只读证据](evidence/rv-predeploy-20261112/MANIFEST.json)。

## 新入口的实际行为

1. 读取外部 SHA 固定的原训练 freeze；在动态导入前逐项校验原 `source_pins`、driver 和单独固定的 `analysis_sha256`。复用原 `ctrl_macro_study.thaw`、`macro_policy.load`；cold-load 记录必须匹配 checkpoint、context 且声明 `fresh_process=true`，这些字节一致性检查不认证 owner。**不重新训练或重跑原 collection。**
2. 登记 train/calibration/B/C 来源隔离，核对原 checkpoint 的 `source_bindings` 与 collection 图像哈希，拒绝同一来源跨 split、同图不同 source 名、同来源换字节、重复 context 与任何非 development 的 B/C role。seed 只作簇内重复。
3. B/C 的两个原始 execution plan 在任何新 actor 调用前一并冻结。固定 `tuned-fixed` 与 `conditional`，相同内容 checkpoint、动作上限、READ bound、finalizer reserve、可见原始 case／原始 read intervention。
4. B 调用原 `macro_execution.execute`；C 先用原 `reconcile` 读回全部 B 原件，要求结果完整且未改变，再调用原执行器。各阶段进程重新加载原 checkpoint，保留 native 原始轨迹、效果、stdout/stderr 与外层时钟。
5. START 先以 exclusive-create＋fsync 记录；中断／错误保留 UNKNOWN。已有 START 拒绝重派发。`reconcile-B/C` 只读，不创建 actor，也不修补缺失结果。
6. 对照冻结 `registered_cases × METHODS` 逐项检查完整 roster，拒绝等长替换 context；按完整计划分母报告状态，任一 UNKNOWN／FAILED／未启动阻止全面板均值。只在完整时计算簇内配对、来源等权的“质量−实测时延成本”差，不产生 p 值、确认通过或 owner 决定。

这里的 B/C 是 **development_B/C**；历史训练暴露与来源 owner 尚未认证，始终 `fresh_source_confirmation=false`。B 的均值阈值只给描述性的参考策略，C 仍执行事前登记的两臂比较；它没有执行原 StageOwner 选择，不是 G4 已选候选的普通 C 使用。
当前原执行器保持固定臂顺序；缓存／负载顺序效应与四线功效登记尚未闭合，不能用小 probe 作因果效益结论。
原 native admission 保留其信息前缀、READ 输入／输出与最终交付约束。新入口不改 material role，不解封未来标签；仅靠来源 ID/hash 不能认证来源、历史独立性或时钟真实性。

## 登记输入与最小执行

请求 JSON 只允许以下字段；所有路径／pin／case 必须来自真实原件，本文不提供虚构样本或签名。

| 字段 | 必须填写 |
| --- | --- |
| `repository` | 含上述原 native API 的绝对 checkout 路径；原 freeze 和 source inventory 必须匹配 |
| `training_run` | 已完成原 fit、含 `FROZEN.json`、`CHECKPOINT.json`、`COLD_LOAD.json` 的目录 |
| `training_freeze_sha256`／`checkpoint_sha256` | 独立保留的原始字节 SHA256 |
| `phases` | `B`、`C` 两个非空 registered-case 数组；每项保留原 `source_id/case_id/seed/read_condition/case`；`read_condition=original`，`case.role=development` |
| `minimum_observed_gain` | 运行前固定的有限非负描述性阈值；不是统计资格门 |

若原 campaign 产物、native 版本兼容性与运行身份均已核验，再各取一个不同来源且原 owner 已允许的 development B/C case，可登记 4 个实际 native 调用的连通 probe；这不新增来源资格，也不提供有效功效。目前已有原 key 对应的完整 run-v2 campaign，先读取其产物；不另派 28-episode 替代采集或另一套同源 campaign。

```sh
python3 replay_perception_native.py freeze --request "$RV_REQUEST" --expected-sha256 "$RV_REQUEST_SHA256" --output "$RV_NEW_OUTPUT"
python3 replay_perception_native.py B --expected-sha256 "$RV_FREEZE_SHA256" --output "$RV_NEW_OUTPUT"
python3 replay_perception_native.py C --expected-sha256 "$RV_FREEZE_SHA256" --output "$RV_NEW_OUTPUT"
python3 replay_perception_native.py reconcile-B --expected-sha256 "$RV_FREEZE_SHA256" --output "$RV_NEW_OUTPUT"
```

`RV_FREEZE_SHA256` 是第一步输出的实际 pin；不重用请求 pin。输出目录必须位于所有 actor runtime roots 之外。故障后先读原件，不能自动换目录／新操作 ID 重试不确定执行。
原 actor 时延已包含初始化、选择、动作、评分与 admission；外层 wall／parent CPU 单列，不能与嵌套时延相加。provider、energy、完整进程树、历史训练／数据取得与摊销仍未知，始终 `full_cost_observed=false`。

## 未闭合项与本地机械验证

- **wrapper 真实调用仍待运行（actor=0）：** 原 run-v2 frozen fit 与强制独立子进程 cold-load 已完成，CHECKPOINT_PIN、COLD_LOAD 与实际文件 hash 一致。其 fit72／cal54，但 `calibration.complete=false`、`full_cost_observed=false`；还须在 wrapper 原入口实际验证新 freeze／source pins／plan 及 B/C 配对登记，不能把上游 fit 成功计作 wrapper 的 4 次 actor 已执行。
- **R 2×2 仍 OPEN：** 尚无同一真实任务上的 episodic／skill replay 可用执行适配器，不能把 ACT controlled probe 与 MEM UNKNOWN 拼成配对效果。
- **同信息循环与 VERIFY 付费检查仍 OPEN：** 当前 native 宏只有 STOP／真实 READ，不提供任意同输入循环或独立 checker 的等预算接口；没有伪造“同信息”对照。
- **新来源 B/C 与原 owner 仍 OPEN：** 需要原来源登记／暴露证据和原有授权链，不接受自签名替代；现有 development 不重标 confirmation。
- **效益／采用仍 OPEN：** 强基线训练资格、完整成本、功效、顺序平衡、多重校正、旧能力以及原生选择／不同 C／冷恢复另验收。

本地测试使用构造数据验证边界；其中真子进程 `os._exit(9)` 后只有一次模拟 contact，重进程调用被 START 拦截。它验证一次执行机制，不是真实任务／真实模型／owner 结果。首轮有一个测试期望异常类型错误，随后修正断言；另覆盖等长替换来源／context、非法质量／负成本和 `1e999`；实现的拒绝条件未放宽。

### 已执行的原生接口机械集成

2026-11-12 在独立目录物化 #6159 精确提交的 92 个原文件，逐个校验 Git blob SHA1 后再导入。复用已有 `test_ctrl_macro_study.prepared_fixture`、`test_macro_actor.fixture_deployment`；机械 checkpoint 只由上游构造标签生成，不计入真实训练／来源数／收益。原 `study.freeze → thaw → 独立进程 cold-load`、新入口 `freeze/load_native`、B/C 原 `macro_execution_plan.validate_plan/check_inputs` 全部通过，**actor 调用为 0**，没有 B/C START 或执行目录。

同一主 driver 下替换 `macro_policy.py` 或 `ctrl_macro_analysis.py`，新进程均在导入前拒绝且篡改脚本的导入标记未产生；原校验器另拒绝 sealed role、checkpoint context drift、retained-plan 字节变化及缺少 cold-load freshness。exclusive-create 保留已有文件与符号链接目标；JSON 输入拒绝符号链接。仅文件 fsync，不声称掉电后的目录持久性或并发敌对文件系统认证。10 项入口边界测试通过；这些均为机械验证。

后续真实 actor 所需源码集合是原 driver／analysis、`ndu_real_runtime` 与 `ndu_real_materials` 的全部非测试 Python 文件及 `experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py`。机械基线 freeze 是 82 项 inventory；后续真实 run-v1 是 83 项（82 项源码＋1 项 receipt），不能用固定数量替代逐项 pin。部署清单另含 driver／analysis／prepare，共 85 个源码文件；真实产物须按自身 FROZEN 验证，不能套用旧计数。必须连同原 `FROZEN/COLLECTION_PLAN/CHECKPOINT/CHECKPOINT_PIN/COLD_LOAD`、真实 weights/control/material 原件与原 Python 环境转交。机械集成机的 numpy/Pillow 足以运行上述校验；未安装 torch 的这次机械运行没有证明真实 actor 依赖或隔离器能力。

完整参考套件在本次最终 Python 源码上实际运行 **129/129 通过、0 跳过**（119 继承＋10 新增），unittest 用时 1.198 s，含进程启动的 wall 1.5757 s。随后 `just fmt` 退出 0，Python 源码字节未变；未在格式化后重复运行测试。`NATIVE_PERCEPTION_EVIDENCE.json` 保留原始日志、每个执行源文件 SHA256、92 文件上游 manifest、接口集成日志及复现脚本。载荷使用 zlib＋base64 无损归档，每项有原字节数与 SHA256；解码校验后才能引用。它记录的是本地原接口机械执行，真实 actor、科学效益与原 owner 决定仍为 0／未取得。

## 原 campaign 的后续状态与复用门

上表 #6159 的 `39763265...` 是本 wrapper 已执行机械集成的精确版本；新完整 campaign 使用已发布的 `3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd`，位于 `/home/qq/ctrl-real-policy-20261112-1333-v3`。只有新原件的 freeze/thaw、原 plan/checkpoint 校验及 wrapper 配对登记实际通过后，才能据此接通调用；源代码存在不等于该调用已经通过。
旧 run-v1 保留 126/126 pairs、UNKNOWN 0、完整 EXPORT 与 FIT_FAILED。归一化 producer 的真正修复来自上游 3c94；[#6221](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6221) 新增的是原始公开输入回归，未重复修改生产实现。新旧 converter/fitter pin 不同，禁止把旧 EXPORT 改 pin 后喂给新代码。
原 [v2 请求](evidence/rv-predeploy-20261112/campaign-bootstrap-pty-request-v2.json) 的 host=`ai395`、key=`ctrl-1333-real-campaign-pty-v2`；完整原请求对账返回 `reused=true`，原 session=`dpty-40ff97e76f70d0a5e1c37280afeab264b349cee40962d4e6b77d543fdb391c65`。输出目录为 `/home/qq/ctrl-real-study-20261112-1333/run-v2`；这是原身份读回，不是新采集。初次 session 读回超时不能判为执行失败。
后续原 `bootstrap-v2/campaign.log` 已记录 frozen collect／export／fit、content adaptation，以及 adapted collect／export／fit 和 factorial freeze 的 exit 0；最新完整读取快照末条为 factorial_evaluate STARTED。完整内容因子实验、终态评分与科学分析尚未闭合。这些执行属于上游 campaign；wrapper actor 仍为 0，来源数及成本不与它拼接。
新 frozen freeze SHA256=`7679b083343d6de9d7b3e1f1acc4f3252b044de36deafadb289ff532c7de7497`。11,489 B checkpoint 的实际文件 SHA256 与 CHECKPOINT_PIN／COLD_LOAD 一致：`c4ee4a0219117edeec6381b0bb01b896f9a182862298eba22d3c69a828c17096`；context=`2c5f3ca8bd208680ea54ffba80f0ab5d1d7c19c906f54779015c4588fe2b9058`。FIT 与 COLD-LOAD 的 START／COMPLETED 原件均已读回；export126/126、UNKNOWN0、fit72／cal54。两个 conditional 分组各9来源，unconditional18，`calibration.complete=false`；这不会因 fit 返回0而自动成为已校准、有效益或可采用的策略。
同一原 source 的 `ctrl_macro_factorial.py::reconcile` 将 `REPORT.json` 的 `decision` 硬编码为 `"NoUpdate"`，没有原 owner 签发。该原始研究标签必须留在原报告，统一台账仍为 `owner_decision=null`；不以报告字符串关闭 G4。当前运行的冻结源码／已受理请求保持不变，语义修正只能进入另一个明确版本。
原 bootstrap 的收尾语句误读 `run-v1/COMPLETED.json`，实际运行目录仍是 run-v2。保持已接收原请求不变；应先 reconcile run-v2 原阶段与产物，不能据 bootstrap 尾部报错重派。未来 launch 生成器应从同一 `campaign_output` 生成执行参数和 completion 路径，但这里没有修改原请求或启动任何新任务。
当前科学资格继续 HOLD／未完成，`adoption=NOT_REQUESTED`、`owner_decision=null`。精确阶段、原始字节／摘要与后续读回统一登记于 [NEXT_STEP_EVIDENCE.json](NEXT_STEP_EVIDENCE.json) 和 [BLOCKER_CLOSURE_NEXT.md](BLOCKER_CLOSURE_NEXT.md)。

最新 adapted 原件也已读取：其 CHECKPOINT_PIN／COLD_LOAD=`11e9e251d06ab46f12b0b16a8622a7a2c8d059943bdce763e1aa901df9471858`，context=`3d17b06cfd5df77ed383e7045048a4cd068102d662aadce1e7bb969be61d973b`；fit72／cal54，校准仍 incomplete、完整成本仍 unknown。factorial 冻结 pin=`f75c44d6092aa1a91af1db859823a7d1e20d9219016d00ce69b843ac5d462325`，计划 576 次执行。完整终态仍待读取，不将 START 或计划数写成完成数。
