# 解析 Belief 旁路：一次结构消融，零新增权重编辑

本包检验一个具体机制：模型已经计算了与终止任务同一时间、同一事件的解析概率，又让 learned Belief head 从混合特征再次预测同一终止事件；直接使用模型自己的解析输出，是否改善概率误差及完整任务效用？原 Belief 的训练目标是 teacher posterior，并非拟合自身 bank[7]。实验固定于公开 `hepta-private-ci` 的原 joint 模型与有限 CTMC 任务，源 commit 为 `5b69a046d886cf4c2a73c50e58197360ea15d8f5`。

**结果同时包含正向结构证据和验收限制。** 在预先指定 seed `870160000` 的 320 个测试世界上，未门控的 P 相对 A 在 IID/OOD 两域、全部五个训练 fit 上均提高完整 expected utility；五 fit 描述性 95% 区间均为正。两域后验概率误差也均下降。按冻结的原 VAL 门执行时，P 仅接受 1/5 fit，CP 接受 2/5 fit；门控后相对各自当前基线的任务收益区间均跨零。交付前发现 64/320 个日程与早先另一 fit 的测试重合，故不能声称所有测试日程全局未见，具体勘误见下文。本包没有把原始结构信号当作门控部署成功，也没有将旁路写成纯权重编辑成功。

唯一新增干预是执行图分支，新增参数编辑、梯度步骤、候选搜索、超参数重试均为 **0**。旧 C 相对 A 已存在的 continuation 权重修改属于前一项研究，本轮不再次拟合 C。科学运行只有一次，主计时段 19.757740 CPU 秒，退出码 0，stderr 为空。

## 1. 源码语义与可证明范围

完整执行前论证见 [SOURCE_SEMANTICS.md](SOURCE_SEMANTICS.md)，五份实际 checkpoint 的预检身份见 [SEMANTICS_BEFORE_RUN.json](SEMANTICS_BEFORE_RUN.json)。该任务终止目标是固定第 6 步的 `coordinate > 0`，提前提交仍预测此事件。`NumpyPolicy.represent` 按模型自己的转移表与 decoder confusion，在实际 `observation_tick` 更新观测历史，得到 33 维 conditional mass。

若当前模型质量为行向量 \(m_t\)，未来模型转移为 \(P_t,\ldots,P_5\)，正类指示向量为 \(e_+\)，则模型自己的终止概率为

\[
p_{\mathrm{model}} = m_t P_t \cdots P_5 e_+.
\]

forecast bank 的三组 horizon 是下一边界、后两边界和 deadline=6，每组阈值为 −0.5、0、0.5。因此零起始 `bank[7]` 恰是本任务 deadline 正类概率，等于 85 维原特征的 `raw[83]`。本轮在所有缓存特征状态上另用同一模型 mass 和剩余转移表重新传播，验证这一等式；最大绝对差为 `3.3306690738754696e-16`，低于预设 `2e-12`。

这里使用的是**模型后验**。只有初始分布、转移、emission、观测时点和目标事件都与 Oracle 匹配时，滤波归纳才能保证它等于 Oracle 后验。本轮没有把 teacher posterior 作为 scorer 的输入。Oracle 只在既有有限任务的评分器中用于指标目标、动作后效用及期望分支概率。

这也界定了状态充分性：单独的 mass33 不含当前 tick 和剩余日程，通常不足以确定 deadline 概率；本模型还提供 public43 与 forecast bank。当前指数恢复 CTMC 的两个 refractory 状态足以表示该有限模型的恢复动力学，但不自动适用于非指数恢复年龄、累计 reset 次数或历史 first-passage 事件。任务 REPAIR 修复观测服务的 broken 状态，与隐状态 CTMC 边界恢复不同。

## 2. 四臂与冻结顺序

| 原始臂 | checkpoint | 终止 Belief | continuation 三输出 | 本轮新增权重编辑 |
|---|---|---|---|---:|
| A | 原始 renewal | 原 learned head | 原始 | 0 |
| C | 前项研究冻结的 C | 原 learned head | 旧 C | 0 |
| P | 与 A 完全相同 | 自身 `bank[7]` | 与 A 完全相同 | 0 |
| CP | 与 C 完全相同 | 自身 `bank[7]` | 与 C 完全相同 | 0 |

旁路只替换返回的 Belief 概率及两项 submit score：`1-2p`、`2p-1`。STOP、WAIT/READ/REPAIR score、合法动作、转移表、decoder、预算、计时、费用和精确效用递推均沿用原定义。两 submit score 相反源于本二分类事件穷尽状态，不代表一般 Call/Put first-passage 概率互补。

执行前 [协议](PROTOCOL_BEFORE_RESULTS.json) 固定唯一候选、源 hash、五个 fit、验证规则、新总 seed、样本数和 120 CPU 秒硬上限。随后先计算所有五 fit 的原 TRAIN/VAL 四臂指标并逐份写入 `fit_*_BEFORE_TEST.json`，再写入 [全部门冻结收据](records/ALL_TRAIN_VAL_BEFORE_TEST.json)，最后才生成本轮测试世界。收据 hash 链与进程事件能核验记录顺序，不是外部公开预注册或独立时间戳公证，也不能仅凭不同 ID 保证跨研究日程未重用。

固定门是 P−A ≥0.005、CP−C ≥0.005。拒绝时恢复对应 learned 执行模式，checkpoint 参数从未被旁路修改。这里使用的是**冻结的原 VAL 门**，该 VAL 也曾用于选择旧 C，不能称为全新独立验证集。所有门都在新测试前冻结，没有根据测试结果改变门或选择臂。

| fit | 原 VAL：P−A | 接受 P | 原 VAL：CP−C | 接受 CP |
|---:|---:|:---:|---:|:---:|
| 11 | −0.0002996262 | 否 | +0.0060637278 | 是 |
| 23 | +0.0001675086 | 否 | +0.0055073319 | 是 |
| 37 | +0.0005795886 | 否 | −0.0155745085 | 否 |
| 53 | +0.0002026194 | 否 | +0.0016750941 | 否 |
| 71 | +0.0172415808 | 是 | +0.0013055251 | 否 |

## 3. 指标定义与原 TRAIN/VAL 结果

`expected_utility` 是原已知有限 CTMC 法则下的完整策略期望收益，含原动作成本、失败、异步观测和提前终止；不是 Q-MSE 代理，也不是抽取单次轨迹的回报。每 fit 原 TRAIN 为 64 个世界，原 VAL 为 16 个世界。测试每 fit 每域 32 个世界，五 fit 合计 320 个测试世界，含下述 64 个跨研究重用日程。每个世界的随机结果由既有递推积分，世界本身仍是有限样本，真实环境适用性仍受任务模型限制。

记录中的 `belief_brier` 精确定义为 `mean((p - Oracle.posterior)^2)`，即后验概率 MSE，也等于相对 Oracle 的 Brier excess risk；不含 Bernoulli 标签的不可约项 `p_oracle*(1-p_oracle)`。它不是实测交易标签 Brier。`q_mse` 先在每个 probe 行内平均合法动作的平方误差，再跨行平均；`continuation_q_mse` 则在所有合法 WAIT/READ/REPAIR 项上统一平均。probe 来自固定行为策略，所有臂共享，不是各臂访问分布。报告先对每 fit 汇总，再对五 fit 等权平均。完整 probe、逐世界收益和未四舍五入值均保留。

| split | 臂 | 完整 utility | Belief 后验 MSE | Q-MSE | continuation Q-MSE |
|---|---|---:|---:|---:|---:|
| TRAIN | A | 0.2412000255 | 0.0002682476 | 0.0040076345 | 0.0105101764 |
| TRAIN | C | 0.2513658602 | 0.0002682476 | 0.0030736502 | 0.0076922168 |
| TRAIN | P | 0.2411236680 | 0.0002310929 | 0.0039020604 | 0.0105101764 |
| TRAIN | CP | 0.2493588368 | 0.0002310929 | 0.0029680761 | 0.0076922168 |
| 原 VAL | A | 0.2035406899 | 0.0006109115 | 0.0089639776 | 0.0236428254 |
| 原 VAL | C | 0.2372673844 | 0.0006109115 | 0.0079100362 | 0.0204858922 |
| 原 VAL | P | 0.2071190241 | 0.0001555516 | 0.0081278872 | 0.0236428254 |
| 原 VAL | CP | 0.2370628185 | 0.0001555516 | 0.0070739458 | 0.0204858922 |

原 TRAIN 的平均 utility 没有改善，因此结果不能概括为“解析概率一换就必然提高策略价值”。P/CP 的 continuation Q-MSE 分别与 A/C 完全一致；降低终止概率误差不会自动修复 continuation 的 Bellman 关系、动作排序或全局 NDU 目标。

## 4. 指定测试世界的原始与门控结果

**跨研究种子碰撞勘误。** 记录审阅在科学运行完成后发现生成器使用 `total_seed + fit*10000`，因此本轮 fit11 与旧 `870040000` 研究 fit23 的实际随机种子相等：`870160000 + 11*10000 = 870040000 + 23*10000 = 870270000`。OOD 两边同加 1000000，也相等。只在内存中将本轮 fit11 的世界 ID 改回旧 fit23 的命名，序列化 SHA 即分别精确等于旧结果记录：IID `85777af0a0e60ac97b3864ef7f101add2951673f27ba6917d6ab2170afcc2093`，OOD `b971f69307dd671dcc699440af9f411173c4918cb849750fa5f3f8b0b6964b40`。这 64/320 个日程先前由另一 checkpoint 评分过；不同总种子和不同世界 ID 不构成全局未见日程保证。

冻结 driver、协议、结果及既有 CI 均保持原字节，不重跑、不剔除 fit、不换种子。所有门先于本轮生成/评分的顺序仍成立，但全部效力结论保持探索性；不将这次运行当作完全独立于此前研究的确认性验证。原协议中的 fresh 是当时设计意图，不是已证明的全研究去重事实；独立 verifier 的 world 计数与本地 ID 检查也不应误解为全研究日程去重证明。

完整审计见 [SEED_OVERLAP_ERRATUM.md](SEED_OVERLAP_ERRATUM.md) 和 [seed_overlap_audit.json](seed_overlap_audit.json)。它覆盖当前 10 个 block 与三项旧研究 30 个 block 的 300 次比较、全部四研究 fit/domain 的 seed、现存当前及旧网格逐世界内容，以及原 TRAIN/VAL/正式确认 cohort 的源码种子定义。本轮日程内部与旧网格的逐世界比较无重复，但不能证明剩余 256 个日程在所有历史来源中未出现；可确认全局未见数量保持 `null`。另有三组 behavior RNG seed 碰撞，其含义限于 RNG 初值相等，不声明 probe 内容相同。

| 域 | 臂 | 完整 utility | Belief 后验 MSE | Q-MSE |
|---|---|---:|---:|---:|
| IID | A | 0.2199835923 | 0.0004671731 | 0.0073373301 |
| IID | C | 0.2388294429 | 0.0004671731 | 0.0068981706 |
| IID | P | 0.2255392739 | 0.0002552645 | 0.0069252189 |
| IID | CP | 0.2456453937 | 0.0002552645 | 0.0064860594 |
| IID | P_gated | 0.2209271133 | 0.0004372930 | 0.0072817895 |
| IID | CP_gated | 0.2405549975 | 0.0003692651 | 0.0067082908 |
| OOD | A | 0.1191587572 | 0.0040542276 | 0.0374149400 |
| OOD | C | 0.1296199242 | 0.0040542276 | 0.0362534383 |
| OOD | P | 0.1576995829 | 0.0003864558 | 0.0309538121 |
| OOD | CP | 0.1554207446 | 0.0003864558 | 0.0297923103 |
| OOD | P_gated | 0.1264881195 | 0.0035369613 | 0.0365155643 |
| OOD | CP_gated | 0.1325687199 | 0.0030317408 | 0.0343763784 |

以下区间是五个原独立训练 fit 的成对 Student-t 描述性 95% 区间，df=4；未做多重比较校正。不能把 320 个共享 checkpoint 的世界当作 320 次独立训练重复。完整的六类 contrast × 三指标 × 两域，共 36 组区间都在 `records/RESULTS.json.gz`，独立 helper 全部重算。

| 完整 utility 差值 | IID 均值 [描述性 95% CI] | OOD 均值 [描述性 95% CI] |
|---|---|---|
| P−A，原始 | +0.0055556816 [0.0025252581, 0.0085861051] | +0.0385408257 [0.0031720762, 0.0739095752] |
| CP−C，原始 | +0.0068159508 [0.0015806005, 0.0120513011] | +0.0258008203 [−0.0024576250, 0.0540592657] |
| P_gated−A | +0.0009435210 [−0.0016761132, 0.0035631552] | +0.0073293623 [−0.0130202098, 0.0276789344] |
| CP_gated−C | +0.0017255546 [−0.0022687892, 0.0057198984] | +0.0029487956 [−0.0141147482, 0.0200123394] |
| C−A，已有 continuation 对照 | +0.0188458506 [−0.0214270623, 0.0591187635] | +0.0104611670 [−0.0070577682, 0.0279801022] |
| 交互 CP−C−P+A | +0.0012602692 [−0.0040018556, 0.0065223940] | −0.0127400053 [−0.0423192383, 0.0168392276] |

| fit | IID：P−A | OOD：P−A | IID：CP−C | OOD：CP−C |
|---:|---:|---:|---:|---:|
| 11 | +0.0061418167 | +0.0297500180 | +0.0012265764 | +0.0259489595 |
| 23 | +0.0018563157 | +0.0008327658 | +0.0074011964 | −0.0112049813 |
| 37 | +0.0083340656 | +0.0458276103 | +0.0130429225 | +0.0475930462 |
| 53 | +0.0067286051 | +0.0796469228 | +0.0061516066 | +0.0257848182 |
| 71 | +0.0047176049 | +0.0366468116 | +0.0062574520 | +0.0408822591 |

Belief 后验 MSE 的原始 P−A 与 CP−C 相等：IID 为 `−0.00021190856635418506`，CI `[−0.0002722848426870092, −0.0001515322900213609]`；OOD 为 `−0.003667771786902`，CI `[−0.006102083316588456, −0.0012334602572155436]`。全部五 fit 两域均下降。continuation Q-MSE 在 IID 仍为 A/P 的 `0.019490467915580574` 与 C/CP 的 `0.01812524564799769`；在 OOD 为 `0.08979569548369645` 与 `0.08646919821053924`，旁路未改变它们。

这些结果支持的局部机制是：在此固定模型、任务及共同 probe 上，现成解析 forecast 比 learned Belief 更接近 Oracle 后验；绕过后者在本轮原始四臂对照中改善了概率误差及部分策略价值。它不单独区分 head 的拟合不足、混合特征压缩和泛化误差，也不证明任意解析 core 都已正确，或纯权重编辑足以实现相同函数。当前 85→48 tanh→4 head 把 bank 与其他特征混合，不能仅凭选择 raw[83] 的概念直接指定现有 49 个 Belief 参数就获得精确旁路。

门控结果的区间仍跨零，且原 VAL 被复用，本轮没有形成可声明部署收益优势的资格。raw CP 的 OOD 也有一个 fit 退化。没有比较完整梯度重训成本，没有新 LLM 编辑能力测试，没有 FullHX、Current100k 或 HeptaTrader 实盘验证。

## 5. 数值、成本和证据保全

| 项目 | 实际记录 |
|---|---:|
| 科学主计时段 CPU 秒 | 19.757740000000002 |
| 科学主计时段 wall 秒 | 20.016549041999998 |
| 测量点进程累计 CPU 秒 | 19.814992 |
| 峰值 RSS 字节 | 123584512 |
| CPU 硬上限 / soft signal / 协作检查 | 120 / 115 / 110 秒 |
| strict reference 矩阵积 | 713873 |
| 与 BLAS 最大绝对差 | 8.881784197001252e−16 |
| 非有限矩阵结果 | 0 |
| 检查的唯一特征状态总数 | 16570 |
| `bank[7]` 全状态最小 / 最大 | 0.016479630399495675 / 0.9837718725938918 |
| 非法概率 / projection 新增裁剪 / teacher 输入 | 0 / 0 / 0 |

主计时终点在最终 results 压缩和 qualification 写入之前；120 CPU 秒硬门覆盖完整进程，因此主计时不是全部包装 I/O 的总耗时。实现使用显式 reduction 参考矩阵积，NumPy overflow/invalid/divide 设为 raise；BLAS 只作数值对照。旧 learned sigmoid 自带的 logit ±700 裁剪保持不变，“零裁剪”仅指新增 projection。概率越界或非有限会使整次运行失败，未做暗中 clip。

运行环境为 Python 3.9.6、NumPy 2.0.2、macOS arm64，线程数固定为 1。此次约 20 秒是有限 CTMC 消融成本，不是大型模型部署加速或训练成本优越性证据。

`PREVIOUS_123_BEFORE.json` 与 `OLD_123_PRESERVATION.json` 保留旧 88 个分组 payload 文件和旧 NDU value-grid 35 文件的完整前后大小/SHA；本次实验未改这些文件。可变总根文档未纳入旧 123 清单。38 个原始结果文件逐字节转移核验，收据为 `TRANSFER_VERIFICATION.json`；`records/PROCESS_VERIFICATION.json` 保存去主机身份的完成状态和 12 个有序阶段事件。包内只有公开源模型派生的有限任务记录，不包含新 HeptaTrader 行数据、账户或订单、原模型权重副本、主机绝对操作路径或下载缓存。

## 6. 独立验证与复现入口

建议本目录发布为 `tools/hcsn/wsp_20261104/analytic_belief`，与 `joint`、`exploratory_belief`、`ndu_value_grid` 相邻。后面命令从本目录执行。记录验证需要 Python 与 NumPy，不运行模型、不下载权重、不生成新世界：

```bash
PYTHONDONTWRITEBYTECODE=1 python verify_analytic_belief.py \
  --study-root ../joint \
  --old-heads ../exploratory_belief/OLD_CONTINUATION_HEADS.json.gz

PYTHONDONTWRITEBYTECODE=1 python verify_seed_overlap.py --study-root ../joint
```

已实际通过：20 份 probe、100 个臂×split 记录、320 个本轮世界记录、36 个 contrast×metric CI、123 个旧文件大小及 hash、38 个转移原始文件及 12 条进程事件。helper 不导入实验 driver/evaluator；以标量求和、first-legal argmax 和独立标准差公式复算记录指标。其职责是记录算术和身份一致性，不是第二次模型运行、全研究日程去重或对物理真值的独立证明。执行收据见 [INDEPENDENT_RECORD_VERIFICATION.json](records/INDEPENDENT_RECORD_VERIFICATION.json)。

第二个 helper 只使用 Python 标准库，重建种子组合和既存记录的内容身份，再与 overlap 收据比较；状态为 `passed_with_disclosed_cross_study_reuse`。它没有模型调用或随机数生成，核对通过表示重用事实与范围已经披露，不表示没有重用。

若需从原公开 checkpoint 重跑，先用 joint acquisition 验证原归档的全部成员再提取所需十个输入，输出目录必须不存在。示例路径是使用者选择的占位符：

```bash
python ../joint/acquire_inputs.py --output /absolute/path/to/new-public-inputs

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
VECLIB_MAXIMUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
python -B run_analytic_belief.py \
  --study-root ../joint \
  --inputs /absolute/path/to/new-public-inputs \
  --old-results ../joint/records/results_strict.json.gz \
  --old-heads ../exploratory_belief/OLD_CONTINUATION_HEADS.json.gz \
  --output /absolute/path/to/new-analytic-bypass-run
```

也可给 acquisition 传 `--repository` 指向含固定 commit 的 checkout，或传 `--archive` 使用现有但仍完整校验的公开归档。重新运行必须使用独立输出目录；固定协议与 driver 的 SHA 校验会拒绝静默修改。程序使用 Unix `resource.RLIMIT_CPU`，相同 CPU 限额在较慢主机可能按协议阻断，不应为完成结果偷偷延长该研究的门。

身份锚点：协议 SHA `88de0753b8e1c36bab97768b3fa8c55cb43d5ef17a3f0700fa0ed8912fe15515`；执行 driver SHA `9e8950bbf7949a4d9caf5841f3507e042b3a934df0d1be7aba19158e7b7e23c0`；全部门在测试前冻结收据 SHA `8a5a3a1214c594e93280c75d45506a6fddee1acb45a4f32a910c17f780ac778d`；原始压缩结果 SHA `fe5cf45508635bfc4bd96154a073fba3c292d6a82fd452c54b17ac27e3850dfb`。文件级发布白名单为 `MANIFEST.json`；完整机器可读结果资格为 `PACKAGE_QUALIFICATION.json`。
