# 复现 770D Cell 的封存结果与异路径恢复

这份说明对应本轮 runtime 数据包。归档自动附带的通用说明提到旧的 `run_calibrated_cells.py`；本轮应使用下面的 runtime 专属入口。完整恢复不会训练新模型、调用 Encoder、重新拟合校准或评价任务质量。

## 1. 固定源码和输入

仓库：[TrillionniumFoundation/hepta-private-ci](https://github.com/TrillionniumFoundation/hepta-private-ci)。在独立 checkout 中使用：

```text
数值代码冻结提交：bb0d5c67ab5457e551b97fbda9a57390e3a69425
包含恢复与绘图工具的提交：201cccfcee22ad787fc491f484268beaa4cfdb56
该提交 Git tree：865d627cac200906593c820764c270321b0eca09
```

后一提交保留前者的数值实现，追加固定观察提取、成本账和恢复/绘图工具。后续报告提交不改变这些数值文件。归档中 `runtime/recovery-helper-pin.json` 另存具体脚本摘要。

| 文件 | 字节 | SHA256 |
|---|---:|---|
| `hepta-cell-runtime-770-evidence-v1.tar.gz` | 147,909,524 | `f2fa364efa81ffb96bfc27bc5517c43a4d3b1dcd3374d9eee7660d6c250cc498` |
| 同名 `.tar.gz.index.json` | 36,760 | `afcb12d61f1e62e86951886733f537e5a48909f5c9e2aa74b76de26cf1c2ccad` |
| bundle manifest | 归档内 | `266af205b6053df3c3968d2de52ff6ede8d8ebc6add3909fa7bc081cd52a6fdc` |
| 原始固定 `runtime-facts.json` | 31,392 | `aa3641e69da7c4202b4b49ef62ddb7b355330aa157e9211802e578c8c6fb4be6` |

数据包含 **234 个逻辑文件、230 个唯一内容对象、154,374,750 个逻辑字节**。原始路径只保留为来源记录，恢复后的 loader 使用包内相对路径。源码和 PNG 留在 Git；共享 Encoder checkpoint、Python 环境和旧完整研究语料没有复制进本轮数据包。9 份私有参数 NPZ 是本轮保存的训练数据产物，已经完整包含。

本机验证使用 Linux、Python 3.12.14、NumPy 2.2.6；仅重新画图需要 Matplotlib 3.10.8。BLAS 显式设置为单线程。其他平台/BLAS 组合可以检查固定容差，但没有由本次实验保证跨实现逐位相同。

## 2. 一条命令完成本轮恢复检查

在上述源码 checkout 的仓库根目录运行。`ARCHIVE` 和 `INDEX` 应指向交付的原始文件，恢复目录和输出目录必须尚不存在：

```bash
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

python qa/stem-bakeoff/evidence/20261024-cell-runtime/source/verify_runtime_recovery.py \
  --archive /path/to/hepta-cell-runtime-770-evidence-v1.tar.gz \
  --index /path/to/hepta-cell-runtime-770-evidence-v1.tar.gz.index.json \
  --index-sha256 afcb12d61f1e62e86951886733f537e5a48909f5c9e2aa74b76de26cf1c2ccad \
  --restore-root ./restored-runtime-v1 \
  --output ./runtime-recovery-v1
```

该入口按顺序启动 **13 个 fresh child processes**：1 次完整 restore、1 次三结构 serving replay、9 次 checkpoint 验证、1 次队列发布恢复、1 次固定事实提取。它还在父进程检查恢复前后的完整文件清单、文件大小/SHA、普通文件及 link count=1，验证 45 个成本账输入绑定与封存数值代码。

预期结果：

```json
{
  "passed": true,
  "total_parameter_states_verified": 4032,
  "facts_sha256": "aa3641e69da7c4202b4b49ef62ddb7b355330aa157e9211802e578c8c6fb4be6"
}
```

输出目录保留 `recovery-summary.json`、每个 child 的 argv、stdout、stderr、exit code 和计时，以及重新派生的 facts。失败时保留 `failed.json` 和已有输出，不覆盖失败观察。对照原始 report 的比较也由入口执行，不仅检查某次 replay 自己能够运行。

## 3. 各项恢复的实际覆盖

| 项目 | 核验内容 | 不包含 |
|---|---|---|
| 完整归档 | 外部 index SHA → archive SHA → manifest SHA → 每个普通文件 SHA | 自动安装环境或执行来源项目代码 |
| Serving | 三种结构，1024 IDs×64 行；full、cache、top-3 与主实验摘要相同 | 重跑全部计时条件或评价路由相关性 |
| 私有参数 | 9 条件全部参数数组、4032 个 Cell 摘要；每条件首尾 Cell 的固定三行预测 | 4032 个不同任务、全部 Cell 的重新质量评价 |
| 队列 | 已发布三份 Head 的输入、初始参数、任务/代数、权重和固定 logits | 新训练、故障注入、优化器中间状态恢复 |
| Facts | 从恢复目录提取全部固定输入，输出字节 SHA 与原件一致 | 重抽样、选阈值、重拟合 |
| 成本账 | 45 项原输入都映射到恢复文件并逐一验证，已知合计与封存独立重算相同 | 推测未测时间、价格或能耗 |

九条 checkpoint 分别含 64、256、1024 个状态，三个结构各一组。跨规模共享初始化 seed 前缀，因此 4032 个状态槽位对应 3072 个不同最终批量参数摘要。恢复入口只验证保存的最终参数；Adam moments 没有被保存，不能宣称中断续训。

## 4. 只查看原始观察和重新画图

恢复后的主要入口如下：

```text
restored-runtime-v1/runtime/bundle/
restored-runtime-v1/runtime/serving/report.json
restored-runtime-v1/runtime/training/report.json
restored-runtime-v1/runtime/training/{linear,gated,residual}-{64,256,1024}/
restored-runtime-v1/runtime/queue/report.json
restored-runtime-v1/runtime/queue/training.sqlite
restored-runtime-v1/runtime/costs/{registry,ledger,verification,arithmetic,notes}-v1.json
restored-runtime-v1/runtime/stages/
restored-runtime-v1/runtime/tests/
restored-runtime-v1/bounded-runtime-tests/
```

重新生成图不执行 ML 工作，输出路径必须新建：

```bash
python qa/stem-bakeoff/evidence/20261024-cell-runtime/source/plot_runtime_facts.py \
  --facts ./runtime-recovery-v1/runtime-facts-rederived.json \
  --output ./runtime-summary-reproduced.png
```

图的数值只来自 facts。不同 Matplotlib/字体版本可能改变图像字节，而不改变事实；固定环境下的交付 PNG SHA 为 `462d6a1e46472684013c84462b087ddaf14223cdb7a69fd3111ce5ad049d8603`。

## 5. 成本与权限

每个 child receipt 的计时嵌套在 controller 的外层观察中。统计总恢复成本时应只计完整 controller 进程树一次；不要把 child 计时再加一遍。原主账按其固定 cutoff 保留，打包、恢复、图表和报告发布是后续 closing 工作。

重新测主训练或服务应使用新的输出目录和新的成本 receipt，不能覆盖本轮封存文件。重新测历史输入不会产生一个新的独立质量测试集。所有已保存状态保持 `SHADOW_ONLY / DENY_ALL`；新队列 Head 未校准，原生生产资格、学习质量和跨任务泛化均不由恢复成功授予。
