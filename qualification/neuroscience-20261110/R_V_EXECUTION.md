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
旧 CTRL `runtime/NATIVE_DIAGNOSTIC.json` 记录 `host_alias=rog`，weights SHA256 `db6e3d05270163368d10176299a7d5be3ccee2d8e773fcfbb32454ff1c0f9f54`；绝对数据目录未公开。实际目录必须从原 `FROZEN.json` 的 `collection_plan.config.material_root`、`profile.weights` 读取并逐项验证，不能猜造。

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

先各取一个不同来源的、原 owner 已允许的 development B/C case，可形成 4 个实际 native 执行的调用连通 probe；这不新增来源资格，也不提供有效功效。已有同源 campaign 的运行身份先协调，不重跑整个六策略／内容因子实验。

```sh
python3 replay_perception_native.py freeze --request "$RV_REQUEST" --expected-sha256 "$RV_REQUEST_SHA256" --output "$RV_NEW_OUTPUT"
python3 replay_perception_native.py B --expected-sha256 "$RV_FREEZE_SHA256" --output "$RV_NEW_OUTPUT"
python3 replay_perception_native.py C --expected-sha256 "$RV_FREEZE_SHA256" --output "$RV_NEW_OUTPUT"
python3 replay_perception_native.py reconcile-B --expected-sha256 "$RV_FREEZE_SHA256" --output "$RV_NEW_OUTPUT"
```

`RV_FREEZE_SHA256` 是第一步输出的实际 pin；不重用请求 pin。输出目录必须位于所有 actor runtime roots 之外。故障后先读原件，不能自动换目录／新操作 ID 重试不确定执行。
原 actor 时延已包含初始化、选择、动作、评分与 admission；外层 wall／parent CPU 单列，不能与嵌套时延相加。provider、energy、完整进程树、历史训练／数据取得与摊销仍未知，始终 `full_cost_observed=false`。

## 未闭合项与本地机械验证

- **真实调用仍待运行：** 必须取得当前可访问的原训练目录／checkpoint／原允许来源；此文发布本身不代表 4 个 native actor 已执行。
- **R 2×2 仍 OPEN：** 尚无同一真实任务上的 episodic／skill replay 可用执行适配器，不能把 ACT controlled probe 与 MEM UNKNOWN 拼成配对效果。
- **同信息循环与 VERIFY 付费检查仍 OPEN：** 当前 native 宏只有 STOP／真实 READ，不提供任意同输入循环或独立 checker 的等预算接口；没有伪造“同信息”对照。
- **新来源 B/C 与原 owner 仍 OPEN：** 需要原来源登记／暴露证据和原有授权链，不接受自签名替代；现有 development 不重标 confirmation。
- **效益／采用仍 OPEN：** 强基线训练资格、完整成本、功效、顺序平衡、多重校正、旧能力以及原生选择／不同 C／冷恢复另验收。

本地测试使用构造数据验证边界；其中真子进程 `os._exit(9)` 后只有一次模拟 contact，重进程调用被 START 拦截。它验证一次执行机制，不是真实任务／真实模型／owner 结果。首轮有一个测试期望异常类型错误，随后修正断言；另覆盖等长替换来源／context、非法质量／负成本和 `1e999`；实现的拒绝条件未放宽。

### 已执行的原生接口机械集成

2026-11-12 在独立目录物化 #6159 精确提交的 92 个原文件，逐个校验 Git blob SHA1 后再导入。复用已有 `test_ctrl_macro_study.prepared_fixture`、`test_macro_actor.fixture_deployment`；机械 checkpoint 只由上游构造标签生成，不计入真实训练／来源数／收益。原 `study.freeze → thaw → 独立进程 cold-load`、新入口 `freeze/load_native`、B/C 原 `macro_execution_plan.validate_plan/check_inputs` 全部通过，**actor 调用为 0**，没有 B/C START 或执行目录。

同一主 driver 下替换 `macro_policy.py` 或 `ctrl_macro_analysis.py`，新进程均在导入前拒绝且篡改脚本的导入标记未产生；原校验器另拒绝 sealed role、checkpoint context drift、retained-plan 字节变化及缺少 cold-load freshness。exclusive-create 保留已有文件与符号链接目标；JSON 输入拒绝符号链接。仅文件 fsync，不声称掉电后的目录持久性或并发敌对文件系统认证。10 项入口边界测试通过；这些均为机械验证。

后续真实 actor 所需源码集合是原 driver／analysis、`ndu_real_runtime` 与 `ndu_real_materials` 的全部非测试 Python 文件及 `experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py`；原冻结 inventory 为 82 项，另加 driver／analysis 两个独立 pin。必须连同原 `FROZEN/COLLECTION_PLAN/CHECKPOINT/CHECKPOINT_PIN/COLD_LOAD`、真实 weights/control/material 原件与原 Python 环境转交。集成机的 numpy/Pillow 足以运行上述校验；没有安装 torch，也没有证明 actor 运行依赖、真实素材可达或隔离器能力已满足。

完整参考套件在本次最终 Python 源码上实际运行 **129/129 通过、0 跳过**（119 继承＋10 新增），unittest 用时 1.198 s，含进程启动的 wall 1.5757 s。随后 `just fmt` 退出 0，Python 源码字节未变；未在格式化后重复运行测试。`NATIVE_PERCEPTION_EVIDENCE.json` 保留原始日志、每个执行源文件 SHA256、92 文件上游 manifest、接口集成日志及复现脚本。载荷使用 zlib＋base64 无损归档，每项有原字节数与 SHA256；解码校验后才能引用。它记录的是本地原接口机械执行，真实 actor、科学效益与原 owner 决定仍为 0／未取得。
