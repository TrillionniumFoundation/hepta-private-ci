# 真实签名 Organ Credit 闭环：本批交付结果

本批已经完成 **正式训练 SNN → 原生 owner → 真实签名学习账本 → 资源结算 → 下一回合决策边界** 的实际闭环。16 个回合产生 48 条认证事实；签名失败不会释放资源结算，也不能开启下一回合。正式运行、独立审计、移址重放和交付脚本的完整 16 回合重放均通过。

这是一批独立的集成验证。它没有替换或改写 `adaptive_neuron_v2` 已封存的训练、九组部署比较或统计结果，也不以这个单 seed 序列推断性能优势。

## 1. 不可变身份

| 对象 | 身份 |
| --- | --- |
| 桥接源 commit | `e91a7002bfd650e4a2b057b18b9d81f4242b9ed2` |
| 源 tree | `58172975f4523cd00f259a0b07f19e5a5045ac94` |
| 独立源封存 | 228 个输入；SHA-256 `2388d2131cea782a3e75190c5791cfa13a9d065bfa2b28879235f9a0d54495b6` |
| 正式训练 checkpoint | confirmation seed 601，`meta_theta`；SHA-256 `5c82147c3165bba99ad285d8abdbfb3cffd3e434a7856d1d5a8da4574f870b73` |
| 原 owner 二进制 | SHA-256 `261c63bc5f3a8ca1940dac27424ef8740e03ddc918b12f29af7d44b4b4ad25e4` |
| 正式签名桥二进制 | SHA-256 `839b75613e98d182b6f2f9e5b1276ab81c41e18e976cf0faea732e17e866a026` |

源封存不仅记录当前文件 SHA-256，也在冻结和验证时逐项核对不可变 Git commit 中的 blob。额外原生产 crate 和桥接输入拒绝符号链接、父目录符号链接及仓库根路径逃逸。运行环境固定为 CPython 3.12.14，并记录 Python 可执行文件身份；NumPy 2.3.5、SciPy 1.17.0 和 cryptography 50.0.2 均精确锁定。缺包、版本变化、源路径逃逸和缺失/改变 Git 对象的定点拒绝检查通过。[源封存](results/formal001/SOURCE_SEAL.json)；[环境与路径检查](results/development/provenance001/QUALIFICATION.json)。

## 2. 真正执行了什么

Rust 签名桥编译了原字节的五个生产 crate：`hepta-types`、`hepta-intuition`、`hepta-cognitive-types`、`hepta-memory-retrieval`、`hepta-learning-ledger`，并完整 source-compose 原 `outcome_credit_v2.rs`。实际调用正常 trust activation、`DurableLedger`、`LedgerWitnessStore`、`LedgerWriter::append_decision` 和 `append_outcome_credit_v2`，没有启用旧 qualification-write 绕行特性。[构建回执](results/formal001/BUILD_RECEIPT.json)。

每一回合的顺序是：

1. 原 owner 用真实模型、当前 account 和严格递增的 account sequence 打开任务。
2. 签名 Decision 批准执行该训练 readout，候选明确包含 `abstain`。它是运行准入 Decision，发生在任何观测之前。
3. 原二进制逐 tick 执行八细胞 hard SNN。只有当下的 observation 进入 owner；未来证据与真实标签仍留在 driver。实际停止后不再购买后续观测。
4. 保存真实终态 checkpoint、实际资源工作量和观察到的 reward。此时尚未结算资源。
5. 原认证路径提交 Outcome 和 CreditBatch。只有完整成功的 closure 与当前 pending task 的 case、organ、模型、训练 checkpoint、owner 二进制、终态 checkpoint、outcome、reward 和 support digest 全部一致，gate 才允许 `Native Settle`。
6. gate 检查资源记录原字节的 digest，以及原 owner 持久化 `SETTLEMENT.json` 的 outcome 绑定。确认结算后，下一回合使用已经变化的真实 account 和 price。

签名事实中的 Decision 表示任务准入；真正的 SNN 停止动作来自原 owner，并进入终态证据。二者没有混作同一个决策事实。

## 3. 原始计量

| 指标 | 正式运行结果 |
| --- | ---: |
| 回合数 | 16 |
| 真实 owner ticks / SNN model calls | 48 |
| 真实 SNN 细胞更新 | 384 |
| 真实放电 | 288 |
| 输入 MAC / readout MAC | 2,304 / 384 |
| 资源执行单位 | 84 |
| 签名 Decision / Outcome / CreditBatch | 16 / 16 / 16 |
| 新资源结算记录 | 16 |
| 任务总 deadline / 实际观测 | 192 / 48 |
| 未购买后续观测 | 144 |
| 最终 balance / shadow price | 16.05 / 0.018125 |

84 个资源单位严格等于 $48+288/8$。这些是声明的观测与放电预算单位，不是焦耳。144 个未购买观测证明建议动作确实改变了执行轨迹；这个数量本身不证明任务效用优于其他策略。[正式循环汇总](results/formal001/LOOP_SUMMARY.json)；[root 独立逐回合算式核对](results/root_review001/REVIEW.json)。

正式循环另实际进行了 55 次签名桥 RPC，产生 90 个 evidence 签名，其中 2 个故意损坏用于拒签测试；原有效 proof 的独立验证为 88 次。账本冷恢复累计读取 1,230 条历史记录。owner 的恢复、模型验证、边界构建、无效请求和重试均有独立计数，不能把它们隐藏在 48 次实际任务 tick 中。[独立审计](results/formal001/AUDIT.json)。

## 4. 两层 credit 的数学对应

真实 `CreditBatchV2` 将观察到的 task reward 以 Q32 分配给本地研究 organ，守恒残差为零。资源账户只在这个签名闭合通过之后更新：

$$
W= N_{\mathrm{ticks}}+N_{\mathrm{spikes}}/8,
$$

$$
b_{k+1}=\min\left(32,\;b_k-W_k+B_k+0.5R_k\right),
$$

$$
p_{k+1}=\operatorname{clip}\left(p_k+0.005(W_k-B_k-0.5R_k),\;0,\;0.08\right).
$$

下一回合的边界使用 $c_{\mathrm{eff}}=c_{\mathrm{base}}+2p_{k+1}$；单回合内 price 固定。因此本次结果包含真实的签名成功与否对后续准入、资源状态和决策边界的影响。

checkpoint 的联合元训练参数为 $\mu=0.7796034644$、$\sigma=1.0995770960$、$\lambda=0.06004424517$。它们属于训练时 first-passage surrogate。部署 hard SNN 消费同一 checkpoint 的权重与阈值。资源 shadow price $p$ 与 surrogate/hazard 参数 $\lambda$ 继续保持不同语义，不能把两者的数值直接等同。

## 5. 已闭合的故障与身份约束

| 检查 | 实际结果 |
| --- | --- |
| Observer 坏签名、过期 evidence、旧 ledger head | 不生成新的 CreditBatch；原终态与资源状态保持；禁止下一回合 |
| Outcome 已提交、allocator 签名失败 | 保留这一个合法 Outcome；冷恢复后 Outcome 为 `IdempotentReplay`，Credit 正常追加一次 |
| 签名闭合已提交、adapter 尚未确认 | 新进程完整重试，两条签名事实均幂等，不重复分配资源 |
| Native Settle 已提交、adapter 尚未确认 | 冷恢复读到已结算状态，重试不新增资源记录 |
| 另一个回合的真实有效 admission / closure | gate 根据完整当前身份拒绝 |
| 修改终态绑定、资源记录 digest、settlement outcome | 拒绝，gate 和 owner 文件均未变化 |
| trust 展示 signer 列表替换、signed payload 与 fact 错配 | 独立 Python canonical 编码重建拒绝 |
| gate 文件截断或篡改 | 拒绝恢复 |

独立审计重新构造 root trust distribution、evidence 的 scope/role/epoch/有效期编码，以及每条 Decision、Outcome、CreditBatch 的签名 payload；Q32 credit-batch digest 也从实际事实重建。它不只检查“某个签名能验证”。[审计回执](results/formal001/AUDIT.json)。

## 6. 可移植性与构建差异

正式 raw 与源副本移入新目录后，保留了 266 个最小 Git 对象，覆盖提交、所需路径 trees 和全部 228 个输入 blobs。原始宿主 metadata 单独保存；只修改复制工作集中的可执行文件路径、模型/校验文件路径及新根 permit。所有模型、checkpoint、签名账本、owner 事件、资源记录与源身份保持原字节或原 digest。冻结的审计程序完成了全部 16 回合新进程重放，原始数据没有变化。[移址回执](results/formal001/HOST_PATH_RELOCATION.json)；[完整移址审计](results/formal001/PORTABLE_AUDIT.json)。

交付归档中的 `runs/formal001/portable/REPLAY.py` 可在新的目的目录建立独立工作副本，并调用同一冻结审计程序。该交付入口也完成了全部 16 回合验证。[交付入口审计](results/formal001/DELIVERED_REPLAY_AUDIT.json)。重放需要已声明的 Linux 可执行环境与精确 Python 依赖；这里没有声称跨操作系统通用二进制。

两个独立、位于仓库外的正式构建根生成了完全相同的二进制 SHA-256。早期仓库内开发构建与正式构建不相同：冻结构建脚本的两条 path-remap 规则在重叠路径下会留下不同的 panic/source path 字符串。这个观察已保留，因此本报告只声明两个正式布局的字节一致，不声明任意构建目录不变性。[复建证据](results/formal001/REPRODUCIBILITY.json)；[开发/正式差异](results/formal001/BUILD_PRESERVATION.json)。

## 7. 成本与保留的失败

开发构建、两次成功开发闭环与审计、正式批、正式复建、交付脚本重放、定点 provenance 检查、缓存清理及独立 root review 的已记录区间，合计约 **489.374 秒阶段 wall、477.685 秒 CPU**。三个 whole-launch 计时替代项的合并舍入半宽分别约为 0.015 秒和 0.03 秒。wall 是声明处理区间的相加，不是含编程和等待的日历时间。发布与归档有单独后续回执。[非重复成本索引](results/formal001/COSTS.json)；[whole-launch 替代计量](results/formal001/WHOLE_LAUNCH_COSTS.json)。

正式主批本身约 119.71 秒 whole-launch wall，包含构建、源验证、任务运行、两种审计与可移植准备。Nested build/run/audit 回执解释这个区间，不能再次加到总数中。模型工作量、签名/重放/边界计算和 Python 对照分开记录；未测量硬件能耗。

保留的开发失败包括离线索引版本冲突、原生产账本拒绝缺少 `abstain` 的 admission；后者发生在任何 SNN tick 和签名事实之前。首选外部 timer 不存在时，科学子进程尚未启动，随后改用 Bash 内建 whole-launch 计时。第二次正式复建的 native 构建和二进制比较成功，但其外层保存脚本复制了同名子级 `COMPLETE.json`，导致最后一次独占回执发布失败；原外层 START、完整 traceback、child build 回执和包含全部父子进程的 whole-launch CPU/wall 均已保存，成本索引使用后者，不掩盖这个发布故障。[复建发布故障与计量](results/formal001/REBUILD_OUTER_LAUNCH.json)。

## 8. 保证的边界

本批真正运行了生产签名校验和账本路径，但使用的是用户授权本地研究域的临时 trust root 与 fixture keys。多个签名身份由同一研究者控制；它不证明组织独立性，不使用生产凭据，也不授予生产执行权限。

签名门控属于新增 adapter。原 owner 二进制完全未改；其公开 `Settle` API 本身没有因此获得签名校验能力。直接绕过 adapter 调用该 API，不在本次 gate 保证范围内。要把这个保证提升为生产服务保证，还需在服务入口和凭据/文件访问边界强制使用该 adapter，并在实际部署环境另行验证。当前交付完成的是可核验、可重放的本地真实代码路径闭环。
