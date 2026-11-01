# HCSN R13 复现说明

本页从一个新的仓库副本开始，恢复归档输入和结果，检查冻结身份，再给出各项复跑命令。
所有命令均在**仓库根目录**执行。本文是追加的复现说明，不属于已经冻结的科学源码。

| 身份 | 固定值 |
| --- | --- |
| 仓库 | `TrillionniumFoundation/hepta-private-ci` |
| 结果发布分支 | `research/hcsn-state-action-cost-r13-20261031` |
| R13 科学源码提交 | `04436032a808a5a1bbda10a66e487a32b8c654ff` |
| 继承的 R12 提交 | `1eb979ff62499abf82118b6a4196c44324c11242` |
| 实验目录 | `experiments/hcsn_validation_r13_20261031` |

科学源码冻结提交先于结果和归档发布。应使用包含两个归档和真实读取收据的**结果发布分支**，
再按下述 SHA256 检查其科学源码。不要在克隆后直接切回科学源码提交并期待后续生成的
archives、publication receipts 和结果也已存在于那个较早提交中。

## 1. 取得一个新的工作副本

下面的稀疏检出包含本轮和两个继承研究目录，不需要构建整个 Rust 工作区：

```bash
git clone --filter=blob:none --sparse --single-branch \
  --branch research/hcsn-state-action-cost-r13-20261031 \
  https://github.com/TrillionniumFoundation/hepta-private-ci.git hepta-hcsn-r13-reproduce
cd hepta-hcsn-r13-reproduce
git sparse-checkout set \
  experiments/hcsn_validation_r13_20261031 \
  experiments/hcsn_validation_r12_20261031 \
  experiments/hcsn_regeneration_content_20261031
git rev-parse HEAD
```

保留最后显示的实际结果发布提交。后续科学身份检查仍针对上表中的固定源提交。
如果已使用完整的新克隆，可以直接从仓库根目录继续。

## 2. 固定执行环境

实际记录的解释器是 **CPython 3.12.14，Linux x86-64**。完整费用收据使用 Linux `wait4`；
数值启动器还使用 `fork` 和资源限制。本页的测试、数值验证、价值任务与成本重算只需要
NumPy／SciPy／Matplotlib 及下列固定依赖，不执行 R12 的 Torch 内容训练。

使用独立环境，不向 `PYTHONPATH` 添加其他项目副本：

```bash
python3.12 -m venv .venv-hcsn-r13
. .venv-hcsn-r13/bin/activate
python -m pip install \
  numpy==2.3.5 scipy==1.17.0 matplotlib==3.10.8 \
  contourpy==1.3.3 cycler==0.12.1 fonttools==4.61.1 \
  kiwisolver==1.4.9 packaging==26.3 pillow==12.3.0 \
  pyparsing==3.3.2 python-dateutil==2.9.0.post0 six==1.17.0
export PYTHONPATH=""
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
python -B - <<'PY'
import importlib.metadata as metadata
import platform
assert platform.python_version() == "3.12.14", platform.python_version()
for name in ("numpy", "scipy", "matplotlib"):
    print(name, metadata.version(name))
print(platform.platform())
PY
```

若使用已有隔离依赖目录，可以将 `PYTHONPATH` 仅设为该目录；仓库根目录由 `-m` 或本页
脚本自行加入。记录实际版本与路径，不借用另一个原始项目目录来满足缺失的研究模块。
已完成的最小树检查使用了这一方式，具体环境见 `RECONSTRUCTION_CHECK.json`。

固定包版本不会使不同 CPU、BLAS 构建、操作系统和共享宿主上的时延自动相同。
数值通过条件以冻结容差为准；逐字节相同是已记录执行环境下的额外观察。

## 3. 依次恢复输入归档和结果归档

归档路径是仓库相对路径，所以两次恢复的目标都必须是仓库根目录 `.`：

```bash
python -B experiments/hcsn_validation_r13_20261031/evidence.py restore \
  --index experiments/hcsn_validation_r13_20261031/archives/inputs/INDEX.json \
  --destination .
python -B experiments/hcsn_validation_r13_20261031/evidence.py restore \
  --index experiments/hcsn_validation_r13_20261031/archives/results/INDEX.json \
  --destination .
```

`INDEX.json` 邻接的所有 `evidence.tar.gz.partNNNN` 都必须保留原文件名。
恢复工具按清单验证每个分片、拼接归档和每个成员的大小与 SHA256，并拒绝符号链接、
不安全路径、缺失成员，以及覆盖不同内容。同字节的已有文件可以再次校验。

输入归档含 **1,934 个文件、41,569,249 个未压缩成员字节**。结果归档的准确成员数和大小
以其 `INDEX.json` 及实际恢复回执为准。两者都完成后，应能读取下面的真实记录：

- `SOURCE_PUBLICATION_READBACK.json`；
- `value/SOURCE_FREEZE.json` 和 `value/SOURCE_PUBLICATION_READBACK.json`；
- `numerics/results/formal_01/FREEZE.json`。

以上四个文件的短路径均相对 R13 实验目录。R12 内容预测和进程收据则恢复到仓库级路径
`experiments/hcsn_validation_r12_20261031/content/results/formal001/`，其他继承源码和候选位于
各自的 R12 或 `experiments/hcsn_regeneration_content_20261031/` 目录，不位于 R13 内。

缺文件或遇到不同内容时，应核对发布分支、归档清单和
目标目录；不要通过改写 freeze、重新生成 publication receipt 或覆盖原结果来消除身份错误。

### 已有文件的完整冲突核对

已对输入归档与固定 R12 基线 `1eb979ff62499abf82118b6a4196c44324c11242` 做完整路径核对：
先逐层读取 root 和 experiments 的 Git tree，再只对两个相关研究目录请求完整递归 tree，
两个响应均为 `truncated=false`。每个归档文件先核对归档 SHA256 和字节数，再计算其 Git blob
SHA，与同路径的远端 tree 记录比较，同时检查文件／目录／符号链接冲突。

| 输入所在目录 | 远端已有且字节身份相同 | 远端不存在、恢复时新增 | 不同内容或结构冲突 |
| --- | ---: | ---: | ---: |
| `hcsn_regeneration_content_20261031` | 82 | 0 | 0 |
| `hcsn_validation_r12_20261031` | 43 | 1,808 | 0 |
| R13 的 `LOCAL_INPUT_MANIFEST.json` | 0 | 1 | 0 |
| 合计 | **125** | **1,809** | **0** |

因此全部 **1,934** 个输入归档路径均已覆盖，相对于这个固定基线无需覆盖任何不同内容。
`BASELINE_READBACK.json` 中的两个已知本地差异——R12 `value/README.md` 和
`content/audit_results.py`——**都不在输入归档内**，恢复不会用本地后续版本替换克隆中的文件。
详细树身份和逐项结果见 `review/INPUT_REMOTE_TREES.json` 与
`review/INPUT_RESTORE_CONFLICT_CHECK.json`；本核对不需要运行科学实验。

这项结论针对已指定的固定基线，不覆盖用户另行改动的工作目录。出现冲突时继续保留原克隆
文件与冻结输入，并换用新的副本。若需要完全独立的空目录实验树，可采用
`RECONSTRUCTION_CHECK.json` 已记录的方式：将两个归档恢复到空根目录，再按其中
`added_sources` 明示清单补齐并验证 33 个源文件／读取收据；不修改原克隆。随后从这个新根
目录执行本页的身份检查和复跑命令。科学源码和原始结果始终保持原身份。

## 4. 先验证源码和 publication 身份

先检查 29 个已发布文件和原数值执行涉及的 8 个直接源码／协议文件：

```bash
python -B - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path.cwd()
base = root / "experiments/hcsn_validation_r13_20261031"
publication = json.loads((base / "SOURCE_PUBLICATION_READBACK.json").read_text())
assert publication["verified"] is True
assert publication["commit_sha"] == "04436032a808a5a1bbda10a66e487a32b8c654ff"
for entry in publication["files"]:
    actual = hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()
    assert actual == entry["sha256"], entry["path"]
numeric = json.loads((base / "numerics/results/formal_01/FREEZE.json").read_text())
for name, expected in numeric["source_sha256"].items():
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    assert actual == expected, name
print("Published files verified:", len(publication["files"]))
print("Numerical execution sources verified:", len(numeric["source_sha256"]))
PY
```

随后执行 7 项行为测试，再运行价值任务加载器的完整 publication 检查：

```bash
python -B -m experiments.hcsn_validation_r13_20261031.value.tests -v
python -B - <<'PY'
from experiments.hcsn_validation_r13_20261031.value.run import verify
record = verify(publication=True)
print("Value sources:", len(record["source_sha256"]))
print("Inherited inputs:", len(record["inherited_input_sha256"]))
PY
```

已记录检查结果为 **7/7 测试通过，10 个 value 源文件和 107 个继承输入身份通过**。
此处复用已发布的 `value/SOURCE_FREEZE.json`。**复现时不要运行 `value.run freeze`**：
该命令是最初注册新候选时使用的写入流程，现有 freeze 和 readback 必须保持原身份。

## 5. 数值套件复跑

使用新输出目录；下列目录及同名 `.stdout.log`／`.stderr.log` 均不得已存在：

```bash
python -B experiments/hcsn_validation_r13_20261031/numerics/launch.py \
  --out experiments/hcsn_validation_r13_20261031/numerics/results/reproduction_numerics_01 \
  --stage formal \
  --frozen-commit 04436032a808a5a1bbda10a66e487a32b8c654ff
```

该命令执行全部连续年龄参考、三网格检查、分段恢复、两个新进程恢复与负对照。
启动器限制单线程、512 MiB 地址空间和 120 CPU 秒。新的输出目录保留源码快照、所有原始
状态、`cases.jsonl`、`SUMMARY.json`、`FAILURES.json` 和 `PROCESS_RECEIPT.json`。

预期分组是 **80 行：68 项普通验收通过、12 项故意损坏状态的等价检查失败**，另外的检测行
确认这些损坏已被识别。不能将 12 个保留负例改写成通过来得到“80/80”。

`--stage formal` 选择已注册完整协议；复跑相同的确定性参数与候选不会产生新科学样本。
同网格分段逐位相等和对连续过程的三网格逼近是两类不同检查。

## 6. 价值任务完整复跑

如果需要完整重新执行 24 个既有 family × seed × configuration 案例，使用新的价值输出
目录，并保留前述冻结来源和六个继承模型：

```bash
python -B -m experiments.hcsn_validation_r13_20261031.value.run supervise \
  --out experiments/hcsn_validation_r13_20261031/value/evidence/reproduction_value_01
```

真实参数名是 `--out`。目录必须位于 R13 `value/` 内，且尚未存在。监督器把日志和完整费用
回执写到 **value 根目录**，本例为：

- `value/reproduction_value_01_STDOUT.log`；
- `value/reproduction_value_01_STDERR.log`；
- `value/reproduction_value_01_PROCESS.json`。

案例原始状态、配对动作轨迹、强制首动作轨迹、结果及汇总在
`value/evidence/reproduction_value_01/`。失败时保留 `FAILURE.json`；下一次尝试换一个新名称，
包括上面三个监督器文件的 basename，不覆盖失败尝试。

这会重执行已经规定且已曝光的配置；不会训练新内容模型、重新拟合控制器或增加独立 seed。
原始 `confirmation_01` 是其当时冻结后的首次执行；后来复跑这些同一对象应标为复现。
本次最小树重建检查只执行了 7 项测试、publication 验证和数值套件，**没有再次执行这 24 案例**。

## 7. 成本与质量独立重算

成本模块首先为新的历史重分析目录写入精确输入／源清单，然后执行重算。两个命令的
`--output` 必须相同；第一次 `freeze` 前目录不能存在，第二次 `run` 使用它刚创建的目录：

```bash
python -B -m experiments.hcsn_validation_r13_20261031.cost.audit freeze \
  --output experiments/hcsn_validation_r13_20261031/cost/results/reproduction_cost_01
python -B -m experiments.hcsn_validation_r13_20261031.cost.audit run \
  --output experiments/hcsn_validation_r13_20261031/cost/results/reproduction_cost_01
```

这里的 `cost.audit freeze` 为**新的重分析输出**生成 manifest，不会改写价值或数值科学 freeze。
重算使用已有 96 个候选的 720 份原始预测表，检查 295 份进程收据并输出 CSV、描述性 Pareto
和训练摊销图。它不重新执行模型或训练，不能标为新留出确认。

295 份收据分为 102 个训练任务、96 个评估、96 个 profile 和 1 个独立历史审计。
历史审计的 `4.6045 CPU s` 单列，不进入候选训练摊销。原失败 `historical_001` 和修复后
成功的 `historical_002` 都应保留。stress 域没有独立 profile 时，域推理成本维持空值。

## 8. 如何读取和累计费用

| 工作 | 完整费用记录 | 不能再次相加的内层记录 |
| --- | --- | --- |
| 数值复跑 | 新输出目录的 `PROCESS_RECEIPT.json` | 内部阶段 CPU、已等待的恢复子进程 CPU |
| 价值完整复跑 | `value/<输出目录名>_PROCESS.json` | `PROCESS_BODY.json`、actor／phase／案例时间 |
| 成本重分析 | 新输出目录的 `ANALYSIS_PROCESS_RECEIPT.json` | 原 R12 训练／评估／profile 收据不属于本次重分析进程 |
| 最小树检查 | `RECONSTRUCTION_CHECK.json` 中三个外层命令收据 | 其中数值命令的内部 `wait4` 收据 |

每次真正执行的复跑仍消耗计算，应在新增执行费用中单列；不能把重复执行当作新增独立科学
样本，也不能把同一进程的包含性费用重复累计。R12 共享 donor 在总研究训练账中各计一次；
单独部署一个候选的训练摊销另行计入该 donor 全额，两种口径不能混加。

CPU、wall、峰值进程 RSS、任务查询 tariff 和物理能耗是不同量。没有历史能耗记录时保留
`null`，不能通过 CPU 秒乘假定功率生成 Joule。不同机器上的实际时延与峰值内存应重新记录。

## 9. 已完成的最小树检查与边界

`RECONSTRUCTION_CHECK.json` 和 `reconstruction_checks/attempt001/` 记录了实际独立重建：
1,934 个归档输入加上 29 个明示 R13 文件、两个 R12 依赖文件及两份真实 publication receipt，
共 1,967 个初始文件。所有 `experiments.*` 的实际导入路径均在重建树内，未导入原仓库副本。

7 项测试、publication loader 检查和一次完整数值套件通过；六个数值完整直接末态与原
`formal_01` SHA256 一致，八个数值执行源码／协议身份一致。该检查证明所执行路径的依赖完整性，
没有验证未运行的其他工程工作流，也没有把固定 renewal 内容门变成完整传播模型。

本页命令按发布的 `evidence.py`、`numerics/launch.py`、`value/run.py` 与 `cost/audit.py`
真实 CLI 核对；编写本页时未再次启动训练、24 案例确认或成本重算。
