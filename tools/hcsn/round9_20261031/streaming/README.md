# R9：充分统计量流式实现与当前 NumPy 对照

**实现验收通过；脉冲状态的独立必要性未得到证明。** 当前结果以
`evidence/v2` 为准。对提交
`00b94d54a9b85f285298d1a964777bdecfa85385` 新发布的完整历史 NumPy
执行器，72 个配置中流式实现 **38 个更快、34 个更慢**，CPU 与墙钟的
胜负计数相同。大批量多次查询和逐观察更新有收益；标量单次、标量逐观察
更新均出现回退。能耗为 `null`。

这是一项复用冻结 R8 模型的实现与成本验证。它没有重新训练，没有引入
新的盲测样本，也没有把框架切换或通用缓存收益解释成脉冲神经元独占的能力。

## 实现与适用任务

`filter.py` 维护三模态已知漂移模型的两个充分统计量：

\[
A=\sum_i\frac{\Delta y_i}{s_i^2},\qquad
B=\sum_i\frac{\Delta t_i}{s_i^2}.
\]

漂移模态为 `[-0.8, 0, 0.8]`，先验为 `[0.3, 0.4, 0.3]`。冻结的解析
滤波器使用已拟合的两个 scale 和三个 prior-shift 参数；普通 exact
control 使用同一统计量实现和已知模型参数。两者获得相同公开观察、时间
间隔、噪声和未来风险查询。

该任务的未来布朗路径在历史观察结束后重新开始；历史不是一段“已存活、
未碰边界”的删失路径。因此这里的两统计量充分性不能直接移植为任意
存活条件、任意移动边界或未知动力学下的充分性结论。

每条流的动态数组 payload 为 **40 字节**：A、B、两个补偿累计误差和
int64 观察计数。原 benchmark 的 32×3 binary64 历史输入为 768 字节。
这是状态 payload 比较，不是进程 RSS、Python 对象总内存或整机内存测量；
benchmark 仍持有公共输入数组。

## v2 修复及保留的历史

独立审阅发现 v1 在注册任务域以外有三个漏洞：有限输入累计溢出后仍提交
状态、`2**63` unsigned count 恢复时回绕、有限参数产生非有限 posterior
logits 时返回 NaN。v2 先完整计算并验证候选累计器/计数，再更新状态；恢复
时限制 int64 范围，并拒绝非有限 logits/posterior/risk；uint64 输入长度也
被安全规整。

`AMENDMENT.json` 记录修复理由。原 `evidence/results.json`、
`evidence/startup.json` 及 `evidence/source_v1/` 的四个原源文件均保留。
原记录未被新结果覆盖；主结论使用 `evidence/v2/results.json`，当前后端成本
使用 `evidence/v2/numpy_comparison.json`。

v2 的 16 个质量组为四个 regime × 三个冻结解析 fit 和一个普通 exact
control。所有组通过，14 项输入/恢复检查通过：

| 验证 | v2 结果 |
|---|---:|
| 相对冻结 Torch 执行器的最大概率差 | `1.3606963573664643e-6`，门限 `3e-6` |
| 相对最新 NumPy 执行器的最大概率差 | `3.2479380920880097e-7`，门限 `3e-6` |
| 两种参考执行器的动作分歧 | 0 |
| 整块输入与逐条输入的最大概率差 | `4.440892098500626e-16`，门限 `1e-12` |
| 相同分块的连续运行与 JSON 恢复 | 序列化状态、预测逐项精确相同 |
| 非法输入、计数及浮点溢出检查 | 14/14 通过 |

这里的恢复是同进程 JSON 序列化后重建对象，不是磁盘 journal/fsync 或真实
进程崩溃恢复。完整原生 owner 的进程恢复属于相邻 `../native/` 的独立验收。
四个 regime 共 8,192 个既有 R8 confirmation 输入，多个模型复用这些输入；
模型评估次数不计为新的独立样本。

## 主成本对照：最新完整历史 NumPy 实现

`numpy_comparison.py` 直接调用 R8 `state_task/replay.py::predict`；不是仅与
较旧 Torch 路径比较。注册身份见 `evidence/v2/NUMPY_REGISTERED.json`，
基线提交为 `00b94d54a9b85f285298d1a964777bdecfa85385`。

比较覆盖四个 regime、两个 family、三个 batch size 和三个 workload，共
72 个配对配置；每种实现每配置测量五轮，共 720 条原始 timing。
配对顺序交替，线程数固定为 1，包含各实现实际输入转换、初始化/更新、
风险预测、动作判断及 JSON 输出。32 次查询的 horizon 在 0.25–1.8 间
变化，避免把重复计算同一个答案的缓存机会误当成流式模型优势。

下表的 CPU 倍数为 **完整历史 NumPy 的中位时间 ÷ 流式中位时间**；
大于 1 表示流式更快。每行汇总八个 regime×family 配置；中位数和范围
均针对这八个配置的倍数。

| Batch | Workload | 流式胜/负 | CPU 倍数中位数 | CPU 倍数范围 |
|---:|---|---:|---:|---:|
| 1 | 单次摄入、单次查询 | 0 / 8 | 0.574× | 0.560–0.630× |
| 1 | 摄入一次、32 次不同 horizon | 8 / 0 | 1.146× | 1.111–1.203× |
| 1 | 32 次逐观察更新并查询 | 0 / 8 | 0.626× | 0.548–0.670× |
| 64 | 单次摄入、单次查询 | 0 / 8 | 0.757× | 0.685–0.944× |
| 64 | 摄入一次、32 次不同 horizon | 8 / 0 | 1.512× | 1.473–1.554× |
| 64 | 32 次逐观察更新并查询 | 0 / 8 | 0.932× | 0.881–0.965× |
| 2048 | 单次摄入、单次查询 | 6 / 2 | 1.088× | 0.840–1.261× |
| 2048 | 摄入一次、32 次不同 horizon | 8 / 0 | 1.877× | 1.752–2.591× |
| 2048 | 32 次逐观察更新并查询 | 8 / 0 | 1.430× | 1.359–1.531× |
| **全部** | **72 配置** | **38 / 34** | — | — |

墙钟的每行胜负数与 CPU 相同。Batch 2048 单次查询的两项回退来自
`long_history` 的两个 family。不能把“大 batch 全部更快”作为结论。
所有表格都是共享主机上的描述性计时，不是独占主机延迟保证或多比较
显著性检验。

**标量回退策略必须按工作负载说明。** 若完整历史本来就在调用方手中，
标量单次和逐观察任务应保留完整历史 NumPy 路径；batch 64 的对应两类
任务也是如此。`StreamingFilter` 当前不包含自动 backend 路由。若已丢弃
历史而只保留 40 字节状态，就不能凭空切回完整历史后端；要保留 fallback
历史时必须重新计入其内存与维护成本。标量重复未来查询仍有实测收益。

普通 exact control 同样获得这些流式收益，所以
`probability_spike_necessity_proved=false` 和
`independent_spiking_necessity=false` 均保持为 false。

## 启动、训练和能耗账目

`evidence/v2/startup.json` 保留新进程启动测量，包含 import、加载、一次
推理、JSON、启动与退出；文件缓存可能已热。该附加测量比较的是旧 Torch
与流式路径：解析 arm 的中位 CPU 为 1.170561 秒与 0.218534 秒，普通 arm
为 1.188451 秒与 0.194616 秒。它没有测量最新 NumPy 基线的冷启动，不能
把这些倍数套用到提交 00 的完整历史 NumPy 路径。

本轮新增训练 CPU 为 0；继承的 R8 全模型搜索 CPU 为 31.871367 秒，其中
三个解析 fit 合计 3.808075 秒，普通 exact control 无训练。既有 R8 数据
生成和初始化成本仍在原记录中，未被重写为零。独立 checkpoint 编解码计时
不含落盘/fsync。当前无可读 powercap/GPU 计量，`energy_joules=null`；
CPU/墙钟改善不换算成能耗收益。

## 从新目录复现

使用安装 NumPy、SciPy 和 CPU PyTorch 的 Python。v2 的记录环境是
Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0、PyTorch 2.8.0+cpu。
不同环境的时间与微小数值差异可能变化，以冻结验收门判断结果。

**全新 clone 先恢复 R8 模型。** 提交 00 的 12 个模型及训练记录位于
R8 `bundles/state_task.tar.gz.part000`、`part001`，不能假设 clone 后已有
展开的 `state_task/evidence/models/`。从交付 checkout 根目录按
[`R8 REPRODUCE_ZH.md`](../../round8_20261031/REPRODUCE_ZH.md) 先执行：

```bash
python3 tools/hcsn/round8_20261031/bundles.py verify state_task
python3 tools/hcsn/round8_20261031/bundles.py restore state_task
```

`verify` 只校验，不展开；`restore` 才恢复缺失成员。原恢复器按
`bundles/state_task.json` 核验每卷、整包及所有成员的 SHA-256，拒绝目录
穿越、符号链接和同路径不同字节覆盖。两个分卷分别为 4,194,304 和
1,620,749 字节，含 30 个冻结证据成员。稀疏 checkout 还须物化 R8
`state_task` 源码与冻结 JSON、`bundles.py`、该索引和两个分卷。本地已
恢复的模型在验证入口前再次按 `FREEZE.json` 检查；本次验证不等于已在
空白 clone 上重新执行 bundle 下载/展开。`reproduce.py` 不自动修改源
checkout；缺输入时提示这两条命令并拒绝开始。

`reproduce.py` 验证注册源与 R8 checkpoints，将必要源文件、全部 12 个
冻结 R8 checkpoints、R8 历史训练成本记录复制到一个**全新 repo 路径**。
原 streaming 结果不会复制。R8 数据会由原 `make_data` 按冻结 seeds 重新
生成；不重新训练、不改变原脚本。它把线程数设为 1，并验证原源/证据与
复制输入在运行后均未改变。已有目标路径一律拒绝，不覆盖或续写。

完整复现顺序为原 `audit.py`、`startup.py`、`numpy_comparison.py`：

```bash
python tools/hcsn/round9_20261031/streaming/reproduce.py \
  --output-repo /tmp/hepta-streaming-full-new \
  --python /path/to/torch-venv/bin/python
```

仅验证原 audit 入口：

```bash
python tools/hcsn/round9_20261031/streaming/reproduce.py \
  --output-repo /tmp/hepta-streaming-check-new \
  --python /path/to/torch-venv/bin/python \
  --checks-only
```

`--checks-only` 仍执行 audit 内冻结的小型 Torch timing，省略两项额外成本
campaign。`--python` 默认当前解释器；若当前 Python 未安装 torch，须明确
指定上述数值环境。包装器保留 venv 启动路径，不把 python symlink 解析成
缺少依赖的系统解释器。

新结果位于目标 repo 的
`tools/hcsn/round9_20261031/streaming/evidence/v2/`；顶层
`REPRODUCTION_INPUTS.json`、`REPRODUCTION_RESULT.json` 和
`reproduction-logs/` 记录全部复制身份、命令、输出及原文件未改变检查。
`REPRODUCTION_VALIDATION.json` 记录本次入口验证；复现输入不是新的科学
confirmation 样本。`DELIVERY_MANIFEST.json` 列出本目录需交付文件，排除
pycache 与临时重放目录，并保留 v1 和 amendment。
