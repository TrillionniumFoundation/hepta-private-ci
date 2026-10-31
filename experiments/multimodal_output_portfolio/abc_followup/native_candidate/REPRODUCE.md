# 复现：固定 future-correctness 候选的新分支比较

## 冻结身份与前提

发布时点的完整 18 文件位于 commit `5f67ed90455e63cca697ff7f8fd9694fc42abccf`，tree `f1029dc3d790ebe1f730978edb3c3cfceaba8aec`。[FREEZE_READY](FREEZE_READY.json) 绑定其余 17 文件；[PROTOCOL](PROTOCOL.json) 绑定 42 个项目 Python 源文件、12 个输入文件以及完整的来源/动作/候选/统计配置。

本轮不分发 raw 数据、媒体、权重或 journal。精确重放需要协议所列的原始 artifact，包括原 manifest/MNIST archives、固定生成器/observer、`model-003` 及其 predictor/calibrator freezes、sequence 802 的真实候选文件、原 repair 20-model 完成记录和前序执行的时间线证据。缺少这些输入时 guard 应真实失败，不能通过自造 fixture、改写旧 receipt 或弱化分配检查来运行正式采集。前序构建和模型复现说明见 [native REPRODUCE](../native/REPRODUCE.md)。

所有命令从仓库根 `/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery` 运行。此次实际 Python 为 `/workspace/scratch/2b3c256bef7d/ndu-env/bin/python`。以下为实际执行命令；对应 output/receipt 已存在时必须保留，collector 不接受覆盖。完整原样重放须在具备这些原始输入且目标输出尚不存在的隔离工作区执行。改动绝对路径或协议会改变其身份，须作为另一次明确登记的实验。

## 冻结前检查

以下检查只用 synthetic census 或已经使用过的历史 public inputs，不物化本轮复用来源。

```bash
env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /workspace/scratch/2b3c256bef7d/ndu-env/bin/python -B \
  -m experiments.multimodal_output_portfolio.abc_followup.process \
  --receipt /workspace/scratch/2b3c256bef7d/abc4-native-runs/candidate-boundary-checks-001.process.json \
  --module experiments.multimodal_output_portfolio.abc_followup.native_candidate.boundary_checks -- \
  --protocol experiments/multimodal_output_portfolio/abc_followup/native_candidate/PROTOCOL.json \
  --output /workspace/scratch/2b3c256bef7d/abc4-native-runs/candidate-boundary-checks-001.json

env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /workspace/scratch/2b3c256bef7d/ndu-env/bin/python -B \
  -m experiments.multimodal_output_portfolio.abc_followup.process \
  --receipt /workspace/scratch/2b3c256bef7d/abc4-native-runs/candidate-source-checks-001.process.json \
  --module experiments.multimodal_output_portfolio.abc_followup.native_candidate.source_guard_tests
```

实际结果为 12 项 focused checks 与 4 项 unittest 通过。两项本地 v1→v2 source/timeline 登记修正只涉及登记持久性与完成时间的措辞，均先于正式访问。不得把旧 v1 记录当作当前 loader 的有效 access。

## 发布冻结后：实际采集与分析

执行前先确认 GitHub 上对应完整冻结 tree。collector 自动创建新的、与 protocol 绑定的 `native_candidate_reuse` access；之后才允许物化完整 `repair_test` 队列。不要手写 access-registration。

```bash
env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /workspace/scratch/2b3c256bef7d/ndu-env/bin/python -B \
  -m experiments.multimodal_output_portfolio.abc_followup.process \
  --receipt /workspace/scratch/2b3c256bef7d/abc4-native-runs/candidate-reuse-001.process.json \
  --module experiments.multimodal_output_portfolio.abc_followup.native_candidate.collect -- \
  --protocol experiments/multimodal_output_portfolio/abc_followup/native_candidate/PROTOCOL.json

env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /workspace/scratch/2b3c256bef7d/ndu-env/bin/python -B \
  -m experiments.multimodal_output_portfolio.abc_followup.process \
  --receipt /workspace/scratch/2b3c256bef7d/abc4-native-runs/candidate-reuse-analysis-001.process.json \
  --module experiments.multimodal_output_portfolio.abc_followup.native_candidate.analysis -- \
  --protocol experiments/multimodal_output_portfolio/abc_followup/native_candidate/PROTOCOL.json
```

collector 必须输出 1000 source pairs、2000 future rows、6000 model predictions，并保留全部 72 份预提交文件及实际 PNG/UTF-8 输出。analysis 核对完整 source/action census、两个 action 的共同 prefix、全部预提交与媒体 hash、冻结前向结果、原始未来状态及新 access 的顺序，然后执行固定的 4000 次来源对 bootstrap。

## 结果位置与判断标准

本地原始采集位于 `/workspace/scratch/2b3c256bef7d/abc4-native-runs/candidate-reuse-001`，分析位于 `candidate-reuse-analysis-001`。此目录中的 [RESULTS.json](RESULTS.json) 与实际 `result.json` 字节相同，SHA 为 `f49b6e77c67ee7249b31400a60d688b93768801617106418887a5625e7014a95`。

预定的两项区间均跨零，冻结校准分组、概率及分类均零变化。不要改动 bootstrap seed、来源范围、指标、候选或幅度来改变结论。来源在项目中已经观察过，新增项目独立来源数为零；本轮也没有执行 updated-head native tick、参数应用或生产 acceptance。

[EXECUTION_RECEIPTS](EXECUTION_RECEIPTS.json) 收录两项正式阶段的实际 registration、精确子进程 receipt、来源访问登记及完整计费范围；[CHECK_PROCESS_RECEIPTS](CHECK_PROCESS_RECEIPTS.json) 收录预访问检查。原始过程 logs 只在本地保留，以其中的 SHA 核对。运行成本来自共享宿主、单线程执行，不能据此声称隔离环境服务延迟。
