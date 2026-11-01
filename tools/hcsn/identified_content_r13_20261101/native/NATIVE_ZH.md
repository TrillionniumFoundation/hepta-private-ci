# R13 原生传播、缓存、事件迁移与恢复

## 已完成的结果与适用范围

本目录完成了可复用的有限 CTMC 原生算子、正确处理模型更新的 Gillespie 事件执行器，以及独立的研究状态适配器。全部实现留在研究目录，没有修改或激活生产 `neuron.runtime`。冻结后的同一动态库通过 61 项传播与观测检查，事件 CLI 通过 20 项检查，研究状态适配器通过 13 项检查。跨进程恢复使用真实的新进程，既检查连续执行一致性，也检查不合法恢复和迁移的拒绝。

后续还完成两项与原冻结结果分开保存的直接证据：[HETEROGENEOUS_CELLS_ZH.md](HETEROGENEOUS_CELLS_ZH.md) 测量 1/16/64/256 个不同参数、不同 Q 的模型；[LEARNED_EVENT_ZH.md](LEARNED_EVENT_ZH.md) 直接把冻结 fit 131101 的精确 Q 导出到事件 CLI，在真实新进程中重放触界、恢复、复位与内容切换。两项均未修改运行源、二进制或任务确认结果。

缓存 dense transition 的完整后端 CPU 成本明显低于 R12 每行重新构造算子的实现，但仍是合法缓存 NumPy/SciPy 基线的 2.13–4.37 倍。因此，本次支持“去掉重复准备与逐行调用开销”的工程改进，不能支持“Rust 核比强 NumPy 基线快”或“完整解析金融模型带来独特速度优势”。原始证据分别见 [prepared_frozen](evidence/prepared_frozen/RESULTS.json)、[migration_frozen](evidence/migration_frozen/RESULTS.json)、[runtime_adapter_frozen](evidence/runtime_adapter_frozen/RESULTS.json) 和 [benchmark_frozen](evidence/benchmark_frozen/RESULTS.json)。

这里的准确性是对给定有限矩阵 `Q` 的传播准确性。完整 He–Xiong 数值核、物理参数辨识、有限体积网格与连续扩散误差，由父实验及 `precision/`、`propagation/` 分别提供证据。原生算子不把矩阵指数一致性当作连续模型已被精确实现的证明。

## 冻结身份与可审查阶段

[RUNTIME_FREEZE.json](RUNTIME_FREEZE.json) 固定十个运行源文件、两个二进制以及最终验证回执。其 Rust 源集合身份为：

`fbd72c05616d81f48043abbb4da2da290501c1bd7545d1df799c7e3fb44d298f`

| 产物 | SHA-256 |
|---|---|
| `libhcsn_prepared.so` | `19299f8802da6932f9a0e08025f265c38b855be8e9417b17f2c558115ef50ad2` |
| `hcsn-events-r13` | `9bf0be69618c1e022cef1b3f6026d656109e58e7d6a2cd838d4f66d131e3a08d` |

实现分成三个独立可审查层次：`prepared.rs`、`lib.rs`、`adapter.py` 处理不可变矩阵、批传播和观测；`events.rs`、`checkpoint.rs`、`events_main.rs` 处理实际跳变与恢复；`runtime_adapter.py` 处理请求时间、模型身份、后验及检查点谱系。各 Rust 文件少于 500 行，只使用标准库。继承来源和最初差异记录在 [INHERITED.json](INHERITED.json)。

根目录格式化改变 Rust import 分组后，动态库的二进制哈希也发生变化。第一次“二进制应相同”的断言失败，没有把它记成通过。旧产物保存在 `evidence/build_before_fmt/`，新产物提升为默认库后，传播、真实事件进程、研究适配器和全部 60 个基准进程重新执行。详细过程见 [FORMAT_IDENTITY.json](evidence/FORMAT_IDENTITY.json)。`*_after_fmt` 中早先仍使用旧 CLI 的回执是历史记录；本报告引用的是明确使用最终产物的 `*_frozen` 目录。

## 传播与内容观测

对行生成元 `Q`，设 `lambda=max(-Q_ii)`，`U=I+Q/lambda`。原生传播使用正性 uniformization：

\[
 p\exp(Q\,dt)
 =\sum_{k\geq0}e^{-\lambda dt}\frac{(\lambda dt)^k}{k!}pU^k.
\]

`Model::new` 只在创建时验证生成元并构造稀疏 `U`；模型身份绑定矩阵维数、版本和所有 float64 位。模型不可变，任何新 `Q` 都创建新模型，因而不能意外拿旧 transition 传播新参数。每个 cache key 精确包含 `dt.to_bits()` 与 sparse/dense 模式，不进行时间量化。

较大的 `lambda*dt` 用 2 的幂次分段，使单段 Poisson 均值不超过 16。每段按尾部预算构造权重，整体截尾预算设为 `1e-13`。Sparse 模式在行向量上执行稀疏递推；dense 模式先从基向量构造小步 transition，再平方得到整段 transition。此后可以把同一个 `P` 同时提供给规划器和批传播。尾部预算不包含全部浮点累积误差，不能把它表述成最终数值误差的严格统一上界。

传播不强制归一化，不用这一操作掩盖质量误差。每批输入和输出仍做合法性检查。观测使用按行缩放的 Bayes 更新，明确拒绝全零 likelihood 或零 evidence。最后一行发生错误时，整个调用方输出保持不变。线程局部工作区保留容量，`out` 允许 Python 输出缓冲区复用；这里没有宣称整个 Python 调用零分配，也没有提供完整分配分析器。

独立参照是 SciPy `expm(Q*dt)`。网格由 R13 `propagation.api` 导出，coarse/default/fine 的状态数分别为 78、116、188；测试时间为 0、0.05、0.45、2.1、29.4，覆盖 sparse 与 dense 两种模式。全部对照的最大逐元素误差为 `4.3336861876852595e-14`，最大质量误差为 `5.346834086594754e-13`。还检查了半群分段、吸收状态、批处理、输出别名、极大 likelihood 缩放、版本及 handle 拒绝、非法生成元、长时工作量边界和 exact-dt 缓存。全部 61 项通过，不代表任意参数、任意时长都有同样误差。

## 缓存上限与拒绝原子性

当前每模型最多缓存 32 个 `(dt, mode)`，缓存 payload 上限 64 MiB；维数、批大小、live handle 和分段另有显式上限，详见 [ABI.md](ABI.md)。cache-full 返回明确的 `cache_limit`，没有暗中舍弃精度或换用近似时间。

[cache_limit_witness.py](cache_limit_witness.py) 在冻结源上填满缓存，并检查失败的研究 tick 不改变 posterior 字节、clock、sequence 或 checkpoint digest。随后单 owner 清理底层 `PreparedModel` 缓存，以完全相同的请求重试成功。证据为 [CACHE_LIMIT_WITNESS.json](evidence/CACHE_LIMIT_WITNESS.json)。`runtime_adapter.py` 没有自动清理策略；已有 `PreparedModel.clear_cache` 可供明确的资源管理策略使用。清理不会改变模型或 actor state，但之后重新构造 transition 必须重新计费。

## 事件推进和固定网格上的模型更新

分布传播给出状态占用概率；事件 CLI 采样一条实际 CTMC 路径，计数和记录真实的跳变。两者不是同一种状态，也不能用恢复态的概率质量冒充事件次数。

事件状态保存当前离散状态、时钟、hazard anchor、unit-exponential threshold、PRNG 状态、计数、模型版本与历史摘要。普通固定 `Q` 的分段推进保留 anchor 与 threshold，因此同一模型下的整段与分段执行可逐位重放。目标状态只在跳变发生时，按当时的 `Q` 行抽样；检查点不保存一个旧模型预选的目标。

在时间 `t` 更新为 `Q_new` 时，先用 `Q_old` 处理至 `t`，包括恰好发生在 `t` 的旧模型事件。若当前持有的暴露阈值为 `E`、anchor 为 `a`、旧离开率为 `lambda_old`，残余暴露为

\[
 E_{\mathrm{rem}}=E-\lambda_{\mathrm{old}}(t-a).
\]

`preserve` 策略把 `E_rem` 与新 anchor `t` 绑定；下一事件时间按新离开率重算为 `t+E_rem/lambda_new`。`resample` 策略在更新时间重新抽取独立 `Exp(1)`，同样不复用旧目标或旧绝对事件时刻。新离开率为零时不安排事件，重新激活时按所选暴露策略恢复。普通由已发生历史确定的模型更新下，这两种策略分别提供持续的随机数耦合或显式的无记忆重采样。

合法跳变遵守两个内容 block 的布局：相邻 active 网格跳变、`active0 -> R1` 触界、`R1 -> R2` 恢复阶段推进、`R2 -> active` 复位，并显式记录内容保留或切换。一个 `dt` 内可处理多次完整循环。实际 FVM 的 64 秒更新路径产生 632 次总跳变，含 2 次触界、2 次恢复阶段推进、2 次复位、0 次内容切换；固定 `Q` 的对应见证为 614 次总跳变。这里的少量路径用于确定执行语义与重放，不是事件率或总体精度的统计估计。

20 项检查覆盖实际新进程分段恢复、实际 FVM 模型更新、旧目标被新 `Q` 移除的受控例子、残余暴露公式、独立 PRNG 重采样计算、吸收与重新激活，以及错误版本、倒退时钟、非更新版本、非法布局、篡改、来源不匹配和覆盖写入的拒绝。整段与跨进程分段的最终检查点字节和路径一致。CLI 的失败流程不写新的检查点；内部可变事件对象并未承诺任意异常后的内存事务回滚，生产调用应以提交成功的检查点为恢复边界。

原生事件模型检查相同维数及转移结构，实际迁移 fixture 也使用同一组网格边界。它没有仅凭维数证明物理网格相同。研究分布适配器另外绑定 `layout_identity`；生产事件适配也必须绑定同样的状态基和观测定义。重划网格必须先定义状态映射，不能隐式套用本次固定网格迁移合同。

## 真实进程恢复与研究接入合同

事件 CLI 形式为 `init MODEL SCRIPT NEW_CHECKPOINT SEED` 或 `resume CHECKPOINT SCRIPT NEW_CHECKPOINT EXPECTED_VERSION`，脚本支持 `advance dt` 与 `migrate absolute_time MODEL_PATH preserve|resample`。检查点记录精确 float64 位、完整矩阵、模型/程序身份、暴露与 RNG；写入使用不覆盖临时文件、fsync 与原子 hard link。

研究分布适配器用独立 schema 保存联合 posterior、时钟、sequence、模型/网格/观测 identity 和 predecessor digest。tick 请求必须提供 `dt`、期望模型版本、期望检查点及 READ 声明；未要求 READ 时不得携带 likelihood，要求 READ 时不得缺少它。预测和观测成功后才提交状态。新模型只在相同网格身份上保留 posterior；恢复重建 cache，并验证运行源和动态库身份。真实三个 Python 进程完成连续与分段恢复的一致性，13 项检查全部通过。

这些 SHA 摘要用于可复现身份与损坏检测，没有赋予检查点认证或生产 witness 权限。适配器不实现生产 CAS、可信传感器、Q24 量化或资源准入；[PRODUCTION_ADAPTER_ZH.md](PRODUCTION_ADAPTER_ZH.md) 给出已读取的生产接入点和最小缺口。

## 相同误差标准下的 CPU 成本

[benchmark.py](benchmark.py) 保存了实际执行程序。五个设置、四种后端、各三次重复，共 60 个独立新进程，固定 BLAS 单线程并打乱执行顺序。每个后端都处理相同 float64 的 `Q`、prior 和正 likelihood，必须通过相对独立 NumPy reference 的 `3e-11` posterior 阈值。所有 60 项通过。

该基准的一个 batch 内所有行共享同一个 Q，不能据此推断大量独立参数 cell 的成本。新增异质基准为每个 cell 单独调用完整金融边界、构造 Q 和缓存 P；其全成本 native/NumPy 比为 1.74–2.20，256 cell 在当前 128-handle 上限下用两个 worker 完成。具体 payload、RSS 及第一次 `/proc` PID namespace 采样问题的公开修正见专项报告。

每次计时包括模型构造、生成元验证、三种时间 `.15/.45/2.1` 的全部准备、规划器需要的 transition 导出、首次工作区分配，以及 30 步传播加观测。Sparse 后端给规划器构造 dense transition 的成本也计入；strong NumPy 允许相同的不可变模型、精确时间缓存、批 BLAS 和概率/观测合法性检查。表中为每设置三次总 CPU 秒的中位数。

| 状态数 / batch | R12 逐行 | Prepared sparse | Prepared dense | Cached NumPy | Dense / NumPy |
|---|---:|---:|---:|---:|---:|
| 116 / 24 | 0.382890 | 0.282258 | 0.017080 | 0.008013 | 2.13 |
| 116 / 64 | 1.041135 | 0.817459 | 0.025219 | 0.008981 | 2.81 |
| 116 / 256 | 3.941423 | 2.825565 | 0.069825 | 0.015993 | 4.37 |
| 78 / 64 | 0.257725 | 0.117925 | 0.012392 | 0.004921 | 2.52 |
| 188 / 64 | 10.099290 | 10.934500 | 0.079847 | 0.027400 | 2.91 |

Dense 相对 R12 逐行实现的成本比为 0.00791–0.04808，但稀疏缓存本身在较细网格仍可能更慢。可观测的收益主要来自重用整段 transition 和批处理，不能全部归因于“验证只做一次”。这些是一个主机的 CPU 证据，不含 GPU，也没有证明任意 batch、任意新 dt 或任意高频模型更新的收益。

构造与准备已全部计入后端比较；公共 fixture/输入生成、解释器导入和基准启动在计时外，外层新进程 wall time 单独保留，不用于速度结论。编译另有 wall time 回执，未测编译 CPU，也不按每个模型重复摊销。该微基准不是完整文本任务部署成本；真实任务的训练、前端、进程启动和 service setup 由父实验的独立成本账本统计。

## 复现入口与后续限制

最终有效回执位于 `evidence/prepared_frozen/`、`migration_frozen/`、`runtime_adapter_frozen/`、`benchmark_frozen/`。对应程序为 `test_prepared.py`、`test_migration.py`、`test_runtime_adapter.py`、`benchmark.py`。各程序先于执行保存在本目录；重新运行时应写新的输出路径并记录编译身份，避免覆盖已冻结证据。

可继续改进的具体对象是 dense matrix multiply 的实现或合法 BLAS 接入、缓存失效频率与高频模型更新成本、独立测量的进程资源上界，以及生产候选状态提交合同。纯 FP32、任意网格迁移、自然时间序列任务上的泛化、相对 generic HMM 的质量优势及生产准入，均不是本目录已经完成的结论。
