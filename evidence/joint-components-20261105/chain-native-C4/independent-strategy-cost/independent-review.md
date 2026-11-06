# C4 W1 策略成本：第二人完整 raw 复算

## 结论

**三组原始记录内部一致，但“W1 成本及公开服务活性”仍不能关闭。** 对固定 C4 的 30 个 legal-v3 分片、13-arm actual-reuse-v3，以及 full-limb from-zero 分量，本审查逐行重建了输入、挑战、ticket、候选证明字节、配对流、成本分母和验证器覆盖，再与已经保存的原 reader 输出比较；全部一致，没有重跑原 reader 或任何 native 程序。最重要的成本结果是：from-zero 构造不需要合法 winner，生产验证器的拒绝 thread CPU 是该实验完整攻击构造分母的 **19.726812–23.367739 倍**。即使把单次共享材料生成完整计入总分母，九类合计仍是 **19.575369 倍**。

这里的“完整攻击构造”严格限于原计时范围 `actual-prefix-setup-and-all-searches-including-challenge-hashes-trial-retention-and-winner-clone`。它不等于完整网络攻击成本，也不是攻击者成本下界。下文单列了计时范围、材料敏感性与尚未覆盖的公开服务门禁。

数字来源是同目录 `independent-strategy-recomputation.json` 与 `cost-findings.json`；逐类完整表在 `cost-tables.md`。原 raw 位于 `/workspace/scratch/93bfcfe29fc8/w1/C4-strategy-receipts/`。这些是固定本地主机、固定 x64/release 二进制的有限观察，不授予独立 WAN、跨管理员故障域、全局最便宜工作或生产激活资格。

## 固定输入与独立处理范围

源码为 Chain `8df4b21d893906570d48f5beafabb3b31e0aefbc`，tree `6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`。三份原 owner receipt 的前后源码均为相同的完整 10,357 tracked entries / 985,270,534 bytes，`committed-clean` 且逐 tracked bytes 验证；Cargo configuration 前后相同。实际记录的构建使用 Rust 1.95.0、`--locked --release`、target `x86_64-unknown-linux-gnu`。

整包 `C4-strategy-receipts.tar.xz` 为 32,389,648 bytes，SHA-256 `4d0bf158860d62813e64d8ccdbf22db0c537dbf3cd94d471d2293f9c584ab08d`。父审查者已独立复核整包、136 个原始成员、894,173,992 原字节和 56 个真实空文件。本审查没有把其摘要当作 raw：直接读取 32 份 JSONL，合计 **882,441,044 bytes**，逐文件核 `export-index.json` 的 size/SHA，并在读取前后核同一个文件描述符的 inode/size/mtime/ctime。三份原 manifest 和外层 manifest 也按 index 绑定。

三份保留 ELF 的实际本地字节另行读回核验：

| 原 native | ELF bytes | SHA-256 |
| --- | ---: | --- |
| `pon_w1_legal_strategy_v3` | 749,744 | `5fac508b448d0815173f3802438b5a0b48479fbe15fd1e4b701e981159606740` |
| `pon_w1_reused_cost_v3` | 882,288 | `45cd16459be074cec79e2815243236b8877dde17b2cb267bc5b55b4861865d9f` |
| `pon_w1_false_trace_reuse_v1` | 715,112 | `1fdf21d5f9e9d970b2304191d60631eb4ba7d15b009105bd3fd6f7ed502f7b7f` |

这些字节与原 runner 对执行路径的构建后、执行前后 hash 一致。这里不把原 runner 的保留 ELF 宣称为新造的逐进程 `/proc/exe` FD 采集，也不以哈希替代独立硬件或对抗管理员的执行证明。完整 source/config/argv/原始结果随原 receipt 保留。

独立解析器不 import 原 reader：自行实现公开 wire hash framing、九类矩阵配方和模域乘积，核每个连续 nonce、challenge、trace/ticket 字节、target 判定、proof SHA、完整候选 proof、最后 C word 的 canonical mutation，核各 arm 的全部流相同以及 H 的前缀相同。每项原 native verdict 都保留并统计；**没有在 Python 重新执行 W1 transcript 算法**，因此“Accepted / Transcript / Product”是被源与执行记录绑定的原生结果，而不是本次复算自行签发的密码学验证结论。全部 32 个原保存 reader 的计数与成本算术是在独立计算之后逐字段比较的。

## 时钟和分项不能混用

三组 native 的 `cpu_ns` 来自 Linux `ClockId::ThreadCPUTime`，并要求 start/finish 在同一个 native thread；`wall_ns` 来自 Rust `Instant::elapsed`。原始所有被使用的 timing 均是实测正整数，没有把缺失 CPU 写成零。源码依据为 `examples/support/w1_cost_producers.rs` 的 `Clock::start/finish` 与 `cpu()`（36–74）。

下表的 producer total 是原 cohort 的包围计时。`setup + search` 已包含在 total 内，不再相加收费。各组全部行的总和仅用于说明这轮实验实际记录了多少工作；尤其跨 H 与重复 arm 的累计不能当作独立链工作。

| 分量 | 真实 setups | searches | 全部 nonce / 其中失败 nonce | 完整 producer/attacker CPU | 完整 producer/attacker wall |
| --- | ---: | ---: | ---: | ---: | ---: |
| legal-v3，30 shards × 4 arms | 960 | 23,360 | 389,788 / 366,428 | 531.839972120 s | 531.930546526 s |
| actual-reuse-v3，9 类 × 13 arms | 936 | 1,888 | 3,848 / 1,960 | 8.256738667 s | 8.257605316 s |
| full-limb from-zero | 72 | 288 | 573 / 285 | 0.020182415 s | 0.020354010 s |

三组本轮均没有耗尽 4,096 的 search；这仅是观察到所有 search 最终命中，不豁免失败 nonce，也不能证明更困难 target 的尾部成本。

分开计时的材料生成如下。legal-v3 的材料区间每 shard 一次，表中为其 30 次实际记录的和；后两组为整个九类 campaign 各一次。它们没有任意重复加到每个 arm 或候选上：

| 分量 | 单独材料生成 CPU | 单独材料生成 wall |
| --- | ---: | ---: |
| legal-v3，30 个实际区间合计 | 56.171504 ms | 56.497096 ms |
| actual-reuse-v3，全 campaign 一次 | 1.539209 ms | 1.538400 ms |
| full-limb from-zero，全 campaign 一次 | 1.680241 ms | 1.685711 ms |

legal-v3 的付费 setup 是 0.415246696 s CPU，全部 search 是 531.395306714 s；inclusive total 还含 0.029418710 s 包围计时残差。证据 digest/hex/JSON value 构造另为 **7.245323491 s CPU**，product mutation 另为 **0.169790217 s CPU**，所有 case/label 的验证调用共 **403.187179598 s CPU**。这些区间互不冒充 producer 成本。JSONL 序列化/写出、后续 retained buffer 销毁和进程整体开销不在该 producer timer 中；全 native wall 与各已测 phase 的差额不能直接叫作 JSON CPU。

实际各 native 子进程的 wall 合计分别为 1,026.874150743 s、20.470751766 s、3.573923850 s；这些包括原程序其他工作与 I/O，既不是 thread CPU，也不能加到已经包含其中的 phase 上。外层 coordinator 的 CPU/rusage 若另有记录，范围又不同，不在本表冒充 native thread CPU 或能耗。

## 四种合法策略究竟比较了什么

legal-v3 的四臂是 transposed/full-limb 算术 × 每次物化/只在 target hit 物化。`Task::new` 对四者使用相同 Dense AB/product/prefix preparation；每次 nonce 都完整执行 challenge-dependent transcript、ticket。lazy 只省去失败时的 proof buffer 物化，不能省掉失败 transcript。依据 `legal_attempt.rs:59–82,104–153` 与 `pon_w1_legal_strategy_v3.rs:95–173,266–328`。

本次独立核对了四臂相同 task/target/sample/search/nonce 的全部 challenge、trace、ticket、最终 proof digest 与首个 hit，未发现因选不同 nonce 流而形成的伪加速。四臂顺序按原规则轮转，8 samples 覆盖每个四臂位置两次。H=1/8/64 每个 cohort 真正做一次 setup 后复用相应数量的 search，没有把单次 setup 用 1/H 的纸面除法替代实际复用。

但是 H 不进入 challenge 域。各 H 的共同 search prefix 完全相同：5840 个 shard 内 canonical candidate 经跨 H 去重仅 **5120 个 indexed search streams**，其中 **85562 个 nonce、80442 个失败 nonce、5120 个 hits**。这仍是五个固定材料任务、两个 target 下的八个样本编号，不是 5120 个独立抽样任务。23360 个 search 和 186880 个 verifier 调用也不能被称作同数量独立工作或 verifier 实现。

30 个 shard 中，按八样本完整 CPU 总额选择一个固定 arm，20 个最低者为 `lazy-full-limb`，10 个为 `eager-full-limb`。相对 `eager-transposed`，同 shard 的观测比值为 **1.139018–1.216205**。这些是有限、回顾式 arm 选择；表中没有逐 nonce 拼一个事后最快 oracle，也没有未测未来任务泛化。

单独分离两个因素后，lazy 并不处处更快：transposed 的 eager/lazy CPU 比值为 **0.956553–1.035958**，full-limb 为 **0.972791–1.063563**。低于 1 意味着该固定 cohort 的 lazy 较慢。相比之下，在这轮有限配对中，full-limb 算术相对 transposed 的比值范围为 eager **1.095943–1.207347**、lazy **1.130820–1.211524**。不能把 combined gain 全部归因于延迟物化。

最佳固定 arm 的完整 CPU/nonce 比值横跨 1.233760–1.641781 ms，具体 task/target/H 不同，范围不代表一项统一成本。完整 30 行保留在 `cost-tables.md`，每行给真实 8 setups、全部 nonce/misses、CPU/wall、每 hit 的完整分母。

## 稀疏、零结构与 13-arm 专项

13-arm campaign 的原固定参数是单 target `7f…ff`、8 samples、每 setup 实际 4 searches。936 个 constructor 调用中有 **472 个 supported、464 个 unsupported**；unsupported 仍实际付费，单独 setup 合计 **2.720998 ms CPU / 2.673834 ms wall**，未把它们当成零成本合法 producer。

1888 个 arm-level searches 全流配对后仅有 **288 个 indexed streams / 588 nonce**，所以 3848 个实际 nonce 是为了比较不同 arm 重复执行的成本。原完整 13-arm grid 没有 lazy-full-limb 或 Sparse-preparation 臂，不能用它来声称已经覆盖所有已知便宜合法构造。

固定八个 H4 cohorts 的最低观测臂是：periodic/full-rank 为 `prepared-generic`；zero 为 `blocked-zero`；identity、rank-one、sparse-diagonal 和两种 one-zero 为 `prepared-structured`；continuity 为 `maintenance-limb`。例如 zero 完整付费 8 setups、32 searches、62 nonce（30 misses），CPU **99.509695 ms**，即 1.604995 ms/nonce；continuity 为 8 setups、32 searches、71 nonce（39 misses），CPU **108.974611 ms**。这些均有对应完整 candidate 和原 production/reference Accepted 记录，而不是只凭算法名称推断捷径。

此前已交付的 Sparse 两个原 synthetic native 分量仍单列于 `../sparse-C4-raw/independent-sparse-review.md` 与 `cost-table.md`：每 target 1080 cells、616 complete/464 unsupported，9 类 × 8 samples，完整 64 attempts 与每 16 attempts 一个实际 setup，15 臂。该独立表已经计入 setup、所有失败 attempts、proof cleanup 和 teardown。它与上述 H4 search-until-hit 计时不同，challenge 域也不同，部分 one-zero 材料配方不同；不能按名字相同直接拼成跨 suite 排行或速度提升。

Sparse 内部公平的 Dense/Sparse 配对仅观察到总 CPU 比值约 0.992–1.034，部分持出样本甚至更慢。既有 2/6 校准/持出策略保留其失败结果；这不是学习质量、真实模型或诚实 no-update 的完整资格。细节不重复测量，不用旧 C2 数字替代 C4。

## 两种无效输入，两个不同的分母

### 已有合法 winner 的最后 C word 篡改

legal-v3 的 `product-last` 分量先获得该真实合法 proof，然后计时 clone 与最后 C word canonical increment；trace/ticket 不变。独立重建全部 23360 次 mutation，原四 label 均记录 `Product` 拒绝。若假定已有可用 winner，单看 clone+mutation 的边际 CPU，生产拒绝 / mutation CPU 在 120 个固定 class/target/H/arm 行中为 **73.531016–353.390441 倍**。

若把本实验同一 arm 的诚实获取成本加到 mutation 分母，比值变为 0.029797–0.769108。两种比值都保留在 `product_mutation_denominators`，但后者**不能**推出攻击者必付诚实挖矿成本。是否从已有公开 proof 获取、跨接收者复用、相同 challenge 下再次送入、去重/缓存是否有效，都必须由实际公开服务路径另证；本分量没测这些网络行为。主程序计时边界见 `pon_w1_legal_strategy_v3.rs:331–350`。

### 从零构造，不需要合法 winner

`w1_from_zero.rs:6–27` 仅验证/序列化公开 A/B，C 与声明 trace 初始为零；每 nonce 做 `hash(public-v3-from-zero-v1, challenge, nonce)` 再计算 ticket。完整搜索只在命中时 clone 49,188-byte proof 并填入伪 trace，**没有计算 AB 产品，也没有借用成功 producer 的 trace**。本审查重建每个伪 trace、ticket、首个 hit 和全部 288 份完整候选字节，核 1440 次原 native verdict 全为 `Transcript`。

每类的实际分母含 8 次公共 prefix setup、32 个 searches、所有失败 hash trials、challenge hashing、trial hex/retention 与 winner clone。全九类累计 72 setups、573 nonce（285 失败）、288 候选，setup 为 **14.477627 ms CPU**，search 为 **5.335944 ms CPU**，包围 total 为 **20.182415 ms CPU**（含 0.368844 ms 包围残差）。它不是只拿成功的一个 hash 作分母。

生产路径的对应 288 次拒绝共 **427.969566 ms CPU**；各类按同类完整分母的比值为 **19.726812–23.367739**，九类合计比值 **21.205072**。详细九行同时列 wall 比值。`production` 与 `full-limb-experimental` 为同一算术内核的两次调用；本比值只用 production 一次，不把五个 label 相加夸大接收方成本。五个 label 对应四种不同内核，主 legal-v3 的四个 label 则只对应三种内核。

“Full attacker”并非所有端到端工作都在计时：原 prefix 的 canonical A/B 序列化与 winner 完整 buffer clone 已付费；单独材料生成、JSONL 证据序列化与写出、外围 wire/transport 封装与发送、公开 admission/排队/存储/接收网络开销以及后续 retained-buffer 销毁没有加进此分母。试验还包含真实网络攻击者可能省去的 trial hex/retention，因此它也不是攻击最低成本。更大复用 horizon、hash midstate 复用或别的实现/硬件仍可能更便宜，未作数值外推。

为避免低估材料构造，做一次保守的汇总敏感性核算：将整个 from-zero campaign 已记录的 **1.680241 ms CPU / 1.685711 ms wall** 材料生成区间只计一次，分摊到这次全部 72 setups / 288 searches，不对每类或每候选重复收费。于是：

| 范围 | 完整分母 | 对应 production 拒绝 | 比值 |
| --- | ---: | ---: | ---: |
| 原攻击构造 thread CPU | 20.182415 ms | 427.969566 ms | 21.205072 |
| 再加一次共享材料生成的 thread CPU | 21.862656 ms | 427.969566 ms | 19.575369 |
| 再加一次共享材料生成的 wall | 22.039721 ms | 429.270824 ms | 19.477144 |

有公开 task 的攻击者未必需要支付该材料生成，但这里仍把实际一次完整成本计入敏感性分母；剩余的网络/公开服务成本依然未知，未通过假设填零。

## 原门禁与公开服务资格

原 native 的 900-second build、每 child/shard 300-second、5-second termination grace 均保留。legal-factorial 原 whole job 为 180 分钟；actual-reuse-v3 的原 `trnm-required-baseline.yml` job 为 155 分钟。full-limb 此次只是原 `false-trace-reuse` 的一个模式，原共享 55 分钟 job 还包括另一个模式及 tests/lints，本次单模式 PASS 不能说整 job 已执行。原 owner/reader PASS 表示捕获完整、语义结果与固定规则一致，不是成本政策自动通过。本次解析没有改冻结源码、门禁、预算或样本数。

`config/pon/work-security-acceptance-v1.json` 仍是 `proposed-local-diagnostic-policy`，不是 consensus parameter；其中 `maximum_marginal_rejection_amplification` 为 1，公开服务还要求 60 秒窗口、49 秒 offer span、至少 100 个诚实和攻击请求、诚实零失败与 p99 不超过 2 秒等。当前 from-zero 有限关系层 CPU 比值显著高于 1，但它不是同完整 service scope 的测量，不能伪称原 public-service gate 已执行并通过/失败。能确定的是：**这些微基准无法给出该门禁的 PASS，且已暴露足以继续保持 P0 OPEN 的拒绝成本不对称**。

要关闭用户原条件，仍须在原资源与原 workload/验收标准下，将已知便宜合法策略、from-zero 无效构造、已有 winner 的可复用篡改分别送入实际普通公开入口，保留真实 admission/身份/撤销/当前 root/队列/重试/缓存作用及完整成本；不能把诚实挖矿成本强加为攻击下界，也不能通过调高阈值、延长预算或删掉失败样本来得到 PASS。本报告不给新增执行或修改生产协议授权；只交付本轮完整 raw 的可核验结论。

## 交付物与局限

`delivery-manifest.json` 冻结独立解析器、后处理脚本、完整数值 JSON、48 行成本表、本文、源码引用 inventory 和本地执行记录的字节哈希。原生 evidence 保持在原始目录，未重写。本地后处理首版有一处 Python 字典闭合语法错误，原日志 `summarize-attempt-1.log` 保留；修正后仅重算已生成的独立数字并追加材料敏感性，没有更换 raw、重跑 reader/native 或改变任何统计分母。

本次证明的范围是固定 C4 和真实保存 raw 的数据/算术复核。尚无全球最便宜合法算法、攻击最低成本、能耗、独立硬件、真实 WAN 与多管理员长期运行结论；也没有完整模型冷取、学习质量、长期状态预算或联合 H2/H3 普通入口通过的推论。
