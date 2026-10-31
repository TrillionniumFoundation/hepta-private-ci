# ABC：实际输出训练与因果反馈控制

这是在恢复的 v7 图文原型上新登记的开发实验。它使用新的来源区间，重新执行实际离散输出训练、有限候选路径、冻结反馈策略、独立媒体复核和真实执行成本评价。

历史 v7 源码与部分 checkpoint 已按原始 Git blob／文件 hashes 恢复。历史 ABC 原始运行记录及计时没有恢复；本目录的新结果不冒充那些旧运行。

## 已完成的结果

完整结论见 [RESULTS.md](RESULTS.md)，机器可读状态见 [GATES.json](GATES.json)。两个 A/B 主比较的原 nominal 97.5% 区间均跨零；时序传输子实验通过有限基线家族的工程收益门，但未完成全模态神经生成或原生 Hepta 资格。`all_blockers_closed` 仍为 false。

| 证据 | 阅读入口 |
| --- | --- |
| A/B 全部条件、主比较、消融、风险层次 | [独立审阅](results/ab-001/REVIEW.md)、[全部聚合数值](results/ab-001/summary.json)、[置信区间图](results/ab-001/effect-intervals.png) |
| 实际时延、CPU、匹配质量和完整价格网格 | [成本审阅](results/cost-001/REVIEW.md)、[完整压缩报告](results/cost-001/cost-analysis-report.json.gz)、[进程回执](results/cost-001/execution-receipts.json) |
| 真实 AV 字节与因果传输、唯一事后 220 ms 基线 | [C 审阅](results/causal-av-001/REVIEW.md)、[正式聚合](CAUSAL_AV_EVALUATION.json)、[事后诊断](CAUSAL_AV_STATIC_220_DIAGNOSTIC_RESULT.json) |
| 当前原生契约与旧 owner 实测记录 | [原生资格审阅](results/native-review-001/REVIEW.md)、[固定提交的文档身份](results/native-review-001/FETCH_METADATA.json) |
| 全部本地原始证据的范围与哈希清单 | [聚合 inventory 审阅](results/evidence-inventory-001/REVIEW.md) |

原始媒体、模型和逐步记录共 47,770 个文件、5,448,401,856 bytes，完整本地清单已完成。Git 中保存源码、协议与聚合证据；原始证据的长期归档仍等待具体导出授权。

## 方法与协议

- [设计解释与适用边界](DESIGN_AND_SCOPE.md)：Merton 对应、NDU profile、训练与推理控制、消融的识别范围。
- [有限条件风险模型](DYNAMIC_RISK.md)：因果 Bellman 递推、隐藏目标、随机成本、有限模型最优性和误差界假设。
- [主协议](protocol.json)：来源、五个训练 seed、三种训练目标、评价及统计。
- [修订 001](protocol-amendment-001.json)：共享状态干预、条件访问、局部奖励、route 与 MPC。
- [修订 002](protocol-amendment-002.json)：另加全部八视图的同来源计时；保留原三视图协议。
- [修订 003](protocol-amendment-003.json)：同队列质量／成本比较及明确的描述性成本价格情景。

修订不改变原有主端点。协议中保留 `all_blockers_closed: false`，因为它是预执行时的状态，不能事后改写为成功回执。实际结果应在独立结果文件中报告。

## 实现位置

| 部分 | 入口 |
| --- | --- |
| 实际 Bernoulli 像素与自回归 token | `emission.py`、`runtime.py`、`media.py` |
| 精确基础模型恢复及评分器资格 | `base_recovery.py`、`qualification.py` |
| 五 seed × 三训练目标 | `training_run.py`、`output_training.py`、`warm_start.py` |
| 21 条真实候选路径 | `trees.py` |
| 条件矩价值、反馈及静态路线 | `critic.py`、`control.py`、`route.py` |
| 独立随机流的短视野规划 | `planning.py` |
| 全部策略冻结后再打开评价 | `control_run.py`、`evaluation.py` |
| 同初始草稿的共享状态干预 | `interventions.py` |
| 成对来源与训练 seed 统计 | `analysis.py`、`statistics.py` |
| Resident 完整请求计时 | `timing_run.py`、`timing.py`、`episodes.py` |
| 真实媒体重评分与恢复连续性 | `evidence_audit.py`、`selected_audit.py`、`resume_verify.py` |
| 自然音视频来源及归属核验 | `temporal_sources.py`、`temporal_source_repair.py` |

`PublicFrame` 只携带可用于控制的实际观察和状态副本。私有目标及实际未来 RNG 留在运行 owner 中。Oracle 在公共策略选择已保存后产生。Secondary observer 只参与离线资格与评价。

## 图文复现顺序

从仓库根目录运行。实测环境为 Python 3.12.14、PyTorch 2.14.1+cpu、NumPy 2.3.5、Pillow 12.3.0；神经计算使用两个 CPU threads。运行文件会记录各自完整环境及源码 hashes。不同环境下的数值结果和计时不能预先假定逐字节相同。

以下变量应指向调用者自己选择的独立目录。每个执行器拒绝覆盖已经存在的输出目录。运行期间保持登记的源码不变。

```bash
HEPTA_PYTHON=/absolute/path/to/python
HEPTA_CACHE=/absolute/path/to/mnist-cache
HEPTA_RUNS=/absolute/path/to/new-run-directory
HEPTA_MODULE=experiments.multimodal_output_portfolio.abc_recovery
HEPTA_PROTOCOL="$PWD/experiments/multimodal_output_portfolio/abc_recovery/protocol.json"
```

1. 恢复来源登记并核验固定 manifest identity。

```bash
"$HEPTA_PYTHON" -B -m experiments.multimodal_output_portfolio.v7.sources \
  --cache "$HEPTA_CACHE" --output "$HEPTA_RUNS/sources/source-manifest.json"
```

2. 执行基础模型恢复及新的独立评分器资格。

```bash
"$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.base_recovery" \
  --cache "$HEPTA_CACHE" --manifest "$HEPTA_RUNS/sources/source-manifest.json" \
  --output "$HEPTA_RUNS/base"

"$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.qualification" \
  --cache "$HEPTA_CACHE" --manifest "$HEPTA_RUNS/sources/source-manifest.json" \
  --primary "$HEPTA_RUNS/base/reward-observer.pt" --protocol "$HEPTA_PROTOCOL" \
  --output "$HEPTA_RUNS/qualification"
```

主评分器 wrapper 含本次实际计时，可能有新的文件 SHA；参数 identity 及相应回执应一同核验。旧 secondary 的失败资格原样保留，新 secondary 是一个独立登记的模型。

3. 完成全部十五个生成器训练。

```bash
"$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.training_run" \
  --cache "$HEPTA_CACHE" --manifest "$HEPTA_RUNS/sources/source-manifest.json" \
  --protocol "$HEPTA_PROTOCOL" --qualification "$HEPTA_RUNS/qualification/result.json" \
  --primary "$HEPTA_RUNS/base/reward-observer.pt" \
  --warm-start "$HEPTA_RUNS/base/supervised.pt" --output "$HEPTA_RUNS/training"
```

4. 拟合全部控制器、统一封存，然后评价全部留出条件。

```bash
"$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.control_run" \
  --cache "$HEPTA_CACHE" --manifest "$HEPTA_RUNS/sources/source-manifest.json" \
  --protocol "$HEPTA_PROTOCOL" --training "$HEPTA_RUNS/training" \
  --qualification "$HEPTA_RUNS/qualification" --primary "$HEPTA_RUNS/base/reward-observer.pt" \
  --output "$HEPTA_RUNS/control"

"$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.analysis" \
  --control "$HEPTA_RUNS/control" --protocol "$HEPTA_PROTOCOL" \
  --manifest "$HEPTA_RUNS/sources/source-manifest.json" --output "$HEPTA_RUNS/analysis"
```

完整评价为 24 个条件、491,520 条策略重放行，独立来源单位仍是 128 个来源对，另有五个交叉训练 seed。每个模型实际执行全部 21 条候选路径，共 1,290,240 个候选终端节点；固定动力学干预另列。

5. 在训练、候选路径生成及独立审计均结束后，串行执行两份计时。避免同时运行其他重计算任务。

```bash
for HEPTA_TIMING_PROFILE in registered_three supplementary_all; do
  "$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.timing_run" \
    --cache "$HEPTA_CACHE" --manifest "$HEPTA_RUNS/sources/source-manifest.json" \
    --protocol "$HEPTA_PROTOCOL" --training "$HEPTA_RUNS/training" \
    --control "$HEPTA_RUNS/control" --qualification "$HEPTA_RUNS/qualification" \
    --primary "$HEPTA_RUNS/base/reward-observer.pt" \
    --view-profile "$HEPTA_TIMING_PROFILE" \
    --output "$HEPTA_RUNS/timing-$HEPTA_TIMING_PROFILE"
done
```

两份计时共用同一批八个来源对；相同场景或重复 round 不增加独立来源数。主质量评价与计时使用相同的采样规律，但批大小及随机流不同，不承诺逐输出相同。质量与成本联合分析使用计时队列自己实际生成并评分的输出。

6. 全视图计时完成后，运行同队列的描述性质量／成本分析。

```bash
"$HEPTA_PYTHON" -B -m "$HEPTA_MODULE.cost_analysis" \
  --timing "$HEPTA_RUNS/timing-supplementary_all" --protocol "$HEPTA_PROTOCOL" \
  --manifest "$HEPTA_RUNS/sources/source-manifest.json" --output "$HEPTA_RUNS/cost-analysis"
```

价格情景没有外部标定，不能用其中最有利的一点替代主端点。原始效用、动作代理成本和计入实际随机耗时的效用分别报告。

## 证据阅读方式

[恢复与训练汇总](results/recovery-and-training-001/)保存基础恢复、评分器资格、十五模型训练、768,000 对媒体重评分及三臂恢复核验的聚合回执。原始输出、模型、逐步 RNG／Adam checkpoint 和运行日志由各运行目录保留；Git 中的聚合回执不等于已保存全部原始媒体。

独立审计分清覆盖范围：训练媒体审计遍历所有实际训练输出；留出 selected-tree 审计重评分所有已选 public/oracle 路径的去重集合及指定干预。后者不宣称独立重评分全部候选节点。

完整脚本执行来源另按字节归档于 [orchestrators_001](results/orchestrators_001/manifest.json)。其中包含原环境绝对路径，是实际执行的来源记录；迁移目录后重新生成的登记文件会有新的 identity。不要修改旧回执以伪装成相同运行。

工程测试与科学门槛分开记录。模块旁的 `*_tests.py` 检查采样、非预知性、风险递推、配对统计、篡改拒绝及真实序列化。真实留出比较决定是否观察到收益；原生 Hepta admission 和全模态神经生成还需要各自的证据。
