# 独立预确认审阅与正式原始统计复核

审阅者：`continuity_audit`，与 `missing_content` 作者分开。正式冻结源码：`cf15dfe62476b0081c0d5d329671e345033794c7`。本次审阅没有修改冻结源、重新训练、选择模型或打开其他确认流。

## 结论

**本轮已登记的有限缺测校准验收，通过独立原始统计复核。** 它是普通和 Flow 核心共用的已知生成器推断修复，不构成解析核心收益、学习型缺测处理、真实全模态或生产采用资格。

独立审计程序 `audit_confirm_independent.py` 不导入项目 `posterior.py`、`audit.py` 或 `confirm.py` 的推断、评分和汇总函数。只复用已冻结的原始生成器，重建同一个已经打开的确认数据，确认保存的输入／标签／擦除标记／READ 返回与其完全一致；没有生成另一批测试数据。

审计针对每个 prefix 独立枚举四个 key × 八个 value 的全部可能擦除 WRITE，依次施加初始四 key、无放回 value、Selective 两个不同覆盖 key 等公开约束，再由剩余世界频数形成后验。它没有读取目标或 `target_available` 来选择后验。

| 核查项 | 实际范围与结果 |
|---|---|
| 真实 raw prefix 后验 | 3,072 个全部独立重建，与存档 reference 一致 |
| 原始模型预测 | 18 个 NPZ 的哈希、labels、available 均一致；从 logits 重新算原概率 |
| 校准改动 | 所有不确定 query 等于独立后验；所有确定 query 原概率逐值不变 |
| 准确率、Brier、NLL | 总体／available／unavailable 指标全部重新计算 |
| Proper-score 验收 | 12 个已登记 episode bootstrap 下界全部重算并通过 |
| 拒答验收 | 18 个模型的 episode 级 exact binomial 下界全部重算并通过 |
| 原登记独立参照 | 48 个 prefix 的 latent world 数与结果一致 |
| 实际 READ | 1,536 个真实原始返回、先选动作和两个后继得分全部复算；取得 WRITE 后四值全恢复 |
| 源与权重 | 全部 manifest 项和 18 个 checkpoint 审计前后哈希一致 |
| 比较量 | 3,562,414 个数值元素；最大绝对差 3.55e-15 |

同一个 episode 内的四次 query 及三个固定 checkpoint 没有被当作独立样本。Proper-score 统计先在每个 episode 内平均三个固定 checkpoint 的配对改进，再重采样 1,024 个独立 episode，沿用 5,000 次 bootstrap 及 `0.05/12` 分位点。它是预登记的 bootstrap 近似，不是精确有限样本覆盖定理。拒答门则逐模型按具有至少一条接受预测的 episode，核查是否存在任一接受错误，使用 `0.05/18` 的单侧 Clopper–Pearson 下界。

## 修复的实际含义

MQAR 缺失目标正确率从约 0.163% 提升到 20.410%；Binding 提升到 19.824%；Selective 为 16.887%。这些是同一新流上的点估计。MQAR 和 Binding 的条件后验通常在五个未见类别上均匀；Selective 的原始／覆盖缺失类型不同，不能一律用八分类或五分类均匀猜测解释。

校准后高置信度接受预测在本次样本中全部正确，但覆盖率相应下降：MQAR／Binding 为 75%，Selective 约 65.942%。没有把拒答后的准确率解释为所有问题均能回答。普通与 Flow 的修复后正确率相同；剩余已知内容的概率细节仍来自各自原模型。

## 预确认审阅及已闭合问题

在新确认流打开之前，独立审阅已核查 Selective 的可识别性：擦除初始 WRITE 时，其 key 可由其他三个 initial key 确定；擦除 overwrite 时，key 只能落在其余三个未被另一 overwrite 使用的地址上。新代码枚举这些 key 与未见 value，没有假装知道真实 erased key。

另运行 seed `162901` 的 96 个 DEV prefix，后验与独立排列枚举最大误差为 0；Selective 包含 23 个初始擦除和 9 个覆盖擦除。这个预审使用项目中与 `infer` 分开的排列参照；最终审计才是本审阅者另写的 raw-token 枚举器。该预审不属于新确认样本。

预审要求并确认作者修复了四项执行合同：

- 显式验证完整 18 个 `(task, core, seed)` 以及 18/12/3/48 的结果数量。
- 运行末尾重新核验全部 18 个权重，而不只检查源码 manifest。
- READ 动作在实际 acquisition 和目标评分之前选出。
- 校准接口要求规范 FP64 概率，保证已知行的字节保持说法有明确 dtype 范围。

最终预审另用 seed `162902` 的 12 个 DEV 样本核验 FP64 接受、FP32 拒绝，并实际核对全部源和权重哈希。精确身份、修改闭合与命令见 `INDEPENDENT_REVIEW.json`。

预审的 96-prefix 检查可用下列命令复现，仍只属于开发回归：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -B - <<'PY'
import numpy as np
from experiments.hcsn_addressed_flow_20261101 import data
from experiments.hcsn_missing_posterior_r16_20261101.posterior import infer
from experiments.hcsn_missing_posterior_r16_20261101.audit import independent
for task in data.CONTENT_TASKS:
    arrays = data.batch(task, 32, 162901, 'dev', 'missing')
    first = arrays['x'].shape[1] - 4
    for row in range(32):
        x, observed = arrays['x'][row, :first], arrays['observed'][row, :first]
        actual = infer(task, x, observed)
        expected, _ = independent(task, x, observed)
        np.testing.assert_allclose(actual.by_address(), expected, rtol=0, atol=1e-14)
        for key, value in np.unique(actual.missing_events, axis=0):
            token = np.zeros(24)
            token[key] = token[4 + value] = token[12] = 1
            assert np.all(actual.acquire(token).by_address().max(1) == 1)
PY
```

## 成本与审计边界

原唯一确认的外层 fresh-process receipt 为 **19.116589 CPU 秒、20.226870 wall 秒**，包含启动、导入、模型／参照／READ 工作和输出。内层 `SUMMARY` 的 14.848721 CPU 秒包含在其中，不再次相加。日志哈希、user＋system CPU 恒等式及外层包围内层计时均通过审查。这是对原测量收据的身份和算术检查，不是事后重新测量原时钟。

独立最终审计另用 **6.204706 整进程 CPU 秒、11.791294 wall 秒**；其内部 4.343385 CPU 秒同样不能重复相加。预审、编辑和更早开发不在这两个数字里。实际能耗仍为 null。

最终审计从保存的 logits 重算统计，没有第二次执行全部神经网络 forward；checkpoint 身份与冻结执行记录单独核查。它也没有把 schema 层的因果源代码检查升级成独立硬件逐步信息流证明。没有新模型、开放域语义、视频增量、GPU 或生产门由此获得资格。

## 重跑独立审计

使用新输出名，程序拒绝覆盖既有回执。重跑固定 `confirmation_01` 是原始证据复核，不能当作另一独立确认：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -B -m experiments.hcsn_missing_posterior_r16_20261101.audit_confirm_independent --run experiments/hcsn_missing_posterior_r16_20261101/confirmation_01 --output experiments/hcsn_missing_posterior_r16_20261101/INDEPENDENT_CONFIRMATION_REPLAY.json
```
