# HCSN 本轮证据的恢复与复现

本文件说明如何恢复原始记录、复算结果、重跑指定数值问题，以及单独重训。**恢复已有证据、重新计算统计量、重新执行推理和重新训练是四种不同操作。** 原结果的来源由不可变提交、公开运行编号、发布清单、归档 INDEX 和成员 SHA256 共同确定，不能用任意本地文件的自报哈希代替。

本目录的 [SOURCE_AND_EVIDENCE.json](SOURCE_AND_EVIDENCE.json) 给出最终来源定位和哈希；[FINAL_REPORT_ZH.md](FINAL_REPORT_ZH.md) 给出验收结论。任何重试都使用新的输出目录，保留失败尝试。后续版本应另建实验协议，不能修改本轮门槛后复用原测试结果宣称通过。

## 1. 源码与环境

使用本轮报告对应的仓库提交，保持下列目录的源码完整：

```text
experiments/hcsn_blocker_closure_v1/
experiments/hcsn_conservative_acceleration_v1/
experiments/hcsn_distributional_v2/
experiments/hcsn_free_boundary_v1/
experiments/continuous_spiking_network/
experiments/hcsn_real_av_v1/
```

主要科学执行封存为：

| 对象 | 不可变提交 |
|---|---|
| 444 个内容训练任务及 hosted 数学/native 验证 | `c9063043d088b6b469e740b9b6f341f3faea3928` |
| 90 个真实音视频训练任务 | `6469cc94a72aed214c5c9d2ff2fba14cdb146626` |
| 新演员音视频数据证据 | `dca9febc8143c682077fe27d40dbeaa1137bcaa4` |
| 训练检查点绑定与硬件参考工具的初始完整封存 | `d8b94bd750b4c52bd253b81285acc6c4a2dbeacf` |

独立审计和恢复工具的最终源哈希另列于来源清单。原始训练使用 Python 3.12.14、PyTorch 2.8.0+cpu、NumPy 2.3.5、SciPy 1.17.0；原工作流记录了镜像 digest、4 CPU 配额、8 GiB 内存和无 swap。镜像 digest 的工作流声明不是外部独立硬件证明。

所有命令从仓库根目录执行。CPU 复现时固定线程数：

```bash
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
```

在独立虚拟环境中安装所需依赖；图形重绘还需要 Matplotlib。依赖安装不计入已报告的 worker CPU，安装成本不能被解释为已测得零。CPU 与 CUDA 结果分开记录，不能通过在 CPU 环境中设置名称来生成 GPU 或能耗结论。

## 2. 恢复永久发布的原始证据

Actions 临时下载并非唯一来源。两个完整发布包均以有界分块、成员索引和清单保存在独立证据提交；即使临时 artifact 到期，也可以从固定提交恢复。使用来源清单中的 `evidence.core` 或 `evidence.av`，每个条目含 `commit`、`run_id`、`source_seal`、`publication_path`、`publication_sha256`、`index_path` 和 `index_sha256`。

下面的示例只读取公开的固定提交，下载到新的研究恢复目录，逐一验证每个发布文件。它不会发起新训练：

```python
import json
from pathlib import Path
import subprocess
import sys

package = Path("experiments/hcsn_blocker_closure_v1")
manifest = json.loads((package / "SOURCE_AND_EVIDENCE.json").read_text())
destination = Path("/tmp/hcsn-evidence-replay").resolve()
destination.mkdir(exist_ok=False)
for key in ("core", "av"):
    record = manifest["evidence"][key]
    subprocess.run([
        sys.executable, "-m",
        "experiments.hcsn_blocker_closure_v1.audits.recover_publication",
        "--commit", record["commit"],
        "--receipt-path", record["publication_path"],
        "--receipt-sha256", record["publication_sha256"],
        "--seal", record["source_seal"],
        "--run-id", str(record["run_id"]),
        "--output", str(destination / (key + "_publication")),
        "--audit-output", str(destination / (key + "_download.json")),
    ], check=True)
```

完整解包接口为：

```bash
python -m experiments.hcsn_blocker_closure_v1.evidence restore --index /absolute/core_publication/experiments/hcsn_blocker_closure_v1/artifacts/closure001/INDEX.json --output /absolute/core_restored
python -m experiments.hcsn_blocker_closure_v1.av_evidence restore --index /absolute/av_publication/experiments/hcsn_blocker_closure_v1/av/artifacts/closure001/INDEX.json --output /absolute/av_restored
```

`/absolute/...` 是示例位置，应替换成上一段实际创建的目录。完整解包核对全部分块、整条压缩流、重建的原始清单和每一个成员。成员只能是安全相对路径的普通文件，不能覆盖不同的已有内容。所需空间以清单中的实际压缩／解压字节数为准。

磁盘紧张时，`audits/selective_restore.py` 可以通过 `--select` 或 `--pattern` 只保存需要的成员，并仍检查整条连续 tar.xz 流及所有成员的字节哈希。选择性恢复的回执必须保留实际落盘清单；它不是“全部文件已落盘”。原始压缩分块仍保留完整证据。研究源文件的恢复与运行结果恢复应放在不同目录，避免用归档中的历史文档覆盖现行审计工具。

完整恢复后的主要研究目录分别为：

```text
core_restored/content/results/hosted001/
core_restored/results/hosted001/
av_restored/results/hosted001/
av_restored/results/hosted_driver001/
```

## 3. 独立复算与统计解释

内容结果有两层独立复核：`audits/content_outcome_audit.py` 从全部 worker 及执行账本重算任务矩阵、开发选择、配对差异、区间、符号翻转检验、Holm 校正和成本；`audits/content_raw_metric_replay.py` 从原始 logits、标签和注册数据重新计算准确率、交叉熵、Brier 与 10 箱 ECE。后者不调用原评价函数，也核对标签顺序。

音视频独立复核由 `audits/av_outcome_audit.py` 完成，读取全程结束的公开 run/jobs 回执后才解析正式结果。它重算分类、校准、演员／种子矩阵和注册 bootstrap；成本补充由 `audits/av_outcome_cost_supplement.py` 单独输出，不改变科学门槛。正式运行命令、输入哈希及各输出位置随各审计回执保存；命令行选项可通过相应模块的 `--help` 查看。

原始科学门槛仍以 `content/DESIGN.json` 和 `av/AV_DESIGN.json` 为准。8 个种子不是 8 个独立数据集；音视频测试中的 192 个片段来自 8 个演员，不能作为 192 个独立演员重复。内容的机制检验按事前规定的四个族分别作 Holm 校正，不表示全部机制对比的统一家族错误率控制。音视频的交叉 bootstrap 和单侧 Bonferroni 下界按原实现复算，不因某个区间靠近零而改变通过条件。

原统计分析与图形中的通过字段，表示该项预定门槛是否全部满足。未通过不能改写成证明没有任何效果；点估计为正也不能改写成通过。精确的范围限制见 [统计解释](audits/STATISTICAL_INTERPRETATION_ZH.md)。

## 4. 数学 oracle 与梯度

下面两条命令重算已声明的有限状态问题，不训练内容网络：

```bash
python -m experiments.hcsn_blocker_closure_v1.oracle.audit --output /tmp/hcsn-oracle-replay
python -m experiments.hcsn_blocker_closure_v1.oracle.torch_bridge_tests --output /tmp/hcsn-oracle-gradient-replay
```

每次使用新的输出目录。保留策略迭代、独立 LP、Bellman 收缩残差、展开标签 CTMC、活动集合及有限差分记录。数学正确性只覆盖这些明确的有限问题；旧移动网格边界反例、普通双阈值对照，以及非光滑策略切换都必须保留。

## 5. 训练检查点与真实 native 执行

检查点在结果访问前已指定为 `fixed/selective_copy__value_jg__seed881101`。它不因最终分数优劣被替换。恢复该 worker 的 job、selection、selected_state、两份验证预测，以及训练数组和 PROTOCOL。权重 SHA256 从已经验证的归档成员索引取得。

按照 [执行绑定 README](execution_binding/README.md) 调用 `execution_binding.measure`，显式传入训练提交、协议 SHA 和检查点 SHA。工具重算验证 argmin、核对源码及数据后执行真实原生 owner。需要原有 vendor manifest 对应的 binary；仓库的 `experiments.hcsn_free_boundary_v1.restore_native` 可按封存分块恢复它。

完整外层 `wait4` 记录已经包含解释器、导入、校验、子进程、IPC、状态写入和进程退出。内部 neural/native 计时都是嵌套子集，不能再加到外层 CPU 上。验证内容包括断点续跑、全状态恢复、真实消息干预、KEEP/STOP 和停止后拒绝继续读取；它没有把工程停止目标变成内容分类的最优停止策略。

## 6. 硬件参考测量

按照 [硬件 README](hardware/README.md) 先注册再运行 `hardware.measure`。输入是事先指定的两任务、五模型、首个正式种子的验证选择权重；测量使用验证输入，不使用测试标签。归档 INDEX、协议、预检及每个权重均需外部哈希绑定。

CPU resident 与包含输入／输出复制的端到端时序分开；CUDA 需要设备同步、设备事件和实际可见设备。能量只能来自匹配 GPU UUID 的真实 NVML 累积计数器；无设备、无计数器或计数异常均保留为 null。固定持久神经状态大小不包括权重、输入、输出、临时张量、日志或训练反向图。

注册与测量各使用独立外层 `wait4` 账本。当前 harness 是冻结 FP32 参考实现，未采用专门融合内核或全面硬件调优；其结果不代表所有架构可达到的最优吞吐。

## 7. 单独重训与重绘

重新训练需要新预检、新注册和新的输出路径。内容流程依次为 `content.preflight`、`content.study register`、`run --stage development`、`lock`、`run --stage fixed`、`run --stage equal_cpu`、`analyze`。学习率和等 CPU 组的物理 arm 必须在正式测试前锁定。注册输出必须位于 `experiments/hcsn_blocker_closure_v1/` 下，预检文件必须位于仓库根目录之内；不能复用已有尝试目录。

音视频采用对应的 `av.study` 流程，并额外绑定不可变数据提交和 transport 清单。`av.study register` 实际调用 `git show` 和 `git rev-parse`，所以仅有恢复的数据文件或浅层源码 checkout 不够：本地 Git 对象库必须含有数据提交及其 transport blob。可先获取固定提交：

```bash
git fetch --no-tags https://github.com/TrillionniumFoundation/hepta-private-ci.git dca9febc8143c682077fe27d40dbeaa1137bcaa4
```

注册时必须同时指定 `--dataset /absolute/restored-data/DATASET.json`、`--data-commit dca9febc8143c682077fe27d40dbeaa1137bcaa4`、`--data-transport-path experiments/hcsn_blocker_closure_v1/av/transport_41156412198/TRANSPORT.json`、新预检文件及新输出目录。`DATASET.json` 所在目录必须保留清单规定的全部 15 个文件，完整性和文件集合均被检查。上述本地路线直接使用研究模块，不调用要求真实 hosted 身份和配额的 `av_hosted prepare`。

本地重训记录属于新的本地尝试；不要伪造 GitHub 运行环境变量来冒充原 hosted 执行。原 hosted 资源、镜像及来源约束由两份冻结工作流实现。新硬件、软件或编译优化改变了比较条件，应生成新的记录，并以原研究作为对照。

图形重绘从已完成且完整性通过的两份原始 `ANALYSIS.json` 读取数值：

```bash
python -m experiments.hcsn_blocker_closure_v1.audits.render_results --content-analysis /absolute/core_restored/content/results/hosted001/ANALYSIS.json --av-analysis /absolute/av_restored/results/hosted001/ANALYSIS.json --output /tmp/hcsn-figures-replay
```

输出包含 PNG、SVG 和输入／源文件哈希。图形渲染不增加新的随机种子、显著性检验或实验样本。
