# HCSN v2：恢复、核验与重新运行

本页区分三件事：恢复已发表证据、只读重新分析、在新目录重新做实验。所有已有 `results/*` 及登记协议都保留原样；复跑使用新的协议文件和新的输出目录。命令参数已与本轮实际执行收据及当前 CLI 核对。编写此入口时只做 manifest 列举和小临时 bundle 验证，没有重新解压整个项目或再做训练。

## 1. 环境与目录

本轮核验环境为 Linux、Python 3.12.14、CPU PyTorch。固定依赖见 [requirements-cpu.txt](requirements-cpu.txt)：

| 依赖 | 版本 |
| --- | --- |
| torch | 2.8.0+cpu |
| numpy | 2.3.5 |
| scipy | 1.17.0 |
| mpmath | 1.3.0 |
| matplotlib | 3.10.8 |

以下以当前 checkout 根为工作目录。原生 research host 为随仓库保存并校验身份的 Linux 可执行文件；本页没有重新编译、GPU 或硬件能耗复现步骤。恢复脚本本身只依赖 Python 标准库；数值测试、分析和训练才需要上述数值环境。

```bash
cd /path/to/hepta-private-ci
HCSN_ROOT="$(pwd -P)"
HCSN_V2="$HCSN_ROOT/experiments/hcsn_distributional_v2"
HCSN_RAW_ROOT="$HCSN_ROOT/../hcsn_original_sources"
HCSN_RUN_ROOT="$HCSN_V2/reruns/local_001"

python3.12 -m venv "$HCSN_ROOT/../hcsn_cpu_venv"
source "$HCSN_ROOT/../hcsn_cpu_venv/bin/activate"
python -m pip install -r "$HCSN_V2/requirements-cpu.txt"

export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
mkdir -p "$HCSN_RUN_ROOT"
```

`HCSN_RUN_ROOT` 每次应使用新名字；不要把它设成已有研究目录。已有 session 使用专门的 CPU dependency 目录并通过 `PYTHONPATH` 接入；新 checkout 用上述虚拟环境即可，不需要复制历史环境的绝对路径。

历史 `command`、`request.data`、日志和收据中的绝对路径，是当时执行的原始记录，不应批量替换后重新称为同一证据。当前代码的 `ROOT/PACKAGE` 由源文件位置确定；注册的数据和依赖通过仓库相对路径重新定位。移动 checkout 后使用本页的当前路径和新运行身份，不能直接执行旧收据中的绝对命令，也不能把旧中途 checkpoint 的路径绑定当成已经迁移成功。

## 2. 自动发现并恢复证据

入口为 [restore_artifacts.py](restore_artifacts.py)，复用冻结的 [v1/archive.py](../hcsn_free_boundary_v1/archive.py) streaming pack/restore 合同。

### 2.1 先列目录

```bash
python -m experiments.hcsn_distributional_v2.restore_artifacts list \
  --raw-root "$HCSN_RAW_ROOT"

python -m experiments.hcsn_distributional_v2.restore_artifacts list --only-v2
```

`list` 不解压 tar parts，不验证压缩载荷。它列出输入 manifest SHA256、成员数、压缩大小和实际目标目录，并检查声明的成员路径、parts 是否存在以及跨 bundle 的不同内容冲突。省略原始数据路径时，完整目录中的 raw 目标显示为空；这不授权程序自行猜测 raw-root。

v2 自动扫描 `artifacts/**/*.json`，只接受顶层 `schema="hcsn-evidence-bundle.v1"` 的 manifest。普通执行收据不属于 bundle；以后增加 main-content 或 LIF bundle 时，不需要改动恢复脚本中的名字列表。所有 v2 成员均相对于 **v2 包根**解释。

### 2.2 全量或仅 v2 恢复

```bash
python -m experiments.hcsn_distributional_v2.restore_artifacts restore \
  --raw-root "$HCSN_RAW_ROOT"

# v1 与原始数据已经恢复时，才只做 v2：
python -m experiments.hcsn_distributional_v2.restore_artifacts restore --only-v2
```

完整恢复必须显式提供 `--raw-root`。五种 v1 manifest 的根不同：

| v1 artifacts 中的 manifest | 正确 destination | 成员路径例子 |
| --- | --- | --- |
| `original_data.json` | CLI 的 `--raw-root` | `mnist/...`、`fsdd/recordings/...` |
| `auxiliary_evidence.json` | `experiments/hcsn_free_boundary_v1` | `data/native003/...`、`results/...` |
| `study001_evidence.json` | `experiments/hcsn_free_boundary_v1` | `results/study001/...` |
| `conditional001_evidence.json` | `experiments/hcsn_free_boundary_v1` | `results/conditional001/...` |
| `equal_updates_core002_evidence.json` | `experiments/hcsn_free_boundary_v1/results/equal_updates_core002` | `ANALYSIS.json` 等直接位于该诊断根的文件 |

不要把最后一种也恢复到 v1 包根，否则会丢失它应有的目录层级。辅助 bundle 还包含主任务执行需要排除的 native003 历史图像身份；不能只恢复选中的模型权重而遗漏这些依赖。

实际恢复沿用旧实现：逐 part、整个压缩流和每个文件校验 SHA；拒绝不安全路径；已有相同内容验证后复用；已有不同内容报错，不覆盖。恢复以成员为单位验证和写入，后面失败不会删除前面已验证恢复的文件。再次运行仍按内容身份处理，不会默默重置研究目录。

每次调用创建独立收据目录，默认位于 `v2/reproduction_receipts/<UTC>_<id>`；可用 `--receipt-dir NEW_DIRECTORY` 指定新位置。在 `experiments/` 内只允许该独立 receipts 区域，禁止把新收据写入 sealed 的 `results`、`data` 或 `artifacts`。收据包含：

- `CATALOG.json`、`PLAN.json`：输入 manifest SHA、实际目标目录、实现 SHA 与操作范围。
- `source/`：此次恢复入口及所调用旧 archive 的精确源副本。
- `BUNDLE_RECEIPTS.json`：每个 bundle 的恢复/复用结果；逐 bundle CPU 是嵌套明细。
- `WORKER_EXECUTION.json`：`wait4` 计量完整 worker，包含导入、校验、解压、写入与退出。
- `EXECUTION.json`：whole-parent self CPU 和 worker CPU；两者相加一次，不再加逐 bundle 明细。

如果发布目录尚无某个完整 manifest，自动发现不会凭名字推测其内容。恢复后运行下面依赖它的分析器时，需要先确认相应研究已经完整交付。

## 3. 数学与实现测试

先恢复依赖，再把数值审计写到新的目录：

```bash
python -m experiments.hcsn_distributional_v2.kernel_tests \
  --output "$HCSN_RUN_ROOT/kernel_audit"

python -m experiments.hcsn_distributional_v2.grid_control_tests \
  --output "$HCSN_RUN_ROOT/grid_control_audit"

python -m unittest -v \
  experiments.hcsn_distributional_v2.model_tests \
  experiments.hcsn_distributional_v2.content_tests \
  experiments.hcsn_distributional_v2.task_value_tests \
  experiments.hcsn_distributional_v2.task_value_execution_tests \
  experiments.hcsn_distributional_v2.runtime_tests

python -m experiments.hcsn_distributional_v2.content_domain_preflight \
  --output "$HCSN_RUN_ROOT/domain_preflight.json"
```

kernel 和 finite-control 审计包含独立参考、局部梯度和小性能探针，不是内容大模型训练。`content_tests` 包含小型训练/计时/停止回归；它不是正式 176-search 矩阵。任务 oracle 的独立二元历史树、收益分解和梯度核对由 `task_value_tests` 覆盖。

数学审计报告中的 body/self 时间与完整外层进程时间具有不同范围。若要把新审计算入总研究成本，应另用进程级计量包住调用；不要把内部 probe 和包含它的整次审计 CPU 相加。

## 4. 已发表内容矩阵的只读主分析

完整恢复 `results/content002` 之后，可以新建分析目录重新核对原始预测、选择锁、参数更新、固定预算检查和原登记比较：

```bash
python -m experiments.hcsn_distributional_v2.content_analysis \
  --protocol "$HCSN_V2/CONTENT002_PROTOCOL.json" \
  --study "$HCSN_V2/results/content002" \
  --output "$HCSN_RUN_ROOT/content_analysis_original"
```

该命令分析已存在的研究，不重新训练或选择另一 checkpoint。应先有完整成功的 `COMPLETE.json` 与全部登记 jobs；缺失或失败的原始记录不能用重复训练覆盖，也不能用一个较小的完成子集冒充完整矩阵。

## 5. 在新目录重新登记并训练

下面是完整内容研究的**新执行**。既有 `content001` abort 收据和固定 `content_domain_preflight003.json` 是该版本注册器的历史依赖，需要从交付包恢复；前节新运行的 preflight 不用于覆盖这两个历史记录。

```bash
HCSN_CONTENT_PROTOCOL="$HCSN_RUN_ROOT/CONTENT_REPRO_PROTOCOL.json"
HCSN_CONTENT_STUDY="$HCSN_RUN_ROOT/content_repro"

python -m experiments.hcsn_distributional_v2.content_study register \
  --protocol "$HCSN_CONTENT_PROTOCOL" \
  --output "$HCSN_CONTENT_STUDY" \
  --cpu-seconds 60 --mechanism-seeds 8 --workers 5

# 保存唯一的 CONTENT*PROTOCOL.json 副本，后续 runtime 绑定需要它。
mkdir "$HCSN_CONTENT_STUDY/source"
cp "$HCSN_CONTENT_PROTOCOL" \
  "$HCSN_CONTENT_STUDY/source/CONTENT_REPRO_PROTOCOL.json"

python -m experiments.hcsn_distributional_v2.content_study run \
  --protocol "$HCSN_CONTENT_PROTOCOL" \
  --output "$HCSN_CONTENT_STUDY"

python -m experiments.hcsn_distributional_v2.content_analysis \
  --protocol "$HCSN_CONTENT_PROTOCOL" \
  --study "$HCSN_CONTENT_STUDY" \
  --output "$HCSN_RUN_ROOT/content_analysis_repro"
```

这套参数对应176个 model/task/seed search，每个 search 完成两组学习率，各用60训练 CPU 秒上限；完整 optimizer update 的越界费用仍记录。原代码保留研究配方名称 `content002`，新协议文件、登记哈希和输出目录区分新的执行身份。

CPU 预算门受硬件与负载影响，同一 seed 也不保证达到完全相同的更新数、选中步或最终权重。已存证据可以逐字节恢复；新 CPU-budget 训练属于复现实验协议，不能承诺逐字节重造训练结果。此处使用已披露的相同数据，不能再称为未观察的新测试。

## 6. 任务 oracle、联合任务头和真实 v1 owner 活动

完整任务活动入口已经包含准备、精确 oracle 预检、TRAIN teacher、两个同参数头的全部候选、VAL 选择锁、缓存反事实、真实 owner、跨进程恢复和最终审计：

```bash
python -m experiments.hcsn_distributional_v2.task_value_campaign \
  --output "$HCSN_RUN_ROOT/task_value_repro" \
  --raw-root "$HCSN_RAW_ROOT" \
  --prior-attempt "$HCSN_V2/results/task_value001"
```

`--prior-attempt` 在此引用已保留的首次失败费用，不会再次执行那个失败。新活动仍使用冻结的 v1 MNIST backbone 和同一确定性图像集合，不能把它的内容结果归给 v2 分布模型。

该外层 campaign 使用 `wait4` 包含所有已等待的 worker/native 后代；phase 和 owner 收据为其中明细，不重复累加。它会自动调用报告器；不要在同一目录重复运行报告器去覆盖原报告。

若只要复核已存首发未来值与后来实际净收益，不需要再运行活动：

```bash
python -m experiments.hcsn_distributional_v2.task_future_calibration \
  --source "$HCSN_V2/results/task_value002" \
  --v2-source "$HCSN_V2/results/distributional_native001" \
  --output "$HCSN_RUN_ROOT/future_calibration_repro"
```

它只读已有逐 stream 数据，不新增神经推理、训练或 DP 求解。

## 7. Runtime 与已训练 v2 的实际 owner

默认复用已发表、成功完成的 MNIST checkpoint。也可把 `HCSN_BACKBONE_RUN` 改成第五节新研究中同名 job 的目录；必须已经成功结束并有全部身份文件和唯一协议 snapshot。

```bash
HCSN_BACKBONE_RUN="$HCSN_V2/results/content002/runs/mnist__distribution_free_dual__9201"

python -m experiments.hcsn_distributional_v2.runtime_eval run \
  --output "$HCSN_RUN_ROOT/runtime_repro" \
  --checkpoint-run "$HCSN_BACKBONE_RUN"

python -m experiments.hcsn_distributional_v2.distributional_native_smoke \
  --output "$HCSN_RUN_ROOT/distributional_native_repro" \
  --backbone-run "$HCSN_BACKBONE_RUN"
```

`--checkpoint-run` 接收成功训练目录，不能传任意同形状 NPZ 来代替。它绑定 summary、selection、IDENTITY、EXECUTION、协议、完整物理配置和权重。runtime 包含完整 optimizer update 微基准和新 Python 恢复，不声称等质量吞吐或能耗优势。

native 工程活动用该 v2 的64张原 TRAIN 图像拟合观察模型、六张原 VAL 图像组成两个任务流，实际操作 owner 并测试活动/quiet 的新进程恢复。这是执行工程证据，不能重命名为新总体质量测试。程序自行调用已校验的旧 `restore_native` 恢复相同 research host；其原始二进制和权限合同保持不变。

## 8. LIF SNN 补充研究

源 CLI 已冻结，补充结果应只在该研究完整完成后分析。已有研究仍在运行时，不得把以下命令指向它的输出目录。只读分析现有完整补充：

```bash
python -m experiments.hcsn_distributional_v2.lif_supplement_analysis \
  --protocol "$HCSN_V2/LIF_SUPPLEMENT001_PROTOCOL.json" \
  --study "$HCSN_V2/results/lif_supplement001" \
  --output "$HCSN_RUN_ROOT/lif_analysis_original"
```

如果确需重新训练补充组，则另取新协议和新目录：

```bash
python -m experiments.hcsn_distributional_v2.lif_supplement preflight \
  --output "$HCSN_RUN_ROOT/lif_preflight"

python -m experiments.hcsn_distributional_v2.lif_supplement register \
  --protocol "$HCSN_RUN_ROOT/LIF_REPRO_PROTOCOL.json" \
  --output "$HCSN_RUN_ROOT/lif_repro" \
  --preflight "$HCSN_RUN_ROOT/lif_preflight/RESULTS.json"

python -m experiments.hcsn_distributional_v2.lif_supplement run \
  --protocol "$HCSN_RUN_ROOT/LIF_REPRO_PROTOCOL.json" \
  --output "$HCSN_RUN_ROOT/lif_repro"

python -m experiments.hcsn_distributional_v2.lif_supplement_analysis \
  --protocol "$HCSN_RUN_ROOT/LIF_REPRO_PROTOCOL.json" \
  --study "$HCSN_RUN_ROOT/lif_repro" \
  --output "$HCSN_RUN_ROOT/lif_analysis_repro"
```

该冻结补充的 parent 固定为 `CONTENT002_PROTOCOL.json` 和 `results/content002`，复用其18个 free-dual search；CLI 没有更换 parent 的参数。上述新 LIF 运行也不会自动改成与第五节新训练的 free-dual 配对。补充的两学习率、15/30/60 CPU 选择门和单 worker 调度来自该固定 parent 合同，不改原176-job矩阵或原统计门。

## 9. 本交付入口的实际验证范围

[reproduction_receipts/list001](reproduction_receipts/list001) 保存了对当时已发布五个 v1、三个 v2 manifest 的实际目录列举。以后 bundle 数增多是自动发现的正常结果，不要求始终等于八。

[reproduction_receipts/restore_smoke001](reproduction_receipts/restore_smoke001) 仅构造很小的临时 bundle，实际验证五种 v1 目标、v2 包根目标、只列举不解压、相同内容复用、不同已有内容拒绝且保留、显式 raw-root、拒绝 sealed 收据位置，以及后来新增的嵌套 v2 manifest 自动发现。测试脚本、预期失败日志、实现快照和完整外层 CPU 收据均保留。

这项入口验证没有重新恢复大型项目 bundle，没有运行本页的训练命令，也没有改变已有研究结果。恢复后的完整性依赖归档 SHA，科学结论与验收范围仍应按 [CONTRACT.md](CONTRACT.md)、[MATH.md](MATH.md)、[TASK_VALUE.md](TASK_VALUE.md) 和各独立报告阅读。
