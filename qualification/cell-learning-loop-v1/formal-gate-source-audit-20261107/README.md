# P1 正式采用来源审计 — 2026-11-07

**结论：`HOLD_FORMAL_P1`。** 本目录只新增审计记录，没有改变原源码、
工件、门槛或 owner，没有运行训练、模型 forward、采用或 desktop CUDA 操作。
[AUDIT.json](AUDIT.json) 保存机器可读事实、原件大小、SHA256、Git blob、
精确提交和来源链接。被审查组合源码为 `9bbf4bb4d1b5466f62d75d6b70dad4d26ec75d55`；
这份审计不转移历史测试资格给后续组合提交。

**用户已经广泛授权继续推进及追加研究。** 下文“余额为 0”描述已有冻结协议，
不表示用户没有追加研究授权。可以在既有授权下准备新的前瞻协议；它必须继承
历史总账、失败候选、任务暴露、保持条件和来源权限。新目录或新实验 ID 不能
重置这些事实，也不能补造缺失的正式门、自然 future 或历史计量。

## 三个门不能互相替代

| 门 | 实际预设／执行情况 | 当前缺口 |
| --- | --- | --- |
| 原 V13 的 48 题 calibration | 初始 floor 为 `ceil(0.8×48)=39`，实际 `41/48`；后续 floor 为 `max(39, 41−1)=40`。含原 project profile sources 时还要求实际执行 `6/6`。 | Cedar loop 没复制 calibration inputs，也没有执行此门。原 profile 条件不能由 Cedar 的两个请求替代。 |
| Cedar 原 publication callback | 训练前固定 `passed=False`，理由为没有登记独立九臂 future round，以及完整生命周期成本未知。 | 真实执行了拒绝，未执行正式 future gate；`59→55` 不是这个原 callback 的动态触发条件。 |
| 后置 72 题 decision replay | 规则为新任务严格改进且历史 aggregate 不下降；显式 `post_run_replay=true`、`prior_results_known=true`、`prospective_claim=false`。 | 父 `59/72`、候选 `55/72`，五退一进，quality veto。它是事后追加资格检查，不能倒写为原训练前动态门。 |

原 V13 provenance 的后两次候选分别 `39/48`、`38/48`，因未到 `40/48`
真实拒绝发布；前述来源、分母、条件和失败都应继续保留。后继研究不得降低原
calibration 条件或另行声明的 no-loss 条件，也不能只通过其中之一就称全部通过。

原件：[provenance_run.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/provenance_run.py)、
[原 provenance RESULTS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/evidence/provenance/RESULTS.json)、
[原 gate audit](../GATE_AUDIT.json)、
[replay 协议](../decision_replay/evidence/replay-20261106-001/PROTOCOL.json)、
[replay 结果](../decision_replay/RESULTS.json)。

## 正式九臂来源与 future 仍缺失

原 loop 引用 `V15 FutureAdoptionGate`，但其冻结执行包没有该实现；
被审查提交没有 `qualification/memory-cell-v15`。协议记载的 donor
`0abc3f5132c944d517e6a75d6d5362819fd285ec` 经 GitHub 文件 API 再核，
返回 `404 / No commit found for the ref`。本机限定路径清单搜索没有找到该 gate
或 V15 工作目录。记录保留查询范围与原错误；这不证明所有主机或未发布分支均不存在。

另一个真实 V15 分支 `f18d8299c8d445d68576e1c81368ecb981817e30` 的
[admission.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f18d8299c8d445d68576e1c81368ecb981817e30/qualification/memory-cell-v15/admission.py)
实现 `MatchedEvaluator`，并有
[cohort 检查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f18d8299c8d445d68576e1c81368ecb981817e30/qualification/memory-cell-v15/cohort.py)。
没有经核实的 source map 将它绑定到此处所称的正式九臂门；不能拿它替代。
精确 gate 源码、九臂 roster、冻结阈值、comparison/look 余额和登记 cohort
在机器记录中保持 `null`。

原运行的自然 future 来源组为 **0**。两个 Cedar authored held 请求由 `0/2`
变为 `2/2`，但父模型从未学习过 Cedar 任一版本，因而也不证明消除已学错误。
历史 72 题、原 calibration 及 Cedar 结果都已暴露：可用于历史保持或开发检查，
不能改名成为新的独立 future。来源为
[原协议](../evidence/run-20261106-001/PROTOCOL.json)和[原结果](../RESULTS.json)。

## 已有协议余额与实际来源前沿

原协议冻结 **1 次候选、16 updates、batch 20、lr 0.01**；实际已完成
**1 次、16 updates、288 presentations／124 rows**。本协议余额为 **0**。
replay 新增 updates 为 0。每个 worker 的 60 秒 deadline 不是新增训练预算，
父 step 240、候选 step 256 也不是历史研究总支出。

对归档 owner 以 `mode=ro&immutable=1` 查询，数据库 SHA256 仍为
`878aca2ad555ee8fe41b26ed1824751cb9c6e0e9b5f09c2b93f9c1e8064f45fb`，
没有产生 WAL/SHM。当前来源为 `skills=2`、`cedar-intake=2`；release 仍为父
artifact、epoch 1。父与已拒候选都依赖 `skills=1`，当前均不具来源新鲜性。
重新复制 revision 1 owner 或给旧权重改来源标签不能建立有效 successor。

候选冷执行属于 **unpublished shadow**；活跃冷请求用的是 skills 修订前的旧父。
尚没有“新候选正式发布 → 冷读当前 release → 下一真实任务”的证据。
精确 artifact、来源 body digest、source cut 和数据库绑定见 `AUDIT.json.owner`
及其原件引用。

## 已知成本必须保留，未知项不能补零

| 已知测量范围 | CPU 秒 | wall 秒 | 限定 |
| --- | ---: | ---: | --- |
| Cedar 两次完整 driver invocation | 7.730896 | 7.792046205002407 | 含准备、十个 workers、driver 和收尾 |
| 后置 decision replay | 3.099507 | 3.140813904999959 | 零训练更新，仍有实际计算 |
| 上两项已记录合计 | 10.830403 | 10.932860110002366 | 不是完整生命周期总成本 |
| 原 V13 provenance 五阶段 | 0.670666507 | 0.6928170920000412 | `5×240=1200` updates，包含后来拒绝的候选 |
| 原共享 feature preparation | 2.375312928 | 2.2946990359923802 | 独立共享准备账，不逐候选重复收费 |

同一父 artifact 的初始 provenance fit 为 240 updates、4,800 presentations、
`0.07970184599980712` 秒。原成本报告中的 `0.063814` 秒属于另一个 profiled
checkpoint，不能混用。机器记录保留五阶段逐项结果、训练消耗和实际来源链接。
这些范围不能盲目相加为研究 grand total；须核对区间、共享分摊和嵌套 envelope。

原结果中八项仍为 `null`：账单、能源、完整 retained byte-seconds、历史取得、
host network bytes、开发／审阅、p99、事后交付报告成本。历史全部搜索和取得
也没有一个完整合并账本。若原计量或外部账单无法找回，unknown 必须保留；
新的测量、零单价或新目录不会恢复过去的成本。

成本来源：[原 loop 结果](../RESULTS.json)、[replay 结果](../decision_replay/RESULTS.json)、
[原 provenance 结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/evidence/provenance/RESULTS.json)、
[独立 V13 成本审查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/evidence/AUDIT_COST.md)。

## 追加研究仍需解决的实现与证据

原 MiniLM、Python venv 和 donor checkout 的记录路径在本机均已不存在，
90,405,214 字节 ONNX 权重未打包进 loop。模型 SHA 和运行时版本仍可核对；
其他主机同 SHA 资产未在此次审查中验证，恢复的取得与准备成本须入账。

固定 Adapter 对 `A/B/W/b` 全部执行 Adam，没有抗遗忘或选择性更新开关。
原 loop 已混入 120 条旧样本和 4 条新样本，仍发生回退。追加方法需要新的
精确实现与完整状态绑定，包含额外 replay／teacher forwards 的实际消耗；
不能冒用原默认 reference 源码资格。

新的前瞻协议可以继续准备，但须继承上述总账与暴露记录，恢复精确正式门，
登记有可信时间与来源的独立自然 future，保留原保持条件，补齐可比完整成本，
并通过实际 owner 的 publication 和下一真实任务使用链。
无法恢复的历史证据继续阻断正式 full-cost 采用，不靠重新编号消除。

## 审计验证范围

归档时逐字核对 14 个本地引用与固定组合提交；重新计算 5 个远端原件的 Git blob，
均匹配 GitHub 返回的对象 ID；原 owner SHA 不变。`AUDIT.json` 可由标准库
JSON parser 读取。此次只交付本目录两个新文件，不重跑模型或原资格测试，
不修改采用策略，也不签发权限。
