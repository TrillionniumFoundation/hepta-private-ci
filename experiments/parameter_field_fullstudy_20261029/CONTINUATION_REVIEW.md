# 参数场 × Hepta 全量实验：本轮接续交接

## 当前结论

执行链中发现的登记、分析准入、失败留证和退出状态问题已修复，**45 项合成工程检查通过**。全量科学实验仍未完成，当前没有后台科学 worker。本轮新增科学梯度为 0，没有打开新的 qualification/final endpoint；没有新的净收益或 Hepta 交互结论。

本轮新增源码与证据均在本地 Git 保存。最后公开分支仍为 `research/parameter-field-fullstudy-20261029`，公开 HEAD 仍是 `b7b2104a6d0ec2f27651223bda76e5419255035f`。本轮公开写入次数为 0。

## 已完成的执行修复

| 问题 | 已完成改动 | 验证 |
|---|---|---|
| 原证据目录依赖共享内存 | 新建不可变 `OPS_ATTEMPT02_DISK.json`，将 raw/CAS 放到磁盘目录，重绑 A/C/controller freezes 与队列；原操作计划保留 | 原 A 65 文件、C 86 文件及新冻结闭包逐一匹配；科学源代码、样本、种子、动作、guard、预算和统计门槛不变 |
| 完整报告无法取得 controller PID 登记 | 新增 `analysis_launch_v2.py`，独立取得 controller 锁、内存准入、真实子进程登记，再调用未修改的报告器 | 10 项合成检查 |
| 后续输入冻结容易遗漏实际祖先或完整人口 | 新增 `register_followups_v2.py`，只有完整 A 证据齐全时才能生成 B/W/R；全部前置人口齐全才生成 endpoint 登记和完整 14-job 队列 | 12 项合成检查；真实本地 Git blob 核验 |
| 汇总和最终封存需要手工组装大量身份 | 新增 `register_summary_v2.py`，绑定实际输入、26 个分析 seals 和 30 个 finalizer seals；登记阶段只读 metadata/hash | 11 项合成检查，包括与原分析和封存验证器的完整接口验证 |
| 控制器在写进度失败时没有标准失败凭据；原控制器某些失败路径仍返回 0 | 新增 `controller_envelope_v2.py`，记录实际 Popen 尝试/PID，保留有界失败凭据，严格限定零工作恢复；仅完整 14 项身份一致时返回成功 | 12 项合成检查；实际恢复入口返回 75，资源不足时旧现场未移动 |

四组检查合计 45 项，未导入 Torch/NumPy、没有科学训练或端点评分。最初的 44 项联合检查有一处子进程 CPU 差分舍入失败；已改成累计 user+system 时间之差，并增加非零但不增长计数的精确零测试。原失败凭据和修复后的通过凭据都保留。原科学代码与已冻结控制器没有被改写。

## 本轮真实执行与失败记录

1. 磁盘版原 controller 实际启动，始终未取得科学 worker 准入。最后成功进度在 90.5116 秒；其后写 `PROGRESS.json` 因 cgroup 预留不足抛出 `MemoryError`，退出码为 1。
2. 当时没有任何 job START、科学阶段目录或 operation 文件，worker registry 为空。其零工作结论来自源代码与遗留字节的核验，未冒称过去已有 Popen 观察器。
3. 新 envelope 的实际恢复检查返回 **75 / ADMISSION_BLOCKED**。它先检查完整的 768 MiB worker 预留 + 1 GiB margin，因此没有移动旧事件的五个文件，也没有启动训练。
4. 固定报告器已生成新的 `execution_status_disk/RESULTS.json`，状态为 **BLOCKED**，`efficacy_artifacts_opened=false`，五项研究结论为 null。第一次输入把零科学工作的控制器故障放进专供未知额外训练工作的历史失败槽，遭原 schema 拒绝；修正后该故障归入资源状态，原训练成本与失败没有变更。

## 当前资源与自动审批阻塞

2026-10-29 07:58 EDT 的快照：cgroup 上限 8 GiB，有效占用 7,602,749,440 B；首 worker 需要 1,879,048,192 B 余量，仍缺 **891,863,040 B（约 0.831 GiB）**。OOM 累计计数仍为 8，oom_kill 仍为 4，不能据这些累计计数推断某个 PID 的死因。

磁盘在登记时有约 3.2 GiB 可用，之后本轮清理自身两个无效安装下载回收 352,321,536 B。最终共享磁盘可用空间又下降到约 **0.52 GiB**。相对于 2 GiB raw 上限 + 256 MiB reserve 的完整容量安排，还缺约 **1.73 GiB**。这表明磁盘路径改造完成，但共享环境的实际全量容量仍未满足。没有证据把这次容量变化归因于某个具体工作流。

### 自动审批拒绝 1：公开发布

尝试把 `OPS_ATTEMPT02_DISK.json` 和资源回收凭据登记到 `TrillionniumFoundation/hepta-private-ci` 时，自动审批在执行前拒绝。仓库当前实际是 **public**。拒绝理由是现有授权未明确覆盖向该公开目的地披露操作记录、内部路径、容量信息和执行证据。

需要的明确授权对象是：本轮已准备好的新增源码、协议/操作登记、报告和执行凭据，发布到上述具体公开仓库。公开后这些内容可被所有人读取。本轮没有上传新模型检查点或原始科学数据；这些新产物也尚不存在。

### 自动审批拒绝 2：跨工作流 RAM 缓存回收

已完成只读核验的候选仅为 `/dev/shm/hepta-adaptive-deny-cargo/registry/src`：

- 1,338 / 1,338 个依赖包完整核验；74,687 个常规文件与保留压缩包逐文件 hash 一致。
- 修改、缺失、类型或链接异常为 0；实际分配量为 1,810,456,576 B，约 1.686 GiB。
- 1,338 个未包含在原归档内的完成标记已另存备份，并验证每个标记的字节与 mode。
- 检查时未发现活跃进程引用，但这是瞬时观察，不能代表其他工作流的所有权授权或后续使用安排。

提出的实际操作包含持有现存 Cargo 缓存锁、再次核验文件和引用、保留压缩包/索引/其他代码与实验数据。自动审批仍在执行前拒绝，理由是这属于另一工作流的数据，可重建不能代替授权，也不能消除扰动风险。**缓存未删除、未移动。**

继续使用共享环境，需要明确的跨工作流资源维护授权和足够磁盘空间。提供本研究独立的 8 GiB RAM、至少 4 GiB 可用磁盘执行环境也可解决共享容量问题；仍须按实际观测通过原资源门，不能改变门槛制造通过。

## 五项科学问题的固定后续工作

| 阶段 | 固定工作 | 梯度 microsteps |
|---|---|---:|
| A | 144 个完整分支 parent、576 个候选 tail 标签、48 条 development paths；记录 guard 后状态、fallback 与成本 | 117,504 |
| B | 3 个固定模型 ×16 个新 schedule ×5 种方法，共240 paths；独立任务/保留能力/成本比较 | 69,120 |
| C | 8 个配对评估 seed 的 ordinary/Hepta × baseline/field 2×2，另有固定开发与 warmup；32 eval paths | 57,536 |
| W | 3 个固定 parent 的隐藏动量方向诊断；保持参数与场信息约束，记录动作价值排序 | 2,880 |
| R | 重构并逐字节验证全部576 terminal；作为新增重构证据和额外成本，不增加统计样本 | 96,768 |
| 合计 | 固定设计，不代表已完成工作 | **343,808** |

历史已发生梯度下界仍为 **103,184**；其中未保存的额外工作未知，不能声称这是完整成本。原 attempt01 原始数据丢失与历史 V5 exact-regression **FAIL** 均保留。一次合法后继差异的工程预检不能替代独立净收益、保留能力和 Hepta 交互结论。扩展 neuron 与模态仍需等待固定研究结果。

## 资源放行后的精确恢复入口

以下命令已经固定到真实本地 Git 提交与源文件 SHA。执行前应核对完整磁盘安排和实时 RAM；当前真实 raw 的五文件清单必须保持一致。新入口在资源不足时返回75且保留旧现场。

```bash
env PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2   PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime:/dev/shm/hepta-field-fullstudy-20261029/source   python -B -m experiments.parameter_field_fullstudy_20261029.controller_envelope_v2   --root /workspace/scratch/178ced6a501f/fullstudy_attempt02_disk   --queue /workspace/scratch/178ced6a501f/fullstudy_queue_attempt02_disk.json   --freeze /dev/shm/hepta-field-fullstudy-20261029/source/experiments/parameter_field_fullstudy_20261029/registrations/OPS_ATTEMPT02_DISK_ENVELOPE_SOURCE_FREEZE.json   --freeze-sha256 91f1cf6dee69f7240a3c4cd9ba223facc7003cd96d0d95413f53a89a09a30e14   --amendment /dev/shm/hepta-field-fullstudy-20261029/source/experiments/parameter_field_fullstudy_20261029/OPS_ATTEMPT02_DISK.json   --amendment-sha256 d0572d7c26f7d15f9a78f3a8d6e6b72f70ae709e075c89a04f4599d90146d372   --recover-zero-work
```

A 三组完成后，调用 `register_followups_v2 --stage followups` 生成实际 B/W/R freezes，再以原队列 SHA 为前提安装生成队列。A/B/C/W/R 全部完成后，调用 `--stage endpoints` 生成最终14项队列；只有完成后的实际文件能够提供这些 hash，不预造占位冻结。

14项完整结束且 controller 停止后，调用 `register_summary_v2 --stage analysis`，由 `analysis_launch_v2` 执行未修改的完整报告器；aggregate 完成后再调用 `register_summary_v2 --stage finalizer` 和原 finalizer，完成逐路径真实重建验证。

分析登记精确绑定26个 seals；封存登记精确绑定30个 seals。所有原始失败、控制记录、原始输出与实际成本继续保留。controller、登记、分析与封存成本单列，累计 CPU 数字不能与其增量重复相加。

## 本地源码身份与交付范围

- 实际 A/C 源码登记：`0f7efa5e79cbcafe925fe35aee4a73ec65738c36`。
- 实际 envelope 源码登记：`434d390b3d972efa940f1054a09bc2858632f0c8`。
- 最新实现提交：`f4af33088b2b292a2cb2e7ccf8bd8f22bd2833dc`；后续文档/证据提交不改变这些冻结身份。
- 原科学协议 SHA：`2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55`。
- 磁盘 OPS SHA：`d0572d7c26f7d15f9a78f3a8d6e6b72f70ae709e075c89a04f4599d90146d372`。
- 新 controller freeze SHA：`91f1cf6dee69f7240a3c4cd9ba223facc7003cd96d0d95413f53a89a09a30e14`。

本地 Git 是现有研究项目的可审阅源码/证据快照，未推送到公开仓库。恢复原资产仍需既有严格校验的模型、observer、MNIST 与 CPU Torch runtime；本交付不把模型资产或未完成科学样本冒充为已经生产的新结果。

## 磁盘资源的另一项具体审批候选

只读盘点得到一个限定范围：仅 `/tmp/hepta-pq-target/release/deps` 直属、已列入 `evidence/DISK_CACHE_RELEASE_PROPOSAL.json` 的 **1,095 个普通、单硬链接 `.rlib` 文件**，实际分配 **3,917,512,704 B（约3.648 GiB）**。其余二进制、`.so`、`.rmeta`、`.d`、类型诊断、build/profile 元数据、源代码与原始证据均不在范围内。

这些按位置与扩展名归类为 Rust 优化依赖库构建产物；尚未核验完整重建环境。清理后对应工作流需要重编译，CPU 时间未知。这项方案只是提交用户审阅，未执行删除、搬移或归档，也没有把它作为绕开已拒绝缓存操作的替代执行。操作前需重新核对进程引用和清单中的全部文件身份。

若用户选择保留其他工作流的缓存，独立执行环境可以替代 RAM 与磁盘两项跨工作流维护授权。
