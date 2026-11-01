# R12 独立 Rust 有限传播、真实事件与恢复

## 已完成的范围

本目录提供无第三方 Rust crate 的独立原生实现：同一个有限 CTMC 行生成元的概率传播、Bayes 观察更新、真实 Gillespie 跳变，以及保存后在新进程继续执行。它是 Linux 上的研究算子和 CLI，不是生产 `NeuronRuntime` 的资格或权限交付。

完整金融核决定的 R12 实际 `Q/prior/emission` 已进入独立原生验证。`evidence/contract_01/fixture.json` 保留执行时的完整原字节；`RESULTS.json` 绑定其 SHA-256、构建身份、原始输出与检查结果。金融参数、boundary、五输出、reward/read-cost 一并保留；不能把本目录的核对解释为重新证明完整金融模型的最优停止。

## 数值合同与 API

```c
int propagate(size_t n, const double *q, double dt,
              const double *prior, double *out);
int observe(size_t n, const double *prior,
            const double *likelihood, double *out);
```

`q` 是 `n*n` 行优先数组，概率是行向量。调用者必须提供有效、对齐的内存；空指针会拒绝，任意悬空指针不可能由这个 C ABI 安全诊断。结果仅在成功时写入。Python 接口为 `adapter.NativeOperator.propagate(q, prior, dt)` 和 `observe(prior, likelihood)`。

| 返回值 | 含义 |
|---:|---|
| 0 | 成功 |
| 1 | 维度不合法 |
| 2 | 非有限值、负时间或非法概率/likelihood |
| 3 | 非 CTMC 生成元 |
| 4 | 概率质量或观察归一化失败 |
| 5 | 显式工作预算超限 |
| 6 | 数值有效性失败 |
| 7 | 空指针 |
| 8 | 可捕获 Rust panic |

传播采用 uniformization：`lambda=max(-diag(Q))`，`P=I+Q/lambda`，按 Poisson 权重累加 `prior*P^k`。每段 `lambda*dt<=16`，大时间自动分段；下一项与递减项比率给出 Poisson 尾的几何上界，各段共同分配 `1e-13` 的截断预算。这是精确实数运算中对合法生成元的尾界，不是 f64 全部运算的区间舍入证明。生成元、概率、质量、工作规模另行检查。

传播不会在末尾强制归一化来掩盖丢失质量。只有观察更新执行 Bayes 归一化，并先按最大 likelihood 缩放，支持极大/极小正密度。纯 FP32 未实现、未验收。ABI 维度上限4096、单次最多16384段，并不等于对所有这些规模都完成了性能或误差资格验证。

## 独立验证结果

### 一般有限模型

`test_native.py` 的首次独立审计保存在 `evidence/audit_01/`，共 **67/67** 检查通过：

| 检查 | 实测结果 |
|---|---:|
| 与 SciPy 独立矩阵指数的最大传播误差 | `3.186340080674199e-14` |
| 最大绝对概率质量误差 | `8.693046282814976e-14` |
| Native 差分与独立 Frechet 导数最大差 | `1.904205959579741e-12` |
| 原生跨进程后验与独立 expm/Bayes 差 | `4.3298697960381105e-15` |

覆盖1、2、5、20、24、64维一般生成元，零时长、零速率、128时间传播、解析两状态1000时间极限、分段一致性、极端 likelihood 缩放、无效输入及输出不改写。三个实际进程完成整段、前段、恢复后段；最终 checkpoint 逐字节相同。校验和、版本以及已有 checkpoint 覆写拒绝也实际执行。

这份审计绑定当时源码和二进制。`evidence/build_01/` 保留它们，源码按原字节 gzip 冻结。随后格式化和新增事件 CLI 的来源另外由当前 `evidence/build/BUILD_RECEIPT.json` 记录，没有把旧运行冒称为新源码运行。回执由 `BUILD.json` 原字节改名 `BUILD_RECEIPT.json`，避免根格式工具将其误判为 Bazel 文件；改名的字节身份记录在 `evidence/RECEIPT_RENAME.json`。

根 `just fmt` 后又仅拆分了 import 分组。真实合同审计所用的完整源码与CLI二进制保留在 `evidence/build_contract_01/`，每份源码都恢复到已记录的精确SHA后才gzip冻结；当前release库与该审计库逐字节相同。新CLI嵌入了新的源码身份，其构建与旧运行身份明确分开。`FROZEN_NATIVE.json` 汇总最终绑定，不将未执行的新CLI进程追认为旧恢复试验。

### R12 完整金融核所生成的实际 Q

`test_contract.py` 在格式化后的实际构建上完成 **68/68** 检查，原件在 `evidence/contract_01/`。

- 同一个20维 `Q`，时间覆盖0.05、0.15、0.45、0.75、1.05、2.1、128。
- 每个时间点逐一核对七种观察结果的后验。
- 概率传播/后验的最大绝对误差 `1.7041923427996153e-14`。
- 最大质量误差 `6.894484982922222e-14`。

这里验证的是该有限模型的原生前向一致性。完整核反向传播、控制器策略及训练结果由上层研究协议分别验收；本目录没有给 Rust 核附加一个未经核对的 surrogate gradient。

## 真实首达、恢复与复位事件

`events.rs` 使用同一个 `Q` 的 Gillespie 等待时间/转移分布。SplitMix64 生成固定52位开区间均匀数；它只服务可复现实验，不是安全随机数。每个 content block 包含8个活动状态及两段 Erlang 恢复状态。

| 有限模型中的真实转移 | 事件记录 |
|---|---|
| active0 → 同 content 的 R1 | `first_hit` |
| R1 → R2 | `refractory_phase` |
| R2 → 同 content 的 active | `reset_keep` |
| R2 → 另一 content 的 active | `reset_switch` |
| 相邻活动格之间移动 | `active_jump` |

固定种子20261031、实际 R12 Q 的一次 `dt=256` 推进记录 **1993次跳变、51次网格首达、50次恢复phase转移、50次复位、8次content切换**。期末仍有一次首达后的恢复未完成，未将其冒算成复位。单次推进允许反复跨界与复位。

整段256，与64之后退出进程、再在新进程推进192，得到逐事件完全相同的时间/起止节点/事件种类，最终 checkpoint 也逐字节相同。独立脚本从原始转移重新检查因果顺序、正转移率、phase关系、计数和最终状态。

保存内容包括当前节点、绝对时钟、下一次跳变的**绝对时刻与目标**、PRNG状态、累计计数、轨迹摘要及完整Q。恢复不会重新抽取已经排定的等待时间。checkpoint 使用 f64 位模式，绑定源码身份与 SHA-256，采用同步写入和原子 create-only 发布；摘要只提供完整性核对，不是外部签名或权限证明。没有测试断电损坏或任意外部副作用的 exactly-once。

这是有限网格 CTMC 的真实样本路径，不是连续 Brownian 路径；概率占用 `prior*exp(Q*dt)` 也不是这个样本的事件计数。当前事件合同在整条路径上固定Q；上下文改变Q时，需要另行定义剩余 hazard 与未完成恢复的转换，不能沿用旧 pending event 冒称新模型。

## 24/64/256 cell 的 CPU 计费

首次 `audit_01` 的同进程成本只作为诊断保留：此前 BLAS 线程的活动可能影响 `process_time`。另用 `benchmark_native.py` 在 **18个独立新进程** 中重新计费，每进程显式限定一个 BLAS/OMP/MKL 线程。`evidence/bench_01/RESULTS.json` 保留全部9次测量、启动/导入/准备/完整子进程CPU、wall、RSS和输出。

每颗 cell 的状态维数为20，本表的24/64/256是同一Q与prior的同质批次数量，不是256维网格或完整网络规模。对照为合法复用的预计算 `exp(Q*dt)` 矩阵乘法；其准备成本单列，并未忽略它。

| dt | cell数 | Native批次CPU中位数，ms | 缓存矩阵批次CPU中位数，ms |
|---:|---:|---:|---:|
|0.15|24|0.388667|0.022643|
|0.15|64|0.819256|0.058817|
|0.15|256|3.149194|0.234839|
|0.45|24|0.308779|0.022384|
|0.45|64|1.399948|0.057605|
|0.45|256|3.064959|0.237322|
|2.1|24|0.383128|0.022424|
|2.1|64|1.868794|0.058767|
|2.1|256|4.230159|0.234578|

当前 native 每调用重新验证生成元、分配状态并执行 uniformization，缓存矩阵对照只需乘法，所以这里没有 native 热执行优势。缓存准备约0.46–0.66ms，Native加载/准备约0.35–0.61ms；导入及完整进程成本另见原始回执。线程限制减少了计费污染，没有隔离共享硬件负载。未测GPU、焦耳、完整金融核训练成本或端到端任务效用，不能把这些原语耗时替代完整系统经济性。

## 复现和审阅阶段

```bash
python tools/hcsn/unified_cell_r12_20261031/native/build.py --rustc /path/to/rustc
python tools/hcsn/unified_cell_r12_20261031/native/test_native.py --output /tmp/native-audit-new
python tools/hcsn/unified_cell_r12_20261031/native/test_contract.py --fixture tools/hcsn/unified_cell_r12_20261031/native/evidence/contract_01/fixture.json --output /tmp/native-contract-new
python tools/hcsn/unified_cell_r12_20261031/native/benchmark_native.py --fixture tools/hcsn/unified_cell_r12_20261031/native/evidence/contract_01/fixture.json --output /tmp/native-benchmark-new
```

依赖编译器版本与全部二进制哈希位于 `BUILD_RECEIPT.json`；Rust仅使用标准库。Python验证需要NumPy/SciPy，CLI本身不依赖它们。所有审计输出目录拒绝覆盖。

这组改动按实际依赖可分为四个审阅阶段：`core.rs/lib.rs/adapter.py/build.py` 的算子接口；`main.rs/sha256.rs` 的状态恢复；`events.rs/events_main.rs` 的真实事件；独立验证、计费及原始证据。每个Rust文件均小于500行；不修改原项目生产owner或Cargo依赖。
