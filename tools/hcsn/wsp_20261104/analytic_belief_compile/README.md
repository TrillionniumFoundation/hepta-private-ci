# 把自身解析 Belief 编译回 49 个现有权重

本包完成了一次纯参数研究：在五份公开 joint renewal checkpoint 上，仅编辑现有 Belief 行的 48 个系数和 1 个 bias，将模型自身 `bank[7]` 的解析概率近似编译回原执行图。原 TRAIN 之外的行未进入拟合；teacher posterior 未进入目标。W1、解析 core、decoder 和对应基线的三个 continuation 输出均保持不变。

**数值编译可行，任务收益尚未形成优势证据。** 五个直接候选和五个投影梯度候选都达到预定的同一凸目标数值精度，存储参数的原始/安全半径均通过 Fraction 精确校验。直接求解显著减少了本次小型凸问题的迭代成本，但主要任务收益区间均包含零。更接近模型自己的解析概率，也不保证更接近 Oracle 后验：TRAIN 自身 logit MSE 均值从 `0.0115570237` 降到 `0.0063172877`，Oracle 后验 MSE 却从 `0.0002682476` 增到 `0.0002910364`。

本轮保持执行图不变，区别于相邻 `analytic_belief` 的零权重解析旁路。它近似编译了模型的自身预测，没有实现精确旁路，也没有证明全局 NDU 最优、FullHX/HeptaTrader 收益、通用 LLM 权重理解或完整梯度训练的成本优势。

## 1. 固定来源、参数与目标

来源是公开 `TrillionniumFoundation/hepta-private-ci` commit `5b69a046d886cf4c2a73c50e58197360ea15d8f5` 的原 joint 交付，训练 fit 为 11、23、37、53、71。完整来源身份在 [冻结设计](DESIGN_BEFORE_RESULTS.json)、[协议](PROTOCOL_BEFORE_RESULTS.json) 和每 fit `PROBLEM` 中。

原模型的 `bank[7] = raw[83]` 是按自身 conditional mass、转移表和 decoder 计算的固定 deadline=6、严格 `coordinate>0` 概率。它只有在模型法则与 Oracle 匹配时才等于真实模型后验。语义依据沿用相邻 [解析旁路源码论证](../analytic_belief/SOURCE_SEMANTICS.md)。本轮仍在每个缓存特征状态上核对 bank7 与同模型剩余时间传播的概率一致性。

每 fit 只取其全部原 TRAIN 行，行数依次为 **308、290、299、341、344**。从该 checkpoint 重建隐藏特征并添加 bias，得到 \(H\in\mathbb{R}^{n\times49}\)，原 Belief 参数为 \(b_0\)。目标为

\[
t_i=\log(p_i)-\log(1-p_i),\qquad p_i=\text{own bank}[7].
\]

要求所有目标概率有限且严格位于 `(0,1)`，否则阻断；没有通过 clip 制造有限 logit。拟合问题固定为

\[
\min_b f(b)=\frac1n\lVert Hb-t\rVert_2^2+10^{-4}\lVert b-b_0\rVert_2^2,
\qquad\lVert b-b_0\rVert_2\le\rho_{\mathrm{safe}},
\]

其中原预算是 \(\rho=0.5\lVert b_0\rVert_2\)，数值安全半径预先固定为 \(\rho_{\mathrm{safe}}=\rho(1-10^{-8})\)。这不是从 VAL 选出的正则或半径。每 fit 恰好求一个直接候选和一个 PGD 候选，没有 lambda 搜索、扩大预算或重新选择目标。

完整 `H`、自身 bank7、logit 目标、b0、Gram、rhs、谱和半径保存在 `records/fit_*_PROBLEM.json.gz`，不混入 teacher posterior。独立 verifier 将 H 对照旧 TRAIN geometry，最大差 `4.579669976578771e-16`；自身概率逐项精确等于旧旁路的 **TRAIN** probe。这条来源链没有使用旧 TEST probe。

## 2. 两个求解器解决同一个凸问题

令 \(\delta=b-b_0\)、\(y=t-Hb_0\)、\(A=H^TH/n+10^{-4}I\)、\(g=H^Ty/n\)。直接解使用 eigendecomposition 与单调标量根，求

\[
(A+\mu I)\delta=g,\quad\mu\ge0,\quad
\mu(\lVert\delta\rVert_2^2-\rho_{\mathrm{safe}}^2)\approx0.
\]

它保留独立 Cholesky 线性解残差、KKT、乘子和互补性诊断。五个 fit 的乘子都为正，说明本轮半径约束均起作用。PGD 从同一 b0 开始，使用同一 H、目标、正则和半径；步长固定为 `1/L`，其中 `L=2*lambda_max(A)`。它只按自己的最终参数 Frank–Wolfe gap ≤`1e-8` 或固定最多 20,000 步停止，不读取直接解作为停止 oracle。

在可行参数处，凸问题的 FW gap 为

\[
\nabla f(b)^T(b-b_0)+\rho_{\mathrm{safe}}\lVert\nabla f(b)\rVert_2.
\]

数学上的该量可界定此固定凸目标的次优性；本包报告的是浮点数值计算值，不把它冒充向外舍入的精确实数全局证书。记录中允许极小的负舍入误差（最低允许 −`1e-12`）；本轮直接解最小报告值约 −`1.08e-19`。独立标量重算得到直接 gap ≤`1.34e-15`、最大 KKT infinity residual 约 `4.86e-14`；PGD 均约 `9.99e-9`。

所有候选都先形成实际 JSON 参数，再重新读回。只替换 `network.w2[3]`、`network.b2[3]`；恢复这 49 个值后必须与其 A/C 父 checkpoint 全部字段相等。`candidate_models` 保留新模型 canonical SHA 和完整 head 导出配方，读回 head 与用于评价的参数逐项相同；包内没有复制完整原模型。

Fraction 检查的是两个存储 binary64 向量的**精确实数差**，不是先舍入的 numpy delta。它同时检查原球 `sum(b0²)/4` 与安全球。预声明的最终数值向内 guard 只在浮点根解、投影或写回导致精确安全球越界时触发，乘 `1-1e-12` 一次后重新核验。实际 D 的 fit11、23 和 G 的 fit53 触发；全部十个候选满足两项预算。此 guard 没有参考 VAL 或任务收益。

| fit | D 正则目标 | G 正则目标 | PGD 步数 | D CPU 秒 | G CPU 秒 | 共享 Gram/谱 CPU 秒 |
|---:|---:|---:|---:|---:|---:|---:|
| 11 | 0.0089899523 | 0.0089899594 | 6549 | 0.003812 | 0.147752 | 0.001470 |
| 23 | 0.0068892936 | 0.0068893014 | 9624 | 0.002531 | 0.216738 | 0.000625 |
| 37 | 0.0080641207 | 0.0080641283 | 5713 | 0.002229 | 0.131426 | 0.000631 |
| 53 | 0.0026068930 | 0.0026068999 | 18039 | 0.002281 | 0.423286 | 0.000646 |
| 71 | 0.0052118354 | 0.0052118421 | 15776 | 0.002226 | 0.351794 | 0.000634 |

## 3. 六个原始臂、四个门控臂

| 臂 | continuation | Belief | 新编辑 |
|---|---|---|---|
| A | 原始 A | 原 learned | 0 |
| C | 旧冻结 C | 原 learned | 0，本轮不重拟合 C |
| D | A | 直接凸编译 | 49 个 Belief 参数 |
| CD | C | 同一个直接编译结果 | 相对 C 的 49 个 Belief 参数 |
| G | A | PGD 编译 | 49 个 Belief 参数 |
| CG | C | 同一个 PGD 结果 | 相对 C 的 49 个 Belief 参数 |

D/G 的接受门为相对 A 完整 validation utility ≥`0.005`；CD/CG 相对 C 使用同一阈值。拒绝时逐参数恢复对应父模型。本轮用的是**冻结的原 VAL**，它也曾用于选择旧 C，不能称为全新独立验证集。

| fit | D−A / G−A 原 VAL gain | D / G 接受 | CD−C / CG−C 原 VAL gain | CD / CG 接受 |
|---:|---:|:---:|---:|:---:|
| 11 | −0.0007246181 | 否 / 否 | −0.0002904027 | 否 / 否 |
| 23 | −0.0041555753 | 否 / 否 | +0.0026700781 | 否 / 否 |
| 37 | 0 | 否 / 否 | −0.0020275528 | 否 / 否 |
| 53 | −0.0005798342 | 否 / 否 | −0.0003822395 | 否 / 否 |
| 71 | +0.0135425138 | 是 / 是 | −0.0012528877 | 否 / 否 |

同格的 D/G validation utility 在本轮数值相同，但它们的参数与概率并不相同。五份全部 solver/原 TRAIN/原 VAL/gate 记录写入 `ALL_SOLVERS_AND_GATES_BEFORE_TEST.json` 后，才生成测试世界。没有依据 TEST 修改候选或 gate。

## 4. 从种子域分隔到实际内容去重

本轮没有继续使用容易发生跨 fit 碰撞的加法总种子。冻结设计摘要、固定生成器 SHA、fit、domain、用途（world / behavior probe）和重复编号组成带字段标签的 canonical JSON，再以 SHA-256 的完整 256 位摘要作为 RNG entropy。设计摘要不包含自身 hash、派生 seed、当前结果或时间戳；20 条 stream 的确切来源与 entropy 都在协议中，并经独立重算。

**不同 seed 仍不能保证不同日程，因此另外检查实际内容。** `HISTORY_REGISTRY.json.gz` 保留 400 个原 TRAIN/VAL 世界与四项旧研究的 1280 个 world occurrences，共 **1680 次来源出现、1616 个唯一日程**。另外 20 个数值重放 block 已核对等同于旧 strict 内容。来源文件 SHA、完整 world 和去除管理性 ID/未读取 packet 占位符后的 canonical schedule 指纹均保留。

全部 320 个本轮世界（五 fit × 两域 × 32）生成后，先与已登记历史及本轮彼此比较，完成 `ALL_TEST_WORLDS_DEDUP_BEFORE_SCORING.json`，才进行任何 TEST scorer、Oracle 或 behavior probe 评价。实际发现 **0 个已知内容重复**。发现重复的预定规则是整次阻断，不补抽、不换 seed、不删除样本。

覆盖范围有明确边界：原正式 confirmation 的 world 内容不在当前可用公开 training archive 内；登记了其源码种子定义，但这不等于逐内容比较。未知或外部历史也不在本审计内。因此只能称“在已登记内容范围内未重复”，不能称所有历史中全球未见。相比先前旁路研究，本轮没有再出现已知的 64 个跨 fit 旧日程复用；所有研究的原记录保持不变。

## 5. 完整任务效用结果

expected utility 仍是原有限 CTMC 法则下包含等待、读操作、修复、失败、异步观测与费用的完整策略期望值，不是 Q-MSE 代理。Oracle 只作评价。以下对每 fit 汇总，再对五 fit 等权平均。95% CI 为五个训练 fit 的配对 Student-t 描述性区间，df=4，未经多重比较校正。

| 原始或门控对照 | IID：均值 [95% CI] | OOD：均值 [95% CI] |
|---|---|---|
| D−A | +0.0018235953 [−0.0027858902, 0.0064330808] | +0.0023913279 [−0.0111387829, 0.0159214387] |
| G−A | +0.0018235953 [−0.0027858902, 0.0064330808] | +0.0023913279 [−0.0111387829, 0.0159214387] |
| CD−C | −0.0021990373 [−0.0047281503, 0.0003300757] | +0.0057464333 [−0.0035080757, 0.0150009423] |
| CG−C | −0.0021990373 [−0.0047281503, 0.0003300757] | +0.0057640148 [−0.0034859738, 0.0150140034] |
| D_gated−A / G_gated−A | +0.0014331155 [−0.0025458511, 0.0054120821] | +0.0012230491 [−0.0021726795, 0.0046187776] |
| CD_gated−C / CG_gated−C | 0 [0, 0] | 0 [0, 0] |
| D−G | 0 [0, 0] | 0 [0, 0] |
| CD−CG | 0 [0, 0] | −0.0000175815 [−0.0000663956, 0.0000312326] |
| C−A，既有 continuation 对照 | +0.0241135515 [−0.0149629227, 0.0631900257] | +0.0217995329 [−0.0052443978, 0.0488434637] |

零门控增量意味着全部恢复 C，不是成功地提高了 C。直接解与 PGD 达到相同凸目标精度也不意味着策略完全相同：OOD fit53 的 CD/CG 出现了约 `8.79e-5` 的 fit 平均 utility 差，记录已保留。

| split / 域 | 臂 | 完整 utility | 对 Oracle 后验 MSE | 自身 bank logit MSE | Q-MSE |
|---|---|---:|---:|---:|---:|
| 原 TRAIN | A | 0.2412000255 | 0.0002682476 | 0.0115570237 | 0.0040076345 |
| 原 TRAIN | D | 0.2398178024 | 0.0002910364 | 0.0063172877 | 0.0040534198 |
| 原 TRAIN | C | 0.2513658602 | 0.0002682476 | 0.0115570237 | 0.0030736502 |
| 原 TRAIN | CD | 0.2495409182 | 0.0002910364 | 0.0063172877 | 0.0031194355 |
| 原 VAL | A | 0.2035406899 | 0.0006109115 | 0.0158267230 | 0.0089639776 |
| 原 VAL | D | 0.2051571871 | 0.0005630964 | 0.0117965753 | 0.0088817977 |
| IID | A | 0.2164845447 | 0.0005018681 | 0.0167272531 | 0.0083260079 |
| IID | C | 0.2405980962 | 0.0005018681 | 0.0167272531 | 0.0073642807 |
| IID | D | 0.2183081400 | 0.0005207785 | 0.0119060826 | 0.0083650576 |
| IID | CD | 0.2383990589 | 0.0005207785 | 0.0119060826 | 0.0074033305 |
| OOD | A | 0.1039622726 | 0.0040396051 | 0.0849777948 | 0.0312311373 |
| OOD | C | 0.1257618055 | 0.0040396051 | 0.0849777948 | 0.0293477451 |
| OOD | D | 0.1063536005 | 0.0033341772 | 0.0661919924 | 0.0300035776 |
| OOD | CD | 0.1315082388 | 0.0033341772 | 0.0661919924 | 0.0281201854 |

完整六个 raw / 四个 gated 臂、全部逐世界收益、七项指标和 **154 组 contrast×metric CI** 均在 `RESULTS.json.gz`。`belief_brier` 精确定义为与 Oracle posterior 的概率 MSE，即 Brier excess risk，不含 Bernoulli 不可约噪声项；不是实际标签 Brier。Q-MSE 先对各行合法动作平均再对行平均；continuation Q-MSE 在合法 continuation 项上汇总。probe 使用固定行为策略，所有臂共享，并非各臂访问分布。

更好地拟合自身 bank 的 logit，与更准确的 Oracle 概率、Bellman Q 和更高任务价值是不同目标。这里既有模型法则与真实法则的差异，也有受限 49 维读出的编译误差；本轮不单独识别各自贡献。半径内的最佳近似仍有非零误差，不能把凸求解成功写成解析概率精确实现。前项旁路研究使用另一批世界，不能把其均值与本轮均值直接当作 P 对 D 的配对比较。

## 6. 完整成本口径

| 五 fit 合计 CPU 阶段 | 秒 |
|---|---:|
| 共享原 TRAIN 特征构建 | 0.452756 |
| 共享 Gram/谱 | 0.004006 |
| 直接 solver（含记录的数值诊断） | 0.013079 |
| PGD solver（含自身停止检查） | 1.270996 |
| 含共享特征与 Gram/谱的 D 编译阶段 | 0.469841 |
| 含相同共享成本的 G 编译阶段 | 1.727758 |
| 整个科学主计时段，包含两者及评价 | 22.614680 |

在这一次同主机 CPU 测量中，只比较 solver 的比值约 97.18；计入 Gram/谱约 74.63；计入特征构建约 **3.68**。它们是同一 49 维固定凸目标容差下的阶段成本观察，非重复性能基准；直接 solver 毫秒级时间尤其容易受计时与环境扰动影响。不能将 solver 比值解释为整个研究、完整模型训练、实际推理或同任务质量的加速倍数。

整轮 wall 为 `22.7039915` 秒，峰值 RSS 为 `128598016` 字节；主计时终点在最终结果压缩/qualification 写入前。180 CPU 秒硬门覆盖完整进程，175 秒 soft signal、170 秒协作检查。运行一次，退出码 0，stderr 为空，没有重跑。

strict reference 路径共记录 `797035` 次矩阵积，含 Gram/solver 运算，BLAS 对照最大绝对差 `1.1546319456101628e-14`，非有限结果 0；没有新增概率 clip。NumPy overflow/invalid/divide 设为 raise。原 learned sigmoid 自带的 logit ±700 裁剪沿用原实现。硬件软件范围为该次 macOS arm64 / Python 3.9.6 / NumPy 2.0.2 单线程 CPU 执行，未用 GPU。

## 7. 验证、可复现入口与发布范围

本目录发布为 `tools/hcsn/wsp_20261104/analytic_belief_compile`；相邻目录为 `joint`、`analytic_belief`、`exploratory_belief` 和 `ndu_value_grid`。从本目录执行两个记录验收入口：

```bash
PYTHONDONTWRITEBYTECODE=1 python verify_belief_compile_records.py \
  --study-root ../joint --analytic-root ../analytic_belief

PYTHONDONTWRITEBYTECODE=1 python verify_belief_solver_records.py \
  --study-root ../joint --analytic-root ../analytic_belief
```

两者均已实际通过。第一项用独立标量运算核 20 个 probe、160 个臂×split 记录、154 个 CI、320 个世界、已知内容去重、冻结顺序及旧 177 文件；第二项独立核全部五个完整凸问题、旧 TRAIN H/自身概率来源、目标、梯度、Gram/rhs、L、μ/KKT/FW 和存储参数的 Fraction 预算，不重新求候选解或迭代 PGD。候选完整 JSON roundtrip 与恢复后等于父模型的检查由已审、已固定身份的 driver 在科学运行中完成；记录 helper 独立核 head 参数 recipe 与记录身份，没有再次取得完整源模型重构 candidate SHA。收据在 `records/INDEPENDENT_RECORD_VERIFICATION.json` 与 `records/INDEPENDENT_SOLVER_VERIFICATION.json`。

完整模型重放需要原公开输入；可用已验证的现有输入目录，或通过 joint acquisition 获取，输出必须是新目录：

```bash
python ../joint/acquire_inputs.py --output /absolute/path/to/new-public-inputs

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
VECLIB_MAXIMUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
python -B run_belief_compile.py \
  --study-root ../joint --analytic-root ../analytic_belief \
  --inputs /absolute/path/to/new-public-inputs \
  --old-results ../joint/records/results_strict.json.gz \
  --old-heads ../exploratory_belief/OLD_CONTINUATION_HEADS.json.gz \
  --output /absolute/path/to/new-belief-compilation-run
```

程序使用 Unix `resource.RLIMIT_CPU`，较慢环境可能在固定硬门下阻断；重新运行不应修改本研究冻结文件。记录验证无需网络、模型前向或随机世界生成。历史 registry 的 preparation helper 用于追溯原保存文件的只读来源构建，当前包已经包含完整冻结 registry；正式确认/未知历史的覆盖缺口始终保留。

工具 UTC `2026-11-04 06:47:29` 记录最终执行前冻结，属于内部可审查顺序，不是外部预注册。协议 SHA `f0b35b698c3da2738ef187fa6dea1f402a418d5cbf317f3fa425c5097fe26e90`；design SHA `da512b0ac3a1fc9c67e8d004456f2c8605dcbddb3ec64888f3431627ec77b18c`；执行 driver SHA `2472219f9d94fda23b74852ef4b09a0377e70c4211bb43bdd67aab6c4304e2f6`。全部 solver/gate 冻结 SHA 为 `35f198fef38058d37d72777bec5777e608b65020cf476cf1740ec37e542c9738`，全部测试内容去重收据 SHA 为 `83c34d0b2edae732f0cade22796fec92cb9579992141e890905670edb9e41bb4`，结果 gzip SHA 为 `63ae9ff85631fd53c70f4dc69a82dc59feaaa84e37a19ed1efcb19e8316babd6`。

49 个原始科学记录按 SHA 逐字节转移；旧 177 个冻结文件前后逐一核对，见 `PREVIOUS_177_BEFORE.json` 与 `OLD_177_PRESERVATION.json`。发布允许集合及大小/SHA 见 `MANIFEST.json`，机器可读资格见 `PACKAGE_QUALIFICATION.json`。本包只有公开 joint 模型派生的合成任务证据，没有新私有 HeptaTrader 行、账号/订单、完整原权重副本、主机绝对操作路径、转移缓存或 Python 缓存。
