# Hepta Continuous Spiking Network: 可复现研究原型

本项目执行了从 He–Xiong 完整金融解析模型，到连续神经元动力学、受控序列任务和真实冻结 encoder 的研究验证。所有已完成实验保留逐种子结果及失败情形。**目前支持“可以构造并训练”，不支持“已经优于普通门控、SNN 或 Transformer”，也没有达到完整 backbone 预训练的证据条件。**

结论与实际数字见 [RESULTS.md](RESULTS.md)。原始论文：[He & Xiong (2012), Rollover Risk and Credit Risk](https://www.princeton.edu/~wxiong/papers/rollover.pdf)。

## 研究分层

| 目录 | 具体内容 | 不能由此推得的结论 |
| --- | --- | --- |
| `analytic/` | 原文债券、股权、违约边界闭式解；独立积分、BVP、PDE；受控域 JAX 自动微分核 | 金融估值本身就是神经时间动力学 |
| `dynamics/` | 连续 Call/Put-inspired 快慢反馈、恢复、耦合、步长与梯度验证 | 任意参数下都是脉冲或都稳定训练 |
| `benchmarks/` | 五种子序列任务；同结构 sigmoid、GRU、Transformer、LIF-SNN；固定 v2 修复 | 大规模语言、全模态或能效优势 |
| `encoder/` | 冻结 MiniLM 与训练集 PCA，只训练 Head；实际 SST 独立数据划分 | encoder 本身被替换，或完整多模态模型已训练 |
| `reference_toy.py` | 保留前一轮简化最优停止模型 | 与完整有限期限 He–Xiong 模型等同 |

原文的 `F,G` 是首达概率和贴现首达概率。原文没有提供第二个自动满足 smooth pasting 的独立 put 神经算子。完整金融式的复现、自动微分核与已训练的简化神经层分别标明；本轮分类准确率来自后者。v2 的边界由输入与记忆计算，不是在每步求解原论文的最优停止边界。

## 复现环境

实际执行环境为 Linux、CPython 3.12.14、8 CPU 配额、8 GiB 内存，没有 GPU。源依赖固定在 `requirements-cpu.txt`；该文件固定主要直接依赖，不是所有操作系统和传递依赖的容器镜像。CPU 运行结果与源码摘要随证据保留。

在本目录创建独立环境后安装依赖：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-cpu.txt
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
```

以下命令会重新生成相应结果文件；需要保留交付证据时先复制项目，或为支持该参数的脚本指定新的输出目录。

### 金融解析与动力学

```bash
python analytic/run_validation.py
python analytic/validate_jax.py
python dynamics/run_validation.py
python dynamics/write_report.py
```

### 序列任务

```bash
python benchmarks/run_benchmarks.py --steps 300 --seeds 5
python benchmarks/validate_models.py
python benchmarks/run_v2.py
python benchmarks/validate_v2.py
python benchmarks/run_v2_reference.py
```

### 冻结 encoder

公开模型和数据下载单独进行，下载地址、revision、SHA 均固定。下载不执行远程仓库代码。当前缓存命中也必须通过六个公开源文件的 SHA 检查。

```bash
python encoder/prepare_features.py --cache /tmp/hcsn-encoder-assets
python encoder/run_heads.py --features /tmp/hcsn-encoder-assets/frozen_features.npz
python benchmarks/run_frozen_v2.py --features /tmp/hcsn-encoder-assets/frozen_features.npz
python benchmarks/validate_snn.py
python benchmarks/run_snn_reference.py
```

SNN 命令所需路径和可选参数以 `--help` 与其目录报告为准。`encoder/audit_heads.py` 专用于交付的 `pre_audit_head_results.json` 和对应检查点；它重放预测、修正校准指标与元数据，不是新的模型训练。源模型权重、数据文本和特征缓存不进入本仓库，提供下载脚本及摘要。保留的是本项目训练的小型 Head 检查点。

## 如何解读证据

- 参数量约匹配，样本、更新次数和 checkpoint 选择规则匹配；没有声称 FLOPs、状态容量或 wall-time 完全相同。
- 五种子标准差只描述初始化及训练差异，不能代表全部数据抽样不确定性；v2/SNN 对同一冻结文本 holdout 的追加分析属于探索性对照。
- 原 `warm_training_seconds` 仅剔除第一次更新，HCSN/sigmoid 第二次更新可能再次 JIT。保留原始字段供审计，禁止据此做模型速度排名。Head 延迟也不含 encoder；进程峰值 RSS 不是单模型内存。
- 文本扰动发生在完整句子编码之后，保留含全句信息的全局 mean 特征。因此不是原始缺字或缺模态实验。
- `backbone_decision.json` 记录本轮未启动完整预训练的实证原因。没有把缺少质量优势的结果扩大为大模型训练。

独立审查见 [dynamics/INDEPENDENT_AUDIT.md](dynamics/INDEPENDENT_AUDIT.md)，修正后的 encoder 指标和修正前记录同时保留。此目录是隔离的研究工具，不改变 Hepta 现有运行时或生产路径。
