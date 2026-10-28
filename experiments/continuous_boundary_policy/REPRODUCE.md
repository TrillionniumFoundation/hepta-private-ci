# 复现匹配循环策略补充实验

本目录是 `continuous_boundary_flow/study-002` 的独立补充；旧研究的样本、模型、证据和三个主验收结论保持原样，两轮结果不合并。模型、信息预算和四项主比较见 [README.md](README.md)，最终解释见 [REPORT.zh.md](REPORT.zh.md)，完整表格见 [results/RESULTS.zh.md](results/RESULTS.zh.md)。

## 1. 已发布身份与实际结果

| 对象 | 身份 |
| --- | --- |
| 源码/协议发布提交 | `57ca7eda3ea4bbf556ed2e1f071e00ac702a3366` |
| `SOURCE_SEAL.json` SHA-256 | `6b3afbf2af8476730c1260f470bd8f0f68d69652950499388abc3b178f0fd858` |
| `PROTOCOL.json` SHA-256 | `c55747dd06640b92aca2198dcbfa21a0a5bf53f5890daf6bc51aa257f887865a` |
| 选择结果发布提交 | `8efa84ecb0ae5e5a1f38b15974da6e1db1f80df0` |
| `SELECTION_SEAL.json` SHA-256 | `1e06fb919d5dd06f61de1c03940f0478a989e9c0fcbabd0e6f39f305837485b4` |
| `evidence/bundle/INDEX.json` SHA-256 | `56c5c232eb564522ae7fb7e5aec9a274ace10801d312aaf9ac4edd929d7cacb0` |
| 完整压缩 archive SHA-256 | `c9b809f9393ddbc81569f740e402b8c2fe4fbb78c04d44ba7960fb227138d58f` |
| 原始独立审计 `AUDIT.json` SHA-256 | `320e45cdffe0299d39874686d114450d6babcb7a1d14bf0cf2286899e1feb1ee` |

8 个新种子、216 个候选模型、104 个选定检查点和 26,624 条确认轨迹已完成；独立证据审计通过，四项收益门槛通过 **0/4**。工程运行完成 24,576 次主更新、21 次新进程续行和 336 次完全一致的 replay；工程通过不表示科学收益通过。

## 2. 先恢复完整证据，再审计

使用本研究最终发布版本的仓库，并保留上述提交历史。以下命令均从仓库根目录执行。审计依赖 NumPy 2.3.5、SciPy 1.17.0；不需要编译或运行 native host。

```sh
python -m pip install -r experiments/continuous_boundary_flow/requirements.txt
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
python -m experiments.continuous_boundary_flow.evidence_bundle unpack \
  --bundle-dir experiments/continuous_boundary_policy/evidence/bundle \
  --output-dir /tmp/hepta-policy-restored
```

输出目录必须不存在，并有足够空间。归档包含 1,397 个文件、551 个目录、135,381,408 原始 bytes；压缩 archive 为 126,976,094 bytes，分为 265 片，另有 1 片文件名册。每片最多 480,000 bytes。解包器校验分片、完整 archive、文件名册、长度和 SHA-256，并拒绝链接、越界路径、重复或额外成员。

恢复后的布局：

- `study/run/`：原始协议、源/环境/选择封存、公共训练数据、全部候选模型及开发集收益、选定检查点、确认分片、原始成本和严格 `MANIFEST.json`。
- `study/analysis/`：原始独立审计、确认前审计、分析脚本和结果；最终表格在 `results-final/`。
- `study/preflight/`：预检轨迹、测试及构建收据；`runtime/` 保存两份原 Linux x86_64 可执行文件和 `NATIVE_EXECUTABLES.json`。
- `engineering/`：持续状态轨迹、检查点、新进程续行记录、共同输入计时和工程总收据。

```sh
python -m experiments.continuous_boundary_policy.audit \
  --study /tmp/hepta-policy-restored/study/run \
  --repository "$PWD" \
  --output /tmp/hepta-policy-recomputed-audit.json
```

审计输出文件也必须不存在。不要将日志或分析输出写入 `study/run/`：额外文件会触发严格名册拒绝。比较新审计与归档 `study/analysis/AUDIT.json` 的完整字节 SHA-256；原始审计不含此次复算时钟或绝对运行路径。逐文件解包校验已通过；异路径复算及哈希比较的实际状态以 [evidence/ROUNDTRIP.json](evidence/ROUNDTRIP.json) 为准。若不同，应保存并解释差异。

审计独立重算连续隐藏状态、分数、动作、任务账本和统计区间；有限网格构造器是共同封存依赖。稀疏参考核查原生收据、检查点链和独立 Q24 读出，并未另写一个独立 sparse 内核。小型有理数 DP 夹具的精确性仅针对该有限任务。

## 3. 从原收据重新生成表格

```sh
python /tmp/hepta-policy-restored/study/analysis/GENERATE_TABLES.py \
  --study /tmp/hepta-policy-restored/study/run \
  --audit /tmp/hepta-policy-restored/study/analysis/AUDIT.json \
  --engineering /tmp/hepta-policy-restored/engineering \
  --output /tmp/hepta-policy-regenerated-tables
```

显式给出所有路径，输出目录必须不存在且位于原 run、engineering 外。脚本仅机械提取已完成收据，不重训、不扩样、不新增统计检验。归档 `results/` 是保留的初版表格；`results-final/` 修正了 Markdown 竖线造成的列分隔问题，统计 JSON 字节相同。`GENERATE_TABLES.initial.py`、初表和 `TABLE_FORMAT_NOTE.json` 保留修订历史。

## 4. 原二进制与构建范围

| 原执行文件 | SHA-256 |
| --- | --- |
| `continuous_host` | `1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5` |
| `boundary_policy_score_host` | `edda06935dbbc7606530ba281b5af8bb97a09de81e3be8da3433b7ffd8647ac1` |

兼容 Linux x86_64 环境可直接使用恢复后的 `study/preflight/runtime/` 文件；解包保留执行权限，文件字节绑定上述身份。环境记录见同目录 `NATIVE_EXECUTABLES.json`。这避免把一次不同环境的重建误当原二进制，源码审计本身仍不需要执行它们。

需要重建时，原 sparse/NDU 步骤见 [旧 native/README.md](../continuous_boundary_flow/native/README.md)。补充 host 在同一核查后的构建树上单独构建：

```sh
python -m experiments.continuous_boundary_policy.native.build \
  --repository /absolute/repository --native-build /absolute/verified-native-build \
  --output-dir /absolute/new-score-build-receipt --compiler /absolute/pinned-rust-toolchain/bin
```

`native/preflight/BUILD_RECEIPT.json` 和 `SOURCE_MANIFEST.json` 绑定最终格式化后文件与二进制；`.preformat.json` 及测试收据保留实际受测的早先构建身份，不把它们改称最终二进制的执行测试。自行构建的不同二进制不能冒充上述身份；初始化会拒绝不匹配。研究不同构建需另立版本、发布新源/二进制封存，不能修改原记录或跳过校验。

## 5. 精确重复运行与新的科学研究

**同源、同协议、同种子的重复运行是复现，不是新增独立统计样本。** 以下命令在独立工作副本和全新输出目录重复原协议，复用已发布的原源/二进制身份。新科学研究则必须先确定新协议与新种子，完成适配代码、预检、格式化和构建，再运行 `study freeze` 并发布新源/协议/二进制封存，之后才能训练；原确认结果不得用于调整本次已封存模型或门槛。

```sh
git fetch origin research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export HEPTA_POLICY_SOURCE_COMMIT=57ca7eda3ea4bbf556ed2e1f071e00ac702a3366
export HEPTA_POLICY_RUN=/absolute/new-policy-reproduction
export HEPTA_POLICY_NATIVE=/tmp/hepta-policy-restored/study/preflight/runtime/continuous_host
export HEPTA_POLICY_SCORE=/tmp/hepta-policy-restored/study/preflight/runtime/boundary_policy_score_host
python -m experiments.continuous_boundary_policy.study initialize \
  --output "$HEPTA_POLICY_RUN" --native-binary "$HEPTA_POLICY_NATIVE" \
  --score-binary "$HEPTA_POLICY_SCORE" --publication-commit "$HEPTA_POLICY_SOURCE_COMMIT"
python -m experiments.continuous_boundary_policy.study train \
  --output "$HEPTA_POLICY_RUN" --native-binary "$HEPTA_POLICY_NATIVE" \
  --score-binary "$HEPTA_POLICY_SCORE"
python /tmp/hepta-policy-restored/study/analysis/PRECONFIRMATION_AUDIT_SCRIPT.py \
  --study "$HEPTA_POLICY_RUN" --repository "$PWD" \
  --output /absolute/new-policy-analysis/PRECONFIRMATION_AUDIT.json
```

确认前脚本检查所有候选、选择及成本前缀，并拒绝任何已有确认产物；它不能直接用于已完成的归档 run。随后把新 run 的 `SELECTION_SEAL.json` 原字节发布到 `experiments/continuous_boundary_policy/evidence/SELECTION_SEAL.json`，使用此次实际提交。成本时钟不同会改变选择封存，不能把原选择提交冒充新 run 的提交。新科学版本也必须在打开新确认集前完成这一发布步骤。

```sh
git fetch origin research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export HEPTA_POLICY_SELECTION_COMMIT=REPLACE_WITH_PUBLISHED_SELECTION_COMMIT
python -m experiments.continuous_boundary_policy.study confirm \
  --output "$HEPTA_POLICY_RUN" --native-binary "$HEPTA_POLICY_NATIVE" \
  --score-binary "$HEPTA_POLICY_SCORE" --publication-commit "$HEPTA_POLICY_SELECTION_COMMIT"
python -m experiments.continuous_boundary_policy.audit \
  --study "$HEPTA_POLICY_RUN" --output /absolute/new-policy-analysis/AUDIT.json
python -m experiments.continuous_boundary_policy.engineering \
  --study "$HEPTA_POLICY_RUN" --score-binary "$HEPTA_POLICY_SCORE" \
  --output /absolute/new-policy-engineering
```

必须使用上述显式 refspec：单分支 sparse clone 中只 fetch 分支可能仅更新 `FETCH_HEAD`；初始化要求对应 named remote ref 存在，并核对发布提交的祖先关系及精确封存字节。任何失败均保留原始记录；不能删除失败后把续跑包装成未中断实验，不覆盖原 run，也不追加种子直到获得显著结果。

## 6. 成本、统计与结论边界

科学成本保留 `costs.jsonl` 原值。训练、边界求解、确认、native CPU、数值通信字节和实际 JSON 流量分别核查；包围阶段已经包含子窗口，不能再次相加。协议对 child CPU 时钟差使用 5 微秒容差，不改写原值。

净效用按实际数值跨进程输入每 byte 扣除 `1e-6`：连续模型每步 24 bytes，native sparse 每步 160 bytes；四项主比较均使用 24 bytes。该口径不是完整 wire 流量，也未给 CPU 或能耗虚构价格。

工程 `SUMMARY.json` 的 `overall_window_cost` 是包含子进程的总窗口；warm/cold/native 各项是其子范围。24,576 次主更新及 336 次 replay 不增加确认样本；持续状态与冷恢复证据不构成无限期稳定性或 durable native owner 证明。

解包、独立审计及归档耗时另列为复现/机械封装成本，不并入原科学成本。四项主比较保留配对种子、Bonferroni 区间及 `0.005` 收益门槛；描述性排名不能替代主验收。没有硬件能耗测量，不作节能结论，也不把有限决策 Bellman 边界称为 He–Xiong 原模型的精确连续时间自由边界。
