# V8 remaining-to-terminal32：完整开发实验与研究结论

## 结论与处置

**固定的 96 个控制槽位全部完成 32 步，0 个实际异常；全部 24 对 Full/field 的动作、完整数值状态和旧面板损失数值完全一致（最大绝对差为 0）。但预先登记的确认进入规则失败，结果为 `REJECT_FOR_CONFIRMATION`。**

未来 DEV 改善幅度通过 **4/16**，旧 DEV 改善幅度通过 **6/8**，CPU 通过 **4/8**。本轮没有选择或消耗新确认 cohort，没有访问私有评估密钥，没有科学接受或 native 准入。所有数据都是已经解封的 V5/V6 历史开发证据；这 4/16 是固定开发筛选的通过数，不是新的显著性检验。[评分结果](evaluation.json)

这一实验解决了一个具体的开发设计问题：在共同的 32 步实际终点、逐步重规划和相同逐步动作盒下，mandatory H1/Loss2 基线与 Full/field 都能完整执行。它没有使主 V8 网格的其他停止消失，也没有证明任意未来状态可行。

## 冻结身份与比较对象

| 项目 | 固定身份 |
|---|---|
| 实际执行源码 | `65a5a1e6bb5034c27168535600a408a34d792e74` |
| 执行冻结提交 | `d3654af8446873df9d19e3b00a2b8d1ccb06e4bd` |
| 129 文件源码闭包 SHA256 | `660f79d805689b880ba6637e3038eb4251e8f3cc959cb608e282004824ef328a` |
| 主协议 SHA256 | `27a84ceccb166766a4c6af299aef259b639486411d344c7f593552c0778e1585` |
| 外部确认进入规则 SHA256 | `5b195a871b492a6680bcd2a3087c528ecce9fa55cbeb732d40116f4200b21b9a` |
| 控制封存 SHA256 | `f0b71272ec0e148bf05fad8b1e244defa4ae5802b26e40c8b017c44ead09cef4` |

实际 runner 是单独冻结的无损压缩存储版本：原 127 个源码字节保持不变，增加 runner 与存储测试，完整原始记录按 canonical JSON 加换行保存为 `mtime=0` gzip，索引绑定压缩前后长度与 SHA256。原 127 文件 plain writer 执行了 **0** 个真实 fit；本报告的 96 槽全部来自新 129 文件身份。主科学协议和进入规则的全部数值条件没有变化。

源码：[主协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65a5a1e6bb5034c27168535600a408a34d792e74/qa/stem-bakeoff/cell_field_remaining_protocol_v8.json)、[terminal 响应](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65a5a1e6bb5034c27168535600a408a34d792e74/qa/stem-bakeoff/cell_field_terminal_v8.py)、[控制策略](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65a5a1e6bb5034c27168535600a408a34d792e74/qa/stem-bakeoff/cell_field_remaining_v8.py)、[实际压缩 runner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/65a5a1e6bb5034c27168535600a408a34d792e74/qa/stem-bakeoff/cell_field_remaining_run_compressed_v8.py)。

固定 24 个原 warmup：历史版本 V5/V6 × AG News/DBpedia × linear/gated × seed 7/17/29。每个 warmup 都运行四个方法，不按结果选择任务或删除失败；方法顺序按预先固定的循环轮换。使用已有冻结编码特征与 36/52 参数小 head，完整连续优化器状态为 108/156 维，另保留时钟、RNG、上下文和来源绑定。本实验不是 LLM 全参数微调。

| 方法 | 每一步的提议终点 | 跨步风险信息 |
|---|---|---|
| `myopic_h1` | 下一物理步 | 完整一阶响应 |
| `loss2_remaining` | 固定实际第 32 步 | 中间仅两项平均损失；末端保留八面板直接输出 |
| `full_adjoint_remaining` | 固定实际第 32 步 | 完整 Adam 状态的终端伴随响应 |
| `terminal_field8_remaining` | 固定实际第 32 步 | 相同终端响应及八维终端 observable |

在实际第 k 步，后三种方法使用长度 `32−k` 的条件参考：仅首动作自由，其余名义控制为零；所有方法只采用一个经安全器核验的动作，然后重新规划。H1 的内部提议目标仍明确是下一步。共同的是实际 32 步评价终点、重规划频率、动作盒、价格与安全器，不能把 H1 的内部目标说成已经与另外三种相同。

所有方法使用 `dt=.02`、`rho=.03`、`old_weight=.25`、`gamma=0` 和每坐标界 `4/sqrt(p)`。在本实验固定的线性化风险、对角 effort 和可分动作盒问题中，只开放首动作与开放更长前缀得到相同的首动作；这不表示非线性多步闭环策略等价。

## 实际共同 J32 与规划面板

实际执行结束后统一计算：

\[
J_{32}=\overline L_{\rm current}(x_{32})+0.25\overline L_{\rm old}(x_{32})
       +\tfrac12(0.02)(0.03)\sum_{k=0}^{31}\|u_k\|_2^2.
\]

这里的两项损失分别是四个规划面板的平均值；最后一项是实际采用动作的全部物理 effort 价格。它们与独立留作历史 DEV 评分的旧 512 个 future/old 样本分开。[完整 96 行与配对差值](descriptive-contrasts.json)

| 方法 | 实际 J32 均值 | current 规划损失 | old 规划损失 | 实际 effort 价格 |
|---|---:|---:|---:|---:|
| H1 | 1.327404895 | 1.006124240 | 1.025816995 | 0.064826406 |
| Loss2 remaining | 1.303877738 | 1.009727699 | 1.027790955 | 0.037202301 |
| Full remaining | 1.288113348 | 0.999644243 | 1.022055907 | 0.032955128 |
| terminal field8 remaining | 1.288113348 | 0.999644243 | 1.022055907 | 0.032955128 |

每个均值包含全部 24 fit；“较低”按差值小于 `−1e−12` 计数，只是描述。

| field 减去基线 | ΔJ32 / 较低 fit | Δcurrent / 较低 fit | Δold / 较低 fit | Δeffort / 较低 fit |
|---|---:|---:|---:|---:|
| H1 | −0.039291547 / 24 | −0.006479997 / 24 | −0.003761088 / 24 | −0.031871277 / 24 |
| Loss2 | −0.015764390 / 24 | −0.010083456 / 24 | −0.005735048 / 24 | −0.004247172 / 15 |
| Full | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

field 与 Full 的这四项数值在全部 24 fit 完全相同。对 H1 的 J32 差值中，风险两项合计为 `−.007420269`，effort 为 `−.031871277`；必须保留这项分解，不能把全部 J32 优势当作预测或泛化优势。对 Loss2 的 effort 在另外 9 个 fit 增加，但 J32 和两类规划损失仍在全部 24 fit 降低。

这些是在各自实际闭环轨迹上的整体策略比较，包含响应模型、动作选择和共同安全器的交互，不是保持动作不变的预测误差归因。尤其不能把某一步“后续控制全为零”的条件预测，拿去与后来每步重规划的自适应尾部作差并称为模型误差。

## 历史 DEV：旧 512 样本上的固定筛选

每组是一个历史版本 × 一个任务 × 一个 head，三个 seed 的同源差值先平均再对 512 个源样本取均值。共 8 组；V5/V6 是已经解封的两批开发数据，不是八个新独立任务。开发规则要求全部 16 项 future 差值 `≤−.006`、全部 8 项 old 相对原 warmup 差值 `≤−.020`，并要求全部 8 组 CPU 比 `≤3`。这些开发幅度为可用新来源容量所预先登记，没有在看到本结果后改变。[逐源 NLL/正确率](per-source-dev-statistics.npz)、[96 项指标及数组索引](records.json)、[历史来源身份](historical-provenance.json)

| 历史组 | future field−H1 | future field−Loss2 | old field−warmup | CPU field/H1 | CPU field/Full |
|---|---:|---:|---:|---:|---:|
| V5 AG linear | −.007826648 | −.006856432 | −.054830235 | 2.340346 | 1.092816 |
| V5 AG gated | −.007592570 | −.006371628 | −.060245914 | 3.121676 | 1.122871 |
| V5 DB linear | −.005695519 | −.003989785 | −.045706259 | 2.600528 | 0.937394 |
| V5 DB gated | −.001351323 | −.002546370 | −.030769520 | 1.731940 | 1.170984 |
| V6 AG linear | +.000946836 | −.000962528 | −.011206826 | 2.967800 | 1.178804 |
| V6 AG gated | −.003233025 | −.005193080 | −.008409242 | 3.188907 | 0.992217 |
| V6 DB linear | +.002861794 | −.003712384 | −.075828996 | 3.365246 | 1.057705 |
| V6 DB gated | +.001870445 | −.002856992 | −.051517342 | 3.823993 | 1.062264 |

仅 V5 AG 两个 head 的四项 future 对比达到开发幅度。field 相对 Loss2 的 future 均值在 8/8 组较低，相对 H1 只在 5/8 组较低；V6 AG linear 和 DB 两个 head 反而较高。old 相对 warmup 的八组均值都下降，但 V6 AG 两组未达到固定 `−.020` 幅度。不能把负的 old 样本均值直接当作新总体保留证书。

CPU 使用三个 seed **完整策略调用 CPU 的和之比**，包括参考构造、模型系数、规划、所有失败的共同安全搜索和核验；公共输入加载、持久化、独立回放和事后 DEV 评分分列。表中 field/Full 只是本次实测，不证明任意环境的运行速度排序。四组 field/H1 超过原 `3×` 界限，不能因 field 与 Full 数值等价而豁免成本条件。

## 共同安全层、信息预算和 PFT 的适用范围

每个动作采用同一固定 portfolio：先在原点运行旧的单射线整块修复，失败后从**同一原点与同一意图动作**运行四旧面板 joint 修复；不拼接两条轨迹，也没有 Full 风险动作作为 fallback。所有失败尝试付费并保留。每次采用前，四个原 warmup old anchor 都经过实际 Adam 后的零松弛损失检验；零控制也必须经历实际 Adam，不能视作参数保持。

Loss2 的两维限制只描述风险提议器；实际执行系统与所有方法一样拥有完整状态及共同旧面板安全 oracle。这是一项公平共享机制，不能宣称整个 Loss2 控制器只拥有两项信息。32 步中反复使用的八个规划面板是自适应经验约束，不是独立留出的统计证书。

对局部时变系统 `δx_(k+1)=A_k δx_k+B_k δu_k`，令终端八输出系数 `R_k=C_T A_(T−1)…A_k`，则终端坐标 `z_k=R_k δx_k` 满足 `z_(k+1)=z_k+R_(k+1)B_k δu_k`。本轮八维 field 使用这一终端关系；它保留本地固定终点输出所需的一阶信息，并在实际 24 对闭环中复现 Full 的动作与状态。

系数仍由完整 Adam 状态、已知训练上下文和名义零尾轨迹计算，并逐步重算且计费。因此结果支持 **有限窗口、指定输出的一阶等价**，不支持“八维自主非线性 Markov 状态”、免费获得未来系数、任意中间输出可恢复或全参数 LLM 的低成本等价。独立审计验证了系数构造，而不只是保存矩阵的乘法。

与论文《A Parameter Field Theory of LLMs》的关系因此更明确：局部闭包/可观测投影可以足够准确地复现 Full，但规划目标的代理偏差、经验保留约束的泛化和实际计算成本仍是独立问题。本轮规划损失与共同 J32 全部改善，外部历史 DEV 却有三组比 H1 更差，直接限制了“局部信息保真自然带来外部效用”的论断。native 签名、恢复和撤销机制只能执行准入规则，不能把这个开发拒绝变成科学接受。

## 独立核验与物理基线配对

[独立回放收据](audit/audit.json) 为 PASS：完整 96 槽、**3,072 次实际优化器更新**、**3,072 项保存提议**全部核验；额外构造 **38,784 次零尾参考更新**与 **36,480 个前向 JVP 步**。首动作响应矩阵最大绝对差 `3.2526065174565133e−18`，初始八行 observable 最大绝对差 `4.729372449219227e−11`。Full/field 的 24 对实际动作、完整数值状态和旧损失差均为 0。

审计逐一核对采用状态、receipt、完整 θ/m/v、时钟、RNG、上下文、原 anchors、全部保存的 paid portfolio ledger，以及实际动作对应的预测和 effort；没有重新搜索全部失败安全分支。所有 **1,179** 个封存成员与 **129** 个执行源码在前后核对一致；审计未访问选择标签、未运行新安全搜索、未产生新候选轨迹。[逐槽核验](audit/cases.json)

额外的纯读配对检查将本轮 H1 与主 V8 网格 `config04`（同 `old_weight=.25`、stride1）对应起来。24 对均从相同完整 warmup 出发并到达32；最大动作差 `1.220135104063047e−13`，同一步终端 θ/m/v 最大差 `2.6645352591003757e−15`。完整中间状态的 SHA 并非全部相等，旧 grid 又未保存每一步数值向量，所以不报告整个状态链逐位相同，也不从散列差推导数值距离。这项比较没有新优化器更新或规划调用；两个 runner 的追踪和系数计算实现不同，不能用其 CPU 差作因果归因。[配对的完整 24 行](descriptive-contrasts.json)

## 成本与资格记录

| 范围 | CPU 秒 | wall 秒 |
|---|---:|---:|
| 公共输入准备，独立分列 | 0.113829817 | 0.122658377 |
| 实际 96 控制的 runner 循环 | 133.197984309 | 133.227124324 |
| 独立全量回放/系数核验 | 321.572752525 | 322.298283505 |
| 历史 DEV 评分 | 14.724620616 | 14.926757097 |

runner 循环含循环持久化和结束校验，计时在最后 report/seal 写入前停止；不能称其包含全部最终封存开销。各策略 gate 使用其完整调用计时，而不是上表 runner 总计。已有特征提取不在本轮控制成本内，不能把这些秒数当作从原始文本开始的端到端 LLM 成本。

控制核心与原 runner 共 12 项独立测试通过；存储修订增加 3 项；事后审计/评分工具共 10 项。工具资格保留了先前四项数值测试与后来六项边界/统计测试的真实阶段，没有补造重复运行时间。peer 发现的外部 seal 必填、已采用步骤必须保留完整 repair、report 与外部执行身份的绑定均已修复并定点核验。[工具资格](tools/tool-qualification.json)

## 复现顺序与输出位置

使用冻结 Python/NumPy/SciPy 环境，外层设置 `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`；实际 runner 还核对运行时线程池。先校验 source manifest 与所有输入 pins，再按 **控制 → 完整封存 → 独立审计 → 旧 DEV 评分 → 描述汇总** 的顺序运行。完整命令与各阶段源码哈希见伴随 publication manifest。

```text
cell_field_remaining_run_compressed_v8.py --protocol ... --protocol-sha256 27a84c... 
  --source-manifest remaining-compressed-executed-source.json --source-sha256 660f79...
  --source-commit 65a5a1e6bb5034c27168535600a408a34d792e74
  --workspace ... --grid pft-development-v7b/grid --planning pft-development-v7b/planning-only --output NEW_CONTROL
audit_remaining_v8.py --workspace ... --run NEW_CONTROL --grid pft-development-v7b/grid
  --planning pft-development-v7b/planning-only --pins PINNED_EXECUTION_JSON --output NEW_AUDIT
score_remaining_v8.py --workspace ... --run NEW_CONTROL --grid pft-development-v7b/grid
  --pins PINNED_EXECUTION_JSON --audit NEW_AUDIT/audit.json --audit-sha256 VERIFIED_AUDIT_SHA
  --entry-rule cell_field_remaining_compressed_confirmation_entry_v8.json
  --entry-sha256 5b195a871b492a6680bcd2a3087c528ecce9fa55cbeb732d40116f4200b21b9a --output NEW_DEV
summarize_remaining_v8.py --run NEW_CONTROL --audit NEW_AUDIT/audit.json
  --evaluation NEW_DEV/evaluation.json --grid pft-development-v8/grid-r2 --output NEW_DESCRIPTIVE_JSON
```

上面的省略项是文档占位，不是可执行的短 SHA；伴随 manifest 保存完整实际 CLI。重新执行产生的新 seal 与计时必须重新登记，不能直接套用本次 seal 的身份。

## 证据摘要与最终边界

| 证据 | SHA256 |
|---|---|
| 控制 report | `be41a3ac46db817396f9e5135987bae09ac6bc5f9c04943e4e3090bcad2d50f0` |
| 独立 audit | `8451f3830951eee294f18d84118d9764aee5ea042179079bb4a88859a23c6d73` |
| DEV evaluation | `8121678b55d77e96f44c4a15d76675fd6cb73aac297ec2a41b83131e92f3666a` |
| DEV 逐源数组 | `414edf010f49166eb77cb66574286e5cf728e36f918ec9bcc09e3a42ab9b6e78` |
| 描述配对汇总 | `462125a594950b6ad0e0cfa95e45c805455f3cd4050bd1e9c2f8df57d314cb31` |

工程完整执行、本地信息保真和可审计性在本轮得到具体支持；所有任务的外部效用幅度、严格的保留幅度与 `3×` 成本门槛没有共同通过。因此不进入新确认、不新增调参、不宣称已合格候选。原来 12 个科学比较的 Bonferroni 单侧置信上界要求（future 严格 `<−.001`、old `≤0`）及成本/完成条件保持原样，本轮没有执行或通过这项新的科学确认。
