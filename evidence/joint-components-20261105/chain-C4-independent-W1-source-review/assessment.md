# C4 W1 成本的独立源码审查

审查时间：2026-11-05 17:56 UTC。审查者：`/root/pq_recovery`，与执行者 `/root/w1_audit` 分工。

**结论：固定实验的计数与计量范围可以精确复核；现有两个实验均不能单独关闭“最便宜合法工作、攻击者最低成本及公开服务活性”。本文件是源码审查，不是 C4 原生运行结果。C4 实际 raw 尚待执行者交付，所有资格状态保持 HOLD。**

本轮没有运行 Cargo、采样、原生测试或成本 collector，没有修改冻结源、验收门禁、时间预算或资源。没有把 C2 或更早历史数据换名为 C4 数据。

## 1. 审查对象与来源

冻结 Chain commit：`8df4b21d893906570d48f5beafabb3b31e0aefbc`；tree：`6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`。

独立读取 GitHub exact C4 commit 和完整 C2→C4 compare。C2 是 `03521b2f32346a49cccde8ff72e8c7b886b31222`。该 compare 恰有三条路径：workflow、`report_module_evidence.py`、`test_applicability.py`。原 `w1/C2-legal-v3-entry-audit.json` 的 22 个本地源文件都重新按实际字节计算 Git blob 并匹配旧清单；其中 **21 个在 C4 未变，workflow 是已知例外**，C3 将原 6 个 legal kernel 测试登记更新到实际 9 个并加入逐名检查。没有笼统声称 22 个都未变。

另从 exact C4 独立取回六个补充源码：rejection collector/reader、当前 `pon_work.rs`、`blocked_zero.rs`、`blocked_one_zero.rs`、`structured.rs`。全部保存于本目录 `source/`；完整字节与 blob 清单见 [source-inventory.json](sandbox:/workspace/scratch/93bfcfe29fc8/pq_recovery/w1-independent-c4/source-inventory.json)，GitHub commit/compare 读回见 [c4-source-retrieval.json](sandbox:/workspace/scratch/93bfcfe29fc8/pq_recovery/w1-independent-c4/c4-source-retrieval.json)。

本文源码代号均指这棵冻结树：

| 代号 | 路径、关键入口 | Git blob |
| --- | --- | --- |
| L | `trillionnium/crates/trnm-pon-node/examples/pon_w1_legal_strategy_v3.rs`：`challenge`、`prepare`、`search`、`cohort`、`run` | `2418f26674eab741c8cda5e219a930d40b36e658` |
| LR | `scripts/pon_w1_legal_strategy_reader_v3.py`：`Records`、`summary`、`rate_diagnostic`、`analyze` | `f740317811f3d0ae035d25985f7069fd2ace28e8` |
| LA | `trillionnium/crates/trnm-crypto-primitives/src/pon_work/legal_attempt.rs`：`Task::new`、`with_preparation`、`attempt_with_progress`、`sparse_preparation` | `b1c5952de1a4b957f85f418d3e6ab66d8a64607a` |
| R | `trillionnium/crates/trnm-crypto-primitives/examples/pon_rejection_cost.rs`：`search`、两种 mutation、`sample_json` | `fce5834c1d9780f058f8aaff4041771c8c173c14` |
| RR | `scripts/pon_work_rejection_report.py`：`validate_search`、`validate_mutation`、`summarize` | `23429d1d01307f61d4df56244e869a628787dda0` |
| K | `trillionnium/crates/trnm-crypto-primitives/src/pon_work.rs`：cheap checks、kernel dispatch、`PreparedTask` | `ce1608248d2ee67ed8f5d82a2c5f15942689139b` |
| Z | `trillionnium/crates/trnm-crypto-primitives/src/pon_work/blocked_zero.rs` | `0ae9356516dd4201b086fc4323296db57fbea219` |
| O | `trillionnium/crates/trnm-crypto-primitives/src/pon_work/blocked_one_zero.rs` | `d95d20caba662c884241a51cb045cfa17fa03983` |
| S | `trillionnium/crates/trnm-crypto-primitives/src/pon_work/structured.rs` | `1358d5f5a2df7f593ecfde0382357961631b6a8f` |

## 2. 两个实验分别比较什么

**Legal v3 是四种生产策略的 2×2 比较。** 两种 challenge transcript arithmetic 为 transposed/full-limb，两种 proof materialization 为 every-attempt/target-hit。`prepare` 对所有格子调用 `Task::new`，实际统一使用 Dense AB 预处理。它没有把四个 verifier 当作四个 producer。[L:95–109；LA:62–89]

**Rejection v2 是一个 PreparedTask producer 和四种 verifier 的比较。** 四个内核是 retained-transposed、scalar-reference、limb-transcript、production-full-limb。每个 cohort 从同一实际合法 winner 构造 legal、transcript mutation、product-last-cell mutation 三种输入；同一输入送给四个内核。[R:71–85、450–488]

一个具体需要修正的解释边界：**当前 C4 的 legal v3 有四个 verifier 入口标签，但只有三种不同内核。** `production` 调 `verify`，`full-limb-experimental` 调 `verify_full_limb`；在当前 `pon_work.rs` 中二者都选择 `VerificationKernel::FullLimb`。这不破坏四种 producer 的 2×2 比较，但不能把 v3 输出称为“四个独立 verifier 内核相互证明”。Rejection v2 明确调用 `verify_transposed`，没有这个重复。[L:36、360–366；K:423–456、530–560]

## 3. 四种合法策略的匹配条件

对固定 class、target、sample、search index、nonce，challenge 由 task hash、target、固定 seed=0、sample、search index、nonce 确定。**策略和 reuse horizon 均不在 challenge 中。** 四种策略从 nonce=0 连续搜索，首个 target hit 即停止，无 hit 则必须保留全部 4096 次尝试。Rust `same_legal_stream` 对完整流与 winner 作一致性检查；reader 再核挑战、ticket、proof digest、命中位置、物化规则及跨 horizon fingerprint。[L:79–93、125–183；LR:188–240、396–412]

H=1、8、64 是每个实际 setup 后进行的 search 次数；命令名称虽然叫 `reuse-winners`，发生 exhaustion 时 **H 不等于实际 winner 数**。每个 cohort 的 setup 确实只执行一次，并实际运行 H 次完整 search，不是把 H=1 的 setup 时间在报表中除以 H。各 horizon 另行准备、另行测量，却共享相同搜索前缀；跨 horizon 不增加相同流的独立性。[L:266–309；LR:315–349]

每个 class 只有一组确定性矩阵材料，八个 sample 变化的是挑战流，而不是八个独立真实任务。两个 target 为 `7f…ff` 和 `07…ff`，相应 target weight 精确为 2、32；这不是生产难度或全体任务分布。[L:18–37、385–417；LR:317]

生产策略执行顺序按 `(sample + target_index + order) % 4` 轮换；八个 sample 中每种策略在每个 cohort 位置出现两次。**Verifier 顺序却不能作同样的分组结论。** 其起点是 `(sample + order + search_index) % 4`。代入固定 strategy 后得到 `(strategy - target_index + search_index) % 4`，sample 抵消。尤其 H=1，固定策略的八个 sample 使用相同 verifier 顺序。跨四种策略合看才覆盖四个起点。按 strategy 输出的 verifier 耗时未消除位置、预热等影响；legal 总在 product-last 之前也没有 case 顺序随机化。[L:275、352–366]

这属于计量解释限制，不是已经发现的 consensus 接受错误。未据此修改冻结源或删减原门禁。

## 4. 时间确切覆盖哪些工作

| 阶段 | Legal v3 实际口径 | Rejection v2 实际口径 |
| --- | --- | --- |
| 共同材料 | 每 shard 单独 `material_setup`；包含材料生成、rank check、材料选择和 task ID；不分摊到四策略 | 每 cohort 的 material、task binding 分项进入 setup |
| 可复用 setup | 每 sample/strategy 实际 Dense AB、prefix、输入复制一次；已包含在 `cohort.total` | 每 cohort 实际 PreparedTask，进入 `honest_acquisition_ns` |
| 所有尝试 | 挑战、完整 transcript、ticket、命中判断、试次保留；eager miss 的 proof 构造和释放在 producer 内 | 每个真实 proof/ticket 尝试均计；phase 时间之外的 audit hashing/记录开销仍包含在 whole search wall |
| Lazy miss | 不分配 proof；仍计算完整 challenge transcript/ticket | 未测 lazy arm，统一 PreparedTask 完整 proof |
| 证据构造 | `trial_evidence` 的完整试次 digest 与 trial JSON values 单独计 CPU/wall | 一部分 hashing/记录已在 whole search wall；最终 JSON/probes 不在 verifier 时间内 |
| Winner/报文输出 | candidate 包装、额外 hash/hex、JSON serialization/write/flush、保留对象最终释放未统一计入 producer 或 trial evidence | JSON serialization、stdout、非计时 probe 不进入 native verification timer |
| 无效构造 | 复制 winner，改变最后 canonical C word；独立 mutation timer | 两种 mutation 分列 clone、patch、fake-ticket search、overhead；含失败 fake candidates |
| 验证 | 每成功 search、每 case/path，单次完整 native verify；无 fact cache | 同一 proof 四内核完整 verify，实际 outcome 与返回 product；另做非计时 progress probe |
| 时钟 | 同线程 CPU 与 monotonic wall，各自求和 | 只有 monotonic wall；不能换成 CPU、能耗或费用 |

来源：L `cohort`/`trial_evidence`，LA `attempt_with_progress`；R `search`/`Mutation::json`/`sample_json`；LR/RR 的 scope 字段与加总代码。

**禁止重复加 setup。** Legal v3 的 `cohort.total` 已含 setup 与所有 searches；分解应为 `total = setup + sum(search timing) + inclusive overhead`，不能再次把 setup 加进总成本。共同 material_setup 单独保留。证据与验证是另外的账，不能把它们悄悄删掉后称为完整节点的端到端成本，也不能让同一阶段在两个分母中重复出现。

另一个材料口径细节：`w1_material::materials(None,None)` 先构造多个默认材料（包括 full-rank 的 rank 检查），随后才选择当前 class，L 再构造两个 one-zero case。因此 `material_setup` 是这个诊断程序实际准备流程的开销，并非某一类生产任务最小的独立准备费用。它被单列是正确的；不能用该值给 zero 等类别加一个不可避免的 full-rank 生成成本。

## 5. 稀疏与零结构的合法捷径已经存在，但未入 v3 四格

LA 的 `Preparation::Sparse` 在完整 canonical validation 后建立 B 的非零行索引，跳过零乘积，仍构造完整固定 product/prefix；挑战 transcript 未减少。v3 的 `prepare` 没有选择它。Sparse 在不同稀疏度可能有不同开销，本轮没有测量其相对速度，不能直接宣布它全域最快。[LA:62–89、164–208]

Z 对精确 zero/zero 直接构造 zero product prefix；每个挑战仍展开噪声并生成完整 transcript，但通过 `ER_prefix × FL_prefix` 及分块因式重排计算。它保留所有 32,768 个 transcript 输出 words 及原 hash 顺序。O 对恰有一边 zero、另一边 nonzero rank-one 的材料推导并核验因子，再用专用路径生成完整 transcript。S 还存在 zero/identity/diagonal/rank-one product preparation；不支持的材料返回 None，而不把通用 fallback 伪装成专用算法。[Z:18–140；O:23–155；S:214–296]

这些是当前源码中真实的数学复用/结构优化，不是“少算一个验证必需步骤”。它们说明：测量一种通用 Dense producer 在 zero 输入上仍执行多少运算，**不能作为任何合法实现都必须付出的成本下界**。同时，源码中有合法算法和相应测试，仍不等于该算法在当前 C4 本次原生预算内已经测得成本；本轮不把既有测试源码当作执行证据。

协议库接受某个 canonical 任务的 proof，也不独立证明普通节点会允许攻击者任意选择或提交该任务。任务可选性、登记、当前挑战及资源 admission 需由普通节点入口的另项证据绑定。

## 6. 无效输入的分母必须区分三种情景

设 `A` 为当前实验中的实际合法 winner acquisition（setup 加所有 honest attempts），`M` 为已有 winner 后的完整增量 mutation，`V` 为 victim 单次拒绝的完整 verifier 成本。

### 6.1 本实验的特定“先诚实生成，再修改”流程

`V / (A + M)` 只回答“这条指定流程，从自己诚实获得一个 winner 开始，花了多少成本”。它可以与 `A/V`、`V/M` 并列报告，**不能当作所有攻击者的最低构造成本**。RR 的字段名 `first_construction_including_honest_acquisition_ns` 必须连同这一前提保留；不是一个任意无效输入的 from-zero lower bound。[RR:413–425]

### 6.2 已有或取得公开 winner

Product mutation 不改 task、challenge、trace 或 ticket；只 clone proof 并将最后 C word 递增模 q。ticket 已经通过，所以无重新采矿。合法 transcript 仍匹配；victim 完成 replay 与 product corrections 才拒绝。故 `V/M` 是必须单独报告的真实增量诊断。攻击者可能复用已获得的 winner；即使某方为 winner 付过 A，也不能在每个攻击请求中重复给攻击者记账 A。[R:269–289；K:807–846]

如果同一个输入可被重复提交 k 次，需要区分一次构造及多次发送、每次重新 clone/变异、网络复制、拒绝 cache、去重、当前挑战过期和 admission 配额。形式上的 `kV/(A+M+发送成本)` 只是带明确条件的模型，不是本实验已经测得的网络结果。四种内核对同一 proof 的四次调用也不是四个独立的攻击 acquisition。[RR:439–445]

### 6.3 从零构造无效 transcript 或重用攻击模板

K 的 cheap checks 只要求长度/version、canonical A/B/C、匹配 expected task、非零 target、`hash(ticket, challenge, trace_claim) <= target`。它不在 replay 前证明 trace_claim 有效。**在已知当前挑战与被允许任务 A/B 的库调用边界，寻找一个便宜的 fake trace/ticket 不要求先生成合法 W1 transcript。** Victim 会在 replay 后发现 Transcript 不符。这里没有推导该输入必能越过普通服务的任务/授权/配额边界。[K:670–725、769–812]

Rejection v2 的 transcript mutation 虽然使用了新的 cheap fake-trace ticket search，但其构造函数仍先 clone 真实 winner；报告把 honest A 算入一种 first-construction 情景。它**没有测量从 canonical task bytes 开始、无真实 winner 的最小无效构造过程**。同样，v3 仅测 product-last，没有覆盖上述 from-zero 路线。[R:291–339；L:239–252、335–374]

因此不能将 honest mining 的成本当作 fake-trace 攻击者的必付下界。对公开服务活性，需要从真实可用输入、模板重用、挑战更新和服务 admission 开始计量；不能仅依据这个库级拒绝实验得出受攻击时的吞吐、p99、诚实失败率或网络攻击预算结论。

## 7. C4 raw 到达后的第二人独立重算

不先读取执行者的比率结论来填结果。以完整原始 receipts、stdout/stderr、retained ELF、source/config/lock/toolchain 记录为输入，分以下步骤独立核对。

1. **资格与字节。** 先确认实际 C4 commit/tree、原 release/locked/toolchain/host、完整 source guards 前后、Cargo config 前后、实际命令和原 900s build/300s shard/5s grace；对原始 log 与 ELF 重算 SHA256。每个 timeout、capture error、truncation 和 reader error 均保留。原 wrapper 的 before/after binary hash 证明范围依其实际机制，不外推成未实施的进程级 race 校验。
2. **完整网格。** 必须恰有 30 个 distinct `(class,target,horizon)` shard；每个 campaign/end 完整，八 samples ×四策略，每个 cohort 一个 setup，恰 H 个 search。不是用一个累加总数代替配置集合完整性。
3. **完整尝试与匹配。** 每个 search nonce 连续，从 0 开始，首 hit 即停止；无 hit 必须保留 4096。重算 challenge/ticket/proof SHA、materialization 数、真实 proof bytes；比较四策略的 complete-stream fingerprints。跨 H 用 `(class,target,sample,search_index)` 再去重核同前缀。记录数学重算、native verdict、execution authenticity各自的证据边界；reader 不会凭记录本身认证 CPU 时钟。
4. **固定格子的独立账本。** 对每一 `(class,target,horizon,strategy)` 的八个 cohort 分别保留 `P=sum(total.cpu_ns)`、`Pwall`、`S=sum(setup)`、`Q=sum(search timing)`、`P-S-Q`、`E=sum(evidence)`、`M=sum(mutation)`，以及每 case/path 的 `V=sum(verification)`。要求非负时钟与 `P>=S+Q`；同法核 wall。不混同 CPU 与 wall，不把 evidence 加到四个 verifier 各算一次。
5. **次数与合法率。** `N=sum(attempts)`、`W=实际经所有所需 native verdict 接受的 search hits`、`X=exhaustions`。一个 hit 不因四个 verifier 重复算四次。若任何 shard semantic alert，保留全部失败且按原 reader 抑制 validity-based rates，不能挑选其余看似正常格子取得资格。
6. **比率用比值的总和分母。** 固定格子下，producer CPU/observed winner=`P/W`；attempts/s=`N×10^9/P`；observed valid hits/s=`W×10^9/P`。策略比较用 `sum(PstrategyA)/sum(PstrategyB)`，同时保留八个配对 cohort；不把每 sample 的最快策略拼成并不存在的固定算法。所有算术先保留整数/Fraction，显示时再舍入。
7. **Target weight。** `weight=floor(2^256/(target+1))`，这里为 2、32。`W×weight` 与其 CPU rate 只是 reader 明示的 hypothetical work-equivalent，不是实际记账 chainwork、区块产出或网络份额。记录 attempts 与 work-equivalent 都不能取代账本/节点证明。
8. **Rejection v2 独立加总。** 固定 class/target 内核对 setup 三项之和、honest search 三阶段+overhead、A=setup+search wall、fake search 每次失败与耗尽、M=clone+patch+search+overhead；按同一输入 variant/kernel 分别累加 V。分列 `V/(A+M)` 与 `V/M`，在缺失或 fake exhaustion 时保留全部尝试成本及 ready-verification 子集，不凭中位数删去失败成本。四内核比率使用相同 class/target/variant 的 sum(V)。
9. **独立性。** Rejection v2 的 12×3×4 position 轮换在完整组中使每个 arm 各位置一次；核 raw 实际 position，不能只看常量。V3 的 verifier alias 与固定-strategy 顺序问题按上文保留，不赋予其不存在的独立性。

合法总成本、已有 winner 的增量拒绝成本、从零无效构造成本和公开节点服务成本，分别给出 measured / not measured。不会为了完整表格填入假想的 missing measurement。

## 8. 960 / 23,360 能证明什么

| 完整网格的结构计数 | 公式与意义 |
| --- | --- |
| 30 shards | `5 classes × 2 targets × 3 horizons` |
| 960 setup/cohorts | `30 × 8 samples × 4 strategies`；是真实函数调用，前提是 raw 完整 |
| 23,360 search 调用 | `5 × 2 × 8 × 4 × (1+8+64)`；不是 23,360 nonce attempts |
| 5,840 search 调用/固定策略 | 仍含跨 horizon 的前缀重复 |
| 5,120 unique indexed streams | `5 × 2 × 8 × 64`；已消除四策略与 H 前缀重复 |
| 至多 5,840 candidate records | 每 shard 的 matched winner 只保存一次；跨 H 仍重复；有 exhaustion 则更少 |
| 至多 186,880 verifier calls | `23,360 × 2 cases × 4 paths`；全 hit 时达到，并非这么多独立任务或攻击 |

这些计数能支持固定网格执行完整、没有只挑成功 shard、包含 setup 与 misses、四策略使用相同搜索流以及实际 denominator 的核算。必须配合每行 raw、顺序、首 hit/耗尽规则和 source/binary 资格；单独打印这些总数不能证明执行了对应工作。

它们不能支持最便宜合法算法下界、最便宜无效构造下界、全部可选任务、生产难度、量子成本、资源公平性、真实学习提升、能源/货币费用、独立 WAN 管理方或公开服务活性。原 acceptance profile 的 sample floor=8 是一个必要样本数条件；并不使其余原门禁自动成立。原 marginal rejection threshold、service window/offer span/诚实失败/p99/攻击预算要求没有因本次运行而改变。

## 9. 外部 C4 coordinator 的只读核对

已读 `w1/run_frozen_w1_legal_v3_c4.py`。两个 selected Cargo argv 与当前 workflow 的原 9-kernel/6-example 命令一致；9 个 kernel 的逐名/总数/零 ignored guard 保留。collector 仍调用原 owner `env -u CARGO_INCREMENTAL python3 -B scripts/ci/run_w1_false_trace_reuse_v1.py --arch x64 --local --legal-strategy-v3`，原 owner 保留 900s build、30×300s native shard、5s termination grace。

外层是 10800s 的完整本地窗口，包含它自己的 source/config/preflight 与这两个 selected controls；每个 selected controls 另有更保守的 900s cap，coordinator明确没有称为原 workflow 的单项 cap。它没有执行 hosted legal-factorial lane 的所有 header/History/CPU controls、all-target/all-feature lint或第二架构，故 **不能被写成完整 hosted lane 通过**。环境 CARGO_BUILD_JOBS=2、RUST_TEST_THREADS=1 与原 workflow 相同；本次没有新增预算豁免。

## 10. 当前交付与后续结果边界

本轮已完成冻结源继承/计量范围/已知合法优化/攻击成本分母的独立审查，报告了两个具体解释风险：v3 四入口只有三内核，以及固定 strategy 的 verifier rotation 抵消。未发现因这些点可以直接推出的非法 proof 接受。尚未收到 C4 raw，**没有填写 C4 性能数值、原门禁 PASS 或公开服务结论**。

实际 C4 raw 到达后，按第 7 节独立重算并形成单独结果文件；保留本文件作为执行前的固定审查，不覆盖 C2 或此前失败证据。
