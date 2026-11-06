# C4 Sparse / Dense 真实原始成本独立复算

## 结论与范围

两条原有 synthetic census 分量的原始字节、执行绑定和逐阶段算术核对通过。每个 target 的 15 个 arm、9 种材料、8 个 sample、64 次尝试及 reuse=16 全部保留；没有缩减采样、扩大原 300 秒子进程预算，也没有重跑 native 或原 reader。

已测样本中，Sparse 对 Dense 的整体降本很小。以每类 8 个 sample 的 **producer thread CPU 总和之比 Dense/Sparse** 计算，target 0 为 **0.992235–1.026487**，target 1 为 **0.991831–1.034214**。比值小于 1 表示这组 Sparse 更慢。9 类等权相加后，Dense/Sparse 分别是 6.071193128/5.995093233 秒与 5.819261528/5.754802636 秒。它们是本次有限观察，不能证明全局最便宜合法策略，也不是无效请求攻击者必付的成本下界。

实际零结构和稀疏结构得到的主要收益在 setup。原 FullLimb Dense 的 setup 仅占这里 producer CPU 的 **2.019%–2.125%**；尝试阶段占 **97.116%–97.785%**。Sparse 把 zero/identity/diagonal 等 setup 压低，但每个 winning/losing attempt 仍执行 challenge-dependent transcript，之后才算 ticket 和判 target。源码 `legal_attempt.rs:104–153` 与这次所有 miss 保留及同 trace/ticket 的数据一致。不能仅从 Sparse、Zero 或 RankOne 名称推出绕过完整 transcript。

这次仍只是原有 **两条 synthetic primitive 分量**：没有执行完整 17-child owner、Mode-A 研究、五 tile 资格、完整模型安装、网络任务注册、native header admission、生产激活或公开服务活性测试。原记录 `challenge_is_native_header=false`、`production_activation=false`、`work_hardness_qualified=false` 全部保留。

## 身份与实物证据

源为 C4 `8df4b21d893906570d48f5beafabb3b31e0aefbc`，tree `6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`。原 source guard 前后相同，记录逐字验证 10,357 个 tracked entries / 985,270,534 字节。锁文件 SHA-256 为 `39ab5baeecb55c5445e6bbbbb359cb4ddcddd75a237e19ec243dc2f0f92849be`；build 为 `--offline --locked --release --jobs 2`、features `[default]`、opt-level 3，配置记录前后相同且无违规项。配置记录本身没有声称完整语义证明。

归档 `C4-synthetic-receipts.tar.xz` 为 7,915,876 字节，SHA-256 `5e8d57f85c506e797a75fb46c46603fce18d00e7572aa10689db59f1ce4d7451`。121 个 chunk、固定远端 version、两段传输 hash、整包 hash 和 37 个 regular members 均独立核对；其中 36 个原始文件共 91,967,135 字节，包括 11 个真实空文件。export index 的 SHA 为 `6c3beecd568ecc3dc31a3e941f80895a40af1316bc46df3649d416c5d2f53d3c`，terminal manifest 为 `5be432e2450a924fb8f477b259236fd4db4174381b599e975bea558f23be2b45`。未知附带 capture.json 仍按原清单保管，没有给予新的执行资格。

实际 build ELF 与两个 child 的 `/proc/exe` 留存 ELF 均为 **940,136 字节**，SHA-256 `5ec78d0664fb0e1d5516c6f6d75383a70b9d1091f01ff1e9ac0cfd24e74c0296`。本次独立重哈希了这些实际字节，并核对原 capture 的 PID/start ticks、coordinator ancestry、post-open identity 标志、精确 launch path/dev/inode、原 before/after build/launch hash。每 child 都有唯一实际捕获；模式 selector 不是 Rust test 个数，Rust tests executed 仍为 0。

两 native 的实际进程 wall 分别为 **183.453322240 秒、81.103040705 秒**（后者精确值见 execution-binding-review.json），在各自原 300 秒内结束、exit 0。原 stdout cap 256 MiB、stderr cap 1 MiB 未变。外层 build 900 / reader 180 / source guard 600 / outer 3600 秒是此前单独登记的外部上限，不冒称这两个 owner 子进程的原预算。

## 独立复算方法与账本

`recompute_sparse.py` 不导入原 reader，也不调用任何 native。它按 cell 重新分组原 JSONL，独立检查 material 字节 hash、public task/challenge/ticket/work ID framing、同材料同 sample/index 的所有 arm trace/ticket 与 materialized proof hash、每个 epoch 的 setup/16 次尝试/teardown、全部 winner 与 loser、phase CPU/wall 加和及 cumulative 计数。完成独立计算后才与已保存的原 reader 结果比对。原 reader 的计数、phase sums、每个已关闭 cache epoch 的固定预算前缀和 2/6 calibration/evaluation 选择全部一致。

| 原始量 | Target 0 (`7f…ff`) | Target 1 (`07…ff`) |
| --- | ---: | ---: |
| JSONL records | 45,907 | 45,907 |
| Requested cells | 1,080 | 1,080 |
| Complete / unsupported / failed | 616 / 464 / 0 | 616 / 464 / 0 |
| Setup calls | 2,928 | 2,928 |
| Closed cache epochs | 2,464 | 2,464 |
| Attempts, including all misses | 39,424 | 39,424 |
| Recorded winning/verified arm attempts | 19,674 | 1,230 |
| Distinct indexed challenge streams | 4,608 | 4,608 |
| Relation winners after duplicate-arm removal | 2,282 | 143 |

2,928 setups 是 616×4 次成功准备，加 464×1 次真实 unsupported 探测。Unsupported 的付费 setup 仍入账，但没有当作 0-cost 合法工作：两 target 分别共花 2.553140 ms 和 2.248095 ms。15 arms 中只有 77 个 class/arm 组合支持执行；每种组合有 8 个 sample。Dense 和 Sparse 都覆盖 9 类，blocked-zero 和 blocked-zero-integer-paired 各只支持 zero，blocked-one-zero-rank-one 只支持左右各一个 zero 的两类。其余不支持的记录没有被删除。

两个 target 共享同一个 task/sample/index challenge、trace 和 ticket 序列，目标不同只改变命中判断与 lazy proof materialization。第二 target 不是又采了 4,608 个独立任务。不同 arm 反复运行同一 stream；19,674/1,230 不能当作互不相同的合法工作数量，更不能相加成链权重。

| CPU 分项（秒；全体 arms 的实际支付） | Target 0 | Target 1 |
| --- | ---: | ---: |
| Setup | 0.800908682 | 0.778351109 |
| Attempts：含所有 miss 与 hit | 66.610123730 | 64.885277767 |
| Producer proof cleanup | 0.405295691 | 0.175256143 |
| Completed epoch teardown | 0.050412679 | 0.042974700 |
| 两 verifier 与其结果 cleanup，另列 | 105.071060026 | 6.472573483 |
| 其中 production verifier | 33.445326655 | 2.061879140 |
| 其中 scalar reference verifier | 71.489706571 | 4.402775671 |
| Native whole-run thread CPU | 183.286544515 | 80.983547680 |

Producer 定义严格为前四项之和，不与 verifier、observed-cell 连续计时或 cached lifetime 重叠相加。Material acquisition、task/raw conversion/rank 观察、审计、JSON 构造与输出单独保留；whole-run 与这些命名 phase 的差额不能直接叫作纯序列化成本。这里 CPU 字段来自同线程 `ThreadCPUTime`，wall 来自 `Instant`，均不是能耗。Whole-run thread CPU 也不等于整个 coordinator 或全系统 CPU。

观测器在两个子进程运行时活动；coordinator 整段 process CPU 记录为 **182.499691561 秒**，包含采集与其他协调工作，不能全算作某个 native attempt，也不能据此推能耗。资源记录为 48 个可见逻辑 CPU、未修改资源限制、未证明 host 独占隔离。这样的壁钟样本不能与不含观测器的旧样本宣称没有测量差异。

## 可汇入联合成本表的有限最低观察

下表每项费用含 **32 次真实 setup + 512 次完整尝试（8×64，含 miss）+ proof cleanup + 32 次 teardown**。每个 cache 只跨实际 16 次尝试。`CPU ms / observed hit` 用同 cell 集合的真实命中数作分母，含全部落空成本；不是忽略失败后只取一个 winner 的时间。Target 1 的分母只有每类 9–26 个 observed hits，不能解读成精确稳态期望成本。

“最低”是本次同 class、同 target、全部 8 samples 的回顾性最小总 CPU，存在事后选择偏差；它既不是隐藏任务预测值，也不是无限 horizon、未知算法或跨不同任务选择的下界。完整逐 arm 数据与成对 sample 比值都在 JSON 中。

| Target | Input class | Cheapest measured arm (all 8 samples) | Producer CPU ms / 512 attempts | CPU ms / attempt | CPU ms / observed hit | Dense / Sparse CPU |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 0 | periodic-dense-fixture | lazy-full-limb-sparse | 714.606714 | 1.395716 | 3.120553 | 1.021168 |
| 0 | full-rank-field | lazy-full-limb | 667.599252 | 1.303905 | 2.702831 | 0.993228 |
| 0 | zero | lazy-full-limb-sparse | 649.620008 | 1.268789 | 2.470038 | 1.012414 |
| 0 | identity | lazy-full-limb-sparse | 651.983667 | 1.273406 | 2.750986 | 1.025543 |
| 0 | rank-one | lazy-full-limb | 673.051100 | 1.314553 | 2.598653 | 0.992235 |
| 0 | sparse-diagonal | lazy-full-limb-sparse | 671.871026 | 1.312248 | 2.859026 | 1.011376 |
| 0 | continuity-maintenance-v1 | maintenance-limb | 633.378336 | 1.237067 | 2.278339 | 1.012294 |
| 0 | left-zero-right-rank-one | lazy-full-limb-sparse | 658.300835 | 1.285744 | 2.420224 | 1.026487 |
| 0 | right-zero-left-rank-one | lazy-full-limb-sparse | 645.952280 | 1.261626 | 2.465467 | 1.020087 |
| 1 | periodic-dense-fixture | lazy-full-limb-sparse | 642.030792 | 1.253966 | 42.802053 | 1.012600 |
| 1 | full-rank-field | lazy-full-limb | 636.074464 | 1.242333 | 39.754654 | 0.991891 |
| 1 | zero | blocked-zero | 634.780825 | 1.239806 | 70.531203 | 1.021655 |
| 1 | identity | lazy-full-limb-sparse | 627.287062 | 1.225170 | 31.364353 | 1.034214 |
| 1 | rank-one | lazy-full-limb | 641.233093 | 1.252408 | 71.248121 | 0.991831 |
| 1 | sparse-diagonal | lazy-full-limb-sparse | 627.372807 | 1.225338 | 48.259447 | 1.021400 |
| 1 | continuity-maintenance-v1 | maintenance-limb | 640.050788 | 1.250099 | 33.686884 | 0.995295 |
| 1 | left-zero-right-rank-one | lazy-full-limb-sparse | 653.697404 | 1.276753 | 40.856088 | 1.003664 |
| 1 | right-zero-left-rank-one | lazy-full-limb-sparse | 636.266722 | 1.242708 | 24.471797 | 1.029628 |

## 选择偏差、授权边界和待联合判断

原 recipe 先用 sample 0–1 选 arm，再在 2–7 上评价。独立重算保持这个划分，没有从后 6 个 sample 重新挑赢家。Target 1 的 full-rank-field 在前两例选择 Sparse，后六例 Dense/selected=0.984709，实际略慢；periodic-dense 两 target 的对应比值为 0.999151 和 0.995229，也没有可靠收益。Continuity target 0 的 calibration-selected maintenance-limb 后六例比值为 1.041081；target 1 为 0.998527。原先登记的选择规则允许这些诚实退步，不能把全 8 例事后最小替换进去。

执行顺序只轮转了 8 次，未把 15 个位置完全平衡：sample 0 Dense 在首位、Sparse 在末位，sample 1–7 Sparse 紧挨在 Dense 之前。报告保留这一缓存、热状态和顺序混杂；几个百分点的差异不能声称普适算法优势或统计显著。全部 18 个 class/target 的 8 对实测比值均保留，未只报有利 sample。

这次实际证明的是：固定 C4 中现存 Sparse/结构化 producer 在明确 synthetic 任务、64 attempts、reuse 16、两 target 的成本和验证行为可核验，没有漏掉其 unsupported 或 losing 尝试。它补上了先前四 Dense 策略并未测 Sparse 的覆盖空白。它没有把公开 API 的数学关系验过提升为活跃链任务授权，也没有完成用户要求的所有最便宜合法工作或公共活性门禁。

无效输入成本必须另外用从零伪 trace/reticket 的实际 raw 和可复用攻击模型计算。不能把上述诚实 producer 的全量 transcript 费用强加给恶意发送者；拿合法 winner 改最后一个 cell 的成本也不能替代从零构造成本。后续 legal-v3、13-arm reused 和 full-limb from-zero 独立复算将分别保留其固定任务、nonce stream、reuse horizon、证明物化和 verifier 定义；不会与本表不同 recipe 的 one-zero 材料合并为同一任务，也不会把四个 verifier 标签当四个 producer。

## 可复核文件

- 原始字节与传输：`C4-synthetic-receipts.tar.xz`、`archive-verification.json`、`extracted/synthetic-census-two-child/`。
- 真实执行记录与 ELF：`execution-binding-review.json`，原 terminal `manifest.json` 与三个保留 ELF。
- 独立计算代码：`recompute_sparse.py`；独立结果：`independent-sparse-recomputation.json`，SHA-256 `ef5908d155df0b3418b1922ddb071c2b9992efa2ab1ea8408c496a7a4870df4e`。
- 可合并静态表：`cost-table.md`。
- 固定 C4 源码：`../w1-independent-c4/source/trillionnium/crates/trnm-crypto-primitives/examples/pon_work_expensive_v1.rs`、`../w1-independent-c4/source/trillionnium/crates/trnm-crypto-primitives/src/pon_work/legal_attempt.rs`、`../w1-independent-c4/source/scripts/pon_work_expensive_reader_v1.py`、`../w1-independent-c4/source/formal/pon-nakamoto-v1/contract_wire.py`。它们之前已经与 C4 Git blobs 独立逐字核对；这次不修改冻源。
