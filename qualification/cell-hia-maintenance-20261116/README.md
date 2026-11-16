# MEM / PRED 固定协议原生 HIA 学习闭环：完整原件恢复运行

## 本次结论

2026-11-16 UTC，本地 Linux 上的实际 NumPy GRU、实际原生 HIA continuation 和同一 CellOwner SQLite 已完成固定的 A → 训练候选 → B 与 A 保留评价 → NoUpdate → C → 独立进程冷恢复。MEM 与 PRED 均按原规则得到 **NoUpdate**。本次没有采用新参数，不能据此宣称获得可保留的已采用收益。

这是生成 Python 语法维护任务的受控夹具，不是真实仓库任务资格，也不是普通 daemon 的 adoption 权限证明。本地运行没有经过真实 hepta-runtime process owner，因此 `runtime_pins` 为 null、`actual_runtime_transport` 为 false。父任务另行通过真实 runtime 入口执行的 campaign 必须保留自己的完整原件与实际传输协议；不能把本次本地结果替代那次运行。

## 固定协议与结果

A、B、C 各 8 个互不重名的程序，来自 4 个固定语法错误模板。B、C 只是程序名和常数不同，不能当作跨任务族或真实分布独立性。CPython 实际 compile 验证修复后的语法，没有执行程序，没有语义正确性或完整测试套件保证。

两 Cell 均使用 seed 7641、hidden_dim 4、Adam、学习率 0.003、16 次更新、3 事件序列。MEM 有 260 个参数；PRED 有 262 个参数，逐次评分 4 个动作。只用 A 的实际编译经验训练。B 和 A 保留评估后，只有候选严格超过 frozen、no_learning、deterministic 的 B 成功数，且 A 保留不少于 frozen，才可 Adopt。没有根据 B/C 调整参数或放宽规则。

| B 对照或后续阶段 | MEM | PRED |
| --- | ---: | ---: |
| Frozen | 2 / 8 | 2 / 8 |
| No learning | 2 / 8 | 2 / 8 |
| No memory | 2 / 8 | 2 / 8 |
| 训练后候选 | 6 / 8 | 2 / 8 |
| 确定性诊断规则 | 8 / 8 | 8 / 8 |
| A 保留：frozen → candidate | 2 → 6 / 8 | 2 → 2 / 8 |
| 决定 | NoUpdate | NoUpdate |
| C：实际选中的原模型 | 2 / 8 | 2 / 8 |
| 独立进程冷恢复后 logits | 与重启前完全相等 | 与重启前完全相等 |

MEM 候选在这个夹具上超过冻结模型，却未超过确定性规则；PRED 候选没有增加成功数。双方按既定 gate 完成 NoUpdate。C 执行的确为仍然生效的原模型：权重、优化器状态、wrapper identity、版本 manifest 与持久 owner 状态均经原件一致性检查。NoUpdate 完整结束证明这次流程守住既定规则，不证明学习优于普通 agent。

Frozen 与 no_learning 在第一轮中有意完全相同。no_memory 每个观测间重置 recurrent state，只是任务内记忆消融，不能作为不保留跨会话经验的对照。不同 Cell 及确定性规则的实际运算量没有强行匹配；记录逻辑工作量，而不宣称公平总算力实验。

## 实际调用、身份和恢复

全部 A/B/C、B 对照、A 保留评估及冷恢复 inference 均通过 HiaCellComponent。MEM 留下 265 条、PRED 留下 457 条原生 COMPLETE 记录，共 722 条；每条都有同一 owner 数据库中的原始 intent、内层 Cell 结果、HIA 返回、外层 receipt 和 state hash。没有未决 continuation。

每个原模型、训练候选、确定性 Cell 都有独立 manifest，共 6 份。manifest 绑定 PLAN、17 个实际加载模块的源码原字节、Python/NumPy/数值库身份、原生镜像和编译器记录、当前 model/config/kernel/head/optimizer/bundle。训练候选没有复用父版本身份。

冷恢复启动了新 Python 进程，加载同一选中 NPZ、owner checkpoint、原生 image 与 wrapper manifest，并生成新的 `cold-new-prediction` 请求。它验证最终 C 状态上的新 inference，不是新独立任务，也不是多轮长期能力试验。

## 完整成本记录及界限

| 度量 | 本次观测 |
| --- | ---: |
| 实际 CPython 编译调用 | 208 |
| 实际训练更新 | 16 + 16 = 32 |
| campaign 内部总 wall，包括 IO、所有对照与冷子进程 | 3.358155546 s |
| 外部启动到退出总 wall | 3.560103565 s |
| campaign 父进程 CPU | 1.773163332 s |
| 外部 wait4 汇总 child CPU | 4.786317000 s |
| MEM / PRED 训练 wall | 0.007646343 / 0.007632541 s |
| MEM / PRED 完整冷子进程 wall | 0.376702072 / 0.277187195 s |
| MEM / PRED 完整冷子进程 CPU | 1.088471 / 0.999279 s |
| MEM component-call p95 / p99 | 2.608308 / 3.959800 ms |
| PRED component-call p95 / p99 | 2.650845 / 3.696629 ms |
| MEM / PRED 累计 native wall | 12.155777 / 18.695295 ms |
| MEM / PRED 逻辑 parameter-work | 66852 / 117670 |
| 外部 Linux wait4 最大子进程 RSS | 63288 KiB |
| 共享镜像原构建 wall，单独计而未在本次重编 | 0.207677312 s |

component-call p95/p99 仅覆盖 component invocation，不包括 owner 入场/落账、编译或完整任务延迟。logical parameter-work 不是硬件 FLOPs。CPU 与 wall 不同，数值库线程可令 CPU 超过 wall。RSS 是 Linux wait4 的最大单个子进程高水位，不是同时存活进程内存总和。能耗、聚合峰值内存、硬件队列占用均未测量；没有用零替代缺测。

## 原件保留与独立只读检查

`PRE_RUN_FREEZE.json` 在任务执行前固定当前协议和源码；`run001/executed-source/` 保存执行模块原字节。`run001/native/` 保存完整 .so、HIA source、实际 loader 和 build record。`run001/memory/` 与 `run001/predictor/` 各含 parent/candidate/live NPZ、A 训练 NPZ、所有阶段 JSON、冷子进程原输出及 SQLite。`compile.jsonl` 保留每次输入源码、输出、诊断和成本。`RUN_PROCESS.json` 与 stdout/stderr 保留外部进程证据。

持久脚本 `scripts/verify_hepta_maintenance_cycle.py` 从这些原件检查固定协议、所有文件绑定、模型与优化器数组摘要、A-only 数据、B/保留 gate、实际选中版本、冷 PID/状态/logits、722 条 SQLite intent/receipt/native state 的逐条一致性。检查器不 import candidate，不调用 native，不训练，不重编夹具。其结果为 **READ_ONLY_CONSISTENCY_PASS**。它是原件一致性检查，不是独立任务复现实验或生产者真实性证明。

本次 runtime pins 新接口另用明确标注 synthetic 的纯元数据夹具验证精确复制、origin 保留及 5 类无效/重复字段拒绝；该验证没有训练或 native call，不产生运行时执行资格。

### 核心身份

- PLAN SHA256: `29cc56ef6adf1d6170c51def1d9201bff8a392e80f9831cc8eb91ddb89acccc7`
- RESULT SHA256: `2b9c15ef25e0ac9e5d1c7f64d557718e8bd0804b6e93886403edcadd26f79134`
- native image SHA256: `cbb27c677e12008afee0c8228570b5cc3cdc2a873e923e3062dd35c56eebc8eb`
- loader SHA256: `b65ad0be0f573dca5070b3e27d73abede1c1228e335d21c57d853855f1bc0c8b`
- hosted compiler commit: `f33d8da316de8fdf27b504371f1a5310997ff548`
- compiler implementation SHA256: `ce622f4e903a9ec410c30d0dd49ff2c32dfc12226b6327c049afe4db60a41a80`
- read-only verifier SHA256: `899723e758d8e89cb59c8fd25f7c734a1e39a829e49029f216a371a4d3527bd5`

## 旧原件丢失记录

先前 4 个 `/dev/shm` 运行目录在环境重启后消失，包含成功运行及失败尝试的原件，不能再重审。`PRIOR_EVIDENCE_LOSS.json` 将它们逐一标注 `previous_observed_raw_lost`、`originals_available=false`、`current_qualification_credit=false`。历史观测只来自之前工具输出和会话记录，未伪装成恢复原件。报告过的 677 次 compile、112 次训练更新、约 4.53981 秒 wall 仅作历史成本信息，不是当前可复核总账。

本次恢复运行保留相同模板、训练日程和负面结论，但它没有恢复已丢失的原始字节，也不能据此增加独立样本量。最终资格以当前保存完整的 raw bundle 为准。

## 复核方式

解压完整 evidence archive 后，从对应仓库调用：

```bash
python scripts/verify_hepta_maintenance_cycle.py /absolute/path/to/maintenance-recovery-001/run001
```

检查器只读检查归档内容；无需重新加载原生 image 或恢复模型运行。`FILE_MANIFEST.json` 逐文件列出原件 SHA256，压缩包额外摘要见同目录 `ARCHIVE.json`。实际重跑必须另建输出目录，以原固定 schedule 运行并完整保留任何失败尝试，不能覆盖本次证据。
