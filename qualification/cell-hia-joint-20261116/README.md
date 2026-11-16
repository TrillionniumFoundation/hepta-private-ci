# HIA / Cell 联合候选：阶段结果与下一关

实际 runtime 原件已读并复核，结论为 **限定 PASS：固定 operator runtime 下的真实 HIA / GRU 调用、原 job 冷重观测及受控维护夹具的完整 NoUpdate 闭环**。源码、build、runtime pins、三组协议和 campaign 原件的关系见 [GATES.json](GATES.json)及[实际 runtime 结果](ACTUAL_RUNTIME_RESULT.json)。**六项科研目标尚未全部完成；没有普通 daemon、FinalUse 或已采用学习收益资格。** 修复后的 GitHub Actions 重跑为 `pending_at_publication`，不能以本次实际 lane 的 PASS 替代 CI 通过。

## 1. 固定身份与证据范围

| 对象 | 固定选择 |
| --- | --- |
| 实际执行的 Cell 源码 head | `12cd0514c7936955e090af88a35ee1237def2b7c` |
| HIA bridge 源码 | `8ba46fc7a112fc220cdcbbd48dc5d24fda76a738` |
| Hosted HIA compiler | `f33d8da316de8fdf27b504371f1a5310997ff548` |
| Runtime 源码 | `5f7f03a1f22905789371ce0e181a1a0f013beca9` |
| Native image SHA256 | `cbb27c677e12008afee0c8228570b5cc3cdc2a873e923e3062dd35c56eebc8eb` |
| 选定本地集成候选：final-joint-004 | `3efd003d699eeb0333601e714b450fc0590f29cfe013ff8ae3f62b2b32d3665b` |
| 实际 runtime 派生候选 | `2a8e8759c7e1941f184fde2463a13a9d39dfa9edcf00c8a5ae475ad81dd3b469` |
| Runtime source tree | `7e5e3864aa303a8bc7c3a8d2262a46c76efa6e4a` |
| 实际 Mac runtime binary SHA256 | `a8cfa33fe6c69175a9653197fb7094a572d623fe2b934e7926da28e35301f2bf` |
| 实际 runtime config SHA256 | `96eaab9f5b76aef9ac5fcac6b32ca1be663e7a0d55e999dad89899c35317f9e5` |

004 manifest 保留原 Cell 基线 `bb34e073…`；新增及改动源码由完整文件 SHA256 清单绑定，共 243 项。实际执行 head 与历史基线含义不同；最终证据发布 head 还将包含后处理、复核及文档，不能替代执行源码身份。每次更改源码、设备、runtime 或模型，都必须产生明确的新候选身份，并保存来源关系。

证据按下列执行分别成立，不能拼成同一次通过：

- **final-joint-004**：16 项本地真实 native HIA / GRU / 故障恢复检查。模型为 input=3、hidden=4、seed=41；不证明学习收益或真实 runtime。
- **final-controls-v2**：48 项 lifecycle 与受限 process-bridge 控制测试通过；不是实际 runtime 的替代物。
- **maintenance-recovery-001/run001**：本地生成语法维护任务的 A/B/C 学习实验，input=13、hidden=4、seed=7641。17 个执行模块与 004 的对应源码摘要全部一致，但模型、数据、PLAN 和候选身份不同。原件及独立只读复核见[维护实验报告](../cell-hia-maintenance-20261116/README.md)和[完整压缩原件](../cell-hia-maintenance-20261116/raw-evidence.tar.gz)。
- **实际 runtime lane：限定 PASS，原件已读**。Mac arm64 controller 运行上述实编 runtime，经既有 operator 账户在 `ai395` 执行 observe、predict、完整 campaign，共 **3 个实际 job、3 次 process_start**。每个 job 随后由新 controller 进程只调用原 job 的 status/read，**3 次冷重观测均无第二次 start，stdout 原始字节相同**。实际候选的 origin 指向 004；campaign 六份每版本 manifest 绑定同一 runtime source tree/binary/config 和 `2a8e8759…` origin。17 个执行模块及三个 controller helper 与 `12cd0514…` 对应源码一致，执行 closure 未改。

实际原件根为 `runtime-bridge/evidence/actual-runtime-v4`；可下载[controller 原件](actual-runtime-v4-controller-evidence.tar.gz)和[worker 原件](actual-runtime-v4-worker-evidence.tar.gz)。[候选](ACTUAL_RUNTIME_CANDIDATE.json)、[build](ACTUAL_RUNTIME_BUILD.json)、[pins](ACTUAL_RUNTIME_PINS.json)与 [controller helper 源码凭据](RUNTIME_HELPER_SOURCE_RECEIPTS.json)均单独保留。`OUTER_CANDIDATE.json` 保存精确候选原字节；`ORIGINAL_BUILD.json → RELOCATED_BUILD.json → campaign/native/build.json` 摘要链完整，路径重定位未改变 source/compiler/image 身份。

[外层原始记录独立复核](RUNTIME_RECORD_REVIEW.json)为 **READ_ONLY_RECORD_REVIEW_PASS**：321 个原件前后未变，六次 MCP 会话的实际参数、原 job、完整终态和输出字节一致，三个 helper 独立匹配 GitHub 的固定源码。该复核只读取保留记录，不重新执行模型、native 或 runtime；runtime binary 本体未装入证据包，其摘要对应构建 receipt 与 pins。

remote SQL 只读计数留下两个 0B WAL，旧 verifier 的首次拒绝与原件均保留。新增独立后处理直接复核真实原件，[RUNTIME_CAMPAIGN_REVIEW.json](RUNTIME_CAMPAIGN_REVIEW.json) 为 **READ_ONLY_SNAPSHOT_CONSISTENCY_PASS**：61 个文件精确复制，仅省略两个指定的严格空 WAL，SHM 保留，source 与 snapshot 前后不变，再由未修改的旧 verifier 复核 722 条记录。后处理自身不证明 transport；transport 结论来自原始实际 MCP 协议，没有用旧 local 报告替代 remote evidence。

独立外层[原件复核](RUNTIME_RECORD_REVIEW.json)为 **READ_ONLY_RECORD_REVIEW_PASS**：321 个原文件前后不变，六份 first/cold session 与原始记录逐项一致，三个 controller helper 的 GitHub 源码摘要匹配 `12cd0514…`。[已知秘密模式扫描](RUNTIME_SECRET_SCAN.json)在两个待发布原件包中命中 0 项；该结论仅限所列字节模式。外层复核没有重新执行模型、native、runtime 或打开 SQLite，也不扩大原执行的资格范围；[复核器源码](verify_runtime_records.py)随原件保留。

**final-joint-003 是后续 operator 配置校正前的 superseded 本地候选。** 它的原件作为历史保留，不为 004 补测试、不与 004 合并成本，也不为真实 runtime 提供通过资格。

## 2. 六项工作的真实状态

| 工作项 | 已有可观察内容 | 尚待证明 |
| --- | --- | --- |
| P0 共同最小系统 | 来源图固定 source/compiler/image/device/runtime binary/config、各版本模型、数据与 PLAN；实际 worker/campaign 原件链一致 | 修复后 CI 重跑；新任务与新版本须重新冻结，不继承本次资格 |
| P0 真实 Cell—HIA 桥 | 实际 operator runtime → worker → native HIA → GRU、持久 intent/result、三次原 job 冷重观测；004 另含故障检查 | 普通 daemon、FinalUse 与真实业务效果边界；不同故障 lane 不拼成一次执行 |
| P0 MEM/PRED 学习闭环 | 实际 runtime 内固定 A → 训练 → B/保留评价 → 两次完整 NoUpdate → C → 模型冷恢复 | 已采用后的新任务收益；跨多轮任务、重启的保留收益 |
| P1 三类更新进入同一 runtime | 参数候选及 NoUpdate；局部 compatible readout 迁移、旧版本 fencing 控制 | 代码优化实际采用与完整成本下降；三类更新在同一 runtime 的完整实例 |
| P1 长期可塑性与分化比较 | 当前只有短程、固定模板的局部控制 | 容量、数据、推理、训练和评价机会受控的长期比较 |
| P1 完整成本与恢复 | 部分 wall/CPU/RSS、训练、compile、冷恢复、调用分位数、unknown 记录 | 能耗、聚合峰值内存、队列占用、切换/迁移总成本、真实业务效果与长期总账 |

### 学习结果与限制

下表取自实际 runtime campaign 原件；计数与本地夹具相同，但两次执行分别保留版本身份与成本，不增加独立真实分布样本量。

| B 或后续阶段 | MEM | PRED |
| --- | ---: | ---: |
| Frozen / no_learning / no_memory，各自 | 2/8 | 2/8 |
| 训练候选 | 6/8 | 2/8 |
| 确定性诊断规则 | 8/8 | 8/8 |
| A 保留：frozen → candidate | 2 → 6/8 | 2 → 2/8 |
| 决定 | NoUpdate | NoUpdate |
| C：实际选中的原模型 | 2/8 | 2/8 |
| 新进程冷恢复后的预测 | 与重启前相同 | 与重启前相同 |

训练始终为每 Cell 16 步 Adam、学习率 0.003。只有 B 严格超过 frozen、no_learning 和确定性规则，且 A 保留不退步，才允许 Adopt。实际 campaign 的 2/2 NoUpdate 表示流程按规则完整结束，**不是两次已采用收益**；候选 MEM 的改善也没有超过简单确定性规则。此 fixture 的确定性规则已达到 8/8，而门槛要求 strictly 超过，所以任何候选都无法在此 fixture 获得收益 adoption 资格。**本次不放宽门槛；下一收益实验必须在查看 B/C 前预注册有区分力的真实任务与完整成本标准。**

A/B/C 各 8 个程序来自相同 4 种语法模板，仅名称、常数分开；B/C 不是独立真实任务分布。成功只表示实际 CPython compile 通过，不表示程序语义或仓库测试通过。Frozen 与 no_learning 在本轮有意相同；no_memory 是观测之间重置隐状态的**任务内**消融，不是跨会话经验消融。实际 runtime campaign 的 722 条 native continuation 完成、该 campaign 无未决请求，不能推广为所有故障夹具均无未决。

### 权限、迁移和故障界限

实际 runtime 路径使用管理员配置的 **operator process owner**。它不等价于 Rust `FinalUse` capability 边界；`ordinary_daemon_adoption=false`、`final_use_capability_boundary_qualified=false`。

状态迁移只适用于**同一 SQLite owner、同一 partition、无 pending intent、纯组件、确切当前 checkpoint**。TemporalComponent 还要求相同 Cell/config/episode/recurrent kernel；compatible readout 版本可保留 hidden state/cursor，旧版本只能精确重放既有 receipt。它不是任意 Cell 拆分、跨 owner 迁移或在途外部效果转移。

004 原件中 `owner.sqlite` 有 6 条 committed，`reply-loss.sqlite` 有 1 条 committed；`hard-death.sqlite` 和 `unknown.sqlite` 各保留 1 条 pending。后者是故障夹具的预期保守状态：取消不冒充完成，unknown 不自动重放；进程硬退出后缺失的原始成本不伪造，预算保留。不能宣称“全系统零未决”或已验证所有业务效果恰好一次。

代码优化尚未采用；先前相关原件已丢失，不计作当前速度收益证据。此前丢失的学习记录亦仅列为 `previous_observed_raw_lost`，不增加当前独立样本量或通过次数。

## 3. 完整成本：已知与缺测

这些是不同执行的观测，不能直接相加或作同条件速度比较。

| 度量 | 004 本地集成 | 本地 maintenance | 实际 runtime |
| --- | ---: | ---: | --- |
| 记录的运行窗口 wall | 4.236000388 s | campaign 3.358155546 s；含启动 3.560103565 s | lane 9.056936291 s；campaign 2.322323980 s |
| 父进程 CPU | 0.563164592 s | 1.773163332 s | campaign 0.892213877 s；完整 lane CPU 未测 |
| child CPU | 3.770918 s | 外部 wait4 4.786317 s | 两个冷子进程 0.130503 / 0.110914 s；非全部 child 总账 |
| 最大单个 child RSS | 34,792 KiB | 63,288 KiB | 未测 |
| Native compile wall | 0.210931281 s，本次构建 | 0.207677312 s，先前共享构建，单列不重复算 | 复用 004 镜像；原构建 0.210931281 s，未重复编译 |
| Mac runtime cargo build | 不适用 | 不适用 | 157.996383792 s，另计，不含在 lane 中 |
| 实际任务 compile / 更新 | 不作学习评价 | 208 次 compile；16+16 次训练更新 | 208 次 compile；16+16 次训练更新 |
| MEM / PRED 训练 wall | 不适用 | 0.007646343 / 0.007632541 s | 0.004635057 / 0.004767721 s |
| 模型冷子进程延迟 | 10 样本 p95=p99=256.089617 ms | MEM 376.702072 ms；PRED 277.187195 ms | MEM 135.445277 ms；PRED 114.144259 ms |
| Component invocation p95 / p99 | 未按此口径汇总 | MEM 2.608308 / 3.959800 ms；PRED 2.650845 / 3.696629 ms | MEM 2.080050 / 2.437473 ms；PRED 2.085640 / 2.450933 ms |
| 逻辑 parameter-work | 非硬件 FLOPs | MEM 66,852；PRED 117,670 | MEM 66,852；PRED 117,670 |
| 能耗、聚合峰值内存、硬件队列 | 未测 | 未测 | 未测 |
| 切换、迁移完整成本 | 未形成成本资格 | 本次 NoUpdate，无实际参数切换样本 | NoUpdate，无实际参数采用或迁移样本 |
| 丢失/重复的真实业务效果 | 未做业务级资格 | 仅 compile 夹具 | 三个原 job 冷结果一致；非任意业务效果资格 |

004 的分位数是 10 个样本的 nearest-rank；maintenance 分位数只覆盖 component invocation，排除 owner 入场/落账及任务 compile。RSS 不是多进程同时内存之和；CPU 不是 wall；parameter-work 不是实际 FLOPs。004 线程配置全部固定为 1，本地 maintenance 的三个数值线程变量为未设置。实际 worker 是 Linux x86_64 / Python 3.14.4 / NumPy 2.3.5，五个数值线程变量（`MKL_NUM_THREADS`、`NUMEXPR_NUM_THREADS`、`OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`VECLIB_MAXIMUM_THREADS`）均为 1；本地 Python 是 3.12.14，不能把不同 lane 的 wall 差当作同预算结构速度收益。48 项控制测试另有 0.971092182 s 外层 wall。9.056936291 s 不含 runtime 构建、依赖准备或先前失败尝试，尚非项目完整总成本；实际原件后处理另耗 0.393664806 s，不含训练或 native 执行。

## 4. 复核与重现

依赖版本、设备与线程变量按原 candidate / PLAN 复核。原件只读检查不要求重新运行模型：

```bash
python -B scripts/verify_hepta_maintenance_cycle.py /absolute/path/to/maintenance-recovery-001/run001

# 实际 remote 原件可能保留严格空 WAL；仅在只读副本上交给原 verifier。
python -B scripts/review_hepta_maintenance_snapshot.py /absolute/path/to/actual-runtime-v4/worker/lane-v4-state/maintenance/campaign --snapshot-dir /absolute/path/to/new-readonly-snapshot --output /absolute/path/to/new-review.json
```

以下命令创建**新的**实验目录；保留所有失败，不覆盖原件。不同路径、设备或配置会产生新的 manifest，不能直接继承旧资格。

```bash
CELL_ROOT=/absolute/path/to/hepta-private-ci
HIA_ROOT=/absolute/path/to/Hepta
EVIDENCE_ROOT=/absolute/path/to/new-evidence
export PYTHONPATH="$CELL_ROOT/scripts"

python -B -m unittest -v test_hepta_cells_owner_control test_hepta_cells_lifecycle test_hepta_cells_temporal_component test_hepta_cells_population_owner test_runtime_process_bridge
python -B "$CELL_ROOT/scripts/qualify_hia_cell_joint.py" --hia-root "$HIA_ROOT" --output "$EVIDENCE_ROOT/local-joint"
python -B -m hepta_cells.maintenance_cycle "$EVIDENCE_ROOT/maintenance" --native-build-record "$EVIDENCE_ROOT/local-joint/native/build.json"
python -B "$CELL_ROOT/scripts/verify_hepta_maintenance_cycle.py" "$EVIDENCE_ROOT/maintenance"
```

实际 runtime 的 Linux CI 复现入口是 [cell-hia-joint workflow](../../.github/workflows/cell-hia-joint.yml)，当前是修复后待重跑，并非已通过的 CI。它以 `cargo +1.95.0 build --locked --all-features --release --bin hepta-runtime` 构建并保留日志与 binary SHA，再运行 `qualify_runtime_process_bridge.py ... --allow-disposable-sshd --with-maintenance`，最后由独立空 WAL 后处理检查该 runtime campaign 自己的原件。该 qualifier 仅允许真实一次性 GitHub Actions runner；不能伪造 `GITHUB_ACTIONS` 来绕过环境约束。真实 worker 成功、controller 新进程重观测以及 worker 内模型冷恢复是不同检查，应分别保留。

### CI 与发布状态

[初次 Actions run 43797077251](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43797077251) 为 **failure**：native control unittest 缺少显式 HIA `PYTHONPATH`，无法导入 `tools`，其后 runtime 构建、执行及学习资格步骤均 skipped，不计通过；[原始 CI 记录](CI_RUN_43797077251.json)保留。workflow 已修复 HIA 工作目录/import path，并将空 WAL 情形改为独立只读后处理。修复后完整重跑在发布时为 **`pending_at_publication`**，不得填写假 PASS。

另据 `2026-11-16T03:44:45Z` 的[Runtime / HIA CI 快照](CI_FOLLOWUP_RUNTIME132_HIA902.md)及[原始记录](CI_FOLLOWUP_RUNTIME132_HIA902.json)，Runtime #132 和 HIA #902 均为 **PENDING**，当时没有观察到失败步骤；HIA source 单个 job 的 success 不代表 native job 或整个 workflow 已通过。此时间点快照不能替代后续终态。

关联 PR：[Hepta #902](https://github.com/TrillionniumFoundation/Hepta/pull/902)、[Cell #6399](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6399)、[Cell #6400](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6400)、[Runtime #132](https://github.com/TrillionniumFoundation/hepta-runtime/pull/132)。PR 存在、实际 lane 的限定 PASS 与 CI 通过是三个不同状态。

## 5. 下一关：固定预算比较的必要条件

1. 冻结同一候选图：源码、compiler、runtime binary/config、设备/数值库、模型、数据、plan、父子版本身份；实际 runtime protocol 必须与这些 pins 匹配。
2. 在查看 B/C 前预注册有区分力的真实、可重放长期维护任务族及完整成本标准，固定互不泄漏的 A/B/C 与旧能力集合、环境变化和重启/故障时点；B/C 不用于调参或重新选 gate，本次门槛不放宽。
3. 至少具备普通工具 agent、相同 Cell 关闭学习、允许学习固定拓扑、不保留跨会话经验、确定性监督调度、完整候选加重启故障的对照。另按原六项要求比较 head、局部拓扑、时序核；每个比较须事先控制总模型容量、数据、推理/训练预算与评价机会。
4. 把候选失败、NoUpdate、训练、验证、编译、后台推理、切换、迁移、恢复和重复尝试全部计费；事先定义 wall/CPU/内存/能耗/队列和业务效果的采集口径、上限与缺测处理。
5. 先闭合三个小实例：输出保持且完整成本下降的代码采用；独立 B 通过后实际 Adopt、C 改善且旧能力保留的参数更新；有明确状态关系和 custody 条件的迁移。每项均需同一 runtime 中的新原件。
6. 在多轮任务、环境变化和冷重启后保留已采用收益，再评估统计不确定性与完整成本。两次短夹具 NoUpdate 不能替代这一关。

以上条件完成前，结论限于已保存原件所支持的局部工程行为，不声称已超出普通 agent 的组织方式、已取得新的长期能力或完成全部科研目标。
