# 本地证据验证与恢复

本轮已观察留出只能用于复核；恢复、重跑或改变目录不会产生新的独立留出。
数值实现及协议为 `3674fe9bce6634def78b24606e4cd74ad9bd2269`，
包含原始验证脚本、报告数据和迁移 helper 的归档源码版本为
`0fb7be3a6f42dae0024953a0cc494b8f0ef8a9dc`，tree `d99cb78df3d494fa6ab911011c8ba88cdb534be2`。
两个版本的 268 份数值／协议文件逐字节相同。

## 1. 验证数据包

包名为 `hepta-cell-prospective-action-evidence-v1.tar.gz`，
独立索引为同名加 `.index.json`。完整摘要、实际大小、恢复状态见 [delivery-index.json](delivery-index.json)。
源码位于 Git；包内是内容寻址的数据对象和逻辑路径表，不包含安装环境或共享模型 checkpoint。

先将上述源码版本取回到单独 checkout，并将包及索引放到可读目录。
以下变量应替换为自己的绝对路径；输出目录必须不存在。
验证和恢复工具使用 hashlib.file_digest，以下 python3 至少需要 Python 3.11；本次实测使用 Python 3.12.14。

```bash
hepta_repo=/absolute/path/to/hepta
hepta_data=/absolute/path/to/evidence
hepta_restore=/absolute/path/to/new-restored-evidence
hepta_archive="$hepta_data/hepta-cell-prospective-action-evidence-v1.tar.gz"
hepta_index="$hepta_archive.index.json"

python3 "$hepta_repo/qa/stem-bakeoff/package_cell_local_evidence.py" verify \
  --archive "$hepta_archive" --index "$hepta_index"

python3 "$hepta_repo/qa/stem-bakeoff/package_cell_local_evidence.py" restore \
  --archive "$hepta_archive" --index "$hepta_index" \
  --output "$hepta_restore"
```

独立索引本身也须与 `delivery-index.json` 中保存的 SHA256 一致。
工具逐一检查 tar 成员类型、路径、对象大小与摘要，再恢复每个逻辑文件并重新读回核验。
恢复产物是普通文件，各逻辑文件独立保存；原始绝对路径仍作为 receipt 中的来源标识保留。
不要通过修改封存 receipt 的路径或重新生成 seal 来适配新目录。

## 2. 固定 Head 的无重训迁移验证

本轮主推理已经对全部 81 个学习 Head 做新进程重载，logits 与 probabilities 逐位一致。
交付阶段额外检查一个事先固定的代表：Granite clean field770、seed 7、n8、gated、168 行输入。
它用于证明目录迁移与依赖绑定，不新增任务评分。

需要原数值环境：Linux、Python 3.12.14、NumPy 2.2.6、单 BLAS 线程。
没有声明不同 CPU、BLAS 或软件版本之间普遍逐位一致。
运行时环境和公开依赖可根据保留的锁定清单重建；执行恢复的上游源码不会自动发生。

```bash
hepta_python=/absolute/path/to/python3.12
hepta_index_sha=3edf38f3294e46ad67bdefd0f6df539bb1326e64b94035be570325dec5483f27
hepta_replay=/absolute/path/to/new-replay-output

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONDONTWRITEBYTECODE=1 \
"$hepta_python" \
  "$hepta_repo/qa/stem-bakeoff/evidence/20261024-prospective-action/source/replay_relocated_action_head.py" \
  --archive "$hepta_archive" --index "$hepta_index" \
  --index-sha256 "$hepta_index_sha" --restored-root "$hepta_restore" \
  --source-dir "$hepta_repo/qa/stem-bakeoff" --output "$hepta_replay"
```

helper 从归档 manifest 的 `provenance.roots` 与成员表解析原始路径，验证输入字节、模型摘要、
特征身份、source 顺序、calibration context 和完整 seal，再启动一次既有 `cell_action_evaluate.py`。
比较的是两个数组的 dtype、shape 和原始数值字节；NPZ 容器压缩字节不是数值一致性标准。
输出必须位于封存输入树之外。其源文件摘要固定为
`0774d9b8f9f6cac1af8b1e0bfac8921e0229ce2bfe8ad96bf13dd41428e4a3e0`。

## 3. 只从封存结果重建报告

恢复目录中的 `prospective/` 包含本轮报告提取需要的固定输入。
提取只读取已保存的指标、区间和私有成本，不重新预测、拟合或 bootstrap。
输出必须使用新文件名。

```bash
python3 \
  "$hepta_repo/qa/stem-bakeoff/evidence/20261024-prospective-action/source/derive_report_facts.py" \
  --phase-root "$hepta_restore/prospective" \
  --output /absolute/path/to/new-research-facts.json

MPLCONFIGDIR=/absolute/path/to/writable-matplotlib-cache \
"$hepta_python" \
  "$hepta_repo/qa/stem-bakeoff/evidence/20261024-prospective-action/source/plot_report_facts.py" \
  --facts /absolute/path/to/new-research-facts.json \
  --output /absolute/path/to/new-learning-curves.png
```

报告 JSON 的确定性摘要为
`1139b79df97554b6cac94e925579154ad01ab97c6cae48d847bc45e82e4b46be`。
绘图环境本轮使用 Matplotlib 3.10.8；不同渲染环境可能生成不同 PNG 字节，数值依据始终是固定 JSON。

## 4. 完整实验与依赖边界

归档包含完整候选输入、来源绑定、执行日志、未知结果、全项目替代计划、三份特征、
全部私有参数、训练搜索记录、校准、推理、参数控制、固定分析及成本账本。
原始执行条件、Luigi 的三个依赖构建尝试和全项目重跑、Sanic 的诊断条件均保留。
编排源码在 Git；临时 worktree、安装环境、字节码缓存、checkpoint 权重和普通预分配空间不属于数据归档。

五个新项目的 96 个实现 revision 对应的公共 Git 对象已保留并验证可解析，来源不依赖 promisor 或 alternates。
文件恢复不会生成空的 Git `refs/heads`／`refs/tags` 目录；若需把恢复对象库作为 bare Git 使用，应先按说明建立这些空目录。
旧开发项目的 160 份 prepared case 与先前已交付 Part D 的路径／摘要映射保留在 disclosure 中；
原历史 Git 源码也可依照 pinned revision 再获取。重建并执行完整 benchmark 仍需要这些源树、对应解释器和锁定依赖。

Granite checkpoint 固定为 `ibm-granite/granite-embedding-97m-multilingual-r2`，
revision `835ad14087e140460703cf0fae09f97d469d65c2`。
已完成编码并验证特征后，本机权重缓存被清理以释放空间；模型获取收据、tokenizer/config 摘要与冻结特征仍在。
本次恢复和 Head 验证不需要重新下载权重。重新编码须先按收据取回并核对完整 inventory。

本轮研究成本 v3 的 152 个输入绑定（含 registry）均有归档成员覆盖，完整账本数值可直接复核。
原 receipt 的路径命名空间保持不变；如需在新路径下调用通用成本编译器，应建立显式的新映射 registry，
并保留原 registry 及各输入内容摘要，不覆盖封存文件。不能把旧 schema 的 `logical_task_count=0` 当成本轮零任务；
本轮逻辑任务计数在专用 notes 和报告中明确为一。

通用数据包内部的 `REPRODUCE.md` 描述跨阶段打包工具；本轮任务定义以本文件及
[`CELL_PROSPECTIVE_ACTION_PROTOCOL.md`](../../CELL_PROSPECTIVE_ACTION_PROTOCOL.md) 为准。
下一次学习方法或选择规则改变需要新的冻结计划及独立数据，本轮 48 个留出 bug 此后登记为已观察。

## 5. 成本截止点

研究账本 v3 在准备、推理、固定分析和私有成本核验完成后封存。
归档构建、完整恢复、代表性 Head 回放、交付复核及格式化发生在截止点后，单独保存在关闭收据中。
归档不会反复包含自己的生成成本来形成循环依赖；外层交付索引把数据包、代码、关闭收据联系起来。
所有未知时间、网络字节、能耗与价格继续保留为未知。
