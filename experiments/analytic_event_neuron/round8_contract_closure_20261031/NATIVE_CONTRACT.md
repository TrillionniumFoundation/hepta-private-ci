# R7 有限状态模型的真实 Rust 部署、恢复与成本

本轮把冻结内容编码器、状态传播、采样和已学习 Q 头实际放入 Rust 的 `NeuronModelPort::execute`，再由仓库原有 `NeuronRuntime` 执行 sparse tick、journal 和独立 witness。Python `NativePolicy` 仅发送公开 `State`、接收原生选出的动作；原版 R7 `BrokerClient/ArtifactWorker` 执行真正的 READ、WAIT、REPAIR、STOP、文件读取、修复和终端产物读回。这已经超出 R7 历史 `native_bridge.py` 的数值输入桥接范围。

部署的数值合同是 **`r7-finite-v1`**。它不是连续 OU 首达的精度认证，也不包含本轮独立研究的 Brownian 新核。生产 authority 保持 `DENY_ALL`，没有修改或激活生产 neuron。

## 1. 被部署的模型与运算顺序

- 四种模型：`direct`、`continuous`、`clocked`、`first_passage`；部署方式为 `mean` 和 `hard`。两个已训练 Q 头均可选择。
- 完整内容网络为 18 维公开输入 → hidden → 8 维内容；drive 为 `1.5*tanh`。readout 在每个潜态的 `[E[X], E[X²], refractory_plus, refractory_minus]` 上分别计算非线性 Q，再对状态概率求平均。不能先平均潜态再运行非线性 head。
- 原 R7 JSON 无 schema，严格按 R7 张量集合读取。`round8-fixed-cell-calibrator-v1` 必须另外包含完整四个 `kernel_content.*` 张量；它们产生冻结 propagation drive，`content.*` 则用于可更新的 readout content。缺失或额外张量、未知 schema、显式不兼容 `kernel_version` 均拒绝。
- Gaussian OU 使用 `expm1` 和 libm `erfc`。区间落在正尾时用尾概率之差，避免 `1+erf` 和近 1 CDF 相减造成的取消。它保留 R7 的概率模型，但极尾结果不保证与旧 `torch.ndtr` 的舍入位相同。
- `continuous` 仍是把整条 Gaussian 质量折叠到有限网格两端的 R7 模型，不是无界 Gaussian 状态。`clocked` 在 tick 端点结算越界。`first_passage` 用同一上风有限 CTMC 的 uniformization 和 scaling/squaring 求吸收转移，不能借此声称粗网格已经等于连续 OU。
- 每次决定严格推进一个原 R7 模型 tick。新事件保持到当前 tick 结束；tick 开始时已在不应期的质量仅在当前 tick 末按固定恢复概率释放，不能在同一 tick 再发放。这不是物理时间指数恢复合同。
- `hard` 使用与 R7 相同的 `SHA256(round7/policy/v1/seed/calls/latent)` 随机键。checkpoint 保留 seed、calls 和完整 one-hot 状态；`mean` 保留 N+2 概率质量。运行中不从 Python 接收外算 transition、latent draw 或动作。
- 四动作占原 sparse 输出的前四个通道，第五通道固定为零。原 `SparseConfig` 要求 `top_k <= width/5`，因此不能用四通道、top-k=1 绕过原校验。原生信号必须逐项等于已选动作的 Q24 one-hot 加零通道。

网格、reset 分布和状态 readout basis 在模型加载时构造并保留；零质量潜态跳过 readout。这些成本缩减不更改概率合同。当前原生内核仍有分配和持久化开销，不把它描述为硬件最优实现。

## 2. 实际恢复边界

`pair.json` 绑定 source digest、模型完整字节 SHA256、kernel version、head、deployment、seed、calls、质量向量、native checkpoint 和最近公开任务状态 digest。恢复要求调用方提供此前收到的完整 pair digest，并核对真实 journal/witness 的 sequence 和 checkpoint。

owner 持有独占文件锁。非法请求或旧 ACK 在 dispatch 前拒绝，不能消耗状态、随机键或 journal。发生 native commit 之后而 paired checkpoint 未完成的情形，owner 被标为 poisoned；后续启动发现 pending 或 native/policy frontier 不一致时拒绝恢复。代码不会猜测效果结果或重新发送未知 READ。

**合格范围是已确认的策略决定边界，且原 broker 进程继续存活。** 这次没有把 broker 的完整业务状态、未完成外部效果或任意崩溃原子事务迁进 Rust checkpoint。资格实验真实停止并重新启动 native 子进程，保留同一个实际 broker，再继续读取。单独创建但尚未完成第一次动作的 owner 也不被认定为可重放的已确认边界。

原生信号的 `abstain` 如实记录原 runtime profile 的输出；它没有被标定为任务成功概率，也不改变 `DENY_ALL` 权限。

## 3. 已完成的资格证据

最终编译为 `evidence/native_build/BUILD_ATTEMPT03.json`。最终测试是 **`NEXTEST_FINAL.json`**，其 metadata 指向 `native-r7-build03/r7-native-policy-tests`；`FINAL_READBACK.json` 再次核验路径、实际测试二进制 SHA、build receipt 和当前源码。较早 `NEXTEST_ATTEMPT03.json` 属于开发 build02，完整保留，不能代替最终 receipt。

| 核验 | 实际结果 |
| --- | --- |
| 原仓库 `just test` → nextest | 4/4 Rust 测试通过 |
| 冻结候选 | 20 个原 R7 + 20 个 readout 校准 + 20 个 content/readout 校准 |
| 配对资格 cases | 240 组，共 480 次真实 broker 执行 |
| native 子进程 | 705 个 |
| 成对轨迹逐项相等 | 240/240，含原 native checkpoint 和 pair digest |
| 真正冷恢复 | 225/225；其余 15 组首个动作即 STOP，没有伪计为重启 |
| 最大 Rust/PyTorch Q 误差 | 9.4369e−15 |
| 最大质量和 moments 误差 | 6.8834e−15 |
| 最大期望事件数误差 | 5.5512e−15 |
| 实际终端产物独立读回 | 两侧全部通过，240 对 / 480 次 |
| 身份与恢复拒绝检查 | 11/11：旧 ACK、并发 owner、seed/head/model、篡改 pair、pending、schema/kernel/tensor/encoder 不兼容 |

详细记录为 `evidence/native_validation01/REPORT.json`、`REGISTERED.json`、`RAW.jsonl.gz`、`guards/REPORT.json`，以及每个真实 owner/broker 的原始文件。pending 检查是明确的 partial-publication fixture；没有伪称它是 SIGKILL 实验。

保留了开发反例：build01 把四动作直接映射成 width=4 后被原 SparseConfig 拒绝；其后使用第五零通道修正。初次 nextest reuse 缺少隔离 workspace manifest，也保留了失败命令和后续修复。没有替换样本、忽略失败或重选训练权重。

## 4. 先定位真实成本，再实测改进

`native_cost01` 在完全相同的 240 个固定候选/任务上移除了资格审计中的 PyTorch oracle，直接测量 NativePolicy、Rust、原 broker 的完整执行；包含每个任务的实际文件生成、启动、读取、修复、STOP 和产物独立读回。48 行聚合按 mode × stage × deployment × restart 给出。

这些是共享 CPU 环境下每行五个冻结 fit 的描述性测量。以不重启的整段执行为例，native 子进程通常为 3.1–4.9 ms CPU，而每个任务重新创建 Python broker 约消耗 86–102 ms CPU。owner 的 wall 时间约 4.2–9.2 ms，其中模型内运算通常只有：direct 10–25 µs、Gaussian 50–98 µs、first-passage 336–515 µs。启动和 journal/paired 提交占主要部分，不能把事件更少等同于实际 CPU 更少。

随后只做一个有针对性的改动：使用 **一个原版 BrokerClient 进程**，在上一个任务终止后调用既有 `start` 接口开始下一个任务。仍然按原 240 项顺序执行相同 public world、相同 frozen model、相同 native 冷重启标志；每个任务的 native owner 仍独立，没有把模型/业务状态串入下一任务。

| 口径 | 每任务新建 broker | 顺序复用一个 broker | 实测变化 |
| --- | ---: | ---: | ---: |
| 实际部署阶段 parent+native+broker CPU | 24.389180 s | 1.752554 s | −92.814% |
| 实际部署阶段 wall | 26.909963 s | 2.973717 s | −88.949% |
| 含 driver 导入、读回、检查、证据序列化的 campaign CPU | 25.833095 s | 3.029266 s | −88.274% |
| broker 进程 | 240 | 1 | 复用既有 owner |
| native 进程 | 345 | 345 | 保持原任务/冷恢复合同 |
| action、完整 final_state、终端产物内容和 SHA256 | 基线 | 240/240 逐项相等 | 无质量、预算或收费变化 |

首次真实任务承担了 68.564 ms 的 broker 启动等待，最终 close 也计入总账；没有丢弃 warmup。复用后的实际 native CPU 为 0.953384 s、broker CPU 为 0.392258 s、parent 部署 CPU 为 0.406912 s。broker CPU 由子进程结束后的真实 rusage 取得，并完整收一次，没有任意分摊为每个 episode 的虚假精确值。

这是 **进程生命周期优化** 的实测结果，收益来自避免 239 次 Python broker 启动。内核、权重、动作数、事件合同和读取结果保持不变。这一结果不证明解析 cell 优于 direct，也不是能耗读数。

### 成本字段如何相加

`encode / cdf_transition / ctmc_transition / propagate / sample / readout` 是模型内部互不重叠的 wall 纳秒。direct 的 identity transition 单独列出，不冒称 CDF 调用。`native_runtime` 包含这些模型阶段，余项包含原 sparse tick、validation、序列化与 journal IO；不能把余项全部称为纯 commit CPU。`complete_owner` 又包含 runtime 和 paired persistence。

`transport_serialization_scheduling` 是 request roundtrip 减 owner 时间，包含 JSON 与调度；startup roundtrip 包含 model load、owner open/recovery 和握手。broker source IO、terminal IO 和完整 broker roundtrip 也有包含关系。完整 CPU 由真实 parent/child rusage 计算，**不要把重叠的 wall 列相加当作 CPU**。资格审计的 parent CPU 包含 PyTorch comparator，实际成本表已另行排除它。

## 5. 来源、编译和复现

- 编译器：Rust **1.95.0**，`59807616e`，LLVM 22.1.2，edition 2024，opt-level=2，去掉 debug 信息。
- 原 Hepta source identity：`732e934ba496d90fbe042b8d41d479ef901643e5`，60 个源码/manifest 逐 Git blob 验证，见 `UPSTREAM_IDENTITY.json`。
- 依赖：serde / serde_core / serde_derive **1.0.229**；serde_json **1.0.151**，启用 `float_roundtrip`；libc **0.2.186**；sha2 **0.10.9**。serde_json 的 float roundtrip 对 cold state 位级保持有直接作用。
- 本轮是明确的 **cached-artifact rustc build**。全部新 application Rust 源码在本轮编译，链接已存在的原 Hepta/registry 静态库；所有依赖 artifact 的 SHA 和实际命令均记录。未在本轮重新从 registry archive 构建依赖，不能称为 fresh Cargo build 或供应链重认证。没有导入其他并行任务未提交的 native-loop application 实现。
- 最终可执行文件 SHA256：`185b4071bc8b60097eb3ca089054f4a5bb814417c8f78a82273c0456ec8d2830`。
- 最终 Rust/source/dependency 组合 digest：`42ac9dbfb0e01f78a857baf179d51c9946e4ce829447fc08e3ea9e07b814ea35`。

`native/build.py` 拒绝覆盖已有输出并保存 compiler、命令、依赖和 source receipt。`native/workflow.py` 在隔离副本使用原仓库 `just fmt` 和 `just test`，不会修改生产 Cargo/Bazel manifest；nextest 使用显式标识的 rustc 测试 binary。可用以下入口重建或复核，所有输出目录都应取新路径：

```bash
python experiments/analytic_event_neuron/round8_contract_closure_20261031/native/build.py \
  --output /tmp/r7-native-new-build --report /tmp/r7-native-new-build.json \
  --upstream /path/to/verified-hepta \
  --upstream-identity experiments/analytic_event_neuron/round8_contract_closure_20261031/evidence/native_build/UPSTREAM_IDENTITY.json \
  --dependencies /path/to/identified/target/debug/deps --toolchain /path/to/rust-1.95.0

python experiments/analytic_event_neuron/round8_contract_closure_20261031/native/workflow.py test \
  --output /tmp/r7-native-new-tests --report /tmp/r7-native-new-tests.json \
  --build-report /tmp/r7-native-new-build.json \
  --toolchain /path/to/rust-1.95.0 --tools /path/to/just-and-nextest

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.native_validation \
  --binary /tmp/r7-native-new-build/r7-native-policy \
  --build-report /tmp/r7-native-new-build.json --output /tmp/r7-native-new-qualification
```

`native.costs` 从新 qualification 读取所有预定案例，`native.costs_reuse` 从成本基线的 `REGISTERED.json` 读取精确执行顺序；它们均不选择或训练模型。实际使用参数见对应 `REGISTERED.json` 和本报告所列命令 receipt。`native.pack` 保留合格 binary、test binary、source identity 和 workflow/build receipts，并分成小于 384,001 字节的完整 tar.gz 二进制片段；合并后逐 member SHA 校验。原始任务/owner数据由根实验统一打包，避免重复保存。

### 建议的代码审查阶段

1. `kernels.rs` + `model.rs` + `native_tests.rs`：冻结数学合同、模型 schema 与逐潜态 readout。
2. `port.rs` + `owner.rs` + `main.rs`：真实 runtime、身份绑定、互斥和 paired commit/recovery。
3. `native_policy.py` + `native_validation.py` + `build.py/workflow.py`：真实 broker 接线、独立数值/进程验证与可复查构建。
4. `native/costs.py` + `native/costs_reuse.py` + `native/pack.py`：完整成本、经验证的进程复用优化和证据交付。

这些阶段共享已冻结的接口，但分别回答数学实现、实际状态所有权、实验可重现性和真实使用成本的问题，便于逐段审查超过单个小变更规模的交付。
