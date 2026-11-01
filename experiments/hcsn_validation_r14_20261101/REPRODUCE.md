# R14 证据恢复与复现

从本研究分支的完整 checkout 操作。实际执行环境为 Python **3.12.14**、CPU PyTorch **2.8.0+cpu**、NumPy **2.3.5**、SciPy **1.17.0**、ncps **1.0.1**、mpmath **1.3.0**、Matplotlib **3.10.8**。源冻结还核对 ncps/CfC 文件身份。原始结果与新尝试的目录必须分开。

所有命令从仓库根执行。示例临时目录必须不存在；如果已经存在，选择新的名字，不删除已有证据。恢复器先核对容器、解压结果、tar 与每个成员的大小和 SHA256，再恢复文件。`merge_verified.py` 只补充缺失文件，接受相同字节，拒绝覆盖不同既有内容。

## 1. 准备运行环境

在独立的 Python 3.12.14 环境中安装本轮实际版本：

```bash
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r experiments/hcsn_validation_r14_20261101/requirements-cpu.txt
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
```

设备不同可能改变计时和浮点行为；冻结模型与数值误差要求仍按原协议检查。物理能耗在本次机器上不可用，不用估计功率补成焦耳。

## 2. 恢复继承的内容模型输入

这个输入包包含 96 个候选 fit 和六个 donor 的 selected checkpoint、旧源码与三个 manifests、数据身份、全部旧预测和训练进程账。新内容研究所用 48 个 joint checkpoint 都在其中，不另行复制一套训练成本。

```bash
python experiments/hcsn_validation_r14_20261101/cost/package_results.py \
  --restore-index experiments/hcsn_validation_r14_20261101/cost/archives/inputs_01/INDEX.json \
  --output /tmp/hcsn-r14-inputs-reconstructed
python experiments/hcsn_validation_r14_20261101/publication/merge_verified.py \
  --source /tmp/hcsn-r14-inputs-reconstructed \
  --destination .
```

合并前会检查全部目标冲突，拒绝把不同来源文件静默覆盖为当前版本。原始选择清单为 [INHERITED_INPUT_FILES.json](cost/INHERITED_INPUT_FILES.json)。

## 3. 恢复三套完整结果

数值线的原始 NPZ 本身已满足单文件大小限制，直接保留在 Git 文件树中。其余三套证据按以下顺序恢复：

```bash
python experiments/hcsn_validation_r14_20261101/cost/package_results.py \
  --restore-index experiments/hcsn_validation_r14_20261101/cost/archives/publication_01/INDEX.json \
  --output /tmp/hcsn-r14-cost-reconstructed
python experiments/hcsn_validation_r14_20261101/publication/merge_verified.py \
  --source /tmp/hcsn-r14-cost-reconstructed \
  --destination experiments/hcsn_validation_r14_20261101/cost
python experiments/hcsn_validation_r14_20261101/value/publication/pack.py restore
python experiments/hcsn_validation_r14_20261101/content/publication/pack.py restore
```

恢复后，逐 worker 的原始记录、NPZ、checkpoint、日志、源快照、独立审计和开发失败均位于原 manifest 中的相对路径。较大的 `content/results/formal_01/RESULTS.json` 与 4.79 MB 独立审计原件也在归档内；直接可读的 `RESULTS_COMPACT.json` 保留全部关键汇总，没有用它替换原始数据。

已完成的新目录恢复证据：

- [继承输入与成本重建](cost/archives/RECONSTRUCTION_VERIFICATION.json)
- [value 完整恢复](value/publication/RESTORE_CHECK.json)
- [content 完整恢复](content/publication/FRESH_RESTORE_VERIFICATION.json)

## 4. 在新目录运行科学尝试

以下命令沿用冻结源码和输入；所有输出目录必须是新目录。开发失败与原确认目录保留，不在原目录上覆盖重跑。

### 数值线

```bash
python -B experiments/hcsn_validation_r14_20261101/numerics/launch.py \
  --out experiments/hcsn_validation_r14_20261101/numerics/results/reproduction_02
```

其余公式、拒绝域、分段、切线与连续误差含义见 [数值 README](numerics/README.md)。

### 实际后续 Qπ

```bash
python -B -m experiments.hcsn_validation_r14_20261101.value.run run \
  --out experiments/hcsn_validation_r14_20261101/value/evidence/reproduction_02
python -B -m experiments.hcsn_validation_r14_20261101.value.rollout_repair.run run \
  --out experiments/hcsn_validation_r14_20261101/value/rollout_repair/evidence/reproduction_02
```

已有两套 SOURCE_FREEZE 不重建。第一项覆盖全部实际到访前缀和强制首动作的完整后续；第二项包含 96 个实际进程和 16 个完整时钟进程。见 [实际 Qπ README](value/README.md) 与 [修复 README](value/rollout_repair/README.md)。

### 内容完整后端冻结／共同训练

```bash
python -B -m experiments.hcsn_validation_r14_20261101.content.study freeze \
  --output experiments/hcsn_validation_r14_20261101/content/results/reproduction_02
python -B -m experiments.hcsn_validation_r14_20261101.content.launch train \
  --output experiments/hcsn_validation_r14_20261101/content/results/reproduction_02
python -B -m experiments.hcsn_validation_r14_20261101.content.study candidates \
  --output experiments/hcsn_validation_r14_20261101/content/results/reproduction_02
python -B -m experiments.hcsn_validation_r14_20261101.content.launch evaluate \
  --output experiments/hcsn_validation_r14_20261101/content/results/reproduction_02
python -B -m experiments.hcsn_validation_r14_20261101.content.evaluate summarize \
  --output experiments/hcsn_validation_r14_20261101/content/results/reproduction_02
python -B experiments/hcsn_validation_r14_20261101/content/review/audit_results.py \
  --output experiments/hcsn_validation_r14_20261101/content/results/reproduction_02 \
  --report experiments/hcsn_validation_r14_20261101/content/results/reproduction_02/review/INDEPENDENT_RESULTS_AUDIT_01.json
```

训练后、留出集前冻结全部候选，不能先看测试结果再改 seed、学习率、更新步数、费用或选模规则。三种继承 fit 仍为三个单位；同权重 joint 执行消融的估计量见 [内容 README](content/README.md)。

### 全域完整模型成本

```bash
python -B -m experiments.hcsn_validation_r14_20261101.cost.study prepare \
  --output experiments/hcsn_validation_r14_20261101/cost/results/reproduction_03
python -B -m experiments.hcsn_validation_r14_20261101.cost.study run \
  --output experiments/hcsn_validation_r14_20261101/cost/results/reproduction_03
python -B -m experiments.hcsn_validation_r14_20261101.cost.study summarize \
  --output experiments/hcsn_validation_r14_20261101/cost/results/reproduction_03
python -B -m experiments.hcsn_validation_r14_20261101.cost.audit \
  --output experiments/hcsn_validation_r14_20261101/cost/results/reproduction_03
```

保持 720 个 worker 串行；运行时避免同时安排本项目其他训练或压缩。测量含义、共享主机限制、历史训练跨时段摊销、首批计时及整批请求数约束见 [成本 README](cost/README.md)。

## 5. 核验与费用解释

所有原始进程回执保留完整退出码、CPU、墙钟、RSS 和不可用的焦耳。独立结果审计覆盖保存的证据和算术，不冒称重新训练或重新执行全部期望树。各完整子进程已包含嵌套 forward/actor 阶段；复核和归档的费用另列，不重复加总。源码修复、失败尝试和新的冻结目录均作为证据保留。

本次只增加 Python 研究与证据目录，没有改 Rust 网络或生产激活配置。仓库整体 Rust 构建／GPU 路径未在当前 CPU 环境运行；本报告不声称那些检查已通过。
